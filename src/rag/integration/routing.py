from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .contracts import ToolRoute


@dataclass(frozen=True)
class RoutePlan:
    route: ToolRoute
    decision_id: str
    use_sql: bool
    use_rag: bool
    use_ml: bool
    ml_tool_code: str | None
    reason: str


class EvidenceRouter:
    """Deterministic P2 pre-router. It never replaces the approved P0/P1 router."""

    _SQL_TERMS = frozenset(
        {
            "매출", "고객 수", "고객수", "이용률", "점유율", "건수", "증가율",
            "감소율", "평균", "합계", "몇 건", "얼마", "추이", "전월", "전년",
        }
    )
    _RAG_TERMS = frozenset(
        {
            "정책", "규정", "매뉴얼", "절차", "프로모션", "계약", "제휴",
            "조건", "조항", "승인", "대응 방법", "처리 방법", "지침",
        }
    )
    _MIXED_TERMS = frozenset({"왜", "원인", "영향", "관련", "변화 이유"})
    _NO_SHOW_TERMS = frozenset({"노쇼", "no-show", "no show", "미방문"})
    _PREDICTION_TERMS = frozenset(
        {
            "예측", "전망", "향후", "7일", "위험", "확률", "가능성",
            "우선순위", "연락 대상", "연락할",
        }
    )

    def decide(self, question: str) -> RoutePlan:
        normalized = " ".join(question.lower().split())
        has_sql = self._contains(normalized, self._SQL_TERMS)
        has_rag = self._contains(normalized, self._RAG_TERMS)
        asks_context = self._contains(normalized, self._MIXED_TERMS)
        has_ml = self._contains(normalized, self._NO_SHOW_TERMS) and self._contains(
            normalized, self._PREDICTION_TERMS
        )
        ml_tool_code = "predict-reservation-no-show" if has_ml else None
        if ml_tool_code and has_rag:
            route = ToolRoute.ML_AND_RAG
            reason = "No-show 모델 예측과 운영 문서가 모두 필요"
        elif ml_tool_code:
            route = ToolRoute.ML_ONLY
            reason = "예약 No-show 미래 위험 예측"
        elif has_sql and (has_rag or asks_context):
            route, reason = ToolRoute.SQL_AND_RAG, "수치와 문서 맥락이 모두 필요"
        elif has_sql:
            route, reason = ToolRoute.SQL_ONLY, "정형 수치 질문"
        elif has_rag:
            route, reason = ToolRoute.RAG_ONLY, "정책·매뉴얼 질문"
        else:
            route, reason = ToolRoute.GENERAL, "Tool 호출 근거 없음"
        decision_id = sha256(f"{route.value}:{normalized}".encode("utf-8")).hexdigest()[:24]
        return RoutePlan(
            route=route,
            decision_id=decision_id,
            use_sql=route in {ToolRoute.SQL_ONLY, ToolRoute.SQL_AND_RAG},
            use_rag=route in {
                ToolRoute.RAG_ONLY,
                ToolRoute.SQL_AND_RAG,
                ToolRoute.ML_AND_RAG,
            },
            use_ml=route in {ToolRoute.ML_ONLY, ToolRoute.ML_AND_RAG},
            ml_tool_code=ml_tool_code,
            reason=reason,
        )

    @staticmethod
    def _contains(text: str, terms: frozenset[str]) -> bool:
        return any(term in text for term in terms)
