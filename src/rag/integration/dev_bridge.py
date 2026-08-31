"""기존 P0/P1 요청 흐름을 보존하면서 승인된 P2 근거 조정기를 선택적으로 연결한다."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .adapters import AnswerviceContextAdapter
from .contracts import IntegrationResponse, IntegrationStatus, ToolRoute
from .coordinator import EvidenceCoordinator


class DevP2EvidenceBridge:
    """백엔드 요청 문맥에 승인 route 영수증을 결합해 P2 근거 수집을 호출하는 선택적 브리지다."""

    def __init__(self, coordinator: EvidenceCoordinator) -> None:
        self._coordinator = coordinator

    def collect(
        self,
        question: str,
        request_context: Any,
        approved_route: ToolRoute,
        router_decision_id: str,
    ) -> IntegrationResponse:
        """요청 문맥을 변환하고 승인 route·decision ID를 고정해 통합 근거 응답을 수집한다."""

        context = replace(
            AnswerviceContextAdapter.convert(request_context),
            approved_route=approved_route,
            router_decision_id=router_decision_id,
        )
        return self._coordinator.execute(question, context)

    @staticmethod
    def should_preserve_p0_p1(response: IntegrationResponse) -> bool:
        """P2가 미적용·차단·실패이면 기존 P0/P1 결과를 유지해야 한다고 판정한다."""

        return response.route == ToolRoute.GENERAL or response.status in {
            IntegrationStatus.BLOCKED,
            IntegrationStatus.FAILED,
        }
