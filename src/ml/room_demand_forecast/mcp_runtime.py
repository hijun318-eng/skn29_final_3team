from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
REPO_DIR = PROJECT_DIR.parents[2]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from room_demand_ml.config import DEFAULT_OUTPUT_DIR
from room_demand_ml.service import RoomDemandForecastService
from src.rag.integration.contracts import IntegrationContext, ToolRegistration
from src.rag.integration.mcp_dispatcher import McpJsonRpcDispatcher
from src.rag.integration.routing import EvidenceRouter
from src.rag.integration.tool_service import ConfiguredToolRegistry, RegistryToolService


class AuditedRoomDemandExecutor:
    def __init__(self):
        self.service = RoomDemandForecastService()
        self.audit_path = DEFAULT_OUTPUT_DIR / "mcp_tool_runs.jsonl"
        self._lock = threading.Lock()

    def execute_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.service.execute_arguments(arguments)
        with self._lock:
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        return result


class RoomDemandMcpRuntime:
    def __init__(self, mode: str = "disabled"):
        registration = self._load_registration()
        if mode == "local_demo":
            raise RuntimeError(
                "room-demand model is an offline reference and is not an ML Tool candidate"
            )
        elif mode != "disabled":
            raise ValueError("ANSWERVICE_ML_TOOL_MODE must be disabled or local_demo")
        self.registration = registration
        registry = ConfiguredToolRegistry((registration,))
        self.dispatcher = McpJsonRpcDispatcher(
            RegistryToolService(registry, {})
        )
        self.router = EvidenceRouter()

    def dispatch(self, request: dict[str, Any], context: IntegrationContext) -> dict[str, Any]:
        return self.dispatcher.dispatch(request, context)

    def route(self, question: str) -> dict[str, Any]:
        plan = self.router.decide(question)
        return {
            "route": plan.route.value,
            "decision_id": plan.decision_id,
            "use_sql": plan.use_sql,
            "use_rag": plan.use_rag,
            "use_ml": plan.use_ml,
            "ml_tool_code": plan.ml_tool_code,
            "reason": plan.reason,
        }

    @staticmethod
    def context(request_id: str, role: str = "hotel_analyst") -> IntegrationContext:
        return IntegrationContext(
            request_id=request_id,
            trace_id=f"trace-{request_id}",
            actor_id="local-demo-actor",
            role=role,
            as_of="2026-07-28",
            session_id="local-main-chat-fixture",
        )

    @staticmethod
    def _load_registration() -> ToolRegistration:
        payload = json.loads(
            (PROJECT_DIR / "config" / "mcp_registration.json").read_text(encoding="utf-8")
        )
        payload["required_roles"] = frozenset(payload["required_roles"])
        return ToolRegistration(**payload)
