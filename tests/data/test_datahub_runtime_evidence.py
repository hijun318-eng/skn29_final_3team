import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / "src/data/datahub_runtime_evidence.i5.v1.json"
CONTRACT_PATH = ROOT / "src/data/serving_analytics_contract.i4.v1.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_runtime_evidence_records_successful_live_validation():
    evidence = load(EVIDENCE_PATH)
    assert evidence["contract_version"] == "I5-DATAHUB-v1.1.0-RUNTIME-DRAFT"
    assert evidence["datahub_version"] == "v1.7.0"
    assert evidence["trino_version"] == "476"
    assert (evidence["status"], evidence["runtime_execution"]) == ("PASS", "PASS")
    assert evidence["blocker"] is None
    assert evidence["recorded_at"].endswith("Z")
    assert all(item["status"] == "PASS" and item["exit_code"] == 0 for item in evidence["ingestion_plan"])
    assert all(item["status"] == "PASS" for item in evidence["observed"].values())
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["canonical_sha256"]) for item in evidence["observed"].values())
    assert evidence["observed"]["search"]["view_count"] == 8
    assert evidence["observed"]["schema"]["column_count"] == 116
    assert evidence["observed"]["lineage"]["upstream_edge_count"] > 0
    assert evidence["observed"]["lineage"]["fine_grained_lineage_count"] > 0


def test_recipe_order_and_hashes_are_reproducible():
    evidence = load(EVIDENCE_PATH)
    assert [item["source"] for item in evidence["ingestion_plan"]] == [
        "pms", "pos", "crm", "facility", "banquet", "serving"
    ]
    for order, item in enumerate(evidence["ingestion_plan"], 1):
        recipe = ROOT / item["recipe"]
        assert item["order"] == order
        assert recipe.is_file()
        assert hashlib.sha256(recipe.read_bytes()).hexdigest() == item["recipe_sha256"]


def test_expected_assets_match_the_serving_contract():
    evidence = load(EVIDENCE_PATH)
    contract = load(CONTRACT_PATH)
    urns = [view["urn"] for view in contract["views"]]
    assert evidence["expected"]["urns"] == urns
    assert evidence["expected"]["view_count"] == len(contract["views"]) == 8
    assert evidence["expected"]["column_count"] == sum(len(view["columns"]) for view in contract["views"]) == 116


def test_evidence_has_no_secret_bearing_fields():
    raw = EVIDENCE_PATH.read_text(encoding="utf-8")
    assert not re.search(r'"[^"\n]*(password|secret|token|credential)[^"\n]*"\s*:', raw, re.I)
