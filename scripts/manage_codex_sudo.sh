#!/usr/bin/env bash
# /app/Pagina-web/scripts/manage_codex_sudo.sh
# Script para gestionar el acceso NOPASSWD para el agente Codex

SUDOERS_FILE="/etc/sudoers.d/99-codex-bypass"
USER_NAME="pext"

apply() {
    echo "Aplicando configuración de sudo NOPASSWD para $USER_NAME..."
    echo "$USER_NAME ALL=(ALL) NOPASSWD: ALL" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chown root:root "$SUDOERS_FILE"
    sudo chmod 0440 "$SUDOERS_FILE"
    if sudo -n true 2>/dev/null; then
        echo "✅ Configuración aplicada correctamente."
    else
        echo "❌ Error al aplicar la configuración."
        exit 1
    fi
}

remove() {
    echo "Eliminando configuración de sudo NOPASSWD para $USER_NAME..."
    if [ -f "$SUDOERS_FILE" ]; then
        sudo rm "$SUDOERS_FILE"
        echo "✅ Configuración eliminada."
    else
        echo "ℹ️ El archivo $SUDOERS_FILE no existe."
    fi
}

status() {
    if [ -f "$SUDOERS_FILE" ]; then
        echo "🟢 Estado: ACTIVO (El archivo existe)"
        echo "Regla actual:"
        sudo cat "$SUDOERS_FILE"
    else
        echo "🔴 Estado: INACTIVO"
    fi
}

case "${1:-}" in
    apply) apply ;;
    remove) remove ;;
    status) status ;;
    *) echo "Uso: $0 {apply|remove|status}" ;;
esac
