# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for downloading, hashing and recording provenance (no real network)."""

from __future__ import annotations

import hashlib
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


fetch = _load("fetch", REPO_ROOT / "scripts" / "fetch.py")
write_manifest = _load("write_manifest", REPO_ROOT / "scripts" / "write_manifest.py")


class _FakeResponse:
    def __init__(self, content: bytes, *, status: int = 200):
        self._content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


CONTENT = b"a;b\n1;2\n3;4\n5;6\n"


class TestSha256File:
    def test_matches_hashlib(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_bytes(CONTENT)
        assert fetch.sha256_file(p) == hashlib.sha256(CONTENT).hexdigest()


class TestRowCount:
    def test_counts_data_rows_excluding_header(self, tmp_path):
        p = tmp_path / "f.csv"
        p.write_bytes(CONTENT)
        assert fetch.row_count(p, format="csv") == 3

    def test_none_for_non_line_delimited_formats(self, tmp_path):
        p = tmp_path / "f.xlsx"
        p.write_bytes(CONTENT)
        assert fetch.row_count(p, format="xlsx") is None


class TestDownload:
    def test_streams_to_dest_and_creates_parents(self, tmp_path, monkeypatch):
        dest = tmp_path / "nested" / "out.csv"
        monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: _FakeResponse(CONTENT))

        fetch.download("https://example.org/data.csv", dest)

        assert dest.read_bytes() == CONTENT

    def test_raises_on_http_error(self, tmp_path, monkeypatch):
        dest = tmp_path / "out.csv"
        monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: _FakeResponse(b"", status=404))

        with pytest.raises(RuntimeError):
            fetch.download("https://example.org/missing.csv", dest)


class TestBuildRecord:
    def test_all_required_keys_present(self, tmp_path):
        dest = tmp_path / "carga.csv"
        dest.write_bytes(CONTENT)

        record = fetch.build_record(
            source="ons", dataset="carga", source_url="https://x", dest=dest, format="csv"
        )

        assert set(record) == fetch.RECORD_KEYS
        assert record["sha256"] == hashlib.sha256(CONTENT).hexdigest()
        assert record["byte_size"] == len(CONTENT)
        assert record["row_count"] == 3


class TestWriteRecord:
    def test_writes_under_source_dataset_path(self, tmp_path):
        record = {"source": "ons", "dataset": "carga", "sha256": "abc"}
        out = fetch.write_record(record, provenance_dir=tmp_path)

        assert out == tmp_path / "ons" / "carga.json"
        assert json.loads(out.read_text()) == record


class TestFetchIntegration:
    def test_fetch_then_write_manifest_reads_it_back(self, tmp_path, monkeypatch):
        """
        Proves the wiring the PR-02 handoff promised: a record `fetch()` writes
        is exactly what `write_manifest.collect_provenance()` picks up.
        """
        dest = tmp_path / "raw" / "carga.csv"
        monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: _FakeResponse(CONTENT))
        monkeypatch.setattr(fetch, "PROVENANCE_DIR", tmp_path / "prov")
        monkeypatch.setattr(write_manifest, "PROVENANCE_DIR", tmp_path / "prov")

        fetch.fetch(source="ons", dataset="carga", url="https://x", dest=dest, format="csv")

        records = write_manifest.collect_provenance()
        assert records["ons/carga.json"]["row_count"] == 3
