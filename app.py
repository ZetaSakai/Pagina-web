import os
import re
import uuid
import base64
import functools
from datetime import datetime, timezone, timedelta

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

# Database compatibility layer (MySQL with SQLite fallback)
from db_compat import get_db_connection, init_sqlite_schema, is_using_sqlite, MySQLError as Error

try:
    import mysql.connector
except ImportError:
    mysql = None

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv():
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        if not os.path.exists(env_path):
            return False
        with open(env_path, 'r', encoding='utf-8') as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())
        return True

try:
    from flask_wtf import CSRFProtect
except ModuleNotFoundError:
    CSRFProtect = None

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ModuleNotFoundError:
    Limiter = None

    def get_remote_address():
        return request.remote_addr or '127.0.0.1'

# Load environment variables from .env file
load_dotenv()

# ──────────────────────────────────────────────
# App configuration
# ──────────────────────────────────────────────
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(32).hex())
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2 GB upload limit

# Allowed hosts for production security
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
ALLOWED_HOSTS = [h.strip().lower() for h in ALLOWED_HOSTS if h.strip()]

# Session cookie security settings
# SECURE=False when DEBUG=True (local), SECURE=True when DEBUG=False (production with HTTPS)
debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 'yes']
app.config['SESSION_COOKIE_SECURE'] = not debug_mode  # Only secure cookies in production
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access (XSS protection)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['PREFERRED_URL_SCHEME'] = 'https' if not debug_mode else 'http'

# CSRF Protection
if CSRFProtect is not None:
    csrf = CSRFProtect(app)
else:
    csrf = None
    app.jinja_env.globals['csrf_token'] = lambda: ''

# Use Cloudflare's client IP header when present; fall back to the direct remote address.
def get_client_ip():
    cf_ip = request.headers.get('CF-Connecting-IP', '').strip()
    if cf_ip:
        return cf_ip
    forwarded_for = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
    return forwarded_for or get_remote_address()


# Rate Limiter - using memory storage for simplicity (use Redis for production)
if Limiter is not None:
    limiter = Limiter(
        key_func=get_client_ip,
        app=app,
        default_limits=["100 per minute", "1000 per hour"],
        storage_uri="memory://"
    )
else:
    class _NoopLimiter:
        def limit(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    limiter = _NoopLimiter()

# ──────────────────────────────────────────────
# Security Middleware - Host Header Protection
# ──────────────────────────────────────────────
@app.before_request
def validate_host_header():
    """Validate Host header to prevent host header injection attacks.
    This protects even when DEBUG=True is enabled."""
    host = request.host.split(':')[0].lower()  # Remove port
    if ALLOWED_HOSTS and host not in ALLOWED_HOSTS:
        app.logger.warning(f'Blocked request with invalid Host header: {host}')
        abort(403)

# Comment edit window (seconds). Users can edit within this time after posting.
COMMENT_EDIT_WINDOW = 15 * 60  # 15 minutes

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'covers'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'games'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'avatars'), exist_ok=True)

# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DB_PORT', 3310)),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', 'root'),
    'database': os.environ.get('DB_NAME', 'main'),
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_general_ci',
}

# Allowed file extensions for uploads
ALLOWED_COVER_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
ALLOWED_GAME_EXTENSIONS = {'zip', 'rar', '7z', 'exe', 'apk', 'dmg', 'pkg'}
ALLOWED_AVATAR_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

# Magic bytes for image validation
IMAGE_MAGIC_BYTES = {
    b'\x89PNG\r\n\x1a\n': 'png',
    b'\xff\xd8\xff': 'jpg',
    b'RIFF': 'webp',  # WebP starts with RIFF
}


def get_db():
    """Return a database connection (MySQL or SQLite fallback)."""
    return get_db_connection(DB_CONFIG)


def init_db():
    """Run init_db.sql to create / migrate tables."""
    sql_path = os.path.join(app.root_path, 'init_db.sql')
    with open(sql_path, 'r', encoding='utf-8') as f:
        sql = f.read()

    conn = get_db()
    cursor = conn.cursor()
    for statement in sql.split(';'):
        stmt = statement.strip()
        if stmt:
            try:
                cursor.execute(stmt)
            except Error:
                pass  # tables may already exist
    conn.commit()
    cursor.close()
    conn.close()


def migrate_db():
    """Add new columns to existing tables (safe to run multiple times)."""
    migrations = [
        "ALTER TABLE users ADD COLUMN role ENUM('standard','developer','admin') NOT NULL DEFAULT 'standard'",
        "ALTER TABLE users ADD COLUMN description TEXT NULL",
        "ALTER TABLE users ADD COLUMN slug VARCHAR(60) NULL",
        "ALTER TABLE users ADD UNIQUE KEY uq_slug (slug)",
        "ALTER TABLE games ADD COLUMN slug VARCHAR(120) NULL",
        "ALTER TABLE games ADD UNIQUE KEY uq_game_slug (slug)",
        "ALTER TABLE comments ADD COLUMN updated_at TIMESTAMP NULL DEFAULT NULL",
        "ALTER TABLE comment_replies ADD COLUMN updated_at TIMESTAMP NULL DEFAULT NULL",
        "ALTER TABLE games ADD COLUMN downloads INT NOT NULL DEFAULT 0",
        "ALTER TABLE games ADD COLUMN price DECIMAL(10,2) NOT NULL DEFAULT 0.00",
        "ALTER TABLE users ADD COLUMN developer_plan ENUM('none','estandar','pro','ultimate') NOT NULL DEFAULT 'none'",
        "CREATE TABLE IF NOT EXISTS ratings (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, game_id INT NOT NULL, rating INT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE KEY uq_user_game_rating (user_id, game_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS purchases (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, game_id INT NOT NULL, email VARCHAR(120) NOT NULL, card_name VARCHAR(120) NOT NULL, last4 VARCHAR(4) NOT NULL, amount DECIMAL(10,2) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS donations (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NULL, amount DECIMAL(10,2) NOT NULL, email VARCHAR(120) NOT NULL, card_name VARCHAR(120) NOT NULL, last4 VARCHAR(4) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "ALTER TABLE users ADD COLUMN social_x VARCHAR(255) NULL",
        "ALTER TABLE users ADD COLUMN social_youtube VARCHAR(255) NULL",
        "ALTER TABLE users ADD COLUMN social_instagram VARCHAR(255) NULL",
        "ALTER TABLE users ADD COLUMN social_github VARCHAR(255) NULL",
        "ALTER TABLE users ADD COLUMN username_changes_count INT NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_username_update TIMESTAMP NULL DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN email_changes_count INT NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_email_update TIMESTAMP NULL DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN last_password_update TIMESTAMP NULL DEFAULT NULL",
    ]
    conn = get_db()
    cursor = conn.cursor()
    for stmt in migrations:
        try:
            cursor.execute(stmt)
        except Error:
            pass  # column already exists
    conn.commit()
    cursor.close()
    conn.close()


