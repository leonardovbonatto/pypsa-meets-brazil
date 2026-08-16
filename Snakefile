# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Workflow entrypoint.

Run:
    pixi run dry      # resolve the DAG without executing (cheapest sanity check)
    pixi run smoke    # end-to-end run on the tiny smoke config
"""

from pathlib import Path

configfile: "config/config.default.yaml"


include: "rules/common.smk"
include: "rules/fetch.smk"
include: "rules/build.smk"
include: "rules/solve.smk"
include: "rules/sddp.smk"


RUN_ID = run_id(config)


rule all:
    input:
        f"results/{RUN_ID}/manifest.json",


rule solve_all:
    """
    Solve every configured T0 artifact.

    Also network-reaching, transitively, via the fetch -> build chain the
    solved network depends on; see fetch_all/build_all for why this stays
    outside `all`.
    """
    input:
        f"results/{RUN_ID}/network_t0_solved.nc",
        f"results/{RUN_ID}/dispatch_summary_t0.json",


rule fetch_all:
    """
    Acquire every configured upstream dataset, for every year the configured
    snapshot range spans.

    Deliberately NOT a dependency of `all`: these rules reach the network, and
    CI must be able to run the whole default workflow on committed fixtures
    without downloading anything (ADR-0001). Fetching is an explicit request.
    """
    input:
        expand(
            "resources/ons/CURVA_CARGA_{year}.csv",
            year=snapshot_years(config),
        ),
        expand(
            "resources/ons/CVU_USINA_TERMICA_{year}.csv",
            year=snapshot_years(config),
        ),
        expand(
            "resources/ons/INTERCAMBIO_NACIONAL_{year}.csv",
            year=snapshot_years(config),
        ),
        [
            f"resources/ons/FATOR_CAPACIDADE_2_{year}_{month:02d}.csv"
            for year, month in snapshot_year_months(config)
        ],
        [
            f"resources/ons/GERACAO_USINA_2_{year}_{month:02d}.csv"
            for year, month in snapshot_year_months(config)
        ],
        "resources/ons/CAPACIDADE_GERACAO.csv",


rule write_run_manifest:
    """
    Emit the run manifest required by ADR-0001 §4: config hash, git SHA, and the
    provenance hashes of every input that fed this run.

    Currently the only rule in the workflow, so it doubles as proof that the DAG
    resolves. It is not a placeholder — this manifest is what makes a result
    reproducible, and every later rule feeds it.
    """
    output:
        "results/{run}/manifest.json",
    params:
        config_hash=lambda wc: config_hash(config),
    log:
        "logs/write_run_manifest/{run}.log",
    script:
        "scripts/write_manifest.py"
