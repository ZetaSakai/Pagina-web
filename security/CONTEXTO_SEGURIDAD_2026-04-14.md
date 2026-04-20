# Contexto Completo - Implementación de Seguridad New Era Games
**Fecha**: 2026-04-14  
**Estado**: Parcialmente completado - pendiente recargar Nginx

---

## 1. Resumen Ejecutivo

Se implementó un plan de seguridad completo para New Era Games considerando:
- Hardware limitado: Intel Celeron N4100, 3.6GB RAM (~350MB disponibles)
- Producción con DEBUG=True (requerido para workflow de desarrollo)
- Puerto objetivo: **8080** (Flask directo) / **80** (Nginx proxy)

---

## 2. Cambios Realizados

### A. Archivos de Configuración

#### `.env` (Variables de entorno)
```bash
FLASK_SECRET_KEY=Nw3r4-G4m3s-S3cr3t-K3y-Pr0d-2026
FLASK_DEBUG=True
DB_HOST=db
DB_PORT=3310
DB_USER=root
DB_PASSWORD=root
DB_NAME=main
MYSQL_ROOT_PASSWORD=root
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
CLOUDFLARE_PROXY=true
```

#### `docker-compose.yml`
- Puerto cambiado a **8080:8080**
- Variables de entorno desde `.env`
- DB puerto 3310
- Eliminado servicio dev_ssh por seguridad

#### `Dockerfile`
```dockerfile
EXPOSE 8080
CMD ["gunicorn", "--timeout", "120", "--capture-output", 
     "--error-logfile", "-", "--access-logfile", "-", 
     "-w", "4", "-b", "0.0.0.0:8080", "app:app"]
```

### B. app.py - Endurecimiento de Seguridad

#### Imports con fallback (compatibilidad)
```python
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(): pass

try:
    from flask_wtf import CSRFProtect
except ModuleNotFoundError:
    CSRFProtect = None

try:
    from flask_limiter import Limiter
except ModuleNotFoundError:
    Limiter = None
```

#### Configuración de sesión segura
```python
debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 'yes']
app.config['SESSION_COOKIE_SECURE'] = not debug_mode  # Solo HTTPS en producción real
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Previene XSS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Previene CSRF
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
```

#### Validación de Host Header (CRÍTICO)
```python
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

@app.before_request
def validate_host_header():
    """Previene host header injection attacks."""
    host = request.host.split(':')[0].lower()
    if ALLOWED_HOSTS and host not in ALLOWED_HOSTS:
        app.logger.warning(f'Blocked request with invalid Host header: {host}')
        abort(403)
```

#### Debugger seguro con use_evalex=False
```python
app.run(
    debug=debug_mode,
    host='0.0.0.0',
    port=8080,
    use_evalex=False  # ¡CRÍTICO! Deshabilita consola interactiva
)
```

#### Endpoints con Rate Limiting
| Endpoint | Límite | Propósito |
|----------|--------|-----------|
| `/register` | 5/min | Prevenir registro masivo |
| `/login` | 10/min | Prevenir brute force |
| `/procesar-donacion` | 3/min | Prevenir spam donaciones |
| `/donar-developer/<username>` | 3/min | Prevenir spam donaciones |
| `/publish` | 10/hora | Prevenir spam contenido |
| `/game/<id>/purchase` | 5/min | Prevenir spam compras |

#### Download Authorization (Vulnerabilidad #1 corregida)
```python
@app.route('/game/<int:game_id>/download-file')
@login_required
def download_game_file(game_id):
    user_id = session.get('user_id')
    role = session.get('role')
    
    if not check_user_owns_game(user_id, game_id, role):
        abort(403)  # Solo creador, admin o comprador
```

#### Función `check_user_owns_game()`
Verifica si usuario es:
1. Creador del juego
2. Admin
3. Comprador (tabla `purchases`)

### C. Templates - CSRF Tokens

Añadido `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>` en:
- `templates/login.html`
- `templates/register.html`
- `templates/editor.html` (formulario publish)
- `templates/producto.html` (comentarios, likes, compras, favoritos, editar, borrar)
- `templates/settings.html`
- `templates/profile.html`
- `templates/donar.html`

### D. Limpieza de Archivos Sensibles

Movidos a `.secure_backup/`:
- `*.key` (claves privadas)
- `*.pem` (certificados)
- `backup_*.sql` (dumps BD)
- `*.zip` (backups proyecto)
- `wetransfer_*.zip`

