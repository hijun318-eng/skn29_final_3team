"""근거 제한 RAG 답변의 요청·상태·주장·인용 JSON 계약을 정의한다."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AnswerStatus(StrEnum):
    """답변 생성 결과를 성공·근거 없음·충돌·실패로 구분한다."""

    ANSWER = "ANSWER"
    NO_EVIDENCE = "NO_EVIDENCE"
    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"
    GENERATION_FAILED = "GENERATION_FAILED"


class Citation(BaseModel):
    """답변 주장이 사용한 evidence 식별자와 사용자 표시 인용을 연결한다."""

    evidence_id: str
    citation: str


class AnswerClaim(BaseModel):
    """하나의 검증 가능한 문장과 이를 지지하는 evidence ID 목록이다."""

    text: str
    evidence_ids: list[str] = Field(min_length=1)


class AnswerSection(BaseModel):
    """문서·조항 metadata와 그 범위의 근거 연결 주장을 묶는다."""

    title: str
    article_number: int | None = None
    document_id: str = ""
    document_title: str = ""
    document_version: str = ""
    claims: list[AnswerClaim] = Field(default_factory=list)


class Conflict(BaseModel):
    """둘 이상의 evidence가 충돌한 설명과 관련 ID를 보존한다."""

    description: str
    evidence_ids: list[str] = Field(min_length=2)


class AnswerContextReceipt(BaseModel):
    """모델 입력에서 근거가 사용한 보수적 token 예산과 제외 개수를 서버 측에 기록한다."""

    estimator_version: str
    maximum_context_tokens: int = Field(gt=0)
    evidence_token_budget: int = Field(gt=0)
    used_evidence_tokens: int = Field(ge=0)
    input_evidence_count: int = Field(ge=0)
    packed_evidence_count: int = Field(ge=0)
    dropped_evidence_count: int = Field(ge=0)


class AnswerResponse(BaseModel):
    """모델·결정론 composer가 반환해야 할 전체 근거 답변 schema다."""

    schema_version: str = "rag-answer-v1.1"
    request_id: str
    trace_id: str
    status: AnswerStatus
    answer: str
    answer_type: Literal["PROCEDURE", "CRITERIA", "IMMEDIATE", "POLICY", "SUMMARY", "COMPARE"] | None = None
    summary: list[str] = Field(default_factory=list)
    sections: list[AnswerSection] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    context_receipt: AnswerContextReceipt | None = None
    model_version: str = "rag-local-answer-v2"


class AnswerRequest(BaseModel):
    """질문·intent·retrieval receipt·허용 evidence를 답변 생성기에 전달한다."""

    request_id: str
    trace_id: str
    query: str
    evidence_blocks: list[dict[str, Any]]
    intent: Literal["PROCESS", "IMMEDIATE_ACTION", "DECISION_CRITERIA", "REGULATION_CHECK", "COMPARISON", "SUMMARY"] = "REGULATION_CHECK"
    retrieval_request_id: str | None = None


class GroundedModelClaim(BaseModel):
    """외부 모델이 선택할 수 있는 원문 claim과 evidence 연결의 닫힌 계약이다."""

    model_config = ConfigDict(extra="forbid")

    text: str
    evidence_ids: list[str] = Field(min_length=1)


class GroundedModelSection(BaseModel):
    """표시 제목과 근거 claim만 모델에 맡기고 문서 metadata는 서버가 봉인한다."""

    model_config = ConfigDict(extra="forbid")

    title: str
    claims: list[GroundedModelClaim]


class GroundedModelOutput(BaseModel):
    """GPT가 반환하는 최소 출력이며 최종 사용자 응답은 서버가 다시 구성한다."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ANSWER", "NO_EVIDENCE"]
    sections: list[GroundedModelSection]
