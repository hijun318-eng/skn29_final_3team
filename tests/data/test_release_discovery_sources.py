import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure/database/datahub"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DATAHUB))

from release_datahub import DataHubDiscoveryClient  # noqa: E402
from release_scope import (  # noqa: E402
    ReleaseScope,
    ReleaseScopeError,
    load_release_scopes,
    load_release_scopes_with_serving,
)
from release_trino import TrinoDiscoveryError, TrinoMetadataClient  # noqa: E402
from src.data.governance_contract import datahub_schema_readback_sha1  # noqa: E402
from author_semantic_catalog import (  # noqa: E402
    author_and_verify,
    parse_args as parse_authoring_args,
)
from build_release_bundle import (  # noqa: E402
    async_main as build_bundle_main,
    parse_args as parse_bundle_args,
)
import preflight_policy_decisions as preflight_module  # noqa: E402
from preflight_policy_decisions import write_check_result  # noqa: E402


class RecipePath:
    def __init__(self, name, text):
        self.name = name
        self._text = text

    def resolve(self):
        return self

    def read_text(self, **_kwargs):
        return self._text

    def __str__(self):
        return self.name


def _recipe(source_type, *, database=True, schema=True):
    config = {
        "platform_instance": "${PLATFORM_INSTANCE}",
        "env": "${DATASET_ENV}",
    }
    if database:
        config["database"] = "${SOURCE_DATABASE}"
    if schema:
        config["schema_pattern"] = {"allow": ["${SOURCE_SCHEMA}"]}
    return {
        "source": {"type": source_type, "config": config},
        "sink": {"type": "datahub-rest", "config": {"server": "${GMS_URL}"}},
    }


def test_runtime_recipe_scopes_are_environment_backed_and_generic():
    import yaml

    source = RecipePath("aurora.runtime.yml", yaml.safe_dump(_recipe("postgres")))
    serving_recipe = _recipe("trino")
    serving_config = serving_recipe["source"]["config"]
    serving_config["platform_instance"] = "${SERVING_INSTANCE}"
    serving_config["database"] = "${SERVING_CATALOG}"
    serving_config["schema_pattern"]["allow"] = ["${SERVING_SCHEMA}"]
    serving = RecipePath("lens.runtime.yml", yaml.safe_dump(serving_recipe))
    environment = {
        "PLATFORM_INSTANCE": "instance_a",
        "DATASET_ENV": "PROD",
        "SOURCE_DATABASE": "lake",
        "SOURCE_SCHEMA": "curated",
        "SERVING_INSTANCE": "instance_b",
        "SERVING_CATALOG": "mart",
        "SERVING_SCHEMA": "published",
    }
    scopes = load_release_scopes((source, serving), environment)

    assert scopes == (
        ReleaseScope("aurora", "curated", "instance_a", "lake.curated", "PROD"),
        ReleaseScope("mart", "published", "instance_b", "mart.published", "PROD"),
    )


def test_static_or_unresolved_recipe_scope_is_rejected():
    import yaml

    value = _recipe("postgres")
    value["source"]["config"]["schema_pattern"]["allow"] = ["fixed_schema"]
    path = RecipePath("source.runtime.yml", yaml.safe_dump(value))
    with pytest.raises(ReleaseScopeError, match="runtime environment"):
        load_release_scopes(
            (path,),
            {
                "PLATFORM_INSTANCE": "instance_a",
                "DATASET_ENV": "PROD",
                "SOURCE_DATABASE": "lake",
            },
        )


def test_dynamic_serving_ingestion_accepts_only_explicit_approval_schema():
    """동적 수집 recipe는 유지하되 승인 후보는 호출자가 고른 한 schema로 제한한다."""

    import yaml

    source = RecipePath("aurora.runtime.yml", yaml.safe_dump(_recipe("postgres")))
    serving_recipe = _recipe("trino", schema=False)
    serving_recipe["source"]["config"]["platform_instance"] = "${SERVING_INSTANCE}"
    serving_recipe["source"]["config"]["database"] = "${SERVING_CATALOG}"
    serving_recipe["source"]["config"]["schema_pattern"] = {
        "deny": ["^information_schema$"]
    }
    serving = RecipePath("serving.runtime.yml", yaml.safe_dump(serving_recipe))

    scopes = load_release_scopes_with_serving(
        (source, serving),
        {
            "PLATFORM_INSTANCE": "instance_a",
            "DATASET_ENV": "PROD",
            "SOURCE_DATABASE": "lake",
            "SOURCE_SCHEMA": "curated",
            "SERVING_INSTANCE": "instance_b",
            "SERVING_CATALOG": "serving",
        },
        "analytics_v4_3",
    )

    assert scopes[-1] == ReleaseScope(
        "serving",
        "analytics_v4_3",
        "instance_b",
        "serving.analytics_v4_3",
        "PROD",
    )


