from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocumentConfig:
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
