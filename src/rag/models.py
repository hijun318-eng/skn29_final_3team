"""로컬 SQLite RAG 경로의 문서 설정·chunk·검색 결과 계약을 정의한다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocumentConfig:
    """Markdown 원본의 식별자·역할·버전·상태 설정을 표현한다."""

    manual_id: str
    title: str
    version: str
    source_path: Path
    role_scope: tuple[str, ...]
    document_status: str = "WORKING_KNOWLEDGE"
    authority_level: str = "INTERNAL_WORKING_GUIDE"
    validity_status: str = "UNRESOLVED"


@dataclass(frozen=True)
class Chunk:
    """로컬 tokenizer가 만든 section 단위 원문과 token 위치를 보존한다."""

    chunk_id: str
    manual_id: str
    section_number: str
    section_title: str
    content: str
    token_terms: tuple[str, ...]
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class SearchResult:
    """로컬 lexical 검색에서 반환할 문서·section·score·snippet을 묶는다."""

    manual_id: str
    manual_title: str
    manual_version: str
    section_number: str
    section_title: str
    score: float
    snippet: str
    citation_label: str
    search_mode: str = "KEYWORD_NGRAM"
    fallback_used: bool = False
