"""Post-deploy Lakebase grant: register the Databricks reader GROUP as a
Postgres group role and grant it read on the synced-aggregate schema.

WHY THIS EXISTS
---------------
The dashboard app reads the synced KPI aggregates over a *direct* psycopg
Postgres connection. Databricks does NOT auto-propagate Unity Catalog grants
(or the app's ``uc_securable`` binding) to Postgres role privileges, so a
Postgres-layer GRANT is required for that read path. Rather than granting each
app service principal individually, we centralize the read on a Databricks
GROUP: the group is registered as a Postgres group role via the
``databricks_auth`` extension and granted USAGE + SELECT on the synced schema.
Every group member -- including the app SP -- then inherits the read by
connecting AS the group role (PGUSER = group name, own OAuth token).

PREREQUISITE (bring-your-own): the Databricks group named by ``--group`` must
already exist and the app SP must be a member. This task owns only the
Postgres side (create the group role + grant read); it does NOT create the
Databricks group or manage its membership.

RUN-AS IDENTITY: this runs as the job's run-as identity, which must own (or
hold GRANT on) the synced schema -- i.e. the deploying identity. It mints its
OWN Lakebase credential via the SDK and connects as itself, then issues the
grants to the group role.

Idempotent: every statement is safe to re-run. ``databricks_create_role`` is a
no-op if the role exists; the GRANTs are additive; ALTER DEFAULT PRIVILEGES
covers future tables landed by re-syncs.
"""

from __future__ import annotations

import argparse

import psycopg
from databricks.sdk import WorkspaceClient


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", required=True,
                   help="Lakebase endpoint path projects/<p>/branches/<b>/endpoints/<e>")
    p.add_argument("--database", required=True, help="Logical Postgres database name")
    p.add_argument("--schema", required=True,
                   help="Synced-aggregate schema to grant read on (e.g. dev_<user>_posture)")
    p.add_argument("--group", required=True,
                   help="Databricks group display name (case-sensitive) to register as a "
                        "Postgres group role")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    ws = WorkspaceClient()
    host = ws.postgres.get_endpoint(name=args.endpoint).status.hosts.host
    token = ws.postgres.generate_database_credential(endpoint=args.endpoint).token
    me = ws.current_user.me().user_name

    dsn = (
        f"host={host} port=5432 dbname={args.database} "
        f"user={me} password={token} sslmode=require"
    )

    # Identifiers are interpolated with double-quoting; they come from trusted
    # bundle variables (schema name, group name), not user input.
    schema = args.schema
    group = args.group
    stmts = [
        "CREATE EXTENSION IF NOT EXISTS databricks_auth",
        f"SELECT databricks_create_role('{group}', 'GROUP')",
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{group}"',
        f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{group}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT ON TABLES TO "{group}"',
    ]

    failures = 0
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        for s in stmts:
            try:
                cur.execute(s)
                try:
                    row = cur.fetchone()
                except psycopg.ProgrammingError:
                    row = None
                print("OK  ", s, ("-> " + str(row)) if row else "")
            except psycopg.errors.DuplicateObject:
                # databricks_create_role on an existing role -> already registered.
                print("SKIP", s, "-> role already exists")
            except Exception as exc:  # noqa: BLE001 - surface, don't abort the batch
                failures += 1
                print("FAIL", s, "->", type(exc).__name__, exc)

        # Verify the end state so the task fails loudly if the grant did not take.
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (group,))
        role_exists = cur.fetchone() is not None
        cur.execute("SELECT has_schema_privilege(%s, %s, 'USAGE')", (group, schema))
        usage_ok = cur.fetchone()[0]
        print(f"\ngroup role exists: {role_exists}")
        print(f"group USAGE on {schema}: {usage_ok}")

    # Do NOT call sys.exit(): the serverless spark_python_task runner execs this
    # file inside a kernel and treats ANY SystemExit (even 0) as a task failure.
    # Signal failure by raising; return normally on success.
    if failures or not role_exists or not usage_ok:
        raise RuntimeError(
            f"Grant task incomplete (failures={failures}, "
            f"role_exists={role_exists}, usage_ok={usage_ok})"
        )
    print("\nReader group role provisioned and granted read successfully.")


if __name__ == "__main__":
    main()
