"""Cyber360 Lakeflow Declarative Pipeline -- config-driven, no glue scripts.

The pipeline's sole job is the OCSF **gold layer**, driven by ``cyber360.yaml``:

  1. GOLD           Config-gated demo-data load. When
                    ``cyber360.load_synthetic_data`` is true, materialize the
                    OCSF gold table for every domain from the shared generator
                    (same PRNG seeds as the app's SeedProvider). When false,
                    the gold tables are the customer's own (bring-your-own-data)
                    and the pipeline reads them untouched.

  2. METRIC VIEWS   A UC Metric View per domain (the governed semantic layer the
                    app AND Genie query natively). ``CREATE ... VIEW WITH
                    METRICS`` is UC DDL that a declarative pipeline cannot run, so
                    each view is a declarative ``.sql`` asset under
                    ``resources/metricviews/`` (with a ``materialization:`` block
                    for query acceleration), applied by warehouse-executed
                    ``sql_task`` steps chained after this pipeline in the
                    ``cyber360_data_plane`` job.

KPI reads are served by querying those metric views natively on the SQL
Warehouse (``providers.metricview.MetricViewProvider``) with ``MEASURE()`` --
there is no longer a flattened-aggregate stage here or a Lakebase reverse-ETL.
The measure math lives ONCE, in the metric view. Adding a domain or measure is a
pure ``cyber360.yaml`` + ``mv_*.sql`` edit.
"""

from __future__ import annotations

import dlt
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from lib.config import load_pipeline_config
from lib.generator import default_now_ms, generate_gold

spark = SparkSession.getActiveSession()

# ---------------------------------------------------------------------------
# Boot: pipeline configuration (from databricks.yml `configuration:` block)
# ---------------------------------------------------------------------------

CATALOG = spark.conf.get("cyber360.catalog", "cyber360")
SCHEMA = spark.conf.get("cyber360.schema", "posture")
LOAD_SYNTHETIC = spark.conf.get("cyber360.load_synthetic_data", "true").lower() == "true"

CONFIG = load_pipeline_config(catalog=CATALOG, schema=SCHEMA)

# Anchor generated timestamps to the pipeline run time so the `now() - INTERVAL`
# windows in the measure expressions always resolve against fresh data.
_NOW_MS = default_now_ms()


# ---------------------------------------------------------------------------
# Explicit gold schemas (avoid inference on nullable timestamp/double columns)
# ---------------------------------------------------------------------------

_GOLD_SCHEMAS: dict[str, StructType] = {
    "identity_access": StructType([
        StructField("account_uid", StringType()),
        StructField("account_name", StringType()),
        StructField("time", TimestampType()),
        StructField("actor_user_org_unit", StringType()),
        StructField("auth_protocol", StringType()),
        StructField("is_privileged", BooleanType()),
        StructField("status", StringType()),
        StructField("is_mfa", BooleanType()),
        StructField("via_sso", BooleanType()),
        StructField("owner_active", BooleanType()),
        StructField("in_pam_vault", BooleanType()),
        StructField("provisioning_hours", DoubleType()),
        StructField("last_recertified", TimestampType()),
        StructField("last_activity", TimestampType()),
    ]),
    "vulnerability_management": StructType([
        StructField("finding_uid", StringType()),
        StructField("first_seen", TimestampType()),
        StructField("severity_id", IntegerType()),
        StructField("status_id", IntegerType()),
        StructField("cve_uid", StringType()),
        StructField("cvss_score", DoubleType()),
        StructField("cve_is_kev", BooleanType()),
        StructField("device_hostname", StringType()),
        StructField("device_type", StringType()),
        StructField("device_region", StringType()),
        StructField("resolved_time", TimestampType()),
        StructField("is_fix_available", BooleanType()),
        StructField("remediation_due", TimestampType()),
        StructField("has_exception", BooleanType()),
        StructField("last_scanned", TimestampType()),
    ]),
}


# ---------------------------------------------------------------------------
# Stage 1 -- GOLD (config-gated demo load)
# ---------------------------------------------------------------------------
#
# Defined as DLT tables ONLY when loading synthetic demo data. In
# bring-your-own-data mode the gold tables already exist in UC and the pipeline
# reads them directly (see `_read_gold`). We build the table definitions in a
# loop so a new domain in cyber360.yaml needs no new code here.

def _make_gold_table(gold_name: str):
    schema = _GOLD_SCHEMAS.get(gold_name)

    @dlt.table(
        name=gold_name,
        comment=f"OCSF gold table for '{gold_name}' (synthetic demo data).",
        table_properties={"delta.enableChangeDataFeed": "true"},
    )
    def _gold():
        rows = generate_gold(gold_name, now_ms=_NOW_MS)
        return spark.createDataFrame(rows, schema=schema)

    return _gold


if LOAD_SYNTHETIC:
    for _domain in CONFIG.domains:
        _name = CONFIG.gold_table_name(_domain)
        globals()[f"gold_{_name}"] = _make_gold_table(_name)


# ---------------------------------------------------------------------------
# Stage 2 -- METRIC VIEWS (governed semantic layer; the app + Genie query these)
# ---------------------------------------------------------------------------
#
# The UC Metric Views are NOT created here. ``CREATE ... VIEW WITH METRICS`` is
# a Unity Catalog DDL command that a Spark Declarative Pipeline cannot run: the
# runtime rejects it both inside an ``@dlt.table`` body
# ([UNSUPPORTED_COMMAND_IN_QUERY_DEFINITION]) and at module scope during graph
# analysis ([UNITY_CREDENTIAL_SCOPE_MISSING_SCOPE]). Per the Databricks docs,
# metric views are created from a SQL warehouse -- each domain's view is a
# declarative ``.sql`` asset under ``resources/metricviews/`` (carrying its own
# ``materialization:`` block), applied by the ``metric_view_*`` ``sql_task`` steps
# chained after this pipeline in the ``cyber360_data_plane`` job. The app reads
# those metric views directly, so this pipeline only needs to land the gold.
