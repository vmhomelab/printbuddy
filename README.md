<p align="center">
  <img width="2172" height="724" alt="ChatGPT Image 22  Juli 2026, 11_21_37" src="https://github.com/user-attachments/assets/559f049b-b5c6-43c6-8d98-2322a21e83b8" />
</p>

<p align="center">
  <a href="https://wiki.printbuddy.tech">Wiki</a>
  ·
  <a href="https://github.com/vmhomelab/Printbuddy/releases/latest">Latest release</a>
  ·
  <a href="https://demo.printbuddy.tech">Public demo</a>
  ·
  <a href="https://hub.docker.com/r/vmhomelabde/printbuddy">Docker Hub</a>
</p>

<p align="center">
  Demo login: <code>admin</code> / <code>printbuddy</code>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a>
  ·
  <a href="#supported-provider-families">Providers</a>
  ·
  <a href="#features">Features</a>
  ·
  <a href="#home-assistant">Home Assistant</a>
  ·
  <a href="#development">Development</a>
  ·
  <a href="#printbuddy">Printbuddy Mascot</a>
</p>

---

> [!WARNING]
> **Printbuddy is under active development.**
>
> Use it for homelab testing, development, and controlled deployments. Features and provider-specific workflows are moving quickly and may change between releases.

---

## What is Printbuddy?

Printbuddy is a self-hosted 3D-printer management application for users who want one place to monitor, organize, and automate their printers without depending on a vendor cloud dashboard.

The app is built around provider-specific printer integrations. Bambu Lab, Moonraker/Klipper-style printers, PrusaLink, Prusa Connect, and Elegoo SDCP devices do not behave the same way, so Printbuddy keeps those transports separated behind a provider boundary instead of forcing everything through one Bambu-shaped workflow.

Current app version in `main`: **0.2.5.0**.

---

## Quick start

### Docker Compose on Linux

The default `docker-compose.yml` is optimized for Linux hosts and uses host networking so printer discovery, cameras, MQTT/FTP, and virtual-printer ports can work without container NAT surprises.

```bash
mkdir printbuddy && cd printbuddy
curl -fsSLO https://raw.githubusercontent.com/vmhomelab/Printbuddy/main/docker-compose.yml
docker compose up -d
```

Open Printbuddy:

```text
http://<docker-host-ip>:8000
```

Useful checks:

```bash
docker compose ps
docker compose logs -f printbuddy
curl http://127.0.0.1:8000/health
```

### Docker Desktop / bridge networking

Docker Desktop on Windows and macOS does not support Linux-style `network_mode: host`.

For Docker Desktop:

1. Comment out `network_mode: host` in `docker-compose.yml`.
2. Uncomment the `ports:` block.
3. Add printers manually by IP address; automatic discovery may not cross Docker Desktop networking.
4. Set `VIRTUAL_PRINTER_PASV_ADDRESS=<docker-host-ip>` if you use virtual-printer FTP passive mode.

### Images

Stable releases are published to Docker Hub:

```bash
docker pull docker.io/vmhomelabde/printbuddy:latest
```

Development builds are published from `dev`:

```bash
docker pull docker.io/vmhomelabde/printbuddy:dev
```

Use `latest` unless you intentionally want to test current development work.

---

## Supported provider families

| Provider key | Printer family | Current scope |
|---|---|---|
| `bambu` | Bambu Lab LAN printers | Existing Bambu MQTT/FTP support, AMS-aware workflows, discovery, cameras, virtual-printer/proxy workflows |
| `klipper` / `mainsail` / `fluidd` | Moonraker-backed Klipper printers | Status, temperatures, files, controls, and provider-aware print/file workflows through Moonraker |
| `prusalink` | Local PrusaLink / CORE One-style printers | HTTP/Digest/API-key detection, status, files, upload/start, and metadata-aware archive/spool accounting |
| `prusaconnect` | Prusa Connect cloud/mobile API | Cloud status/control integration boundary; file workflows remain intentionally limited until implemented safely |
| `elegoo_sdcp` | Elegoo Centauri Carbon / SDCP devices | LAN SDCP status and camera/start-option work, with provider-specific safeguards |

Bambu remains the default provider for older printer records so existing installations keep working during migration.

