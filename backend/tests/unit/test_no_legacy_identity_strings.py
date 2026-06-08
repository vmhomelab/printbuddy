"""Repository-wide guard against legacy upstream identity strings."""

from __future__ import annotations

from pathlib import Path

LEGACY_TERMS = ("bambu" + "ddy", "Bambu" + "ddy", "BAMBU" + "DDY", "ma" + "ziggy")
EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "dist",
    "htmlcov",
    "node_modules",
    "__pycache__",
}
EXCLUDED_FILES = {
    ".coverage",
}


def _is_text_file(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\0" not in chunk


def test_tracked_text_files_do_not_contain_legacy_identity_strings() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    matches: list[str] = []

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in EXCLUDED_FILES or any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if not _is_text_file(path):
            continue

        rel_path = path.relative_to(repo_root)
        for line_number, line in enumerate(path.read_text(errors="ignore").splitlines(), start=1):
            if any(term in line for term in LEGACY_TERMS):
                matches.append(f"{rel_path}:{line_number}:{line}")

    assert matches == []
