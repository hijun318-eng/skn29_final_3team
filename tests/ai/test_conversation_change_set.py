"""AnalysisChangeSet 5개 연산이 슬롯 병합을 결정론적으로 표현하는지 검증."""

from __future__ import annotations

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.conversation.change_set import (
    ChangeOperation,
    apply_dimension_changes,
    apply_metric_change,
    derive_dimension_changes,
    derive_metric_change,
)


def test_metric_change_set_when_candidate_present() -> None:
    change = derive_metric_change("room_revenue", is_followup=False, inherited_metric_id=None)
    assert change.op is ChangeOperation.SET
    assert apply_metric_change(change) == ("room_revenue", False)


def test_metric_change_preserve_on_followup() -> None:
    change = derive_metric_change(None, is_followup=True, inherited_metric_id="room_revenue")
    assert change.op is ChangeOperation.PRESERVE
    assert apply_metric_change(change) == ("room_revenue", True)


def test_metric_change_clear_on_new_topic() -> None:
    change = derive_metric_change(None, is_followup=False, inherited_metric_id="room_revenue")
    assert change.op is ChangeOperation.CLEAR
    assert apply_metric_change(change) == (None, False)


def test_dimension_add_value_keeps_existing_and_appends_new() -> None:
    inherited = ({"asset_fqn": "serving.room_daily", "column": "hotel_code"},)
    candidate = (
        {"asset_fqn": "serving.room_daily", "column": "hotel_code"},
        {"asset_fqn": "serving.room_daily", "column": "room_type"},
    )
    changes = derive_dimension_changes(candidate, inherited, is_followup=True)
    assert all(c.op is ChangeOperation.ADD_VALUE for c in changes)
    assert len(changes) == 1
    assert changes[0].value["column"] == "room_type"

    result, is_inherited = apply_dimension_changes(changes, inherited)
    assert is_inherited is True
    assert {d["column"] for d in result} == {"hotel_code", "room_type"}


def test_dimension_remove_value_keeps_remainder() -> None:
    inherited = (
        {"asset_fqn": "serving.room_daily", "column": "hotel_code"},
        {"asset_fqn": "serving.room_daily", "column": "room_type"},
    )
    candidate = ({"asset_fqn": "serving.room_daily", "column": "hotel_code"},)
    changes = derive_dimension_changes(candidate, inherited, is_followup=True)
    assert all(c.op is ChangeOperation.REMOVE_VALUE for c in changes)
    assert changes[0].value["column"] == "room_type"

    result, is_inherited = apply_dimension_changes(changes, inherited)
    assert is_inherited is True
    assert {d["column"] for d in result} == {"hotel_code"}


def test_dimension_disjoint_candidate_is_a_full_set() -> None:
    inherited = ({"asset_fqn": "serving.room_daily", "column": "hotel_code"},)
    candidate = ({"asset_fqn": "serving.fnb_daily", "column": "outlet_id"},)
    changes = derive_dimension_changes(candidate, inherited, is_followup=True)
    assert len(changes) == 1
    assert changes[0].op is ChangeOperation.SET

    result, is_inherited = apply_dimension_changes(changes, inherited)
    assert is_inherited is False
    assert {d["column"] for d in result} == {"outlet_id"}


def test_dimension_preserve_and_clear() -> None:
    inherited = ({"asset_fqn": "serving.room_daily", "column": "hotel_code"},)

    preserved = derive_dimension_changes((), inherited, is_followup=True)
    assert preserved[0].op is ChangeOperation.PRESERVE
    result, is_inherited = apply_dimension_changes(preserved, inherited)
    assert is_inherited is True
    assert {d["column"] for d in result} == {"hotel_code"}

    cleared = derive_dimension_changes((), inherited, is_followup=False)
    assert cleared[0].op is ChangeOperation.CLEAR
    result, is_inherited = apply_dimension_changes(cleared, inherited)
    assert result == ()
    assert is_inherited is False

    assert derive_dimension_changes((), (), is_followup=False) == ()
