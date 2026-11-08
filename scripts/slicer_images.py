#!/usr/bin/env python3
"""Derive the published slicer-sidecar image tags from slicer-api/.env.example.

``slicer-api/.env.example`` is the single place where the sidecar source
revision (``SLICER_API_BUILD_CONTEXT``) and the bundled slicer versions
(``BAMBU_VERSION`` / ``ORCA_VERSION``) are pinned. The images published to
Docker Hub are tagged ``<slicer version>-<short sidecar revision>``, e.g.
``docker.io/vmhomelabde/printbuddy-bambu-studio-api:02.08.02.61-661cd47``.
Both compose files use the moving ``:latest`` tag (moved by pushes to main),
like the Printbuddy image itself, so ``docker compose pull`` and the in-app
updater keep the sidecar current. The backend's
``EXPECTED_SIDECAR_REVISION`` must equal the pinned revision: Printbuddy
compares it with the revision a running sidecar reports and warns when the
sidecar is outdated.

Usage:
  scripts/slicer_images.py --github-output   # write values for GitHub Actions
  scripts/slicer_images.py --check           # verify every reference is in sync
  scripts/slicer_images.py                   # print the values
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / "slicer-api" / ".env.example"
SLICER_COMPOSE = ROOT / "slicer-api" / "docker-compose.yml"
MAIN_COMPOSE = ROOT / "docker-compose.yml"
SLICER_API_SERVICE = ROOT / "backend" / "app" / "services" / "slicer_api.py"

REGISTRY = "docker.io/vmhomelabde"
BAMBU_IMAGE = "printbuddy-bambu-studio-api"
ORCA_IMAGE = "printbuddy-orca-slicer-api"
SIDECAR_REPO = "vmhomelab/orca-slicer-api"

_ENV_LINE = re.compile(r"^([A-Z0-9_]+)=(.*)$")
_CONTEXT = re.compile(r"^https://github\.com/(?P<repo>[\w.-]+/[\w.-]+?)(?:\.git)?#(?P<rev>[0-9a-f]{40})$")
_VERSION = re.compile(r"^[0-9][0-9.]*$")


def read_env(path: Path = ENV_EXAMPLE) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ENV_LINE.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def derive(env: dict[str, str]) -> dict[str, str]:
    context = env.get("SLICER_API_BUILD_CONTEXT", "")
    match = _CONTEXT.match(context)
    if not match:
        raise SystemExit(
            f"SLICER_API_BUILD_CONTEXT must be https://github.com/<owner>/<repo>.git#<40-char commit>, got {context!r}"
        )
    if match.group("repo") != SIDECAR_REPO:
        raise SystemExit(f"SLICER_API_BUILD_CONTEXT must point at {SIDECAR_REPO}, got {match.group('repo')!r}")
    bambu = env.get("BAMBU_VERSION", "")
    orca = env.get("ORCA_VERSION", "")
    for name, value in (("BAMBU_VERSION", bambu), ("ORCA_VERSION", orca)):
        if not _VERSION.match(value):
            raise SystemExit(f"{name} must be a plain version number, got {value!r}")
    revision = match.group("rev")
    short = revision[:7]
    return {
        "sidecar_repo": SIDECAR_REPO,
        "sidecar_revision": revision,
        "sidecar_revision_short": short,
        "bambu_version": bambu,
        "orca_version": orca,
        "bambu_image": f"{REGISTRY}/{BAMBU_IMAGE}",
        "orca_image": f"{REGISTRY}/{ORCA_IMAGE}",
        "bambu_tag": f"{bambu}-{short}",
        "orca_tag": f"{orca}-{short}",
        "bambu_ref": f"{REGISTRY}/{BAMBU_IMAGE}:{bambu}-{short}",
        "orca_ref": f"{REGISTRY}/{ORCA_IMAGE}:{orca}-{short}",
    }


def check(values: dict[str, str], env: dict[str, str]) -> list[str]:
    """Return mismatches between the derived image refs and their references."""
    problems: list[str] = []
    latest = {
        "BAMBU_STUDIO_API_IMAGE": f"{REGISTRY}/{BAMBU_IMAGE}:latest",
        "ORCA_SLICER_API_IMAGE": f"{REGISTRY}/{ORCA_IMAGE}:latest",
    }
    for key, ref in latest.items():
        if env.get(key) != ref:
            problems.append(f"{ENV_EXAMPLE.relative_to(ROOT)}: {key} should be {ref}, is {env.get(key)!r}")

    slicer_compose = SLICER_COMPOSE.read_text(encoding="utf-8")
    compose_defaults = {
        **latest,
        "SLICER_API_BUILD_CONTEXT": env["SLICER_API_BUILD_CONTEXT"],
        "SIDECAR_REVISION": values["sidecar_revision"],
        "BAMBU_VERSION": values["bambu_version"],
        "ORCA_VERSION": values["orca_version"],
    }
    for key, value in compose_defaults.items():
        defaults = set(re.findall(rf"\$\{{{key}:-([^}}]*)\}}", slicer_compose))
        if defaults != {value}:
            problems.append(
                f"{SLICER_COMPOSE.relative_to(ROOT)}: every ${{{key}:-...}} default should be {value}, "
                f"found {sorted(defaults) or 'none'}"
            )

    service = SLICER_API_SERVICE.read_text(encoding="utf-8")
    expected = re.findall(r'^EXPECTED_SIDECAR_REVISION = "([0-9a-f]+)"$', service, re.MULTILINE)
    if expected != [values["sidecar_revision"]]:
        problems.append(
            f"{SLICER_API_SERVICE.relative_to(ROOT)}: EXPECTED_SIDECAR_REVISION should be "
            f"{values['sidecar_revision']}, found {expected or 'none'}"
        )

    # The main docker-compose.yml tracks :latest, like the Printbuddy image
    # itself; only the image names are checked there.
    main_compose = MAIN_COMPOSE.read_text(encoding="utf-8")
    for image_name in (BAMBU_IMAGE, ORCA_IMAGE):
        expected = f"{REGISTRY}/{image_name}:latest"
        found = re.findall(rf"{re.escape(REGISTRY)}/{image_name}:[\w.-]+", main_compose)
        if not found:
            problems.append(f"{MAIN_COMPOSE.relative_to(ROOT)}: no {image_name} image reference found")
        problems.extend(
            f"{MAIN_COMPOSE.relative_to(ROOT)}: {other} should be {expected}" for other in found if other != expected
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if any image reference is out of sync")
    parser.add_argument("--github-output", action="store_true", help="append the values to $GITHUB_OUTPUT")
    args = parser.parse_args(argv)

    env = read_env()
    values = derive(env)

    if args.check:
        problems = check(values, env)
        if problems:
            print("Slicer sidecar image references are out of sync:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(
            f"Slicer sidecar references match revision {values['sidecar_revision_short']} "
            f"(published as {values['bambu_ref']} and {values['orca_ref']}; compose files use :latest)."
        )
        return 0

    if args.github_output:
        output = os.environ.get("GITHUB_OUTPUT")
        if not output:
            raise SystemExit("GITHUB_OUTPUT is not set")
        with open(output, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
        return 0

    for key, value in values.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
