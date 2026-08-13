from __future__ import annotations

import hashlib
import time
from typing import Any

from src.ai.node1 import normalize_question
from src.ai.node2 import generate_sql, repair_sql
from src.ai.node3 import explain_result
from src.ai.schema import validate_payload


class FakeDataPlatformAdapter:
    _asset = {
        "urn": "urn:answervice:dataset:pms.public.pms_guests",
        "fqn": "pms.public.pms_guests",
        "name": "PMS guest fixture",
        "schema_version": "1.0.0",
        "seed_version": "20260729",
    }

    def __init__(self, scenario: str | None = None) -> None:
        self._queries: dict[str, dict[str, Any]] = {}
        self.cancelled_query_ids: list[str] = []
        self.scenario = scenario

    def search_assets(self, query: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return [{**self._asset, "query": query, "context_timezone": context["timezone"]}]

    def get_asset_schema(self, urn: str) -> dict[str, Any]:
        return {"urn": urn, "columns": [{"name": "guest_id", "type": "uuid"}]}

    def execute_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]:
        digest = hashlib.sha256(
            f"{sql}|{sorted(parameters.items())}|{gate_token}".encode()
        ).hexdigest()[:16]
        query_id = f"fake-{digest}"
        scenario = self.scenario
        if scenario == "slow":
            time.sleep(0.25)
        if scenario == "query_failed":
            result = {
                "query_id": query_id,
                "status": "FAILED",
                "rows": [],
                "evidence_complete": False,
            }
        else:
            status = "SUCCEEDED"
            if scenario == "partial":
                status = "PARTIAL"
            elif scenario == "query_timeout":
                status = "TIMEOUT"
            elif scenario == "query_cancelled":
                status = "CANCELLED"
            rows = [] if scenario in {"empty", "suspicious_zero"} else [
                {"synthetic_value": 1}
            ]
            result = {
                "query_id": query_id,
                "status": status,
                "rows": rows,
                "evidence_complete": scenario != "g3_failed",
                "zero_result_suspicious": scenario == "suspicious_zero",
                "filters": {"dataset": "synthetic"},
                "sampling": {
                    "applied": False,
                    "returned_rows": len(rows),
                    "total_rows": len(rows),
                },
                "masking": {"applied": False, "fields": ()},
            }
        self._queries[query_id] = result
        return result

    def get_query_status(self, query_id: str) -> dict[str, Any]:
        return self._queries.get(query_id, {"query_id": query_id, "status": "NOT_FOUND"})

    def cancel_query(self, query_id: str) -> dict[str, Any]:
        result = self._queries.get(query_id)
        if result is None:
            return {"query_id": query_id, "status": "NOT_FOUND"}
        self.cancelled_query_ids.append(query_id)
        result["status"] = "CANCELLED"
        return result

    def get_source_health(self) -> list[dict[str, Any]]:
        return [
            {"source": source, "status": "FAKE_HEALTHY"}
            for source in ("pms", "pos", "crm", "facility", "banquet")
        ]


class FakeModelAdapter:
    def __init__(self, scenario: str | None = None) -> None:
        self.scenario = scenario

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        scenario = self.scenario
        if node == "node2":
            if scenario == "model_timeout":
                raise TimeoutError("synthetic model timeout")
            if scenario == "invalid_model_schema":
                return {"model_version": "DRAFT-FAKE-BASE-v0.1"}
            if scenario == "g2_blocked":
                sql = "DELETE FROM pms.public.pms_stays"
            elif scenario == "repair_once":
                sql = "SELECT value FROM unknown.schema.table"
            else:
                sql = "SELECT 1 AS synthetic_value FROM pms.public.pms_guests LIMIT 1"
            references = payload["references"]
            response_references = references
            if scenario == "repair_once":
                response_references = [{**references[0], "fqn": "unknown.schema.table"}]
            return {
                "sql": sql,
                "references": response_references,
                "parameters": {},
                "model_version": "DRAFT-FAKE-BASE-v0.1",
            }
        if node == "node2_repair" and payload.get("attempt") == 1:
            return {
                "sql": "SELECT 1 AS synthetic_value FROM pms.public.pms_guests LIMIT 1",
                "references": payload["references"],
                "parameters": {},
                "model_version": "DRAFT-FAKE-BASE-v0.1",
            }
        if node == "node3":
            return {
                "summary": "검증된 합성 데이터 분석 결과입니다.",
                "model_version": "DRAFT-FAKE-BASE-v0.1",
            }
        raise ValueError(f"unsupported node: {node}")


class ContractFakeModelAdapter:
    version = "MODEL-FIXTURE-v1.0.0"
    model_version = "DRAFT-FAKE-BASE-v0.1"

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        validate_payload(f"{node}_request", payload)
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
        validate_payload(f"{node}_response", response)
        return response
