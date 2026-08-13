# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Inspect a fetched tabular file and emit its data-dictionary YAML (see
`docs/data-dictionary/README.md`). Also derives a pandera schema from a
committed dictionary, so a later fetch of the "same" dataset can be validated
against it: upstream adding, dropping or retyping a column then fails loudly
in CI instead of silently changing what a downstream number means.

`unit` and `description` are always emitted as null: they cannot be inferred
from the data and are the one part of the dictionary a human fills in by
hand after inspection (see the data-dictionary README).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa
import yaml

SAMPLE_SIZE = 3


def inspect_csv(
    path: Path, *, delimiter: str = ",", encoding: str = "utf-8", decimal: str = "."
) -> pd.DataFrame:
    return pd.read_csv(path, delimiter=delimiter, encoding=encoding, decimal=decimal)


def _jsonable(value: Any) -> Any:
    """Make a sampled cell value safe for both JSON and YAML dumping."""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar (int64, float64, bool_, ...)
        return value.item()
    return value


def _column_entries(df: pd.DataFrame) -> list[dict[str, Any]]:
    entries = []
    for col in df.columns:
        series = df[col]
        entries.append(
            {
                "name": col,
                "dtype": str(series.dtype),
                "unit": None,
                "nullable": bool(series.isna().any()),
                "null_rate": round(float(series.isna().mean()), 4),
                "description": None,
                "sample": [_jsonable(v) for v in series.dropna().head(SAMPLE_SIZE)],
            }
        )
    return entries


def schema_hash(df: pd.DataFrame) -> str:
    """Hash of column names + dtypes. Changes exactly when upstream shape changes."""
    payload = json.dumps({c: str(t) for c, t in df.dtypes.items()}, sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_dictionary(
    df: pd.DataFrame,
    *,
    dataset: str,
    source: str,
    source_url: str,
    retrieved: str,
    format: str = "csv",
    encoding: str = "utf-8",
    delimiter: str = ",",
    decimal: str = ".",
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "source": source,
        "source_url": source_url,
        "retrieved": retrieved,
        "format": format,
        "encoding": encoding,
        "delimiter": delimiter,
        "decimal": decimal,
        "row_count": len(df),
        "schema_hash": schema_hash(df),
        "columns": _column_entries(df),
        "notes": [],
    }


def write_dictionary(dictionary: dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(dictionary, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return out_path


def load_dictionary(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def to_pandera_schema(dictionary: dict[str, Any]) -> pa.DataFrameSchema:
    """
    Build a pandera schema from a committed data dictionary.

    `strict=True`: a fetch that gains, loses or reorders columns relative to
    the dictionary is exactly the kind of silent drift this exists to catch,
    so it is treated as a failure rather than tolerated.
    """
    columns = {
        col["name"]: pa.Column(col["dtype"], nullable=col["nullable"])
        for col in dictionary["columns"]
    }
    return pa.DataFrameSchema(columns, strict=True)
