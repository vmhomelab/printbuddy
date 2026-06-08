"""Repository-wide guard against legacy upstream identity strings."""

from __future__ import annotations

import subprocess
from pathlib import Path


LEGACY_TERMS = ("bambu" + "ddy", "Bambu" + "ddy", "BAMBU" + "DDY", "ma" + "ziggy")


def test_tracked_text_files_do_not_contain_legacy_identity_strings() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        ["git", "grep", "-n", "-I", *sum((["-e", term] for term in LEGACY_TERMS), [])],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode in {0, 1}, result.stderr
    assert result.stdout == ""
