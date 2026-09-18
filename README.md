<p align="center">
  <img src="docs/assets/dbx-banner.jpeg" alt="Databricks" width="100%" />
</p>

# CyberUnified Unified Dashboard

A cybersecurity posture dashboard that runs as a Databricks App. It shows KPIs
across security domains (identity, vulnerabilities, and more) on top of your
OCSF data.

**You configure it, you don't code it.** Everything — domains, measures, KPIs,
thresholds, Genie Spaces — lives in **`app/cyber-unified.yaml`**. Adding a domain is a
YAML edit, not a code change.

> New here? Read **[`SKILL.md`](./SKILL.md)** first for the design principles.

---

## Architecture

**The app READS an already-published Unity Catalog metric view. It creates
nothing in your data layer.**

**Data plane — yours, not ours.** You already have a **UC Metric View**; the app
is simply told its **name** (`domains[].metric_view.name`, resolved inside
`${CYBERUNIFIED_CATALOG}.${CYBERUNIFIED_SCHEMA}`). That name may differ per
environment — repointing the app at another workspace is a one-line YAML edit.
The bundle deploys no pipeline, no job, and no DDL against your data, so the app
needs **no privilege on whatever the view is built over** (e.g. a federated
`conn_cyberarch` source catalog).

**App plane (FastAPI + React).** The app queries that metric view natively with
`MEASURE()` on the **SQL Warehouse**, per-user **on-behalf-of** — so Unity Catalog
permissions are enforced for each viewer. The drill-down table SELECTs its
configured columns from the **same** metric view. **Lakebase** (managed Postgres)
serves only the app's own read-write state — three tables (preferences, chats,
sessions) it creates itself at startup.

```
your published UC Metric View ─┐
                               ├─▶ MEASURE() on SQL Warehouse (per-user OBO) ─┐
                (drill-down rows: SELECT from the same view) ─────────────────┤
                                                                              ▼
                                          React SPA ─▶ FastAPI ─▶ MetricViewProvider
                                                              └─ SeedProvider (in-memory
                                                                 synthesis; zero workspace
                                                                 deps, local/demo)
Lakebase (managed Postgres) ──▶ app state only: preferences · chats · sessions
```

One Databricks Asset Bundle (`databricks.yml`) deploys the app, the Lakebase
project, and one **gated, sandbox-only** seed job — nothing else.

---

## Prerequisites

- **Databricks CLI ≥ 0.297** (`databricks --version`) authenticated to the target
  workspace (`databricks auth login`). Older CLIs may hard-error on the newer
  Lakebase resource types this bundle uses (`postgres_projects`, `postgres_branches`,
  `postgres_endpoints`, `postgres_databases`); see the note under **Deploy** about
  validation warnings.
