-- CyberUnified UC Metric View: Phishing & Email Security.
-- This file is the source of truth for the metric-view definition and owns its
-- own lifecycle as a DAB asset. It is executed by the cyber_unified_data_plane job
-- via a sql_task; :catalog, :schema and :source_table are supplied as task
-- parameters so the file carries no hardcoded location.
--
-- The metric view LIVES in :catalog.:schema (USE ... below) and reads the stable
-- `phishing_source` view (created by phishing_source.sql, a separate sql_task
-- step run first). That indirection lets the per-target source swap be a pure
-- task parameter (:source_table) without string-templating this fragile
-- $$-dollar-quoted body. Keep this file to a SINGLE CREATE (plus the two USE
-- statements): the SQL-file task executor mis-parses a file that also creates the
-- source view alongside the metric-view body.
--
-- NOTES vs. the raw CyberArk schema:
--   * A `day` dimension (CAST(eventtimestamp AS DATE)) is added -- the app
--     windows KPI reads on `day >= current_date() - INTERVAL N DAY` and builds
--     the trend series with GROUP BY `day`, so every metric view needs it.
--   * The rate measures are scaled *100: the app renders `format: percent` as a
--     0-100 value, whereas the raw rate expressions are 0-1 fractions.
--   * Measure exprs are written in PORTABLE SQL (CASE WHEN / NULLIF / standard
--     division -- no try_divide/COUNT_IF) so the IDENTICAL string in cyber-unified.yaml
--     evaluates the same in Spark (here) and in DuckDB (the local seed provider).
--   * Region / Campaign Name are surfaced as named dimensions; every other source
--     column comes through the `source.* EXCEPT (...)` wildcard.
USE CATALOG IDENTIFIER(:catalog);
USE SCHEMA IDENTIFIER(:schema);

CREATE OR REPLACE VIEW phishing_detail_metric_view WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: "Phishing and email-security posture measures over simulated-phishing campaign events (click, report, and no-action outcomes)."
source: phishing_source
dimensions:
  - expr: "source.* EXCEPT (Region, campaignname, eventtimestamp)"
  - name: day
    expr: CAST(eventtimestamp AS DATE)
    comment: Event date dimension (drives the 30/60/90-day windows and trend)
    display_name: Day
  - name: Region
    expr: source.Region
    comment: Geographic region of the recipient
    display_name: Region
  - name: Campaign Name
    expr: source.campaignname
    comment: Name of the phishing campaign
    display_name: Campaign Name
measures:
  - name: count
    expr: COUNT(*)
    comment: Total number of phishing-campaign event rows in the dataset.
    display_name: Count
  - name: phishing_click_rate
    expr: COUNT(CASE WHEN eventtype = 'Email Click' THEN 1 END) / NULLIF(COUNT(*), 0) * 100
    comment: Percentage of phishing emails where the recipient clicked the link (clicks / total).
    display_name: Phishing Click Rate
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 2
    synonyms:
      - email click rate
      - phishing email click percentage
      - click-through rate
      - CTR
  - name: avg_click_rate
    expr: AVG(CASE WHEN eventtype = 'Email Click' THEN 1.0 ELSE 0.0 END) * 100
    comment: Average click rate across all phishing records (each scored 1 clicked / 0 not).
    display_name: Average Click Rate
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 2
    synonyms:
      - click rate
      - email click rate
      - CTR
      - click-through rate
  - name: phishing_report_rate
    expr: COUNT(CASE WHEN eventtype = 'Reported' THEN 1 END) / NULLIF(COUNT(*), 0) * 100
    comment: Percentage of phishing emails that were reported by the recipient (reports / total).
    display_name: Phishing Report Rate
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 2
    synonyms:
      - reporting rate
      - reported percentage
      - phishing report percentage
      - email report rate
# Materialization accelerates the KPI reads (aggregate-aware query rewriting).
# The app queries this view natively with MEASURE() and the optimizer serves
# precomputed results. The day-grained aggregated MV covers the 30/60/90-day
# window rollups the app filters on, and the unaggregated baseline is the
# fallback for any query the aggregate cannot satisfy. Keep this view free of
# per-user access controls / invoker-dependent exprs (current_user/is_member) --
# materialization precomputes as the owner and is disabled for views that carry
# them. Per-user governance is enforced by OBO at query time instead.
# NOTE: keep this YAML body free of the semicolon character AND of a doubled
# dollar sign -- the sql_task file runner splits statements on the semicolon
# (ignoring dollar-quoting) and the doubled dollar closes this quoted body early,
# so either one inside a comment truncates the DDL and fails the parse.
materialization:
  schedule: every 6 hours
  mode: relaxed
  materialized_views:
    - name: by_day
      type: aggregated
      dimensions:
        - day
      measures:
        - count
        - phishing_click_rate
        - avg_click_rate
        - phishing_report_rate
      partition_by:
        - day
    - name: baseline
      type: unaggregated
$$;
