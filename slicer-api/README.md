# Slicer-API sidecar (optional)

Self-contained Docker Compose stack that runs HTTP wrappers around the
OrcaSlicer and/or Bambu Studio CLI. Printbuddy's **Slice** action calls
these to slice models server-side, no desktop slicer required.

This folder is **optional**. Printbuddy works without it — Slice falls back
to opening the model in the user's local desktop slicer via URI scheme.
Enable the API path by:

1. Starting one or both services here
2. **Settings → Slicer → Use Slicer API** = on
3. Set **Slicer sidecar URL** for whichever slicer you've started

## Quick start

```bash
cd slicer-api/
cp .env.example .env       # edit ports / versions if you like

# OrcaSlicer only (default profile):
docker compose up -d
curl http://localhost:3003/health

# Both slicers:
docker compose --profile bambu up -d
curl http://localhost:3001/health   # bambu-studio-api
curl http://localhost:3003/health   # orca-slicer-api
```

First build downloads the slicer's AppImage (~110 MB OrcaSlicer, ~220 MB
BambuStudio) and compiles the Node wrapper. Takes 3–8 minutes per service.
Subsequent runs reuse the local image — instant start.

If a separate x86_64 box isn't an option, the amd64 images can be run on
an ARM64 host under emulation — experimental, roughly 3-6x slower than
native, and a stopgap until native ARM64 images ship. See
[Experimental setup for ARM64](#experimental-setup-for-arm64) below.

## Ports

| Service | Default host port | Why this port |
|---|---|---|
| `orca-slicer-api` | **3003** | Printbuddy's virtual-printer feature reserves 3000 and 3002 |
| `bambu-studio-api` | **3001** | First free port in that range |

Override via `ORCA_API_PORT` / `BAMBU_API_PORT` in `.env`.

## Printbuddy wiring

In the Printbuddy UI: **Settings → Slicer**:

- **Preferred Slicer**: pick OrcaSlicer or Bambu Studio.
- **Use Slicer API**: turn on.
- **Sidecar URL**: paste the full URL of the chosen slicer's sidecar.
  Default values match the Compose defaults:
  - OrcaSlicer: `http://localhost:3003`
  - Bambu Studio: `http://localhost:3001`

Leaving the URL field blank uses the `SLICER_API_URL` /
`BAMBU_STUDIO_API_URL` environment defaults from Printbuddy's config.

## Where the source lives

Both images build from the git context configured by
`SLICER_API_BUILD_CONTEXT` in `.env`. The Compose file uses Docker's git build
context, so you don't need to clone the sidecar manually — Docker pulls the repo
at build time.

The fork patches AFKFelix's upstream wrapper with the `inherits:`
chain resolver, `from: "User"` → `"system"` rewrite, `# ` clone-prefix
strip, and sentinel-value strip — all empirically required to slice
real GUI exports without segfaulting the CLI. Once those land
upstream, this Compose file can be flipped to pull from
`ghcr.io/afkfelix/orca-slicer-api` directly.

## Updating

Bump the versions in `.env`, then rebuild.

OrcaSlicer only (the default):

```bash
docker compose build --no-cache
docker compose up -d
```

With the Bambu Studio sidecar — the profile flag belongs on **both**
commands:

```bash
docker compose --profile bambu build --no-cache
docker compose --profile bambu up -d
```

`--no-cache` is needed because the Dockerfile downloads the AppImage
inline; Docker won't re-fetch it on a version change otherwise.

`bambu-studio-api` sits behind `profiles: [bambu]`, and a bare
`docker compose build` skips profile-gated services silently: it reports
success, `restart: unless-stopped` keeps the old container serving, and
you stay on the old image no matter how often you repeat it. To update
one sidecar only, name it — `docker compose build --no-cache
bambu-studio-api && docker compose up -d bambu-studio-api` — which
enables its profile implicitly.

To roll back to a previous slicer release, set `ORCA_VERSION` /
`BAMBU_VERSION` back in `.env` and re-run the commands above.

## Experimental setup for ARM64

Runs the `linux/amd64` images on an ARM64 host under QEMU emulation, via
the `docker-compose.arm64.yml` override in this folder. Expect roughly
3-6x slower slicing than native, worsening with model complexity. This is
a stopgap until native ARM64 images ship, not a replacement for running
the sidecar on an x86_64 box — if you have one, use it.

**Set up QEMU binfmt on the host first**, or the containers fail with
`exec format error`. On Debian/Ubuntu that is `qemu-user-static` plus
`binfmt-support`; Docker Desktop on Apple Silicon already has it. The
per-distribution commands are in the
[Printbuddy wiki](https://wiki.printbuddy.tech) — do that before
the steps below.

### Quick start for ARM64

```bash
cd slicer-api/
cp .env.example .env       # edit ports if you like

# Make every later `docker compose` command pick up the ARM64 override:
echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.arm64.yml' >> .env

# OrcaSlicer only (default profile):
docker compose up -d
curl http://localhost:3003/health

# Both slicers:
docker compose --profile bambu up -d
curl http://localhost:3001/health   # bambu-studio-api
curl http://localhost:3003/health   # orca-slicer-api
```

That `COMPOSE_FILE` line is what makes the rest of this README work
unchanged on ARM64 — **Updating** included. Without it every command has
to name both files (`docker compose -f docker-compose.yml -f
docker-compose.arm64.yml …`), and the first bare `docker compose pull` or
`up -d` drops the override: on a host with no amd64 emulation registered
for that image you get a manifest error, and once native ARM64 images
exist you would silently switch between them and back.

## Troubleshooting

- **`address already in use` on port 3000 or 3002** — Printbuddy's
  virtual-printer feature owns those. Don't change `ORCA_API_PORT` to
  3000 or 3002.
- **`/health` reports `version: "unknown"`** — cosmetic. The bundled
  binary works; the wrapper just couldn't parse the version string from
  the slicer's `--help` output (BambuStudio's format differs from
  OrcaSlicer's, which is what the wrapper was tuned for).
- **Slice returns "Failed to slice the model"** — the wrapper hides the
  CLI's stderr. Re-run inside the container to see it:

  ```bash
  docker exec orca-slicer-api /app/squashfs-root/AppRun --slice 1 \
      --load-settings "/path/to/printer.json;/path/to/preset.json" \
      --load-filaments /path/to/filament.json \
      --allow-newer-file --outputdir /tmp/out /path/to/model.3mf
  ```
