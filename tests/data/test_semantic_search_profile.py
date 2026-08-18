import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import httpx
import yaml


ROOT = Path(__file__).resolve().parents[2]
DATAHUB_DIR = ROOT / "infrastructure/database/datahub"
ENV_EXAMPLE = ROOT / "infrastructure/database/.env.example"
MODEL_DIGEST = "sha256:0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"
DATASET_URN = "urn:li:dataset:(urn:li:dataPlatform:trino,analytics.events,PROD)"
SEMANTIC_INDEX = "datasetindex_v2_semantic"
sys.path.insert(0, str(DATAHUB_DIR))

from verify_semantic_search import (  # noqa: E402
    NOT_VERIFIED,
    SEMANTIC_SEARCH_QUERY,
    VERIFIED,
    VerificationConfig,
    VerificationError,
    verify_live,
)
from semantic_compose_evidence import validate_compose_inspection  # noqa: E402


class ComposeLoader(yaml.SafeLoader):
    """Parse Compose override tags without reimplementing Compose merging."""


def _compose_override(loader: ComposeLoader, node: yaml.Node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


ComposeLoader.add_constructor("!override", _compose_override)


class SemanticSearchComposeContractTest(unittest.TestCase):
    def document(self) -> dict:
        path = DATAHUB_DIR / "compose.semantic-search.yml"
        return yaml.load(path.read_text(encoding="utf-8"), Loader=ComposeLoader)

    def test_overlay_enables_pinned_local_elasticsearch_and_model_contract(self):
        services = self.document()["services"]
        elasticsearch = services["semantic-elasticsearch"]
        self.assertEqual(["semantic-search"], elasticsearch["profiles"])
        self.assertEqual(
            "docker.elastic.co/elasticsearch/elasticsearch:8.18.2@sha256:"
            "7506a97309af9fa3221ce1d60068223aabb613afe96c1d3a0add5f6bb0e0b61c",
            elasticsearch["image"],
        )
        self.assertEqual("false", elasticsearch["environment"]["xpack.security.enabled"])
        self.assertTrue(elasticsearch["ports"][0].startswith("127.0.0.1:"))

        ollama = services["ollama"]
        self.assertIn("@sha256:", ollama["image"])
        self.assertTrue(ollama["ports"][0].startswith("127.0.0.1:"))
        bootstrap = services["ollama-model-bootstrap"]
        self.assertEqual(
            ["pull", "${OLLAMA_EMBEDDING_MODEL:?set OLLAMA_EMBEDDING_MODEL}"],
            bootstrap["command"],
        )
        self.assertIn("OLLAMA_EMBEDDING_MODEL_DIGEST", bootstrap["environment"])
        env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn(f"OLLAMA_EMBEDDING_MODEL_DIGEST={MODEL_DIGEST}", env_text)

    def test_datahub_processes_receive_exact_v1_7_flags_and_ordering(self):
        services = self.document()["services"]
        expected = {
            "SEARCH_SERVICE_SEMANTIC_SEARCH_ENABLED": "true",
            "ELASTICSEARCH_SEMANTIC_SEARCH_ENABLED": "true",
            "ELASTICSEARCH_SEMANTIC_SEARCH_ENTITIES": "document,dataset",
            "EMBEDDING_PROVIDER_TYPE": "local",
            "LOCAL_EMBEDDING_ENDPOINT": "http://ollama:11434/v1/embeddings",
            "LOCAL_EMBEDDING_MODEL": "${OLLAMA_EMBEDDING_MODEL:?set OLLAMA_EMBEDDING_MODEL}",
            "LOCAL_EMBEDDING_VECTOR_DIMENSION": "768",
            "ELASTICSEARCH_SHIM_ENABLED": "true",
            "ELASTICSEARCH_SHIM_ENGINE_TYPE": "ELASTICSEARCH_8",
        }
        for service_name in ("system-update-quickstart", "datahub-gms-quickstart"):
            environment = services[service_name]["environment"]
            for key, value in expected.items():
                self.assertEqual(value, environment[key])
            self.assertEqual("elasticsearch", environment["ELASTICSEARCH_IMPLEMENTATION"])
        update_dependencies = services["system-update-quickstart"]["depends_on"]
        self.assertIn("ollama-model-bootstrap", update_dependencies)
        self.assertNotIn("opensearch", update_dependencies)
        self.assertEqual(["legacy-search"], services["opensearch"]["profiles"])
        producer = services["dataset-semantic-content-bootstrap"]
        self.assertEqual(
            {
                "datahub-gms-quickstart",
                "datahub-service-token-check",
                "datahub-ingestion",
                "ollama-model-bootstrap",
                "semantic-elasticsearch",
            },
            set(producer["depends_on"]),
        )
        self.assertEqual(
            ["python", "publish_dataset_semantic_content.py"], producer["entrypoint"]
        )
        self.assertEqual(
            "infrastructure/database/datahub/Dockerfile.semantic-content",
            producer["build"]["dockerfile"],
        )
        dockerfile = (DATAHUB_DIR / "Dockerfile.semantic-content").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "python:3.13.7-slim-bookworm@sha256:"
            "adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d",
            dockerfile,
        )
        requirements = (
            DATAHUB_DIR / "requirements.semantic-content.txt"
        ).read_text(encoding="utf-8").splitlines()
        self.assertTrue(requirements)
        self.assertTrue(all("==" in line for line in requirements))
        for consumer in ("datahub-actions-quickstart", "frontend-quickstart"):
            self.assertIn(
                "dataset-semantic-content-bootstrap", services[consumer]["depends_on"]
            )
        ingestion = services["datahub-ingestion"]
        self.assertEqual(
            ["metadata-ingestion", "semantic-search"], ingestion["profiles"]
        )
        self.assertIn("*.runtime.yml", ingestion["command"][0])
        self.assertIn("trino", ingestion["depends_on"])
        self.assertNotIn("trino-analytics-keeper", ingestion["depends_on"])

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI is unavailable")
    def test_root_semantic_merge_excludes_legacy_engine(self):
        command = [
            "docker", "compose", "--env-file", str(ENV_EXAMPLE),
            "-f", str(ROOT / "compose.yml"),
            "-f", str(DATAHUB_DIR / "compose.semantic-search.yml"),
            "--profile", "full", "--profile", "semantic-search",
            "config", "--format", "json",
        ]
        completed = subprocess.run(command, check=True, capture_output=True)
        services = json.loads(completed.stdout.decode("utf-8-sig"))["services"]
        self.assertNotIn("opensearch", services)
        update = services["system-update-quickstart"]
        self.assertEqual(
            {"kafka-broker", "mysql", "ollama-model-bootstrap", "semantic-elasticsearch"},
            set(update["depends_on"]),
        )
        self.assertEqual("semantic-elasticsearch", update["environment"]["ELASTICSEARCH_HOST"])
        self.assertIn("dataset-semantic-content-bootstrap", services)
        self.assertIn("datahub-ingestion", services)
        self.assertIn(
            "datahub-ingestion",
            services["dataset-semantic-content-bootstrap"]["depends_on"],
        )
        self.assertIn(
            "dataset-semantic-content-bootstrap",
            services["datahub-actions-quickstart"]["depends_on"],
        )

    def test_standard_start_and_refresh_keep_metadata_independent_from_semantic(self):
        start = (ROOT / "infrastructure/database/scripts/start.ps1").read_text(
            encoding="utf-8"
        )
        provision = start.index("provision-source-postgres.sh")
        dependent_start = start.index(
            "datahub-actions-quickstart frontend-quickstart", provision
        )
        self.assertLess(provision, dependent_start)
        refresh = (DATAHUB_DIR / "ingest_runtime_catalog.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("datahub-ingestion", refresh)
        self.assertIn("docker wait", refresh)
        self.assertIn("BASE_METADATA_INGESTED", refresh)
        self.assertNotIn("dataset-semantic-content-bootstrap", refresh)
        self.assertNotIn("ollama", refresh.lower())


class SemanticSearchVerifierContractTest(unittest.IsolatedAsyncioTestCase):
    def config(self, **changes) -> VerificationConfig:
        values = {
            "datahub_url": "http://127.0.0.1:18081",
            "elasticsearch_url": "http://127.0.0.1:19200",
            "ollama_url": "http://127.0.0.1:11434",
            "probe_query": "generic governed dataset",
            "expected_model_digest": MODEL_DIGEST,
        }
        values.update(changes)
        return VerificationConfig(**values)

    @staticmethod
    def success_handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 11434 and request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": "nomic-embed-text:latest", "digest": MODEL_DIGEST}]},
            )
        if request.url.port == 11434 and request.url.path == "/v1/embeddings":
            return httpx.Response(
                200,
                json={"model": "nomic-embed-text", "data": [{"embedding": [0.125] * 768}]},
            )
        if request.url.port == 19200 and request.url.path == "/":
            return httpx.Response(
                200,
                json={
                    "tagline": "You Know, for Search",
                    "cluster_uuid": "approved-semantic-cluster",
                    "version": {"number": "8.18.2", "build_flavor": "default"},
                },
            )
        if request.url.port == 19200 and request.url.path == f"/_resolve/index/{SEMANTIC_INDEX}":
            return httpx.Response(
                200,
                json={
                    "indices": [{"name": SEMANTIC_INDEX, "attributes": ["open"]}],
                    "aliases": [],
                    "data_streams": [],
                },
            )
        if request.url.port == 19200 and request.url.path == f"/{SEMANTIC_INDEX}/_mapping":
            vector = {
                "type": "dense_vector", "dims": 768, "index": True, "similarity": "cosine"
            }
            return httpx.Response(
                200,
                json={
                    SEMANTIC_INDEX: {
                        "mappings": {
                            "properties": {
                                "embeddings": {
                                    "properties": {
                                        "nomic_embed_text": {
                                            "properties": {
                                                "chunks": {
                                                    "type": "nested",
                                                    "properties": {"vector": vector},
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            )
        if request.url.port == 19200 and request.url.path == f"/_cluster/health/{SEMANTIC_INDEX}":
            return httpx.Response(
                200,
                json={
                    "status": "yellow", "timed_out": False, "relocating_shards": 0,
                    "initializing_shards": 0, "number_of_pending_tasks": 0,
                },
            )
        if request.url.port == 19200 and request.url.path == "/_tasks":
            return httpx.Response(200, json={"nodes": {}})
        if request.url.port == 19200 and request.url.path == f"/{SEMANTIC_INDEX}/_count":
            return httpx.Response(200, json={"count": 17})
        if request.url.port == 19200 and request.url.path == f"/{SEMANTIC_INDEX}/_search":
            return httpx.Response(
                200,
                json={
                    "timed_out": False,
                    "_shards": {"total": 1, "successful": 1, "failed": 0},
                    "hits": {"hits": [{"_source": {"urn": DATASET_URN}}]},
                },
            )
        if request.url.port == 18081 and request.url.path == "/config":
            return httpx.Response(
                200,
                json={
                    "versions": {
                        "acryldata/datahub": {
                            "version": "v1.7.0",
                            "commit": "7f81ccbfe27b9acc947f5f600fcf9ddb72138a80",
                        }
                    }
                },
            )
        if request.url.port == 18081 and request.url.path == "/api/graphql":
            payload = json.loads(request.content)
            if payload["query"] != SEMANTIC_SEARCH_QUERY:
                return httpx.Response(400, json={"message": "unexpected operation"})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "semanticSearchAcrossEntities": {
                            "searchResults": [
                                {
                                    "entity": {"urn": DATASET_URN, "type": "DATASET"},
                                    "matchedFields": [{"name": "description", "value": "events"}],
                                }
                            ]
                        }
                    }
                },
            )
        return httpx.Response(404, json={"message": "not found"})

    async def verify_with(self, handler=None):
        active_handler = handler or self.success_handler

        async def compose_probe(project: str, datahub_url: str, elasticsearch_url: str):
            self.assertEqual("answervice", project)
            self.assertEqual("http://127.0.0.1:18081", datahub_url)
            self.assertEqual("http://127.0.0.1:19200", elasticsearch_url)
            return {
                "compose_project": project,
                "shared_network": "answervice_datahub-network",
                "effective_search_host": "semantic-elasticsearch",
            }

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(active_handler), trust_env=False
        ) as client:
            return await verify_live(
                self.config(), client=client, compose_probe=compose_probe
            )

    async def test_all_contract_evidence_is_required_for_verified(self):
        result = await self.verify_with()
        self.assertEqual(VERIFIED, result["status"])
        self.assertTrue(all(check["verified"] for check in result["checks"].values()))
        binding = result["checks"]["deployment_binding"]["evidence"]
        self.assertEqual(SEMANTIC_INDEX, binding["semantic_index"])
        self.assertEqual(1, binding["bound_dataset_count"])

    async def test_wrong_model_digest_never_reports_verified(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.port == 11434 and request.url.path == "/api/tags":
                return httpx.Response(
                    200, json={"models": [{"name": "nomic-embed-text", "digest": "sha256:" + "0" * 64}]}
                )
            return self.success_handler(request)

        result = await self.verify_with(handler)
        self.assertEqual(NOT_VERIFIED, result["status"])
        self.assertFalse(result["checks"]["embedding"]["verified"])

    async def test_opensearch_is_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.port == 19200 and request.url.path == "/":
                return httpx.Response(
                    200,
                    json={
                        "tagline": "The OpenSearch Project: https://opensearch.org/",
                        "cluster_uuid": "legacy",
                        "version": {"number": "2.19.3", "distribution": "opensearch"},
                    },
                )
            return self.success_handler(request)

        result = await self.verify_with(handler)
        self.assertEqual(NOT_VERIFIED, result["status"])
        self.assertFalse(result["checks"]["elasticsearch"]["verified"])

    async def test_active_reindex_never_reports_verified(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.port == 19200 and request.url.path == "/_tasks":
                return httpx.Response(200, json={"nodes": {"node": {"tasks": {"node:1": {}}}}})
            return self.success_handler(request)

        result = await self.verify_with(handler)
        self.assertEqual(NOT_VERIFIED, result["status"])
        self.assertFalse(result["checks"]["deployment_binding"]["verified"])

    async def test_graphql_result_without_vector_document_never_reports_verified(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.port == 19200 and request.url.path == f"/{SEMANTIC_INDEX}/_search":
                return httpx.Response(
                    200,
                    json={
                        "timed_out": False,
                        "_shards": {"total": 1, "successful": 1, "failed": 0},
                        "hits": {"hits": []},
                    },
                )
            return self.success_handler(request)

        result = await self.verify_with(handler)
        self.assertEqual(NOT_VERIFIED, result["status"])
        self.assertFalse(result["checks"]["deployment_binding"]["verified"])

    async def test_missing_digest_is_rejected_before_network_io(self):
        with self.assertRaisesRegex(VerificationError, "full sha256"):
            await verify_live(self.config(expected_model_digest=""))

    async def test_non_loopback_endpoint_is_rejected_before_network_io(self):
        with self.assertRaisesRegex(VerificationError, "loopback"):
            await verify_live(self.config(datahub_url="https://metadata.example.test"))


class SemanticComposeInspectionTest(unittest.TestCase):
    @staticmethod
    def document(service: str, ports: dict, aliases: list[str], environment=None):
        return {
            "State": {"Running": True},
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "answervice",
                    "com.docker.compose.service": service,
                },
                "Env": [f"{key}={value}" for key, value in (environment or {}).items()],
            },
            "NetworkSettings": {
                "Ports": ports,
                "Networks": {
                    "answervice_datahub-network": {"Aliases": aliases}
                },
            },
        }

    def documents(self):
        environment = {
            "ELASTICSEARCH_HOST": "semantic-elasticsearch",
            "ELASTICSEARCH_IMPLEMENTATION": "elasticsearch",
            "ELASTICSEARCH_PORT": "9200",
            "ELASTICSEARCH_SHIM_ENABLED": "true",
            "ELASTICSEARCH_SHIM_ENGINE_TYPE": "ELASTICSEARCH_8",
            "SEARCH_SERVICE_SEMANTIC_SEARCH_ENABLED": "true",
            "ELASTICSEARCH_SEMANTIC_SEARCH_ENABLED": "true",
            "ELASTICSEARCH_SEMANTIC_SEARCH_ENTITIES": "document,dataset",
        }
        return [
            self.document(
                "datahub-gms-quickstart",
                {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18081"}]},
                ["datahub-gms-quickstart", "datahub-gms"],
                environment,
            ),
            self.document(
                "semantic-elasticsearch",
                {"9200/tcp": [{"HostIp": "127.0.0.1", "HostPort": "19200"}]},
                ["semantic-elasticsearch"],
            ),
        ]

    def test_inspection_binds_host_endpoints_and_gms_dns_target(self):
        evidence = validate_compose_inspection(
            self.documents(),
            "answervice",
            "https://127.0.0.1:18081",
            "http://127.0.0.1:19200",
        )
        self.assertEqual("semantic-elasticsearch", evidence["effective_search_host"])

    def test_opensearch_effective_host_is_rejected(self):
        documents = self.documents()
        documents[0]["Config"]["Env"] = [
            "ELASTICSEARCH_HOST=opensearch"
            if item.startswith("ELASTICSEARCH_HOST=") else item
            for item in documents[0]["Config"]["Env"]
        ]
        with self.assertRaisesRegex(VerificationError, "environment has drifted"):
            validate_compose_inspection(
                documents,
                "answervice",
                "https://127.0.0.1:18081",
                "http://127.0.0.1:19200",
            )


if __name__ == "__main__":
    unittest.main()
