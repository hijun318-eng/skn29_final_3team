"""DataHub GraphQL에서 승인 후보 엔터티를 비동기로 끝까지 탐색하는 카탈로그 어댑터다."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from src.data.datahub_connection import DataHubConnectionSettings


class DataHubCatalogError(RuntimeError):
    """DataHub 응답이 없거나 불완전해 신뢰 가능한 카탈로그를 구성할 수 없음을 알린다.

    ``category``는 관측·전환 판단용 실패 분류다. ``timeout``은 응답 시간 초과,
    ``transport``는 연결·HTTP 상태 실패, ``protocol``은 인증된 응답이 계약을 위반한
    경우이며 기본값은 계약 위반이다. 값은 로그에만 쓰고 사용자 응답에는 노출하지 않는다.
    """

    def __init__(self, message: str, *, category: str = "protocol") -> None:
        super().__init__(message)
        self.category = category


class DataHubSemanticSearchError(DataHubCatalogError):
    """설정된 DataHub가 의미 검색 계약을 수행하지 못했음을 일반 조회 실패와 구분한다."""


class DataHubSearchUnavailableError(DataHubCatalogError):
    """질문 단위 lexical 검색이 실패했음을 카탈로그 열거 실패와 구분해 알린다."""


@dataclass(frozen=True)
class DataHubSearchHit:
    """검색 엔터티의 URN·유형과 DataHub가 돌려준 일치 필드를 불변 값으로 보존한다."""
    urn: str
    entity_type: str
    matched_fields: tuple[tuple[str, str], ...] = ()


class DataHubCatalogClient:
    """실시간 DataHub graph의 dataset·용어·거버넌스 엔터티를 제한된 페이지 크기로 읽는다."""

    MAX_CANDIDATE_RESULTS = 50
    MAX_CANDIDATE_QUERY_CHARACTERS = 256

    _SEARCH_QUERY = """
query SearchAcrossEntities($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    start count total
    searchResults { entity { urn type } }
  }
}
""".strip()
    _SCROLL_QUERY = """
query ScrollAcrossEntities($input: ScrollAcrossEntitiesInput!) {
  scrollAcrossEntities(input: $input) {
    nextScrollId count
    searchResults { entity { urn type } }
  }
}
""".strip()
    _SEMANTIC_QUERY = """
query SemanticSearchAcrossEntities($input: SearchAcrossEntitiesInput!) {
  semanticSearchAcrossEntities(input: $input) {
    start count total
    searchResults { entity { urn type } matchedFields { name value } }
  }
}
""".strip()
    _DATASET_QUERY = """
query GovernedDataset($urn: String!) {
  dataset(urn: $urn) {
    urn name
    status { removed lifecycleStage { urn name } }
    ownership {
      owners {
        type associatedUrn ownershipType { urn }
        owner { ... on CorpUser { urn } ... on CorpGroup { urn } }
      }
    }
    domain { domain { urn } }
    properties { name qualifiedName description customProperties { key value } }
    glossaryTerms { terms { term { urn } } }
    schemaMetadata {
      version name hash
      fields {
        fieldPath nativeDataType nullable isPartOfKey description
        glossaryTerms { terms { term { urn } } }
      }
    }
    editableSchemaMetadata {
      editableSchemaFieldInfo {
        fieldPath description
        glossaryTerms { terms { term { urn } } }
      }
    }
  }
}
""".strip()
    _GLOSSARY_TERM_QUERY = """
query GovernedGlossaryTerm($urn: String!) {
  glossaryTerm(urn: $urn) {
    urn exists
    status { removed lifecycleStage { urn name } }
    ownership {
      owners {
        type associatedUrn ownershipType { urn }
        owner { ... on CorpUser { urn } ... on CorpGroup { urn } }
      }
    }
    domain { domain { urn } }
    glossaryTermInfo {
      name description termSource sourceRef
      customProperties { key value }
    }
  }
}
""".strip()
    _CORP_GROUP_QUERY = """
