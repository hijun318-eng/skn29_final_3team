import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RULES = json.loads(
    (ROOT / "infrastructure/database/trino/etc/access-control-rules.json").read_text(
        encoding="utf-8"
    )
)

PROFILES = {
    "answervice_pms_only": ({"pms", "serving"}, {"hotel_daily_metrics"}),
    "answervice_crm_only": ({"crm"}, set()),
    "answervice_pms_crm": ({"pms", "crm", "serving"}, {"hotel_daily_metrics"}),
    "answervice_integrated_revenue": (
        {"pms", "crm", "pos", "serving"},
        {"hotel_daily_metrics", "fnb_daypart_metrics"},
    ),
}


def _rules(kind, user):
    return [item for item in RULES[kind] if item.get("user") == user]


def test_each_access_profile_has_allowlist_then_catch_all_deny():
    for user, (catalogs, _) in PROFILES.items():
        rules = _rules("catalogs", user)
        assert len(rules) == 2
        assert set(rules[0]["catalog"].strip("()").split("|")) == catalogs
        assert rules[0]["allow"] == "read-only"
        assert rules[1] == {"user": user, "catalog": ".*", "allow": "none"}


def test_profile_table_rules_enforce_raw_domains_and_serving_dependencies():
    for user, (catalogs, serving_views) in PROFILES.items():
        rules = _rules("tables", user)
        assert rules[-1]["catalog"] == ".*" and rules[-1]["privileges"] == []
        allowed = [item for item in rules[:-1] if item["privileges"] == ["SELECT"]]
        raw_catalogs = set()
        actual_serving = set()
        for item in allowed:
            if item["catalog"] == "serving":
                actual_serving.update(item["table"].strip("()").split("|"))
            else:
                raw_catalogs.update(item["catalog"].strip("()").split("|"))
        assert raw_catalogs == catalogs - {"serving"}
        assert actual_serving == serving_views


def test_access_control_refreshes_without_browser_selected_credentials():
    properties = (
        ROOT / "infrastructure/database/trino/etc/access-control.properties"
    ).read_text(encoding="utf-8")
    assert "security.refresh-period=5s" in properties
    assert not any("token" in item for item in json.dumps(RULES).lower().split())
