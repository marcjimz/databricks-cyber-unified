"""Provider factory -- returns the correct DataProvider based on config."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Cyber360Config
    from providers.base import DataProvider


def get_provider(config: "Cyber360Config", token: str = "") -> "DataProvider":
    """Return the appropriate DataProvider based on config.data_source.provider."""
    if config.data_source.provider == "metricview":
        from providers.metricview import MetricViewProvider
        return MetricViewProvider(config, token)
    else:
        from providers.seed import SeedProvider
        return SeedProvider(config)
