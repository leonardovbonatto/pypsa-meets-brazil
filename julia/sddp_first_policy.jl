# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
#
# ADR-0005 stage 1f/1g: the first SDDP policy on real Brazilian data, with
# a choice of risk measure. A 12-stage (one annual cycle), 4-subsystem
# hydro-thermal model - reservoir storage bounded by real capacity
# (PR-30), demand and hydro/thermal capacity/cost from T0 (already real),
# inflow uncertainty from the real fitted PAR(1) model (PR-28/29),
# correlated across subsystems within each month. See
# scripts/prepare_sddp_inputs.py's module docstring and
# docs/handoffs/PR-31-*.md / PR-32-*.md for what is and is not yet real
# here (known_limitations() at the bottom of this file).
#
# Run: julia --project=julia julia/sddp_first_policy.jl <inputs_dir> <output_dir> [risk_kind] [lambda] [alpha] [seed]
#   risk_kind: "expectation" (default) or "cvar"
#   lambda:    PRIMER Sec 4.4's weight on the CVaR term, (1-lambda)*E + lambda*CVaR_alpha
#              (only used when risk_kind="cvar"; default 0.5)
#   alpha:     the CVaR tail fraction, e.g. 0.1 = worst 10% of outcomes
#              (only used when risk_kind="cvar"; default 0.1)
#   seed:      Random.seed! for SDDP's own training/simulation sampling -
#              PR-32 shipped without this, so re-runs produced slightly
#              different numbers; default 0 (PR-33).

using Random
using SDDP
using HiGHS
using DataFrames
using Parquet2

const SUBSYSTEMS = ["N", "NE", "S", "SE_CO"]
const LOAD_SHED_COST = 10_000.0  # matches scripts/build_network.py::LOAD_SHED_COST (T0)

function known_limitations(risk_kind::String)
    limitations = [
        "Inflow scenarios are i.i.d. per month, not autocorrelated month-to-month " *
        "within the policy - PAR(1)'s fitted phi (PR-28) is not yet wired into SDDP's state.",
        "12 monthly stages, one annual cycle - not an infinite-horizon cyclic policy graph.",
        "No inter-subsystem transmission in this reduced hydro-thermal subproblem - " *
        "real network coupling belongs in PyPSA/linopy once cuts are consumed there.",
        "Wind, solar and nuclear excluded from this reduced model.",
        "SimulationStoppingRule (SDDP.jl's own recommended default) is wired in, " *
        "but checked directly (PR-33) that it does NOT actually trigger within " *
        "iteration_limit=1000 - training still hits the safety cap in practice, " *
        "the same as PR-32's fixed count did, just at a higher number. The bound " *
        "was still slowly rising at iteration 1000 (2.53bn -> 2.56bn from iteration " *
        "250 to 1000), and numeric issues rose to 57 (0 at 50 iterations, low " *
        "single digits at 300) - a real, unresolved signal that this model's LP " *
        "conditioning may degrade as cuts accumulate, worth investigating directly " *
        "rather than raising the cap indefinitely.",
        "100 Monte Carlo simulation realizations back every reported statistic - " *
        "still real sampling noise, especially for tail (P90) statistics.",
    ]
    if risk_kind == "expectation"
        push!(
            limitations,
            "Expectation-only - no risk aversion. See the \"cvar\" risk_kind for " *
            "PRIMER Sec 4.4's (1-lambda)*E + lambda*CVaR_alpha blend.",
        )
    end
    return limitations
end

"""
Translate PRIMER Sec 4.4's `(1 - lambda) * E[cost] + lambda * CVaR_alpha[cost]`
into SDDP.jl's risk measure types.

**A real convention mismatch, checked via `@doc SDDP.EAVaR` rather than
assumed**: SDDP.jl's `EAVaR(lambda, beta)` puts `lambda` on the
EXPECTATION term (`lambda * E + (1-lambda) * AVaR(beta)`) - the OPPOSITE
of PRIMER's `lambda`, which weights the CVaR term. `beta` is the tail
fraction and matches PRIMER's `alpha` directly (`beta=1` is plain
expectation, `beta=0` is worst-case - the same convention as
`SDDP.CVaR`'s own `gamma` in its docstring). Getting the `lambda` swap
wrong would silently train a policy with the opposite risk appetite from
the one requested - the same class of unit-convention trap this project
keeps finding in ONS data (MWmed/MWmes, PR-27/30), just self-inflicted
this time instead of upstream.
"""
function parse_risk_measure(risk_kind::String, lambda::Float64, alpha::Float64)
    if risk_kind == "expectation"
        return SDDP.Expectation()
    elseif risk_kind == "cvar"
        return SDDP.EAVaR(; lambda = 1.0 - lambda, beta = alpha)
    else
        error("unknown risk_kind: $risk_kind (expected \"expectation\" or \"cvar\")")
    end
end

function read_parquet_df(path::String)
    return DataFrame(Parquet2.readfile(path); copycols = true)
end

