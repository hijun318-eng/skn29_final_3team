from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import date, datetime, time
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.ai.metric_glossary import metric_glossary

from app.contracts import (
    AnalysisRequest,
    PeriodEvidence,
    RequestContext,
    SourceReference,
)
from app.ports.data_platform import DataPlatformAdapter
from app.services.context_builder import (
    ContextAsset,
    ContextBuildError,
    ContextBuildErrorCode,
    ContextBuildRequest,
    ContextMetric,
    ContextPackage,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)


def _metric_glossary() -> dict[str, tuple[str, ...]]:
    try:
        return metric_glossary()
    except (OSError, ValueError) as error:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "R3 metric glossary 계약을 확인할 수 없습니다.",
        ) from error


def _normalize_question(payload: dict[str, object]) -> dict[str, object]:
    from src.ai.node1 import normalize_question

    return normalize_question(payload)


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
        if not period_values and structured_request:
            candidates = structured_request.get("period_candidates")
            if isinstance(candidates, list) and len(candidates) == 1:
                candidate = candidates[0]
                if isinstance(candidate, dict):
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
        parameter_bindings = supplied_bindings or tuple(
            [
                ContextParameterBinding(name, "date", period_values[name])
                for name in ("period_start", "period_end_exclusive")
                if name in period_values
            ]
            + [
                ContextParameterBinding(
                    f"required_filter_{index}", item.value_type, item.value
                )
                for index, item in enumerate(metric_filters, start=1)
            ]
        )
        request = ContextBuildRequest(
            context_release="context-v1",
            policy_version="policy-v1",
            time_version=context.as_of.isoformat(),
            entitlement_hash=hashlib.sha256(
                f"{context.user_id}:{context.role.value}".encode()
            ).hexdigest(),
            assets=items,
            token_count=max(1, len(payload.question.split()) * 4),
            model_context_tokens=24_000,
            parameter_bindings=parameter_bindings,
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
        glossary = _metric_glossary()
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
        normalized = (
            normalizer(node1_payload)
            if callable(normalizer)
            else _normalize_question(node1_payload)
        )
        selected = normalized.get("selected_metric_id")
        if not isinstance(selected, str) or selected not in candidate_ids:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에서 권한이 있는 승인 metric 하나를 확인할 수 없습니다.",
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
        structured_request = {
            "intent_candidates": list(normalized.get("intent_candidates", ())),
            "dimension_candidates": list(normalized.get("dimension_candidates", ())),
            "period_candidates": list(normalized.get("period_candidates", ())),
        }
        return (
            selected_assets,
            str(normalized["normalized_question"]),
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
        return None

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
            return (
                "Treat this as an exhaustive filter-set violation, not a single missing "
                "predicate. In the WHERE clause of every CTE containing the named asset, "
                "apply each placeholder exactly once: "
                f"{checklist}. Also require PMS room_revenue > 0; POS order_status IN "
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

    @classmethod
    def g3_violation(cls, query: dict[str, object]) -> str | None:
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
