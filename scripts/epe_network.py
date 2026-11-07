# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Read EPE's nodal network (ADR-0026) from a local BaseDadosGT copy into tidy
tables: buses (with state and subsystem), AC lines, transformers and HVDC
links between AC buses.

**EPE data stays local.** Outputs go under git-ignored `resources/epe/`;
only this code and a provenance record are committed. Tests use synthetic
text in the same layout.

Format: PSR's comma-separated `.dat`. Line 1 is `$version=N`, line 2 the
header after `!`, Latin-1. Impedances are % on a 100 MVA base (checked in
`impedance_check`). `Rating` 99999 is a placeholder, read as no rating.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import io
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from epe_interc import provenance

STATES = "AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split()
STATE_IN_NAME = re.compile(r"-(" + "|".join(STATES) + r")\d{3}\b")
# EPE `System` -> this project's subsystem. 6 is Acre-Rondonia (SE/CO since
# 2009), 7 Manaus-Amapa-Roraima (N). Codes not listed are reported, not guessed.
SYSTEM_TO_SUBSYSTEM = {1: "SE_CO", 2: "S", 3: "NE", 4: "N", 6: "SE_CO", 7: "N"}
NO_RATING = 99999.0
BASE_MVA = 100.0


def read_psr(path: Path) -> pd.DataFrame:
    """A PSR comma-separated `.dat`: drop `$version`, take the `!` header."""
    text = path.read_text(encoding="latin-1")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("$version"):
        raise ValueError(f"{path}: no $version line")
    if len(lines) < 2 or not lines[1].startswith("!"):
        raise ValueError(f"{path}: no ! header")
    body = "\n".join([lines[1][1:]] + lines[2:])
    return pd.read_csv(io.StringIO(body))


def bus_states(buses: pd.DataFrame, *branches: pd.DataFrame) -> pd.Series:
    """Code -> state: from the name, else from a neighbour across any of
    `branches` (transformers first, then lines, which reach series-capacitor
    buses), repeated until nothing changes."""
    state = buses.set_index("Code")["Name"].str.extract(STATE_IN_NAME)[0]
    for b in branches:
        state = _propagate(state, b[["BusFromCode", "BusToCode"]])
    return state


def _propagate(state: pd.Series, edges: pd.DataFrame) -> pd.Series:
    while True:
        known = state.dropna()
        a = edges.assign(s=edges["BusToCode"].map(known))[["BusFromCode", "s"]].dropna()
        b = edges.assign(s=edges["BusFromCode"].map(known))[["BusToCode", "s"]].dropna()
        found = (
            pd.concat(
                [a.rename(columns={"BusFromCode": "Code"}), b.rename(columns={"BusToCode": "Code"})]
            )
            .drop_duplicates("Code")
            .set_index("Code")["s"]
        )
        fill = found[found.index.isin(state.index[state.isna()])]
        if fill.empty:
            return state
        state.loc[fill.index] = fill


def tidy_buses(
    buses: pd.DataFrame,
    transformers: pd.DataFrame,
    coords: pd.DataFrame,
    lines: pd.DataFrame | None = None,
) -> pd.DataFrame:
    out = buses[["Code", "Name", "System", "Area", "BaseVoltage"]].copy()
    branches = [transformers] + ([lines] if lines is not None else [])
    out["state"] = out["Code"].map(bus_states(buses, *branches))
    out["subsystem"] = out["System"].map(SYSTEM_TO_SUBSYSTEM)
    xy = coords.drop_duplicates("Code").set_index("Code")
    out["lat"] = out["Code"].map(xy["Latitude"])
    out["lon"] = out["Code"].map(xy["Longitude"])
    return out.rename(
        columns={
            "Code": "bus",
            "Name": "name",
            "System": "system",
            "Area": "area",
            "BaseVoltage": "v_nom_kv",
        }
    )


def tidy_lines(circuits: pd.DataFrame) -> pd.DataFrame:
    rating = circuits["Rating"].where(circuits["Rating"] < NO_RATING)
    return pd.DataFrame(
        {
            "line": circuits["Code"],
            "bus0": circuits["BusFromCode"],
            "bus1": circuits["BusToCode"],
            "r_pct": circuits["Resistance"],
            "x_pct": circuits["Reactance"],
            "b_mvar": circuits["TotalSusceptance"],
            "s_nom_mva": rating,
            "existing_flag": circuits["Existing"],
        }
    )


def tidy_transformers(transformers: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "transformer": transformers["Code"],
            "bus0": transformers["BusFromCode"],
            "bus1": transformers["BusToCode"],
            "r_pct": transformers["R"],
            "x_pct": transformers["X"],
            "existing_flag": transformers["Existing"],
        }
    )


