from __future__ import annotations

import re
from typing import Any


class ManualResponseNormalizer:
    """PDF 추출 본문을 원문 손실 없이 화면용 섹션으로 나눈다."""

    _RELATED_MARKER = "이 영역의 문서"
    _RULES_MARKER = "이 영역에서 공통으로 지킬 기준"
    _FOOTERS = (
        "내부 업무지침 · 현장 실행형 · 의미전달 검증완료본",
        "내부 업무지침 · 의미전달 검증완료본",
    )

    def normalize(self, item: dict[str, Any]) -> dict[str, Any]:
        content = " ".join(str(item.get("content") or item.get("snippet") or "").split())
        cleaned = content
        for footer in self._FOOTERS:
            cleaned = cleaned.replace(footer, "").strip()

        summary, related_text, rules_text = self._split_sections(cleaned)
        return {
            **item,
            "document_id": str(item.get("manual_id") or ""),
            "normalized_body": {
                "summary": summary,
                "related_guidelines": self._bullets(related_text),
                "action_rules": self._bullets(rules_text),
                "body_paragraphs": self._paragraphs(content),
            },
        }

    def _split_sections(self, text: str) -> tuple[str, str, str]:
        summary, related, rules = text, "", ""
        if self._RELATED_MARKER in summary:
            summary, related = summary.split(self._RELATED_MARKER, 1)
        if self._RULES_MARKER in related:
            related, rules = related.split(self._RULES_MARKER, 1)
        elif self._RULES_MARKER in summary:
            summary, rules = summary.split(self._RULES_MARKER, 1)
        return summary.strip(), related.strip(), rules.strip()

    @staticmethod
    def _bullets(text: str) -> list[str]:
        return [item.strip(" .") for item in text.split("•") if item.strip(" .")]

    def _paragraphs(self, text: str) -> list[str]:
        separated = text
        for marker in (self._RELATED_MARKER, self._RULES_MARKER):
            separated = separated.replace(marker, f"\n{marker}\n")
        separated = separated.replace("•", "\n• ")
        return [paragraph.strip() for paragraph in separated.splitlines() if paragraph.strip()]

    @staticmethod
    def answer_points(answer: str) -> list[str]:
        body = answer.split("본문내용:\n", 1)[-1]
        body = body.rsplit("\n근거:", 1)[0].strip()
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", body) if item.strip()]
        return paragraphs[:4] if paragraphs else [body]
