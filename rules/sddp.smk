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

# Training/simulation effort for both policy rules, shared so the two stay
# comparable (comparing an expectation policy trained one way against a
# CVaR policy trained another would make the whole comparison meaningless).
#
# 1000 iterations is a CEILING IMPOSED BY THE MODEL, not a converged value:
# PR-39 measured training crashing at iteration 2277 (expectation) and 1569
# (CVaR) with HiGHS returning "OPTIMAL" alongside "INFEASIBLE_POINT" as the
# LP degrades with accumulated cuts. The bound is still climbing when it
# crashes, so this policy is knowingly under-converged - raising this number
# without first fixing the conditioning just moves the crash earlier.
#
# 1000 simulations (up from 100) because PR-39 checked whether the tail
# statistics were sampling noise - they were not, but the larger sample is
# cheap and makes P90 figures meaningfully steadier.
# See docs/handoffs/PR-39-*.md for the measurements behind both numbers.
SDDP_ITERATION_LIMIT = 1000
SDDP_N_SIMULATIONS = 1000


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


rule fit_inflow_par1_ree:
    """
    REE-level counterpart of fit_inflow_par1 (ADR-0008 stage 2): fits a
    PAR(1) model per REE (12x12 spatial correlation) instead of per
    subsystem, on the shorter, more ragged 2016-2025 ena_ree record - see
    scripts/fit_inflow_par1_ree.py's module docstring and
    docs/handoffs/PR-37-*.md for what "shorter and more ragged" concretely
    means here, including a real zero-inflow-before-tracking quirk found
    and handled while fitting (TELES PIRES).
    """
    input:
        "resources/inflow_ena_ree.csv",
    output:
        params="resources/inflow_par1_params_ree.csv",
        correlation="resources/inflow_par1_correlation_ree.csv",
        validation="results/inflow_par1_validation_ree.json",
    log:
        "logs/fit_inflow_par1_ree/run.log",
    script:
        "../scripts/fit_inflow_par1_ree.py"


rule prepare_sddp_inputs:
    """
    Assemble every real input the first SDDP policy needs (ADR-0005 stage
    1f) into Parquet files julia/sddp_first_policy.jl reads: monthly
    demand, hydro/thermal capacity, thermal cost, initial reservoir
    storage, PAR(1) parameters, and correlated monthly inflow shocks.

    Python, not Julia. Joins T0 data (already real) with the PAR(1) fit
    (PR-28/29) and reservoir capacity (PR-30) - see the module docstring
    in scripts/prepare_sddp_inputs.py for the full reasoning, including
    why monthly MWmed/MWmes/MW units are directly commensurable here.

    Outputs `shocks` (raw correlated standardized shocks) and
    `inflow_params` (mu/sigma/phi) instead of pre-computed inflow levels
    since PR-38 - the AR(1) recursion and exp(mu+sigma*z) transform now
    happen in julia/sddp_first_policy.jl, where a state variable can carry
    the previous month's anomaly forward.
    """
    input:
        demand="resources/demand_t0.csv",
        generators="resources/generators_t0.csv",
        costs="resources/costs_t0.csv",
        reservoir_capacity="resources/reservoir_ear_capacity.csv",
        reservoir_history="resources/reservoir_ear_history.csv",
        par1_params="resources/inflow_par1_params.csv",
        par1_correlation="resources/inflow_par1_correlation.csv",
    output:
        demand="resources/sddp_inputs/demand.parquet",
        capacity="resources/sddp_inputs/capacity.parquet",
        cost="resources/sddp_inputs/cost.parquet",
        reservoir_capacity="resources/sddp_inputs/reservoir_capacity.parquet",
        initial_storage="resources/sddp_inputs/initial_storage.parquet",
        inflow_params="resources/sddp_inputs/inflow_params.parquet",
        shocks="resources/sddp_inputs/shocks.parquet",
    params:
        n_scenarios=10,
        seed=0,
    log:
        "logs/prepare_sddp_inputs/run.log",
    script:
        "../scripts/prepare_sddp_inputs.py"


rule sddp_first_policy:
    """
    ADR-0005 stage 1f: train the first expectation-only SDDP policy on
    real Brazilian data - see julia/sddp_first_policy.jl's module
    docstring and docs/handoffs/PR-31-*.md/PR-38-*.md for scope and named
    simplifications (KNOWN_LIMITATIONS in both files). Since PR-38, the
    policy carries real PAR(1) temporal persistence via a state-augmented
    AR(1) inflow anomaly, not just i.i.d.-per-month draws.
    """
    input:
        "resources/sddp_inputs/demand.parquet",
        "resources/sddp_inputs/capacity.parquet",
        "resources/sddp_inputs/cost.parquet",
        "resources/sddp_inputs/reservoir_capacity.parquet",
        "resources/sddp_inputs/initial_storage.parquet",
        "resources/sddp_inputs/inflow_params.parquet",
        "resources/sddp_inputs/shocks.parquet",
    output:
        cuts="results/sddp_first_policy/cuts.parquet",
        summary="results/sddp_first_policy/summary.json",
    params:
        iteration_limit=SDDP_ITERATION_LIMIT,
        n_simulations=SDDP_N_SIMULATIONS,
    log:
        "logs/sddp_first_policy/run.log",
    shell:
        "pixi run -e sddp julia --project=julia julia/sddp_first_policy.jl "
        "resources/sddp_inputs results/sddp_first_policy expectation 0.5 0.1 0 "
        "{params.iteration_limit} {params.n_simulations} > {log} 2>&1"


rule sddp_cvar_policy:
    """
    ADR-0005 stage 1g: the same model as sddp_first_policy, trained with
    PRIMER Sec 4.4's CVaR risk measure instead of plain expectation -
    (1-lambda)*E + lambda*CVaR_alpha, lambda=0.5, alpha=0.1 (worst 10%).

    Exists alongside sddp_first_policy, not instead of it, so the two can
    be compared - see docs/handoffs/PR-32-*.md for what that comparison
    actually showed (a real convergence sensitivity, not a clean result).
    """
    input:
        "resources/sddp_inputs/demand.parquet",
        "resources/sddp_inputs/capacity.parquet",
        "resources/sddp_inputs/cost.parquet",
        "resources/sddp_inputs/reservoir_capacity.parquet",
        "resources/sddp_inputs/initial_storage.parquet",
        "resources/sddp_inputs/inflow_params.parquet",
        "resources/sddp_inputs/shocks.parquet",
    output:
        cuts="results/sddp_cvar_policy/cuts.parquet",
        summary="results/sddp_cvar_policy/summary.json",
    params:
        iteration_limit=SDDP_ITERATION_LIMIT,
        n_simulations=SDDP_N_SIMULATIONS,
    log:
        "logs/sddp_cvar_policy/run.log",
    shell:
        "pixi run -e sddp julia --project=julia julia/sddp_first_policy.jl "
        "resources/sddp_inputs results/sddp_cvar_policy cvar 0.5 0.1 0 "
        "{params.iteration_limit} {params.n_simulations} > {log} 2>&1"
