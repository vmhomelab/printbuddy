# Printbuddy v0.2.5.4

<p align="center">
  <img src="frontend/public/img/printbuddy_logo_dark_transparent.png" alt="Printbuddy Logo" width="320">
</p>

**v0.2.5.4 is the biggest Printbuddy release so far.** It brings two new integrations (OctoPrint and GyroidVault), a production-ready **job plan** for projects, a **smartphone-optimized UI**, much better **Klipper/Moonraker** support (QIDI, Creality K2 with K2-OpenHost, Snapmaker U1), a major round of **slicer** improvements, and an **updater that now keeps the slicer sidecars and itself up to date**.

It also fixes a long-standing performance problem: a slow or unreachable HTTP printer can no longer freeze the whole UI.

<!-- SCREENSHOT 1 (Hero): docs/screenshots/v0254-hero-dashboard.png
     Printers page on desktop with a mix of printer types (Bambu, Klipper/QIDI, OctoPrint, PrusaLink), ideally one printing.
<p align="center">
  <img src="docs/screenshots/v0254-hero-dashboard.png" alt="Printbuddy v0.2.5.4 printers overview" width="800">
</p>
-->

---

## Highlights

- 🐙 **OctoPrint as a new printer type**: control, File Manager, webcam and discovery for Marlin/RepRap printers
- 📚 **GyroidVault integration** and a new combined **Model import** page
- 📋 **Project job plans**: plan every plate with quantity, material and printer, see running totals and queue everything with one click
- 📱 **Smartphone-optimized layout** with PWA improvements
- 🧰 **Klipper/Moonraker**: chamber heater/light/fans, multi-tool toolheads, K2-OpenHost CFS, Snapmaker SpoolLink and live toolhead position
- 🔪 **Slicer**: slice all plates into separate files, Snapmaker multi-color 3MFs, and a connection test that shows which slicer answered
- 🔄 **Updater** updates the slicer sidecars and itself
- ⚡ **No more UI freezes** with slow HTTP printers (Moonraker, OctoPrint, PrusaLink, PrusaConnect, Elegoo)

---

## ✨ New features

### OctoPrint support (#34)

Printers managed by OctoPrint (OctoPi, Anycubic, Raise3D Pro2, …) can now be added with the **OctoPrint URL** and an **API key**.

- Live status: state, nozzle/bed/chamber temperatures, progress and remaining time
- Start, pause, resume and cancel prints
- File Manager: list, upload, download and delete on `local` and `sdcard`
- Manual controls: home, jog, extrude, temperatures and part fan
- Print archiving, like for every other printer type
- The webcam configured in OctoPrint (including rotation) is used automatically, unless you enter your own camera URL
- Clear error messages when the API key is invalid or lacks permissions
- **Discovery**: subnet scan on ports 5000/80 finds OctoPrint instances without an API key (configurable with `DISCOVERY_OCTOPRINT_PORTS`)
- The Add/Edit dialogs use a single "OctoPrint URL" field; `http://` is added if missing

<!-- SCREENSHOT 2: docs/screenshots/v0254-octoprint-add.png
     "Add printer" dialog with printer type OctoPrint selected (URL + API key fields). Optionally a second shot of the OctoPrint printer card.
<p align="center">
  <img src="docs/screenshots/v0254-octoprint-add.png" alt="Adding an OctoPrint printer" width="600">
</p>
-->

### Model import page and GyroidVault

MakerWorld and the new GyroidVault integration now share one sidebar entry: **Model import** (`/import`) with the tabs **MakerWorld**, **GyroidVault** and **Settings**. Old `/makerworld` and `/gyroidvault` links redirect to the right tab, and your sidebar order and visibility are kept.

