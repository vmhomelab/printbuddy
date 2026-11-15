# GyroidVault integration

Printbuddy can browse a self-hosted [GyroidVault](https://github.com/TeeCodeDev/GyroidVault)
model library and import model files into the Printbuddy library. It is one of the sources
on the **Model import** page, next to MakerWorld. From there the usual
File Manager flow (slice, print, queue) applies. One GyroidVault instance is supported.

Printbuddy only talks to GyroidVault over HTTP; no GyroidVault code is included.

## Setup

1. In GyroidVault, create a dedicated account with the **viewer** role (read-only), or the
   **uploader** role if Printbuddy should report prints back (see below). GyroidVault API
   keys **cannot be revoked individually**. The only way to invalidate a key is to rotate
   GyroidVault's JWT secret, which also logs out every user. An account with as few rights
   as possible limits what a leaked key can do.
2. Log in as that account and generate an API key in your profile
   (`POST /api/auth/api-key`).
3. In Printbuddy open **Model import → Settings → GyroidVault model library**, enter the
   GyroidVault URL (for example `http://192.168.1.50:3457`) and the API key, then use
   **Test connection**. The test reports the GyroidVault version, the account and its
   role, and warns if the key belongs to an account with write access or if GyroidVault
   is older than the tested version (2.3.0).
4. Turn the integration on and save. Browsing happens in **Model import → GyroidVault**
   (the old `/gyroidvault` address redirects there) for users with `library:read`.

The API key is stored encrypted (same key as MFA/OIDC secrets) and is never returned by
the API. Leaving the key field empty on save keeps the stored key.

## Using it

- Search supports GyroidVault's own syntax (`tag:`, `-tag:`, `cat:`, `format:`, `user:`)
  plus the category, tag, format and sort filters.
- Selecting a model shows its files. Importable types are `.3mf`, `.stl`, `.gcode`,
  `.obj`, `.step` and `.stp`. Files that are already in the library are marked and cannot
  be selected again.
- Imports go to a top-level **GyroidVault** folder (created automatically) or to any
  writable folder. Importing needs `library:upload`.
- Each imported file keeps a link back to the model in GyroidVault (`source_url`), which
  is also what prevents duplicate imports.

## Limits

- GyroidVault rate-limits downloads to 60 per 15 minutes. When the limit is hit, the
  remaining files of that import are reported as failed and can be retried later.
- A single download is capped at 2 GiB and is streamed to disk.
- GyroidVault has no versioned API. The endpoints used (`/healthz`, `/api/auth/me`,
  `/api/models`, `/api/models/:id`, `/api/categories`, `/api/tags`,
  `/api/files/:id/download` and thumbnail paths under `/uploads/` and `/library-files/`)
  were taken from the GyroidVault 2.3.x source.

## API

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET/PUT /api/v1/gyroidvault/settings` | `settings:read` / `settings:update` | URL, enabled flag, API key (write-only) |
| `POST /api/v1/gyroidvault/test` | `settings:update` | Test reachability, version and key |
| `GET /api/v1/gyroidvault/status` | `library:read` | Connection status |
| `GET /api/v1/gyroidvault/models` | `library:read` | Search/list models |
| `GET /api/v1/gyroidvault/models/{id}` | `library:read` | Model detail with files and import state |
| `GET /api/v1/gyroidvault/categories`, `/tags` | `library:read` | Filter values |
| `GET /api/v1/gyroidvault/asset?path=…&token=…` | stream token | Thumbnail proxy (images only) |
| `POST /api/v1/gyroidvault/import` | `library:upload` | Import files `{model_id, file_ids, folder_id}` |
| `GET /api/v1/gyroidvault/recent-imports` | `library:read` | Last imported files |

`PUT /api/v1/gyroidvault/settings` also takes `report_prints` (boolean).

## Reporting prints back to GyroidVault

With **Report prints to GyroidVault** switched on, every completed or failed print of an
imported model adds an entry to that model's print history in GyroidVault
(`POST /api/models/:id/prints`, notes like `Printbuddy · X1C · Benchy`). Cancelled prints
are not reported.

- This needs an API key of an account with the **uploader** role; viewer accounts are
  rejected by GyroidVault. The connection test warns about this.
- Printbuddy finds the model through the printed library file: the queue item's file, or
  for direct prints from the File Manager the archive's file hash. Files sliced inside
  Printbuddy are followed back to the imported model.
- Only imports from the currently configured GyroidVault URL are reported, and each
  archived print is reported once.
- Reporting runs in the background after the print finishes. If GyroidVault is down or
  rejects the request, the print is not reported and a warning is logged; nothing is
  retried.
