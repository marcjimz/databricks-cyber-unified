# AGENTS.md — CyberUnified Unified Dashboard (Databricks Asset Bundle)

Operating guide for agentic coding tools (Claude Code, Genie Code, and similar).
This file is named `AGENTS.md` so agentic tools auto-discover it. Read it before
changing anything. It describes the repo layout, the command workflow, and — most
importantly — **the configuration model**, so an agent never "fixes" something by
hardcoding a domain and breaking the config-driven architecture.

## Working principles (read first)

Two defaults govern every change in this repo:

- **Config-driven by default.** This dashboard's entire reason to exist is that a
  metric view + `cyber-unified.yaml` config fully define what the UI shows — KPIs,
  scorecard tiles, domain health, trends, AND the drill-down table. Adding a
  security domain, a measure, or a detail column MUST be a pure config/SQL edit
  (`cyber-unified.yaml` + `resources/metricviews/mv_<domain>.sql`), with **zero** app
  code changes. When in doubt, choose the option that pushes behavior into config,
  not into a `if domain == "phishing"` branch. If you find yourself typing a domain
  name, a measure name, or a column list into `.py`/`.tsx`, stop — that belongs in
  `cyber-unified.yaml`. A hardcoded domain is a defect, not a feature.
- **OBO by default (least privilege).** The data plane is on-behalf-of the
  logged-in user, end to end. KPI + drill-down reads run on the SQL Warehouse with
  the user's forwarded token (`X-Forwarded-Access-Token`), so Unity Catalog
  permissions are enforced per user. The app service principal exists ONLY to
  provision resources and own the app's read-write STATE (preferences/chats/
  sessions in Lakebase). Never add an SP data path for KPI/drill-down reads; never
  widen `user_api_scopes` without a code path that needs it. A permission error is
  not fixed by escalating privilege — that is a defect.

## What this is

A config-driven cybersecurity posture dashboard. It ships as a Databricks Asset
Bundle (DAB) that provisions: a UC schema + volume, a Lakeflow pipeline that lands
an OCSF-style **gold table**, a **UC Metric View** (`WITH METRICS`, materialized)
that is the single semantic source of the measure math, a Databricks App (FastAPI
+ built React SPA), and an autoscaling **Lakebase** Postgres project that serves
ONLY the app's read-write state. KPIs are read by querying the metric view
natively with `MEASURE()` on the SQL Warehouse (per-user OBO) — there is no
reverse-ETL and no flattened aggregate stage.

The pivot in progress: the dashboard now starts with **ONE** domain — **phishing
& email security** — driven by a single metric view. Identity & vulnerability were
staging-only demo domains and have been removed (git history preserves them).

## Repo layout

```
databricks.yml            Bundle root (name: cyber-unified): variables, targets, resources, group permissions
  targets: databricks_sandbox (default, FEVM, SYNTHETIC) | edp_dev (Azure EDP DEV, REAL CyberArk source) | prod
resources/
  metricviews/
    mv_phishing.sql        UC Metric View (CREATE VIEW WITH METRICS LANGUAGE YAML) + materialization. :catalog/:schema
                           are where the view LIVES; :source_table is what it READS (swaps per target — pure config).
pipelines/
  cyber_unified_pipeline.py     Lakeflow pipeline: config-gated synthetic gold-table load (_GOLD_SCHEMAS). No metric-view DDL
                           here (a declarative pipeline cannot run CREATE VIEW WITH METRICS — that's the data-plane job).
  lib/generator.py         Deterministic synthetic gold rows (phishing_detail). The ONE source of synthetic data, shared
                           by the pipeline's demo-load AND the app's seed provider.
  lib/config.py            Dependency-free cyber-unified.yaml reader for the pipeline (no app import).
setup/generate_csvs.py     Standalone CSV emitter (make generate-data) — reference/inspection only.
app/
  cyber-unified.yaml            THE config (SSOT): org, data_source, domains (metric_view measures + dimensions + detail_table),
                           top_line_kpis, features. Customers edit THIS to point at their data — no code changes.
  main.py                  FastAPI entry: loads config, resolves ${ENV} from app env, inits Lakebase state pool + migrations.
  core/config.py           Pydantic models for cyber-unified.yaml + RAG/format/period helpers (shared math).
  core/sql.py              SQL Warehouse client (Statement Execution API), per-request OBO token.
  providers/
    metricview.py          PROD provider: queries the UC metric view with MEASURE() on the warehouse (OBO). GENERIC —
                           no domain names. Also serves the generic detail table (SELECT from source_table).
    seed.py                LOCAL provider (make dev, zero workspace deps): computes ANY domain's measures + detail rows
                           from generator.py rows via DuckDB, using the SAME measure SQL from config. GENERIC.
    __init__.py            Provider factory (provider: "metricview" | "seed").
  api/                     FastAPI routers: config, health, metrics (scorecard + /metrics/{domain}), tables
                           (/{domain}/rows — generic), incidents (gated by soc_view_enabled).
  models/                  Pydantic response models (common, domain, detail, scorecard, incidents).
  frontend/                Vite + React SPA (config-driven; /domain/:key is one generic route). dist/ is COMMITTED.
  migrations/              Lakebase app-state migrations (preferences/chats/sessions) — app-owned RW state only.
README.md / SKILL.md       Deployment guide + design principles. MEMORY.md — dev log (gitignored).
```

