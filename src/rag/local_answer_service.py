from __future__ import annotations

import json
import re
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .manual_article_formatter import ManualArticleFormatter


class ChatCompletionRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceBoundAnswerComposer:
    """Create deterministic, evidence-only OpenAI-compatible answer payloads."""

    _EVIDENCE_PATTERN = re.compile(r"ID:\s*(?P<evidence_id>[^\n]+)\n(?P<text>.*?)(?=\n\nID:|\n\nEND_EVIDENCE|\Z)", re.DOTALL)
    _QUERY_PATTERN = re.compile(r"질문:\s*(?P<query>.*?)(?:\n요청 의도:\s*[A-Z_]+)?\n\n제공된 근거", re.DOTALL)
    _INTENT_PATTERN = re.compile(r"요청 의도:\s*(?P<intent>[A-Z_]+)")
    _COMPARISON_PATTERN = re.compile(r"비교|차이|다른 점|어떻게 달라|vs\.?", re.IGNORECASE)
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

    @staticmethod
    def _snippet_limit() -> int:
        try:
            return max(1, int(os.getenv("RAG_SNIPPET_MAX_CHARS", "1800").strip() or "1800"))
        except ValueError:
            return 1800

    def compose(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        user_content = self._latest_user_content(messages)
        query = self._extract_query(user_content)
        intent_match = self._INTENT_PATTERN.search(user_content)
        intent = intent_match.group("intent") if intent_match else "SUMMARY"
        requested_answer_type = self._ANSWER_TYPE_BY_INTENT.get(intent, "SUMMARY")
        is_follow_up = "후속 질문:" in user_content or "현재 질문:" in user_content
        evidence = self._extract_evidence(user_content)
        if not evidence:
            return {
                "request_id": "local-answer",
                "trace_id": "local-answer",
                "status": "NO_EVIDENCE",
                "answer": "검색된 근거가 없습니다.",
                "citations": [],
                "conflicts": [],
                "limitations": ["로컬 근거 기반 응답 모드"],
                "model_version": "rag-local-answer-v1",
            }
        formatter = ManualArticleFormatter()
        comparison_items = self._best_items_by_title(evidence, query)
        is_comparison = (
            requested_answer_type == "COMPARE" or bool(self._COMPARISON_PATTERN.search(query))
        ) and len(comparison_items) >= 2
        is_context_comparison = is_follow_up and len(comparison_items) >= 2
        structured_sections = ()
        if is_comparison:
            selected = comparison_items[:2]
        elif is_context_comparison:
            selected = comparison_items[:2]
        else:
            routed_manual_id = evidence[0]["manual_id"]
            document_candidates = [
                item for item in evidence if item["manual_id"] == routed_manual_id
            ]
            primary = self._best_item(document_candidates, query)
            document_evidence = document_candidates
            if requested_answer_type != "SUMMARY":
                try:
                    primary_page = int(primary.get("page_start") or 0)
                except (TypeError, ValueError):
                    primary_page = 0
                nearby = [
                    item
                    for item in document_candidates
                    if primary_page
                    and str(item.get("page_start") or "").isdigit()
                    and abs(int(item["page_start"]) - primary_page) <= 1
                ]
                if nearby:
                    document_evidence = nearby
            structured_sections = formatter.build_sections(
                document_evidence,
                query,
                requested_answer_type,
            )
            used_evidence_ids = {
                evidence_id
                for section in structured_sections
                for claim in section.claims
                for evidence_id in claim.evidence_ids
            }
            selected = (
                [item for item in document_evidence if item["evidence_id"] in used_evidence_ids]
                if used_evidence_ids
                else [primary]
            )
        citations = [
            {
                "evidence_id": item["evidence_id"],
                "citation": item["citation"] or self._readable_excerpt(item["body"], query, 1)[0][:240],
            }
            for item in selected
        ]
        if is_comparison or is_context_comparison:
            answer = self._comparison_answer(
                selected,
                query,
                citations,
                area="비교" if is_comparison else "관련 기준",
            )
            answer_type = "COMPARE"
        else:
            item = selected[0]
            if structured_sections:
                rendered = "\n\n".join(
                    formatter.render_section(section) for section in structured_sections
                )
                body = (
                    f"[문서 요약]\n\n{rendered}"
                    if requested_answer_type == "SUMMARY"
                    else f"[비교 기준]\n\n{rendered}"
                    if requested_answer_type == "COMPARE"
                    else rendered
                )
                section_title = " / ".join(
                    f"제{section.number}조 {section.title}" for section in structured_sections
                )
            else:
                excerpt = self._readable_excerpt(item["body"], query, 8)
                section_title = self._section_title(item, item["body"])
                body = f"[{self._heading(query, intent)}]\n\n" + "\n\n".join(excerpt)
            answer = (
                f"문서명: {item['title'] or '확인 불가'}\n"
                f"지침번호: {item['manual_id'] or '확인 불가'}\n"
                f"영역: {section_title}\n"
                f"본문내용:\n{body}\n"
                "근거: " + " / ".join(citation["citation"] for citation in citations)
            )
        return {
            "request_id": "local-answer",
            "trace_id": "local-answer",
            "status": "ANSWER",
            "answer": answer,
            "answer_type": answer_type if (is_comparison or is_context_comparison) else requested_answer_type,
            "summary": self._answer_summary(selected, query, is_comparison or is_context_comparison),
            "citations": citations,
            "conflicts": [],
            "limitations": ["로컬 근거 기반 응답 모드: 제공된 검색 근거만 사용"],
            "model_version": "rag-local-answer-v1",
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
            f"본문내용:\n[{self._comparison_heading(query)}]\n\n" + "\n\n".join(sections) + "\n"
            "근거: " + " / ".join(item["citation"] for item in citations)
        )

    @staticmethod
    def _heading(query: str, intent: str) -> str:
        text = " ".join(query.lower().split())
        if "위험" in text and any(term in text for term in ("분류", "판단", "기준", "구분")):
            return "위험 판단 기준"
        if "보고" in text and any(term in text for term in ("즉시", "바로", "기준", "시점", "상황")):
            return "즉시 보고 기준"
        if any(term in text for term in ("남길 기록", "기록 항목", "무엇을 기록")):
            return "반드시 남길 기록"
        if any(term in text for term in ("금지", "하면 안", "해서는 안")):
            return "금지사항"
        if any(term in text for term in ("업무 종료", "종료 기준", "완료 기준", "마무리")):
            return "업무 종료 기준"
        if any(term in text for term in ("예시", "사례")):
            return "상황별 적용 예시"
        if intent == "IMMEDIATE_ACTION":
            return "즉시 조치"
        if intent == "DECISION_CRITERIA":
            return "판단 기준"
        if intent == "COMPARISON":
            return "비교 기준"
        if intent == "SUMMARY":
            return "문서 요약"
        if any(term in text for term in ("처리 순서", "처리 절차", "어떻게", "진행 순서", "먼저")):
            return "처리 순서"
        return {
            "IMMEDIATE_ACTION": "즉시 조치",
            "DECISION_CRITERIA": "판단 기준",
            "REGULATION_CHECK": "규정·조건",
            "COMPARISON": "비교 기준",
            "SUMMARY": "문서 요약",
        }.get(intent, "처리 순서" if intent == "PROCESS" else "문서 안내")

    @classmethod
    def _comparison_heading(cls, query: str) -> str:
        heading = cls._heading(query, "COMPARISON")
        return heading if heading.endswith("비교 기준") else f"{heading} 비교"

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
    def _comparison_items(evidence: list[dict[str, str]]) -> list[dict[str, str]]:
        selected: list[dict[str, str]] = []
        titles: set[str] = set()
        for item in evidence:
            title = item["title"].strip()
            if title and title not in titles:
                selected.append(item)
                titles.add(title)
        return selected

    def _best_items_by_title(
        self,
        evidence: list[dict[str, str]],
        query: str,
    ) -> list[dict[str, str]]:
        grouped: dict[str, list[dict[str, str]]] = {}
        for item in evidence:
            grouped.setdefault(item["title"].strip(), []).append(item)
        return [self._best_item(items, query) for items in grouped.values() if items]

    @staticmethod
    def _best_item(evidence: list[dict[str, str]], query: str) -> dict[str, str]:
        raw_tokens = [
            token
            for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", query)
            if token not in {"알려줘", "어떻게", "기준을", "관련", "대한"}
        ]
        tokens = list(dict.fromkeys(
            variant
            for token in raw_tokens
            for variant in (
                (token, token[:3], token[:2]) if len(token) >= 4 else (token,)
            )
        ))
        keywords = list(dict.fromkeys(tokens + [
            term
            for term in ("즉시", "보고", "안전", "시설", "위험", "통제", "중단", "승인", "연락", "확인")
            if term in query
        ]))
        return max(
            evidence,
            key=lambda item: sum(
                (item["body"].count(keyword) * 3) + item["title"].count(keyword)
                for keyword in keywords
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
        keywords = [
            token
            for token in ("즉시", "보고", "안전", "시설", "위험", "통제", "중단", "승인", "연락", "확인")
            if token in query
        ]
        ranked = sorted(
            enumerate(unique),
            key=lambda pair: (-sum(keyword in pair[1] for keyword in keywords), pair[0]),
        )
        selected = [line for _, line in ranked[:limit]]
        return selected or ["확인 가능한 본문이 없습니다."]

    @classmethod
    def _section_title(cls, item: dict[str, str], body: str) -> str:
        section_title = item["section_title"]
        if section_title and section_title != "페이지 본문":
            return section_title
        article = re.search(r"제\s*(\d+)\s*조", body)
        return f"제{article.group(1)}조" if article else "확인 불가"

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
                    "title": fields.get("문서명", ""),
                    "manual_id": fields.get("지침번호", ""),
                    "section_title": fields.get("영역", ""),
                    "citation": fields.get("근거", ""),
                    "body": body.strip() if separator else text,
                    "page_start": fields.get("페이지", ""),
                    "chunk_index": index,
                }
            )
        return evidence


def create_app() -> FastAPI:
    app = FastAPI(title="Answervice Local Evidence Answer", version="1.0")
    composer = EvidenceBoundAnswerComposer()

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
