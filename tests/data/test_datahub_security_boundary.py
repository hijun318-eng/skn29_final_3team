"""DataHub 운영 stack의 인증·TLS·secret-source 경계를 회귀 검증한다."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.data.datahub_connection import (
    DataHubConnectionError,
    DataHubConnectionSettings,
)


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"


class ComposeLoader(yaml.SafeLoader):
    """Compose merge tag를 값 보존 방식으로 읽는 test loader다."""


def _compose_override(loader: ComposeLoader, node: yaml.Node):
    """``!override`` node의 실제 scalar/sequence/mapping 값만 구성한다."""

    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


ComposeLoader.add_constructor("!override", _compose_override)


def _yaml(path: Path) -> dict[str, object]:
    """Compose custom tag가 없는 base fragment를 객체로 읽는다."""

    value = yaml.load(path.read_text(encoding="utf-8"), Loader=ComposeLoader)
    assert isinstance(value, dict)
    return value


def test_gms_is_production_authenticated_tls_and_loopback_only() -> None:
    """GMS API가 prod/authz/TLS를 강제하고 host 평문 listener를 만들지 않는지 확인한다."""

    service = _yaml(DATAHUB / "compose.consumer.yml")["services"][
        "datahub-gms-quickstart"
    ]
    environment = service["environment"]
    assert environment["DATAHUB_SERVER_TYPE"] == "prod"
    assert environment["METADATA_SERVICE_AUTH_ENABLED"] == "true"
    assert environment["METADATA_SERVICE_AUTH_ENFORCE_EXISTENCE_ENABLED"] == "true"
    assert environment["METADATA_SERVICE_AUTHENTICATOR_EXCEPTIONS_ENABLED"] == "true"
    assert environment["REST_API_AUTHORIZATION_ENABLED"] == "true"
    assert environment["GUEST_AUTHENTICATION_ENABLED"] == "false"
    assert environment["SERVER_PORT"] == "8443"
    assert environment["SERVER_SSL_ENABLED"] == "true"
    assert service["ports"][0].startswith("127.0.0.1:")
    assert service["ports"][0].endswith(":8443")
    assert any("DATAHUB_TLS_KEYSTORE_HOST_FILE" in item for item in service["volumes"])


def test_internal_consumers_share_authenticated_encrypted_gms_boundary() -> None:
    """Actions·Frontend가 GMS system auth와 SSL truststore를 함께 사용함을 검증한다."""

    services = _yaml(DATAHUB / "compose.consumer.yml")["services"]
    actions = services["datahub-actions-quickstart"]
    assert actions["environment"]["DATAHUB_GMS_PROTOCOL"] == "https"
    assert actions["environment"]["METADATA_SERVICE_AUTH_ENABLED"] == "true"
    assert "DATAHUB_SYSTEM_CLIENT_SECRET" in actions["environment"]
    assert actions["environment"]["REQUESTS_CA_BUNDLE"] == "/run/secrets/datahub-ca.pem"
    assert actions["environment"]["CURL_CA_BUNDLE"] == "/run/secrets/datahub-ca.pem"
    assert actions["environment"]["KAFKA_BOOTSTRAP_SERVER"] == "broker:29092"
    assert actions["environment"]["SCHEMA_REGISTRY_URL"] == (
        "https://datahub-gms:8443/schema-registry/api/"
    )
    assert actions["environment"]["DATAHUB_ACTIONS_INGESTION_EXECUTOR_ENABLED"] == (
        "false"
    )

    for config_name in ("doc_propagation_action.yaml", "executor.yaml"):
        config = _yaml(DATAHUB / "actions" / config_name)
        connection = config["source"]["config"]["connection"]
        assert connection["bootstrap"] == "${KAFKA_BOOTSTRAP_SERVER:-localhost:9092}"
        assert connection["schema_registry_url"] == (
            "${SCHEMA_REGISTRY_URL:-http://localhost:8081}"
        )
        assert connection["schema_registry_config"]["ssl.ca.location"] == (
            "${DATAHUB_TLS_CA_FILE:-/run/secrets/datahub-ca.pem}"
        )
        assert config["datahub"]["server"].startswith(
            "${DATAHUB_GMS_PROTOCOL:-http}://"
        )
    executor = _yaml(DATAHUB / "actions" / "executor.yaml")
    assert executor["enabled"] == (
        "${DATAHUB_ACTIONS_INGESTION_EXECUTOR_ENABLED:-false}"
    )

    frontend = services["frontend-quickstart"]
    assert frontend["environment"]["DATAHUB_GMS_USE_SSL"] == "true"
    assert frontend["environment"]["METADATA_SERVICE_AUTH_ENABLED"] == "true"
    assert "DATAHUB_GMS_SSL_TRUSTSTORE_PATH" in frontend["environment"]
    assert frontend["ports"][0].startswith("127.0.0.1:")


def test_runtime_and_publishers_use_separate_service_credentials() -> None:
    """조회 runtime과 mutation 작업자가 별도 token·actor를 쓰면서 TLS 계약을 공유하는지 검증한다."""

    backend = _yaml(ROOT / "app" / "backend" / "compose.fragment.yml")["services"][
        "backend"
    ]
    ingestion = _yaml(DATAHUB / "compose.ingestion.yml")["services"][
        "datahub-ingestion"
    ]
    semantic = _yaml(DATAHUB / "compose.semantic-search.yml")["services"][
        "dataset-semantic-content-bootstrap"
    ]
    for service in (backend, ingestion, semantic):
        environment = service["environment"]
        assert environment["DATAHUB_GMS_URL"] == "https://datahub-gms:8443"
        assert environment["DATAHUB_TLS_CA_FILE"] == "/run/secrets/datahub-ca.pem"
        assert any("DATAHUB_TLS_CA_HOST_FILE" in item for item in service["volumes"])
    assert "DATAHUB_READ_API_TOKEN" in backend["environment"]
    assert "DATAHUB_READ_ACTOR_URN" in backend["environment"]
    assert backend["environment"]["DATAHUB_CATALOG_TTL_SECONDS"] == (
        "${DATAHUB_CATALOG_TTL_SECONDS:-86400}"
    )
    assert backend["environment"]["RELEASE_READINESS_CACHE_TTL_SECONDS"] == (
        "${RELEASE_READINESS_CACHE_TTL_SECONDS:-86400}"
    )
    assert backend["environment"]["DATAHUB_SEARCH_MODE"] == (
        "${DATAHUB_SEARCH_MODE:-datahub_lexical}"
    )
    for publisher in (ingestion, semantic):
        assert "DATAHUB_PUBLISH_API_TOKEN" in publisher["environment"]
        assert "DATAHUB_READ_API_TOKEN" not in publisher["environment"]

    for recipe_path in DATAHUB.joinpath("recipes").glob("*.runtime.yml"):
        sink = _yaml(recipe_path)["sink"]["config"]
        assert sink == {
            "server": "${DATAHUB_GMS_URL}",
            "token": "${DATAHUB_PUBLISH_API_TOKEN}",
            "ca_certificate_path": "${DATAHUB_TLS_CA_FILE}",
        }


def test_connection_settings_hide_token_and_reject_plain_http() -> None:
    """canonical 설정 객체가 token을 표현하지 않고 평문 origin을 거부하는지 확인한다."""

    ca_file = Path(__file__).resolve()
    token = "not-a-real-secret"
    settings = DataHubConnectionSettings.from_env(
        {
            "DATAHUB_GMS_URL": "https://datahub.example.test:8443",
            "DATAHUB_READ_API_TOKEN": token,
            "DATAHUB_READ_ACTOR_URN": "urn:li:corpuser:service_catalog_reader",
            "DATAHUB_TLS_CA_FILE": str(ca_file.resolve()),
        }
    )
    assert token not in repr(settings)
    assert settings.authorization_headers == {"Authorization": f"Bearer {token}"}

    with pytest.raises(DataHubConnectionError, match="HTTPS"):
        DataHubConnectionSettings.from_env(
            {
                "DATAHUB_GMS_URL": "http://datahub.example.test:8080",
                "DATAHUB_READ_API_TOKEN": token,
                "DATAHUB_READ_ACTOR_URN": "urn:li:corpuser:service_catalog_reader",
                "DATAHUB_TLS_CA_FILE": str(ca_file.resolve()),
            }
        )


def test_legacy_token_names_and_secret_cli_options_are_absent() -> None:
    """과거 token alias나 argv credential 옵션이 다시 들어오는 회귀를 차단한다."""

    production_files = [
        *DATAHUB.glob("*.py"),
        *DATAHUB.glob("*.yml"),
        *DATAHUB.glob("*.md"),
        *DATAHUB.joinpath("recipes").glob("*.yml"),
        ROOT / "app" / "backend" / "compose.fragment.yml",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in production_files)
    assert "DATAHUB_GMS_TOKEN" not in combined
    assert re.search(r"\bDATAHUB_TOKEN\b", combined) is None
    assert "--datahub-token" not in combined
    assert "--token" not in combined
