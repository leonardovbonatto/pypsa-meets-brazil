# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0020's Phase 1 gate scoring."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import pandas as pd
import pypsa
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load("check_phase1_gate", REPO_ROOT / "scripts" / "check_phase1_gate.py")
logging.getLogger("pypsa").setLevel(logging.WARNING)

HOURS = pd.date_range("2024-01-01", periods=2, freq="h")


def _generation_rows():
    rows = []
    for t in HOURS:
        stamp = t.strftime("%Y-%m-%d %H:%M:%S")
        rows += [
            (stamp, "SE", "EOLIELÉTRICA", "TIPO I", 100.0),
            (stamp, "SE", "FOTOVOLTAICA", "TIPO I", 50.0),
            (stamp, "SE", "FOTOVOLTAICA", gate.MMGD_MODALITY, 20.0),
            (stamp, "PY", "HIDROELÉTRICA", "TIPO I", 999.0),
            (stamp, "S", "TÉRMICA", "TIPO I", 30.0),
        ]
    return pd.DataFrame(
        rows,
        columns=[
            "din_instante",
            "id_subsistema",
            "nom_tipousina",
            "cod_modalidadeoperacao",
            "val_geracao",
        ],
    )


class TestObservedGeneration:
    def test_splits_mmgd_drops_py_and_averages_over_hours(self):
        obs = gate.observed_generation(_generation_rows()).set_index(["subsystem", "source"])
        assert obs.loc[("SE_CO", "wind"), "observed_mw"] == pytest.approx(100.0)
        assert obs.loc[("SE_CO", "solar"), "observed_mw"] == pytest.approx(50.0)
        assert obs.loc[("SE_CO", "solar_mmgd"), "observed_mw"] == pytest.approx(20.0)
        assert "hydro" not in obs.index.get_level_values("source")

    def test_unknown_plant_type_raises(self):
        raw = _generation_rows()
        raw.loc[0, "nom_tipousina"] = "MARÉ"
        with pytest.raises(ValueError, match="unmapped ONS plant type"):
            gate.observed_generation(raw)


def _network() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(HOURS)
    for b in ["N", "NE"]:
        n.add("Bus", b)
    n.add("Load", "NE", bus="NE", p_set=10.0)
    n.add("Generator", "N wind", bus="N", carrier="wind", p_nom=20.0)
    n.add(
        "Generator",
        "NE load_shedding",
        bus="NE",
        carrier="load_shedding",
        p_nom=1e3,
        marginal_cost=1e4,
    )
    n.add("Link", "N-NE", bus0="N", bus1="NE", p_nom=20.0, p_min_pu=-1.0)
    n.optimize(solver_name="highs", include_objective_constant=False)
    return n


class TestGate:
    def test_model_generation_excludes_load_shedding(self):
        model = gate.model_generation(_network()).set_index(["subsystem", "source"])
        assert model.loc[("N", "wind"), "model_mw"] == pytest.approx(10.0)
        assert "load_shedding" not in model.index.get_level_values("source")

    def test_interchange_error_is_scaled_by_capacity(self):
        n = _network()
        observed = pd.DataFrame(
            {"snapshot": HOURS, "bus0": "N", "bus1": "NE", "observed_mw": [10.0, 12.0]}
        )
        links = pd.DataFrame({"bus0": ["N"], "bus1": ["NE"], "p_nom_mw": [20.0]})
        table = gate.interchange_table(n, observed, links)
        # model 10 MW mean, observed 11: 1 MW off is 5% of 20 MW, a pass.
        assert table.loc[0, "error_share_of_capacity"] == pytest.approx(0.05)
        assert bool(table.loc[0, "passed"])

    def test_report_fails_on_one_source_outside_tolerance(self):
        generation = pd.DataFrame(
            {
                "subsystem": ["SIN"] * 4,
                "source": gate.SCORED_SOURCES,
                "model_mw": [100.0, 110.0, 100.0, 100.0],
                "observed_mw": [100.0, 100.0, 100.0, 100.0],
            }
        ).assign(ratio=lambda d: d["model_mw"] / d["observed_mw"])
        interchange = pd.DataFrame({"boundary": ["N-NE"], "passed": [True]})
        report = gate.gate_report(generation, interchange)
        assert not report["passed"]
        assert report["national_generation"]["solar"]["passed"] is False
        assert report["national_generation"]["wind"]["passed"] is True
