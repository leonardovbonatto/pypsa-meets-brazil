# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Tests the Python-side half of the ADR-0005 coupling proof: that a
Parquet file written by `julia/smoke_test.jl` reads back with the shape a
downstream linopy constraint-builder needs.

Deliberately does NOT invoke Julia - CI has no `sddp` pixi environment,
the same reason `fetch_all` never runs in CI. The committed fixture is a
real, unmodified output of `julia/smoke_test.jl`, not synthesized here.
"""

from pathlib import Path

import pandas as pd

FIXTURE = Path(__file__).parent / "fixtures" / "sddp" / "cuts_sample.parquet"


def test_fixture_exists():
    assert FIXTURE.is_file()


def test_cuts_have_the_expected_shape():
    cuts = pd.read_parquet(FIXTURE)

    assert list(cuts.columns) == ["node", "intercept", "state_variable", "coefficient"]
    assert len(cuts) > 0

    # SDDP.jl's stages are 1-indexed nodes; the smoke test has 3 (no cuts on
    # the terminal stage, since there is nothing left to bound the cost of).
    assert set(cuts["node"].astype(int)) <= {1, 2, 3}


def test_cuts_are_real_numbers_not_placeholders():
    cuts = pd.read_parquet(FIXTURE)

    # A single cut's intercept can legitimately be 0 - that's a real bound,
    # not a sign of failure. What a broken/untrained policy actually looks
    # like: every cut identically 0 (nothing learned), or a NaN/inf from a
    # numerical failure.
    intercepts = cuts["intercept"].astype(float)
    assert (intercepts != 0).any()
    assert intercepts.notna().all()
    assert (intercepts.abs() < 1e6).all()
