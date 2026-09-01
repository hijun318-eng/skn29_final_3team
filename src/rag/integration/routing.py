"""상위 오케스트레이터의 승인 route 영수증을 SQL·RAG·ML 실행 플래그로 변환한다."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ToolRoute


@dataclass(frozen=True)
class RoutePlan:
    """승인 route, decision ID, 각 근거 도구 사용 여부와 ML 도구 코드를 담는다."""

    route: ToolRoute
    decision_id: str
    use_sql: bool
    use_rag: bool
    use_ml: bool
    ml_tool_code: str | None
    reason: str


class EvidenceRouter:
    """상위 오케스트레이터가 승인한 route 영수증을 실행 계획으로 변환한다."""

    def decide(
        self,
        route: ToolRoute,
        decision_id: str | None,
    ) -> RoutePlan:
        """typed route와 비어 있지 않은 decision ID만 받아 결정론적 실행 계획을 만들고 그 외는 거부한다."""

        if not isinstance(route, ToolRoute):
            raise ValueError("APPROVED_ROUTE_INVALID")
        normalized_decision_id = (decision_id or "").strip()
        if not normalized_decision_id:
            raise ValueError("ROUTER_DECISION_REQUIRED")
        use_sql = route in {ToolRoute.SQL_ONLY, ToolRoute.SQL_AND_RAG}
        use_rag = route in {
            ToolRoute.RAG_ONLY,
            ToolRoute.SQL_AND_RAG,
            ToolRoute.ML_AND_RAG,
        }
        use_ml = route in {ToolRoute.ML_ONLY, ToolRoute.ML_AND_RAG}
        return RoutePlan(
            route=route,
            decision_id=normalized_decision_id,
            use_sql=use_sql,
            use_rag=use_rag,
            use_ml=use_ml,
            ml_tool_code="ml.predict" if use_ml else None,
            reason="APPROVED_ORCHESTRATOR_ROUTE",
        )