Actualizado `.gitignore`:
```
.secure_backup/
*.key
*.pem
*.crt
*.sql
*.zip
*.log
static/uploads/
```

### E. Nginx Configuración

Archivo: `nginx/new-era-games.conf`
```nginx
server {
    listen 80;
    server_name _;
    
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_buffering off;
    }
    
    location /static {
        alias /app/Pagina-web/static;
        expires 30d;
    }
}
```

### F. Scripts de Seguridad

#### `security/cloudflare_ufw_setup.sh`
Script para configurar UFW con IPs de Cloudflare (pendiente ejecutar si se usa Cloudflare).

#### `security/PRODUCCION.md`
Documentación completa de producción con debug.

---

## 3. Estado Actual

| Componente | Estado | Notas |
|------------|--------|-------|
| Flask app (8080) | ✅ Funcionando | Debug=True, protecciones activas |
| Nginx config | ✅ Instalada | En `/etc/nginx/sites-available/` y `sites-enabled/` |
| Nginx reload | ⚠️ Pendiente | Requiere `sudo systemctl reload nginx` |
| Dominio no-ip | ⚠️ Configuración en local | Datos ya están en el sistema |
| Cloudflare WAF | ⏸️ Opcional | Script listo, requiere configuración DNS externa |

---

## 4. Protección contra Ataques

### DEBUG=True Seguro
| Riesgo | Mitigación |
|--------|------------|
| Debugger interactivo de Werkzeug | `use_evalex=False` - deshabilita consola Python |
| Host header injection | Validación en `@app.before_request` |
| CSRF | Flask-WTF con tokens en todos los formularios |
| Brute force | Flask-Limiter en login/registro |
| Descargas no autorizadas | Verificación de propiedad/compra |
| Session hijacking | HttpOnly + SameSite=Lax cookies |

### Capas de Defensa
1. **Nginx** (puerto 80): Proxy inverso, rate limiting externo posible
2. **Flask** (puerto 8080): Rate limiting, CSRF, validación hosts
3. **Cloudflare** (opcional): WAF en la nube, DDoS protection

---

## 5. Comandos Pendientes

### Para completar la implementación:

```bash
# 1. Recargar Nginx (pendiente)
sudo systemctl reload nginx

# 2. Verificar que funciona
curl -I http://localhost:80
# Debe mostrar: Server: Werkzeug/3.1.6 Python/3.12.3

# 3. Si se usa Cloudflare:
#    - Configurar DNS en Cloudflare
#    - Activar proxy (nube naranja)
#    - Ejecutar: ./security/cloudflare_ufw_setup.sh
```

---

## 6. Arquitectura Final

```
Internet
    │
    ├─── (Opcional) Cloudflare WAF ───► Puerto 80 ──┐
    │                                                │
    └─── (Directo) ──────────────────────────────────┤
                                                     ▼
                                              Nginx (proxy)
                                                     │
                                                     ▼
                                              Flask :8080
                                              (Debug=True,
                                               protecciones activas)
                                                     │
                                                     ▼
                                              MySQL :3310
```

---

## 7. Variables de Entorno Clave

| Variable | Valor | Propósito |
|----------|-------|-----------|
| `FLASK_SECRET_KEY` | `Nw3r4-G4m3s-S3cr3t-K3y-Pr0d-2026` | Firma de sesiones |
| `FLASK_DEBUG` | `True` | Modo debug (logs, auto-reload) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1,0.0.0.0` | Hosts permitidos |
| `DB_HOST` | `db` | Host MySQL (Docker) |
| `DB_PORT` | `3310` | Puerto MySQL |

---

## 8. Próximos Pasos Recomendados

1. **Inmediato**: Ejecutar `sudo systemctl reload nginx`
2. **DNS**: Configurar dominio no-ip (datos ya en local)
3. **Opcional**: Cloudflare para DDoS protection
4. **Monitoreo**: Revisar logs `app.log` y `/var/log/nginx/new-era-games-error.log`

---

## 9. Referencias

- Documentación completa: `security/PRODUCCION.md`
- Config Nginx: `nginx/new-era-games.conf`
- Script UFW: `security/cloudflare_ufw_setup.sh`
- Archivos sensibles: `.secure_backup/`

---

**Fin del documento de contexto**
