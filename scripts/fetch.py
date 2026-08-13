# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Fetch a dataset from an upstream URL and record its provenance (ADR-0001, L3).

Every fetch writes a small JSON record under `resources/_provenance/<source>/`
so a later session — or `write_manifest.collect_provenance()` — can answer
"which vintage of upstream data produced this result?" without re-downloading
or re-reading anything. This module is the one place that logic lives; data
connector scripts (one per dataset) call `fetch()` and do nothing else with
the network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

PROVENANCE_DIR = Path("resources/_provenance")
CHUNK_SIZE = 1 << 20  # 1 MiB

# Required by `check_meta.py`'s provenance validation — keep the two in sync.
RECORD_KEYS = {
    "source",
    "dataset",
    "source_url",
    "retrieved",
    "format",
    "sha256",
    "byte_size",
    "row_count",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_count(path: Path, *, format: str) -> int | None:
    """
    Best-effort data-row count, excluding the header.

    Only meaningful for line-delimited formats. Fixed-width decks and
    geodatabases return None rather than a number that looks precise and
    isn't.
    """
    if format not in {"csv", "tsv"}:
        return None
    with path.open("rb") as f:
        lines = sum(1 for _ in f)
    return max(lines - 1, 0)


def download(url: str, dest: Path, *, timeout: float = 60.0) -> None:
    """Stream `url` to `dest`, creating parent directories as needed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with dest.open("wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)


def build_record(
    *,
    source: str,
    dataset: str,
    source_url: str,
    dest: Path,
    format: str,
    retrieved: datetime | None = None,
) -> dict[str, Any]:
    """
    Assemble the provenance record for one fetched file.

    Every field is either measured from the file on disk or supplied by the
    caller — nothing here is inferred or guessed, which is what makes the
    record trustworthy months later.
    """
    return {
        "source": source,
        "dataset": dataset,
        "source_url": source_url,
        "retrieved": (retrieved or datetime.now(UTC)).isoformat(timespec="seconds"),
        "format": format,
        "sha256": sha256_file(dest),
        "byte_size": dest.stat().st_size,
        "row_count": row_count(dest, format=format),
    }


def write_record(record: dict[str, Any], *, provenance_dir: Path | None = None) -> Path:
    # Resolved at call time (not as a default argument) so tests can
    # monkeypatch the module-level PROVENANCE_DIR, same pattern as
    # write_manifest.collect_provenance().
    out = (provenance_dir or PROVENANCE_DIR) / record["source"] / f"{record['dataset']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def fetch(*, source: str, dataset: str, url: str, dest: Path, format: str) -> dict[str, Any]:
    """Download, then record. The one entry point connector scripts call."""
    download(url, dest)
    record = build_record(source=source, dataset=dataset, source_url=url, dest=dest, format=format)
    write_record(record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Publisher, e.g. 'ons', 'aneel'.")
    parser.add_argument("--dataset", required=True, help="Dataset slug, e.g. 'carga_verificada'.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--dest", required=True, type=Path, help="Where to save the raw file.")
    parser.add_argument("--format", required=True, choices=["csv", "tsv", "xlsx", "zip", "other"])
    args = parser.parse_args()

    record = fetch(
        source=args.source, dataset=args.dataset, url=args.url, dest=args.dest, format=args.format
    )
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
