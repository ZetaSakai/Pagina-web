import os
import re
import uuid
import base64
import functools

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import mysql.connector
from mysql.connector import Error

# ──────────────────────────────────────────────
# App configuration
# ──────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = 'new-era-games-secret-key-change-in-production'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB upload limit

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'covers'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'games'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'avatars'), exist_ok=True)

# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3310,
    'user': 'root',
    'password': 'root',
    'database': 'main',
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_general_ci',
}


def get_db():
    """Return a new MySQL connection."""
    return mysql.connector.connect(**DB_CONFIG)


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
        "ALTER TABLE users ADD COLUMN slug VARCHAR(60) NULL",
        "ALTER TABLE users ADD UNIQUE KEY uq_slug (slug)",
        "ALTER TABLE games ADD COLUMN slug VARCHAR(120) NULL",
        "ALTER TABLE games ADD UNIQUE KEY uq_game_slug (slug)",
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
            "INSERT INTO users (username, email, password, role, slug) VALUES (%s, %s, %s, %s, %s)",
            ('admin', 'admin@newera.local', hashed, 'admin', 'admin')
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
    init_db()
    migrate_db()
    print("✔ Base de datos inicializada correctamente.")
except Error as e:
    print(f"⚠ No se pudo inicializar la BD: {e}")

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
            cur.execute('SELECT id, username, email, pic, role, slug FROM users WHERE id = %s', (session['user_id'],))
            user = cur.fetchone()
            cur.close()
            conn.close()
        except Error:
            pass
    return dict(current_user=user)


# ══════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════

# ─── Home ─────────────────────────────────────
@app.route('/')
def index():
    games = []
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('''
            SELECT g.id, g.cover, g.title, g.description, g.categories, g.slug AS game_slug,
                   u.username AS creator_name, u.pic AS creator_pic, u.slug AS creator_slug
            FROM games g
            LEFT JOIN users u ON g.creator_id = u.id
            ORDER BY g.created_at DESC
        ''')
        games = cur.fetchall()
        cur.close()
        conn.close()
    except Error as e:
        flash(f'Error al cargar juegos: {e}', 'danger')
    return render_template('Index.html', games=games)


# ─── Informació ───────────────────────────────
@app.route('/informacion')
def informacion():
    return render_template('Informació.html')


# ─── Contactos ────────────────────────────────
@app.route('/contactos')
def contactos():
    return render_template('contactos.html')


# ─── Register ─────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
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
                'INSERT INTO users (username, email, password, slug) VALUES (%s, %s, %s, %s)',
                (username, email, hashed, slug)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Cuenta creada! Ahora inicia sesión.', 'success')
            return redirect(url_for('login'))
        except mysql.connector.IntegrityError:
            flash('El usuario o correo ya existe.', 'danger')
            return redirect(url_for('register'))
        except Error as e:
            flash(f'Error: {e}', 'danger')
            return redirect(url_for('register'))

    return render_template('register.html')


# ─── Login ────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
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
def publish():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        categories = request.form.get('categories', '').strip()
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
                '''INSERT INTO games (cover, title, description, creator_id, categories, game_file, slug)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                (cover_rel_path, title, description, session['user_id'], categories, game_rel_path, slug)
            )
            conn.commit()
            game_id = cur.lastrowid

            # Auto-promote user to developer role
            cur.execute("SELECT role FROM users WHERE id = %s", (session['user_id'],))
            row = cur.fetchone()
            if row and row[0] == 'standard':
                cur.execute("UPDATE users SET role = 'developer' WHERE id = %s", (session['user_id'],))
                conn.commit()
                session['role'] = 'developer'

            cur.close()
            conn.close()
            flash('¡Juego publicado correctamente!', 'success')
            return redirect(url_for('game_detail', slug=slug))
        except Error as e:
            flash(f'Error al publicar: {e}', 'danger')
            return redirect(url_for('publish'))

    return render_template('editor.html')


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
                cur.execute('''
                    SELECT cr.*, u.username, u.pic AS user_pic, u.slug AS user_slug
                    FROM comment_replies cr
                    JOIN users u ON cr.user_id = u.id
                    WHERE cr.comment_id = %s
                    ORDER BY cr.created_at ASC
                ''', (comment['id'],))
                comment['replies'] = cur.fetchall()

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

    return render_template('producto.html', game=game, comments=comments, is_favorited=is_favorited)


# ─── Download game file ──────────────────────
@app.route('/game/<int:game_id>/download-file')
def download_game_file(game_id):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT game_file, title FROM games WHERE id = %s', (game_id,))
        game = cur.fetchone()
        cur.close()
        conn.close()

        if game and game['game_file']:
            file_path = os.path.join(app.root_path, 'static', game['game_file'])
            if os.path.exists(file_path):
                directory = os.path.dirname(file_path)
                filename = os.path.basename(file_path)
                # Use original extension but game title as download name
                ext = os.path.splitext(filename)[1]
                download_name = secure_filename(game['title']) + ext
                return send_from_directory(directory, filename, as_attachment=True, download_name=download_name)
    except Error as e:
        flash(f'Error: {e}', 'danger')

    flash('Archivo no disponible.', 'warning')
    return redirect(url_for('index'))


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

        cur.execute('SELECT id, username, email, pic, role, slug, created_at FROM users WHERE username = %s OR slug = %s',
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
        avatar = request.files.get('avatar')
        if avatar and avatar.filename:
            ext = os.path.splitext(secure_filename(avatar.filename))[1]
            avatar_filename = f"{uuid.uuid4().hex}{ext}"
            avatar_rel_path = f"uploads/avatars/{avatar_filename}"
            avatar_abs_path = os.path.join(app.root_path, 'static', 'uploads', 'avatars', avatar_filename)
            avatar.save(avatar_abs_path)

            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute('UPDATE users SET pic = %s WHERE id = %s', (avatar_rel_path, session['user_id']))
                conn.commit()
                cur.close()
                conn.close()
                flash('¡Foto de perfil actualizada!', 'success')
            except Error as e:
                flash(f'Error: {e}', 'danger')
        else:
            flash('Selecciona una imagen.', 'warning')
        return redirect(url_for('settings'))

    return render_template('settings.html')


# ─── Download page (static) ─────────────────
@app.route('/download')
def download():
    return render_template('download.html')


# ══════════════════════════════════════════════
#  Run
# ══════════════════════════════════════════════
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
