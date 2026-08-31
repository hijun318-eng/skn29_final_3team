"""RAG 답변의 evidence 용량·관련성·문서 버전 충돌 Gate를 구현한다."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any

from .answer_contracts import Conflict
from .manual_article_formatter import ManualArticleFormatter


@dataclass(frozen=True)
class AnswerSafetySettings:
    """답변에 허용할 검색 점수·evidence·claim·문자 상한을 보존한다."""

    minimum_relevance_score: float = 0.18
    maximum_evidence_chars: int = 30000
    maximum_chunks: int = 10
    maximum_points_per_article: int = 50
    maximum_answer_chars: int = 20000

    @classmethod
    def load(cls, path: Path | None = None) -> "AnswerSafetySettings":
        """JSON과 환경 override를 읽고 모든 답변 안전 한도의 범위를 검증한다."""

        config_path = path or Path(os.getenv("RAG_ANSWER_CONFIG", "config/rag/answer.json"))
        payload = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        settings = cls(
            minimum_relevance_score=float(os.getenv(
                "RAG_ANSWER_MIN_RELEVANCE_SCORE",
                payload.get("minimum_relevance_score", cls.minimum_relevance_score),
            )),
            maximum_evidence_chars=int(os.getenv(
                "RAG_ANSWER_MAX_EVIDENCE_CHARS",
                payload.get("maximum_evidence_chars", cls.maximum_evidence_chars),
            )),
            maximum_chunks=int(os.getenv(
                "RAG_ANSWER_MAX_CHUNKS",
                payload.get("maximum_chunks", cls.maximum_chunks),
            )),
            maximum_points_per_article=int(os.getenv(
                "RAG_ANSWER_MAX_POINTS_PER_ARTICLE",
                payload.get("maximum_points_per_article", cls.maximum_points_per_article),
            )),
            maximum_answer_chars=int(os.getenv(
                "RAG_ANSWER_MAX_CHARS",
                payload.get("maximum_answer_chars", cls.maximum_answer_chars),
            )),
        )
        if not 0 <= settings.minimum_relevance_score <= 1:
            raise ValueError("minimum_relevance_score must be between 0 and 1")
        if min(
            settings.maximum_evidence_chars,
            settings.maximum_chunks,
            settings.maximum_points_per_article,
            settings.maximum_answer_chars,
        ) < 1:
            raise ValueError("answer limits must be positive")
        return settings


class EvidenceSafetyGate:
    """질문 관련성이 있는 활성 evidence를 문서별 정렬하고 version 충돌을 찾는다."""

    _STOP_WORDS = {
        "내부", "지침", "문서", "알려줘", "어떻게", "기준", "관련", "내용", "자세히",
        "무엇", "해야", "처리", "순서", "절차", "비교", "차이", "공통점", "각각",
    }
    _NEGATIVE = ("불가능", "불가", "금지", "할 수 없", "하지 않", "안 된다", "제외", "제한")
    _POSITIVE = ("가능", "허용", "할 수 있", "환불한다", "보상한다", "적용한다")

    def __init__(self, settings: AnswerSafetySettings) -> None:
        self._settings = settings

    def ranked_groups(
        self,
        evidence: list[dict[str, Any]],
        query: str,
        target_numbers: tuple[int, ...],
    ) -> list[list[dict[str, Any]]]:
        """문서·version별 evidence를 관련성으로 필터링해 결정론적 순서로 반환한다."""

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in evidence:
            document = str(item.get("manual_id") or item.get("document_id") or item.get("title") or "").strip()
            version = str(item.get("version") or "").strip()
            if document:
                grouped.setdefault((document, version), []).append(item)
        candidates = [
            group for group in grouped.values()
            if self._is_relevant(group, query, target_numbers)
        ]
        return sorted(candidates, key=lambda group: self._rank_key(group, query))

    def detect_conflicts(
        self,
        groups: list[list[dict[str, Any]]],
        query: str,
        answer_type: str,
        formatter: ManualArticleFormatter,
    ) -> list[Conflict]:
        """같은 문서의 활성 version이 반대 의미 claim을 갖는 경우 충돌로 반환한다."""

        by_manual: dict[str, list[list[dict[str, Any]]]] = {}
        for group in groups:
            if not group or not self._active(group[0]):
                continue
            key = str(group[0].get("manual_id") or group[0].get("title") or "").strip()
            by_manual.setdefault(key, []).append(group)

        conflicts: list[Conflict] = []
        query_terms = self._query_terms(query)
        for manual_id, versions in by_manual.items():
            distinct_versions = {str(group[0].get("version") or "") for group in versions}
            if len(distinct_versions) < 2:
                continue
            for left, right in combinations(versions, 2):
                left_sections = formatter.build_sections(left, query, answer_type)
                right_sections = formatter.build_sections(right, query, answer_type)
                left_claims = self._focused_claims(left_sections, query_terms)
                right_claims = self._focused_claims(right_sections, query_terms)
                left_polarity = self._polarity(" ".join(text for text, _ in left_claims))
                right_polarity = self._polarity(" ".join(text for text, _ in right_claims))
                if left_polarity * right_polarity != -1:
                    continue
                evidence_ids = list(dict.fromkeys(
                    evidence_id
                    for _, ids in (*left_claims, *right_claims)
                    for evidence_id in ids
                ))
                if len(evidence_ids) >= 2:
                    conflicts.append(Conflict(
                        description=(
                            f"{manual_id}의 버전 {left[0].get('version') or '미상'}과 "
                            f"{right[0].get('version') or '미상'}에서 적용 가능 여부가 상충합니다."
                        ),
                        evidence_ids=evidence_ids,
                    ))
        return conflicts

    def _is_relevant(
        self,
        group: list[dict[str, Any]],
        query: str,
        target_numbers: tuple[int, ...],
    ) -> bool:
        text = self._group_text(group)
        scores = self._scores(group)
        if scores and max(scores) < self._settings.minimum_relevance_score:
            return False
        query_terms = self._query_terms(query)
        if query_terms and any(term in text for term in query_terms):
            return True
        if any(
            str(item.get("document_type") or "").upper() == "INTERNAL_REPORT"
            for item in group
        ):
            return bool(scores) and max(scores) >= self._settings.minimum_relevance_score
        if query_terms:
            return False
        return any(
            re.search(rf"제\s*{number}\s*조", text)
            for number in target_numbers
        )

    def _rank_key(self, group: list[dict[str, Any]], query: str) -> tuple[float, float, str]:
        text = self._group_text(group)
        lexical_hits = sum(term in text for term in self._query_terms(query))
        retrieval_score = max(self._scores(group), default=0.0)
        identity = f"{group[0].get('manual_id', '')}:{group[0].get('version', '')}"
        return -float(lexical_hits), -retrieval_score, identity

    @classmethod
    def _query_terms(cls, query: str) -> set[str]:
        terms: set[str] = set()
        for raw in re.findall(r"[0-9A-Za-z가-힣]{2,}", query.lower()):
            term = raw
            for suffix in ("으로", "에서", "에게", "까지", "부터", "하고", "과", "와", "을", "를", "은", "는", "이", "가", "의"):
                if term.endswith(suffix) and len(term) > len(suffix) + 1:
                    term = term[:-len(suffix)]
                    break
            if len(term) >= 2 and term not in cls._STOP_WORDS:
                terms.add(term)
        return terms

    @classmethod
    def query_terms(cls, query: str) -> set[str]:
        """질문별 고정 map 없이 일반 lexical 비교에 사용할 토큰만 반환한다."""
        return cls._query_terms(query)

    @staticmethod
    def _group_text(group: list[dict[str, Any]]) -> str:
        return " ".join(
            f"{item.get('title', '')} {item.get('section_title', '')} {item.get('body', '')}".lower()
            for item in group
        )

    @staticmethod
    def _scores(group: list[dict[str, Any]]) -> list[float]:
        scores: list[float] = []
        for item in group:
            value = item.get("retrieval_score", item.get("score"))
            if value in (None, ""):
                continue
            try:
                scores.append(float(value))
            except (TypeError, ValueError):
                continue
        return scores

    @staticmethod
    def _active(item: dict[str, Any]) -> bool:
        if str(item.get("document_status") or "").upper() in {"REJECTED", "WITHDRAWN", "DELETED"}:
            return False
        if str(item.get("approval_status") or "").upper() in {"REJECTED", "WITHDRAWN"}:
            return False
        today = date.today()
        try:
            if item.get("effective_from") and date.fromisoformat(str(item["effective_from"])[:10]) > today:
                return False
            expiry = item.get("effective_to") or item.get("expires_at")
            if expiry and date.fromisoformat(str(expiry)[:10]) < today:
                return False
        except ValueError:
            pass
        return True

    @classmethod
    def _polarity(cls, text: str) -> int:
        if any(term in text for term in cls._NEGATIVE):
            return -1
        if any(term in text for term in cls._POSITIVE):
            return 1
        return 0

    @staticmethod
    def _focused_claims(sections: tuple[Any, ...], query_terms: set[str]) -> list[tuple[str, tuple[str, ...]]]:
        claims = [(claim.text, claim.evidence_ids) for section in sections for claim in section.claims]
        focused = [item for item in claims if any(term in item[0].lower() for term in query_terms)]
        return focused or claims
