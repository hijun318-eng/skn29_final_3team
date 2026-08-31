"""구조화 보고서 evidence를 원문 문장·표 행 단위 claim과 인용으로 보존한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .manual_article_formatter import ManualArticleFormatter, ManualClaim


@dataclass(frozen=True)
class ReportSection:
    """동일 heading 경로 아래의 중복 제거된 보고서 claim을 묶는다."""

    title: str
    claims: tuple[ManualClaim, ...]


class ReportEvidenceFormatter:
    """조문 번호를 가정하지 않고 DOCX heading·본문·표 순서를 답변 절로 만든다."""

    _LOCATOR_PREFIX = re.compile(r"^\[DOCX\s+[^\]]+\]\s*")
    _STRUCTURE_ONLY = re.compile(
        r"^\[/?(?:TABLE|TABLE_SEGMENT)(?:\s+[^\]]*)?\]$"
    )
    _STRUCTURE_MARKER = re.compile(
        r"\[(?:"
        r"DOCX\s+[^\]]+"
        r"|/?(?:TABLE|TABLE_SEGMENT)(?:\s+[^\]]*)?"
        r"|(?:TABLE_HEADER_CONTEXT|PARAGRAPH|HEADING|EXPLICIT_PAGE_BREAK|HEADER|FOOTER|FIELD_SIMPLE)"
        r"(?:\s+[^\]]*)?"
        r")\]\s*"
    )
    _CELL_MARKER = re.compile(r"\[r\d+c\d+\b[^\]]*\]\s*")
    _SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。])\s+")

    def build_sections(
        self,
        evidence: list[dict[str, Any]],
        query_terms: set[str],
    ) -> tuple[ReportSection, ...]:
        """검색 순서의 heading별 원문 단위를 합치고 각 claim의 evidence ID를 유지한다."""

        merged: dict[str, dict[str, list[str]]] = {}
        for item in sorted(evidence, key=ManualArticleFormatter.evidence_order):
            evidence_id = str(item.get("evidence_id") or "").strip()
            if not evidence_id:
                continue
            title = self._section_title(str(item.get("section_title") or ""))
            claims = merged.setdefault(title, {})
            points = self._points(
                str(item.get("body") or item.get("content") or item.get("text") or "")
            )
            ranked = sorted(
                enumerate(points),
                key=lambda pair: (
                    -sum(term in pair[1].lower() for term in query_terms),
                    pair[0],
                ),
            )
            for _index, point in ranked:
                claims.setdefault(point, [])
                if evidence_id not in claims[point]:
                    claims[point].append(evidence_id)
        return tuple(
            ReportSection(
                title=title,
                claims=tuple(
                    ManualClaim(text=point, evidence_ids=tuple(evidence_ids))
                    for point, evidence_ids in claims.items()
                ),
            )
            for title, claims in merged.items()
            if claims
        )

    def claim_segments(self, body: str) -> tuple[str, ...]:
        """보고서 parser가 보존한 전체 문장·표 행을 외부 답변 claim 검증 단위로 반환한다."""

        return self._points(body)

    @classmethod
    def _section_title(cls, value: str) -> str:
        normalized = cls._LOCATOR_PREFIX.sub("", " ".join(value.split())).strip()
        return normalized or "보고서 본문"

    @classmethod
    def _points(cls, body: str) -> tuple[str, ...]:
        points: list[str] = []
        for raw_line in body.replace("\r", "\n").splitlines():
            line = " ".join(raw_line.split()).strip()
            if not line or cls._STRUCTURE_ONLY.fullmatch(line):
                continue
            line = cls._STRUCTURE_MARKER.sub("", line)
            line = cls._CELL_MARKER.sub("", line).strip(" |-:")
            if not line:
                continue
            for sentence in cls._SENTENCE_BOUNDARY.split(line):
                point = sentence.strip(" |-:")
                if len(point) >= 4 and point not in points:
                    points.append(point)
        return tuple(points)

    @staticmethod
    def render_section(section: ReportSection) -> str:
        """보고서 heading과 원문 claim을 간결한 bullet 절로 표시한다."""

        return f"[{section.title}]\n\n" + "\n\n".join(
            f"- {claim.text}" for claim in section.claims
        )
