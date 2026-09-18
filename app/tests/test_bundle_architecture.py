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


def test_data_plane_builds_no_data(bundle: dict) -> None:
    """The data-plane job must only build VIEWS, so it is target-agnostic.

    Real-data targets have their own gold tables. If a data-building task is
    chained in front of the metric views, those targets cannot run the data plane
    at all -- the failure cascades and the app gets no semantic layer.
    """
    tasks = bundle["resources"]["jobs"]["cyber_unified_data_plane"]["tasks"]
    keys = [t["task_key"] for t in tasks]

    assert "build_gold" not in keys, (
        f"data-plane job builds data again (tasks={keys}). It must only apply "
        "the metric-view SQL."
    )
    for task in tasks:
        assert "pipeline_task" not in task, (
            f"task {task['task_key']!r} runs a pipeline; the data plane must be "
            "sql_task-only so it runs identically on a customer workspace."
        )
        for dep in task.get("depends_on", []):
            assert dep["task_key"] in keys, (
                f"task {task['task_key']!r} depends on {dep['task_key']!r}, "
                "which no longer exists -- dangling dependency."
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
