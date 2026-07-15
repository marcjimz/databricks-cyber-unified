# Cyber360 Unified Dashboard — Development Skill & Compliance Guide

> **Audience:** Genie Code (and any AI/human contributor) shipping on this repo.
> **Read this first.** It encodes the non-negotiable principles, the architecture
> contract, and the workflow rules. Violating these breaks the demo's promise:
> *a customer clones this repo, edits YAML, points at their own data, and ships.*

---

## 1. The One Principle

**Configuration drives everything. Code is the engine; YAML is the steering wheel.**

The application is *config-driven*. The single source of truth is the dashboard
spec YAML (`app/cyber360.yaml`, mirrored in the frontend as
`lib/config/dashboard-spec.ts`). Adding a domain, adding a KPI, repointing a
metric, swapping a Genie Space, or retuning a RAG threshold is a **YAML edit** —
never a component or endpoint change.

If you find yourself editing a React component or a FastAPI route to change *what
the dashboard shows*, stop. The change belongs in the YAML. Editing code is only
for changing *how the framework behaves* — new measure formats, new chart types,
new provider backends.

### What the config onboards

- **Org identity** — name, scale context, branding/logo.
- **Domains** — each domain is a security posture area (Identity & Access,
  Vulnerability Management, …). A domain carries: `key`, `label`, `icon`,
  `description`, a Genie Space, a metric view, and health rollups.
- **Descriptions/meaning** — provenance and semantics live in the measure
  `comment` field, exactly like a Databricks Metric View. There is intentionally
  **no `ocsf_class` column** on a measure — the meaning lives in the comment.
- **KPIs** — top-line scorecard tiles and per-domain measures, each with a SQL
  expression, format, goal direction, and RAG thresholds.

---

## 2. Framework Tenets (non-negotiable)

1. **Everything is a KPI built on top of the gold layer.**
   The UI never touches raw or silver data. It renders measures computed over
   gold-layer tables (or their pre-aggregations). A number on screen is always a
   measure defined in the YAML with an expression, a format, and a RAG threshold.

