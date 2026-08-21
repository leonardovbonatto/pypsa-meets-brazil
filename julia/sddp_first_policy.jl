# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
#
# ADR-0005 stage 1f/1g: the first SDDP policy on real Brazilian data, with
# a choice of risk measure. A 12-stage (one annual cycle), 4-subsystem
# hydro-thermal model - reservoir storage bounded by real capacity
# (PR-30), demand and hydro/thermal capacity/cost from T0 (already real),
# inflow uncertainty from the real fitted PAR(1) model (PR-28/29),
# correlated across subsystems within each month.
#
# !! PR-38's temporal-persistence claim is only HALF true - corrected in
# PR-40, do not read PR-38's handoff without this correction. The AR(1)
# recursion added in PR-38 makes the sampled SCENARIOS autocorrelated
# month-to-month (real, working), but it does NOT make the POLICY aware of
# that autocorrelation. `z` is declared an SDDP.State yet appears in no
# @constraint and in no objective term - the recursion runs in plain Julia
# inside `parameterize` and its result is fix()-ed as a constant - so the
# LP never sees `z`, its dual is identically zero, and the cost-to-go
# function is FLAT in it. Measured, not theorised: all 22,000 exported cut
# coefficients on z[*] are exactly 0.0 across both policies (PR-40).
# The policy therefore cannot reason "water is worth more this month
# because last month was dry", which is the entire point of modelling
# persistence. See docs/handoffs/PR-40-*.md.
#
# See scripts/prepare_sddp_inputs.py's module docstring and
# docs/handoffs/PR-31-*.md / PR-32-*.md / PR-38-*.md / PR-39-*.md /
# PR-40-*.md for what is and is not real here (known_limitations() below).
#
# Run: julia --project=julia julia/sddp_first_policy.jl <inputs_dir> <output_dir> [risk_kind] [lambda] [alpha] [seed] [iteration_limit] [n_simulations]
#   risk_kind: "expectation" (default) or "cvar"
#   lambda:    PRIMER Sec 4.4's weight on the CVaR term, (1-lambda)*E + lambda*CVaR_alpha
#              (only used when risk_kind="cvar"; default 0.5)
#   alpha:     the CVaR tail fraction, e.g. 0.1 = worst 10% of outcomes
#              (only used when risk_kind="cvar"; default 0.1)
#   seed:      Random.seed! for SDDP's own training/simulation sampling -
#              PR-32 shipped without this, so re-runs produced slightly
#              different numbers; default 0 (PR-33).
#   iteration_limit / n_simulations: training cap and Monte Carlo
#              simulation count, both CLI args since PR-39 rather than
#              hardcoded - PR-38 left a real open question (does CVaR's
#              backwards-looking P90 close with more of either?) that
#              could not be investigated without editing this file.

using Random
using SDDP
using HiGHS
using DataFrames
using Parquet2

const SUBSYSTEMS = ["N", "NE", "S", "SE_CO"]
const LOAD_SHED_COST = 10_000.0  # matches scripts/build_network.py::LOAD_SHED_COST (T0)

