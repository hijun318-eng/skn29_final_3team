"""P2 RAG tool의 증거 유형·구현 Gate·공개 input/output schema를 정의한다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class EvidenceType(str, Enum):
    """분석 SQL과 내부 문서 검색 evidence의 출처 유형을 구분한다."""

    SQL = "SQL_EVIDENCE"
    DOCUMENT = "DOCUMENT_EVIDENCE"


class ImplementationState(str, Enum):
    """RAG tool 구현이 운영 승인 전 어느 통합 단계인지 나타낸다."""

    INTEGRATED_RC = "INTEGRATED_RC"


@dataclass(frozen=True)
class P2GateStatus:
    """제품 registry·자동 routing 활성화 전 기술·승인 상태를 공개한다."""

    implementation_state: str = ImplementationState.INTEGRATED_RC
    p2_gate: str = "TECHNICALLY_VALIDATED"
    tool_registration: str = "INTERNAL_HTTP_AVAILABLE"
    production_integration: str = "LOCAL_DOCKER_VALIDATED"
    affects_p0_p1_completion: bool = False


@dataclass(frozen=True)
class RagToolContract:
    """내부 지침 검색 tool의 이름·버전·route와 JSON schema를 고정한다."""

    tool_code: str = "internal-manual-search"
    tool_type: str = "RAG"
    semantic_version: str = "1.0.0-rc1"
    owner: str = "UNASSIGNED"
    risk_level: str = "INTERNAL_RESTRICTED"
    transport: str = "INTERNAL_HTTP"
    timeout_seconds: int = 30
    maximum_retries: int = 0
    enabled: bool = False
    approval_status: str = "PENDING_BUSINESS_OWNER_APPROVAL"
    health_status: str = "HEALTH_ENDPOINT_AVAILABLE"
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True
    evidence_type: str = EvidenceType.DOCUMENT

    def public_metadata(self) -> dict[str, Any]:
        """비밀 설정 없이 client가 표시할 tool identity와 Gate 상태를 반환한다."""

        return asdict(self)

    def input_schema(self) -> dict[str, Any]:
        """질문과 mult-turn 문맥에 허용되는 tool 입력 JSON schema를 반환한다."""

        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "minLength": 2, "maxLength": 500},
                "recent_utterances": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {"type": "string", "minLength": 1, "maxLength": 500},
                },
                "selected_document_ids": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {"type": "string", "minLength": 1, "maxLength": 100},
                },
            },
        }

    def output_schema(self) -> dict[str, Any]:
        """문서 evidence와 경고를 포함한 tool 출력 JSON schema를 반환한다."""

        return {
            "type": "object",
            "required": ["request_id", "document_evidence", "warnings"],
            "properties": {
                "request_id": {"type": "string"},
                "observed_facts": {"type": "array"},
                "document_facts": {"type": "array"},
                "interpretations": {"type": "array"},
                "sql_evidence": {"type": "array", "maxItems": 0},
                "document_evidence": {"type": "array"},
                "warnings": {"type": "array"},
                "as_of": {"type": ["string", "null"]},
            },
        }


def build_retrieval_envelope(
    request_id: str,
    as_of: str | None,
    results: list[dict[str, Any]],
    trace_id: str | None = None,
) -> dict[str, Any]:
    """검색 payload를 trace와 document evidence가 명시된 전달 envelope로 감싼다."""

    warnings = sorted(
        {str(item["warning"]) for item in results if item.get("warning")}
    )
    evidence = [
        {
            "evidence_type": EvidenceType.DOCUMENT,
            "document_id": item["manual_id"],
            "document_title": item["title"],
            "document_version": item["version"],
            "effective_from": item.get("effective_from"),
            "expires_at": item.get("expires_at"),
            "citation": item["citation"],
            "score": item["score"],
            "snippet": item["snippet"],
        }
        for item in results
    ]
    return {
        "request_id": request_id,
        "trace_id": trace_id or request_id,
        "observed_facts": [],
        "document_facts": evidence,
        "interpretations": [],
        "sql_evidence": [],
        "document_evidence": evidence,
        "warnings": warnings,
        "as_of": as_of,
    }
