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
