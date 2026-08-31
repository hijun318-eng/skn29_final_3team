"""LLM prompt의 질문·evidence를 복원하고 구조 답변을 제한 길이로 render한다."""

from __future__ import annotations

from typing import Any

from .answer_contracts import AnswerSection, Citation
from .answer_prompt import parse_answer_input
from .answer_safety import AnswerSafetySettings


class AnswerPromptParser:
    """고정 prompt label에서 질문과 허용 evidence metadata를 안전하게 추출한다."""

    def __init__(self, settings: AnswerSafetySettings) -> None:
        self._settings = settings

    def extract_query(self, content: str) -> str:
        """사용자 prompt의 질문 field를 반환하고 계약 불일치 시 빈 문자열을 반환한다."""

        payload = parse_answer_input(content)
        return payload["query"].strip() if payload is not None else ""

    def extract_evidence(self, content: str) -> list[dict[str, Any]]:
        """개수·문자 한도 안에서 evidence block과 citation metadata를 복원한다."""

        payload = parse_answer_input(content)
        if payload is None:
            return []
        evidence = payload["evidence"]
        if (
            len(evidence) > self._settings.maximum_chunks
            or sum(len(item["body"]) for item in evidence)
            > self._settings.maximum_evidence_chars
        ):
            return []
        return [dict(item) for item in evidence]

    @staticmethod
    def latest_user_content(messages: list[dict[str, Any]]) -> str:
        """chat message를 역순 탐색해 최신 문자열 user content를 반환한다."""

        for message in reversed(messages):
            if message.get("role") == "user" and isinstance(message.get("content"), str):
                return message["content"]
        return ""


class StructuredAnswerRenderer:
    """근거 연결 section을 출력 한도에 맞추고 citation과 읽기 형식으로 변환한다."""

    def __init__(self, settings: AnswerSafetySettings) -> None:
        self._settings = settings

    def limit_sections(self, sections: list[AnswerSection]) -> tuple[list[AnswerSection], bool]:
        """section·claim 수와 최종 문자 한도를 적용해 결과와 truncation 여부를 반환한다."""

        limited = []
        truncated = False
        for section in sections:
            claims = section.claims[: self._settings.maximum_points_per_article]
            truncated = truncated or len(claims) < len(section.claims)
            if claims:
                limited.append(section.model_copy(update={"claims": claims}, deep=True))
        while limited and len(self.render(limited, [Citation(evidence_id="x", citation="x")])) > self._settings.maximum_answer_chars:
            last = limited[-1]
            if len(last.claims) > 1:
                last.claims.pop()
            else:
                limited.pop()
            truncated = True
        return limited, truncated

    @staticmethod
    def citations(sections: list[AnswerSection], evidence: list[dict[str, Any]]) -> list[Citation]:
        """실제 사용된 evidence ID만 원래 citation 순서로 중복 없이 반환한다."""

        by_id = {str(item.get("evidence_id")): item for item in evidence}
        used_ids = list(dict.fromkeys(
            evidence_id
            for section in sections
            for claim in section.claims
            for evidence_id in claim.evidence_ids
        ))
        return [
            Citation(
                evidence_id=evidence_id,
                citation=str(by_id[evidence_id].get("citation") or evidence_id),
            )
            for evidence_id in used_ids
            if evidence_id in by_id
        ]

    @staticmethod
    def render(sections: list[AnswerSection], citations: list[Citation]) -> str:
        """문서·조항별 claim과 근거를 일관된 한국어 사용자 답변으로 직렬화한다."""

        documents = list(dict.fromkeys(
            f"{section.document_title or '확인 불가'}"
            + (f" v{section.document_version}" if section.document_version else "")
            for section in sections if section.document_id or section.document_title
        ))
        manual_ids = list(dict.fromkeys(section.document_id for section in sections if section.document_id))
        multiple_documents = len(manual_ids) > 1
        bodies = []
        for section in sections:
            label = f"제{section.article_number}조 {section.title}" if section.article_number else section.title
            if multiple_documents and section.document_title:
                label = f"{section.document_title} · {label}"
            numbered = section.article_number == 4
            lines = [
                f"{index}. {claim.text}" if numbered else f"- {claim.text}"
                for index, claim in enumerate(section.claims, start=1)
            ]
            bodies.append(f"[{label}]\n\n" + "\n\n".join(lines))
        return (
            "문서명: " + " / ".join(documents or ["확인 불가"]) + "\n"
            "지침번호: " + " / ".join(manual_ids or ["확인 불가"]) + "\n"
            "영역: " + " / ".join(dict.fromkeys(section.title for section in sections)) + "\n"
            "본문내용:\n" + "\n\n".join(bodies) + "\n"
            "근거: " + " / ".join(citation.citation for citation in citations)
        )
