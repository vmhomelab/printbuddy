# Fail reason statistics

Printbuddy can record *why* a print failed and show which causes are most common.
It sits next to the existing **Failure Analysis** widget and does not change it: its own
tables hold the reports, and Printbuddy's print log, archives and queue are only read.

## Reporting a failed print

Each printer card has a **Report failed print** button (for users with `printers:control`,
everyone when authentication is off). It opens a dialog for the printer's current print
(while printing or paused) or, otherwise, its most recent print.

- Pick a reason from the tiles (icon, title, short examples). An optional comment and an
  optional name can be added; the name is empty by default, so reports can stay anonymous.
- One report per print run. Reporting the same run again updates the report; a report can
  be withdrawn. Reporting never stops or changes the print.
- If the printer currently shows a Bambu HMS error that maps to a reason, that tile is
  pre-selected and the error is shown ("suggested from the printer's current error").
- The report stores a snapshot of the print (printer, date, name, material per slot,
  grams, estimated time, thumbnail link), so the statistics survive archive deletion and
  reprints of the same file.

## Reasons

Reports store a reason **code**; the visible title comes from the translations. Renaming a
reason therefore never rewrites history, and counts don't depend on the UI language.

Default reasons (codes `fail_reason_01` … `fail_reason_14`): clogged nozzle, warping,
layer shift, slicing error, material run-out, hardware/software fault, external
interference, tangled filament, missing maintenance, poor print quality, spaghetti / part
detached, filament feeding / AMS, print preparation error and other ("other" is always
listed last).

Users with `settings:update` (everyone when authentication is off) see a cog in the dialog:

- add, edit, re-order and hide reasons (at most 100 reasons, hidden ones included);
- default reasons are only hidden, never deleted; custom reasons that already have reports
  are hidden, unused ones are deleted; **Restore default reasons** shows hidden defaults again;
- text typed for a default reason replaces the translated text; leaving it empty goes back
  to the translation;
- icon: one of ~50 built-in icons, or an uploaded image (JPG/PNG/GIF/WebP, max 10 MB),
  scaled down to fit 500 × 500 px and stored as PNG under `<archive dir>/failure_reason_icons`.

Hidden reasons can't be chosen for new reports. Existing reports keep them and they stay
in the statistics.

## Statistics widget

**Statistics → Fail reason statistics** lists every visible reason with count and share for
the page's date range (plus hidden reasons that have reports). Each row expands to the
affected prints: printer, date, material, estimated grams and time, **Stopped/Failed at**
(how far the print got), print name with thumbnail, comment and reporter. The latest 15 are
shown, then "Show all (N)".

Filters: **Printer** (one printer or all) and **Source** (all reports / picked by people /
detected automatically), with **Reset filter**. A pencil on each print opens the dialog to
change or confirm its reason.

## Existing failure history

So that existing installations don't start from zero, print log entries with status
`failed` or `aborted` are taken over automatically. The sync runs in the background: once at
startup over the whole print log, and after every finished print and after a failure reason
or status is changed in the Edit Archive dialog only for that print's archive, so it stays
cheap with long histories. Reading the statistics never writes. It is idempotent, only reads
Printbuddy's tables, and a unique index on `print_log_entry_id` rules out duplicates even
with several workers.

- The `failure_reason` text is mapped onto the reason codes: all Edit Archive labels in
  all 9 languages and the automatic texts ("Layer shift", "Filament runout", "Clogged
  nozzle"). Unknown texts are kept and land in **Unassigned**.
- "User cancelled" and stale prints are not failure causes and are skipped. Failed prints
  without any reason (e.g. Klipper errors) land in **Unassigned**.
- HMS codes: all codes in `hms_errors.py` have a mapping, or are marked as not being a
  failure cause (pauses, info messages, laser/cutting module, cloud, firmware updates).
  Printbuddy doesn't keep the HMS code of a finished print, so the codes are used for the
  printer's live errors (dialog suggestion) and for queue items whose `error_message`
  contains them. The mapping is in `backend/app/services/failure_reason_mapping.py`.
- Imported reports are marked as *automatic* (from automatic data) or *from archive*
  (picked by a person in the Edit Archive dialog). They follow later changes in the Edit
  Archive dialog until a person confirms or changes the reason; after that the sync never
  overwrites it. A person's own report for the same run always wins.
- A withdrawn imported report is kept as an invisible marker, so the next sync doesn't
  bring it back.

**Stopped/Failed at:** when a print ends without completing, its last progress is stored
(Bambu `last_progress`, Moonraker `progress`). Prints that ended before this feature
existed show "–". A print reported after it completed shows 100 %; a print reported while
it is still running shows the progress at that moment until it ends.

## API

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /api/v1/custom-failure-reports/printers/{id}/target` | `printers:read` | Print a new report would apply to, existing report, suggestion |
| `POST /api/v1/custom-failure-reports/` | `printers:control` | Report a print run (or update its report) |
| `PATCH /api/v1/custom-failure-reports/{id}` | `printers:control` | Change reason, comment or name |
| `DELETE /api/v1/custom-failure-reports/{id}` | `archives:delete_all` | Withdraw a report |
| `GET /api/v1/custom-failure-reports/stats` | `archives:read` | Counts per reason (`date_from`, `date_to`, `source`, `printer_id`) |
| `GET /api/v1/custom-failure-reports/` | `archives:read` | Reports, newest first (`reason`, `date_from`, `date_to`, `source`, `printer_id`) |
| `GET /api/v1/custom-failure-reports/reasons/` | `printers:read` | Reasons (`include_hidden`) |
| `POST /api/v1/custom-failure-reports/reasons/` | `settings:update` | Add a reason |
| `PATCH/DELETE /api/v1/custom-failure-reports/reasons/{id}` | `settings:update` | Edit / hide or delete a reason |
| `PUT /api/v1/custom-failure-reports/reasons/order` | `settings:update` | Re-order |
| `POST /api/v1/custom-failure-reports/reasons/restore-defaults` | `settings:update` | Show hidden defaults again |
| `POST/DELETE /api/v1/custom-failure-reports/reasons/{id}/icon` | `settings:update` | Upload / remove an image |
| `GET /api/v1/custom-failure-reports/reasons/{id}/icon` | stream token | Uploaded image |

Reporting and changing a reason need `printers:control` (Operators, Administrators), so
read-only Viewers can't create or change reports; withdrawing needs `archives:delete_all`.
The button, the pencil and **Withdraw report** are hidden for users without the permission.

## Database

New tables `custom_failure_reports`, `custom_failure_reasons` and
`custom_failure_run_progress`, created by `create_all` (SQLite and PostgreSQL). Nothing in
existing tables is changed. The default reasons are seeded once at startup (`init_db`);
defaults added in a later version are inserted before "Other".

`custom_failure_reports` contained the columns for the history import and the progress
(`source`, `original_reason`, `hms_code`, `print_log_entry_id` with a unique index,
`dismissed_at`, `progress_percent`) from its first version, so no `ALTER TABLE` is needed.
