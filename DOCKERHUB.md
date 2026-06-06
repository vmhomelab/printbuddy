# Printbuddy

**Self-hosted print archive and management system for Bambu Lab, Klipper, and Prusa 3D printers.**

No cloud dependency. Complete privacy. Full control.

[![GitHub](https://img.shields.io/github/stars/vmhomelab/Printbuddy?style=flat-square&label=GitHub)](https://github.com/vmhomelab/Printbuddy)
[![License](https://img.shields.io/github/license/vmhomelab/Printbuddy?style=flat-square)](https://github.com/vmhomelab/Printbuddy/blob/main/LICENSE)

## Quick Start

```bash
mkdir printbuddy && cd printbuddy
curl -fsSLO https://raw.githubusercontent.com/vmhomelab/Printbuddy/main/docker-compose.yml
docker compose up -d
```

Open **http://localhost:8000** and add your printer.

> **Requirements:** Printer on the same local network. Bambu Lab printers require Developer Mode enabled for LAN access.

## Supported Architectures

| Architecture | Tag |
|---|---|
| x86-64 (Intel/AMD) | `amd64` |
| arm64 (Raspberry Pi 4/5) | `arm64` |

## Features

- **Real-Time Monitoring** — Live printer status, camera streaming, HMS error tracking, resizable multi-printer dashboard
- **Print Archive** — Automatic 3MF archiving with metadata, interactive 3D model viewer, photo attachments, failure analysis, side-by-side comparison
- **Print Scheduling** — Drag-and-drop queue, multi-printer assignment by model or location, time-based scheduling, re-print with AMS mapping
- **Smart Automation** — Smart plug control via Tasmota, Home Assistant, and MQTT; auto power-on/off; energy monitoring; maintenance reminders
- **Proxy / Virtual Printer Modes** — Send jobs from supported slicers into archive, review, queue, or proxy workflows
- **Notifications** — WhatsApp, Telegram, Discord, Email, Pushover, and ntfy with customizable templates and quiet hours
- **Projects** — Group related prints, track parts and plates, bill of materials, cost tracking, export as ZIP/JSON
- **File Manager** — Upload and organize sliced files, folder structure, print directly to any printer
- **Integrations** — Spoolman filament sync, MQTT publishing, Prometheus metrics, Bambu Cloud profiles, REST API, Home Assistant
- **Security** — Optional authentication with group-based permissions, JWT tokens, and API key support

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TZ` | `UTC` | Timezone, e.g. `Europe/Berlin` |
| `PORT` | `8000` | Web UI port |
| `PUID` | `1000` | User ID for file permissions |
| `PGID` | `1000` | Group ID for file permissions |
| `DEBUG` | `false` | Enable debug logging |

## Volumes

| Path | Purpose |
|---|---|
| `/app/data` | Database, archived prints, thumbnails |
| `/app/logs` | Application logs |

## Docker Compose

```yaml
services:
  printbuddy:
    image: ghcr.io/vmhomelab/printbuddy:latest
    container_name: printbuddy
    network_mode: host
    environment:
      - TZ=Europe/Berlin
      - PUID=1000
      - PGID=1000
      - PORT=8000
    volumes:
      - printbuddy_data:/app/data
      - printbuddy_logs:/app/logs
    restart: unless-stopped

volumes:
  printbuddy_data:
  printbuddy_logs:
```

> **macOS/Windows:** Docker Desktop doesn't support `network_mode: host`. Replace it with `ports: ["8000:8000"]` and add printers manually by IP.

## Updating

```bash
docker compose pull && docker compose up -d
```

## Development Builds

Development builds are published from the `dev` branch:

```bash
docker pull ghcr.io/vmhomelab/printbuddy:dev
```

Use `latest` for stable releases and `dev` only when you explicitly want to test the current development branch.

## Supported Printers

| Family | Models | Status |
|---|---|---|
| Bambu Lab H2 | H2C, H2D, H2D Pro, H2S | Tested |
| Bambu Lab X1 | X1 Carbon, X1E | Tested |
| Bambu Lab P1 | P1P, P1S | Compatible |
| Bambu Lab P2 | P2S | Compatible |
| Bambu Lab A1 | A1, A1 Mini | Compatible |
| Klipper / Moonraker | Fluidd, Mainsail, Moonraker-compatible printers | Supported |
| PrusaLink | PrusaLink-compatible printers | Supported |

## Links

- **GitHub:** [github.com/vmhomelab/Printbuddy](https://github.com/vmhomelab/Printbuddy)
- **Container image:** [ghcr.io/vmhomelab/printbuddy](https://github.com/vmhomelab/Printbuddy/pkgs/container/printbuddy)
- **Issues:** [GitHub Issues](https://github.com/vmhomelab/Printbuddy/issues)

## License

MIT License - see [LICENSE](https://github.com/vmhomelab/Printbuddy/blob/main/LICENSE) for details.
