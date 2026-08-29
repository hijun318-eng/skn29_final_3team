from __future__ import annotations

import re
from typing import Any

from .answer_contracts import AnswerClaim, AnswerResponse, AnswerSection, AnswerStatus, Citation
from .answer_io import AnswerPromptParser, StructuredAnswerRenderer
from .answer_safety import AnswerSafetySettings, EvidenceSafetyGate
from .manual_article_formatter import ManualArticleFormatter


class EvidenceBoundAnswerComposer:
    """Build one deterministic answer contract from evidence that passed the safety gate."""

    _INTENT_PATTERN = re.compile(r"요청 의도:\s*(?P<intent>[A-Z_]+)")
    _ANSWER_TYPE_BY_INTENT = {
        "PROCESS": "PROCEDURE", "IMMEDIATE_ACTION": "IMMEDIATE",
        "DECISION_CRITERIA": "CRITERIA", "REGULATION_CHECK": "POLICY",
        "COMPARISON": "COMPARE", "SUMMARY": "SUMMARY",
    }
    _COMPARISON_PATTERN = re.compile(r"비교|차이|공통점|vs\.?", re.IGNORECASE)
    _APPROVAL_OWNER_PATTERN = re.compile(r"승인\s*담당자|승인권자|누가\s*승인")

    def __init__(self, settings: AnswerSafetySettings | None = None) -> None:
        self._settings = settings or AnswerSafetySettings.load()
        self._parser = AnswerPromptParser(self._settings)
        self._gate = EvidenceSafetyGate(self._settings)
        self._formatter = ManualArticleFormatter()
        self._renderer = StructuredAnswerRenderer(self._settings)

    def compose(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        content = self._parser.latest_user_content(messages)
        query = self._parser.extract_query(content)
        intent_match = self._INTENT_PATTERN.search(content)
        intent = intent_match.group("intent") if intent_match else "SUMMARY"
        answer_type = self._ANSWER_TYPE_BY_INTENT.get(intent, "SUMMARY")
        evidence = self._parser.extract_evidence(content)
        if not evidence:
            return self._response(AnswerStatus.NO_EVIDENCE, answer_type=answer_type)

        targets = self._formatter.target_numbers(query, answer_type)
        groups = self._gate.ranked_groups(evidence, query, targets) if query else self._group(evidence)
        requested = self._formatter.specific_numbers(query)
        if not groups or (requested and not any(
            set(requested).intersection(self._formatter.available_numbers(group))
            for group in groups
        )):
            return self._response(AnswerStatus.NO_EVIDENCE, answer_type=answer_type)

        conflicts = self._gate.detect_conflicts(groups, query, answer_type, self._formatter)
        if conflicts:
            conflict_ids = list(dict.fromkeys(
                evidence_id for conflict in conflicts for evidence_id in conflict.evidence_ids
            ))
            return self._response(
                AnswerStatus.POTENTIAL_CONFLICT,
                answer_type=answer_type,
                answer="서로 다른 문서 버전의 근거가 충돌합니다.",
                citations=self._citations_for_ids(conflict_ids, evidence),
                conflicts=conflicts,
            )

        selected = groups[:2] if self._is_comparison(content, answer_type) else groups[:1]
        sections = [section for group in selected for section in self._sections(group, query, answer_type)]
        if self._APPROVAL_OWNER_PATTERN.search(query):
            sections = self._approval_sections(selected)
        if not sections and not requested:
            sections = [self._generic_section(group) for group in selected if group]
        if not sections:
            return self._response(AnswerStatus.NO_EVIDENCE, answer_type=answer_type)

        limited, truncated = self._renderer.limit_sections(sections)
        citations = self._renderer.citations(limited, evidence)
        limitations = ["로컬 근거 기반 응답 모드"]
        if truncated:
            limitations.append("답변 길이 제한으로 일부 항목을 생략했습니다.")
        return self._response(
            AnswerStatus.ANSWER,
            answer_type=answer_type,
            answer=self._renderer.render(limited, citations),
            sections=limited,
            citations=citations,
            limitations=limitations,
        )

    def _sections(self, group: list[dict[str, Any]], query: str, answer_type: str) -> list[AnswerSection]:
        first = group[0]
        return [
            AnswerSection(
                title=section.title,
                article_number=section.number,
                document_id=str(first.get("manual_id") or first.get("document_id") or ""),
                document_title=str(first.get("title") or ""),
                document_version=str(first.get("version") or ""),
                claims=[AnswerClaim(text=claim.text, evidence_ids=list(claim.evidence_ids)) for claim in section.claims],
            )
            for section in self._formatter.build_sections(group, query, answer_type)
        ]

    def _approval_sections(self, groups: list[list[dict[str, Any]]]) -> list[AnswerSection]:
        sections: list[AnswerSection] = []
        for group in groups:
            first = group[0]
            body = "\n".join(str(item.get("body") or "") for item in group)
            claims: list[AnswerClaim] = []
            for label in ("주관 담당", "협조 담당"):
                match = re.search(rf"{label}\s*\n\s*([^\n•]+)", body)
                if match:
                    claims.append(AnswerClaim(text=f"{label}: {match.group(1).strip()}", evidence_ids=[str(first["evidence_id"])]))
            claims.append(AnswerClaim(
                text="승인 담당자의 구체 직책은 문서에 별도로 명시되지 않았습니다.",
                evidence_ids=[str(first["evidence_id"])],
            ))
            sections.append(AnswerSection(
                title="승인 담당 근거", article_number=2,
                document_id=str(first.get("manual_id") or first.get("document_id") or ""),
                document_title=str(first.get("title") or ""),
                document_version=str(first.get("version") or ""), claims=claims,
            ))
        return sections

    @staticmethod
    def _generic_section(group: list[dict[str, Any]]) -> AnswerSection:
        first = group[0]
        return AnswerSection(
            title=str(first.get("section_title") or "근거"),
            document_id=str(first.get("manual_id") or first.get("document_id") or ""),
            document_title=str(first.get("title") or ""),
            document_version=str(first.get("version") or ""),
            claims=[
                AnswerClaim(text=" ".join(str(item.get("body") or "").split()), evidence_ids=[str(item["evidence_id"])])
                for item in group if str(item.get("body") or "").strip()
            ],
        )

    @staticmethod
    def _group(evidence: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in evidence:
            key = (
                str(item.get("manual_id") or item.get("document_id") or item.get("title") or "local"),
                str(item.get("version") or ""),
            )
            grouped.setdefault(key, []).append(item)
        return [grouped[key] for key in sorted(grouped)]

    def _is_comparison(self, query: str, answer_type: str) -> bool:
        return answer_type == "COMPARE" or bool(self._COMPARISON_PATTERN.search(query))

    @staticmethod
    def _citations_for_ids(ids: list[str], evidence: list[dict[str, Any]]) -> list[Citation]:
        by_id = {str(item.get("evidence_id")): item for item in evidence}
        return [Citation(evidence_id=item_id, citation=str(by_id[item_id].get("citation") or item_id)) for item_id in ids if item_id in by_id]

    @staticmethod
    def _response(
        status: AnswerStatus,
        *,
        answer_type: str,
        answer: str = "검색된 근거가 없습니다.",
        sections: list[AnswerSection] | None = None,
        citations: list[Citation] | None = None,
        conflicts: list[Any] | None = None,
        limitations: list[str] | None = None,
    ) -> dict[str, Any]:
        response = AnswerResponse(
            request_id="local-answer", trace_id="local-answer", status=status,
            answer=answer, answer_type=answer_type,
            summary=[claim.text for section in sections or [] for claim in section.claims],
            sections=sections or [], citations=citations or [], conflicts=conflicts or [],
            limitations=limitations or ["로컬 근거 기반 응답 모드"],
        )
        return response.model_dump(mode="json")
