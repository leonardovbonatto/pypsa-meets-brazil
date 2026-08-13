# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build rules: turn fetched raw data into tidy, model-ready artifacts.

Like `fetch.smk`, these depend on real fetched data and are deliberately not
part of `all` — CI has none of it. Snakemake still resolves the chain
automatically: asking for `resources/demand_t0.csv` triggers the fetch rule
first if the raw yearly files are missing.
"""


rule build_demand_t0:
    """
    Tidy T0 demand series: one row per (snapshot, subsystem), load in MW.

    Validates the fetched frame against the committed data dictionary before
    doing anything else, maps ONS subsystem codes onto the config's SE_CO/S/NE/N
    labels, and checks the result has no gaps or duplicate hours per subsystem.
    """
    input:
        raw=expand(
            "resources/ons/CURVA_CARGA_{year}.csv",
            year=snapshot_years(config),
        ),
        dictionary="docs/data-dictionary/ons/curva_carga.yaml",
    output:
        "resources/demand_t0.csv",
    params:
        subsystems=config["subsystems"],
    log:
        "logs/build_demand_t0/run.log",
    script:
        "../scripts/build_demand.py"


rule build_generators_t0:
    """
    T0 generator capacity: one row per (subsystem, technology), MW.

    Filters to active units, maps ONS subsystem codes (dropping PY - see
    scripts/_ons.py) and plant types onto this project's labels, and sums
    installed capacity. Capacity and topology only - no cost, no availability
    profile yet (see docs/handoffs/PR-08-*.md).
    """
    input:
        raw="resources/ons/CAPACIDADE_GERACAO.csv",
        dictionary="docs/data-dictionary/ons/capacidade_geracao.yaml",
    output:
        "resources/generators_t0.csv",
    params:
        subsystems=config["subsystems"],
    log:
        "logs/build_generators_t0/run.log",
    script:
        "../scripts/build_generators.py"


rule build_network_t0:
    """
    T0 network: one bus per subsystem, snapshots from config, the tidy demand
    series attached as time-varying loads, and the aggregated generator
    capacity attached as one Generator per (subsystem, technology). No lines,
    no marginal cost, no availability profile, no solver yet - see
    docs/handoffs/PR-08-*.md.
    """
    input:
        demand="resources/demand_t0.csv",
        generators="resources/generators_t0.csv",
    output:
        "resources/networks/t0.nc",
    params:
        subsystems=config["subsystems"],
    log:
        "logs/build_network_t0/run.log",
    script:
        "../scripts/build_network.py"


rule build_all:
    """Build every configured model-ready artifact. Also network-reaching; see fetch_all."""
    input:
        "resources/demand_t0.csv",
        "resources/generators_t0.csv",
        "resources/networks/t0.nc",
