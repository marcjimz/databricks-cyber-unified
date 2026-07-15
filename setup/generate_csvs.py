"""Standalone OCSF CSV emitter.

Writes the same config-driven synthetic gold rows the Lakeflow pipeline
generates in-cluster to ``data/<domain>/*.csv`` for reference, review, and
bring-your-own-data examples. Not used on the request path.

Usage:
    python pipelines/generate_csvs.py            # writes to ./data
    python pipelines/generate_csvs.py --out data # explicit output dir
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

# Make the pipeline support library importable regardless of CWD.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "pipelines"))

from lib.generator import (  # noqa: E402
    generate_identity_rows,
    generate_vulnerability_rows,
)

# domain subdir -> (gold table csv name, generator fn)
OUTPUTS = {
    "identity": ("identity_access.csv", generate_identity_rows),
    "vulnerability": ("vulnerability_management.csv", generate_vulnerability_rows),
}


def _fmt(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    return value


def _write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: _fmt(v) for k, v in r.items()})


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Cyber360 OCSF demo CSVs.")
    parser.add_argument(
        "--out",
        default=str(_REPO_ROOT / "data"),
        help="Output root directory (default: <repo>/data)",
    )
    args = parser.parse_args()

    out_root = Path(args.out)
    for subdir, (filename, gen) in OUTPUTS.items():
        rows = gen()
        dest = out_root / subdir / filename
        _write_csv(rows, dest)
        print(f"  wrote {len(rows):>5} rows -> {dest}")


if __name__ == "__main__":
    main()
