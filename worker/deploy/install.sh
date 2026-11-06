#!/usr/bin/env bash
# Instalador del worker en un LXC Proxmox (Debian/Ubuntu, como root).
#- daemon scheduler (python -m cronworker.scheduler)
#- GUI local: gunicorn (127.0.0.1:8080) + Apache reverse proxy en :80
#Uso: bash worker/deploy/install.sh  (desde /opt/worker-cron)
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # /opt/worker-cron/worker
APP_DIR="$(dirname "$SRC_DIR")"                             # /opt/worker-cron
WORK_DIR="$SRC_DIR"
SERVICE_USER="cronworker"

echo "== [1/6] Dependencias del sistema =="
apt-get update
apt-get install -y python3 python3-venv python3-pip python3-yaml apache2

echo "== [2/6] Usuario y directorios =="
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$WORK_DIR/data" "$WORK_DIR/logs"
# El chown -R definitivo va al final (después de crear el venv): ver paso 6.

echo "== [3/6] Entorno Python =="
python3 -m venv "$WORK_DIR/venv"
"$WORK_DIR/venv/bin/pip" install --upgrade pip
"$WORK_DIR/venv/bin/pip" install -r "$WORK_DIR/requirements.txt" gunicorn

echo "== [4/6] Servicio daemon scheduler =="
cp "$SRC_DIR/deploy/cron-worker.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable cron-worker.service

echo "== [5/6] Servicio GUI (gunicorn + Apache) =="
cp "$SRC_DIR/deploy/cron-gui.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable cron-gui.service

# Apache: vhost de la GUI como reverse proxy
cp "$SRC_DIR/deploy/apache-cron-gui.conf" /etc/apache2/sites-available/cron-gui.conf
a2enmod proxy proxy_http
a2dissite 000-default 2>/dev/null || true
a2ensite cron-gui

echo "== [6/6] Arranque =="
# La GUI corre como "$SERVICE_USER" y se autoactualiza escribiendo dentro del
# árbol (código + backups) y haciendo `git pull`. Todo el repo — incluido
# .git — debe pertenecerle; si se hace `git pull` como root, los ficheros
# cambian de dueño y la actualización falla con "Permission denied".
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

systemctl restart apache2
systemctl start cron-gui || echo "cron-gui: arranque pendiente (configura config.yaml y reinicia)"
systemctl start cron-worker || echo "cron-worker: arranque pendiente (configura config.yaml y reinicia)"

echo ""
echo "Instalación completada."
echo "  - GUI local:  http://<IP-del-LXC>/   (Apache → gunicorn 127.0.0.1:8080)"
echo "  - Daemon:     systemctl status cron-worker"
echo "  - Logs:       journalctl -u cron-worker -f | journalctl -u cron-gui -f"
echo "  - Config:     $WORK_DIR/config.yaml  (base_url y api_token del hosting)"
echo "  - Actualizar: sudo -u $SERVICE_USER git -C $APP_DIR pull && systemctl restart cron-gui cron-worker"
echo "                (nunca 'git pull' como root: la GUI se autoactualiza como $SERVICE_USER)"
