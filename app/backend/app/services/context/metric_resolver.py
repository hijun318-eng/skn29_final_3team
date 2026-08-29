"""DataHub 메타데이터 및 용어사전 기반 지표(Metric) 및 기간/차원 해석기 모듈.

[핵심 목적]
사용자의 자연어 질문과 대화 상태를 바탕으로:
1. 멀티턴 Fast-Path: 이전 턴에서 상속된 지표/기간/차원이 있는 경우 거버넌스 검증 후 LLM Node 1 호출을 건너뜀
2. 단일 턴 정규화: LLM Node 1을 호출하여 DataHub 비즈니스 용어사전(Glossary Terms), 차원 목록, 캘린더 메타데이터와 대조
3. 모호성 감지 (Disambiguation): 여러 지표나 기간으로 해석될 수 있는 경우 `ContextBuildError(CLARIFICATION_REQUIRED)`를 반환하여
   사용자에게 명확한 선택지를 제공합니다.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date, datetime, time, timedelta
import json
import os
import re
from time import monotonic
from typing import Any
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.contracts import AnalysisRequest, ClarificationType, DisambiguationOption, RequestContext
from app.ports.data_platform import (
    AssetCandidateSet,
    DataPlatformAdapter,
    ExecutionAssetSelection,
    GovernedFieldReference,
    MetadataUnavailableError,
)
from app.services.context.builder import ContextBuildError, ContextBuildErrorCode
from app.services.context.metric_execution_scope import (
    ratio_reference as _ratio_reference,
    select_assets_for_metrics as _select_assets_for_metrics,
    synthetic_ratio_metric as _synthetic_ratio_metric,
)
from app.services.context.filter_candidate_resolver import (
    dimension_member_receipts,
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
from app.services.context.node1_interpretation import (
    build_node1_interpretation_context,
)
from app.services.context.runtime_contracts import (
    comparison_time_parameter_names,
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
_ANALYSIS_TIME_BUCKETS = frozenset({"day", "week", "month", "quarter", "year"})
_MAX_OMITTED_FILTER_DIMENSION_PROBES = 4
_KOREAN_CALENDAR_UNITS = {
    "분기": "quarter",
    "연도": "year",
    "년도": "year",
    "일": "day",
    "주": "week",
    "월": "month",
    "년": "year",
}


def _explicit_calendar_time_bucket(question: str) -> str | None:
    """명시된 반복 달력 단위를 유한 time-bucket 계약으로만 변환한다.

    날짜의 ``5월``·``2026년`` 자체는 cadence가 아니므로 선택하지 않는다. 한국어의
    생산적 ``별/마다/매-`` 형태만 인정하고, 서로 다른 단위가 동시에 나타나면 임의
    우선순위를 두지 않고 ``None``으로 닫는다.
    """

    normalized = unicodedata.normalize("NFKC", question).casefold()
    buckets: set[str] = set()
    for token in re.findall(r"[가-힣]+", normalized):
        for stem, bucket in _KOREAN_CALENDAR_UNITS.items():
            if (
                token.startswith(f"{stem}별")
                or token.startswith(f"{stem}마다")
                or token.startswith(f"매{stem}")
            ):
                buckets.add(bucket)
                break
    return next(iter(buckets)) if len(buckets) == 1 else None


def _reconcile_explicit_calendar_bucket(
    normalized: dict[str, Any],
    question: str,
) -> dict[str, Any]:
    """질문의 명시 cadence와 일반 shape 오판만 ``time_trend``로 결속한다.

    Metric·기간·차원은 추가하지 않는다. 순위나 정확히 두 기간 비교처럼 다른 연산이
    이미 선택됐거나 cadence가 충돌하면 모델 결정을 덮지 않고 후속 검증에 맡긴다.
    """

    bucket = _explicit_calendar_time_bucket(question)
    operation = normalized.get("analysis_operation")
    if (
        bucket is None
        or normalized.get("metric_resolution") != "selected"
        or enum_signal(normalized.get("requested_route"), CONVERSATION_ROUTES)
        == "REPORT_ACTION"
        or operation not in {None, "aggregate", "breakdown", "time_trend"}
        or normalized.get("result_limit") is not None
    ):
        return normalized
    reconciled = dict(normalized)
    reconciled["analysis_operation"] = "time_trend"
    reconciled["intent_candidates"] = ["time_trend"]
    reconciled["analysis_time_bucket"] = bucket
    return reconciled


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
    """검증된 기간 수와 일반 비교 결과 형태의 중복 신호를 일관되게 결속한다.

    질문 문자열을 다시 파싱하지 않고 이미 검증된 구조만 사용한다. 정확히 두 기간과
    comparison 관계가 확정됐는데 일반 aggregate/breakdown으로 남은 응답은
    period_comparison으로 좁힌다. 반대로 서로 다른 측정값이 둘 이상 확정됐지만 두 번째
    기간이 없으면 하나의 공유 기간에서 지표들을 나란히 조회하는 일반 형태로 복구한다.
    추이·순위처럼 별도 의미가 있는 충돌과 시간 모호성은 보정하지 않고 후속 검증이
    fail-closed하도록 둔다.
    """

    is_ambiguous = (
        isinstance(ambiguity, dict) and ambiguity.get("is_ambiguous") is True
    )
    if (
        relationship == "comparison"
        and len(periods) == 2
        and analysis_operation in {"aggregate", "breakdown"}
        and intents == [analysis_operation]
        and bool(selected_metric_ids)
        and len(measurement_source_texts) == len(selected_metric_ids)
        and result_limit is None
        and not is_ambiguous
    ):
        return "period_comparison", relationship, ["period_comparison"]
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


def _reconcile_filter_only_dimensions(
    normalized: dict[str, Any],
) -> dict[str, Any]:
    """Keep equality predicates while removing their duplicate output grouping.

    Aggregate, time-trend and period-comparison shapes do not request a categorical
    breakdown. A dimension that is already an explicit filter must not become a
    constant result column solely because Node 1 returned it in both lists.
    """

    if normalized.get("analysis_operation") not in {
        "aggregate",
        "time_trend",
        "period_comparison",
    }:
        return normalized
    dimensions = normalized.get("dimension_candidates")
    filters = normalized.get("filter_candidates")
    if not isinstance(dimensions, list) or not isinstance(filters, list):
        return normalized
    filtered_dimensions = {
        str(candidate.get("dimension_id"))
        for candidate in filters
        if isinstance(candidate, dict) and candidate.get("dimension_id")
    }
    reconciled_dimensions = [
        identifier
        for identifier in dimensions
        if identifier not in filtered_dimensions
    ]
    if reconciled_dimensions == dimensions:
        return normalized
    return {**normalized, "dimension_candidates": reconciled_dimensions}


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


def _semantic_tokens(value: object) -> tuple[str, ...]:
    """Return Unicode word tokens for metadata-to-metadata alias comparison."""

    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return tuple(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def _contains_token_sequence(
    container: tuple[str, ...],
    sequence: tuple[str, ...],
) -> bool:
    if not sequence or len(sequence) > len(container):
        return False
    return any(
        container[index : index + len(sequence)] == sequence
        for index in range(len(container) - len(sequence) + 1)
    )


def _metric_aliases_specialize(
    specific_aliases: tuple[str, ...],
    base_aliases: tuple[str, ...],
) -> bool:
    """Match a reviewed specialization using only multi-token DataHub aliases."""

    specific_tokens = tuple(
        tokens for alias in specific_aliases if (tokens := _semantic_tokens(alias))
    )
    base_tokens = tuple(
        tokens
        for alias in base_aliases
        if len(tokens := _semantic_tokens(alias)) >= 2
    )
    return any(
        len(specific) > len(base)
        and _contains_token_sequence(specific, base)
        for specific in specific_tokens
        for base in base_tokens
    )


def _metric_dimension_keys(metric: dict[str, object]) -> set[tuple[str, str]]:
    dimensions = metric.get("dimensions")
    if not isinstance(dimensions, (list, tuple)):
        return set()
    return {
        (str(item.get("asset_fqn") or ""), str(item.get("column") or ""))
        for item in dimensions
        if isinstance(item, dict)
        and item.get("asset_fqn")
        and item.get("column")
    }


def _metric_family_dimension_ids(
    normalized: dict[str, Any],
    candidates: list[dict[str, object]],
    glossary: dict[str, tuple[str, ...]],
    dimension_terms: dict[str, dict[str, object]],
    *,
    omitted_only: bool = False,
) -> tuple[str, ...]:
    """Find bounded extra dimensions shared by every selected metric family.

    The relationship is derived from reviewed DataHub aliases and governed metric
    dimensions. It does not infer a filter value or select a metric itself.
    """

    if (
        normalized.get("metric_resolution") != "selected"
        or (
            omitted_only
            and normalized.get("filter_candidates") not in ([], ())
        )
    ):
        return ()
    raw_selected = normalized.get("selected_metric_ids")
    if not isinstance(raw_selected, list) or not raw_selected:
        return ()
    selected_ids = tuple(
        item for item in raw_selected if isinstance(item, str) and item in glossary
    )
    if len(selected_ids) != len(raw_selected):
        return ()

    metrics = {
        str(metric["id"]): metric
        for metric in candidates
        if isinstance(metric.get("id"), str)
    }
    field_identifiers: dict[tuple[str, str], list[str]] = {}
    for identifier, term in dimension_terms.items():
        field = term.get("field")
        if not isinstance(field, dict):
            continue
        key = (str(field.get("asset_fqn") or ""), str(field.get("column") or ""))
        if all(key):
            field_identifiers.setdefault(key, []).append(identifier)

    eligible_by_selected: list[set[str]] = []
    dimension_rank: dict[str, tuple[bool, int]] = {}
    for selected_id in selected_ids:
        selected_metric = metrics.get(selected_id)
        if selected_metric is None:
            return ()
        selected_dimensions = {
            column for _asset_fqn, column in _metric_dimension_keys(selected_metric)
        }
        eligible: set[str] = set()
        for other_id, other_metric in metrics.items():
            if other_id == selected_id or other_id not in glossary:
                continue
            other_dimensions = {
                column for _asset_fqn, column in _metric_dimension_keys(other_metric)
            }
            extra_columns: set[str] = set()
            specializing_metric: dict[str, object] | None = None
            if (
                _metric_aliases_specialize(glossary[other_id], glossary[selected_id])
                and other_dimensions > selected_dimensions
            ):
                extra_columns = other_dimensions - selected_dimensions
                specializing_metric = other_metric
            elif (
                _metric_aliases_specialize(glossary[selected_id], glossary[other_id])
                and selected_dimensions > other_dimensions
            ):
                extra_columns = selected_dimensions - other_dimensions
                specializing_metric = selected_metric
            if specializing_metric is None:
                continue
            for key in _metric_dimension_keys(specializing_metric):
                if key[1] not in extra_columns:
                    continue
                identifiers = field_identifiers.get(key, ())
                if len(identifiers) != 1:
                    continue
                identifier = identifiers[0]
                eligible.add(identifier)
                rank = _candidate_metric_rank(specializing_metric)
                dimension_rank[identifier] = min(
                    dimension_rank.get(identifier, rank),
                    rank,
                )
        if not eligible:
            return ()
        eligible_by_selected.append(eligible)

    shared = set.intersection(*eligible_by_selected)
    return tuple(
        sorted(shared, key=lambda item: (dimension_rank[item], item))[
            :_MAX_OMITTED_FILTER_DIMENSION_PROBES
        ]
    )


def _canonical_value_in_question(question: str, value: str) -> bool:
    """Require one literal canonical value with Unicode identifier boundaries."""

    haystack = unicodedata.normalize("NFKC", question).casefold()
    needle = unicodedata.normalize("NFKC", value).casefold().strip()
    if not needle:
        return False
    for match in re.finditer(re.escape(needle), haystack):
        left = haystack[match.start() - 1] if match.start() else ""
        right = haystack[match.end()] if match.end() < len(haystack) else ""
        if not (left and (left.isalnum() or left == "_")) and not (
            right and (right.isalnum() or right == "_")
        ):
            return True
    return False


def _approved_member_matches(
    question: str,
    term: dict[str, object],
) -> tuple[dict[str, object], ...]:
    """질문에 경계가 맞는 승인 member alias를 canonical member로만 반환한다."""

    members = term.get("members")
    if not isinstance(members, list):
        return ()
    matches = []
    for member in members:
        if not isinstance(member, dict):
            continue
        aliases = member.get("aliases")
        if isinstance(aliases, list) and any(
            isinstance(alias, str)
            and _canonical_value_in_question(question, alias)
            for alias in aliases
        ):
            matches.append(member)
    return tuple(matches)


def _selected_metrics_bind_dimension(
    normalized: dict[str, Any],
    candidates: list[dict[str, object]],
    dimension_terms: dict[str, dict[str, object]],
    identifier: str,
) -> bool:
    raw_selected = normalized.get("selected_metric_ids")
    if not isinstance(raw_selected, list) or not raw_selected:
        return False
    selected_metrics = {
        str(metric["id"]): metric
        for metric in candidates
        if isinstance(metric.get("id"), str)
    }
    field = dimension_terms[identifier].get("field")
    field_key = (
        str(field.get("asset_fqn") or ""),
        str(field.get("column") or ""),
    ) if isinstance(field, dict) else ("", "")
    return all(
        isinstance(metric_id, str)
        and metric_id in selected_metrics
        and field_key in _metric_dimension_keys(selected_metrics[metric_id])
        for metric_id in raw_selected
    )


def _constrain_metric_terms_to_dimension(
    business_terms: dict[str, dict[str, object]],
    candidates: list[dict[str, object]],
    dimension_terms: dict[str, dict[str, object]],
    identifier: str,
) -> None:
    """Node1 재해석 후보를 승인 Dimension과 결속 가능한 Metric으로 제한한다.

    Dimension Member가 확정된 요청에서 해당 필드를 지원하지 않는 Metric은 실행 가능한
    해석이 아니다. DataHub Metric-Dimension 관계로 불가능한 후보만 제거하며, 남은
    Metric 중 어떤 측정값을 선택할지는 계속 Node1과 후속 서버 검증이 담당한다.
    """

    field = dimension_terms[identifier].get("field")
    field_key = (
        str(field.get("asset_fqn") or ""),
        str(field.get("column") or ""),
    ) if isinstance(field, dict) else ("", "")
    compatible_ids = {
        str(metric["id"])
        for metric in candidates
        if isinstance(metric.get("id"), str)
        and field_key in _metric_dimension_keys(metric)
    }
    selectable_ids = {
        metric_id
        for metric_id, term in business_terms.items()
        if term.get("kind") == "metric"
    }
    retained_ids = selectable_ids & compatible_ids
    if not retained_ids:
        raise ContextBuildError(
            ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
            "승인 차원 필터와 결속 가능한 지표 후보가 없습니다.",
        )
    for metric_id in selectable_ids - retained_ids:
        del business_terms[metric_id]


def _period_boundary(value: object) -> date:
    """기간 경계를 timezone 유무와 무관하게 달력 날짜로 정규화한다."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text)
    except ValueError:
        return datetime.fromisoformat(text).date()


