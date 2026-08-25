from __future__ import annotations

import json
import re
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


class ChatCompletionRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceBoundAnswerComposer:
    """Create deterministic, evidence-only OpenAI-compatible answer payloads."""

    _EVIDENCE_PATTERN = re.compile(r"ID:\s*(?P<evidence_id>[^\n]+)\n(?P<text>.*?)(?=\n\nID:|\n\nEND_EVIDENCE|\Z)", re.DOTALL)
    _QUERY_PATTERN = re.compile(r"질문:\s*(?P<query>.*?)\n\n제공된 근거", re.DOTALL)
    _COMPARISON_PATTERN = re.compile(r"비교|차이|다른 점|어떻게 달라|vs\.?", re.IGNORECASE)
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
        comparison_items = self._comparison_items(evidence)
        is_comparison = bool(self._COMPARISON_PATTERN.search(query)) and len(comparison_items) >= 2
        if is_comparison:
            selected = comparison_items[:2]
        elif is_follow_up and len(comparison_items) >= 2:
            selected = self._best_items_by_title(evidence, query)[:2]
        else:
            selected = [self._best_item(evidence, query)]
        citations = [
            {
                "evidence_id": item["evidence_id"],
                "citation": item["citation"] or self._readable_excerpt(item["body"], query, 1)[0][:240],
            }
            for item in selected
        ]
        if is_comparison or len(selected) >= 2:
            answer = self._comparison_answer(
                selected,
                query,
                citations,
                area="비교" if is_comparison else "관련 기준",
            )
            answer_type = "COMPARE"
        else:
            item = selected[0]
            excerpt = self._readable_excerpt(item["body"], query, 5)
            section_title = self._section_title(item, item["body"])
            answer = (
                f"문서명: {item['title'] or '확인 불가'}\n"
                f"지침번호: {item['manual_id'] or '확인 불가'}\n"
                f"영역: {section_title}\n"
                f"본문내용:\n" + "\n\n".join(excerpt) + "\n"
                f"근거: {citations[0]['citation']}"
            )
        return {
            "request_id": "local-answer",
            "trace_id": "local-answer",
            "status": "ANSWER",
            "answer": answer,
            "answer_type": answer_type if is_comparison else "SUMMARY",
            "summary": self._answer_summary(selected, query, len(selected) >= 2),
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
            "본문내용:\n" + "\n\n".join(sections) + "\n"
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
        tokens = [
            token
            for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", query)
            if token not in {"알려줘", "어떻게", "기준을", "관련", "대한"}
        ]
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
        bounded = body[: self._snippet_limit()].replace("\r", "\n")
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
        if len(unique) > limit:
            selected.append("자세한 내용은 PDF 원문 보기를 확인하세요.")
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
        for match in self._EVIDENCE_PATTERN.finditer(content):
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
