# CyberUnified — Databricks Asset Bundle deploy helpers.
#
# Mirrors the bluebird Makefile idiom: the env is a POSITIONAL word, e.g.
#   make deploy sandbox    # validate -> deploy -> run app, on databricks_sandbox
#   make deploy edp_dev
#   make deploy prod
#
# Individual steps (same positional env):
#   make validate sandbox    # databricks bundle validate -t databricks_sandbox
#   make app sandbox         # deploy + run the app (cyber_unified_app)
#
# SANDBOX-ONLY utilities (emulate what a real workspace already provides; NOT
# part of deploy, and never run against a real target):
#   make seed sandbox              # write the synthetic gold table (gated)
#   make sandbox-metricview sandbox # publish a metric view over that gold
#
# `make deploy sandbox` = exactly:
#   databricks bundle validate -t databricks_sandbox
#   databricks bundle deploy   -t databricks_sandbox
#   databricks bundle run      -t databricks_sandbox cyber_unified_app
#
# `make setup <env>` = FIRST-TIME bootstrap for a NEW workspace/target: deploy
# TWICE (a fresh deploy often needs a second pass — Lakebase provisions the
# project/app asynchronously, so objects that depend on them settle on the 2nd
# pass), then run the app.
#
# Env words are SHORT aliases mapped to the databricks.yml `targets:`
#   sandbox -> databricks_sandbox   (FEVM, SYNTHETIC phishing data)
#   edp_dev -> edp_dev              (Azure EDP DEV, REAL CyberArk source)
#   prod    -> prod
# (the full target names also work as the env word.)

PYTHON   := python3
NPM      := npm
APP_DIR  := app
FE_DIR   := $(APP_DIR)/frontend
FE_DIST  := $(FE_DIR)/dist

# Full resource keys (a bare prefix like `cyber_unified_` fails with "resource not found").
APP_KEY        := cyber_unified_app
SEED_JOB       := cyber_unified_seed_job

# Env words treated as a positional target (kept in sync with databricks.yml
# `targets:`). Short aliases + the canonical names are both accepted.
ENVS := sandbox edp_dev prod databricks_sandbox
ENV  := $(filter $(ENVS),$(MAKECMDGOALS))

# Map the short alias to the real databricks.yml target name.
TARGET := $(ENV)
ifeq ($(ENV),sandbox)
  TARGET := databricks_sandbox
endif

# Auth resolves from the ENVIRONMENT by default (like bluebird): ambient auth when
# deploying from inside a Databricks workspace, or your active CLI profile / the
# DATABRICKS_* env vars on a laptop. No profile is hardcoded -- forcing `-p <name>`
# breaks the in-workspace path (there is no ~/.databrickscfg profile there).
#
# Only pass a profile when you actually need one -- e.g. a laptop where several
# profiles share a host and the CLI can't disambiguate ("multiple profiles
# matched"). Do it per-invocation:
#   make deploy edp_dev PROFILE=edp_dev
#   make deploy sandbox PROFILE=fe-vm-real-time-mode-demo
PROFILE ?=
PFLAG := $(if $(PROFILE),-p $(PROFILE),)

.PHONY: help install install-backend install-frontend build build-frontend \
        dev lint lint-backend lint-frontend clean generate-data \
        guard-target setup deploy release validate app seed sandbox-metricview $(ENVS)

# ──────────────────────────────────────────────
# Development (local, no workspace)
# ──────────────────────────────────────────────

help: ## Show this help
	@echo "CyberUnified — usage:"
	@echo "  Local dev:"
	@echo "    make install            install backend (.[dev], incl. duckdb) + frontend deps"
	@echo "    make build              build the React SPA -> app/frontend/dist"
	@echo "    make dev                run FastAPI locally with the seed provider (:8000)"
	@echo "    make lint               ruff + tsc/eslint"
	@echo "    make generate-data      (re)generate the bundled synthetic CSVs into data/"
	@echo "  Deploy (positional env: sandbox | edp_dev | prod):"
	@echo "    make deploy <env>       validate -> deploy -> run app (NO frontend build)"
	@echo "    make setup <env>        FIRST-TIME: deploy x2 -> app"
	@echo "    make release <env>      build the SPA THEN deploy (use when the UI changed; needs npm)"
	@echo "    make validate <env>     bundle validate only"
	@echo "    make app <env>          deploy + run the app ($(APP_KEY))"
	@echo "  Sandbox-only utilities (emulate a real workspace; NOT part of deploy):"
	@echo "    make seed sandbox            write the synthetic gold table ($(SEED_JOB), gated)"
	@echo "    make sandbox-metricview sandbox  publish a metric view over that gold"

install: install-backend install-frontend ## Install all dependencies

install-backend: ## Install Python dependencies (incl. dev: duckdb seed engine)
	cd $(APP_DIR) && pip install -e ".[dev]"

install-frontend: ## Install Node dependencies
	cd $(FE_DIR) && $(NPM) install

build: build-frontend ## Build everything for deployment

build-frontend: ## Build React SPA to dist/
	cd $(FE_DIR) && $(NPM) run build

dev: build ## Run FastAPI locally with built frontend (seed provider)
	cd $(APP_DIR) && CYBERUNIFIED_PROVIDER=seed uvicorn main:app --reload --host 0.0.0.0 --port 8000

lint: lint-backend lint-frontend ## Lint everything

lint-backend: ## Lint Python with ruff
	cd $(APP_DIR) && ruff check .

