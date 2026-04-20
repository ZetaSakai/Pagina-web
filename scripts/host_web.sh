#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/app/Pagina-web"
NGINX_SITE_SRC="$PROJECT_ROOT/nginx/new-era-games.conf"
NGINX_CONF_SRC="$PROJECT_ROOT/nginx/nginx.conf"
NGINX_SITE_DST="/etc/nginx/sites-available/new-era-games"
SYSTEMD_APP_DST="/etc/systemd/system/new-era-games-debug.service"
SYSTEMD_APP_SRC="$PROJECT_ROOT/deploy/new-era-games-debug.service"
NOIP_DEFAULTS="/etc/default/noip-duc"
NOIP_DEB="$PROJECT_ROOT/no-ip/noip-duc_3.3.0/binaries/noip-duc_3.3.0_amd64.deb"
DOMAIN="newera-games.servegame.com"

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "Este script debe ejecutarse con sudo/root."
        exit 1
    fi
}

install_nginx_config() {
    mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
    cp "$NGINX_CONF_SRC" /etc/nginx/nginx.conf
    cp "$NGINX_SITE_SRC" "$NGINX_SITE_DST"
    ln -sf "$NGINX_SITE_DST" /etc/nginx/sites-enabled/new-era-games
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    systemctl enable nginx
    systemctl restart nginx
}

mount_db_image() {
    local MOUNT_POINT="$PROJECT_ROOT/mysql_data_ci"
    local DB_IMAGE="$PROJECT_ROOT/db_casefold.img"
    
    if ! mount | grep -q "$MOUNT_POINT"; then
        echo "Montando imagen de base de datos ($DB_IMAGE)..."
        if [ ! -f "$DB_IMAGE" ]; then
            echo "Error: No se encuentra la imagen: $DB_IMAGE"
            return 1
        fi
        mkdir -p "$MOUNT_POINT"
        mount -o loop "$DB_IMAGE" "$MOUNT_POINT"
    fi
}

install_app_service() {
    mount_db_image
    docker compose -f "$PROJECT_ROOT/docker-compose.yml" up -d db
    
    cp "$SYSTEMD_APP_SRC" "$SYSTEMD_APP_DST"
    pkill -f "python3 /app/Pagina-web/app.py" 2>/dev/null || true
    pkill -f "python3 app.py" 2>/dev/null || true
    systemctl daemon-reload
    systemctl enable new-era-games-debug.service
    systemctl restart new-era-games-debug.service
}

install_noip() {
    if ! command -v noip-duc >/dev/null 2>&1; then
        dpkg -i "$NOIP_DEB"
    fi

    if [[ ! -f "$NOIP_DEFAULTS" ]]; then
        cat > "$NOIP_DEFAULTS" <<EOF
NOIP_USERNAME=
NOIP_PASSWORD=
NOIP_HOSTNAMES=$DOMAIN
EOF
    fi

    if grep -q '^NOIP_HOSTNAMES=' "$NOIP_DEFAULTS"; then
        sed -i "s|^NOIP_HOSTNAMES=.*|NOIP_HOSTNAMES=$DOMAIN|" "$NOIP_DEFAULTS"
    else
        echo "NOIP_HOSTNAMES=$DOMAIN" >> "$NOIP_DEFAULTS"
    fi

    if systemctl list-unit-files | grep -q '^noip-duc\.service'; then
        systemctl enable noip-duc
        systemctl restart noip-duc
    elif systemctl list-unit-files | grep -q '^noip2\.service'; then
        systemctl enable noip2
        systemctl restart noip2
    else
        echo "No se encontró un servicio systemd de No-IP; revisa la instalación del paquete."
    fi
}

show_status() {
    echo "=== App ==="
    systemctl --no-pager --full status new-era-games-debug.service | sed -n '1,20p' || true
    echo "=== Nginx ==="
    systemctl --no-pager --full status nginx | sed -n '1,20p' || true
    echo "=== No-IP ==="
    systemctl --no-pager --full status noip-duc 2>/dev/null | sed -n '1,20p' || \
    systemctl --no-pager --full status noip2 2>/dev/null | sed -n '1,20p' || true
    echo "=== HTTP 80 ==="
    curl -sI http://localhost:80 | sed -n '1,12p' || true
    echo "=== HTTP 8080 ==="
    curl -sI http://localhost:8080 | sed -n '1,12p' || true
}

require_root
install_nginx_config
install_app_service
install_noip
show_status
