import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config/server-access-profiles.v1.json"
COMPOSE_PATH = ROOT / "infrastructure/database/datahub/compose.consumer.yml"
BACKEND_COMPOSE_PATH = ROOT / "app/backend/compose.fragment.yml"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
RECIPES_PATH = ROOT / "infrastructure/database/datahub/recipes"


EXPECTED = {
    "pms_only": (
        ["urn:li:domain:rooms"],
        "DATAHUB_PMS_ONLY_TOKEN",
        "answervice_pms_only",
    ),
    "crm_only": (
        ["urn:li:domain:membership"],
        "DATAHUB_CRM_ONLY_TOKEN",
        "answervice_crm_only",
    ),
    "pms_crm": (
        ["urn:li:domain:rooms", "urn:li:domain:membership"],
        "DATAHUB_PMS_CRM_TOKEN",
        "answervice_pms_crm",
    ),
    "integrated_revenue": (
        [
            "urn:li:domain:rooms",
            "urn:li:domain:membership",
            "urn:li:domain:food_and_beverage",
        ],
        "DATAHUB_INTEGRATED_REVENUE_TOKEN",
        "answervice_integrated_revenue",
    ),
}


def test_server_access_profiles_are_explicit_default_deny_grants():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert contract["contract_version"] == "SERVER-ACCESS-PROFILES-v1.0.0"
    assert contract["default_effect"] == "deny"
    assert contract["all_users_policy_dependency"] is False
    assert contract["datahub"]["policy_provisioning"] == "explicit_actor_domain_grants"
    assert contract["datahub"]["oss_search_visibility"] == "application_domain_filter_required"
    assert set(contract["profiles"]) == set(EXPECTED)

    actors = set()
    token_envs = set()
    principals = set()
    for name, (domains, token_env, trino_principal) in EXPECTED.items():
        profile = contract["profiles"][name]
        assert profile["domains"] == domains
        assert profile["datahub_actor"] == f"urn:li:corpuser:{trino_principal}"
        assert profile["datahub_token_env"] == token_env
        assert profile["trino_principal"] == trino_principal
        actors.add(profile["datahub_actor"])
        token_envs.add(token_env)
        principals.add(trino_principal)

    assert len(actors) == len(token_envs) == len(principals) == 4


def test_datahub_v1_7_auth_and_authorization_are_enabled_without_embedded_secrets():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    for setting in (
        'METADATA_SERVICE_AUTH_ENABLED: "true"',
        'AUTH_POLICIES_ENABLED: "true"',
        'VIEW_AUTHORIZATION_ENABLED: "true"',
        'REST_API_AUTHORIZATION_ENABLED: "true"',
    ):
        assert setting in compose
    assert compose.count('METADATA_SERVICE_AUTH_ENABLED: "true"') == 2
    assert compose.count("DATAHUB_SYSTEM_CLIENT_SECRET: ${DATAHUB_SYSTEM_CLIENT_SECRET}") == 4
    assert "JohnSnowKnowsNothing" not in compose
    assert 'METADATA_SERVICE_AUTH_ENABLED: "false"' not in compose


def test_token_names_are_wired_but_values_remain_external():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    env_example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    backend_compose = BACKEND_COMPOSE_PATH.read_text(encoding="utf-8")

    for profile in contract["profiles"].values():
        token_env = profile["datahub_token_env"]
        assert f"{token_env}=REQUIRED" in env_example
        assert f"{token_env}: ${{{token_env}:-}}" in backend_compose
        assert set(profile) == {"domains", "datahub_actor", "datahub_token_env", "trino_principal"}

    assert "DATAHUB_SYSTEM_CLIENT_SECRET=REQUIRED" in env_example
    assert "DATAHUB_INGESTION_TOKEN=REQUIRED" in env_example
    for recipe in RECIPES_PATH.glob("*.yml"):
        contents = recipe.read_text(encoding="utf-8")
        assert "token: ${DATAHUB_INGESTION_TOKEN}" in contents
        assert "urn:li:tag:AI_SEARCH_ALLOWED" in contents


def test_recipes_register_source_domains_and_serving_lineage_domains():
    expected_domains = {
        "pms.i2.yml": "urn:li:domain:rooms",
        "crm.i2.yml": "urn:li:domain:membership",
        "pos.i3.yml": "urn:li:domain:food_and_beverage",
        "facility.i3.yml": "urn:li:domain:facility",
        "banquet.i3.yml": "urn:li:domain:banquet",
    }
    for name, domain in expected_domains.items():
        contents = (RECIPES_PATH / name).read_text(encoding="utf-8")
        assert "type: simple_add_dataset_domain" in contents
        assert domain in contents

    serving = (RECIPES_PATH / "serving.i4.yml").read_text(encoding="utf-8")
    assert "type: pattern_add_dataset_domain" in serving
    for domain in (
        "urn:li:domain:rooms",
        "urn:li:domain:food_and_beverage",
        "urn:li:domain:facility",
        "urn:li:domain:banquet",
    ):
        assert domain in serving