lint-frontend: ## Lint TypeScript
	cd $(FE_DIR) && $(NPM) run lint

clean: ## Remove build artifacts
	rm -rf $(FE_DIST) $(APP_DIR)/__pycache__ $(APP_DIR)/**/__pycache__
	find $(APP_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# NOTE: the app READS an already-published UC metric view — the bundle builds no
# schema, table, or view. On the sandbox, `make seed` + `make sandbox-metricview`
# emulate what a real workspace already has. This only (re)generates the bundled
# synthetic CSVs (the seeder generates the same gold in-code), for local inspection.
generate-data: ## (Re)generate the bundled synthetic phishing CSV into data/
	$(PYTHON) setup/generate_csvs.py

# ──────────────────────────────────────────────
# DAB Deployment (positional env word)
# ──────────────────────────────────────────────

# Fail clearly if no (or an unknown/ambiguous) env was given.
guard-target:
	@if [ -z "$(TARGET)" ]; then \
	  echo "error: specify a target env, e.g. 'make deploy sandbox'"; \
	  echo "       valid envs: $(ENVS)"; exit 2; fi
	@if [ $(words $(ENV)) -gt 1 ]; then \
	  echo "error: pick ONE env, got: $(ENV)"; exit 2; fi

# Full deploy: validate -> deploy -> run app. NOTHING is created in the data
# layer: the app reads an already-published metric view, so deploy succeeds or
# fails on DEPLOYMENT alone (a data-layer/grant problem can no longer fail it).
# NOTE: deploy does NOT build the frontend. The built SPA (app/frontend/dist) is
# COMMITTED and `bundle deploy` ships it as-is, so deploy needs no npm/node -- it
# runs from a Databricks workspace terminal or CI unchanged. Rebuild the SPA
# explicitly with `make build` (or `make release <env>`) when the UI changed.
deploy: guard-target
	databricks bundle validate -t $(TARGET) $(PFLAG)
	databricks bundle deploy   -t $(TARGET) $(PFLAG)
	databricks bundle run      -t $(TARGET) $(PFLAG) $(APP_KEY)

# FIRST-TIME bootstrap for a fresh workspace: deploy twice (the 1st pass creates
# the Lakebase project/app; the 2nd settles resources that depend on them), then
# run the app. Like `deploy`, it does NOT build the frontend.
setup: guard-target
	databricks bundle validate -t $(TARGET) $(PFLAG)
	databricks bundle deploy   -t $(TARGET) $(PFLAG) || true   # 1st pass: expect partial on a fresh workspace
	databricks bundle deploy   -t $(TARGET) $(PFLAG)           # 2nd pass: must succeed
	databricks bundle run      -t $(TARGET) $(PFLAG) $(APP_KEY)
	@echo "setup complete for $(TARGET)."

# Rebuild the SPA THEN deploy -- use from a machine with npm/node when the UI
# changed and dist/ needs regenerating. Keeps `deploy` itself build-free.
release: build
	$(MAKE) deploy $(ENV)

validate: guard-target ## bundle validate only
	databricks bundle validate -t $(TARGET) $(PFLAG)

app: guard-target ## deploy + (re)start the app
	databricks bundle deploy -t $(TARGET) $(PFLAG)
	databricks bundle run    -t $(TARGET) $(PFLAG) $(APP_KEY)

# Synthetic-gold seed -- SANDBOX ONLY, and deliberately NOT part of `deploy`
# (bluebird `make seed` idiom). Real-data targets (edp_dev/prod) have their own
# tables and must never seed; load_synthetic_data defaults FALSE, so the job is a
# no-op unless it is turned on right here. The flag is passed to BOTH deploy and
# run because the parameter is baked into the job definition at deploy time.
seed: guard-target ## SANDBOX: write the synthetic gold table (gated on load_synthetic_data)
	databricks bundle deploy -t $(TARGET) $(PFLAG) --var="load_synthetic_data=true"
	databricks bundle run    -t $(TARGET) $(PFLAG) --var="load_synthetic_data=true" $(SEED_JOB)

# Publish a metric view over the seeded synthetic gold -- SANDBOX UTILITY ONLY.
# On a real target the metric view ALREADY EXISTS and is owned by the customer;
# the app is simply told its name (domains[].metric_view.name). This target only
# EMULATES that on the sandbox so the same config resolves locally. It is NOT a
# bundle resource and NOT a deploy step -- it applies setup/sandbox/*.sql straight
# from the CLI against the warehouse.
#
# Guarded: refuses to run against anything but the sandbox, because it issues
# CREATE OR REPLACE VIEW / CREATE VIEW WITH METRICS.
sandbox-metricview: guard-target ## SANDBOX ONLY: publish a metric view over the seeded gold
	@if [ "$(TARGET)" != "databricks_sandbox" ]; then \
	  echo "error: sandbox-metricview is a SANDBOX-ONLY utility (got target '$(TARGET)')."; \
	  echo "       Real targets already publish their own metric view -- point"; \
	  echo "       domains[].metric_view.name at it instead."; exit 2; fi
	$(PYTHON) setup/sandbox/apply_metricview.py --target $(TARGET) \
	  $(if $(PROFILE),--profile $(PROFILE),)

# Env words are inert goals (consumed by ENV/TARGET above) so `make deploy sandbox`
# doesn't try to build a target literally named `sandbox`.
$(ENVS):
	@:
