from __future__ import annotations

import json
import os
import sys
from typing import Any

from mcp_runtime import RoomDemandMcpRuntime


class StdioMcpServer:
    protocol_version = "2025-06-18"

    def __init__(self) -> None:
        self.runtime = RoomDemandMcpRuntime(
            os.getenv("ANSWERVICE_ML_TOOL_MODE", "disabled")
        )
        self.role = os.getenv("ANSWERVICE_ML_TOOL_ROLE", "hotel_analyst")

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "answervice-room-demand-ml",
                        "version": "1.0.0",
                    },
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        return self.runtime.dispatch(
            request, self.runtime.context(str(request_id), self.role)
        )

    def run(self) -> None:
        for line in sys.stdin:
            try:
                response = self.handle(json.loads(line))
            except Exception as error:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": type(error).__name__},
                }
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    StdioMcpServer().run()
