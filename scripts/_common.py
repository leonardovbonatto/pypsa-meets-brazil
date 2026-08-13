# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Helpers shared by rule files and scripts.

Logic lives here rather than in `rules/*.smk` so it is importable and testable:
Snakemake files are for rules, not for functions.
"""

from __future__ import annotations

import hashlib
import json


def config_hash(cfg: dict) -> str:
    """
    Stable sha256 of the resolved configuration.

    Keys are sorted so the hash depends on config *content*, not on YAML key
    order or merge sequence. Two runs sharing a hash consumed the same settings,
    which is what makes a result attributable.
    """
    payload = json.dumps(cfg, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_id(cfg: dict) -> str:
    """
    Directory name for this run's results.

    An explicit `run_name` wins, so a human can label an experiment. Otherwise
    the tier plus a short config hash keeps concurrent runs from colliding while
    staying readable in `results/`.
    """
    if name := cfg.get("run_name"):
        return str(name)
    return f"{cfg['tier']}-{config_hash(cfg)[:8]}"


def snapshot_years(cfg: dict) -> list[int]:
    """
    Calendar years spanned by `snapshots.start`..`snapshots.end`, inclusive.

    Fetch and build rules derive which yearly files they need from this
    instead of carrying a separate `years:` list that could silently drift
    out of sync with the snapshot range actually being modelled.
    """
    start_year = int(cfg["snapshots"]["start"][:4])
    end_year = int(cfg["snapshots"]["end"][:4])
    return list(range(start_year, end_year + 1))
