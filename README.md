<p align="center">
  <img src="docs/assets/dbx-banner.jpeg" alt="Databricks" width="100%" />
</p>

# Cyber360 Unified Dashboard

A cybersecurity posture dashboard that runs as a Databricks App. It shows KPIs
across security domains (identity, vulnerabilities, and more) on top of your
OCSF data.

**You configure it, you don't code it.** Everything — domains, measures, KPIs,
thresholds, Genie Spaces — lives in **`app/cyber360.yaml`**. Adding a domain is a
YAML edit, not a code change.

> New here? Read **[`SKILL.md`](./SKILL.md)** first for the design principles.

---

## Architecture

One Databricks Asset Bundle (`databricks.yml`) deploys two parts:

**Data plane.** A **Lakeflow pipeline** reads your OCSF gold tables, builds a
**UC Metric View** per domain, and rolls the measures into two tables:
`agg_daily` (daily trends) and `agg_rollup` (30/60/90-day KPI tiles). Synced
tables copy those into **Lakebase** (managed Postgres) as read-only.

**App plane (FastAPI + React).** The app reads the KPIs from Lakebase and serves
the dashboard. It connects to Postgres as the app's service principal — which
inherits read access through a Databricks reader group (see [Deploy](#deploy)).
It also owns three state tables (preferences, chats, sessions) it creates itself
at startup. SQL Warehouse / Genie are used **only** for the interactive Genie
drawer, never for KPI reads.

```
OCSF gold ─▶ Lakeflow pipeline ─▶ UC Metric Views ─▶ agg_daily / agg_rollup ─▶ (synced) ─▶ Lakebase
                                                                                              │
React SPA ─▶ FastAPI ─▶ LakebaseProvider (KPI reads) ─────────────────────────────────────────┘
                     └─ SeedProvider (in-memory OCSF synthesis; zero workspace deps, local/demo)
```

---

## Prerequisites

- **Databricks CLI ≥ 0.297** (`databricks --version`) authenticated to the target
  workspace (`databricks auth login`). Older CLIs may hard-error on the newer
  Lakebase resource types this bundle uses (`postgres_projects`, `postgres_databases`,
  `postgres_synced_tables`); see the note under **Deploy** about validation warnings.
- **Python 3.11+** and **Node 20+** (for local dev / building the SPA).
- Workspace permission to create a Lakebase project, pipeline, synced tables,
  schema/volume, and an app.
- **Bring-your-own prerequisites** (the bundle does *not* create these):
  - The **UC catalog** (`var.catalog`) must already exist and be owned/accessible by
    the deploying identity — the bundle only creates the schema inside it.
  - The **reader group** (`var.lakebase_reader_group`, default `cyber360-lakebase-readers`)
    must already exist as a Databricks group, **and the app service principal must be
    a member.** The KPI read path connects as this group's Postgres role.

---

## Deploy

All workspace-specific values (catalog, schema, warehouse id, Lakebase topology,
reader group, Genie embed URLs) are **DAB variables** — override them at deploy
time, never hardcode. Defaults live in `databricks.yml`.

### Set these first (they are NOT hardcoded to your workspace)

| What | How | Why |
|------|-----|-----|
| **Workspace host** | Deploy from a Databricks **Git folder** (targets that workspace automatically), or set `DATABRICKS_HOST` / use `databricks auth login` / `-p <profile>`. | `workspace.host` is an auth field — the CLI resolves it *before* variables, so it can't be a `${var}` and is intentionally omitted from `databricks.yml`. It resolves from the ambient environment. |
| **`lakebase_owner_role`** | `--var lakebase_owner_role=<your-role-id>` | The Postgres role that OWNS the app database. Lakebase derives it from the **deploying identity's** email (dots → hyphens), e.g. `jane.doe@corp.com` → `jane-doe`. The default (`marcin-jimenez`) is the original author's — **override it for any other deployer.** |
| **`catalog`** (and `schema` if desired) | `--var catalog=<your_catalog>` | The UC catalog is a bring-your-own prerequisite (see above). |
| **`warehouse_id`** | `--var warehouse_id=<id>` | Only used by the interactive Genie drawer, never KPI reads. |
| **`lakebase_reader_group`** | `--var lakebase_reader_group=<group>` if not using the default | Must be an existing Databricks group whose members include the app SP (see Prerequisites). |

### Deploy flow (two-phase — required, by design)

Synced tables can't bind until their source aggregate tables exist, so the first
`deploy` **partially fails on the synced tables — that is expected** — you run the
pipeline, then deploy again. Substitute your own `--var` overrides throughout:

```bash
# Assume host comes from a Git folder / DATABRICKS_HOST / active profile.
export VARS="--var catalog=<your_catalog> --var warehouse_id=<id> --var lakebase_owner_role=<your-role-id>"

# 1. Phase-1 deploy — creates Lakebase project, schema, pipeline, app.
#    The synced tables FAIL here because agg_daily/agg_rollup don't exist yet. EXPECTED.
databricks bundle deploy -t dev $VARS

# 2. Build the data plane — pipeline (gold + agg_daily/agg_rollup) then the metric views.
databricks bundle run cyber360_data_plane -t dev $VARS

# 3. Phase-2 deploy — now the synced tables succeed (their sources exist). "Deployment complete!"
databricks bundle deploy -t dev $VARS

# 4. Grant the reader group read on the synced schema (the app SP inherits it via
#    group membership). MUST run after phase-2 created the synced tables in Postgres.
databricks bundle run cyber360_grant_reader_role -t dev $VARS

# 5. Start the app (prints the app URL).
databricks bundle run cyber360_app -t dev $VARS
```

> **Why the grant step (4) exists:** Databricks does not propagate UC / `uc_securable`
> grants down to Postgres role privileges, and the app reads the synced aggregates over
> a *direct* psycopg connection. Skipping step 4 leaves the metrics API returning 500 /
> "Failed to load data" even though everything deployed. The grant is idempotent — safe
> to re-run, and covers future re-syncs via `ALTER DEFAULT PRIVILEGES`.

> **Validation warnings are harmless.** `databricks bundle validate` emits
> `unknown field: replace_existing / postgres_databases / postgres_synced_tables`
> on current CLI builds — the bundled JSON schema lags the Lakebase API. These fields
> are valid and deploy correctly; **do not remove them to silence the warnings** (that
> breaks the deploy). Upgrade the CLI to clear them.

### Deploy from the workspace UI (Git folder)

Prefer the UI, or don't have the CLI locally? Sync the repo into a **Git folder**
and run the bundle from a workspace terminal. Because you're inside the target
workspace, the host resolves automatically — no `DATABRICKS_HOST` needed.

1. **Add the Git folder.** In the workspace sidebar: **Workspace → Repos** (or
   your user folder) → **Add → Git folder**. Paste the repo URL, pick the branch
   (`feature/kpi-formatting-reporting-period` or `main`), and **Create**.
2. **Pull latest** any time with the **⟳ (Git)** button on the folder → **Pull**.
3. **Open a terminal in the workspace.** Use a notebook's **web terminal**
   (attach any cluster → the `%sh`/terminal), or a compute node's terminal, then
   `cd` into the Git folder (e.g. `cd /Workspace/Repos/<you>/databricks-cyber-unified`).
4. **Run the same two-phase flow** as above — the CLI is preinstalled on
   Databricks compute, so the `databricks bundle …` commands work as-is:

   ```bash
   export VARS="--var catalog=<your_catalog> --var warehouse_id=<id> --var lakebase_owner_role=<your-role-id>"
   databricks bundle deploy -t dev $VARS                    # phase 1 (synced tables fail — expected)
   databricks bundle run cyber360_data_plane -t dev $VARS   # build aggregates
   databricks bundle deploy -t dev $VARS                    # phase 2 (synced tables succeed)
   databricks bundle run cyber360_grant_reader_role -t dev $VARS
   databricks bundle run cyber360_app -t dev $VARS          # app live
   ```

5. **Find the running app** under **Compute → Apps → `cyber360-dashboard`** (its
   URL is also printed by step 5).

> After a `git add app/frontend/dist` rebuild or any code change, **Pull** the Git
> folder again before re-running `bundle deploy` so the workspace copy is current.

### The `prod` target

Everything above uses `-t dev`, which is the supported flow. The `prod` target
exists as scaffolding but **fails `bundle validate -t prod`** with:

```
target with 'mode: production' cannot include a pipeline with 'development: true'
```

This is a Databricks guardrail, not a bug: a `mode: production` target refuses a
pipeline flagged `development: true` (dev-mode pipelines reuse compute and relax
retry semantics — not safe to ship as prod). The pipeline's `development` flag
is a per-target variable (`pipeline_development`, `true` for dev/tst, pinned
`false` for prod), so all three targets — `dev`, `tst`, `prod` — validate.

**Bring-your-own-data.** The bundled synthetic data is a convenience, not a
requirement. The `load_synthetic_data` variable (**default `true`**) gates the
pipeline's demo-load stage. Point the config at your own OCSF gold tables and
flip it off:

```bash
databricks bundle deploy -t dev --var load_synthetic_data=false
```

---

## CI/CD & feature environments

GitHub Actions (`.github/workflows/`) automate the flow. Once set up, you get an
**isolated environment per feature branch** and release-style promotion.

### One-time setup

CI authenticates with **OAuth machine-to-machine (a service principal)** — no
personal access tokens. Only the client secret is a GitHub *secret*; everything
else is a plain *variable*.

**1. Create the service principal + OAuth secret** (workspace admin):
- **Settings → Identity and access → Service principals → Add service principal**
  (or reuse the app's SP). Note its **Application (client) ID**.
- On that SP → **Secrets → Generate secret**. Copy the **Client secret** *and*
  the **Client ID** shown — the secret is displayed only once.
- Grant the SP what a deploy needs: workspace access (CAN_USE), `CAN_MANAGE` on
  the app + bundle resources, `USE CATALOG`/`CREATE SCHEMA` on the catalog, and
  membership in the Lakebase reader group. (It's the identity CI deploys as.)

**2. Configure the repo** (**Settings → Secrets and variables → Actions**):

| Kind | Name | Value |
|------|------|-------|
| **Secret** | `DATABRICKS_CLIENT_SECRET` | The SP's OAuth **client secret** (from step 1). The only secret. |
| Variable | `DATABRICKS_HOST` | Target workspace URL, e.g. `https://<ws>.cloud.databricks.com` |
| Variable | `DATABRICKS_CLIENT_ID` | The SP's application (client) ID |
| Variable | `CYBER360_CATALOG` | Your UC catalog |
| Variable | `CYBER360_WAREHOUSE_ID` | SQL warehouse id (Genie only) |
| Variable | `CYBER360_OWNER_ROLE` | Lakebase owner role id (see Deploy) |
| Variable | `CYBER360_LAKEBASE_PROJECT` | Lakebase project id (e.g. `cyber360-lakebase`) |

> The Databricks CLI auto-detects `DATABRICKS_HOST` + `DATABRICKS_CLIENT_ID` +
> `DATABRICKS_CLIENT_SECRET` and performs the OAuth M2M token exchange itself —
> the workflows just set these env vars, no login step needed.

Gate `prod` with a **protected GitHub environment** (`Settings → Environments`)
with required reviewers, so promotion to prod needs human approval.

### The self-serve loop (per feature)

1. **Branch off `main`** with a `feature/…` name and push it.
2. **`ci.yml`** runs the gate (ruff, SPA build, migration + bundle validation).
3. **`feature-deploy.yml`** forks a **paired Lakebase branch** off `production`
   (own copy-on-write snapshot of prod data), deploys the app pointed at it, and
   checks the app reaches **RUNNING/ACTIVE**.
4. **Test it in Databricks:** open **Compute → Apps → `cyber360-dashboard`** and
   click the URL. (You pass the app's OAuth front door as a logged-in user; a
   `curl` with a token does *not* — that's why CI checks app *status*, not HTTP.)
5. **Open a PR** → merge promotes to `tst`; a gated dispatch promotes to `prod`.
6. **Close the PR** → `feature-teardown.yml` deletes the paired Lakebase branch.

> The paired-branch flow (fork → deploy → grant inheritance) is verified
> end-to-end. See `SKILL.md §5a` for the design and the
> [lakebase-app-dev-kit](https://github.com/databricks-solutions/lakebase-app-dev-kit)
> as the graduation path.

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
- [ ] **Reader grant:** after `cyber360_grant_reader_role`, KPIs load (HTTP 200); skip it and the metrics API 500s.
- [ ] **Config onboarding:** add a domain in YAML → `/domain/<key>` renders with no code change.
- [ ] Reporting-period (30/60/90d) deltas + trend charts read from the synced aggregates.
- [ ] Preferences + chats persist across sessions (app-owned state tables).

---

## Branch discipline

Never commit to `main`. Develop on a feature branch, and run any Lakebase DDL/DML
against a **branched Lakebase database** (not the shared instance). Open a PR into
`main` and run `/review` (Isaac Review) before pushing. See `SKILL.md` §5.
