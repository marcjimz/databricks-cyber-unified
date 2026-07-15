# Cyber360 Unified Dashboard

A **config-driven** cybersecurity posture dashboard that runs as a Databricks
App. KPIs are built on an **OCSF-aligned gold layer**, served from **Lakebase**
(managed Postgres) via native synced tables, and rendered by a React SPA behind
a FastAPI backend. You customize it by editing **`app/cyber360.yaml`** — domains,
measures, KPIs, thresholds, and Genie Spaces — **not** by touching code.

> The binding development principles live in **[`SKILL.md`](./SKILL.md)** — read
> it first. In short: config drives everything, KPIs sit on the OCSF gold layer,
> the data plane is 100% DABs-native (no imperative scripts), the app enforces
> On-Behalf-Of (OBO) auth end-to-end, and adding a domain is a pure YAML edit.

---

## Architecture

Two cleanly separated planes, both deployed by one Databricks Asset Bundle
(`databricks.yml`):

**Data plane (declarative, no scripts).** A config-driven **Lakeflow Declarative
Pipeline** reads the OCSF gold tables, generates a **UC Metric View** per domain
(the governed semantic layer), and materializes their measures into two generic
aggregate tables — `agg_daily` (daily-grain series for trends) and `agg_rollup`
(30/60/90-day windows + period-over-period deltas for KPI tiles). Native
`synced_database_tables` reverse-ETL those aggregates into Lakebase Postgres as
read-only tables.

**App plane (FastAPI + React).** The app serves the built SPA + JSON APIs. KPI
reads come from the synced Lakebase aggregates over a **per-request OBO
connection**, so Unity Catalog permissions are enforced all the way down to
Postgres (no data access = no app access). The app also owns three read-write
state tables (preferences, chats, sessions) that it bootstraps itself with
idempotent `CREATE TABLE IF NOT EXISTS` migrations at startup. SQL Warehouse /
Genie are used **only** for the interactive Genie drawer, never for KPI reads.

```
OCSF gold ─▶ Lakeflow pipeline ─▶ UC Metric Views ─▶ agg_daily / agg_rollup ─▶ (synced) ─▶ Lakebase
                                                                                              │ OBO
React SPA ─▶ FastAPI ─▶ LakebaseProvider (KPI reads) ─────────────────────────────────────────┘
                     └─ SeedProvider (in-memory OCSF synthesis; zero workspace deps, local/demo)
```

---

## Prerequisites

- **Databricks CLI ≥ 1.3.0** (`databricks --version`) authenticated to the target
  workspace (`databricks auth login`).
- **Python 3.11+** and **Node 20+** (for local dev / building the SPA).
- Workspace permission to create a database instance, pipeline, synced tables,
  schema/volume, and an app.

---

## Deploy

All workspace-specific values (catalog, schema, warehouse id, Lakebase instance,
Genie embed URLs) are **DAB variables** — override them at deploy time, never
hardcode. Defaults live in `databricks.yml`.

```bash
databricks bundle validate -t dev      # check the bundle config
databricks bundle deploy   -t dev      # creates instance, pipeline, synced tables, app
databricks bundle run cyber360_pipeline -t dev   # build gold → metric views → aggregates
databricks bundle run cyber360_app      -t dev   # start the app (prints the app URL)
```

**Bring-your-own-data.** The bundled synthetic data is a convenience, not a
requirement. The `load_synthetic_data` variable (**default `true`**) gates the
pipeline's demo-load stage. Point the config at your own OCSF gold tables and
flip it off:

```bash
databricks bundle deploy -t dev --var load_synthetic_data=false
```

---

## Local development (no workspace needed)

The `SeedProvider` synthesizes the full dashboard in-memory, so you can run
everything locally with zero Databricks dependencies:

```bash
make install        # backend (pip -e) + frontend (npm)
make build          # build the React SPA into app/frontend/dist
make dev            # uvicorn on :8000 with the seed provider
```

Regenerate the bundled demo CSVs (for inspection only — the pipeline generates
the same gold in-code):

```bash
make generate-data
```

---

## Onboard a new domain (the headline how-to)

