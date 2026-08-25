from pydantic import BaseModel, Field
from typing import List, Literal, Optional


class Citation(BaseModel):
    evidence_id: str
    citation: str


class AnswerResponse(BaseModel):
    schema_version: str = Field(default="rag-answer-v1.0")
    request_id: str
    trace_id: str
    status: Literal["ANSWER", "NO_EVIDENCE", "POTENTIAL_CONFLICT", "GENERATION_FAILED"]
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class AnswerRequest(BaseModel):
    request_id: str
    trace_id: str
    query: str
    evidence_blocks: List[dict]
    # For evidence_blocks, a dict like:
    # {
    #   "evidence_id": "...",
    #   "text": "...",
    #   "citation": "..."
    # }
