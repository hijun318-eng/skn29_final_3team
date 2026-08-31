from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnswerStatus(StrEnum):
    ANSWER = "ANSWER"
    NO_EVIDENCE = "NO_EVIDENCE"
    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"
    GENERATION_FAILED = "GENERATION_FAILED"


class Citation(BaseModel):
    evidence_id: str
    citation: str


class AnswerClaim(BaseModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class AnswerSection(BaseModel):
    title: str
    article_number: int | None = None
    document_id: str = ""
    document_title: str = ""
    document_version: str = ""
    claims: list[AnswerClaim] = Field(default_factory=list)


class Conflict(BaseModel):
    description: str
    evidence_ids: list[str] = Field(min_length=2)


class AnswerResponse(BaseModel):
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
    model_version: str = "rag-local-answer-v2"


class AnswerRequest(BaseModel):
    request_id: str
    trace_id: str
    query: str
    evidence_blocks: list[dict[str, Any]]
    intent: Literal["PROCESS", "IMMEDIATE_ACTION", "DECISION_CRITERIA", "REGULATION_CHECK", "COMPARISON", "SUMMARY"] = "REGULATION_CHECK"
    retrieval_request_id: str | None = None
