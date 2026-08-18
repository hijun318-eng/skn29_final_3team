import json
import os
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import httpx


ROOT = Path(__file__).resolve().parents[2]
DATAHUB_DIR = ROOT / "infrastructure/database/datahub"
sys.path.insert(0, str(DATAHUB_DIR))

from dataset_semantic_clients import DATASET_QUERY, SEARCH_QUERY, TERM_QUERY  # noqa: E402
from dataset_semantic_contract import (  # noqa: E402
    EXPECTED_MODEL_KEY,
    SEMANTIC_INDEX,
    SemanticContentError,
)
from publish_dataset_semantic_content import (  # noqa: E402
    PUBLISHED,
    PublicationConfig,
    _parser,
    publish_live,
)
from verify_semantic_search import VERIFIED, VerificationConfig, verify_live  # noqa: E402


MODEL_DIGEST = "sha256:0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"
URN_ONE = "urn:li:dataset:(urn:li:dataPlatform:trino,live.sales,PROD)"
URN_TWO = "urn:li:dataset:(urn:li:dataPlatform:trino,live.customers,PROD)"
TERM_URN = "urn:li:glossaryTerm:Revenue"


class ProducerTransport:
    def __init__(self) -> None:
        self.aspects = {
            URN_ONE: {
                "embeddings": {
                    "other_model": {
                        "modelVersion": "approved/other",
                        "generatedAt": 1,
                        "totalChunks": 0,
                        "chunks": [],
                    }
                }
            },
            URN_TWO: None,
        }
        self.proposals = []
        self.embedding_requests = []
        self.bad_digest = False
        self.bad_dimension = False
        self.bad_urn = False

    @staticmethod
    def _dataset(urn: str) -> dict:
        if urn == URN_ONE:
            return {
                "urn": urn,
                "name": "sales",
                "status": {"removed": False},
                "domain": {
                    "domain": {
                        "urn": "urn:li:domain:commerce",
                        "properties": {"name": "Commerce", "description": "상거래 도메인"},
                    }
                },
                "properties": {
                    "name": "Sales facts",
                    "qualifiedName": "live.sales",
                    "description": "승인된 매출 사실 데이터",
                },
                "glossaryTerms": {"terms": [{"term": {"urn": TERM_URN}}]},
                "schemaMetadata": {
                    "fields": [
                        {
                            "fieldPath": "recognized_revenue",
                            "nativeDataType": "decimal(18,2)",
                            "description": "인식 매출",
                            "glossaryTerms": {"terms": [{"term": {"urn": TERM_URN}}]},
                        }
                    ]
                },
            }
        return {
            "urn": urn,
            "name": "customers",
            "status": {"removed": False},
            "domain": None,
            "properties": {
                "name": "Customer profiles",
                "qualifiedName": "live.customers",
                "description": "고객 프로필",
            },
            "glossaryTerms": None,
            "schemaMetadata": None,
        }

    @staticmethod
    def _mapping() -> dict:
        return {
            SEMANTIC_INDEX: {
                "mappings": {
                    "properties": {
                        "embeddings": {
                            "properties": {
                                EXPECTED_MODEL_KEY: {
                                    "properties": {
                                        "chunks": {
                                            "type": "nested",
                                            "properties": {
                                                "vector": {
                                                    "type": "dense_vector",
                                                    "dims": 768,
                                                    "index": True,
                                                    "similarity": "cosine",
                                                }
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

    def _graphql(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body["query"]
        variables = body["variables"]
        if query == SEARCH_QUERY:
            start = variables["input"]["start"]
            urns = [URN_ONE, URN_TWO]
            selected = urns[start : start + variables["input"]["count"]]
            if self.bad_urn and start == 0:
                selected = ["urn:li:chart:wrong"]
            rows = [{"entity": {"urn": urn, "type": "DATASET"}} for urn in selected]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "searchAcrossEntities": {
                            "start": start,
                            "count": len(rows),
                            "total": 2,
                            "searchResults": rows,
                        }
                    }
                },
            )
        if query == DATASET_QUERY:
            urn = variables["urn"]
            return httpx.Response(200, json={"data": {"dataset": self._dataset(urn)}})
        if query == TERM_QUERY:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "glossaryTerm": {
                            "urn": TERM_URN,
                            "exists": True,
                            "status": {"removed": False},
                            "glossaryTermInfo": {
                                "name": "Recognized revenue",
                                "description": "회계 정책에 따라 인식된 매출",
                            },
                        }
                    }
                },
            )
        return httpx.Response(400, json={"message": "unexpected GraphQL query"})

    def _entity_get(self, request: httpx.Request) -> httpx.Response:
        urn = unquote(request.url.path.rsplit("/", 1)[1])
        aspect = self.aspects[urn]
        aspects = {} if aspect is None else {"semanticContent": {"value": aspect}}
        return httpx.Response(200, json={"urn": urn, "aspects": aspects})

    def _proposal(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        proposal = body["proposal"]
        assert body["async"] == "false"
        assert proposal["entityType"] == "dataset"
        assert proposal["changeType"] == "UPSERT"
        assert proposal["aspectName"] == "semanticContent"
        assert proposal["aspect"]["contentType"] == "application/json"
        aspect = json.loads(proposal["aspect"]["value"])
        model = aspect["embeddings"][EXPECTED_MODEL_KEY]
        for chunk in model["chunks"]:
            chunk["vector"] = [
                struct.unpack("!f", struct.pack("!f", value))[0]
                for value in chunk["vector"]
            ]
        self.aspects[proposal["entityUrn"]] = aspect
        self.proposals.append(proposal)
        return httpx.Response(200, json={"value": proposal["entityUrn"]})

    def _ollama(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            digest = "sha256:" + "0" * 64 if self.bad_digest else MODEL_DIGEST
            return httpx.Response(
                200,
                json={"models": [{"name": "nomic-embed-text:latest", "digest": digest}]},
            )
        body = json.loads(request.content)
        self.embedding_requests.append(body)
        dimension = 767 if self.bad_dimension else 768
        return httpx.Response(
            200,
            json={
                "model": "nomic-embed-text",
                "data": [
                    {
                        "index": index,
                        "embedding": [0.123456789 + index] * dimension,
                    }
                    for index, _text in enumerate(body["input"])
                ],
            },
        )

    def _elasticsearch(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/_resolve/index/{SEMANTIC_INDEX}":
            return httpx.Response(
                200,
                json={
                    "indices": [{"name": SEMANTIC_INDEX, "attributes": ["open"]}],
                    "aliases": [],
                },
            )
        if request.url.path == f"/{SEMANTIC_INDEX}/_mapping":
            return httpx.Response(200, json=self._mapping())
        if request.url.path == "/_tasks":
            return httpx.Response(200, json={"nodes": {}})
        if request.url.path == f"/{SEMANTIC_INDEX}/_search":
            requested = json.loads(request.content)["query"]["bool"]["filter"][0]["terms"]["urn"]
            hits = []
            for urn in requested:
                aspect = self.aspects.get(urn)
                embeddings = aspect.get("embeddings") if isinstance(aspect, dict) else None
                if isinstance(embeddings, dict) and EXPECTED_MODEL_KEY in embeddings:
                    hits.append({"_source": {"urn": urn, "embeddings": embeddings}})
            return httpx.Response(
                200,
                json={
                    "timed_out": False,
                    "_shards": {"total": 1, "successful": 1, "failed": 0},
                    "hits": {"hits": hits},
                },
            )
        return httpx.Response(404, json={"message": "unexpected Elasticsearch request"})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.port == 18081 and request.url.path == "/api/graphql":
            return self._graphql(request)
        if request.url.port == 18081 and request.method == "GET":
            return self._entity_get(request)
        if request.url.port == 18081 and request.url.path == "/aspects":
            return self._proposal(request)
        if request.url.port == 11434:
            return self._ollama(request)
        if request.url.port == 19200:
            return self._elasticsearch(request)
        return httpx.Response(404, json={"message": "unexpected endpoint"})


class DatasetSemanticContentProducerContractTest(unittest.IsolatedAsyncioTestCase):
    def config(self) -> PublicationConfig:
        return PublicationConfig(
            datahub_url="http://127.0.0.1:18081",
            ollama_url="http://127.0.0.1:11434",
            elasticsearch_url="http://127.0.0.1:19200",
            model="nomic-embed-text",
            expected_model_digest=MODEL_DIGEST,
            page_size=1,
            embedding_batch_size=2,
        )

    async def run_with(self, transport: ProducerTransport):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), trust_env=False
        ) as http:
            return await publish_live(self.config(), http=http, clock=lambda: 1_808_000_000_123)

    async def test_dynamic_metadata_to_mcp_to_float32_exact_index_binding(self):
        transport = ProducerTransport()
        result = await self.run_with(transport)
        self.assertEqual(PUBLISHED, result["status"])
        self.assertEqual(2, result["dataset_count"])
        self.assertEqual(2, result["updated_dataset_count"])
        self.assertEqual(2, len(transport.proposals))
        first = transport.aspects[URN_ONE]["embeddings"]
        self.assertIn("other_model", first)
        model = first[EXPECTED_MODEL_KEY]
        self.assertIn(MODEL_DIGEST, model["modelVersion"])
        self.assertEqual(768, len(model["chunks"][0]["vector"]))
        self.assertIn("Recognized revenue", model["chunks"][0]["text"])
        second = await self.run_with(transport)
        self.assertEqual(0, second["updated_dataset_count"])
        self.assertEqual(2, second["unchanged_dataset_count"])
        self.assertEqual(2, len(transport.proposals))

    def test_cli_defaults_keep_datahub_credentials_out_of_argv(self):
        environment = {
            "OLLAMA_URL": "http://127.0.0.1:11434",
            "DATAHUB_SEMANTIC_ELASTICSEARCH_URL": "http://127.0.0.1:19200",
            "OLLAMA_EMBEDDING_MODEL": "nomic-embed-text",
            "OLLAMA_EMBEDDING_MODEL_DIGEST": MODEL_DIGEST,
        }
        with patch.dict(os.environ, environment, clear=False):
            args = _parser().parse_args([])
        self.assertFalse(hasattr(args, "datahub_url"))
        self.assertEqual(environment["OLLAMA_URL"], args.ollama_url)
        self.assertEqual(
            environment["DATAHUB_SEMANTIC_ELASTICSEARCH_URL"], args.elasticsearch_url
        )

    async def test_wrong_model_digest_fails_before_any_mcp(self):
        transport = ProducerTransport()
        transport.bad_digest = True
        with self.assertRaisesRegex(SemanticContentError, "artifact"):
            await self.run_with(transport)
        self.assertEqual([], transport.proposals)

    async def test_wrong_vector_dimension_fails_before_any_mcp(self):
        transport = ProducerTransport()
        transport.bad_dimension = True
        with self.assertRaisesRegex(SemanticContentError, "dimension"):
            await self.run_with(transport)
        self.assertEqual([], transport.proposals)

    async def test_non_dataset_search_urn_fails_before_any_mcp(self):
        transport = ProducerTransport()
        transport.bad_urn = True
        with self.assertRaisesRegex(SemanticContentError, "dataset URN"):
            await self.run_with(transport)
        self.assertEqual([], transport.proposals)


@unittest.skipUnless(
    os.getenv("RUN_LIVE_DATAHUB_SEMANTIC_PRODUCER_SMOKE") == "1",
    "explicit live semantic producer smoke is disabled",
)
class DatasetSemanticContentProducerLivePositiveSmoke(unittest.IsolatedAsyncioTestCase):
    async def test_live_publication_and_graphql_semantic_result(self):
        model = os.getenv("OLLAMA_EMBEDDING_MODEL")
        digest = os.getenv("OLLAMA_EMBEDDING_MODEL_DIGEST")
        self.assertTrue(model, "OLLAMA_EMBEDDING_MODEL is required for opted-in live smoke")
        self.assertTrue(digest, "OLLAMA_EMBEDDING_MODEL_DIGEST is required for opted-in live smoke")
        result = await publish_live(
            PublicationConfig(
                datahub_url=os.environ["DATAHUB_GMS_URL"],
                ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
                elasticsearch_url=os.getenv(
                    "DATAHUB_SEMANTIC_ELASTICSEARCH_URL", "http://127.0.0.1:19200"
                ),
                model=model,
                expected_model_digest=digest,
                datahub_token=os.environ["DATAHUB_API_TOKEN"],
                datahub_ca_file=(
                    os.getenv("DATAHUB_TLS_CA_FILE")
                    or os.environ["DATAHUB_TLS_CA_HOST_FILE"]
                ),
            )
        )
        self.assertEqual(PUBLISHED, result["status"])
        verified = await verify_live(
            VerificationConfig(
                datahub_url=os.environ["DATAHUB_GMS_URL"],
                elasticsearch_url="http://127.0.0.1:19200",
                ollama_url="http://127.0.0.1:11434",
                probe_query=result["probe_query"],
                expected_model_digest=digest,
                datahub_token=os.environ["DATAHUB_API_TOKEN"],
                datahub_ca_file=(
                    os.getenv("DATAHUB_TLS_CA_FILE")
                    or os.environ["DATAHUB_TLS_CA_HOST_FILE"]
                ),
            )
        )
        self.assertEqual(VERIFIED, verified["status"])


if __name__ == "__main__":
    unittest.main()
