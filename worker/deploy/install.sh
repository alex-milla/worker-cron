#!/usr/bin/env bash
# Instalador del worker en un LXC Proxmox (Debian/Ubuntu, se ejecuta como root).
set -euo pipefail

WORKER_DIR="/opt/cron-worker"
SERVICE_USER="cronworker"

echo "== [1/4] Dependencias del sistema =="
apt-get update
apt-get install -y python3 python3-venv python3-pip

echo "== [2/4] Usuario y directorio =="
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$WORKER_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$WORKER_DIR" "$WORKER_DIR/data" "$WORKER_DIR/logs"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$WORKER_DIR"

echo "== [3/4] Entorno Python =="
python3 -m venv "$WORKER_DIR/venv"
"$WORKER_DIR/venv/bin/pip" install --upgrade pip
# Copia antes los fuentes del worker a este directorio
if [ -f "$WORKER_DIR/requirements.txt" ]; then
    "$WORKER_DIR/venv/bin/pip" install -r "$WORKER_DIR/requirements.txt"
fi

echo "== [4/4] Servicio systemd =="
if [ -f deploy/cron-worker.service ]; then
    cp deploy/cron-worker.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable cron-worker.service
    echo "Listo. Copia config.yaml y arranca con: systemctl start cron-worker"
fi
