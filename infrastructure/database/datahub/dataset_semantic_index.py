"""발행된 DataHub dataset semantic content의 Elasticsearch 증거를 검증한다."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote

import httpx

from dataset_semantic_clients import _endpoint, local_base_url
from dataset_semantic_contract import (
    EXPECTED_DIMENSION,
    EXPECTED_MODEL_KEY,
    SEMANTIC_INDEX,
    SemanticContentError,
    indexed_model_fingerprint,
    validated_vector,
)


ELASTICSEARCH_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "::1", "semantic-elasticsearch"}
)


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        response.raise_for_status()
        value = response.json()
    except httpx.HTTPStatusError as exc:
        raise SemanticContentError(
            f"Elasticsearch returned HTTP {exc.response.status_code}"
        ) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise SemanticContentError("Elasticsearch did not return JSON") from exc
    if not isinstance(value, dict):
        raise SemanticContentError("Elasticsearch returned a non-object JSON value")
    return value


class ElasticsearchSemanticClient:
    """정확한 DataHub semantic index를 기다리고 indexed MCP vector를 검증한다."""

    def __init__(
        self,
        base_url: str,
        http: httpx.AsyncClient,
        *,
        timeout_seconds: float,
        convergence_seconds: float,
        poll_seconds: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_seconds <= 0 or convergence_seconds <= 0 or poll_seconds < 0:
            raise SemanticContentError("Elasticsearch time bounds are invalid")
        self.base_url = local_base_url(
            base_url, "Elasticsearch URL", ELASTICSEARCH_HOSTS
        )
        self.http = http
        self.timeout = timeout_seconds
        self.convergence = convergence_seconds
        self.poll_seconds = poll_seconds
        self.sleep = sleep
        self.clock = clock
        self.index_name = SEMANTIC_INDEX

    async def _json(
        self, method: str, path: str, *, body: object | None = None, params: object = None
    ) -> dict[str, Any]:
        try:
            response = await self.http.request(
                method,
                _endpoint(self.base_url, path),
                json=body,
                params=params,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise SemanticContentError("Elasticsearch request timed out") from exc
        except httpx.HTTPError as exc:
            raise SemanticContentError("Elasticsearch request failed") from exc
        return _json_object(response)

    async def require_ready(self) -> None:
        """예상 dense-vector mapping을 가진 구체 index 하나만 허용한다."""

        resolved = await self._json(
            "GET", f"/_resolve/index/{quote(self.index_name, safe='')}"
        )
        direct = [
            item.get("name")
            for item in resolved.get("indices", [])
            if isinstance(item, Mapping)
            and item.get("name") == self.index_name
            and "closed" not in item.get("attributes", [])
        ]
        aliases = [
            target
            for item in resolved.get("aliases", [])
            if isinstance(item, Mapping) and item.get("name") == self.index_name
            for target in item.get("indices", [])
            if isinstance(target, str)
        ]
        targets = sorted(set(direct + aliases))
        if len(targets) != 1:
            raise SemanticContentError("Dataset semantic index does not resolve uniquely")
        self.index_name = targets[0]
        mapping = await self._json(
            "GET", f"/{quote(self.index_name, safe='')}/_mapping"
        )
        try:
            chunks = mapping[self.index_name]["mappings"]["properties"]["embeddings"][
                "properties"
            ][EXPECTED_MODEL_KEY]["properties"]["chunks"]
            vector = chunks["properties"]["vector"]
        except (KeyError, TypeError) as exc:
            raise SemanticContentError("Dataset semantic index mapping is missing") from exc
        if (
            chunks.get("type") != "nested"
            or vector.get("type") != "dense_vector"
            or vector.get("dims") != EXPECTED_DIMENSION
            or vector.get("index") is not True
            or vector.get("similarity") != "cosine"
        ):
            raise SemanticContentError("Dataset semantic vector mapping is incompatible")
        tasks = await self._json(
            "GET", "/_tasks", params={"actions": "*reindex", "detailed": "true"}
        )
        nodes = tasks.get("nodes")
        if not isinstance(nodes, Mapping):
            raise SemanticContentError("Elasticsearch tasks response is malformed")
        if any(
            isinstance(node, Mapping) and bool(node.get("tasks")) for node in nodes.values()
        ):
            raise SemanticContentError("Dataset semantic reindex is still active")

    @staticmethod
    def _indexed_model_matches(actual: object, expected: Mapping[str, Any]) -> bool:
        if not isinstance(actual, Mapping):
            return False
        if (
            actual.get("modelVersion") != expected.get("modelVersion")
            or actual.get("totalChunks") != expected.get("totalChunks")
        ):
            return False
        chunks = actual.get("chunks")
        if not isinstance(chunks, list) or len(chunks) != expected.get("totalChunks"):
            return False
        for position, chunk in enumerate(chunks):
            if not isinstance(chunk, Mapping) or chunk.get("position") != position:
                return False
            try:
                validated_vector(chunk.get("vector"))
            except SemanticContentError:
                return False
        try:
            return indexed_model_fingerprint(actual) == indexed_model_fingerprint(expected)
        except SemanticContentError:
            return False

    async def _indexed_urns(
        self, expected: Mapping[str, Mapping[str, Any]]
    ) -> set[str]:
        urns = list(expected)
        vector_path = f"embeddings.{EXPECTED_MODEL_KEY}.chunks.vector"
        payload = await self._json(
            "POST",
            f"/{quote(self.index_name, safe='')}/_search",
            body={
                "size": len(urns),
                "_source": ["urn", f"embeddings.{EXPECTED_MODEL_KEY}"],
                "query": {
                    "bool": {
                        "filter": [
                            {"terms": {"urn": urns}},
                            {
                                "nested": {
                                    "path": f"embeddings.{EXPECTED_MODEL_KEY}.chunks",
                                    "query": {"exists": {"field": vector_path}},
                                }
                            },
                        ]
                    }
                },
            },
        )
        if payload.get("timed_out") is True:
            raise SemanticContentError("Elasticsearch vector binding timed out")
        shards = payload.get("_shards")
        if not isinstance(shards, Mapping) or shards.get("failed") != 0:
            raise SemanticContentError("Elasticsearch vector binding had shard failures")
        hits_node = payload.get("hits")
        hits = hits_node.get("hits") if isinstance(hits_node, Mapping) else None
        if not isinstance(hits, list):
            raise SemanticContentError("Elasticsearch vector binding hits are malformed")
        matched: set[str] = set()
        for hit in hits:
            source = hit.get("_source") if isinstance(hit, Mapping) else None
            urn = source.get("urn") if isinstance(source, Mapping) else None
            embeddings = source.get("embeddings") if isinstance(source, Mapping) else None
            actual = embeddings.get(EXPECTED_MODEL_KEY) if isinstance(embeddings, Mapping) else None
            if urn in expected and self._indexed_model_matches(actual, expected[urn]):
                matched.add(urn)
        return matched

    async def wait_until_indexed(
        self, expected: Mapping[str, Mapping[str, Any]], batch_size: int
    ) -> None:
        """모든 정확한 MCP fingerprint가 검색될 때까지 제한 시간 안에서 기다린다."""

        if not expected or batch_size < 1:
            raise SemanticContentError("Vector index evidence requires datasets and a batch size")
        items = list(expected.items())
        batches = [
            dict(items[start : start + batch_size])
            for start in range(0, len(items), batch_size)
        ]
        deadline = self.clock() + self.convergence
        while True:
            matched: set[str] = set()
            for batch in batches:
                matched.update(await self._indexed_urns(batch))
            if matched == set(expected):
                return
            if self.clock() >= deadline:
                raise SemanticContentError(
                    "Published dataset semanticContent did not converge in Elasticsearch"
                )
            await self.sleep(self.poll_seconds)
