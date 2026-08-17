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
    installed capacity. Capacity and topology only from this rule - cost
    (build_costs_t0) and availability (build_availability_t0,
    build_hydro_availability_t0, build_mmgd_t0) are separate rules, combined
    downstream in build_network_t0.
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


rule build_costs_t0:
    """
    T0 thermal marginal cost: one row per subsystem, R$/MWh.

    Reduces weekly per-plant CVU to a single mean per subsystem - not a
    per-plant join against generators_t0.csv, which this dataset's plant
    identities don't support (see docs/handoffs/PR-09-ons-cvu-connector.md).
    """
    input:
        raw=expand(
            "resources/ons/CVU_USINA_TERMICA_{year}.csv",
            year=snapshot_years(config),
        ),
        dictionary="docs/data-dictionary/ons/cvu_usina_termica.yaml",
    output:
        "resources/costs_t0.csv",
    params:
        subsystems=config["subsystems"],
    log:
        "logs/build_costs_t0/run.log",
    script:
        "../scripts/build_costs.py"


rule build_links_t0:
    """
    T0 inter-subsystem transfer capacity: one row per real ONS boundary
    (ADR-0006), MW. p_nom is the largest absolute historical flow observed
    on that boundary - a documented lower-bound proxy for true transfer
    capacity, not a rated value.
    """
    input:
        raw=expand(
            "resources/ons/INTERCAMBIO_NACIONAL_{year}.csv",
            year=snapshot_years(config),
        ),
        dictionary="docs/data-dictionary/ons/intercambio_nacional.yaml",
    output:
        "resources/links_t0.csv",
    params:
        subsystems=config["subsystems"],
    log:
        "logs/build_links_t0/run.log",
    script:
        "../scripts/build_links.py"


rule build_availability_t0:
    """
    T0 wind/solar availability profile: one row per (snapshot, subsystem,
    technology) that has real data, p_max_pu (dimensionless, [0,1]).

    Aggregate fleet capacity factor (sum generation / sum capacity, not a
    naive mean of the per-plant-group ratio - see build_availability.py) per
    (subsystem, technology, hour). SE_CO wind has no data in this dataset at
    all (see docs/handoffs/PR-14-*.md) - deliberately absent here, handled
    explicitly in build_network.attach_availability().
    """
    input:
        raw=[
            f"resources/ons/FATOR_CAPACIDADE_2_{year}_{month:02d}.csv"
            for year, month in snapshot_year_months(config)
        ],
        dictionary="docs/data-dictionary/ons/fator_capacidade.yaml",
    output:
        "resources/availability_t0.csv",
    log:
        "logs/build_availability_t0/run.log",
    script:
        "../scripts/build_availability.py"


rule build_hydro_availability_t0:
    """
    T0 hydro availability profile, from OBSERVED generation (ADR-0007).

    This is a backcast, not an optimisation: it tells the model what hydro
    actually did. Read ADR-0007 before presenting anything derived from it.
    """
    input:
        raw=[
            f"resources/ons/GERACAO_USINA_2_{year}_{month:02d}.csv"
            for year, month in snapshot_year_months(config)
        ],
        dictionary="docs/data-dictionary/ons/geracao_usina.yaml",
        capacity="resources/generators_t0.csv",
    output:
        "resources/hydro_availability_t0.csv",
    log:
        "logs/build_hydro_availability_t0/run.log",
    script:
        "../scripts/build_hydro_availability.py"


rule build_mmgd_t0:
    """
    T0 MMGD (distributed rooftop PV) capacity and hourly availability, from
    observed generation. Backcast, same principle as hydro (ADR-0007).

    Closes the gap PR-18 quantified: ~5.1 GW of real MMGD output that
    capacidade_geracao does not cover, against ~4.9 GW of spurious thermal.
    """
    input:
        raw=[
            f"resources/ons/GERACAO_USINA_2_{year}_{month:02d}.csv"
            for year, month in snapshot_year_months(config)
        ],
        dictionary="docs/data-dictionary/ons/geracao_usina.yaml",
    output:
        capacity="resources/mmgd_generators_t0.csv",
        availability="resources/mmgd_availability_t0.csv",
    log:
        "logs/build_mmgd_t0/run.log",
    script:
        "../scripts/build_mmgd.py"


rule build_inflow:
    """
    Tidy historical inflow (ENA) series, all four published figures
    (gross/storable x MWmed/% of long-term average), from ONS's daily
    per-subsystem dataset (ADR-0005, SDDP epic stage 1).

    Not T0-specific and not wired into build_network_t0: this feeds the
    separate SDDP/PAR(p) pipeline (still PLANNED, see docs/STACK.md), not
    the T0 network, which still uses ADR-0007's hydro backcast. Year range
    comes from inflow_history_years(), not snapshot_years() - see that
    function's docstring.
    """
    input:
        raw=expand(
            "resources/ons/ENA_DIARIO_SUBSISTEMA_{year}.csv",
            year=inflow_history_years(config),
        ),
        dictionary="docs/data-dictionary/ons/ena_subsistema.yaml",
    output:
        "resources/inflow_ena.csv",
    params:
        subsystems=config["subsystems"],
    log:
        "logs/build_inflow/run.log",
    script:
        "../scripts/build_inflow.py"


