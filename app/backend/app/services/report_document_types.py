"""렌더 전 source와 최종 HTML·PDF bytes의 SHA-256 계약 및 안전한 문서를 만들 수 없을 때 사용하는 단일 render 오류 경계를 정의한다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


class ReportDocumentRenderError(RuntimeError):
    """보고서 source·chart·외부 resource 또는 PDF bytes가 렌더 계약을 위반했음을 나타낸다.

    renderer 경계는 이 예외를 사용해 외부 URL 접근과 지원하지 않는 시각화, invalid PDF를
    fail-closed 처리하며 불완전한 문서를 성공 artifact로 저장하지 않는다.
    """
    pass


@dataclass(frozen=True, slots=True)
class RenderedReportDocument:
    """확정 source snapshot의 checksum과 그 snapshot에서 생성된 HTML·PDF bytes를 묶는다.

    세 값은 승인 문서 저장 시 함께 영속화되며 HTML/PDF checksum은 각각 실제 bytes에서
    다시 계산된다. 따라서 editor 상태나 이후 draft 변경을 확정 문서 내용으로 대체할 수 없다.
    """
    source_checksum: str
    html: str
    pdf: bytes

    @property
    def html_checksum(self) -> str:
        """렌더링된 UTF-8 HTML 바이트의 SHA-256 무결성 식별자를 반환한다.

        source checksum과 별도로 최종 표현 계층의 변조 여부를 비교할 때 사용한다.
        """
        return hashlib.sha256(self.html.encode("utf-8")).hexdigest()

    @property
    def pdf_checksum(self) -> str:
        """최종 PDF 바이트 그대로의 SHA-256 무결성 식별자를 반환한다.

        재렌더링이나 전송 과정에서 문서 bytes가 달라졌는지 검증할 수 있도록 인코딩 변환을 하지 않는다.
        """
        return hashlib.sha256(self.pdf).hexdigest()


def canonical_source_checksum(source: Mapping[str, Any], orientation: str) -> str:
    """소스 체크섬 값을 비교와 해시에 사용할 수 있는 표준 형태로 정규화한다."""
    serialized = json.dumps(
        {"orientation": orientation, "source": source},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