Adding a security domain is a **pure `app/cyber360.yaml` edit** — no page, route,
or endpoint code. The pipeline builds the metric view + aggregates, a synced
table lands them in Lakebase, and the generic `/domain/<key>` page renders it.

1. Add a `domains[]` entry:

   ```yaml
   - key: endpoint
     label: "Endpoint Protection"
     short: "Endpoint"
     icon: shield
     description: "EDR coverage, isolation, and threat response posture."

     genie:
       embed_url: "${GENIE_ENDPOINT_EMBED_URL}"
       starters:
         - "Which hosts are missing the EDR agent?"

     health:
       score_measures: [edr_coverage]
       highlights: [edr_coverage, hosts_unprotected]

     metric_view:
       name: mv_endpoint
       source_table: "${CYBER360_CATALOG}.${CYBER360_SCHEMA}.endpoint"
       comment: "Endpoint protection posture over the device inventory."
       dimensions:
         - name: day
           expression: "CAST(last_seen AS DATE)"
       measures:
         - name: edr_coverage
           label: "EDR coverage"
           expression: "COUNT_IF(edr_installed) / COUNT(*) * 100"
           comment: "Share of managed hosts running the EDR agent."
           format: percent
           goal: higher
           green: 98
           amber: 90
           caption: "Target: 100%"
   ```

2. (Optional) reference a measure in `top_line_kpis` to add a scorecard tile.
3. `databricks bundle deploy -t dev && databricks bundle run cyber360_pipeline -t dev`.

That's it — nav link, KPI tiles, trend charts, drill-down table, and Genie drawer
all appear with **zero code**.

### Scale metrics within a domain

Add a `measures[]` entry to that domain's `metric_view` with an `expression`
(SQL over the gold/metric-view), a `comment` (its meaning — provenance lives
here, there is intentionally no `ocsf_class` column), a `format`, a `goal`, and
RAG thresholds. Reference it from `health` or `top_line_kpis`, then redeploy.

---

## Config schema reference

| Key | Purpose |
|-----|---------|
| `org` | Org name + logo shown in the shell. |
| `data_source` | `catalog`, `schema`, `warehouse_id` (Genie only), `provider` (`seed`\|`lakebase`). |
| `lakebase` | Instance/database, `synced_tables` (read-only aggregates), `state_tables` (app-owned). |
| `data_loading` | `load_synthetic` demo-load gate (mirrors the `load_synthetic_data` DAB var). |
| `features` | `genie_enabled`, `soc_view_enabled`, `theme_toggle`, `lineage_popover`. |
| `top_line_kpis` | `{domain, measure, trend, caption}` — executive scorecard tiles. |
| `domains[]` | `key`, `label`, `short`, `icon`, `description`, `genie`, `health`, `metric_view`. |
| `metric_view` | `name`, `source_table`, `comment`, `dimensions[]`, `measures[]`. |
| measure fields | `name`, `label`, `expression`, `comment`, `format` (percent\|count\|days\|hours\|score), `goal` (higher\|lower), `green`/`amber` thresholds, `caption`, optional `fixed_status`, `trend`. |
| `health` | `score_measures[]` (rollup score), `highlights[]` (surfaced tiles). |
| `genie` | `space_id`, `embed_url`, `starters[]`. |

---

## Verification checklist

- [ ] `databricks bundle validate -t dev` → `Validation OK!`
- [ ] `make build` produces `app/frontend/dist/`.
- [ ] Pipeline run materializes `agg_daily` / `agg_rollup`; synced tables land in Lakebase.
- [ ] **OBO:** a user without grants sees "Access restricted", not data.
- [ ] **Config onboarding:** add a domain in YAML → `/domain/<key>` renders with no code change.
- [ ] Reporting-period (30/60/90d) deltas + trend charts read from the synced aggregates.
- [ ] Preferences + chats persist across sessions (app-owned state tables).

---

## Branch discipline

Never commit to `main`. Develop on a feature branch, and run any Lakebase DDL/DML
against a **branched Lakebase database** (not the shared instance). Open a PR into
`main` and run `/review` (Isaac Review) before pushing. See `SKILL.md` §5.
