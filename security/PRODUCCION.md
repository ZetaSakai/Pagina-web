# Producción con Debug Habilitado - New Era Games

## Configuración Actual

La aplicación está configurada para ejecutarse en **producción con DEBUG=True** pero con las siguientes protecciones de seguridad:

### Puerto
- **8080** (web y Docker)

### Protecciones Implementadas

| Protección | Estado | Descripción |
|------------|--------|-------------|
| **Host Header Validation** | ✅ Activo | Previene inyección de Host header - rechaza requests con Host no autorizado |
| **use_evalex=False** | ✅ Activo | Deshabilita el debugger interactivo de Werkzeug (evita ejecución remota de código) |
| **CSRF Protection** | ✅ Activo | Flask-WTF con tokens en todos los formularios |
| **Rate Limiting** | ✅ Activo | Flask-Limiter en endpoints críticos (login, registro, donaciones, purchases) |
| **Session Cookies** | ✅ Config | HttpOnly=True, SameSite=Lax, Secure=False (local HTTP) |
| **Download Authorization** | ✅ Activo | Verifica propiedad/compra antes de permitir descargas |
| **Allowed Hosts** | ✅ Config | Lista blanca de hosts permitidos (ALLOWED_HOSTS) |

### Variables de Entorno (.env)

```bash
FLASK_SECRET_KEY=<clave-segura-generada>
FLASK_DEBUG=True
DB_HOST=db
DB_PORT=3310
DB_USER=root
DB_PASSWORD=root
DB_NAME=main
ALLOWED_HOSTS=localhost,127.0.0.1
```

## ¿Por qué es seguro tener DEBUG=True?

El riesgo principal de `DEBUG=True` en Flask es el **debugger interactivo de Werkzeug** que permite ejecutar código Python arbitrario desde el navegador si alguien puede触发ar un error.

**Nuestra mitigación:**
1. `use_evalex=False` - Deshabilita completamente la consola interactiva
2. Host Header Validation - Previene ataques de envenenamiento
3. Rate Limiting - Previene fuerza bruta y DoS
4. CSRF Protection - Previene ataques cross-site

## Comandos para Producción

### Iniciar con Docker (Recomendado)
```bash
docker compose up --build -d
```

### Iniciar directo con Python
```bash
python app.py
```

Acceso: http://localhost:8080

## WAF Externo (Cloudflare) - Pendiente

Para protección completa contra DDoS y ataques externos:

1. Configurar DNS del dominio en Cloudflare
2. Activar proxy (nube naranja)
3. Ejecutar script UFW: `./security/cloudflare_ufw_setup.sh`
4. Implementar reglas WAF en panel de Cloudflare

## Monitoreo Recomendado

```bash
# Ver logs en tiempo real
docker compose logs -f web

# Ver intentos de Host header bloqueados
docker compose logs web | grep -i "Blocked request"
```
