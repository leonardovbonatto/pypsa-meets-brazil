# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Meta checks for CI (ADR-0001): a code PR touches the changelog, every
committed provenance record has the shape `fetch.py` writes and
`write_manifest.py` expects, and ADR numbers under `docs/decisions/` are
unique. Each failure names the offending file, so a red build is a lead, not
a puzzle.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Not run as part of a package — make sibling `scripts/` modules importable
# regardless of the caller's cwd, same as `rules/common.smk` does for rules.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch import RECORD_KEYS

CHANGELOG = Path("CHANGELOG.md")
DECISIONS_DIR = Path("docs/decisions")
PROVENANCE_DIR = Path("resources/_provenance")

# Paths whose changes require a changelog entry. Docs-only and CI-only PRs
# are exempt by omission — they don't change what the project *does*.
CODE_PREFIXES = ("scripts/", "rules/", "config/")
CODE_PATHS = {"Snakefile"}

ADR_PATTERN = re.compile(r"^ADR-(\d{4})-.+\.md$")


def changed_files(base: str, head: str = "HEAD") -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def check_changelog(files: list[str]) -> str | None:
    """None means ok; otherwise the failure message."""
    touches_code = any(f.startswith(CODE_PREFIXES) or f in CODE_PATHS for f in files)
    if touches_code and "CHANGELOG.md" not in files:
        return (
            "code changed but CHANGELOG.md was not updated "
            "(add an [Unreleased] entry, or apply the 'no-changelog' label)"
        )
    return None


def check_provenance_records(provenance_dir: Path = PROVENANCE_DIR) -> list[str]:
    errors = []
    if not provenance_dir.is_dir():
        return errors
    for path in sorted(provenance_dir.rglob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: invalid JSON ({exc})")
            continue
        missing = RECORD_KEYS - set(record)
        if missing:
            errors.append(f"{path}: missing keys {sorted(missing)}")
    return errors


def check_adr_numbering(decisions_dir: Path = DECISIONS_DIR) -> list[str]:
    errors = []
    seen: dict[str, Path] = {}
    for path in sorted(decisions_dir.glob("ADR-*.md")):
        match = ADR_PATTERN.match(path.name)
        if not match:
            errors.append(f"{path}: filename does not match ADR-NNNN-slug.md")
            continue
        number = match.group(1)
        if number in seen:
            errors.append(f"{path}: duplicate ADR number {number} (also {seen[number]})")
        seen[number] = path
    return errors


def main() -> int:
    errors: list[str] = []

    if os.environ.get("META_SKIP_CHANGELOG") != "true":
        base = os.environ.get("META_BASE_REF", "origin/main")
        if msg := check_changelog(changed_files(base)):
            errors.append(msg)

    errors += [f"provenance: {e}" for e in check_provenance_records()]
    errors += [f"adr: {e}" for e in check_adr_numbering()]

    if errors:
        print("meta checks failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("meta checks ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
