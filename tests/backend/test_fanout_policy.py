"""Measure 위치와 JOIN 카디널리티별 팬아웃 결정표를 검증한다."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.services.context.contract import GovernedJoin  # noqa: E402
from app.services.context.fanout_policy import (  # noqa: E402
    AssetGrainEvidence,
    FanoutPlan,
    FanoutReason,
    GrainSafetyEvidence,
    RelatedSideUse,
    decide_fanout_plan,
)


LEFT = "serving.analytics.fact_left"
RIGHT = "serving.analytics.dimension_right"
LEFT_JOIN_KEY = f"{LEFT}.entity_id"
RIGHT_JOIN_KEY = f"{RIGHT}.entity_id"


def _join(
    cardinality: str = "many_to_one",
    *,
    preaggregation_required: bool = False,
    preaggregation_field: str = LEFT_JOIN_KEY,
) -> GovernedJoin:
    return GovernedJoin(
        id="left_to_right",
        left=LEFT,
        right=RIGHT,
        kind="inner",
        cardinality=cardinality,
        equality_conditions=((LEFT_JOIN_KEY, RIGHT_JOIN_KEY),),
        temporal_conditions=(),
        preaggregation_required=preaggregation_required,
        preaggregation_grain=(preaggregation_field,),
        preaggregation_keys=(preaggregation_field,),
    )


def _asset_evidence(
    asset_fqn: str,
    *,
    unique_on_join: bool,
) -> AssetGrainEvidence:
    join_key = f"{asset_fqn}.entity_id"
    row_key = f"{asset_fqn}.row_id"
    return AssetGrainEvidence(
        asset_fqn=asset_fqn,
        available_fields=frozenset(
            {join_key, row_key, f"{asset_fqn}.measure_value"}
        ),
        unique_key_sets=((join_key,),) if unique_on_join else ((row_key,),),
    )


def _evidence(
    measure_assets: frozenset[str],
    related_side_use: RelatedSideUse,
    *,
    unique_left: bool = False,
    unique_right: bool = True,
    common_grain_bindings: tuple[tuple[str, str], ...] = (),
) -> GrainSafetyEvidence:
    return GrainSafetyEvidence(
        measure_assets=measure_assets,
        related_side_use=related_side_use,
        assets=(
            _asset_evidence(LEFT, unique_on_join=unique_left),
            _asset_evidence(RIGHT, unique_on_join=unique_right),
        ),
        common_grain_bindings=common_grain_bindings,
    )


@pytest.mark.parametrize(
    ("join", "measure_asset", "unique_left", "unique_right"),
    (
        (_join("many_to_one"), LEFT, False, True),
        (_join("one_to_many"), RIGHT, True, False),
    ),
)
def test_many_side_measure_can_join_a_proven_unique_dimension(
    join: GovernedJoin,
    measure_asset: str,
    unique_left: bool,
    unique_right: bool,
) -> None:
    decision = decide_fanout_plan(
        join,
        _evidence(
            frozenset({measure_asset}),
            RelatedSideUse.DIMENSION_BREAKDOWN,
            unique_left=unique_left,
            unique_right=unique_right,
        ),
    )

    assert decision.plan == FanoutPlan.DIRECT_JOIN
    assert decision.reason == FanoutReason.UNIQUE_ONE_SIDE


def test_declared_cardinality_without_join_key_uniqueness_is_rejected() -> None:
    decision = decide_fanout_plan(
        _join(),
        _evidence(
            frozenset({LEFT}),
            RelatedSideUse.DIMENSION_BREAKDOWN,
            unique_right=False,
        ),
    )

    assert decision.plan == FanoutPlan.REJECT
    assert decision.reason == FanoutReason.UNIQUENESS_UNPROVEN


def test_one_to_one_requires_both_join_keys_to_be_unique() -> None:
    rejected = decide_fanout_plan(
        _join("one_to_one"),
        _evidence(
            frozenset({LEFT}),
            RelatedSideUse.DIMENSION_BREAKDOWN,
            unique_left=False,
            unique_right=True,
        ),
    )
    accepted = decide_fanout_plan(
        _join("one_to_one"),
        _evidence(
            frozenset({LEFT}),
            RelatedSideUse.DIMENSION_BREAKDOWN,
            unique_left=True,
            unique_right=True,
        ),
    )

    assert rejected.plan == FanoutPlan.REJECT
    assert rejected.reason == FanoutReason.UNIQUENESS_UNPROVEN
    assert accepted.plan == FanoutPlan.DIRECT_JOIN


def test_one_to_one_honors_an_explicit_preaggregation_contract() -> None:
    decision = decide_fanout_plan(
        _join("one_to_one", preaggregation_required=True),
        _evidence(
            frozenset({LEFT}),
            RelatedSideUse.DIMENSION_BREAKDOWN,
            unique_left=True,
            unique_right=True,
        ),
    )

    assert decision.plan == FanoutPlan.PREAGGREGATE
    assert decision.reason == FanoutReason.DECLARED_PREAGGREGATION


def test_one_side_measure_uses_semi_join_for_many_side_filter() -> None:
    decision = decide_fanout_plan(
        _join(),
        _evidence(frozenset({RIGHT}), RelatedSideUse.FILTER_ONLY),
    )

    assert decision.plan == FanoutPlan.SEMI_JOIN
    assert decision.reason == FanoutReason.FILTER_ONLY_MANY_SIDE


def test_one_side_measure_cannot_break_down_by_many_side_without_allocation() -> None:
    decision = decide_fanout_plan(
        _join(),
        _evidence(frozenset({RIGHT}), RelatedSideUse.DIMENSION_BREAKDOWN),
    )

    assert decision.plan == FanoutPlan.REJECT
    assert decision.reason == FanoutReason.ALLOCATION_REQUIRED


@pytest.mark.parametrize(
    ("bindings", "expected_plan", "expected_reason"),
    (
        (
            ((LEFT_JOIN_KEY, RIGHT_JOIN_KEY),),
            FanoutPlan.PREAGGREGATE,
            FanoutReason.MULTI_FACT_COMMON_GRAIN,
        ),
        ((), FanoutPlan.REJECT, FanoutReason.COMMON_GRAIN_REQUIRED),
    ),
)
def test_multi_fact_join_requires_all_governed_join_keys_as_common_grain(
    bindings: tuple[tuple[str, str], ...],
    expected_plan: FanoutPlan,
    expected_reason: FanoutReason,
) -> None:
    decision = decide_fanout_plan(
        _join(),
        _evidence(
            frozenset({LEFT, RIGHT}),
            RelatedSideUse.SECOND_MEASURE,
            common_grain_bindings=bindings,
        ),
    )

    assert decision.plan == expected_plan
    assert decision.reason == expected_reason


def test_many_to_many_is_rejected_until_bridge_contract_is_typed() -> None:
    decision = decide_fanout_plan(
        _join("many_to_many"),
        _evidence(
            frozenset({LEFT}),
            RelatedSideUse.DIMENSION_BREAKDOWN,
            unique_right=False,
            common_grain_bindings=((LEFT_JOIN_KEY, RIGHT_JOIN_KEY),),
        ),
    )

    assert decision.plan == FanoutPlan.REJECT
    assert decision.reason == FanoutReason.MANY_TO_MANY_UNSUPPORTED


def test_declared_preaggregation_uses_the_governed_edge_contract() -> None:
    decision = decide_fanout_plan(
        _join(preaggregation_required=True),
        _evidence(frozenset({LEFT}), RelatedSideUse.DIMENSION_BREAKDOWN),
    )

    assert decision.plan == FanoutPlan.PREAGGREGATE
    assert decision.reason == FanoutReason.DECLARED_PREAGGREGATION


def test_preaggregation_field_must_exist_in_endpoint_schema() -> None:
    with pytest.raises(ValueError, match="preaggregation references an unknown field"):
        decide_fanout_plan(
            _join(
                preaggregation_required=True,
                preaggregation_field=f"{LEFT}.not_a_column",
            ),
            _evidence(frozenset({LEFT}), RelatedSideUse.DIMENSION_BREAKDOWN),
        )


def test_common_grain_cannot_be_an_arbitrary_string_pair() -> None:
    with pytest.raises(ValueError, match="common grain references an unknown field"):
        decide_fanout_plan(
            _join(),
            _evidence(
                frozenset({LEFT, RIGHT}),
                RelatedSideUse.SECOND_MEASURE,
                common_grain_bindings=(
                    (f"{LEFT}.not_a_column", f"{RIGHT}.not_a_column"),
                ),
            ),
        )


def test_evidence_must_cover_both_edge_endpoints_once() -> None:
    with pytest.raises(ValueError, match="cover each join endpoint exactly once"):
        decide_fanout_plan(
            _join(),
            GrainSafetyEvidence(
                measure_assets=frozenset({LEFT}),
                related_side_use=RelatedSideUse.DIMENSION_BREAKDOWN,
                assets=(_asset_evidence(LEFT, unique_on_join=False),),
            ),
        )
