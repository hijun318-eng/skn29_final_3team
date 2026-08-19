"""live DataHub dataset metadata를 검증된 ``semanticContent`` MCP로 발행한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from dataset_semantic_clients import DataHubSemanticClient, OllamaEmbeddingClient
from dataset_semantic_contract import (
    EXPECTED_DIMENSION,
    EXPECTED_MODEL_KEY,
    DatasetDocument,
    DocumentChunk,
    SemanticContentError,
    chunk_document,
    model_data,
    model_version,
    same_model_data,
)
from dataset_semantic_index import ElasticsearchSemanticClient
from src.data.datahub_connection import DataHubConnectionSettings


PUBLISHED = "PUBLISHED_AND_INDEXED"
NOT_PUBLISHED = "CONFIGURED_NOT_PUBLISHED"


@dataclass(frozen=True)
class PublicationConfig:
    """live publication 한 번에 필요한 제한된 endpoint와 artifact identity를 묶는다."""

    datahub_url: str
    ollama_url: str
    elasticsearch_url: str
    model: str
    expected_model_digest: str
    datahub_token: str | None = field(default=None, repr=False)
    datahub_ca_file: str | Path | None = None
    timeout_seconds: float = 30.0
    convergence_seconds: float = 180.0
    page_size: int = 100
    max_entities: int = 10_000
    concurrency: int = 8
    embedding_batch_size: int = 16
    index_batch_size: int = 100
    max_chunks: int = 50_000


def _epoch_ms() -> int:
    return time.time_ns() // 1_000_000


def _validated_bounds(config: PublicationConfig) -> None:
    if (
        config.embedding_batch_size < 1
        or config.embedding_batch_size > 256
        or config.index_batch_size < 1
        or config.index_batch_size > 1_000
        or config.max_chunks < 1
    ):
        raise SemanticContentError("Semantic publication batch bounds are invalid")


def _chunks_by_document(
    documents: Sequence[DatasetDocument], max_chunks: int
) -> tuple[tuple[DocumentChunk, ...], ...]:
    chunk_sets = tuple(chunk_document(document.text) for document in documents)
    if sum(len(chunks) for chunks in chunk_sets) > max_chunks:
        raise SemanticContentError("Live dataset metadata exceeds the configured chunk bound")
    return chunk_sets


async def _embed_all(
    ollama: OllamaEmbeddingClient,
    chunk_sets: Sequence[Sequence[DocumentChunk]],
    batch_size: int,
) -> tuple[tuple[list[float], ...], ...]:
    flat_chunks = [chunk for chunks in chunk_sets for chunk in chunks]
    flat_vectors: list[list[float]] = []
    for start in range(0, len(flat_chunks), batch_size):
        batch = flat_chunks[start : start + batch_size]
        flat_vectors.extend(await ollama.embed([chunk.text for chunk in batch]))
    grouped: list[tuple[list[float], ...]] = []
    cursor = 0
    for chunks in chunk_sets:
        grouped.append(tuple(flat_vectors[cursor : cursor + len(chunks)]))
        cursor += len(chunks)
    if cursor != len(flat_vectors):
        raise SemanticContentError("Embedding batches could not be rebound to datasets")
    return tuple(grouped)


async def _read_existing(
    datahub: DataHubSemanticClient,
    urns: Sequence[str],
    concurrency: int,
) -> dict[str, dict[str, Any] | None]:
    semaphore = asyncio.Semaphore(concurrency)

    async def read(urn: str) -> tuple[str, dict[str, Any] | None]:
        """Read one aspect under the shared concurrency guard."""

        async with semaphore:
            return urn, await datahub.semantic_content(urn)

    return dict(await asyncio.gather(*(read(urn) for urn in urns)))


def _embeddings(value: object, urn: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or not isinstance(value.get("embeddings"), Mapping):
        raise SemanticContentError(f"Existing semanticContent is malformed for {urn}")
    embeddings = dict(value["embeddings"])
    if any(not isinstance(key, str) or not isinstance(item, Mapping) for key, item in embeddings.items()):
        raise SemanticContentError(f"Existing semanticContent model map is malformed for {urn}")
    return embeddings


async def _publish_changed(
    datahub: DataHubSemanticClient,
    candidates: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
) -> None:
    for urn, aspect in candidates.items():
        await datahub.upsert_semantic_content(urn, aspect)
        readback = await datahub.semantic_content(urn)
        if not isinstance(readback, Mapping):
            raise SemanticContentError("DataHub did not persist published semanticContent")
        expected_embeddings = aspect["embeddings"]
        actual_embeddings = readback.get("embeddings")
        if not isinstance(actual_embeddings, Mapping):
            raise SemanticContentError("DataHub semanticContent readback has no model map")
        expected_model = expected_embeddings[EXPECTED_MODEL_KEY]
        if not same_model_data(actual_embeddings.get(EXPECTED_MODEL_KEY), expected_model):
            raise SemanticContentError("DataHub semanticContent readback differs from its MCP")
        for model_key, previous in current[urn].items():
            if model_key != EXPECTED_MODEL_KEY and actual_embeddings.get(model_key) != previous:
                raise SemanticContentError("Semantic MCP overwrote another embedding model")


async def publish_live(
    config: PublicationConfig,
    *,
    http: httpx.AsyncClient | None = None,
    clock: Callable[[], int] = _epoch_ms,
) -> dict[str, Any]:
    """mutation 전에 모든 입력을 검증하고 정확한 vector의 active index 도달을 증명한다."""

    _validated_bounds(config)
    owns_http = http is None
    if http is not None and not isinstance(
        getattr(http, "_transport", None), httpx.MockTransport
    ):
        raise SemanticContentError("Only httpx.MockTransport may be injected")
    if owns_http:
        endpoint = httpx.URL(config.datahub_url)
        ca_path = Path(config.datahub_ca_file).resolve() if config.datahub_ca_file else None
        if (
            endpoint.scheme != "https"
            or not config.datahub_token
            or ca_path is None
            or not ca_path.is_file()
        ):
            raise SemanticContentError(
                "owned DataHub publication transport requires HTTPS, bearer token, and CA"
            )
    active_http = http or httpx.AsyncClient(
        verify=str(ca_path),
        timeout=httpx.Timeout(config.timeout_seconds),
        trust_env=False,
        limits=httpx.Limits(max_connections=max(16, config.concurrency * 2)),
    )
    datahub = DataHubSemanticClient(
        config.datahub_url,
        active_http,
        token=config.datahub_token,
        timeout_seconds=config.timeout_seconds,
        page_size=config.page_size,
        max_entities=config.max_entities,
        concurrency=config.concurrency,
    )
    ollama = OllamaEmbeddingClient(
        config.ollama_url,
        active_http,
        model=config.model,
        digest=config.expected_model_digest,
        timeout_seconds=config.timeout_seconds,
    )
    elasticsearch = ElasticsearchSemanticClient(
        config.elasticsearch_url,
        active_http,
        timeout_seconds=config.timeout_seconds,
        convergence_seconds=config.convergence_seconds,
    )
    try:
        documents, _artifact, _index = await asyncio.gather(
            datahub.discover_documents(),
            ollama.verify_artifact(),
            elasticsearch.require_ready(),
        )
        chunk_sets = _chunks_by_document(documents, config.max_chunks)
        vector_sets = await _embed_all(
            ollama, chunk_sets, config.embedding_batch_size
        )
        generated_at = clock()
        expected_models = {
            document.urn: model_data(
                chunks,
                vectors,
                model=config.model,
                digest=config.expected_model_digest,
                generated_at=generated_at,
            )
            for document, chunks, vectors in zip(
                documents, chunk_sets, vector_sets, strict=True
            )
        }
        existing_aspects = await _read_existing(
            datahub, [document.urn for document in documents], config.concurrency
        )
        previous_models = {
            urn: _embeddings(existing_aspects[urn], urn) for urn in expected_models
        }
        candidates: dict[str, dict[str, Any]] = {}
        for urn, expected in expected_models.items():
            if same_model_data(previous_models[urn].get(EXPECTED_MODEL_KEY), expected):
                continue
            merged = dict(previous_models[urn])
            merged[EXPECTED_MODEL_KEY] = expected
            candidates[urn] = {"embeddings": merged}
        await _publish_changed(datahub, candidates, previous_models)
        await elasticsearch.wait_until_indexed(
            expected_models, config.index_batch_size
        )
        return {
            "status": PUBLISHED,
            "dataset_count": len(documents),
            "chunk_count": sum(len(chunks) for chunks in chunk_sets),
            "updated_dataset_count": len(candidates),
            "unchanged_dataset_count": len(documents) - len(candidates),
            "model": config.model,
            "model_version": model_version(config.model, config.expected_model_digest),
            "model_digest": config.expected_model_digest.lower(),
            "vector_dimension": EXPECTED_DIMENSION,
            "semantic_index": elasticsearch.index_name,
            "probe_query": documents[0].probe_query,
        }
    finally:
        if owns_http:
            await active_http.aclose()


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ollama-url",
        default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
    )
    parser.add_argument(
        "--elasticsearch-url",
        default=os.getenv(
            "DATAHUB_SEMANTIC_ELASTICSEARCH_URL", "http://127.0.0.1:19200"
        ),
    )
    parser.add_argument("--model", default=os.getenv("OLLAMA_EMBEDDING_MODEL", ""))
    parser.add_argument(
        "--expected-model-digest",
        default=os.getenv("OLLAMA_EMBEDDING_MODEL_DIGEST", ""),
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--convergence-seconds", type=float, default=180.0)
    parser.add_argument("--page-size", type=_positive_int, default=100)
    parser.add_argument("--max-entities", type=_positive_int, default=10_000)
    parser.add_argument("--concurrency", type=_positive_int, default=8)
    parser.add_argument("--embedding-batch-size", type=_positive_int, default=16)
    parser.add_argument("--index-batch-size", type=_positive_int, default=100)
    parser.add_argument("--max-chunks", type=_positive_int, default=50_000)
    return parser


async def _run(args: argparse.Namespace) -> int:
    try:
        datahub_settings = DataHubConnectionSettings.from_publish_env()
        result = await publish_live(
            PublicationConfig(
                datahub_url=datahub_settings.base_url,
                ollama_url=args.ollama_url,
                elasticsearch_url=args.elasticsearch_url,
                model=args.model,
                expected_model_digest=args.expected_model_digest,
                datahub_token=datahub_settings.token,
                datahub_ca_file=datahub_settings.ca_file,
                timeout_seconds=args.timeout_seconds,
                convergence_seconds=args.convergence_seconds,
                page_size=args.page_size,
                max_entities=args.max_entities,
                concurrency=args.concurrency,
                embedding_batch_size=args.embedding_batch_size,
                index_batch_size=args.index_batch_size,
                max_chunks=args.max_chunks,
            )
        )
    except (SemanticContentError, ValueError) as exc:
        result = {"status": NOT_PUBLISHED, "reason": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == PUBLISHED else 2


def main() -> int:
    """semantic publication을 실행하고 fail-closed 상태를 shell 종료 코드로 노출한다."""

    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