def test_trino_inventory_discovers_catalog_then_point_looks_up_columns():
    statements = []
    query_counter = 0

    def handler(request):
        nonlocal query_counter
        query_counter += 1
        assert request.headers["x-trino-user"] == "metadata_reader"
        assert request.headers["authorization"].startswith("Basic ")
        statement = request.content.decode("utf-8")
        statements.append(statement)
        if '"system"."metadata"."catalogs"' in statement:
            names = ("catalog_name", "connector_name")
            rows = [["aurora", "postgresql"], ["system", "system"]]
        elif '"information_schema"."tables"' in statement:
            names = ("table_name", "table_type")
            rows = [["events", "BASE TABLE"]]
        elif '"information_schema"."columns"' in statement:
            names = ("ordinal_position", "column_name", "data_type", "is_nullable")
            rows = [[1, "event_id", "bigint", "NO"], [2, "observed_at", "date", "YES"]]
        else:
            raise AssertionError(statement)
        return httpx.Response(
            200,
            json={
                "id": f"query-{query_counter}",
                "stats": {"state": "FINISHED"},
                "columns": [{"name": name} for name in names],
                "data": rows,
            },
        )

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as http:
            async with TrinoMetadataClient(
                "https://trino.test", "metadata_reader", "test-password", http=http
            ) as client:
                return await client.discover(
                    (ReleaseScope("aurora", "curated", "instance_a", "lake.curated", "PROD"),)
                )

    inventory = asyncio.run(exercise())

    assert len(inventory.relations) == 1
    assert inventory.relations[0].fqn == "aurora.curated.events"
    assert inventory.column_count == 2
    assert len(inventory.query_ids) == 3
    assert any("table_schema" in statement and "curated" in statement for statement in statements)
    assert any("table_name" in statement and "events" in statement for statement in statements)


def test_trino_inventory_fails_when_runtime_catalog_is_absent():
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "id": "query-catalogs",
                "stats": {"state": "FINISHED"},
                "columns": [{"name": "catalog_name"}, {"name": "connector_name"}],
                "data": [["another", "postgresql"]],
            },
        )

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as http:
            async with TrinoMetadataClient(
                "https://trino.test", "metadata_reader", "test-password", http=http
            ) as client:
                await client.discover(
                    (ReleaseScope("aurora", "curated", "instance_a", "lake.curated", "PROD"),)
                )

    with pytest.raises(TrinoDiscoveryError, match="unavailable"):
        asyncio.run(exercise())


def test_trino_discovery_rejects_insecure_or_unverified_owned_transport():
    """운영 metadata client는 HTTP와 CA 없는 owned HTTPS를 모두 거절한다."""

    with pytest.raises(ValueError, match="configuration"):
        TrinoMetadataClient("http://trino.test", "reader", "test-password")
    with pytest.raises(ValueError, match="CA file"):
        TrinoMetadataClient("https://trino.test", "reader", "test-password")


@pytest.mark.parametrize("parser", (parse_authoring_args, parse_bundle_args))
def test_trino_password_cannot_be_supplied_on_command_line(parser):
    """authoring 명령은 process argv에 Trino password를 싣는 옵션을 노출하지 않는다."""

    with pytest.raises(SystemExit):
        parser(["--trino-password", "must-not-enter-argv"])


def test_authoring_commands_fail_before_network_when_password_env_is_missing(
    monkeypatch,
):
    """두 authoring entrypoint 모두 password env 누락을 network 전에 차단한다."""

    monkeypatch.setenv("TRINO_DATAHUB_USER", "datahub_ingestion")
    monkeypatch.delenv("TRINO_DATAHUB_PASSWORD", raising=False)
    monkeypatch.setenv("TRINO_TLS_CA_HOST_FILE", "C:/external/not-read-before-password.pem")
    monkeypatch.setenv("DATAHUB_PUBLISH_ACTOR_URN", "urn:li:corpuser:publisher")

    with pytest.raises(ValueError, match="credentials"):
        asyncio.run(
            author_and_verify(
                {},
                parse_authoring_args(
                    ["--check", "--serving-schema", "analytics_v4_3"]
                ),
            )
        )
    with pytest.raises(ValueError, match="credentials"):
        asyncio.run(build_bundle_main(["--serving-schema", "analytics_v4_3"]))


def test_check_output_is_external_and_never_overwritten(
    tmp_path,
    monkeypatch,
):
    """서명 대상 byte는 repository 밖 새 파일에만 한 번 기록된다."""

    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(preflight_module, "ROOT", repository)
    output = tmp_path / "publication-check.json"
    result = {"status": "CHECKED", "policy": {}, "publication_check": {}}

    write_check_result(output, result)

    assert json.loads(output.read_text(encoding="utf-8")) == result
    with pytest.raises(FileExistsError):
        write_check_result(output, result)
    with pytest.raises(ValueError, match="outside"):
        write_check_result(repository / "check.json", result)