function known_limitations(risk_kind::String)
    limitations = [
        "AR(1) temporal persistence (PR-38) starts every simulated year from " *
        "z=0 for every subsystem at the root node - the unconditional mean " *
        "log-inflow anomaly, not a real observed prior December. SDDP.jl's " *
        "root node must be one deterministic starting point.",
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
        "REPORTED COSTS ARE A RATE (R\$/h summed over 12 monthly stages), NOT " *
        "an annual R\$ total - a real unit error found in PR-39 and NOT yet " *
        "fixed. The stage objective is marginal_cost [R\$/MWh] * generation " *
        "[MW], which is R\$/h; converting to R\$ needs a hours-in-month factor " *
        "(~730) that appears nowhere. Verified exactly, not inferred: " *
        "sum_s(cost_s * thermal_gen_s) + LOAD_SHED_COST * load_shed " *
        "reproduces the reported figure to a ratio of 1.0000000000000018. " *
        "LOAD_SHED_COST=10,000 was correctly copied from build_network.py, but " *
        "PyPSA applies snapshot weightings automatically and SDDP.jl does not - " *
        "right constant, wrong unit context. Every \"expected annual cost in " *
        "R\$\" this epic has reported since PR-31 is therefore short by ~730x. " *
        "Policy and load-shed statistics are essentially unaffected (near-" *
        "uniform scaling), so comparisons between runs remain valid; only the " *
        "absolute R\$ labels are wrong.",
        "1000 Monte Carlo simulation realizations back every reported statistic " *
        "(raised from 100 in PR-39, after checking the tail statistics actually " *
        "move) - real sampling noise remains, but PR-38's " *
        "CVaR-P90-above-expectation finding was directly confirmed NOT to be an " *
        "artifact of the old 100-realization sample.",
        "THE POLICY IS BLIND TO TEMPORAL PERSISTENCE, despite PR-38's claim " *
        "(corrected in PR-40, measured not theorised): all 22,000 exported cut " *
        "coefficients on z[*] are exactly 0.0 across both policies, because z " *
        "appears in no constraint and no objective term - the LP never sees it, " *
        "so the cost-to-go is flat in it. PR-38 delivered persistent SCENARIOS " *
        "with a persistence-BLIND policy. This most likely explains the ~2x " *
        "cost/load-shed increase PR-38 reported and attributed to persistence " *
        "being priced correctly: the simulated world got harder while the " *
        "policy did not improve. It is also a strong candidate explanation for " *
        "the CVaR-P90-above-expectation anomaly below - a risk measure cannot " *
        "hedge against a state variable it cannot observe. Fixing it needs a " *
        "different formulation (Markovian policy graph, or a levels-space AR " *
        "that can enter the balance constraint linearly), pending its own ADR.",
        "PR-38's AR(1) state doubled the state-variable count (4 -> 8: z per " *
        "subsystem alongside storage per subsystem) - a real, checked increase " *
        "in mean/P90 load shed and cost versus PR-31/33's i.i.d.-inflow baseline " *
        "(P90 load shed ~58,000-63,000 MW-months here vs ~30,090 there), but see " *
        "the persistence-blindness entry above for why this is NOT evidence that " *
        "persistence is being priced correctly. " *
        "The now-larger state space also makes the SAME PR-33-named convergence " *
        "concern more visible, not new: expectation and CVaR are no longer " *
        "near-identical (PR-33's own headline finding) but CVaR's P90 load shed " *
        "came out HIGHER than expectation's - backwards from theory, the same " *
        "direction PR-32 found and PR-33 only partly resolved by raising " *
        "iterations.",
        "TRAINING HAS A HARD CEILING WELL SHORT OF CONVERGENCE (PR-39, measured " *
        "not assumed): with seed 0, training CRASHES at iteration 2277 " *
        "(expectation) and 1569 (CVaR) with HiGHS reporting " *
        "\"Termination status: OPTIMAL, Primal status: INFEASIBLE_POINT\" - the " *
        "LP becomes ill-conditioned as cuts accumulate. This is PR-33's " *
        "\"numeric issues rose to 57\" warning turning into a hard failure now " *
        "that PR-38 doubled the state space. Two consequences, both real: " *
        "(1) iteration_limit=1000 is NOT a converged policy - the bound was " *
        "still climbing at the crash (7.292e8 at iteration 1000 -> 7.901e8 at " *
        "2277, +8.3%); it is simply the largest round number safely below the " *
        "observed breakdown. (2) PR-38's open question \"does CVaR's backwards " *
        "P90 close with more iterations?\" CANNOT be answered by training " *
        "longer - and CVaR, the policy that would most need the extra " *
        "iterations, breaks 708 iterations EARLIER than expectation does. " *
        "Fixing the conditioning (cut pruning, coefficient scaling) is the real " *
        "prerequisite, not a larger cap - deliberately not attempted here.",
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
    inflow_params = read_parquet_df(joinpath(inputs_dir, "inflow_params.parquet"))
    shocks = read_parquet_df(joinpath(inputs_dir, "shocks.parquet"))

    hydro_cap = Dict(row.subsystem => row.hydro_mw for row in eachrow(capacity))
    thermal_cap = Dict(row.subsystem => row.thermal_mw for row in eachrow(capacity))
    thermal_marginal_cost = Dict(row.subsystem => row.marginal_cost for row in eachrow(cost))
    max_storage = Dict(row.subsystem => row.ear_max_mwmes for row in eachrow(reservoir_capacity))
    storage0 = Dict(row.subsystem => row.initial_storage_mwmes for row in eachrow(initial_storage))
    demand_by_month = Dict((row.month, row.subsystem) => row.demand_mw for row in eachrow(demand))

    # (month, subsystem) -> (mu, sigma, phi) - the PAR(1) fit (PR-28/29),
    # used inside build_model's parameterize callback to run the AR(1)
    # recursion in plain Julia (not a JuMP expression - see module header).
    inflow_param_by_month = Dict(
        (row.month, row.subsystem) => (mu = row.mu, sigma = row.sigma, phi = row.phi) for
        row in eachrow(inflow_params)
    )

    shocks_by_month = Dict{Int,Vector{Dict{String,Float64}}}()
    probs_by_month = Dict{Int,Vector{Float64}}()
    for month in 1:12
        month_rows = filter(r -> r.month == month, shocks)
        by_scenario = Dict{Int,Dict{String,Float64}}()
        prob_by_scenario = Dict{Int,Float64}()
        for row in eachrow(month_rows)
            d = get!(by_scenario, row.scenario, Dict{String,Float64}())
            d[row.subsystem] = row.shock
            prob_by_scenario[row.scenario] = row.probability
        end
        ids = sort(collect(keys(by_scenario)))
        shocks_by_month[month] = [by_scenario[i] for i in ids]
        probs_by_month[month] = [prob_by_scenario[i] for i in ids]
    end

    return (;
        hydro_cap,
        thermal_cap,
        thermal_marginal_cost,
        max_storage,
        storage0,
        demand_by_month,
        inflow_param_by_month,
        shocks_by_month,
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
        # Standardized log-inflow anomaly (PR-38), CORRECTED IN PR-40.
        #
        # What this does: carries last month's anomaly forward so the
        # sampled inflow SCENARIOS are autocorrelated (real and working).
        #
        # What it does NOT do, contrary to PR-38's claim: make the POLICY
        # persistence-aware. `z` appears in no @constraint and no objective
        # term - the AR(1) recursion runs in plain Julia inside
        # `parameterize` and its result is fix()-ed as a constant. The LP
        # therefore never sees `z`; its dual is identically zero and every
        # cut coefficient on it is exactly 0.0 (measured across all 22,000
        # exported cuts, PR-40). The cost-to-go is FLAT in z.
        #
        # This is not a bug to patch here - it is inherent to doing a
        # LOG-space AR in Julia arithmetic. exp(mu + sigma*z) is nonlinear,
        # so it cannot be a linear constraint, which is exactly why the
        # recursion was moved outside the LP in the first place. Making the
        # policy see persistence needs a different formulation (a Markovian
        # policy graph, or a levels-space AR that CAN enter the balance
        # constraint linearly) - a real modelling decision, deliberately
        # left to its own ADR rather than improvised here.
        @variable(subproblem, z[s in SUBSYSTEMS], SDDP.State, initial_value = 0.0)
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
            inputs.shocks_by_month[month],
            inputs.probs_by_month[month],
        ) do omega
            for s in SUBSYSTEMS
                par = inputs.inflow_param_by_month[(month, s)]
                z_in = JuMP.fix_value(z[s].in)
                # shock_sd keeps z's OWN unconditional variance at 1 despite
                # phi varying by month - the same PAR(1) approximation
                # scripts/fit_inflow_par1.py's simulate_par1_correlated
                # already uses in Python (PR-28/29). Omitting it (a real
                # bug caught while verifying this PR against real data,
                # not assumed to be a genuine persistence effect) inflates
                # z's stationary variance to 1/(1-phi^2) - for S's phi up
                # to 0.81, nearly 3x too wide - and roughly doubled every
                # downstream cost/load-shed statistic.
                shock_sd = sqrt(max(1 - par.phi^2, 1e-6))
                z_out = par.phi * z_in + omega[s] * shock_sd
                JuMP.fix(z[s].out, z_out)
                JuMP.fix(inflow[s], exp(par.mu + par.sigma * z_out))
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
    iteration_limit = length(ARGS) >= 7 ? parse(Int, ARGS[7]) : 1000
    n_simulations = length(ARGS) >= 8 ? parse(Int, ARGS[8]) : 100
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
        iteration_limit = iteration_limit,
        print_level = 1,
        log_file = "/dev/null",
        risk_measure = risk_measure,
        # SDDP.jl's pre-training numerical_stability_report probes
        # `parameterize` WITHOUT going through the real state-fixing
        # sequence that actual training/simulation branches use - a real,
        # checked incompatibility (not assumed): `z[s].in`'s `fix_value`
        # (PR-38's AR(1) state, see build_model) genuinely requires a
        # concrete antecedent the generic probe never provides, unlike the
        # coefficient-range analysis it's designed for, which doesn't need
        # one. Disabling it loses only that static, purely informational
        # report - the per-iteration numeric-issue count PR-33's own
        # findings rely on is tracked separately, during real solves, and
        # is unaffected.
        run_numerical_stability_report = false,
    )

    risk_adjusted_bound = SDDP.calculate_bound(model; risk_measure = risk_measure)
    println("Trained. Risk-adjusted bound (R\$): ", risk_adjusted_bound)

    # :stage_objective is not requested here - SDDP.simulate() always
    # includes it automatically in every stage's result dict; it is not a
    # JuMP decision variable that needs listing like the others.
    simulations =
        SDDP.simulate(model, n_simulations, [:storage, :hydro_generation, :thermal_generation, :load_shed])

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
        "iteration_limit" => iteration_limit,
        "n_simulations" => n_simulations,
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
