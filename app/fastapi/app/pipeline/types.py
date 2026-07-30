"""Pipeline 핵심 타입 — 기획서 §7.5 식별자 + §9.2 Context Package.

모든 Pipeline 컴포넌트가 공유하는 Pydantic v2 데이터 계약이다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 상태 머신 (기획서 §9.3 처리 흐름)
# ---------------------------------------------------------------------------


class PipelineState(str, Enum):
    """결정론적 Pipeline 실행 상태."""
    INIT = "INIT"
    ROUTER = "ROUTER"
    NODE1_NORMALIZE = "NODE1_NORMALIZE"
    CONTEXT_BUILD = "CONTEXT_BUILD"
    G1_CONTEXT = "G1_CONTEXT"
    SQL_SOURCE_SELECT = "SQL_SOURCE_SELECT"
    G2_SQL_POLICY = "G2_SQL_POLICY"
    NODE2_FIX = "NODE2_FIX"
    G2_PRIME = "G2_PRIME"
    EXECUTE = "EXECUTE"
    G3_RESULT = "G3_RESULT"
    NODE3_EXPLAIN = "NODE3_EXPLAIN"
    DONE = "DONE"
    FAILED = "FAILED"


class RouteType(str, Enum):
    """Router가 결정하는 실행 경로."""
    TEMPLATE = "TEMPLATE"
    CACHE = "CACHE"
    GENERAL = "GENERAL"


# ---------------------------------------------------------------------------
# Gate 결과
# ---------------------------------------------------------------------------


class GateResult(BaseModel):
    """G1/G2/G3 판정 결과."""
    passed: bool
    gate: str = Field(description="G1/G2/G2'/G3")
    error_code: str = ""
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Context Package (기획서 §9.2)
# ---------------------------------------------------------------------------


class AssetRef(BaseModel):
    """DataHub 자산 참조."""
    urn: str
    trino_fqn: str
    columns: list[str] = Field(default_factory=list)


class MetricRef(BaseModel):
    """승인된 지표."""
    metric_id: str
    field: str
    aggregation: str = "sum"
    time_field: str = ""


class JoinRef(BaseModel):
    """승인된 JOIN."""
    left: str
    right: str
    cardinality: str = "many_to_one"
    status: str = "approved"


class ContextPackage(BaseModel):
    """불변 Context Package (기획서 §9.2).

    DataHub 검색 + 업무 정책 결합으로 질문마다 구성된다.
    """
    context_release: str = ""
    policy_version: str = ""
    question: str = ""
    as_of: str = ""
    timezone: str = "Asia/Seoul"
    period_start: str = ""
    period_end_exclusive: str = ""
    user_role: str = ""
    assets: list[AssetRef] = Field(default_factory=list)
    metrics: list[MetricRef] = Field(default_factory=list)
    joins: list[JoinRef] = Field(default_factory=list)
    token_count: int = 0
    hash: str = ""


# ---------------------------------------------------------------------------
# Node 입출력
# ---------------------------------------------------------------------------


class NormalizedQuestion(BaseModel):
    """Node 1 출력 — 질문 정규화."""
    intent: str = ""
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    period: str = ""
    search_terms: list[str] = Field(default_factory=list)
    is_ambiguous: bool = False
    clarify_question: str = ""


class GeneratedSQL(BaseModel):
    """Node 2 출력 — 생성 SQL."""
    sql: str = ""
    sql_hash: str = ""
    source: str = Field(default="node2", description="template/cache/node2/node2prime")


class ShapedResult(BaseModel):
    """Result Shaper 출력."""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    sampling_evidence: dict[str, Any] = Field(default_factory=dict)


class ExplanationResult(BaseModel):
    """Node 3 출력 — 근거 기반 설명."""
    explanation: str = ""
    evidence_summary: str = ""
    limitations: list[str] = Field(default_factory=list)
    model_version: str = "stub-v1"


# ---------------------------------------------------------------------------
# Pipeline 최종 결과
# ---------------------------------------------------------------------------


class PipelineResult(BaseModel):
    """Pipeline 실행 최종 결과."""
    request_id: str
    state: PipelineState
    route_type: RouteType = RouteType.GENERAL
    question: str = ""
    context: ContextPackage | None = None
    sql: GeneratedSQL | None = None
    result: ShapedResult | None = None
    explanation: ExplanationResult | None = None
    g1: GateResult | None = None
    g2: GateResult | None = None
    g3: GateResult | None = None
    error: str = ""
    artifact_id: str = ""
