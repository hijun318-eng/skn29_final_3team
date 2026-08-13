from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from threading import local
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ports.data_platform import NoEntitledAssetsError
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

    _CONTEXT_CONTRACT_VERSION = "I4-CONTEXT-v2.3.0-DRAFT"
    _THREE_SOURCE_CONTEXT_VERSION = "I5-3SOURCE-CONTEXT-v1.1.0-DRAFT"
    _VIEW_CONTRACT_VERSION = "I4-DATA-v1.0.0-DRAFT"
    _BINDING_CONTRACT_VERSION = "ASSET-BINDING-v1.0.0-DRAFT"

    _DATASET_QUERY = """
query Dataset($urn: String!) {
  dataset(urn: $urn) {
    urn
    name
    status { removed }
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
    _CRM_HINTS = ("crm", "고객", "회원", "멤버", "등급", "포인트", "적립", "소멸")
    _PMS_HINTS = ("pms", "호텔", "객실", "숙박", "투숙", "매출")
    _POS_HINTS = ("pos", "식음", "f&b", "주문", "통합 매출")
    _PMS_CRM_POS_JOIN_ID = "pms_crm_pos_gold_revenue_month_v1"

    def __init__(
        self,
        trino_url: str,
        trino_user: str,
        datahub_url: str = "http://datahub-gms:8080",
        datahub_token: str | None = None,
        contract_path: Path | None = None,
        binding_path: Path | None = None,
        three_source_path: Path | None = None,
        require_live_metadata: bool = True,
        allow_template_assets: bool = False,
    ) -> None:
        self._trino_user = trino_user
        self._datahub_url = datahub_url.rstrip("/")
        self._datahub_token = datahub_token
        self._require_live_metadata = require_live_metadata
        self._allow_template_assets = allow_template_assets
        self._trino = _PartialAwareTrinoAdapter(
            trino_url,
            transport=self._request,
        )
        self._queries: dict[str, dict[str, Any]] = {}
        self._next_uris: dict[str, str] = {}
        self._cancellation = local()
        root = Path(__file__).resolve().parents[4]
        source = contract_path or root / "src" / "data" / "analytics_context_contract.i4.v2.json"
        contract = json.loads(source.read_text(encoding="utf-8"))
        if (
            contract.get("contract_version") != self._CONTEXT_CONTRACT_VERSION
            or contract.get("context_source") != "LIVE_DATAHUB"
        ):
            raise ValueError("analytics context contract version is not approved")
        metrics = contract.get("metrics")
        if not isinstance(metrics, list) or not metrics:
            raise ValueError("analytics context contract must include metric registry")
        metric_ids = [metric.get("id") for metric in metrics if isinstance(metric, dict)]
        if len(metric_ids) != len(metrics) or len(metric_ids) != len(set(metric_ids)):
            raise ValueError("analytics context contract metric ids must be unique")
        self._metrics = tuple(metrics)
        approved_joins = contract.get("approved_joins")
        if (
            not isinstance(approved_joins, list)
            or not approved_joins
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not isinstance(item.get("assets"), list)
                or not item["assets"]
                for item in approved_joins
            )
        ):
            raise ValueError("analytics context contract approved joins are invalid")
        self._approved_joins = {
            frozenset(map(str, item["assets"])): str(item["id"])
            for item in approved_joins
        }
        self._approved_join_metrics = {
            frozenset(map(str, item["assets"])): tuple(item.get("metrics", ()))
            for item in approved_joins
        }
        if (
            len(self._approved_joins) != len(approved_joins)
            or len({item["id"] for item in approved_joins}) != len(approved_joins)
        ):
            raise ValueError("analytics context contract approved joins must be unique")
        three_source = json.loads(
            (three_source_path or root / "src" / "data" / "pms_crm_pos_context.i5.v1.json")
            .read_text(encoding="utf-8")
        )
        self._validate_three_source_context(three_source)
        self._three_source_verified = True
        self._three_source_filters = tuple(three_source["required_filters"])
        self._three_source_parameters = tuple(three_source["parameter_bindings"])
        self._three_source_assets = tuple(
            {
                "urn": asset["urn"],
                "fqn": asset["fqn"],
                "name": asset["fqn"].rsplit(".", 1)[-1],
                "columns": tuple(asset["columns"]),
                "schema_version": "1.0.0",
                "seed_version": "20260729",
                "uses": ("approved_pms_crm_pos_join",),
                "kind": "raw",
                "column_types": dict(asset.get("column_types") or {}),
            }
            for asset in three_source["assets"]
        )
        view_contract = json.loads((root / contract["view_contract"]).read_text(encoding="utf-8"))
        verification = view_contract.get("verification") or {}
        if (
            view_contract.get("contract_version") != self._VIEW_CONTRACT_VERSION
            or view_contract.get("validation_only") is not True
            or any(
                (verification.get(name) or {}).get("status") != "PASS"
                for name in ("trino_columns", "trino_select", "read_only_policy")
            )
        ):
            raise ValueError("analytics View binding is not verified")
        health = json.loads(
            (
                binding_path
                or root / "src" / "data" / "asset_binding_health.i5.v1.json"
            ).read_text(encoding="utf-8")
        )
        bindings = health.get("bindings")
        required_binding_fields = {
            "binding_id",
            "urn",
            "fqn",
            "status",
            "version",
            "verified_at",
            "provenance",
        }
        if (
            health.get("contract_version") != self._BINDING_CONTRACT_VERSION
            or set(health.get("required_fields") or ()) != required_binding_fields
            or not isinstance(bindings, list)
            or len(bindings) != len(view_contract.get("views", ()))
            or any(
                not isinstance(item, dict)
                or not required_binding_fields.issubset(item)
                or any(not item.get(key) for key in ("binding_id", "urn", "fqn", "version"))
                for item in bindings
            )
            or any(
                len({item.get(key) for item in bindings}) != len(bindings)
                for key in ("binding_id", "urn", "fqn")
            )
        ):
            raise ValueError("Asset Binding health contract is invalid")
        binding_by_fqn = {item["fqn"]: item for item in bindings}
        if {
            (item.get("urn"), item.get("fqn"), item.get("version"))
            for item in bindings
        } != {
            (view.get("urn"), view.get("fqn"), view.get("schema_version"))
            for view in view_contract["views"]
        }:
            raise ValueError("Asset Binding identity does not match the View contract")
        self._bindings_verified = (
            health.get("status") == "HEALTHY"
            and health.get("runtime_execution") == "PASS"
            and all(self._binding_verified(item) for item in bindings)
        )
        self._live_runtime_verified = self._bindings_verified
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
                "binding_id": binding_by_fqn[view["fqn"]]["binding_id"],
                "binding_status": binding_by_fqn[view["fqn"]]["status"],
                "binding_version": binding_by_fqn[view["fqn"]]["version"],
            }
            for view in view_contract["views"]
            if view.get("schema_version") == view_contract.get("schema_version")
            and str(view.get("fqn", "")).startswith("serving.analytics.")
            and view.get("urn")
            == (
                "urn:li:dataset:(urn:li:dataPlatform:trino,"
                f"{view.get('fqn')},PROD)"
            )
        ]
        if len(views) != len(view_contract.get("views", ())):
            raise ValueError("analytics View binding identity does not match the contract")
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
        self._assets = tuple(
            views + raw_assets
            if require_live_metadata or allow_template_assets
            else views
        )
        self._live_schemas: dict[str, tuple[dict[str, str], ...]] = {}

    @staticmethod
    def _binding_verified(binding: dict[str, Any]) -> bool:
        verified_at = binding.get("verified_at")
        provenance = binding.get("provenance") or {}
        datahub = provenance.get("datahub_exact_search") or {}
        trino = provenance.get("trino_metadata") or {}
        try:
            timestamp = datetime.fromisoformat(str(verified_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        return (
            binding.get("status") == "VERIFIED"
            and isinstance(verified_at, str)
            and verified_at.endswith("Z")
            and timestamp.utcoffset() is not None
            and timestamp.utcoffset().total_seconds() == 0
            and datahub.get("status") == "PASS"
            and trino.get("status") == "PASS"
            and re.fullmatch(
                r"[0-9a-f]{64}", str(datahub.get("response_sha256") or "")
            )
            is not None
            and re.fullmatch(
                r"[0-9a-f]{64}", str(trino.get("result_sha256") or "")
            )
            is not None
        )

    @classmethod
    def _validate_three_source_context(cls, contract: dict[str, Any]) -> None:
        filters = contract.get("required_filters")
        bindings = contract.get("parameter_bindings")
        assets = contract.get("assets")
        if (
            contract.get("contract_version") != cls._THREE_SOURCE_CONTEXT_VERSION
            or contract.get("synthetic") is not True
            or not isinstance(filters, list)
            or not isinstance(bindings, list)
            or not isinstance(assets, list)
            or not assets
            or (contract.get("approved_join") or {}).get("id")
            != cls._PMS_CRM_POS_JOIN_ID
            or (contract.get("gold_evidence") or {}).get("runtime", {}).get("status")
            != "PASS"
            or re.fullmatch(
                r"[0-9a-f]{64}",
                str((contract.get("gold_evidence") or {}).get("sql_sha256") or ""),
            )
            is None
            or re.fullmatch(
                r"[0-9a-f]{64}",
                str((contract.get("gold_evidence") or {}).get("result_sha256") or ""),
            )
            is None
        ):
            raise ValueError("three-source Context contract is invalid")
        expected_names = [
            "period_start",
            "period_end_exclusive",
            *(f"required_filter_{index}" for index in range(1, len(filters) + 1)),
        ]
        if [item.get("name") for item in bindings] != expected_names:
            raise ValueError("three-source Context parameter order is invalid")
        if any(
            set(item) != {"field", "operator", "value_type", "value"}
            or item["operator"] != "eq"
            or not cls._typed_value_is_valid(item["value_type"], item["value"])
            for item in filters
        ) or any(
            set(item) != {"name", "value_type", "value"}
            or not cls._typed_value_is_valid(item["value_type"], item["value"])
            for item in bindings
        ):
            raise ValueError("three-source Context typed value is invalid")
        for index, item in enumerate(filters, start=2):
            binding = bindings[index]
            if (binding["value_type"], binding["value"]) != (
                item["value_type"],
                item["value"],
            ):
                raise ValueError("three-source Context binding value was mutated")

    @staticmethod
    def _typed_value_is_valid(value_type: str, value: object) -> bool:
        if value_type == "boolean":
            return isinstance(value, bool)
        if value_type == "number":
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
        if value_type == "string":
            return isinstance(value, str) and bool(value)
        if value_type == "date" and isinstance(value, str):
            try:
                return date.fromisoformat(value).isoformat() == value
            except ValueError:
                return False
        return False

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
        query_use = self._query_use(query, context.get("template_id"))
        if self._require_live_metadata:
            if not self._trino.health():
                raise ValueError("live Trino runtime verification is unavailable")
            if not self._datahub_health():
                raise ValueError("live DataHub runtime verification is unavailable")
        elif query_use == "approved_pms_crm_pos_join":
            if not self._three_source_verified:
                raise ValueError("versioned 3-source runtime verification is unavailable")
        elif not self._bindings_verified:
            if not self._allow_template_assets or not self._trino.health():
                raise ValueError("Asset Binding runtime verification is unavailable")
        for asset in self._rank_assets(query, query_use):
            if column_count + len(asset["columns"]) > 60:
                continue
            columns = asset["columns"]
            column_types = dict(asset.get("column_types") or {})
            if self._require_live_metadata:
                live = self._datahub_dataset(asset["urn"])
                schema = live.get("schemaMetadata") or {}
                fields = schema.get("fields") or ()
                columns = tuple(field["fieldPath"] for field in fields)
                live_types = {
                    str(field["fieldPath"]): str(field.get("nativeDataType") or "")
                    for field in fields
                }
                live_name = str(schema.get("name", ""))
                raw_name = ".".join(asset["fqn"].split(".")[1:])
                name_matches = (
                    live_name == asset["fqn"]
                    if asset["kind"] == "view"
                    else live_name == raw_name or live_name.endswith("." + raw_name)
                )
                columns_match = (
                    set(columns) == set(asset["columns"])
                    if asset["kind"] == "view"
                    else set(asset["columns"]).issubset(columns)
                )
                if (
                    live.get("urn") != asset["urn"]
                    or (live.get("status") or {}).get("removed") is not False
                    or not name_matches
                    or not columns_match
                    or any(
                        live_types.get(name) != expected
                        for name, expected in column_types.items()
                    )
                ):
                    raise ValueError("live DataHub metadata does not match the contract")
                column_types = {
                    name: live_types[name]
                    for name in asset["columns"]
                    if live_types.get(name)
                }
            self._live_schemas[asset["urn"]] = tuple(
                {"name": name, "type": column_types.get(name, "contract")}
                for name in asset["columns"]
            )
            item = {key: value for key, value in asset.items() if key != "columns"}
            item["join_ids"] = ()
            selected.append(item)
            column_count += len(asset["columns"])
        selected_fqns = {item["fqn"] for item in selected}
        approved_join_id = None
        if query_use == "approved_pms_crm_pos_join":
            approved_join_id = self._PMS_CRM_POS_JOIN_ID
        elif query_use == "approved_pms_crm_join":
            approved_join_id = self._approved_joins.get(frozenset(selected_fqns))
        if approved_join_id:
            for item in selected:
                item["join_ids"] = (approved_join_id,)
        metrics = tuple(
            metric for metric in self._metrics if metric.get("asset_fqn") in selected_fqns
        )
        if query_use == "approved_pms_crm_join":
            metrics += self._approved_join_metrics.get(frozenset(selected_fqns), ())
        for item in selected:
            item_metrics = tuple(
                metric for metric in metrics if metric["asset_fqn"] == item["fqn"]
            )
            if item_metrics or query_use not in {
                "approved_pms_crm_join",
                "approved_pms_crm_pos_join",
            }:
                item["metrics"] = item_metrics
        if query_use == "approved_pms_crm_pos_join" and selected:
            selected[0]["required_filters"] = self._three_source_filters
            selected[0]["parameter_bindings"] = self._three_source_parameters
        if self._require_live_metadata and not selected:
            raise NoEntitledAssetsError("live DataHub returned no entitled matching assets")
        return selected

    def get_asset_schema(self, urn: str) -> dict[str, Any]:
        columns = self._live_schemas.get(urn)
        if columns is None:
            raise ValueError("asset was not approved by live DataHub search")
        return {
            "urn": urn,
            "columns": [dict(column) for column in columns],
        }

    def _rank_assets(
        self,
        query: str,
        query_use: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        lowered = query.lower()
        use = query_use or self._query_use(query)
        words = set(re.findall(r"[a-z0-9_]{3,}", lowered))
        ranked: list[tuple[int, dict[str, Any]]] = []
        candidates = (
            self._three_source_assets
            if use == "approved_pms_crm_pos_join"
            else self._assets
        )
        for asset in candidates:
            if use not in asset["uses"]:
                continue
            searchable = " ".join((asset["name"], asset["fqn"], *asset["columns"])).lower()
            score = sum(word in searchable for word in words)
            score += 3 * sum(
                hint in lowered for hint in self._KOREAN_HINTS.get(asset["name"], ())
            )
            if score or use in {"approved_pms_crm_join", "approved_pms_crm_pos_join"}:
                ranked.append((score, asset))
        return tuple(asset for _score, asset in sorted(ranked, key=lambda item: (-item[0], item[1]["fqn"])))

    @classmethod
    def _query_use(cls, query: str, template_id: object | None = None) -> str:
        if template_id == "weekly-room-operations":
            return "approved_pms_crm_join"
        lowered = query.lower()
        has_crm = any(hint in lowered for hint in cls._CRM_HINTS)
        if (
            has_crm
            and any(hint in lowered for hint in cls._PMS_HINTS)
            and any(hint in lowered for hint in cls._POS_HINTS)
        ):
            return "approved_pms_crm_pos_join"
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

    def _datahub_health(self) -> bool:
        try:
            with urlopen(Request(f"{self._datahub_url}/health"), timeout=10) as response:
                return response.status == 200
        except (HTTPError, TimeoutError, URLError):
            return False

    def execute_query(
        self,
        sql: str,
        parameters: dict[str, Any],
        gate_token: str,
    ) -> dict[str, Any]:
        if not gate_token:
            raise ValueError("G2 gate token is required")
        bound_sql = self._bind_parameters(sql, parameters)
        try:
            page = self._trino.execute(bound_sql)
            result = self._collect(page)
        except AdapterError as error:
            if error.code == AdapterErrorCode.TIMEOUT:
                raise TimeoutError(str(error)) from error
            raise ValueError(str(error)) from error
        result["period"] = {
            "start": self._parameter_value(parameters.get("period_start")),
            "end_exclusive": self._parameter_value(
                parameters.get("period_end_exclusive")
            ),
        }
        result["filters"] = {
            name: self._parameter_value(value)
            for name, value in parameters.items()
            if re.fullmatch(r"required_filter_\d+", name)
        }
        self._queries[result["query_id"]] = result
        return result

    def bind_cancellation(self, check: Callable[[], bool] | None) -> None:
        self._cancellation.check = check

    def _cancel_requested(self) -> bool:
        check = getattr(self._cancellation, "check", None)
        return bool(check and check())

    @staticmethod
    def _bind_parameters(
        sql: str,
        parameters: dict[str, Any],
    ) -> str:
        bound = sql
        for name, value in parameters.items():
            placeholder = f":{name}"
            if re.search(rf"{re.escape(placeholder)}(?![a-z0-9_])", bound) is None:
                raise ValueError(f"unknown template parameter: {name}")
            if isinstance(value, dict):
                if set(value) != {"value_type", "value"}:
                    raise ValueError(f"invalid typed parameter: {name}")
                value_type = value["value_type"]
                raw_value = value["value"]
            else:
                raw_value = value
                value_type = (
                    "date"
                    if name in {"period_start", "period_end_exclusive"}
                    else "boolean"
                    if isinstance(value, bool)
                    else "number"
                    if isinstance(value, (int, float))
                    else "string"
                )
            if not I2DataPlatformAdapter._typed_value_is_valid(value_type, raw_value):
                raise ValueError(f"invalid typed parameter: {name}")
            if name not in {"period_start", "period_end_exclusive"} and not re.fullmatch(
                r"required_filter_\d+", name
            ):
                raise ValueError(f"unsupported template parameter: {name}")
            if value_type == "boolean":
                literal = "TRUE" if raw_value else "FALSE"
            elif value_type == "number":
                literal = str(raw_value)
            elif value_type == "string":
                literal = "'" + str(raw_value).replace("'", "''") + "'"
            else:
                quoted = re.search(
                    rf"'[^']*{re.escape(placeholder)}(?![a-z0-9_])[^']*'",
                    bound,
                )
                literal = str(raw_value) if quoted else f"DATE '{raw_value}'"
            bound = re.sub(
                rf"{re.escape(placeholder)}(?![a-z0-9_])",
                lambda _match: literal,
                bound,
            )
        if re.search(r":[a-z_][a-z0-9_]*", bound):
            raise ValueError("template parameter is missing")
        return bound

    @staticmethod
    def _parameter_value(value: Any) -> Any:
        return value.get("value") if isinstance(value, dict) else value

    def _collect(
        self,
        first: QueryPage,
        partial: bool = False,
    ) -> dict[str, Any]:
        page = first
        columns = page.columns
        rows = list(page.rows)
        warnings = list(page.warnings)
        if self._cancel_requested():
            if page.next_uri:
                self._trino.cancel(page.next_uri)
            return self._cancelled_result(page.query_id)
        while page.next_uri:
            self._next_uris[page.query_id] = page.next_uri
            if self._cancel_requested():
                self._trino.cancel(page.next_uri)
                return self._cancelled_result(page.query_id)
            try:
                page = self._trino.next_page(page.next_uri)
            except AdapterError as error:
                raise ValueError(str(error)) from error
            columns = page.columns or columns
            rows.extend(page.rows)
            warnings.extend(page.warnings)
            if self._cancel_requested():
                if page.next_uri:
                    self._trino.cancel(page.next_uri)
                return self._cancelled_result(page.query_id)
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

    @staticmethod
    def _cancelled_result(query_id: str) -> dict[str, Any]:
        return {
            "query_id": query_id,
            "status": "CANCELLED",
            "rows": [],
            "evidence_complete": False,
            "zero_result_suspicious": False,
            "filters": {},
            "sampling": {"applied": False, "returned_rows": 0, "total_rows": 0},
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
