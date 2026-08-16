# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
SDDP epic rules (ADR-0005). Deliberately not part of `all` or `solve_all`:
they need the separate `sddp` pixi environment (Julia, ~170 MiB), which a
plain `pixi install -e dev` - and CI - never installs. Requested explicitly,
the same reason `fetch_all` stays out of `all`.
"""


rule sddp_smoke_test:
    """
    ADR-0005 stage-1 feasibility check: trains SDDP.jl's own textbook
    hydro-thermal example (single reservoir, 3 stages, stochastic inflow,
    thermal backup - no Brazilian data at all) and writes the resulting
    Benders cuts to Parquet. Proves the Julia -> Parquet -> Python coupling
    PRIMER Sec 4.5/5.10 describes actually works, independent of whether the
    real inflow/reservoir model is right - see docs/handoffs/PR-26-*.md.

    Not RUN_ID-scoped like the T0 pipeline's outputs: this doesn't depend on
    config.default.yaml at all.
    """
    output:
        "results/sddp_smoke_test/cuts.parquet",
    log:
        "logs/sddp_smoke_test/run.log",
    shell:
        "pixi run -e sddp julia --project=julia julia/smoke_test.jl {output} > {log} 2>&1"
