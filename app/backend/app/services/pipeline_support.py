from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlglot import exp, parse, parse_one
from sqlglot.errors import SqlglotError

from app.contracts import (
    AnalysisRequest,
    ErrorCode,
    PeriodEvidence,
    RequestContext,
    SourceReference,
)
from app.ports.data_platform import DataPlatformAdapter
from app.adapters.context_registry_repository import (
    ContextRegistryConflict,
    ContextRegistryUnavailable,
    PublishedContextRelease,
)
from app.services.context_builder import (
    ContextAsset,
    ContextBuildError,
    ContextBuildErrorCode,
    ContextBuildRequest,
    ContextDimension,
    ContextMetric,
    ContextJoinPolicy,
    ContextPackage,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)


@lru_cache(maxsize=1)
def _metric_glossary() -> dict[str, tuple[str, ...]]:
    path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "ai"
        / "contracts"
        / "metric_glossary.i5.v1.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    if not isinstance(payload.get("version"), str) or not isinstance(metrics, dict):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "R3 metric glossary 계약을 확인할 수 없습니다.",
        )
    glossary = {
        str(metric_id): tuple(str(alias) for alias in aliases)
        for metric_id, aliases in metrics.items()
        if isinstance(aliases, list) and aliases
    }
    if len(glossary) != len(metrics):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "R3 metric glossary alias 계약을 확인할 수 없습니다.",
        )
    return glossary


@lru_cache(maxsize=1)
def _dimension_glossary() -> dict[str, tuple[str, ...]]:
    path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "ai"
        / "contracts"
        / "metric_glossary.i5.v1.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "승인 dimension glossary 계약을 확인할 수 없습니다.",
        )
    return {
        str(dimension_id): tuple(str(alias) for alias in aliases)
        for dimension_id, aliases in dimensions.items()
        if isinstance(aliases, list) and aliases
    }


def _normalize_question(payload: dict[str, object]) -> dict[str, object]:
    from src.ai.node1 import normalize_question

    return normalize_question(payload)


