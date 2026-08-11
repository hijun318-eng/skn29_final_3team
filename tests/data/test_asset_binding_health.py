import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BINDING_PATH = ROOT / "src/data/asset_binding_health.i5.v1.json"
CONTRACT_PATH = ROOT / "src/data/serving_analytics_contract.i4.v1.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_asset_bindings_are_unique_exact_pairs():
    health = load(BINDING_PATH)
    contract = load(CONTRACT_PATH)
    bindings = health["bindings"]
    assert health["required_fields"] == [
        "binding_id", "urn", "fqn", "status", "version", "verified_at", "provenance"
    ]
    assert len(bindings) == 8
    for key in ("binding_id", "urn", "fqn"):
        assert len({item[key] for item in bindings}) == len(bindings)
    assert {(item["urn"], item["fqn"]) for item in bindings} == {
        (view["urn"], view["fqn"]) for view in contract["views"]
    }


def test_unverified_bindings_cannot_claim_health():
    health = load(BINDING_PATH)
    assert (health["status"], health["runtime_execution"]) == ("BLOCKED", "NOT_RUN")
    for item in health["bindings"]:
        assert item["status"] == "PENDING_RUNTIME_VERIFICATION"
        assert item["verified_at"] is None
        assert re.fullmatch(r"\d+\.\d+\.\d+", item["version"])
        assert item["provenance"] == {
            "datahub_exact_search": {"status": "NOT_RUN", "response_sha256": None},
            "trino_metadata": {"status": "NOT_RUN", "result_sha256": None},
        }


def test_verified_timestamp_rule_requires_utc():
    def is_utc(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value.endswith("Z") and parsed.utcoffset().total_seconds() == 0

    assert is_utc("2026-08-10T12:00:00Z")
    assert not is_utc("2026-08-10T21:00:00+09:00")
