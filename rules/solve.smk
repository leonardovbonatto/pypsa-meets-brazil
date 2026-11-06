# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Solve rules: run the optimization and write a dispatch summary.

Like `build.smk`, deliberately not part of `all` - the network these solve
depends on the whole fetch -> build chain, which CI cannot run offline.
"""


rule solve_network_t0:
    """
    Solve the T0 network with the configured solver and write a dispatch
    summary alongside it.

    A clean "optimal" status is necessary but not sufficient for the result
    to be physically meaningful: see scripts/solve_network.py's
    KNOWN_LIMITATIONS (written into the summary itself) and
    docs/handoffs/PR-11-*.md before trusting a number out of this.
    """
    input:
        "resources/networks/t0.nc",
    output:
        network="results/{run}/network_t0_solved.nc",
        summary="results/{run}/dispatch_summary_t0.json",
    params:
        solver_name=config["solver"]["name"],
        solver_options=config["solver"]["options"],
    log:
        "logs/solve_network_t0/{run}.log",
    script:
        "../scripts/solve_network.py"


rule check_phase1_gate:
    """
    ADR-0020: the roadmap's Phase 1 gate. Scores the solved T0 network's
    2024 national wind, utility solar, nuclear and thermal generation (within
    5% of ONS) and each boundary's mean flow (within 5% of capacity). The
    report always gets written; `passed` in it is the verdict.
    """
    input:
        network="results/{run}/network_t0_solved.nc",
        generation=[
            f"resources/ons/GERACAO_USINA_2_{year}_{month:02d}.csv"
            for year, month in snapshot_year_months(config)
        ],
        interchange=expand(
            "resources/ons/INTERCAMBIO_NACIONAL_{year}.csv",
            year=snapshot_years(config),
        ),
        links="resources/links_t0.csv",
    output:
        generation="results/{run}/phase1_gate/generation.csv",
        interchange="results/{run}/phase1_gate/interchange.csv",
        report="results/{run}/phase1_gate/report.json",
    log:
        "logs/check_phase1_gate/{run}.log",
    script:
        "../scripts/check_phase1_gate.py"


rule solve_network_t1:
    """ADR-0022: solve the T1 (state) network with the configured solver."""
    input:
        "resources/networks/t1.nc",
    output:
        network="results/{run}/network_t1_solved.nc",
        summary="results/{run}/dispatch_summary_t1.json",
    params:
        solver_name=config["solver"]["name"],
        solver_options=config["solver"]["options"],
    log:
        "logs/solve_network_t1/{run}.log",
    script:
        "../scripts/solve_network.py"


rule check_t1_gate:
    """
    ADR-0022 decision 5: T1's national generation within 1% of T0's, and its
    inter-subsystem flows scored with ADR-0020's interchange criterion.
    """
    input:
        t1="results/{run}/network_t1_solved.nc",
        t0="results/{run}/network_t0_solved.nc",
        nodes="resources/t1/nodes.csv",
        interchange=expand(
            "resources/ons/INTERCAMBIO_NACIONAL_{year}.csv",
            year=snapshot_years(config),
        ),
        links_t0="resources/links_t0.csv",
    output:
        report="results/{run}/t1_gate/report.json",
    log:
        "logs/check_t1_gate/{run}.log",
    script:
        "../scripts/check_t1_gate.py"
