"""Measure 위치·JOIN 방향·grain 증거로 팬아웃 안전 물리 계획을 결정한다.

이 정책은 SQL 생성기를 아직 전환하지 않는다. 현재 계약으로 입증할 수 없는 조합을
명시적으로 ``REJECT``하여, 후속 AnalysisPlan이 문장 패턴이나 LLM 추정으로 안전성을
열지 못하게 하는 결정표다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from app.services.context.contract import GovernedJoin

if TYPE_CHECKING:
    from app.services.context.semantic_release import CanonicalAsset


class RelatedSideUse(str, Enum):
    """주 Measure 반대편 JOIN 자산을 분석에서 사용하는 방식이다."""

    FILTER_ONLY = "FILTER_ONLY"
    DIMENSION_BREAKDOWN = "DIMENSION_BREAKDOWN"
    SECOND_MEASURE = "SECOND_MEASURE"


class FanoutPlan(str, Enum):
    """Planner가 생성하고 SQL Guard가 검증할 팬아웃 처리 방식이다."""

    DIRECT_JOIN = "DIRECT_JOIN"
    PREAGGREGATE = "PREAGGREGATE"
    SEMI_JOIN = "SEMI_JOIN"
    REJECT = "REJECT"


class FanoutReason(str, Enum):
    """계획 선택 또는 차단의 결정론적 근거다."""

    ONE_TO_ONE = "ONE_TO_ONE"
    UNIQUE_ONE_SIDE = "UNIQUE_ONE_SIDE"
    FILTER_ONLY_MANY_SIDE = "FILTER_ONLY_MANY_SIDE"
    DECLARED_PREAGGREGATION = "DECLARED_PREAGGREGATION"
    MULTI_FACT_COMMON_GRAIN = "MULTI_FACT_COMMON_GRAIN"
    UNIQUENESS_UNPROVEN = "UNIQUENESS_UNPROVEN"
    COMMON_GRAIN_REQUIRED = "COMMON_GRAIN_REQUIRED"
    ALLOCATION_REQUIRED = "ALLOCATION_REQUIRED"
    MANY_TO_MANY_UNSUPPORTED = "MANY_TO_MANY_UNSUPPORTED"


@dataclass(frozen=True)
class AssetGrainEvidence:
    """한 asset에서 검증된 전체 field와 고유성을 보장하는 key 집합이다."""

    asset_fqn: str
    available_fields: frozenset[str]
    unique_key_sets: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class GrainSafetyEvidence:
    """JOIN 계획 판정에 필요한 metadata 증거이며 사용자 문장이나 모델 추정을 포함하지 않는다."""

    measure_assets: frozenset[str]
    related_side_use: RelatedSideUse
    assets: tuple[AssetGrainEvidence, ...]
    common_grain_bindings: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FanoutDecision:
    """한 governed edge에 대한 안전 계획과 이유를 함께 반환한다."""

    join_id: str
    plan: FanoutPlan
    reason: FanoutReason


def decide_fanout_plan(
    join: GovernedJoin,
    evidence: GrainSafetyEvidence,
) -> FanoutDecision:
    """카디널리티 방향과 명시적 grain 증거만으로 JOIN 물리 계획을 선택한다."""

    endpoints = frozenset({join.left, join.right})
    assets = _validate_evidence(join, evidence)

    if join.cardinality == "many_to_many":
        # 현재 GovernedJoin에는 bridge grain·allocation expression 계약이 없다. 단순히
        # allocation_rule_id 문자열 하나만으로 열면 검증할 수 없으므로 기본 거부한다.
        return _decision(join, FanoutPlan.REJECT, FanoutReason.MANY_TO_MANY_UNSUPPORTED)

    if join.cardinality == "one_to_one":
        if not all(
            _join_key_is_unique(join, asset_fqn, assets)
            for asset_fqn in endpoints
        ):
            return _decision(
                join,
                FanoutPlan.REJECT,
                FanoutReason.UNIQUENESS_UNPROVEN,
            )
        if join.preaggregation_required:
            return _decision(
                join,
                FanoutPlan.PREAGGREGATE,
                FanoutReason.DECLARED_PREAGGREGATION,
            )
        return _decision(join, FanoutPlan.DIRECT_JOIN, FanoutReason.ONE_TO_ONE)

    many_asset, one_asset = _oriented_assets(join)
    if not _join_key_is_unique(join, one_asset, assets):
        return _decision(join, FanoutPlan.REJECT, FanoutReason.UNIQUENESS_UNPROVEN)

    if evidence.measure_assets == endpoints:
        if _common_grain_covers_join(join, evidence.common_grain_bindings):
            return _decision(
                join,
                FanoutPlan.PREAGGREGATE,
                FanoutReason.MULTI_FACT_COMMON_GRAIN,
            )
        return _decision(join, FanoutPlan.REJECT, FanoutReason.COMMON_GRAIN_REQUIRED)

    measure_asset = next(iter(evidence.measure_assets))
    if (
        measure_asset == one_asset
        and evidence.related_side_use == RelatedSideUse.FILTER_ONLY
    ):
        return _decision(
            join,
            FanoutPlan.SEMI_JOIN,
            FanoutReason.FILTER_ONLY_MANY_SIDE,
        )

    if (
        measure_asset == one_asset
        and evidence.related_side_use == RelatedSideUse.DIMENSION_BREAKDOWN
    ):
        # 현재 release에는 검증 가능한 allocation expression·basis 계약이 없다.
        # 문자열 ID나 모델 신호만으로 분배를 허용하지 않고 계약 확장 전까지 닫는다.
        return _decision(join, FanoutPlan.REJECT, FanoutReason.ALLOCATION_REQUIRED)

    if join.preaggregation_required:
        return _decision(
            join,
            FanoutPlan.PREAGGREGATE,
            FanoutReason.DECLARED_PREAGGREGATION,
        )

    if measure_asset == many_asset:
        return _decision(join, FanoutPlan.DIRECT_JOIN, FanoutReason.UNIQUE_ONE_SIDE)

    raise ValueError("fan-out evidence does not match its related-side use")


def _oriented_assets(join: GovernedJoin) -> tuple[str, str]:
    if join.cardinality == "many_to_one":
        return join.left, join.right
    if join.cardinality == "one_to_many":
        return join.right, join.left
    raise ValueError("fan-out planning requires a supported cardinality")


def canonical_asset_grain_evidence(asset: CanonicalAsset) -> AssetGrainEvidence:
    """canonical asset의 schema와 grain key를 JOIN planner가 검증할 고유성 증거로 투영한다."""

    fields = frozenset(f"{asset.fqn}.{column.name}" for column in asset.columns)
    key = tuple(f"{asset.fqn}.{column}" for column in asset.grain_keys)
    return AssetGrainEvidence(
        asset_fqn=asset.fqn,
        available_fields=fields,
        unique_key_sets=(key,) if key else (),
    )


def _validate_evidence(
    join: GovernedJoin,
    evidence: GrainSafetyEvidence,
) -> dict[str, AssetGrainEvidence]:
    endpoints = frozenset({join.left, join.right})
    if (
        not evidence.measure_assets
        or not evidence.measure_assets.issubset(endpoints)
    ):
        raise ValueError("fan-out evidence references an unknown join endpoint")
    assets = {item.asset_fqn: item for item in evidence.assets}
    if set(assets) != endpoints or len(assets) != len(evidence.assets):
        raise ValueError("fan-out evidence must cover each join endpoint exactly once")
    for asset_fqn, asset in assets.items():
        prefix = f"{asset_fqn}."
        if not asset.available_fields or any(
            not field.startswith(prefix)
            or not field.removeprefix(prefix)
            or "." in field.removeprefix(prefix)
            for field in asset.available_fields
        ):
            raise ValueError("fan-out asset fields must be qualified by their endpoint")
        for key_set in asset.unique_key_sets:
            if (
                not key_set
                or len(set(key_set)) != len(key_set)
                or not set(key_set).issubset(asset.available_fields)
            ):
                raise ValueError("fan-out unique key evidence is invalid")
    if (
        evidence.related_side_use == RelatedSideUse.SECOND_MEASURE
    ) != (evidence.measure_assets == endpoints):
        raise ValueError("second-measure use requires measures from both join endpoints")
    if len(set(evidence.common_grain_bindings)) != len(
        evidence.common_grain_bindings
    ):
        raise ValueError("fan-out common grain bindings must be unique")
    for left, right in evidence.common_grain_bindings:
        if left not in assets[join.left].available_fields or right not in assets[
            join.right
        ].available_fields:
            raise ValueError("fan-out common grain references an unknown field")
    declared_fields = {
        *join.preaggregation_grain,
        *join.preaggregation_keys,
    }
    if any(
        sum(field in asset.available_fields for asset in assets.values()) != 1
        for field in declared_fields
    ):
        raise ValueError("fan-out preaggregation references an unknown field")
    return assets


def _join_key_is_unique(
    join: GovernedJoin,
    asset_fqn: str,
    assets: dict[str, AssetGrainEvidence],
) -> bool:
    join_fields = {
        field
        for pair in join.equality_conditions
        for field in pair
        if field in assets[asset_fqn].available_fields
    }
    return any(set(key_set).issubset(join_fields) for key_set in assets[asset_fqn].unique_key_sets)


def _common_grain_covers_join(
    join: GovernedJoin,
    bindings: tuple[tuple[str, str], ...],
) -> bool:
    return bool(bindings) and set(bindings) == set(join.equality_conditions)


def _decision(
    join: GovernedJoin,
    plan: FanoutPlan,
    reason: FanoutReason,
) -> FanoutDecision:
    return FanoutDecision(join_id=join.id, plan=plan, reason=reason)
