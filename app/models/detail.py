"""Generic, config-driven drill-down table models.

Replaces the per-domain AccountRow/FindingRow models. A domain's drill-down
table is defined entirely by its `detail_table:` config block; the rows are
returned as a list of column descriptors + opaque row dicts, so the SAME
endpoint and frontend component serve any domain with zero code changes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DetailColumn(BaseModel):
    """A column descriptor echoed back to the frontend so it can render headers
    + apply per-column formatting without knowing the domain."""
    field: str
    label: str
    format: str = "text"


class DetailRowsResponse(BaseModel):
    """A page of drill-down rows. `columns` mirrors the domain's configured
    detail_table columns; `rows` are field->value dicts (values as returned by
    the query, coerced to JSON-safe scalars)."""
    columns: list[DetailColumn]
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class DetailQuery(BaseModel):
    """Query params for the generic drill-down endpoint. `filter_key` selects
    one of the domain's configured filters (its trusted WHERE fragment);
    pagination is standard. No free-form predicate is ever accepted."""
    filter_key: str | None = None
    page: int = 1
    page_size: int = 25
