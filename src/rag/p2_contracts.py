from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class EvidenceType(str, Enum):
    SQL = "SQL_EVIDENCE"
    DOCUMENT = "DOCUMENT_EVIDENCE"


class ImplementationState(str, Enum):
    INTEGRATED_CANDIDATE = "INTEGRATED_CANDIDATE"


@dataclass(frozen=True)
class P2GateStatus:
    implementation_state: str = ImplementationState.INTEGRATED_CANDIDATE
    p2_gate: str = "NOT_APPROVED"
    tool_registration: str = "DISABLED"
    production_integration: str = "CURRENT_INTEGRATION_E2E_PENDING"
    affects_p0_p1_completion: bool = False


@dataclass(frozen=True)
class RagToolContract:
    tool_code: str = "internal-manual-search"
    tool_type: str = "RAG"
    semantic_version: str = "0.5.0-poc"
    owner: str = "UNASSIGNED"
    risk_level: str = "INTERNAL_RESTRICTED"
    transport: str = "INTERNAL_HTTP"
    timeout_seconds: int = 30
    maximum_retries: int = 0
    enabled: bool = False
    approval_status: str = "NOT_APPROVED"
    health_status: str = "UNKNOWN"
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True
    evidence_type: str = EvidenceType.DOCUMENT

    def public_metadata(self) -> dict[str, Any]:
        return asdict(self)

    def input_schema(self) -> dict[str, Any]:
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
