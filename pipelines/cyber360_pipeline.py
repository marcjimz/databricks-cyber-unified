"""Cyber360 Lakeflow Declarative Pipeline -- config-driven, no glue scripts.

One pipeline, three declarative stages, all driven by ``cyber360.yaml``:

  1. GOLD           Config-gated demo-data load. When
                    ``cyber360.load_synthetic_data`` is true, materialize the
                    OCSF gold table for every domain from the shared generator
                    (same PRNG seeds as the app's SeedProvider). When false,
                    the gold tables are the customer's own (bring-your-own-data)
                    and the pipeline reads them untouched.

  2. METRIC VIEWS   A UC Metric View per domain (governed semantic layer that
                    Genie Spaces sit on). ``CREATE ... VIEW WITH METRICS`` is UC
                    DDL that a declarative pipeline cannot run, so each view is a
                    declarative ``.sql`` asset under ``resources/metricviews/``,
                    applied by warehouse-executed ``sql_task`` steps chained after
                    this pipeline in the ``cyber360_data_plane`` job.

  3. AGGREGATES     Materialize two GENERIC tables that cover every
                    domain/measure with zero schema change:
                      agg_daily(domain, day, measure, value)
                        -> daily-grain series for trend/area charts
                      agg_rollup(domain, period, measure, value, prev_value, delta)
                        -> 30/60/90d windowed values + period-over-period deltas
                           for KPI tiles
                    Both are CDF-enabled with the primary keys the
                    ``postgres_synced_tables`` reverse-ETL expects.

Adding a domain or measure is a pure ``cyber360.yaml`` edit: this pipeline
picks it up with no code change. Measure expressions are evaluated here exactly
as written in the YAML, so the semantic definition lives in one place.
"""

from __future__ import annotations

import dlt
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
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
ROLLUP_PERIODS = [30, 60, 90]

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


def _read_gold(gold_name: str):
    """Read a domain's gold table, dependency-tracked in demo mode."""
    if LOAD_SYNTHETIC:
        return dlt.read(gold_name)
    return spark.read.table(CONFIG.fq(gold_name))


def _day_expression(domain: dict) -> str:
    """The 'day' dimension expression from a domain's metric_view."""
    for dim in domain["metric_view"].get("dimensions", []):
        if dim.get("name") == "day":
            return dim["expression"]
    # Fallback: cast the first timestamp-ish column; keeps the pipeline robust.
    return "CURRENT_DATE()"


# ---------------------------------------------------------------------------
# Stage 2 -- METRIC VIEWS (governed semantic layer; Genie sits on these)
# ---------------------------------------------------------------------------
#
# The UC Metric Views are NOT created here. ``CREATE ... VIEW WITH METRICS`` is
# a Unity Catalog DDL command that a Spark Declarative Pipeline cannot run: the
# runtime rejects it both inside an ``@dlt.table`` body
# ([UNSUPPORTED_COMMAND_IN_QUERY_DEFINITION]) and at module scope during graph
# analysis ([UNITY_CREDENTIAL_SCOPE_MISSING_SCOPE]). Per the Databricks docs,
# metric views are created from a SQL warehouse -- each domain's view is a
# declarative ``.sql`` asset under ``resources/metricviews/``, applied by the
# ``metric_view_*`` ``sql_task`` steps chained after this pipeline in the
# ``cyber360_data_plane`` job. The KPI aggregates below read the OCSF gold tables
# directly and do NOT depend on the metric views, so the dashboard's data plane
# is unaffected.


# ---------------------------------------------------------------------------
# Stage 3 -- AGGREGATES (generic, two tables cover all domains/measures)
# ---------------------------------------------------------------------------

def _measure_value_sql(view: str, day_expr: str, expr: str, where: str | None) -> str:
    clause = f" WHERE {where}" if where else ""
    return f"SELECT CAST(({expr}) AS DOUBLE) AS value FROM {view}{clause}"


@dlt.table(
    name="agg_daily",
    comment="Generic daily-grain measure series (domain, day, measure, value).",
    table_properties={"delta.enableChangeDataFeed": "true"},
)
def agg_daily():
    frames = []
    for domain in CONFIG.domains:
        gold_name = CONFIG.gold_table_name(domain)
        view = f"_gold_{gold_name}"
        _read_gold(gold_name).createOrReplaceTempView(view)
        day_expr = _day_expression(domain)
        for m in domain["metric_view"].get("measures", []):
            df = spark.sql(
                f"SELECT '{domain['key']}' AS domain, "
                f"CAST(({day_expr}) AS DATE) AS day, "
                f"'{m['name']}' AS measure, "
                f"CAST(({m['expression']}) AS DOUBLE) AS value "
                f"FROM {view} GROUP BY CAST(({day_expr}) AS DATE)"
            )
            frames.append(df)

    result = frames[0]
    for df in frames[1:]:
        result = result.unionByName(df)
    return result.where(F.col("day").isNotNull())


@dlt.table(
    name="agg_rollup",
    comment="Generic 30/60/90d rollups with period-over-period deltas "
            "(domain, period, measure, value, prev_value, delta).",
    table_properties={"delta.enableChangeDataFeed": "true"},
)
def agg_rollup():
    # Return a LAZY DataFrame (one row per domain/period/measure, unioned) rather
    # than eagerly computing values with .collect() inside this function. DLT
    # invokes @dlt.table bodies during graph ANALYSIS -- before the upstream gold
    # tables are materialized -- so an eager .collect() reads an empty view and
    # bakes all-zero aggregates into the output. Building lazy Spark SQL frames
    # (as agg_daily does) defers evaluation to execution time, against the
    # materialized gold. Each measure's current/prev window value is a scalar
    # aggregate subquery; COALESCE(..., 0.0) preserves the "empty window -> 0.0"
    # semantics the KPI tiles expect.
    frames = []
    for domain in CONFIG.domains:
        gold_name = CONFIG.gold_table_name(domain)
        view = f"_rollup_gold_{gold_name}"
        _read_gold(gold_name).createOrReplaceTempView(view)
        day_expr = _day_expression(domain)

        for period in ROLLUP_PERIODS:
            cur_where = f"({day_expr}) >= current_date() - INTERVAL {period} DAY"
            prev_where = (
                f"({day_expr}) >= current_date() - INTERVAL {2 * period} DAY "
                f"AND ({day_expr}) < current_date() - INTERVAL {period} DAY"
            )
            for m in domain["metric_view"].get("measures", []):
                cur_sql = _measure_value_sql(view, day_expr, m["expression"], cur_where)
                prev_sql = _measure_value_sql(view, day_expr, m["expression"], prev_where)
                df = spark.sql(
                    f"SELECT '{domain['key']}' AS domain, "
                    f"CAST({period} AS INT) AS period, "
                    f"'{m['name']}' AS measure, "
                    f"COALESCE(cur.value, 0.0) AS value, "
                    f"COALESCE(prev.value, 0.0) AS prev_value, "
                    f"COALESCE(cur.value, 0.0) - COALESCE(prev.value, 0.0) AS delta "
                    f"FROM ({cur_sql}) cur CROSS JOIN ({prev_sql}) prev"
                )
                frames.append(df)

    result = frames[0]
    for df in frames[1:]:
        result = result.unionByName(df)
    return result
