"""사전 승인된 SQL 계획만 데이터 플랫폼에서 실행해 출처가 있는 관측 근거로 변환한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import IntegrationContext, SqlEvidence
from .coordinator import ToolCallError


@dataclass(frozen=True)
class ApprovedSqlPlan:
    """검증 SQL·매개변수·gate token·출처·정책 버전과 승인 여부를 묶은 실행 영수증이다."""

    sql: str
    parameters: dict[str, Any]
    gate_token: str
    source_refs: tuple[str, ...]
    policy_version: str
    approved: bool = False


class ApprovedSqlPlanResolver(Protocol):
    """질문과 호출 문맥을 이미 승인된 SQL 계획에 연결하는 resolver 규약이다."""

    def resolve(
        self, question: str, context: IntegrationContext
    ) -> ApprovedSqlPlan:
        """질문에 대응하는 SQL, 매개변수, 실행 gate와 출처가 포함된 계획을 반환한다."""

        ...


class DataPlatformPort(Protocol):
    """승인 SQL 실행 시작과 query 상태·행 조회를 제공하는 데이터 플랫폼 규약이다."""

    def execute_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]:
        """SQL과 매개변수·gate token을 제출하고 query ID를 포함한 시작 영수증을 반환한다."""

        ...

    def get_query_status(self, query_id: str) -> dict[str, Any]:
        """query ID의 최종 상태, 근거 완전성, 결과 행을 포함한 실행 영수증을 조회한다."""

        ...


class ApprovedSqlEvidenceAdapter:
    """SQL을 생성·수정하지 않고 승인된 완전한 계획만 실행해 관측 근거로 변환한다."""

    def __init__(
        self,
        data_platform: DataPlatformPort,
        resolver: ApprovedSqlPlanResolver,
    ) -> None:
        self._data_platform = data_platform
        self._resolver = resolver

    def query(self, question: str, context: IntegrationContext) -> SqlEvidence:
        """승인 계획을 실행하고 성공·부분 성공이면서 완전한 dict 행만 SQL 근거로 반환한다."""

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
