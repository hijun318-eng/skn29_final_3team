from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mcp_runtime import PROJECT_DIR, RoomDemandMcpRuntime
from room_demand_ml.config import DEFAULT_OUTPUT_DIR


def rpc(request_id: int, method: str, params: dict | None = None) -> dict:
    request = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    return request


def fixture_arguments() -> dict[str, str]:
    return {
        "property_id": "SYNTHETIC_HOTEL_001",
        "feature_as_of": "2026-07-28",
        "feature_set_version": "room-demand-feature-v1.0",
        "input_schema_version": "room-demand-forecast-input-v1.0",
    }


def normalize(response: dict) -> dict:
    value = json.loads(json.dumps(response, ensure_ascii=False))
    for item in value.get("result", {}).get("content", []):
        try:
            payload = json.loads(item.get("text", ""))
        except json.JSONDecodeError:
            continue
        prediction = payload.get("prediction", {})
        prediction["execution_id"] = "mlrun-fixture"
        prediction["duration_ms"] = 0.0
        item["text"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return value


def run_stdio(arguments: dict[str, str]) -> list[dict]:
    requests = [
        rpc(11, "initialize", {"protocolVersion": "2025-06-18"}),
        rpc(12, "tools/list"),
        rpc(
            13,
            "tools/call",
            {"name": "forecast-room-demand-7d", "arguments": arguments},
        ),
    ]
    environment = os.environ.copy()
    environment["ANSWERVICE_ML_TOOL_MODE"] = "local_demo"
    environment["ANSWERVICE_ML_TOOL_ROLE"] = "hotel_analyst"
    environment["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        [sys.executable, str(PROJECT_DIR / "mcp_server.py")],
        cwd=PROJECT_DIR,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    stdout, stderr = process.communicate(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in requests),
        timeout=30,
    )
    if process.returncode != 0:
        raise RuntimeError(f"stdio MCP failed: {stderr}")
    return [normalize(json.loads(line)) for line in stdout.splitlines() if line.strip()]


def main() -> None:
    production = RoomDemandMcpRuntime("disabled")
    demo = RoomDemandMcpRuntime("local_demo")
    context = demo.context("room-demand-fixture")
    arguments = fixture_arguments()
    production_list = production.dispatch(rpc(1, "tools/list"), context)
    production_call = production.dispatch(
        rpc(
            2,
            "tools/call",
            {"name": demo.registration.tool_code, "arguments": arguments},
        ),
        context,
    )
    demo_list = demo.dispatch(rpc(3, "tools/list"), context)
    demo_call = normalize(
        demo.dispatch(
            rpc(
                4,
                "tools/call",
                {"name": demo.registration.tool_code, "arguments": arguments},
            ),
            context,
        )
    )
    stdio = run_stdio(arguments)
    routes = {
        "room_demand": demo.route("향후 7일 객실수요를 예측해줘"),
        "no_show": demo.route("이 예약의 노쇼 위험을 예측해줘"),
    }
    checks = {
        "production_hidden": production_list["result"]["tools"] == [],
        "production_call_blocked": production_call["result"]["isError"],
        "demo_listed": demo_list["result"]["tools"][0]["name"]
        == demo.registration.tool_code,
        "demo_call_success": not demo_call["result"]["isError"],
        "room_demand_route": routes["room_demand"]["ml_tool_code"]
        == "forecast-room-demand-7d",
        "no_show_route_separate": routes["no_show"]["ml_tool_code"]
        == "predict-reservation-no-show",
        "stdio_initialize": stdio[0]["result"]["serverInfo"]["name"]
        == "answervice-room-demand-ml",
        "stdio_list": stdio[1]["result"]["tools"][0]["name"]
        == "forecast-room-demand-7d",
        "stdio_call": not stdio[2]["result"]["isError"],
    }
    payload = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "routes": routes,
        "production_list": production_list,
        "production_call": production_call,
        "demo_list": demo_list,
        "demo_call": demo_call,
        "stdio_responses": stdio,
    }
    (DEFAULT_OUTPUT_DIR / "main_chat_mcp_fixture.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    local_config = {
        "mcpServers": {
            "answervice-room-demand-ml": {
                "command": str(Path(sys.executable).resolve()),
                "args": [str((PROJECT_DIR / "mcp_server.py").resolve())],
                "env": {
                    "ANSWERVICE_ML_TOOL_MODE": "local_demo",
                    "ANSWERVICE_ML_TOOL_ROLE": "hotel_analyst",
                },
            }
        }
    }
    (DEFAULT_OUTPUT_DIR / "mcp_server_config.local.json").write_text(
        json.dumps(local_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
