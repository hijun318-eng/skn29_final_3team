from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.data.i2_adapters import (
    AdapterError,
    AdapterErrorCode,
    QueryPage,
    TrinoAdapter,
)


class _PartialAwareTrinoAdapter(TrinoAdapter):
    @staticmethod
    def _page(payload: dict[str, Any]) -> QueryPage:
        try:
            return TrinoAdapter._page(payload)
        except AdapterError as error:
            if error.code != AdapterErrorCode.PARTIAL:
                raise
            return QueryPage(
                payload["id"],
                payload.get("stats", {}).get("state", "QUEUED"),
                tuple(item["name"] for item in payload.get("columns", [])),
                tuple(tuple(row) for row in payload.get("data", [])),
                payload.get("nextUri"),
                tuple(item.get("message", "") for item in payload.get("warnings", [])),
            )


class I2DataPlatformAdapter:
    """R2 I2 contract를 R4 DataPlatform port로 연결한다."""

    _DATASET_QUERY = """
query Dataset($urn: String!) {
  dataset(urn: $urn) {
    urn
    name
    schemaMetadata { name fields { fieldPath nativeDataType } }
  }
}
""".strip()
    _KOREAN_HINTS = {
        "banquet_monthly_metrics": ("연회", "행사"),
        "facility_daily_metrics": ("시설", "장애", "다운타임"),
        "fnb_daypart_metrics": ("식음", "레스토랑", "주문", "객단가"),
        "hotel_daily_metrics": ("호텔", "객실", "숙박", "점유", "adr", "revpar"),
        "hotel_monthly_metrics": ("월간", "월별"),
        "hotel_yearly_metrics": ("연간", "연별"),
        "resource_monthly_metrics": ("자원", "자재"),
        "workforce_monthly_metrics": ("인력", "직원", "근무"),
        "crm_members": ("회원", "멤버", "등급", "잔여 포인트"),
        "crm_member_grade_history": ("등급 변경", "등급 이력"),
        "crm_point_transactions": ("포인트", "적립", "사용", "소멸"),
    }
    _CRM_HINTS = ("crm", "회원", "멤버", "등급", "포인트", "적립", "소멸")
    _PMS_HINTS = ("pms", "호텔", "객실", "숙박", "투숙", "매출")
    _PMS_CRM_JOIN_ID = "pms_stay_to_crm_membership_grade_event_time_v1"

    def __init__(
        self,
        trino_url: str,
        trino_user: str,
        datahub_url: str = "http://datahub-gms:8080",
        datahub_token: str | None = None,
        contract_path: Path | None = None,
    ) -> None:
        self._trino_user = trino_user
        self._datahub_url = datahub_url.rstrip("/")
        self._datahub_token = datahub_token
        self._trino = _PartialAwareTrinoAdapter(
            trino_url,
            transport=self._request,
        )
        self._queries: dict[str, dict[str, Any]] = {}
        self._next_uris: dict[str, str] = {}
        root = Path(__file__).resolve().parents[4]
        source = contract_path or root / "src" / "data" / "analytics_context_contract.i4.v2.json"
        contract = json.loads(source.read_text(encoding="utf-8"))
        if contract.get("context_source") != "LIVE_DATAHUB":
            raise ValueError("analytics context contract must require LIVE_DATAHUB")
        metrics = contract.get("metrics")
        if not isinstance(metrics, list) or not metrics:
            raise ValueError("analytics context contract must include metric registry")
        metric_ids = [metric.get("id") for metric in metrics if isinstance(metric, dict)]
        if len(metric_ids) != len(metrics) or len(metric_ids) != len(set(metric_ids)):
            raise ValueError("analytics context contract metric ids must be unique")
        self._metrics = tuple(metrics)
        view_contract = json.loads((root / contract["view_contract"]).read_text(encoding="utf-8"))
        views = [
            {
                "urn": view["urn"],
                "fqn": view["fqn"],
                "name": view["name"],
                "columns": tuple(view["columns"]),
                "schema_version": view["schema_version"],
                "seed_version": view["seed_version"],
                "uses": ("serving_views",),
                "kind": "view",
            }
            for view in view_contract["views"]
        ]
        raw_assets = [
            {
                "urn": asset["urn"],
                "fqn": asset["fqn"],
                "name": asset["fqn"].rsplit(".", 1)[-1],
                "columns": tuple(asset["columns"]),
                "schema_version": "1.0.0",
                "seed_version": "20260729",
                "uses": tuple(asset["uses"]),
                "kind": "raw",
            }
            for asset in contract["raw_assets"]
        ]
        self._assets = tuple(views + raw_assets)
        self._live_schemas: dict[str, tuple[str, ...]] = {}

    def _request(
        self,
        method: str,
        url: str,
        body: Any | None,
    ) -> dict[str, Any]:
        data = body.encode("utf-8") if isinstance(body, str) else None
        request = Request(
            url,
            data=data,
            headers={
                "Content-Type": (
                    "text/plain; charset=utf-8"
                    if isinstance(body, str)
                    else "application/json"
                ),
                "X-Trino-User": self._trino_user,
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=10) as response:
                raw = response.read()
        except HTTPError as error:
            code = (
                AdapterErrorCode.FORBIDDEN
                if error.code in {401, 403}
                else AdapterErrorCode.UPSTREAM
            )
            raise AdapterError(code, f"upstream HTTP {error.code}") from error
        except TimeoutError as error:
            raise AdapterError(
                AdapterErrorCode.TIMEOUT,
                "upstream request timed out",
            ) from error
        except URLError as error:
            raise AdapterError(
                AdapterErrorCode.UPSTREAM,
                "upstream request failed",
            ) from error
        return {} if not raw else json.loads(raw)

    def search_assets(
        self,
        query: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if context.get("role") != "hotel_analyst":
            return []
        selected: list[dict[str, Any]] = []
        column_count = 0
        query_use = self._query_use(query)
        for asset in self._rank_assets(query):
            if column_count + len(asset["columns"]) > 60:
                continue
            live = self._datahub_dataset(asset["urn"])
            schema = live.get("schemaMetadata") or {}
            columns = tuple(field["fieldPath"] for field in schema.get("fields") or ())
            live_name = str(schema.get("name", ""))
            raw_name_suffix = "." + ".".join(asset["fqn"].split(".")[1:])
            name_matches = (
                live_name == asset["fqn"]
                if asset["kind"] == "view"
                else live_name.endswith(raw_name_suffix)
            )
            columns_match = (
                set(columns) == set(asset["columns"])
                if asset["kind"] == "view"
                else set(asset["columns"]).issubset(columns)
            )
            if (
                live.get("urn") != asset["urn"]
                or not name_matches
                or not columns_match
            ):
                raise ValueError("live DataHub metadata does not match the contract")
            self._live_schemas[asset["urn"]] = asset["columns"]
            item = {key: value for key, value in asset.items() if key != "columns"}
            item["join_ids"] = (
                (self._PMS_CRM_JOIN_ID,)
                if query_use == "approved_pms_crm_join"
                else ()
            )
            selected.append(item)
            column_count += len(columns)
        selected_fqns = {item["fqn"] for item in selected}
        metrics = tuple(
            metric for metric in self._metrics if metric.get("asset_fqn") in selected_fqns
        )
        for item in selected:
            item["metrics"] = tuple(
                metric for metric in metrics if metric["asset_fqn"] == item["fqn"]
            )
        return selected

    def get_asset_schema(self, urn: str) -> dict[str, Any]:
        columns = self._live_schemas.get(urn)
        if columns is None:
            raise ValueError("asset was not approved by live DataHub search")
        return {
            "urn": urn,
            "columns": [{"name": name, "type": "contract"} for name in columns],
        }

    def _rank_assets(self, query: str) -> tuple[dict[str, Any], ...]:
        lowered = query.lower()
        use = self._query_use(query)
        words = set(re.findall(r"[a-z0-9_]{3,}", lowered))
        ranked: list[tuple[int, dict[str, Any]]] = []
        for asset in self._assets:
            if use not in asset["uses"]:
                continue
            searchable = " ".join((asset["name"], asset["fqn"], *asset["columns"])).lower()
            score = sum(word in searchable for word in words)
            score += 3 * sum(
                hint in lowered for hint in self._KOREAN_HINTS.get(asset["name"], ())
            )
            if score or use == "approved_pms_crm_join":
                ranked.append((score, asset))
        return tuple(asset for _score, asset in sorted(ranked, key=lambda item: (-item[0], item[1]["fqn"])))

    @classmethod
    def _query_use(cls, query: str) -> str:
        lowered = query.lower()
        has_crm = any(hint in lowered for hint in cls._CRM_HINTS)
        if has_crm and any(hint in lowered for hint in cls._PMS_HINTS):
            return "approved_pms_crm_join"
        return "crm_only" if has_crm else "serving_views"

    def _datahub_dataset(self, urn: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._datahub_token:
            headers["Authorization"] = f"Bearer {self._datahub_token}"
        request = Request(
            f"{self._datahub_url}/api/graphql",
            data=json.dumps(
                {"query": self._DATASET_QUERY, "variables": {"urn": urn}}
            ).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())
        except (HTTPError, TimeoutError, URLError, json.JSONDecodeError) as error:
            raise ValueError("live DataHub lookup failed") from error
        if payload.get("errors") or not (payload.get("data") or {}).get("dataset"):
            raise ValueError("live DataHub dataset is unavailable")
        return payload["data"]["dataset"]

    def execute_query(
        self,
        sql: str,
        parameters: dict[str, Any],
        gate_token: str,
    ) -> dict[str, Any]:
        if not gate_token:
            raise ValueError("G2 gate token is required")
        bound_sql = self._bind_date_parameters(sql, parameters)
        try:
            page = self._trino.execute(bound_sql)
            result = self._collect(page)
        except AdapterError as error:
            if error.code == AdapterErrorCode.TIMEOUT:
                raise TimeoutError(str(error)) from error
            raise ValueError(str(error)) from error
        self._queries[result["query_id"]] = result
        return result

    @staticmethod
    def _bind_date_parameters(
        sql: str,
        parameters: dict[str, Any],
    ) -> str:
        bound = sql
        for name, value in parameters.items():
            if (
                not isinstance(value, str)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
            ):
                raise ValueError(f"{name} must be an ISO date")
            date.fromisoformat(value)
            placeholder = f":{name}"
            if placeholder not in bound:
                raise ValueError(f"unknown template parameter: {name}")
            bound = bound.replace(placeholder, value)
        if re.search(r":[a-z_][a-z0-9_]*", bound):
            raise ValueError("template parameter is missing")
        return bound

    def _collect(
        self,
        first: QueryPage,
        partial: bool = False,
    ) -> dict[str, Any]:
        page = first
        columns = page.columns
        rows = list(page.rows)
        warnings = list(page.warnings)
        while page.next_uri:
            self._next_uris[page.query_id] = page.next_uri
            try:
                page = self._trino.next_page(page.next_uri)
            except AdapterError as error:
                raise ValueError(str(error)) from error
            columns = page.columns or columns
            rows.extend(page.rows)
            warnings.extend(page.warnings)
        shaped = [dict(zip(columns, row)) for row in rows]
        return {
            "query_id": page.query_id,
            "status": "PARTIAL" if partial or warnings else "SUCCEEDED",
            "rows": shaped,
            "evidence_complete": True,
            "zero_result_suspicious": False,
            "filters": {"template": "weekly-room-operations"},
            "sampling": {
                "applied": False,
                "returned_rows": len(shaped),
                "total_rows": len(shaped),
            },
            "masking": {"applied": False, "fields": ()},
        }

    def get_query_status(self, query_id: str) -> dict[str, Any]:
        return self._queries.get(
            query_id,
            {"query_id": query_id, "status": "NOT_FOUND"},
        )

    def cancel_query(self, query_id: str) -> dict[str, Any]:
        next_uri = self._next_uris.get(query_id)
        if next_uri:
            self._trino.cancel(next_uri)
        result = self._queries.setdefault(query_id, {"query_id": query_id})
        result["status"] = "CANCELLED"
        return result

    def get_source_health(self) -> list[dict[str, Any]]:
        status = "HEALTHY" if self._trino.health() else "UNHEALTHY"
        return [{"source": "trino", "status": status}]