def seed_admin():
    """Create the admin user if it does not already exist."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    existing = cursor.fetchone()
    if not existing:
        hashed = generate_password_hash('x86q9Hx1oF*')
        cursor.execute(
            "INSERT INTO users (username, email, password, role, description, slug) VALUES (%s, %s, %s, %s, %s, %s)",
            ('admin', 'admin@newera.local', hashed, 'admin', '', 'admin')
        )
        conn.commit()
        print("✔ Admin user seeded.")
    cursor.close()
    conn.close()


def backfill_slugs():
    """Generate slugs for any users/games that don't have one yet."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Users without slugs
    cursor.execute("SELECT id, username FROM users WHERE slug IS NULL OR slug = ''")
    for user in cursor.fetchall():
        slug = make_slug(user['username'])
        try:
            cursor.execute("UPDATE users SET slug = %s WHERE id = %s", (slug, user['id']))
        except Error:
            slug = slug + '-' + str(user['id'])
            cursor.execute("UPDATE users SET slug = %s WHERE id = %s", (slug, user['id']))

    # Games without slugs
    cursor.execute("SELECT id, title FROM games WHERE slug IS NULL OR slug = ''")
    for game in cursor.fetchall():
        slug = make_slug(game['title'])
        try:
            cursor.execute("UPDATE games SET slug = %s WHERE id = %s", (slug, game['id']))
        except Error:
            slug = slug + '-' + str(game['id'])
            cursor.execute("UPDATE games SET slug = %s WHERE id = %s", (slug, game['id']))

    conn.commit()
    cursor.close()
    conn.close()


# Run schema migration on import
try:
    if is_using_sqlite():
        from db_compat import _SQLITE_PATH
        init_sqlite_schema(_SQLITE_PATH)
        print("✔ Base de datos SQLite inicializada correctamente.")
    else:
        init_db()
        migrate_db()
        print("✔ Base de datos MySQL inicializada correctamente.")
except Error as e:
    # Force SQLite fallback if MySQL init fails
    try:
        from db_compat import _detect_backend, _SQLITE_PATH
        import db_compat
        db_compat._USE_SQLITE = True
        db_compat._SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'newera_dev.db')
        init_sqlite_schema(db_compat._SQLITE_PATH)
        print(f"⚠ MySQL no disponible ({e}), SQLite inicializado como fallback.")
    except Exception as e2:
        print(f"⚠ No se pudo inicializar la BD: {e2}")

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def make_slug(text):
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[áàäâ]', 'a', text)
    text = re.sub(r'[éèëê]', 'e', text)
    text = re.sub(r'[íìïî]', 'i', text)
    text = re.sub(r'[óòöô]', 'o', text)
    text = re.sub(r'[úùüû]', 'u', text)
    text = re.sub(r'[ñ]', 'n', text)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    return text[:120] if text else 'sin-titulo'


def allowed_file(filename, allowed_extensions):
    """Check if file has an allowed extension."""
    if '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in allowed_extensions


