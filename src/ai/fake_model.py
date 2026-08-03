"""Deterministic, dependency-free fake model adapter for consumer contract tests."""

from __future__ import annotations

from typing import Any

from .node2 import generate_sql, repair_sql
from .node1 import normalize_question
from .node3 import explain_result
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
            response = generate_sql(payload)
        elif node == "node2_repair":
            response = repair_sql(payload)
        elif node == "node3":
            response = explain_result(payload)
        else:
            raise ValueError(f"unsupported node: {node}")

        response["model"]["model_version"] = self.model_version
        response["model"]["fixture_version"] = self.version
        validate_payload(response_schema, response)
        return response
