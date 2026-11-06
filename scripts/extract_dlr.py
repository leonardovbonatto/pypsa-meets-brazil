# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Extract the tables T1 uses from DLR's open Brazilian dataset (ADR-0022).

The Zenodo zip nests every table under one root folder whose numbered
sub-folders have spaces in their names. This copies the tables T1 needs
to stable, space-free paths under resources/dlr/, so rules can name them.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import zipfile
from pathlib import Path

ROOT = "Deng_2022_after_revision_Brazilian_power_system_open_data/"

# published path in the zip (under ROOT) -> output key in the rule
TABLES = {
    "grid_operation": "2 Aggregated grid network topology/"
    "EPEWebmap_equivalent_grid_aggregate_by_state_only_operation.csv",
    "load_2020": "7 Electricity load profiles/distribute_by_consumption/"
    "Hourly_electricity_demand_per_state_2020.csv",
    "plants_2020": "6 Power plants/ANEEL_powerplants_per_state_per_type_reference_year_2020.csv",
}


def extract(zip_path: Path, outputs: dict[str, Path]) -> None:
    """Write each TABLES entry to its output path; raise if one is missing."""
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for key, inner in TABLES.items():
            member = ROOT + inner
            if member not in names:
                raise ValueError(f"{member!r} is not in {zip_path}")
            out = outputs[key]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(member))


def main() -> None:
    snake = globals()["snakemake"]
    extract(Path(snake.input.zip), {key: Path(getattr(snake.output, key)) for key in TABLES})


if __name__ == "__main__":
    main()
