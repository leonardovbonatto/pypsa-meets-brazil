# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Shared imports for rule files.

The implementations live in `scripts/_common.py` so they can be unit tested;
this file only makes them visible to the workflow namespace.
"""

import sys
from pathlib import Path

# Snakemake executes with the repository root as cwd, but `scripts/` is not on
# sys.path by default. Resolve relative to this file so the import works
# regardless of how the workflow was invoked.
sys.path.insert(0, str(Path(workflow.basedir) / "scripts"))

from _common import config_hash, run_id  # noqa: E402,F401
