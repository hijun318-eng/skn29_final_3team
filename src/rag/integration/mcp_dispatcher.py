from __future__ import annotations

import json
from typing import Any

from .contracts import IntegrationContext
from .coordinator import ToolCallError
from .tool_service import RegistryToolService


class McpJsonRpcDispatcher:
    """MCP 2025-06-18 tools/list and tools/call dispatcher without a network listener."""

    def __init__(self, service: RegistryToolService) -> None:
        self._service = service

    def dispatch(
        self,
        request: dict[str, Any],
        context: IntegrationContext,
    ) -> dict[str, Any]:
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0" or request_id is None:
            return self._error(request_id, -32600, "Invalid Request")
        method = request.get("method")
        if method == "tools/list":
            return self._list(request_id, context)
        if method == "tools/call":
            return self._call(request_id, request.get("params"), context)
        return self._error(request_id, -32601, "Method not found")

    def _list(self, request_id: Any, context: IntegrationContext) -> dict[str, Any]:
        tools = [
            {
                "name": item["tool_code"],
                "title": item["title"] or item["tool_code"],
                "description": item["description"],
                "inputSchema": item["input_schema_json"] or {"type": "object"},
            }
            for item in self._service.list_tools(context.role)
        ]
        return self._result(request_id, {"tools": tools})

    def _call(
        self,
        request_id: Any,
        params: Any,
        context: IntegrationContext,
    ) -> dict[str, Any]:
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return self._error(request_id, -32602, "Invalid tools/call params")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return self._error(request_id, -32602, "Invalid tools/call arguments")
        try:
            output = self._service.call_tool(params["name"], arguments, context)
        except ToolCallError as error:
            if error.code == "TOOL_NOT_REGISTERED":
                return self._error(request_id, -32602, f"Unknown tool: {params['name']}")
            return self._result(
                request_id,
                {
                    "content": [{"type": "text", "text": error.code}],
                    "isError": True,
                },
            )
        text = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
        return self._result(
            request_id,
            {"content": [{"type": "text", "text": text}], "isError": False},
        )

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