def test_datahub_discovery_filters_by_platform_instance_before_detail_lookup():
    target = "urn:li:dataset:(urn:li:dataPlatform:postgres,instance_a.lake.curated.events,PROD)"
    unrelated = "urn:li:dataset:(urn:li:dataPlatform:postgres,instance_b.lake.curated.events,PROD)"
    detail_calls = []

    def handler(request):
        body = json.loads(request.content)
        query = body["query"]
        if "ReleaseDatasets" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "searchAcrossEntities": {
                            "start": 0,
                            "count": 2,
                            "total": 2,
                            "searchResults": [
                                {"entity": {"urn": target, "type": "DATASET"}},
                                {"entity": {"urn": unrelated, "type": "DATASET"}},
                            ],
                        }
                    }
                },
            )
        assert "schemaName" not in query
        urn = body["variables"]["urn"]
        detail_calls.append(urn)
        return httpx.Response(
            200,
            json={
                "data": {
                    "dataset": {
                        "urn": urn,
                        "name": "events",
                        "status": {"removed": False, "lifecycleStage": None},
                        "ownership": {"owners": []},
                        "domain": None,
                        "properties": {
                            "name": "events",
                            "qualifiedName": None,
                            "description": None,
                            "customProperties": [],
                        },
                        "schemaMetadata": {
                            "version": 0,
                            "name": "lake.curated.events",
                            "platformUrn": "urn:li:dataPlatform:postgres",
                            # Pinned DataHub connector는 schemaMetadata.hash를 비워 둘 수
                            # 있으므로 실제 field read-back fingerprint가 권위 값이다.
                            "hash": "",
                            "fields": [
                                {
                                    "fieldPath": "event_id",
                                    "nativeDataType": "bigint",
                                    "nullable": False,
                                    "isPartOfKey": True,
                                    "description": None,
                                }
                            ],
                        },
                        "editableSchemaMetadata": {
                            "editableSchemaFieldInfo": [
                                {
                                    "fieldPath": "event_id",
                                    "description": "Curated event identifier.",
                                }
                            ]
                        },
                    }
                }
            },
        )

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as http:
            async with DataHubDiscoveryClient(
                "http://localhost:18081", http=http
            ) as client:
                return await client.discover_datasets(
                    (ReleaseScope("aurora", "curated", "instance_a", "lake.curated", "PROD"),)
                )

    datasets = asyncio.run(exercise())

    assert [dataset.urn for dataset in datasets] == [target]
    assert detail_calls == [target]
    assert datasets[0].schema_hash == datahub_schema_readback_sha1(
        [
            {
                "ordinal_position": 1,
                "name": "event_id",
                "native_type": "bigint",
                "nullable": False,
            }
        ]
    )
    assert datasets[0].fields[0].description == "Curated event identifier."


def test_glossary_discovery_uses_rest_status_and_live_lifecycle_definition():
    """v1.7 GraphQL의 null term status를 Rest.li aspect와 lifecycle 목록으로 보완한다."""

    urn = "urn:li:glossaryTerm:revenue"
    lifecycle_urn = "urn:li:lifecycleStageType:approved"

    def handler(request):
        if request.method == "GET":
            assert "aspects=List(status)" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "urn": urn,
                    "aspects": {
                        "status": {
                            "value": {
                                "removed": False,
                                "lifecycleStage": lifecycle_urn,
                            }
                        }
                    },
                },
            )
        body = json.loads(request.content)
        query = body["query"]
        if "ReleaseLifecycleStages" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "listLifecycleStages": [
                            {
                                "urn": lifecycle_urn,
                                "name": "APPROVED",
                                "description": "approved release",
                            }
                        ]
                    }
                },
            )
        assert "ReleaseGlossaryTerm" in query
        return httpx.Response(
            200,
            json={
                "data": {
                    "glossaryTerm": {
                        "urn": urn,
                        "exists": True,
                        "status": None,
                        "ownership": {
                            "owners": [
                                {
                                    "owner": {
                                        "__typename": "CorpGroup",
                                        "urn": "urn:li:corpGroup:stewards",
                                        "name": "stewards",
                                        "info": {
                                            "displayName": "Stewards",
                                            "description": "owners",
                                        },
                                    }
                                }
                            ]
                        },
                        "domain": {
                            "domain": {
                                "urn": "urn:li:domain:finance",
                                "properties": {
                                    "name": "Finance",
                                    "description": "finance domain",
                                },
                            }
                        },
                        "glossaryTermInfo": {
                            "name": "Revenue",
                            "description": "recognized revenue",
                            "customProperties": [],
                        },
                    }
                }
            },
        )

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as http:
            async with DataHubDiscoveryClient(
                "http://localhost:18081", http=http
            ) as client:
                return await client.discover_terms((urn,))

    terms = asyncio.run(exercise())

    assert len(terms) == 1
    assert terms[0].removed is False
    assert terms[0].lifecycle is not None
    assert terms[0].lifecycle.urn == lifecycle_urn
    assert terms[0].lifecycle.name == "APPROVED"