def _validate_selected_data_availability(
    assets: list[dict[str, object]],
    periods: list[dict[str, Any]],
    partial_context: dict[str, Any],
) -> dict[str, str] | None:
    """선택 자산들의 release-bound 승인 기간 교집합 안에서만 실행을 허용한다.

    이 값은 현재 wall clock이나 물리 테이블의 임의 ``max(date)``가 아니라 sealed
    product capability가 명시한 승인 watermark다. 여러 자산 실행에서는 모든 자산이
    범위를 제공해야 하며, 공통으로 안전한 교집합만 사용한다.
    """

    presence = [
        bool(asset.get("data_available_from"))
        or bool(asset.get("data_available_through"))
        for asset in assets
    ]
    if not any(presence):
        return None
    if not assets or not all(presence):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METADATA,
            "선택된 자산의 데이터 가용 기간 계약이 불완전합니다.",
            partial_context=partial_context,
        )
    if any(not asset.get("product_release_id") for asset in assets):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METADATA,
            "데이터 가용 기간은 product release receipt와 함께 제공되어야 합니다.",
            partial_context=partial_context,
        )
    try:
        available_from = max(
            date.fromisoformat(str(asset["data_available_from"]))
            for asset in assets
        )
        available_through = min(
            date.fromisoformat(str(asset["data_available_through"]))
            for asset in assets
        )
    except (KeyError, ValueError) as error:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METADATA,
            "선택된 자산의 데이터 가용 기간 형식이 유효하지 않습니다.",
            partial_context=partial_context,
        ) from error
    if available_from > available_through:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METADATA,
            "선택된 자산들이 공통 데이터 가용 기간을 공유하지 않습니다.",
            partial_context=partial_context,
        )
    availability = {
        "data_available_from": available_from.isoformat(),
        "data_available_through": available_through.isoformat(),
    }
    partial_context["data_availability"] = dict(availability)
    end_exclusive = available_through + timedelta(days=1)
    if any(
        _period_boundary(period.get("start")) < available_from
        or _period_boundary(period.get("end_exclusive")) > end_exclusive
        for period in periods
    ):
        available_period = {
            "start": available_from.isoformat(),
            "end_exclusive": end_exclusive.isoformat(),
            "source_text": (
                f"{available_from.isoformat()} ~ {available_through.isoformat()}"
            ),
        }
        raise ContextBuildError(
            ContextBuildErrorCode.OUT_OF_DATA_RANGE,
            (
                "요청 기간이 승인된 데이터 가용 범위 밖입니다. "
                f"가용 절대 기간은 {available_from.isoformat()}부터 "
                f"{available_through.isoformat()}까지입니다."
            ),
            (str(available_period["source_text"]),),
            disambiguation_options=_disambiguation_options_for_periods(
                [available_period]
            ),
            partial_context=partial_context,
        )
    return availability


