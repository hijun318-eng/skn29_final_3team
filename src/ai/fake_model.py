"""Deterministic, dependency-free fake model adapter for consumer contract tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .node1 import normalize_question
from .node3 import explain_result
from .prompt_registry import get_prompt
from .schema import validate_payload


class FakeModelAdapter:
    version = "MODEL-FIXTURE-v1.0.0"
    model_version = "DRAFT-FAKE-BASE-v0.1"

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_schema = f"{node}_request"
        response_schema = f"{node}_response"
        validate_payload(request_schema, payload)

        if node == "node1":
            response = normalize_question(payload)
        elif node == "node2":
            response = {
                "sql": "SELECT 1 AS synthetic_value LIMIT 1",
                "references": self._references(payload["context_package"]),
                "parameters": [],
                "model": get_prompt("node2.sql").metadata(),
            }
        elif node == "node2_repair":
            response = {
                "trace_id": payload["trace_id"],
                "attempt": 1,
                "corrected_sql": "SELECT 1 AS synthetic_value LIMIT 1",
                "references": self._references(payload["context_package"]),
                "parameters": [],
                "model": get_prompt("node2.repair").metadata(),
            }
        elif node == "node3":
            response = explain_result(payload)
        else:
            raise ValueError(f"unsupported node: {node}")

        response["model"]["model_version"] = self.model_version
        response["model"]["fixture_version"] = self.version
        validate_payload(response_schema, response)
        return response

    @staticmethod
    def _references(context_package: dict[str, Any]) -> list[dict[str, Any]]:
        asset = context_package["assets"][0]
        return [
            {
                "urn": asset["urn"],
                "trino_fqn": asset["trino_fqn"],
                "columns": deepcopy(asset["columns"]),
                "join_ids": [join["id"] for join in context_package["joins"]],
                "metric_ids": [metric["id"] for metric in context_package["metrics"]],
            }
        ]
