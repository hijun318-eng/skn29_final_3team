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
from app.services.context.model_time_context import previous_period_anchor
from app.services.context.runtime_contracts import time_parameter_names


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
    """Cap intervals that contain the current business date at ``as_of``."""

    completed: list[dict[str, Any]] = []
    for period in periods:
        item = dict(period)
        start = datetime.fromisoformat(str(item["start"]))
        end = datetime.fromisoformat(str(item["end_exclusive"]))
        if start < as_of < end:
            item["end_exclusive"] = as_of.isoformat()
        completed.append(item)
    return completed


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
        ]
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
        if payload.resolved_slots is not None and payload.resolved_slots.metric_id:
            pre_metric = payload.resolved_slots.metric_id
            if pre_metric in candidate_ids:
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

                pre_ratio = _ratio_reference(
                    metric_terms, executable_by_id, pre_metric
                )
                pre_keep_ids = {pre_metric}
                pre_synthetic = None
                if pre_ratio is not None:
                    pre_keep_ids |= {pre_ratio["numerator_metric_id"], pre_ratio["denominator_metric_id"]}
                    pre_synthetic = _synthetic_ratio_metric(
                        pre_metric,
                        metric_terms[pre_metric],
                        pre_ratio,
                        executable_by_id[pre_metric],
                    )
                selected_assets = _select_assets_for_metrics(assets, pre_keep_ids, pre_synthetic)

                periods: list[dict[str, Any]] = []
                if payload.resolved_slots.period_start and payload.resolved_slots.period_end_exclusive:
                    periods = [{
                        "start": payload.resolved_slots.period_start,
                        "end_exclusive": payload.resolved_slots.period_end_exclusive,
                        "source_text": f"{payload.resolved_slots.period_start} ~ {payload.resolved_slots.period_end_exclusive}",
                    }]

                structured_request = {
                    "intent_candidates": ["general"],
                    "metric_ids": sorted(pre_keep_ids),
                    "dimension_candidates": validated_dims,
                    "dimension_fields": [
                        dimension_terms[d]["field"]
                        for d in validated_dims
                        if d in dimension_terms
                    ],
                    "filter_fields": pre_filters,
                    "period_candidates": periods,
                    "period_relationship": "single",
                    "selected_metric_id": pre_metric,
                    "metric_term": metric_terms[pre_metric],
                    "metric_terms": {
                        mid: metric_terms[mid]
                        for mid in pre_keep_ids
                        if mid in metric_terms
                    },
                }
                return selected_assets, payload.question, structured_request

        # ── 2. 단일 턴: LLM Node 1을 호출하여 질문 정규화 ──
        normalizer = getattr(self._model, "normalize_question", None)
        if not callable(normalizer):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "구조화된 Node1 resolver 모델 호출기가 필요합니다.",
            )
        node1_input = {
            "question": payload.question,
            "role_hint": context.role.value,
            "as_of": datetime.combine(
                context.as_of,
                time.min,
                timezone,
            ).isoformat(),
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
        periods = _complete_periods_before_as_of(
            _model_periods(normalized.get("period_candidates"), timezone),
            datetime.combine(context.as_of, time.min, timezone),
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
        if len(intents) != 1:
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
        selected = normalized.get("selected_metric_id")
        raw_suggestions = normalized.get("metric_candidates")
        suggestion_ids = [
            item
            for item in raw_suggestions
            if isinstance(item, str) and item in candidate_ids
        ] if isinstance(raw_suggestions, list) else []
        partial_context = {
            "intent_candidates": intents,
            "metric_ids": (
                [selected]
                if isinstance(selected, str) and selected in candidate_ids
                else suggestion_ids
            ),
            "metric_candidates": suggestion_ids,
            "selected_metric_id": (
                selected
                if isinstance(selected, str) and selected in candidate_ids
                else None
            ),
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
        has_saved_period = not is_comparison and all(
            name in payload.parameters for name in time_parameter_names(assets)
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
                periods = [{
                    "start": payload.resolved_slots.period_start,
                    "end_exclusive": payload.resolved_slots.period_end_exclusive,
                    "source_text": f"{payload.resolved_slots.period_start} ~ {payload.resolved_slots.period_end_exclusive}",
                }]
            else:
                raise ContextBuildError(
                    ContextBuildErrorCode.PERIOD_REQUIRED,
                    "분석 기간은 정확히 1개의 기간 범위로 해석되어야 합니다.",
                    _period_suggestions(periods),
                    disambiguation_options=_disambiguation_options_for_periods(periods),
                    partial_context=partial_context,
                )
        if not isinstance(selected, str) or selected not in candidate_ids:
            target_cand_ids = suggestion_ids or candidate_ids
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문이 여러 지표로 해석될 수 있거나 승인된 단일 지표로 특정되지 않았습니다.",
                _suggestions(target_cand_ids, glossary),
                disambiguation_options=_disambiguation_options_for_metrics(target_cand_ids, metric_terms),
                partial_context=partial_context,
            )
        ratio = _ratio_reference(metric_terms, executable_by_id, selected)
        if is_comparison and ratio is not None:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Ratio metric과 기간 비교의 동시 사용은 아직 거버넌스되지 않았습니다.",
            )
        keep_ids = {selected}
        synthetic = None
        if ratio is not None:
            keep_ids |= {ratio["numerator_metric_id"], ratio["denominator_metric_id"]}
            synthetic = _synthetic_ratio_metric(
                selected,
                metric_terms[selected],
                ratio,
                executable_by_id[selected],
            )
        selected_assets = _select_assets_for_metrics(assets, keep_ids, synthetic)
        structured_request = {
            "intent_candidates": intents,
            "metric_ids": sorted(keep_ids),
            "dimension_candidates": selected_dimensions,
            "dimension_fields": [dimension_terms[item]["field"] for item in selected_dimensions],
            "filter_fields": filter_fields,
            "period_candidates": periods,
            "period_relationship": relationship,
            "selected_metric_id": selected,
            # Node1의 route/표현/생략문 신호는 후보다. 계약 enum 안의 값만 통과시키고
            # 라우트 확정과 전제조건 검증은 ConversationSlotResolver가 한다.
            "requested_route": enum_signal(normalized.get("requested_route"), CONVERSATION_ROUTES),
            "presentation_type": enum_signal(
                normalized.get("presentation_type"), PRESENTATION_TYPES
            ),
            "is_elliptical": normalized.get("is_elliptical"),
            "metric_term": metric_terms[selected],
            "metric_terms": {
                mid: metric_terms[mid] for mid in keep_ids if mid in metric_terms
            },
        }
        question = normalized.get("normalized_question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Node1 normalized_question 은 필수입니다.")
        return selected_assets, question, structured_request
