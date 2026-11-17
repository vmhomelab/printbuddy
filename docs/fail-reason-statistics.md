# Fail reason statistics

Printbuddy can record *why* a print failed and show which causes are most common.
It sits next to the existing **Failure Analysis** widget and does not change it: its own
tables hold the reports, and Printbuddy's archives are only read.

## Reporting a failed print

Each printer card has a **Report failed print** button (for users with `printers:control`,
everyone when authentication is off). It opens a dialog for the printer's current print
(while printing or paused) or, otherwise, its most recent print.

- Pick a reason from the tiles (icon, title, short examples). An optional comment and an
  optional name can be added; the name is empty by default, so reports can stay anonymous.
- One report per print run. Reporting the same run again updates the report; a report can
  be withdrawn. Reporting never stops or changes the print.
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

## Statistics widget

**Statistics → Fail reason statistics** lists every visible reason with count and share for
the page's date range. Each row expands to the
affected prints: printer, date, material, estimated grams and time, print name with
thumbnail, comment and reporter. The latest 15 are shown, then "Show all (N)".

## API

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /api/v1/custom-failure-reports/printers/{id}/target` | `printers:read` | Print a new report would apply to, existing report |
| `POST /api/v1/custom-failure-reports/` | `printers:control` | Report a print run (or update its report) |
| `PATCH /api/v1/custom-failure-reports/{id}` | `printers:control` | Change reason, comment or name |
| `DELETE /api/v1/custom-failure-reports/{id}` | `archives:delete_all` | Withdraw a report |
| `GET /api/v1/custom-failure-reports/stats` | `archives:read` | Counts per reason (`date_from`, `date_to`) |
| `GET /api/v1/custom-failure-reports/` | `archives:read` | Reports, newest first (`reason`, `date_from`, `date_to`) |
| `GET /api/v1/custom-failure-reports/reasons/` | `printers:read` | Reasons in display order |

Reporting and changing a reason need `printers:control` (Operators, Administrators), so
read-only Viewers can't create or change reports; withdrawing needs `archives:delete_all`.
The button, the pencil and **Withdraw report** are hidden for users without the permission.

## Database

New tables `custom_failure_reports` and `custom_failure_reasons`, created by `create_all`
(SQLite and PostgreSQL). Nothing in existing tables is changed.