def validate_image_magic(filepath):
    """Validate image file by checking magic bytes."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(12)
            for magic, file_type in IMAGE_MAGIC_BYTES.items():
                if header.startswith(magic):
                    return True
            # Additional check for WebP (RIFF....WEBP)
            if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
                return True
        return False
    except (IOError, OSError):
        return False


def check_user_owns_game(user_id, game_id, role=None):
    """Check if user owns a game (creator, admin, or purchaser)."""
    if not user_id:
        return False
    if role in ['admin']:
        return True
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        # Check if user is creator
        cur.execute('SELECT creator_id FROM games WHERE id = %s', (game_id,))
        game = cur.fetchone()
        if game and game['creator_id'] == user_id:
            cur.close()
            conn.close()
            return True
        # Check if user purchased
        cur.execute('SELECT 1 FROM purchases WHERE user_id = %s AND game_id = %s', (user_id, game_id))
        purchased = cur.fetchone()
        cur.close()
        conn.close()
        return purchased is not None
    except Error:
        return False


# Seed admin & backfill slugs after helpers are defined
try:
    seed_admin()
    backfill_slugs()
except Error as e:
    print(f"⚠ Seed/backfill error: {e}")

# ──────────────────────────────────────────────
# Auth decorator
# ──────────────────────────────────────────────

def login_required(view):
    """Redirect to login page if user is not authenticated."""
    @functools.wraps(view)
    def wrapped(**kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para acceder a esta página.', 'warning')
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped


# ──────────────────────────────────────────────
# Context processor — inject session user into all templates
# ──────────────────────────────────────────────

@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        try:
            conn = get_db()
            cur = conn.cursor(dictionary=True)
            cur.execute('SELECT id, username, email, pic, role, slug, description, developer_plan, social_x, social_youtube, social_instagram, social_github, username_changes_count, last_username_update, email_changes_count, last_email_update, last_password_update FROM users WHERE id = %s', (session['user_id'],))
            user = cur.fetchone()
            cur.close()
            conn.close()
        except Error:
            pass
    
    show_welcome = session.pop('show_welcome', False)
    return dict(current_user=user, show_welcome=show_welcome)


# ══════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════

# ─── SEO and Static Files ──────────────────────
@app.route('/robots.txt')
def robots_txt():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'robots.txt')


@app.route('/sitemap.xml')
def sitemap_xml():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'sitemap.xml')


# ─── Home ─────────────────────────────────────
@app.route('/')
def index():
    # Popular games logic (Ordered by downloads or average rating based on sort param)
    popular_games = []
    games = []
    db_connected = False
    sort_by = request.args.get('sort', 'popular')

    try:
        conn = get_db()
        if conn:
            db_connected = True
            cur = conn.cursor(dictionary=True)

            if sort_by == 'top_rated':
                cur.execute('''
                    SELECT g.id, g.cover, g.title, g.slug AS game_slug, g.price,
                           COALESCE((SELECT AVG(rating) FROM ratings r WHERE r.game_id = g.id), 0) AS avg_rating
                    FROM games g
                    ORDER BY avg_rating DESC, id DESC
                    LIMIT 7
                ''')
            else:
                cur.execute('''
                    SELECT g.id, g.cover, g.title, g.slug AS game_slug, g.price, g.downloads
                    FROM games g
                    ORDER BY g.downloads DESC, id DESC
                    LIMIT 7
                ''')

            popular_games = cur.fetchall()

            cur.execute('''
                SELECT g.id, g.cover, g.title, g.description, g.categories, g.slug AS game_slug, g.price,
                       u.username AS creator_name, u.pic AS creator_pic, u.slug AS creator_slug
                FROM games g
                LEFT JOIN users u ON g.creator_id = u.id
                ORDER BY g.created_at DESC
            ''')
            games = cur.fetchall()
            cur.close()
            conn.close()
    except Exception as e:
        app.logger.error(f'Error de base de datos: {e}')
        db_connected = False

    return render_template('Index.html', games=games, popular_games=popular_games, db_connected=db_connected)

# ─── Informació ───────────────────────────────
@app.route('/informacion')
def informacion():
    return render_template('Informació.html')


# ─── Pricing ──────────────────────────────────
@app.route('/pricing')
def pricing():
    return render_template('pricing.html')


# ─── Contactos ────────────────────────────────
@app.route('/contactos')
def contactos():
    return render_template('contactos.html')


# ─── Donaciones ───────────────────────────────
@app.route('/donar')
def donar():
    return render_template('donar.html')


@app.route('/procesar-donacion', methods=['POST'])
@limiter.limit("3 per minute")  # Prevent donation spam
def procesar_donacion():
    amount = request.form.get('amount', '0.00').strip()
    card_name = request.form.get('card_name', '').strip()
    email = request.form.get('email', '').strip()
    card_number = request.form.get('card_number', '').replace(' ', '')
    
    # Simple validation
    try:
        f_amount = float(amount)
        if f_amount <= 0:
            raise ValueError
    except ValueError:
        flash('Monto de donación inválido.', 'danger')
        return redirect(url_for('donar'))

    if not card_name or not email or len(card_number) < 13:
        flash('Datos de pago incompletos.', 'danger')
        return redirect(url_for('donar'))
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        last4 = card_number[-4:]
        user_id = session.get('user_id') # Optional user_id
        
        cur.execute('''
            INSERT INTO donations (user_id, amount, email, card_name, last4)
            VALUES (%s, %s, %s, %s, %s)
        ''', (user_id, f_amount, email, card_name, last4))
        
        conn.commit()
        cur.close()
        conn.close()
        
        flash(f'¡Gracias por tu donación de ${f_amount:.2f}! Tu apoyo es vital para el proyecto.', 'success')
        return redirect(url_for('index'))
        
    except Error as e:
        flash(f'Error en el procesamiento: {e}', 'danger')
        return redirect(url_for('donar'))


@app.route('/donar-developer/<username>', methods=['POST'])
@limiter.limit("3 per minute")  # Prevent donation spam
def donar_developer(username):
    amount = request.form.get('amount', '0.00').strip()
    card_name = request.form.get('card_name', '').strip()
    email = request.form.get('email', '').strip()
    card_number = request.form.get('card_number', '').replace(' ', '')
    
    try:
        f_amount = float(amount)
        if f_amount <= 0:
            raise ValueError
    except ValueError:
        flash('Monto de donación inválido.', 'danger')
        return redirect(url_for('user_profile', username=username))

    if not card_name or not email or len(card_number) < 13:
        flash('Datos de pago incompletos.', 'danger')
        return redirect(url_for('user_profile', username=username))
    
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        
        # Get developer id
        cur.execute('SELECT id, role FROM users WHERE username = %s', (username,))
        dev = cur.fetchone()
        
        if not dev or dev['role'] not in ['developer', 'admin']:
            cur.close()
            conn.close()
            flash('Desarrollador no encontrado o no puede recibir donaciones.', 'danger')
            return redirect(url_for('user_profile', username=username))

        last4 = card_number[-4:]
        user_id = session.get('user_id')
        
        cur.execute('''
            INSERT INTO donations (user_id, developer_id, amount, email, card_name, last4)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (user_id, dev['id'], f_amount, email, card_name, last4))
        
        conn.commit()
        cur.close()
        conn.close()
        
        flash(f'¡Gracias por tu apoyo directo de ${f_amount:.2f} a {username}!', 'success')
        return redirect(url_for('user_profile', username=username))
        
    except Error as e:
        flash(f'Error en el procesamiento: {e}', 'danger')
        return redirect(url_for('user_profile', username=username))


# ─── Register ─────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # Prevent mass registration
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('passwd', '')

        if not username or not email or not password:
            flash('Todos los campos son obligatorios.', 'danger')
            return redirect(url_for('register'))

        hashed = generate_password_hash(password)
        slug = make_slug(username)

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO users (username, email, password, description, slug) VALUES (%s, %s, %s, %s, %s)',
                (username, email, hashed, '', slug)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Cuenta creada! Ahora inicia sesión.', 'success')
            return redirect(url_for('login'))
        except Error as e:
            err_msg = str(e).lower()
            if 'unique' in err_msg or 'duplicate' in err_msg or 'integrity' in err_msg:
                flash('El usuario o correo ya existe.', 'danger')
            else:
                flash(f'Error: {e}', 'danger')
            return redirect(url_for('register'))

    return render_template('register.html')


# ─── Login ────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")  # Prevent brute force
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('passwd', '')

        try:
            conn = get_db()
            cur = conn.cursor(dictionary=True)
            cur.execute('SELECT * FROM users WHERE email = %s', (email,))
            user = cur.fetchone()
            cur.close()
            conn.close()
        except Error as e:
            flash(f'Error de base de datos: {e}', 'danger')
            return redirect(url_for('login'))

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['developer_plan'] = user.get('developer_plan', 'none')
            session['show_welcome'] = True
            flash(f'¡Bienvenido, {user["username"]}!', 'success')
            return redirect(url_for('index'))

        flash('Email o contraseña incorrectos.', 'danger')
        return redirect(url_for('login'))

    return render_template('login.html')


# ─── Logout ───────────────────────────────────
@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión.', 'info')
    return redirect(url_for('index'))


# ─── Publish game ─────────────────────────────
@app.route('/publish', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per hour")  # Prevent content spam
def publish():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        categories = request.form.get('categories', '').strip()
        price = request.form.get('price', '0.00').strip() or '0.00'
        cover_file = request.files.get('cover')
        game_file = request.files.get('game_file')

        if not title or not description or not cover_file:
            flash('Título, descripción y portada son obligatorios.', 'danger')
            return redirect(url_for('publish'))

        # Save cover image
        ext = os.path.splitext(secure_filename(cover_file.filename))[1]
        cover_filename = f"{uuid.uuid4().hex}{ext}"
        cover_rel_path = f"uploads/covers/{cover_filename}"
        cover_abs_path = os.path.join(app.root_path, 'static', 'uploads', 'covers', cover_filename)
        cover_file.save(cover_abs_path)

        # Save game file
        game_rel_path = None
        if game_file and game_file.filename:
            g_ext = os.path.splitext(secure_filename(game_file.filename))[1]
            game_filename = f"{uuid.uuid4().hex}{g_ext}"
            game_rel_path = f"uploads/games/{game_filename}"
            game_abs_path = os.path.join(app.root_path, 'static', 'uploads', 'games', game_filename)
            game_file.save(game_abs_path)

        # Generate slug
        slug = make_slug(title)

        try:
            conn = get_db()
            cur = conn.cursor()

            # Check slug uniqueness, append id if needed
            cur.execute('SELECT id FROM games WHERE slug = %s', (slug,))
            if cur.fetchone():
                slug = slug + '-' + uuid.uuid4().hex[:6]

            cur.execute(
                '''INSERT INTO games (cover, title, description, creator_id, categories, game_file, slug, price)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                (cover_rel_path, title, description, session['user_id'], categories, game_rel_path, slug, price)
            )
            conn.commit()
            game_id = cur.lastrowid

            # Process Paywall if applicable
            plan = request.form.get('plan', 'estandar')
            card_name = request.form.get('card_name', '').strip()
            payment_email = request.form.get('email', '').strip()
            last4 = request.form.get('last4', '').strip()
            
            if plan in ['pro', 'ultimate'] and card_name and payment_email and last4:
                amount = 4.99 if plan == 'pro' else 9.99
                cur.execute(
                    '''INSERT INTO purchases (user_id, game_id, email, card_name, last4, amount)
                       VALUES (%s, %s, %s, %s, %s, %s)''',
                    (session['user_id'], game_id, payment_email, card_name, last4, amount)
                )
                conn.commit()

            # Auto-promote user to developer role
            cur.execute("SELECT role FROM users WHERE id = %s", (session['user_id'],))
            row = cur.fetchone()
            if row and row[0] == 'standard':
                cur.execute("UPDATE users SET role = 'developer' WHERE id = %s", (session['user_id'],))
                conn.commit()
                session['role'] = 'developer'

            # Update developer plan if not set
            plan = request.form.get('plan', 'estandar')
            cur2 = conn.cursor(dictionary=True)
            cur2.execute("SELECT developer_plan FROM users WHERE id = %s", (session['user_id'],))
            user_plan_row = cur2.fetchone()
            cur2.close()
            if user_plan_row and user_plan_row.get('developer_plan') == 'none':
                cur.execute("UPDATE users SET developer_plan = %s WHERE id = %s", (plan, session['user_id']))
                conn.commit()
                session['developer_plan'] = plan

            cur.close()
            conn.close()
            flash('¡Juego publicado correctamente!', 'success')
            return redirect(url_for('game_detail', slug=slug))
        except Error as e:
            flash(f'Error al publicar: {e}', 'danger')
            return redirect(url_for('publish'))

    return render_template('editor.html')


@app.route('/game/<int:game_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_game(game_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT * FROM games WHERE id = %s', (game_id,))
        game = cur.fetchone()

        if not game:
            cur.close()
            conn.close()
            flash('Juego no encontrado.', 'warning')
            return redirect(url_for('index'))

        # Check permissions: creator or admin
        if game['creator_id'] != session['user_id'] and session.get('role') != 'admin':
            cur.close()
            conn.close()
            flash('No tienes permiso para editar este juego.', 'danger')
            return redirect(url_for('game_detail', slug=game['slug'] or game['id']))

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            categories = request.form.get('categories', '').strip()
            price = request.form.get('price', '0.00').strip() or '0.00'
            cover_file = request.files.get('cover')
            game_file = request.files.get('game_file')

            if not title or not description:
                flash('Título y descripción son obligatorios.', 'danger')
                return redirect(url_for('edit_game', game_id=game_id))

            # Update fields
            new_cover_rel_path = game['cover']
            if cover_file and cover_file.filename:
                # Remove old cover
                old_cover_path = os.path.join(app.root_path, 'static', game['cover'])
                if os.path.exists(old_cover_path):
                    try:
                        os.remove(old_cover_path)
                    except:
                        pass
                
                ext = os.path.splitext(secure_filename(cover_file.filename))[1]
                cover_filename = f"{uuid.uuid4().hex}{ext}"
                new_cover_rel_path = f"uploads/covers/{cover_filename}"
                cover_abs_path = os.path.join(app.root_path, 'static', 'uploads', 'covers', cover_filename)
                cover_file.save(cover_abs_path)

            new_game_rel_path = game['game_file']
            if game_file and game_file.filename:
                if game['game_file']:
                    old_game_path = os.path.join(app.root_path, 'static', game['game_file'])
                    if os.path.exists(old_game_path):
                        try:
                            os.remove(old_game_path)
                        except:
                            pass
                
                g_ext = os.path.splitext(secure_filename(game_file.filename))[1]
                game_filename = f"{uuid.uuid4().hex}{g_ext}"
                new_game_rel_path = f"uploads/games/{game_filename}"
                game_abs_path = os.path.join(app.root_path, 'static', 'uploads', 'games', game_filename)
                game_file.save(game_abs_path)

            # Update database
            cur.execute(
                '''UPDATE games SET cover=%s, title=%s, description=%s, categories=%s, game_file=%s, price=%s
                   WHERE id=%s''',
                (new_cover_rel_path, title, description, categories, new_game_rel_path, price, game_id)
            )
            conn.commit()

            # Process Paywall if applicable
            plan = request.form.get('plan', 'estandar')
            card_name = request.form.get('card_name', '').strip()
            payment_email = request.form.get('email', '').strip()
            last4 = request.form.get('last4', '').strip()
            
            if plan in ['pro', 'ultimate'] and card_name and payment_email and last4:
                amount = 4.99 if plan == 'pro' else 9.99
                cur.execute(
                    '''INSERT INTO purchases (user_id, game_id, email, card_name, last4, amount)
                       VALUES (%s, %s, %s, %s, %s, %s)''',
                    (session['user_id'], game_id, payment_email, card_name, last4, amount)
                )
                conn.commit()
            cur.close()
            conn.close()
            flash('¡Juego actualizado correctamente!', 'success')
            return redirect(url_for('game_detail', slug=game['slug'] or game_id))

        cur.close()
        conn.close()
        return render_template('edit_game.html', game=game)
    except Error as e:
        flash(f'Error al editar: {e}', 'danger')
        return redirect(url_for('index'))


@app.route('/game/<int:game_id>/delete', methods=['POST'])
@login_required
def delete_game(game_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT * FROM games WHERE id = %s', (game_id,))
        game = cur.fetchone()

        if not game:
            cur.close()
            conn.close()
            flash('Juego no encontrado.', 'warning')
            return redirect(url_for('index'))

        # Check permissions: creator or admin
        if game['creator_id'] != session['user_id'] and session.get('role') != 'admin':
            cur.close()
            conn.close()
            flash('No tienes permiso para eliminar este juego.', 'danger')
            return redirect(url_for('game_detail', slug=game['slug'] or game['id']))

        # Delete physical files
        if game['cover']:
            cover_path = os.path.join(app.root_path, 'static', game['cover'])
            if os.path.exists(cover_path):
                try:
                    os.remove(cover_path)
                except:
                    pass
        
        if game['game_file']:
            game_path = os.path.join(app.root_path, 'static', game['game_file'])
            if os.path.exists(game_path):
                try:
                    os.remove(game_path)
                except:
                    pass

        cur.execute('DELETE FROM games WHERE id = %s', (game_id,))
        conn.commit()
        cur.close()
        conn.close()
        flash('Juego eliminado correctamente.', 'success')
        return redirect(url_for('index'))
    except Error as e:
        flash(f'Error al eliminar: {e}', 'danger')
        return redirect(url_for('index'))


# ─── Game detail (slug or id) ────────────────
@app.route('/game/<slug>')
def game_detail(slug):
    game = None
    comments = []
    is_favorited = False
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)

        # Try slug first, then numeric id
        if slug.isdigit():
            cur.execute('''
                SELECT g.*, u.username AS creator_name, u.pic AS creator_pic,
                       u.slug AS creator_slug, u.role AS creator_role
                FROM games g LEFT JOIN users u ON g.creator_id = u.id
                WHERE g.id = %s
            ''', (int(slug),))
        else:
            cur.execute('''
                SELECT g.*, u.username AS creator_name, u.pic AS creator_pic,
                       u.slug AS creator_slug, u.role AS creator_role
                FROM games g LEFT JOIN users u ON g.creator_id = u.id
                WHERE g.slug = %s
            ''', (slug,))
        game = cur.fetchone()

        if game:
            # Favorite count
            cur.execute('SELECT COUNT(*) AS cnt FROM favorites_games WHERE game_id = %s', (game['id'],))
            game['fav_count'] = cur.fetchone()['cnt']

            # Check if current user favorited this game
            if 'user_id' in session:
                cur.execute('SELECT 1 FROM favorites_games WHERE user_id = %s AND game_id = %s',
                            (session['user_id'], game['id']))
                is_favorited = cur.fetchone() is not None

                # Check if purchased OR owner/admin
                if game['creator_id'] == session['user_id'] or session.get('role') == 'admin':
                    has_purchased = True
                else:
                    cur.execute('SELECT 1 FROM purchases WHERE user_id = %s AND game_id = %s',
                                (session['user_id'], game['id']))
                    has_purchased = cur.fetchone() is not None
            else:
                has_purchased = False

            # Fetch average rating
            cur.execute('SELECT AVG(rating) AS avg_r, COUNT(rating) AS count_r FROM ratings WHERE game_id = %s', (game['id'],))
            rating_data = cur.fetchone()
            game['avg_rating'] = rating_data['avg_r'] or 0
            game['rating_count'] = rating_data['count_r'] or 0

            # Fetch current user's rating
            game['user_rating'] = 0
            if 'user_id' in session:
                cur.execute('SELECT rating FROM ratings WHERE user_id = %s AND game_id = %s',
                            (session['user_id'], game['id']))
                row = cur.fetchone()
                if row:
                    game['user_rating'] = row['rating']

            from datetime import timedelta
            # Fetch comments with like count
            cur.execute('''
                SELECT c.*, u.username, u.pic AS user_pic, u.slug AS user_slug,
                       (SELECT COUNT(*) FROM comment_likes cl WHERE cl.comment_id = c.id) AS like_count
                FROM comments c
                JOIN users u ON c.user_id = u.id
                WHERE c.game_id = %s
                ORDER BY c.created_at DESC
            ''', (game['id'],))
            comments = cur.fetchall()

            # Fetch replies for each comment
            for comment in comments:
                # Compute edit deadline ISO string for JS
                c_created = comment['created_at']
                if c_created.tzinfo is not None:
                    c_created = c_created.replace(tzinfo=None)
                comment['edit_deadline'] = (c_created + timedelta(seconds=COMMENT_EDIT_WINDOW)).isoformat()

                cur.execute('''
                    SELECT cr.*, u.username, u.pic AS user_pic, u.slug AS user_slug
                    FROM comment_replies cr
                    JOIN users u ON cr.user_id = u.id
                    WHERE cr.comment_id = %s
                    ORDER BY cr.created_at ASC
                ''', (comment['id'],))
                comment['replies'] = cur.fetchall()

                # Add edit_deadline to each reply
                for reply in comment['replies']:
                    r_created = reply['created_at']
                    if r_created.tzinfo is not None:
                        r_created = r_created.replace(tzinfo=None)
                    reply['edit_deadline'] = (r_created + timedelta(seconds=COMMENT_EDIT_WINDOW)).isoformat()

                # Check if current user liked this comment
                comment['user_liked'] = False
                if 'user_id' in session:
                    cur.execute(
                        'SELECT id FROM comment_likes WHERE comment_id = %s AND user_id = %s',
                        (comment['id'], session['user_id'])
                    )
                    comment['user_liked'] = cur.fetchone() is not None

        cur.close()
        conn.close()
    except Error as e:
        flash(f'Error: {e}', 'danger')

    if not game:
        flash('Juego no encontrado.', 'warning')
        return redirect(url_for('index'))

    now_utc = datetime.now(timezone.utc)
    return render_template('producto.html', game=game, comments=comments, is_favorited=is_favorited,
                           now_utc=now_utc, comment_edit_window=COMMENT_EDIT_WINDOW,
                           has_purchased=has_purchased)


# ─── Download game file ──────────────────────
@app.route('/game/<int:game_id>/download-file')
@login_required
def download_game_file(game_id):
    """
    Secure download endpoint - requires user to own the game.
    Authorization checked: creator, admin, or purchaser.
    """
    user_id = session.get('user_id')
    role = session.get('role')

    # Check if user owns this game
    if not check_user_owns_game(user_id, game_id, role):
        abort(403)  # Forbidden - user doesn't own the game

    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT game_file, title FROM games WHERE id = %s', (game_id,))
        game = cur.fetchone()

        if not game or not game['game_file']:
            cur.close()
            conn.close()
            abort(404)

        file_path = os.path.join(app.root_path, 'static', game['game_file'])
        if not os.path.exists(file_path):
            cur.close()
            conn.close()
            abort(404)

        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1]
        download_name = secure_filename(game['title']) + ext

        # Increment download count
        cur = conn.cursor()
        cur.execute('UPDATE games SET downloads = downloads + 1 WHERE id = %s', (game_id,))
        conn.commit()
        cur.close()
        conn.close()

        return send_from_directory(directory, filename, as_attachment=True, download_name=download_name)

    except Error as e:
        app.logger.error(f'Download error: {e}')
        abort(500)


@app.route('/game/<int:game_id>/purchase', methods=['POST'])
@login_required
@limiter.limit("5 per minute")  # Prevent purchase spam
def purchase_game(game_id):
    card_name = request.form.get('card_name', '').strip()
    email = request.form.get('email', '').strip()
    card_number = request.form.get('card_number', '').replace(' ', '')
    tip_amount = request.form.get('tip_amount', '0').strip() or '0'
    
    try:
        tip_amount = max(0.0, float(tip_amount))
    except (ValueError, TypeError):
        tip_amount = 0.0
    
    if not card_name or not email or len(card_number) < 13:
        flash('Datos de pago incompletos.', 'danger')
        return redirect(url_for('game_detail', slug=str(game_id)))
    
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        
        # Get game price
        cur.execute('SELECT price, title FROM games WHERE id = %s', (game_id,))
        game = cur.fetchone()
        
        if not game:
            cur.close()
            conn.close()
            flash('Juego no encontrado.', 'danger')
            return redirect(url_for('index'))
            
        # Record the purchase (amount = price + tip)
        total_amount = float(game['price']) + tip_amount
        last4 = card_number[-4:]
        cur.execute('''
            INSERT INTO purchases (user_id, game_id, email, card_name, last4, amount)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (session['user_id'], game_id, email, card_name, last4, total_amount))
        
        conn.commit()
        cur.close()
        conn.close()
        
        if tip_amount > 0:
            flash(f'¡Pago de ${total_amount:.2f} procesado (incluye ${tip_amount:.2f} de propina)! Iniciando descarga de {game["title"]}...', 'success')
        else:
            flash(f'¡Pago de ${total_amount:.2f} procesado! Iniciando descarga de {game["title"]}...', 'success')
        return redirect(url_for('download_game_file', game_id=game_id))
        
    except Error as e:
        flash(f'Error en el procesamiento: {e}', 'danger')
        return redirect(url_for('game_detail', slug=str(game_id)))


# ─── Rate game ───────────────────────────────
@app.route('/game/<int:game_id>/rate', methods=['POST'])
@login_required
def rate_game(game_id):
    rating = request.form.get('rating')
    if not rating or not rating.isdigit() or not (1 <= int(rating) <= 5):
        flash('Valoración inválida.', 'danger')
        return redirect(url_for('game_detail', slug=str(game_id)))

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO ratings (user_id, game_id, rating)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE rating = %s
        ''', (session['user_id'], game_id, rating, rating))
        conn.commit()
        cur.close()
        conn.close()
        flash('¡Gracias por tu valoración!', 'success')
    except Error as e:
        flash(f'Error: {e}', 'danger')

    # Redirect to game detail
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT slug FROM games WHERE id = %s', (game_id,))
        g = cur.fetchone()
        cur.close()
        conn.close()
        if g and g['slug']:
            return redirect(url_for('game_detail', slug=g['slug']))
    except:
        pass

    return redirect(url_for('game_detail', slug=str(game_id)))


# ─── Post comment ─────────────────────────────
@app.route('/game/<int:game_id>/comment', methods=['POST'])
@login_required
def post_comment(game_id):
    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'danger')
        return redirect(url_for('game_detail', slug=str(game_id)))

    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            'INSERT INTO comments (game_id, user_id, content) VALUES (%s, %s, %s)',
            (game_id, session['user_id'], content)
        )
        conn.commit()
        # Get game slug for redirect
        cur.execute('SELECT slug FROM games WHERE id = %s', (game_id,))
        g = cur.fetchone()
        cur.close()
        conn.close()
        flash('Comentario publicado.', 'success')
        if g and g['slug']:
            return redirect(url_for('game_detail', slug=g['slug']))
    except Error as e:
        flash(f'Error: {e}', 'danger')

    return redirect(url_for('game_detail', slug=str(game_id)))


# ─── Like / unlike comment ───────────────────
@app.route('/comment/<int:comment_id>/like', methods=['POST'])
@login_required
def like_comment(comment_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            'SELECT id FROM comment_likes WHERE comment_id = %s AND user_id = %s',
            (comment_id, session['user_id'])
        )
        existing = cur.fetchone()

        if existing:
            cur.execute('DELETE FROM comment_likes WHERE id = %s', (existing['id'],))
        else:
            cur.execute(
                'INSERT INTO comment_likes (comment_id, user_id) VALUES (%s, %s)',
                (comment_id, session['user_id'])
            )
        conn.commit()

        cur.execute('SELECT game_id FROM comments WHERE id = %s', (comment_id,))
        comment = cur.fetchone()
        if comment:
            cur.execute('SELECT slug FROM games WHERE id = %s', (comment['game_id'],))
            g = cur.fetchone()
            cur.close()
            conn.close()
            if g and g['slug']:
                return redirect(url_for('game_detail', slug=g['slug']))
            return redirect(url_for('game_detail', slug=str(comment['game_id'])))
        cur.close()
        conn.close()
    except Error as e:
        flash(f'Error: {e}', 'danger')

    return redirect(url_for('index'))


# ─── Reply to comment ────────────────────────
@app.route('/comment/<int:comment_id>/reply', methods=['POST'])
@login_required
def reply_comment(comment_id):
    content = request.form.get('content', '').strip()
    if not content:
        flash('La respuesta no puede estar vacía.', 'danger')
        return redirect(url_for('index'))

    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            'INSERT INTO comment_replies (comment_id, user_id, content) VALUES (%s, %s, %s)',
            (comment_id, session['user_id'], content)
        )
        conn.commit()

        cur.execute('SELECT game_id FROM comments WHERE id = %s', (comment_id,))
        comment = cur.fetchone()
        if comment:
            cur.execute('SELECT slug FROM games WHERE id = %s', (comment['game_id'],))
            g = cur.fetchone()
            cur.close()
            conn.close()
            flash('Respuesta publicada.', 'success')
            if g and g['slug']:
                return redirect(url_for('game_detail', slug=g['slug']))
            return redirect(url_for('game_detail', slug=str(comment['game_id'])))
        cur.close()
        conn.close()
    except Error as e:
        flash(f'Error: {e}', 'danger')

    return redirect(url_for('index'))


# ─── Delete comment ─────────────────────────
@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT * FROM comments WHERE id = %s', (comment_id,))
        comment = cur.fetchone()

        if not comment:
            cur.close()
            conn.close()
            flash('Comentario no encontrado.', 'warning')
            return redirect(url_for('index'))

        if comment['user_id'] != session['user_id'] and session.get('role') != 'admin':
            cur.close()
            conn.close()
            flash('No tienes permiso para eliminar este comentario.', 'danger')
            cur.execute('SELECT slug FROM games WHERE id = %s', (comment['game_id'],))
            g = cur.fetchone()
            return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(comment['game_id'])))

        game_id = comment['game_id']
        # Delete replies first
        cur.execute('DELETE FROM comment_replies WHERE comment_id = %s', (comment_id,))
        # Delete likes
        cur.execute('DELETE FROM comment_likes WHERE comment_id = %s', (comment_id,))
        # Delete comment
        cur.execute('DELETE FROM comments WHERE id = %s', (comment_id,))
        conn.commit()

        cur.execute('SELECT slug FROM games WHERE id = %s', (game_id,))
        g = cur.fetchone()
        cur.close()
        conn.close()
        flash('Comentario eliminado.', 'success')
        return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(game_id)))
    except Error as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('index'))


# ─── Edit comment ────────────────────────────
@app.route('/comment/<int:comment_id>/edit', methods=['POST'])
@login_required
def edit_comment(comment_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT * FROM comments WHERE id = %s', (comment_id,))
        comment = cur.fetchone()

        if not comment:
            cur.close()
            conn.close()
            flash('Comentario no encontrado.', 'warning')
            return redirect(url_for('index'))

        if comment['user_id'] != session['user_id']:
            cur.close()
            conn.close()
            flash('No tienes permiso para editar este comentario.', 'danger')
            cur.execute('SELECT slug FROM games WHERE id = %s', (comment['game_id'],))
            g = cur.fetchone()
            return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(comment['game_id'])))

        # Check time window
        now_utc = datetime.now(timezone.utc)
        created = comment['created_at']
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - created).total_seconds()
        if elapsed > COMMENT_EDIT_WINDOW:
            cur.close()
            conn.close()
            flash('El tiempo para editar este comentario ha expirado.', 'warning')
            cur2 = get_db().cursor(dictionary=True)
            cur2.execute('SELECT slug FROM games WHERE id = %s', (comment['game_id'],))
            g = cur2.fetchone()
            cur2.close()
            return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(comment['game_id'])))

        new_content = request.form.get('content', '').strip()
        if not new_content:
            flash('El comentario no puede estar vacío.', 'danger')
        else:
            cur.execute(
                'UPDATE comments SET content = %s, updated_at = %s WHERE id = %s',
                (new_content, now_utc, comment_id)
            )
            conn.commit()
            flash('Comentario editado.', 'success')

        cur.execute('SELECT slug FROM games WHERE id = %s', (comment['game_id'],))
        g = cur.fetchone()
        cur.close()
        conn.close()
        return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(comment['game_id'])))
    except Error as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('index'))


# ─── Delete reply ────────────────────────────
@app.route('/reply/<int:reply_id>/delete', methods=['POST'])
@login_required
def delete_reply(reply_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT cr.*, c.game_id FROM comment_replies cr JOIN comments c ON cr.comment_id = c.id WHERE cr.id = %s', (reply_id,))
        reply = cur.fetchone()

        if not reply:
            cur.close()
            conn.close()
            flash('Respuesta no encontrada.', 'warning')
            return redirect(url_for('index'))

        if reply['user_id'] != session['user_id'] and session.get('role') != 'admin':
            cur.close()
            conn.close()
            flash('No tienes permiso para eliminar esta respuesta.', 'danger')
            cur2 = get_db().cursor(dictionary=True)
            cur2.execute('SELECT slug FROM games WHERE id = %s', (reply['game_id'],))
            g = cur2.fetchone()
            cur2.close()
            return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(reply['game_id'])))

        game_id = reply['game_id']
        cur.execute('DELETE FROM comment_replies WHERE id = %s', (reply_id,))
        conn.commit()

        cur.execute('SELECT slug FROM games WHERE id = %s', (game_id,))
        g = cur.fetchone()
        cur.close()
        conn.close()
        flash('Respuesta eliminada.', 'success')
        return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(game_id)))
    except Error as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('index'))


# ─── Edit reply ──────────────────────────────
@app.route('/reply/<int:reply_id>/edit', methods=['POST'])
@login_required
def edit_reply(reply_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT cr.*, c.game_id FROM comment_replies cr JOIN comments c ON cr.comment_id = c.id WHERE cr.id = %s', (reply_id,))
        reply = cur.fetchone()

        if not reply:
            cur.close()
            conn.close()
            flash('Respuesta no encontrada.', 'warning')
            return redirect(url_for('index'))

        if reply['user_id'] != session['user_id']:
            cur.close()
            conn.close()
            flash('No tienes permiso para editar esta respuesta.', 'danger')
            cur2 = get_db().cursor(dictionary=True)
            cur2.execute('SELECT slug FROM games WHERE id = %s', (reply['game_id'],))
            g = cur2.fetchone()
            cur2.close()
            return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(reply['game_id'])))

        now_utc = datetime.now(timezone.utc)
        created = reply['created_at']
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - created).total_seconds()
        if elapsed > COMMENT_EDIT_WINDOW:
            cur.close()
            conn.close()
            flash('El tiempo para editar esta respuesta ha expirado.', 'warning')
            cur2 = get_db().cursor(dictionary=True)
            cur2.execute('SELECT slug FROM games WHERE id = %s', (reply['game_id'],))
            g = cur2.fetchone()
            cur2.close()
            return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(reply['game_id'])))

        new_content = request.form.get('content', '').strip()
        if not new_content:
            flash('La respuesta no puede estar vacía.', 'danger')
        else:
            cur.execute(
                'UPDATE comment_replies SET content = %s, updated_at = %s WHERE id = %s',
                (new_content, now_utc, reply_id)
            )
            conn.commit()
            flash('Respuesta editada.', 'success')

        cur.execute('SELECT slug FROM games WHERE id = %s', (reply['game_id'],))
        g = cur.fetchone()
        cur.close()
        conn.close()
        return redirect(url_for('game_detail', slug=g['slug'] if g and g['slug'] else str(reply['game_id'])))
    except Error as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('index'))


# ─── User profile ────────────────────────────
@app.route('/user/<username>')
def user_profile(username):
    profile = None
    games = []
    follower_count = 0
    following_count = 0
    is_following = False
    is_fav_dev = False
    fav_dev_count = 0
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)

        cur.execute('SELECT id, username, email, pic, role, slug, description, created_at, developer_plan, social_x, social_youtube, social_instagram, social_github FROM users WHERE username = %s OR slug = %s',
                    (username, username))
        profile = cur.fetchone()

        if profile:
            # Games by this user
            cur.execute('''
                SELECT id, title, cover, slug, categories, created_at
                FROM games WHERE creator_id = %s ORDER BY created_at DESC
            ''', (profile['id'],))
            games = cur.fetchall()

            # Follower / following counts
            cur.execute('SELECT COUNT(*) AS cnt FROM follows WHERE followed_id = %s', (profile['id'],))
            follower_count = cur.fetchone()['cnt']
            cur.execute('SELECT COUNT(*) AS cnt FROM follows WHERE follower_id = %s', (profile['id'],))
            following_count = cur.fetchone()['cnt']

            # Favorite developer count
            cur.execute('SELECT COUNT(*) AS cnt FROM favorites_developers WHERE developer_id = %s', (profile['id'],))
            fav_dev_count = cur.fetchone()['cnt']

            # Is current user following / fav this profile?
            if 'user_id' in session and session['user_id'] != profile['id']:
                cur.execute('SELECT 1 FROM follows WHERE follower_id = %s AND followed_id = %s',
                            (session['user_id'], profile['id']))
                is_following = cur.fetchone() is not None

                cur.execute('SELECT 1 FROM favorites_developers WHERE user_id = %s AND developer_id = %s',
                            (session['user_id'], profile['id']))
                is_fav_dev = cur.fetchone() is not None

        cur.close()
        conn.close()
    except Error as e:
        flash(f'Error: {e}', 'danger')

    if not profile:
        flash('Usuario no encontrado.', 'warning')
        return redirect(url_for('index'))

    return render_template('profile.html', profile=profile, games=games,
                           follower_count=follower_count, following_count=following_count,
                           is_following=is_following, is_fav_dev=is_fav_dev, fav_dev_count=fav_dev_count)


# ─── Follow / unfollow ───────────────────────
@app.route('/user/<username>/follow', methods=['POST'])
@login_required
def toggle_follow(username):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT id FROM users WHERE username = %s OR slug = %s', (username, username))
        target = cur.fetchone()
        if target and target['id'] != session['user_id']:
            cur.execute('SELECT 1 FROM follows WHERE follower_id = %s AND followed_id = %s',
                        (session['user_id'], target['id']))
            if cur.fetchone():
                cur.execute('DELETE FROM follows WHERE follower_id = %s AND followed_id = %s',
                            (session['user_id'], target['id']))
            else:
                cur.execute('INSERT INTO follows (follower_id, followed_id) VALUES (%s, %s)',
                            (session['user_id'], target['id']))
            conn.commit()
        cur.close()
        conn.close()
    except Error as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('user_profile', username=username))


# ─── Favorite game ───────────────────────────
@app.route('/game/<int:game_id>/favorite', methods=['POST'])
@login_required
def toggle_fav_game(game_id):
    slug = str(game_id)
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT 1 FROM favorites_games WHERE user_id = %s AND game_id = %s',
                    (session['user_id'], game_id))
        if cur.fetchone():
            cur.execute('DELETE FROM favorites_games WHERE user_id = %s AND game_id = %s',
                        (session['user_id'], game_id))
        else:
            cur.execute('INSERT INTO favorites_games (user_id, game_id) VALUES (%s, %s)',
                        (session['user_id'], game_id))
        conn.commit()
        cur.execute('SELECT slug FROM games WHERE id = %s', (game_id,))
        g = cur.fetchone()
        if g and g['slug']:
            slug = g['slug']
        cur.close()
        conn.close()
    except Error as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('game_detail', slug=slug))


# ─── Favorite developer ─────────────────────
@app.route('/user/<username>/favorite', methods=['POST'])
@login_required
def toggle_fav_developer(username):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT id FROM users WHERE username = %s OR slug = %s', (username, username))
        target = cur.fetchone()
        if target and target['id'] != session['user_id']:
            cur.execute('SELECT 1 FROM favorites_developers WHERE user_id = %s AND developer_id = %s',
                        (session['user_id'], target['id']))
            if cur.fetchone():
                cur.execute('DELETE FROM favorites_developers WHERE user_id = %s AND developer_id = %s',
                            (session['user_id'], target['id']))
            else:
                cur.execute('INSERT INTO favorites_developers (user_id, developer_id) VALUES (%s, %s)',
                            (session['user_id'], target['id']))
            conn.commit()
        cur.close()
        conn.close()
    except Error as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('user_profile', username=username))


# ─── Avatar upload ───────────────────────────
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        form_type = request.form.get('form_type', 'profile')
        updated = False

        try:
            conn = get_db()
            cur = conn.cursor(dictionary=True)

            if form_type == 'profile':
                description = request.form.get('description', '').strip()
                social_x = request.form.get('social_x', '').strip()
                social_youtube = request.form.get('social_youtube', '').strip()
                social_instagram = request.form.get('social_instagram', '').strip()
                social_github = request.form.get('social_github', '').strip()
                avatar = request.files.get('avatar')

                if avatar and avatar.filename:
                    ext = os.path.splitext(secure_filename(avatar.filename))[1]
                    avatar_filename = f"{uuid.uuid4().hex}{ext}"
                    avatar_rel_path = f"uploads/avatars/{avatar_filename}"
                    avatar_abs_path = os.path.join(app.root_path, 'static', 'uploads', 'avatars', avatar_filename)
                    avatar.save(avatar_abs_path)

                    cur.execute('UPDATE users SET pic = %s WHERE id = %s', (avatar_rel_path, session['user_id']))
                    updated = True

                if description is not None:
                    cur.execute('UPDATE users SET description = %s WHERE id = %s', (description, session['user_id']))
                    updated = True
                    
                if 'social_x' in request.form:
                    cur.execute('UPDATE users SET social_x = %s WHERE id = %s', (social_x, session['user_id']))
                    updated = True
                if 'social_youtube' in request.form:
                    cur.execute('UPDATE users SET social_youtube = %s WHERE id = %s', (social_youtube, session['user_id']))
                    updated = True
                if 'social_instagram' in request.form:
                    cur.execute('UPDATE users SET social_instagram = %s WHERE id = %s', (social_instagram, session['user_id']))
                    updated = True
                if 'social_github' in request.form:
                    cur.execute('UPDATE users SET social_github = %s WHERE id = %s', (social_github, session['user_id']))
                    updated = True

            elif form_type == 'account':
                new_username = request.form.get('username', '').strip()
                new_email = request.form.get('email', '').strip()
                current_password = request.form.get('current_password', '')
                new_password = request.form.get('new_password', '')
                confirm_password = request.form.get('confirm_new_password', '')

                cur.execute('SELECT email, password, username_changes_count, last_username_update, email_changes_count, last_email_update, last_password_update FROM users WHERE id = %s', (session['user_id'],))
                user_record = cur.fetchone()

                now_utc = datetime.now(timezone.utc)

                if new_username and new_username != session.get('username'):
                    if user_record['username_changes_count'] >= 3:
                        flash('Has alcanzado el límite máximo de cambios de nombre de usuario (3).', 'danger')
                    else:
                        last_update = user_record['last_username_update']
                        can_update = True
                        if last_update:
                            if last_update.tzinfo is None:
                                last_update = last_update.replace(tzinfo=timezone.utc)
                            if (now_utc - last_update).days < 30:
                                flash('Debes esperar 30 días entre cambios de nombre de usuario.', 'warning')
                                can_update = False
                        
                        if can_update:
                            cur.execute('SELECT id FROM users WHERE username = %s', (new_username,))
                            if cur.fetchone():
                                flash('Ese nombre de usuario ya está en uso.', 'danger')
                            else:
                                cur.execute('UPDATE users SET username = %s, username_changes_count = username_changes_count + 1, last_username_update = %s WHERE id = %s', (new_username, now_utc, session['user_id']))
                                session['username'] = new_username
                                updated = True

                if new_email and new_email != user_record['email']:
                    if user_record['email_changes_count'] >= 5:
                        flash('Has alcanzado el límite máximo de cambios de correo electrónico (5).', 'danger')
                    else:
                        last_update = user_record['last_email_update']
                        can_update = True
                        if last_update:
                            if last_update.tzinfo is None:
                                last_update = last_update.replace(tzinfo=timezone.utc)
                            if (now_utc - last_update).days < 30:
                                flash('Debes esperar 30 días entre cambios de correo electrónico.', 'warning')
                                can_update = False

                        if can_update:
                            cur.execute('SELECT id FROM users WHERE email = %s', (new_email,))
                            if cur.fetchone():
                                flash('Ese correo electrónico ya está registrado.', 'danger')
                            else:
                                cur.execute('UPDATE users SET email = %s, email_changes_count = email_changes_count + 1, last_email_update = %s WHERE id = %s', (new_email, now_utc, session['user_id']))
                                updated = True

                if current_password and (new_password or confirm_password):
                    if new_password != confirm_password:
                        flash('Las contraseñas nuevas no coinciden.', 'danger')
                    else:
                        last_update = user_record['last_password_update']
                        can_update = True
                        if last_update:
                            if last_update.tzinfo is None:
                                last_update = last_update.replace(tzinfo=timezone.utc)
                            if (now_utc - last_update).total_seconds() < 86400: # 24 hours
                                flash('Debes esperar 24 horas entre cambios de contraseña.', 'warning')
                                can_update = False

                        if can_update:
                            if check_password_hash(user_record['password'], current_password):
                                hashed_pw = generate_password_hash(new_password)
                                cur.execute('UPDATE users SET password = %s, last_password_update = %s WHERE id = %s', (hashed_pw, now_utc, session['user_id']))
                                updated = True
                            else:
                                flash('La contraseña actual es incorrecta.', 'danger')

            if updated:
                conn.commit()
                flash('¡Ajustes guardados!', 'success')
            else:
                flash('No se detectaron cambios u ocurrió un error de validación.', 'info')

            cur.close()
            conn.close()
        except Error as e:
            flash(f'Error: {e}', 'danger')

        return redirect(url_for('settings'))

    return render_template('settings.html')


# ─── Upgrade Plan route ──────────────────────
@app.route('/upgrade_plan', methods=['POST'])
def upgrade_plan():
    if not session.get('user_id'):
        return jsonify({'error': 'No autorizado'}), 401
    
    plan = request.form.get('plan')
    if plan not in ['estandar', 'pro', 'ultimate']:
        return jsonify({'error': 'Plan inválido'}), 400
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET developer_plan = %s WHERE id = %s", (plan, session['user_id']))
        conn.commit()
        session['developer_plan'] = plan
        cur.close()
        conn.close()
        return jsonify({'success': True, 'plan': plan})
    except Error as e:
        return jsonify({'error': str(e)}), 500


# ─── Error Handlers ──────────────────────────
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(403)
def access_denied(e):
    return render_template('404.html', message="Acceso denegado. Actividad sospechosa detectada."), 403


# ─── Security Honeypot ───────────────────────
@app.route('/admin/.env')
@app.route('/wp-admin')
@app.route('/.git')
def honeypot():
    ip = get_client_ip()
    app.logger.warning(f"HONEYPOT TRIGGERED by IP: {ip} on path: {request.path}")
    # Simular un error de carga pesada o simplemente denegar
    return abort(403)


# ══════════════════════════════════════════════
#  Run
# ══════════════════════════════════════════════
if __name__ == '__main__':
    migrate_db()
    # Production configuration with DEBUG enabled for development workflow
    # SECURITY: use_evalex=False disables the interactive debugger shell
    # while keeping debug logs and auto-reload active
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 'yes']
    use_reloader = os.environ.get('FLASK_USE_RELOADER', 'True').lower() in ['true', '1', 'yes']
    app.run(
        debug=debug_mode,
        host='0.0.0.0',
        port=8080,
        use_reloader=use_reloader,
        use_evalex=False  # Disable interactive debugger (security critical!)
    )