def hvdc_links(
    dc_buses: pd.DataFrame, dc_lines: pd.DataFrame, converters: pd.DataFrame, links: pd.DataFrame
) -> pd.DataFrame:
    """One row per DC line, between the AC buses of its two converters,
    rated at its DC link's base power (MW per pole)."""
    ac_of = converters.drop_duplicates("DCBusCode").set_index("DCBusCode")["ACBusCode"]
    link_of = dc_buses.set_index("Code")["DCLink"]
    power = links.set_index("Code")["BasePower"]
    out = pd.DataFrame(
        {
            "hvdc": dc_lines["Code"],
            "name": dc_lines["Name"],
            "bus0": dc_lines["BusFromCode"].map(ac_of),
            "bus1": dc_lines["BusToCode"].map(ac_of),
            "p_nom_mw": dc_lines["BusFromCode"].map(link_of).map(power),
            "link_name": dc_lines["BusFromCode"].map(link_of).map(links.set_index("Code")["Name"]),
        }
    )
    return out


def impedance_check(lines: pd.DataFrame, buses: pd.DataFrame) -> dict:
    """Median series reactance in ohms per voltage class, reading x as % on
    100 MVA: X_ohm = x_pct / 100 * kV^2 / 100. A plausibility check of the
    unit reading (a typical 500 kV line is tens of ohms)."""
    kv = lines["bus0"].map(buses.set_index("bus")["v_nom_kv"])
    ohm = lines["x_pct"] / 100.0 * kv**2 / BASE_MVA
    frame = pd.DataFrame({"kv": kv, "ohm": ohm})
    return {
        str(int(k)): round(float(g["ohm"].median()), 2)
        for k, g in frame.groupby("kv")
        if k in (138, 230, 345, 440, 500, 525, 765)
    }


def report(
    buses: pd.DataFrame, lines: pd.DataFrame, transformers: pd.DataFrame, hvdc: pd.DataFrame
) -> dict:
    hv = buses["v_nom_kv"].between(230, 800)
    return {
        "buses": len(buses),
        "lines": len(lines),
        "transformers": len(transformers),
        "hvdc_lines": len(hvdc),
        "share_with_state": round(float(buses["state"].notna().mean()), 4),
        "share_with_state_230kv_up": round(float(buses.loc[hv, "state"].notna().mean()), 4),
        "share_with_coordinates": round(float(buses["lat"].notna().mean()), 4),
        "share_with_subsystem": round(float(buses["subsystem"].notna().mean()), 4),
        "unmapped_systems": {
            str(k): int(v)
            for k, v in buses.loc[buses["subsystem"].isna(), "system"].value_counts().items()
        },
        "lines_without_rating": int(lines["s_nom_mva"].isna().sum()),
        "existing_flag_counts": {
            str(k): int(v) for k, v in lines["existing_flag"].value_counts().items()
        },
        "median_line_reactance_ohm_by_kv": impedance_check(lines, buses),
        "hvdc_mw_by_link": hvdc.groupby("link_name")["p_nom_mw"].first().to_dict(),
    }


def main() -> None:
    snake = globals()["snakemake"]
    raw = Path(snake.input.dbus).parent
    r = {
        name: read_psr(raw / f"{name}.dat")
        for name in (
            "dbus",
            "dcirc",
            "dtrans",
            "gcbus",
            "ddcbus",
            "ddcline",
            "dcnvlcc",
            "dmtdclink",
        )
    }
    buses = tidy_buses(r["dbus"], r["dtrans"], r["gcbus"], r["dcirc"])
    lines = tidy_lines(r["dcirc"])
    transformers = tidy_transformers(r["dtrans"])
    hvdc = hvdc_links(r["ddcbus"], r["ddcline"], r["dcnvlcc"], r["dmtdclink"])
    out = Path(snake.output.buses).parent
    out.mkdir(parents=True, exist_ok=True)
    buses.to_csv(snake.output.buses, index=False)
    lines.to_csv(snake.output.lines, index=False)
    transformers.to_csv(snake.output.transformers, index=False)
    hvdc.to_csv(snake.output.hvdc, index=False)
    Path(snake.output.report).write_text(
        json.dumps(report(buses, lines, transformers, hvdc), indent=2, ensure_ascii=False) + "\n"
    )
    # The only committed artefact derived from these files (ADR-0026).
    record = provenance(
        [raw / f"{name}.dat" for name in r],
        repository=snake.params.repository,
        commit=snake.params.commit,
    )
    Path(snake.output.provenance).parent.mkdir(parents=True, exist_ok=True)
    Path(snake.output.provenance).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