function load_inputs(inputs_dir::String)
    demand = read_parquet_df(joinpath(inputs_dir, "demand.parquet"))
    capacity = read_parquet_df(joinpath(inputs_dir, "capacity.parquet"))
    cost = read_parquet_df(joinpath(inputs_dir, "cost.parquet"))
    reservoir_capacity = read_parquet_df(joinpath(inputs_dir, "reservoir_capacity.parquet"))
    initial_storage = read_parquet_df(joinpath(inputs_dir, "initial_storage.parquet"))
    scenarios = read_parquet_df(joinpath(inputs_dir, "scenarios.parquet"))

    hydro_cap = Dict(row.subsystem => row.hydro_mw for row in eachrow(capacity))
    thermal_cap = Dict(row.subsystem => row.thermal_mw for row in eachrow(capacity))
    thermal_marginal_cost = Dict(row.subsystem => row.marginal_cost for row in eachrow(cost))
    max_storage = Dict(row.subsystem => row.ear_max_mwmes for row in eachrow(reservoir_capacity))
    storage0 = Dict(row.subsystem => row.initial_storage_mwmes for row in eachrow(initial_storage))
    demand_by_month = Dict((row.month, row.subsystem) => row.demand_mw for row in eachrow(demand))

    scenarios_by_month = Dict{Int,Vector{Dict{String,Float64}}}()
    probs_by_month = Dict{Int,Vector{Float64}}()
    for month in 1:12
        month_rows = filter(r -> r.month == month, scenarios)
        by_scenario = Dict{Int,Dict{String,Float64}}()
        prob_by_scenario = Dict{Int,Float64}()
        for row in eachrow(month_rows)
            d = get!(by_scenario, row.scenario, Dict{String,Float64}())
            d[row.subsystem] = row.inflow_mwmed
            prob_by_scenario[row.scenario] = row.probability
        end
        ids = sort(collect(keys(by_scenario)))
        scenarios_by_month[month] = [by_scenario[i] for i in ids]
        probs_by_month[month] = [prob_by_scenario[i] for i in ids]
    end

    return (;
        hydro_cap,
        thermal_cap,
        thermal_marginal_cost,
        max_storage,
        storage0,
        demand_by_month,
        scenarios_by_month,
        probs_by_month,
    )
end

function build_model(inputs)
    return SDDP.LinearPolicyGraph(
        stages = 12,
        sense = :Min,
        lower_bound = 0.0,
        optimizer = HiGHS.Optimizer,
    ) do subproblem, month
        @variable(
            subproblem,
            0 <= storage[s in SUBSYSTEMS] <= inputs.max_storage[s],
            SDDP.State,
            initial_value = inputs.storage0[s]
        )
        @variable(subproblem, 0 <= hydro_generation[s in SUBSYSTEMS] <= inputs.hydro_cap[s])
        @variable(subproblem, 0 <= thermal_generation[s in SUBSYSTEMS] <= inputs.thermal_cap[s])
        @variable(subproblem, spill[s in SUBSYSTEMS] >= 0)
        @variable(subproblem, load_shed[s in SUBSYSTEMS] >= 0)
        @variable(subproblem, inflow[s in SUBSYSTEMS])

        @constraint(
            subproblem,
            [s in SUBSYSTEMS],
            storage[s].out == storage[s].in - hydro_generation[s] - spill[s] + inflow[s]
        )
        @constraint(
            subproblem,
            [s in SUBSYSTEMS],
            hydro_generation[s] + thermal_generation[s] + load_shed[s] ==
            inputs.demand_by_month[(month, s)]
        )

        SDDP.@stageobjective(
            subproblem,
            sum(
                inputs.thermal_marginal_cost[s] * thermal_generation[s] +
                LOAD_SHED_COST * load_shed[s] for s in SUBSYSTEMS
            )
        )

        SDDP.parameterize(
            subproblem,
            inputs.scenarios_by_month[month],
            inputs.probs_by_month[month],
        ) do omega
            for s in SUBSYSTEMS
                JuMP.fix(inflow[s], omega[s])
            end
        end
    end
end

