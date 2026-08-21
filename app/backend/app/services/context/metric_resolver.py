"""DataHub 메타데이터 및 용어사전 기반 지표(Metric) 및 기간/차원 해석기 모듈.

[핵심 목적]
사용자의 자연어 질문과 대화 상태를 바탕으로:
1. 멀티턴 Fast-Path: 이전 턴에서 상속된 지표/기간/차원이 있는 경우 거버넌스 검증 후 LLM Node 1 호출을 건너뜀
2. 단일 턴 정규화: LLM Node 1을 호출하여 DataHub 비즈니스 용어사전(Glossary Terms), 차원 목록, 캘린더 메타데이터와 대조
3. 모호성 감지 (Disambiguation): 여러 지표나 기간으로 해석될 수 있는 경우 `ContextBuildError(CLARIFICATION_REQUIRED)`를 반환하여
   사용자에게 명확한 선택지를 제공합니다.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time
import os
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.contracts import AnalysisRequest, ClarificationType, DisambiguationOption, RequestContext
from app.ports.data_platform import DataPlatformAdapter, MetadataUnavailableError
from app.services.context.builder import ContextBuildError, ContextBuildErrorCode
from app.services.context.metric_execution_scope import (
    ratio_reference as _ratio_reference,
    select_assets_for_metrics as _select_assets_for_metrics,
    synthetic_ratio_metric as _synthetic_ratio_metric,
)
from app.services.context.filter_candidate_resolver import (
    dimension_terms as _resolve_dimension_terms,
    resolve_filter_candidates,
    validated_pre_filters,
)
from app.services.context.filter_value_resolver import discover_dimension_values
from app.services.context.period_clarification import (
    disambiguation_options_for_metrics as _disambiguation_options_for_metrics,
    disambiguation_options_for_periods as _disambiguation_options_for_periods,
    period_suggestions as _period_suggestions,
)
from app.services.context.model_signals import (
    CONVERSATION_ROUTES,
    PRESENTATION_TYPES,
    enum_signal,
)
from app.services.context.model_time_context import (
    previous_period_anchor,
    previous_result_shape,
)
from app.services.context.runtime_contracts import (
    time_parameter_names,
    time_selection_mode,
)


_ANALYSIS_OPERATIONS = frozenset(
    {
        "aggregate",
        "breakdown",
        "time_trend",
        "top_n",
        "bottom_n",
        "period_comparison",
    }
)


def _reconcile_comparison_axis(
    *,
    analysis_operation: str | None,
    relationship: str,
    intents: list[str],
    periods: list[dict[str, Any]],
    selected_metric_ids: list[str],
    measurement_source_texts: list[str],
    selected_dimensions: list[str],
    result_limit: object,
    ambiguity: object,
) -> tuple[str | None, str, list[str]]:
    """두 지표 비교를 불완전한 두 기간 비교로 오인한 Node 1 출력을 보정한다.

    질문 문자열을 다시 파싱하지 않고 이미 검증된 구조만 사용한다. 서로 다른 측정값이
    둘 이상 확정됐고 두 번째 기간 증거가 없으며 모호성도 선언되지 않은 경우에는
    ``period_comparison``이 성립할 수 없다. 이때 하나의 공유 기간에서 지표들을 나란히
    조회하는 aggregate/breakdown으로만 좁혀 복구한다. 두 기간이 실제로 있거나 시간
    모호성이 남아 있으면 그대로 두어 기존 PERIOD_REQUIRED 경계가 닫도록 한다.
    """

    is_ambiguous = (
        isinstance(ambiguity, dict) and ambiguity.get("is_ambiguous") is True
    )
    if not (
        analysis_operation == "period_comparison"
        and relationship == "comparison"
        and len(periods) < 2
        and len(selected_metric_ids) > 1
        and len(measurement_source_texts) == len(selected_metric_ids)
        and result_limit is None
        and not is_ambiguous
    ):
        return analysis_operation, relationship, intents
    reconciled = "breakdown" if selected_dimensions else "aggregate"
    return reconciled, "single", [reconciled]


def _suggestions(
    metric_ids: list[str],
    glossary: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """지표 ID 목록에서 고유한 사용자 추천 레이블 튜플을 생성합니다."""
    counts = Counter(alias for aliases in glossary.values() for alias in aliases)
    values: list[str] = []
    for metric_id in metric_ids:
        label = next(
            (alias for alias in glossary.get(metric_id, ()) if counts[alias] == 1),
            None,
        )
        if label and label not in values:
            values.append(label)
    return tuple(values)


def _candidate_metric_rank(metric: dict[str, object]) -> tuple[bool, int]:
    """후보 adapter가 제공한 양의 rank를 우선하고 rank 없는 기존 adapter 순서는 안정적으로 유지한다."""

    value = metric.get("candidate_rank")
    valid = isinstance(value, int) and not isinstance(value, bool) and value > 0
    return (not valid, value if valid else 0)


def _model_periods(candidates: object, timezone: ZoneInfo) -> list[dict[str, Any]]:
    if not isinstance(candidates, list) or len(candidates) > 4:
        raise ValueError("Node1 period_candidates 는 최대 4개 항목 이내의 배열이어야 합니다.")
    validated: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Node1 기간 후보 항목은 객체여야 합니다.")
        try:
            start = datetime.fromisoformat(str(candidate["start"]))
            end = datetime.fromisoformat(str(candidate["end_exclusive"]))
            source_text = str(candidate["source_text"]).strip()
        except (KeyError, ValueError) as error:
            raise ValueError("Node1 기간 후보 형식이 올바르지 않습니다.") from error
        if (
            start.utcoffset() is None
            or end.utcoffset() is None
            or start.astimezone(timezone).utcoffset() != start.utcoffset()
            or end.astimezone(timezone).utcoffset() != end.utcoffset()
            or start >= end
            or not source_text
        ):
            raise ValueError("Node1 기간 후보가 컨텍스트 타임존 규칙을 위반했습니다.")
        validated.append(dict(candidate))
    return validated


def _complete_periods_before_as_of(
    periods: list[dict[str, Any]],
    as_of: datetime,
) -> list[dict[str, Any]]:
    """현재 진행 중인 구간의 미포함 종료 경계를 ``as_of``로 닫는다."""

    completed: list[dict[str, Any]] = []
    for period in periods:
        item = dict(period)
        start = datetime.fromisoformat(str(item["start"]))
        end = datetime.fromisoformat(str(item["end_exclusive"]))
        if start < as_of < end:
            item["end_exclusive"] = as_of.isoformat()
        completed.append(item)
    return completed


def _range_period_recheck_required(
    normalized: dict[str, Any],
    assets: list[dict[str, object]],
    candidate_ids: list[str],
    metric_terms: dict[str, dict[str, object]],
    executable_by_id: dict[str, dict[str, object]],
    as_of: datetime,
) -> bool:
    """확정된 range Metric에서 기간 슬롯만 비었을 때 1회 재검토가 필요한지 판정한다.

    질문 문구를 파싱하지 않고 첫 Node 1 출력과 active release 계약만 사용한다. snapshot
    Metric, 비분석 route, 미확정 Metric은 기간 범위를 요구하지 않거나 다른 명확화가 먼저이므로
    재호출하지 않는다. 실행 scope 구성 오류는 하류의 기존 typed gate가 그대로 보고한다.
    """

    raw_periods = normalized.get("period_candidates")
    ambiguity = normalized.get("ambiguity")
    if isinstance(ambiguity, dict) and ambiguity.get("is_ambiguous") is True:
        return False
    future_start = False
    if isinstance(raw_periods, list):
        try:
            future_start = any(
                isinstance(item, dict)
                and datetime.fromisoformat(str(item["start"])) >= as_of
                for item in raw_periods
            )
        except (KeyError, TypeError, ValueError):
            future_start = False
    if raw_periods != [] and not future_start:
        return False
    if normalized.get("metric_resolution") != "selected":
        return False
    if enum_signal(normalized.get("requested_route"), CONVERSATION_ROUTES) in {
        "PRESENTATION",
        "REPORT_ACTION",
    }:
        return False
    raw_ids = normalized.get("selected_metric_ids")
    if (
        not isinstance(raw_ids, list)
        or not 1 <= len(raw_ids) <= 4
        or len(raw_ids) != len(set(raw_ids))
        or any(not isinstance(item, str) or item not in candidate_ids for item in raw_ids)
    ):
        return False
    keep_ids = set(raw_ids)
    synthetic: list[dict[str, object]] = []
    try:
        for metric_id in raw_ids:
            ratio = _ratio_reference(metric_terms, executable_by_id, metric_id)
            if ratio is None:
                continue
            keep_ids.update(
                {
                    ratio["numerator_metric_id"],
                    ratio["denominator_metric_id"],
                }
            )
            synthetic.append(
                _synthetic_ratio_metric(
                    metric_id,
                    metric_terms[metric_id],
                    ratio,
                    executable_by_id[metric_id],
                )
            )
        selected_assets = _select_assets_for_metrics(
            assets,
            keep_ids,
            tuple(synthetic),
        )
        return time_selection_mode(selected_assets) == "range"
    except (ContextBuildError, KeyError, TypeError, ValueError):
        return False


def _analysis_shape_recheck_required(normalized: dict[str, Any]) -> bool:
    """선택된 분석 요청의 결과 형태 슬롯이 불완전하면 1회 재검토를 요구한다.

    ``analysis_operation``과 ``intent_candidates``는 같은 결정을 표현하는 active Node 1
    계약의 typed 필드다. BUSINESS Metric이 선택된 분석인데 두 필드가 비었거나 서로
    다르면 질문 문장을 서버에서 재해석하지 않고 모델에 한 번만 재검토시킨다.
    """

    if normalized.get("metric_resolution") != "selected":
        return False
    if enum_signal(normalized.get("requested_route"), CONVERSATION_ROUTES) in {
        "PRESENTATION",
        "REPORT_ACTION",
    }:
        return False
    raw_ids = normalized.get("selected_metric_ids")
    if (
        not isinstance(raw_ids, list)
        or not 1 <= len(raw_ids) <= 4
        or len(raw_ids) != len(set(raw_ids))
        or any(not isinstance(item, str) or not item for item in raw_ids)
    ):
        return False
    operation = normalized.get("analysis_operation")
    raw_intents = normalized.get("intent_candidates")
    return not (
        operation in _ANALYSIS_OPERATIONS
        and isinstance(raw_intents, list)
        and raw_intents == [operation]
    )


class MetricResolver:
    """승인된 자산 메타데이터 및 용어사전과 사용자의 질의를 대조하여 단일 지표를 확정하는 리졸버."""

    def __init__(self, adapter: DataPlatformAdapter, model: object) -> None:
        self._adapter = adapter
        self._model = model
        try:
            configured_ttl = float(
                os.getenv("DIMENSION_VALUE_CACHE_TTL_SECONDS", "300")
            )
        except ValueError:
            configured_ttl = 300.0
        self._dimension_value_cache_ttl = min(3_600.0, max(30.0, configured_ttl))
        self._dimension_value_cache: dict[
            tuple[str, str], tuple[float, tuple[str, ...]]
        ] = {}

    async def _dimension_values(self, asset_fqn: str, column: str) -> tuple[str, ...]:
        """Return one bounded live value domain with a short process-local TTL."""

        key = (asset_fqn, column)
        now = monotonic()
        cached = self._dimension_value_cache.get(key)
        if cached is not None and now < cached[0]:
            return cached[1]
        values = await discover_dimension_values(self._adapter, asset_fqn, column)
        if len(self._dimension_value_cache) >= 256:
            expired = [item for item, entry in self._dimension_value_cache.items() if now >= entry[0]]
            for item in expired:
                self._dimension_value_cache.pop(item, None)
            if len(self._dimension_value_cache) >= 256:
                self._dimension_value_cache.pop(next(iter(self._dimension_value_cache)))
        self._dimension_value_cache[key] = (
            now + self._dimension_value_cache_ttl,
            values,
        )
        return values

    async def resolve(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], str, dict[str, object]]:
        """사용자 요청으로부터 지표, 차원, 기간, 의도를 확정하고 구조화된 요청 객체를 생성합니다."""
        calendar_ids = {
            str(metadata.get("calendar_id") or "")
            for asset in assets
            for metadata in (asset.get("time_metadata"),)
            if isinstance(metadata, dict)
        }
        if len(calendar_ids) != 1 or not next(iter(calendar_ids), ""):
            raise MetadataUnavailableError(
                "선택된 DataHub 자산들이 단일 거버넌스 캘린더를 공유하지 않습니다."
            )
        calendar_id = next(iter(calendar_ids))
        executable_metrics = [
            metric
            for asset in assets
            for metric in asset.get("metrics", ())
            if isinstance(metric, dict) and isinstance(metric.get("id"), str)
        ]
        executable_ids = [str(metric["id"]) for metric in executable_metrics]
        if len(executable_ids) != len(set(executable_ids)):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_METRIC,
                "런타임 메타데이터에 중복된 지표 식별자가 존재합니다.",
            )
        executable_by_id = {
            str(metric["id"]): metric for metric in executable_metrics
        }
        candidates = [
            metric
            for metric in executable_metrics
            if metric.get("visibility", "BUSINESS") == "BUSINESS"
            and metric.get("candidate_selectable", True) is True
        ]
        candidates.sort(key=_candidate_metric_rank)
        candidate_ids = [str(metric["id"]) for metric in candidates]
        if not candidate_ids:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "런타임 메타데이터에서 거버넌스 지표를 찾을 수 없습니다.",
            )
        try:
            metric_terms = await self._adapter.get_metric_terms(tuple(candidate_ids))
        except MetadataUnavailableError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise MetadataUnavailableError(
                "DataHub Metric Glossary 조회에 실패했습니다."
            ) from error
        if set(metric_terms) != set(candidate_ids):
            raise MetadataUnavailableError(
                "DataHub Metric Glossary에 일부 지표 정의가 누락되었습니다."
            )
        glossary: dict[str, tuple[str, ...]] = {}
        for metric_id in candidate_ids:
            term = metric_terms[metric_id]
            label = str(term["label"])
            aliases = tuple(map(str, term["aliases"]))
            glossary[metric_id] = (
                label,
                *(alias for alias in aliases if alias != label),
            )
        business_terms: dict[str, dict[str, object]] = {
            metric_id: {"kind": "metric", "aliases": list(glossary[metric_id])}
            for metric_id in candidate_ids
        }
        support_terms: dict[str, dict[str, object]] = {}
        for metric in executable_metrics:
            metric_id = str(metric["id"])
            if (
                metric_id in candidate_ids
                or metric.get("visibility") != "SUPPORT"
                or metric.get("candidate_selectable", True) is not True
            ):
                continue
            semantic = metric.get("semantic")
            if not isinstance(semantic, dict):
                continue
            name = str(semantic.get("name") or "").strip()
            aliases = semantic.get("aliases")
            if not name or not isinstance(aliases, list):
                continue
            searchable_aliases = list(
                dict.fromkeys(
                    value
                    for value in (name, *(str(item).strip() for item in aliases))
                    if value
                )
            )
            if searchable_aliases:
                support_terms[metric_id] = {
                    "kind": "support_metric",
                    "aliases": searchable_aliases,
                }
        business_terms.update(support_terms)
        dimension_terms = _resolve_dimension_terms(assets)
        business_terms.update(
            {
                identifier: {
                    "kind": "dimension",
                    "aliases": list(term["aliases"]),
                }
                for identifier, term in dimension_terms.items()
            }
        )
        allowed_dimensions = {
            identifier
            for identifier, term in business_terms.items()
            if term["kind"] == "dimension"
        }
        try:
            timezone = ZoneInfo(context.timezone)
        except ZoneInfoNotFoundError as error:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "컨텍스트 타임존이 유효하지 않습니다.",
            ) from error

        # ── 1. Pre-resolved fast-path (멀티턴 슬롯 상속 시 Node 1 호출 건너뜀) ──
        resolved_metric_ids = (
            payload.resolved_slots.resolved_metric_ids
            if payload.resolved_slots is not None
            else ()
        )
        if resolved_metric_ids:
            if set(resolved_metric_ids).issubset(candidate_ids):
                pre_dims = list(payload.resolved_slots.dimension_ids)
                allowed_dimensions = {
                    identifier
                    for identifier, term in business_terms.items()
                    if term["kind"] == "dimension"
                }
                col_to_dim = {
                    str(term.get("field", {}).get("column")): identifier
                    for identifier, term in dimension_terms.items()
                    if isinstance(term.get("field"), dict) and term.get("field", {}).get("column")
                }
                validated_dims = []
                for d in pre_dims:
                    if d in allowed_dimensions:
                        validated_dims.append(d)
                    elif d in col_to_dim and col_to_dim[d] in allowed_dimensions:
                        validated_dims.append(col_to_dim[d])

                pre_filters = validated_pre_filters(
                    payload.resolved_slots.user_filters, dimension_terms, allowed_dimensions
                )

                pre_keep_ids = set(resolved_metric_ids)
                pre_synthetic: list[dict[str, object]] = []
                for pre_metric in resolved_metric_ids:
                    pre_ratio = _ratio_reference(
                        metric_terms, executable_by_id, pre_metric
                    )
                    if pre_ratio is None:
                        continue
                    if payload.resolved_slots.analysis_operation == "period_comparison":
                        raise ContextBuildError(
                            ContextBuildErrorCode.INVALID_METRIC,
                            "Ratio metric과 기간 비교의 동시 사용은 아직 거버넌스되지 않았습니다.",
                        )
                    pre_keep_ids |= {
                        pre_ratio["numerator_metric_id"],
                        pre_ratio["denominator_metric_id"],
                    }
                    pre_synthetic.append(
                        _synthetic_ratio_metric(
                            pre_metric,
                            metric_terms[pre_metric],
                            pre_ratio,
                            executable_by_id[pre_metric],
                        )
                    )
                selected_assets = _select_assets_for_metrics(
                    assets,
                    pre_keep_ids,
                    tuple(pre_synthetic),
                )
                analysis_time_mode = time_selection_mode(selected_assets)

                periods: list[dict[str, Any]] = []
                if payload.resolved_slots.period_start and payload.resolved_slots.period_end_exclusive:
                    periods = [{
                        "start": payload.resolved_slots.period_start,
                        "end_exclusive": payload.resolved_slots.period_end_exclusive,
                        "source_text": f"{payload.resolved_slots.period_start} ~ {payload.resolved_slots.period_end_exclusive}",
                    }]
                if (
                    payload.resolved_slots.comparison_period_start
                    and payload.resolved_slots.comparison_period_end_exclusive
                ):
                    periods.append(
                        {
                            "start": payload.resolved_slots.comparison_period_start,
                            "end_exclusive": payload.resolved_slots.comparison_period_end_exclusive,
                            "source_text": (
                                f"{payload.resolved_slots.comparison_period_start} ~ "
                                f"{payload.resolved_slots.comparison_period_end_exclusive}"
                            ),
                        }
                    )
                if analysis_time_mode == "latest_snapshot":
                    if (
                        payload.resolved_slots.analysis_operation
                        in {"time_trend", "period_comparison"}
                        or periods
                    ):
                        raise ContextBuildError(
                            ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                            "최신 스냅샷 지표에는 기간 범위·추이·기간 비교 전략이 승인되지 않았습니다.",
                        )

                structured_request = {
                    "intent_candidates": [
                        payload.resolved_slots.analysis_operation or "general"
                    ],
                    "metric_ids": sorted(pre_keep_ids),
                    "dimension_candidates": validated_dims,
                    "dimension_fields": [
                        dimension_terms[d]["field"]
                        for d in validated_dims
                        if d in dimension_terms
                    ],
                    "filter_fields": pre_filters,
                    "period_candidates": periods,
                    "period_relationship": (
                        "comparison" if len(periods) == 2 else "single"
                    ),
                    "time_mode": analysis_time_mode,
                    "selected_metric_id": (
                        resolved_metric_ids[0]
                        if len(resolved_metric_ids) == 1
                        else None
                    ),
                    "selected_metric_ids": list(resolved_metric_ids),
                    "analysis_operation": payload.resolved_slots.analysis_operation,
                    "result_limit": payload.resolved_slots.result_limit,
                    "metric_terms": {
                        mid: metric_terms[mid]
                        for mid in resolved_metric_ids
                        if mid in metric_terms
                    },
                }
                if len(resolved_metric_ids) == 1:
                    structured_request["metric_term"] = metric_terms[
                        resolved_metric_ids[0]
                    ]
                return selected_assets, payload.question, structured_request

        # ── 2. 단일 턴: LLM Node 1을 호출하여 질문 정규화 ──
        normalizer = getattr(self._model, "normalize_question", None)
        if not callable(normalizer):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "구조화된 Node1 resolver 모델 호출기가 필요합니다.",
            )
        as_of_datetime = datetime.combine(
            context.as_of,
            time.min,
            timezone,
        )
        node1_input = {
            "question": payload.question,
            "role_hint": context.role.value,
            "as_of": as_of_datetime.isoformat(),
            "timezone": context.timezone,
            "calendar_id": calendar_id,
            "allowed_routes": ["general", "template"],
            "business_terms": business_terms,
        }
        # 직전 턴 기간은 대화 앵커다. 이 값을 넘기지 않으면 "그 전 달"처럼 앵커가 이전
        # 기간인 표현을 Node1이 as_of 기준으로 잘못 해석하고, 서버가 문장을 다시 파싱해
        # 보정해야 한다. 앵커를 권위 시간 컨텍스트로 함께 전달해 해석을 한 곳에 모은다.
        previous_period = previous_period_anchor(payload.resolved_slots, timezone)
        if previous_period is not None:
            node1_input["previous_period"] = previous_period
        prior_shape = previous_result_shape(payload.resolved_slots)
        if prior_shape is not None:
            node1_input["previous_result_shape"] = prior_shape
        normalized = await normalizer(node1_input)
        if not isinstance(normalized, dict):
            raise ValueError("Node1 응답은 객체여야 합니다.")

        # Only an ANALYSIS interpretation that actually detected a named filter
        # may trigger a live suggestion query. This prevents report/presentation
        # turns and ordinary metric questions from touching Trino. When a bounded
        # domain is available, one constrained re-interpretation may select its
        # exact canonical value; the server still verifies that value afterward.
        detected_filters = normalized.get("filter_candidates")
        requested_route = enum_signal(
            normalized.get("requested_route"), CONVERSATION_ROUTES
        )
        can_discover_values = callable(
            getattr(self._adapter, "execute_query", None)
        ) and callable(getattr(self._adapter, "get_query_status", None))
        relevant_dimensions = {
            str(candidate.get("dimension_id"))
            for candidate in detected_filters
            if isinstance(candidate, dict)
            and candidate.get("dimension_id") in allowed_dimensions
            and isinstance(candidate.get("value_text"), str)
            and str(candidate["value_text"]).strip()
        } if isinstance(detected_filters, (list, tuple)) else set()
        should_reinterpret = False
        if can_discover_values and requested_route not in {"PRESENTATION", "REPORT_ACTION"}:
            for identifier in sorted(relevant_dimensions):
                field = dimension_terms[identifier].get("field")
                if not isinstance(field, dict):
                    continue
                try:
                    values = await self._dimension_values(
                        str(field["asset_fqn"]),
                        str(field["column"]),
                    )
                except (KeyError, OSError, TypeError, ValueError):
                    values = ()
                if not values:
                    continue
                business_terms[identifier]["value_candidates"] = list(values)
                raw_values = {
                    str(candidate["value_text"]).strip().casefold()
                    for candidate in detected_filters
                    if isinstance(candidate, dict)
                    and candidate.get("dimension_id") == identifier
                }
                if not raw_values.issubset({value.casefold() for value in values}):
                    should_reinterpret = True
        if should_reinterpret:
            normalized = await normalizer(node1_input)
            if not isinstance(normalized, dict):
                raise ValueError("Node1 재해석 응답은 객체여야 합니다.")
        interpretation_rechecked = False
        if _range_period_recheck_required(
            normalized,
            assets,
            candidate_ids,
            metric_terms,
            executable_by_id,
            as_of_datetime,
        ):
            node1_input["interpretation_recheck"] = {
                "target": "period_candidates",
                "attempt": 1,
            }
            normalized = await normalizer(node1_input)
            if not isinstance(normalized, dict):
                raise ValueError("Node1 기간 재검토 응답은 객체여야 합니다.")
            interpretation_rechecked = True
        if (
            not interpretation_rechecked
            and _analysis_shape_recheck_required(normalized)
        ):
            node1_input["interpretation_recheck"] = {
                "target": "analysis_operation",
                "attempt": 1,
            }
            normalized = await normalizer(node1_input)
            if not isinstance(normalized, dict):
                raise ValueError("Node1 결과 형태 재검토 응답은 객체여야 합니다.")
        periods = _complete_periods_before_as_of(
            _model_periods(normalized.get("period_candidates"), timezone),
            as_of_datetime,
        )
        ambiguity = normalized.get("ambiguity")
        period_is_ambiguous = (
            isinstance(ambiguity, dict)
            and ambiguity.get("is_ambiguous") is True
        )
        if (
            normalized.get("metric_resolution") == "selected"
            and not period_is_ambiguous
            and any(
                datetime.fromisoformat(str(item["start"])) >= as_of_datetime
                for item in periods
            )
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.OUT_OF_DATA_RANGE,
                "요청 기간은 데이터 기준일보다 이전에 시작해야 합니다.",
            )
        relationship = normalized.get("period_relationship")
        if relationship not in ("single", "comparison"):
            raise ValueError("Node1 period_relationship 은 'single' 또는 'comparison' 이어야 합니다.")
        is_comparison = relationship == "comparison"
        intents = [
            item
            for item in normalized.get("intent_candidates", ())
            if isinstance(item, str) and item
        ]
        shape_elided_followup = (
            normalized.get("metric_resolution") == "missing"
            and normalized.get("is_elliptical") is True
            and not intents
        )
        if len(intents) != 1 and not shape_elided_followup:
            raise ValueError("Node1은 정확히 1개의 분석 의도를 선택해야 합니다.")
        raw_dimensions = normalized.get("dimension_candidates", ())
        if not isinstance(raw_dimensions, list):
            raise ValueError("Node1 dimension_candidates 는 배열이어야 합니다.")
        selected_dimensions = [
            item
            for item in raw_dimensions
            if isinstance(item, str) and item in allowed_dimensions
        ]
        if len(selected_dimensions) != len(raw_dimensions):
            raise ValueError("Node1이 런타임 메타데이터 범위 밖의 차원을 선택했습니다.")
        filter_fields = resolve_filter_candidates(
            normalized.get("filter_candidates") or (),
            allowed_dimensions,
            dimension_terms,
        )
        raw_measurements = normalized.get("measurement_source_texts")
        if (
            not isinstance(raw_measurements, list)
            or len(raw_measurements) > 4
            or any(
                not isinstance(item, str)
                or not item.strip()
                or item not in payload.question
                for item in raw_measurements
            )
        ):
            raise ValueError(
                "Node1 measurement_source_texts 는 질문 원문의 고유한 연속 구간 4개 이하여야 합니다."
            )
        measurement_source_texts = [item.strip() for item in raw_measurements]
        if len(measurement_source_texts) != len(set(measurement_source_texts)):
            raise ValueError("Node1 measurement_source_texts 에 중복 구간이 있습니다.")
        expected_single_measurement = (
            measurement_source_texts[0]
            if len(measurement_source_texts) == 1
            else None
        )
        # measurement_source_texts가 질문 근거의 권위 목록이다. 단일 호환 projection은
        # 의미를 추가하지 않으므로 모델 출력과 대조하지 않고 서버가 결정론적으로 만든다.
        measurement_source_text = expected_single_measurement

        raw_selected_ids = normalized.get("selected_metric_ids")
        if (
            not isinstance(raw_selected_ids, list)
            or len(raw_selected_ids) > 4
            or any(not isinstance(item, str) or not item for item in raw_selected_ids)
            or len(raw_selected_ids) != len(set(raw_selected_ids))
        ):
            raise ValueError(
                "Node1 selected_metric_ids 는 고유한 지표 ID 4개 이하여야 합니다."
            )
        selected_metric_ids = list(raw_selected_ids)
        expected_single_selected = (
            selected_metric_ids[0] if len(selected_metric_ids) == 1 else None
        )
        # selected_metric_ids가 권위 목록이다. 단일 호환 필드는 모델이 따로 결정하게 두면
        # 같은 응답 안에서도 불일치할 수 있으므로 서버가 목록에서 항상 재계산한다.
        selected = expected_single_selected

        analysis_operation = normalized.get("analysis_operation")
        result_limit = normalized.get("result_limit")
        if analysis_operation is not None and analysis_operation not in _ANALYSIS_OPERATIONS:
            raise ValueError("Node1 analysis_operation 값이 유효하지 않습니다.")
        if shape_elided_followup:
            if analysis_operation is not None:
                raise ValueError(
                    "Node1 결과 형태 생략 후속 질문은 분석 연산을 지정할 수 없습니다."
                )
        elif analysis_operation is not None and intents != [analysis_operation]:
            raise ValueError("Node1 분석 연산과 의도가 일치하지 않습니다.")
        if result_limit is not None and (
            analysis_operation not in {"top_n", "bottom_n"}
            or isinstance(result_limit, bool)
            or not isinstance(result_limit, int)
            or not 1 <= result_limit <= 100
        ):
            raise ValueError(
                "Node1 result_limit은 top_n·bottom_n에서만 1~100으로 지정할 수 있습니다."
            )
        if analysis_operation in {"top_n", "bottom_n"} and result_limit is None:
            raise ValueError("Node1 순위 연산에는 result_limit이 필요합니다.")
        metric_resolution = normalized.get("metric_resolution")
        if metric_resolution not in {
            "selected",
            "ambiguous",
            "unsupported",
            "missing",
        }:
            raise ValueError("Node1 metric_resolution 값이 유효하지 않습니다.")
        raw_suggestions = normalized.get("metric_candidates")
        if not isinstance(raw_suggestions, list) or any(
            not isinstance(item, str) for item in raw_suggestions
        ):
            raise ValueError("Node1 metric_candidates 는 문자열 배열이어야 합니다.")
        raw_metric_ids = list(dict.fromkeys(raw_suggestions))
        if len(raw_metric_ids) != len(raw_suggestions):
            raise ValueError("Node1 metric_candidates 에 중복 식별자가 있습니다.")
        known_metric_ids = set(candidate_ids) | set(support_terms)
        if any(item not in known_metric_ids for item in raw_metric_ids):
            raise ValueError("Node1이 런타임 메타데이터 범위 밖의 지표를 선택했습니다.")
        if any(item not in candidate_ids for item in selected_metric_ids):
            raise ValueError("Node1이 BUSINESS 승인 범위 밖의 출력 지표를 선택했습니다.")
        suggestion_ids = [
            item
            for item in raw_metric_ids
            if item in candidate_ids
        ]
        analysis_operation, relationship, intents = _reconcile_comparison_axis(
            analysis_operation=analysis_operation,
            relationship=relationship,
            intents=intents,
            periods=periods,
            selected_metric_ids=selected_metric_ids,
            measurement_source_texts=measurement_source_texts,
            selected_dimensions=selected_dimensions,
            result_limit=result_limit,
            ambiguity=normalized.get("ambiguity"),
        )
        is_comparison = relationship == "comparison"
        requested_support_ids = list(
            dict.fromkeys(
                item
                for item in ([selected] if isinstance(selected, str) else []) + raw_metric_ids
                if item in support_terms
            )
        )
        partial_context = {
            "intent_candidates": intents,
            "metric_ids": selected_metric_ids or suggestion_ids,
            "metric_candidates": suggestion_ids,
            "metric_resolution": metric_resolution,
            "measurement_source_text": measurement_source_text,
            "measurement_source_texts": measurement_source_texts,
            "selected_metric_id": selected,
            "selected_metric_ids": selected_metric_ids,
            "analysis_operation": analysis_operation,
            "result_limit": result_limit,
            "dimension_candidates": selected_dimensions,
            "dimension_fields": [
                dimension_terms[item]["field"] for item in selected_dimensions
            ],
            "filter_fields": filter_fields,
            "period_candidates": periods,
            "period_relationship": relationship,
            "requested_route": enum_signal(
                normalized.get("requested_route"), CONVERSATION_ROUTES
            ),
            "presentation_type": enum_signal(
                normalized.get("presentation_type"), PRESENTATION_TYPES
            ),
            "is_elliptical": normalized.get("is_elliptical"),
        }
        if requested_support_ids:
            if (
                metric_resolution != "unsupported"
                or not measurement_source_texts
                or selected_metric_ids
                or raw_metric_ids != requested_support_ids
            ):
                raise ValueError(
                    "Node1 support 지표 판정과 후보가 일치하지 않습니다."
                )
            requested_names = [
                str(support_terms[item]["aliases"][0])
                for item in requested_support_ids
            ]
            display = ", ".join(f"'{name}'" for name in requested_names)
            raise ContextBuildError(
                ContextBuildErrorCode.METRIC_NOT_AVAILABLE,
                f"요청한 {display} 지표는 다른 지표 계산을 위한 내부 값이므로 직접 분석할 수 없습니다.",
                partial_context=partial_context,
            )
        if metric_resolution == "selected":
            selection_contract_matches = (
                bool(measurement_source_texts)
                and len(measurement_source_texts) == len(selected_metric_ids)
                and bool(selected_metric_ids)
                and suggestion_ids == selected_metric_ids
            )
            if not selection_contract_matches:
                # 모델이 ``selected``라고 하면서 다른 후보를 함께 반환하면 어느 지표도
                # 실행하지 않는다. 유효한 BUSINESS 후보만 남긴 typed 명확화로 낮춰
                # 사용자 질문을 서비스 장애로 오인시키지 않되, 임의 지표 자동 선택도 막는다.
                unresolved_ids = list(
                    dict.fromkeys([*suggestion_ids, *selected_metric_ids])
                )
                clarification_context = {
                    **partial_context,
                    "metric_ids": unresolved_ids,
                    "metric_candidates": unresolved_ids,
                    "metric_resolution": (
                        "ambiguous" if len(unresolved_ids) > 1 else "missing"
                    ),
                    "selected_metric_id": None,
                    "selected_metric_ids": [],
                }
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METRIC,
                    "질문을 하나의 승인 지표로 확정하지 못했습니다.",
                    _suggestions(unresolved_ids, glossary),
                    disambiguation_options=_disambiguation_options_for_metrics(
                        unresolved_ids, metric_terms
                    ),
                    partial_context=clarification_context,
                )
            if analysis_operation is None:
                raise ValueError(
                    "Node1 selected 분석 연산과 의도가 일치하지 않습니다."
                )
        elif selected_metric_ids:
            raise ValueError(
                "Node1은 selected 판정에서만 selected_metric_ids를 반환할 수 있습니다."
            )
        elif metric_resolution == "missing" and measurement_source_texts:
            raise ValueError(
                "Node1 missing 판정은 측정 대상 원문을 반환할 수 없습니다."
            )
        elif metric_resolution != "missing" and not measurement_source_texts:
            raise ValueError(
                "Node1 missing 이외 판정에는 측정 대상 원문이 필요합니다."
            )
        elif metric_resolution == "ambiguous" and len(suggestion_ids) < 2:
            raise ValueError("Node1 ambiguous 판정에는 2개 이상의 승인 지표 후보가 필요합니다.")
        elif metric_resolution in {"unsupported", "missing"} and suggestion_ids:
            raise ValueError(
                "Node1 unsupported 또는 missing 판정은 승인 지표 후보를 반환할 수 없습니다."
            )
        if relationship == "comparison" and analysis_operation not in {
            None,
            "period_comparison",
        }:
            raise ValueError(
                "Node1 비교 기간과 analysis_operation이 일치하지 않습니다."
            )
        if relationship == "single" and analysis_operation == "period_comparison":
            raise ValueError(
                "Node1 period_comparison은 정확히 두 기간과 함께 반환되어야 합니다."
            )
        if metric_resolution == "unsupported":
            raise ContextBuildError(
                ContextBuildErrorCode.METRIC_NOT_AVAILABLE,
                "요청한 분석 지표는 현재 승인된 분석 범위에 없습니다.",
                partial_context=partial_context,
            )
        if metric_resolution == "missing":
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에 분석할 지표가 포함되지 않았습니다.",
                _suggestions(candidate_ids, glossary),
                disambiguation_options=_disambiguation_options_for_metrics(candidate_ids, metric_terms),
                partial_context=partial_context,
            )
        if metric_resolution == "ambiguous":
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문이 여러 승인 지표로 해석될 수 있습니다.",
                _suggestions(suggestion_ids, glossary),
                disambiguation_options=_disambiguation_options_for_metrics(
                    suggestion_ids, metric_terms
                ),
                partial_context=partial_context,
            )
        keep_ids = set(selected_metric_ids)
        synthetic: list[dict[str, object]] = []
        for selected_id in selected_metric_ids:
            ratio = _ratio_reference(metric_terms, executable_by_id, selected_id)
            if is_comparison and ratio is not None:
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METRIC,
                    "Ratio metric과 기간 비교의 동시 사용은 아직 거버넌스되지 않았습니다.",
                )
            if ratio is None:
                continue
            keep_ids |= {
                ratio["numerator_metric_id"],
                ratio["denominator_metric_id"],
            }
            synthetic.append(
                _synthetic_ratio_metric(
                    selected_id,
                    metric_terms[selected_id],
                    ratio,
                    executable_by_id[selected_id],
                )
            )
        selected_assets = _select_assets_for_metrics(
            assets,
            keep_ids,
            tuple(synthetic),
        )
        analysis_time_mode = time_selection_mode(selected_assets)
        partial_context["time_mode"] = analysis_time_mode
        if analysis_time_mode == "latest_snapshot":
            if is_comparison or analysis_operation in {
                "time_trend",
                "period_comparison",
            }:
                raise ContextBuildError(
                    ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                    "최신 스냅샷 지표에는 추이 또는 기간 비교 전략이 승인되지 않았습니다.",
                    partial_context=partial_context,
                )
            if periods:
                raise ContextBuildError(
                    ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                    "기간 범위를 최신 스냅샷 기준일로 임의 변환할 수 없습니다.",
                    partial_context=partial_context,
                )
        else:
            has_saved_period = not is_comparison and all(
                name in payload.parameters
                for name in time_parameter_names(selected_assets)
            )
            if is_comparison:
                if len(periods) != 2:
                    raise ContextBuildError(
                        ContextBuildErrorCode.PERIOD_REQUIRED,
                        "기간 비교 분석은 정확히 2개의 기간 범위를 요구합니다.",
                        _period_suggestions(periods),
                        disambiguation_options=_disambiguation_options_for_periods(periods),
                        partial_context=partial_context,
                    )
            elif not has_saved_period and len(periods) != 1:
                if (
                    payload.resolved_slots is not None
                    and payload.resolved_slots.period_start
                    and payload.resolved_slots.period_end_exclusive
                ):
                    periods = [
                        {
                            "start": payload.resolved_slots.period_start,
                            "end_exclusive": payload.resolved_slots.period_end_exclusive,
                            "source_text": (
                                f"{payload.resolved_slots.period_start} ~ "
                                f"{payload.resolved_slots.period_end_exclusive}"
                            ),
                        }
                    ]
                else:
                    raise ContextBuildError(
                        ContextBuildErrorCode.PERIOD_REQUIRED,
                        "분석 기간은 정확히 1개의 기간 범위로 해석되어야 합니다.",
                        _period_suggestions(periods),
                        disambiguation_options=_disambiguation_options_for_periods(periods),
                        partial_context=partial_context,
                    )
        structured_request = {
            "intent_candidates": intents,
            "metric_ids": sorted(keep_ids),
            "dimension_candidates": selected_dimensions,
            "dimension_fields": [dimension_terms[item]["field"] for item in selected_dimensions],
            "filter_fields": filter_fields,
            "period_candidates": periods,
            "period_relationship": relationship,
            "time_mode": analysis_time_mode,
            "selected_metric_id": selected,
            "selected_metric_ids": selected_metric_ids,
            "analysis_operation": analysis_operation,
            "result_limit": result_limit,
            # Node1의 route/표현/생략문 신호는 후보다. 계약 enum 안의 값만 통과시키고
            # 라우트 확정과 전제조건 검증은 ConversationSlotResolver가 한다.
            "requested_route": enum_signal(normalized.get("requested_route"), CONVERSATION_ROUTES),
            "presentation_type": enum_signal(
                normalized.get("presentation_type"), PRESENTATION_TYPES
            ),
            "is_elliptical": normalized.get("is_elliptical"),
            "metric_terms": {
                mid: metric_terms[mid] for mid in selected_metric_ids
            },
        }
        if selected is not None:
            structured_request["metric_term"] = metric_terms[selected]
        question = normalized.get("normalized_question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Node1 normalized_question 은 필수입니다.")
        return selected_assets, question, structured_request
