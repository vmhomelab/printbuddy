# Open Filament Database API integration notes

Phase-0 discovery notes for adding Open Filament Database (OFDB) support to PrintBuddy's local spool creation flow.

## Scope

Initial integration should use OFDB as a metadata/catalog source for creating PrintBuddy **local inventory** spools. OFDB should not become a second inventory backend. The intended flow is:

1. User enables OFDB under Profiles.
2. Add Spool exposes an optional OFDB search section only when enabled.
3. User selects an OFDB filament/variant/size.
4. PrintBuddy pre-fills the existing spool form.
5. The created local spool can be assigned to a printer/toolhead/slot using existing inventory assignment logic.
6. Existing built-in inventory usage tracking decrements/records usage against that spool.

## Base URL

```text
https://api.openfilamentdatabase.org/api/v1/
```

Use a backend proxy/service rather than browser-direct fetches so PrintBuddy controls timeouts, error handling, normalization, tests, and future caching.

## Confirmed endpoints

### Brand index

```text
GET /brands/index.json
```

Confirmed response shape:

```json
{
  "version": "2026.07.14",
  "generated_at": "2026-07-14T23:09:27Z",
  "count": 149,
  "brands": [
    {
      "id": "65026f70-74db-5916-bc7a-63ffc8bff0b2",
      "name": "ELEGOO",
      "slug": "elegoo",
      "origin": "CN",
      "material_count": 7,
      "path": "elegoo/index.json",
      "logo_slug": "ELEGOO_logo_png_b1ae954a.png"
    }
  ]
}
```

### Brand detail

```text
GET /brands/{brand_slug}/index.json
```

Example:

```text
GET /brands/elegoo/index.json
```

Confirmed response shape includes `materials`:

```json
{
  "id": "65026f70-74db-5916-bc7a-63ffc8bff0b2",
  "name": "ELEGOO",
  "website": "https://elegoo.com/",
  "origin": "CN",
  "source": "openprinttag",
  "slug": "elegoo",
  "materials": [
    {
      "id": "176f6aaf-2154-5a26-9a0a-646e7f5895ce",
      "material": "PLA",
      "slug": "PLA",
      "filament_count": 11,
      "path": "materials/PLA/index.json"
    }
  ],
  "logo_slug": "ELEGOO_logo_png_b1ae954a.png"
}
```

### Material index

```text
GET /brands/{brand_slug}/materials/{MATERIAL}/index.json
```

Example:

```text
GET /brands/elegoo/materials/PLA/index.json
```

Materials are uppercase identifiers such as `PLA`, `PETG`, `ABS`, `ASA`, `TPU`, etc.

Confirmed response shape:

```json
{
  "material": "PLA",
  "id": "176f6aaf-2154-5a26-9a0a-646e7f5895ce",
  "brand_id": "65026f70-74db-5916-bc7a-63ffc8bff0b2",
  "slug": "PLA",
  "material_class": "FFF",
  "filaments": [
    {
      "id": "c9923157-23d1-5ea4-93d6-255bdeffc6cc",
      "name": "PLA",
      "slug": "pla",
      "variant_count": 49,
      "path": "filaments/pla/index.json"
    }
  ]
}
```

### Filament detail

```text
GET /brands/{brand_slug}/materials/{MATERIAL}/filaments/{filament_slug}/index.json
```

Example:

```text
GET /brands/elegoo/materials/PLA/filaments/pla/index.json
```

Confirmed response shape includes print temperatures, density, slicer settings, and variants:

```json
{
  "id": "c9923157-23d1-5ea4-93d6-255bdeffc6cc",
  "name": "PLA",
  "diameter_tolerance": 0.02,
  "density": 1.26,
  "min_print_temperature": 190,
  "max_print_temperature": 230,
  "min_bed_temperature": 50,
  "max_bed_temperature": 70,
  "slicer_settings": {
    "orcaslicer": {
      "generic_id": "GFL99",
      "id": "OGFE04",
      "profile_name": "Elegoo PLA"
    }
  },
  "brand_id": "65026f70-74db-5916-bc7a-63ffc8bff0b2",
  "material_id": "176f6aaf-2154-5a26-9a0a-646e7f5895ce",
  "slug": "pla",
  "material": "PLA",
  "discontinued": false,
  "variants": [
    {
      "id": "52fb7b34-50e9-50d0-a53b-f1a5c517030e",
      "name": "Black",
      "color_hex": "#000000",
      "slug": "black",
      "size_count": 4,
      "path": "variants/black.json"
    }
  ]
}
```

### Variant detail

```text
GET /brands/{brand_slug}/materials/{MATERIAL}/filaments/{filament_slug}/variants/{variant_slug}.json
```

Example:

```text
GET /brands/elegoo/materials/PLA/filaments/pla/variants/black.json
```

Confirmed response shape includes color, traits, and sizes:

```json
{
  "id": "52fb7b34-50e9-50d0-a53b-f1a5c517030e",
  "name": "Black",
  "color_hex": "#000000",
  "traits": {
    "industrially_compostable": true
  },
  "filament_id": "c9923157-23d1-5ea4-93d6-255bdeffc6cc",
  "slug": "black",
  "discontinued": false,
  "sizes": [
    {
      "filament_weight": 1000,
      "diameter": 1.75,
      "id": "ad8629c5-6e1e-5c7f-9622-82533e74b3fc",
      "variant_id": "52fb7b34-50e9-50d0-a53b-f1a5c517030e",
      "discontinued": false,
      "purchase_links": [
        {
          "store_id": "bb7dac98-72db-5693-ba78-dc2bff69b056",
          "url": "https://eu.elegoo.com/products/pla-filament-1-75mm-colored-1kg",
          "id": "93ac02f2-d84b-59bb-a46c-180ba361f92d",
          "size_id": "ad8629c5-6e1e-5c7f-9622-82533e74b3fc",
          "spool_refill": false
        }
      ]
    }
  ]
}
```

