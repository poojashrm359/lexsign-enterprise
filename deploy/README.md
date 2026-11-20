# LexSign production deployment – DigitalOcean minimum setup

One Ubuntu 24.04 Droplet runs everything: FastAPI (uvicorn) behind Nginx with a free
Let's Encrypt certificate, and MongoDB 8 on the same server, locked to localhost with a
password. A cron job dumps the database every night and keeps 14 days of archives.

Approximate running cost: 1 GB Droplet about ₹620 per month plus a domain. Add the
20% snapshot backup option on the Droplet if you want a full-server rollback as well.

Files in this folder:

| File | Purpose |
|---|---|
| `setup-server.sh` | One-time setup of a fresh droplet. Re-runnable. |
| `lexsign.service` | systemd unit: starts the app at boot, restarts on crash. |
| `nginx-lexsign.conf` | Nginx reverse proxy template. |
| `backup-mongo.sh` | Nightly `mongodump`, installed as `/usr/local/bin/lexsign-backup`. |
| `update.sh` | Deploy a new version: backup, `git pull`, pip install, restart. |

## 1. Buy and prepare

1. Push this repository to GitHub (private is fine; use a deploy key or HTTPS token).
2. Buy a domain, for example at GoDaddy. Decide the hostname, e.g. `court.example.in`.
3. DigitalOcean account with a card. Add your SSH public key under Settings → Security.

## 2. Create the Droplet

Create → Droplets:

- Region: **Bangalore (BLR1)**
- Image: **Ubuntu 24.04 LTS**
- Size: Basic → Regular → **1 GB / 1 vCPU** (about $6/month). 2 GB if you want headroom.
- Authentication: **SSH key**
- Hostname: `lexsign-prod`

Note the public IP. In Networking → Firewalls you may also add a cloud firewall allowing
only SSH (22), HTTP (80) and HTTPS (443). The script configures `ufw` on the server too.

## 3. Point the domain

At the domain registrar add an **A record**: name `court` (or `@`), value = droplet IP,
TTL 600. Wait 10–30 minutes. `nslookup court.example.in` should return the droplet IP.

## 4. Run the setup script

```bash
ssh root@DROPLET_IP
curl -fsSL https://raw.githubusercontent.com/YOUR_USER/lexsign-enterprise/main/deploy/setup-server.sh -o setup-server.sh
bash setup-server.sh https://github.com/YOUR_USER/lexsign-enterprise.git court.example.in
```

For a private repository, clone manually first with a token, then run the script from
`/root/app/deploy/setup-server.sh` with the same arguments; it reuses an existing clone.

The script takes about five minutes. It installs packages, adds a 1 GB swap file, enables
the firewall, installs MongoDB with authentication and a random password, clones the app
into `/home/lexsign/app`, creates the Python virtualenv, installs the systemd service and
Nginx site, takes a first backup and prints the status. The MongoDB connection string
is written to `/etc/lexsign.env` (root only) and nowhere else.

At the end it should print `local API check: HTTP 200`.

## 5. Enable HTTPS

Once DNS resolves to the droplet:

```bash
certbot --nginx -d court.example.in --redirect -m you@example.com --agree-tos -n
```

Certbot edits the Nginx site, installs the certificate and renews it automatically.
Open `https://court.example.in`. You should see the login page.

## 6. First login – do this immediately

The database is seeded with `admin / Admin@123` and `reader1..3 / Reader@123`.

1. Log in as `admin`, go to Admin Directory, create a **new admin** with a strong password.
2. Log out, log in as the new admin, delete `admin`, `reader1`, `reader2`, `reader3`.
3. Create the real reader accounts for each hall.

Until the API has token authentication, also consider the IP allow-list block in
`nginx-lexsign.conf` (commented out) so that only the court's network can reach the
admin and clerk endpoints. After editing: `nginx -t && systemctl reload nginx`.

## 7. Point the kiosk players at the server

In each player's `C:\Tools\LexSign\lexsign-kiosk.cmd` set
`SERVER_URL=https://court.example.in` and reboot the player. See `kiosk/README.md`.

## Day-to-day

| Task | Command (as root on the server) |
|---|---|
| Deploy a new version | `bash /home/lexsign/app/deploy/update.sh` |
| App logs | `journalctl -u lexsign -f` |
| Restart app | `systemctl restart lexsign` |
| Backup now | `lexsign-backup` |
| List backups | `ls -lh /var/backups/lexsign` |
| Restore a backup | `source /etc/lexsign.env && mongorestore --uri="$MONGO_URL" --drop --gzip --archive=/var/backups/lexsign/lexsign-DATE.gz` |
| Copy backups off the server | `scp root@DROPLET_IP:/var/backups/lexsign/*.gz .` (run weekly from an office PC, or enable Droplet snapshots) |
| Disk / memory | `df -h`, `free -m` |

## Troubleshooting

- **`MONGODB CONNECTION FAILED` in `journalctl -u lexsign`** – check `systemctl status mongod`
  and that `/etc/lexsign.env` exists. `mongosh "$MONGO_URL" --eval 'db.runCommand({ping:1})'`
  must succeed.
- **502 from Nginx** – the app is down: `systemctl status lexsign`, then the journal.
- **Excel upload fails with 413** – raise `client_max_body_size` in the Nginx site.
- **Certificate renewal** – `certbot renew --dry-run` must pass; it runs twice daily by timer.
- **Out of memory on a 1 GB droplet** – `free -m`; the swap file covers spikes. If MongoDB
  is regularly swapping, resize the droplet to 2 GB (no reinstall needed).

## Moving to a managed database later

Create a DigitalOcean Managed MongoDB, add the droplet as a trusted source, restore the
latest backup into it with `mongorestore`, change `MONGO_URL` in `/etc/lexsign.env`, and
`systemctl restart lexsign`. No code changes.