## Command workflow

Prereqs: Databricks CLI (autoscaling Lakebase support); authenticated to the
target workspace (`databricks auth login --host <url>`). Targets:
`databricks_sandbox` (default, FEVM, synthetic), `edp_dev` (Azure EDP DEV, real
CyberArk source), `prod`.

The Makefile follows the bluebird idiom: the env is a POSITIONAL word (`make
deploy sandbox`), mapped to the databricks.yml target (`sandbox` ->
`databricks_sandbox`; `edp_dev`, `prod` as-is).

```bash
# Local dev (zero workspace deps — seed provider computes KPIs from generator.py):
make install            # installs .[dev] incl. duckdb (seed engine) + frontend deps
make dev                # build SPA + uvicorn on :8000 (CYBERUNIFIED_PROVIDER=seed)

# Full deploy sequence in ONE target (validate -> deploy -> data-plane job -> app):
make deploy sandbox     # FEVM, synthetic phishing data
make deploy edp_dev     # Azure EDP DEV, REAL CyberArk source (no synthetic load)
make setup sandbox      # FIRST-TIME on a fresh workspace: deploy x2 -> data-plane -> app

# Individual steps (same positional env):
make validate sandbox   # bundle validate only
make data-plane sandbox # run cyber_unified_data_plane (pipeline gold + phishing metric view)
make app sandbox        # deploy + (re)start the app
```

### Deploy gotchas

- **Two-phase on a fresh workspace.** The first `bundle deploy` may partially fail
  (Lakebase provisions the project asynchronously; synced/derived objects race
  ahead). Re-run `deploy`, then run the data-plane job, then start the app.
- **Job keys are full resource keys** (`cyber_unified_data_plane`, `cyber_unified_app`) — a
  bare prefix fails with "resource not found".
- **`workspace.host` is a literal per target** — it configures auth, so DAB forbids
  `${var}` interpolation on it. `databricks_sandbox` and `edp_dev` pin their hosts;
  omit/override via `DATABRICKS_HOST` or `-p <profile>` when deploying elsewhere.
- **Metric-view DDL runs on the warehouse, not in the pipeline.** `CREATE VIEW WITH
  METRICS` is UC DDL a declarative pipeline rejects; it is a `sql_task`
  (`metric_view_phishing`) chained after the pipeline in `cyber_unified_data_plane`.
- **`:source_table` swaps the metric view's source per target** without editing SQL:
  unqualified `phishing_detail` (sandbox → local synthetic gold) vs.
  `conn_cyberarch.dbo.phishing_detail` (edp_dev → real). The view always LIVES in
  `${var.catalog}.${var.schema}`.
- **Materialization needs a clean view.** Keep the metric view free of per-user
  access controls / invoker-dependent exprs (`current_user`, `is_member`) —
  materialization precomputes as the owner and is disabled for views that carry them.
  Per-user governance is enforced by OBO at query time instead.
- **Lakebase serves app STATE only.** KPI reads never touch Lakebase. Don't add a
  synced-aggregate table or read KPIs from Postgres.

## Configuration model (the heart of the repo)

`app/cyber-unified.yaml` is the single source of truth. `${ENV}` placeholders resolve
at startup from the app env (populated by DAB variables). A domain is defined ONCE
and everything downstream is generic:

