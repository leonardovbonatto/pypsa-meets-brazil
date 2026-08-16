# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
#
# ADR-0005 stage-1 feasibility smoke test: SDDP.jl's own textbook
# hydro-thermal scheduling example (single reservoir, 3 stages, stochastic
# inflow, thermal backup), trained, with the resulting Benders cuts written
# to Parquet - the exact cross-language artifact PRIMER Sec 4.5/5.10
# describes. Deliberately no Brazilian data: this proves the Julia -> SDDP
# -> Parquet -> (eventually) Python coupling works at all, independent of
# whether the real inflow/reservoir model is right.
#
# Run: julia --project=julia julia/smoke_test.jl [output_path]

using SDDP
using HiGHS
using DataFrames
using Parquet2

function build_model()
    return SDDP.LinearPolicyGraph(
        stages = 3,
        sense = :Min,
        lower_bound = 0.0,
        optimizer = HiGHS.Optimizer,
    ) do subproblem, t
        @variable(subproblem, 0 <= volume <= 200, SDDP.State, initial_value = 200)
        @variables(subproblem, begin
            thermal_generation >= 0
            hydro_generation >= 0
            hydro_spill >= 0
            inflow
        end)
        @constraints(subproblem, begin
            volume.out == volume.in - hydro_generation - hydro_spill + inflow
            thermal_generation + hydro_generation == 150.0
        end)
        fuel_cost = [50.0, 100.0, 150.0]
        SDDP.@stageobjective(subproblem, fuel_cost[t] * thermal_generation)
        inflow_realizations = [0.0, 50.0, 100.0]
        probability = [1 / 3, 1 / 3, 1 / 3]
        SDDP.parameterize(subproblem, inflow_realizations, probability) do omega
            JuMP.fix(inflow, omega)
        end
    end
end

"""
Flatten SDDP.jl's native cut JSON (one entry per node, each with a list of
cuts made of an intercept and per-state-variable coefficients) into one row
per cut - the shape a downstream linopy constraint-builder actually wants:
one Benders cut per row, ready to loop over.
"""
function cuts_to_dataframe(cuts_json_path::String)
    nodes = SDDP.JSON.parsefile(cuts_json_path)
    rows = NamedTuple[]
    for node in nodes
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
    return DataFrame(rows)
end

function main()
    output_path = length(ARGS) >= 1 ? ARGS[1] : joinpath(@__DIR__, "smoke_test_cuts.parquet")

    model = build_model()
    # log_file defaults to "SDDP.log" in the current directory - redundant
    # with Snakemake's own {log} redirect of this whole script's stdout, and
    # would otherwise litter the repo root every run.
    SDDP.train(model; iteration_limit = 20, print_level = 1, log_file = "/dev/null")

    lower_bound = SDDP.calculate_bound(model)
    println("Trained. Lower bound (expected cost, R\$-equivalent units): ", lower_bound)

    cuts_json_path = joinpath(@__DIR__, "_smoke_test_cuts.json")
    SDDP.write_cuts_to_file(model, cuts_json_path)
    cuts = cuts_to_dataframe(cuts_json_path)
    rm(cuts_json_path)

    Parquet2.writefile(output_path, cuts)
    println("Wrote ", nrow(cuts), " cuts to ", output_path)
    return lower_bound, nrow(cuts)
end

main()
