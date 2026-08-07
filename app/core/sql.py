"""SQL Warehouse client (Statement Execution API).

Used for KPI reads -- ``providers.metricview.MetricViewProvider`` queries the UC
metric views natively through this client -- and for the interactive Genie /
ad-hoc drill-down experience. Statements run with per-request OBO tokens, so all
data access respects Unity Catalog permissions per user.
"""

from __future__ import annotations

import logging
import os
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

logger = logging.getLogger(__name__)

# Maximum wait time for statement execution (seconds)
_STATEMENT_TIMEOUT = 120


class SQLClient:
    """Executes SQL statements against a Databricks SQL Warehouse."""

    def __init__(self, warehouse_id: str):
        self.warehouse_id = warehouse_id

    def execute(self, sql: str, *, token: str = "") -> list[dict]:
        """Execute a SQL statement and return results as list of dicts.

        Args:
            sql: SQL statement to execute.
            token: OBO token for user-scoped access. Falls back to env config.

        Returns:
            List of row dictionaries.

        Raises:
            PermissionError: If the user lacks access to the queried data.
            RuntimeError: If the statement fails or times out.
        """
        host = os.environ.get("DATABRICKS_HOST", "")

        if token:
            # OBO: authenticate AS THE USER with their forwarded token. The app
            # runtime also carries the SP's OAuth env (DATABRICKS_CLIENT_ID/SECRET),
            # so a bare WorkspaceClient(token=...) trips the SDK's "more than one
            # authorization method configured: oauth and pat" guard. Pin an explicit
            # PAT-auth Config so ONLY the user token is used (ignores ambient OAuth).
            from databricks.sdk.core import Config

            cfg = Config(host=host, token=token, auth_type="pat")
            ws = WorkspaceClient(config=cfg)
        else:
            ws = WorkspaceClient()

        response = ws.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=self.warehouse_id,
            wait_timeout="0s",  # async execution
        )

        # Poll for completion
        statement_id = response.statement_id
        start = time.time()

        while response.status and response.status.state in (
            StatementState.PENDING,
            StatementState.RUNNING,
        ):
            if time.time() - start > _STATEMENT_TIMEOUT:
                ws.statement_execution.cancel_execution(statement_id)
                raise RuntimeError(f"Statement {statement_id} timed out after {_STATEMENT_TIMEOUT}s")
            time.sleep(0.5)
            response = ws.statement_execution.get_statement(statement_id)

        if response.status and response.status.state == StatementState.FAILED:
            error_msg = response.status.error.message if response.status.error else "Unknown error"
            if "PERMISSION_DENIED" in error_msg or "does not have" in error_msg.lower():
                raise PermissionError(error_msg)
            raise RuntimeError(f"Statement failed: {error_msg}")

        # Parse results
        if not response.result or not response.result.data_array:
            return []

        columns = [col.name for col in (response.manifest.schema.columns if response.manifest else [])]
        rows = []
        for row_data in response.result.data_array:
            rows.append(dict(zip(columns, row_data)))

        return rows
