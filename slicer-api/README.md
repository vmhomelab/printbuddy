# Slicer-API sidecar (optional)

Self-contained Docker Compose stack that runs HTTP wrappers around the
OrcaSlicer and/or Bambu Studio CLI. Printbuddy's **Slice** action calls
these to slice models server-side, no desktop slicer required.

For a step-by-step user guide, including what to pick in the Slice dialog
for each printer, see [docs/slicer-sidecar.md](../docs/slicer-sidecar.md).

The same sidecars can also run from PrintBuddy's main `docker-compose.yml`
(commented-out `bambu-studio-api` / `orca-slicer-api` services). This
folder is for running them as a separate stack or building them yourself.

This folder is **optional**. Printbuddy works without it — Slice falls back
to opening the model in the user's local desktop slicer via URI scheme.
Enable the API path by:

1. Starting one or both services here
2. **Settings → Slicer → Use Slicer API** = on
3. Set **Slicer sidecar URL** for whichever slicer you've started

## Quick start

```bash
cd slicer-api/
cp .env.example .env       # edit ports if you like

# OrcaSlicer only (default profile):
docker compose up -d
curl http://localhost:3003/health

# Both slicers:
docker compose --profile bambu up -d
curl http://localhost:3001/health   # bambu-studio-api
curl http://localhost:3003/health   # orca-slicer-api
```

`up` pulls the prebuilt images from Docker Hub
(`docker.io/vmhomelabde/printbuddy-bambu-studio-api` and
`docker.io/vmhomelabde/printbuddy-orca-slicer-api`, tagged
`<slicer version>-<sidecar revision>`). The tags are set by
`BAMBU_STUDIO_API_IMAGE` / `ORCA_SLICER_API_IMAGE` in `.env`.

To build the images yourself (other slicer versions, own sidecar changes),
give them local names in `.env` (e.g. `printbuddy-bambu-studio-api:local`)
so the published tags are not overwritten, then:

```bash
docker compose --profile bambu build --no-cache --pull
docker compose --profile bambu up -d
```

A build downloads the slicer's AppImage (~110 MB OrcaSlicer, ~220 MB
Bambu Studio) and takes 3–8 minutes per service.

### Which slicer for which printer

| Sidecar | Default version | Notes |
|---|---|---|
| `bambu-studio-api` | Bambu Studio 02.08.02.61 | Recommended for Bambu Lab printers. Required for newer models such as the **X2D** (Bambu Studio ≥ 02.05.03). AMD64 only. |
| `orca-slicer-api` | OrcaSlicer 2.3.2 | Covers many non-Bambu printers. OrcaSlicer 2.3.2 has no X2D profiles. |

PrintBuddy slices with the sidecar of the **Preferred Slicer** setting, so
start the matching service. Plain `docker compose up -d` starts **only**
OrcaSlicer; Bambu Studio needs `--profile bambu`.

**Snapmaker U1:** keep the Compose default on stable `2.3.2`. For U1 vendor
profiles and painted multi-colour projects, opt in with `ORCA_VERSION=2.4.0`
or newer in `.env` — `2.5.0-beta` includes upstream
[#15998](https://github.com/OrcaSlicer/OrcaSlicer/pull/15998) (painted 3MF +
multi `--load-filaments` no longer SIGSEGVs — was #12426). Snapmaker's Orca
fork already handled these files for U1; vanilla Orca now sizes painted
segmentation from `filament_diameter` the same way the rest of the slicer
does. 2.3.x lacks U1 machine profiles entirely.

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
- **Sidecar URL**: leave blank for the defaults (`http://localhost:3003` for
  OrcaSlicer, `http://localhost:3001` for Bambu Studio), which match the
  loopback ports in this Compose file when Printbuddy uses host networking.
  For bridged Docker setups, put both stacks on a shared network and use
  `http://orca-slicer-api:3000` / `http://bambu-studio-api:3000` — see
  “Network and security” in `docs/slicer-sidecar.md`.

Leaving the URL field blank uses the `SLICER_API_URL` /
`BAMBU_STUDIO_API_URL` environment defaults from Printbuddy's config.

## Where the source lives

Both images build from the immutable Git revision configured by
`SLICER_API_BUILD_CONTEXT` in `.env` (source:
[vmhomelab/orca-slicer-api](https://github.com/vmhomelab/orca-slicer-api),
AGPL-3.0). The published images are built from exactly that revision by
`.github/workflows/docker-publish-slicer.yml`, and carry it in their
`org.opencontainers.image.revision` label.

To move to a new sidecar revision or slicer version, change
`SLICER_API_BUILD_CONTEXT` / `BAMBU_VERSION` / `ORCA_VERSION` in
`.env.example`, then run `python scripts/slicer_images.py` to get the new
image tags and update `BAMBU_STUDIO_API_IMAGE` / `ORCA_SLICER_API_IMAGE`
and the defaults in this `docker-compose.yml`.
`python scripts/slicer_images.py --check` (also run in CI) fails until all
references match. Pushing the change to `dev` or `main` publishes the new
images and moves the `dev` / `latest` tags, which the main
`docker-compose.yml` uses.

The maintained fork carries the Printbuddy-specific inheritance resolver,
stock-profile listing, bundle API, and safe slice-progress contract. Once
those land upstream, this Compose file can be flipped to a versioned upstream
image or immutable upstream revision.

## Updating

The images default to the moving `:latest` tag (`:dev` for PrintBuddy's dev
branch), so after a PrintBuddy update just pull and restart:

```bash
docker compose --profile bambu pull
docker compose --profile bambu up -d
```

PrintBuddy's **Test slicer connection** warns when the sidecar is not the
revision this PrintBuddy version expects. If your `.env` still pins a fixed tag
(e.g. `…:2.3.2-9ff0c6e`), switch it to `:latest` once.

Self-built images: rebuild with `docker compose --profile bambu build --no-cache --pull`.
`--no-cache` is needed because the Dockerfile downloads the AppImage
inline; Docker won't re-fetch it on a version change otherwise.

## Troubleshooting

- **`failed to read dockerfile: open Dockerfile.bambu-studio`** — your
  `.env` still points `SLICER_API_BUILD_CONTEXT` at an old sidecar revision
  without the Bambu Studio image. Copy the value from `.env.example`.
- **Bambu Studio build fails with "No Ubuntu 22.04 AppImage found"** — the
  version does not exist, or the GitHub API lookup was rate-limited. Set
  `BAMBU_APPIMAGE_URL` in `.env` to the `BambuStudio_ubuntu22.04-…AppImage`
  asset URL from the Bambu Studio release page.
- **`Filament profile "… @BBL X2D" is not compatible with printer "Bambu Lab X2D 0.4 nozzle"`**
  — for the X2D, Bambu Studio names its 0.4 mm filament profiles with an
  explicit suffix (`… @BBL X2D 0.4 nozzle`); the variants without a suffix
  are for the 0.6/0.8 mm nozzles.
- **`Unable to resolve inherited … profile: parent "…" was not found`** —
  the running slicer does not ship that stock profile, typically a printer
  that is newer than the slicer version. Use Bambu Studio or raise the
  version in `.env`.

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
