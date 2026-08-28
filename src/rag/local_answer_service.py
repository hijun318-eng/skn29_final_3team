from __future__ import annotations

import json
import re
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .answer_safety import AnswerSafetySettings, EvidenceSafetyGate
from .manual_article_formatter import ManualArticleFormatter, ManualSection


class ChatCompletionRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceBoundAnswerComposer:
    """검색 근거의 관련성·조항·충돌을 검증해 결정론적 답변만 구성한다."""

    _EVIDENCE_PATTERN = re.compile(r"ID:\s*(?P<evidence_id>[^\n]+)\n(?P<text>.*?)(?=\n\nID:|\n\nEND_EVIDENCE|\Z)", re.DOTALL)
    _QUERY_PATTERN = re.compile(r"질문:\s*(?P<query>.*?)(?:\n요청 의도:\s*[A-Z_]+)?\n\n제공된 근거", re.DOTALL)
    _INTENT_PATTERN = re.compile(r"요청 의도:\s*(?P<intent>[A-Z_]+)")
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

    @staticmethod
    def _snippet_limit() -> int:
        try:
            return max(1, int(os.getenv("RAG_SNIPPET_MAX_CHARS", "1800").strip() or "1800"))
        except ValueError:
            return 1800

    def compose(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """최신 사용자 prompt의 근거만 사용해 공통 RAG 답변 계약을 반환한다."""
        user_content = self._latest_user_content(messages)
        query = self._extract_query(user_content)
        intent_match = self._INTENT_PATTERN.search(user_content)
        intent = intent_match.group("intent") if intent_match else "SUMMARY"
        requested_answer_type = self._ANSWER_TYPE_BY_INTENT.get(intent, "SUMMARY")
        evidence = self._bounded_evidence(self._extract_evidence(user_content))
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
        return self._result(
            status="ANSWER",
            answer=answer,
            answer_type=answer_type,
            summary=self._answer_summary(selected, query, True),
            citations=citations,
            limitations=["로컬 근거 기반 응답 모드: 제공된 검색 근거만 사용"],
        )

    def _bounded_evidence(
        self,
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        bounded: list[dict[str, Any]] = []
        consumed = 0
        for item in evidence[: self._settings.maximum_chunks]:
            body = str(item.get("body") or "")
            remaining = self._settings.maximum_evidence_chars - consumed
            if remaining <= 0:
                break
            bounded.append({**item, "body": body[:remaining]})
            consumed += min(len(body), remaining)
        return bounded

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

    def _no_evidence(self, answer_type: str) -> dict[str, Any]:
        return self._result(
            status="NO_EVIDENCE",
            answer="검색된 근거가 없습니다.",
            answer_type=answer_type,
            limitations=["관련성·검색점수·요청 조항 Gate를 통과한 근거가 없습니다."],
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
        match = self._QUERY_PATTERN.search(content)
        query = match.group("query").strip() if match else ""
        if "후속 질문:" in query:
            return query.rsplit("후속 질문:", 1)[1].strip()
        if "현재 질문:" in query:
            return query.rsplit("현재 질문:", 1)[1].strip()
        return query

    @staticmethod
    def _latest_user_content(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user" and isinstance(message.get("content"), str):
                return message["content"]
        return ""

    def _extract_evidence(self, content: str) -> list[dict[str, str]]:
        evidence: list[dict[str, str]] = []
        for index, match in enumerate(self._EVIDENCE_PATTERN.finditer(content)):
            evidence_id = match.group("evidence_id").strip()
            text = match.group("text").strip()
            if not evidence_id or not text:
                continue
            metadata, separator, body = text.partition("본문내용:\n")
            fields = {
                key: value.strip()
                for key, value in (
                    line.split(":", 1)
                    for line in metadata.splitlines()
                    if ":" in line
                )
            }
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "document_id": fields.get("문서ID", ""),
                    "title": fields.get("문서명", ""),
                    "manual_id": fields.get("지침번호", ""),
                    "version": fields.get("버전", ""),
                    "section_title": fields.get("영역", ""),
                    "citation": fields.get("근거", ""),
                    "body": body.strip() if separator else text,
                    "page_start": fields.get("페이지", ""),
                    "chunk_index": fields.get("청크순서", index),
                    "score": fields.get("검색점수", ""),
                    "document_status": fields.get("문서상태", ""),
                    "approval_status": fields.get("승인상태", ""),
                    "validity_status": fields.get("유효성상태", ""),
                    "effective_from": fields.get("유효시작일", ""),
                    "effective_to": fields.get("유효종료일", ""),
                }
            )
        return evidence


def create_app() -> FastAPI:
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
        content = json.dumps(composer.compose(request.messages), ensure_ascii=False)
        return {
            "id": "rag-local-answer",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        }

    return app


app = create_app()
