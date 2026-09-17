# Cyber360 — Databricks Asset Bundle deploy helpers.
#
# Mirrors the bluebird Makefile idiom: the env is a POSITIONAL word, e.g.
#   make deploy sandbox    # validate -> deploy -> data-plane job -> run app, on databricks_sandbox
#   make deploy edp_dev
#   make deploy prod
#
# Individual steps (same positional env):
#   make validate sandbox    # databricks bundle validate -t databricks_sandbox
#   make data-plane sandbox  # run cyber360_data_plane (pipeline gold + phishing metric view)
#   make app sandbox         # deploy + run the app (cyber360_app)
#
# `make deploy sandbox` = exactly:
#   databricks bundle validate -t databricks_sandbox
#   databricks bundle deploy   -t databricks_sandbox
#   databricks bundle run      -t databricks_sandbox cyber360_data_plane
#   databricks bundle run      -t databricks_sandbox cyber360_app
#
# `make setup <env>` = FIRST-TIME bootstrap for a NEW workspace/target: deploy
# TWICE (a fresh deploy often needs a second pass — Lakebase provisions the
# project/app asynchronously, so objects that depend on them settle on the 2nd
# pass), then run the data-plane job + app.
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

# Full resource keys (a bare prefix like `cyber360_` fails with "resource not found").
DATA_PLANE_JOB := cyber360_data_plane
APP_KEY        := cyber360_app

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
        guard-target setup deploy release validate data-plane app $(ENVS)

# ──────────────────────────────────────────────
# Development (local, no workspace)
# ──────────────────────────────────────────────

help: ## Show this help
	@echo "Cyber360 — usage:"
	@echo "  Local dev:"
	@echo "    make install            install backend (.[dev], incl. duckdb) + frontend deps"
	@echo "    make build              build the React SPA -> app/frontend/dist"
	@echo "    make dev                run FastAPI locally with the seed provider (:8000)"
	@echo "    make lint               ruff + tsc/eslint"
	@echo "    make generate-data      (re)generate the bundled synthetic CSVs into data/"
	@echo "  Deploy (positional env: sandbox | edp_dev | prod):"
	@echo "    make deploy <env>       validate -> deploy -> data-plane job -> run app (NO frontend build)"
	@echo "    make setup <env>        FIRST-TIME: deploy x2 -> data-plane -> app"
	@echo "    make release <env>      build the SPA THEN deploy (use when the UI changed; needs npm)"
	@echo "    make validate <env>     bundle validate only"
	@echo "    make data-plane <env>   run $(DATA_PLANE_JOB) (gold + phishing metric view)"
	@echo "    make app <env>          deploy + run the app ($(APP_KEY))"

install: install-backend install-frontend ## Install all dependencies

install-backend: ## Install Python dependencies (incl. dev: duckdb seed engine)
	cd $(APP_DIR) && pip install -e ".[dev]"

install-frontend: ## Install Node dependencies
	cd $(FE_DIR) && $(NPM) install

build: build-frontend ## Build everything for deployment

build-frontend: ## Build React SPA to dist/
	cd $(FE_DIR) && $(NPM) run build

dev: build ## Run FastAPI locally with built frontend (seed provider)
	cd $(APP_DIR) && CYBER360_PROVIDER=seed uvicorn main:app --reload --host 0.0.0.0 --port 8000

lint: lint-backend lint-frontend ## Lint everything

lint-backend: ## Lint Python with ruff
	cd $(APP_DIR) && ruff check .

lint-frontend: ## Lint TypeScript
	cd $(FE_DIR) && $(NPM) run lint

clean: ## Remove build artifacts
	rm -rf $(FE_DIST) $(APP_DIR)/__pycache__ $(APP_DIR)/**/__pycache__
	find $(APP_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# NOTE: schema/tables/metric-views are built by the config-driven Lakeflow
# pipeline + data-plane job on deploy — there are no imperative setup scripts.
# This only (re)generates the bundled synthetic CSVs (the pipeline generates the
# same gold in-code), for local inspection.
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

# Full deploy: validate -> deploy -> data-plane (gold + metric view) -> run app.
# NOTE: deploy does NOT build the frontend. The built SPA (app/frontend/dist) is
# COMMITTED and `bundle deploy` ships it as-is, so deploy needs no npm/node -- it
# runs from a Databricks workspace terminal or CI unchanged. Rebuild the SPA
# explicitly with `make build` (or `make release <env>`) when the UI changed.
deploy: guard-target
	databricks bundle validate -t $(TARGET) $(PFLAG)
	databricks bundle deploy   -t $(TARGET) $(PFLAG)
	databricks bundle run      -t $(TARGET) $(PFLAG) $(DATA_PLANE_JOB)
	databricks bundle run      -t $(TARGET) $(PFLAG) $(APP_KEY)

# FIRST-TIME bootstrap for a fresh workspace: deploy twice (the 1st pass creates
# the Lakebase project/app; the 2nd settles resources that depend on them), then
# run the data-plane job + app. Like `deploy`, it does NOT build the frontend.
setup: guard-target
	databricks bundle validate -t $(TARGET) $(PFLAG)
	databricks bundle deploy   -t $(TARGET) $(PFLAG) || true   # 1st pass: expect partial on a fresh workspace
	databricks bundle deploy   -t $(TARGET) $(PFLAG)           # 2nd pass: must succeed
	databricks bundle run      -t $(TARGET) $(PFLAG) $(DATA_PLANE_JOB)
	databricks bundle run      -t $(TARGET) $(PFLAG) $(APP_KEY)
	@echo "setup complete for $(TARGET)."

# Rebuild the SPA THEN deploy -- use from a machine with npm/node when the UI
# changed and dist/ needs regenerating. Keeps `deploy` itself build-free.
release: build
	$(MAKE) deploy $(ENV)

validate: guard-target ## bundle validate only
	databricks bundle validate -t $(TARGET) $(PFLAG)

data-plane: guard-target ## run the data-plane job (pipeline gold + phishing metric view)
	databricks bundle run -t $(TARGET) $(PFLAG) $(DATA_PLANE_JOB)

app: guard-target ## deploy + (re)start the app
	databricks bundle deploy -t $(TARGET) $(PFLAG)
	databricks bundle run    -t $(TARGET) $(PFLAG) $(APP_KEY)

# Env words are inert goals (consumed by ENV/TARGET above) so `make deploy sandbox`
# doesn't try to build a target literally named `sandbox`.
$(ENVS):
	@:
