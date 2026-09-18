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
  security domain, a measure, or a detail column MUST be a pure `cyber-unified.yaml`
  edit — point `metric_view.name` at an already-published view — with **zero** app
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

A config-driven cybersecurity posture dashboard. It **READS an already-published
UC Metric View** and **CREATES NOTHING in the data layer**. It ships as a
Databricks Asset Bundle (DAB) that provisions exactly two things: a Databricks App
(FastAPI + built React SPA), and an autoscaling **Lakebase** Postgres project that
serves ONLY the app's read-write state. KPIs are read by querying the metric view
natively with `MEASURE()` on the SQL Warehouse (per-user OBO) — there is no
reverse-ETL and no flattened aggregate stage.

The whole per-environment data contract is a **NAME**: `domains[].metric_view.name`
in `app/cyber-unified.yaml`, resolved inside
`${CYBERUNIFIED_CATALOG}.${CYBERUNIFIED_SCHEMA}`. That name may differ per
environment. Because the app never builds the view, it needs **no privilege on
whatever the view is built over** (e.g. a customer's federated `conn_cyberarch`).
Both the KPI `MEASURE()`s AND the drill-down rows come from that one relation.

The pivot in progress: the dashboard now starts with **ONE** domain — **phishing
& email security** — driven by a single metric view. Identity & vulnerability were
staging-only demo domains and have been removed (git history preserves them).

## Repo layout

```
databricks.yml            Bundle root (name: cyber-unified): variables, targets, resources, group permissions
  targets: databricks_sandbox (default, FEVM, SYNTHETIC) | edp_dev (Azure EDP DEV, REAL CyberArk source) | prod
  resources: the APP + the Lakebase project ONLY — plus the gated seed job. NO pipeline, NO data-plane job.
setup/sandbox/            SANDBOX-ONLY UTILITY (emulates what a real workspace already provides). NOT a bundle
                           resource, NOT a deploy step, and never run against a real target.
  phishing_source.sql      Pass-through view over the seeded synthetic gold.
  mv_phishing.sql          The emulated UC Metric View (CREATE VIEW WITH METRICS LANGUAGE YAML) + materialization.
  apply_metricview.py      Applies both .sql from the CLI against the warehouse; resolves catalog/schema/warehouse
                           from `bundle summary`. Run via `make sandbox-metricview sandbox`, which HARD-REFUSES
                           any non-sandbox target (these files issue DDL).
scripts/
  seed_synthetic_gold.py   SANDBOX-ONLY, GATED synthetic gold seed (_GOLD_SCHEMAS). A spark_python_task run by
                           `make seed sandbox` — NOT part of deploy, and a no-op unless load_synthetic_data=true
                           (which defaults FALSE). Replaced the old Lakeflow pipeline, which deployed to every
                           target (incl. customer workspaces that already have real tables) and failed graph
                           analysis when it defined no tables. Synthetic data is a DEV AID; never an app resource.
pipelines/
  lib/generator.py         Deterministic synthetic gold rows (phishing_detail). The ONE source of synthetic data, shared
                           by the seed job AND the app's seed provider. A plain helper library (no deployed pipeline).
  lib/config.py            Dependency-free cyber-unified.yaml reader for the seeder (no app import).
setup/generate_csvs.py     Standalone CSV emitter (make generate-data) — reference/inspection only.
app/
  cyber-unified.yaml            THE config (SSOT): org, data_source, domains (metric_view NAME + measures + dimensions
                           + detail_table), top_line_kpis, features. Customers edit THIS to name their already-published
                           metric view — no code changes.
  main.py                  FastAPI entry: loads config, resolves ${ENV} from app env, inits Lakebase state pool + migrations.
  core/config.py           Pydantic models for cyber-unified.yaml + RAG/format/period helpers (shared math).
  core/sql.py              SQL Warehouse client (Statement Execution API), per-request OBO token.
  providers/
    metricview.py          PROD provider: queries the UC metric view with MEASURE() on the warehouse (OBO). GENERIC —
                           no domain names. Also serves the generic detail table (SELECT from the SAME metric view).
    seed.py                LOCAL provider (make dev, zero workspace deps): computes ANY domain's measures + detail rows
                           from generator.py rows via DuckDB, using the SAME measure SQL from config. GENERIC.
    __init__.py            Provider factory (provider: "metricview" | "seed").
  api/                     FastAPI routers: config, health, metrics (scorecard + /metrics/{domain}), tables
                           (/{domain}/rows — generic), incidents (gated by soc_view_enabled).
  models/                  Pydantic response models (common, domain, detail, scorecard, incidents).
  frontend/                Vite + React SPA (config-driven; /domain/:key is one generic route). dist/ is COMMITTED.
  migrations/              Lakebase app-state migrations (preferences/chats/sessions) — app-owned RW state only.
  tests/
    test_bundle_architecture.py  DURABLE GUARD SUITE (8 tests) — fails if a future change reintroduces a pipeline
                           resource, a data-plane job / any sql_task, a metric_view built rather than named, view
                           DDL outside setup/sandbox/, ungated or default-on seeding, seeding inside deploy, a
                           dangling ${resources.*}/${var.*} ref, or a real-data target that enables seeding.
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

# Full deploy sequence in ONE target (validate -> deploy -> run app). NOTHING in the
# data layer is touched, so a deploy succeeds/fails on DEPLOYMENT alone:
make deploy sandbox     # FEVM, reads the sandbox's emulated metric view
make deploy edp_dev     # Azure EDP DEV, reads the customer's published metric view
make setup sandbox      # FIRST-TIME on a fresh workspace: deploy x2 -> app

# Individual steps (same positional env):
make validate sandbox   # bundle validate only
make app sandbox        # deploy + (re)start the app

# SANDBOX-ONLY utilities — they EMULATE what a real workspace already provides.
# Neither is a deploy step; neither is needed by (or safe on) a real target:
make seed sandbox              # gated synthetic gold (cyber_unified_seed_job); no-op unless load_synthetic_data=true
make sandbox-metricview sandbox # publish the emulated metric view over that gold (refuses any other target)
```

### Deploy gotchas

- **The deploy creates nothing in the data layer.** `make deploy` is validate →
  deploy → run app. There is no data-plane job to run, so a data-layer or UC-grant
  problem can no longer fail a deploy. Do NOT reintroduce a deploy-time DDL step.
- **Two-phase on a fresh workspace.** The first `bundle deploy` may partially fail
  (Lakebase provisions the project asynchronously; dependent objects race ahead).
  Re-run `deploy`, then start the app — that is what `make setup <env>` does.
- **Job keys are full resource keys** (`cyber_unified_seed_job`, `cyber_unified_app`) — a
  bare prefix fails with "resource not found".
- **`workspace.host` is a literal per target** — it configures auth, so DAB forbids
  `${var}` interpolation on it. `databricks_sandbox` and `edp_dev` pin their hosts;
  omit/override via `DATABRICKS_HOST` or `-p <profile>` when deploying elsewhere.
- **The metric view is NAMED, never built.** Repointing to a different environment
  is editing `domains[].metric_view.name` — nothing else. There is no source-table
  knob: the app doesn't know or care what the view is built over, which is exactly
  why it needs no privilege on the customer's federated source catalog. Publishing a
  metric view is a SANDBOX utility (`make sandbox-metricview sandbox`), not a
  bundle resource and not a deploy step.
- **Materialization needs a clean view.** If you author a view (sandbox emulation, or
  advising a customer), keep it free of per-user access controls / invoker-dependent
  exprs (`current_user`, `is_member`) — materialization precomputes as the owner and is
  disabled for views that carry them. Per-user governance is enforced by OBO at query
  time instead.
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
      # The NAME of the ALREADY-PUBLISHED view, resolved inside catalog.schema.
      # This is the ENTIRE per-environment contract — there is no source_table.
      name: phishing_detail_metric_view
      dimensions:                       # MUST include a `day` dim (drives 30/60/90 windows + trend)
        - { name: day, expression: "CAST(eventtimestamp AS DATE)" }
      measures:                         # the READ-SIDE contract: which MEASURE()s to ask for + how to present them
        - name: phishing_click_rate     # write PORTABLE SQL (CASE WHEN / NULLIF / standard division):
          expression: "..."             #   the SAME string runs in Spark (metric view) AND DuckDB (seed).
          format: percent               # percent measures are 0-100 (multiply *100 in the expr).
          goal: lower
          green: 5
          amber: 10
    detail_table:                       # the drill-down table — generic, config-driven (NO bespoke row model)
      columns:                          # SELECTed from the SAME metric view; they MUST exist on it
        - { field: useremailaddress, label: "Recipient" }
      filters:                          # quick-filter tabs -> trusted WHERE fragments (never user input)
        - { key: clicked, label: "Clicked", where: "eventtype = 'Email Click'" }
```

Rules baked into the code (nothing hardcoded to a domain):

- **Add a domain** = add a `domains:` entry whose `metric_view.name` points at the
  metric view that environment already publishes. That is the whole production step —
  no bundle resource, no `sql_task`, no `.py`/`.tsx` edits. `/domain/<key>` renders
  automatically. *On the sandbox only*, if you want to emulate that view locally, add
  a `setup/sandbox/mv_<key>.sql` and, if it needs synthetic data, a generator in
  `pipelines/lib/generator.py` + a `_GOLD_SCHEMAS` entry.
- **A `day` dimension is mandatory** — the scorecard windows on
  `day >= current_date() - INTERVAL N DAY` and the trend does `GROUP BY day`.
- **Measure expressions must be portable** — the published metric view (Spark) and the
  seed provider (DuckDB) both evaluate the config expression, so avoid engine-specific
  functions (`try_divide`, `COUNT_IF`); use `CASE WHEN`, `COUNT`, `NULLIF`, and
  standard division. Keep any `setup/sandbox/mv_<key>.sql` measure exprs identical to config.
- **Detail tables are config-only, and read the SAME metric view** —
  `/api/{domain}/rows` SELECTs the configured columns from the domain's metric view
  (OBO) with the configured filters/sort, so every `detail_table` column MUST exist on
  that view. Do NOT reintroduce a per-domain row model (`AccountRow`/`FindingRow`), a
  hardcoded `/identity/accounts`-style endpoint, or a separate source/pass-through view.
- **Features gate optional UI** — `features.soc_view_enabled` gates the incidents
  view; `genie_enabled` the Genie drawer. Unconfigured optional data returns empty,
  never an error.
- **`gold_table` is LOCAL/sandbox bookkeeping ONLY.** Optional on a domain; names the
  synthetic gold table (defaults to `<key>_detail`) for the seed provider + sandbox
  seed job. The metric-view read path never uses it — do not turn it into a data
  source or reintroduce it as a `source_table` by another name.

## Access control

Group-driven, and identical across targets (top-level `permissions:` + the app
block reference `${var.manage_group}` / `${var.user_group}`):
- `manage_group` → CAN_MANAGE on the app + seed job; `user_group` → app CAN_USE,
  seed job CAN_VIEW. The groups must PRE-EXIST (DABs cannot create groups).
- **UC data-layer grants are a one-time metastore-admin step, NOT in the bundle** —
  UC grant principals must be ACCOUNT groups (these are workspace groups). Grant the
  user group `USE CATALOG` + `USE SCHEMA` + `SELECT` on the catalog/schema so members
  can query the metric view. See README "Access control".

## Conventions

- **Config-driven + OBO by default** (see "Working principles") — the two
  non-negotiables. Tempted to hardcode a domain/measure/column? Put it in config.
  Tempted to read data as the SP? Use the user's OBO token.
- **The measure math lives in the published metric view.** `cyber-unified.yaml`
  `expression` mirrors it (used by the seed engine + lineage display). Keep the two
  identical; if they drift, the seed (local) and prod KPIs disagree.
- **Never add a data-layer resource back to the bundle.** No `pipelines:`, no
  data-plane job, no `sql_task`, no view DDL outside `setup/sandbox/`. The guard
  suite `app/tests/test_bundle_architecture.py` fails the build if you do — treat a
  red test there as the architecture rejecting the change, not as a test to fix.
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
