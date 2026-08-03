from __future__ import annotations

import json
import re
from datetime import date
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

    _assets = (
        {
            "urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,pms.public.pms_stays,PROD)",
            "fqn": "pms.public.pms_stays",
            "name": "PMS stays",
            "columns": (
                "actual_checkout_at",
                "property_id",
                "reservation_id",
                "room_revenue",
                "stay_status",
                "complimentary_flag",
                "house_use_flag",
                "is_forecast",
            ),
        },
        {
            "urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,pms.public.pms_reservations,PROD)",
            "fqn": "pms.public.pms_reservations",
            "name": "PMS reservations",
            "columns": ("property_id", "reservation_id", "guest_id"),
        },
        {
            "urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,pms.public.pms_guests,PROD)",
            "fqn": "pms.public.pms_guests",
            "name": "PMS guests",
            "columns": ("property_id", "guest_id"),
        },
        {
            "urn": "urn:li:dataset:(urn:li:dataPlatform:mssql,crm.dbo.crm_customer_map,PROD)",
            "fqn": "crm.dbo.crm_customer_map",
            "name": "CRM customer map",
            "columns": (
                "property_id",
                "pms_guest_id",
                "member_no",
                "valid_from",
                "valid_to",
            ),
        },
        {
            "urn": "urn:li:dataset:(urn:li:dataPlatform:mssql,crm.dbo.crm_member_grade_history,PROD)",
            "fqn": "crm.dbo.crm_member_grade_history",
            "name": "CRM membership grade history",
            "columns": (
                "property_id",
                "member_no",
                "grade_code",
                "valid_from",
                "valid_to",
            ),
        },
    )

    def __init__(self, trino_url: str, trino_user: str) -> None:
        self._trino_user = trino_user
        self._trino = _PartialAwareTrinoAdapter(
            trino_url,
            transport=self._request,
        )
        self._queries: dict[str, dict[str, Any]] = {}
        self._next_uris: dict[str, str] = {}

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
        return [
            {
                **{key: value for key, value in asset.items() if key != "columns"},
                "schema_version": "1.0.0",
                "seed_version": "20260729",
            }
            for asset in self._assets
        ]

    def get_asset_schema(self, urn: str) -> dict[str, Any]:
        asset = next(item for item in self._assets if item["urn"] == urn)
        return {
            "urn": urn,
            "columns": [{"name": name, "type": "contract"} for name in asset["columns"]],
        }

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
