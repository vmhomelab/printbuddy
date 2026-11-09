"""Slicer string-list options as plain lists (#3380)."""


def slicer_strings(raw: object) -> list[str]:
    """A slicer string-list option as its non-empty strings.

    Orca Cloud returns a list the way the slicer writes it to its INI files —
    one string of quoted, ``\\``-escaped items joined by ``;``
    (``"Bambu Lab X1 Carbon 0.4 nozzle";"Bambu Lab H2C 0.4 nozzle"``). Left
    quoted, a ``compatible_printers`` name never equals the selected printer
    preset and the SliceModal hides the profile for every printer. A JSON
    array is never INI-encoded, so its items are kept as they are. A string
    the slicer itself can't read counts as no data rather than failing the
    caller.
    """
    if isinstance(raw, list):
        items = [s for s in raw if isinstance(s, str)]
    elif isinstance(raw, str):
        items = unescape_strings_cstyle(raw) or []
    else:
        return []
    return [s for s in items if s.strip()]


def unquote_slicer_items(raw: list) -> list[str]:
    """The string items of a list, with slicer-quoted items decoded.

    Orca Cloud returns some string vectors as a list whose items are still
    quoted (``['"Elegoo Neptune 4 Pro 0.4 nozzle"']``); use this for Orca
    Cloud content only, since a generic JSON array keeps its items as is. An item that starts with ``"`` is read the way the slicer reads its INI
    form (it may hold several ``;``-joined names); one the slicer can't parse
    is kept as is. Other items are kept unchanged, empty ones included.
    """
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        if item.lstrip().startswith('"'):
            decoded = unescape_strings_cstyle(item.strip())
            if decoded is not None:
                out.extend(decoded)
                continue
        out.append(item)
    return out


def first_slicer_string(raw: object) -> str | None:
    """The first non-empty item of a slicer string-list option, stripped.

    Filament profiles store per-extruder options such as ``filament_type`` as
    one-element lists; pre-pick matching only needs the first slot.
    """
    return next((s.strip() for s in slicer_strings(raw)), None)


def unescape_strings_cstyle(text: str) -> list[str] | None:
    """Port of OrcaSlicer's ``unescape_strings_cstyle`` (libslic3r/Config.cpp).

    Unquoted items are read up to ``;`` as is; quoted items decode ``\\n``,
    ``\\r`` and ``\\<char>``. Empty items are kept, so per-extruder positions
    survive. Returns ``None`` where the slicer reports a parse failure: an
    unterminated quote, a trailing ``\\`` inside quotes, or anything but
    spaces, tabs and ``;`` after a closing quote.
    """
    out: list[str] = []
    i, n = 0, len(text)
    if n == 0:
        return out
    while True:
        while text[i] in " \t":
            i += 1
            if i == n:
                return out
        buf: list[str] = []
        if text[i] == '"':
            i += 1
            while i < n and text[i] != '"':
                c = text[i]
                if c == "\\":
                    i += 1
                    if i == n:
                        return None
                    c = {"r": "\r", "n": "\n"}.get(text[i], text[i])
                buf.append(c)
                i += 1
            if i == n:
                return None
            i += 1
        else:
            while i < n and text[i] != ";":
                buf.append(text[i])
                i += 1
        out.append("".join(buf))
        if i == n:
            return out
        while text[i] in " \t":
            i += 1
            if i == n:
                return out
        if text[i] != ";":
            return None
        i += 1
        if i == n:
            out.append("")
            return out
