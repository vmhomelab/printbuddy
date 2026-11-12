# OctoEverywhere AI failure detection

Printbuddy can use [OctoEverywhere's Gadget API](https://docs.octoeverywhere.com/ai-failure-detection-apis/developer-docs/overview/)
as an optional, cloud-hosted AI print-failure detector. It sits next to the
self-hosted Obico integration on **Settings → Failure Detection**. The two are
configured separately, and you can run either one, both or neither.

## Setup

1. Create a free key at <https://octoeverywhere.com/gadgetapi>. No card is needed.
2. In Printbuddy, open **Settings → Failure Detection → OctoEverywhere AI detection**.
3. Paste the key, click **Test**, turn the provider on and click **Save**.

Printbuddy needs outbound HTTPS access to `gadget-pv1-oeapi.octoeverywhere.com`
and to the regional `*.octoeverywhere.com` processing hosts that Gadget returns.

## How it works

- The AI badge on each printer card shows which provider watches that printer,
  e.g. `AI On · OctoEverywhere`. When both providers are enabled, the card shows one
  badge per provider, and clicking a badge adds or removes the printer from that
  provider's list only.
- For each monitored printer, Printbuddy creates one Gadget *context* per print.
  Creating a context is free.
- While the printer is `RUNNING`, Printbuddy uploads a JPEG snapshot to the
  context. Gadget's temporal model uses earlier snapshots of the same print to judge
  how the print is going.
- The camera source matches the printer's snapshot endpoint: a configured external
  camera, a provider camera (PrusaLink, Creality, Elegoo) or the built-in Bambu camera.
  If a live viewer is open, Printbuddy reuses its frame and does not open a second
  camera connection. Printers without a camera are skipped.
- By default the interval follows Gadget's recommendation, usually 20 s. A fixed
  interval of 10–120 s is also possible. Printbuddy never inspects faster than
  Gadget's minimum.
- **Warning suggested** sends a notification once, through the printer-error
  notification channels with the snapshot attached. This can be turned off.
- **Pause suggested** runs the configured action once: notify, pause, or pause and
  turn off linked smart plugs. A paused print keeps its context and is not paused again
  unless Gadget clears the flag and raises it again.

The sensitivity setting maps to Gadget's confidence levels:

| Setting | Confidence level |
|---|---|
| Low | 4 |
| Medium | 3 |
| High | 2 |

A lower level means Gadget suggests a warning or pause earlier.

## Errors

| Gadget error | Printbuddy behaviour |
|---|---|
| Rate limited, throttled, internal error | Retries at the next interval and respects `Retry-After`. |
| Connection or server failure | Switches to the fallback URL for the rest of the print. |
| Invalid, disabled or IP-restricted key; billing problem; free allowance used up | Pauses all inspections for one hour, or until the key is changed. The error is shown on the status card. |
| Context expired, cancelled or not found | Stops inspecting the current print. |

## Privacy and cost

Snapshots leave your network. According to OctoEverywhere, images sent through the
public Gadget API are not used for AI training.

Every account includes 90,000 free inspections per month, which is about 500 print
hours at a 20 s interval. Gadget's **Free Usage Only** limit is on by default, so you
are not charged unless you turn it off on the Gadget account page.

The API key is stored encrypted and is never returned by Printbuddy's API. Gadget
context IDs and processing URLs are also credentials. They are kept in memory only
and never logged.

## API

All endpoints require authentication when auth is enabled.

| Endpoint | Permission |
|---|---|
| `GET /api/v1/octoeverywhere/settings` | `settings:read` |
| `PUT /api/v1/octoeverywhere/settings` | `settings:update` |
| `GET /api/v1/octoeverywhere/status` | `settings:read` |
| `POST /api/v1/octoeverywhere/test-connection` | `settings:update` |

`test-connection` creates a free context and cancels it straight away, so it uploads
no image and costs nothing.
