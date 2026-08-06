-- Cyber360 UC Metric View: Identity & Access Management.
-- This file is the source of truth for the metric-view definition and owns its
-- own lifecycle as a DAB asset. It is executed by the cyber360_data_plane job
-- via a sql_task; :catalog and :schema are supplied as task parameters so the
-- file carries no hardcoded location.
USE CATALOG IDENTIFIER(:catalog);
USE SCHEMA IDENTIFIER(:schema);

CREATE OR REPLACE VIEW mv_identity_access WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: 'Identity & Access posture measures over authentication events, account changes, and the account inventory snapshot.'
source: identity_access
dimensions:
  - name: day
    expr: CAST(time AS DATE)
  - name: org_unit
    expr: actor_user_org_unit
  - name: auth_protocol
    expr: auth_protocol
  - name: is_privileged
    expr: is_privileged
  - name: account_status
    expr: status
measures:
  - name: mfa_adoption
    expr: try_divide(SUM(IF(is_mfa, 1, 0)), COUNT(*)) * 100
  - name: privileged_accounts
    expr: COUNT_IF(is_privileged = true)
  - name: orphaned_accounts
    expr: COUNT_IF(owner_active = false AND status <> 'disabled')
  - name: sso_integration
    expr: try_divide(SUM(IF(via_sso, 1, 0)), COUNT(*)) * 100
  - name: pam_vault_coverage
    expr: try_divide(COUNT_IF(is_privileged AND in_pam_vault), COUNT_IF(is_privileged)) * 100
  - name: avg_provisioning
    expr: AVG(provisioning_hours) / 24
  - name: access_recertification
    expr: try_divide(COUNT_IF(last_recertified >= now() - INTERVAL 90 DAY), COUNT(*)) * 100
  - name: dormant_admin_accounts
    expr: COUNT_IF(is_privileged AND last_activity < now() - INTERVAL 90 DAY)
# Materialization accelerates the app's KPI reads (aggregate-aware query
# rewriting): the app queries this view natively with MEASURE(); the optimizer
# transparently serves precomputed results. The `day`-grained aggregated MV
# covers the 30/60/90-day window rollups the app filters on; the unaggregated
# baseline is the fallback for any query the aggregate can't satisfy. Refreshed
# by a managed Lakeflow pipeline. NOTE: keep this view free of per-user access
# controls / invoker-dependent exprs (current_user/is_member) -- materialization
# precomputes as the owner and is disabled for views that carry them.
materialization:
  schedule: every 6 hours
  mode: relaxed
  materialized_views:
    - name: by_day
      type: aggregated
      dimensions:
        - day
      measures:
        - mfa_adoption
        - privileged_accounts
        - orphaned_accounts
        - sso_integration
        - pam_vault_coverage
        - avg_provisioning
        - access_recertification
        - dormant_admin_accounts
      partition_by:
        - day
    - name: baseline
      type: unaggregated
$$;
