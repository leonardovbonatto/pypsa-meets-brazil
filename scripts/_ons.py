# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Helpers shared across ONS connector/build scripts.

`id_subsistema` conventions are the same across every ONS dataset this
project consumes so far (`curva_carga`, `capacidade_geracao`, ...) - the
mapping belongs here once, not copied into each build script.
"""

from __future__ import annotations

import pandas as pd

# ONS labels the combined Southeast/Centre-West subsystem SE / SUDESTE; the
# sector, and this project's config, write it SE_CO. Everything else matches.
SUBSYSTEM_MAP = {"N": "N", "NE": "NE", "S": "S", "SE": "SE_CO"}

# PY: the Paraguay-frequency (50 Hz) side of the binational Itaipu plant.
# Present in generation/capacity datasets (not in curva_carga). It feeds
# Paraguay's grid, not Brazil's 60 Hz SIN - Brazil's own 60 Hz share of
# Itaipu is a separate set of rows already counted under SE. Confirmed by
# the plant naming ("ITAIPU 50 HZ"), not just inferred from the code. See
# docs/handoffs/PR-07-ons-capacity-connector.md and the capacidade_geracao
# data dictionary. Known and excluded, not unmapped/erroneous data - must
# not raise `map_subsystems()`'s "unmapped code" error.
EXCLUDED_SUBSYSTEM_CODES = {"PY"}


def map_subsystems(df: pd.DataFrame, *, column: str = "id_subsistema") -> pd.DataFrame:
    """
    Map ONS subsystem codes onto this project's config labels.

    Rows with an excluded-but-known code (currently just PY) are dropped.
    Anything neither mapped nor excluded raises - that is either upstream
    schema drift or a new subsystem code this project hasn't looked at yet,
    and either way should fail loudly rather than pass through unmapped.
    """
    codes = set(df[column])
    unknown = codes - set(SUBSYSTEM_MAP) - EXCLUDED_SUBSYSTEM_CODES
    if unknown:
        raise ValueError(f"unmapped ONS subsystem code(s): {sorted(unknown)}")

    mapped = df[df[column].isin(SUBSYSTEM_MAP)].copy()
    mapped["subsystem"] = mapped[column].map(SUBSYSTEM_MAP)
    return mapped