2. **The gold layer adheres to OCSF.**
   Gold tables follow the [OCSF](https://schema.ocsf.io/) data model. Start with
   the **Identity & Access** domain (Authentication `3002`, Account Change `3001`,
   plus an account-inventory snapshot) and **Vulnerability Management**
   (Vulnerability Finding `2002`, asset scan coverage). New domains map to their
   OCSF classes. Provenance is expressed in measure `comment`s, not columns.

3. **Bundled data is optional — bring your own. Default-on, DAB-gated.**
   The synthetic OCSF data in `data/` is a *convenience for the demo*, not a
   requirement. A customer points the config at their own OCSF-conformant gold
   tables and the app works unchanged. Loading is controlled by a **DAB variable**
   `load_synthetic_data` (**default `true`**) that gates the pipeline's ingest
   stage — flip it to `false` for bring-your-own-data and the pipeline skips the
   load and builds metric views/aggregates over the customer's existing tables.
   No canonical public OCSF synthetic corpus exists, so we generate our own
   (config-driven generator), using the per-class sample events at
   [schema.ocsf.io](https://schema.ocsf.io/) as the field-fidelity reference.

4. **KPIs are served from Lakebase via native synced tables — never a warehouse
   on the request path.** A config-driven **Lakeflow Declarative Pipeline** reads
   the OCSF gold tables, generates the **UC Metric Views** (governed semantic
   layer), and materializes their measures into **30/60/90-day rolling aggregate
   tables** (daily grain for trend charts + windowed rollups for KPI tiles and
   period-over-period deltas). Those aggregate tables are then **synced into
   Lakebase Postgres** by the native DABs `synced_database_tables` resource
   (Continuous/Triggered reverse-ETL over CDF). The app reads low-latency Postgres.
   SQL Warehouse / Genie serve only the interactive Genie drawer — **never** the
   core KPI reads.

5. **Everything is native and DABs-managed — no brittle imperative scripts.**
   The data plane is declared, not scripted: `database_instance`, `pipelines`,
   `synced_database_tables`, `schemas`, `volumes`, and `apps` are all DAB
   resources in `databricks.yml`. Pipeline *code* exists but is **config-driven**
   (parameterized by `cyber360.yaml`) and run by Lakeflow — not standalone
   `python setup.py`-style glue. If you reach for a one-off script to move or
   shape data, stop: express it as a pipeline transform or a synced table.

6. **The app owns its own state via session-managed migrations.** App-native
   read-write state (user **preferences**, **chat** history, **sessions**) lives
   in app-owned Lakebase tables — separate from the read-only synced KPI tables.
   The app runs **idempotent DDL/DML on startup/session bootstrap**
   (`CREATE TABLE IF NOT EXISTS` + lightweight migrations) so preferences and
   chats persist across sessions. This is app-managed, not a deployment script.

7. **On-Behalf-Of (OBO) access, all the way down.**
   The app runs as the *user*, never as a service principal with broad rights. If
   the user cannot access the underlying data, they cannot see it in the app.
   Enforce OBO at every data boundary (Lakebase row access + UC ACLs for Genie).
   A permission denial degrades gracefully in the UI ("Access restricted"), never
   leaks data.

---

## 3. Architecture Contract

```
                        ┌─────────────────── DATA PLANE (100% DABs-declarative) ───────────────────┐
OCSF gold tables ──▶ Lakeflow Declarative Pipeline (config-driven by cyber360.yaml)
 (bring-your-own,      │  1. generates UC Metric Views  (governed semantic layer)
  demo optional)       │  2. materializes measures → daily-grain + 30/60/90d aggregate tables
                       ▼                                             (CDF + primary keys)
                  UC aggregate tables ──synced_database_tables (Continuous/Triggered reverse-ETL)──▶
                                                                                                    │
                        └───────────────────────────────────────────────────────────────────────┘│
                                                                                                    ▼
                                                                              Lakebase (managed Postgres)
                                                                              ├── KPI aggregates (read-only, synced)
                                                                              └── app state (read-write, app-owned):
                                                                                    preferences · chats · sessions
                        ┌────────────────── APP PLANE ──────────────────┐            ▲
Browser (React SPA, config-driven)                                      │            │ OBO
   │ /api/config → drives all rendering                                 │            │
   │ /api/metrics/*, /api/{domain}/* → KPI tiles + trend charts         ▼            │
FastAPI (app/main.py) — serves built SPA + JSON APIs                                 │
   │ OBO middleware (X-Forwarded-Access-Token)                                       │
   │ session bootstrap: idempotent DDL/DML for app-state tables ─────────────────────┤
   ▼                                                                                 │
Provider layer (app/providers/)                                                      │
   ├── SeedProvider     → in-memory OCSF synthesis (demo/local, zero workspace deps) │
   └── LakebaseProvider → reads synced KPI aggregates from Lakebase Postgres (OBO) ──┘

Genie Spaces + SQL Warehouse ──▶ interactive Genie drawer ONLY (OBO, UC-enforced)
```

**Two planes, cleanly separated:**
- **Data plane (declared in `databricks.yml`)** — `database_instance` +
  `pipelines` (Lakeflow, config-driven) + `synced_database_tables` (reverse-ETL) +
  `schemas`/`volumes`. Produces the read-only KPI aggregates in Lakebase. No
  imperative scripts.
- **App plane (owned by the FastAPI app)** — serves config + KPI reads, enforces
  OBO, and manages its own read-write state (preferences/chats/sessions) via
  idempotent migrations at session bootstrap.

**Rules of the contract:**

- The frontend renders **only** from `/api/config` + data endpoints. No hardcoded
  domains, KPIs, thresholds, or labels in components.
- The provider is selected by config (`data_source.provider: seed | lakebase`).
  `SeedProvider` must always work with zero workspace dependencies so the demo
  runs anywhere. `LakebaseProvider` is the production path.
- All workspace-specific values (catalog, schema, Lakebase instance, warehouse id,
  Genie embed URLs) flow as **DAB variables → `app.yaml` env vars → `${VAR}`
  placeholders resolved in `cyber360.yaml` at startup**. Never hardcode a
  workspace URL, catalog, or ID anywhere.
- The entire stack is deployed via DABs (`databricks.yml`) using native resources
  only: `database_instance`, `pipelines`, `synced_database_tables`, `schemas`,
  `volumes`, `genie_spaces`, `apps`. No jobs-as-glue, no imperative sync scripts,
  no hacky workarounds. (Genie space resources need the **direct deployment engine**,
  Databricks CLI ≥ 1.3.0; bundle-created spaces are new, not bound to pre-existing.)
- **Genie Spaces are config-declared, not coded.** Each domain's `genie` block in
  the YAML declares the space; DABs creates it (title/description/warehouse_id) and
  the app embeds it by id/URL. Swapping or adding a Genie Space is a YAML edit.
- **Permissions are declarative.** Bundle-owned schemas/objects carry `grants`
  (principal → privileges) in `databricks.yml`. Runtime data access is still
  governed by UC + OBO (the user's own grants). Neither is app code.
- KPI aggregates in Lakebase are **read-only** (owned by the sync). App-state tables
  (preferences/chats/sessions) are **read-write** and owned by the app. Never let
  the app write to a synced table, and never let the pipeline touch app-state.

### The config-vs-code boundary (the framework promise)

**Config (YAML + DABs) — scales without touching app code:** domains, each
domain's Lakebase data source (metric view → aggregate → synced table, resolved by
name from config), KPIs/measures/thresholds, top-line tiles, reporting periods,
Genie Spaces, grants/permissions, and whether demo data loads.

**Code — only the wireframes:** the *page layouts/components* (scorecard, manager,
SOC, tables, charts, Genie drawer) and the framework engine (measure formats, RAG
logic, provider I/O). These are generic and render whatever the config declares.

**REQUIRED for the promise to hold:** the per-domain drill-down must be a **single
generic route** (`/domain/:key`) driven by config — **not** one coded page per
domain. The v0 reference ships separate `domain/identity` and `domain/vulnerability`
pages; during the port, **collapse them into one config-driven domain template** so
adding a domain in YAML needs zero new page code. Domain-specific tables (e.g.
accounts vs. findings) are selected by a config-declared `table` type, not by a
bespoke page. If you catch yourself adding a page/route/component to add a *domain*,
you've broken the framework — generalize instead.

---

## 4. Config Schema Cheat-Sheet

A measure (the atomic unit) looks like:

```yaml
- name: mfa_adoption
  label: MFA adoption
  expression: "SUM(IF(is_mfa, 1, 0)) / COUNT(*) * 100"  # SQL over the gold/metric-view
  comment: Share of interactive authentications satisfied with an MFA factor.  # MEANING lives here
  format: percent          # percent | count | days | hours | score
  goal: higher             # higher = more is better | lower = less is better
  green: 99                # RAG threshold (raw value)
  amber: 95
  caption: "Target: 100%"
  # fixedStatus: amber     # optional override when there is no numeric target yet
```

- **Domains** own a `metricView` (name, source table, comment, dimensions,
  measures), a `genie` block (spaceId, embed env var, starters), and `health`
  rollups (`scoreMeasures`, `highlights`).
- **topLineKpis** reference `{domain, measure, trend}` — the scorecard tiles.
- **Reporting periods** (30/60/90d comparison) are a first-class contract
  (`ComparisonPeriod`); measures show target + period-over-period change.

To onboard a new domain: add a `domains[]` entry with its OCSF-backed metric view
and measures, add any top-line KPIs, and redeploy. The pipeline picks up the new
metric view + aggregates from config, and a `synced_database_tables` entry lands
them in Lakebase automatically. **No component changes, no scripts.**

---

## 5. Workflow & Branch Discipline (MANDATORY)

1. **Never commit to `main`.** All development happens on a **feature branch**
   (`feat/…`, `fix/…`, `chore/…`). `main` stays shippable at all times.

2. **Branch Lakebase alongside your code branch.** Any DML/DDL against Lakebase
   (schema changes, table adds, aggregate reshapes, seed loads) must run against a
   **branched Lakebase database**, not the shared/main instance. Match the DB
   branch lifecycle to the feature branch: create on branch start, drop/merge on
   PR merge. This keeps `main`'s data plane stable while you iterate on schema.

3. **Open a PR into `main`.** Get review before merge. Keep the demo promise
   green: a fresh clone + YAML edit + `make deploy` must still work.

4. **Prefer Isaac Review before pushing.** Run `/review` (Databricks' recommended
   code-review pipeline) on your branch before opening the PR.

5. **Don't leave the repo root dirty.** Temp/scratch dirs stay inside the repo and
   get added to `.gitignore`. Never write outside the repo root.

---

## 6. Anti-Patterns (do NOT do these)

- ❌ Hardcoding a domain, KPI, label, or threshold in a React component.
- ❌ Adding a workspace URL, catalog name, warehouse id, or Genie URL to source.
- ❌ Querying a SQL Warehouse on the KPI request path (that's Lakebase's job).
- ❌ Writing imperative "sync" / "load" scripts instead of `pipelines` +
  `synced_database_tables` DAB resources.
- ❌ Trying to sync a Metric View directly (it's a semantic layer, not a table —
  materialize its measures into an aggregate table, then sync THAT).
- ❌ Letting the app write to a synced (read-only) KPI table, or the pipeline write
  to app-state tables.
- ❌ Running the app as a service principal / bypassing OBO.
- ❌ Adding an `ocsf_class` column to a measure (use the `comment`).
- ❌ Requiring the bundled synthetic data (it must be optional).
- ❌ Committing to `main` or running DDL against the shared Lakebase DB.
- ❌ Deploying via jobs/scripts instead of native DAB resources.

---

## 7. Definition of Done

A change is done when:

- [ ] The behavior is driven by `cyber360.yaml`, not code (unless it's engine work).
- [ ] `SeedProvider` still runs the full dashboard with zero workspace deps.
- [ ] No hardcoded workspace/catalog/ID/URL anywhere; all via DAB vars → env → YAML.
- [ ] KPIs read from Lakebase (prod path) and are OCSF-gold-backed.
- [ ] OBO is enforced at every data boundary; denials degrade gracefully.
- [ ] Work is on a feature branch with a branched Lakebase DB; PR opened, not `main`.
- [ ] `make build` + `make validate` pass; `make deploy` to a target works.
