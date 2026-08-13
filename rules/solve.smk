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
