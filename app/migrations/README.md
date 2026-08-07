# App-owned database migrations

Versioned, forward-only SQL migrations for the app-owned **state** schema in
Lakebase (`preferences`, `chats`, `sessions`, and anything you add later).

> **Scope.** These migrations manage ONLY the schema the app *owns* and writes
> to (its state tables). KPI data is not in Lakebase at all — it's served by
> querying the UC metric views natively on the SQL Warehouse.

## How it works

- Each change is a numbered SQL file in [`versions/`](./versions):
  `NNNN__short_description.sql` (e.g. `0001__initial_state_tables.sql`).
- On app startup, `core.migrations.run_migrations()` connects to Lakebase, reads
  a `schema_migrations` tracking table, and applies every file whose version has
  not yet run — **in order, once, forward-only.**
- Files are immutable once merged. To change schema, **add a new file** — never
  edit an applied one. This is the same rule the
  [lakebase-app-dev-kit](https://github.com/databricks-solutions/lakebase-app-dev-kit)
  enforces.

## Add a migration

1. Create the next file: `versions/0002__add_widget_prefs.sql`.
2. Write plain SQL (multiple statements allowed; separate with `;`). Prefer
   idempotent DDL (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`).
3. Commit it. It applies automatically on the next deploy's app startup, and in
   CI's migration check.

## Why file-based (and how to graduate)

This runner is intentionally tiny — no extra runtime dependency, works headless
in GitHub Actions and from a coding agent. When the team wants paired
git-branch ↔ Lakebase-branch workflows, schema diffing, and rollback, graduate to
the **lakebase-app-dev-kit** (Alembic/Flyway runners + MCP tools); the
`versions/` layout here is compatible with that move.
