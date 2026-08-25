from __future__ import annotations

import json
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
REPO_DIR = PROJECT_DIR.parents[2]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from src.rag.integration.contracts import IntegrationContext, ToolRegistration
from src.rag.integration.mcp_dispatcher import McpJsonRpcDispatcher
from src.rag.integration.ml_tool import NoShowPredictionToolHandler
from src.rag.integration.routing import EvidenceRouter
from src.rag.integration.tool_service import ConfiguredToolRegistry, RegistryToolService

from no_show_ml.config import ProjectConfig
from no_show_ml.service import NoShowToolService


class AuditedNoShowExecutor:
    def __init__(self, config: ProjectConfig):
        self.service = NoShowToolService(config)
        self.audit_path = config.artifacts_dir / "mcp_tool_runs.jsonl"
        self._lock = threading.Lock()

    def execute_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.service.execute_arguments(arguments)
        with self._lock:
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        return result


class NoShowMcpRuntime:
    def __init__(self, mode: str = "disabled"):
        self.config = ProjectConfig.default()
        registration = self._load_registration()
        if mode == "local_demo":
            if not self._all_readiness_gates_pass():
                raise RuntimeError(
                    "ML Tool activation is blocked until every readiness gate is PASS"
                )
            registration = replace(
                registration,
                enabled=True,
                approval_status="APPROVED",
                health_status="HEALTHY",
            )
        elif mode != "disabled":
            raise ValueError("ANSWERVICE_ML_TOOL_MODE must be disabled or local_demo")
        self.registration = registration
        executor = AuditedNoShowExecutor(self.config)
        handler = NoShowPredictionToolHandler(
            executor, timeout_seconds=registration.timeout_seconds
        )
        registry = ConfiguredToolRegistry((registration,))
        self.dispatcher = McpJsonRpcDispatcher(
            RegistryToolService(registry, {registration.tool_code: handler})
        )
        self.router = EvidenceRouter()

    def _all_readiness_gates_pass(self) -> bool:
        path = self.config.artifacts_dir / "readiness_gate.json"
        readiness = json.loads(path.read_text(encoding="utf-8"))
        return bool(readiness["checks"]) and all(
            check["status"] == "PASS" for check in readiness["checks"]
        )

    def dispatch(
        self, request: dict[str, Any], context: IntegrationContext
    ) -> dict[str, Any]:
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
            as_of="2026-08-04T18:00:00+09:00",
            session_id="local-main-chat-fixture",
        )

    def _load_registration(self) -> ToolRegistration:
        payload = json.loads(
            (self.config.project_dir / "config" / "mcp_registration.json").read_text(
                encoding="utf-8"
            )
        )
        payload["required_roles"] = frozenset(payload["required_roles"])
        return ToolRegistration(**payload)
