from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PdfDocument:
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


@dataclass(frozen=True)
class PdfChunk:
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
    manual_id: str
    title: str
    version: str
    page_start: int
    page_end: int
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
