# Integrated slicer (slicer sidecar)

PrintBuddy can slice models itself: you pick printer, process and filament
profiles in the **Slice** dialog, and PrintBuddy produces a printable
`.gcode.3mf` without a desktop slicer. The actual slicing runs in a small
companion container, the **slicer sidecar**, which wraps the command-line
version of Bambu Studio or OrcaSlicer.

This guide covers:

1. [Setting up the sidecar](#1-set-up-the-sidecar)
2. [Connecting PrintBuddy](#2-connect-printbuddy)
3. [Providing profiles](#3-provide-profiles)
4. [Using the Slice dialog](#4-use-the-slice-dialog)
5. [Printer-specific notes](#5-printer-specific-notes)
6. [Updating](#6-update-the-sidecar)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Set up the sidecar

### Requirements

- Docker with Docker Compose on the **same host** as PrintBuddy.
- PrintBuddy running with `network_mode: host` (the default in PrintBuddy's
  `docker-compose.yml`). The sidecar listens on `127.0.0.1` only, so
  PrintBuddy reaches it via `localhost`. See
  [Network and security](#network-and-security) if your setup differs.
- An AMD64 (x86-64) host for the Bambu Studio sidecar. Bambu Lab publishes no
  ARM64 Linux build. The OrcaSlicer sidecar also runs on ARM64.
- About 2 GB of disk space per sidecar image.

### Choose the slicer

| Sidecar | Port | Image | Use it for |
|---|---|---|---|
| `bambu-studio-api` | 3001 | `docker.io/vmhomelabde/printbuddy-bambu-studio-api` (Bambu Studio 02.08.02.61, AMD64) | **Bambu Lab printers.** Required for newer models such as the **X2D**. |
| `orca-slicer-api` | 3003 | `docker.io/vmhomelabde/printbuddy-orca-slicer-api` (OrcaSlicer 2.3.2, AMD64 and ARM64) | Non-Bambu printers (Prusa, Voron, Creality, …) and older Bambu models. |

PrintBuddy always slices with the sidecar that matches the **Preferred
Slicer** setting. You can run both and switch in the settings.

> OrcaSlicer 2.3.2 does not know the X2D and has known problems with many
> Bambu-authored 3MF files. Use Bambu Studio for Bambu Lab printers.

The image tags have the form `<slicer version>-<sidecar revision>`, for
example `02.08.02.61-cb44369`. Each PrintBuddy release references the exact
tag it was tested with.

### Option A: add the sidecar to PrintBuddy's Compose file (recommended)

PrintBuddy's `docker-compose.yml` contains commented-out `bambu-studio-api`
and `orca-slicer-api` services, next to the optional updater. Uncomment the
service for your slicer (or both):

```yaml
  bambu-studio-api:
    image: docker.io/vmhomelabde/printbuddy-bambu-studio-api:02.08.02.61-cb44369
    container_name: bambu-studio-api
    restart: unless-stopped
    ports:
      - "127.0.0.1:3001:3000"
    volumes:
      - ./slicer-data/bambu:/app/data
```

Use the exact lines from the `docker-compose.yml` of your PrintBuddy version;
the tag shown here may be outdated. Then start it next to PrintBuddy:

```bash
docker compose up -d
```

The sidecar images are pulled from Docker Hub; nothing is built locally.

### Option B: separate Compose stack in `slicer-api/`

Use this if you prefer to manage the sidecars separately, or want to build
the images yourself (Option C). The `slicer-api/` folder of the PrintBuddy
repository contains its own `docker-compose.yml`.

- **PrintBuddy installed from the Git repository** (native install or Docker
  "build from source"): the folder is already there and is updated together
  with PrintBuddy.
- **PrintBuddy installed from the prebuilt Docker image**: download the
  folder's files once, on the PrintBuddy host:

```bash
mkdir -p ~/printbuddy-slicer && cd ~/printbuddy-slicer
```

```bash
for f in docker-compose.yml .env.example README.md; do curl -fsSL -o "$f" "https://raw.githubusercontent.com/vmhomelab/Printbuddy/main/slicer-api/$f"; done
```

Replace `main` with the branch you run PrintBuddy from if it is not `main`.

Create your configuration from the template:

```bash
cp .env.example .env
```

| Variable | Meaning |
|---|---|
| `BAMBU_STUDIO_API_IMAGE` / `ORCA_SLICER_API_IMAGE` | Images to run. Keep the values from `.env.example`. |
| `BAMBU_API_PORT` / `ORCA_API_PORT` | Host ports (3001 / 3003). Do not use 3000 or 3002: PrintBuddy's virtual printers need them. |
| `SLICER_API_BUILD_CONTEXT`, `BAMBU_VERSION`, `ORCA_VERSION`, `BAMBU_APPIMAGE_URL` | Only used when building the images yourself (Option C). |

Start Bambu Studio and OrcaSlicer:

```bash
docker compose --profile bambu up -d
```

To start **only OrcaSlicer**, leave out `--profile bambu`:

```bash
docker compose up -d
```

> In this stack a plain `docker compose up -d` never starts Bambu Studio.
> This is a common reason for "Slicer sidecar unreachable".

### Option C: build the images yourself

Only needed for other slicer versions or your own sidecar changes. In the
`slicer-api/` folder, set `BAMBU_VERSION` / `ORCA_VERSION` (and
`SLICER_API_BUILD_CONTEXT` for another sidecar revision) in `.env`, and give
the images local names so the published tags are not overwritten, for
example:

```ini
BAMBU_STUDIO_API_IMAGE=printbuddy-bambu-studio-api:local
ORCA_SLICER_API_IMAGE=printbuddy-orca-slicer-api:local
```

Then build and start:

```bash
docker compose --profile bambu build --no-cache --pull
```

```bash
docker compose --profile bambu up -d
```

The build downloads the slicer (about 220 MB for Bambu Studio, 110 MB for
OrcaSlicer) and takes 3–8 minutes per sidecar. Bambu Studio must be 02.08.x
or newer.

### Check the sidecar

```bash
curl http://localhost:3001/health
```

```bash
curl http://localhost:3003/health
```

A working sidecar reports `"status":"healthy"` and its slicer version, for
example `"version":"02.08.02.61"`.

### Network and security

The sidecar API has **no authentication**. The Compose file therefore binds
both ports to `127.0.0.1`, so they are not reachable from your LAN or the
internet. Check with `docker ps`: the ports must read `127.0.0.1:3001->3000/tcp`,
not `0.0.0.0:3001->3000/tcp`.

- If PrintBuddy runs with `network_mode: host` on the same machine, nothing
  else is needed.
- If PrintBuddy runs in a bridged Docker network, `localhost` inside the
  PrintBuddy container is not the host. Put PrintBuddy and the sidecars on a
  shared Docker network and use `http://bambu-studio-api:3000` /
  `http://orca-slicer-api:3000` as the sidecar URLs.
- If the sidecar runs on another machine, keep it on a private network and put
  an authenticating reverse proxy in front of it. Do not simply change the
  binding to `0.0.0.0`.

---

## 2. Connect PrintBuddy

In PrintBuddy open **Settings → Slicer**:

1. **Preferred slicer**: `Bambu Studio` or `OrcaSlicer`.
2. **Use Slicer API**: on. Without it, **Slice** hands the file to your desktop
   slicer instead.
3. **Sidecar URL**: leave empty to use the defaults (`http://localhost:3001`
   for Bambu Studio, `http://localhost:3003` for OrcaSlicer), or enter your
   own URL.
4. Click **Test slicer connection**. It checks the sidecar of the preferred
   slicer and must report success before slicing can work.

---

## 3. Provide profiles

Every slice needs a printer, a process and one filament profile per used
filament slot. The Slice dialog lists them in groups:

| Group | Source | Setup |
|---|---|---|
| **Imported** | Profiles you imported under **Settings → Profiles** | Import JSON exports from Bambu Studio / OrcaSlicer. |
| **Orca Cloud** | Your OrcaSlicer cloud profiles | Sign in under **Settings → Profiles → Cloud**. |
| **Cloud** | Your Bambu Cloud profiles plus Bambu's public cloud profiles | Sign in to Bambu Cloud under **Settings → Profiles → Cloud**. |
| **Standard** | The stock profiles shipped with the running slicer | None. The list depends on the preferred slicer. |

When a name exists in several groups, it is shown only once
(Cloud before Imported before Standard).

**Slicer bundles** are an alternative: export a printer preset bundle
(`.bbscfg`) from Bambu Studio (*File → Export → Export Preset Bundle →
Printer preset bundle*) and import it under **Settings → Slicer**. In the
Slice dialog you then pick the bundle and choose process and filaments from
it.

---

## 4. Use the Slice dialog

Open it with the **Slice** (cog) action on a file in the **File Manager**, on
an **Archive** entry, or on a **MakerWorld** model. Supported inputs are
`.stl`, `.3mf`, `.step` and `.stp`. Files that are already sliced
(`.gcode`, `.gcode.3mf`, `.bgcode`) cannot be sliced again.

Work through the dialog from top to bottom:

1. **Plate** (multi-plate 3MF only): pick the plate to slice first. The plate
   is shown under the dialog title.
2. **Printer profile**: the profile of the printer you will print on,
   including the **nozzle size** (for example `Bambu Lab X2D 0.4 nozzle`). It
   must match the nozzle that is actually installed.
3. **Process profile**: layer height and quality. Only profiles that are
   compatible with the selected printer, or whose compatibility is unknown,
   are listed. For Bambu printers prefer profiles ending in `@BBL <model>`.
4. **Build plate**: `Auto` uses the plate stored in the process profile. Pick
   the plate that is really installed. This matters for high-temperature
   filaments: ABS, ASA or PC on a Cool Plate is rejected by the slicer.
5. **Filament 1, 2, …**: one dropdown per filament slot the plate uses; the
   coloured dot shows the colour from the model. PrintBuddy pre-selects a
   profile that matches type and colour. Check every slot:
   - Use a profile for the **same printer and nozzle** (for Bambu: ending in
     `@BBL <model>` or `@BBL <model> <size> nozzle`).
   - Slots the selected plate does not use are greyed out and marked as
     unused.
   - Your own cloud profiles (for example `Generic PLA - Silk PLA`) often carry
     no compatibility information and are always listed. Make sure such a
     profile was created for this printer; otherwise the slicer rejects the
     job.
6. **Slice all N plates** (multi-plate 3MF only): slices every plate into one
   output file. The filament selection then applies to every slot of the
   project.
7. **Add to print queue afterwards** (needs the *queue: create* permission):
   when slicing finishes, the regular **Add to queue** dialog opens for the
   sliced file, where you choose printer, AMS mapping and schedule. The
   setting is remembered per browser.
8. Click **Slice**. The job runs in the background and a progress message
   stays visible while you keep working.

Where the result goes:

- Slicing a **File Manager** file creates a new `<name>.gcode.3mf` in the same
  folder.
- Slicing an **Archive** entry creates a new archive entry.

You can print or queue the result like any other sliced file.

---

## 5. Printer-specific notes

### Bambu Lab X2D

- Use the **Bambu Studio** sidecar. OrcaSlicer 2.3.2 has no X2D profiles
  ("parent … not found" errors).
- Bambu Studio names X2D filament profiles by nozzle:
  - `… @BBL X2D 0.4 nozzle`: 0.4 mm nozzle (the common case)
  - `… @BBL X2D 0.2 nozzle`: 0.2 mm nozzle
  - `… @BBL X2D` **without** a suffix: **0.6 and 0.8 mm nozzles only**

  With a 0.4 mm nozzle, pick the `0.4 nozzle` variant. A profile without the
  suffix is rejected with *"Filament profile … is not compatible with printer
  Bambu Lab X2D 0.4 nozzle"*.
- Process profiles `… @BBL X2D` (without suffix) are for the 0.4 mm nozzle.
- The X2D has two nozzles; each filament slot of the model must get a
  profile for the X2D.

### Bambu Lab H2D, H2S and other dual-nozzle models

- Use the **Bambu Studio** sidecar.
- Filament profiles `… @BBL H2D` / `… @BBL H2S` without a suffix include the
  0.4 mm nozzle.
- Re-slicing a model made for a single-nozzle printer (X1C, P1S, A1, …) for a
  dual-nozzle printer, or the other way round, is supported: PrintBuddy
  lets the slicer re-arrange the objects for the target bed. Check the
  layout in the preview before printing.

### Bambu Lab X1 / P1 / A1 series

- Both sidecars work; Bambu Studio is recommended.
- Profiles named `@BBL X1C` are shared by several models (X1, X1C, P1P,
  P1S, …). The dialog only lists those compatible with the selected printer.
- Profiles without a nozzle suffix are for the 0.4 mm nozzle.

### Non-Bambu printers (Prusa, Voron, Creality, …)

- Use the **OrcaSlicer** sidecar. Bambu Studio ships only a few third-party
  printer profiles.
- Pick printer, process and filament profiles of the same vendor (for
  example all `@MK4S` for a Prusa MK4S).

### Filament slots and colours

- Unused slots of the selected plate do not influence the print. PrintBuddy
  replaces them with the profile of slot 1 to avoid slicer rejections such as
  *"the temperature difference of the filaments used is too large"*.
- Matching profiles to AMS slots happens later, in the **Add to queue** /
  **Print** dialog.

---

## 6. Update the sidecar

A PrintBuddy release can reference newer sidecar images.

- **Option A** (PrintBuddy's Compose file): after updating PrintBuddy,
  compare the `image:` lines of the sidecar services with the new
  `docker-compose.yml` and take over the new tags. Then:

```bash
docker compose pull
```

```bash
docker compose up -d
```

- **Option B** (`slicer-api/` stack): compare your `.env` with the new
  `.env.example` (download it again if the folder is not part of your
  PrintBuddy checkout) and take over `BAMBU_STUDIO_API_IMAGE`,
  `ORCA_SLICER_API_IMAGE` and `SLICER_API_BUILD_CONTEXT`. Then:

```bash
docker compose --profile bambu pull
```

```bash
docker compose --profile bambu up -d
```

- **Option C** (self-built): rebuild with
  `docker compose --profile bambu build --no-cache --pull`.

> **Important:** sidecar revisions before `cb44369` could resolve stock
> profiles against another vendor's base profiles and write a wrong filament
> diameter (2.8 or 2.85 mm instead of 1.75 mm) into the G-code. Re-slice
> files that were sliced with Standard or public Cloud profiles before the
> update; do not print them.

---

## 7. Troubleshooting

| Message | Cause and fix |
|---|---|
| **Slicer sidecar unreachable: All connection attempts failed** | PrintBuddy cannot reach the sidecar of the preferred slicer. Check with `docker ps` that it runs (in the `slicer-api/` stack Bambu Studio needs `--profile bambu`), that `curl http://localhost:3001/health` (or `3003`) works on the host, and that PrintBuddy uses host networking. Then click **Test slicer connection** again. |
| **Filament profile "…" is not compatible with printer "…"** | The filament profile belongs to another printer or nozzle size. Pick the variant for your printer and nozzle (for the X2D 0.4 mm: `… @BBL X2D 0.4 nozzle`). |
| **Unable to resolve inherited … profile: parent "…" was not found** | The running slicer does not ship the stock profile the selected profile is based on, usually because the printer is newer than the slicer. Use Bambu Studio or raise the version in `.env`. |
| **Plate 1: Cool Plate does not support filament 1** | Set **Build plate** to the plate you use (for example High Temp or Textured PEI). |
| **Slicing failed** without details | Look at the sidecar log: `docker logs --tail 100 bambu-studio-api` (or `orca-slicer-api`). |
| **pull access denied** or **manifest unknown** for a `printbuddy-*-api` image | The tag is not published (yet). Use the tag from the current `docker-compose.yml` / `.env.example`, or build the image yourself (Option C). |
| **no matching manifest for linux/arm64** for `printbuddy-bambu-studio-api` | Bambu Studio is only available for AMD64. Use the OrcaSlicer sidecar on ARM64 hosts. |
| Build stops with **failed to read dockerfile: open Dockerfile.bambu-studio** | Your `.env` points `SLICER_API_BUILD_CONTEXT` at an old sidecar revision. Copy the value from `.env.example`. |
| Build stops with **No Ubuntu 22.04 AppImage found** | The Bambu Studio version does not exist or GitHub rate-limited the lookup. Open the Bambu Studio release page on GitHub, copy the URL of the `BambuStudio_ubuntu22.04-…AppImage` file, set it as `BAMBU_APPIMAGE_URL` in `.env` and build again. |
| **address already in use** on 3000 or 3002 | These ports belong to PrintBuddy's virtual printers. Keep the sidecars on 3001 / 3003 or other free ports. |
| The Slice action is missing | Turn on **Use Slicer API** in **Settings → Slicer**. Slicing in the File Manager also needs the *library: upload* permission. |
| The **Add to print queue afterwards** option is missing | Your user lacks the *queue: create* permission, or PrintBuddy is older than this feature. |
