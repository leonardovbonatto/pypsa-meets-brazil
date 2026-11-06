# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0022's DLR table extraction."""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dlr = _load("extract_dlr", REPO_ROOT / "scripts" / "extract_dlr.py")


def _zip(tmp_path: Path, members: dict[str, str]) -> Path:
    path = tmp_path / "dlr.zip"
    with zipfile.ZipFile(path, "w") as z:
        for inner, text in members.items():
            z.writestr(dlr.ROOT + inner, text)
    return path


class TestExtract:
    def test_copies_each_table_to_its_output(self, tmp_path):
        path = _zip(tmp_path, {inner: f"{key}\n" for key, inner in dlr.TABLES.items()})
        outputs = {key: tmp_path / f"{key}.csv" for key in dlr.TABLES}
        dlr.extract(path, outputs)
        assert outputs["grid_operation"].read_text() == "grid_operation\n"

    def test_missing_table_raises(self, tmp_path):
        path = _zip(tmp_path, {})
        with pytest.raises(ValueError, match="is not in"):
            dlr.extract(path, {key: tmp_path / f"{key}.csv" for key in dlr.TABLES})
