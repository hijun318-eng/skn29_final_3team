from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from mcp_runtime import NoShowMcpRuntime, PROJECT_DIR
from no_show_ml.io_utils import write_json
from src.rag.integration.contracts import IntegrationContext
from src.rag.integration.coordinator import ToolCallError
from src.rag.integration.ml_tool import NoShowPredictionToolHandler


class SlowExecutor:
    def execute_arguments(self, arguments):
        time.sleep(0.1)
        return arguments


def main() -> None:
    production = NoShowMcpRuntime("disabled")
    demo = NoShowMcpRuntime("local_demo")
    context = demo.context("main-chat-1")
    arguments = fixture_arguments(demo)
    production_list = production.dispatch(rpc(1, "tools/list"), context)
    production_call = production.dispatch(
        rpc(2, "tools/call", {"name": demo.registration.tool_code, "arguments": arguments}),
        context,
    )
    demo_list = demo.dispatch(rpc(3, "tools/list"), context)
    demo_call = demo.dispatch(
        rpc(4, "tools/call", {"name": demo.registration.tool_code, "arguments": arguments}),
        context,
    )
    demo_call = normalize_response(demo_call)
    routes = {
        "ml_only": demo.route("이 예약의 노쇼 위험을 예측해줘"),
        "rag_only": demo.route("노쇼 처리 규정을 알려줘"),
        "ml_and_rag": demo.route("노쇼 위험 예측과 대응 절차를 알려줘"),
        "sql_only": demo.route("이번 달 객실 매출은 얼마야"),
    }
    stdio = [normalize_response(item) for item in run_stdio_fixture(arguments)]
    checks = {
        "production_hidden": production_list["result"]["tools"] == [],
        "production_call_blocked": production_call["result"]["isError"],
        "demo_listed": demo_list["result"]["tools"][0]["name"]
        == demo.registration.tool_code,
        "demo_call_success": not demo_call["result"]["isError"],
        "ml_route": routes["ml_only"]["route"] == "ML_ONLY",
        "combined_route": routes["ml_and_rag"]["route"] == "ML_AND_RAG",
        "rag_route": routes["rag_only"]["route"] == "RAG_ONLY",
        "stdio_initialize": stdio[0]["result"]["serverInfo"]["name"]
        == "answervice-no-show-ml",
        "stdio_list": len(stdio[1]["result"]["tools"]) == 1,
        "stdio_call": not stdio[2]["result"]["isError"],
        "response_timeout": verify_timeout(),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    payload = {
        "status": status,
        "checks": checks,
        "routes": routes,
        "production_list": production_list,
        "production_call": production_call,
        "demo_list": demo_list,
        "demo_call": demo_call,
        "stdio_responses": stdio,
    }
    artifacts = demo.config.artifacts_dir
    write_json(artifacts / "main_chat_mcp_fixture.json", payload)
    write_local_config(artifacts / "mcp_server_config.local.json")
    update_gate(artifacts, status)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def fixture_arguments(runtime: NoShowMcpRuntime) -> dict[str, str]:
    frame = pd.read_csv(runtime.config.inference_csv, low_memory=False)
    row = frame.iloc[0]
    feature_as_of = pd.Timestamp(row["prediction_cutoff_at"]).tz_localize(
        "Asia/Seoul"
    ).isoformat()
    return {
        "reservation_id": str(row["reservation_id"]),
        "feature_as_of": feature_as_of,
        "feature_set_version": runtime.config.feature_set_version,
        "input_schema_version": "reservation-no-show-input-v1.0",
    }


def rpc(request_id: int, method: str, params: dict | None = None) -> dict:
    request = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    return request


def run_stdio_fixture(arguments: dict[str, str]) -> list[dict]:
    requests = [
        rpc(11, "initialize", {"protocolVersion": "2025-06-18"}),
        rpc(12, "tools/list"),
        rpc(13, "tools/call", {"name": "predict-reservation-no-show", "arguments": arguments}),
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
    payload = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in requests)
    stdout, stderr = process.communicate(payload, timeout=30)
    if process.returncode != 0:
        raise RuntimeError(f"stdio MCP failed: {stderr}")
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def write_local_config(path: Path) -> None:
    value = {
        "mcpServers": {
            "answervice-no-show-ml": {
                "command": str(Path(sys.executable).resolve()),
                "args": [str((PROJECT_DIR / "mcp_server.py").resolve())],
                "env": {
                    "ANSWERVICE_ML_TOOL_MODE": "local_demo",
                    "ANSWERVICE_ML_TOOL_ROLE": "hotel_analyst",
                },
            }
        }
    }
    write_json(path, value)


def normalize_response(response: dict) -> dict:
    value = json.loads(json.dumps(response, ensure_ascii=False))
    for item in value.get("result", {}).get("content", []):
        if item.get("type") != "text":
            continue
        try:
            payload = json.loads(item["text"])
        except (json.JSONDecodeError, TypeError):
            continue
        prediction = payload.get("prediction", {})
        if "execution_id" in prediction:
            prediction["execution_id"] = "mlrun-fixture"
        if "duration_ms" in prediction:
            prediction["duration_ms"] = 0.0
        item["text"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return value


def verify_timeout() -> bool:
    handler = NoShowPredictionToolHandler(SlowExecutor(), timeout_seconds=0.01)
    context = IntegrationContext("timeout", "trace-timeout", "actor", "hotel_analyst", "2026-08-04")
    arguments = {
        "reservation_id": "RES-1",
        "feature_as_of": "2026-08-04T18:00:00+09:00",
        "feature_set_version": "reservation-no-show-feature-v1.0",
        "input_schema_version": "reservation-no-show-input-v1.0",
    }
    try:
        handler.call(arguments, context)
    except ToolCallError as error:
        return error.code == "TOOL_TIMEOUT"
    return False


def update_gate(artifacts: Path, status: str) -> None:
    readiness_path = artifacts / "readiness_gate.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    local_gates = {
        "main_chat_router_fixture",
        "mcp_jsonrpc_fixture",
        "mcp_stdio_fixture",
        "local_hard_timeout_fixture",
    }
    for check in readiness["checks"]:
        if check["gate"] in local_gates:
            check["status"] = status
    write_json(readiness_path, readiness)
    summary_path = artifacts / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["main_chat_mcp_status"] = status
    write_json(summary_path, summary)


if __name__ == "__main__":
    main()