---

## Features

- Multi-printer dashboard with provider-aware status normalization.
- Real-time monitoring for supported printer families (including add-ons like the Panda Breath form Biqu).
- Printer file manager with provider-specific upload, list, download, delete, and print actions.
- Print archives, logs, metadata capture, usage tracking, and reprint workflows.
- Local filament inventory with Spoolman integration and non-AMS loaded-spool assignment support.
- Open Filament Database-assisted spool creation.
- Notification providers including Telegram, Discord, email, Pushover, ntfy, and other configured channels.
- Optional authentication, API keys, role/group-style permissions, and MFA support.
- Bambu virtual-printer/proxy modes for supported slicer workflows.
- Optional slicer sidecars for OrcaSlicer and Bambu Studio API workflows.
- Smart-home and automation hooks, including MQTT/Home Assistant-oriented integrations.
- Optional Docker self-update sidecar for controlled Compose-based updates.
- SQLite by default, with optional PostgreSQL through `DATABASE_URL`.

---

## Screenshots

<p align="center">
  <img width="3230" height="1335" alt="Printbuddy dashboard overview" src="https://github.com/user-attachments/assets/d0aea010-5449-4a47-a860-fd26f5a7b6d9" />
</p>

<p align="center">
  <img width="708" height="525" alt="Printbuddy file manager view" src="https://github.com/user-attachments/assets/a435ea7a-dac7-4c57-98ec-c65eec4467f5" />
  <img width="706" height="652" alt="Printbuddy printer detail view" src="https://github.com/user-attachments/assets/584f786d-7d71-416d-9878-86d45cf8f389" />
</p>

<p align="center">
  <img width="420" height="576" alt="Printbuddy mobile printer view" src="https://github.com/user-attachments/assets/730a2060-1032-46cb-bc3f-a341e8a730cb" />
</p>

<p align="center">
  <img width="960" height="874" alt="Klipper-based printer with control options" src="https://github.com/user-attachments/assets/c402bcbf-3797-4ad7-b14e-f0ade3bb92d1" />
</p>

<p align="center">
  <img width="532" height="811" alt="Panda Breath support" src="https://github.com/user-attachments/assets/7c827ed8-cc55-4dcf-acbd-e860bfb60844" />
</p>

<p align="center">
  <img width="360" height="663" alt="Printbuddy update via the UI" src="https://github.com/user-attachments/assets/7bb731b4-c1f3-46c4-a161-56ce976a66ba" />
</p>

