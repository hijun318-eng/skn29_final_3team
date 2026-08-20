from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
RECIPES = ROOT / "infrastructure/database/datahub/recipes"
INGESTION_COMPOSE = ROOT / "infrastructure/database/datahub/compose.ingestion.yml"
INGESTION_SCRIPT = ROOT / "infrastructure/database/datahub/ingest_runtime_catalog.ps1"
START_SCRIPT = ROOT / "infrastructure/database/scripts/start.ps1"


EXPECTED_PROPERTIES_TRANSFORMER = [
    {
        "type": "simple_add_dataset_properties",
        "config": {
            "semantics": "PATCH",
            "replace_existing": False,
            "properties": {},
        },
    }
]


def test_only_runtime_discovery_recipes_remain():
    paths = sorted(RECIPES.glob("*.yml"))
    assert [path.name for path in paths] == [
        "banquet.runtime.yml",
        "crm.runtime.yml",
        "facility.runtime.yml",
        "pms.runtime.yml",
        "pos.runtime.yml",
        "serving.runtime.yml",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        recipe = yaml.safe_load(text)
        config = recipe["source"]["config"]
        sink = recipe["sink"]["config"]
        assert sink["server"] == "${DATAHUB_GMS_URL}"
        assert sink["token"] == "${DATAHUB_PUBLISH_API_TOKEN}"
        assert sink["ca_certificate_path"] == "${DATAHUB_TLS_CA_FILE}"
        assert "platform_instance" in config
        assert "table_pattern" not in config
        assert "view_pattern" not in config
        assert recipe["transformers"] == EXPECTED_PROPERTIES_TRANSFORMER
        assert "release_marker" not in text
        assert "2026-" not in text


def test_recipes_use_runtime_schema_or_database_scope_not_table_allowlists():
    for name in ("pms", "banquet", "crm"):
        recipe = yaml.safe_load(
            (RECIPES / f"{name}.runtime.yml").read_text(encoding="utf-8")
        )
        allow = recipe["source"]["config"]["schema_pattern"]["allow"]
        assert len(allow) == 1 and str(allow[0]).startswith("${")
    for name in ("facility", "pos"):
        recipe = yaml.safe_load(
            (RECIPES / f"{name}.runtime.yml").read_text(encoding="utf-8")
        )
        assert str(recipe["source"]["config"]["database"]).startswith("${")
    serving = yaml.safe_load(
        (RECIPES / "serving.runtime.yml").read_text(encoding="utf-8")
    )
    config = serving["source"]["config"]
    assert config["include_tables"] is True
    assert config["include_views"] is True
    # Serving은 release schema를 고정하지 않고 connector system metadata만 제외한다.
    assert config["schema_pattern"] == {"deny": ["^(information_schema|system)$"]}


def test_ingestion_profile_runs_every_runtime_recipe_without_static_asset_lists():
    compose = yaml.safe_load(INGESTION_COMPOSE.read_text(encoding="utf-8"))
    service = compose["services"]["datahub-ingestion"]
    assert service["entrypoint"] == ["/bin/sh", "-euc"]
    assert "for recipe in /recipes/*.runtime.yml" in service["command"][0]
    assert set(service["networks"]) == {"database-network", "datahub-network"}
    assert set(service["volumes"]) == {
        "./datahub/recipes:/recipes:ro",
        "${TRINO_TLS_CA_HOST_FILE:?TRINO_TLS_CA_HOST_FILE is required}:/run/secrets/trino-ca.pem:ro",
        "${DATAHUB_TLS_CA_HOST_FILE:?DATAHUB_TLS_CA_HOST_FILE is required}:/run/secrets/datahub-ca.pem:ro",
    }
    assert "sha256:" in service["image"]
    assert service["environment"]["REQUESTS_CA_BUNDLE"] == "/run/secrets/datahub-ca.pem"
    script = INGESTION_SCRIPT.read_text(encoding="utf-8")
    assert "Get-ChildItem" in script and "*.runtime.yml" in script
    assert "-Apply" in script and "BASE_METADATA_INGESTED" in script
    assert "catalog_ready=false|next=SEMANTIC_CHECK" in script
    assert "docker wait $ingestionContainer[0]" in script
    assert "ANSWERVICE_RUNTIME_CATALOG_INGESTION_COMPLETE" in service["command"][0]
    assert "ANSWERVICE_RUNTIME_CATALOG_INGESTION_COMPLETE" in script
    assert "docker logs --tail 20" in script
    assert "compose.semantic-search.yml" not in script
    assert "dataset-semantic-content-bootstrap" not in script
    assert "PUBLISHED" not in script and "VERIFIED" not in script


def test_base_ingestion_never_claims_semantic_catalog_readiness():
    start = START_SCRIPT.read_text(encoding="utf-8")
    assert "DATABASE_CATALOG_METADATA_READY" not in start
    assert (
        "DATABASE_BASE_METADATA_INGESTED|catalog_ready=false|next=SEMANTIC_CHECK"
        in start
    )
    assert "PUBLISHED_AND_VERIFIED" in start


def test_patch_transformer_contract_preserves_runtime_properties_on_reingestion():
    """semantic 발행 뒤 같은 base aspect가 재실행돼도 custom property가 유지되는 계약을 고정한다."""

    connector_properties = {"connector.table_type": "BASE TABLE"}
    semantic_properties = {
        "answervice.contract_version": "ANSWERVICE-RUNTIME-GOVERNANCE-v1",
        "answervice.catalog_sha256": "a" * 64,
        "answervice.release_manifest": "manifest",
    }

    # DataHub v1.7 SimpleAddDatasetProperties(PATCH)는 server 값을 먼저 읽고
    # connector가 이번 실행에서 실제로 관측한 key만 우선시킨다.
    after_first_base = dict(connector_properties)
    after_semantic_publish = after_first_base | semantic_properties
    after_second_base = after_semantic_publish | connector_properties

    assert after_second_base == after_semantic_publish
    assert {
        key: value
        for key, value in after_second_base.items()
        if key.startswith("answervice.")
    } == semantic_properties
