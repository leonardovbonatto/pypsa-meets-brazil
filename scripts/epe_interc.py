# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Read EPE's interchange limits (`interc.dat`, `minterc004.dat`) from a local
copy of the BaseDadosGT repository and cross-check them against the T0
transfer limits (ADR-0006, ADR-0012). Plan steps 2 and 3,
`Brazilian-Grid-in-PyPSA.md` §8.

**EPE data stays local.** The repository has no licence file, so raw files,
parsed tables and the cross-check are written under `resources/epe/`, which
git ignores. Only this code and a provenance record (repository URL, commit,
file hashes) are committed. Tests use synthetic text in the same layout.

**Format, read from the files, not documented upstream.** Both are
fixed-width text in PSR's SDDP layout: `!` starts a comment, the last comment
line before the data marks each field with a run of non-blank characters, and
fields are cut at those spans. `99999` means unconstrained in this file; the
binding limit then sits in another constraint set. EPE routes the North
through fictitious nodes (IMPERATRIZ, XINGU), so only the SE-NE boundary maps
one to one onto a T0 link.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

UNCONSTRAINED_MW = 99999.0

# T0 boundary -> (EPE row name, which EPE direction is bus0 -> bus1).
DIRECT_MATCHES = {"NE-SE_CO": ("SE -> NE", "TF")}


def _spans(header: str) -> list[tuple[int, int]]:
    """Column spans of the field markers in a `!` header line."""
    body = " " + header[1:]
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", body)]


def parse_fixed_width(text: str, names: list[str], *, n_text: int) -> pd.DataFrame:
    """Rows of a PSR fixed-width file. The first `n_text` fields, which may
    hold spaces, are cut at the field markers of the first header line with
    `len(names)` markers; the rest are numbers or single words, split on
    whitespace, because they are right-aligned and spill left past their
    markers (measured on the real files)."""
    lines = text.splitlines()
    header = next(
        (line for line in lines if line.startswith("!") and len(_spans(line)) == len(names)),
        None,
    )
    if header is None:
        raise ValueError(f"no header line with {len(names)} fields")
    starts = [a for a, _ in _spans(header)]
    rows = []
    for line in lines:
        if not line.strip() or line.startswith(("!", "$")):
            continue
        text_fields = [line[starts[i] : starts[i + 1]].strip() for i in range(n_text)]
        rest = line[starts[n_text] :].split()
        if len(rest) != len(names) - n_text:
            raise ValueError(f"expected {len(names) - n_text} trailing fields: {line!r}")
        rows.append(text_fields + rest)
    return pd.DataFrame(rows, columns=names)


INTERC_FIELDS = [
    "num", "name", "from", "to", "type", "currency",
    "capac_ft_mw", "loss_ft_pu", "capac_tf_mw", "loss_tf_pu",
]  # fmt: skip
MINTERC_FIELDS = ["date", "num", "name", "keyword", "block", "value"]


def parse_interc(text: str) -> pd.DataFrame:
    df = parse_fixed_width(text, INTERC_FIELDS, n_text=4)
    for column in ("capac_ft_mw", "loss_ft_pu", "capac_tf_mw", "loss_tf_pu"):
        df[column] = df[column].astype(float)
    df["num"] = df["num"].astype(int)
    return df


def parse_minterc(text: str) -> pd.DataFrame:
    df = parse_fixed_width(text, MINTERC_FIELDS, n_text=3)
    df["date"] = pd.to_datetime(df["date"], format="%d/%m/%Y")
    df["num"] = df["num"].astype(int)
    # `*` in the real file applies a value to every load block; kept as <NA>.
    df["block"] = pd.to_numeric(df["block"].replace("*", None)).astype("Int64")
    df["value"] = df["value"].astype(float)
    return df


def cross_check(interc: pd.DataFrame, links: pd.DataFrame) -> dict:
    """Per T0 boundary: our symmetric p_nom against EPE's limit in each
    direction where the boundary maps directly, else why it does not."""
    by_name = interc.set_index("name")
    report = {}
    for row in links.itertuples():
        boundary = f"{row.bus0}-{row.bus1}"
        if boundary not in DIRECT_MATCHES:
            report[boundary] = {
                "t0_p_nom_mw": float(row.p_nom_mw),
                "comparable": False,
                "reason": "EPE routes this boundary through fictitious nodes or "
                "leaves it unconstrained (99999) in interc.dat",
            }
            continue
        epe_name, forward = DIRECT_MATCHES[boundary]
        epe = by_name.loc[epe_name]
        backward = "FT" if forward == "TF" else "TF"
        report[boundary] = {
            "t0_p_nom_mw": float(row.p_nom_mw),
            "comparable": True,
            "epe_row": epe_name,
            "epe_bus0_to_bus1_mw": float(epe[f"capac_{forward.lower()}_mw"]),
            "epe_bus1_to_bus0_mw": float(epe[f"capac_{backward.lower()}_mw"]),
        }
    return report


def provenance(paths: list[Path], *, repository: str, commit: str) -> dict:
    return {
        "source": repository,
        "commit": commit,
        "licence": "none stated in the repository; data kept local (plan §8)",
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},
    }


def main() -> None:
    snake = globals()["snakemake"]
    raw = Path(snake.input.interc).read_text(encoding="latin-1")
    interc = parse_interc(raw)
    minterc = parse_minterc(Path(snake.input.minterc).read_text(encoding="latin-1"))
    report = cross_check(interc, pd.read_csv(snake.input.links))

    Path(snake.output.interc).parent.mkdir(parents=True, exist_ok=True)
    interc.to_csv(snake.output.interc, index=False)
    minterc.to_csv(snake.output.minterc, index=False)
    Path(snake.output.cross_check).write_text(json.dumps(report, indent=2) + "\n")
    record = provenance(
        [Path(snake.input.interc), Path(snake.input.minterc)],
        repository=snake.params.repository,
        commit=snake.params.commit,
    )
    Path(snake.output.provenance).parent.mkdir(parents=True, exist_ok=True)
    Path(snake.output.provenance).write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
