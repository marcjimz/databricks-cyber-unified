-- Cyber360: phishing metric-view SOURCE view.
-- A thin pass-through over the per-target source table, bound safely via
-- IDENTIFIER(:source_table) (accepts an unqualified or fully-qualified name):
--   * sandbox : :source_table = phishing_detail                    (synthetic gold)
--   * edp_dev : :source_table = conn_cyberarch.dbo.phishing_detail (real source)
-- The metric view (mv_phishing.sql) always reads this stable name, so the
-- per-target source swap is a pure task parameter -- no string-templating of the
-- metric-view body (which is fragile: any apostrophe breaks the quoting).
--
-- Kept in its OWN sql_task step (separate from mv_phishing.sql): the SQL-file
-- task executor mis-parses a file that mixes this CREATE with the metric view's
-- $$-dollar-quoted body, so each view is applied by its own single-CREATE file.
USE CATALOG IDENTIFIER(:catalog);
USE SCHEMA IDENTIFIER(:schema);

CREATE OR REPLACE VIEW phishing_source AS
SELECT * FROM IDENTIFIER(:source_table);
