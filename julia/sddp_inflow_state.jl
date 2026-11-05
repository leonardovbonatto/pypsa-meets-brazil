# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
#
# ADR-0011: the policy remembers last month's inflow.
#
# sddp_first_policy.jl remembers storage and a dry/normal/wet regime label
# (ADR-0010). Within a regime, each month's inflow is drawn fresh, so the
# policy cannot tell a deep drought from a mild one: N's month-to-month
# correlation in its training scenarios is 0.46 against 0.88 in the data.
#
# Here each subsystem's inflow is an SDDP.State, linked month to month by the
# levels PAR(1) built in scripts/prepare_sddp_inflow_state.py:
#
#     inflow.out = mu_m + Phi_m * (inflow.in - mu_{m-1}) + shock_scale_m * e
#
# It is linear, so the cuts carry a coefficient on last month's inflow - the
# thing PR-40's log-space `z` state could never get. The graph is linear (12
# nodes): the memory lives in the state, not in regime nodes.
#
# The levels model can produce negative inflow (about 1-4% of months for N,
# NE and S; ADR-0011). A penalised `deficit` tops inflow up to zero. It costs
# DEFICIT_COST, twice LOAD_SHED_COST, so it is never worth buying water with:
# one MWmes of water can avoid at most one MWmes of shedding.
#
# Scoring uses the same 1000 log-PAR(1) paths as every earlier design, as the
# noise values that reproduce each path exactly (prepare_sddp_inflow_state).
#
# Run: julia --project=julia julia/sddp_inflow_state.jl <sddp_inputs_dir> <inflow_state_dir> <output_dir> [seed] [iteration_limit] [n_simulations]

include(joinpath(@__DIR__, "sddp_first_policy.jl"))

const DEFICIT_COST = 2.0 * LOAD_SHED_COST

function load_inflow_state_inputs(sddp_inputs_dir::String, inflow_state_dir::String)
    demand = read_parquet_df(joinpath(sddp_inputs_dir, "demand.parquet"))
    capacity = read_parquet_df(joinpath(sddp_inputs_dir, "capacity.parquet"))
    cost = read_parquet_df(joinpath(sddp_inputs_dir, "cost.parquet"))
    reservoir_capacity = read_parquet_df(joinpath(sddp_inputs_dir, "reservoir_capacity.parquet"))
    initial_storage = read_parquet_df(joinpath(sddp_inputs_dir, "initial_storage.parquet"))
    model = read_parquet_df(joinpath(inflow_state_dir, "inflow_model.parquet"))
    initial_inflow = read_parquet_df(joinpath(inflow_state_dir, "initial_inflow.parquet"))
    noise = read_parquet_df(joinpath(inflow_state_dir, "noise.parquet"))
    scoring_noise = read_parquet_df(joinpath(inflow_state_dir, "scoring_noise.parquet"))

    # (month, subsystem) -> the levels recursion's coefficients.
    recursion = Dict(
        (Int(r.month), r.subsystem) => (mu = r.mu, Phi = r.Phi, mu_prev = r.mu_prev, shock_scale = r.shock_scale)
        for r in eachrow(model)
    )

    noise_by_month = Dict{Int,Vector{Dict{String,Float64}}}()
    probs_by_month = Dict{Int,Vector{Float64}}()
    for month in 1:12
        rows = filter(r -> r.month == month, noise)
        by_scenario = Dict{Int,Dict{String,Float64}}()
        prob = Dict{Int,Float64}()
        for r in eachrow(rows)
            get!(by_scenario, r.scenario, Dict{String,Float64}())[r.subsystem] = r.e
            prob[r.scenario] = r.probability
        end
        ids = sort(collect(keys(by_scenario)))
        noise_by_month[month] = [by_scenario[i] for i in ids]
        probs_by_month[month] = [prob[i] for i in ids]
    end

    # SDDP.Historical on a linear graph: one vector per path of (stage, noise).
    scoring_paths = Vector{Tuple{Int,Dict{String,Float64}}}[]
    for path_rows in groupby(scoring_noise, :path)
        stages = Tuple{Int,Dict{String,Float64}}[]
        for month_rows in groupby(sort(DataFrame(path_rows), :month), :month)
            push!(stages, (Int(month_rows.month[1]), Dict(r.subsystem => r.e for r in eachrow(month_rows))))
        end
        push!(scoring_paths, stages)
    end

    return (;
        links = load_links(sddp_inputs_dir),
        renewables = load_renewables(sddp_inputs_dir),
        thermal_floor = load_thermal_floor(sddp_inputs_dir),
        hydro_cap = Dict(r.subsystem => r.hydro_mw for r in eachrow(capacity)),
        thermal_cap = Dict(r.subsystem => r.thermal_mw for r in eachrow(capacity)),
        thermal_marginal_cost = Dict(r.subsystem => r.marginal_cost for r in eachrow(cost)),
        max_storage = Dict(r.subsystem => r.ear_max_mwmes for r in eachrow(reservoir_capacity)),
        storage0 = Dict(r.subsystem => r.initial_storage_mwmes for r in eachrow(initial_storage)),
        inflow0 = Dict(r.subsystem => r.initial_inflow_mwmed for r in eachrow(initial_inflow)),
        demand_by_month = Dict((r.month, r.subsystem) => r.demand_mw for r in eachrow(demand)),
        recursion,
        noise_by_month,
        probs_by_month,
        scoring_paths,
    )
