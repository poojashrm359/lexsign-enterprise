#!/usr/bin/env bash
# =============================================================================
#  LexSign one-time server setup for a fresh Ubuntu 24.04 DigitalOcean Droplet
#  (minimum setup: app + MongoDB on the same server, nightly backups)
#
#  Run as root on the droplet:
#     bash setup-server.sh <git-repo-url> <domain>
#  Example:
#     bash setup-server.sh https://github.com/YOUR_USER/lexsign-enterprise.git court.example.in
#
#  Safe to re-run: every step checks whether it has already been done.
# =============================================================================
set -euo pipefail

REPO_URL="${1:-}"
DOMAIN="${2:-}"
if [[ -z "$REPO_URL" || -z "$DOMAIN" ]]; then
    echo "usage: bash setup-server.sh <git-repo-url> <domain>"
    exit 1
fi

APP_USER=lexsign
APP_DIR=/home/$APP_USER/app
ENV_FILE=/etc/lexsign.env
DB_NAME=consumer_court_db
DB_USER=lexsign
BACKUP_DIR=/var/backups/lexsign

log() { echo; echo "==> $*"; }

# -----------------------------------------------------------------------------
log "1/9  System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y python3 python3-venv python3-pip nginx git certbot python3-certbot-nginx ufw gnupg curl

# -----------------------------------------------------------------------------
log "2/9  Swap file (a 1 GB droplet needs it for pip installs and MongoDB)"
if ! swapon --show | grep -q '/swapfile'; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -w vm.swappiness=10 >/dev/null
    grep -q 'vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

# -----------------------------------------------------------------------------
log "3/9  Firewall: SSH + HTTP/HTTPS only (MongoDB stays on localhost)"
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null

# -----------------------------------------------------------------------------
log "4/9  MongoDB 8.0 Community (official repository)"
if ! command -v mongod >/dev/null; then
    curl -fsSL https://www.mongodb.com/static/pgp/server-8.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-8.0.gpg
    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" \
        > /etc/apt/sources.list.d/mongodb-org-8.0.list
    apt-get update -y
    apt-get install -y mongodb-org
fi
systemctl enable --now mongod
sleep 3

# Create the application database user once, then turn authentication on.
if [[ ! -f "$ENV_FILE" ]]; then
    DB_PASS="$(openssl rand -hex 24)"
    mongosh --quiet --eval "
        db.getSiblingDB('admin').createUser({
            user: '$DB_USER', pwd: '$DB_PASS',
            roles: [ { role: 'readWrite', db: '$DB_NAME' }, { role: 'backup', db: 'admin' } ]
        })"
    cat > "$ENV_FILE" <<EOF
MONGO_URL=mongodb://$DB_USER:$DB_PASS@127.0.0.1:27017/$DB_NAME?authSource=admin
EOF
    chmod 600 "$ENV_FILE"
    echo "    database user created, connection string written to $ENV_FILE"
fi

if ! grep -q 'authorization: enabled' /etc/mongod.conf; then
    # Keep MongoDB on localhost and require a login
    if grep -q '^security:' /etc/mongod.conf; then
        sed -i 's/^security:.*/security:\n  authorization: enabled/' /etc/mongod.conf
    else
        printf '\nsecurity:\n  authorization: enabled\n' >> /etc/mongod.conf
    fi
    systemctl restart mongod
fi

# -----------------------------------------------------------------------------
log "5/9  Application user and code"
id -u $APP_USER >/dev/null 2>&1 || adduser --disabled-password --gecos "" $APP_USER
if [[ ! -d "$APP_DIR/.git" ]]; then
    sudo -u $APP_USER git clone "$REPO_URL" "$APP_DIR"
else
    sudo -u $APP_USER git -C "$APP_DIR" pull --ff-only
fi
sudo -u $APP_USER bash -c "
    cd '$APP_DIR'
    [[ -d .venv ]] || python3 -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -r requirements.txt
"

# -----------------------------------------------------------------------------
log "6/9  systemd service"
install -m 644 "$APP_DIR/deploy/lexsign.service" /etc/systemd/system/lexsign.service
systemctl daemon-reload
systemctl enable --now lexsign
systemctl restart lexsign

# -----------------------------------------------------------------------------
log "7/9  Nginx reverse proxy for $DOMAIN"
sed "s/__DOMAIN__/$DOMAIN/g" "$APP_DIR/deploy/nginx-lexsign.conf" > /etc/nginx/sites-available/lexsign
ln -sf /etc/nginx/sites-available/lexsign /etc/nginx/sites-enabled/lexsign
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# -----------------------------------------------------------------------------
log "8/9  Nightly MongoDB backup (02:30, kept 14 days) in $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
install -m 755 "$APP_DIR/deploy/backup-mongo.sh" /usr/local/bin/lexsign-backup
cat > /etc/cron.d/lexsign-backup <<'EOF'
30 2 * * * root /usr/local/bin/lexsign-backup >> /var/log/lexsign-backup.log 2>&1
EOF
/usr/local/bin/lexsign-backup && echo "    first backup done"

# -----------------------------------------------------------------------------
log "9/9  Status"
sleep 2
systemctl --no-pager --lines=5 status lexsign | sed -n '1,12p'
curl -s -o /dev/null -w "    local API check: HTTP %{http_code}\n" http://127.0.0.1:8000/api/benches

cat <<EOF

=============================================================================
 Setup finished.

 Next, once the DNS A record for $DOMAIN points to this server, get HTTPS:

     certbot --nginx -d $DOMAIN --redirect -m you@example.com --agree-tos -n

 Then open https://$DOMAIN and log in. Immediately create a new admin
 account with a strong password and delete the default admin/reader users.
=============================================================================
EOF
