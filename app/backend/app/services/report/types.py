"""보고서 렌더링 결과(RenderedReportDocument) 및 체크섬 무결성 타입 정의 모듈.

[핵심 목적]
보고서 원본 소스(JSON)의 Canonical SHA-256 체크섬과, 이를 통해 렌더링된
HTML 및 PDF 바이너리 바이트의 무결성을 엄격히 보증하는 불변 데이터 클래스 및 예외를 정의합니다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


class ReportDocumentRenderError(RuntimeError):
    """보고서 소스, 차트 규격 또는 PDF 렌더링 과정에서 계약 위반 발생 시 발생하는 예외."""


@dataclass(frozen=True, slots=True)
class RenderedReportDocument:
    """렌더링된 보고서의 원본 소스 체크섬 및 생성된 HTML 문자열/PDF 바이너리 바이트 묶음 클래스.

    Attributes:
        source_checksum: 원본 소스 JSON의 canonical SHA-256 해시
        html: 렌더링된 HTML 문서 문자열
        pdf: 렌더링된 PDF 바이너리 바이트
    """

    source_checksum: str
    html: str
    pdf: bytes

    @property
    def html_checksum(self) -> str:
        """HTML UTF-8 바이트의 SHA-256 해시를 반환합니다."""
        return hashlib.sha256(self.html.encode("utf-8")).hexdigest()

    @property
    def pdf_checksum(self) -> str:
        """PDF 바이너리 바이트의 SHA-256 해시를 반환합니다."""
        return hashlib.sha256(self.pdf).hexdigest()


def canonical_source_checksum(source: Mapping[str, Any], orientation: str) -> str:
    """보고서 소스와 페이지 방향(orientation)을 정규화 JSON으로 직렬화한 후 SHA-256 해시를 산출합니다."""
    serialized = json.dumps(
        {"orientation": orientation, "source": source},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
