#!/usr/bin/env bash
# Nightly MongoDB backup for LexSign. Installed by setup-server.sh as /usr/local/bin/lexsign-backup
# and run from /etc/cron.d/lexsign-backup. Keeps the last 14 archives.
#
#   Restore one:   mongorestore --uri="$MONGO_URL" --drop --gzip --archive=/var/backups/lexsign/lexsign-YYYY-MM-DD_HHMM.gz
set -euo pipefail

BACKUP_DIR=/var/backups/lexsign
KEEP_DAYS=14

# shellcheck disable=SC1091
source /etc/lexsign.env
mkdir -p "$BACKUP_DIR"

STAMP="$(date +%F_%H%M)"
OUT="$BACKUP_DIR/lexsign-$STAMP.gz"
mongodump --uri="$MONGO_URL" --gzip --archive="$OUT" --quiet
chmod 600 "$OUT"

find "$BACKUP_DIR" -name 'lexsign-*.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date '+%F %T') backup written: $OUT ($(du -h "$OUT" | cut -f1))"
