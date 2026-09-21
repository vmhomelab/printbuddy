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

## Ports

| Service | Default host port | Why this port |
|---|---|---|
| `orca-slicer-api` | **3003** | Printbuddy's virtual-printer feature reserves 3000 and 3002 |
| `bambu-studio-api` | **3001** | First free port in that range |

Override via `ORCA_API_PORT` / `BAMBU_API_PORT` in `.env`.

## Network exposure

The Compose stack binds both sidecar ports to **`127.0.0.1` only**. This is
intentional: the API has no authentication and must be consumed by the local
Printbuddy host-network container, not exposed to the LAN or the Internet.

If Printbuddy and the sidecar run on separate hosts, place them on a private
network and add authentication/reverse-proxy controls before exposing either
port; do not simply change the host binding to `0.0.0.0`.

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

Both images build from the immutable Git revision configured by
`SLICER_API_BUILD_CONTEXT` in `.env`. Docker pulls that exact source revision,
so deployments are reproducible. Update the revision only after the fork
change has been tested and published; do not point production at a moving
branch name.

The maintained fork carries the Printbuddy-specific inheritance resolver,
stock-profile listing, bundle API, and safe slice-progress contract. Once
those land upstream, this Compose file can be flipped to a versioned upstream
image or immutable upstream revision.

## Updating

Bump the versions in `.env`, then:

```bash
docker compose --profile bambu build --no-cache
docker compose --profile bambu up -d
```

`--no-cache` is needed because the Dockerfile downloads the AppImage
inline; Docker won't re-fetch it on a version change otherwise.

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