**[GyroidVault](https://github.com/TeeCodeDev/GyroidVault)** is a self-hosted model library. Printbuddy can now:

- Connect to one GyroidVault instance (URL + API key, with a connection test). The key is stored encrypted and is never sent back to the browser.
- Search and filter models by text, category, tag and file format
- Show a model's files and import STL, 3MF, G-code, STEP and OBJ files into the library (default folder "GyroidVault", or any writable folder)
- Skip files that were already imported, and create thumbnails for STL and G-code imports
- Optionally report completed and failed prints of imported models back to the model's GyroidVault print history, also after slicing in Printbuddy

Permissions: browsing needs `library:read`, importing needs `library:upload`. See [`docs/gyroidvault.md`](docs/gyroidvault.md).

<!-- SCREENSHOT 3: docs/screenshots/v0254-gyroidvault-browse.png
     Model import page, GyroidVault tab: search results grid with filters, ideally with one model opened showing its files.
<p align="center">
  <img src="docs/screenshots/v0254-gyroidvault-browse.png" alt="Browsing GyroidVault from Printbuddy" width="800">
</p>
-->

### Project job plans

Projects can now carry a **job plan**: every plate that has to be printed, for example for a customer order.

- Add plates from project or library files (with a multi-plate picker)
- Per row: quantity, group (e.g. "base set", "accessory"), material and colour per filament slot (or picked from inventory), and an optional printer or printer model
- Progress per plate: done, printing, queued, failed or open
- Summary panel with job progress, total and remaining print time and filament, filament per material and colour, and a **warning when your inventory stock is too low**
- **Queue all open copies with one click** (optionally staged for manual start), or queue a single row. Queuing again only adds what is still missing.
- **Order number** field (e.g. an Etsy order) shown in the project header and on project cards, together with the job progress
- When creating a project you can directly **link a File Manager folder**, so planned print time and filament show up right away
- Stats cards show planned print time and filament; templates copy the plan

<!-- SCREENSHOT 4: docs/screenshots/v0254-project-job-plan.png
     Project detail page with the job plan section: several rows with quantities/colours/progress and the summary panel (totals + filament per colour) visible.
<p align="center">
  <img src="docs/screenshots/v0254-project-job-plan.png" alt="Project job plan with running totals" width="800">
</p>
-->

### Smartphone-optimized layout

- Fixed top bar that respects the notch and status bar, larger touch targets and the theme toggle in the header
- **Refresh button** in the top bar, since an installed home-screen app has no reload button
- Mobile drawer respects safe areas; toasts and the bug-report bubble stay on screen and no longer cover content
- Profiles tabs scroll horizontally, File Manager actions wrap, Inventory header and project detail fit on phones
- Centered PWA icons

<!-- SCREENSHOT 5: docs/screenshots/v0254-mobile.png
     2-3 phone screenshots side by side (e.g. printers page, open drawer, project detail), taken in the installed PWA.
<p align="center">
  <img src="docs/screenshots/v0254-mobile.png" alt="Printbuddy on a smartphone" width="700">
</p>
-->

### Klipper / Moonraker

- **Chamber heater, chamber light and generic part fans** are detected automatically (e.g. QIDI Q2). The printer card shows chamber temperature and target, a light toggle and part/aux/chamber fan controls; the chamber target is limited to the heater's `max_temp`. (#35)
- **Multi-tool toolheads as AMS-style tiles**: each tool shows its label, filament colour, material, brand and inventory fill level; the active tool is highlighted. Click a tile to assign, change or clear a spool.
- **Creality K2 with K2-OpenHost (Kalico)**: the CFS is now shown (material, colour, brand, RFID %, humidity and temperature per unit) and can be controlled: load/unload slots and pick a slot per tool when starting a print, including multi-colour. Firmware errors such as "slot has no filament" are shown to you.
- **Snapmaker U1 / SpoolLink**: slots are linked to Spoolman spools and show the correct fill level, even when Printbuddy's Spoolman sync is off. Slot colours of non-Bambu printers are displayed correctly.
- **New manual controls layout**: XY jog cross with Home XY in the centre, homing column and Z column (also used for PrusaLink and OctoPrint), plus a **live toolhead position and Z offset** readout
- **Better archives**: Moonraker prints now store filament weight, material, colours, nozzle, temperatures and the slicer thumbnail. Filament usage is based on what was actually extruded, so cancelled prints are charged correctly.

<!-- SCREENSHOT 6: docs/screenshots/v0254-klipper-card.png
     Klipper printer card with chamber temperature + light/fan controls AND the multi-tool tiles (or the K2 CFS). If you have both, make two shots: v0254-klipper-chamber.png and v0254-multitool-tiles.png.
<p align="center">
  <img src="docs/screenshots/v0254-klipper-card.png" alt="Klipper printer with chamber controls and toolhead tiles" width="800">
</p>
-->

<!-- SCREENSHOT 7: docs/screenshots/v0254-jog-controls.png
     The new manual controls panel (XY cross, Z column, live position readout).
<p align="center">
  <img src="docs/screenshots/v0254-jog-controls.png" alt="New manual controls with live toolhead position" width="500">
</p>
-->

### Slicer

- **Slice all plates: choose the output**. Keep one multi-plate 3MF, or write one `{name}_plate_N.gcode.3mf` per plate so every plate becomes its own library entry
- **Snapmaker multi-colour and multi-plate 3MFs** slice with OrcaSlicer, with paint kept on multi-filament loads. OrcaSlicer 2.3.2 stays the stable default; 2.5.0-beta is a documented opt-in for Snapmaker.
- **The connection test shows which slicer answered**, e.g. "Connected to OrcaSlicer 2.3.2", and warns when the URL points to the other sidecar than the one you selected
- Per-printer guidance: OrcaSlicer for non-Bambu printers, Bambu Studio for Bambu Lab printers
- The sidecar reports its revision; Printbuddy warns when your sidecar is outdated
- The Slice dialog no longer asks everybody to sign in to Bambu Cloud. A banner appears only when a session expired or a cloud is unreachable, now for Orca Cloud as well.
- Orca Cloud printer compatibility and preset inheritance are resolved correctly, also across vendors
- The slicer sidecars can now be enabled directly in the main `docker-compose.yml` (see [`docs/slicer-sidecar.md`](docs/slicer-sidecar.md))

<!-- SCREENSHOT 8: docs/screenshots/v0254-slice-all-plates.png
     Slice modal with "Slice all plates" on and the new output choice (combined file / separate files) visible.
<p align="center">
  <img src="docs/screenshots/v0254-slice-all-plates.png" alt="Slice all plates with output choice" width="600">
</p>
-->

<!-- SCREENSHOT 9: docs/screenshots/v0254-slicer-connection-test.png
     Settings → Slicer after a successful connection test showing "Connected to <slicer> <version>".
<p align="center">
  <img src="docs/screenshots/v0254-slicer-connection-test.png" alt="Slicer connection test showing the detected slicer" width="600">
</p>
-->

### Updater

- The in-app updater now also **pulls and recreates the slicer sidecars** after Printbuddy, so they always match the version Printbuddy expects (`PRINTBUDDY_UPDATE_SLICER_SIDECARS=false` to opt out)
- A targeted update (e.g. to a beta) installs the **sidecars of that exact release**
- The updater **updates itself** through a short-lived helper container (`PRINTBUDDY_UPDATE_SELF=false` to opt out)
- Compose now runs with your real project directory and `.env`, so relative bind mounts and `${VARS}` keep their values

See [`docs/self-update-sidecar.md`](docs/self-update-sidecar.md).

### More improvements

- **3D model viewer**: new **Solid / Wireframe / X-ray** display modes
- **Notifications**: choose whether the 25/50/75 % milestones follow overall printer progress (matches the UI and Live Activity) or layer progress (default)
- **Authentication**: new admin setting **"Remember me for 30 days"** (Settings → Users → Authentication). Logins with "Remember me" checked then get a 30-day session instead of 24 hours. Works for password, LDAP, OIDC and 2FA logins.
- Changing a printer's API URL now reconnects the printer, like changing its IP address
- "Source code" links in the sidebar footer and on the login page (AGPL-3.0 §13), plus `NOTICE-modifications.md`

<!-- SCREENSHOT 10 (optional): docs/screenshots/v0254-model-viewer-xray.png
     3D viewer in X-ray or wireframe mode with the Solid/Wireframe/X-ray switch visible.
<p align="center">
  <img src="docs/screenshots/v0254-model-viewer-xray.png" alt="3D viewer in X-ray mode" width="600">
</p>
-->

---

## 🐛 Fixes

- **Slow UI with Klipper/Moonraker (e.g. QIDI Max4) and other HTTP printers**: every status read used to block the server while it waited for the printer. A slow or offline printer could freeze every page, the camera and the light toggles for tens of seconds. Each HTTP printer is now polled in its own background thread (Moonraker every 3 s, PrusaConnect every 10 s, others every 5 s). A printer counts as offline only after two failed polls in a row, and saved printers connect in parallel at startup.
- **PrusaLink / CORE One**: pausing no longer sends a "print stopped" notification and resuming no longer counts as a new print. Maintenance stops are reported as "stopped" instead of "failed", and stopped prints get a finish time.
- **Live Activity** no longer disappears and reappears right after a print starts
- **PostgreSQL**: upgrading databases created before v0.2.5.0 no longer aborts startup during migration
- Post-print SD-card cleanup and timelapse scans no longer try Bambu FTP for non-Bambu printers (saved about 8 s per print)
- The 3D viewer no longer reloads the model endlessly in the printer File Manager
- MakerWorld imports return a clear error instead of crashing on unexpected failures
- Missing `aiohttp`, `networkx` and `lxml` dependencies are now declared, so 3MF reading works everywhere

---

## ⬆️ Upgrading

```bash
docker compose pull
```

```bash
docker compose up -d
```

Or use the **Update** button in Settings if you run the updater sidecar.

**If you use the updater sidecar**, change its volume from the single compose file to the whole project directory (read-only), so it can see your `.env`:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
  - ./:/host:ro          # was: ./docker-compose.yml:/host/docker-compose.yml:ro
```

Without this change, the updater still updates Printbuddy, but it skips its own self-update.

**If you run the slicer sidecars** from `slicer-api/`, they now default to the moving `:latest` images. Remove fixed image tags from your `.env` if you want them to follow Printbuddy automatically.

---

## 🙏 Thanks

Thanks to everyone who tested the betas (v0.2.5.4b1–b5), reported bugs and contributed, especially @jdrew82 for the Snapmaker filament slot and OrcaSlicer/Snapmaker work (#38, #41).

**Full changelog:** [`v0.2.5.3...v0.2.5.4`](https://github.com/vmhomelab/printbuddy/compare/v0.2.5.3...v0.2.5.4)
