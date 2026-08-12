import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "infrastructure/database/datahub/bootstrap_access_control.py"
SPEC = importlib.util.spec_from_file_location("bootstrap_access_control", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_serving_domains_follow_all_transitive_upstreams():
    views = json.loads(MODULE.SERVING_CONTRACT.read_text(encoding="utf-8"))["views"]

    domains = MODULE.serving_domains(views)

    assert domains["serving.analytics.hotel_daily_metrics"] == ["rooms"]
    assert domains["serving.analytics.hotel_monthly_metrics"] == [
        "banquet", "facility", "food_and_beverage", "rooms"
    ]
    assert domains["serving.analytics.resource_monthly_metrics"] == ["facility", "rooms"]


def test_policy_urn_is_stable_and_does_not_contain_credentials():
    assert MODULE._policy_urn("pms_only") == MODULE._policy_urn("pms_only")
    assert MODULE._policy_urn("pms_only") != MODULE._policy_urn("crm_only")
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "DATAHUB_BOOTSTRAP_TOKEN" in source
    assert "sk-proj-" not in source
    assert "rpa_" not in source