Additional current screenshots and walkthroughs live in the [wiki](https://wiki.printbuddy.tech) and release notes.

---

## Configuration

Common environment variables from the provided Compose file:

| Variable | Default | Description |
|---|---:|---|
| `TZ` | `Europe/Berlin` | Container timezone |
| `PUID` | `1000` | Host user ID used for files written to mounted volumes |
| `PGID` | `1000` | Host group ID used for files written to mounted volumes |
| `PORT` | `8000` | Web UI/API port |
| `DATABASE_URL` | unset | Optional PostgreSQL URL; SQLite is used when unset |
| `MFA_ENCRYPTION_KEY` | auto-generated | Optional managed key for MFA secrets at rest |
| `USE_SYSTEM_TRUST_STORE` | unset | Trust mounted CA certificates for local HTTPS integrations |
| `SLICER_API_URL` | `http://localhost:3003` | Optional OrcaSlicer sidecar URL |
| `BAMBU_STUDIO_API_URL` | `http://localhost:3001` | Optional Bambu Studio sidecar URL |
| `SELF_UPDATE_ENABLED` | `false` | Enables the optional updater sidecar when configured |
| `UPDATER_URL` / `UPDATER_TOKEN` | unset | Printbuddy-to-updater sidecar connection settings |

Runtime data is stored in Docker volumes by default:

| Volume | Container path | Purpose |
|---|---|---|
| `printbuddy_data` | `/app/data` | Database, archives, backups, virtual-printer state |
| `printbuddy_logs` | `/app/logs` | Application logs |

See [`DEPLOYMENT.md`](DEPLOYMENT.md), [`UPDATING.md`](UPDATING.md), and [`docs/self-update-sidecar.md`](docs/self-update-sidecar.md) for operational details.

---

## Home Assistant

Printbuddy can be used with Home Assistant in two ways:

- **Home Assistant add-on:** runs Printbuddy directly inside Home Assistant with Ingress, persistent add-on storage, and LAN printer access through host networking. Repository: [vmhomelab/printbuddy-ha-addon](https://github.com/vmhomelab/printbuddy-ha-addon)
- **Home Assistant custom integration:** connects Home Assistant to an existing Printbuddy instance and exposes configured printers as Home Assistant devices and telemetry entities. Repository: [vmhomelab/ha-printbuddy-integration](https://github.com/vmhomelab/ha-printbuddy-integration)

Wiki pages:

- [Printbuddy Home Assistant Add-on](https://github.com/vmhomelab/printbuddy/wiki/Home-Assistant-Add-on)
- [Printbuddy Home Assistant Integration](https://github.com/vmhomelab/printbuddy/wiki/Home-Assistant-Integration)

---

## Updating

> ## Updating via the UI
>
> To use the update feature over the UI, please make sure that you edited the docker-compose.yml file accordingly. See [here](https://github.com/vmhomelab/printbuddy/blob/main/docs/self-update-sidecar.md) on what to do.

For Docker Compose deployments:

```bash
docker compose pull
docker compose up -d
```

If your Compose file is old, refresh it from `main` and compare it with your local changes before replacing it:

```bash
curl -fsSL https://raw.githubusercontent.com/vmhomelab/Printbuddy/main/docker-compose.yml \
  -o docker-compose.yml.new
```

For native installs, use the included updater when available:

```bash
sudo /opt/printbuddy/install/update.sh
```

Take a backup before major upgrades. Settings → Backup can export state from inside the app; Docker users can also back up the `printbuddy_data` volume manually.

---

## Repository workflow

Development happens on `dev` first, then tested changes are merged to `main` for stable releases.

```text
dev  -> active development and test images
main -> stable releases and latest image metadata
```

Release flow:

1. Prepare and test changes on `dev`.
2. Bump `APP_VERSION` for the release.
3. Merge approved changes into `main`.
4. Create the matching GitHub release/tag.
5. Publish and verify Docker images for the exact released commit.

---

## Development

### Backend

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt -r requirements-dev.txt

ruff check backend/
ruff format --check backend/

cd backend
../venv/bin/python -m pytest tests/ --tb=short
```

### Frontend

```bash
cd frontend
npm ci
npm run lint
npx tsc --noEmit
npm run test:run
npm run build
```

Before committing docs or code changes, run:

```bash
git diff --check
git status --short --branch
```

---

## Printbuddy

Printbuddy has its own printable mascot.

- MakerWorld: <https://makerworld.com/de/models/2894134-your-printbuddy#profileId-3234154>
- Printables: <https://www.printables.com/model/1746692-your-printbuddy>

---

## Project links

- Wiki: <https://wiki.printbuddy.tech>
- Demo: <https://demo.printbuddy.tech>
- GitHub releases: <https://github.com/vmhomelab/Printbuddy/releases>
- Docker image: <https://hub.docker.com/r/vmhomelabde/printbuddy>
- Home Assistant add-on: <https://github.com/vmhomelab/printbuddy-ha-addon>
- Home Assistant integration: <https://github.com/vmhomelab/ha-printbuddy-integration>
- Project board: <https://github.com/users/vmhomelab/projects/4/views/1>

---

## Attribution and license

Printbuddy is a modified fork of an upstream AGPL-3.0 project. The repository keeps the upstream license and history context, and Printbuddy-specific modification notices are documented in [`NOTICE-modifications.md`](NOTICE-modifications.md).

See [`LICENSE`](LICENSE) for the full AGPL-3.0 license text.

---

## Star history

<a href="https://www.star-history.com/?repos=vmhomelab%2Fprintbuddy&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=vmhomelab/printbuddy&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=vmhomelab/printbuddy&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=vmhomelab/printbuddy&type=date&legend=top-left" />
 </picture>
</a>

<p align="center">
  <strong>Printbuddy</strong><br>
  Your tiny helper for keeping the printer chaos under control.
</p>
