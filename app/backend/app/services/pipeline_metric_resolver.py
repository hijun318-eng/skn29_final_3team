"""DataHub glossary·dimension·calendar 후보 안에서만 model의 구조화 질의 해석을 검증해 단일 metric·기간·intent를 선택하고 모호성은 ContextBuildError로 반환한다."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.contracts import AnalysisRequest, RequestContext
from app.ports.data_platform import DataPlatformAdapter, MetadataUnavailableError
from app.services.context_builder import ContextBuildError, ContextBuildErrorCode
from app.services.pipeline_runtime_contracts import time_parameter_names


def _suggestions(
    metric_ids: list[str],
    glossary: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
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


def _period_suggestions(candidates: object) -> tuple[str, ...]:
    if not isinstance(candidates, (list, tuple)):
        return ()
    return tuple(
        str(candidate["source_text"])
        for candidate in candidates
        if isinstance(candidate, dict)
        and isinstance(candidate.get("source_text"), str)
    )


def _model_periods(candidates: object, timezone: ZoneInfo) -> list[dict[str, Any]]:
    if not isinstance(candidates, list) or len(candidates) > 4:
        raise ValueError("Node1 period_candidates must be a bounded array")
    validated: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Node1 period candidate must be an object")
        try:
            start = datetime.fromisoformat(str(candidate["start"]))
            end = datetime.fromisoformat(str(candidate["end_exclusive"]))
            source_text = str(candidate["source_text"]).strip()
        except (KeyError, ValueError) as error:
            raise ValueError("Node1 period candidate is invalid") from error
        if (
            start.utcoffset() is None
            or end.utcoffset() is None
            or start.astimezone(timezone).utcoffset() != start.utcoffset()
            or end.astimezone(timezone).utcoffset() != end.utcoffset()
            or start >= end
            or not source_text
        ):
            raise ValueError("Node1 period candidate violates Context timezone")
        validated.append(dict(candidate))
    return validated


def _dimension_terms(assets: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    terms: dict[str, dict[str, object]] = {}
    for asset in assets:
        for dimension in asset.get("dimensions", ()):
            if not isinstance(dimension, dict):
                continue
            identifier = dimension.get("id") or dimension.get("field")
            aliases = dimension.get("aliases")
            if not isinstance(identifier, str) or not identifier:
                continue
            if not isinstance(aliases, (list, tuple)) or not aliases:
                continue
            terms[identifier] = {
                "kind": "dimension",
                "aliases": [str(alias) for alias in aliases if str(alias).strip()],
                "field": {
                    "asset_fqn": str(dimension.get("asset_fqn") or asset.get("fqn") or ""),
                    "column": str(dimension.get("column") or dimension.get("field") or ""),
                },
            }
    return terms


class MetricResolver:
    """권한 asset의 runtime glossary와 모델의 구조화 선택을 대조해 단일 metric을 확정한다.

    Data Platform이 반환한 term·calendar metadata만 후보로 사용하고 모델 응답의 ID가 그
    집합에 정확히 존재할 때만 선택한다. 누락·모호성·calendar 불일치는 임의 alias나 질문
    키워드로 보강하지 않고 typed context failure로 차단한다.
    """
    def __init__(self, adapter: DataPlatformAdapter, model: object) -> None:
        self._adapter = adapter
        self._model = model

    async def resolve(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], str, dict[str, object]]:
        """지표 resolver 후보를 거버넌스 제약과 입력 증거로 판정해 하나의 결과로 좁힌다."""
        calendar_ids = {
            str(metadata.get("calendar_id") or "")
            for asset in assets
            for metadata in (asset.get("time_metadata"),)
            if isinstance(metadata, dict)
        }
        if len(calendar_ids) != 1 or not next(iter(calendar_ids), ""):
            raise MetadataUnavailableError(
                "Selected DataHub assets do not share one governed calendar."
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
                "Runtime metadata did not resolve a governed metric.",
            )
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_METRIC,
                "Runtime metadata contains duplicate metric identifiers.",
            )
        try:
            metric_terms = await self._adapter.get_metric_terms(tuple(candidate_ids))
        except MetadataUnavailableError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise MetadataUnavailableError(
                "DataHub Metric Glossary lookup failed."
            ) from error
        if set(metric_terms) != set(candidate_ids):
            raise MetadataUnavailableError(
                "DataHub Metric Glossary is missing a resolved metric."
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
        dimension_terms = _dimension_terms(assets)
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
                "Context timezone is invalid.",
            ) from error
        # ── Pre-resolved fast-path ──────────────────────────────────────────
        # 멀티턴 대화에서 이전 턴의 슬롯을 상속할 때, Orchestrator가
        # payload.resolved_slots (ResolvedSlots)를 전달한다.
        # 거버넌스 검증(후보 목록 및 권한 대조)을 철저히 수행한 뒤 Node 1 LLM 호출을 건너뛴다.
        if payload.resolved_slots is not None and payload.resolved_slots.metric_id:
            pre_metric = payload.resolved_slots.metric_id
            if pre_metric in candidate_ids:
                pre_dims = list(payload.resolved_slots.dimension_ids)
                allowed_dimensions = {
                    identifier
                    for identifier, term in business_terms.items()
                    if term["kind"] == "dimension"
                }
                validated_dims = [d for d in pre_dims if d in allowed_dimensions]

                selected_assets: list[dict[str, object]] = []
                for asset in assets:
                    item = dict(asset)
                    if "metrics" in item:
                        item["metrics"] = tuple(
                            metric
                            for metric in item.get("metrics", ())
                            if isinstance(metric, dict) and metric.get("id") == pre_metric
                        )
                    selected_assets.append(item)
                if not any(asset.get("join_ids") for asset in selected_assets):
                    selected_assets = [asset for asset in selected_assets if asset.get("metrics")]

                periods: list[dict[str, Any]] = []
                if payload.resolved_slots.period_start and payload.resolved_slots.period_end_exclusive:
                    periods = [{
                        "start": payload.resolved_slots.period_start,
                        "end_exclusive": payload.resolved_slots.period_end_exclusive,
                        "source_text": f"{payload.resolved_slots.period_start} ~ {payload.resolved_slots.period_end_exclusive}",
                    }]

                structured_request = {
                    "intent_candidates": ["general"],
                    "metric_ids": [pre_metric],
                    "dimension_candidates": validated_dims,
                    "dimension_fields": [
                        dimension_terms[d]["field"]
                        for d in validated_dims
                        if d in dimension_terms
                    ],
                    "period_candidates": periods,
                    "selected_metric_id": pre_metric,
                    "metric_term": metric_terms[pre_metric],
                }
                return selected_assets, payload.question, structured_request
        # ── End pre-resolved fast-path ─────────────────────────────────────

        normalizer = getattr(self._model, "normalize_question", None)
        if not callable(normalizer):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "A structured Node1 resolver is required.",
            )
        normalized = await normalizer(
            {
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
        )
        if not isinstance(normalized, dict):
            raise ValueError("Node1 response must be an object")
        periods = _model_periods(normalized.get("period_candidates"), timezone)
        has_saved_period = all(
            name in payload.parameters for name in time_parameter_names(assets)
        )
        if not has_saved_period and len(periods) != 1:
            raise ContextBuildError(
                ContextBuildErrorCode.PERIOD_REQUIRED,
                "The analysis period must resolve to one range.",
                _period_suggestions(periods),
            )
        selected = normalized.get("selected_metric_id")
        if not isinstance(selected, str) or selected not in candidate_ids:
            suggestions = normalized.get("metric_candidates")
            suggestion_ids = [
                item
                for item in suggestions if isinstance(item, str) and item in candidate_ids
            ] if isinstance(suggestions, list) else candidate_ids
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "The request did not resolve to one governed metric.",
                _suggestions(suggestion_ids or candidate_ids, glossary),
            )
        selected_assets: list[dict[str, object]] = []
        for asset in assets:
            item = dict(asset)
            if "metrics" in item:
                item["metrics"] = tuple(
                    metric
                    for metric in item.get("metrics", ())
                    if isinstance(metric, dict) and metric.get("id") == selected
                )
            selected_assets.append(item)
        if not any(asset.get("join_ids") for asset in selected_assets):
            selected_assets = [asset for asset in selected_assets if asset.get("metrics")]
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
            raise ValueError("Node1 must resolve exactly one analysis intent")
        selected_dimensions = [
            item
            for item in normalized.get("dimension_candidates", ())
            if isinstance(item, str) and item in allowed_dimensions
        ]
        if len(selected_dimensions) != len(normalized.get("dimension_candidates", ())):
            raise ValueError("Node1 selected a dimension outside runtime metadata")
        structured_request = {
            "intent_candidates": intents,
            "metric_ids": [selected],
            "dimension_candidates": selected_dimensions,
            "dimension_fields": [dimension_terms[item]["field"] for item in selected_dimensions],
            "period_candidates": periods,
            "selected_metric_id": selected,
            "metric_term": metric_terms[selected],
        }
        question = normalized.get("normalized_question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Node1 normalized_question is required")
        return selected_assets, question, structured_request

