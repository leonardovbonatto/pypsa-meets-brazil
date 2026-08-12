# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for run-manifest construction and config hashing."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    """Import a module from a path — `scripts/` is not an installed package."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


write_manifest = _load("write_manifest", REPO_ROOT / "scripts" / "write_manifest.py")
common = _load("_common", REPO_ROOT / "scripts" / "_common.py")


BASE_CONFIG = {"tier": "t0", "run_name": None, "snapshots": {"start": "2024-01-01"}}


class TestConfigHash:
    def test_is_deterministic(self):
        assert common.config_hash(BASE_CONFIG) == common.config_hash(BASE_CONFIG)

    def test_ignores_key_order(self):
        """The hash must depend on content, not on how the dict was assembled."""
        reordered = {"snapshots": {"start": "2024-01-01"}, "run_name": None, "tier": "t0"}
        assert common.config_hash(BASE_CONFIG) == common.config_hash(reordered)

    def test_detects_nested_change(self):
        """A change buried in a nested key must still change the hash."""
        changed = {**BASE_CONFIG, "snapshots": {"start": "2024-01-02"}}
        assert common.config_hash(BASE_CONFIG) != common.config_hash(changed)


class TestRunId:
    def test_explicit_name_wins(self):
        assert common.run_id({**BASE_CONFIG, "run_name": "smoke"}) == "smoke"

    def test_falls_back_to_tier_and_hash(self):
        rid = common.run_id(BASE_CONFIG)
        assert rid.startswith("t0-")
        assert len(rid) == len("t0-") + 8

    def test_differing_configs_do_not_collide(self):
        other = {**BASE_CONFIG, "tier": "t0", "snapshots": {"start": "2024-06-01"}}
        assert common.run_id(BASE_CONFIG) != common.run_id(other)


class TestManifest:
    def test_records_required_fields(self):
        m = write_manifest.build_manifest("smoke", BASE_CONFIG, "deadbeef")

        assert m["run_id"] == "smoke"
        assert m["config_hash"] == "deadbeef"
        assert m["config"] == BASE_CONFIG
        assert set(m) >= {"created_utc", "git", "environment", "inputs"}
        assert set(m["git"]) == {"sha", "branch", "dirty"}

    def test_is_json_serialisable(self):
        """The manifest is written as JSON; a non-serialisable field must fail here."""
        m = write_manifest.build_manifest("smoke", BASE_CONFIG, "deadbeef")
        assert json.loads(json.dumps(m)) == m

    def test_collects_provenance_records(self, tmp_path, monkeypatch):
        prov = tmp_path / "prov"
        (prov / "ons").mkdir(parents=True)
        (prov / "ons" / "carga.json").write_text('{"sha256": "abc", "rows": 42}')
        monkeypatch.setattr(write_manifest, "PROVENANCE_DIR", prov)

        records = write_manifest.collect_provenance()
        assert records["ons/carga.json"]["rows"] == 42

    def test_corrupt_provenance_is_reported_not_dropped(self, tmp_path, monkeypatch):
        """A malformed record must stay visible in the manifest, not disappear."""
        prov = tmp_path / "prov"
        prov.mkdir()
        (prov / "broken.json").write_text("{not json")
        monkeypatch.setattr(write_manifest, "PROVENANCE_DIR", prov)

        records = write_manifest.collect_provenance()
        assert "error" in records["broken.json"]

    def test_missing_provenance_dir_is_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(write_manifest, "PROVENANCE_DIR", tmp_path / "absent")
        assert write_manifest.collect_provenance() == {}


@pytest.mark.parametrize("cfg_path", sorted((REPO_ROOT / "config").rglob("*.yaml")))
def test_shipped_configs_are_valid(cfg_path):
    """Every committed config must parse and carry the keys the workflow needs."""
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    assert cfg["tier"] in {"t0", "t1", "t2", "t3"}
    assert {"start", "end", "resolution"} <= set(cfg["snapshots"])
    assert cfg["solver"]["name"]
