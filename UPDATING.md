# Updating Printbuddy

> **Note:** The in-app **Update** button may be unreliable when upgrading from
> older releases. Use the commands below instead — they cover every supported
> install path and are safe to run repeatedly.

Pick the section that matches how Printbuddy was installed.

---

## Docker / Docker Compose

```bash
# 1. Make sure your compose file isn't pinned to an old image or old project.
#    The image line should point at the Printbuddy Docker Hub package, for example:
#      image: docker.io/vmhomelabde/printbuddy:latest
#
#    If you intentionally test the development channel, use:
#      image: docker.io/vmhomelabde/printbuddy:dev
#
#    Do not use the old upstream image name from the pre-fork project.

# 2. Pull and restart
docker compose pull
docker compose up -d
```

**If your `docker-compose.yml` is old or still references the pre-fork project,** refresh it
from the Printbuddy repository. Recent compose files use the `printbuddy` service
name, `docker.io/vmhomelabde/printbuddy` image, Printbuddy data/log volumes,
`cap_add: NET_BIND_SERVICE`, virtual-printer ports, and the optional Postgres
block.

```bash
curl -fsSL https://raw.githubusercontent.com/vmhomelab/Printbuddy/main/docker-compose.yml \
  -o docker-compose.yml.new

# Diff against yours, merge by hand, then:
docker compose up -d
```

For the dev/test channel, replace `main` with `dev` in the raw URL or change the
image tag to `docker.io/vmhomelabde/printbuddy:dev` after downloading.

---

## Native install (`install.sh` or manual `git clone`)

Both paths produce a git working tree at the install directory, so the update is
the same. Preferred:

```bash
sudo /opt/printbuddy/install/update.sh
```

`update.sh` stops the service, snapshots the database via the built-in backup
API, fast-forwards to the configured upstream branch, installs Python deps,
rebuilds the frontend, and restarts the service. It rolls back automatically if
any step fails.

### Manual equivalent

If you'd rather run the steps yourself:

```bash
cd /opt/printbuddy
sudo systemctl stop printbuddy
sudo -u printbuddy git fetch origin
sudo -u printbuddy git reset --hard origin/main
sudo -u printbuddy venv/bin/pip install -r requirements.txt
sudo systemctl start printbuddy
```

Replace `/opt/printbuddy` with your install path if different. Database schema
migrations run automatically on startup — no Alembic step is required.

---

## Installed from a GitHub ZIP or tarball download

These installs have no `.git` directory, so neither `update.sh` nor a plain
`git pull` will work. Reinstall cleanly:

```bash
# 1. Back up your stateful data
sudo systemctl stop printbuddy
sudo tar czf ~/printbuddy-backup.tgz -C /opt/printbuddy \
  data printbuddy.db printbuddy.db-shm printbuddy.db-wal \
  virtual_printer archive projects icons .env 2>/dev/null || true

# 2. Remove the old install and reinstall via install.sh
sudo rm -rf /opt/printbuddy
curl -fsSL https://raw.githubusercontent.com/vmhomelab/Printbuddy/main/install/install.sh \
  -o /tmp/install.sh && sudo bash /tmp/install.sh --path /opt/printbuddy

# 3. Restore your data
sudo systemctl stop printbuddy
sudo tar xzf ~/printbuddy-backup.tgz -C /opt/printbuddy
sudo systemctl start printbuddy
```

---

## Before you upgrade

Take a backup. Settings → Backup → **Create Backup** downloads a ZIP containing
the database and all stateful directories. Any bare-metal update via `update.sh`
does this automatically; Docker and manual upgrades do not.