end

function build_inflow_state_model(inputs)
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
        # Free: the levels model can go negative, and the next month's
        # recursion needs the raw value, not the topped-up one.
        @variable(subproblem, inflow[s in SUBSYSTEMS], SDDP.State, initial_value = inputs.inflow0[s])
        @variable(subproblem, 0 <= hydro_generation[s in SUBSYSTEMS] <= inputs.hydro_cap[s])
        @variable(
            subproblem,
            inputs.thermal_floor[(month, s)] <= thermal_generation[s in SUBSYSTEMS] <=
            inputs.thermal_cap[s]
        )
        @variable(subproblem, spill[s in SUBSYSTEMS] >= 0)
        @variable(subproblem, load_shed[s in SUBSYSTEMS] >= 0)
        @variable(subproblem, deficit[s in SUBSYSTEMS] >= 0)
        @variable(subproblem, noise[s in SUBSYSTEMS])
        net_import = add_transmission(subproblem, inputs.links)
        renewable = add_renewables(subproblem, inputs.renewables, month)

        @constraint(
            subproblem,
            [s in SUBSYSTEMS],
            inflow[s].out ==
            inputs.recursion[(month, s)].mu +
            inputs.recursion[(month, s)].Phi * (inflow[s].in - inputs.recursion[(month, s)].mu_prev) +
            inputs.recursion[(month, s)].shock_scale * noise[s]
        )
        @constraint(subproblem, [s in SUBSYSTEMS], inflow[s].out + deficit[s] >= 0)
        @constraint(
            subproblem,
            [s in SUBSYSTEMS],
            storage[s].out ==
            storage[s].in - hydro_generation[s] - spill[s] + inflow[s].out + deficit[s]
        )
        @constraint(
            subproblem,
            [s in SUBSYSTEMS],
            hydro_generation[s] + thermal_generation[s] + load_shed[s] + net_import[s] +
            renewable[s] == inputs.demand_by_month[(month, s)]
        )

        SDDP.@stageobjective(
            subproblem,
            (HOURS_PER_MONTH[month] / MONEY_SCALE) * sum(
                inputs.thermal_marginal_cost[s] * thermal_generation[s] +
                LOAD_SHED_COST * load_shed[s] +
                DEFICIT_COST * deficit[s] for s in SUBSYSTEMS
            )
        )

        SDDP.parameterize(subproblem, inputs.noise_by_month[month], inputs.probs_by_month[month]) do omega
            for s in SUBSYSTEMS
                JuMP.fix(noise[s], omega[s])
            end
        end
    end
end

"""
How much water the deficit slack supplied, per subsystem: its share of the
effective inflow (inflow plus deficit) over all simulated months, the share of
months in which it was used, and its penalty cost in R\$ per year. ADR-0011
fails a run where S's share exceeds 1%.
"""
function deficit_stats(simulations)
    stats = Dict{String,Any}()
    for s in SUBSYSTEMS
        deficit = [stage[:deficit][s] for realization in simulations for stage in realization]
        inflow = [stage[:inflow][s].out for realization in simulations for stage in realization]
        stats[s] = Dict(
            "share_of_inflow_energy" => sum(deficit) / sum(inflow .+ deficit),
            "share_of_months_used" => count(>(1e-9), deficit) / length(deficit),
            "penalty_cost_rs_per_year" =>
                MONEY_SCALE * sum(
                    (HOURS_PER_MONTH[t] / MONEY_SCALE) * DEFICIT_COST * stage[:deficit][s] for
                    realization in simulations for (t, stage) in enumerate(realization)
                ) / length(simulations),
        )
    end
    return stats
end

function inflow_state_limitations()
    return [
        "ADR-0011: last month's inflow is a state, linked by a levels PAR(1); " *
        "the policy graph is linear (12 nodes), with no regime labels.",
        "The levels model can give negative inflow; a deficit slack at twice " *
        "the load-shed cost tops it up to zero. Its share is reported per subsystem.",
        "Training noise is one set per month (n_noise draws), a three-parameter " *
        "lognormal where residuals are right-skewed, with a floor fixed per month.",
        "Scored on the same 1000 log-PAR(1) paths as ADR-0010's policy, as the " *
        "noise values that reproduce each path; those may fall outside the training support.",
        "The initial inflow state is the observed December 2025 mean, the same " *
        "date as the initial storage.",
        "12 monthly stages, one annual cycle; transmission as in " *
        "sddp_first_policy.jl (ADR-0012); renewables and nuclear as monthly " *
        "net load with free curtailment (ADR-0013).",
    ]
