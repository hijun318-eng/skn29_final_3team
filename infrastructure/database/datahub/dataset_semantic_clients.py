"""dataset discovery, embedding, MCP, index 증거를 위한 비동기 로컬 client를 제공한다."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from dataset_semantic_contract import (
    DatasetDocument,
    SemanticContentError,
    build_document,
    normalize_model,
    parse_dataset,
    parse_glossary_term,
    referenced_term_urns,
    require_dataset_urn,
    require_sha256,
    require_supported_model,
    validated_vector,
)


DATAHUB_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "::1", "datahub-gms", "datahub-gms-quickstart"}
)
OLLAMA_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "ollama"})

SEARCH_QUERY = """
query SemanticBootstrapDatasets($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    start count total
    searchResults { entity { urn type } }
  }
}
""".strip()

DATASET_QUERY = """
query SemanticBootstrapDataset($urn: String!) {
  dataset(urn: $urn) {
    urn name
    status { removed }
    domain { domain { urn properties { name description } } }
    properties { name qualifiedName description }
    glossaryTerms { terms { term { urn } } }
    schemaMetadata {
      fields {
        fieldPath nativeDataType description
        glossaryTerms { terms { term { urn } } }
      }
    }
  }
}
""".strip()

TERM_QUERY = """
query SemanticBootstrapGlossaryTerm($urn: String!) {
  glossaryTerm(urn: $urn) {
    urn exists
    status { removed }
    glossaryTermInfo { name description }
  }
}
""".strip()


def local_base_url(
    value: str,
    label: str,
    allowed_hosts: frozenset[str],
    *,
    allowed_schemes: frozenset[str] = frozenset({"http"}),
) -> str:
    """허용된 scheme·host에 속하는 인증정보 없는 service root만 반환한다."""

    parsed = urlsplit(value)
    if parsed.scheme not in allowed_schemes or parsed.hostname not in allowed_hosts:
        raise SemanticContentError(f"{label} must be an approved local endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SemanticContentError(f"{label} must not include credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise SemanticContentError(f"{label} must not include a path")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _json_object(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        value = response.json()
    except httpx.HTTPStatusError as exc:
        raise SemanticContentError(
            f"{label} returned HTTP {exc.response.status_code}"
        ) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise SemanticContentError(f"{label} did not return JSON") from exc
    if not isinstance(value, dict):
        raise SemanticContentError(f"{label} returned a non-object JSON value")
    return value


class DataHubSemanticClient:
    """live dataset을 발견하고 각 dataset의 semantic aspect 하나를 동기 발행한다."""

    def __init__(
        self,
        base_url: str,
        http: httpx.AsyncClient,
        *,
        token: str | None,
        timeout_seconds: float,
        page_size: int,
        max_entities: int,
        concurrency: int,
    ) -> None:
        if (
            timeout_seconds <= 0
            or page_size < 1
            or max_entities < page_size
            or concurrency < 1
        ):
            raise SemanticContentError("DataHub bounds must be positive and consistent")
        self.base_url = local_base_url(
            base_url,
            "DataHub URL",
            DATAHUB_HOSTS,
            allowed_schemes=frozenset({"http", "https"}),
        )
        self.http = http
        self.timeout = timeout_seconds
        self.page_size = page_size
        self.max_entities = max_entities
        self.concurrency = concurrency
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-RestLi-Protocol-Version": "2.0.0",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    async def _request(
        self,
        method: str,
        url: str | httpx.URL,
        label: str,
        *,
        json_body: object | None = None,
    ) -> httpx.Response:
        try:
            response = await self.http.request(
                method,
                url,
                headers=self.headers,
                json=json_body,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise SemanticContentError(f"{label} timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise SemanticContentError(
                f"{label} returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SemanticContentError(f"{label} request failed") from exc

    async def graphql(self, query: str, variables: Mapping[str, object]) -> dict[str, Any]:
        """GraphQL을 실행하고 오류 없는 객체형 data payload만 반환한다."""

        response = await self._request(
            "POST",
            _endpoint(self.base_url, "/api/graphql"),
            "DataHub GraphQL",
            json_body={"query": query, "variables": dict(variables)},
        )
        payload = _json_object(response, "DataHub GraphQL")
        if payload.get("errors"):
            raise SemanticContentError("DataHub GraphQL returned errors")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SemanticContentError("DataHub GraphQL response has no data object")
        return data

    async def _dataset_urns(self) -> tuple[str, ...]:
        start = 0
        urns: list[str] = []
        seen: set[str] = set()
        while True:
            data = await self.graphql(
                SEARCH_QUERY,
                {
                    "input": {
                        "types": ["DATASET"],
                        "query": "*",
                        "start": start,
                        "count": self.page_size,
                    }
                },
            )
            page = data.get("searchAcrossEntities")
            rows = page.get("searchResults") if isinstance(page, Mapping) else None
            total = page.get("total") if isinstance(page, Mapping) else None
            if (
                not isinstance(rows, list)
                or not isinstance(total, int)
                or isinstance(total, bool)
                or total < 0
                or total > self.max_entities
                or page.get("start") != start
                or not isinstance(page.get("count"), int)
            ):
                raise SemanticContentError("DataHub dataset pagination is invalid")
            for row in rows:
                entity = row.get("entity") if isinstance(row, Mapping) else None
                urn = require_dataset_urn(entity.get("urn") if isinstance(entity, Mapping) else None)
                if entity.get("type") != "DATASET" or urn in seen:
                    raise SemanticContentError("DataHub dataset search identity is invalid")
                seen.add(urn)
                urns.append(urn)
            if start + len(rows) >= total:
                break
            if not rows:
                raise SemanticContentError("DataHub dataset pagination made no progress")
            start += len(rows)
        if len(urns) != total:
            raise SemanticContentError("DataHub dataset pagination total does not match results")
        return tuple(urns)

    async def _bounded_entities(
        self,
        identities: Sequence[str],
        query: str,
        field: str,
    ) -> tuple[object, ...]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch(identity: str) -> object:
            """Fetch one identity while honoring the workflow concurrency bound."""

            async with semaphore:
                data = await self.graphql(query, {"urn": identity})
            if field not in data:
                raise SemanticContentError(f"DataHub GraphQL did not return {field}")
            return data[field]

        return tuple(await asyncio.gather(*(fetch(identity) for identity in identities)))

    async def discover_documents(self) -> tuple[DatasetDocument, ...]:
        """모든 활성 dataset을 발견하고 참조된 glossary term 전체를 해석한다."""

        urns = await self._dataset_urns()
        if not urns:
            raise SemanticContentError("DataHub has no datasets to embed")
        raw_datasets = await self._bounded_entities(urns, DATASET_QUERY, "dataset")
        datasets = tuple(
            dataset
            for urn, raw in zip(urns, raw_datasets, strict=True)
            if (dataset := parse_dataset(raw, urn)) is not None
        )
        if not datasets:
            raise SemanticContentError("DataHub has no active datasets to embed")
        term_urns = referenced_term_urns(datasets)
        raw_terms = await self._bounded_entities(term_urns, TERM_QUERY, "glossaryTerm")
        terms = {
            urn: parse_glossary_term(raw, urn)
            for urn, raw in zip(term_urns, raw_terms, strict=True)
        }
        return tuple(build_document(dataset, terms) for dataset in datasets)

    async def semantic_content(self, urn: str) -> dict[str, Any] | None:
        """검증된 dataset URN 하나의 현재 semanticContent aspect를 조회한다."""

        safe_urn = require_dataset_urn(urn)
        path = _endpoint(self.base_url, f"/entitiesV2/{quote(safe_urn, safe='')}")
        url = httpx.URL(path).copy_with(query=b"aspects=List(semanticContent)")
        response = await self._request("GET", url, "DataHub semanticContent readback")
        payload = _json_object(response, "DataHub semanticContent readback")
        aspects = payload.get("aspects")
        if not isinstance(aspects, Mapping):
            raise SemanticContentError("DataHub entity readback has no aspects object")
        wrapper = aspects.get("semanticContent")
        if wrapper is None:
            return None
        value = wrapper.get("value") if isinstance(wrapper, Mapping) else None
        if not isinstance(value, dict):
            raise SemanticContentError("DataHub semanticContent readback is malformed")
        return value

    async def upsert_semantic_content(self, urn: str, aspect: Mapping[str, Any]) -> None:
        """호출자가 수렴을 검증할 수 있도록 aspect 하나를 동기 방식으로 기록한다."""

        safe_urn = require_dataset_urn(urn)
        encoded_aspect = json.dumps(
            dict(aspect), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        proposal = {
            "entityType": "dataset",
            "entityUrn": safe_urn,
            "changeType": "UPSERT",
            "aspectName": "semanticContent",
            "aspect": {"value": encoded_aspect, "contentType": "application/json"},
        }
        await self._request(
            "POST",
            _endpoint(self.base_url, "/aspects?action=ingestProposal"),
            "DataHub synchronous semanticContent MCP",
            json_body={"proposal": proposal, "async": "false"},
        )


class OllamaEmbeddingClient:
    """승인된 로컬 model artifact 하나로 유한한 768차원 vector batch만 생성한다."""

    def __init__(
        self,
        base_url: str,
        http: httpx.AsyncClient,
        *,
        model: str,
        digest: str,
        timeout_seconds: float,
    ) -> None:
        if timeout_seconds <= 0:
            raise SemanticContentError("Ollama timeout must be positive")
        self.base_url = local_base_url(base_url, "Ollama URL", OLLAMA_HOSTS)
        self.http = http
        self.model = require_supported_model(model)
        self.digest = require_sha256(digest)
        self.timeout = timeout_seconds

    async def _json(self, method: str, path: str, *, body: object | None = None) -> dict[str, Any]:
        try:
            response = await self.http.request(
                method,
                _endpoint(self.base_url, path),
                json=body,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise SemanticContentError("Ollama request timed out") from exc
        except httpx.HTTPError as exc:
            raise SemanticContentError("Ollama request failed") from exc
        return _json_object(response, "Ollama")

    async def verify_artifact(self) -> None:
        """설치된 model 이름과 불변 digest가 승인 policy와 일치하는지 검증한다."""

        payload = await self._json("GET", "/api/tags")
        models = payload.get("models")
        if not isinstance(models, list):
            raise SemanticContentError("Ollama tags response has no models list")
        matches = [
            item
            for item in models
            if isinstance(item, Mapping)
            and any(
                isinstance(item.get(field), str)
                and normalize_model(item[field]) == normalize_model(self.model)
                for field in ("name", "model")
            )
        ]
        if len(matches) != 1 or str(matches[0].get("digest", "")).lower() != self.digest:
            raise SemanticContentError("Installed Ollama model artifact does not match its digest")

    async def embed(self, texts: Sequence[str]) -> tuple[list[float], ...]:
        """비어 있지 않은 batch를 embedding하고 model identity·coverage·vector를 검증한다."""

        if not texts or any(not isinstance(text, str) or not text for text in texts):
            raise SemanticContentError("Ollama embedding batch must contain non-empty text")
        payload = await self._json(
            "POST", "/v1/embeddings", body={"model": self.model, "input": list(texts)}
        )
        response_model = payload.get("model")
        if not isinstance(response_model, str) or normalize_model(response_model) != normalize_model(
            self.model
        ):
            raise SemanticContentError("Ollama embedding response identified a different model")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise SemanticContentError("Ollama embedding response count does not match input")
        indexed: dict[int, list[float]] = {}
        for position, item in enumerate(data):
            if not isinstance(item, Mapping):
                raise SemanticContentError("Ollama embedding item is malformed")
            index = item.get("index", position)
            if not isinstance(index, int) or isinstance(index, bool) or index in indexed:
                raise SemanticContentError("Ollama embedding indices are invalid")
            indexed[index] = validated_vector(item.get("embedding"))
        if set(indexed) != set(range(len(texts))):
            raise SemanticContentError("Ollama embedding indices do not cover the input batch")
        return tuple(indexed[index] for index in range(len(texts)))
