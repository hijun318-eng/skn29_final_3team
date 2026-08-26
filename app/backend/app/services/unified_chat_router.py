"""단일 채팅 메시지를 서버가 소유하는 분석·예측·내부지침 경로로 분류한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable


class ChatIntent(StrEnum):
    """통합 채팅에서 허용하는 실행 목적과 명확화 상태를 열거한다."""

    ANALYSIS = "ANALYSIS"
    FORECAST = "FORECAST"
    INTERNAL_GUIDELINE = "INTERNAL_GUIDELINE"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class ChatRoutingDecision:
    """서버가 선택한 실행 목적, 신뢰도와 명확화 선택지를 전달한다."""

    intent: ChatIntent
    confidence: float
    clarification_options: tuple[dict[str, str], ...] = ()


class UnifiedChatRouter:
    """브라우저 추측 없이 서버에서 채팅 실행 경로를 선택한다."""

    _GUIDELINE_TAGS = ("[내부 지침]", "[내부지침]")

    _GUIDELINE_TERMS = (
        "지침", "규정", "정책", "매뉴얼", "절차", "처리 방법", "대응 방법",
        "문서", "무엇을 물어", "질문 예시",
        "원문", "조항", "금지사항", "분실물", "개인정보", "안전사고",
        "환불 기준", "취소 규정", "보고 기준",
    )
    _GUIDELINE_DOMAIN_TERMS = (
        "개인정보", "보고서", "고객 불만", "객실", "예약", "체크인", "체크아웃",
        "취소", "환불", "보상", "노쇼", "식음", "위생", "레저", "시설", "누수",
        "안전", "화재", "실신", "부상", "주차", "행사", "로비",
    )
    _GUIDELINE_ACTION_TERMS = (
        "해야", "기준", "절차", "처리", "대응", "가능", "금지", "보고",
        "알려", "차이", "구분", "요약",
    )
    _DATA_METRIC_TERMS = (
        "매출", "점유율", "adr", "revpar", "평점", "voc", "추이", "실적",
        "현황", "증가", "감소", "지난달", "이번 달", "이번달",
    )
    _FORECAST_TERMS = ("예측", "전망", "향후", "앞으로", "수요 예측")
    _FUTURE_TERMS = ("내일", "다음 주", "다음주", "이번 주말", "향후", "앞으로")
    _ANALYSIS_TERMS = (
        "매출", "점유율", "adr", "revpar", "평점", "voc", "추이", "비교",
        "실적", "현황", "증가", "감소", "지난달", "이번 달", "이번달",
    )
    _FOLLOW_UP_TERMS = ("그중", "그 중", "그럼", "그러면", "더", "같은", "방금", "기준")
    _AMBIGUOUS_TERMS = ("상황", "어때", "어떻게 보여")

    def classify(
        self,
        question: str,
        previous_turns: Iterable[dict[str, Any]] = (),
    ) -> ChatRoutingDecision:
        """현재 질문과 직전 턴의 typed 상태로 하나의 실행 경로를 결정한다."""
        normalized = " ".join(question.lower().split())
        if any(normalized.startswith(tag) for tag in self._GUIDELINE_TAGS):
            return ChatRoutingDecision(ChatIntent.INTERNAL_GUIDELINE, 1.0)
        previous_intent = self._previous_intent(previous_turns)
        explicit_guideline = any(term in normalized for term in self._GUIDELINE_TERMS)
        domain_guideline = (
            any(term in normalized for term in self._GUIDELINE_DOMAIN_TERMS)
            and any(term in normalized for term in self._GUIDELINE_ACTION_TERMS)
            and not any(term in normalized for term in self._DATA_METRIC_TERMS)
        )
        has_guideline = explicit_guideline or domain_guideline
        has_forecast = any(term in normalized for term in self._FORECAST_TERMS) or (
            "수요" in normalized and any(term in normalized for term in self._FUTURE_TERMS)
        )
        has_analysis = any(term in normalized for term in self._ANALYSIS_TERMS)

        if self._is_follow_up(normalized) and not (has_guideline or has_forecast or has_analysis):
            if previous_intent is not None:
                return ChatRoutingDecision(previous_intent, 0.86)
        if has_guideline and has_forecast:
            return self._ambiguous()
        if (
            any(term in normalized for term in self._AMBIGUOUS_TERMS)
            and any(term in normalized for term in self._FUTURE_TERMS)
            and not has_forecast
        ):
            return self._ambiguous()
        if has_guideline:
            return ChatRoutingDecision(ChatIntent.INTERNAL_GUIDELINE, 0.94)
        if has_forecast:
            return ChatRoutingDecision(ChatIntent.FORECAST, 0.93)
        return ChatRoutingDecision(ChatIntent.ANALYSIS, 0.82 if has_analysis else 0.65)

    @classmethod
    def _is_follow_up(cls, question: str) -> bool:
        return len(question) <= 60 and any(term in question for term in cls._FOLLOW_UP_TERMS)

    @staticmethod
    def _previous_intent(previous_turns: Iterable[dict[str, Any]]) -> ChatIntent | None:
        turns = list(previous_turns)
        if not turns:
            return None
        slots = turns[-1].get("resolved_slots") or {}
        if slots.get("rag") is not None:
            return ChatIntent.INTERNAL_GUIDELINE
        if slots.get("ml") is not None:
            return ChatIntent.FORECAST
        return ChatIntent.ANALYSIS

    @staticmethod
    def _ambiguous() -> ChatRoutingDecision:
        return ChatRoutingDecision(
            ChatIntent.AMBIGUOUS,
            0.5,
            (
                {"label": "현재 객실 운영 현황", "value": "현재 객실 운영 현황을 분석해줘"},
                {"label": "[객실 수요예측] GRAND 호텔", "value": "GRAND 호텔의 향후 7일 객실 수요를 예측해줘"},
            ),
        )
