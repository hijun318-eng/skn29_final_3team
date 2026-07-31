from __future__ import annotations

from typing import Any


class FakeModelAdapter:
    """R3 계약을 소비하는 결정론적 로컬 fake."""

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        scenario = payload.get("scenario")
        if node == "node2":
            if scenario == "g2_blocked":
                sql = "DELETE FROM pms.public.pms_stays"
            elif scenario == "repair_once":
                sql = "SELECT value FROM unknown.schema.table"
            else:
                sql = (
                    "SELECT 1 AS synthetic_value "
                    "FROM pms.public.pms_guests LIMIT 1"
                )
            references = payload["references"]
            response_references = references
            if scenario == "repair_once":
                response_references = [
                    {**references[0], "fqn": "unknown.schema.table"}
                ]
            return {
                "sql": sql,
                "references": response_references,
                "parameters": {"scenario": scenario},
                "model_version": "DRAFT-FAKE-BASE-v0.1",
            }
        if node == "node2_repair" and payload.get("attempt") == 1:
            return {
                "sql": (
                    "SELECT 1 AS synthetic_value "
                    "FROM pms.public.pms_guests LIMIT 1"
                ),
                "references": payload["references"],
                "parameters": {"scenario": scenario},
                "model_version": "DRAFT-FAKE-BASE-v0.1",
            }
        if node == "node3":
            return {
                "summary": "검증된 합성 데이터 분석 결과입니다.",
                "model_version": "DRAFT-FAKE-BASE-v0.1",
            }
        raise ValueError(f"unsupported node: {node}")
