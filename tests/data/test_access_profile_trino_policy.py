import json
import re
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
    "answervice_integrated_operations": (
        {"pms", "crm", "pos", "facility", "banquet", "serving"},
        {
            "banquet_monthly_metrics", "facility_daily_metrics",
            "fnb_daypart_metrics", "hotel_daily_metrics",
            "hotel_monthly_metrics", "hotel_yearly_metrics",
            "resource_monthly_metrics", "workforce_monthly_metrics",
        },
    ),
}

RAW_TABLES = {
    "pms": ("public", {"pms_guests", "pms_room_inventory_daily", "pms_reservations", "pms_stays"}),
    "crm": ("dbo", {"crm_customer_map", "crm_member_grade_history", "crm_members", "crm_point_transactions"}),
    "pos": ("pos_db", {"pos_order_items", "pos_orders", "pos_service_periods", "pos_stores"}),
    "facility": ("facility", {"facility_events", "facility_master", "facility_resource_daily", "hotel_staffing_daily"}),
    "banquet": ("public", {"banquet_bookings", "banquet_revenue"}),
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
            assert item["filter"] == "property_id = 'SYNTHETIC_HOTEL_001'"
            if item["catalog"] == "serving":
                actual_serving.update(item["table"].strip("()").split("|"))
            else:
                raw_catalogs.add(item["catalog"])
                schema, tables = RAW_TABLES[item["catalog"]]
                assert item["schema"] == schema
                assert set(item["table"].strip("()").split("|")) == tables
        assert raw_catalogs == catalogs - {"serving"}
        assert actual_serving == serving_views


def test_access_control_refreshes_without_browser_selected_credentials():
    properties = (
        ROOT / "infrastructure/database/trino/etc/access-control.properties"
    ).read_text(encoding="utf-8")
    assert "security.refresh-period=5s" in properties
    assert not any("token" in item for item in json.dumps(RULES).lower().split())


def test_unknown_principal_is_default_denied_without_generic_read_fallback():
    assert [rule for rule in RULES["catalogs"] if "user" not in rule] == [
        {"catalog": "system", "allow": "none"},
        {"catalog": ".*", "allow": "none"},
    ]
    assert [rule for rule in RULES["tables"] if "user" not in rule] == [
        {"privileges": []}
    ]
    assert RULES["queries"][-1] == {"allow": []}
    assert all("user" in rule for rule in RULES["queries"][:-1])
    assert RULES["system_session_properties"] == [{"allow": False}]


def test_resource_groups_bound_each_profile_and_platform_workload():
    config = json.loads(
        (ROOT / "infrastructure/database/trino/etc/resource-groups.json").read_text(
            encoding="utf-8"
        )
    )
    answervice, platform = config["rootGroups"]
    profile = answervice["subGroups"][0]
    assert (answervice["hardConcurrencyLimit"], answervice["maxQueued"]) == (4, 16)
    assert profile["name"] == "profile_${USER}"
    assert (profile["hardConcurrencyLimit"], profile["maxQueued"]) == (2, 4)
    assert (platform["hardConcurrencyLimit"], platform["maxQueued"]) == (2, 4)
    assert config["selectors"] == [
        {
            "user": "answervice_(pms_only|crm_only|pms_crm|integrated_revenue|integrated_operations)",
            "group": "answervice.profile_${USER}",
        },
        {
            "user": "(hotel_synthetic_setup|datahub_ingestion)",
            "group": "platform",
        },
    ]
    properties = (
        ROOT / "infrastructure/database/trino/etc/resource-groups.properties"
    ).read_text(encoding="utf-8")
    assert "resource-groups.configuration-manager=file" in properties
    assert "resource-groups.config-file=etc/resource-groups.json" in properties

    trino = (ROOT / "infrastructure/database/trino/etc/config.properties").read_text(
        encoding="utf-8"
    )
    assert "query.max-execution-time=2m" in trino
    assert "query.max-run-time=3m" in trino
    compose = (ROOT / "infrastructure/database/compose.yml").read_text(encoding="utf-8")
    assert "./trino/etc:/etc/trino:ro" in compose


def test_approved_query_contract_has_no_direct_identifier_needing_a_mask():
    context = json.loads(
        (ROOT / "src/data/analytics_context_contract.i4.v2.json").read_text(
            encoding="utf-8"
        )
    )
    serving = json.loads(
        (ROOT / "src/data/serving_analytics_contract.i4.v1.json").read_text(
            encoding="utf-8"
        )
    )
    three_source = json.loads(
        (ROOT / "src/data/pms_crm_pos_context.i5.v1.json").read_text(
            encoding="utf-8"
        )
    )
    columns = {
        *(
            column
            for asset in context["raw_assets"]
            for column in asset["columns"]
        ),
        *(
            column
            for view in serving["views"]
            for column in view["columns"]
        ),
        *(
            column
            for asset in three_source["assets"]
            for column in asset["columns"]
        ),
    }
    direct_identifier = re.compile(
        r"^(email|e_mail|phone|mobile|full_name|first_name|last_name|"
        r"resident_number|passport_number|credit_card_number)$",
        re.IGNORECASE,
    )
    assert not {column for column in columns if direct_identifier.fullmatch(column)}
    assert all(
        item.get("filter") == "property_id = 'SYNTHETIC_HOTEL_001'"
        for user in PROFILES
        for item in _rules("tables", user)[:-1]
    )
