"""Create/refresh the Cyber360 UC Metric Views -- config-driven, warehouse-executed.

WHY THIS IS A SEPARATE STEP (not part of the Lakeflow pipeline):
``CREATE ... VIEW WITH METRICS`` is a Unity Catalog DDL command. It cannot run
inside a Spark Declarative Pipeline: the runtime rejects it both inside an
``@dlt.table`` body ([UNSUPPORTED_COMMAND_IN_QUERY_DEFINITION]) and at module
scope during graph analysis ([UNITY_CREDENTIAL_SCOPE_MISSING_SCOPE], because the
analysis phase has no Unity credential scope for the catalog's storage). Per the
Databricks docs, metric views are created from a SQL warehouse. This step runs
AFTER the pipeline materializes the OCSF gold tables and issues each domain's
metric-view DDL against the SQL warehouse via the Statement Execution API.

Config-driven: the metric-view definitions (dimensions + measures) come straight
from ``cyber360.yaml``, so adding a domain or measure is a pure YAML edit -- this
script needs no change. The semantic definition lives in one place.

Runs in two contexts with no code change (WorkspaceClient auto-configures):
  * Locally:  DATABRICKS_HOST=<workspace> python pipelines/create_metric_views.py \
                --catalog <cat> --schema <schema> --warehouse-id <id>
  * As a Databricks Job notebook/python task (params: catalog, schema,
    warehouse_id) chained after the pipeline task.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import load_pipeline_config  # noqa: E402


def metric_view_yaml(cfg, domain: dict) -> str:
    """Render a domain's metric_view block as UC Metric View YAML (spec v1.1)."""
    mv = domain["metric_view"]
    source = cfg.fq(cfg.gold_table_name(domain))
    lines = ["version: 1.1"]
    if mv.get("comment"):
        # Single-line comment; collapse any embedded newlines from the YAML block.
        comment = " ".join(str(mv["comment"]).split())
        lines.append(f"comment: '{comment}'")
    lines += [f"source: {source}", "dimensions:"]
    for dim in mv.get("dimensions", []):
        lines.append(f"  - name: {dim['name']}")
        lines.append(f"    expr: {dim['expression']}")
    lines.append("measures:")
    for m in mv.get("measures", []):
        lines.append(f"  - name: {m['name']}")
        lines.append(f"    expr: {m['expression']}")
    return "\n".join(lines)


def create_statement(cfg, domain: dict) -> tuple[str, str]:
    """(fully-qualified view name, CREATE ... WITH METRICS statement)."""
    name = cfg.fq(domain["metric_view"]["name"])
    body = metric_view_yaml(cfg, domain)
    stmt = f"CREATE OR REPLACE VIEW {name} WITH METRICS LANGUAGE YAML AS $$\n{body}\n$$"
    return name, stmt


def main() -> int:
    ap = argparse.ArgumentParser(description="Create Cyber360 UC Metric Views.")
    ap.add_argument("--catalog", default=os.environ.get("CYBER360_CATALOG"))
    ap.add_argument("--schema", default=os.environ.get("CYBER360_SCHEMA"))
    ap.add_argument("--warehouse-id", default=os.environ.get("CYBER360_WAREHOUSE_ID"))
    args = ap.parse_args()

    if not (args.catalog and args.schema and args.warehouse_id):
        ap.error("catalog, schema and warehouse-id are all required "
                 "(flags or CYBER360_CATALOG/SCHEMA/WAREHOUSE_ID env).")

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    cfg = load_pipeline_config(catalog=args.catalog, schema=args.schema)
    w = WorkspaceClient()

    failures = 0
    for domain in cfg.domains:
        name, stmt = create_statement(cfg, domain)
        resp = w.statement_execution.execute_statement(
            warehouse_id=args.warehouse_id, statement=stmt, wait_timeout="50s"
        )
        state = resp.status.state if resp.status else None
        if state == StatementState.SUCCEEDED:
            print(f"OK   {name}")
        else:
            failures += 1
            err = resp.status.error.message if (resp.status and resp.status.error) else state
            print(f"FAIL {name}: {err}")

    if failures:
        print(f"{failures} metric view(s) failed.")
        return 1
    print(f"Created/refreshed {len(cfg.domains)} metric view(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
