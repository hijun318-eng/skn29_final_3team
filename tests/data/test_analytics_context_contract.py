import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads(
    (ROOT / "src/data/analytics_context_contract.i4.v2.json").read_text(encoding="utf-8")
)


def test_raw_allowlist_is_exact_and_bounded():
    assets = {asset["fqn"]: asset for asset in CONTRACT["raw_assets"]}
    assert set(assets) == {
        "crm.dbo.crm_members",
        "crm.dbo.crm_member_grade_history",
        "crm.dbo.crm_point_transactions",
        "crm.dbo.crm_customer_map",
        "pms.public.pms_stays",
        "pms.public.pms_reservations",
        "pms.public.pms_guests",
    }
    assert all(asset["columns"] for asset in assets.values())
    assert sum(len(asset["columns"]) for asset in assets.values()) <= 60


def test_only_crm_and_approved_join_can_use_raw_assets():
    allowed_uses = {"crm_only", "approved_pms_crm_join"}
    assert set(CONTRACT["selection_policy"]["raw_allowed_for"]) == allowed_uses
    assert all(set(asset["uses"]) <= allowed_uses for asset in CONTRACT["raw_assets"])
    assert CONTRACT["selection_policy"]["default"] == "serving_views"


def test_pms_crm_join_matches_frozen_source_registry():
    source_registry = json.loads(
        (ROOT / "src/data/source_registry.v1.json").read_text(encoding="utf-8")
    )
    expected = next(
        join
        for join in source_registry["approved_joins"]
        if join["join_id"] == "pms_stay_to_crm_membership_grade_event_time_v1"
    )
    actual = CONTRACT["approved_joins"]
    assert len(actual) == 1
    assert actual[0]["id"] == expected["join_id"]
    assert actual[0]["cardinality"] == expected["cardinality"]
    assert actual[0]["event_time_field"] == expected["event_time_field"]
    assert len(actual[0]["assets"]) == 5
