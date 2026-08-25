"""내부 문서 질의의 업무 영역·의도·문맥 상속 결과를 제한된 RAG 경로로 분류한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RagRoute(StrEnum):
    """질의를 데이터 분석 또는 내부 문서 검색으로 제한하는 경로 계약이다."""

    DATA_ONLY = "DATA_ONLY"
    DOCUMENT_ONLY = "DOCUMENT_ONLY"


class RagIntent(StrEnum):
    """RAG 답변 형식과 긴급도를 결정하는 허용 의도 집합이다."""

    PROCESS = "PROCESS"
    IMMEDIATE_ACTION = "IMMEDIATE_ACTION"
    DECISION_CRITERIA = "DECISION_CRITERIA"
    REGULATION_CHECK = "REGULATION_CHECK"
    COMPARISON = "COMPARISON"
    SUMMARY = "SUMMARY"


@dataclass(frozen=True)
class RagRoutingDecision:
    """선택 경로와 업무 영역, 해석된 질문 및 문맥 사용 여부를 묶는다."""

    route: RagRoute
    domains: tuple[str, ...]
    intent: RagIntent
    confidence: float
    resolved_question: str
    requires_context: bool


class RagQueryRouter:
    """업무 도메인과 사용자 목적을 결정하고 짧은 후속 질문만 이전 문맥으로 복원한다."""

    _DOMAIN_TERMS = {
        "PRIVACY": ("개인정보", "주민번호", "연락처", "정보 유출"),
        "REPORT": ("보고서", "보고서 작성", "보고서 양식"),
        "CUSTOMER_SERVICE": ("고객응대", "고객 응대", "불만", "민원"),
        "ROOM": ("객실", "룸", "청소", "비품"),
        "RESERVATION_CHECKIN_PAYMENT": ("예약", "입실", "퇴실", "체크인", "체크아웃", "결제"),
        "CANCELLATION_REFUND_COMPENSATION": ("취소", "환불", "보상", "위약금"),
        "FOOD_BEVERAGE": ("식음", "레스토랑", "조식", "식당"),
        "LEISURE": ("레저", "수영장", "피트니스", "사우나"),
        "FACILITY": ("시설", "장애", "고장", "설비"),
        "SAFETY": ("안전", "사고", "화재", "쓰러", "응급"),
        "PARKING_EVENT_LOBBY": ("주차", "행사", "로비", "연회"),
    }

    _DOCUMENT_TERMS = frozenset(
        {
            "지침", "규정", "정책", "매뉴얼", "절차", "원문", "근거", "조항",
            "대응", "처리 기준", "승인", "위약금", "환불", "개인정보", "안전",
            "입실", "퇴실", "예약", "결제", "고객응대", "업무 기준",
        }
    )

    def decide(self, query: str, requested_mode: str) -> RagRoute:
        """상세 분류 결과에서 호출자가 사용할 최종 RAG 경로만 반환한다."""

        return self.classify(query, requested_mode).route

    def classify(
        self,
        query: str,
        requested_mode: str,
        recent_utterances: tuple[str, ...] = (),
    ) -> RagRoutingDecision:
        """요청 모드와 최근 발화를 이용해 문서 영역·의도·신뢰도를 결정한다."""

        normalized = " ".join(query.lower().split())
        domains = self._domains(normalized)
        context_used = False
        resolved = query.strip()
        if not domains and self._is_follow_up(normalized) and recent_utterances:
            previous = next((item.strip() for item in reversed(recent_utterances) if item.strip()), "")
            inherited = self._domains(previous.lower())
            if previous and inherited:
                domains = inherited
                resolved = f"{previous}\n후속 질문: {query.strip()}"
                context_used = True
        document_signal = bool(domains) or any(term in normalized for term in self._DOCUMENT_TERMS)
        route = RagRoute.DOCUMENT_ONLY if requested_mode == "DOCUMENT_ONLY" or document_signal else RagRoute.DATA_ONLY
        confidence = 1.0 if requested_mode == "DOCUMENT_ONLY" else 0.92 if domains else 0.78 if document_signal else 0.35
        return RagRoutingDecision(
            route=route,
            domains=domains,
            intent=self._intent(normalized),
            confidence=confidence,
            resolved_question=resolved,
            requires_context=context_used,
        )

    @classmethod
    def _domains(cls, query: str) -> tuple[str, ...]:
        return tuple(domain for domain, terms in cls._DOMAIN_TERMS.items() if any(term in query for term in terms))[:3]

    @staticmethod
    def _intent(query: str) -> RagIntent:
        if any(term in query for term in ("차이", "비교", "어떻게 달라")):
            return RagIntent.COMPARISON
        if any(term in query for term in ("지금", "즉시", "먼저", "쓰러", "화재")):
            return RagIntent.IMMEDIATE_ACTION
        if any(term in query for term in ("기준", "조건", "어떤 상황", "언제 보고")):
            return RagIntent.DECISION_CRITERIA
        if any(term in query for term in ("요약", "핵심", "중요한 내용")):
            return RagIntent.SUMMARY
        if any(term in query for term in ("처리", "절차", "어떻게")):
            return RagIntent.PROCESS
        return RagIntent.REGULATION_CHECK

    @staticmethod
    def _is_follow_up(query: str) -> bool:
        return len(query) <= 40 and any(term in query for term in ("그", "기준", "즉시", "보고", "그러면", "그럼", "더 알려"))