end

function inflow_state_main()
    sddp_inputs_dir = ARGS[1]
    inflow_state_dir = ARGS[2]
    output_dir = ARGS[3]
    seed = length(ARGS) >= 4 ? parse(Int, ARGS[4]) : 0
    iteration_limit = length(ARGS) >= 5 ? parse(Int, ARGS[5]) : 1000
    n_simulations = length(ARGS) >= 6 ? parse(Int, ARGS[6]) : 100
    mkpath(output_dir)
    Random.seed!(seed)

    inputs = load_inflow_state_inputs(sddp_inputs_dir, inflow_state_dir)
    model = build_inflow_state_model(inputs)
    parallel_scheme = Threads.nthreads() > 1 ? SDDP.Threaded() : SDDP.Serial()
    println("Parallel scheme: ", parallel_scheme, " with ", Threads.nthreads(), " threads")
    SDDP.train(
        model;
        parallel_scheme = parallel_scheme,
        stopping_rules = [SDDP.SimulationStoppingRule()],
        iteration_limit = iteration_limit,
        print_level = 1,
        log_file = "/dev/null",
        run_numerical_stability_report = false,
    )
    bound = SDDP.calculate_bound(model) * MONEY_SCALE
    println("Trained. Bound (R\$): ", bound)

    recorded = [:storage, :inflow, :deficit, :load_shed, :flow, :curtailment]
    simulations = SDDP.simulate(model, n_simulations, recorded)
    in_sample = simulation_stats(simulations)
    in_sample_deficit = deficit_stats(simulations)
    println("In-sample mean cost (R\$, includes deficit penalty): ", in_sample.expected_cost)

    scored = SDDP.simulate(
        model,
        length(inputs.scoring_paths),
        recorded;
        sampling_scheme = SDDP.Historical(inputs.scoring_paths),
    )
    out_of_sample = simulation_stats(scored)
    out_of_sample_deficit = deficit_stats(scored)
    println("PAR(1) out-of-sample mean cost (R\$): ", out_of_sample.expected_cost)
    println(
        "PAR(1) out-of-sample Mean/P50/P90 load shed (MW-months): ",
        out_of_sample.mean_load_shed,
        " / ",
        out_of_sample.p50_load_shed,
        " / ",
        out_of_sample.p90_load_shed,
    )
    for s in SUBSYSTEMS
        println("  deficit share ", s, ": in-sample ", in_sample_deficit[s]["share_of_inflow_energy"])
    end

    cuts_json_path = joinpath(output_dir, "_cuts.json")
    SDDP.write_cuts_to_file(model, cuts_json_path)
    cuts = SDDP.JSON.parsefile(cuts_json_path)
    rows = NamedTuple[]
    for node in cuts
        node_stage, node_state = parse_cut_node(node["node"])
        for cut in node["single_cuts"]
            state_names = collect(keys(cut["coefficients"]))
            push!(
                rows,
                (
                    node = string(node["node"]),
                    stage = node_stage,
                    markov_state = node_state,
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
        "cuts_money_scale" => MONEY_SCALE,
        "cuts_units" => "millions of R\$ per MWmes (storage) and per MWmed (inflow); multiply by cuts_money_scale for R\$",
        "risk_kind" => "expectation",
        "bound_rs" => bound,
        "deficit_cost_rs_per_mwh" => DEFICIT_COST,
        "expected_total_cost_rs" => in_sample.expected_cost,
        "mean_annual_load_shed_mw_months" => in_sample.mean_load_shed,
        "p90_annual_load_shed_mw_months" => in_sample.p90_load_shed,
        "mean_annual_load_shed_by_subsystem" => in_sample.load_shed_by_subsystem,
        "deficit" => in_sample_deficit,
        "par1_out_of_sample" => Dict(
            "n_paths" => length(inputs.scoring_paths),
            "expected_total_cost_rs" => out_of_sample.expected_cost,
            "mean_annual_load_shed_mw_months" => out_of_sample.mean_load_shed,
            "p50_annual_load_shed_mw_months" => out_of_sample.p50_load_shed,
            "p90_annual_load_shed_mw_months" => out_of_sample.p90_load_shed,
            "mean_annual_load_shed_by_subsystem" => out_of_sample.load_shed_by_subsystem,
            "deficit" => out_of_sample_deficit,
            "transmission" => flow_stats(scored, inputs.links),
        ),
        "n_cuts" => length(rows),
        "known_limitations" => inflow_state_limitations(),
    )
    open(joinpath(output_dir, "summary.json"), "w") do io
        SDDP.JSON.print(io, summary, 2)
    end
    println("Wrote ", length(rows), " cuts and summary.json to ", output_dir)
end

if abspath(PROGRAM_FILE) == @__FILE__
    inflow_state_main()
end