```yaml
domains:
  - key: phishing
    label: "Phishing & Email Security"
    metric_view:
      name: mv_phishing
      source_table: "${CYBERUNIFIED_CATALOG}.${CYBERUNIFIED_SCHEMA}.phishing_detail"
      dimensions:                       # MUST include a `day` dim (drives 30/60/90 windows + trend)
        - { name: day, expression: "CAST(eventtimestamp AS DATE)" }
      measures:                         # measure MATH lives here AND in mv_*.sql — keep them identical
        - name: phishing_click_rate     # write PORTABLE SQL (CASE WHEN / NULLIF / standard division):
          expression: "..."             #   the SAME string runs in Spark (metric view) AND DuckDB (seed).
          format: percent               # percent measures are 0-100 (multiply *100 in the expr).
          goal: lower
          green: 5
          amber: 10
    detail_table:                       # the drill-down table — generic, config-driven (NO bespoke row model)
      columns:                          # SELECTed from source_table, shown in order
        - { field: useremailaddress, label: "Recipient" }
      filters:                          # quick-filter tabs -> trusted WHERE fragments (never user input)
        - { key: clicked, label: "Clicked", where: "eventtype = 'Email Click'" }
```

Rules baked into the code (nothing hardcoded to a domain):

- **Add a domain** = add a `domains:` entry + `resources/metricviews/mv_<key>.sql`
  + a `metric_view_<key>` `sql_task` in `databricks.yml`. If it needs synthetic
  data, add a generator in `pipelines/lib/generator.py` + a `_GOLD_SCHEMAS` entry.
  No `.py`/`.tsx` edits. `/domain/<key>` renders automatically.
- **A `day` dimension is mandatory** — the scorecard windows on
  `day >= current_date() - INTERVAL N DAY` and the trend does `GROUP BY day`.
- **Measure expressions must be portable** — the metric view (Spark) and the seed
  provider (DuckDB) both evaluate the config expression, so avoid engine-specific
  functions (`try_divide`, `COUNT_IF`); use `CASE WHEN`, `COUNT`, `NULLIF`, and
  standard division. Keep `mv_<key>.sql` measure exprs identical to config.
- **Detail tables are config-only** — `/api/{domain}/rows` SELECTs the configured
  columns from the domain's `source_table` (OBO) with the configured filters/sort.
  Do NOT reintroduce a per-domain row model (`AccountRow`/`FindingRow`) or a
  hardcoded `/identity/accounts`-style endpoint.
- **Features gate optional UI** — `features.soc_view_enabled` gates the incidents
  view; `genie_enabled` the Genie drawer. Unconfigured optional data returns empty,
  never an error.

## Access control

Group-driven, and identical across targets (top-level `permissions:` + the app
block reference `${var.manage_group}` / `${var.user_group}`):
- `manage_group` → CAN_MANAGE on app/job/pipeline; `user_group` → app CAN_USE,
  job/pipeline CAN_VIEW. The groups must PRE-EXIST (DABs cannot create groups).
- **UC data-layer grants are a one-time metastore-admin step, NOT in the bundle** —
  UC grant principals must be ACCOUNT groups (these are workspace groups). Grant the
  user group `USE CATALOG` + `USE SCHEMA` + `SELECT` on the catalog/schema so members
  can query the metric view. See README "Access control".

## Conventions

- **Config-driven + OBO by default** (see "Working principles") — the two
  non-negotiables. Tempted to hardcode a domain/measure/column? Put it in config.
  Tempted to read data as the SP? Use the user's OBO token.
- **The measure math lives ONCE.** It is the metric view's YAML body, mirrored in
  `cyber-unified.yaml` `expression` (used by the seed engine + lineage display). Keep the
  two identical; if they drift, the seed (local) and prod KPIs disagree.
- **The front end is config-driven.** Never reintroduce a hardcoded data model, a
  mock store, or `if key === "identity"` branching in a page. Columns, rows, KPIs,
  trends, and breakdowns all come from `/api/config` + `/api/metrics/:key` +
  `/api/:key/rows`. `dist/` is committed (the Apps runtime has no build step) —
  rebuild with `make build` and commit when the UI changes.
- **Branching + PRs.** Substantial changes land on a feature branch → PR → merge to
  `main`, one concern per PR. Keep environment config isolated in `databricks.yml`
  targets — no per-developer hardcoding.
- **Never commit** tokens/credentials, customer data, `MEMORY.md`, `node_modules/`,
  `.venv/`, `__pycache__/`, or `.claude/` / `.isaac/`. `app/frontend/dist/` IS
  committed on purpose (see `.gitignore`).

## Living-deliverable rule

This file is part of the deliverable. Any change to repo structure, the command
workflow, the configuration model, or the access-control model MUST update
AGENTS.md in the SAME change.
