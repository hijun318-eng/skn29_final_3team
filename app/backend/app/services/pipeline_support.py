from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, time
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlglot import ErrorLevel, exp, parse
from sqlglot.errors import ParseError

from app.contracts import (
    AnalysisRequest,
    PeriodEvidence,
    RequestContext,
    SourceReference,
)
from app.ports.data_platform import DataPlatformAdapter, MetadataUnavailableError
from app.services.context_builder import (
    ContextAsset,
    ContextBuildError,
    ContextBuildErrorCode,
    ContextBuildRequest,
    ContextMetric,
    ContextMetricFormula,
    ContextMetricTerm,
    ContextPackage,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)


def _metric_suggestions(
    metric_ids: list[str],
    glossary: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    alias_counts = Counter(alias for aliases in glossary.values() for alias in aliases)
    suggestions = []
    for metric_id in metric_ids:
        label = next(
            (alias for alias in glossary.get(metric_id, ()) if alias_counts[alias] == 1),
            None,
        )
        if label and label not in suggestions:
            suggestions.append(label)
    return tuple(suggestions)


def _period_suggestions(candidates: object) -> tuple[str, ...]:
    return tuple(
        str(candidate["source_text"])
        for candidate in candidates or ()
        if isinstance(candidate, dict)
        and isinstance(candidate.get("source_text"), str)
    ) if isinstance(candidates, (list, tuple)) else ()


def _normalize_question(payload: dict[str, object]) -> dict[str, object]:
    from src.ai.node1 import normalize_question

    return normalize_question(payload)


def _validated_model_periods(
    question: str,
    model_candidates: object,
    expected_candidates: object,
    timezone: ZoneInfo,
) -> list[dict[str, object]]:
    if not isinstance(model_candidates, list) or not isinstance(expected_candidates, list):
        raise ValueError("Node1 period_candidates must be arrays")
    if len(model_candidates) > 4:
        raise ValueError("Node1 returned too many period candidates")
    if not expected_candidates:
        if model_candidates:
            raise ValueError(
                "Node1 period candidate has no deterministic calendar match"
            )
        return []
    strict_calendar_match = bool(expected_candidates)
    validated = []
    parsed = []
    for model_candidate in model_candidates:
        if not isinstance(model_candidate, dict):
            raise ValueError("Node1 period candidate must be an object")
        try:
            model_start = datetime.fromisoformat(str(model_candidate["start"]))
            model_end = datetime.fromisoformat(str(model_candidate["end_exclusive"]))
            source_text = str(model_candidate["source_text"])
        except (KeyError, ValueError) as error:
            raise ValueError("Node1 period candidate is invalid") from error
        if (
            model_start.utcoffset() is None
            or model_end.utcoffset() is None
            or model_start.utcoffset() != model_start.astimezone(timezone).utcoffset()
            or model_end.utcoffset() != model_end.astimezone(timezone).utcoffset()
            or model_start >= model_end
            or not source_text
            or (not strict_calendar_match and source_text not in question)
        ):
            raise ValueError("Node1 period candidate violates the supplied calendar context")
        validated.append(model_candidate)
        parsed.append((model_start, model_end))
    if not strict_calendar_match:
        return validated
    try:
        expected_periods = [
            (
                datetime.fromisoformat(str(candidate["start"])),
                datetime.fromisoformat(str(candidate["end_exclusive"])),
            )
            for candidate in expected_candidates
            if isinstance(candidate, dict)
        ]
    except (KeyError, ValueError) as error:
        raise ValueError("calendar contract period candidate is invalid") from error
    if len(expected_periods) != len(expected_candidates):
        raise ValueError("calendar contract period candidate is invalid")
    if len(parsed) == len(expected_periods):
        if parsed != expected_periods:
            raise ValueError("Node1 period candidate violates the supplied calendar context")
        return validated
    if len(expected_periods) == 1 and len(parsed) > 1:
        ordered = sorted(parsed)
        contiguous = all(left[1] == right[0] for left, right in zip(ordered, ordered[1:]))
        if contiguous and (ordered[0][0], ordered[-1][1]) == expected_periods[0]:
            return [dict(expected_candidates[0])]
    raise ValueError("Node1 period candidate count violates the calendar contract")


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
        model=None,
    ) -> None:
        self._adapter = adapter
        self._context_builder = context_builder
        self._model = model

    def build_context(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
        structured_request: dict[str, object] | None = None,
    ) -> ContextPackage:
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
                        result_field=str(metric.get("result_field") or metric["id"]),
                        unit=str(metric.get("unit") or ""),
                        formula=(
                            ContextMetricFormula(
                                operator=str(metric["formula"]["operator"]),
                                operands=tuple(map(str, metric["formula"]["operands"])),
                            )
                            if isinstance(metric.get("formula"), dict)
                            else None
                        ),
                        reduction=str(metric.get("reduction") or ""),
                    )
                    for metric in asset.get("metrics", ())
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
                column_types=tuple(
                    (str(column["name"]), str(column["type"]))
                    for column in self._adapter.get_asset_schema(
                        str(asset["urn"])
                    )["columns"]
                    if str(column.get("type") or "") != "contract"
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
            for asset in items
            for metric in asset.metrics
            for item in metric.required_filters
        )
        period_values = {
            name: payload.parameters[name]
            for name in ("period_start", "period_end_exclusive")
            if name in payload.parameters
        }
        if (
            not period_values
            and structured_request is not None
            and "period_candidates" in structured_request
        ):
            candidates = structured_request.get("period_candidates")
            if not isinstance(candidates, list) or len(candidates) != 1:
                raise ContextBuildError(
                    ContextBuildErrorCode.PERIOD_REQUIRED,
                    "질문에 분석 기간을 하나만 명확히 포함해 주세요.",
                    _period_suggestions(candidates),
                )
            candidate = candidates[0]
            if not isinstance(candidate, dict):
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METADATA,
                    "Node1 period candidate must be an object.",
                )
            try:
                period_values = {
                    "period_start": datetime.fromisoformat(
                        str(candidate["start"])
                    ).date().isoformat(),
                    "period_end_exclusive": datetime.fromisoformat(
                        str(candidate["end_exclusive"])
                    ).date().isoformat(),
                }
            except (KeyError, ValueError) as error:
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METADATA,
                    "Node1 period candidate is not a valid ISO date-time range.",
                ) from error
        if period_values and set(period_values) != {
            "period_start",
            "period_end_exclusive",
        }:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Analysis period requires start and end_exclusive together.",
            )
        if period_values and period_values["period_start"] >= period_values["period_end_exclusive"]:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Analysis period must be a non-empty half-open range.",
            )
        derived_period_bindings = tuple(
            [
                ContextParameterBinding(name, "date", period_values[name])
                for name in ("period_start", "period_end_exclusive")
                if name in period_values
            ]
        )
        supplied_non_period = tuple(
            item
            for item in supplied_bindings
            if item.name not in {"period_start", "period_end_exclusive"}
        )
        derived_filter_bindings = tuple(
            ContextParameterBinding(
                f"required_filter_{index}", item.value_type, item.value
            )
            for index, item in enumerate(metric_filters, start=1)
        )
        if supplied_bindings:
            supplied_names = {item.name for item in supplied_non_period}
            parameter_bindings = (
                (
                    *derived_period_bindings,
                    *supplied_non_period,
                    *(
                        item
                        for item in derived_filter_bindings
                        if item.name not in supplied_names
                    ),
                )
                if derived_period_bindings
                else supplied_bindings
            )
        else:
            parameter_bindings = (*derived_period_bindings, *derived_filter_bindings)
        context_releases = {
            str(asset.get("context_release") or "context-v1") for asset in assets
        }
        policy_versions = {
            str(asset.get("policy_version") or "policy-v1") for asset in assets
        }
        if len(context_releases) != 1 or len(policy_versions) != 1:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context asset은 동일한 release와 policy version을 사용해야 합니다.",
            )
        metric_term_payloads = tuple(
            item
            for asset in assets
            for item in asset.get("metric_terms", ())
            if isinstance(item, dict)
        )
        if (
            isinstance(structured_request, dict)
            and isinstance(structured_request.get("metric_term"), dict)
        ):
            metric_term_payloads = (structured_request["metric_term"],)
        if not metric_term_payloads:
            metric_ids = tuple(dict.fromkeys(metric.id for asset in items for metric in asset.metrics))
            if not metric_ids and any(
                "pms_crm_pos_gold_revenue_month_v1" in asset.join_ids for asset in items
            ):
                metric_ids = ("total_guest_revenue_krw",)
            if len(metric_ids) == 1:
                metric_term_payloads = (self._adapter.get_metric_terms(metric_ids)[metric_ids[0]],)
        request = ContextBuildRequest(
            context_release=context_releases.pop(),
            policy_version=policy_versions.pop(),
            time_version=context.as_of.isoformat(),
            entitlement_hash=hashlib.sha256(
                f"{context.user_id}:{context.role.value}".encode()
            ).hexdigest(),
            assets=items,
            token_count=max(1, len(payload.question.split()) * 4),
            model_context_tokens=24_000,
            parameter_bindings=parameter_bindings,
            metric_terms=tuple(
                ContextMetricTerm(
                    id=str(item["id"]),
                    urn=str(item["urn"]),
                    label=str(item["label"]),
                    aliases=tuple(map(str, item["aliases"])),
                    definition=str(item["definition"]),
                    unit=str(item["unit"]),
                    version=str(item["version"]),
                )
                for item in metric_term_payloads
            ),
        )
        return self._context_builder.build(
            request,
            frozenset(item.urn for item in items),
        )

    def select_metric(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], str, dict[str, object]]:
        three_source = any(
            "pms_crm_pos_gold_revenue_month_v1" in asset.get("join_ids", ())
            for asset in assets
        )
        if not any("metrics" in asset for asset in assets) and not three_source:
            return assets, payload.question, {}

        candidates = [
            metric
            for asset in assets
            for metric in asset.get("metrics", ())
            if isinstance(metric, dict) and isinstance(metric.get("id"), str)
        ]
        if three_source:
            candidates.append(
                {
                    "id": "total_guest_revenue_krw",
                    "time_field": "derived.month",
                }
            )
        candidate_ids = [str(metric["id"]) for metric in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_METRIC,
                "동일한 metric id를 중복 선택할 수 없습니다.",
            )
        try:
            metric_terms = self._adapter.get_metric_terms(tuple(candidate_ids))
        except MetadataUnavailableError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise MetadataUnavailableError(
                "DataHub Metric Glossary를 조회하지 못했습니다."
            ) from error
        if set(metric_terms) != set(candidate_ids):
            raise MetadataUnavailableError(
                "DataHub Metric Glossary가 승인된 Metric 후보를 모두 포함하지 않습니다."
            )
        glossary = {}
        for metric_id in candidate_ids:
            term = metric_terms[metric_id]
            label = str(term["label"])
            aliases = tuple(map(str, term["aliases"]))
            glossary[metric_id] = (label, *(alias for alias in aliases if alias != label))
        business_terms = {
            metric_id: {"kind": "metric", "aliases": list(glossary[metric_id])}
            for metric_id in candidate_ids
            if metric_id in glossary
        }
        time_fields = {
            str(metric.get("time_field"))
            for metric in candidates
            if isinstance(metric.get("time_field"), str)
        }
        dimension_aliases = {
            "business_date": ["일별", "일자별", "날짜별", "일자", "날짜"],
            "year_month": ["월별", "월 단위", "월"],
            "actual_checkout_at": ["일별", "일자별", "날짜별", "월별", "월 단위"],
        }
        business_terms.update(
            {
                field: {
                    "kind": "dimension",
                    "aliases": dimension_aliases[field],
                }
                for field in time_fields
                if field in dimension_aliases
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
        node1_payload = {
            "question": payload.question,
            "role_hint": context.role.value,
            "as_of": as_of,
            "timezone": context.timezone,
            "calendar_id": "gregorian-kr",
            "allowed_routes": ["general", "template"],
            "business_terms": business_terms,
        }
        normalizer = getattr(self._model, "normalize_question", None)
        sealed = _normalize_question(node1_payload)
        sealed_periods = sealed.get("period_candidates")
        if callable(normalizer):
            for attempt in range(2):
                normalized = normalizer(node1_payload)
                try:
                    model_periods = _validated_model_periods(
                        payload.question,
                        normalized.get("period_candidates"),
                        sealed_periods,
                        timezone,
                    )
                    break
                except ValueError:
                    if attempt == 1:
                        raise
        else:
            normalized = sealed
            model_periods = _validated_model_periods(
                payload.question,
                normalized.get("period_candidates"),
                sealed_periods,
                timezone,
            )
        has_saved_period = all(
            name in payload.parameters
            for name in ("period_start", "period_end_exclusive")
        )
        if not has_saved_period and len(model_periods) != 1:
            raise ContextBuildError(
                ContextBuildErrorCode.PERIOD_REQUIRED,
                "질문에 분석 기간을 하나만 명확히 포함해 주세요.",
                _period_suggestions(model_periods or sealed_periods),
            )
        selected = sealed.get("selected_metric_id")
        if not isinstance(selected, str) or selected not in candidate_ids:
            normalized_candidates = sealed.get("metric_candidates")
            suggestion_ids = [
                metric_id
                for metric_id in (
                    normalized_candidates
                    if isinstance(normalized_candidates, list)
                    else ()
                )
                if isinstance(metric_id, str) and metric_id in candidate_ids
            ] or candidate_ids
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에서 권한이 있는 승인 metric 하나를 확인할 수 없습니다.",
                _metric_suggestions(suggestion_ids, glossary),
            )
        selected_assets = []
        for asset in assets:
            item = dict(asset)
            if "metrics" in item:
                item["metrics"] = tuple(
                    metric
                    for metric in item.get("metrics", ())
                    if isinstance(metric, dict) and metric.get("id") == selected
                )
            selected_assets.append(item)
        if not three_source and not any(
            asset.get("join_ids") for asset in selected_assets
        ):
            selected_assets = [
                asset for asset in selected_assets if asset.get("metrics")
            ]
        structured_request = {
            "intent_candidates": [
                item
                for item in normalized.get("intent_candidates", ())
                if item in {"aggregate", "compare", "trend"}
            ] or list(sealed.get("intent_candidates", ())),
            "dimension_candidates": [
                item
                for item in normalized.get("dimension_candidates", ())
                if item in business_terms and business_terms[item]["kind"] == "dimension"
            ],
            "period_candidates": model_periods,
            "selected_metric_id": selected,
            "metric_term": metric_terms[selected],
        }
        return (
            selected_assets,
            str(sealed["normalized_question"]),
            structured_request,
        )

    @staticmethod
    def g2_violation(
        plan: dict[str, object],
        package: ContextPackage,
    ) -> str | None:
        if not isinstance(plan, dict):
            return "MODEL_SCHEMA_INVALID"
        sql = str(plan.get("sql", "")).strip()
        normalized = sql.lower()
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
            not PipelineSupport._read_only_query_shape(sql)
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
        ast_violation = PipelineSupport._ast_policy_violation(sql, package)
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
        three_source = "pms_crm_pos_gold_revenue_month_v1" in package.approved_join_ids
        if three_source:
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
        cte_names = {
            name.lower()
            for name in re.findall(
                r"(?:\bwith\b|,)\s*([a-z_][a-z0-9_]*)\s+as\s*\(",
                sql,
                flags=re.IGNORECASE,
            )
        }
        table_matches = re.findall(
            r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)"
            r"(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?",
            sql,
            flags=re.IGNORECASE,
        )
        queried = {
            table.strip('"').lower()
            for table, _alias in table_matches
            if table.strip('"').lower() not in cte_names
        }
        if queried != {item.lower() for item in referenced}:
            return "SQL_REFERENCE_MISMATCH"
        if len({table.split(".", 1)[0] for table in queried}) > 1:
            referenced_join_ids = {
                str(join_id)
                for item in references
                for join_id in item.get("join_ids", ())
            }
            if (
                not package.approved_join_ids
                or referenced_join_ids != set(package.approved_join_ids)
                or queried != {item.fqn.lower() for item in package.assets}
            ):
                return "UNAPPROVED_JOIN"
        column_scopes = PipelineSupport._cte_scopes(sql) if three_source else (sql,)
        for scope in column_scopes:
            scope_tables = re.findall(
                r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)"
                r"(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?",
                scope,
                flags=re.IGNORECASE,
            )
            columns_by_alias = {
                (alias or table.rsplit(".", 1)[-1]).lower(): columns_by_fqn[fqn]
                for table, alias in scope_tables
                if (fqn := table.strip('"').lower()) in columns_by_fqn
            }
            if any(
                column not in columns_by_alias[alias]
                for alias, column in re.findall(
                    r"(?<![a-z0-9_])([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)",
                    scope.lower(),
                )
                if alias in columns_by_alias
            ):
                return "REFERENCE_OUTSIDE_CONTEXT"
        required_filters = (
            *package.required_filters,
            *(item for metric in package.metrics for item in metric.required_filters),
        )
        if three_source:
            scopes = PipelineSupport._cte_scopes(sql)
            if (
                not PipelineSupport._three_source_composition_matches(sql)
                or not PipelineSupport._three_source_join_semantics_match(scopes)
            ):
                return "UNAPPROVED_JOIN"
            if not PipelineSupport._three_source_projection_matches(sql):
                return "METRIC_REFERENCE_MISMATCH"
            if not PipelineSupport._three_source_time_semantics_match(scopes, package):
                return "TIME_SEMANTICS_INVALID"
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
        return ast_violation

    @staticmethod
    def g2_repair_hint(violation: str, package: ContextPackage) -> str:
        """Return context-derived repair constraints without rewriting model SQL."""
        if violation == "TIME_SEMANTICS_INVALID":
            bindings = {item.name: item.value for item in package.parameter_bindings}
            start = bindings.get("period_start", "<period_start>")
            end = bindings.get("period_end_exclusive", "<period_end_exclusive>")
            native_types = {
                f"{asset.fqn}.{column}": native_type
                for asset in package.assets
                for column, native_type in asset.column_types
            }
            return (
                "Apply both source-specific rules exactly. "
                "PMS pms.public.pms_stays.actual_checkout_at has native type "
                f"{native_types.get('pms.public.pms_stays.actual_checkout_at', 'unknown')}: "
                "its month join key must be date_format(date_trunc('month', "
                "<pms_alias>.actual_checkout_at AT TIME ZONE 'Asia/Seoul'), '%Y-%m') "
                "AS month and its half-open period must use "
                f"TIMESTAMP '{start} 00:00:00 Asia/Seoul' and "
                f"TIMESTAMP '{end} 00:00:00 Asia/Seoul'. "
                "POS pos.pos_db.pos_orders.ordered_at has native type "
                f"{native_types.get('pos.pos_db.pos_orders.ordered_at', 'unknown')}: "
                "its month join key must be date_format(date_trunc('month', "
                "<pos_alias>.ordered_at), '%Y-%m') AS month with no AT TIME ZONE, "
                "and its half-open period must use "
                f"TIMESTAMP '{start} 00:00:00' and TIMESTAMP '{end} 00:00:00' "
                "with no timezone name or offset."
            )
        if violation == "UNAPPROVED_JOIN":
            return (
                "Preserve the two pre-aggregated PMS and POS CTEs and join them on both "
                "property_id and month. Use only the approved identity chain: "
                "PMS stay(property_id,reservation_id) -> reservation(property_id,reservation_id) "
                "-> guest(property_id,guest_id) -> customer_map(property_id,pms_guest_id); "
                "POS order(property_id,pos_customer_ref) -> "
                "customer_map(property_id,pos_customer_ref); then customer_map(property_id,member_no) "
                "-> grade_history(property_id,member_no). Apply valid_from <= event AND "
                "(valid_to IS NULL OR event < valid_to) to both customer_map and grade_history."
            )
        if violation == "METRIC_REFERENCE_MISMATCH":
            return (
                "The final projection must expose the approved metric contract exactly: "
                "COALESCE(<pms_cte>.property_id, <pos_cte>.property_id) AS property_id, "
                "COALESCE(<pms_cte>.month, <pos_cte>.month) AS month, and the sum of "
                "the two CTE revenue aggregates AS total_guest_revenue_krw. Do not rename "
                "the metric to total_revenue or another alias."
            )
        if violation == "METRIC_FILTER_MISSING":
            required_filters = (
                *package.required_filters,
                *(item for metric in package.metrics for item in metric.required_filters),
            )
            checklist = "; ".join(
                f"{item.field} = :required_filter_{index}"
                for index, item in enumerate(required_filters, start=1)
            )
            base = (
                "Treat this as an exhaustive filter-set violation, not a single missing "
                "predicate. In the WHERE clause containing the named asset, "
                "apply each placeholder exactly once: "
                f"{checklist}. Preserve the approved assets, period, aggregation, "
                "dimensions, and LIMIT."
            )
            if "pms_crm_pos_gold_revenue_month_v1" not in package.approved_join_ids:
                return base
            return (
                f"{base} For every CTE containing each named asset, apply its filter. "
                "Also require PMS room_revenue > 0; POS order_status IN "
                "('PAID','PARTIAL_REFUND'); POS payment_status IN "
                "('PAID','PARTIAL_REFUND'); and both customer-map and GOLD-grade "
                "event-time validity predicates. Recheck the entire list before returning."
            )
        return "Repair only the normalized violation while preserving approved assets and bindings."

    @staticmethod
    def _read_only_query_shape(sql: str) -> bool:
        words: list[str] = []
        depth = 0
        quoted = False
        index = 0
        while index < len(sql):
            character = sql[index]
            if character == "'":
                if quoted and index + 1 < len(sql) and sql[index + 1] == "'":
                    index += 2
                    continue
                quoted = not quoted
            elif not quoted:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth < 0:
                        return False
                elif depth == 0 and (character.isalpha() or character == "_"):
                    end = index + 1
                    while end < len(sql) and (sql[end].isalnum() or sql[end] == "_"):
                        end += 1
                    words.append(sql[index:end].lower())
                    index = end
                    continue
            index += 1
        if quoted or depth or not words or words[0] not in {"select", "with"}:
            return False
        statements = [
            word
            for word in words
            if word in {"select", "insert", "update", "delete", "merge"}
        ]
        return statements == ["select"] and not {"union", "intersect", "except"}.intersection(words)

    @staticmethod
    def _ast_policy_violation(sql: str, package: ContextPackage) -> str | None:
        """Fail closed on SQL structure, functions, stars, and non-context columns."""
        try:
            statements = parse(sql, read="trino", error_level=ErrorLevel.RAISE)
        except ParseError:
            return "UNSAFE_SQL"
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            return "UNSAFE_SQL"
        tree = statements[0]
        if next(tree.find_all(exp.Star), None) is not None:
            return "REFERENCE_OUTSIDE_CONTEXT"
        if (
            not tree.named_selects
            or len(tree.named_selects) != len(set(tree.named_selects))
        ):
            return "UNSAFE_SQL"

        allowed_functions = {
            "ABS",
            "AND",
            "AVG",
            "CAST",
            "COALESCE",
            "COUNT",
            "DATE_ADD",
            "FROM_ISO8601_TIMESTAMP",
            "IF",
            "MAX",
            "MIN",
            "NULLIF",
            "OR",
            "ROUND",
            "ROW_NUMBER",
            "SUM",
            "TIMESTAMP_TRUNC",
            "TIME_TO_STR",
        }
        if any(
            function.sql_name() not in allowed_functions
            for function in tree.find_all(exp.Func)
        ):
            return "UNSAFE_SQL"

        asset_columns = {
            asset.fqn.lower(): {column.lower() for column in asset.columns}
            for asset in package.assets
        }
        cte_outputs = {
            cte.alias_or_name.lower(): {
                expression.alias_or_name.lower()
                for expression in cte.this.expressions
                if expression.alias_or_name
            }
            for cte in tree.find_all(exp.CTE)
        }
        approved_results = {metric.result_field.lower() for metric in package.metrics}

        for select in tree.find_all(exp.Select):
            direct_tables = [
                table
                for table in select.find_all(exp.Table)
                if table.find_ancestor(exp.Select) is select
            ]
            relations: dict[str, set[str]] = {}
            for table in direct_tables:
                relation_name = ".".join(
                    part
                    for part in (table.catalog, table.db, table.name)
                    if part
                ).lower()
                alias = table.alias_or_name.lower()
                if relation_name in cte_outputs:
                    relations[alias] = cte_outputs[relation_name]
                elif relation_name in asset_columns:
                    relations[alias] = asset_columns[relation_name]
                else:
                    return "REFERENCE_OUTSIDE_CONTEXT"

            projection_aliases = {
                expression.alias.lower()
                for expression in select.expressions
                if expression.alias
            }
            for column in select.find_all(exp.Column):
                if column.find_ancestor(exp.Select) is not select:
                    continue
                name = column.name.lower()
                qualifier = column.table.lower()
                if qualifier:
                    if qualifier not in relations or name not in relations[qualifier]:
                        return "REFERENCE_OUTSIDE_CONTEXT"
                    continue
                if name in projection_aliases or name in approved_results:
                    continue
                matching_relations = sum(
                    name in columns for columns in relations.values()
                )
                if matching_relations != 1:
                    return "REFERENCE_OUTSIDE_CONTEXT"
        return None

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
        if where is None or PipelineSupport._has_top_level_or(where.group(1)):
            return False
        field = re.escape(required.field.lower().rsplit(".", 1)[-1])
        matches = re.findall(
            rf"(?<![a-z0-9_])(?:[a-z_][a-z0-9_]*\.)?{field}\s*=\s*"
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
                    or PipelineSupport._has_top_level_or(where.group(1))
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
        return (
            Counter(placeholders) == expected_counts
            and PipelineSupport._three_source_source_predicates_match(scopes)
        )

    @staticmethod
    def _has_top_level_or(expression: str) -> bool:
        """Reject predicate-bypass OR while allowing parenthesized validity windows."""
        depth = 0
        quote: str | None = None
        token: list[str] = []
        index = 0

        def flush() -> bool:
            is_or = "".join(token).lower() == "or"
            token.clear()
            return is_or

        while index < len(expression):
            character = expression[index]
            if quote:
                if character == quote:
                    if index + 1 < len(expression) and expression[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
                index += 1
                continue
            if character in {"'", '"'}:
                if depth == 0 and flush():
                    return True
                quote = character
            elif character == "(":
                if depth == 0 and flush():
                    return True
                depth += 1
            elif character == ")":
                if depth == 0 and flush():
                    return True
                depth = max(0, depth - 1)
            elif depth == 0 and (character.isalnum() or character == "_"):
                token.append(character)
            elif depth == 0 and flush():
                return True
            index += 1
        return flush()

    @staticmethod
    def _three_source_composition_matches(sql: str) -> bool:
        scopes = PipelineSupport._cte_scopes(sql)
        if len(scopes) != 2:
            return False
        for fqn in ("pms.public.pms_stays", "pos.pos_db.pos_orders"):
            matching_scopes = [
                scope
                for scope in scopes
                if re.search(
                    rf"\bfrom\s+{re.escape(fqn)}\s+(?:as\s+)?[a-z_][a-z0-9_]*",
                    scope,
                    re.IGNORECASE,
                )
            ]
            if len(matching_scopes) != 1:
                return False
            scope = matching_scopes[0]
            alias = re.search(
                rf"\bfrom\s+{re.escape(fqn)}\s+(?:as\s+)?([a-z_][a-z0-9_]*)",
                scope,
                re.IGNORECASE,
            )
            select = re.search(
                r"\bselect\b(.+?)\bfrom\b", scope, re.IGNORECASE | re.DOTALL
            )
            if alias is None or select is None or re.search(
                rf"(?<![a-z0-9_]){re.escape(alias.group(1))}\.\"?property_id\"?(?![a-z0-9_])",
                select.group(1),
                re.IGNORECASE,
            ) is None:
                return False
        outer = re.search(
            r"\bfrom\s+([a-z_][a-z0-9_]*)"
            r"(?:\s+(?:as\s+)?((?!(?:full|inner|left|right|cross|join|where|order|limit)\b)"
            r"[a-z_][a-z0-9_]*))?\s+"
            r"full\s+outer\s+join\s+([a-z_][a-z0-9_]*)"
            r"(?:\s+(?:as\s+)?((?!(?:on|where|order|limit)\b)[a-z_][a-z0-9_]*))?\s+"
            r"on\s+(.+?)(?:\border\s+by\b|\blimit\b|$)",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        if outer is None:
            return False
        left_table, left_alias, right_table, right_alias, condition = outer.groups()
        left = left_alias or left_table
        right = right_alias or right_table
        return all(
            re.search(
                rf"(?:{re.escape(left)}\.\"?{field}\"?\s*=\s*{re.escape(right)}\.\"?{field}\"?"
                rf"|{re.escape(right)}\.\"?{field}\"?\s*=\s*{re.escape(left)}\.\"?{field}\"?)",
                condition,
                re.IGNORECASE,
            )
            for field in ("property_id", "month")
        )

    @staticmethod
    def _three_source_join_semantics_match(scopes: tuple[str, ...]) -> bool:
        def alias(scope: str, fqn: str) -> str | None:
            match = re.search(
                rf"\b(?:from|join)\s+{re.escape(fqn)}\s+(?:as\s+)?([a-z_][a-z0-9_]*)",
                scope,
                re.IGNORECASE,
            )
            return match.group(1) if match else None

        def column(table_alias: str, name: str) -> str:
            return rf"{re.escape(table_alias)}\.\"?{name}\"?"

        def equality(scope: str, left: str, right: str) -> bool:
            return re.search(
                rf"(?:{left}\s*=\s*{right}|{right}\s*=\s*{left})",
                scope,
                re.IGNORECASE,
            ) is not None

        def temporal(scope: str, history: str, event: str) -> bool:
            starts_before = re.search(
                rf"(?:{column(history, 'valid_from')}\s*<=\s*{event}"
                rf"|{event}\s*>=\s*{column(history, 'valid_from')})",
                scope,
                re.IGNORECASE,
            )
            ends_after = re.search(
                rf"\(\s*{column(history, 'valid_to')}\s+is\s+null\s+or\s+"
                rf"(?:{event}\s*<\s*{column(history, 'valid_to')}"
                rf"|{column(history, 'valid_to')}\s*>\s*{event})\s*\)",
                scope,
                re.IGNORECASE,
            )
            return starts_before is not None and ends_after is not None

        source_specs = {
            "pms.public.pms_stays": (
                "actual_checkout_at",
                (
                    ("source", "property_id", "reservation", "property_id"),
                    ("source", "reservation_id", "reservation", "reservation_id"),
                    ("reservation", "property_id", "guest", "property_id"),
                    ("reservation", "guest_id", "guest", "guest_id"),
                    ("guest", "property_id", "map", "property_id"),
                    ("guest", "guest_id", "map", "pms_guest_id"),
                ),
            ),
            "pos.pos_db.pos_orders": (
                "ordered_at",
                (
                    ("source", "property_id", "map", "property_id"),
                    ("source", "pos_customer_ref", "map", "pos_customer_ref"),
                ),
            ),
        }
        for source_fqn, (event_name, identities) in source_specs.items():
            matching = [scope for scope in scopes if alias(scope, source_fqn)]
            if len(matching) != 1:
                return False
            scope = matching[0]
            aliases = {
                "source": alias(scope, source_fqn),
                "reservation": alias(scope, "pms.public.pms_reservations"),
                "guest": alias(scope, "pms.public.pms_guests"),
                "map": alias(scope, "crm.dbo.crm_customer_map"),
                "grade": alias(scope, "crm.dbo.crm_member_grade_history"),
            }
            required = {"source", "map", "grade"}
            if source_fqn.startswith("pms."):
                required.update(("reservation", "guest"))
            if any(not aliases[name] for name in required):
                return False
            event = column(str(aliases["source"]), event_name)
            if any(
                not equality(
                    scope,
                    column(str(aliases[left]), left_column),
                    column(str(aliases[right]), right_column),
                )
                for left, left_column, right, right_column in identities
            ):
                return False
            if not all(
                equality(
                    scope,
                    column(str(aliases["map"]), name),
                    column(str(aliases["grade"]), name),
                )
                for name in ("property_id", "member_no")
            ):
                return False
            if not all(
                temporal(scope, str(aliases[history]), event)
                for history in ("map", "grade")
            ):
                return False
        return True

    @staticmethod
    def _three_source_projection_matches(sql: str) -> bool:
        outer = re.search(
            r"\)\s*select\s+(.+?)\s+from\s+([a-z_][a-z0-9_]*)"
            r"(?:\s+(?:as\s+)?((?!(?:full|inner|left|right|cross|join|where|order|limit)\b)"
            r"[a-z_][a-z0-9_]*))?\s+"
            r"full\s+outer\s+join\s+([a-z_][a-z0-9_]*)"
            r"(?:\s+(?:as\s+)?((?!(?:on|where|order|limit)\b)[a-z_][a-z0-9_]*))?\s+on\b",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        if outer is None:
            return False
        projection, left_table, left_alias, right_table, right_alias = outer.groups()
        left = left_alias or left_table
        right = right_alias or right_table

        def coalesced_key(field: str, output: str) -> bool:
            return re.search(
                rf"(?:coalesce\s*\(\s*{re.escape(left)}\.{field}\s*,\s*"
                rf"{re.escape(right)}\.{field}\s*\)|coalesce\s*\(\s*"
                rf"{re.escape(right)}\.{field}\s*,\s*{re.escape(left)}\.{field}\s*\))"
                rf"\s+as\s+{output}(?![a-z0-9_])",
                projection,
                re.IGNORECASE,
            ) is not None

        total = re.search(
            r"(coalesce\s*\(.+?\)\s*\+\s*coalesce\s*\(.+?\))\s+"
            r"as\s+total_guest_revenue_krw(?![a-z0-9_])",
            projection,
            re.IGNORECASE | re.DOTALL,
        )
        if total is None:
            return False
        total_expression = total.group(1)
        has_both_sources = all(
            re.search(
                rf"(?<![a-z0-9_]){re.escape(alias)}\.[a-z_][a-z0-9_]*",
                total_expression,
                re.IGNORECASE,
            )
            for alias in (left, right)
        )
        return (
            coalesced_key("property_id", "property_id")
            and coalesced_key("month", "month")
            and has_both_sources
        )

    @staticmethod
    def _three_source_time_semantics_match(
        scopes: tuple[str, ...], package: ContextPackage
    ) -> bool:
        assets = {asset.fqn: asset for asset in package.assets}
        specifications = (
            (
                "pms.public.pms_stays",
                "actual_checkout_at",
                "timestamp with time zone",
            ),
            ("pos.pos_db.pos_orders", "ordered_at", "timestamp without time zone"),
        )
        for fqn, event_column, expected_kind in specifications:
            asset = assets.get(fqn)
            native_type = (
                dict(asset.column_types).get(event_column, "").lower()
                if asset
                else ""
            )
            is_with_zone = "with time zone" in native_type
            is_without_zone = any(
                marker in native_type for marker in ("datetime", "timestamp")
            ) and not is_with_zone
            if (expected_kind == "timestamp with time zone" and not is_with_zone) or (
                expected_kind == "timestamp without time zone" and not is_without_zone
            ):
                return False
            matching = [
                scope
                for scope in scopes
                if re.search(rf"\bfrom\s+{re.escape(fqn)}\b", scope, re.IGNORECASE)
            ]
            if len(matching) != 1:
                return False
            scope = matching[0]
            alias_match = re.search(
                rf"\bfrom\s+{re.escape(fqn)}\s+(?:as\s+)?([a-z_][a-z0-9_]*)",
                scope,
                re.IGNORECASE,
            )
            if alias_match is None:
                return False
            event = rf"{re.escape(alias_match.group(1))}\.\"?{event_column}\"?"
            if is_with_zone:
                month_value = rf"date_trunc\s*\(\s*'month'\s*,\s*{event}\s+at\s+time\s+zone\s+'Asia/Seoul'\s*\)"
                literals = {
                    name: rf"timestamp\s*':{name}\s+00:00:00\s+Asia/Seoul'"
                    for name in ("period_start", "period_end_exclusive")
                }
            else:
                month_value = rf"date_trunc\s*\(\s*'month'\s*,\s*{event}\s*\)"
                literals = {
                    name: (
                        rf"(?:date\s*':{name}'|"
                        rf"timestamp\s*':{name}\s+00:00:00')"
                    )
                    for name in ("period_start", "period_end_exclusive")
                }
            month_key = (
                rf"date_format\s*\(\s*{month_value}\s*,\s*'%Y-%m'\s*\)"
            )
            select = re.search(
                r"\bselect\b(.+?)\bfrom\b", scope, re.IGNORECASE | re.DOTALL
            )
            if select is None or re.search(
                rf"{month_key}\s+(?:as\s+)?\"?month\"?(?![a-z0-9_])",
                select.group(1),
                re.IGNORECASE,
            ) is None:
                return False
            for name, operator in (
                ("period_start", r">="),
                ("period_end_exclusive", r"<"),
            ):
                if re.search(
                    rf"{event}\s*{operator}\s*{literals[name]}",
                    scope,
                    re.IGNORECASE,
                ) is None:
                    return False
        return True

    @staticmethod
    def _three_source_source_predicates_match(scopes: tuple[str, ...]) -> bool:
        aliases: dict[str, tuple[str, str]] = {}
        for fqn in ("pms.public.pms_stays", "pos.pos_db.pos_orders"):
            for scope in scopes:
                match = re.search(
                    rf"\b(?:from|join)\s+{re.escape(fqn)}\s+(?:as\s+)?([a-z_][a-z0-9_]*)",
                    scope,
                    re.IGNORECASE,
                )
                where = re.search(
                    r"\bwhere\b(.+?)(?:\bgroup\s+by\b|\border\s+by\b|\blimit\b|$)",
                    scope,
                    re.IGNORECASE | re.DOTALL,
                )
                if match and where:
                    aliases[fqn] = (match.group(1), where.group(1))
                    break
        if set(aliases) != {"pms.public.pms_stays", "pos.pos_db.pos_orders"}:
            return False
        pms_alias, pms_where = aliases["pms.public.pms_stays"]
        if re.search(
            rf"(?<![a-z0-9_]){re.escape(pms_alias)}\.\"?room_revenue\"?\s*>\s*0(?:\.0+)?(?![a-z0-9_])",
            pms_where,
            re.IGNORECASE,
        ) is None:
            return False
        pos_alias, pos_where = aliases["pos.pos_db.pos_orders"]
        for column in ("order_status", "payment_status"):
            match = re.search(
                rf"(?<![a-z0-9_]){re.escape(pos_alias)}\.\"?{column}\"?\s+in\s*\(([^)]+)\)",
                pos_where,
                re.IGNORECASE,
            )
            if match is None or {
                value.strip().strip("'").upper() for value in match.group(1).split(",")
            } != {"PAID", "PARTIAL_REFUND"}:
                return False
        return True

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

    @staticmethod
    def _result_value_type(value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        return "unsupported"

    @classmethod
    def _result_metadata(
        cls,
        rows: list[dict[str, object]],
        columns: tuple[str, ...],
    ) -> dict[str, object]:
        typed_columns = []
        for name in columns:
            kinds = {
                cls._result_value_type(row.get(name))
                for row in rows
                if row.get(name) is not None
            }
            if kinds <= {"integer", "number"} and "number" in kinds:
                kinds = {"number"}
            value_type = next(iter(kinds)) if len(kinds) == 1 else (
                "null" if not kinds else "mixed"
            )
            typed_columns.append({"name": name, "type": value_type})
        canonical_rows = json.dumps(
            rows,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "columns": typed_columns,
            "row_count": len(rows),
            "checksum": hashlib.sha256(canonical_rows.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _projection_aliases(plan: dict[str, object]) -> tuple[str, ...] | None:
        sql = plan.get("sql")
        if not isinstance(sql, str):
            return None
        try:
            statements = parse(sql, read="trino", error_level=ErrorLevel.RAISE)
        except ParseError:
            return None
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            return None
        aliases = tuple(statements[0].named_selects)
        if not aliases or len(aliases) != len(set(aliases)):
            return None
        return aliases

    @staticmethod
    def _sensitive_result_field(name: str) -> bool:
        return bool(
            re.search(
                r"(?:^|_)(?:email|e_mail|phone|mobile|tel|member_(?:id|no)|"
                r"guest_id|customer_id|user_id|resident_(?:id|no))(?:_|$)",
                name,
                re.IGNORECASE,
            )
        )

    @classmethod
    def g3_violation(
        cls,
        query: dict[str, object],
        plan: dict[str, object],
        package: ContextPackage,
    ) -> str | None:
        if not query.get("evidence_complete"):
            return "EVIDENCE_INCOMPLETE"
        if not isinstance(query.get("query_id"), str) or not query["query_id"]:
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
        expected_columns = cls._projection_aliases(plan)
        if expected_columns is None or not isinstance(package, ContextPackage):
            return "RESULT_CONTRACT_INVALID"
        if any(tuple(row) != expected_columns for row in rows):
            return "RESULT_SCHEMA_INVALID"
        if any(cls._sensitive_result_field(name) for name in expected_columns):
            return "SENSITIVE_RESULT_BLOCKED"
        actual_metadata = cls._result_metadata(rows, expected_columns)
        if query.get("result_metadata") != actual_metadata:
            return "EVIDENCE_MISMATCH"
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
        returned_rows = sampling.get("returned_rows")
        total_rows = sampling.get("total_rows")
        sampling_applied = sampling.get("applied")
        if (
            not isinstance(sampling_applied, bool)
            or not isinstance(returned_rows, int)
            or isinstance(returned_rows, bool)
            or not isinstance(total_rows, int)
            or isinstance(total_rows, bool)
            or returned_rows != len(rows)
            or total_rows < returned_rows
            or (not sampling_applied and total_rows != returned_rows)
        ):
            return "EVIDENCE_MISMATCH"
        masking_applied = masking.get("applied")
        masking_fields = masking.get("fields")
        if (
            not isinstance(masking_applied, bool)
            or not isinstance(masking_fields, (list, tuple))
            or any(not isinstance(field, str) for field in masking_fields)
            or len(masking_fields) != len(set(masking_fields))
            or not set(masking_fields).issubset(expected_columns)
            or masking_applied != bool(masking_fields)
        ):
            return "MASKING_EVIDENCE_INVALID"
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

    @classmethod
    def normalize_empty_aggregate(
        cls, query: dict[str, object], package: ContextPackage
    ) -> dict[str, object]:
        """Turn SQL's one-row NULL aggregate into an honest empty Safe Result."""
        rows = query.get("rows")
        metric_ids = {metric.id for metric in package.metrics}
        if not isinstance(rows, list) or len(rows) != 1 or not metric_ids:
            return query
        row = rows[0]
        selected = metric_ids.intersection(row) if isinstance(row, dict) else set()
        if not selected or any(row[metric_id] is not None for metric_id in selected):
            return query
        normalized = dict(query)
        normalized["rows"] = []
        metadata = query.get("result_metadata")
        columns = tuple(
            str(item["name"])
            for item in metadata.get("columns", ())
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ) if isinstance(metadata, dict) else tuple(row)
        normalized["result_metadata"] = cls._result_metadata([], columns)
        sampling = dict(query.get("sampling") or {})
        sampling.update(returned_rows=0, total_rows=0)
        normalized["sampling"] = sampling
        return normalized

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
        request_id: str,
        query_id: str,
        context_hash: str,
    ) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"{request_id}:{query_id}:{context_hash}",
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
                synthetic=(
                    asset["synthetic"]
                    if isinstance(asset.get("synthetic"), bool)
                    else None
                ),
            )
            for asset in assets
        )
