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
    expr: SUM(IF(is_mfa, 1, 0)) / COUNT(*) * 100
  - name: privileged_accounts
    expr: COUNT_IF(is_privileged = true)
  - name: orphaned_accounts
    expr: COUNT_IF(owner_active = false AND status <> 'disabled')
  - name: sso_integration
    expr: SUM(IF(via_sso, 1, 0)) / COUNT(*) * 100
  - name: pam_vault_coverage
    expr: COUNT_IF(is_privileged AND in_pam_vault) / COUNT_IF(is_privileged) * 100
  - name: avg_provisioning
    expr: AVG(provisioning_hours) / 24
  - name: access_recertification
    expr: COUNT_IF(last_recertified >= now() - INTERVAL 90 DAY) / COUNT(*) * 100
  - name: dormant_admin_accounts
    expr: COUNT_IF(is_privileged AND last_activity < now() - INTERVAL 90 DAY)
$$;
