"""검색 evidence 밖의 사실을 쓰지 않는 결정론적 OpenAI-compatible 답변 service다."""

from __future__ import annotations

import re
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .answer_contracts import GroundedModelOutput
from .answer_safety import AnswerSafetySettings, EvidenceSafetyGate
from .answer_prompt import parse_answer_input
from .manual_article_formatter import ManualArticleFormatter, ManualClaim, ManualSection
from .report_evidence_formatter import ReportEvidenceFormatter, ReportSection


class ChatCompletionRequest(BaseModel):
    """로컬 answer endpoint가 받을 role/content message 배열을 검증한다."""

    messages: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceBoundAnswerComposer:
    """검색 근거의 관련성·조항·충돌을 검증해 결정론적 답변만 구성한다."""

    _ANSWER_TYPE_BY_INTENT = {
        "PROCESS": "PROCEDURE",
        "IMMEDIATE_ACTION": "IMMEDIATE",
        "DECISION_CRITERIA": "CRITERIA",
        "REGULATION_CHECK": "POLICY",
        "COMPARISON": "COMPARE",
        "SUMMARY": "SUMMARY",
    }
    _LABELS = {
        "주관 담당",
        "협조 담당",
        "적용 범위",
        "문서 성격",
        "이 지침을 사용하는 상황",
        "시작 전에 확인할 사항",
        "구체적인 판단·처리 기준",
    }

    def __init__(self, settings: AnswerSafetySettings | None = None) -> None:
        self._settings = settings or AnswerSafetySettings()
        self._safety = EvidenceSafetyGate(self._settings)
        self._formatter = ManualArticleFormatter()
        self._report_formatter = ReportEvidenceFormatter()

    @staticmethod
    def _snippet_limit() -> int:
        try:
            return max(1, int(os.getenv("RAG_SNIPPET_MAX_CHARS", "1800").strip() or "1800"))
        except ValueError:
            return 1800

    def compose(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """최신 사용자 prompt의 근거만 사용해 공통 RAG 답변 계약을 반환한다."""
        user_content = self._latest_user_content(messages)
        answer_input = parse_answer_input(user_content)
        if answer_input is None:
            return self._no_evidence("SUMMARY")
        query = answer_input["query"].strip()
        intent = answer_input["intent"]
        requested_answer_type = self._ANSWER_TYPE_BY_INTENT.get(intent, "SUMMARY")
        evidence = self._bounded_evidence(answer_input["evidence"])
        if evidence is None:
            return self._no_evidence(
                requested_answer_type,
                limitation="입력 근거가 로컬 답변 한도를 넘어 일부를 생략하지 않고 거부했습니다.",
            )
        if not evidence:
            return self._no_evidence(requested_answer_type)
        target_numbers = self._formatter.target_numbers(query, requested_answer_type)
        groups = self._safety.ranked_groups(evidence, query, target_numbers)
        if not groups:
            return self._no_evidence(requested_answer_type)
        conflicts = self._safety.detect_conflicts(
            groups,
            query,
            requested_answer_type,
            self._formatter,
        )
        if conflicts:
            evidence_ids = list(dict.fromkeys(
                evidence_id
                for conflict in conflicts
                for evidence_id in conflict.evidence_ids
            ))
            return self._result(
                status="POTENTIAL_CONFLICT",
                answer="\n".join(conflict.description for conflict in conflicts),
                answer_type=requested_answer_type,
                citations=self._citations(evidence, evidence_ids),
                conflicts=[conflict.model_dump(mode="json") for conflict in conflicts],
                limitations=["상충하는 문서 버전을 임의로 선택하지 않았습니다."],
            )
        comparison_items = [self._best_item(group, query) for group in groups]
        is_comparison = requested_answer_type == "COMPARE" and len(comparison_items) >= 2
        if is_comparison:
            selected = comparison_items[:2]
        else:
            document_evidence = groups[0]
            if self._document_type(document_evidence) == "INTERNAL_REPORT":
                return self._report_answer(
                    document_evidence,
                    query,
                    requested_answer_type,
                )
            structured_sections = self._formatter.build_sections(
                document_evidence,
                query,
                requested_answer_type,
            )
            if not structured_sections:
                return self._no_evidence(requested_answer_type)
            limited_sections, truncated = self._limit_sections(structured_sections)
            used_evidence_ids = list(dict.fromkeys(
                evidence_id
                for section in limited_sections
                for claim in section.claims
                for evidence_id in claim.evidence_ids
            ))
            citations = self._citations(document_evidence, used_evidence_ids)
            rendered = "\n\n".join(
                self._formatter.render_section(section) for section in limited_sections
            )
            body = (
                f"[문서 요약]\n\n{rendered}"
                if requested_answer_type == "SUMMARY"
                else rendered
            )
            primary = self._best_item(document_evidence, query)
            answer = (
                f"문서명: {primary['title'] or '확인 불가'}\n"
                f"지침번호: {primary['manual_id'] or '확인 불가'}\n"
                "영역: "
                + " / ".join(
                    f"제{section.number}조 {section.title}" for section in limited_sections
                )
                + f"\n본문내용:\n{body}\n"
                + "근거: "
                + " / ".join(item["citation"] for item in citations)
            )
            limitations = ["로컬 근거 기반 응답 모드: 제공된 검색 근거만 사용"]
            if truncated:
                limitations.append("답변 길이 제한에 따라 조항별 항목 수를 제한했습니다.")
            return self._result(
                status="ANSWER",
                answer=answer,
                answer_type=requested_answer_type,
                summary=[
                    claim.text
                    for section in limited_sections
                    for claim in section.claims
                ],
                sections=[self._section_payload(section) for section in limited_sections],
                citations=citations,
                limitations=limitations,
            )
        citations = self._citations(
            selected,
            [item["evidence_id"] for item in selected],
        )
        answer = self._comparison_answer(
            selected,
            query,
            citations,
            area="비교",
        )
        answer_type = "COMPARE"
        sections = self._comparison_sections(selected, query)
        return self._result(
            status="ANSWER",
            answer=answer,
            answer_type=answer_type,
            summary=[
                claim["text"]
                for section in sections
                for claim in section["claims"]
            ],
            sections=sections,
            citations=citations,
            limitations=["로컬 근거 기반 응답 모드: 제공된 검색 근거만 사용"],
        )

    @staticmethod
    def _document_type(evidence: list[dict[str, Any]]) -> str:
        values = {
            str(item.get("document_type") or "").strip().upper()
            for item in evidence
        }
        return values.pop() if len(values) == 1 else ""

    def _report_answer(
        self,
        evidence: list[dict[str, Any]],
        query: str,
        answer_type: str,
    ) -> dict[str, Any]:
        """내부 보고서 heading·표·문장을 그대로 인용한 typed 답변을 구성한다."""

        sections = self._report_formatter.build_sections(
            evidence,
            EvidenceSafetyGate.query_terms(query),
        )
        limited_sections, truncated = self._limit_report_sections(sections)
        if not limited_sections:
            return self._no_evidence(answer_type)
        used_evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for section in limited_sections
                for claim in section.claims
                for evidence_id in claim.evidence_ids
            )
        )
        citations = self._citations(evidence, used_evidence_ids)
        if not citations:
            return self._no_evidence(answer_type)
        primary = self._best_item(evidence, query)
        rendered = "\n\n".join(
            self._report_formatter.render_section(section)
            for section in limited_sections
        )
        answer = (
            f"문서명: {primary['title'] or '확인 불가'}\n"
            f"문서ID: {primary['manual_id'] or '확인 불가'}\n"
            f"담당조직: {primary.get('owner_team') or '확인 불가'}\n"
            "영역: "
            + " / ".join(section.title for section in limited_sections)
            + f"\n본문내용:\n[보고서 근거 요약]\n\n{rendered}\n"
            + "근거: "
            + " / ".join(item["citation"] for item in citations)
        )
        limitations = ["로컬 근거 기반 응답 모드: 제공된 보고서 근거만 사용"]
        if truncated:
            limitations.append("답변 길이 제한에 따라 영역별 근거 수를 제한했습니다.")
        return self._result(
            status="ANSWER",
            answer=answer,
            answer_type=answer_type,
            summary=[
                claim.text
                for section in limited_sections
                for claim in section.claims
            ],
            sections=[
                self._report_section_payload(section, primary)
                for section in limited_sections
            ],
            citations=citations,
            limitations=limitations,
        )

    def _limit_report_sections(
        self,
        sections: tuple[ReportSection, ...],
    ) -> tuple[tuple[ReportSection, ...], bool]:
        """질문 관련성이 높은 보고서 근거를 전체 답변 한도 안에서 선별한다."""

        limited: list[ReportSection] = []
        truncated = False
        remaining_chars = self._settings.maximum_answer_chars
        remaining_points = self._settings.maximum_points_per_article
        for section in sections:
            claims: list[ManualClaim] = []
            for claim in section.claims[:remaining_points]:
                if len(claim.text) > remaining_chars:
                    truncated = True
                    break
                claims.append(claim)
                remaining_chars -= len(claim.text)
                remaining_points -= 1
            truncated = truncated or len(claims) < len(section.claims)
            if claims:
                limited.append(ReportSection(section.title, tuple(claims)))
            if remaining_chars <= 0 or remaining_points <= 0:
                break
        truncated = truncated or len(limited) < len(sections)
        return tuple(limited), truncated

    @staticmethod
    def _report_section_payload(
        section: ReportSection,
        document: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "title": section.title,
            "article_number": None,
            "document_id": str(document.get("manual_id") or ""),
            "document_title": str(document.get("title") or ""),
            "document_version": str(document.get("version") or ""),
            "claims": [
                {"text": claim.text, "evidence_ids": list(claim.evidence_ids)}
                for claim in section.claims
            ],
        }

    def _bounded_evidence(
        self,
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """로컬 한도를 넘는 입력은 본문을 자르지 않고 전체 요청을 fail-closed 처리한다."""

        if (
            len(evidence) > self._settings.maximum_chunks
            or sum(len(str(item.get("body") or "")) for item in evidence)
            > self._settings.maximum_evidence_chars
        ):
            return None
        return [dict(item) for item in evidence]

    def _limit_sections(
        self,
        sections: tuple[ManualSection, ...],
    ) -> tuple[tuple[ManualSection, ...], bool]:
        limited: list[ManualSection] = []
        truncated = False
        for section in sections:
            claims = section.claims[: self._settings.maximum_points_per_article]
            truncated = truncated or len(claims) < len(section.claims)
            limited.append(ManualSection(section.number, section.title, claims))
        return tuple(limited), truncated

    @staticmethod
    def _section_payload(section: ManualSection) -> dict[str, Any]:
        return {
            "title": section.title,
            "article_number": section.number,
            "claims": [
                {"text": claim.text, "evidence_ids": list(claim.evidence_ids)}
                for claim in section.claims
            ],
        }

    def _citations(
        self,
        evidence: list[dict[str, Any]],
        evidence_ids: list[str],
    ) -> list[dict[str, str]]:
        by_id = {
            str(item.get("evidence_id") or ""): item
            for item in evidence
        }
        return [
            {
                "evidence_id": evidence_id,
                "citation": str(by_id[evidence_id].get("citation") or "")
                or self._readable_excerpt(
                    str(by_id[evidence_id].get("body") or ""), "", 1
                )[0][:240],
            }
            for evidence_id in evidence_ids
            if evidence_id in by_id
        ]

    def _no_evidence(
        self,
        answer_type: str,
        limitation: str | None = None,
    ) -> dict[str, Any]:
        return self._result(
            status="NO_EVIDENCE",
            answer="검색된 근거가 없습니다.",
            answer_type=answer_type,
            limitations=[
                limitation
                or "관련성·검색점수·요청 조항 Gate를 통과한 근거가 없습니다."
            ],
        )

    @staticmethod
    def _result(
        *,
        status: str,
        answer: str,
        answer_type: str,
        summary: list[str] | None = None,
        sections: list[dict[str, Any]] | None = None,
        citations: list[dict[str, str]] | None = None,
        conflicts: list[dict[str, Any]] | None = None,
        limitations: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "rag-answer-v1.1",
            "request_id": "local-answer",
            "trace_id": "local-answer",
            "status": status,
            "answer": answer,
            "answer_type": answer_type,
            "summary": summary or [],
            "sections": sections or [],
            "citations": citations or [],
            "conflicts": conflicts or [],
            "limitations": limitations or [],
            "model_version": "rag-local-answer-v2",
        }

    def _comparison_answer(
        self,
        items: list[dict[str, str]],
        query: str,
        citations: list[dict[str, str]],
        area: str = "비교",
    ) -> str:
        sections = []
        for item in items:
            lines = self._readable_excerpt(item["body"], query, 3)
            sections.append(f"[{item['title'] or '확인 불가'}]\n" + "\n\n".join(lines))
        return (
            "문서명: " + " / ".join(item["title"] or "확인 불가" for item in items) + "\n"
            "지침번호: " + " / ".join(item["manual_id"] or "확인 불가" for item in items) + "\n"
            f"영역: {area}\n"
            "본문내용:\n[문서 비교]\n\n" + "\n\n".join(sections) + "\n"
            "근거: " + " / ".join(item["citation"] for item in citations)
        )

    def _comparison_sections(
        self,
        items: list[dict[str, str]],
        query: str,
    ) -> list[dict[str, Any]]:
        """비교 문서별 발췌를 해당 evidence ID와 연결한 공통 section 계약으로 만든다."""

        return [
            {
                "title": item.get("section_title") or "비교 근거",
                "article_number": None,
                "document_id": item.get("manual_id") or "",
                "document_title": item.get("title") or "",
                "document_version": item.get("version") or "",
                "claims": [
                    {
                        "text": line,
                        "evidence_ids": [item["evidence_id"]],
                    }
                    for line in self._extractive_claims(item, query, 3)
                ],
            }
            for item in items
        ]

    def _extractive_claims(
        self,
        item: dict[str, str],
        query: str,
        limit: int,
    ) -> list[str]:
        """manual·report parser의 전체 segment만 관련성 순으로 골라 비교 claim을 만든다."""

        candidates = list(
            self._formatter.claim_segments(
                item["body"],
                item.get("section_title") or "",
            )
        ) or list(self._report_formatter.claim_segments(item["body"]))
        query_terms = EvidenceSafetyGate.query_terms(query)
        ranked = sorted(
            enumerate(dict.fromkeys(candidates)),
            key=lambda pair: (
                -sum(term in pair[1].lower() for term in query_terms),
                pair[0],
            ),
        )
        return [line for _, line in ranked[:limit]]

    def _answer_summary(
        self,
        items: list[dict[str, str]],
        query: str,
        is_comparison: bool,
    ) -> list[str]:
        if is_comparison:
            return [
                f"[{item['title'] or '확인 불가'}]\n" + "\n".join(self._readable_excerpt(item["body"], query, 3))
                for item in items
            ]
        return self._readable_excerpt(items[0]["body"], query, 5)

    @staticmethod
    def _best_item(evidence: list[dict[str, str]], query: str) -> dict[str, str]:
        query_terms = EvidenceSafetyGate.query_terms(query)
        return max(
            evidence,
            key=lambda item: sum(
                (item["body"].lower().count(term) * 3)
                + item["title"].lower().count(term)
                for term in query_terms
            ),
        )

    def _readable_excerpt(self, body: str, query: str, limit: int) -> list[str]:
        bounded = re.sub(
            r"\s*내부\s*업무지침\s*[·ㆍ]\s*현장\s*실행형\s*[·ㆍ]\s*의미전달\s*검증완료본",
            "",
            body[: self._snippet_limit()],
        ).replace("\r", "\n")
        compact = re.sub(r"\s+", " ", bounded).strip()
        candidates: list[str] = []
        intro = compact.split(" 주관 담당 ", 1)[0].strip()
        intro = re.split(r"[•▪]", intro, maxsplit=1)[0].strip()
        sentence = re.search(r"^.*?[.!?](?:\s|$)", intro)
        if sentence:
            intro = sentence.group(0).strip()
        if len(intro) >= 8:
            candidates.append(intro)
        for match in re.finditer(r"[•▪]\s*(.*?)(?=\s+[•▪]|\s+제\s*\d+\s*조\.?|$)", compact):
            line = re.sub(r"\s+", " ", match.group(1)).strip(" -•▪")
            if len(line) >= 8 and line not in self._LABELS:
                candidates.append(line)
        if not candidates:
            candidates = [
                line
                for line in (re.sub(r"\s+", " ", value).strip() for value in bounded.splitlines())
                if len(line) >= 8 and line not in self._LABELS
            ]
        unique = list(dict.fromkeys(candidates))
        query_terms = EvidenceSafetyGate.query_terms(query)
        ranked = sorted(
            enumerate(unique),
            key=lambda pair: (
                -sum(term in pair[1].lower() for term in query_terms),
                pair[0],
            ),
        )
        selected = [line for _, line in ranked[:limit]]
        return selected or ["확인 가능한 본문이 없습니다."]

    def _extract_query(self, content: str) -> str:
        payload = parse_answer_input(content)
        return payload["query"].strip() if payload is not None else ""

    @staticmethod
    def _latest_user_content(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user" and isinstance(message.get("content"), str):
                return message["content"]
        return ""

    def _extract_evidence(self, content: str) -> list[dict[str, str]]:
        payload = parse_answer_input(content)
        if payload is None:
            return []
        return [dict(item) for item in payload["evidence"]]


def _grounded_model_output(answer: dict[str, Any]) -> GroundedModelOutput:
    """결정론적 composer 결과를 외부·로컬 공통 최소 모델 계약으로 축약한다."""

    status = "ANSWER" if answer.get("status") == "ANSWER" else "NO_EVIDENCE"
    sections = []
    if status == "ANSWER":
        sections = [
            {
                "title": str(section.get("title") or "근거 기반 답변"),
                "claims": [
                    {
                        "text": str(claim.get("text") or ""),
                        "evidence_ids": list(claim.get("evidence_ids") or []),
                    }
                    for claim in section.get("claims") or []
                ],
            }
            for section in answer.get("sections") or []
        ]
    return GroundedModelOutput(status=status, sections=sections)


def create_app() -> FastAPI:
    """health와 evidence-bound chat completion route를 포함한 FastAPI app을 만든다."""

    app = FastAPI(title="Answervice Local Evidence Answer", version="1.0")
    composer = EvidenceBoundAnswerComposer(AnswerSafetySettings.load())

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        return {"status": "healthy"}

    @app.post("/v1/chat/completions")
    def chat_completion(request: ChatCompletionRequest) -> dict[str, Any]:
        content = _grounded_model_output(
            composer.compose(request.messages)
        ).model_dump_json()
        return {
            "id": "rag-local-answer",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        }

    return app


app = create_app()
