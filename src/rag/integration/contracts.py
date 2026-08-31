"""도구 라우팅, 호출 주체, 등록 정책, SQL·문서·예측 근거의 통합 응답 계약을 정의한다."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ToolRoute(str, Enum):
    """상위 오케스트레이터가 승인할 수 있는 SQL·RAG·ML 실행 조합을 열거한다."""

    GENERAL = "GENERAL"
    SQL_ONLY = "SQL_ONLY"
    RAG_ONLY = "RAG_ONLY"
    SQL_AND_RAG = "SQL_AND_RAG"
    ML_ONLY = "ML_ONLY"
    ML_AND_RAG = "ML_AND_RAG"


class IntegrationStatus(str, Enum):
    """통합 도구 실행의 미적용·완료·부분 성공·정책 차단·실패를 구분한다."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class IntegrationContext:
    """한 도구 호출의 주체·역할·기준일·추적 ID와 승인된 라우팅 영수증을 전달한다."""

    request_id: str
    trace_id: str
    actor_id: str
    role: str
    as_of: str
    approved_route: ToolRoute = ToolRoute.GENERAL
    session_id: str | None = None
    router_decision_id: str | None = None
    parent_artifact_id: str | None = None
    report_run_id: str | None = None
    recent_utterances: tuple[str, ...] = ()
    selected_document_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolRegistration:
    """도구 버전·근거 유형·승인·상태·역할·스키마 제한을 담은 Registry 레코드다."""

    tool_code: str
    semantic_version: str
    evidence_type: str
    enabled: bool
    approval_status: str
    required_roles: frozenset[str]
    timeout_seconds: int = 30
    maximum_retries: int = 0
    title: str = ""
    description: str = ""
    input_schema_json: dict[str, Any] = field(default_factory=dict)
    output_schema_json: dict[str, Any] = field(default_factory=dict)
    health_status: str = "UNKNOWN"

    def callable_by(self, role: str) -> bool:
        """도구가 활성·승인·정상이고 요청 역할이 허용 목록에 있을 때만 호출 가능으로 판정한다."""

        return (
            self.enabled
            and self.approval_status == "APPROVED"
            and self.health_status == "HEALTHY"
            and role in self.required_roles
        )


@dataclass(frozen=True)
class SqlEvidence:
    """승인 SQL 실행의 query ID, 기준일, 관측 행, 원천 참조와 완료 상태를 보존한다."""

    query_id: str
    as_of: str
    observed_facts: tuple[dict[str, Any], ...]
    source_refs: tuple[str, ...]
    status: str = "SUCCEEDED"


@dataclass(frozen=True)
class DocumentEvidence:
    """권한 필터를 통과한 문서 조각의 식별자·버전·인용·본문·점수·유효기간을 담는다."""

    document_id: str
    document_title: str
    document_version: str
    citation: str
    snippet: str
    score: float
    effective_from: str | None = None
    expires_at: str | None = None


@dataclass(frozen=True)
class IntegrationResponse:
    """하나의 승인 route에서 수집한 관측·문서·예측 근거와 오류를 분리해 반환한다."""

    request_id: str
    trace_id: str
    as_of: str
    route: ToolRoute
    status: IntegrationStatus
    observed_facts: tuple[dict[str, Any], ...] = ()
    document_facts: tuple[DocumentEvidence, ...] = ()
    interpretations: tuple[dict[str, Any], ...] = ()
    sql_evidence: tuple[SqlEvidence, ...] = ()
    document_evidence: tuple[DocumentEvidence, ...] = ()
    model_predictions: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    tool_errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """중첩 데이터클래스와 Enum을 감사·전송 가능한 사전 구조로 변환한다."""

        return asdict(self)
