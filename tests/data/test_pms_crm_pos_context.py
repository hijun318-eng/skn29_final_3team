import hashlib
import json
import math
import re
from datetime import date
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTEXT_PATH = ROOT / "src/data/pms_crm_pos_context.i5.v1.json"
CONTEXT = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
SQL_PATH = ROOT / CONTEXT["gold_evidence"]["sql_file"]
SQL = SQL_PATH.read_text(encoding="utf-8")


def _valid(value_type, value):
    if value_type == "string":
        return isinstance(value, str) and bool(value)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "number":
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    if value_type == "date":
        return (
            isinstance(value, str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None
            and date.fromisoformat(value).isoformat() == value
        )
    return False


def test_context_reuses_approved_case_join_assets_and_grain():
    assert CONTEXT["contract_version"] == "I5-3SOURCE-CONTEXT-v1.1.0-DRAFT"
    assert CONTEXT["case_id"] == "G120-046"
    assert CONTEXT["synthetic"] is True
    assert CONTEXT["property_id"] == "SYNTHETIC_HOTEL_001"
    assert CONTEXT["execution_time"] == {
        "timezone": "Asia/Seoul",
        "period_start": "2026-05-01",
        "period_end_exclusive": "2026-07-01",
    }
    assert CONTEXT["grain"] == ["property_id", "month"]
    assert CONTEXT["approved_join"] == {
        "id": "pms_crm_pos_gold_revenue_month_v1",
        "cardinality": "preaggregate_then_one_to_one_month",
        "source_preaggregations": ["pms_crm_by_property_month", "pos_crm_by_property_month"],
        "combine_keys": ["property_id", "month"],
        "amplification_limit": 1,
    }
    fqns = {asset["fqn"] for asset in CONTEXT["assets"]}
    assert {fqn.split(".", 1)[0] for fqn in fqns} == {"pms", "crm", "pos"}
    assert len(fqns) == len(CONTEXT["assets"]) == 6
    assert all(asset["urn"] and asset["columns"] for asset in CONTEXT["assets"])


def test_context_filters_and_parameters_are_typed_and_deterministic():
    filters = CONTEXT["required_filters"]
    assert [item["field"] for item in filters] == sorted(item["field"] for item in filters)
    assert all(set(item) == {"field", "operator", "value_type", "value"} for item in filters)
    assert all(item["operator"] == "eq" and _valid(item["value_type"], item["value"]) for item in filters)

    bindings = CONTEXT["parameter_bindings"]
    assert [item["name"] for item in bindings] == [
        "period_start",
        "period_end_exclusive",
        *(f"required_filter_{index}" for index in range(1, len(filters) + 1)),
    ]
    assert all(_valid(item["value_type"], item["value"]) for item in bindings)
    assert [(item["value_type"], item["value"]) for item in bindings[2:]] == [
        (item["value_type"], item["value"]) for item in filters
    ]
    assert "period_end" not in {item["name"] for item in bindings}


def test_gold_sql_preaggregates_sources_before_property_month_join():
    normalized = re.sub(r"\s+", " ", SQL.lower())
    assert normalized.startswith("with pms_gold as (")
    assert "), pos_gold as (" in normalized
    assert "full outer join pos_gold" in normalized
    assert "p.property_id = f.property_id and p.month = f.month" in normalized
    assert SQL.count("GROUP BY 1, 2") == 2
    assert SQL.count("SYNTHETIC_HOTEL_001") == 2
    assert SQL.count("2026-05-01") == 2
    assert SQL.count("2026-07-01") == 2
    assert re.search(r"\b(insert|update|delete|merge|create|alter|drop|truncate|call)\b", normalized) is None


def test_gold_evidence_hashes_rows_and_totals():
    evidence = CONTEXT["gold_evidence"]
    assert hashlib.sha256(SQL_PATH.read_bytes()).hexdigest() == evidence["sql_sha256"]
    canonical = "".join("|".join(row) + "\n" for row in evidence["rows"])
    assert hashlib.sha256(canonical.encode()).hexdigest() == evidence["result_sha256"]
    assert len(evidence["rows"]) == evidence["row_count"] == 2
    assert sum(Decimal(row[-1]) for row in evidence["rows"]) == Decimal(
        evidence["total_guest_revenue_krw"]
    )
    assert evidence["runtime"]["engine"] == "Trino 476"
    assert evidence["runtime"]["status"] == "PASS"


def test_existing_i3_gold_evidence_remains_unchanged():
    contract = json.loads((ROOT / "src/data/i3_contract.v1.json").read_text(encoding="utf-8"))
    fixture = next(item for item in contract["gold_fixtures"] if item["id"] == "gold_total_guest_revenue_mom")
    assert fixture["sql_sha256"] == "3b9384005e7d2b0138f0c23475b7b0873dd85ada7ef3ace2229e68d20a2249fa"
    assert fixture["sha256"] == "5333602fe9d11b9c23be1833ec316e894f6ee55359185a0f9ea0052b18e56865"