rule build_reservoir:
    """
    Tidy historical reservoir storage (EAR) series and current reservoir
    capacity per subsystem, from ONS's daily per-subsystem dataset
    (ADR-0005, SDDP epic stage 1e). Real capacity, not fabricated - see
    scripts/build_reservoir.py and docs/handoffs/PR-30-*.md.

    Not T0-specific, like build_inflow: feeds the separate SDDP pipeline.
    Year range comes from inflow_history_years(config, dataset=
    "ear_subsistema"), independent of ena_subsistema's own range even
    though both currently happen to span the same years.
    """
    input:
        raw=expand(
            "resources/ons/EAR_DIARIO_SUBSISTEMA_{year}.csv",
            year=inflow_history_years(config, dataset="ear_subsistema"),
        ),
        dictionary="docs/data-dictionary/ons/ear_subsistema.yaml",
    output:
        history="resources/reservoir_ear_history.csv",
        capacity="resources/reservoir_ear_capacity.csv",
    params:
        subsystems=config["subsystems"],
    log:
        "logs/build_reservoir/run.log",
    script:
        "../scripts/build_reservoir.py"


rule build_reservoir_registry:
    """
    Tidy per-reservoir physical registry and the REE-to-subsystem mapping
    ena_ree/ear_ree need (ADR-0008 stage 2) - real data, not the
    domain-name inference ADR-0008 expected to need. See
    scripts/build_reservoir_registry.py and docs/handoffs/PR-35-*.md.

    Single current snapshot, like build_generators_t0/capacidade_geracao -
    not year-split.
    """
    input:
        raw="resources/ons/RESERVATORIOS.csv",
        dictionary="docs/data-dictionary/ons/reservatorio.yaml",
    output:
        registry="resources/reservoir_registry.csv",
        ree_map="resources/ree_subsystem_map.csv",
    log:
        "logs/build_reservoir_registry/run.log",
    script:
        "../scripts/build_reservoir_registry.py"


rule build_inflow_ree:
    """
    REE-level counterpart of build_inflow (ADR-0008 stage 2) - see
    scripts/build_inflow_ree.py and docs/handoffs/PR-36-*.md.

    Deliberately does NOT require every REE to share the same date count,
    unlike build_inflow: 3 REEs only exist as separately-tracked units
    from 2017-12-30 onward, a real REE-structure revision, not a gap.
    """
    input:
        raw=expand(
            "resources/ons/ENA_DIARIO_REE_{year}.csv",
            year=inflow_history_years(config, dataset="ena_ree"),
        ),
        dictionary="docs/data-dictionary/ons/ena_ree.yaml",
        ree_map="resources/ree_subsystem_map.csv",
    output:
        "resources/inflow_ena_ree.csv",
    log:
        "logs/build_inflow_ree/run.log",
    script:
        "../scripts/build_inflow_ree.py"


rule build_reservoir_ree:
    """
    REE-level counterpart of build_reservoir (ADR-0008 stage 2) - see
    scripts/build_reservoir_ree.py and docs/handoffs/PR-36-*.md.

    Clips both a below-zero and an over-capacity boundary quirk, real and
    checked, concentrated in the smallest-capacity REEs - see the
    ear_ree.yaml data dictionary's notes.
    """
    input:
        raw=expand(
            "resources/ons/EAR_DIARIO_REE_{year}.csv",
            year=inflow_history_years(config, dataset="ear_ree"),
        ),
        dictionary="docs/data-dictionary/ons/ear_ree.yaml",
        ree_map="resources/ree_subsystem_map.csv",
    output:
        history="resources/reservoir_ear_history_ree.csv",
        capacity="resources/reservoir_ear_capacity_ree.csv",
    log:
        "logs/build_reservoir_ree/run.log",
    script:
        "../scripts/build_reservoir_ree.py"


rule build_network_t0:
    """
    T0 network: one bus per subsystem, snapshots from config, the tidy demand
    series attached as time-varying loads, the aggregated generator capacity
    (including a distinct MMGD carrier) attached as one Generator per
    (subsystem, technology), a marginal_cost on every generator,
    inter-subsystem transfer Links (ADR-0006), real hourly wind/solar
    availability plus backcast hydro and MMGD availability (ADR-0007), and a
    load-shedding backstop generator per bus. Links are a transport model, not
    real transmission physics with impedances - a permanent T0 simplification
    per ADR-0006, not a stopgap.
    """
    input:
        demand="resources/demand_t0.csv",
        generators="resources/generators_t0.csv",
        mmgd_generators="resources/mmgd_generators_t0.csv",
        links="resources/links_t0.csv",
        availability="resources/availability_t0.csv",
        hydro_availability="resources/hydro_availability_t0.csv",
        mmgd_availability="resources/mmgd_availability_t0.csv",
        costs="resources/costs_t0.csv",
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
        "resources/mmgd_generators_t0.csv",
        "resources/links_t0.csv",
        "resources/availability_t0.csv",
        "resources/hydro_availability_t0.csv",
        "resources/mmgd_availability_t0.csv",
        "resources/costs_t0.csv",
        "resources/networks/t0.nc",
        "resources/inflow_ena.csv",
        "resources/reservoir_ear_history.csv",
        "resources/reservoir_ear_capacity.csv",
        "resources/reservoir_registry.csv",
        "resources/ree_subsystem_map.csv",
        "resources/inflow_ena_ree.csv",
        "resources/reservoir_ear_history_ree.csv",
        "resources/reservoir_ear_capacity_ree.csv",
