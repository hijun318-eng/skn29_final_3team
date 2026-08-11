import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / "src/data/datahub_runtime_evidence.i5.v1.json"
CONTRACT_PATH = ROOT / "src/data/serving_analytics_contract.i4.v1.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_runtime_evidence_is_truthfully_partial_and_blocked():
    evidence = load(EVIDENCE_PATH)
    assert evidence["contract_version"] == "I5-DATAHUB-v1.1.0-RUNTIME-DRAFT"
    assert evidence["datahub_version"] == "v1.7.0"
    assert evidence["trino_version"] == "476"
    assert (evidence["status"], evidence["runtime_execution"]) == ("BLOCKED", "PARTIAL")
    assert evidence["blocker"]["code"] == "CRM_MSDB_METADATA_PERMISSION_DENIED"
    assert evidence["blocker"]["required_checkpoint"] == "R1_RUNTIME_HEALTHY"
    assert evidence["recorded_at"].endswith("+09:00")
    assert [item["status"] for item in evidence["ingestion_plan"]] == [
        "PASS", "PASS", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN"
    ]
    assert [item["exit_code"] for item in evidence["ingestion_plan"]] == [0, 0, None, None, None, None]
    assert evidence["observed"]["ingestion"]["status"] == "PARTIAL"
    assert len(evidence["observed"]["ingestion"]["run_ids"]) == 2
    assert evidence["observed"]["ingestion"]["canonical_sha256"] == hashlib.sha256(
        b"pms:0|pos:0"
    ).hexdigest()
    for name in ("search", "schema", "lineage"):
        assert evidence["observed"][name]["status"] == "NOT_RUN"
        assert evidence["observed"][name]["canonical_sha256"] is None


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
