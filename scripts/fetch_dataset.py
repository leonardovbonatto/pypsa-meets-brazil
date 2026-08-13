# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Snakemake entry point for a single dataset fetch.

Thin by design: all the logic lives in `fetch.py` so it stays importable and
testable, and this file only translates the `snakemake` object into that
call. Rule files hold rules, modules hold logic (see the PR-02 handoff).
"""

# NOTE: no `from __future__ import annotations` — Snakemake's injected preamble
# would push it out of first position and raise SyntaxError. See write_manifest.py.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch import build_record, download, write_record


def main() -> None:
    snake = globals()["snakemake"]

    raw = Path(snake.output.raw)
    download(snake.params.url, raw)

    record = build_record(
        source=snake.params.source,
        dataset=snake.params.dataset,
        source_url=snake.params.url,
        dest=raw,
        format="csv",
    )
    # Write via the rule's declared output path rather than fetch.py's default
    # layout, so Snakemake can see and clean up exactly what it promised.
    out = Path(snake.output.provenance)
    write_record(record, provenance_dir=out.parent.parent)


if __name__ == "__main__":
    main()
