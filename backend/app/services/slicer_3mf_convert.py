"""Per-slice 3MF input normalisation for the slicer pipeline.

Helpers here rewrite the bytes we hand the slicer CLI so known upstream
crash / reject paths don't fire:

- :func:`substitute_unused_plate_filaments` /
  :func:`filaments_for_plate_load` — unused AMS slots don't trip
  BambuStudio's loaded-filament temperature validator; mono-slot plates
  compact to a one-element ``--load-filaments`` list so Orca #12426's
  paint + multi-filament SIGSEGV doesn't force a paint strip.
- :func:`threemf_has_paint_color` / :func:`strip_3mf_paint_color` /
  :func:`extract_3mf_paint_colors` / :func:`reapply_3mf_paint_colors` —
  OrcaSlicer CLI SIGSEGVs on painted multi-filament 3MFs with
  ``--load-filaments`` (upstream #12426). Stripping ``paint_color`` turns
  the file into the "plain.3mf" case that the CLI handles; extract +
  reapply restore face-paint onto a same-topology result 3MF when the
  triangle order is preserved (metadata for desktop reopen — it does
  not put painted multi-colour into the G-code that already sliced
  without paint).
- :func:`extract_3mf_meshes_as_stl` — last-resort geometry export when
  even a paint-stripped 3MF still crashes the CLI on cross-vendor
  re-slices (Bambu → Snapmaker).

Cross-nozzle-class layout is handled by forwarding ``--arrange`` (see
``slicer_api.SlicerApiService.slice_with_profiles`` and
``_run_slicer_with_fallback`` in ``api/routes/library.py``).
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from io import BytesIO

logger = logging.getLogger(__name__)

_PROJECT_SETTINGS_PATH = "Metadata/project_settings.config"
_MODEL_SETTINGS_PATH = "Metadata/model_settings.config"
_SLICE_INFO_PATH = "Metadata/slice_info.config"

# ``paint_color="…"`` on ``<triangle>`` elements — the attribute that
# triggers Orca CLI #12426 when combined with 2+ ``--load-filaments``.
_PAINT_COLOR_ATTR_RE = re.compile(rb'\s*paint_color="[^"]*"')
_PAINT_COLOR_VALUE_RE = re.compile(rb'\bpaint_color="([^"]*)"')
# Match a full ``<triangle …>`` / ``<triangle …/>`` opening so we can
# read or rewrite per-face paint in document order.
_TRIANGLE_TAG_RE = re.compile(rb"<triangle\b[^>]*?/?>", re.IGNORECASE)


def count_plates_in_3mf(zip_bytes: bytes) -> int:
    """Return the number of plates the source 3MF defines, or ``0`` if the
    file isn't a parseable 3MF / has no plate metadata. Used by the
    cross-class slice-all loop (#1493) to know how many ``--slice N``
    calls to dispatch before merging the per-plate outputs back into one
    multi-plate 3MF.
    """
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
            if _MODEL_SETTINGS_PATH not in zf.namelist():
                return 0
            xml = zf.read(_MODEL_SETTINGS_PATH).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError, KeyError):
        return 0
    # Count ``<metadata key="plater_id" value="..."/>`` entries — each
    # ``<plate>`` element carries exactly one. Cheap and tolerant of the
    # full schema (no need to parse the whole XML, which is large and may
    # contain CDATA quirks).
    return len(re.findall(r'<metadata key="plater_id" value="(\d+)"', xml))


def extract_source_printer_model(zip_bytes: bytes) -> str | None:
    """Return the canonical short model code (e.g. ``"X1C"``, ``"H2D"``) for
    the 3MF's embedded ``printer_model`` field, or ``None`` if the input
    isn't a 3MF, has no embedded settings, the field is missing, or the
    model isn't recognised. Canonicalisation goes through
    :func:`normalize_printer_model`, which strips the ``"Bambu Lab "``
    vendor prefix and maps long display names to the short codes that
    :func:`is_dual_nozzle_model` matches against (the raw field is
    ``"Bambu Lab H2D"``, not ``"H2D"``).
    """
    from backend.app.utils.printer_models import normalize_printer_model

    try:
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
            if _PROJECT_SETTINGS_PATH not in zf.namelist():
                return None
            cfg = json.loads(zf.read(_PROJECT_SETTINGS_PATH).decode("utf-8"))
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, OSError, KeyError):
        return None
    if not isinstance(cfg, dict):
        return None
    raw = cfg.get("printer_model")
    if not raw:
        return None
    canonical = normalize_printer_model(str(raw))
    return canonical or None


_PLATE_BLOCK_RE = re.compile(r"<plate>.*?</plate>", re.DOTALL)


def merge_plate_3mfs(
    plate_outputs: list[tuple[int, bytes]],
    source_3mf_bytes: bytes | None = None,
) -> bytes:
    """Combine N single-plate sliced 3MFs into one multi-plate 3MF.

    Used by the cross-class slice-all loop (#1493) where Printbuddy slices
    each plate independently against the target printer (BS CLI's
    ``--arrange`` is project-wide so a single ``--slice 0`` call would
    consolidate every plate's objects onto one bed — the bug this whole
    path exists to work around). Each input is a single-plate 3MF whose
    ``Metadata/plate_N.gcode`` / ``plate_N.json`` / ``plate_N.png``
    entries already carry the right plate index because the BS CLI
    preserves the requested plate number in the output filenames.

    The merge strategy:
    - The first plate's 3MF is the base — its ``project_settings.config``
      (target printer), ``3D/3dmodel.model``, and Auxiliaries images
      carry forward.
    - Per-plate artifacts from the other inputs (``plate_N.gcode``,
      ``plate_N.gcode.md5``, ``plate_N.json``, ``plate_N.png``,
      ``plate_N_small.png``, ``plate_no_light_N.png``, ``top_N.png``,
      ``pick_N.png``) are overlaid into the base.
    - ``slice_info.config`` is re-assembled from each input's single
      ``<plate>`` block so the resulting file lists all N plates.
    - ``source_3mf_bytes``, when supplied, is used as a fallback source
      of per-plate thumbnails (``plate_N.png`` and ``plate_N_small.png``)
      when the sliced outputs don't carry them — BS CLI with ``--arrange``
      regenerates the plate gcode but rarely writes a fresh per-plate
      preview, so without this fallback the merged 3MF would only have
      a cover image for plate 1 (the base 3MF) and the archive page's
      per-plate previews would be blank.

    Returns the merged 3MF bytes. Single-element input is a passthrough.
    Empty input raises ``ValueError``.
    """
    if not plate_outputs:
        raise ValueError("merge_plate_3mfs: at least one plate output required")
    ordered = sorted(plate_outputs, key=lambda p: p[0])

    if len(ordered) == 1:
        return ordered[0][1]

    # Collect each plate's <plate>...</plate> block out of its
    # slice_info.config. The single-plate slice output puts exactly one
    # such block; if a plate's output is missing the section (shouldn't
    # happen on a successful slice, but stay defensive) skip it — better
    # to ship a partial multi-plate 3MF than to fail the whole merge.
    plate_blocks: list[str] = []
    for plate_num, plate_bytes in ordered:
        try:
            with zipfile.ZipFile(BytesIO(plate_bytes), "r") as zf:
                if _SLICE_INFO_PATH not in zf.namelist():
                    continue
                xml = zf.read(_SLICE_INFO_PATH).decode("utf-8", errors="replace")
        except (zipfile.BadZipFile, OSError, KeyError) as exc:
            logger.warning("merge_plate_3mfs: couldn't read plate %d slice_info (%s)", plate_num, exc)
            continue
        match = _PLATE_BLOCK_RE.search(xml)
        if match:
            plate_blocks.append(match.group(0))

    combined_slice_info = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<config>\n"
        "  <header>\n"
        '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
        '    <header_item key="X-BBL-Client-Version" value="02.06.00.51"/>\n'
        "  </header>\n" + "\n".join(f"  {block}" for block in plate_blocks) + "\n</config>\n"
    ).encode("utf-8")

    # Per-plate artifact filenames we lift from each input into the base.
    def _per_plate_entries(n: int) -> set[str]:
        return {
            f"Metadata/plate_{n}.gcode",
            f"Metadata/plate_{n}.gcode.md5",
            f"Metadata/plate_{n}.json",
            f"Metadata/plate_{n}.png",
            f"Metadata/plate_{n}_small.png",
            f"Metadata/plate_no_light_{n}.png",
            f"Metadata/top_{n}.png",
            f"Metadata/pick_{n}.png",
        }

    # When the per-plate slices skip writing ``plate_N.png`` (BS CLI with
    # ``--arrange`` does this — the gcode is fresh but the preview slot
    # is empty), fall back to the source 3MF's stored render of the same
    # plate. The visual layout will differ from the arranged H2D version
    # but a recognisable preview is much better than a blank card.
    def _source_thumbnail_fallback(plate_num: int) -> dict[str, bytes]:
        if source_3mf_bytes is None:
            return {}
        wanted = {
            f"Metadata/plate_{plate_num}.png",
            f"Metadata/plate_{plate_num}_small.png",
        }
        found: dict[str, bytes] = {}
        try:
            with zipfile.ZipFile(BytesIO(source_3mf_bytes), "r") as src_zf:
                for name in src_zf.namelist():
                    if name in wanted:
                        found[name] = src_zf.read(name)
        except (zipfile.BadZipFile, OSError) as exc:
            logger.warning("merge_plate_3mfs: source thumbnail fallback failed (%s)", exc)
        return found

    base_num, base_bytes = ordered[0]
    out_buf = BytesIO()
    base_zip_names: set[str] = set()
    with (
        zipfile.ZipFile(BytesIO(base_bytes), "r") as base_zf,
        zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as out_zf,
    ):
        # Pass 1: emit base entries. Track which per-plate-N thumbnails
        # the base actually had so the fallback pass below can fill in
        # the ones that are missing.
        for item in base_zf.infolist():
            base_zip_names.add(item.filename)
            if item.filename == _SLICE_INFO_PATH:
                out_zf.writestr(item, combined_slice_info)
            else:
                out_zf.writestr(item, base_zf.read(item.filename))

        # Source-thumbnail fallback for the base plate when the slicer
        # didn't write its own preview.
        for name, payload in _source_thumbnail_fallback(base_num).items():
            if name not in base_zip_names:
                out_zf.writestr(name, payload)
                base_zip_names.add(name)

        # Pass 2: overlay per-plate artifacts from the other plates'
        # 3MFs, falling back to the source for any plate-N thumbnails
        # the slicer didn't write.
        for plate_num, plate_bytes in ordered[1:]:
            wanted = _per_plate_entries(plate_num)
            written: set[str] = set()
            try:
                with zipfile.ZipFile(BytesIO(plate_bytes), "r") as plate_zf:
                    for name in plate_zf.namelist():
                        if name in wanted:
                            out_zf.writestr(name, plate_zf.read(name))
                            written.add(name)
            except (zipfile.BadZipFile, OSError) as exc:
                logger.warning(
                    "merge_plate_3mfs: couldn't read plate %d artifacts (%s); skipping",
                    plate_num,
                    exc,
                )
                continue
            for name, payload in _source_thumbnail_fallback(plate_num).items():
                if name not in written and name not in base_zip_names:
                    out_zf.writestr(name, payload)

    return out_buf.getvalue()


def threemf_has_paint_color(zip_bytes: bytes) -> bool:
    """Return True when any ``.model`` entry carries a ``paint_color`` attr.

    Cheap scan — stops at the first hit. Used to decide whether to strip
    paint before ``--load-filaments`` (Orca #12426) or fall through.
    """
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".model"):
                    continue
                try:
                    data = zf.read(name)
                except OSError:
                    continue
                if b"paint_color=" in data:
                    return True
    except (zipfile.BadZipFile, OSError):
        return False
    return False


def strip_3mf_paint_color(zip_bytes: bytes) -> bytes:
    """Return a copy of the 3MF with every ``paint_color="…"`` attribute
    removed from ``.model`` mesh files.

    Turns a painted multi-colour project into the "plain.3mf" shape that
    OrcaSlicer's CLI can slice with ``--load-filaments`` (2+) without
    SIGSEGV (#12426). Per-object default extruder metadata in
    ``model_settings.config`` is preserved, so multi-slot filament
    dropdowns still map to whole objects/parts — only face-paint is lost.

    Returns the original bytes unchanged when no paint attrs are present
    or the input isn't a readable zip.
    """
    try:
        zin = zipfile.ZipFile(BytesIO(zip_bytes), "r")
    except (zipfile.BadZipFile, OSError):
        return zip_bytes

    changed = False
    out = BytesIO()
    try:
        with zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.lower().endswith(".model") and b"paint_color=" in data:
                    stripped = _PAINT_COLOR_ATTR_RE.sub(b"", data)
                    if stripped != data:
                        changed = True
                        data = stripped
                zout.writestr(item, data)
    except (zipfile.BadZipFile, OSError):
        return zip_bytes

    if not changed:
        return zip_bytes
    logger.info(
        "Stripped paint_color attributes from 3MF before slice "
        "(avoids Orca CLI SIGSEGV #12426 with multi-filament --load-filaments)"
    )
    return out.getvalue()


def extract_3mf_paint_colors(zip_bytes: bytes) -> dict[str, list[str | None]] | None:
    """Capture per-triangle ``paint_color`` values from every ``.model`` file.

    Returns a map of ``{model_path: [paint_or_None, …]}`` in document order,
    or ``None`` when the archive has no paint (or isn't a readable zip).
    Used to reapply face-paint onto a same-topology result 3MF after the
    CLI workaround strip (#12426).
    """
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
            paint_map: dict[str, list[str | None]] = {}
            any_paint = False
            for name in zf.namelist():
                if not name.lower().endswith(".model"):
                    continue
                try:
                    data = zf.read(name)
                except OSError:
                    continue
                if b"paint_color=" not in data:
                    continue
                values: list[str | None] = []
                for tag in _TRIANGLE_TAG_RE.finditer(data):
                    m = _PAINT_COLOR_VALUE_RE.search(tag.group(0))
                    if m is None:
                        values.append(None)
                    else:
                        any_paint = True
                        values.append(m.group(1).decode("ascii", errors="replace"))
                if values:
                    paint_map[name] = values
            return paint_map if any_paint else None
    except (zipfile.BadZipFile, OSError):
        return None


def reapply_3mf_paint_colors(
    zip_bytes: bytes,
    paint_map: dict[str, list[str | None]],
) -> bytes:
    """Re-inject previously extracted ``paint_color`` attrs onto matching
    ``.model`` meshes in ``zip_bytes``.

    Only mutates a model file when it still exists and has the same triangle
    count as the saved map (same topology / document order). Skips mismatches
    rather than guessing — STL round-trips and heavily rewritten plates won't
    match. Returns the original bytes when nothing can be restored.
    """
    if not paint_map:
        return zip_bytes
    try:
        zin = zipfile.ZipFile(BytesIO(zip_bytes), "r")
    except (zipfile.BadZipFile, OSError):
        return zip_bytes

    changed = False
    out = BytesIO()
    try:
        with zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            names = set(zin.namelist())
            for item in zin.infolist():
                data = zin.read(item.filename)
                saved = paint_map.get(item.filename)
                if saved and item.filename.lower().endswith(".model"):
                    tags = list(_TRIANGLE_TAG_RE.finditer(data))
                    if len(tags) == len(saved):
                        pieces: list[bytes] = []
                        cursor = 0
                        for tag, paint in zip(tags, saved, strict=True):
                            pieces.append(data[cursor : tag.start()])
                            raw_tag = tag.group(0)
                            # Drop any paint the target already carries, then
                            # restore the saved value (or leave unpainted).
                            cleaned = _PAINT_COLOR_ATTR_RE.sub(b"", raw_tag)
                            if paint is not None:
                                insert = f' paint_color="{paint}"'.encode("ascii")
                                if cleaned.endswith(b"/>"):
                                    cleaned = cleaned[:-2] + insert + b"/>"
                                elif cleaned.endswith(b">"):
                                    cleaned = cleaned[:-1] + insert + b">"
                            pieces.append(cleaned)
                            cursor = tag.end()
                        pieces.append(data[cursor:])
                        new_data = b"".join(pieces)
                        if new_data != data:
                            data = new_data
                            changed = True
                zout.writestr(item, data)
            # Ignore paint entries whose model path disappeared from the
            # result archive — common after STL fallback / plate merge.
            missing = [n for n in paint_map if n not in names]
            if missing:
                logger.debug(
                    "Paint reapply: skipped %d model path(s) absent from result: %s",
                    len(missing),
                    missing[:5],
                )
    except (zipfile.BadZipFile, OSError):
        return zip_bytes

    if not changed:
        return zip_bytes
    logger.info(
        "Reapplied face-paint to %d model file(s) in sliced 3MF "
        "(metadata only — G-code was produced without paint due to Orca #12426)",
        sum(1 for v in paint_map.values() if v),
    )
    return out.getvalue()


_VERTEX_RE = re.compile(
    r'<vertex\s+x="([^"]+)"\s+y="([^"]+)"\s+z="([^"]+)"\s*/>',
    re.IGNORECASE,
)
_TRIANGLE_RE = re.compile(
    r'<triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"',
    re.IGNORECASE,
)


def extract_3mf_meshes_as_stl(zip_bytes: bytes) -> bytes | None:
    """Best-effort: pull triangle meshes out of a 3MF and emit one ASCII STL.

    Used as a last-resort input when the Orca CLI SIGSEGVs on the 3MF
    itself (cross-vendor re-slice of a Bambu project for Snapmaker, etc.).
    Loses paint, plates, and per-object filament assignments — the caller
    must ``--arrange`` the result onto the target bed.

    Returns ``None`` when no triangles can be recovered.
    """
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
            model_names = [n for n in zf.namelist() if n.lower().endswith(".model")]
            if not model_names:
                return None
            facets: list[tuple[tuple[float, float, float], ...]] = []
            for name in model_names:
                try:
                    text = zf.read(name).decode("utf-8", errors="replace")
                except OSError:
                    continue
                vertices: list[tuple[float, float, float]] = []
                for m in _VERTEX_RE.finditer(text):
                    try:
                        vertices.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
                    except ValueError:
                        continue
                if not vertices:
                    continue
                for m in _TRIANGLE_RE.finditer(text):
                    try:
                        i1, i2, i3 = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    except ValueError:
                        continue
                    if max(i1, i2, i3) >= len(vertices):
                        continue
                    facets.append((vertices[i1], vertices[i2], vertices[i3]))
    except (zipfile.BadZipFile, OSError):
        return None

    if not facets:
        return None

    lines = ["solid printbuddy_reslice"]
    for v1, v2, v3 in facets:
        # Zero normal is accepted by Orca/BS — they recompute.
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        lines.append(f"      vertex {v1[0]} {v1[1]} {v1[2]}")
        lines.append(f"      vertex {v2[0]} {v2[1]} {v2[2]}")
        lines.append(f"      vertex {v3[0]} {v3[1]} {v3[2]}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid printbuddy_reslice")
    logger.info(
        "Extracted %d triangles from 3MF as STL for CLI crash fallback",
        len(facets),
    )
    return ("\n".join(lines) + "\n").encode("ascii", errors="ignore")


def _plate_used_extruders(source_3mf_bytes: bytes, plate_id: int) -> set[int] | None:
    """Return the 1-indexed extruder set for ``plate_id``, or ``None`` when
    the source can't be parsed (caller should fail open).
    """
    from backend.app.utils.threemf_tools import extract_plate_extruder_set_from_3mf

    try:
        with zipfile.ZipFile(BytesIO(source_3mf_bytes), "r") as zf:
            return extract_plate_extruder_set_from_3mf(zf, plate_id)
    except (zipfile.BadZipFile, OSError) as exc:
        logger.warning("Plate-filament parse failed (%s); leaving filament list unchanged", exc)
        return None


def substitute_unused_plate_filaments(source_3mf_bytes: bytes, plate_id: int | None, items: list[str]) -> list[str]:
    """Replace any filament-list entry whose 1-indexed slot isn't used by
    ``plate_id`` with the entry at slot 1 (index 0).

    Why: the slice modal lets the user pick a filament profile per slot,
    but each plate in a multi-plate project only uses a subset of those
    slots. The modal labels the unused rows "not used by this plate" yet
    still submits their dropdown values. BambuStudio then validates every
    loaded filament for material compatibility — PLA in a used slot +
    ABS defaulted into an unused slot trips
    "the temperature difference of the filaments used is too large"
    (exit 194), even though the plate's G-code never touches the ABS
    slot. Substituting unused entries with slot 1's filament keeps the
    per-filament array length intact (so the source 3MF's per-slot
    references stay valid) while making the loaded-filament set
    materially homogeneous, so the validator passes.

    The substitution is a no-op when:
    - ``plate_id`` is None or ``<= 0`` (slice-all / unknown — handled
      per-plate by :func:`filaments_for_plate_load` instead),
    - the source isn't a valid 3MF / zip,
    - the source doesn't carry plate-extruder metadata (parse returns
      empty set — treat as "every slot is used", same fallback the
      SliceModal uses),
    - ``items`` has fewer than 2 entries (nothing to substitute).
    """
    if plate_id is None or plate_id <= 0 or len(items) < 2:
        return items
    used = _plate_used_extruders(source_3mf_bytes, plate_id)
    if used is None:
        return items
    if not used:
        # Empty result usually means the source 3MF has no per-object
        # extruder metadata (single-filament unsliced project). Treating
        # "no info" as "every slot is used" matches the SliceModal's
        # fail-open default — better to send the user's picks through
        # than to silently rewrite them.
        return items
    out = list(items)
    substituted = []
    for idx in range(len(out)):
        slot = idx + 1
        if slot not in used:
            substituted.append(slot)
            out[idx] = out[0]
    if substituted:
        logger.info(
            "Substituted slot-1 filament for unused slot(s) %s on plate %s "
            "(avoids loaded-filament temp-spread validator)",
            substituted,
            plate_id,
        )
    return out


def filaments_for_plate_load(
    source_3mf_bytes: bytes,
    plate_id: int | None,
    items: list[str],
) -> list[str]:
    """Filament list to pass as ``--load-filaments`` for one plate.

    Multi-slot plates keep :func:`substitute_unused_plate_filaments`
    behaviour (full-length list, unused slots cloned from slot 1).

    Mono-slot plates (the common multi-plate / one-colour-per-plate case)
    compact to a **one-element** list with that slot's profile. That lets
    the Orca CLI keep face-paint without hitting #12426 (paint + 2+
    ``--load-filaments`` SIGSEGV). When the sole used slot isn't slot 1,
    callers should also remap that plate's object extruders to 1 via
    :func:`remap_plate_extruders_to_one` so the single loaded profile is
    what the objects reference.
    """
    if plate_id is None or plate_id <= 0 or len(items) < 2:
        return items
    used = _plate_used_extruders(source_3mf_bytes, plate_id)
    if used is None or not used:
        return substitute_unused_plate_filaments(source_3mf_bytes, plate_id, items)
    if len(used) >= 2:
        return substitute_unused_plate_filaments(source_3mf_bytes, plate_id, items)

    slot = next(iter(used))
    idx = slot - 1
    if 0 <= idx < len(items):
        chosen = items[idx]
    else:
        chosen = items[0]
    logger.info(
        "Plate %s uses a single filament slot (%s); loading one profile for --load-filaments "
        "(avoids Orca #12426 paint + multi-filament SIGSEGV)",
        plate_id,
        slot,
    )
    return [chosen]


def plate_sole_used_slot(source_3mf_bytes: bytes, plate_id: int) -> int | None:
    """Return the sole 1-indexed extruder used by ``plate_id``, or ``None``
    when the plate is multi-slot / unparseable / empty.
    """
    if plate_id <= 0:
        return None
    used = _plate_used_extruders(source_3mf_bytes, plate_id)
    if used is None or len(used) != 1:
        return None
    return next(iter(used))


def plate_needs_multi_filament_load(
    source_3mf_bytes: bytes,
    plate_id: int,
    filament_slot_count: int,
) -> bool:
    """True when ``plate_id`` actually needs 2+ ``--load-filaments`` entries.

    Used to decide proactive paint-stripping for #12426. Unknown / unparseable
    plates fail open to ``filament_slot_count >= 2`` (same as the old global
    heuristic) so we never keep paint on a multi-slot load by accident.
    """
    if filament_slot_count < 2:
        return False
    used = _plate_used_extruders(source_3mf_bytes, plate_id)
    if used is None:
        return True
    if not used:
        # No per-object metadata — treat as "every submitted slot is live".
        return filament_slot_count >= 2
    return len(used) >= 2


def any_plate_needs_multi_filament_load(
    source_3mf_bytes: bytes,
    plate_count: int,
    filament_slot_count: int,
) -> bool:
    """True when any plate in ``1..plate_count`` needs a multi-filament load."""
    if filament_slot_count < 2 or plate_count < 1:
        return filament_slot_count >= 2
    return any(
        plate_needs_multi_filament_load(source_3mf_bytes, plate_num, filament_slot_count)
        for plate_num in range(1, plate_count + 1)
    )


def remap_plate_extruders_to_one(
    source_3mf_bytes: bytes,
    plate_id: int,
    from_slot: int,
) -> bytes:
    """Rewrite ``model_settings.config`` extruder metadata for objects on
    ``plate_id`` from ``from_slot`` → ``1``.

    Used with :func:`filaments_for_plate_load` when a mono-colour plate's
    sole used slot isn't slot 1: we load a single filament profile (index
    1 for the CLI) and point the plate's objects at it. Paint nibbles are
    left alone — with only one ``--load-filaments`` entry #12426 doesn't
    fire, and the CLI clamps out-of-range paint refs.

    Returns the original bytes unchanged when nothing needs rewriting.
    """
    if from_slot <= 1 or plate_id <= 0:
        return source_3mf_bytes
    try:
        zin = zipfile.ZipFile(BytesIO(source_3mf_bytes), "r")
    except (zipfile.BadZipFile, OSError):
        return source_3mf_bytes

    import xml.etree.ElementTree as ET

    try:
        with zin:
            if _MODEL_SETTINGS_PATH not in zin.namelist():
                return source_3mf_bytes
            try:
                raw = zin.read(_MODEL_SETTINGS_PATH)
                root = ET.fromstring(raw)
            except (ET.ParseError, OSError):
                return source_3mf_bytes

            object_ids: set[str] = set()
            for plate_elem in root.findall(".//plate"):
                plater_id = None
                for meta in plate_elem.findall("metadata"):
                    if meta.get("key") == "plater_id":
                        try:
                            plater_id = int(meta.get("value", ""))
                        except (ValueError, TypeError):
                            plater_id = None
                        break
                if plater_id != plate_id:
                    continue
                for inst in plate_elem.findall("model_instance"):
                    for inst_meta in inst.findall("metadata"):
                        if inst_meta.get("key") == "object_id":
                            oid = inst_meta.get("value")
                            if oid:
                                object_ids.add(oid)

            if not object_ids:
                return source_3mf_bytes

            changed = False
            from_str = str(from_slot)
            for obj_elem in root.findall(".//object"):
                if obj_elem.get("id") not in object_ids:
                    continue
                for meta in obj_elem.findall("metadata"):
                    if meta.get("key") == "extruder" and meta.get("value") == from_str:
                        meta.set("value", "1")
                        changed = True
                for part_elem in obj_elem.findall(".//part"):
                    for meta in part_elem.findall("metadata"):
                        if meta.get("key") == "extruder" and meta.get("value") == from_str:
                            meta.set("value", "1")
                            changed = True

            if not changed:
                return source_3mf_bytes

            new_settings = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            out = BytesIO()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = new_settings if item.filename == _MODEL_SETTINGS_PATH else zin.read(item.filename)
                    zout.writestr(item, data)
            logger.info(
                "Remapped plate %s object extruders %s→1 for single-filament load",
                plate_id,
                from_slot,
            )
            return out.getvalue()
    except (zipfile.BadZipFile, OSError):
        return source_3mf_bytes
