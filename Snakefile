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


RUN_ID = run_id(config)


rule all:
    input:
        f"results/{RUN_ID}/manifest.json",


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
