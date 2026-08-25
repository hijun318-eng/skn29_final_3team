from __future__ import annotations

import hashlib

from .vector_models import PdfChunk, PdfDocument


def build_lifecycle_fixture(
    manual_id: str,
    version: str,
    content: str,
) -> tuple[PdfDocument, PdfChunk]:
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
