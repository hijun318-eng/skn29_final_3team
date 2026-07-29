from __future__ import annotations

from typing import Any
from uuid import uuid4


class FakeDataPlatformAdapter:
    """Deterministic local implementation used until R2 supplies a real adapter."""

    _asset = {
        "urn": "urn:answervice:dataset:pms.public.pms_guests",
        "fqn": "pms.public.pms_guests",
        "name": "PMS guest fixture",
        "schema_version": "1.0.0",
        "seed_version": "20260729",
    }

    def __init__(self) -> None:
        self._queries: dict[str, dict[str, Any]] = {}

    def search_assets(self, query: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return [{**self._asset, "query": query, "context_timezone": context["timezone"]}]

    def get_asset_schema(self, urn: str) -> dict[str, Any]:
        return {"urn": urn, "columns": [{"name": "guest_id", "type": "uuid"}]}

    def execute_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]:
        query_id = f"fake-{uuid4().hex}"
        result = {"query_id": query_id, "status": "SUCCEEDED", "rows": [{"value": 1}]}
        self._queries[query_id] = result
        return result

    def get_query_status(self, query_id: str) -> dict[str, Any]:
        return self._queries.get(query_id, {"query_id": query_id, "status": "NOT_FOUND"})

    def cancel_query(self, query_id: str) -> dict[str, Any]:
        result = self._queries.get(query_id)
        if result is None:
            return {"query_id": query_id, "status": "NOT_FOUND"}
        result["status"] = "CANCELLED"
        return result

    def get_source_health(self) -> list[dict[str, Any]]:
        return [{"source": source, "status": "FAKE_HEALTHY"} for source in ("pms", "pos", "crm", "facility", "banquet")]
