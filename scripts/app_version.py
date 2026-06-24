#!/usr/bin/env python3
"""Read, validate, and update Printbuddy's APP_VERSION constant."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "backend" / "app" / "core" / "config.py"
APP_VERSION_RE = re.compile(r'^(APP_VERSION\s*=\s*")([^"]+)(")$', re.MULTILINE)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:\.\d+)?(?:[A-Za-z]+\d+)?$")


def read_version(path: Path = CONFIG_PATH) -> str:
    content = path.read_text(encoding="utf-8")
    match = APP_VERSION_RE.search(content)
    if not match:
        raise SystemExit(f"Could not find APP_VERSION in {path}")
    return match.group(2)


def validate_version(version: str) -> None:
    if version.startswith("v"):
        version = version[1:]
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(
            "Invalid version. Expected forms like 0.2.4, 0.2.4.8, or 0.2.5b1 "
            f"without a leading v; got {version!r}"
        )


def write_version(version: str, path: Path = CONFIG_PATH) -> bool:
    version = version.removeprefix("v")
    validate_version(version)
    content = path.read_text(encoding="utf-8")
    new_content, count = APP_VERSION_RE.subn(rf"\g<1>{version}\g<3>", content, count=1)
    if count != 1:
        raise SystemExit(f"Could not update APP_VERSION in {path}")
    if new_content == content:
        return False
    path.write_text(new_content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--print", action="store_true", help="Print the current APP_VERSION")
    group.add_argument("--set", metavar="VERSION", help="Set APP_VERSION to VERSION")
    group.add_argument("--expected", metavar="VERSION", help="Assert APP_VERSION equals VERSION")
    args = parser.parse_args()

    if args.print:
        print(read_version())
        return 0

    if args.set:
        changed = write_version(args.set)
        print(f"APP_VERSION {'updated to' if changed else 'already'} {args.set.removeprefix('v')}")
        return 0

    expected = args.expected.removeprefix("v")
    validate_version(expected)
    actual = read_version()
    if actual != expected:
        print(f"APP_VERSION mismatch: expected {expected}, found {actual}", file=sys.stderr)
        return 1
    print(f"APP_VERSION OK: {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
