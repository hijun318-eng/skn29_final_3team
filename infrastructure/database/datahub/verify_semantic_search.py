"""로컬 DataHub semantic-search 배포를 live 증거로 fail-closed 검증한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from semantic_compose_evidence import verify_compose_deployment
from semantic_deployment_evidence import VerificationError, verify_deployment_binding
from src.data.datahub_connection import DataHubConnectionSettings

EXPECTED_DIMENSION = 768
EXPECTED_MODEL = "nomic-embed-text"
EXPECTED_MODEL_KEY = "nomic_embed_text"
EXPECTED_DATAHUB_VERSION = "v1.7.0"
EXPECTED_DATAHUB_COMMIT = "7f81ccbfe27b9acc947f5f600fcf9ddb72138a80"
DEFAULT_SEMANTIC_INDEX = "datasetindex_v2_semantic"
VERIFIED = "VERIFIED"
NOT_VERIFIED = "CONFIGURED_NOT_VERIFIED"
SEMANTIC_SEARCH_QUERY = """
query VerifyDatasetSemanticSearch($input: SearchAcrossEntitiesInput!) {
  semanticSearchAcrossEntities(input: $input) {
    searchResults {
      entity { urn type }
      matchedFields { name value }
    }
  }
}
""".strip()

@dataclass(frozen=True)
class VerificationConfig:
    """검증 한 번에 필요한 모든 live endpoint와 승인 artifact identity를 묶는다."""

    datahub_url: str
    elasticsearch_url: str
    ollama_url: str
    probe_query: str
    expected_model_digest: str
    compose_project: str = "answervice"
    semantic_index: str = DEFAULT_SEMANTIC_INDEX
    datahub_token: str | None = field(default=None, repr=False)
    datahub_ca_file: str | Path | None = None
    timeout_seconds: float = 15.0


def _local_base_url(
    value: str,
    label: str,
    *,
    required_scheme: str = "http",
) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != required_scheme
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise VerificationError(f"{label} must use a loopback {required_scheme} URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise VerificationError(f"{label} must not include credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise VerificationError(f"{label} must not include a path")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


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


def _require_sha256(value: str) -> str:
    prefix, separator, hexadecimal = value.lower().partition(":")
    if prefix != "sha256" or separator != ":" or len(hexadecimal) != 64:
        raise VerificationError("expected Ollama model digest must be a full sha256 digest")
    try:
        int(hexadecimal, 16)
    except ValueError as exc:
        raise VerificationError("expected Ollama model digest is not hexadecimal") from exc
    return f"sha256:{hexadecimal}"


def _normalized_model(value: str) -> str:
    return value if ":" in value else f"{value}:latest"


async def verify_embedding(
    client: httpx.AsyncClient,
    base_url: str,
    expected_digest: str,
) -> dict[str, Any]:
    """설치된 model artifact와 실제 유한 embedding vector를 함께 검증한다."""

    required_digest = _require_sha256(expected_digest)
    tags = _json_object(await client.get(_endpoint(base_url, "/api/tags")), "Ollama tags")
    models = tags.get("models")
    if not isinstance(models, list):
        raise VerificationError("Ollama tags response has no models list")
    installed = next(
        (
            item
            for item in models
            if isinstance(item, dict)
            and any(
                isinstance(item.get(field), str)
                and _normalized_model(item[field]) == _normalized_model(EXPECTED_MODEL)
                for field in ("name", "model")
            )
        ),
        None,
    )
    if installed is None:
        raise VerificationError("configured Ollama embedding model is not installed")
    actual_digest = str(installed.get("digest", "")).lower()
    if actual_digest != required_digest:
        raise VerificationError("installed Ollama model digest does not match the approved artifact")

    body = _json_object(
        await client.post(
            _endpoint(base_url, "/v1/embeddings"),
            json={"model": EXPECTED_MODEL, "input": "semantic-search-health-probe"},
        ),
        "Ollama embeddings",
    )
    data = body.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise VerificationError("Ollama embeddings response has no data item")
    vector = data[0].get("embedding")
    if not isinstance(vector, list) or any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(item)
        for item in vector
    ):
        raise VerificationError("Ollama embeddings response has no finite numeric vector")
    if len(vector) != EXPECTED_DIMENSION:
        raise VerificationError(
            f"Ollama vector dimension is {len(vector)}, expected {EXPECTED_DIMENSION}"
        )
    model = body.get("model")
    if not isinstance(model, str) or _normalized_model(model) != _normalized_model(EXPECTED_MODEL):
        raise VerificationError("Ollama response did not identify the configured model")
    return {"model": model, "model_digest": actual_digest, "vector_dimension": len(vector)}


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    try:
        numbers = tuple(int(part.split("-")[0]) for part in parts[:3])
    except ValueError as exc:
        raise VerificationError("Elasticsearch returned an invalid version") from exc
    if len(numbers) < 2:
        raise VerificationError("Elasticsearch returned an incomplete version")
    return (numbers + (0, 0, 0))[:3]


def _safe_index_name(value: str) -> str:
    allowed = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-.:")
    if not value or len(value) > 255 or any(character.lower() not in allowed for character in value):
        raise VerificationError("semantic index name is invalid")
    return value


async def _resolve_active_index(
    client: httpx.AsyncClient,
    base_url: str,
    requested_name: str,
) -> tuple[str, str]:
    safe_name = _safe_index_name(requested_name)
    body = _json_object(
        await client.get(_endpoint(base_url, f"/_resolve/index/{quote(safe_name, safe='')}")),
        "Elasticsearch index resolution",
    )
    direct = [
        entry.get("name")
        for entry in body.get("indices", [])
        if isinstance(entry, dict)
        and entry.get("name") == safe_name
        and "closed" not in entry.get("attributes", [])
    ]
    alias_targets = [
        index_name
        for entry in body.get("aliases", [])
        if isinstance(entry, dict) and entry.get("name") == safe_name
        for index_name in entry.get("indices", [])
        if isinstance(index_name, str)
    ]
    targets = sorted(set(direct + alias_targets))
    if len(targets) != 1:
        raise VerificationError("semantic dataset index does not resolve to one active index")
    resolution = "direct" if direct else "alias"
    return targets[0], resolution


def _mapping_value(node: Any, *path: str) -> Any:
    value = node
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


async def verify_elasticsearch(
    client: httpx.AsyncClient,
    base_url: str,
    semantic_index: str,
) -> dict[str, Any]:
    """live Elasticsearch identity와 active vector-index mapping을 검증한다."""

    root = _json_object(await client.get(_endpoint(base_url, "/")), "Elasticsearch root")
    version = root.get("version")
    if not isinstance(version, dict) or not isinstance(version.get("number"), str):
        raise VerificationError("Elasticsearch root response has no version")
    distribution = str(version.get("distribution", "elasticsearch")).lower()
    if distribution != "elasticsearch" or "opensearch" in str(root.get("tagline", "")).lower():
        raise VerificationError("semantic-search verifier requires Elasticsearch, not OpenSearch")
    number = version["number"]
    if _version_tuple(number) < (8, 18, 0):
        raise VerificationError(f"Elasticsearch {number} is below the required 8.18.0")
    cluster_uuid = root.get("cluster_uuid")
    if not isinstance(cluster_uuid, str) or not cluster_uuid or cluster_uuid == "_na_":
        raise VerificationError("Elasticsearch returned no stable cluster UUID")

    active_index, resolution = await _resolve_active_index(client, base_url, semantic_index)
    mappings = _json_object(
        await client.get(_endpoint(base_url, f"/{quote(active_index, safe='')}/_mapping")),
        "Elasticsearch semantic mapping",
    )
    index_mapping = mappings.get(active_index)
    mapping = index_mapping.get("mappings") if isinstance(index_mapping, dict) else None
    chunks = _mapping_value(
        mapping,
        "properties", "embeddings", "properties", EXPECTED_MODEL_KEY, "properties", "chunks",
    )
    vector = _mapping_value(chunks, "properties", "vector")
    if not isinstance(chunks, dict) or chunks.get("type") != "nested":
        raise VerificationError("semantic index has no nested embedding chunks mapping")
    if not isinstance(vector, dict) or vector.get("type") != "dense_vector":
        raise VerificationError("semantic index has no Elasticsearch dense_vector mapping")
    if vector.get("dims") != EXPECTED_DIMENSION or vector.get("index") is not True:
        raise VerificationError("semantic vector mapping has the wrong dimension or is not indexed")
    if vector.get("similarity") != "cosine":
        raise VerificationError("semantic vector mapping does not use cosine similarity")
    return {
        "distribution": distribution,
        "version": number,
        "cluster_uuid": cluster_uuid,
        "semantic_index": active_index,
        "index_resolution": resolution,
        "vector_field": f"embeddings.{EXPECTED_MODEL_KEY}.chunks.vector",
    }


def _authorization(token: str | None) -> dict[str, str]:
    headers = {"Cache-Control": "no-cache"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def verify_graphql(
    client: httpx.AsyncClient,
    base_url: str,
    probe_query: str,
    token: str | None,
) -> dict[str, Any]:
    """운영 GraphQL semantic operation을 실행하고 dataset 결과를 검증한다."""

    headers = _authorization(token)
    app_config = _json_object(
        await client.get(_endpoint(base_url, "/config"), headers=headers),
        "DataHub config",
    )
    versions = app_config.get("versions")
    release = versions.get("acryldata/datahub") if isinstance(versions, dict) else None
    if not isinstance(release, dict):
        raise VerificationError("DataHub config did not identify its release")
    if release.get("version") != EXPECTED_DATAHUB_VERSION:
        raise VerificationError("DataHub version does not match the semantic-search contract")
    if release.get("commit") != EXPECTED_DATAHUB_COMMIT:
        raise VerificationError("DataHub commit does not match the pinned deployment")

    body = _json_object(
        await client.post(
            _endpoint(base_url, "/api/graphql"),
            headers=headers,
            json={
                "operationName": "VerifyDatasetSemanticSearch",
                "query": SEMANTIC_SEARCH_QUERY,
                "variables": {
                    "input": {"types": ["DATASET"], "query": probe_query, "start": 0, "count": 5}
                },
            },
        ),
        "DataHub GraphQL",
    )
    if body.get("errors"):
        raise VerificationError("semanticSearchAcrossEntities returned GraphQL errors")
    data = body.get("data")
    result = data.get("semanticSearchAcrossEntities") if isinstance(data, dict) else None
    rows = result.get("searchResults") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not rows:
        raise VerificationError("semanticSearchAcrossEntities returned no dataset result")
    urns: list[str] = []
    for row in rows:
        entity = row.get("entity") if isinstance(row, dict) else None
        urn = entity.get("urn") if isinstance(entity, dict) else None
        if entity is None or entity.get("type") != "DATASET" or not isinstance(urn, str):
            raise VerificationError("semanticSearchAcrossEntities returned an invalid dataset row")
        if not urn.startswith("urn:li:dataset:"):
            raise VerificationError("semanticSearchAcrossEntities returned an invalid dataset URN")
        if urn not in urns:
            urns.append(urn)
    return {
        "dataset_result_count": len(urns),
        "dataset_urns": urns,
        "operation": "semanticSearchAcrossEntities",
        "datahub_version": release["version"],
        "datahub_commit": release["commit"],
    }


async def _capture(
    name: str,
    operation: Callable[[], Awaitable[dict[str, Any]]],
) -> tuple[str, dict[str, Any]]:
    try:
        evidence = await operation()
    except (VerificationError, ValueError) as exc:
        return name, {"verified": False, "reason": str(exc)}
    except httpx.HTTPError as exc:
        return name, {
            "verified": False,
            "reason": f"{type(exc).__name__} while contacting the local service",
        }
    except Exception as exc:  # fail closed for malformed third-party responses
        return name, {"verified": False, "reason": f"unexpected {type(exc).__name__}"}
    return name, {"verified": True, "evidence": evidence}


async def verify_live(
    config: VerificationConfig,
    *,
    client: httpx.AsyncClient | None = None,
    compose_probe: Callable[[str, str, str], Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Compose·model·index·DataHub 전 구간의 fail-closed 증거를 수집한다."""

    _require_sha256(config.expected_model_digest)
    owns_client = client is None
    if client is not None and not isinstance(
        getattr(client, "_transport", None), httpx.MockTransport
    ):
        raise VerificationError("Only httpx.MockTransport may be injected")
    datahub_url = _local_base_url(
        config.datahub_url,
        "DataHub URL",
        required_scheme="https" if owns_client else urlsplit(config.datahub_url).scheme,
    )
    elasticsearch_url = _local_base_url(config.elasticsearch_url, "Elasticsearch URL")
    ollama_url = _local_base_url(config.ollama_url, "Ollama URL")
    _safe_index_name(config.semantic_index)
    if not config.probe_query.strip():
        raise VerificationError("probe query must not be empty")

    if owns_client:
        ca_path = Path(config.datahub_ca_file).resolve() if config.datahub_ca_file else None
        if not config.datahub_token or ca_path is None or not ca_path.is_file():
            raise VerificationError(
                "owned DataHub verification transport requires bearer token and CA"
            )
    active_client = client or httpx.AsyncClient(
        timeout=config.timeout_seconds,
        verify=str(ca_path),
        trust_env=False,
    )
    active_compose_probe = compose_probe or verify_compose_deployment
    try:
        initial = await asyncio.gather(
            _capture(
                "compose_binding",
                lambda: active_compose_probe(
                    config.compose_project, datahub_url, elasticsearch_url
                ),
            ),
            _capture(
                "embedding",
                lambda: verify_embedding(active_client, ollama_url, config.expected_model_digest),
            ),
            _capture(
                "elasticsearch",
                lambda: verify_elasticsearch(
                    active_client, elasticsearch_url, config.semantic_index
                ),
            ),
            _capture(
                "graphql",
                lambda: verify_graphql(
                    active_client, datahub_url, config.probe_query, config.datahub_token
                ),
            ),
        )
        details = dict(initial)
        prerequisites = ("compose_binding", "elasticsearch", "graphql")
        if all(details[name]["verified"] for name in prerequisites):
            binding = await _capture(
                "deployment_binding",
                lambda: verify_deployment_binding(
                    active_client,
                    elasticsearch_url,
                    details["elasticsearch"]["evidence"],
                    details["graphql"]["evidence"],
                ),
            )
        else:
            binding = (
                "deployment_binding",
                {
                    "verified": False,
                    "reason": "Compose, Elasticsearch, and GraphQL checks are prerequisites",
                },
            )
        details[binding[0]] = binding[1]
    finally:
        if owns_client:
            await active_client.aclose()
    status = VERIFIED if all(item["verified"] for item in details.values()) else NOT_VERIFIED
    return {"status": status, "checks": details}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-query", required=True)
    parser.add_argument("--elasticsearch-url", default="http://127.0.0.1:19200")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--compose-project",
        default=os.getenv("COMPOSE_PROJECT_NAME", "answervice"),
    )
    parser.add_argument("--semantic-index", default=DEFAULT_SEMANTIC_INDEX)
    parser.add_argument(
        "--expected-model-digest",
        default=os.getenv("OLLAMA_EMBEDDING_MODEL_DIGEST", ""),
    )
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    return parser


async def _run(args: argparse.Namespace) -> int:
    try:
        datahub_settings = DataHubConnectionSettings.from_env()
        result = await verify_live(
            VerificationConfig(
                datahub_url=datahub_settings.base_url,
                elasticsearch_url=args.elasticsearch_url,
                ollama_url=args.ollama_url,
                probe_query=args.probe_query,
                expected_model_digest=args.expected_model_digest,
                compose_project=args.compose_project,
                semantic_index=args.semantic_index,
                datahub_token=datahub_settings.token,
                datahub_ca_file=datahub_settings.ca_file,
                timeout_seconds=args.timeout_seconds,
            )
        )
    except VerificationError as exc:
        result = {"status": NOT_VERIFIED, "checks": {}, "configuration_error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == VERIFIED else 2


def main() -> int:
    """비동기 verifier를 실행하고 shell에서 판별 가능한 종료 코드를 반환한다."""

    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
