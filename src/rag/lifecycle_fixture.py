"""문서 soft-delete·restore 검증에 사용할 결정론적 합성 document와 chunk를 만든다."""

from __future__ import annotations

import hashlib

from .vector_models import PdfChunk, PdfDocument


def build_lifecycle_fixture(
    manual_id: str,
    version: str,
    content: str,
) -> tuple[PdfDocument, PdfChunk]:
    """입력 content SHA를 공유하는 관리자 전용 문서·단일 chunk fixture를 반환한다."""

    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    document = PdfDocument(
        manual_id,
        "합성 생명주기 검증 문서",
        version,
        "synthetic://lifecycle",
        checksum,
        ("SYSTEM_ADMIN",),
    )
    chunk = PdfChunk(
        f"{manual_id}-{version}",
        manual_id,
        1,
        1,
        "합성 검증",
        content,
        checksum,
    )
    return document, chunk
