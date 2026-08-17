# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
SDDP epic rules (ADR-0005). Deliberately not part of `all` or `solve_all`.

Julia rules (currently just `sddp_smoke_test`) need the separate `sddp`
pixi environment (~170 MiB), which a plain `pixi install -e dev` - and CI -
never installs. Python rules (`fit_inflow_par1`) don't need `sddp`, but
still depend on `resources/inflow_ena.csv`, itself built from real fetched
ONS data - the same reason `fetch_all`/`build_all` stay out of `all` too.
Every rule here is requested explicitly.
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


rule fit_inflow_par1:
    """
    Fit a PAR(1) inflow model per subsystem (ADR-0005 stage 1c/1d:
    persistence + spatial correlation) and validate both of PRIMER Sec
    4.7's required properties against the real historical record.

    Python, not Julia - unlike sddp_smoke_test, this rule needs only `dev`.
    Spatial correlation is preserved via a single cross-subsystem residual
    correlation matrix pooled across all calendar months, not fit
    per-month - a real, documented simplification (see KNOWN_LIMITATIONS in
    scripts/fit_inflow_par1.py and docs/handoffs/PR-29-*.md).
    """
    input:
        "resources/inflow_ena.csv",
    output:
        params="resources/inflow_par1_params.csv",
        correlation="resources/inflow_par1_correlation.csv",
        validation="results/inflow_par1_validation.json",
    log:
        "logs/fit_inflow_par1/run.log",
    script:
        "../scripts/fit_inflow_par1.py"
