# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Data acquisition rules.

Every rule here writes both the raw file under `resources/` and its provenance
record under `resources/_provenance/`. Raw data is gitignored and regenerable;
the provenance record is committed, because it is the only thing that can say
which upstream vintage produced a result.

These rules reach the network, so they never run in CI (see `config/test/`).
"""


rule fetch_ons_curva_carga:
    """
    ONS hourly verified load per subsystem, one file per calendar year.

    Wildcarded over `year` because ONS publishes a file per year at a stable
    URL back to 2000; a range in the config expands into one job each.
    """
    output:
        raw="resources/ons/CURVA_CARGA_{year}.csv",
        provenance="resources/_provenance/ons/curva_carga_{year}.json",
    params:
        url=lambda wc: config["sources"]["ons"]["curva_carga"]["url"].format(year=wc.year),
        source="ons",
        dataset=lambda wc: f"curva_carga_{wc.year}",
    log:
        "logs/fetch_ons_curva_carga/{year}.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_capacidade_geracao:
    """
    ONS installed generating capacity, per generating unit. A single current
    file, not year-split - unlike curva_carga, ONS does not publish this one
    with historical vintages at a stable per-year URL.
    """
    output:
        raw="resources/ons/CAPACIDADE_GERACAO.csv",
        provenance="resources/_provenance/ons/capacidade_geracao.json",
    params:
        url=config["sources"]["ons"]["capacidade_geracao"]["url"],
        source="ons",
        dataset="capacidade_geracao",
    log:
        "logs/fetch_ons_capacidade_geracao/run.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_cvu_usina_termica:
    """
    ONS thermal-plant variable cost (CVU), one file per calendar year, weekly
    per-plant granularity within each file. Year-split like curva_carga.
    """
    output:
        raw="resources/ons/CVU_USINA_TERMICA_{year}.csv",
        provenance="resources/_provenance/ons/cvu_usina_termica_{year}.json",
    params:
        url=lambda wc: config["sources"]["ons"]["cvu_usina_termica"]["url"].format(year=wc.year),
        source="ons",
        dataset=lambda wc: f"cvu_usina_termica_{wc.year}",
    log:
        "logs/fetch_ons_cvu_usina_termica/{year}.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_intercambio_nacional:
    """
    ONS real hourly interchange between subsystems, one file per calendar
    year. Year-split like curva_carga. See ADR-0006: this is the ground
    truth for T0's inter-subsystem topology and the source of the
    transfer-capacity proxy used on the resulting Links.
    """
    output:
        raw="resources/ons/INTERCAMBIO_NACIONAL_{year}.csv",
        provenance="resources/_provenance/ons/intercambio_nacional_{year}.json",
    params:
        url=lambda wc: config["sources"]["ons"]["intercambio_nacional"]["url"].format(
            year=wc.year
        ),
        source="ons",
        dataset=lambda wc: f"intercambio_nacional_{wc.year}",
    log:
        "logs/fetch_ons_intercambio_nacional/{year}.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_fator_capacidade:
    """
    ONS hourly wind/solar capacity factor, per plant/plant-group, one file
    per (year, month) from 2022 onward - split by month, not just year,
    because each month alone already runs ~35-40 MB (unit-level hourly
    granularity across ~150-200 plant-groups).
    """
    output:
        raw="resources/ons/FATOR_CAPACIDADE_2_{year}_{month}.csv",
        provenance="resources/_provenance/ons/fator_capacidade_{year}_{month}.json",
    params:
        url=lambda wc: config["sources"]["ons"]["fator_capacidade"]["url"].format(
            year=wc.year, month=wc.month
        ),
        source="ons",
        dataset=lambda wc: f"fator_capacidade_{wc.year}_{wc.month}",
    log:
        "logs/fetch_ons_fator_capacidade/{year}_{month}.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_geracao_usina:
    """
    ONS hourly verified generation per plant, one file per (year, month).
    The largest dataset this project fetches (~66 MB/month): every plant,
    every hour, all technologies including small plants and MMGD.

    Used to constrain hydro by backcasting (ADR-0007) - see that ADR before
    treating anything derived from this as a model *prediction*.
    """
    output:
        raw="resources/ons/GERACAO_USINA_2_{year}_{month}.csv",
        provenance="resources/_provenance/ons/geracao_usina_{year}_{month}.json",
    params:
        url=lambda wc: config["sources"]["ons"]["geracao_usina"]["url"].format(
            year=wc.year, month=wc.month
        ),
        source="ons",
        dataset=lambda wc: f"geracao_usina_{wc.year}_{wc.month}",
    log:
        "logs/fetch_ons_geracao_usina/{year}_{month}.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_ena_subsistema:
    """
    ONS daily natural inflow energy (ENA) per subsystem, one file per
    calendar year, published from 2000 onward. Year range comes from
    `inflow_history_years()`, NOT `snapshot_years()` like every other rule
    here - see that function's docstring (scripts/_common.py) and
    ADR-0005: PAR(p) needs decades of history, not the T0 reference year.
    """
    output:
        raw="resources/ons/ENA_DIARIO_SUBSISTEMA_{year}.csv",
        provenance="resources/_provenance/ons/ena_subsistema_{year}.json",
    params:
        url=lambda wc: config["sources"]["ons"]["ena_subsistema"]["url"].format(year=wc.year),
        source="ons",
        dataset=lambda wc: f"ena_subsistema_{wc.year}",
    log:
        "logs/fetch_ons_ena_subsistema/{year}.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_ear_subsistema:
    """
    ONS daily reservoir storage (EAR) per subsystem, one file per calendar
    year, published from 2000 onward. `ear_max_subsistema` is real max
    storable energy - reservoir capacity for a genuine hydro-thermal SDDP
    policy (ADR-0005 stage 1e), not a fabricated placeholder number.
    """
    output:
        raw="resources/ons/EAR_DIARIO_SUBSISTEMA_{year}.csv",
        provenance="resources/_provenance/ons/ear_subsistema_{year}.json",
    params:
        url=lambda wc: config["sources"]["ons"]["ear_subsistema"]["url"].format(year=wc.year),
        source="ons",
        dataset=lambda wc: f"ear_subsistema_{wc.year}",
    log:
        "logs/fetch_ons_ear_subsistema/{year}.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_ena_ree:
    """
    ONS daily natural inflow energy (ENA) per REE (Reservatorio Equivalente
    de Energia), one file per calendar year, published from 2016 onward -
    shorter than ena_subsistema's 2000-2025 (ADR-0008 stage 2). Same
    inflow_history_years() pattern, its own dataset key.
    """
    output:
        raw="resources/ons/ENA_DIARIO_REE_{year}.csv",
        provenance="resources/_provenance/ons/ena_ree_{year}.json",
    params:
        url=lambda wc: config["sources"]["ons"]["ena_ree"]["url"].format(year=wc.year),
        source="ons",
        dataset=lambda wc: f"ena_ree_{wc.year}",
    log:
        "logs/fetch_ons_ena_ree/{year}.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_ear_ree:
    """
    ONS daily reservoir storage (EAR) per REE, one file per calendar year,
    same 2016-2025 range as ena_ree (ADR-0008 stage 2).
    """
    output:
        raw="resources/ons/EAR_DIARIO_REE_{year}.csv",
        provenance="resources/_provenance/ons/ear_ree_{year}.json",
    params:
        url=lambda wc: config["sources"]["ons"]["ear_ree"]["url"].format(year=wc.year),
        source="ons",
        dataset=lambda wc: f"ear_ree_{wc.year}",
    log:
        "logs/fetch_ons_ear_ree/{year}.log",
    script:
        "../scripts/fetch_dataset.py"


rule fetch_ons_reservatorio:
    """
    ONS per-reservoir physical registry, current snapshot - 162 real
    reservoirs with subsystem, REE, basin/river, volume, elevation and
    turbine productivity (ADR-0008 stage 2). Not year-split, like
    capacidade_geracao. Supplies the real REE-to-subsystem mapping for
    ena_ree/ear_ree, replacing the domain-name inference ADR-0008
    expected to need.
    """
    output:
        raw="resources/ons/RESERVATORIOS.csv",
        provenance="resources/_provenance/ons/reservatorio.json",
    params:
        url=config["sources"]["ons"]["reservatorio"]["url"],
        source="ons",
        dataset="reservatorio",
    log:
        "logs/fetch_ons_reservatorio/run.log",
    script:
        "../scripts/fetch_dataset.py"