query GovernanceOwner($urn: String!) {
  corpGroup(urn: $urn) {
    urn name properties { displayName description }
  }
}
""".strip()
    _DOMAIN_QUERY = """
query GovernanceDomain($urn: String!) {
  domain(urn: $urn) {
    urn id properties { name description }
  }
}
""".strip()
    _LIFECYCLE_QUERY = """
query GovernanceLifecycleStages {
  listLifecycleStages { urn name description }
}
""".strip()
    _HEALTH_QUERY = "query DataHubHealth { me { corpUser { urn } } }"

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        ca_file: str | Path | None = None,
        expected_actor_urn: str | None = None,
        timeout_seconds: float = 10.0,
        page_size: int = 50,
        max_entities: int = 100_000,
    ) -> None:
        endpoint = httpx.URL(base_url)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.host
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or timeout_seconds <= 0
        ):
            raise ValueError("DataHub endpoint and positive timeout are required")
        if page_size < 1 or max_entities < page_size:
            raise ValueError("DataHub pagination bounds are invalid")
        if client is None:
            if (
                endpoint.scheme != "https"
                or not token
                or ca_file is None
                or not expected_actor_urn
            ):
                raise ValueError(
                    "owned DataHub transport requires HTTPS, bearer token, actor, and CA"
                )
            ca_path = Path(ca_file)
            try:
                resolved_ca_path = ca_path.resolve(strict=True)
            except OSError as error:
                raise ValueError("DataHub CA file is unavailable") from error
            if not ca_path.is_absolute() or not resolved_ca_path.is_file():
                raise ValueError("DataHub CA file is unavailable")
        elif not isinstance(getattr(client, "_transport", None), httpx.MockTransport):
            # 임의 network client는 verify=False나 proxy transport로 TLS·Bearer 경계를
            # 우회할 수 있으므로 실제 socket을 열지 않는 test transport만 주입한다.
            raise ValueError("Only httpx.MockTransport may be injected")
        self._base_url = str(endpoint).rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._page_size = page_size
        self._max_entities = max_entities
        self._owns_client = client is None
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._expected_actor_urn = expected_actor_urn
        self._client = client or httpx.AsyncClient(
            headers=self._headers,
            verify=ssl.create_default_context(cafile=str(resolved_ca_path)),
            timeout=httpx.Timeout(timeout_seconds),
            trust_env=False,
        )

    @classmethod
    def from_env(
        cls,
        *,
        timeout_seconds: float = 10.0,
        page_size: int = 50,
        max_entities: int = 100_000,
    ) -> DataHubCatalogClient:
        """canonical DataHub 환경 계약으로 proxy 우회가 없는 production client를 만든다."""

        settings = DataHubConnectionSettings.from_env()
        return cls(
            settings.base_url,
            settings.token,
            ca_file=settings.ca_file,
            expected_actor_urn=settings.actor_urn,
            timeout_seconds=timeout_seconds,
            page_size=page_size,
            max_entities=max_entities,
        )

    async def graphql(
        self,
        query: str,
        variables: dict[str, object],
    ) -> dict[str, Any]:
        """GraphQL 문서와 변수를 전송해 object형 data만 반환하며 통신·형식 오류는 ``DataHubCatalogError``로 닫는다."""
        try:
            response = await self._client.post(
                f"{self._base_url}/api/graphql",
                json={"query": query, "variables": variables},
                headers=self._headers,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as error:
            raise DataHubCatalogError(
                "live DataHub lookup timed out", category="timeout"
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise DataHubCatalogError(
                "live DataHub lookup failed", category="transport"
            ) from error
        if not isinstance(payload, dict):
            raise DataHubCatalogError("live DataHub returned a non-object response")
        errors = payload.get("errors")
        if errors:
            raise DataHubCatalogError("live DataHub GraphQL request failed")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise DataHubCatalogError("live DataHub GraphQL data is missing")
        return data

    async def list_datasets(self) -> tuple[DataHubSearchHit, ...]:
        """모든 dataset URN을 페이지 누락·중복 없이 수집하고 순서가 고정된 tuple로 반환한다."""
        return await self._scroll(entity_types=("DATASET",))

    async def list_glossary_terms(self) -> tuple[DataHubSearchHit, ...]:
        """모든 Glossary Term URN을 bounded pagination으로 수집하고 불완전한 결과는 거부한다."""
        return await self._scroll(entity_types=("GLOSSARY_TERM",))

    async def search_candidates(
        self,
        query_text: str,
        *,
        entity_types: tuple[str, ...],
        count: int,
    ) -> tuple[DataHubSearchHit, ...]:
        """질문에서 유도한 질의 하나로 bounded top-K 후보만 읽고 DataHub 반환 순서를 보존한다.

        전체 열거(``list_datasets``)와 달리 pagination을 하지 않는다. 반환 순서 자체가
        DataHub의 relevance 증거이므로 호출자는 index를 rank로 쓸 수 있다. 결과는 아직
        권한 검증을 거치지 않았으므로 backend entitlement filter 이전에 후보·prompt·응답
        어디에도 노출하면 안 된다.

        실패는 열거 실패와 구분해 ``DataHubSearchUnavailableError``로 닫는다.
        """

        normalized_query = query_text.strip()
        if not normalized_query:
            raise DataHubSearchUnavailableError("search query is empty")
        if len(normalized_query) > self.MAX_CANDIDATE_QUERY_CHARACTERS:
            raise ValueError("search query exceeds the bounded candidate length")
        if (
            not entity_types
            or len(entity_types) != len(set(entity_types))
            or any(not isinstance(item, str) or not item for item in entity_types)
        ):
            raise ValueError("search entity types are required")
        if (
            isinstance(count, bool)
            or count < 1
            or count > self.MAX_CANDIDATE_RESULTS
        ):
            raise ValueError("search count is outside the bounded candidate range")
        try:
            data = await self.graphql(
                self._SEARCH_QUERY,
                {
                    "input": {
                        "types": list(entity_types),
                        "query": normalized_query,
                        "start": 0,
                        "count": count,
                        # 후보 rank는 반환 순서만 사용한다. entitlement 전 metadata 값과
                        # highlight payload를 불필요하게 읽지 않도록 둘 다 비활성화한다.
                        "searchFlags": {
                            "skipAggregates": True,
                            "skipHighlighting": True,
                        },
                    }
                },
            )
        except DataHubCatalogError as error:
            raise DataHubSearchUnavailableError(
                "live DataHub candidate search failed",
                category=error.category,
            ) from error
        page = data.get("searchAcrossEntities")
        results = page.get("searchResults") if isinstance(page, dict) else None
        start = page.get("start") if isinstance(page, dict) else None
        returned_count = page.get("count") if isinstance(page, dict) else None
        total = page.get("total") if isinstance(page, dict) else None
        if (
            not isinstance(results, list)
            or len(results) > count
            or type(start) is not int
            or start != 0
            or type(returned_count) is not int
            # DataHub Core 1.7의 ``count``는 실제 반환 행 수가 아니라 요청 window를
            # 되돌릴 수 있다. 행 수보다 작거나 요청 상한보다 큰 응답만 거부한다.
            or returned_count < len(results)
            or returned_count > count
            or type(total) is not int
            or total < len(results)
            or len(results) != min(total, count)
        ):
            raise DataHubSearchUnavailableError(
                "live DataHub candidate search result is invalid"
            )
        hits: list[DataHubSearchHit] = []
        seen: set[str] = set()
        for item in results:
            try:
                parsed_hit = self._search_hit(item)
            except DataHubCatalogError as error:
                raise DataHubSearchUnavailableError(
                    "live DataHub candidate search hit is invalid"
                ) from error
            if parsed_hit.entity_type not in entity_types:
                raise DataHubSearchUnavailableError(
                    "live DataHub candidate search returned a wrong entity type"
                )
            if parsed_hit.urn in seen:
                raise DataHubSearchUnavailableError(
                    "live DataHub candidate search returned a duplicate entity URN"
                )
            seen.add(parsed_hit.urn)
            # GraphQL selection에 없는 matchedFields를 잘못된 proxy/fake가 보내더라도
            # entitlement 전 candidate evidence에는 URN·type 외 값을 보존하지 않는다.
            hits.append(DataHubSearchHit(parsed_hit.urn, parsed_hit.entity_type))
        return tuple(hits)

    async def semantic_search(
        self,
        query_text: str,
    ) -> tuple[DataHubSearchHit, ...]:
        """자연어를 DataHub 의미 검색에 전달하며 빈 질의나 기능 부재를 ``DataHubSemanticSearchError``로 구분한다."""
        if not query_text.strip():
            raise DataHubSemanticSearchError("semantic search query is empty")
        try:
            return await self._search(
                field="semanticSearchAcrossEntities",
                query_text=query_text,
                entity_types=("DATASET",),
            )
        except DataHubCatalogError as error:
            raise DataHubSemanticSearchError(
                "live DataHub semantic search is unavailable"
            ) from error

    async def _scroll(
        self,
        *,
        entity_types: tuple[str, ...],
    ) -> tuple[DataHubSearchHit, ...]:
        """``scrollAcrossEntities``로 release 전체 멤버십을 열거한다.

        offset pagination은 10,000건 경계에서 조용히 잘리므로 canonical snapshot 열거는
        scroll cursor만 사용한다. ``nextScrollId``가 없어질 때까지 진행하고, 중복 URN,
        진행 없는 페이지, ``max_entities`` 초과를 각각 계약 위반으로 닫아 잘린 카탈로그를
        완전한 것으로 오인하지 않는다. 질문 relevance와 무관한 열거 전용 경로다.
        """

        scroll_id: str | None = None
        seen_scroll_ids: set[str] = set()
        hits: list[DataHubSearchHit] = []
        seen: set[str] = set()
        while True:
            request_input: dict[str, object] = {
                "types": list(entity_types),
                "query": "*",
                "count": self._page_size,
                "searchFlags": {
                    "skipAggregates": True,
                    "skipHighlighting": True,
                },
                # DataHub 공식 deep-pagination 계약은 score가 아닌 안정 URN
                # 정렬을 요구한다. cursor와 함께 매 페이지 같은 정렬을 보낸다.
                "sortInput": {
                    "sortCriteria": [
                        {"field": "urn", "sortOrder": "ASCENDING"}
                    ]
                },
            }
            if scroll_id is not None:
                request_input["scrollId"] = scroll_id
            data = await self.graphql(self._SCROLL_QUERY, {"input": request_input})
            page = data.get("scrollAcrossEntities")
            if not isinstance(page, dict):
                raise DataHubCatalogError(
                    "live DataHub scrollAcrossEntities result is missing"
                )
            results = page.get("searchResults")
            next_scroll_id = page.get("nextScrollId")
            count = page.get("count")
            if (
                not isinstance(results, list)
                or type(count) is not int
                or count < 0
                # DataHub Core 1.7은 마지막 scroll page에서도 요청 window 크기를
                # ``count``로 되돌릴 수 있다. 실제 행 수와 같다고 가정하지 않고,
                # 응답 행 수를 수용하는 요청 상한인지만 검증한다.
                or count < len(results)
                or count > self._page_size
                or len(results) > self._page_size
                or not (next_scroll_id is None or isinstance(next_scroll_id, str))
                or next_scroll_id == ""
            ):
                raise DataHubCatalogError("live DataHub scroll pagination is invalid")
            for item in results:
                hit = self._search_hit(item)
                if hit.entity_type not in entity_types:
                    raise DataHubCatalogError(
                        "live DataHub scroll returned a wrong entity type"
                    )
                if hit.urn in seen:
                    raise DataHubCatalogError(
                        "live DataHub scroll returned a duplicate entity URN"
                    )
                seen.add(hit.urn)
                hits.append(hit)
            if len(hits) > self._max_entities:
                raise DataHubCatalogError(
                    "live DataHub scroll exceeded the catalog entity bound"
                )
            if next_scroll_id is None:
                return tuple(hits)
            if not results:
                raise DataHubCatalogError("live DataHub scroll made no progress")
            if next_scroll_id == scroll_id or next_scroll_id in seen_scroll_ids:
                raise DataHubCatalogError("live DataHub scroll cursor did not advance")
            seen_scroll_ids.add(next_scroll_id)
            scroll_id = next_scroll_id

    async def _search(
        self,
        *,
        field: str,
        query_text: str,
        entity_types: tuple[str, ...],
    ) -> tuple[DataHubSearchHit, ...]:
        query = (
            self._SEMANTIC_QUERY
            if field == "semanticSearchAcrossEntities"
            else self._SEARCH_QUERY
        )
        start = 0
        hits: list[DataHubSearchHit] = []
        seen: set[str] = set()
        # total·start·count를 매 페이지 다시 검증해야 중간 변경이나 잘린 응답을 완전한 catalog로 오인하지 않는다.
        while True:
            data = await self.graphql(
                query,
                {
                    "input": {
                        "types": list(entity_types),
                        "query": query_text,
                        "start": start,
                        "count": self._page_size,
                    }
                },
            )
            page = data.get(field)
            if not isinstance(page, dict):
                raise DataHubCatalogError(f"live DataHub {field} result is missing")
            results = page.get("searchResults")
            total = page.get("total")
            count = page.get("count")
            page_start = page.get("start")
            if (
                not isinstance(results, list)
                or type(total) is not int
                or type(count) is not int
                or type(page_start) is not int
                or total < 0
                or count < 0
                or count < len(results)
                or count > self._page_size
                or page_start != start
                or total > self._max_entities
                or len(results) != min(self._page_size, total - start)
            ):
                raise DataHubCatalogError("live DataHub search pagination is invalid")
            for item in results:
                hit = self._search_hit(item)
                if hit.entity_type not in entity_types:
                    raise DataHubCatalogError("live DataHub search returned a wrong entity type")
                if hit.urn in seen:
                    raise DataHubCatalogError(
                        "live DataHub search returned a duplicate entity URN"
                    )
                seen.add(hit.urn)
                hits.append(hit)
            consumed = len(results)
            if start + consumed >= total:
                break
            if consumed == 0:
                raise DataHubCatalogError("live DataHub pagination made no progress")
            start += consumed
        if len(hits) != total:
            raise DataHubCatalogError(
                "live DataHub search result count differs from pagination total"
            )
        return tuple(hits)

    @staticmethod
    def _search_hit(value: object) -> DataHubSearchHit:
        if not isinstance(value, dict) or not isinstance(value.get("entity"), dict):
            raise DataHubCatalogError("live DataHub search hit is invalid")
        entity = value["entity"]
        urn = entity.get("urn")
        entity_type = entity.get("type")
        if not isinstance(urn, str) or not urn or not isinstance(entity_type, str):
            raise DataHubCatalogError("live DataHub search entity identity is invalid")
        raw_fields = value.get("matchedFields")
        if raw_fields is None:
            raw_fields = []
        if not isinstance(raw_fields, list):
            raise DataHubCatalogError("live DataHub matchedFields is invalid")
        fields: list[tuple[str, str]] = []
        for item in raw_fields:
            if not isinstance(item, dict):
                raise DataHubCatalogError("live DataHub matched field is invalid")
            name, field_value = item.get("name"), item.get("value")
            if isinstance(name, str) and isinstance(field_value, str):
                fields.append((name, field_value))
        return DataHubSearchHit(urn, entity_type, tuple(fields))

    async def get_dataset(self, urn: str) -> dict[str, Any]:
        """검색에서 얻은 dataset URN의 최신 상세 aspect를 읽으며 부재·비객체 응답은 즉시 거부한다."""
        data = await self.graphql(self._DATASET_QUERY, {"urn": urn})
        dataset = data.get("dataset")
        if not isinstance(dataset, dict):
            raise DataHubCatalogError("live DataHub dataset is unavailable")
        return dataset

    async def get_glossary_term(self, urn: str) -> dict[str, Any]:
        """Glossary Term URN의 최신 정의·custom property·native governance aspect를 객체로 반환한다."""
        data = await self.graphql(self._GLOSSARY_TERM_QUERY, {"urn": urn})
        term = data.get("glossaryTerm")
        if not isinstance(term, dict):
            raise DataHubCatalogError("live DataHub Glossary Term is unavailable")
        return term

    async def get_entity_status(self, urn: str) -> dict[str, Any]:
        """GraphQL이 누락하는 entity status를 Rest.li current aspect에서 읽는다."""

        url = httpx.URL(
            f"{self._base_url}/entitiesV2/{quote(urn, safe='')}"
        ).copy_with(query=b"aspects=List(status)")
        try:
            response = await self._client.get(
                url,
                headers={
                    **self._headers,
                    "Accept": "application/json",
                    "X-RestLi-Protocol-Version": "2.0.0",
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as error:
            raise DataHubCatalogError(
                "live DataHub status lookup timed out", category="timeout"
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise DataHubCatalogError(
                "live DataHub status lookup failed", category="transport"
            ) from error
        aspects = payload.get("aspects") if isinstance(payload, dict) else None
        wrapper = aspects.get("status") if isinstance(aspects, dict) else None
        value = wrapper.get("value") if isinstance(wrapper, dict) else None
        if payload.get("urn") != urn or not isinstance(value, dict):
            raise DataHubCatalogError("live DataHub status aspect is unavailable")
        return {"urn": urn, "status": value}

    async def get_corp_group(self, urn: str) -> dict[str, Any]:
        """release가 선언한 CorpGroup URN을 다시 읽어 owner 명칭과 설명의 실제 존재를 확인한다."""
        data = await self.graphql(self._CORP_GROUP_QUERY, {"urn": urn})
        owner = data.get("corpGroup")
        if not isinstance(owner, dict):
            raise DataHubCatalogError("live DataHub CorpGroup is unavailable")
        return owner

    async def get_domain(self, urn: str) -> dict[str, Any]:
        """release가 참조한 Domain URN을 다시 읽어 native domain 엔터티의 존재와 속성을 제공한다."""
        data = await self.graphql(self._DOMAIN_QUERY, {"urn": urn})
        domain = data.get("domain")
        if not isinstance(domain, dict):
            raise DataHubCatalogError("live DataHub Domain is unavailable")
        return domain

    async def list_lifecycle_stages(self) -> tuple[dict[str, Any], ...]:
        """DataHub native lifecycle stage 전체를 읽으며 배열 내부의 비객체 값도 계약 위반으로 거부한다."""
        data = await self.graphql(self._LIFECYCLE_QUERY, {})
        stages = data.get("listLifecycleStages")
        if not isinstance(stages, list) or any(
            not isinstance(item, dict) for item in stages
        ):
            raise DataHubCatalogError("live DataHub lifecycle stages are unavailable")
        return tuple(stages)

    async def health(self) -> bool:
        """인증된 bounded GraphQL query가 기대한 read service actor인지 확인한다."""
        try:
            data = await self.graphql(self._HEALTH_QUERY, {})
            return data == {
                "me": {"corpUser": {"urn": self._expected_actor_urn}}
            }
        except DataHubCatalogError:
            return False

    async def aclose(self) -> None:
        """직접 생성한 ``httpx.AsyncClient``만 닫아 외부에서 주입한 client의 생명주기를 침범하지 않는다."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> DataHubCatalogClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()