def _apply_conversation_default_operation(
    assets: list[dict[str, object]],
    context: RequestContext,
    analysis_operation: str | None,
    intents: list[str],
    partial_context: dict[str, Any],
) -> tuple[str | None, list[str]]:
    """Apply one release-bound presentation-ready default only in Conversation.

    Direct single-turn analysis keeps Node 1's governed aggregate semantics.
    A Conversation may opt into a richer default Artifact only when every
    selected asset carries the same sealed capability value.  At present the
    only valid default is ``time_trend``; other operations need user-provided
    dimensions, limits, or comparison windows and are rejected by the compiler.
    """

    if context.conversation_id is None or analysis_operation != "aggregate":
        return analysis_operation, intents
    defaults = [asset.get("conversation_default_operation") for asset in assets]
    if not any(defaults):
        return analysis_operation, intents
    if not assets or any(value is None for value in defaults):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METADATA,
            "선택된 자산의 Conversation 기본 Artifact 계약이 불완전합니다.",
            partial_context=partial_context,
        )
    unique = {str(value) for value in defaults}
    if unique != {"time_trend"}:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METADATA,
            "선택된 자산의 Conversation 기본 Artifact 계약이 서로 다릅니다.",
            partial_context=partial_context,
        )
    partial_context["conversation_default_operation"] = "time_trend"
    partial_context["analysis_operation"] = "time_trend"
    partial_context["intent_candidates"] = ["time_trend"]
    return "time_trend", ["time_trend"]


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
    """range 분석의 기간 슬롯이 비었을 때 1회 재검토가 필요한지 판정한다.

    질문 문구를 파싱하지 않고 첫 Node 1 출력과 active release 계약만 사용한다. 선택된
    range Metric뿐 아니라 Metric을 생략한 기간-only 후속 질문도 기간 근거만 한 번 다시
    읽는다. 후자는 재검토 뒤에도 Metric 자체는 missing으로 남으므로 상위 대화 계층이
    직전의 정확한 pending intent를 확인하지 않는 한 실행되지 않는다. snapshot Metric과
    비분석 route는 재호출하지 않는다.
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
    # Metric을 생략한 후속 발화에서는 Node 1의 route도 provisional이다. 상위
    # Conversation command가 typed ANALYSIS action을 결합할 수 있으므로, 빈 기간을
    # provisional Presentation/Report 판정만으로 재검토하지 않는 것은 안전하지 않다.
    # 기간만 한 번 다시 읽고도 Metric은 missing으로 유지되어 여기서 실행 권한은 생기지 않는다.
    if normalized.get("metric_resolution") == "missing":
        return True
    if enum_signal(normalized.get("requested_route"), CONVERSATION_ROUTES) in {
        "PRESENTATION",
        "REPORT_ACTION",
    }:
        return False
    if normalized.get("metric_resolution") != "selected":
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


def _analysis_shape_recheck_violation(normalized: dict[str, Any]) -> str | None:
    """선택된 분석 요청의 결과 형태 위반을 bounded 재검토 코드로 반환한다.

    ``analysis_operation``과 ``intent_candidates``는 같은 결정을 표현하는 active Node 1
    계약의 typed 필드다. 서버는 질문을 다시 파싱하지 않고 첫 응답이 실패한 구조적
    제약만 모델에 알려 한 번의 재검토가 같은 오판을 반복하지 않게 한다.
    """

    if normalized.get("metric_resolution") != "selected":
        return None
    if enum_signal(normalized.get("requested_route"), CONVERSATION_ROUTES) in {
        "PRESENTATION",
        "REPORT_ACTION",
    }:
        return None
    raw_ids = normalized.get("selected_metric_ids")
    if (
        not isinstance(raw_ids, list)
        or not 1 <= len(raw_ids) <= 4
        or len(raw_ids) != len(set(raw_ids))
        or any(not isinstance(item, str) or not item for item in raw_ids)
    ):
        return None
    operation = normalized.get("analysis_operation")
    raw_intents = normalized.get("intent_candidates")
    if not (
        operation in _ANALYSIS_OPERATIONS
        and isinstance(raw_intents, list)
        and raw_intents == [operation]
    ):
        return (
            "ANALYSIS_OPERATION_REQUIRED"
            if operation is None and (raw_intents is None or raw_intents == [])
            else "ANALYSIS_OPERATION_INCONSISTENT"
        )
    if "analysis_time_bucket" not in normalized:
        return "ANALYSIS_OPERATION_INCONSISTENT"
    dimensions = normalized.get("dimension_candidates")
    if not isinstance(dimensions, list):
        return "ANALYSIS_OPERATION_INCONSISTENT"
    result_limit = normalized.get("result_limit")
    bucket = normalized.get("analysis_time_bucket")
    if operation == "aggregate":
        return (
            "ANALYSIS_SHAPE_HAS_UNEXPECTED_SLOT"
            if dimensions or result_limit is not None or bucket is not None
            else None
        )
    if operation == "breakdown":
        if not dimensions:
            return "ANALYSIS_DIMENSION_REQUIRED"
        return (
            "ANALYSIS_SHAPE_HAS_UNEXPECTED_SLOT"
            if result_limit is not None or bucket is not None
            else None
        )
    if operation == "time_trend":
        if bucket not in _ANALYSIS_TIME_BUCKETS:
            return "ANALYSIS_TIME_BUCKET_REQUIRED"
        return (
            "ANALYSIS_SHAPE_HAS_UNEXPECTED_SLOT"
            if result_limit is not None
            else None
        )
    if operation in {"top_n", "bottom_n"}:
        if not dimensions:
            return "ANALYSIS_DIMENSION_REQUIRED"
        if (
            isinstance(result_limit, bool)
            or not isinstance(result_limit, int)
            or not 1 <= result_limit <= 100
        ):
            return "ANALYSIS_RESULT_LIMIT_INVALID"
        return "ANALYSIS_SHAPE_HAS_UNEXPECTED_SLOT" if bucket is not None else None
    return (
        "ANALYSIS_SHAPE_HAS_UNEXPECTED_SLOT"
        if result_limit is not None or bucket is not None
        else None
    )


def _reconcile_analysis_bucket_signal(normalized: dict[str, Any]) -> dict[str, Any]:
    """유효한 시간 버킷과 일반 집계 형태의 충돌만 ``time_trend``로 정규화한다.

    bounded recheck 뒤에도 Node1이 ``aggregate`` 또는 ``breakdown``과 유효한
    ``analysis_time_bucket``을 함께 반환할 수 있다. 버킷은 time trend에서만 허용되는
    더 좁은 typed 신호이므로 이 두 일반 형태에 한해 연산을 맞춘다. 버킷·기간·지표를
    새로 추론하지 않으며 ranking·period comparison 충돌은 계속 fail-closed다.
    """

    operation = normalized.get("analysis_operation")
    bucket = normalized.get("analysis_time_bucket")
    if (
        normalized.get("metric_resolution") == "selected"
        and enum_signal(normalized.get("requested_route"), CONVERSATION_ROUTES)
        not in {"PRESENTATION", "REPORT_ACTION"}
        and operation in {"aggregate", "breakdown"}
        and bucket in _ANALYSIS_TIME_BUCKETS
        and normalized.get("result_limit") is None
    ):
        reconciled = dict(normalized)
        reconciled["analysis_operation"] = "time_trend"
        reconciled["intent_candidates"] = ["time_trend"]
        return reconciled
    return normalized


def _common_source_time_bucket(assets: list[dict[str, object]]) -> str:
    """동일 release asset들의 공통 물리 time grain을 대화 기본 추이에만 사용한다."""

    buckets: set[str] = set()
    for asset in assets:
        metadata = asset.get("time_metadata")
        fields = metadata.get("fields") if isinstance(metadata, dict) else None
        if not isinstance(fields, list) or not fields:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Conversation 기본 추이에 필요한 time metadata가 없습니다.",
            )
        for field in fields:
            target = field.get("field") if isinstance(field, dict) else None
            if (
                isinstance(target, dict)
                and target.get("asset_fqn") != asset.get("fqn")
            ):
                continue
            bucket = field.get("bucket") if isinstance(field, dict) else None
            if bucket not in _ANALYSIS_TIME_BUCKETS:
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METADATA,
                    "Conversation 기본 추이의 source time bucket이 유효하지 않습니다.",
                )
            buckets.add(str(bucket))
    if len(buckets) != 1:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METADATA,
            "Conversation 기본 추이의 source time bucket이 서로 다릅니다.",
        )
    return next(iter(buckets))


def _finalize_metric_scope(
    assets: list[dict[str, object]],
    metric_terms: dict[str, dict[str, object]],
    executable_by_id: dict[str, dict[str, object]],
    selected_metric_ids: list[str] | tuple[str, ...],
    *,
    is_period_comparison: bool,
) -> tuple[list[dict[str, object]], set[str], str]:
    """두 해석 경로가 같은 ratio 확장·asset 선택·time mode 계약을 만들게 한다."""

    keep_ids = set(selected_metric_ids)
    synthetic: list[dict[str, object]] = []
    has_comparison_ratio = False
    for metric_id in selected_metric_ids:
        ratio = _ratio_reference(metric_terms, executable_by_id, metric_id)
        if ratio is None:
            continue
        if is_period_comparison:
            _validate_ratio_comparison_operands(ratio, executable_by_id)
            has_comparison_ratio = True
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
    if has_comparison_ratio:
        selected_asset_fqns = {
            str(asset.get("fqn") or "")
            for asset in selected_assets
        }
        if len(selected_asset_fqns) != 1 or "" in selected_asset_fqns:
            raise ContextBuildError(
                ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                "Ratio 기간 비교는 단일 승인 asset 실행 범위만 지원합니다.",
            )
        try:
            comparison_parameters = comparison_time_parameter_names(selected_assets)
        except ContextBuildError as error:
            raise ContextBuildError(
                ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                "Ratio 기간 비교의 공통 시간 계약이 유효하지 않습니다.",
            ) from error
        if comparison_parameters is None:
            raise ContextBuildError(
                ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                "Ratio 기간 비교에는 승인된 comparison window가 필요합니다.",
            )
    return selected_assets, keep_ids, time_selection_mode(selected_assets)


def _validate_ratio_comparison_operands(
    ratio: dict[str, str],
    executable_by_id: dict[str, dict[str, object]],
) -> None:
    """Ratio 비교를 동일 asset·time field·filter 의미의 두 operand로 제한한다."""

    numerator = executable_by_id.get(ratio["numerator_metric_id"])
    denominator = executable_by_id.get(ratio["denominator_metric_id"])
    if numerator is None or denominator is None:
        raise ContextBuildError(
            ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
            "Ratio 기간 비교 operand가 현재 실행 registry에 없습니다.",
        )
    numerator_scope = _ratio_operand_scope(numerator)
    denominator_scope = _ratio_operand_scope(denominator)
    if numerator_scope != denominator_scope:
        raise ContextBuildError(
            ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
            "Ratio 기간 비교의 분자·분모는 동일 asset·시간·필터 계약이어야 합니다.",
        )


def _ratio_operand_scope(
    metric: dict[str, object],
) -> tuple[str, str, tuple[str, ...]]:
    asset_fqn = metric.get("asset_fqn")
    time_field = metric.get("time_field")
    raw_filters = metric.get("required_filters")
    if (
        not isinstance(asset_fqn, str)
        or not asset_fqn
        or not isinstance(time_field, str)
        or not time_field
        or not isinstance(raw_filters, (list, tuple))
        or any(not isinstance(item, dict) for item in raw_filters)
    ):
        raise ContextBuildError(
            ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
            "Ratio 기간 비교 operand의 실행 scope가 불완전합니다.",
        )
    try:
        filters = tuple(
            sorted(
                json.dumps(
                    item,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                for item in raw_filters
            )
        )
    except (TypeError, ValueError) as error:
        raise ContextBuildError(
            ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
            "Ratio 기간 비교 operand의 필터 계약이 유효하지 않습니다.",
        ) from error
    return asset_fqn, time_field, filters


def _structured_request(
    *,
    intents: list[str],
    keep_ids: set[str],
    selected_metric_ids: list[str] | tuple[str, ...],
    selected_dimensions: list[str],
    dimension_terms: dict[str, dict[str, object]],
    filter_fields: list[dict[str, object]],
    periods: list[dict[str, Any]],
    relationship: str,
    analysis_time_mode: str,
    analysis_operation: str | None,
    analysis_time_bucket: str | None,
    result_limit: int | None,
    metric_terms: dict[str, dict[str, object]],
    model_signals: dict[str, object] | None = None,
) -> dict[str, object]:
    """fast-path와 Node 1 경로의 최종 typed request를 한 조립 지점에서 생성한다."""

    output_ids = list(selected_metric_ids)
    selected = output_ids[0] if len(output_ids) == 1 else None
    result: dict[str, object] = {
        "intent_candidates": intents,
        "metric_ids": sorted(keep_ids),
        "dimension_candidates": selected_dimensions,
        "dimension_fields": [
            dimension_terms[item]["field"] for item in selected_dimensions
        ],
        "filter_fields": filter_fields,
        "dimension_member_receipts": dimension_member_receipts(
            filter_fields,
            dimension_terms,
        ),
        "period_candidates": periods,
        "period_relationship": relationship,
        "time_mode": analysis_time_mode,
        "selected_metric_id": selected,
        "selected_metric_ids": output_ids,
        "analysis_operation": analysis_operation,
        "analysis_time_bucket": (
            analysis_time_bucket if analysis_operation == "time_trend" else "none"
        ),
        "result_limit": result_limit,
        # Ratio operand는 독립 BUSINESS Metric일 수 있다. 출력 Metric만 남기면 실행
        # asset의 BUSINESS 범위와 Glossary 범위가 달라져 Context Gate가 닫히므로,
        # 실제 실행 scope에 포함된 BUSINESS Term을 모두 증거로 보존한다.
        "metric_terms": {
            metric_id: metric_terms[metric_id]
            for metric_id in sorted(keep_ids)
            if metric_id in metric_terms
        },
    }
    if model_signals is not None:
        result.update(model_signals)
    if selected is not None:
        result["metric_term"] = metric_terms[selected]
    return result


async def _complete_business_metric_terms(
    adapter: DataPlatformAdapter,
    metric_terms: dict[str, dict[str, object]],
    executable_by_id: dict[str, dict[str, object]],
    keep_ids: set[str],
    context: RequestContext,
) -> dict[str, dict[str, object]]:
    """실행 scope에 남은 독립 BUSINESS operand의 권위 있는 Term을 보완한다."""

    business_ids = {
        metric_id
        for metric_id in keep_ids
        if executable_by_id[metric_id].get("visibility", "BUSINESS") == "BUSINESS"
    }
    missing = tuple(sorted(business_ids - set(metric_terms)))
    if not missing:
        return metric_terms
    try:
        additional = await adapter.get_metric_terms(
            missing,
            context.model_dump(mode="json"),
        )
    except MetadataUnavailableError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise MetadataUnavailableError(
            "DataHub Metric Glossary 실행 dependency 조회에 실패했습니다."
        ) from error
    if set(additional) != set(missing) or any(
        not isinstance(additional.get(metric_id), dict) for metric_id in missing
    ):
        raise MetadataUnavailableError(
            "DataHub Metric Glossary에 BUSINESS 실행 dependency가 누락되었습니다."
        )
    return {**metric_terms, **additional}


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
            tuple[str, str, str], tuple[float, tuple[str, ...]]
        ] = {}
        self._dimension_value_inflight: dict[
            tuple[str, str, str], asyncio.Task[tuple[str, ...]]
        ] = {}

    async def _load_dimension_values(
        self,
        key: tuple[str, str, str],
        asset_fqn: str,
        column: str,
    ) -> tuple[str, ...]:
        """Load and cache one release-bound value domain for all concurrent waiters."""

        try:
            values = await discover_dimension_values(self._adapter, asset_fqn, column)
            now = monotonic()
            if len(self._dimension_value_cache) >= 256:
                expired = [
                    item
                    for item, entry in self._dimension_value_cache.items()
                    if now >= entry[0]
                ]
                for item in expired:
                    self._dimension_value_cache.pop(item, None)
                if len(self._dimension_value_cache) >= 256:
                    self._dimension_value_cache.pop(
                        next(iter(self._dimension_value_cache))
                    )
            self._dimension_value_cache[key] = (
                now + self._dimension_value_cache_ttl,
                values,
            )
            return values
        finally:
            current = asyncio.current_task()
            if self._dimension_value_inflight.get(key) is current:
                self._dimension_value_inflight.pop(key, None)

    async def _dimension_values(
        self,
        cache_namespace: str | None,
        asset_fqn: str,
        column: str,
    ) -> tuple[str, ...]:
        """Return one bounded live domain cached only inside an exact release."""

        if not cache_namespace:
            return await discover_dimension_values(self._adapter, asset_fqn, column)
        key = (cache_namespace, asset_fqn, column)
        now = monotonic()
        cached = self._dimension_value_cache.get(key)
        if cached is not None and now < cached[0]:
            return cached[1]
        task = self._dimension_value_inflight.get(key)
        if task is None:
            task = asyncio.create_task(
                self._load_dimension_values(key, asset_fqn, column)
            )
            self._dimension_value_inflight[key] = task
        return await asyncio.shield(task)

    async def _recheck_omitted_filter(
        self,
        *,
        normalized: dict[str, Any],
        question: str,
        candidates: list[dict[str, object]],
        glossary: dict[str, tuple[str, ...]],
        dimension_terms: dict[str, dict[str, object]],
        business_terms: dict[str, dict[str, object]],
        cache_namespace: str | None,
        normalize: Any,
    ) -> dict[str, Any]:
        """Recheck one explicit governed value that Node 1 omitted.

        Only extra dimensions shared by the selected metric families are probed.
        The model remains responsible for semantic selection; the server only
        supplies a complete bounded value domain and verifies the second output.
        """

        dimension_ids = _metric_family_dimension_ids(
            normalized,
            candidates,
            glossary,
            dimension_terms,
            omitted_only=True,
        )
        if not dimension_ids:
            return normalized

        matches: list[tuple[str, str, tuple[str, ...]]] = []
        for identifier in dimension_ids:
            term = dimension_terms[identifier]
            field = term.get("field")
            if not isinstance(field, dict):
                continue
            governed_matches = _approved_member_matches(question, term)
            members = term.get("members")
            if isinstance(members, list) and members:
                if len(governed_matches) > 1:
                    raise ContextBuildError(
                        ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                        "질문에 명시된 승인 차원값이 둘 이상이라 단일 필터로 확정할 수 없습니다.",
                    )
                if governed_matches:
                    canonical = str(governed_matches[0]["canonical_value"])
                    matches.append((identifier, canonical, (canonical,)))
                # 승인 member가 완전한 controlled domain이면 live DISTINCT로 우회하지 않는다.
                continue
            try:
                values = await self._dimension_values(
                    cache_namespace,
                    str(field["asset_fqn"]),
                    str(field["column"]),
                )
            except (KeyError, OSError, TypeError, ValueError):
                values = ()
            for value in values:
                if _canonical_value_in_question(question, value):
                    matches.append((identifier, value, values))

        if not matches:
            return normalized
        if len(matches) != 1:
            raise ContextBuildError(
                ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                "질문에 명시된 승인 차원값을 단일 필터로 확정하지 못했습니다.",
            )

        identifier, canonical_value, values = matches[0]
        business_terms[identifier]["value_candidates"] = list(values)
        _constrain_metric_terms_to_dimension(
            business_terms,
            candidates,
            dimension_terms,
            identifier,
        )
        rechecked = await normalize()
        if not isinstance(rechecked, dict):
            raise ValueError("Node1 필터 재해석 응답은 객체여야 합니다.")

        raw_filters = rechecked.get("filter_candidates")
        expected_value = unicodedata.normalize(
            "NFKC", canonical_value
        ).casefold()
        filter_is_bound = (
            isinstance(raw_filters, list)
            and len(raw_filters) == 1
            and isinstance(raw_filters[0], dict)
            and raw_filters[0].get("dimension_id") == identifier
            and isinstance(raw_filters[0].get("value_text"), str)
            and unicodedata.normalize(
                "NFKC", str(raw_filters[0]["value_text"])
            ).casefold().strip()
            == expected_value
            and isinstance(raw_filters[0].get("exclude"), bool)
        )
        metrics_are_bound = _selected_metrics_bind_dimension(
            rechecked,
            candidates,
            dimension_terms,
            identifier,
        )
        if not filter_is_bound or not metrics_are_bound:
            raise ContextBuildError(
                ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                "질문에 명시된 승인 필터를 선택 지표와 결속하지 못했습니다.",
            )
        return rechecked

    async def resolve(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
        *,
        candidate_set: AssetCandidateSet | None = None,
        budget: Any = None,
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
        if not candidate_ids and not support_terms:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "런타임 메타데이터에서 거버넌스 지표를 찾을 수 없습니다.",
            )
        metric_terms: dict[str, dict[str, object]] = {}
        if candidate_ids:
            try:
                metric_terms = await self._adapter.get_metric_terms(
                    tuple(candidate_ids),
                    context.model_dump(mode="json"),
                )
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
        for identifier, term in dimension_terms.items():
            matches = _approved_member_matches(payload.question, term)
            if len(matches) > 1:
                raise ContextBuildError(
                    ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                    "질문에 같은 차원의 승인 값이 둘 이상 포함되어 단일 필터로 확정할 수 없습니다.",
                )
            if matches:
                business_terms[identifier]["value_candidates"] = [
                    str(matches[0]["canonical_value"])
                ]
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
                selected_assets, pre_keep_ids, analysis_time_mode = (
                    _finalize_metric_scope(
                        assets,
                        metric_terms,
                        executable_by_id,
                        resolved_metric_ids,
                        is_period_comparison=(
                            payload.resolved_slots.analysis_operation
                            == "period_comparison"
                        ),
                    )
                )

                # 검색 후보는 Node 1용 bounded hint라서 선택 Metric의 차원만 남길 수
                # 있다. 상속된 filter-only side를 그 후보 안에서 검증하면 승인된 필터도
                # 조용히 사라진다. exact field reference를 동일 release receipt에 먼저
                # 재결속해 권한·JOIN·live schema가 확인된 실행 subgraph에서 재검증한다.
                if payload.resolved_slots.user_filters and candidate_set is not None:
                    try:
                        filter_references = tuple(
                            sorted(
                                {
                                    GovernedFieldReference(
                                        asset_fqn=str(item.get("asset_fqn", "")),
                                        column=str(item.get("column", "")),
                                    )
                                    for item in payload.resolved_slots.user_filters
                                    if isinstance(item, dict)
                                }
                            )
                        )
                        if not filter_references:
                            raise ValueError("filter field reference is empty")
                        pre_selection = ExecutionAssetSelection(
                            output_metric_ids=tuple(resolved_metric_ids),
                            execution_metric_ids=tuple(sorted(pre_keep_ids)),
                            field_references=filter_references,
                            receipt_context_release=candidate_set.context_release,
                            receipt_catalog_checksum=candidate_set.catalog_checksum,
                            receipt_canonical_checksum=candidate_set.canonical_checksum,
                            receipt_product_release_id=candidate_set.product_release_id,
                            receipt_runtime_projection_checksum=(
                                candidate_set.runtime_projection_checksum
                            ),
                        )
                    except ValueError as error:
                        raise ContextBuildError(
                            ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                            "상속 필터의 asset·column 계약이 유효하지 않습니다.",
                        ) from error
                    assets = await self._adapter.resolve_execution_assets(
                        pre_selection,
                        {
                            **context.model_dump(mode="json"),
                            "parameters": payload.parameters,
                        },
                    )
                    expanded_metrics = [
                        metric
                        for asset in assets
                        for metric in asset.get("metrics", ())
                        if isinstance(metric, dict)
                        and isinstance(metric.get("id"), str)
                    ]
                    expanded_ids = [str(metric["id"]) for metric in expanded_metrics]
                    if len(expanded_ids) != len(set(expanded_ids)):
                        raise ContextBuildError(
                            ContextBuildErrorCode.DUPLICATE_METRIC,
                            "실행 subgraph에 중복된 지표 식별자가 존재합니다.",
                        )
                    executable_by_id = {
                        str(metric["id"]): metric for metric in expanded_metrics
                    }
                    selected_assets, expanded_keep_ids, analysis_time_mode = (
                        _finalize_metric_scope(
                            assets,
                            metric_terms,
                            executable_by_id,
                            resolved_metric_ids,
                            is_period_comparison=(
                                payload.resolved_slots.analysis_operation
                                == "period_comparison"
                            ),
                        )
                    )
                    if expanded_keep_ids != pre_keep_ids:
                        raise ContextBuildError(
                            ContextBuildErrorCode.INVALID_METRIC,
                            "실행 subgraph의 Metric dependency가 후보 receipt와 다릅니다.",
                        )
                    dimension_terms = _resolve_dimension_terms(assets)

                pre_dims = list(payload.resolved_slots.dimension_ids)
                allowed_dimensions = set(dimension_terms)
                col_to_dim = {
                    str(term.get("field", {}).get("column")): identifier
                    for identifier, term in dimension_terms.items()
                    if isinstance(term.get("field"), dict)
                    and term.get("field", {}).get("column")
                }
                validated_dims = []
                for dimension_id in pre_dims:
                    if dimension_id in allowed_dimensions:
                        validated_dims.append(dimension_id)
                    elif (
                        dimension_id in col_to_dim
                        and col_to_dim[dimension_id] in allowed_dimensions
                    ):
                        validated_dims.append(col_to_dim[dimension_id])
                if len(validated_dims) != len(pre_dims):
                    raise ContextBuildError(
                        ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                        "상속 차원이 현재 승인된 실행 subgraph와 일치하지 않습니다.",
                    )
                try:
                    pre_filters = validated_pre_filters(
                        payload.resolved_slots.user_filters,
                        dimension_terms,
                        allowed_dimensions,
                    )
                except ValueError as error:
                    raise ContextBuildError(
                        ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                        "상속 필터가 현재 승인된 실행 subgraph와 일치하지 않습니다.",
                    ) from error

                metric_terms = await _complete_business_metric_terms(
                    self._adapter,
                    metric_terms,
                    executable_by_id,
                    pre_keep_ids,
                    context,
                )

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

                preflight_context: dict[str, Any] = {
                    "metric_ids": list(resolved_metric_ids),
                    "selected_metric_ids": list(resolved_metric_ids),
                    "analysis_operation": payload.resolved_slots.analysis_operation,
                    "dimension_candidates": validated_dims,
                    "filter_fields": pre_filters,
                    "period_candidates": periods,
                    "period_relationship": (
                        "comparison" if len(periods) == 2 else "single"
                    ),
                }
                pre_operation, pre_intents = _apply_conversation_default_operation(
                    selected_assets,
                    context,
                    payload.resolved_slots.analysis_operation,
                    [payload.resolved_slots.analysis_operation or "general"],
                    preflight_context,
                )
                availability = _validate_selected_data_availability(
                    selected_assets,
                    periods,
                    preflight_context,
                )
                pre_time_bucket = (
                    payload.resolved_slots.analysis_time_bucket
                    if pre_operation == "time_trend"
                    else None
                )
                if pre_operation == "time_trend" and pre_time_bucket is None:
                    pre_time_bucket = _common_source_time_bucket(selected_assets)
                structured_request = _structured_request(
                    intents=pre_intents,
                    keep_ids=pre_keep_ids,
                    selected_metric_ids=resolved_metric_ids,
                    selected_dimensions=validated_dims,
                    dimension_terms=dimension_terms,
                    filter_fields=pre_filters,
                    periods=periods,
                    relationship="comparison" if len(periods) == 2 else "single",
                    analysis_time_mode=analysis_time_mode,
                    analysis_operation=pre_operation,
                    analysis_time_bucket=pre_time_bucket,
                    result_limit=payload.resolved_slots.result_limit,
                    metric_terms=metric_terms,
                )
                if availability is not None:
                    structured_request["data_availability"] = availability
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
        if candidate_set is not None:
            node1_input["interpretation_context"] = (
                build_node1_interpretation_context(
                    candidate_set,
                    context,
                    metric_terms,
                    dimension_terms,
                )
            )
        # 직전 턴 기간은 대화 앵커다. 이 값을 넘기지 않으면 "그 전 달"처럼 앵커가 이전
        # 기간인 표현을 Node1이 as_of 기준으로 잘못 해석하고, 서버가 문장을 다시 파싱해
        # 보정해야 한다. 앵커를 권위 시간 컨텍스트로 함께 전달해 해석을 한 곳에 모은다.
        previous_period = previous_period_anchor(payload.resolved_slots, timezone)
        if previous_period is not None:
            node1_input["previous_period"] = previous_period
        prior_shape = previous_result_shape(payload.resolved_slots)
        if prior_shape is not None:
            node1_input["previous_result_shape"] = prior_shape

        async def normalize() -> dict[str, Any]:
            if budget is not None:
                consume_budget = getattr(budget, "consume", None)
                if not callable(consume_budget):
                    raise TypeError("model call budget is invalid")
                consume_budget()
            return await normalizer(node1_input)

        cache_namespace = (
            ":".join(
                (
                    candidate_set.product_release_id,
                    candidate_set.runtime_projection_checksum,
                    candidate_set.canonical_checksum,
                )
            )
            if candidate_set is not None
            and candidate_set.product_release_id is not None
            and candidate_set.runtime_projection_checksum is not None
            else None
        )
        normalized = await normalize()
        if not isinstance(normalized, dict):
            raise ValueError("Node1 응답은 객체여야 합니다.")

        # Only an ANALYSIS interpretation that actually detected a named filter
        # may trigger a live suggestion query. This prevents report/presentation
        # turns and ordinary metric questions from touching Trino. When a bounded
        # domain is available, one constrained re-interpretation may select its
        # exact canonical value; the server still verifies that value afterward.
        requested_route = enum_signal(
            normalized.get("requested_route"), CONVERSATION_ROUTES
        )
        can_discover_values = callable(
            getattr(self._adapter, "execute_query", None)
        ) and callable(getattr(self._adapter, "get_query_status", None))
        if (
            can_discover_values
            and requested_route not in {"PRESENTATION", "REPORT_ACTION"}
        ):
            normalized = await self._recheck_omitted_filter(
                normalized=normalized,
                question=payload.question,
                candidates=candidates,
                glossary=glossary,
                dimension_terms=dimension_terms,
                business_terms=business_terms,
                cache_namespace=cache_namespace,
                normalize=normalize,
            )
        detected_filters = normalized.get("filter_candidates")
        relevant_dimensions = {
            str(candidate.get("dimension_id"))
            for candidate in detected_filters
            if isinstance(candidate, dict)
            and candidate.get("dimension_id") in allowed_dimensions
            and isinstance(candidate.get("value_text"), str)
            and str(candidate["value_text"]).strip()
        } if isinstance(detected_filters, (list, tuple)) else set()
        family_dimensions = set(
            _metric_family_dimension_ids(
                normalized,
                candidates,
                glossary,
                dimension_terms,
            )
        )
        required_family_values: dict[str, str] = {}
        should_reinterpret = False
        if can_discover_values and requested_route not in {"PRESENTATION", "REPORT_ACTION"}:
            for identifier in sorted(relevant_dimensions):
                term = dimension_terms[identifier]
                field = term.get("field")
                if not isinstance(field, dict):
                    continue
                members = term.get("members")
                governed_matches = _approved_member_matches(payload.question, term)
                if isinstance(members, list) and members:
                    values = tuple(
                        str(member["canonical_value"])
                        for member in members
                        if isinstance(member, dict)
                    )
                else:
                    try:
                        values = await self._dimension_values(
                            cache_namespace,
                            str(field["asset_fqn"]),
                            str(field["column"]),
                        )
                    except (KeyError, OSError, TypeError, ValueError):
                        values = ()
                if not values:
                    continue
                business_terms[identifier]["value_candidates"] = list(values)
                raw_values = {
                    unicodedata.normalize(
                        "NFKC", str(candidate["value_text"])
                    ).casefold().strip()
                    for candidate in detected_filters
                    if isinstance(candidate, dict)
                    and candidate.get("dimension_id") == identifier
                }
                canonical_values = {
                    unicodedata.normalize("NFKC", value).casefold(): value
                    for value in values
                }
                explicit_values = (
                    [str(member["canonical_value"]) for member in governed_matches]
                    if isinstance(members, list) and members
                    else [
                        value
                        for value in values
                        if _canonical_value_in_question(payload.question, value)
                    ]
                ) if identifier in family_dimensions else []
                if len(explicit_values) > 1:
                    raise ContextBuildError(
                        ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                        "질문에 명시된 승인 차원값을 단일 필터로 확정하지 못했습니다.",
                    )
                if explicit_values:
                    required_family_values[identifier] = explicit_values[0]
                if (
                    not raw_values.issubset(canonical_values)
                    or (
                        identifier in required_family_values
                        and not _selected_metrics_bind_dimension(
                            normalized,
                            candidates,
                            dimension_terms,
                            identifier,
                        )
                    )
                ):
                    if identifier in required_family_values:
                        _constrain_metric_terms_to_dimension(
                            business_terms,
                            candidates,
                            dimension_terms,
                            identifier,
                        )
                    should_reinterpret = True
        if should_reinterpret:
            normalized = await normalize()
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
                "violation": "PERIOD_REQUIRED_OR_OUT_OF_RANGE",
            }
            normalized = await normalize()
            if not isinstance(normalized, dict):
                raise ValueError("Node1 기간 재검토 응답은 객체여야 합니다.")
            interpretation_rechecked = True
        normalized = _reconcile_explicit_calendar_bucket(
            normalized,
            payload.question,
        )
        shape_violation = (
            None
            if interpretation_rechecked
            else _analysis_shape_recheck_violation(normalized)
        )
        if shape_violation is not None:
            node1_input["interpretation_recheck"] = {
                "target": "analysis_operation",
                "attempt": 1,
                "violation": shape_violation,
            }
            normalized = await normalize()
            if not isinstance(normalized, dict):
                raise ValueError("Node1 결과 형태 재검토 응답은 객체여야 합니다.")
        normalized = _reconcile_explicit_calendar_bucket(
            normalized,
            payload.question,
        )
        normalized = _reconcile_analysis_bucket_signal(normalized)
        normalized = _reconcile_filter_only_dimensions(normalized)
        final_filters = normalized.get("filter_candidates")
        for identifier, expected in required_family_values.items():
            matching_filters = [
                candidate
                for candidate in final_filters
                if isinstance(candidate, dict)
                and candidate.get("dimension_id") == identifier
                and isinstance(candidate.get("value_text"), str)
                and unicodedata.normalize(
                    "NFKC", str(candidate["value_text"])
                ).casefold().strip()
                == unicodedata.normalize("NFKC", expected).casefold()
                and isinstance(candidate.get("exclude"), bool)
            ] if isinstance(final_filters, list) else []
            if (
                len(matching_filters) != 1
                or not _selected_metrics_bind_dimension(
                    normalized,
                    candidates,
                    dimension_terms,
                    identifier,
                )
            ):
                raise ContextBuildError(
                    ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
                    "질문에 명시된 승인 필터를 선택 지표와 결속하지 못했습니다.",
                )
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
        unresolved_metric_without_intent = (
            normalized.get("metric_resolution") in {"missing", "unsupported"}
            and not intents
        )
        if (
            len(intents) != 1
            and not shape_elided_followup
            and not unresolved_metric_without_intent
        ):
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
        if "analysis_time_bucket" not in normalized:
            raise ValueError("Node1 analysis_time_bucket 필드가 필요합니다.")
        analysis_time_bucket = normalized.get("analysis_time_bucket")
        result_limit = normalized.get("result_limit")
        if analysis_operation is not None and analysis_operation not in _ANALYSIS_OPERATIONS:
            raise ValueError("Node1 analysis_operation 값이 유효하지 않습니다.")
        if shape_elided_followup:
            if analysis_operation is not None or analysis_time_bucket is not None:
                raise ValueError(
                    "Node1 결과 형태 생략 후속 질문은 분석 연산·시간 버킷을 지정할 수 없습니다."
                )
        elif analysis_operation is not None and intents != [analysis_operation]:
            raise ValueError("Node1 분석 연산과 의도가 일치하지 않습니다.")
        if analysis_time_bucket is not None and analysis_time_bucket not in _ANALYSIS_TIME_BUCKETS:
            raise ValueError("Node1 analysis_time_bucket 값이 유효하지 않습니다.")
        if (analysis_operation == "time_trend") != (
            analysis_time_bucket is not None
        ):
            raise ValueError(
                "Node1 time_trend와 analysis_time_bucket이 일치하지 않습니다."
            )
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
            "analysis_time_bucket": analysis_time_bucket,
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
            if (
                analysis_operation in {"breakdown", "top_n", "bottom_n"}
                and not selected_dimensions
            ):
                raise ContextBuildError(
                    ContextBuildErrorCode.ANALYSIS_SHAPE_REQUIRED,
                    (
                        "분석 결과 형태를 확정하지 못했습니다. 전체 값, 기간별 추이, "
                        "승인된 분류 기준별 값 또는 순위 중 원하는 형태를 질문에 "
                        "명확히 포함해 주세요."
                    ),
                    partial_context=partial_context,
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
        selected_assets, keep_ids, analysis_time_mode = _finalize_metric_scope(
            assets,
            metric_terms,
            executable_by_id,
            selected_metric_ids,
            is_period_comparison=is_comparison,
        )
        metric_terms = await _complete_business_metric_terms(
            self._adapter,
            metric_terms,
            executable_by_id,
            keep_ids,
            context,
        )
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
        analysis_operation, intents = _apply_conversation_default_operation(
            selected_assets,
            context,
            analysis_operation,
            intents,
            partial_context,
        )
        if analysis_operation == "time_trend" and analysis_time_bucket is None:
            analysis_time_bucket = _common_source_time_bucket(selected_assets)
            partial_context["analysis_time_bucket"] = analysis_time_bucket
        availability = _validate_selected_data_availability(
            selected_assets,
            periods,
            partial_context,
        )
        structured_request = _structured_request(
            intents=intents,
            keep_ids=keep_ids,
            selected_metric_ids=selected_metric_ids,
            selected_dimensions=selected_dimensions,
            dimension_terms=dimension_terms,
            filter_fields=filter_fields,
            periods=periods,
            relationship=relationship,
            analysis_time_mode=analysis_time_mode,
            analysis_operation=analysis_operation,
            analysis_time_bucket=analysis_time_bucket,
            result_limit=result_limit,
            metric_terms=metric_terms,
            model_signals={
                # Node1의 route/표현/생략문 신호는 후보다. 계약 enum 안의 값만 통과시키고
                # 라우트 확정과 전제조건 검증은 ConversationSlotResolver가 한다.
                "requested_route": enum_signal(
                    normalized.get("requested_route"), CONVERSATION_ROUTES
                ),
                "presentation_type": enum_signal(
                    normalized.get("presentation_type"), PRESENTATION_TYPES
                ),
                "is_elliptical": normalized.get("is_elliptical"),
                "measurement_source_text": measurement_source_text,
                "measurement_source_texts": measurement_source_texts,
            },
        )
        if availability is not None:
            structured_request["data_availability"] = availability
        question = normalized.get("normalized_question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Node1 normalized_question 은 필수입니다.")
        return selected_assets, question, structured_request
