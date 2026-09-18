"""Durable enforcement of the bundle's architectural principles.

These are not unit tests of behaviour -- they are guards that fail when a future
change violates a rule we decided deliberately. The rules exist because breaking
them produced real, hard-to-diagnose deploy failures on the customer workspace.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parent.parent.parent
BUNDLE = REPO / "databricks.yml"


@pytest.fixture(scope="module")
def raw() -> str:
    return BUNDLE.read_text()


@pytest.fixture(scope="module")
def bundle(raw: str) -> dict:
    return yaml.safe_load(raw)


def test_no_pipeline_resource(bundle: dict) -> None:
    """Synthetic data generation must NEVER be a deployed bundle resource.

    A `pipelines:` resource deploys to EVERY target, including customer
    workspaces that already have real tables and schemas. With
    load_synthetic_data=false it also defined zero tables and failed graph
    analysis outright ("Task build_gold failed"). Seeding belongs in the gated
    seed job (scripts/seed_synthetic_gold.py), run explicitly on the sandbox.
    """
    assert "pipelines" not in bundle["resources"], (
        "A `pipelines:` resource was re-added. Synthetic gold is a DEV AID, not "
        "an app resource -- it must not deploy to customer workspaces. Use the "
        "gated cyber_unified_seed_job instead."
    )


def test_bundle_creates_nothing_in_the_data_layer(bundle: dict) -> None:
    """The bundle must not run DDL. We standardize on reading an EXISTING metric view.

    The app is handed `domains[].metric_view.name` and queries it. Anything that
    CREATEs in the data layer breaks on a real target: the old data-plane job ran
    `CREATE OR REPLACE VIEW phishing_source` (needs USE CATALOG on the customer's
    federated source -> denied) and then re-published a metric view that already
    existed. Generating a metric view is a SANDBOX UTILITY (setup/sandbox/), never
    a bundle resource.
    """
    jobs = bundle["resources"].get("jobs", {})
    assert "cyber_unified_data_plane" not in jobs, (
        "the data-plane job is back. The app reads an already-published metric "
        "view; publishing one is a sandbox utility (make sandbox-metricview)."
    )
    for name, job in jobs.items():
        for task in job.get("tasks", []):
            assert "sql_task" not in task, (
                f"job {name!r} task {task['task_key']!r} runs a sql_task. The "
                "bundle must not issue DDL against a customer's data layer."
            )
            assert "pipeline_task" not in task, (
                f"job {name!r} task {task['task_key']!r} runs a pipeline."
            )
        # No dangling intra-job dependencies.
        keys = [t["task_key"] for t in job.get("tasks", [])]
        for task in job.get("tasks", []):
            for dep in task.get("depends_on", []):
                assert dep["task_key"] in keys, (
                    f"job {name!r} task {task['task_key']!r} depends on "
                    f"{dep['task_key']!r}, which does not exist."
                )


def test_metric_view_is_referenced_by_name_only() -> None:
    """The app config must name an existing metric view, not describe how to build one.

    `source_table` is what made the app think it owned the underlying data. The
    per-target contract is a NAME, which may differ per environment.
    """
    cfg = yaml.safe_load((REPO / "app" / "cyber-unified.yaml").read_text())
    for domain in cfg.get("domains", []):
        mv = domain.get("metric_view", {})
        assert mv.get("name"), f"domain {domain.get('key')!r} has no metric_view.name"
        assert "source_table" not in mv, (
            f"domain {domain.get('key')!r} reintroduced metric_view.source_table. "
            "The app reads a published metric view BY NAME and must not know or "
            "depend on what it is built over."
        )


def test_ddl_lives_only_in_the_sandbox_utility_dir() -> None:
    """CREATE VIEW SQL may exist only under setup/sandbox/ (a dev utility)."""
    offenders = []
    for path in REPO.rglob("*.sql"):
        rel = path.relative_to(REPO)
        parts = rel.parts
        if parts[0] in {"node_modules", ".git"} or "node_modules" in parts:
            continue
        # app/migrations/** is the app's OWN Lakebase state schema -- allowed.
        if parts[:2] == ("app", "migrations"):
            continue
        if parts[:2] == ("setup", "sandbox"):
            continue
        if re.search(r"\bCREATE\s+(OR\s+REPLACE\s+)?VIEW\b", path.read_text(), re.I):
            offenders.append(str(rel))
    assert not offenders, (
        f"view DDL outside setup/sandbox/: {offenders}. Publishing views is a "
        "sandbox utility, not part of the deployed application."
    )


def test_seed_is_gated_and_defaults_off(bundle: dict) -> None:
    """The seed gate must default FALSE so real-data targets never seed."""
    default = bundle["variables"]["load_synthetic_data"]["default"]
    assert default is False, (
        f"load_synthetic_data defaults to {default!r}; it MUST default False so "
        "a real-data target cannot seed over the customer's tables."
    )

    seed = bundle["resources"]["jobs"]["cyber_unified_seed_job"]
    params = seed["tasks"][0]["spark_python_task"]["parameters"]
    assert any("--load_synthetic_data=${var.load_synthetic_data}" == p for p in params), (
        "the seed job must pass the gate through to the script, so the script "
        "can no-op when it is not explicitly true."
    )


def test_seed_is_not_part_of_deploy() -> None:
    """`make deploy` must never seed -- seeding is an explicit, separate step."""
    makefile = (REPO / "Makefile").read_text()
    # Isolate the deploy recipe: from `deploy:` to the next top-level target.
    match = re.search(r"^deploy:.*?(?=^\S)", makefile, re.M | re.S)
    assert match, "could not locate the `deploy:` recipe in the Makefile"
    assert "load_synthetic_data" not in match.group(0), (
        "`make deploy` references the seed gate. Deploy must not seed; use the "
        "separate `make seed <env>` target."
    )


def test_no_dangling_resource_or_var_references(raw: str, bundle: dict) -> None:
    """Every ${resources.*} / ${var.*} reference must resolve."""
    resources = bundle["resources"]
    refs = set(re.findall(r"\$\{resources\.([a-z_]+)\.([a-z_0-9]+)", raw))
    dangling = [f"{t}.{k}" for t, k in refs if k not in resources.get(t, {})]
    assert not dangling, f"dangling ${{resources.*}} references: {dangling}"

    declared = set(bundle.get("variables", {}))
    used = set(re.findall(r"\$\{var\.([a-z_0-9]+)\}", raw))
    assert not (used - declared), f"undeclared variables: {sorted(used - declared)}"


def test_real_data_targets_do_not_enable_seeding(bundle: dict) -> None:
    """No real-data target may turn the seed gate on."""
    for name, target in bundle.get("targets", {}).items():
        if name == "databricks_sandbox":
            continue
        value = (target.get("variables") or {}).get("load_synthetic_data")
        assert value in (None, False), (
            f"target {name!r} sets load_synthetic_data={value!r}. Only the "
            "sandbox may seed; real-data targets must leave it off."
        )


def test_sandbox_metric_view_mirrors_the_app_config() -> None:
    """The sandbox's emulated view must expose exactly what the app config names.

    The sandbox exists to MIMIC the customer's published view. If the two drift,
    the sandbox passes while a real target fails at runtime -- which is how a `day`
    dimension that only existed in the sandbox reached production and produced
    `UNRESOLVED_COLUMN ... name 'day' cannot be resolved`.
    """
    sql = (REPO / "setup" / "sandbox" / "mv_phishing.sql").read_text()
    body = sql.split("$$")[1]
    view = yaml.safe_load(body)

    cfg = yaml.safe_load((REPO / "app" / "cyber-unified.yaml").read_text())
    mv_cfg = cfg["domains"][0]["metric_view"]

    view_measures = sorted(m["name"] for m in view["measures"])
    cfg_measures = sorted(m["name"] for m in mv_cfg["measures"])
    assert view_measures == cfg_measures, (
        f"sandbox view measures {view_measures} != app config {cfg_measures}. The "
        "app issues MEASURE(`name`), so these must match exactly."
    )

    # A configured time_dimension must actually exist as a view dimension.
    time_dim = (mv_cfg.get("time_dimension") or "").strip()
    view_dims = [d.get("name") for d in view["dimensions"] if d.get("name")]
    if time_dim:
        assert time_dim in view_dims, (
            f"config time_dimension {time_dim!r} is not a dimension of the sandbox "
            f"view {view_dims}. Windowing on it would fail with UNRESOLVED_COLUMN."
        )

    # Rates must stay in the view's own units; unit conversion belongs in config
    # (`scale`), in ONE place, so sandbox and real targets agree.
    for measure in view["measures"]:
        expr = measure["expr"]
        assert "* 100" not in expr and "*100" not in expr, (
            f"sandbox measure {measure['name']!r} scales in SQL. Scale in config "
            "instead, so the same app config works against the customer's view."
        )


def test_sandbox_sql_avoids_the_statement_splitter_footguns() -> None:
    """The dollar-quoted metric-view body must contain no semicolon.

    The SQL file runner splits statements on `;`; one inside the `$$` body
    truncates the DDL and fails the parse.
    """
    for name in ("mv_phishing.sql", "phishing_source.sql"):
        text = (REPO / "setup" / "sandbox" / name).read_text()
        parts = text.split("$$")
        if len(parts) < 3:
            continue
        # parts[1] is the quoted body; the trailing `;` terminator lives in
        # parts[2] and is legitimate.
        body = parts[1]
        assert ";" not in body, f"{name}: semicolon inside the $$ body breaks parsing"


def test_no_protected_lakebase_branch_or_endpoint_resource(bundle: dict) -> None:
    """Never declare the IMPLICIT Lakebase production branch / primary endpoint.

    A `postgres_projects` resource already creates both. Declaring the branch makes
    DAB delete-and-recreate it on any identity-field change, and the API refuses --
    `cannot delete protected branch (400)` -- which then cascades "dependency
    failed" onto the endpoint, the database and the app, breaking the whole deploy.
    Compute bounds belong in the project's `default_endpoint_settings`.
    """
    resources = bundle["resources"]
    for kind in ("postgres_branches", "postgres_endpoints"):
        assert kind not in resources, (
            f"`{kind}` is declared again. The production branch is PROTECTED and the "
            "primary endpoint is implicit -- configure them via "
            "postgres_projects.default_endpoint_settings instead."
        )


def test_lakebase_paths_do_not_depend_on_resource_outputs(raw: str) -> None:
    """Lakebase paths must be built from variables, not ${resources.postgres_*}.

    Referencing a postgres resource's output re-creates the dependency edge whose
    failure cascaded across every Lakebase resource and the app.
    """
    refs = re.findall(r"\$\{resources\.(postgres_[a-z_]+)\.([a-z_0-9]+)\.", raw)
    assert not refs, (
        f"Lakebase paths reference resource outputs {refs}. Build them from "
        "${var.lakebase_project} / ${var.lakebase_branch} instead."
    )
