# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Write the run manifest for a workflow execution (ADR-0001 §4).

The manifest answers, months later, "what produced this result?" — config,
code version, environment, and the provenance of every input consumed. It is
written on every run, and results without one are not citable.
"""

# NOTE: no `from __future__ import annotations` here. Snakemake prepends a
# preamble to `script:` files to inject the `snakemake` object, which pushes any
# __future__ import out of first position and raises SyntaxError. Unnecessary on
# 3.12 regardless — PEP 604 unions are native.

import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROVENANCE_DIR = Path("resources/_provenance")


def git_revision() -> dict[str, str | bool]:
    """
    Identify the code that produced this run.

    A dirty tree is recorded explicitly rather than hidden: a result produced
    from uncommitted changes is not reproducible, and the manifest should say so
    instead of implying the commit alone explains it.
    """

    def _run(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], capture_output=True, text=True, check=True, timeout=10
            )
            return out.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            return None

    sha = _run("rev-parse", "HEAD")
    status = _run("status", "--porcelain")

    return {
        "sha": sha or "unknown",
        "branch": _run("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        # `status is None` means git failed; treat unknown as dirty, not clean.
        "dirty": True if status is None else bool(status),
    }


def collect_provenance() -> dict[str, dict]:
    """
    Gather the provenance records of every input fetched for this run.

    Embedding them (rather than referencing them) means the manifest stays
    self-describing even if the provenance directory is later rewritten.
    """
    if not PROVENANCE_DIR.is_dir():
        return {}

    records: dict[str, dict] = {}
    for path in sorted(PROVENANCE_DIR.rglob("*.json")):
        try:
            records[str(path.relative_to(PROVENANCE_DIR))] = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            # A corrupt record must not silently vanish from the manifest —
            # record the failure so it is visible in review.
            records[str(path.relative_to(PROVENANCE_DIR))] = {"error": str(exc)}
    return records


def build_manifest(run: str, config: dict, config_hash: str) -> dict:
    return {
        "run_id": run,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "config_hash": config_hash,
        "config": config,
        "git": git_revision(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "inputs": collect_provenance(),
    }


def main() -> None:
    # Injected by Snakemake into the script's globals.
    snake = globals()["snakemake"]

    manifest = build_manifest(
        run=snake.wildcards.run,
        config=dict(snake.config),
        config_hash=snake.params.config_hash,
    )

    out = Path(snake.output[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
