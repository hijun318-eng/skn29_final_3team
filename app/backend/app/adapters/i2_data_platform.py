from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID

from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError

from src.modelops.privacy import DIRECT_IDENTIFIER_FIELDS
from src.data.i2_adapters import (
    AdapterError,
    AdapterErrorCode,
    QueryPage,
    TrinoAdapter,
)
from app.ports.data_platform import DataPlatformAccessDenied, DataPlatformNoAssets, DataPlatformUnavailable


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
    _THREE_SOURCE_CONTEXT_VERSION = "I5-3SOURCE-CONTEXT-v1.0.0-DRAFT"
    _VIEW_CONTRACT_VERSION = "I4-DATA-v1.0.0-DRAFT"
    _BINDING_CONTRACT_VERSION = "ASSET-BINDING-v1.0.0-DRAFT"

    _DATASET_QUERY = """
query Dataset($urn: String!) {
  dataset(urn: $urn) {
    urn
    name
    status { removed }
    schemaMetadata { name fields { fieldPath nativeDataType } }
    platform { urn name }
    ownership {
      owners {
        owner {
          ... on CorpUser { urn username }
          ... on CorpGroup { urn name }
        }
        type
      }
    }
    properties { description }
    domain { domain { urn properties { name } } }
    glossaryTerms { terms { term { urn properties { name } } } }
    tags { tags { tag { urn properties { name } } } }
  }
}
""".strip()
    _SEARCH_QUERY = """
query SearchDatasets($query: String!) {
  search(input: {type: DATASET, query: $query, start: 0, count: 50}) {
    searchResults {
      entity {
        urn
        ... on Dataset {
          name
          properties { description }
          schemaMetadata { name fields { fieldPath description } }
          domain { domain { urn properties { name } } }
          ownership {
            owners {
              owner {
                ... on CorpUser { urn username }
                ... on CorpGroup { urn name }
              }
            }
          }
          glossaryTerms { terms { term { urn properties { name } } } }
          tags { tags { tag { urn properties { name } } } }
          lineage(input: {direction: UPSTREAM, start: 0, count: 100}) {
            relationships {
              entity {
                ... on Dataset {
                  urn
                  domain { domain { urn properties { name } } }
                }
              }
            }
          }
        }
      }
    }
  }
}
""".strip()
    _KOREAN_HINTS = {
        "banquet_monthly_metrics": ("연회", "행사"),
        "facility_daily_metrics": ("시설", "장애", "다운타임"),
        "fnb_daypart_metrics": ("식음", "레스토랑", "주문", "객단가"),
        "hotel_daily_metrics": ("호텔", "객실", "숙박", "점유", "매출", "adr", "revpar"),
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
    _SENSITIVE_RESULT_FIELDS = DIRECT_IDENTIFIER_FIELDS

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
    ) -> None:
        self._trino_user = trino_user
        self._datahub_url = datahub_url.rstrip("/")
        self._datahub_token = datahub_token
        self._require_live_metadata = require_live_metadata
        self._trino = _PartialAwareTrinoAdapter(
            trino_url,
            transport=self._request,
        )
        self._queries: dict[str, dict[str, Any]] = {}
        self._next_uris: dict[str, str] = {}
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
        if contract.get("synthetic") is True:
            for metric in metrics:
                for required_filter in metric["required_filters"]:
                    if required_filter["field"] == "data_period_status":
                        required_filter["value"] = "YTD_SYNTHETIC"
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
                or not self._valid_join_edges(item.get("join_edges"))
                for item in approved_joins
            )
        ):
            raise ValueError("analytics context contract approved joins are invalid")
        self._approved_joins = {
            frozenset(map(str, item["assets"])): str(item["id"])
            for item in approved_joins
        }
        self._join_policies = {
            str(item["id"]): tuple(item["join_edges"])
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
        self._join_policies[self._PMS_CRM_POS_JOIN_ID] = tuple(
            three_source["approved_join"]["join_edges"]
        )
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
        self._assets = tuple(views + raw_assets if require_live_metadata else views)
        self._live_schemas: dict[str, tuple[str, ...]] = {}
        self._catalog_sources = (
            {"source_id": "pms", "platform_instance": "pms", "dataset_urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,pms.pms_db.public.pms_stays,PROD)"},
            {"source_id": "pos", "platform_instance": "pos", "dataset_urn": "urn:li:dataset:(urn:li:dataPlatform:mysql,pos.pos_db.pos_orders,PROD)"},
            {"source_id": "crm", "platform_instance": "crm", "dataset_urn": "urn:li:dataset:(urn:li:dataPlatform:mssql,crm.crm_db.dbo.crm_member_grade_history,PROD)"},
            {"source_id": "facility", "platform_instance": "facility", "dataset_urn": "urn:li:dataset:(urn:li:dataPlatform:clickhouse,facility.facility.facility_events,PROD)"},
            {"source_id": "banquet", "platform_instance": "banquet", "dataset_urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,banquet.banquet_db.public.banquet_bookings,PROD)"},
        )

    def catalog_sources(self, allowed_source_ids: frozenset[str] | None = None) -> list[dict[str, Any]]:
        if not self._require_live_metadata:
            raise ValueError("live DataHub catalog is required")
        if not self._datahub_health():
            raise ValueError("live DataHub runtime verification is unavailable")
        if not self._trino.health():
            raise ValueError("live Trino runtime verification is unavailable")

        sources = []
        for configured in self._catalog_sources:
            if allowed_source_ids is not None and configured["source_id"] not in allowed_source_ids:
                continue
            dataset = self._datahub_dataset(configured["dataset_urn"])
            schema = dataset.get("schemaMetadata") or {}
            fields = schema.get("fields") or []
            ownership = (dataset.get("ownership") or {}).get("owners") or []
            owners = sorted(
                {
                    str((item.get("owner") or {}).get("username") or (item.get("owner") or {}).get("name") or (item.get("owner") or {}).get("urn"))
                    for item in ownership
                    if (item.get("owner") or {}).get("urn")
                }
            )
            if (
                dataset.get("urn") != configured["dataset_urn"]
                or (dataset.get("status") or {}).get("removed") is not False
                or not schema.get("name")
            ):
                raise ValueError("live DataHub metadata does not match the catalog source")
            sources.append(
                {
                    "source_id": configured["source_id"],
                    "platform": (dataset.get("platform") or {}).get("name") or configured["platform_instance"],
                    "location": schema["name"],
                    "dataset_urn": dataset["urn"],
                    "owners": owners,
                    "owner_status": "AVAILABLE" if owners else "MISSING",
                    "schema_status": "AVAILABLE" if fields else "EMPTY",
                    "column_count": len(fields),
                    "search_status": "AVAILABLE",
                    "connection_status": "AVAILABLE",
                }
            )
        return sources

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
            or not cls._valid_join_edges(
                (contract.get("approved_join") or {}).get("join_edges")
            )
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
        trino_user: str | None = None,
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
                "X-Trino-User": trino_user or self._trino_user,
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
            if not context.get("access_profile"):
                return []
            raise DataPlatformAccessDenied("analysis role is not entitled")
        profile = None
        datahub_token = self._datahub_token
        allowed_domains: frozenset[str] | None = None
        if context.get("access_profile") and self._require_live_metadata:
            from app.access_policy import resolve_access_profile
            from app.contracts import Role
            try:
                profile = resolve_access_profile(
                    UUID(str(context.get("user_id"))),
                    Role(str(context.get("role"))),
                    str(context["access_profile"]),
                )
                datahub_token = profile.credential()
            except PermissionError as error:
                raise DataPlatformAccessDenied("access profile is not entitled") from error
            except (RuntimeError, ValueError) as error:
                raise DataPlatformUnavailable("access profile credential is unavailable") from error
            allowed_domains = frozenset(profile.domains)
        selected: list[dict[str, Any]] = []
        policy_filtered = False
        column_count = 0
        query_use = self._query_use(query)
        if self._require_live_metadata:
            if not self._trino.health():
                raise DataPlatformUnavailable("live Trino runtime verification is unavailable")
            if not self._datahub_health():
                raise DataPlatformUnavailable("live DataHub runtime verification is unavailable")
        elif query_use == "approved_pms_crm_pos_join":
            if not self._three_source_verified:
                raise ValueError("versioned 3-source runtime verification is unavailable")
        elif not self._bindings_verified:
            raise ValueError("Asset Binding runtime verification is unavailable")
        candidates = self._rank_assets(query)
        search_metadata: dict[str, dict[str, Any]] = {}
        if self._require_live_metadata:
            if profile is not None:
                candidates = tuple(
                    {asset["urn"]: asset for asset in (*self._assets, *self._three_source_assets)}.values()
                )
            else:
                use_candidates = self._three_source_assets if query_use == "approved_pms_crm_pos_join" else self._assets
                candidates = tuple(asset for asset in use_candidates if query_use in asset["uses"])
            search_results = self._datahub_search(query, datahub_token)
            if not search_results:
                expanded = " OR ".join(
                    name for name, hints in self._KOREAN_HINTS.items()
                    if any(hint in query.lower() for hint in hints)
                )
                if expanded:
                    search_results = self._datahub_search(expanded, datahub_token)
            search_metadata = {str(item["urn"]): item for item in search_results}
            order = {str(item["urn"]): index for index, item in enumerate(search_results)}
            candidates = tuple(
                sorted(
                    (asset for asset in candidates if asset["urn"] in order),
                    key=lambda asset: order[asset["urn"]],
                )
            )
        for asset in candidates:
            if column_count + len(asset["columns"]) > 60:
                continue
            columns = asset["columns"]
            if self._require_live_metadata:
                live = (
                    self._datahub_dataset(asset["urn"], datahub_token)
                    if datahub_token
                    else self._datahub_dataset(asset["urn"])
                )
                schema = live.get("schemaMetadata") or {}
                columns = tuple(field["fieldPath"] for field in schema.get("fields") or ())
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
                ):
                    raise DataPlatformUnavailable("live DataHub metadata does not match the contract")
                metadata = search_metadata[asset["urn"]]
                domain = self._dataset_domain(metadata)
                tags = self._metadata_names(metadata, "tags", "tags", "tag")
                if profile is not None:
                    source_domains = self._serving_source_domains(metadata) if asset["kind"] == "view" else {domain}
                    if (
                        "AI_SEARCH_ALLOWED" not in tags
                        or not source_domains
                        or not source_domains.issubset(allowed_domains)
                        or (asset["kind"] == "raw" and domain not in allowed_domains)
                    ):
                        policy_filtered = True
                        continue
                elif allowed_domains is not None and domain not in allowed_domains:
                    continue
            self._live_schemas[asset["urn"]] = asset["columns"]
            item = {key: value for key, value in asset.items() if key != "columns"}
            item["join_ids"] = ()
            if self._require_live_metadata:
                item.update(
                    {
                        "description": str((metadata.get("properties") or {}).get("description") or ""),
                        "domain": domain,
                        "name": str(metadata.get("name") or asset["name"]),
                        "columns": tuple(
                            {
                                "name": str(field.get("fieldPath")),
                                "description": str(field.get("description") or ""),
                            }
                            for field in (metadata.get("schemaMetadata") or {}).get("fields") or ()
                            if field.get("fieldPath")
                        ),
                        "owners": self._metadata_names(metadata, "ownership", "owners", "owner"),
                        "glossary_terms": self._metadata_names(metadata, "glossaryTerms", "terms", "term"),
                        "tags": tags,
                    }
                )
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
            selected[0]["join_policies"] = tuple(
                {
                    "id": approved_join_id,
                    "left": edge["left"],
                    "right": edge["right"],
                    "cardinality": (
                        "preaggregate_then_one_to_one_month"
                        if approved_join_id == self._PMS_CRM_POS_JOIN_ID
                        else "many_to_zero_or_one"
                    ),
                    "on_predicates": tuple(edge["on_predicates"]),
                }
                for edge in self._join_policies[approved_join_id]
            )
        metrics = tuple(
            metric for metric in self._metrics if metric.get("asset_fqn") in selected_fqns
        )
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
            if policy_filtered:
                raise DataPlatformAccessDenied("DataHub assets are outside the selected profile")
            raise DataPlatformNoAssets("live DataHub returned no matching assets")
        return selected

    @staticmethod
    def _valid_join_edges(value: object) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(
                isinstance(edge, dict)
                and all(isinstance(edge.get(field), str) and edge[field] for field in ("left", "right"))
                and isinstance(edge.get("on_predicates"), list)
                and bool(edge["on_predicates"])
                and all(isinstance(item, str) and item for item in edge["on_predicates"])
                for edge in value
            )
        )

    @staticmethod
    def _dataset_domain(dataset: dict[str, Any]) -> str:
        domain = ((dataset.get("domain") or {}).get("domain") or {})
        urn = str(domain.get("urn") or "")
        return urn

    @staticmethod
    def _serving_source_domains(dataset: dict[str, Any]) -> set[str]:
        return {
            I2DataPlatformAdapter._dataset_domain(relationship.get("entity") or {})
            for relationship in ((dataset.get("lineage") or {}).get("relationships") or ())
            if I2DataPlatformAdapter._dataset_domain(relationship.get("entity") or {})
        }

    @staticmethod
    def _asset_source_domain(fqn: str) -> str:
        if fqn.startswith("serving.analytics."):
            return "hotel-analytics"
        return {
            "pms": "rooms",
            "pos": "food_and_beverage",
            "crm": "membership",
            "facility": "facility",
            "banquet": "banquet",
        }.get(fqn.split(".", 1)[0], "")

    @staticmethod
    def _metadata_names(dataset: dict[str, Any], aspect: str, entries: str, entity: str) -> tuple[str, ...]:
        values = []
        for item in (dataset.get(aspect) or {}).get(entries) or ():
            target = item.get(entity) or {}
            value = (target.get("properties") or {}).get("name") or target.get("username") or target.get("name") or target.get("urn")
            if value:
                values.append(str(value))
        return tuple(sorted(set(values)))

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
    def _query_use(cls, query: str) -> str:
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

    def _datahub_search(self, query: str, token: str | None) -> list[dict[str, Any]]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self._datahub_url}/api/graphql",
            data=json.dumps({"query": self._SEARCH_QUERY, "variables": {"query": query}}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())
        except HTTPError as error:
            if error.code in {401, 403}:
                raise DataPlatformAccessDenied("DataHub search access denied") from error
            raise DataPlatformUnavailable("live DataHub search failed") from error
        except (TimeoutError, URLError, json.JSONDecodeError) as error:
            raise DataPlatformUnavailable("live DataHub search failed") from error
        if payload.get("errors"):
            codes = {
                str((error.get("extensions") or {}).get("code") or "").upper()
                for error in payload["errors"] if isinstance(error, dict)
            }
            if codes & {"UNAUTHORIZED", "FORBIDDEN", "ACCESS_DENIED"}:
                raise DataPlatformAccessDenied("DataHub search was rejected")
            raise DataPlatformUnavailable("live DataHub search failed")
        results = ((payload.get("data") or {}).get("search") or {}).get("searchResults")
        if not isinstance(results, list):
            raise DataPlatformUnavailable("live DataHub search response is invalid")
        return [item["entity"] for item in results if isinstance(item.get("entity"), dict) and item["entity"].get("urn")]

    def _datahub_dataset(self, urn: str, token: str | None = None) -> dict[str, Any]:
        if urn.startswith("urn:li:dataset:(urn:li:dataPlatform:trino,serving.analytics."):
            return self._datahub_editable_dataset(urn, token)
        headers = {"Content-Type": "application/json"}
        credential = token or self._datahub_token
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
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
        except HTTPError as error:
            if error.code in {401, 403}:
                raise DataPlatformAccessDenied("DataHub lookup access denied") from error
            raise DataPlatformUnavailable("live DataHub lookup failed") from error
        except (TimeoutError, URLError, json.JSONDecodeError) as error:
            raise DataPlatformUnavailable("live DataHub lookup failed") from error
        if payload.get("errors"):
            codes = {
                str((error.get("extensions") or {}).get("code") or "").upper()
                for error in payload["errors"] if isinstance(error, dict)
            }
            if codes & {"UNAUTHORIZED", "FORBIDDEN", "ACCESS_DENIED"}:
                raise DataPlatformAccessDenied("DataHub lookup access denied")
            raise DataPlatformUnavailable("live DataHub lookup failed")
        if not (payload.get("data") or {}).get("dataset"):
            raise DataPlatformUnavailable("live DataHub dataset is unavailable")
        return payload["data"]["dataset"]

    def _datahub_editable_dataset(self, urn: str, token: str | None = None) -> dict[str, Any]:
        headers = {"X-RestLi-Protocol-Version": "2.0.0"}
        credential = token or self._datahub_token
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        url = (
            f"{self._datahub_url}/entitiesV2/{quote(urn, safe='')}"
            "?aspects=List(editableDatasetProperties,editableSchemaMetadata)"
        )
        try:
            with urlopen(Request(url, headers=headers), timeout=10) as response:
                payload = json.loads(response.read())
        except HTTPError as error:
            if error.code in {401, 403}:
                raise DataPlatformAccessDenied("DataHub lookup access denied") from error
            raise DataPlatformUnavailable("live DataHub lookup failed") from error
        except (TimeoutError, URLError, json.JSONDecodeError) as error:
            raise DataPlatformUnavailable("live DataHub lookup failed") from error
        aspects = payload.get("aspects") or {}
        key = (aspects.get("datasetKey") or {}).get("value") or {}
        schema = (aspects.get("editableSchemaMetadata") or {}).get("value") or {}
        fields = schema.get("editableSchemaFieldInfo") or []
        if payload.get("urn") != urn or key.get("name") is None or not fields:
            raise DataPlatformUnavailable("live DataHub dataset is unavailable")
        return {
            "urn": payload["urn"],
            "name": str(key["name"]).rsplit(".", 1)[-1],
            "status": {"removed": False},
            "schemaMetadata": {
                "name": key["name"],
                "fields": [
                    {
                        "fieldPath": item["fieldPath"],
                        "nativeDataType": "contract",
                    }
                    for item in fields
                    if isinstance(item, dict) and item.get("fieldPath")
                ],
            },
        }

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
        trino_principal: str | None = None,
    ) -> dict[str, Any]:
        if not gate_token:
            raise ValueError("G2 gate token is required")
        if trino_principal is not None and not re.fullmatch(
            r"answervice_[a-z_]+", trino_principal
        ):
            raise ValueError("Trino principal is invalid")
        bound_sql = self._bind_parameters(sql, parameters)
        trino = self._trino
        if trino_principal is not None:
            trino = _PartialAwareTrinoAdapter(
                self._trino.base_url,
                transport=lambda method, url, body: self._request(
                    method, url, body, trino_principal
                ),
            )
        try:
            explain = self._collect(
                trino.execute(f"EXPLAIN (TYPE VALIDATE) {bound_sql}"),
                trino=trino,
            )
            page = trino.execute(bound_sql)
            result = self._collect(page, trino=trino, sql=bound_sql)
        except AdapterError as error:
            if error.code == AdapterErrorCode.TIMEOUT:
                raise TimeoutError(str(error)) from error
            raise ValueError(str(error)) from error
        result["explain"] = {
            "query_id": explain["query_id"],
            "status": explain["status"],
            "validation_type": "TYPE_VALIDATE",
        }
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
        trino: TrinoAdapter | None = None,
        sql: str | None = None,
    ) -> dict[str, Any]:
        trino = trino or self._trino
        page = first
        columns = page.columns
        rows = list(page.rows)
        warnings = list(page.warnings)
        while page.next_uri:
            self._next_uris[page.query_id] = page.next_uri
            try:
                page = trino.next_page(page.next_uri)
            except AdapterError as error:
                raise ValueError(str(error)) from error
            columns = page.columns or columns
            rows.extend(page.rows)
            warnings.extend(page.warnings)
        shaped = [dict(zip(columns, row)) for row in rows]
        expects_nonempty, projected_sensitive_fields = self._result_expectations(sql)
        sensitive_fields = tuple(
            sorted(
                projected_sensitive_fields
                | {
                    column.lower()
                    for column in columns
                    if column.lower() in self._SENSITIVE_RESULT_FIELDS
                }
            )
        )
        return {
            "query_id": page.query_id,
            "status": "PARTIAL" if partial or warnings else "SUCCEEDED",
            "rows": shaped,
            "evidence_complete": bool(page.query_id and columns and not sensitive_fields),
            "zero_result_suspicious": expects_nonempty and not shaped,
            "filters": {},
            "sampling": {
                "applied": False,
                "returned_rows": len(shaped),
                "total_rows": len(shaped),
            },
            "masking": {"applied": False, "fields": sensitive_fields},
        }

    @classmethod
    def _result_expectations(cls, sql: str | None) -> tuple[bool, set[str]]:
        if not sql:
            return False, set()
        try:
            select = parse_one(sql, read="trino").find(exp.Select)
        except SqlglotError:
            return False, set()
        if select is None:
            return False, set()
        sensitive = {
            column.name.lower()
            for projection in select.expressions
            if projection.find(exp.AggFunc) is None
            for column in projection.find_all(exp.Column)
            if column.name.lower() in cls._SENSITIVE_RESULT_FIELDS
        }
        expects_nonempty = (
            any(projection.find(exp.AggFunc) for projection in select.expressions)
            and select.args.get("group") is None
        )
        return expects_nonempty, sensitive

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
