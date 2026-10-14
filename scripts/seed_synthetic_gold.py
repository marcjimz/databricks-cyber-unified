#!/usr/bin/env python3
"""Seed the synthetic OCSF gold tables into UC -- SANDBOX ONLY, and GATED.

This replaces the former Lakeflow declarative pipeline (`cyber_unified_pipeline`).
Synthetic gold is a DEVELOPMENT AID, not part of the application: real targets
(edp_dev/prod) read the customer's own tables, so nothing here should ever be
deployed or run against them. Mirrors the bluebird `seed_demo_data` idiom --
a gated `spark_python_task`, never a deploy step.

The job NEVER writes anything unless `--load_synthetic_data=true` resolves true;
otherwise it exits 0 as a no-op. Invoke via `make seed sandbox`, which is a
SEPARATE target from `make deploy`.

Schema-compatible with the real CyberArk `phishing_detail` federated table the
edp_dev target reads, so the sandbox mimics the customer's data shape (the whole
point of the sandbox). Rows come from the SAME generator the app's SeedProvider
uses, so measures agree across engines.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

# The generator + config live under pipelines/lib (kept as a helper library, no
# longer a deployed pipeline). Make them importable when this file is run as a
# standalone spark_python_task from the synced workspace tree.
#
# A serverless spark_python_task runs the file via exec() with no `__file__`, so
# the job passes the synced bundle root as --files_root. It is read straight off
# argv because the imports below need it before argparse runs; `__file__` is the
# fallback for running the script locally.
def _files_root() -> Path:
    for arg in sys.argv[1:]:
        if arg.startswith("--files_root="):
            return Path(arg.split("=", 1)[1])
    return Path(__file__).resolve().parent.parent


sys.path.insert(0, str(_files_root() / "pipelines"))

from lib.config import load_pipeline_config  # noqa: E402
from lib.generator import default_now_ms, generate_gold  # noqa: E402

# Explicit gold schemas -- avoid inference on nullable timestamp/double columns.
# Schema-compatible with the real CyberArk `phishing_detail`; timestamps are
# ISO-8601 strings (as the source emits) and the metric view casts
# eventtimestamp -> DATE for the `day` dimension.
_GOLD_SCHEMAS: dict[str, StructType] = {
    "phishing_detail": StructType([
        StructField("userfirstname", StringType()),
        StructField("userlastname", StringType()),
        StructField("useremailaddress", StringType()),
        StructField("useractiveflag", IntegerType()),
        StructField("userdeletedate", StringType()),
        StructField("senttimestamp", StringType()),
        StructField("eventtimestamp", StringType()),
        StructField("eventtype", StringType()),
        StructField("autoenrollment", IntegerType()),
        StructField("campaignstartdate", StringType()),
        StructField("campaigntype", StringType()),
        StructField("campaignstatus", StringType()),
        StructField("templatename", StringType()),
        StructField("templatesubject", StringType()),
        StructField("assessmentisarchived", StringType()),
        StructField("usertags", StringType()),
        StructField("sso_id", StringType()),
        StructField("campaignenddate", StringType()),
        StructField("Pass", BooleanType()),
        StructField("Pass_Rate", DoubleType()),
        StructField("Group", StringType()),
        StructField("Region", StringType()),
        StructField("campaignname", StringType()),
    ]),
}


def _truthy(value: str) -> bool:
    return str(value).strip().lower() == "true"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--load_synthetic_data", default="false")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--files_root", default=None)  # consumed by _files_root() above
    args = ap.parse_args()

    # The gate. Nothing is written unless this is explicitly true, so the job is
    # inert if it is ever deployed somewhere it should not run.
    if not _truthy(args.load_synthetic_data):
        print(
            "[seed] load_synthetic_data is not 'true' "
            f"(got {args.load_synthetic_data!r}) -- no-op, exiting."
        )
        return 0

    spark = SparkSession.builder.getOrCreate()
    config = load_pipeline_config(catalog=args.catalog, schema=args.schema)
    now_ms = default_now_ms()

    for domain in config.domains:
        name = config.gold_table_name(domain)
        target = config.fq(name)
        schema = _GOLD_SCHEMAS.get(name)
        if schema is None:
            print(f"[seed] WARN no explicit schema for '{name}' -- skipping.")
            continue

        rows = generate_gold(name, now_ms=now_ms)
        df = spark.createDataFrame(rows, schema=schema)
        # Overwrite so a re-seed re-anchors the event timestamps to now (the
        # measures use `now() - INTERVAL N DAY` windows).
        (
            df.write.mode("overwrite")
            .option("overwriteSchema", "true")
            .option("delta.enableChangeDataFeed", "true")
            .saveAsTable(target)
        )
        print(f"[seed] wrote {df.count():,} rows -> {target}")

    print("[seed] done.")
    return 0


if __name__ == "__main__":
    # Only raise on failure: under a serverless spark_python_task even
    # SystemExit(0) is reported as a failed run.
    rc = main()
    if rc:
        raise SystemExit(rc)
