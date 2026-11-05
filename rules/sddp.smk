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
# 4000 iterations, raised from PR-39's 1000 because PR-42 REMOVED the
# ceiling that forced that value. PR-39 measured training crashing at
# iteration 2277 (expectation) / 1569 (CVaR) as the LP degraded with
# accumulated cuts; PR-42 traced that to the objective's raw magnitude and
# fixed it by solving in millions of R$ (MONEY_SCALE). Measured after that
# change: both policies complete 4000 iterations with 0 and 2 numeric
# issues respectively, against 51 and 40 before.
#
# 4000 is a measured-safe value, NOT a converged one - the bound was still
# climbing at iteration 4000 (+7.7% from iteration 1000). Finding where it
# actually flattens is real remaining work, not settled here.
#
# 1000 simulations (up from 100) because PR-39 checked whether the tail
# statistics were sampling noise - they were not, but the larger sample is
# cheap and makes P90 figures meaningfully steadier.
# See docs/handoffs/PR-39-*.md and PR-42-*.md for the measurements.
SDDP_ITERATION_LIMIT = 4000
# The regional policy with transmission, net load and the floor settles
# early: on the two-year graph the bound was 44,627 (R$m) at iteration 100 and
# 44,641 at iteration 3146, 0.03% apart (PR-55 handoff), while
# SimulationStoppingRule never fired and the run took 9 s per iteration by the
# end. 300 keeps a margin; the one-year graph converges at about 200.
SDDP_REGIONAL_ITERATION_LIMIT = 300
# ADR-0017: how many years the regional policy graph spans. Two years was
# tried (PR-55) and made the 2024 backtest worse, so it stays at one; the
# multi-year code is kept for a later retry.
SDDP_HORIZON_YEARS = 1
# ADR-0018: what reaches the reservoirs, in SDDP and in the coupled run.
# "gross" (all ENA), "storable_plus_run_of_river" (storable ENA, the rest as
# same-month energy) or "storable" (storable ENA, the rest lost).
SDDP_INFLOW_MODE = "storable"
SDDP_N_SIMULATIONS = 1000

# ADR-0009: hydrological regimes in the Markovian policy graph. K=3 is
# dry/normal/wet, equal-probability bins of the standardized anomaly. The
# graph has 12*K nodes, so raising this multiplies training cost and
# spreads cuts more thinly - ADR-0009 names that as its main risk.
#
# Since ADR-0010 K is PER REGION, and the policy sees the joint regime:
# 3 regions at K=3 is 27 states and 324 nodes. PR-45 measured one national
# regime flattening every subsystem's persistence towards ~0.6, even at K=7.
SDDP_MARKOV_STATES = 3

