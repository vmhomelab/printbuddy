"""Apply the user's own process-setting choices to an outgoing slice.

Printbuddy's slice modal can edit OrcaSlicer's full process parameter set (layer
height, wall count, supports, speeds — the same tree the desktop slicer shows
under Print Settings). Those edits arrive as a sparse ``{key: value}`` map and
are written into the process JSON that goes out as ``--load-settings``, using
the same mechanism ``_patch_process_support_settings`` (#1881) and
``apply_design_overrides`` (#2622) already use.

Precedence is deliberate and is the reason this runs last: the picked preset is
the base, the source 3MF's support configuration and the designer's own tweaks
layer on top, and an explicit choice the user made in the modal beats all of
them. Anything else would silently discard a setting the user just typed.

Values are normalised to the string forms a process preset actually stores
(``"1"`` for a bool, ``"20%"`` for a percent, a list of strings for the
per-extruder vector options). The frontend already serialises through the option
schema, so this is a second line of defence for clients that don't — the slicer
CLI validates far more strictly than the GUI and a wrongly-typed value fails the
whole slice rather than being coerced.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Config keys are lowercase identifiers. Anything else did not come from the
# option schema, so it cannot be a real process setting.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# A process JSON is a flat string map; nesting a structure inside it produces a
# file the CLI rejects outright.
_ScalarTypes = (str, int, float, bool)


def _normalise_scalar(value: object) -> str | None:
    """Render one scalar the way a process preset stores it, or ``None`` if it
    is not a value a process setting can hold."""
    if isinstance(value, bool):
        # Checked before int on purpose — bool is a subclass of int, and a
        # process JSON spells booleans "1"/"0", never "True"/"False".
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return None


def normalise_process_overrides(overrides: dict[str, object]) -> dict[str, str | list[str]]:
    """Filter and normalise a client-supplied override map.

    Keys that don't look like config keys, and values that a process preset
    cannot hold, are dropped with a warning rather than failing the slice: the
    user's other settings are still worth applying, and a hard failure here
    would be reported as "slicing failed" with no clue which field caused it.
    """
    clean: dict[str, str | list[str]] = {}
    for key, value in overrides.items():
        if not isinstance(key, str) or not _KEY_RE.match(key):
            logger.warning("Ignoring process override with unusable key: %r", key)
            continue

        if isinstance(value, list):
            parts = [_normalise_scalar(v) for v in value]
            if any(p is None for p in parts):
                logger.warning("Ignoring process override %s: list contains a non-scalar entry", key)
                continue
            clean[key] = [p for p in parts if p is not None]
            continue

        scalar = _normalise_scalar(value)
        if scalar is None:
            logger.warning("Ignoring process override %s: unsupported value type %s", key, type(value).__name__)
            continue
        clean[key] = scalar

    return clean


def apply_process_overrides(process_json: str, overrides: dict[str, object]) -> str:
    """Write the user's process settings into the outgoing process JSON.

    Returns ``process_json`` unchanged when there is nothing to apply or the
    JSON is unparseable, so a bad input degrades to a slice with the picked
    preset rather than failing it — matching ``apply_design_overrides``.
    """
    if not overrides:
        return process_json

    clean = normalise_process_overrides(overrides)
    if not clean:
        return process_json

    try:
        process_cfg = json.loads(process_json)
    except json.JSONDecodeError:
        logger.warning("Process preset JSON is unparseable; skipping %d user override(s)", len(clean))
        return process_json
    if not isinstance(process_cfg, dict):
        return process_json

    process_cfg.update(clean)
    logger.info("Applying %d user process override(s): %s", len(clean), sorted(clean))
    return json.dumps(process_cfg)
