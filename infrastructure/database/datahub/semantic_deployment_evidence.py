"""DataHub 검색 결과가 active semantic index에서 왔음을 cross-system으로 증명한다."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx


class VerificationError(RuntimeError):
    """live semantic 증거가 없거나 계약을 위반했을 때 발생하는 검증 오류다."""


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _json_object(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        value = response.json()
    except httpx.HTTPStatusError as exc:
        raise VerificationError(f"{label} returned HTTP {exc.response.status_code}") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise VerificationError(f"{label} did not return JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label} returned a non-object JSON value")
    return value


def _active_reindex_tasks(body: dict[str, Any]) -> list[str]:
    active: list[str] = []
    nodes = body.get("nodes", {})
    if not isinstance(nodes, dict):
        raise VerificationError("Elasticsearch tasks response is malformed")
    for node in nodes.values():
        tasks = node.get("tasks", {}) if isinstance(node, dict) else {}
        if not isinstance(tasks, dict):
            raise VerificationError("Elasticsearch tasks response is malformed")
        active.extend(str(task_id) for task_id in tasks)
    return active


async def verify_deployment_binding(
    client: httpx.AsyncClient,
    base_url: str,
    elasticsearch_evidence: dict[str, Any],
    graphql_evidence: dict[str, Any],
) -> dict[str, Any]:
    """DataHub 결과가 검증된 active index와 동일한 배포에서 왔는지 증명한다."""

    index_name = elasticsearch_evidence["semantic_index"]
    encoded_index = quote(index_name, safe="")
    health = _json_object(
        await client.get(_endpoint(base_url, f"/_cluster/health/{encoded_index}")),
        "Elasticsearch semantic index health",
    )
    if health.get("timed_out") is True or health.get("status") not in {"green", "yellow"}:
        raise VerificationError("semantic dataset index is not healthy")
    for field in ("relocating_shards", "initializing_shards", "number_of_pending_tasks"):
        if health.get(field) != 0:
            raise VerificationError("semantic dataset index is still converging")

    tasks = _json_object(
        await client.get(
            _endpoint(base_url, "/_tasks"),
            params={"actions": "*reindex", "detailed": "true"},
        ),
        "Elasticsearch reindex tasks",
    )
    if _active_reindex_tasks(tasks):
        raise VerificationError("semantic dataset reindex is still running")

    vector_path = elasticsearch_evidence["vector_field"]
    chunk_path, separator, field_name = vector_path.rpartition(".")
    if not separator or field_name != "vector":
        raise VerificationError("semantic vector evidence has an invalid field path")
    vector_query = {
        "nested": {
            "path": chunk_path,
            "query": {"exists": {"field": vector_path}},
        }
    }
    vector_count = _json_object(
        await client.post(
            _endpoint(base_url, f"/{encoded_index}/_count"),
            json={"query": vector_query},
        ),
        "Elasticsearch populated vector count",
    ).get("count")
    if not isinstance(vector_count, int) or isinstance(vector_count, bool) or vector_count <= 0:
        raise VerificationError("semantic dataset index has no vector-populated document")

    expected_urns = graphql_evidence["dataset_urns"]
    search = _json_object(
        await client.post(
            _endpoint(base_url, f"/{encoded_index}/_search"),
            json={
                "size": len(expected_urns),
                "track_total_hits": True,
                "_source": ["urn"],
                "query": {
                    "bool": {
                        "filter": [
                            {"terms": {"urn": expected_urns}},
                            vector_query,
                        ]
                    }
                },
            },
        ),
        "Elasticsearch GraphQL-result binding",
    )
    if search.get("timed_out") is True:
        raise VerificationError("Elasticsearch GraphQL-result binding timed out")
    shards = search.get("_shards")
    if not isinstance(shards, dict) or shards.get("failed") != 0:
        raise VerificationError("Elasticsearch GraphQL-result binding had shard failures")
    hits_node = search.get("hits")
    hits = hits_node.get("hits") if isinstance(hits_node, dict) else None
    if not isinstance(hits, list):
        raise VerificationError("Elasticsearch GraphQL-result binding returned malformed hits")
    indexed_urns = {
        source.get("urn")
        for hit in hits
        if isinstance(hit, dict)
        and isinstance((source := hit.get("_source")), dict)
        and isinstance(source.get("urn"), str)
    }
    missing = [urn for urn in expected_urns if urn not in indexed_urns]
    if missing:
        raise VerificationError("GraphQL semantic results are not vector-backed in the active index")
    return {
        "cluster_uuid": elasticsearch_evidence["cluster_uuid"],
        "semantic_index": index_name,
        "vector_document_count": vector_count,
        "bound_dataset_count": len(expected_urns),
        "reindex_active": False,
    }
