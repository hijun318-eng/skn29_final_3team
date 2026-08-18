from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
RECIPES = ROOT / "infrastructure/database/datahub/recipes"
INGESTION_COMPOSE = ROOT / "infrastructure/database/datahub/compose.ingestion.yml"
INGESTION_SCRIPT = ROOT / "infrastructure/database/datahub/ingest_runtime_catalog.ps1"


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
        assert "transformers" not in recipe
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
    # Serving은 release schema를 고정하지 않고 Trino system metadata만 제외한다.
    assert config["schema_pattern"] == {"deny": ["^information_schema$"]}


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
    assert "docker wait $ingestionContainer[0]" in script
    assert "compose.semantic-search.yml" not in script
    assert "dataset-semantic-content-bootstrap" not in script
    assert "PUBLISHED" not in script and "VERIFIED" not in script