- **Python 3.11+** and **Node 20+** (for local dev / building the SPA).
- Workspace permission to create a Lakebase project and an app.
- **Bring-your-own prerequisites** (the bundle does *not* create these):
  - A **published UC Metric View** — the app reads it, it never builds it. Name it in
    `domains[].metric_view.name`. Every `detail_table` column must exist on that view.
  - The **UC catalog and schema** (`var.catalog` / `var.schema`) that the metric view
    lives in must already exist and be readable by the deploying identity. The bundle
    creates neither.
  - Users need UC read access to that view — see [Access control](#access-control-manage-the-group-not-users).

---

## Deploy

All workspace-specific values (catalog, schema, warehouse id, Lakebase topology,
Genie embed URLs) are **DAB variables** — override them at deploy time, never
hardcode. Defaults live in `databricks.yml`. The metric view is named in
`app/cyber-unified.yaml`, not as a variable.

### Set these first (they are NOT hardcoded to your workspace)

| What | How | Why |
|------|-----|-----|
| **Workspace host** | Deploy from a Databricks **Git folder** (targets that workspace automatically), or set `DATABRICKS_HOST` / use `databricks auth login` / `-p <profile>`. | `workspace.host` is an auth field — the CLI resolves it *before* variables, so it can't be a `${var}` and is intentionally omitted from `databricks.yml`. It resolves from the ambient environment. |
| **`lakebase_owner_role`** | `--var lakebase_owner_role=<your-role-id>` | The Postgres role that OWNS the app database. Lakebase derives it from the **deploying identity's** email (dots → hyphens), e.g. `jane.doe@corp.com` → `jane-doe`. The default (`marcin-jimenez`) is the original author's — **override it for any other deployer.** |
| **`catalog`** (and `schema` if desired) | `--var catalog=<your_catalog>` | Where your metric view lives — a bring-your-own prerequisite (see above). |
| **`warehouse_id`** | `--var warehouse_id=<id>` | Runs the metric-view KPI reads (per-user OBO) and the Genie drawer. |

### Deploy flow

`make deploy <env>` is **validate → deploy → run app**. Nothing is created in the
data layer, so a deploy succeeds or fails on **deployment alone** — a data-layer or
UC-grant problem can no longer fail it.

```bash
make deploy sandbox     # FEVM sandbox
make deploy edp_dev     # Azure EDP DEV, reads the customer's published metric view
```

On a **fresh** workspace use `make setup <env>` instead — it deploys **twice**
(Lakebase provisions the project/app asynchronously, so dependent objects settle on
the second pass), then runs the app. Or drive the CLI directly, substituting your
own `--var` overrides:

```bash
# Assume host comes from a Git folder / DATABRICKS_HOST / active profile.
export VARS="--var catalog=<your_catalog> --var warehouse_id=<id> --var lakebase_owner_role=<your-role-id>"

databricks bundle validate -t databricks_sandbox $VARS
databricks bundle deploy   -t databricks_sandbox $VARS   # on a fresh workspace, run this twice
databricks bundle run cyber_unified_app -t databricks_sandbox $VARS   # start the app (prints the URL)
```

> **Validation warnings are harmless.** `databricks bundle validate` emits
> `unknown field: replace_existing / postgres_databases`
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
4. **Run the same flow** as above — the CLI is preinstalled on Databricks compute,
   so the `databricks bundle …` commands work as-is. `make deploy <env>` works too
   (it needs no npm/node: the built SPA is committed):

   ```bash
   export VARS="--var catalog=<your_catalog> --var warehouse_id=<id> --var lakebase_owner_role=<your-role-id>"
   databricks bundle validate -t databricks_sandbox $VARS
   databricks bundle deploy   -t databricks_sandbox $VARS   # twice on a fresh workspace
   databricks bundle run cyber_unified_app -t databricks_sandbox $VARS   # app live
   ```

5. **Find the running app** under **Compute → Apps → `cyber-unified`** (its
   URL is also printed by the last step).

> After a `git add app/frontend/dist` rebuild or any code change, **Pull** the Git
> folder again before re-running `bundle deploy` so the workspace copy is current.

### Targets

The bundle defines three targets, and the Makefile takes the env as a **positional
word** (`make deploy sandbox`):

| Env word | `databricks.yml` target | What it is |
|---|---|---|
| `sandbox` | `databricks_sandbox` | Default. FEVM sandbox, **synthetic** — the only place the seed / metric-view emulation runs. |
| `edp_dev` | `edp_dev` | Azure EDP DEV, reads the **real** published metric view. |
| `prod` | `prod` | The released app (promoted via `promote.yml`); sets an explicit `workspace.root_path` for `mode: production`. |

**Bring-your-own-data is the DEFAULT.** The app reads the metric view you already
publish — point `domains[].metric_view.name` at it and deploy. Nothing else is
needed, and no synthetic data is ever written to a real target: the
`load_synthetic_data` variable (**default `false`**) gates the seed job, which is a
no-op unless explicitly turned on, and turning it on is a sandbox-only step.

### Sandbox-only utilities (emulating a real workspace)

On the FEVM sandbox there is no customer metric view to read, so two guarded
targets **emulate** one. Neither is a bundle resource, a deploy step, or safe on a
real target:

```bash
make seed sandbox               # write the synthetic gold table (cyber_unified_seed_job, gated)
make sandbox-metricview sandbox # publish a metric view over that gold
```

`make sandbox-metricview` applies `setup/sandbox/phishing_source.sql` +
`setup/sandbox/mv_phishing.sql` from the CLI (via
`setup/sandbox/apply_metricview.py`) and **hard-refuses any non-sandbox target**,
because those files issue `CREATE ... VIEW` DDL. On a real workspace the metric view
already exists and is owned by you — just name it in the config.

---

## Access control (manage the group, not users)

Access is driven by **two bring-your-own Databricks groups** so you manage
**group membership only** — never per-user permissions. Add someone to a group
and their access to every CyberUnified resource follows; remove them and it's gone.

| Group (variable) | Default name | Gets |
|---|---|---|
| `manage_group` | `DPG_CYBER360_MANAGE` | **CAN_MANAGE** on the app + the seed job |
| `user_group` | `DPG_CYBER360_USER` | **CAN_USE** on the app; **CAN_VIEW** on the seed job |

These are **workspace** permissions and are fully **declarative in the bundle** —
each resource (the app, the seed job) carries its own `permissions:` block.
Deploying to another workspace applies the identical model. Override the names per
deploy if your groups differ:

```bash
databricks bundle deploy -t databricks_sandbox \
  --var manage_group=MY_ADMINS --var user_group=MY_USERS
```

**Prerequisites (bring-your-own):**
1. The two groups must **already exist** — Databricks Asset Bundles cannot create
   groups. Create them once (workspace admin) and manage their membership going
   forward.
2. **Data-layer (Unity Catalog) grants are a separate, one-time step** and are
   **not** managed by this bundle. Workspace-object permissions (above) accept
   workspace groups, but UC grant principals must be **account-level groups**, so
   the KPI data grants are left to your team's metastore admin. To let
   `user_group` members query the metric views (reads run per-user, so each user
   needs UC access), grant — once, e.g. via a SQL editor or `databricks grants`:

   ```sql
   GRANT USE CATALOG   ON CATALOG <catalog>              TO `DPG_CYBER360_USER`;
   GRANT USE SCHEMA    ON SCHEMA  <catalog>.<schema>     TO `DPG_CYBER360_USER`;
   GRANT SELECT        ON SCHEMA  <catalog>.<schema>     TO `DPG_CYBER360_USER`;
   -- DPG_CYBER360_MANAGE typically gets ALL PRIVILEGES on the schema:
   GRANT ALL PRIVILEGES ON SCHEMA <catalog>.<schema>     TO `DPG_CYBER360_MANAGE`;
   ```

   Without these grants the app opens for `user_group` members but KPI tiles
   return an access error (the per-user OBO query is denied by Unity Catalog).

   > Users need read on the **metric view** only. Because the app never builds the
   > view, neither the app nor its service principal needs any privilege on whatever
   > the view is built over (e.g. a federated source catalog).

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
- Grant the SP what a deploy needs: workspace access (CAN_USE) and `CAN_MANAGE` on
  the app + bundle resources. (It's the identity CI deploys as.) It needs **no**
  data-layer privilege — the deploy creates nothing in Unity Catalog, and KPI reads
  run per-user OBO.

**2. Configure the repo** (**Settings → Secrets and variables → Actions**):

| Kind | Name | Value |
|------|------|-------|
| **Secret** | `DATABRICKS_CLIENT_SECRET` | The SP's OAuth **client secret** (from step 1). The only secret. |
| Variable | `DATABRICKS_HOST` | Target workspace URL, e.g. `https://<ws>.cloud.databricks.com` |
| Variable | `DATABRICKS_CLIENT_ID` | The SP's application (client) ID |
| Variable | `CYBERUNIFIED_CATALOG` | Your UC catalog |
| Variable | `CYBERUNIFIED_WAREHOUSE_ID` | SQL warehouse id (Genie only) |
| Variable | `CYBERUNIFIED_OWNER_ROLE` | Lakebase owner role id (see Deploy) |
| Variable | `CYBERUNIFIED_LAKEBASE_PROJECT` | Lakebase project id (e.g. `cyber-unified`) |

> The Databricks CLI auto-detects `DATABRICKS_HOST` + `DATABRICKS_CLIENT_ID` +
> `DATABRICKS_CLIENT_SECRET` and performs the OAuth M2M token exchange itself —
> the workflows just set these env vars, no login step needed.

Gate `prod` with a **protected GitHub environment** (`Settings → Environments`)
with required reviewers, so promotion to prod needs human approval.

### The self-serve loop (per feature)

1. **Branch off `main`** with a `feature/…` name and push it.
2. **`ci.yml`** runs the gate (ruff, SPA build, migration + bundle validation).
3. **`feature-deploy.yml`** forks a **paired Lakebase branch** off `production`
   (its own copy-on-write snapshot of prod data + read-write endpoint). It does
   **not** deploy a per-branch app — Databricks Apps are a per-environment
   service, not per-PR previews (see below).
4. **Test against the branch:** point the app at the fork via
   `LAKEBASE_ENDPOINT_NAME` — run the app locally (dev-loop) or use the shared
   **dev** app. The data is isolated; the app instance is shared.
5. **Open a PR** → review + merge to `main`. Promotion to **prod** is a manual,
   gated `workflow_dispatch` (`promote.yml`) against the protected `prod`
   environment.
6. **Close the PR** → `feature-teardown.yml` deletes the paired Lakebase branch.

> **Why no app-per-branch?** Each Databricks App is its own long-running compute
> + URL + per-user OAuth consent — spinning one up per branch is high cost for
> little gain, and Apps have no native per-PR preview primitive. The valuable,
> cheap isolation is the **Lakebase branch** (copy-on-write, fork/drop in
> seconds); the app stays a shared per-environment service (`dev`, then `prod`).

---

## Local development (no workspace needed)

The `SeedProvider` synthesizes the full dashboard in-memory, so you can run
everything locally with zero Databricks dependencies:

```bash
make install        # backend (pip -e) + frontend (npm)
make build          # build the React SPA into app/frontend/dist
make dev            # uvicorn on :8000 with the seed provider
```

Regenerate the bundled demo CSVs (for inspection only — the seeder generates the
same gold in-code):

```bash
make generate-data
```

---

## Onboard a new domain (the headline how-to)

Adding a security domain is a **pure `app/cyber-unified.yaml` edit** — no page, route,
or endpoint code. You point it at a metric view your workspace already publishes,
and the generic `/domain/<key>` page renders it.

1. Add a `domains[]` entry naming the published view:

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
       # The NAME of the metric view your workspace ALREADY publishes, resolved
       # inside ${CYBERUNIFIED_CATALOG}.${CYBERUNIFIED_SCHEMA}. The app reads it
       # and creates nothing. This name may differ per environment.
       name: endpoint_detail_metric_view
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

2. (Optional) add a `detail_table` — its `columns` must exist on that metric view,
   since the drill-down SELECTs them from the same view.
3. (Optional) reference a measure in `top_line_kpis` to add a scorecard tile.
4. `make deploy <env>`.

That's it — nav link, KPI tiles, trend charts, drill-down table, and Genie drawer
all appear with **zero code**.

> **On the sandbox only**, where no published view exists, add a
> `setup/sandbox/mv_<key>.sql` to emulate one locally, then run
> `make seed sandbox` + `make sandbox-metricview sandbox`. That is a dev
> convenience — it is never part of a deploy or of a real environment.

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
| `data_source` | `catalog`, `schema`, `warehouse_id`, `provider` (`seed`\|`metricview`). |
| `lakebase` | Endpoint/database + `state_tables` (app-owned read-write state only). |
| `data_loading` | `load_synthetic` demo-load gate (mirrors the `load_synthetic_data` DAB var). |
| `features` | `genie_enabled`, `soc_view_enabled`, `theme_toggle`, `lineage_popover`. |
| `top_line_kpis` | `{domain, measure, trend, caption}` — executive scorecard tiles. |
| `domains[]` | `key`, `label`, `short`, `icon`, `description`, `genie`, `health`, `metric_view`, `detail_table`, optional `gold_table`. |
| `metric_view` | `name` (**the already-published view — the whole per-env contract**), `comment`, `dimensions[]`, `measures[]`. |
| measure fields | `name`, `label`, `expression`, `comment`, `format` (percent\|count\|days\|hours\|score), `goal` (higher\|lower), `green`/`amber` thresholds, `caption`, optional `fixed_status`, `trend`. |
| `detail_table` | `label`, `order_by`, `page_size`, `columns[]`, `filters[]` — SELECTed from the SAME metric view, so every column must exist on it. |
| `gold_table` | **Optional, LOCAL/sandbox bookkeeping only** — names the synthetic gold table (defaults to `<key>_detail`). Not used by the metric-view read path. |
| `health` | `score_measures[]` (rollup score), `highlights[]` (surfaced tiles). |
| `genie` | `space_id`, `embed_url`, `starters[]`. |

---

## Verification checklist

- [ ] `make validate <env>` → `Validation OK!`
- [ ] `make build` produces `app/frontend/dist/`.
- [ ] `pytest app/tests` passes — including the architecture guard suite
      (`app/tests/test_bundle_architecture.py`, 8 tests) that keeps data-layer
      resources out of the bundle.
- [ ] `make deploy <env>` succeeds on **deployment alone** — it touches nothing in the data layer.
- [ ] **UC grants:** `user_group` members can `SELECT` the named metric view, so KPIs load (HTTP 200).
- [ ] **Config onboarding:** add a domain in YAML → `/domain/<key>` renders with no code change.
- [ ] Reporting-period (30/60/90d) deltas + trend charts read from the metric view.
- [ ] Drill-down rows load — every `detail_table` column exists on the metric view.
- [ ] Preferences + chats persist across sessions (app-owned state tables).

---

## Branch discipline

Never commit to `main`. Develop on a feature branch, and run any Lakebase DDL/DML
against a **branched Lakebase database** (not the shared instance). Open a PR into
`main` and run `/review` (Isaac Review) before pushing. See `SKILL.md` §5.
