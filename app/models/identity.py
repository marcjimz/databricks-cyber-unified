"""Identity domain table models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AccountRow(BaseModel):
    uid: str
    name: str
    org_unit: str
    privileged: bool
    sso_enrolled: bool
    in_pam_vault: bool
    last_activity: str | None
    status: Literal["active", "dormant", "orphaned", "disabled"]


class AccountsQuery(BaseModel):
    status: str | None = None
    privileged: bool | None = None
    page: int = 1
    page_size: int = 25
