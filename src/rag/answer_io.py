from __future__ import annotations

import re
from typing import Any

from .answer_contracts import AnswerSection, Citation
from .answer_safety import AnswerSafetySettings


class AnswerPromptParser:
    _EVIDENCE_PATTERN = re.compile(
        r"ID:\s*(?P<evidence_id>[^\n]+)\n(?P<text>.*?)(?=\n\nID:|\n\nEND_EVIDENCE|\Z)",
        re.DOTALL,
    )
    _QUERY_PATTERN = re.compile(
        r"질문:\s*(?P<query>.*?)(?:\n요청 의도:|\n\n제공된 근거)",
        re.DOTALL,
    )

    def __init__(self, settings: AnswerSafetySettings) -> None:
        self._settings = settings

    def extract_query(self, content: str) -> str:
        match = self._QUERY_PATTERN.search(content)
        query = match.group("query").strip() if match else ""
        if "후속 질문:" in query:
            return query.rsplit("후속 질문:", 1)[1].strip()
        if "현재 질문:" in query:
            return query.rsplit("현재 질문:", 1)[1].strip()
        return query

    def extract_evidence(self, content: str) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        used_chars = 0
        for match in self._EVIDENCE_PATTERN.finditer(content):
            if len(evidence) >= self._settings.maximum_chunks:
                break
            evidence_id = match.group("evidence_id").strip()
            text = match.group("text").strip()
            metadata, separator, body = text.partition("본문내용:\n")
            body = body.strip() if separator else text
            body = re.sub(r"\nEND_EVIDENCE\s*$", "", body).strip()
            if not evidence_id or not body or used_chars + len(body) > self._settings.maximum_evidence_chars:
                continue
            fields = {
                key: value.strip()
                for key, value in (
                    line.split(":", 1) for line in metadata.splitlines() if ":" in line
                )
            }
            evidence.append({
                "evidence_id": evidence_id,
                "document_id": fields.get("문서ID", fields.get("지침번호", "")),
                "title": fields.get("문서명", ""),
                "manual_id": fields.get("지침번호", ""),
                "version": fields.get("버전", ""),
                "section_title": fields.get("영역", ""),
                "article_number": fields.get("조항번호", ""),
                "page_start": fields.get("페이지", ""),
                "chunk_id": fields.get("청크ID", ""),
                "chunk_index": fields.get("청크순서", ""),
                "citation": fields.get("근거", ""),
                "retrieval_score": fields.get("검색점수", ""),
                "vector_score": fields.get("벡터점수", ""),
                "lexical_score": fields.get("어휘점수", ""),
                "document_status": fields.get("문서상태", ""),
                "approval_status": fields.get("승인상태", ""),
                "validity_status": fields.get("유효성상태", ""),
                "effective_from": fields.get("유효시작일", ""),
                "effective_to": fields.get("유효종료일", ""),
                "body": body,
            })
            used_chars += len(body)
        return evidence

    @staticmethod
    def latest_user_content(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user" and isinstance(message.get("content"), str):
                return message["content"]
        return ""


class StructuredAnswerRenderer:
    def __init__(self, settings: AnswerSafetySettings) -> None:
        self._settings = settings

    def limit_sections(self, sections: list[AnswerSection]) -> tuple[list[AnswerSection], bool]:
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
