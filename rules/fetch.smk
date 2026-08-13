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
