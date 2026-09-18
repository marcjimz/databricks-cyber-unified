#!/usr/bin/env python3
"""Publish the emulated phishing metric view on the SANDBOX. Utility, not a resource.

On a real target the UC metric view ALREADY EXISTS and is owned by the customer --
the app is told its name (``domains[].metric_view.name`` in cyber-unified.yaml) and
just reads it. This script only EMULATES that on the sandbox, over the synthetic
gold written by ``make seed sandbox``, so the same config resolves locally.

It is deliberately NOT a bundle resource and NOT a deploy step: it issues DDL
(``CREATE OR REPLACE VIEW`` / ``CREATE VIEW ... WITH METRICS``), which must never
run against a customer workspace. Invoke it via ``make sandbox-metricview sandbox``,
which refuses any other target.

Resolves the catalog/schema/warehouse from the bundle itself (``bundle summary``),
so nothing is hardcoded and it follows whatever the sandbox target declares.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# Applied in order. Each file is a SINGLE logical statement group; we split on ';'
# and drop comments, because the warehouse API executes one statement per call.
SQL_FILES = ["phishing_source.sql", "mv_phishing.sql"]


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if proc.returncode != 0:
        sys.exit(f"error: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout


def _bundle_vars(target: str, profile: str | None) -> dict[str, str]:
    """Read catalog/schema/warehouse_id/source table out of the bundle target."""
    cmd = ["databricks", "bundle", "summary", "-t", target, "-o", "json"]
    if profile:
        cmd += ["-p", profile]
    summary = json.loads(_run(cmd))
    variables = summary.get("variables", {})

    def var(name: str, default: str = "") -> str:
        entry = variables.get(name) or {}
        return str(entry.get("value", entry.get("default", default)) or default)

    resolved = {
        "catalog": var("catalog"),
        "schema": var("schema"),
        "warehouse_id": var("warehouse_id"),
        "source_table": var("phishing_source_table", "phishing_detail"),
    }
    missing = [k for k, v in resolved.items() if not v]
    if missing:
        sys.exit(f"error: bundle target {target!r} left these unresolved: {missing}")
    return resolved


def _statements(path: Path) -> list[str]:
    """Split a .sql file into executable statements.

    Strips line comments first, then splits on ';' -- but NOT inside a
    dollar-quoted ($$...$$) body, which the metric-view YAML uses. Getting this
    wrong is a known footgun in this repo: a naive split on ';' breaks the metric
    view's body apart.
    """
    text = "\n".join(
        line for line in path.read_text().splitlines() if not line.strip().startswith("--")
    )
    parts: list[str] = []
    buf: list[str] = []
    in_dollar = False
    for chunk in re.split(r"(\$\$|;)", text):
        if chunk == "$$":
            in_dollar = not in_dollar
            buf.append(chunk)
        elif chunk == ";" and not in_dollar:
            stmt = "".join(buf).strip()
            if stmt:
                parts.append(stmt)
            buf = []
        else:
            buf.append(chunk)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True)
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()

    if args.target != "databricks_sandbox":
        sys.exit(
            f"refusing to run against {args.target!r}: this is a SANDBOX-ONLY "
            "utility that issues DDL. Real targets already publish their own "
            "metric view."
        )

    cfg = _bundle_vars(args.target, args.profile)
    print(f"==> sandbox metric view in {cfg['catalog']}.{cfg['schema']} "
          f"over {cfg['source_table']} (warehouse {cfg['warehouse_id']})")

    for filename in SQL_FILES:
        path = HERE / filename
        for stmt in _statements(path):
            # Bind the same :named parameters the SQL files expect.
            sql = stmt
            for key, value in cfg.items():
                sql = sql.replace(f"IDENTIFIER(:{key})", f"`{value}`" if "." not in value
                                  else ".".join(f"`{p}`" for p in value.split(".")))
                sql = sql.replace(f":{key}", value)
            cmd = [
                "databricks", "api", "post", "/api/2.0/sql/statements",
                "--json", json.dumps({
                    "warehouse_id": cfg["warehouse_id"],
                    "statement": sql,
                    "wait_timeout": "50s",
                }),
            ]
            if args.profile:
                cmd += ["-p", args.profile]
            result = json.loads(_run(cmd))
            state = (result.get("status") or {}).get("state")
            if state != "SUCCEEDED":
                detail = (result.get("status") or {}).get("error", {})
                sys.exit(f"error applying {filename}: {state} {detail}")
            print(f"    ok: {sql.splitlines()[0][:70]}")

    print("==> sandbox metric view published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