# ADR-0010. S runs opposite to the north (-0.25, -0.26), N and NE move
# together (+0.48), and SE_CO dominates storage.
SDDP_REGIONS = {"N_NE": ["N", "NE"], "SE_CO": ["SE_CO"], "S": ["S"]}


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
    storage, regime transition matrices, and regime-conditional inflow
    scenarios.

    Python, not Julia. Joins T0 data (already real) with the PAR(1) fit
    (PR-28/29) and reservoir capacity (PR-30) - see the module docstring
    in scripts/prepare_sddp_inputs.py for the full reasoning, including
    why monthly MWmed/MWmes/MW units are directly commensurable here.

    Outputs `transitions` and `scenarios` since PR-45 (ADR-0009): the
    regime is a node of the policy graph, so inflow levels are computed
    here and julia/sddp_first_policy.jl only fixes them as constants. Since
    ADR-0010 both come from a seeded simulation of the PAR(1), with one
    regime per region.
    """
    input:
        demand="resources/demand_t0.csv",
        generators="resources/generators_t0.csv",
        costs="resources/costs_t0.csv",
        reservoir_capacity="resources/reservoir_ear_capacity.csv",
        reservoir_history="resources/reservoir_ear_history.csv",
        par1_params="resources/inflow_par1_params.csv",
        par1_correlation="resources/inflow_par1_correlation.csv",
        links="resources/links_t0.csv",
        network="resources/networks/t0.nc",
        thermal_floor="resources/thermal_floor_t0.csv",
        inflow="resources/inflow_ena.csv",
    output:
        demand="resources/sddp_inputs/demand.parquet",
        capacity="resources/sddp_inputs/capacity.parquet",
        cost="resources/sddp_inputs/cost.parquet",
        reservoir_capacity="resources/sddp_inputs/reservoir_capacity.parquet",
        initial_storage="resources/sddp_inputs/initial_storage.parquet",
        transitions="resources/sddp_inputs/transitions.parquet",
        scenarios="resources/sddp_inputs/scenarios.parquet",
        par1_paths="resources/sddp_inputs/par1_paths.parquet",
        links="resources/sddp_inputs/links.parquet",
        renewables="resources/sddp_inputs/renewables.parquet",
        thermal_floor="resources/sddp_inputs/thermal_floor.parquet",
        storable_share="resources/sddp_inputs/storable_share.parquet",
    params:
        inflow_mode=SDDP_INFLOW_MODE,
        n_scenarios=10,
        n_par1_paths=1000,
        n_simulated_years=200000,
        horizon_years=SDDP_HORIZON_YEARS,
        n_markov_states=SDDP_MARKOV_STATES,
        regions=SDDP_REGIONS,
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
    simplifications (KNOWN_LIMITATIONS in both files). Since PR-45 the
    policy sees temporal persistence through a Markovian policy graph
    (ADR-0009); check_sddp_regimes is its acceptance test.
    """
    input:
        "resources/sddp_inputs/demand.parquet",
        "resources/sddp_inputs/capacity.parquet",
        "resources/sddp_inputs/cost.parquet",
        "resources/sddp_inputs/reservoir_capacity.parquet",
        "resources/sddp_inputs/initial_storage.parquet",
        "resources/sddp_inputs/transitions.parquet",
        "resources/sddp_inputs/scenarios.parquet",
        "resources/sddp_inputs/par1_paths.parquet",
        "resources/sddp_inputs/links.parquet",
        "resources/sddp_inputs/renewables.parquet",
        "resources/sddp_inputs/thermal_floor.parquet",
        "resources/sddp_inputs/storable_share.parquet",
    output:
        cuts="results/sddp_first_policy/cuts.parquet",
        summary="results/sddp_first_policy/summary.json",
    params:
        iteration_limit=SDDP_REGIONAL_ITERATION_LIMIT,
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
    be compared - but read docs/handoffs/PR-43-*.md before drawing any
    conclusion from that comparison. SDDP.jl applies the risk measure
    INSIDE the Bellman recursion, so this policy minimises a nested
    composition of per-stage risk measures, not CVaR of the total annual
    cost. It therefore scores worse than the expectation policy on plain
    annual-total statistics (monotonically in lambda), which is a category
    error to read as a defect rather than evidence of one.
    """
    input:
        "resources/sddp_inputs/demand.parquet",
        "resources/sddp_inputs/capacity.parquet",
        "resources/sddp_inputs/cost.parquet",
        "resources/sddp_inputs/reservoir_capacity.parquet",
        "resources/sddp_inputs/initial_storage.parquet",
        "resources/sddp_inputs/transitions.parquet",
        "resources/sddp_inputs/scenarios.parquet",
        "resources/sddp_inputs/par1_paths.parquet",
        "resources/sddp_inputs/links.parquet",
        "resources/sddp_inputs/renewables.parquet",
        "resources/sddp_inputs/thermal_floor.parquet",
        "resources/sddp_inputs/storable_share.parquet",
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


rule check_sddp_regimes:
    """
    ADR-0009's acceptance test: at identical storage, water must be worth
    more in the dry regime than the wet one. Reads the exported cuts, so it
    needs no Julia and no retraining, and fails the rule if the test fails.
    See the module docstring in scripts/check_sddp_regimes.py for why this
    compares the slope of the cost-to-go rather than its level.
    """
    input:
        cuts="results/{policy}/cuts.parquet",
        reservoir_capacity="resources/sddp_inputs/reservoir_capacity.parquet",
    output:
        "results/{policy}/regime_check.json",
    wildcard_constraints:
        policy="sddp_first_policy|sddp_cvar_policy",
    params:
        regions=SDDP_REGIONS,
        n_markov_states=SDDP_MARKOV_STATES,
    log:
        "logs/check_sddp_regimes/{policy}.log",
    script:
        "../scripts/check_sddp_regimes.py"


rule prepare_sddp_inflow_state:
    """
    ADR-0011: inputs for the policy that remembers last month's inflow. A
    levels PAR(1) (linear, so inflow can be an SDDP state), its training
    noise, the noise that reproduces each of prepare_sddp_inputs' 1000
    log-PAR(1) scoring paths, the December 2025 starting inflow, and the
    validation table that replaced ADR-0009's negative-inflow figures.
    """
    input:
        inflow="resources/inflow_ena.csv",
        par1_correlation="resources/inflow_par1_correlation.csv",
        par1_paths="resources/sddp_inputs/par1_paths.parquet",
    output:
        inflow_model="resources/sddp_inflow_state/inflow_model.parquet",
        initial_inflow="resources/sddp_inflow_state/initial_inflow.parquet",
        noise="resources/sddp_inflow_state/noise.parquet",
        scoring_noise="resources/sddp_inflow_state/scoring_noise.parquet",
        validation="resources/sddp_inflow_state/levels_validation.json",
    params:
        n_noise=20,
        n_validation_years=20000,
        seed=0,
    log:
        "logs/prepare_sddp_inflow_state/run.log",
    script:
        "../scripts/prepare_sddp_inflow_state.py"


rule sddp_inflow_state_policy:
    """
    ADR-0011: expectation policy with storage and last month's inflow as
    states, on a linear 12-stage graph. Trained and scored like
    sddp_first_policy (same seed, iteration limit, simulations and 1000
    scoring paths) so the two compare directly.
    """
    input:
        "resources/sddp_inputs/demand.parquet",
        "resources/sddp_inputs/capacity.parquet",
        "resources/sddp_inputs/cost.parquet",
        "resources/sddp_inputs/reservoir_capacity.parquet",
        "resources/sddp_inputs/initial_storage.parquet",
        "resources/sddp_inputs/links.parquet",
        "resources/sddp_inputs/renewables.parquet",
        "resources/sddp_inputs/thermal_floor.parquet",
        "resources/sddp_inflow_state/inflow_model.parquet",
        "resources/sddp_inflow_state/initial_inflow.parquet",
        "resources/sddp_inflow_state/noise.parquet",
        "resources/sddp_inflow_state/scoring_noise.parquet",
    output:
        cuts="results/sddp_inflow_state_policy/cuts.parquet",
        summary="results/sddp_inflow_state_policy/summary.json",
    params:
        iteration_limit=SDDP_ITERATION_LIMIT,
        n_simulations=SDDP_N_SIMULATIONS,
    log:
        "logs/sddp_inflow_state_policy/run.log",
    shell:
        "pixi run -e sddp julia --project=julia julia/sddp_inflow_state.jl "
        "resources/sddp_inputs resources/sddp_inflow_state results/sddp_inflow_state_policy 0 "
        "{params.iteration_limit} {params.n_simulations} > {log} 2>&1"


rule check_sddp_inflow_state:
    """
    ADR-0011's acceptance test: after a very dry month (own last inflow at
    P10) water must be worth at least as much as after a very wet one (P90),
    and the deficit slack must carry at most 1% of S's inflow energy. Fails
    the rule if either does not hold. See scripts/check_sddp_inflow_state.py.
    """
    input:
        cuts="results/sddp_inflow_state_policy/cuts.parquet",
        summary="results/sddp_inflow_state_policy/summary.json",
        reservoir_capacity="resources/sddp_inputs/reservoir_capacity.parquet",
        par1_params="resources/inflow_par1_params.csv",
    output:
        "results/sddp_inflow_state_policy/inflow_state_check.json",
    log:
        "logs/check_sddp_inflow_state/run.log",
    script:
        "../scripts/check_sddp_inflow_state.py"


rule solve_network_sddp:
    """
    ADR-0014: solve 2024 on the T0 network with each subsystem's hydro as a
    reservoir valued by the regional SDDP policy's cuts, one month at a time,
    instead of ADR-0007's backcast. Observed 2024 inflow, storage from
    2023-12-31, regime per month read from observed inflow. The backcast run
    (solve_network_t0) is kept for comparison.
    """
    input:
        network="resources/networks/t0.nc",
        cuts="results/sddp_first_policy/cuts.parquet",
        reservoir_capacity="resources/reservoir_ear_capacity.csv",
        reservoir_history="resources/reservoir_ear_history.csv",
        inflow="resources/inflow_ena.csv",
        par1_params="resources/inflow_par1_params.csv",
        par1_correlation="resources/inflow_par1_correlation.csv",
    output:
        monthly="results/sddp_coupled/monthly.csv",
        hourly_prices="results/sddp_coupled/hourly_prices.csv",
        summary="results/sddp_coupled/summary.json",
    params:
        start_storage_date="2023-12-31",
        inflow_mode=SDDP_INFLOW_MODE,
        regions=SDDP_REGIONS,
        n_markov_states=SDDP_MARKOV_STATES,
        solver_name=config["solver"]["name"],
        solver_options=config["solver"]["options"],
    log:
        "logs/solve_network_sddp/run.log",
    script:
        "../scripts/solve_network_sddp.py"


rule backtest_2024:
    """
    ADR-0015: the Phase 7 gate. Compares the coupled 2024 run's monthly
    storage and prices with observed EAR and CMO, January to November, on
    shape. Fails the rule if the pre-registered criterion is not met.
    """
    input:
        model="results/sddp_coupled/monthly.csv",
        reservoir_capacity="resources/reservoir_ear_capacity.csv",
        reservoir_history="resources/reservoir_ear_history.csv",
        cmo="resources/cmo_monthly.csv",
    output:
        table="results/backtest_2024/comparison.csv",
        report="results/backtest_2024/report.json",
    params:
        year=2024,
    log:
        "logs/backtest_2024/run.log",
    script:
        "../scripts/backtest_2024.py"
