"""P2 integration foundation kept inactive until the project gate is approved."""

from .contracts import IntegrationContext, IntegrationResponse, ToolRegistration
from .coordinator import EvidenceCoordinator
from .routing import EvidenceRouter

__all__ = [
    "EvidenceCoordinator",
    "EvidenceRouter",
    "IntegrationContext",
    "IntegrationResponse",
    "ToolRegistration",
]
