from __future__ import annotations

import time
import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_runtime import NoShowMcpRuntime
from run_main_chat_fixture import fixture_arguments, rpc
from src.rag.integration.contracts import IntegrationContext
from src.rag.integration.coordinator import ToolCallError
from src.rag.integration.ml_tool import NoShowPredictionToolHandler


class SlowExecutor:
    def execute_arguments(self, arguments):
        time.sleep(0.1)
        return arguments


class McpRuntimeTest(unittest.TestCase):
    def test_router_separates_ml_rag_and_combined_intents(self) -> None:
        runtime = NoShowMcpRuntime("disabled")
        self.assertEqual(runtime.route("노쇼 위험을 예측해줘")["route"], "ML_ONLY")
        self.assertEqual(runtime.route("노쇼 처리 규정")["route"], "RAG_ONLY")
        self.assertEqual(
            runtime.route("노쇼 위험 예측과 처리 절차")["route"], "ML_AND_RAG"
        )

    def test_production_registration_is_hidden_and_blocked(self) -> None:
        runtime = NoShowMcpRuntime("disabled")
        context = runtime.context("disabled-1")
        listed = runtime.dispatch(rpc(1, "tools/list"), context)
        called = runtime.dispatch(
            rpc(
                2,
                "tools/call",
                {
                    "name": runtime.registration.tool_code,
                    "arguments": fixture_arguments(runtime),
                },
            ),
            context,
        )
        self.assertEqual(listed["result"]["tools"], [])
        self.assertTrue(called["result"]["isError"])

    def test_local_demo_cannot_bypass_readiness_gate(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "readiness gate"):
            NoShowMcpRuntime("local_demo")

    def test_handler_returns_response_timeout(self) -> None:
        handler = NoShowPredictionToolHandler(SlowExecutor(), timeout_seconds=0.01)
        context = IntegrationContext("r", "t", "a", "hotel_analyst", "2026-08-04")
        arguments = {
            "reservation_id": "RES-1",
            "feature_as_of": "2026-08-04T18:00:00+09:00",
            "feature_set_version": "reservation-no-show-feature-v1.0",
            "input_schema_version": "reservation-no-show-input-v1.0",
        }
        with self.assertRaisesRegex(ToolCallError, "TOOL_TIMEOUT"):
            handler.call(arguments, context)


if __name__ == "__main__":
    unittest.main()
