"""RAG 문서·chunk·검색 결과와 locator 완전성 계약을 정의한다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PdfDocument:
    """원본 checksum과 접근 metadata를 포함하는 corpus 문서 영속화 모델이다."""

    manual_id: str
    title: str
    version: str
    source_path: str
    checksum: str
    role_scope: tuple[str, ...]
    document_type: str = "MANUAL"
    owner_team: str = "UNASSIGNED"
    effective_from: str | None = None
    expires_at: str | None = None
    approval_status: str = "NOT_APPROVED"
    validity_status: str = "UNRESOLVED"


@dataclass(frozen=True)
class PdfChunk:
    """원문 위치·section·token 수를 보존하는 embedding 단위 모델이다."""

    chunk_id: str
    manual_id: str
    page_start: int
    page_end: int
    section_title: str
    content: str
    checksum: str
    token_count: int = 0
    chunk_index: int = 0


@dataclass(frozen=True)
class VectorSearchResult:
    """hybrid 점수와 접근·인용 metadata를 결합한 검색 evidence 결과다."""

    manual_id: str
    title: str
    version: str
    page_start: int | None
    page_end: int | None
    section_title: str
    score: float
    vector_score: float
    lexical_score: float
    snippet: str
    content: str
    citation: str
    evidence_id: str
    ranking_stage: str
    reranker_score: float | None
    document_status: str
    authority_level: str
    validity_status: str
    warning: str | None
    document_type: str
    owner_team: str
    effective_from: str | None
    expires_at: str | None
    chunk_index: int = 0
    approval_status: str | None = None
    locator_kind: str = "PAGE"
    locator_start: int | None = None
    locator_end: int | None = None


def has_complete_locator(result: object) -> bool:
    """페이지를 추정하지 않고 page 또는 explicit-segment locator 완전성을 검사한다."""

    locator_kind = getattr(result, "locator_kind", "PAGE")
    if locator_kind == "EXPLICIT_BREAK_SEGMENT":
        start = getattr(result, "locator_start", None)
        end = getattr(result, "locator_end", None)
    elif locator_kind == "PAGE":
        start = getattr(result, "page_start", None)
        end = getattr(result, "page_end", None)
    else:
        return False
    return type(start) is int and type(end) is int and start > 0 and end >= start
