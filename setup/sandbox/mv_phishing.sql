-- CyberUnified: EMULATED phishing metric view -- SANDBOX ONLY.
--
-- On a real target this view ALREADY EXISTS and is owned by the customer; the app
-- is given its NAME (domains[].metric_view.name) and only reads it. This file
-- exists so the sandbox can reproduce that view locally over synthetic gold, and
-- is applied by `make sandbox-metricview sandbox` (setup/sandbox/apply_metricview.py),
-- which refuses any non-sandbox target. It is NOT a bundle resource and NOT a
-- deploy step.
--
-- It is a DELIBERATE MIRROR of the live edp_dev definition (version 1.1, source
-- conn_cyberarch.dbo.phishing_detail) so the SAME app config resolves on both:
--   * SAME measure names: count / Click Rate / Avg Click Rate / Report Rate.
--     The app issues MEASURE(`<name>`), so these must match exactly.
--   * SAME 0-1 FRACTION rates (no *100). The app converts to percent via
--     `scale: 100` in cyber-unified.yaml, so the scaling lives in ONE place.
--   * SAME dimensions: Region + Campaign Name, plus the source.* EXCEPT wildcard.
--     NOTE there is intentionally NO `day` dimension -- the live view has none, and
--     inventing one here would let the sandbox pass while edp_dev failed with
--     UNRESOLVED_COLUMN. metric_view.time_dimension is therefore "" on both.
--
-- If the customer's view changes, update this file to match and keep
-- cyber-unified.yaml pointing at the real measure names.
--
-- FOOTGUN: keep this YAML body free of the semicolon character AND of a doubled
-- dollar sign. The statement splitter is dollar-quote aware, but a semicolon or a
-- stray doubled dollar inside a comment can still truncate the DDL.
USE CATALOG IDENTIFIER(:catalog);
USE SCHEMA IDENTIFIER(:schema);

CREATE OR REPLACE VIEW phishing_detail_metric_view WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: "Phishing and email-security posture measures over simulated-phishing campaign events (click, report, and no-action outcomes)."
source: phishing_source
dimensions:
  - expr: "source.* EXCEPT (Region, campaignname)"
  - name: Region
    expr: source.Region
    comment: Geographic region of the user who received the phishing email
    display_name: Region
  - name: Campaign Name
    expr: source.campaignname
    comment: Name of the phishing campaign
    display_name: Campaign Name
measures:
  - name: count
    expr: COUNT(*)
    comment: Represents the total number of rows in the dataset. Use this measure to count all
    display_name: Count
  - name: Click Rate
    expr: COUNT(CASE WHEN eventtype = 'Email Click' THEN 1 END) / NULLIF(COUNT(*), 0)
    comment: Percentage of phishing emails where the recipient clicked the link, calculated as clicks divided by total emails sent
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
  - name: Avg Click Rate
    expr: AVG(CASE WHEN eventtype = 'Email Click' THEN 1.0 ELSE 0.0 END)
    comment: Average click rate across all phishing email records, where each record is scored as 1 (clicked) or 0 (not clicked)
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
  - name: Report Rate
    expr: COUNT(CASE WHEN eventtype = 'Reported' THEN 1 END) / NULLIF(COUNT(*), 0)
    comment: Percentage of phishing emails that were reported by the recipient, calculated as reports divided by total emails sent
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
$$;
