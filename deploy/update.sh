#!/usr/bin/env bash
# Deploy the latest code from git. Run as root on the server:  bash /home/lexsign/app/deploy/update.sh
set -euo pipefail
APP_DIR=/home/lexsign/app

echo "==> backup before update"
/usr/local/bin/lexsign-backup

echo "==> pull latest code"
sudo -u lexsign git -C "$APP_DIR" pull --ff-only
sudo -u lexsign "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> restart"
install -m 644 "$APP_DIR/deploy/lexsign.service" /etc/systemd/system/lexsign.service
systemctl daemon-reload
systemctl restart lexsign
sleep 2
systemctl --no-pager --lines=3 status lexsign | sed -n '1,8p'
curl -s -o /dev/null -w "API check: HTTP %{http_code}\n" http://127.0.0.1:8000/api/benches