## Error behavior

Confirmed missing brand or missing material returns HTTP 404.

The PrintBuddy backend should convert upstream errors into stable API errors instead of leaking raw upstream HTML/text. Suggested behavior:

- 404 from OFDB -> empty result or `not_found`, depending on route intent.
- timeout/network failure -> 503-style structured detail.
- malformed JSON -> 502-style structured detail.

## Mapping to PrintBuddy spool fields

| OFDB field | PrintBuddy field | Notes |
| --- | --- | --- |
| brand detail `name` | `brand` | Prefer display name over slug. |
| material detail `material` | `material` | Already uppercase and compatible with existing spool material values. |
| filament detail `name` | `subtype` or `slicer_filament_name` | For names like `PLA Basic`, subtype can be `Basic`; profile name should use slicer settings when available. |
| filament `min_print_temperature` | `nozzle_temp_min` | Direct mapping. |
| filament `max_print_temperature` | `nozzle_temp_max` | Direct mapping. |
| filament `slicer_settings.orcaslicer.id` | `slicer_filament` | Candidate for Orca/Bambu-style preset ID when present. Validate against existing fallback behavior. |
| filament `slicer_settings.orcaslicer.profile_name` | `slicer_filament_name` | Preferred display name. |
| variant `name` | `color_name` | Direct mapping. |
| variant `color_hex` | `rgba` | Convert `#RRGGBB` to `RRGGBBFF`. |
| selected size `filament_weight` | `label_weight` | Use selected size; default to 1000g if no size selected. |
| variant/filament ids | future `external_*` fields | Recommended for provenance/duplicates. |

## Recommended normalized backend response

PrintBuddy should not expose the raw OFDB hierarchy directly to the modal. Normalize it first:

```json
{
  "source": "openfilamentdatabase",
  "brand": {
    "id": "65026f70-74db-5916-bc7a-63ffc8bff0b2",
    "slug": "elegoo",
    "name": "ELEGOO"
  },
  "material": "PLA",
  "filament": {
    "id": "c9923157-23d1-5ea4-93d6-255bdeffc6cc",
    "slug": "pla",
    "name": "PLA",
    "density": 1.26,
    "min_print_temperature": 190,
    "max_print_temperature": 230,
    "slicer_profile_id": "OGFE04",
    "slicer_profile_name": "Elegoo PLA"
  },
  "variant": {
    "id": "52fb7b34-50e9-50d0-a53b-f1a5c517030e",
    "slug": "black",
    "name": "Black",
    "color_hex": "#000000"
  },
  "sizes": [
    {
      "id": "ad8629c5-6e1e-5c7f-9622-82533e74b3fc",
      "filament_weight": 1000,
      "diameter": 1.75,
      "spool_refill": false
    }
  ],
  "spool_prefill": {
    "brand": "ELEGOO",
    "material": "PLA",
    "subtype": "PLA",
    "color_name": "Black",
    "rgba": "000000FF",
    "label_weight": 1000,
    "nozzle_temp_min": 190,
    "nozzle_temp_max": 230,
    "slicer_filament": "OGFE04",
    "slicer_filament_name": "Elegoo PLA",
    "data_origin": "openfilamentdatabase"
  }
}
```

## PrintBuddy backend proxy endpoints

Phase 2 adds these PrintBuddy endpoints under `/api/v1/open-filament-database`:

```text
GET /brands
GET /brands/{brand_slug}
GET /brands/{brand_slug}/materials/{MATERIAL}/filaments
GET /brands/{brand_slug}/materials/{MATERIAL}/filaments/{filament_slug}
GET /brands/{brand_slug}/materials/{MATERIAL}/filaments/{filament_slug}/variants/{variant_slug}
GET /search?brand={brand_slug}&material={MATERIAL}&q={query}
```

All endpoints are read-only and gated with `inventory:read` when auth is enabled. The `/search` endpoint mirrors OFDB's hierarchy: it searches within a selected brand + material, not globally across the entire database.

Useful smoke tests:

```bash
curl 'http://localhost:8000/api/v1/open-filament-database/search?brand=elegoo&material=PLA&q=matte'
curl 'http://localhost:8000/api/v1/open-filament-database/brands/elegoo/materials/PLA/filaments/pla/variants/black'
```

## Implementation notes

- Add a persisted app setting such as `open_filament_database_enabled: bool = False`.
- Add a backend service with a small HTTP client timeout, e.g. 10 seconds.
- Keep a stable User-Agent such as `PrintBuddy/<version> (+https://github.com/vmhomelab/PrintBuddy)`.
- Backend route should be read-only and require normal auth/read access consistent with inventory/profile settings.
- Do not block manual spool creation if OFDB is disabled or unavailable.
- Selecting OFDB data should pre-fill fields only; users must be able to edit before saving.
- Keep initial scope local inventory. Spoolman import can be a later extension.

## Open implementation decisions

- Whether to add explicit spool provenance columns: recommended fields are `external_source`, `external_id`, `external_url` or equivalent. Current `data_origin` can identify the source but is not enough for robust duplicate detection.
- Whether the first UI should require brand + material filters before searching, or provide a single free-text search that scans cached brand/material/filament data.
- Whether to cache `/brands/index.json` and brand details in memory for a short TTL to avoid slow modal searches.
- Which slicer setting takes priority when multiple exist. For PrintBuddy's Orca/Bambu-heavy flow, `orcaslicer` should be preferred when present.
