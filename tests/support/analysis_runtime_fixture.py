"""Test-only analysis runtime doubles; never use their output as production evidence."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlglot import exp

from app.ports.data_platform import AssetCandidateSet, ExecutionAssetSelection
from src.ai.schema import validate_payload
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2


@dataclass(frozen=True, slots=True)
class AnalysisRuntimeMetadata:
    """Complete synthetic metadata supplied to the test-only DataPlatform double."""

    assets: tuple[dict[str, Any], ...]
    schemas: dict[str, dict[str, Any]]
    metric_terms: dict[str, dict[str, Any]]
    result_rows: tuple[dict[str, Any], ...]


def default_analysis_runtime_metadata() -> AnalysisRuntimeMetadata:
    fqn = "quasar_lab.semantic.measure_events"
    urn = (
        "urn:li:dataset:(urn:li:dataPlatform:trino,"
        "quasar_lab.semantic.measure_events,PROD)"
    )
    metric_id = "reviewed_measure"
    result_field = "reviewed_total"
    metric = {
        "id": metric_id,
        "asset_fqn": fqn,
        "field": "measure_value",
        "aggregation": "sum",
        "time_field": "recorded_on",
        "result_field": result_field,
        "unit": "fixture_units",
        "reduction": "sum",
        "dimensions": [],
        "governance_version": RUNTIME_GOVERNANCE_VERSION_V2,
        "visibility": "BUSINESS",
        "allowed_roles": ["analyst"],
        "contains_pii": False,
        "allowed_join_ids": [],
        "join_required": False,
        "query_strategies": ["RAW_APPROVED_DETAIL"],
        "required_filters": [{
            "field": "record_state",
            "operator": "eq",
            "value_type": "string",
            "value": "included",
            "parameter": "record_state_filter",
        }],
    }
    asset = {
        "urn": urn,
        "fqn": fqn,
        "name": "TEST FIXTURE measure events",
        "schema_version": "fixture-schema-v1",
        "seed_version": "fixture-data-v1",
        "synthetic": True,
        "context_release": "fixture-context-v1",
        "policy_version": "fixture-policy-v1",
        "grain": {"kind": "event", "keys": ["event_id"]},
        "join_ids": [],
        "metrics": [metric],
        "required_filters": [],
        "dimensions": [],
        "time_metadata": {
            "calendar_id": "gregorian-fixture",
            "start_parameter": "window_start",
            "end_parameter": "window_end",
            "fields": [{
                "field": {"asset_fqn": fqn, "column": "recorded_on"},
                "native_type": "date",
                "bucket": "day",
                "timezone_mode": "context",
            }],
        },
        "query_policy": {
            "dialect": "trino",
            "statement_type": "select",
            "read_only": True,
            "require_limit": True,
            "max_limit": 100,
            "allowed_functions": ["SUM", "CAST"],
            "allowed_catalogs": [fqn.split(".", 1)[0]],
        },
    }
    schema = {
        "urn": urn,
        "columns": [
            {"name": "event_id", "native_type": "varchar", "nullable": False, "role": "identifier"},
            {"name": "recorded_on", "native_type": "date", "nullable": False, "role": "time"},
            {"name": "measure_value", "native_type": "double", "nullable": False, "role": "measure"},
            {"name": "record_state", "native_type": "varchar", "nullable": False, "role": "attribute"},
        ],
    }
    term = {
        "id": metric_id,
        "urn": f"urn:li:glossaryTerm:{metric_id}",
        "label": "Reviewed measure",
        "aliases": ["Reviewed measure", "Reviewed aggregate"],
        "definition": "Synthetic metric used only to exercise the analysis runtime.",
        "unit": "fixture_units",
        "version": "fixture-term-v1",
        "checksum": "fixture-term-checksum-v1",
    }
    return AnalysisRuntimeMetadata((asset,), {urn: schema}, {metric_id: term}, ({result_field: 17},))


def _result_metadata(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> dict[str, Any]:
    typed = []
    for name in columns:
        values = [row.get(name) for row in rows if row.get(name) is not None]
        value = values[0] if values else None
        value_type = (
            "boolean" if isinstance(value, bool)
            else "integer" if isinstance(value, int)
            else "number" if isinstance(value, float)
            else "string" if isinstance(value, str)
            else "null"
        )
        typed.append({"name": name, "type": value_type})
    canonical = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return {
        "columns": typed,
        "row_count": len(rows),
        "checksum": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


class AnalysisRuntimeDataPlatformFake:
    """Async test double driven only by injected runtime metadata and scenario state."""

    def __init__(
        self,
        metadata: AnalysisRuntimeMetadata | None = None,
        scenario: str | None = None,
    ) -> None:
        self.metadata = metadata or default_analysis_runtime_metadata()
        self.scenario = scenario
        self._queries: dict[str, dict[str, Any]] = {}
        self.cancelled_query_ids: list[str] = []
        self.executed_sql: list[str] = []
        self.closed = False

    async def _candidate_assets(self, query: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return [deepcopy(asset) for asset in self.metadata.assets]

    async def search_asset_candidates(
        self,
        query: str,
        context: dict[str, Any],
    ) -> AssetCandidateSet:
        """주입된 fixture를 immutable receipt가 있는 후보 집합으로 반환한다."""

        assets = await self._candidate_assets(query, context)
        rank = 1
        for asset in assets:
            for metric in asset.get("metrics", ()):
                if metric.get("visibility", "BUSINESS") == "BUSINESS":
                    metric["candidate_selectable"] = True
                    metric["candidate_rank"] = rank
                    metric["source_authority"] = "DATAHUB_NATIVE_METRIC_V1"
                    metric["source_urn"] = f"urn:li:metric:{metric['id']}"
                    rank += 1
        return AssetCandidateSet(
            assets=tuple(assets),
            context_release=str(self.metadata.assets[0]["context_release"]),
            catalog_checksum="1" * 64,
            canonical_checksum="2" * 64,
            product_release_id="fixture-product-release",
            runtime_projection_checksum="3" * 64,
            source_authority="DATAHUB_NATIVE_METRIC_V1",
            retrieval_mode="lexical",
        )

    async def resolve_execution_assets(
        self,
        selection: ExecutionAssetSelection,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """테스트가 주입한 전체 fixture를 production 후처리 검증에 전달한다."""

        return [deepcopy(asset) for asset in self.metadata.assets]

    async def get_asset_schema(
        self,
        urn: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if urn not in self.metadata.schemas:
            raise ValueError("unknown test fixture asset")
        return deepcopy(self.metadata.schemas[urn])

    async def get_metric_terms(
        self,
        metric_ids: tuple[str, ...],
        context: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        return {
            metric_id: deepcopy(self.metadata.metric_terms[metric_id])
            for metric_id in metric_ids
            if metric_id in self.metadata.metric_terms
        }

    async def execute_query(self, sql: str, parameters: dict[str, Any], gate_token: str) -> dict[str, Any]:
        self.executed_sql.append(sql)
        digest = hashlib.sha256(f"{sql}|{gate_token}".encode()).hexdigest()[:16]
        query_id = f"test-fixture-{digest}"
        if self.scenario == "slow":
            await asyncio.sleep(0.25)
        if self.scenario == "query_failed":
            result = {"query_id": query_id, "status": "FAILED", "rows": [], "evidence_complete": False}
        else:
            status = {
                "partial": "PARTIAL",
                "query_timeout": "TIMEOUT",
                "query_cancelled": "CANCELLED",
            }.get(self.scenario, "SUCCEEDED")
            rows = [] if self.scenario in {"empty", "suspicious_zero"} else [
                deepcopy(row) for row in self.metadata.result_rows
            ]
            columns = tuple(self.metadata.result_rows[0])
            result = {
                "query_id": query_id,
                "status": status,
                "rows": rows,
                "result_metadata": _result_metadata(rows, columns),
                "evidence_complete": self.scenario != "g3_failed",
                "zero_result_suspicious": self.scenario == "suspicious_zero",
                "filters": {},
                "sampling": {"applied": False, "returned_rows": len(rows), "total_rows": len(rows)},
                "masking": {"applied": False, "fields": []},
            }
        self._queries[query_id] = result
        return deepcopy(result)

    async def get_query_status(self, query_id: str) -> dict[str, Any]:
        return deepcopy(self._queries.get(query_id, {"query_id": query_id, "status": "NOT_FOUND"}))

    async def cancel_query(self, query_id: str) -> dict[str, Any]:
        result = self._queries.get(query_id)
        if result is None:
            return {"query_id": query_id, "status": "NOT_FOUND"}
        self.cancelled_query_ids.append(query_id)
        result["status"] = "CANCELLED"
        return deepcopy(result)

    async def get_source_health(self) -> list[dict[str, Any]]:
        return [
            {"source": asset["fqn"], "status": "TEST_FIXTURE_HEALTHY"}
            for asset in self.metadata.assets
        ]

    async def aclose(self) -> None:
        self.closed = True


Program = Mapping[str, Any] | BaseException | Callable[[str, dict[str, Any]], Any]


class MetadataDrivenAnalysisModel:
    """Programmable async Node1/2/repair/3 test model; it has no production authority."""

    version = "metadata-fixture-model-v1"

    def __init__(
        self,
        scenario: str | None = None,
        programs: Mapping[str, Iterable[Program]] | None = None,
    ) -> None:
        self.scenario = scenario
        self._programs: dict[str, deque[Program]] = defaultdict(deque)
        for node, values in (programs or {}).items():
            self._programs[node].extend(values)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.last_trace: dict[str, Any] = {}
        self.closed = False

    async def normalize_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._respond("node1", payload, self._node1)
        validate_payload("node1_response", response)
        return response

    async def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        if node == "node2" and self.scenario == "model_timeout":
            raise TimeoutError("test fixture model timeout")
        if node == "node2" and self.scenario == "invalid_model_schema":
            return {"model_version": self.version}
        if node == "node2" and self.scenario == "g2_blocked":
            plan = self._node2(payload)
            table = exp.to_table(plan["declared_assets"][0])
            plan["sql"] = exp.Delete(this=table).sql(dialect="trino")
            return plan
        if node == "node2" and self.scenario == "repair_once":
            return self._node2(payload, omit_governed_predicate=True)
        defaults = {
            "node2": self._node2,
            "node2_repair": self._node2,
            "node3": self._node3,
        }
        if node not in defaults:
            raise ValueError(f"unsupported fixture node: {node}")
        return await self._respond(node, payload, defaults[node])

    async def _respond(self, node: str, payload: dict[str, Any], default: Callable) -> dict[str, Any]:
        self.calls.append((node, deepcopy(payload)))
        self.last_trace = {
            "node": node,
            "model_version": self.version,
            "prompt_id": f"test-fixture.{node}",
            "prompt_version": "fixture-v1",
            "prompt_hash": "0" * 64,
            "duration_ms": 0,
            "attempts": 1,
            "status": "TEST_FIXTURE_SUCCESS",
        }
        value: Any = self._programs[node].popleft() if self._programs[node] else default
        if isinstance(value, BaseException):
            raise value
        if value is default:
            result = default(payload)
        elif callable(value):
            result = value(node, deepcopy(payload))
        else:
            result = value
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Mapping):
            raise TypeError("programmed fixture model response must be a mapping")
        return deepcopy(dict(result))

    def _node1(self, payload: dict[str, Any]) -> dict[str, Any]:
        terms = payload["business_terms"]
        metric_ids = sorted(name for name, value in terms.items() if value.get("kind") == "metric")
        if not metric_ids:
            raise ValueError("fixture Node1 requires runtime metric terms")
        as_of = datetime.fromisoformat(payload["as_of"])
        start = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        return {
            "normalized_question": " ".join(str(payload["question"]).split()),
            "intent_candidates": ["aggregate"],
            "measurement_source_text": str(payload["question"]),
            "measurement_source_texts": [str(payload["question"])],
            "metric_candidates": [metric_ids[0]],
            "metric_resolution": "selected",
            "selected_metric_id": metric_ids[0],
            "selected_metric_ids": [metric_ids[0]],
            "analysis_operation": "aggregate",
            "result_limit": None,
            "dimension_candidates": [],
            "filter_candidates": [],
            "period_candidates": [{"start": start.isoformat(), "end_exclusive": end.isoformat(), "source_text": "test-fixture-window"}],
            "period_relationship": "single",
            "ambiguity": {"is_ambiguous": False, "reasons": [], "clarification_question": None},
        }

    def _node2(self, payload: dict[str, Any], omit_governed_predicate: bool = False) -> dict[str, Any]:
        contracts = payload["package"].runtime_contracts
        rule = contracts["metric_rules"][0]
        source = rule["source"]["field"]
        fqn, alias = source["asset_fqn"], "runtime_source"
        column = exp.column(source["column"], table=alias)
        aggregate = {
            "sum": lambda: exp.Sum(this=column),
            "count": lambda: exp.Count(this=column),
            "count_distinct": lambda: exp.Count(this=exp.Distinct(expressions=[column])),
            "average": lambda: exp.Avg(this=column),
            "min": lambda: exp.Min(this=column),
            "max": lambda: exp.Max(this=column),
        }.get(rule["aggregation"])
        if aggregate is None or contracts["join_graph"]["edges"]:
            raise ValueError("fixture Node2 supports one governed source and one executable aggregate")
        query = exp.select(aggregate().as_(rule["result_field"])).from_(exp.to_table(fqn).as_(alias))
        time_rule = contracts["time_rules"]
        time_column = exp.column(rule["time_field"]["column"], table=alias)
        predicates = [
            exp.GTE(this=time_column, expression=exp.Cast(this=exp.Placeholder(this=time_rule["start_parameter"]), to=exp.DataType.build("DATE"))),
            exp.LT(this=time_column.copy(), expression=exp.Cast(this=exp.Placeholder(this=time_rule["end_parameter"]), to=exp.DataType.build("DATE"))),
        ]
        filters = list(rule["required_filters"])
        if omit_governed_predicate:
            filters = filters[1:] if filters else filters
            if not rule["required_filters"]:
                predicates.pop()
        operators = {"eq": exp.EQ, "gt": exp.GT, "gte": exp.GTE, "lt": exp.LT, "lte": exp.LTE}
        for item in filters:
            predicates.append(operators[item["operator"]](
                this=exp.column(item["field"]["column"], table=alias),
                expression=exp.Placeholder(this=item["parameter"]),
            ))
        query = query.where(*predicates).limit(int(contracts["query_policy"]["max_limit"]))
        columns = {source["column"], rule["time_field"]["column"]}
        columns.update(item["field"]["column"] for item in filters)
        return {
            "sql": query.sql(dialect="trino"),
            "model_version": self.version,
            "declared_assets": [fqn],
            "declared_columns": [{"asset_fqn": fqn, "column": name} for name in sorted(columns)],
            "declared_joins": [],
            "declared_metrics": [rule["id"]],
            "references": [item for item in payload.get("references", ()) if item.get("fqn") == fqn],
        }

    def _node3(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": "테스트 fixture가 런타임 메타데이터 기반 결과를 설명했습니다.",
            "model_version": self.version,
        }

    async def aclose(self) -> None:
        self.closed = True
