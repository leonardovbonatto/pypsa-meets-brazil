# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Where EPE's base places plants and load (ADR-0026, PR-76): per-bus weights
used to spread 2024 energy over the T3 buses. EPE gives the geography only;
capacities and load in the model stay ONS 2024.

- Plants: `busconnection.dat` ties (system, plant type H/T/R, plant code)
  to a bus. Capacity from `chidro<sys>` (hydro, `Pot`), `ctermi<sys>`
  (thermal, `PotIns`) and `cgnd<sys>` (renewables and small plants,
  `PotIns`, typed by `TechTyp`: 1 wind, 2 solar, 3 biomass and small
  thermal, 4 small hydro, 0 other). Angra's thermal entries mark nuclear.
- Load: `dload.dat` ties each load point to a bus; `loadp_b004m.dat` gives
  active power per load block. The base entry (date 1900/01/01) averaged
  over its blocks.

The plant files are fixed-width with blank fields, so whitespace splitting
shifts columns. A field is cut by its header marker; numbers are
right-aligned, so the cut ends at the marker's end and starts after the
previous marker.

EPE data stays local: inputs and outputs under ~/epe_local and resources/epe/.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from epe_network import read_psr

TECH = {1: "wind", 2: "solar", 3: "thermal_small", 4: "hydro_small", 0: "other"}
NUCLEAR_NAME = re.compile(r"ANGRA", re.IGNORECASE)
BASE_LOAD_DATE = "1900/01/01"


def fixed_width(text: str, fields: dict[str, str]) -> pd.DataFrame:
    """Rows of a PSR fixed-width file. `fields` maps an output column to the
    header marker it is cut under (e.g. {"code": "NUM", "pot": "....Pot"}).
    The header is the first `!` line holding every marker."""
    lines = text.splitlines()
    header = next(
        (ln for ln in lines if ln.startswith("!") and all(m in ln for m in fields.values())), None
    )
    if header is None:
        raise ValueError(f"no header with markers {list(fields.values())}")
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", " " + header[1:])]
    out = {}
    for col, marker in fields.items():
        idx = next(i for i, (a, b) in enumerate(spans) if (" " + header[1:])[a:b] == marker)
        start = spans[idx - 1][1] if idx > 0 else 0
        out[col] = (start, spans[idx][1])
    rows = []
    for ln in lines:
        if not ln.strip() or ln.startswith(("!", "$")):
            continue
        rows.append({col: ln[a:b].strip() for col, (a, b) in out.items()})
    return pd.DataFrame(rows)


def plant_capacity(raw: Path, systems: list[str]) -> pd.DataFrame:
    """(system, type, code) -> name, capacity MW, carrier."""
    parts = []
    for s in systems:
        for kind, prefix, fields in (
            ("H", "chidro", {"code": "NUM", "name": "...Nombre...", "mw": "....Pot"}),
            ("T", "ctermi", {"code": "Num", "name": "...Nombre...", "mw": ".PotIns"}),
            (
                "R",
                "cgnd",
                {"code": "Num", "name": "Name........", "mw": ".PotIns", "tech": "TechTyp"},
            ),
        ):
            path = raw / f"{prefix}{s}.dat"
            if not path.exists():
                continue
            df = fixed_width(path.read_text(encoding="latin-1"), fields)
            df = df.assign(system=s, type=kind)
            parts.append(df)
    plants = pd.concat(parts, ignore_index=True)
    plants["code"] = pd.to_numeric(plants["code"], errors="coerce")
    plants["mw"] = pd.to_numeric(plants["mw"], errors="coerce").fillna(0.0)
    tech = pd.to_numeric(plants.get("tech"), errors="coerce")
    carrier = pd.Series("hydro", index=plants.index).where(plants["type"] == "H", "thermal")
    carrier = carrier.where(plants["type"] != "R", tech.map(TECH).fillna("other"))
    carrier = carrier.where(
        ~((plants["type"] == "T") & plants["name"].str.contains(NUCLEAR_NAME)), "nuclear"
    )
    return plants.assign(carrier=carrier).dropna(subset=["code"])


def plant_weights(connection: pd.DataFrame, plants: pd.DataFrame) -> pd.DataFrame:
    """bus -> carrier -> MW of EPE plants connected there."""
    joined = connection.merge(
        plants,
        left_on=["SystemId", "PlantType", "PlantCode"],
        right_on=["system", "type", "code"],
        how="inner",
    )
    return (
        joined.groupby(["BusCode", "carrier"], as_index=False)["mw"]
        .sum()
        .rename(columns={"BusCode": "bus", "mw": "weight_mw"})
    )


def load_weights(loads: pd.DataFrame, loadp: pd.DataFrame) -> pd.DataFrame:
    """bus -> base-case active load MW, averaged over load blocks."""
    base = loadp[loadp["Date"] == BASE_LOAD_DATE]
    mean = base.groupby("code")["Pp"].mean()
    out = loads.assign(weight_mw=loads["Code"].map(mean).fillna(0.0))
    return (
        out.groupby("BusCode", as_index=False)["weight_mw"].sum().rename(columns={"BusCode": "bus"})
    )


def main() -> None:
    snake = globals()["snakemake"]
    raw = Path(snake.input.busconnection).parent
    connection = read_psr(Path(snake.input.busconnection))
    plants = plant_capacity(raw, sorted(connection["SystemId"].unique()))
    gen = plant_weights(connection, plants)
    load = load_weights(read_psr(Path(snake.input.dload)), read_psr(Path(snake.input.loadp)))
    Path(snake.output.generation).parent.mkdir(parents=True, exist_ok=True)
    gen.to_csv(snake.output.generation, index=False)
    load.to_csv(snake.output.load, index=False)
    plants.groupby(["type", "carrier"])["mw"].agg(["count", "sum"]).round(0).to_csv(
        snake.output.summary
    )


if __name__ == "__main__":
    main()
