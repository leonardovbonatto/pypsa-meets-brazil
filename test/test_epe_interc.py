# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the EPE interchange loader, on SYNTHETIC text in EPE's layout.

No EPE data is used here: the repository has no licence file, so its files
stay local (Brazilian-Grid-in-PyPSA.md §8). Names and numbers are invented.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


epe = _load("epe_interc", REPO_ROOT / "scripts" / "epe_interc.py")

INTERC = """$version=1
!.Num ....Name.... FROM........ TO.......... Type Currency    CapacFT     LossFT    CapacTF     LossTF
!                                                                  MW         pu         MW         pu
    1 SE -> SU     SUDESTE      SUL             0      R$       99999          0      99999          0
    2 SE -> NE     SUDESTE      NORDESTE        0      R$        1000          0  12000.555          0
    3 NO -> XX     NORTE        FAKE NODE B     0      R$         300          0        400          0
"""

MINTERC = """$version=1
!D/MM/YYYY  .Num ....Name.... KeyWord     Blck .....Value
01/01/2025     2 SE -> NE     CapacTF        3   1900.25
01/04/2025     2 SE -> NE     CapacTF        1   2100
"""


class TestParse:
    def test_reads_names_with_spaces_at_their_columns(self):
        df = epe.parse_interc(INTERC)
        assert df["name"].tolist() == ["SE -> SU", "SE -> NE", "NO -> XX"]
        assert df.loc[2, "to"] == "FAKE NODE B"
        assert df.loc[1, "capac_tf_mw"] == pytest.approx(12000.555)  # spills past its marker

    def test_reads_monthly_overrides(self):
        df = epe.parse_minterc(MINTERC)
        assert df["date"].dt.month.tolist() == [1, 4]
        assert df["block"].tolist() == [3, 1]
        assert df["value"].tolist() == [1900.25, 2100.0]

    def test_raises_without_a_matching_header(self):
        with pytest.raises(ValueError, match="no header"):
            epe.parse_fixed_width("!a b\n1 2\n", ["x", "y", "z"], n_text=1)

    def test_star_block_means_every_block(self):
        text = MINTERC + "01/05/2025     2 SE -> NE     CapacTF        *   2200\n"
        assert epe.parse_minterc(text)["block"].isna().tolist() == [False, False, True]


class TestCrossCheck:
    def test_maps_the_direct_boundary_by_direction(self):
        links = pd.DataFrame(
            {"bus0": ["NE", "SE_CO"], "bus1": ["SE_CO", "S"], "p_nom_mw": [1500.0, 900.0]}
        )
        report = epe.cross_check(epe.parse_interc(INTERC), links)
        ne = report["NE-SE_CO"]
        assert ne["comparable"]
        assert ne["epe_bus0_to_bus1_mw"] == pytest.approx(12000.555)  # NE -> SE is TF
        assert ne["epe_bus1_to_bus0_mw"] == pytest.approx(1000.0)
        assert not report["SE_CO-S"]["comparable"]
