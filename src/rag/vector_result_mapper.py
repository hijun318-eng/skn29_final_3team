from __future__ import annotations

import os
from typing import Iterable

from .vector_models import VectorSearchResult


def _snippet_limit() -> int:
    try:
        return max(1, int(os.getenv("RAG_SNIPPET_MAX_CHARS", "1800").strip() or "1800"))
    except ValueError:
        return 1800


def to_vector_search_result(row: Iterable[object]) -> VectorSearchResult:
    (
        manual_id, title, version, page_start, page_end, section_title, content,
        score, vector_score, lexical_score, document_status, authority_level,
        validity_status, document_type, owner_team, effective_from, expires_at,
    ) = row
    citation = f"[{manual_id} v{version} p.{page_start}-{page_end} {section_title}]"
    return VectorSearchResult(
        manual_id=str(manual_id),
        title=str(title),
        version=str(version),
        page_start=int(page_start),
        page_end=int(page_end),
        section_title=str(section_title),
        score=round(float(score), 6),
        vector_score=round(float(vector_score), 6),
        lexical_score=round(float(lexical_score), 6),
        snippet=" ".join(str(content).split())[:_snippet_limit()],
        citation=citation,
        document_status=str(document_status),
        authority_level=str(authority_level),
        validity_status=str(validity_status),
        warning=(
            "검토 전 내부 참고 문서이며 최종 운영 지침이 아닙니다."
            if str(validity_status) == "UNRESOLVED"
            else None
        ),
        document_type=str(document_type),
        owner_team=str(owner_team),
        effective_from=str(effective_from) if effective_from else None,
        expires_at=str(expires_at) if expires_at else None,
    )
