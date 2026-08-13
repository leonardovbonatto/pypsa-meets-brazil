# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the CI meta checks: changelog, provenance schema, ADR numbering."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check_meta = _load("check_meta", REPO_ROOT / "scripts" / "check_meta.py")


class TestCheckChangelog:
    def test_ok_when_changelog_touched(self):
        assert check_meta.check_changelog(["scripts/fetch.py", "CHANGELOG.md"]) is None

    def test_ok_when_no_code_touched(self):
        assert check_meta.check_changelog(["docs/PRIMER.md", "README.md"]) is None

    def test_flags_code_without_changelog(self):
        msg = check_meta.check_changelog(["scripts/fetch.py"])
        assert msg is not None
        assert "CHANGELOG.md" in msg

    def test_snakefile_counts_as_code(self):
        assert check_meta.check_changelog(["Snakefile"]) is not None


class TestCheckProvenanceRecords:
    def test_missing_dir_is_fine(self, tmp_path):
        assert check_meta.check_provenance_records(tmp_path / "absent") == []

    def test_valid_record_from_fetch_passes(self, tmp_path):
        record = dict.fromkeys(check_meta.RECORD_KEYS, "x")
        prov = tmp_path / "ons"
        prov.mkdir()
        (prov / "carga.json").write_text(json.dumps(record))

        assert check_meta.check_provenance_records(tmp_path) == []

    def test_missing_key_is_reported(self, tmp_path):
        prov = tmp_path / "ons"
        prov.mkdir()
        (prov / "carga.json").write_text(json.dumps({"source": "ons"}))

        errors = check_meta.check_provenance_records(tmp_path)
        assert len(errors) == 1
        assert "missing keys" in errors[0]

    def test_invalid_json_is_reported(self, tmp_path):
        prov = tmp_path / "ons"
        prov.mkdir()
        (prov / "carga.json").write_text("{not json")

        errors = check_meta.check_provenance_records(tmp_path)
        assert "invalid JSON" in errors[0]


class TestCheckAdrNumbering:
    def test_unique_numbers_pass(self, tmp_path):
        (tmp_path / "ADR-0001-a.md").write_text("x")
        (tmp_path / "ADR-0002-b.md").write_text("x")

        assert check_meta.check_adr_numbering(tmp_path) == []

    def test_duplicate_number_is_reported(self, tmp_path):
        (tmp_path / "ADR-0001-a.md").write_text("x")
        (tmp_path / "ADR-0001-b.md").write_text("x")

        errors = check_meta.check_adr_numbering(tmp_path)
        assert len(errors) == 1
        assert "duplicate" in errors[0]

    def test_malformed_filename_is_reported(self, tmp_path):
        (tmp_path / "ADR-repository-conventions.md").write_text("x")

        errors = check_meta.check_adr_numbering(tmp_path)
        assert "does not match" in errors[0]
