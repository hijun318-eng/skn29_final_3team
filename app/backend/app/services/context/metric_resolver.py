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
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.contracts import AnalysisRequest, ClarificationType, DisambiguationOption, RequestContext
from app.ports.data_platform import DataPlatformAdapter, MetadataUnavailableError
from app.services.context.builder import ContextBuildError, ContextBuildErrorCode
from app.services.context.values import RATIO_ZERO_POLICIES
from app.services.context.filter_candidate_resolver import (
    dimension_terms as _resolve_dimension_terms,
    resolve_filter_candidates,
    validated_pre_filters,
)
from app.services.context.period_clarification import (
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


def _ratio_reference(
    metric_terms: dict[str, dict[str, object]],
    candidate_ids: list[str],
    metric_id: str,
) -> dict[str, str] | None:
    term = metric_terms[metric_id]
    if term.get("kind") != "ratio":
        return None
    numerator_id = term.get("numerator_metric_id")
    denominator_id = term.get("denominator_metric_id")
    zero_policy = term.get("zero_policy")
    if (
        not isinstance(numerator_id, str)
        or not isinstance(denominator_id, str)
        or numerator_id == denominator_id
        or numerator_id not in candidate_ids
        or denominator_id not in candidate_ids
        or metric_terms[numerator_id].get("kind", "column") != "column"
        or metric_terms[denominator_id].get("kind", "column") != "column"
        or not isinstance(zero_policy, str)
        or zero_policy not in RATIO_ZERO_POLICIES
    ):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "Ratio metric term의 분자·분모 참조가 승인된 단일 metric을 가리키지 않습니다.",
        )
    return {
        "numerator_metric_id": numerator_id,
        "denominator_metric_id": denominator_id,
        "zero_policy": zero_policy,
    }


def _synthetic_ratio_metric(
    metric_id: str,
    term: dict[str, object],
    ratio: dict[str, str],
) -> dict[str, object]:
    return {
        "id": metric_id,
        "asset_fqn": "",
        "field": "",
        "aggregation": "ratio",
        "time_field": "",
        "required_filters": [],
        "result_field": metric_id,
        "unit": str(term.get("unit") or ""),
        "numerator_metric_id": ratio["numerator_metric_id"],
        "denominator_metric_id": ratio["denominator_metric_id"],
        "zero_policy": ratio["zero_policy"],
    }


def _select_assets_for_metrics(
    assets: list[dict[str, object]],
    keep_ids: set[str],
    synthetic: dict[str, object] | None,
) -> list[dict[str, object]]:
    selected_assets: list[dict[str, object]] = []
    injected = False
    for asset in assets:
        item = dict(asset)
        if "metrics" in item:
            kept = tuple(
                metric
                for metric in item.get("metrics", ())
                if isinstance(metric, dict) and metric.get("id") in keep_ids
            )
            if synthetic is not None:
                # 검색 단계의 ratio 항목은 후보 노출용이다. 실행 Context에는 현재
                # Glossary read-back으로 다시 합성한 한 개의 canonical rule만 둔다.
                kept = tuple(
                    metric
                    for metric in kept
                    if metric.get("id") != synthetic["id"]
                )
            if (
                synthetic is not None
                and not injected
                and any(metric.get("id") == synthetic["numerator_metric_id"] for metric in kept)
            ):
                kept = kept + (synthetic,)
                injected = True
            item["metrics"] = kept
        selected_assets.append(item)
    if synthetic is not None and not injected:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "Ratio metric의 분자 metric이 승인된 asset에서 발견되지 않았습니다.",
        )
    if not any(asset.get("join_ids") for asset in selected_assets):
        selected_assets = [asset for asset in selected_assets if asset.get("metrics")]
    return selected_assets


class MetricResolver:
    """승인된 자산 메타데이터 및 용어사전과 사용자의 질의를 대조하여 단일 지표를 확정하는 리졸버."""

    def __init__(self, adapter: DataPlatformAdapter, model: object) -> None:
        self._adapter = adapter
        self._model = model

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
        candidates = [
            metric
            for asset in assets
            for metric in asset.get("metrics", ())
            if isinstance(metric, dict) and isinstance(metric.get("id"), str)
        ]
        candidate_ids = [str(metric["id"]) for metric in candidates]
        if not candidate_ids:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "런타임 메타데이터에서 거버넌스 지표를 찾을 수 없습니다.",
            )
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_METRIC,
                "런타임 메타데이터에 중복된 지표 식별자가 존재합니다.",
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

                pre_ratio = _ratio_reference(metric_terms, candidate_ids, pre_metric)
                pre_keep_ids = {pre_metric}
                pre_synthetic = None
                if pre_ratio is not None:
                    pre_keep_ids |= {pre_ratio["numerator_metric_id"], pre_ratio["denominator_metric_id"]}
                    pre_synthetic = _synthetic_ratio_metric(pre_metric, metric_terms[pre_metric], pre_ratio)
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
                    "metric_terms": {mid: metric_terms[mid] for mid in pre_keep_ids},
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
        periods = _model_periods(normalized.get("period_candidates"), timezone)
        relationship = normalized.get("period_relationship")
        if relationship not in ("single", "comparison"):
            raise ValueError("Node1 period_relationship 은 'single' 또는 'comparison' 이어야 합니다.")
        is_comparison = relationship == "comparison"
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
                )
        selected = normalized.get("selected_metric_id")
        if not isinstance(selected, str) or selected not in candidate_ids:
            suggestions = normalized.get("metric_candidates")
            suggestion_ids = [
                item
                for item in suggestions if isinstance(item, str) and item in candidate_ids
            ] if isinstance(suggestions, list) else candidate_ids
            target_cand_ids = suggestion_ids or candidate_ids
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문이 여러 지표로 해석될 수 있거나 승인된 단일 지표로 특정되지 않았습니다.",
                _suggestions(target_cand_ids, glossary),
                disambiguation_options=_disambiguation_options_for_metrics(target_cand_ids, metric_terms),
            )
        ratio = _ratio_reference(metric_terms, candidate_ids, selected)
        if is_comparison and ratio is not None:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Ratio metric과 기간 비교의 동시 사용은 아직 거버넌스되지 않았습니다.",
            )
        keep_ids = {selected}
        synthetic = None
        if ratio is not None:
            keep_ids |= {ratio["numerator_metric_id"], ratio["denominator_metric_id"]}
            synthetic = _synthetic_ratio_metric(selected, metric_terms[selected], ratio)
        selected_assets = _select_assets_for_metrics(assets, keep_ids, synthetic)
        allowed_dimensions = {
            identifier
            for identifier, term in business_terms.items()
            if term["kind"] == "dimension"
        }
        intents = [
            item
            for item in normalized.get("intent_candidates", ())
            if isinstance(item, str) and item
        ]
        if len(intents) != 1:
            raise ValueError("Node1은 정확히 1개의 분석 의도를 선택해야 합니다.")
        selected_dimensions = [
            item
            for item in normalized.get("dimension_candidates", ())
            if isinstance(item, str) and item in allowed_dimensions
        ]
        if len(selected_dimensions) != len(normalized.get("dimension_candidates", ())):
            raise ValueError("Node1이 런타임 메타데이터 범위 밖의 차원을 선택했습니다.")
        filter_fields = resolve_filter_candidates(
            normalized.get("filter_candidates") or (), allowed_dimensions, dimension_terms
        )
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
            "metric_terms": {mid: metric_terms[mid] for mid in keep_ids},
        }
        question = normalized.get("normalized_question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Node1 normalized_question 은 필수입니다.")
        return selected_assets, question, structured_request
