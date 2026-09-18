"""Lightweight, dependency-free config reader for the Lakeflow pipeline.

The FastAPI app parses ``cyber-unified.yaml`` with Pydantic (``app/core/config.py``).
The pipeline must not import the app package, so this module re-reads the same
YAML with only PyYAML and resolves the two placeholders the pipeline cares
about -- ``${CYBERUNIFIED_CATALOG}`` / ``${CYBERUNIFIED_SCHEMA}`` -- from the pipeline's
Spark configuration rather than the environment.

The pipeline reads the SAME ``cyber-unified.yaml`` the app ships, so domains,
metric-view definitions and measure expressions stay defined exactly once.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

# Candidate locations for cyber-unified.yaml relative to this file, covering both
# the local repo layout and the DAB-synced workspace files layout.
_CANDIDATES = [
    "cyber-unified.yaml",
    "../cyber-unified.yaml",
    "../app/cyber-unified.yaml",
    "../../app/cyber-unified.yaml",
    "app/cyber-unified.yaml",
]


def _find_config(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    here = Path(__file__).resolve()
    # Search the explicit candidates first (fast path).
    for rel in _CANDIDATES:
        p = (here.parent / rel).resolve()
        if p.exists():
            return p
    # Fall back to walking upward for any cyber-unified.yaml.
    for parent in here.parents:
        hit = parent / "app" / "cyber-unified.yaml"
        if hit.exists():
            return hit
        hit = parent / "cyber-unified.yaml"
        if hit.exists():
            return hit
    raise FileNotFoundError(
        "Could not locate cyber-unified.yaml. Set CYBERUNIFIED_CONFIG_PATH or place the "
        "file alongside the pipeline sources."
    )


def _resolve(obj: Any, overrides: dict[str, str]) -> Any:
    if isinstance(obj, str):
        def repl(m: re.Match) -> str:
            var, default = m.group(1), m.group(2)
            val = overrides.get(var) or os.environ.get(var, "")
            if not val and default is not None:
                return default
            return val
        return _PLACEHOLDER_RE.sub(repl, obj)
    if isinstance(obj, dict):
        return {k: _resolve(v, overrides) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(v, overrides) for v in obj]
    return obj


class PipelineConfig:
    """Parsed, placeholder-resolved view of cyber-unified.yaml for the pipeline."""

    def __init__(self, raw: dict, catalog: str, schema: str):
        self.catalog = catalog
        self.schema = schema
        self._raw = raw

    @property
    def domains(self) -> list[dict]:
        return self._raw.get("domains", [])

    def gold_table_name(self, domain: dict) -> str:
        """Unqualified name of the SYNTHETIC gold table to seed for this domain.

        Sandbox-only bookkeeping: `gold_table` when set, else `<key>_detail`. This
        used to derive from metric_view.source_table, which was removed -- the app
        reads an already-published metric view BY NAME and never knows its source.
        """
        return domain.get("gold_table") or f"{domain['key']}_detail"

    def fq(self, name: str) -> str:
        """Fully-qualify an unqualified table/view name into catalog.schema."""
        return f"{self.catalog}.{self.schema}.{name}"


def load_pipeline_config(
    *,
    catalog: str,
    schema: str,
    path: str | None = None,
) -> PipelineConfig:
    cfg_path = _find_config(path or os.environ.get("CYBERUNIFIED_CONFIG_PATH"))
    with open(cfg_path) as f:
        raw = yaml.safe_load(f)
    overrides = {"CYBERUNIFIED_CATALOG": catalog, "CYBERUNIFIED_SCHEMA": schema}
    resolved = _resolve(raw, overrides)
    return PipelineConfig(resolved, catalog, schema)
