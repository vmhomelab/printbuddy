# Printbuddy

Printbuddy is a fork of [Bambuddy](https://github.com/vmhomelab/printbuddy-ha-addon) with a broader goal: one modern self-hosted dashboard for **Bambu Lab**, **Klipper**, and **Prusa** printers.

> [!WARNING]
> **This repository is still under active development**
>
> This project is not ready for public use yet. Features may be incomplete, unstable, or subject to breaking changes without notice.
>
> Please do not use this repository in production environments at this stage.

> Current state: initial fork setup on `dev`. Bambu Lab support is inherited from Bambuddy. Klipper and Mainsail support is being added through a provider architecture backed by Moonraker.

## Repository workflow

Development happens on `dev` first.

1. Commit and push work to `dev`.
2. Test from `dev`.
3. Merge approved changes into `main`.
4. Release from `main`.


## Docker quick start

For the first test deployment, build directly from the `dev` branch:

```bash
git clone -b dev https://github.com/vmhomelab/Printbuddy.git
cd Printbuddy
docker compose up -d --build
```

Open:

```text
http://<docker-host-ip>:8000
```

On Linux the compose file uses `network_mode: host` so Bambu discovery and camera/virtual-printer ports work correctly. On Docker Desktop, remove `network_mode: host` and enable the commented `ports:` block instead.

Planned image tags once GHCR publishing is enabled:

```text
ghcr.io/vmhomelab/printbuddy:dev
ghcr.io/vmhomelab/printbuddy:latest
```

## Printer provider direction

Printbuddy introduces a provider boundary so printer-specific integrations can evolve without hard-coding every workflow to Bambu MQTT/FTP.

Planned providers:

- `bambu` — existing Bambuddy/Bambu Lab MQTT + FTP support.
- `klipper` — Moonraker-backed Klipper printer status and control.
- `mainsail` — Mainsail UI environments using the same Moonraker API surface.

The first implementation step adds provider metadata to printers and a Moonraker client scaffold. Bambu remains the default provider for backwards compatibility.

## Development setup

Backend:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt -r requirements-dev.txt
ruff check backend/
ruff format --check backend/
cd backend && ../venv/bin/python -m pytest tests/ --tb=short
```

Frontend:

```bash
cd frontend
npm ci
npm run lint
npx tsc --noEmit
npm run test:run
npm run build
```

## Attribution and license

Printbuddy is forked from Bambuddy and keeps the upstream AGPL-3.0 license. Historical upstream documentation and changelog entries may still reference Bambuddy while the fork is being rebranded.
