from __future__ import annotations

from dataclasses import replace
from typing import Any

from .adapters import AnswerviceContextAdapter
from .contracts import IntegrationResponse, IntegrationStatus, ToolRoute
from .coordinator import EvidenceCoordinator


class DevP2EvidenceBridge:
    """Optional bridge called beside the existing P0/P1 flow after P2 approval."""

    def __init__(self, coordinator: EvidenceCoordinator) -> None:
        self._coordinator = coordinator

    def collect(
        self,
        question: str,
        request_context: Any,
        approved_route: ToolRoute,
        router_decision_id: str,
    ) -> IntegrationResponse:
        context = replace(
            AnswerviceContextAdapter.convert(request_context),
            approved_route=approved_route,
            router_decision_id=router_decision_id,
        )
        return self._coordinator.execute(question, context)

    @staticmethod
    def should_preserve_p0_p1(response: IntegrationResponse) -> bool:
        return response.route == ToolRoute.GENERAL or response.status in {
            IntegrationStatus.BLOCKED,
            IntegrationStatus.FAILED,
        }
