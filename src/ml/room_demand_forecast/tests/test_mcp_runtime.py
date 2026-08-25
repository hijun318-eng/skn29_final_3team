from __future__ import annotations

import unittest

from mcp_runtime import RoomDemandMcpRuntime
from run_main_chat_fixture import rpc


class RoomDemandMcpRuntimeTest(unittest.TestCase):
    def test_production_registration_is_hidden(self) -> None:
        runtime = RoomDemandMcpRuntime("disabled")
        response = runtime.dispatch(rpc(1, "tools/list"), runtime.context("disabled"))
        self.assertEqual([], response["result"]["tools"])

    def test_local_demo_is_blocked_for_reference_model(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "offline reference"):
            RoomDemandMcpRuntime("local_demo")

    def test_router_does_not_select_room_demand_reference(self) -> None:
        runtime = RoomDemandMcpRuntime("disabled")
        route = runtime.route("향후 7일 객실수요를 예측해줘")
        self.assertFalse(route["use_ml"])
        self.assertIsNone(route["ml_tool_code"])


if __name__ == "__main__":
    unittest.main()
