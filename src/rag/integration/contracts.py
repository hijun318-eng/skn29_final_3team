from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ToolRoute(str, Enum):
    GENERAL = "GENERAL"
    SQL_ONLY = "SQL_ONLY"
    RAG_ONLY = "RAG_ONLY"
    SQL_AND_RAG = "SQL_AND_RAG"
    ML_ONLY = "ML_ONLY"
    ML_AND_RAG = "ML_AND_RAG"


class IntegrationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class IntegrationContext:
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
        return (
            self.enabled
            and self.approval_status == "APPROVED"
            and self.health_status == "HEALTHY"
            and role in self.required_roles
        )


@dataclass(frozen=True)
class SqlEvidence:
    query_id: str
    as_of: str
    observed_facts: tuple[dict[str, Any], ...]
    source_refs: tuple[str, ...]
    status: str = "SUCCEEDED"


@dataclass(frozen=True)
class DocumentEvidence:
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
        return asdict(self)