function main()
    inputs_dir = length(ARGS) >= 1 ? ARGS[1] : "resources"
    output_dir = length(ARGS) >= 2 ? ARGS[2] : "results/sddp_first_policy"
    risk_kind = length(ARGS) >= 3 ? ARGS[3] : "expectation"
    lambda = length(ARGS) >= 4 ? parse(Float64, ARGS[4]) : 0.5
    alpha = length(ARGS) >= 5 ? parse(Float64, ARGS[5]) : 0.1
    seed = length(ARGS) >= 6 ? parse(Int, ARGS[6]) : 0
    mkpath(output_dir)

    # Seeds Julia's GLOBAL RNG, which SDDP.jl's own forward-pass sampling
    # and SDDP.simulate() both draw from - PR-32 shipped without this, so
    # re-running the same policy produced slightly different numbers each
    # time, which is why that PR's handoff reports a range rather than one
    # fixed comparison. scripts/prepare_sddp_inputs.py's own scenario
    # sampling was already seeded independently (its own `seed` param);
    # this is the second, previously-missing half.
    Random.seed!(seed)

    inputs = load_inputs(inputs_dir)
    model = build_model(inputs)
    risk_measure = parse_risk_measure(risk_kind, lambda, alpha)
    println("Risk measure: ", risk_kind, " (lambda=", lambda, ", alpha=", alpha, ") -> ", risk_measure)

    # SimulationStoppingRule (SDDP.jl's own recommended default) replaces
    # PR-32's fixed iteration_limit=300 - checks BOTH that the bound has
    # stabilized and that two consecutive out-of-sample simulations agree,
    # PRIMER Sec 4.3's "stop when the gap is acceptably small" rather than
    # a guessed count. iteration_limit stays as a generous safety cap, not
    # the primary stopping mechanism, in case the simulation-based rule
    # never triggers for a pathological input.
    SDDP.train(
        model;
        stopping_rules = [SDDP.SimulationStoppingRule()],
        iteration_limit = 1000,
        print_level = 1,
        log_file = "/dev/null",
        risk_measure = risk_measure,
    )

    risk_adjusted_bound = SDDP.calculate_bound(model; risk_measure = risk_measure)
    println("Trained. Risk-adjusted bound (R\$): ", risk_adjusted_bound)

    # :stage_objective is not requested here - SDDP.simulate() always
    # includes it automatically in every stage's result dict; it is not a
    # JuMP decision variable that needs listing like the others.
    simulations = SDDP.simulate(model, 100, [:storage, :hydro_generation, :thermal_generation, :load_shed])

    # The PLAIN Monte Carlo expected cost - not calculate_bound(), which
    # under a CVaR risk measure is a risk-ADJUSTED number, not comparable
    # across risk_kind runs the way a plain expectation is. Computed the
    # same way regardless of which risk measure trained the policy, so
    # expectation-vs-cvar comparisons in the handoff are apples to apples.
    expected_cost = sum(
        sum(stage[:stage_objective] for stage in realization) for realization in simulations
    ) / length(simulations)
    println("Simulated mean total system cost (R\$): ", expected_cost)

    per_realization_load_shed = [
        sum(sum(stage[:load_shed][s] for s in SUBSYSTEMS) for stage in realization) for
        realization in simulations
    ]
    mean_load_shed = sum(per_realization_load_shed) / length(simulations)
    sorted_load_shed = sort(per_realization_load_shed)
    p50_load_shed = sorted_load_shed[ceil(Int, 0.50 * length(sorted_load_shed))]
    p90_load_shed = sorted_load_shed[ceil(Int, 0.90 * length(sorted_load_shed))]
    println(
        "Mean/P50/P90 annual load shed across simulations (MW-months): ",
        mean_load_shed,
        " / ",
        p50_load_shed,
        " / ",
        p90_load_shed,
    )

    load_shed_by_subsystem = Dict(
        s => sum(stage[:load_shed][s] for realization in simulations for stage in realization) /
             length(simulations) for s in SUBSYSTEMS
    )
    for s in SUBSYSTEMS
        println("  ", s, ": ", load_shed_by_subsystem[s], " MW-months/year")
    end

    cuts_json_path = joinpath(output_dir, "_cuts.json")
    SDDP.write_cuts_to_file(model, cuts_json_path)
    cuts = SDDP.JSON.parsefile(cuts_json_path)
    rows = NamedTuple[]
    for node in cuts
        for cut in node["single_cuts"]
            state_names = collect(keys(cut["coefficients"]))
            push!(
                rows,
                (
                    node = node["node"],
                    intercept = cut["intercept"],
                    state_variable = join(state_names, ","),
                    coefficient = join([cut["coefficients"][k] for k in state_names], ","),
                ),
            )
        end
    end
    rm(cuts_json_path)
    Parquet2.writefile(joinpath(output_dir, "cuts.parquet"), DataFrame(rows))

    summary = Dict(
        "seed" => seed,
        "risk_kind" => risk_kind,
        "risk_lambda" => risk_kind == "cvar" ? lambda : nothing,
        "risk_alpha" => risk_kind == "cvar" ? alpha : nothing,
        "risk_adjusted_bound_rs" => risk_adjusted_bound,
        "expected_total_cost_rs" => expected_cost,
        "mean_annual_load_shed_mw_months" => mean_load_shed,
        "p50_annual_load_shed_mw_months" => p50_load_shed,
        "p90_annual_load_shed_mw_months" => p90_load_shed,
        "mean_annual_load_shed_by_subsystem" => load_shed_by_subsystem,
        "n_cuts" => length(rows),
        "known_limitations" => known_limitations(risk_kind),
    )
    open(joinpath(output_dir, "summary.json"), "w") do io
        SDDP.JSON.print(io, summary, 2)
    end
    println("Wrote ", length(rows), " cuts and summary.json to ", output_dir)
end

main()
