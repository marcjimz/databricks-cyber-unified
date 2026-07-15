.PHONY: help install install-backend install-frontend build build-frontend \
       dev lint lint-backend lint-frontend clean \
       generate-data \
       validate deploy deploy-dev deploy-prod

PYTHON   := python3
NPM      := npm
DAB      := databricks bundle
APP_DIR  := app
FE_DIR   := $(APP_DIR)/frontend
FE_DIST  := $(FE_DIR)/dist

# ──────────────────────────────────────────────
# Development
# ──────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend ## Install all dependencies

install-backend: ## Install Python dependencies
	cd $(APP_DIR) && pip install -e ".[dev]"

install-frontend: ## Install Node dependencies
	cd $(FE_DIR) && $(NPM) install

build: build-frontend ## Build everything for deployment

build-frontend: ## Build React SPA to dist/
	cd $(FE_DIR) && $(NPM) run build

dev: build ## Run FastAPI locally with built frontend (seed provider)
	cd $(APP_DIR) && uvicorn main:app --reload --host 0.0.0.0 --port 8000

lint: lint-backend lint-frontend ## Lint everything

lint-backend: ## Lint Python with ruff
	cd $(APP_DIR) && ruff check .

lint-frontend: ## Lint TypeScript
	cd $(FE_DIR) && $(NPM) run lint

clean: ## Remove build artifacts
	rm -rf $(FE_DIST) $(APP_DIR)/__pycache__ $(APP_DIR)/**/__pycache__
	find $(APP_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ──────────────────────────────────────────────
# Data Setup
# ──────────────────────────────────────────────
# NOTE: schema/tables/metric-views/aggregates are built by the config-driven
# Lakeflow pipeline (pipelines/) on `bundle deploy` — there are no imperative
# setup scripts. This target only (re)generates the bundled demo CSVs; the
# pipeline generates the same gold in-code, so this is for local inspection only.

generate-data: ## (Re)generate the bundled synthetic OCSF demo CSVs into data/
	$(PYTHON) setup/generate_csvs.py

# ──────────────────────────────────────────────
# DAB Deployment
# ──────────────────────────────────────────────

validate: ## Validate DAB configuration
	$(DAB) validate

deploy: build validate ## Build and deploy to default target
	$(DAB) deploy

deploy-dev: build ## Build and deploy to dev target
	$(DAB) deploy -t dev

deploy-prod: build ## Build and deploy to production target
	$(DAB) deploy -t prod
