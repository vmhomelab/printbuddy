# Printbuddy in OrcaSlicer's Device tab

*New in Printbuddy v0.2.5.4 · part of the Moonraker/OctoPrint-compatible virtual printers (#52)*

Send a job from OrcaSlicer and keep watching it in the **same window**. When you set up a Printbuddy virtual printer in OrcaSlicer with the host type **OctoPrint**, OrcaSlicer's **Device** tab now shows a Printbuddy dashboard for that printer. You can follow the print, watch the webcam and control the printer without switching to the browser.

This also works with **Snapmaker Orca**, and for every printer type Printbuddy supports (Klipper/Moonraker, PrusaLink, PrusaConnect, OctoPrint, Elegoo, …), not just Bambu Lab.

<!-- SCREENSHOT 1 (Hero): docs/screenshots/vp-device-hero.png
     OrcaSlicer window with the Device tab open, showing the Printbuddy dashboard during a print
     (progress, webcam and temperatures visible). Use the dark theme if the rest of your screenshots are dark.
<p align="center">
  <img src="docs/screenshots/vp-device-hero.png" alt="Printbuddy dashboard in OrcaSlicer's Device tab" width="900">
</p>
-->

---

## What you see

**Print job**
- Printer state with a coloured status indicator
- File name and model, progress in percent with a progress bar, and the current layer
- Remaining time and estimated finish time
- **Pause / Resume** and **Stop** buttons
- Printer error messages, if there are any

**Active material**
- The filament in each spool, AMS/CFS slot or toolhead, with colour and material

**Webcam**
- Live stream of the printer camera, with a fullscreen button
- Snapshot button that opens a still image in a new window

**Temperatures**
- All nozzle, bed and chamber temperatures with current and target values
- Set nozzle and bed targets directly
- **Preheat PLA** (nozzle 200 °C, bed 60 °C) and **Cool down** with one click

**Control**
- Sliders for the part cooling, auxiliary and chamber fans (only the fans your printer has)
- Chamber light switch (if your printer has one)

**More**
- Updates every 2 seconds
- **Open in Printbuddy** link to the full web interface
- English or German, based on your system language
- Works on small windows as well

<!-- SCREENSHOT 2: docs/screenshots/vp-device-controls.png
     Close-up of the right column: temperatures with the set/preheat/cool-down controls, fan sliders and chamber light.
<p align="center">
  <img src="docs/screenshots/vp-device-controls.png" alt="Temperature, fan and light controls" width="500">
</p>
-->

---

## One printer per Device tab

Each printer you set up in OrcaSlicer points to its **own** Printbuddy virtual printer. Its Device tab shows exactly the virtual printer's **target printer**, never a list of every printer in Printbuddy. The header shows the printer name and the virtual printer the job goes through.

Every button acts on that target printer only. If the virtual printer has no target printer yet, or the target printer is inactive, the page tells you where to choose one.

---

## Setup

### 1. Create the virtual printer in Printbuddy

1. Open **Settings → Virtual printer** and click **Add**.
2. Choose the type **Moonraker/OctoPrint**.
3. Pick a mode. For the dashboard, set a **target printer**: the physical printer this virtual printer belongs to. In print-queue mode a target printer is required.
4. Save. The virtual printer card shows the **host URL** and the **API key**.

<!-- SCREENSHOT 3: docs/screenshots/vp-device-printbuddy-card.png
     Printbuddy → Settings → Virtual printer: the Moonraker VP card with host URL, API key (blur it!) and the target printer.
<p align="center">
  <img src="docs/screenshots/vp-device-printbuddy-card.png" alt="Virtual printer card with host URL and API key" width="700">
</p>
-->

### 2. Add the printer in OrcaSlicer

1. In OrcaSlicer, open the **physical printer** settings of your printer preset (the Wi-Fi/network icon next to the printer).
2. Set **Host type** to **OctoPrint**.
3. Paste the **host URL** from the card, e.g. `http://<printbuddy-ip>:8000/api/v1/vp-host/<id>`.
4. Paste the **API key**.
5. Click **Test**, then **OK**.

<!-- SCREENSHOT 4: docs/screenshots/vp-device-orca-setup.png
     OrcaSlicer "Physical Printer" dialog with host type OctoPrint, the Printbuddy host URL and the API key field (blurred).
<p align="center">
  <img src="docs/screenshots/vp-device-orca-setup.png" alt="OrcaSlicer physical printer setup with host type OctoPrint" width="600">
</p>
-->

### 3. Open the Device tab

Switch to the **Device** tab in OrcaSlicer. The Printbuddy dashboard loads right away. After you send a job, OrcaSlicer switches to it automatically.

---

## Security

- The page itself contains no printer data. All data and all control actions require the **virtual printer's API key**. OrcaSlicer sends it automatically.
- In a normal browser, open the host URL with `?apikey=<key>` or enter the key in the form on the page. The key is stored **in this browser only**.
- The webcam uses a short-lived stream token, which is renewed automatically.
- Scripts and styles are separate files, so Printbuddy's strict Content Security Policy also applies to this page.
- Anyone with the API key can control the target printer. Treat the key like a password, and regenerate it on the virtual printer card if it gets out.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| "API key required" | OrcaSlicer didn't send the key. Check the API key in the physical printer settings, or enter it in the form. |
| "No target printer" message | Choose a target printer on the virtual printer card in Printbuddy. |
| Buttons are greyed out | The target printer is offline or busy. Check the printer's connection in Printbuddy. |
| No webcam image | Make sure a camera is configured for the target printer in Printbuddy. |
| Device tab shows `{"detail":"Not found"}` | Your Printbuddy is older than v0.2.5.4, or the host URL is wrong. Copy it again from the virtual printer card. |

---

## Requirements

- Printbuddy **v0.2.5.4** or newer
- OrcaSlicer or Snapmaker Orca
- A **Moonraker/OctoPrint-compatible** virtual printer with a target printer. Bambu-compatible virtual printers keep using Bambu's own Device view.