def _conservative_json_token_estimate(payload: dict[str, object]) -> int:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return max(1, (len(encoded) + 1) // 2)


class PipelineSupport:
    """Context, G2, 식별자 생성처럼 상태 전이와 무관한 순수 보조 로직."""

    MAX_QUERY_ROWS = 1_000
    MAX_RESULT_ROWS = 100
    MAX_RESULT_COLUMNS = 20
    MAX_RESULT_CELLS = 2_000

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        context_builder: ContextPackageBuilder,
        release_resolver: Callable[[date], PublishedContextRelease] | None = None,
    ) -> None:
        self._adapter = adapter
        self._context_builder = context_builder
        self._release_resolver = release_resolver

    def build_context(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
        route_type: str = "GENERAL",
        template_id: str | None = None,
    ) -> ContextPackage:
        if self._release_resolver is None:
            raise ContextBuildError(
                ContextBuildErrorCode.INACTIVE_RELEASE,
                "Context Registry release resolver가 구성되지 않았습니다.",
            )
        try:
            release = self._release_resolver(context.as_of)
        except (ContextRegistryConflict, ContextRegistryUnavailable) as error:
            raise ContextBuildError(
                ContextBuildErrorCode.INACTIVE_RELEASE,
                "요청 시점에 유효한 PUBLISHED Context release가 없습니다.",
            ) from error
        if context.timezone != release.timezone:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "요청 timezone과 승인 TIME_POLICY가 일치하지 않습니다.",
            )
        items = tuple(
            ContextAsset(
                urn=str(asset["urn"]),
                fqn=str(asset["fqn"]),
                columns=tuple(
                    str(column["name"])
                    for column in self._adapter.get_asset_schema(
                        str(asset["urn"])
                    )["columns"]
                ),
                join_ids=tuple(str(join_id) for join_id in asset.get("join_ids", ())),
                metrics=tuple(
                    ContextMetric(
                        id=str(metric["id"]),
                        asset_fqn=str(metric["asset_fqn"]),
                        field=str(metric["field"]),
                        aggregation=str(metric["aggregation"]),
                        time_field=str(metric["time_field"]),
                        required_filters=tuple(
                            ContextRequiredFilter(
                                field=str(item["field"]),
                                operator=str(item["operator"]),
                                value=item["value"],
                                value_type=str(item.get("value_type") or ""),
                            )
                            for item in metric["required_filters"]
                        ),
                        temporal_semantics=str(
                            metric.get("temporal_semantics") or "event_time"
                        ),
                    )
                    for metric in asset.get("metrics", ())
                ),
                dimensions=tuple(
                    ContextDimension(
                        id=str(dimension["id"]),
                        asset_fqn=str(dimension["asset_fqn"]),
                        field=str(dimension["field"]),
                    )
                    for dimension in asset.get("dimensions", ())
                ),
                metric_registry_required="metrics" in asset,
                required_filters=tuple(
                    ContextRequiredFilter(
                        field=str(item["field"]),
                        operator=str(item["operator"]),
                        value=item["value"],
                        value_type=str(item["value_type"]),
                    )
                    for item in asset.get("required_filters", ())
                ),
            )
            for asset in assets
        )
        supplied_bindings = tuple(
            ContextParameterBinding(
                str(item["name"]),
                str(item["value_type"]),
                item["value"],
            )
            for asset in assets
            for item in asset.get("parameter_bindings", ())
        )
        metric_filters = tuple(
            item
            for policy in dict.fromkeys(
                metric.required_filters
                for asset in items
                for metric in asset.metrics
            )
            for item in policy
        )
        context_metrics = tuple(metric for asset in items for metric in asset.metrics)
        current_snapshot = bool(context_metrics) and all(
            metric.temporal_semantics == "current_snapshot"
            for metric in context_metrics
        )
        parameter_bindings = supplied_bindings or tuple(
            [
                ContextParameterBinding(name, "date", payload.parameters[name])
                for name in ("period_start", "period_end_exclusive")
                if name in payload.parameters and not current_snapshot
            ]
            + [
                ContextParameterBinding(
                    f"required_filter_{index}", item.value_type, item.value
                )
                for index, item in enumerate(metric_filters, start=1)
            ]
        )
        request = ContextBuildRequest(
            context_release=release.release_hash,
            policy_version=context.access_policy_version or "policy-v1",
            time_version=release.time_policy_id,
            entitlement_hash=context.entitlement_hash or hashlib.sha256(
                f"{context.user_id}:{context.role.value}".encode()
            ).hexdigest(),
            assets=items,
            token_count=0,
            model_context_tokens=24_000,
            parameter_bindings=parameter_bindings,
            join_policies=tuple(
                ContextJoinPolicy(
                    id=str(item["id"]),
                    left=str(item["left"]),
                    right=str(item["right"]),
                    cardinality=str(item["cardinality"]),
                    on_predicates=tuple(map(str, item["on_predicates"])),
                )
                for asset in assets
                for item in asset.get("join_policies", ())
            ),
            access_profile=context.access_profile or "default",
            allowed_domains=context.allowed_domains,
            trino_principal=context.trino_principal or "",
            datahub_principal=context.datahub_principal or "",
            context_release_id=release.context_release_id,
            context_release_key=release.release_key,
            context_release_version=release.version_no,
            time_policy_id=release.time_policy_id,
            route_type=route_type,
            template_id=template_id,
            as_of=context.as_of.isoformat(),
            timezone=context.timezone,
            calendar_id=release.calendar_id,
        )
        entitled_asset_urns = frozenset(item.urn for item in items)
        draft = self._context_builder.build(
            request,
            entitled_asset_urns,
        )
        from app.adapters.contract_model import ContractModelAdapter

        model_context = ContractModelAdapter._context_package(
            {"package": draft, "context": context}
        )
        token_count = _conservative_json_token_estimate(model_context)
        return self._context_builder.build(
            replace(request, token_count=token_count),
            entitled_asset_urns,
        )

    @staticmethod
    def node1_request(
        payload: AnalysisRequest,
        context: RequestContext,
    ) -> dict[str, object]:
        glossary = _metric_glossary()
        business_terms = {
            metric_id: {"kind": "metric", "aliases": list(glossary[metric_id])}
            for metric_id in sorted(glossary)
        }
        business_terms.update(
            {
                dimension_id: {
                    "kind": "dimension",
                    "aliases": list(aliases),
                }
                for dimension_id, aliases in sorted(_dimension_glossary().items())
            }
        )
        try:
            timezone = ZoneInfo(context.timezone)
        except ZoneInfoNotFoundError as error:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context timezone을 확인할 수 없습니다.",
            ) from error
        as_of = datetime.combine(context.as_of, time.min, timezone).isoformat()
        return {
            "question": payload.question,
            "as_of": as_of,
            "timezone": context.timezone,
            "selected_metric_ids": list(payload.selected_metric_ids),
            "business_terms": business_terms,
        }

    @staticmethod
    def select_metric(
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
        normalized: dict[str, object] | None = None,
    ) -> tuple[list[dict[str, object]], str]:
        if not any("metrics" in asset for asset in assets):
            return assets, str((normalized or {}).get("normalized_question") or payload.question)
        candidates = [
            metric
            for asset in assets
            for metric in asset.get("metrics", ())
            if isinstance(metric, dict) and isinstance(metric.get("id"), str)
        ]
        candidate_ids = [str(metric["id"]) for metric in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_METRIC,
                "동일한 metric id를 중복 선택할 수 없습니다.",
            )
        normalized = normalized or _normalize_question(
            PipelineSupport.node1_request(payload, context)
        )
        if len(payload.selected_metric_ids) != len(set(payload.selected_metric_ids)):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "명시 선택한 metric id는 중복될 수 없습니다.",
            )
        selected = normalized.get("selected_metric_id")
        selected_ids = list(payload.selected_metric_ids)
        if not selected_ids and isinstance(selected, str):
            selected_ids = [selected]
        metric_candidates = normalized.get("metric_candidates")
        if (
            not selected_ids
            and isinstance(metric_candidates, list)
            and len(metric_candidates) > 1
            and any(connector in payload.question for connector in ("와", "과", "및", "+"))
            and all(isinstance(item, str) and item in candidate_ids for item in metric_candidates)
            and len({
                str(metric["asset_fqn"])
                for metric in candidates
                if metric["id"] in metric_candidates
            }) == 1
        ):
            selected_ids = list(dict.fromkeys(metric_candidates))
        if not selected_ids or any(item not in candidate_ids for item in selected_ids):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에서 권한이 있는 승인 metric 하나를 확인할 수 없습니다.",
            )
        selected_assets = []
        dimension_candidates = {
            str(item)
            for item in normalized.get("dimension_candidates", ())
            if isinstance(item, str)
        }
        for asset in assets:
            item = dict(asset)
            if "metrics" in item:
                item["metrics"] = tuple(
                    metric
                    for metric in item.get("metrics", ())
                    if isinstance(metric, dict) and metric.get("id") in selected_ids
                )
            if "dimensions" in item:
                item["dimensions"] = tuple(
                    dimension
                    for dimension in item.get("dimensions", ())
                    if isinstance(dimension, dict)
                    and dimension.get("id") in dimension_candidates
                )
            selected_assets.append(item)
        return selected_assets, str(normalized["normalized_question"])

    @staticmethod
    def g1_error(
        package: ContextPackage,
        payload: AnalysisRequest,
        context: RequestContext,
        route_type: str,
        template_id: str | None,
    ) -> tuple[ErrorCode, str] | None:
        """모든 실행 경로가 공유하는 단일 Context Gate."""
        if (
            not package.context_release_id
            or not package.context_release_key
            or package.context_release_version < 1
            or not package.time_policy_id
            or not package.assets
        ):
            return ErrorCode.CONTEXT_INCOMPLETE, "활성 Context release 근거가 없습니다."
        if (
            package.route_type != route_type
            or package.template_id != template_id
            or (route_type == "TEMPLATE") != bool(template_id)
            or payload.template_id != template_id
        ):
            return ErrorCode.ACCESS_DENIED, "승인된 route·Template binding이 일치하지 않습니다."
        if (
            package.as_of != context.as_of.isoformat()
            or package.timezone != context.timezone
            or not package.calendar_id
        ):
            return ErrorCode.CONTEXT_INCOMPLETE, "승인된 시간 정책이 요청과 일치하지 않습니다."
        period_start = payload.parameters.get("period_start")
        period_end = payload.parameters.get("period_end_exclusive")
        if (period_start is None) != (period_end is None):
            return ErrorCode.CONTEXT_INCOMPLETE, "기간 시작과 종료 경계가 모두 필요합니다."
        if period_start is not None:
            try:
                start = date.fromisoformat(str(period_start))
                end = date.fromisoformat(str(period_end))
            except ValueError:
                return ErrorCode.CONTEXT_INCOMPLETE, "기간 경계 형식이 유효하지 않습니다."
            if start >= end or end > context.as_of:
                return ErrorCode.CONTEXT_INCOMPLETE, "기간 경계가 승인 시간 정책을 벗어났습니다."
        return None

    @staticmethod
    def g2_violation(
        plan: dict[str, object],
        package: ContextPackage,
    ) -> str | None:
        if not isinstance(plan, dict):
            return "MODEL_SCHEMA_INVALID"
        sql = str(plan.get("sql", "")).strip()
        normalized = sql.lower()
        query = PipelineSupport._read_query_ast(sql)
        forbidden = {
            "insert",
            "update",
            "delete",
            "drop",
            "alter",
            "create",
            "grant",
            "revoke",
            "call",
            "merge",
            "execute",
            "prepare",
        }
        tokens = set(re.findall(r"[a-z_]+", normalized))
        if (
            query is None
            or ";" in normalized
            or "--" in normalized
            or "/*" in normalized
            or tokens.intersection(forbidden)
            or {"system", "information_schema"}.intersection(tokens)
            or re.search(
                r"\b(?:current_date|current_timestamp|localtime|now)\s*(?:\(\s*\))?",
                normalized,
            )
        ):
            return "UNSAFE_SQL"
        parameters = plan.get("parameters", {})
        if not isinstance(parameters, dict):
            return "PARAMETERS_INVALID"
        placeholder_names = re.findall(r":([a-z_][a-z0-9_]*)", normalized)
        placeholders = set(placeholder_names)
        expected_parameters = {
            item.name: (item.value_type, item.value)
            for item in package.parameter_bindings
        }
        parameters_invalid = bool(package.parameter_bindings) and (
            placeholders != set(parameters)
            or placeholders != set(expected_parameters)
            or any(
                not PipelineSupport._parameter_matches(
                    parameters[name], *expected_parameters[name]
                )
                for name in placeholders
            )
        )
        if not package.parameter_bindings and not placeholders.issubset(parameters):
            return "PARAMETERS_INVALID"
        limit = re.search(r"\blimit\s+(\d+)\s*$", normalized)
        if limit is None or int(limit.group(1)) > PipelineSupport.MAX_QUERY_ROWS:
            return "RESOURCE_POLICY_MISSING"
        allowed = {item.fqn for item in package.assets}
        references = plan.get("references")
        if not isinstance(references, list) or not references:
            return "REFERENCE_MISSING"
        referenced = {str(item.get("fqn")) for item in references}
        if not referenced.issubset(allowed):
            return "REFERENCE_OUTSIDE_CONTEXT"
        columns_by_fqn = {item.fqn: set(item.columns) for item in package.assets}
        if len(referenced) != len(references) or any(
            not isinstance(item.get("columns"), (list, tuple))
            or not set(map(str, item["columns"])).issubset(
                columns_by_fqn.get(str(item.get("fqn")), set())
            )
            for item in references
        ):
            return "REFERENCE_OUTSIDE_CONTEXT"
        expected_metric_ids = {metric.id for metric in package.metrics}
        if "pms_crm_pos_gold_revenue_month_v1" in package.approved_join_ids:
            expected_metric_ids = {"total_guest_revenue_krw"}
        has_metric_references = any("metric_ids" in item for item in references)
        if expected_metric_ids:
            referenced_metric_ids = {
                str(metric_id)
                for item in references
                for metric_id in item.get("metric_ids", ())
            }
            if referenced_metric_ids != expected_metric_ids:
                return "METRIC_REFERENCE_MISMATCH"
        cte_names = {cte.alias_or_name.lower() for cte in query.find_all(exp.CTE)}
        tables = tuple(
            table
            for table in query.find_all(exp.Table)
            if table.db or table.catalog or table.name.lower() not in cte_names
        )
        queried = {
            ".".join(part.name for part in table.parts).lower()
            for table in tables
        }
        if queried != {item.lower() for item in referenced}:
            return "SQL_REFERENCE_MISMATCH"
        if len(queried) > 1:
            referenced_join_ids = {
                str(join_id)
                for item in references
                for join_id in item.get("join_ids", ())
            }
            relation_names = queried | {
                cte.alias_or_name.lower() for cte in query.find_all(exp.CTE)
            }
            used_join_policies = tuple(
                policy
                for policy in package.join_policies
                if {policy.left.lower(), policy.right.lower()}.issubset(relation_names)
            )
            expected_join_ids = {policy.id for policy in used_join_policies}
            if (
                not used_join_policies
                or referenced_join_ids != expected_join_ids
            ):
                return "UNAPPROVED_JOIN"
            if not PipelineSupport._join_predicates_match(query, used_join_policies):
                return "UNAPPROVED_JOIN_PREDICATE"
        normalized_columns = {
            fqn.lower(): {column.lower() for column in columns}
            for fqn, columns in columns_by_fqn.items()
        }
        columns_by_alias = {
            table.alias_or_name.lower(): normalized_columns[fqn]
            for table in tables
            if (fqn := ".".join(part.name for part in table.parts).lower())
            in normalized_columns
        }
        if any(
            column.name.lower() not in columns_by_alias[column.table.lower()]
            for column in query.find_all(exp.Column)
            if column.table and column.table.lower() in columns_by_alias
        ):
            return "REFERENCE_OUTSIDE_CONTEXT"
        dimensions = {item.field.lower() for item in package.dimensions}
        if dimensions:
            selected = {
                column.name.lower()
                for projection in query.expressions
                for column in projection.find_all(exp.Column)
            }
            grouped = {
                column.name.lower()
                for column in (query.args.get("group") or exp.Group()).find_all(exp.Column)
            }
            ordered = {
                column.name.lower()
                for column in (query.args.get("order") or exp.Order()).find_all(exp.Column)
            }
            referenced_columns = {
                str(column).lower()
                for item in references
                for column in item.get("columns", ())
            }
            if not all(
                dimensions.issubset(columns)
                for columns in (selected, grouped, ordered, referenced_columns)
            ):
                return "DIMENSION_REFERENCE_MISMATCH"
        required_filters = (
            *package.required_filters,
            *(item for metric in package.metrics for item in metric.required_filters),
        )
        three_source = "pms_crm_pos_gold_revenue_month_v1" in package.approved_join_ids
        if three_source:
            if not PipelineSupport._three_source_filters_match(
                normalized, required_filters, placeholder_names
            ):
                return "METRIC_FILTER_MISSING"
        elif any(
            not PipelineSupport._required_filter_matches(
                normalized,
                item,
                parameters,
                allow_literal=False,
            )
            for item in required_filters
        ):
            return "METRIC_FILTER_MISSING"
        if parameters_invalid:
            return "PARAMETERS_INVALID"
        return None

    @staticmethod
    def _join_predicates_match(
        query: exp.Select, policies: tuple[ContextJoinPolicy, ...]
    ) -> bool:
        try:
            expected = Counter(
                PipelineSupport._predicate_group(
                    tuple(parse_one(item, read="trino") for item in policy.on_predicates),
                    {},
                )
                for policy in policies
            )
        except SqlglotError:
            return False
        actual: Counter[tuple[object, ...]] = Counter()
        for select in query.find_all(exp.Select):
            relations = [
                select.args.get("from_").this if select.args.get("from_") else None,
                *(join.this for join in select.args.get("joins") or ()),
            ]
            aliases = {
                relation.alias_or_name.lower(): ".".join(
                    part.name.lower() for part in relation.parts
                )
                for relation in relations
                if isinstance(relation, exp.Table)
            }
            for join in select.args.get("joins") or ():
                if join.args.get("on") is None:
                    return False
                actual[PipelineSupport._predicate_group((join.args["on"],), aliases)] += 1
        return bool(actual) and actual == expected

    @staticmethod
    def _predicate_group(
        expressions: tuple[exp.Expression, ...], aliases: dict[str, str]
    ) -> tuple[object, ...]:
        predicates: list[exp.Expression] = []
        for expression in expressions:
            predicates.extend(expression.flatten() if isinstance(expression, exp.And) else (expression,))
        return tuple(
            sorted(
                (PipelineSupport._canonical_predicate(item, aliases) for item in predicates),
                key=repr,
            )
        )

    @staticmethod
    def _canonical_predicate(
        expression: exp.Expression, aliases: dict[str, str]
    ) -> object:
        if isinstance(expression, exp.Paren):
            return PipelineSupport._canonical_predicate(expression.this, aliases)
        if isinstance(expression, exp.Column):
            parts = [part.name.lower() for part in expression.parts]
            qualifier = ".".join(parts[:-1])
            return ("column", aliases.get(qualifier, qualifier), parts[-1])
        if isinstance(expression, exp.Null):
            return ("null",)
        if isinstance(expression, exp.Literal):
            return ("literal", expression.this, expression.is_string)
        if isinstance(expression, exp.Boolean):
            return ("boolean", bool(expression.this))
        if isinstance(expression, (exp.EQ, exp.Or)):
            values = sorted(
                (
                    PipelineSupport._canonical_predicate(expression.this, aliases),
                    PipelineSupport._canonical_predicate(expression.expression, aliases),
                ),
                key=repr,
            )
            return (expression.key, *values)
        if isinstance(expression, (exp.GT, exp.GTE)):
            operator = "lt" if isinstance(expression, exp.GT) else "lte"
            return (
                operator,
                PipelineSupport._canonical_predicate(expression.expression, aliases),
                PipelineSupport._canonical_predicate(expression.this, aliases),
            )
        if isinstance(expression, (exp.LT, exp.LTE, exp.Is)):
            return (
                expression.key,
                PipelineSupport._canonical_predicate(expression.this, aliases),
                PipelineSupport._canonical_predicate(expression.expression, aliases),
            )
        return (expression.key, expression.sql(dialect="trino", normalize=True))

    @staticmethod
    def _read_query_ast(sql: str) -> exp.Select | None:
        try:
            statements = parse(sql, read="trino")
        except SqlglotError:
            return None
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return None
        query = statements[0]
        if (
            any(
                query.find(kind)
                for kind in (exp.DDL, exp.DML, exp.Union, exp.Intersect, exp.Except)
            )
            or any(
                not isinstance(table.this, exp.Identifier)
                for table in query.find_all(exp.Table)
            )
        ):
            return None
        return query

    @staticmethod
    def _required_filter_matches(
        sql: str,
        required: ContextRequiredFilter,
        parameters: dict[str, object],
        *,
        allow_literal: bool,
    ) -> bool:
        if required.operator != "eq":
            return False
        where = re.search(
            r"\bwhere\b(.+?)(?:\bgroup\s+by\b|\border\s+by\b|\blimit\b|$)",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if where is None or re.search(r"\bor\b", where.group(1), re.IGNORECASE):
            return False
        field = re.escape(required.field.lower().rsplit(".", 1)[-1])
        matches = re.findall(
            rf'(?<![a-z0-9_])(?:[a-z_][a-z0-9_]*\.)?"?{field}"?\s*=\s*'
            r"(?:'([^']*)'|(true|false)|:([a-z_][a-z0-9_]*))(?![a-z0-9_])",
            where.group(1),
            flags=re.IGNORECASE,
        )
        expected = str(required.value).lower()
        values = []
        for string, boolean, parameter in matches:
            if parameter:
                if parameter not in parameters:
                    return False
                value = parameters[parameter]
                if isinstance(value, dict):
                    value = value.get("value")
                values.append(str(value).lower())
            elif allow_literal:
                values.append((string or boolean).lower())
            else:
                return False
        return expected in values

    @staticmethod
    def _three_source_filters_match(
        sql: str,
        required_filters: tuple[ContextRequiredFilter, ...],
        placeholders: list[str],
    ) -> bool:
        scopes = PipelineSupport._cte_scopes(sql)
        if len(scopes) != 2:
            return False
        for scope in scopes:
            where = re.search(
                r"\bwhere\b(.+?)(?:\bgroup\s+by\b|\border\s+by\b|\blimit\b|$)",
                scope,
                re.IGNORECASE | re.DOTALL,
            )
            if where is None or any(
                len(re.findall(rf":{name}(?![a-z0-9_])", where.group(1))) != 1
                for name in ("period_start", "period_end_exclusive")
            ):
                return False
        expected_counts = Counter(
            {"period_start": len(scopes), "period_end_exclusive": len(scopes)}
        )
        for index, required in enumerate(required_filters, start=1):
            fqn, column = required.field.lower().rsplit(".", 1)
            parameter = f"required_filter_{index}"
            matched_scopes = 0
            for scope in scopes:
                alias_match = re.search(
                    rf"\b(?:from|join)\s+{re.escape(fqn)}\s+(?:as\s+)?([a-z_][a-z0-9_]*)",
                    scope,
                    re.IGNORECASE,
                )
                if alias_match is None:
                    continue
                where = re.search(
                    r"\bwhere\b(.+?)(?:\bgroup\s+by\b|\border\s+by\b|\blimit\b|$)",
                    scope,
                    re.IGNORECASE | re.DOTALL,
                )
                if (
                    where is None
                    or re.search(r"\bor\b", where.group(1), re.IGNORECASE)
                    or len(
                        re.findall(
                            rf"(?<![a-z0-9_]){re.escape(alias_match.group(1))}\.\"?{re.escape(column)}\"?\s*=\s*:{parameter}(?![a-z0-9_])",
                            where.group(1),
                            re.IGNORECASE,
                        )
                    )
                    != 1
                ):
                    return False
                matched_scopes += 1
            if matched_scopes == 0:
                return False
            expected_counts[parameter] = matched_scopes
        return Counter(placeholders) == expected_counts

    @staticmethod
    def _cte_scopes(sql: str) -> tuple[str, ...]:
        scopes = []
        for match in re.finditer(
            r"(?:\bwith\b|,)\s*[a-z_][a-z0-9_]*\s+as\s*\(",
            sql,
            re.IGNORECASE,
        ):
            depth = 1
            quoted = False
            index = match.end()
            while index < len(sql) and depth:
                if sql[index] == "'":
                    if quoted and index + 1 < len(sql) and sql[index + 1] == "'":
                        index += 2
                        continue
                    quoted = not quoted
                elif not quoted:
                    depth += sql[index] == "("
                    depth -= sql[index] == ")"
                index += 1
            if depth:
                return ()
            scopes.append(sql[match.end() : index - 1])
        return tuple(scopes)

    @staticmethod
    def _parameter_matches(
        actual: object,
        expected_type: str,
        expected_value: object,
    ) -> bool:
        if isinstance(actual, dict):
            if set(actual) != {"value_type", "value"}:
                return False
            actual_type = actual["value_type"]
            actual_value = actual["value"]
        else:
            actual_type = expected_type
            actual_value = actual
        if actual_type != expected_type or type(actual_value) is not type(expected_value):
            return False
        return actual_value == expected_value

    @staticmethod
    def model_plan_violation(plan: object) -> str | None:
        if not isinstance(plan, dict):
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("sql"), str) or not plan["sql"].strip():
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("references"), list):
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("parameters", {}), dict):
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("model_version"), str):
            return "MODEL_SCHEMA_INVALID"
        return None

    @classmethod
    def g3_violation(
        cls,
        query: dict[str, object],
        package: ContextPackage | None = None,
    ) -> str | None:
        if not query.get("evidence_complete"):
            return "EVIDENCE_INCOMPLETE"
        rows = query.get("rows")
        scalar_types = (str, int, float, bool, type(None))
        if (
            not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
            or any(
                not isinstance(value, scalar_types)
                for row in rows
                for value in row.values()
            )
        ):
            return "RESULT_SCHEMA_INVALID"
        filters = query.get("filters", {})
        sampling = query.get("sampling", {})
        masking = query.get("masking", {})
        if (
            not isinstance(filters, dict)
            or any(not isinstance(value, scalar_types) for value in filters.values())
            or not isinstance(sampling, dict)
            or not isinstance(masking, dict)
        ):
            return "EVIDENCE_SCHEMA_INVALID"
        if package is not None:
            expected = {
                item.name: item.value for item in package.parameter_bindings
            }
            expected_period = {
                "start": expected.pop("period_start", None),
                "end_exclusive": expected.pop("period_end_exclusive", None),
            }
            expected_filters = {
                name: value
                for name, value in expected.items()
                if re.fullmatch(r"required_filter_\d+", name)
            }
            if filters != expected_filters or (
                any(expected_period.values())
                and query.get("period") != expected_period
            ):
                return "EVIDENCE_CONTEXT_MISMATCH"
        masking_fields = masking.get("fields", ())
        if (
            not isinstance(masking.get("applied", False), bool)
            or not isinstance(masking_fields, (list, tuple))
            or any(not isinstance(field, str) for field in masking_fields)
            or (masking_fields and not masking.get("applied"))
        ):
            return "MASKING_EVIDENCE_INCOMPLETE"
        returned_rows = sampling.get("returned_rows")
        total_rows = sampling.get("total_rows")
        if sampling and (
            not isinstance(sampling.get("applied", False), bool)
            or returned_rows != len(rows)
            or not isinstance(total_rows, int)
            or total_rows < len(rows)
            or (not sampling.get("applied") and total_rows != len(rows))
        ):
            return "SAMPLING_EVIDENCE_INVALID"
        if query.get("zero_result_suspicious"):
            return "SUSPICIOUS_EMPTY_RESULT"
        column_count = max((len(row) for row in rows), default=0)
        if (
            len(rows) > cls.MAX_RESULT_ROWS
            or column_count > cls.MAX_RESULT_COLUMNS
            or len(rows) * column_count > cls.MAX_RESULT_CELLS
        ):
            return "RESULT_RANGE_EXCEEDED"
        return None

    @staticmethod
    def period(as_of: date) -> PeriodEvidence:
        return PeriodEvidence(
            start=as_of.replace(day=1),
            end_exclusive=as_of,
        )

    @staticmethod
    def gate_token(package: ContextPackage, sql: str) -> str:
        return hashlib.sha256(
            f"{package.package_hash}:{sql}".encode()
        ).hexdigest()

    @staticmethod
    def artifact_id(
        trace_id: str,
        query_id: str,
        context_hash: str,
    ) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"{trace_id}:{query_id}:{context_hash}",
        )

    @staticmethod
    def sources(
        assets: list[dict[str, object]],
    ) -> tuple[SourceReference, ...]:
        return tuple(
            SourceReference(
                urn=str(asset["urn"]),
                fqn=str(asset["fqn"]),
                name=str(asset["name"]),
                schema_version=str(asset["schema_version"]),
                seed_version=str(asset["seed_version"]),
            )
            for asset in assets
        )
