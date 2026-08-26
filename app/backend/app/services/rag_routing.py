"""통합 채팅 요청을 데이터 분석과 내부 문서 검색 경로로 분류한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class RagRoute(StrEnum):
    """RAG가 선택할 수 있는 데이터·문서 실행 경로를 열거한다."""

    DATA_ONLY = "DATA_ONLY"
    DOCUMENT_ONLY = "DOCUMENT_ONLY"


class RagIntent(StrEnum):
    """내부 문서 질문의 업무 목적을 제한된 유형으로 표현한다."""

    PROCESS = "PROCESS"
    IMMEDIATE_ACTION = "IMMEDIATE_ACTION"
    DECISION_CRITERIA = "DECISION_CRITERIA"
    REGULATION_CHECK = "REGULATION_CHECK"
    COMPARISON = "COMPARISON"
    SUMMARY = "SUMMARY"


@dataclass(frozen=True)
class RagRoutingDecision:
    """분류된 실행 경로와 도메인, 신뢰도 및 후속 질문 여부를 보존한다."""

    route: RagRoute
    domains: tuple[str, ...]
    intent: RagIntent
    confidence: float
    resolved_question: str
    requires_context: bool
    clarification: str | None = None
    clarification_options: tuple[str, ...] = ()


class RagQueryRouter:
    """업무 도메인과 사용자 목적을 결정하고 짧은 후속 질문만 이전 문맥으로 복원한다."""

    _GUIDELINE_TAG = re.compile(r"^\s*\[\s*내부\s*지침\s*\]\s*", re.IGNORECASE)
    _HELP_TERMS = ("어떤 문서", "문서 목록", "무엇을 물어", "질문 예시", "도움말")

    _DOMAIN_TERMS = {
        "PRIVACY": ("개인정보", "주민번호", "연락처", "정보 유출"),
        "REPORT": ("보고서", "보고서 작성", "보고서 양식"),
        "CUSTOMER_SERVICE": ("고객응대", "고객 응대", "불만", "민원"),
        "ROOM": ("객실", "룸", "청소", "비품"),
        "RESERVATION_CHECKIN_PAYMENT": ("예약", "입실", "퇴실", "체크인", "체크아웃", "결제"),
        "CANCELLATION_REFUND_COMPENSATION": ("취소", "환불", "보상", "위약금", "노쇼"),
        "FOOD_BEVERAGE": ("식음", "레스토랑", "조식", "식당", "주방", "위생", "알레르기", "이물"),
        "LEISURE": ("레저", "수영장", "피트니스", "사우나"),
        "FACILITY": ("시설", "장애", "고장", "설비"),
        "SAFETY": ("안전", "사고", "화재", "쓰러", "실신", "부상", "의식", "호흡", "응급"),
        "PARKING_EVENT_LOBBY": ("주차", "행사", "로비", "연회", "분실물", "수하물"),
    }

    _DOCUMENT_TERMS = frozenset(
        {
            "지침", "규정", "정책", "매뉴얼", "절차", "원문", "근거", "조항",
            "대응", "처리 기준", "승인", "위약금", "환불", "개인정보", "안전",
            "입실", "퇴실", "예약", "결제", "고객응대", "업무 기준",
        }
    )
    _DOMAIN_LABELS = {
        "PRIVACY": "개인정보",
        "REPORT": "보고서",
        "CUSTOMER_SERVICE": "고객응대",
        "ROOM": "객실",
        "RESERVATION_CHECKIN_PAYMENT": "예약·입퇴실·결제",
        "CANCELLATION_REFUND_COMPENSATION": "취소·환불·보상",
        "FOOD_BEVERAGE": "식음",
        "LEISURE": "레저",
        "FACILITY": "시설",
        "SAFETY": "안전",
        "PARKING_EVENT_LOBBY": "주차·행사·로비",
    }

    def decide(self, query: str, requested_mode: str) -> RagRoute:
        """요청 모드와 질문 분류 결과에서 최종 RAG 실행 경로를 반환한다."""
        return self.classify(query, requested_mode).route

    def classify(
        self,
        query: str,
        requested_mode: str,
        recent_utterances: tuple[str, ...] = (),
    ) -> RagRoutingDecision:
        """질문과 제한된 이전 문맥을 검사해 문서 검색 결정을 생성한다."""
        cleaned_query = self._strip_guideline_tag(query)
        explicit_guideline = cleaned_query != query.strip()
        normalized = " ".join(cleaned_query.lower().split())
        intent = self._intent(normalized)
        domains = self._domains(normalized, intent)
        context_used = False
        resolved = cleaned_query
        is_help = any(term in normalized for term in self._HELP_TERMS)
        if not domains and not is_help and (explicit_guideline or self._is_follow_up(normalized)) and recent_utterances:
            previous = next(
                (
                    self._strip_guideline_tag(item)
                    for item in reversed(recent_utterances)
                    if item.strip()
                    and self._domains(
                        self._strip_guideline_tag(item).lower(),
                        self._intent(self._strip_guideline_tag(item).lower()),
                    )
                ),
                "",
            )
            inherited = (
                self._domains(previous.lower(), self._intent(previous.lower()))
                if previous
                else ()
            )
            if previous and inherited:
                domains = inherited
                resolved = f"이전 내부지침 문맥: {previous}\n현재 후속 질문: {cleaned_query}"
                context_used = True
        document_signal = bool(domains) or any(term in normalized for term in self._DOCUMENT_TERMS)
        route = RagRoute.DOCUMENT_ONLY if explicit_guideline or requested_mode == "DOCUMENT_ONLY" or document_signal else RagRoute.DATA_ONLY
        confidence = 1.0 if explicit_guideline or requested_mode == "DOCUMENT_ONLY" else 0.92 if domains else 0.78 if document_signal else 0.35
        clarification, clarification_options = self._clarification(
            domains,
            intent,
            context_used,
        )
        return RagRoutingDecision(
            route=route,
            domains=domains,
            intent=intent,
            confidence=confidence,
            resolved_question=resolved,
            requires_context=context_used,
            clarification=clarification if route is RagRoute.DOCUMENT_ONLY else None,
            clarification_options=(
                clarification_options if route is RagRoute.DOCUMENT_ONLY else ()
            ),
        )

    @classmethod
    def _clarification(
        cls,
        domains: tuple[str, ...],
        intent: RagIntent,
        context_used: bool,
    ) -> tuple[str | None, tuple[str, ...]]:
        if context_used:
            return None, ()
        ambiguous = not domains or (
            len(domains) > 1
            and intent
            not in {RagIntent.PROCESS, RagIntent.IMMEDIATE_ACTION, RagIntent.COMPARISON}
        )
        if not ambiguous:
            return None, ()
        option_domains = domains or (
            "SAFETY",
            "PRIVACY",
            "FACILITY",
            "CUSTOMER_SERVICE",
            "CANCELLATION_REFUND_COMPENSATION",
        )
        labels = tuple(cls._DOMAIN_LABELS[domain] for domain in option_domains)
        return (
            "확인할 업무 영역이 명확하지 않습니다. 아래 영역 중 하나를 선택하거나 상황을 더 구체적으로 알려주세요.",
            tuple(f"{label} 관련 기준을 알려줘" for label in labels),
        )

    @classmethod
    def _domains(
        cls,
        query: str,
        intent: RagIntent | None = None,
    ) -> tuple[str, ...]:
        matched = tuple(
            domain
            for domain, terms in cls._DOMAIN_TERMS.items()
            if any(term in query for term in terms)
        )
        # "예약 취소/환불"은 예약과 취소 도메인이 함께 잡히지만 실제 업무 목적은
        # 취소·환불 기준 확인이다. 비교 질문에서만 두 도메인을 그대로 유지한다.
        if (
            intent is not RagIntent.COMPARISON
            and "CANCELLATION_REFUND_COMPENSATION" in matched
            and any(term in query for term in ("취소", "환불", "노쇼", "위약금"))
        ):
            return ("CANCELLATION_REFUND_COMPENSATION",)
        # 긴급 행동 질문에서는 사고 도메인이 장소 도메인보다 우선한다.
        if intent is RagIntent.IMMEDIATE_ACTION and "SAFETY" in matched:
            return ("SAFETY",)
        return matched[:3]

    @staticmethod
    def _intent(query: str) -> RagIntent:
        if any(term in query for term in ("차이", "비교", "달라", "두 기준", "각각", "구분해")):
            return RagIntent.COMPARISON
        if any(
            term in query
            for term in (
                "지금", "즉시", "먼저", "긴급", "사고", "위험", "쓰러", "화재",
                "유출", "노출", "잘못 전달", "누수", "위생 문제",
            )
        ):
            return RagIntent.IMMEDIATE_ACTION
        if any(term in query for term in ("요약", "핵심", "중요한 내용", "주요 내용", "전체적으로", "꼭 알아야 할 내용")):
            return RagIntent.SUMMARY
        if any(term in query for term in ("기준", "조건", "판단", "분류", "어떤 상황", "어떤 경우", "언제 보고")):
            return RagIntent.DECISION_CRITERIA
        if any(term in query for term in ("처리", "절차", "순서", "진행", "어떻게")):
            return RagIntent.PROCESS
        return RagIntent.REGULATION_CHECK

    @staticmethod
    def _is_follow_up(query: str) -> bool:
        return len(query) <= 60 and any(
            term in query
            for term in (
                "그", "기준", "즉시", "보고", "그러면", "그럼", "더 알려", "자세히",
                "금지", "종료", "추가", "처리 순서", "공통점", "차이", "비교", "각각",
                "사례", "예시", "구분",
            )
        )

    @classmethod
    def _strip_guideline_tag(cls, query: str) -> str:
        return cls._GUIDELINE_TAG.sub("", query.strip()).strip()
