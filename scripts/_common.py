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


def snapshot_year_months(cfg: dict) -> list[tuple[int, int]]:
    """
    (year, month) pairs spanned by `snapshots.start`..`snapshots.end`, inclusive.

    Some ONS datasets (`fator_capacidade`, from 2022 onward) publish one file
    per month rather than per year - this is the month-level analogue of
    `snapshot_years()`, for the same reason: derive it from the snapshot
    range instead of carrying a separate list that could drift out of sync.
    """
    start_year, start_month = (
        int(cfg["snapshots"]["start"][:4]),
        int(cfg["snapshots"]["start"][5:7]),
    )
    end_year, end_month = int(cfg["snapshots"]["end"][:4]), int(cfg["snapshots"]["end"][5:7])

    pairs = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        pairs.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return pairs


def inflow_history_years(cfg: dict, dataset: str = "ena_subsistema") -> list[int]:
    """
    Calendar years spanned by `sources.ons.<dataset>.years.start`..`end`.

    Deliberately NOT derived from `snapshots.start`/`end` like `snapshot_years()`:
    PAR(p) needs a long historical inflow record for persistence and drought
    statistics (PRIMER Sec 4.7, ADR-0005), independent of whichever single year
    T0 happens to be modelling. The two ranges are allowed to disagree.

    Shared by both `ena_subsistema` (ADR-0005 stage 1b) and `ear_subsistema`
    (stage 1e, reservoir capacity) - the same historical-window need, a
    different dataset each carries in its own `sources.ons.<dataset>.years`
    key rather than a shared one, so each remains independently changeable.
    """
    years = cfg["sources"]["ons"][dataset]["years"]
    return list(range(years["start"], years["end"] + 1))
