from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import IntegrationContext, SqlEvidence
from .coordinator import ToolCallError


@dataclass(frozen=True)
class ApprovedSqlPlan:
    sql: str
    parameters: dict[str, Any]
    gate_token: str
    source_refs: tuple[str, ...]
    policy_version: str
    approved: bool = False


class ApprovedSqlPlanResolver(Protocol):
    def resolve(
        self, question: str, context: IntegrationContext
    ) -> ApprovedSqlPlan: ...


class DataPlatformPort(Protocol):
    def execute_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]: ...

    def get_query_status(self, query_id: str) -> dict[str, Any]: ...


class ApprovedSqlEvidenceAdapter:
    """Executes approved SQL only; it never generates or repairs SQL."""

    def __init__(
        self,
        data_platform: DataPlatformPort,
        resolver: ApprovedSqlPlanResolver,
    ) -> None:
        self._data_platform = data_platform
        self._resolver = resolver

    def query(self, question: str, context: IntegrationContext) -> SqlEvidence:
        plan = self._resolver.resolve(question, context)
        if not plan.approved:
            raise ToolCallError("SQL_PLAN_NOT_APPROVED")
        if not plan.sql.strip() or not plan.gate_token or not plan.source_refs:
            raise ToolCallError("SQL_PLAN_INCOMPLETE")
        try:
            started = self._data_platform.execute_query(
                plan.sql, plan.parameters, plan.gate_token
            )
            query_id = str(started["query_id"])
            result = self._data_platform.get_query_status(query_id)
        except (KeyError, TypeError, ValueError) as error:
            raise ToolCallError("SQL_SOURCE_FAILED") from error
        status = str(result.get("status", "UNKNOWN"))
        if status not in {"SUCCEEDED", "PARTIAL"}:
            raise ToolCallError(f"SQL_{status}")
        if not result.get("evidence_complete", False):
            raise ToolCallError("SQL_EVIDENCE_INCOMPLETE")
        rows = result.get("rows")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ToolCallError("SQL_RESULT_INVALID")
        return SqlEvidence(
            query_id=query_id,
            as_of=context.as_of,
            observed_facts=tuple(dict(row) for row in rows),
            source_refs=plan.source_refs,
            status=status,
        )
