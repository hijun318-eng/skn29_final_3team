from __future__ import annotations

from typing import Protocol

from app.contracts import RequestContext
from app.services.context_gate import ContextGateRequest
from app.services.routing_service import RouteDecision


class ContextGateInputProvider(Protocol):
    """Builds trusted G1 input without letting the model decide policy."""

    def prepare(
        self,
        assets: list[dict[str, object]],
        context: RequestContext,
        decision: RouteDecision,
    ) -> ContextGateRequest: ...
