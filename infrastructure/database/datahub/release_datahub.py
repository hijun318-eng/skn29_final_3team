"""로컬 DataHub GraphQL에서 scoped base schema와 native governance를 읽는다."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx

from http_client import DataHubMetadataAdminClient
from release_datahub_queries import (
    DATASET_QUERY,
    LIFECYCLE_QUERY,
    SEARCH_QUERY,
    TERM_QUERY,
)
from release_scope import ReleaseScope
from src.data.governance_contract import datahub_schema_readback_sha1


PROPERTY_PREFIX = "answervice."


class DataHubDiscoveryError(RuntimeError):
    """DataHub discovery가 불완전하거나 모호하거나 구조적으로 잘못됐음을 나타낸다."""


@dataclass(frozen=True)
class NativeEntity:
    """로컬 이름 매핑 없이 보존한 DataHub native governance entity다."""

    urn: str
    name: str | None
    description: str | None
    entity_type: str


@dataclass(frozen=True)
class DataHubField:
    """DataHub GraphQL이 반환한 schema field 하나의 검증된 표현이다."""

    name: str
    native_type: str | None
    nullable: bool | None
    is_part_of_key: bool | None
    description: str | None


@dataclass(frozen=True)
class DataHubDataset:
    """release 대조에 필요한 dataset schema와 governance surface를 표현한다."""

    urn: str
    dataset_key_name: str
    origin: str
    platform_urn: str
    name: str | None
    qualified_name: str | None
    description: str | None
    schema_name: str
    schema_version: int
    schema_hash: str
    removed: bool | None
    owners: tuple[NativeEntity, ...]
    domain: NativeEntity | None
    lifecycle: NativeEntity | None
    custom_properties: dict[str, str]
    fields: tuple[DataHubField, ...]


@dataclass(frozen=True)
class DataHubTerm:
    """glossary term과 native owner·domain·lifecycle governance를 표현한다."""

    urn: str
    exists: bool | None
    name: str | None
    description: str | None
    removed: bool | None
    owners: tuple[NativeEntity, ...]
    domain: NativeEntity | None
    lifecycle: NativeEntity | None
    custom_properties: dict[str, str]


class DataHubDiscoveryClient:
    """runtime recipe의 platform instance가 선택한 dataset만 발견한다."""

    def __init__(
        self,
        server: str,
        *,
        token: str | None = None,
        ca_file: str | Path | None = None,
        http: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20.0,
        page_size: int = 100,
        max_entities: int = 2_000,
        concurrency: int = 8,
    ) -> None:
        if (
            page_size < 1
            or max_entities < page_size
            or concurrency < 1
            or timeout_seconds <= 0
        ):
            raise ValueError("DataHub discovery bounds are invalid")
        self._client = DataHubMetadataAdminClient(
            server,
            token=token,
            ca_file=ca_file,
            timeout_seconds=timeout_seconds,
            http=http,
        )
        self._page_size = page_size
        self._max_entities = max_entities
        self._concurrency = concurrency

    async def discover_datasets(
        self,
        scopes: tuple[ReleaseScope, ...],
    ) -> tuple[DataHubDataset, ...]:
        """전체 dataset을 발견한 뒤 runtime recipe identity 범위만 반환한다."""

        identities = {(scope.platform_instance, scope.origin) for scope in scopes}
        urns = [
            urn
            for urn in await self._search_dataset_urns()
            if _in_platform_scope(urn, identities)
        ]
        semaphore = asyncio.Semaphore(self._concurrency)

        async def fetch(urn: str) -> DataHubDataset:
            async with semaphore:
                payload = await self._client.graphql(DATASET_QUERY, {"urn": urn})
                return _dataset(_data_field(payload, "dataset", urn))

        datasets = await asyncio.gather(*(fetch(urn) for urn in urns))
        return tuple(sorted(datasets, key=lambda item: item.urn))

    async def discover_terms(self, urns: tuple[str, ...]) -> tuple[DataHubTerm, ...]:
        """term 본문과 Rest.li status를 lifecycle 정의와 교차 검증한다.

        DataHub v1.7 GraphQL은 GlossaryTerm의 ``status``를 null로 반환하므로
        활성·승인 상태는 동일 URN의 Rest.li aspect에서 읽는다. lifecycle
        이름·설명은 서버가 반환한 정의와 URN을 맞추어 로컬 추론을 막는다.
        """

        if len(urns) != len(set(urns)):
            raise DataHubDiscoveryError("release manifest contains duplicate term URNs")
        lifecycle_payload = await self._client.graphql(LIFECYCLE_QUERY, {})
        lifecycles = _lifecycle_stages(
            lifecycle_payload.get("data") if isinstance(lifecycle_payload, dict) else None
        )
        semaphore = asyncio.Semaphore(self._concurrency)

        async def fetch(urn: str) -> DataHubTerm:
            if not urn.startswith("urn:li:glossaryTerm:"):
                raise DataHubDiscoveryError("release manifest term URN is invalid")
            async with semaphore:
                payload, entity = await asyncio.gather(
                    self._client.graphql(TERM_QUERY, {"urn": urn}),
                    self._client.get_entity(urn, ("status",)),
                )
                return _term(
                    _data_field(payload, "glossaryTerm", urn),
                    _status_aspect(entity),
                    lifecycles,
                )

        terms = await asyncio.gather(*(fetch(urn) for urn in urns))
        return tuple(sorted(terms, key=lambda item: item.urn))

    async def _search_dataset_urns(self) -> tuple[str, ...]:
        start = 0
        urns: list[str] = []
        seen: set[str] = set()
        while True:
            payload = await self._client.graphql(
                SEARCH_QUERY,
                {
                    "input": {
                        "types": ["DATASET"],
                        "query": "*",
                        "start": start,
                        "count": self._page_size,
                    }
                },
            )
            page = _data_field(payload, "searchAcrossEntities")
            results = page.get("searchResults")
            total, count, page_start = page.get("total"), page.get("count"), page.get("start")
            if (
                not isinstance(results, list)
                or not isinstance(total, int)
                or isinstance(total, bool)
                or not isinstance(count, int)
                or isinstance(count, bool)
                or not isinstance(page_start, int)
                or isinstance(page_start, bool)
                or total < 0
                or count < 0
                or total > self._max_entities
                or page_start != start
            ):
                raise DataHubDiscoveryError("DataHub dataset pagination is invalid")
            for item in results:
                if not isinstance(item, dict) or not isinstance(item.get("entity"), dict):
                    raise DataHubDiscoveryError("DataHub dataset search hit is invalid")
                entity = item["entity"]
                urn, entity_type = entity.get("urn"), entity.get("type")
                if (
                    not isinstance(urn, str)
                    or not urn
                    or entity_type != "DATASET"
                    or urn in seen
                ):
                    raise DataHubDiscoveryError("DataHub dataset search identity is invalid")
                seen.add(urn)
                urns.append(urn)
            consumed = len(results)
            if start + consumed >= total:
                break
            if consumed == 0:
                raise DataHubDiscoveryError("DataHub dataset pagination made no progress")
            start += consumed
        if len(urns) != total:
            raise DataHubDiscoveryError("DataHub dataset count differs from pagination total")
        return tuple(urns)

    async def aclose(self) -> None:
        """소유한 metadata transport와 내부 HTTP resource를 닫는다."""

        await self._client.aclose()

    async def __aenter__(self) -> DataHubDiscoveryClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()


def dataset_key(urn: str) -> tuple[str, str, str]:
    """catalog 또는 schema를 가정하지 않고 DataHub dataset URN key를 해석한다."""

    prefix = "urn:li:dataset:("
    if not urn.startswith(prefix) or not urn.endswith(")"):
        raise DataHubDiscoveryError("DataHub dataset URN is invalid")
    inner = urn[len(prefix):-1]
    first, last = inner.find(","), inner.rfind(",")
    if first < 1 or last <= first + 1 or last >= len(inner) - 1:
        raise DataHubDiscoveryError("DataHub dataset key is invalid")
    platform, name, origin = inner[:first], inner[first + 1:last], inner[last + 1:]
    if not platform.startswith("urn:li:dataPlatform:") or not name or not origin:
        raise DataHubDiscoveryError("DataHub dataset key is invalid")
    return platform, name, origin


def _in_platform_scope(
    urn: str,
    identities: set[tuple[str, str]],
) -> bool:
    _platform, name, origin = dataset_key(urn)
    return any(
        origin == expected_origin and name.startswith(f"{instance}.")
        for instance, expected_origin in identities
    )


def _dataset(value: dict[str, Any]) -> DataHubDataset:
    urn = _text(value.get("urn"), "dataset.urn")
    platform, key_name, origin = dataset_key(urn)
    properties = _optional_mapping(value.get("properties"))
    schema = _mapping(value.get("schemaMetadata"), "dataset.schemaMetadata")
    status = _optional_mapping(value.get("status"))
    native_fields = tuple(
        _field(item) for item in _list(schema.get("fields"), "schema fields")
    )
    editable_descriptions = _editable_descriptions(
        value.get("editableSchemaMetadata"),
        {field.name for field in native_fields},
    )
    fields = tuple(
        replace(
            field,
            description=editable_descriptions.get(field.name) or field.description,
        )
        for field in native_fields
    )
    if not fields or len({field.name for field in fields}) != len(fields):
        raise DataHubDiscoveryError("DataHub schema fields are empty or duplicated")
    if any(
        field.native_type is None or field.nullable is None
        for field in fields
    ):
        raise DataHubDiscoveryError("DataHub schema field type or nullability is missing")
    version = schema.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise DataHubDiscoveryError("DataHub schema version is invalid")
    platform_urn = _text(schema.get("platformUrn"), "schema platformUrn")
    if platform_urn != platform:
        raise DataHubDiscoveryError("DataHub dataset and schema platforms differ")
    return DataHubDataset(
        urn=urn,
        dataset_key_name=key_name,
        origin=origin,
        platform_urn=platform,
        name=_optional_text(value.get("name")),
        qualified_name=_optional_text(properties.get("qualifiedName")),
        description=_optional_text(properties.get("description")),
        schema_name=_text(schema.get("name"), "schema name"),
        schema_version=version,
        schema_hash=datahub_schema_readback_sha1(
            [
                {
                    "name": field.name,
                    "ordinal_position": ordinal,
                    "native_type": field.native_type,
                    "nullable": field.nullable,
                }
                for ordinal, field in enumerate(fields, start=1)
            ]
        ),
        removed=status.get("removed") if isinstance(status.get("removed"), bool) else None,
        owners=_owners(value.get("ownership")),
        domain=_domain(value.get("domain")),
        lifecycle=_lifecycle(status.get("lifecycleStage")),
        custom_properties=_custom_properties(properties.get("customProperties")),
        fields=fields,
    )


def _term(
    value: dict[str, Any],
    status: dict[str, Any],
    lifecycles: dict[str, NativeEntity],
) -> DataHubTerm:
    urn = _text(value.get("urn"), "glossary term URN")
    info = _optional_mapping(value.get("glossaryTermInfo"))
    exists = value.get("exists")
    removed = status.get("removed")
    lifecycle_urn = status.get("lifecycleStage")
    if not isinstance(removed, bool) or not isinstance(lifecycle_urn, str):
        raise DataHubDiscoveryError("glossary term status aspect is incomplete")
    return DataHubTerm(
        urn=urn,
        exists=exists if isinstance(exists, bool) else None,
        name=_optional_text(info.get("name")),
        description=_optional_text(info.get("description")),
        removed=removed,
        owners=_owners(value.get("ownership")),
        domain=_domain(value.get("domain")),
        lifecycle=lifecycles.get(lifecycle_urn),
        custom_properties=_custom_properties(info.get("customProperties")),
    )


def _status_aspect(entity: object) -> dict[str, Any]:
    """Rest.li entity envelope에서 glossary status 값을 정확히 추출한다."""

    root = _mapping(entity, "glossary term Rest.li entity")
    aspects = _mapping(root.get("aspects"), "glossary term aspects")
    wrapper = _mapping(aspects.get("status"), "glossary term status wrapper")
    return _mapping(wrapper.get("value"), "glossary term status")


def _lifecycle_stages(data: object) -> dict[str, NativeEntity]:
    """GraphQL lifecycle 목록을 중복 없는 URN 사전으로 검증한다."""

    root = _mapping(data, "lifecycle GraphQL data")
    raw = _list(root.get("listLifecycleStages"), "lifecycle stages")
    stages = [
        NativeEntity(
            urn=_text(item.get("urn"), "lifecycle URN"),
            name=_optional_text(item.get("name")),
            description=_optional_text(item.get("description")),
            entity_type="LifecycleStage",
        )
        for item in (_mapping(value, "lifecycle stage") for value in raw)
    ]
    if len({stage.urn for stage in stages}) != len(stages):
        raise DataHubDiscoveryError("DataHub lifecycle stages are duplicated")
    return {stage.urn: stage for stage in stages}


def _field(value: object) -> DataHubField:
    item = _mapping(value, "schema field")
    nullable, key = item.get("nullable"), item.get("isPartOfKey")
    return DataHubField(
        name=_text(item.get("fieldPath"), "schema field path"),
        native_type=_optional_text(item.get("nativeDataType")),
        nullable=nullable if isinstance(nullable, bool) else None,
        is_part_of_key=key if isinstance(key, bool) else None,
        description=_optional_text(item.get("description")),
    )


def _editable_descriptions(
    value: object,
    native_names: set[str],
) -> dict[str, str | None]:
    """DataHub editable field 설명을 native field identity에만 결합한다."""

    editable = _optional_mapping(value)
    raw_fields = editable.get("editableSchemaFieldInfo") or []
    if not isinstance(raw_fields, list):
        raise DataHubDiscoveryError("DataHub editable schema fields are invalid")
    result: dict[str, str | None] = {}
    for raw in raw_fields:
        field = _mapping(raw, "editable schema field")
        name = _text(field.get("fieldPath"), "editable schema field path")
        if name in result or name not in native_names:
            raise DataHubDiscoveryError(
                "DataHub editable schema fields are duplicate or unknown"
            )
        result[name] = _optional_text(field.get("description"))
    return result


def _owners(value: object) -> tuple[NativeEntity, ...]:
    ownership = _optional_mapping(value)
    raw = ownership.get("owners") or []
    if not isinstance(raw, list):
        raise DataHubDiscoveryError("DataHub ownership is invalid")
    result = []
    for item in raw:
        owner = _mapping(_mapping(item, "owner record").get("owner"), "owner")
        kind = _text(owner.get("__typename"), "owner type")
        info = _optional_mapping(owner.get("info"))
        properties = _optional_mapping(owner.get("properties"))
        result.append(
            NativeEntity(
                urn=_text(owner.get("urn"), "owner URN"),
                name=_optional_text(
                    info.get("displayName")
                    or properties.get("displayName")
                    or owner.get("name")
                    or owner.get("username")
                ),
                description=_optional_text(info.get("description")),
                entity_type=kind,
            )
        )
    return tuple(sorted(result, key=lambda item: item.urn))


def _domain(value: object) -> NativeEntity | None:
    wrapper = _optional_mapping(value)
    raw = wrapper.get("domain")
    if raw is None:
        return None
    entity = _mapping(raw, "domain")
    properties = _optional_mapping(entity.get("properties"))
    return NativeEntity(
        urn=_text(entity.get("urn"), "domain URN"),
        name=_optional_text(properties.get("name")),
        description=_optional_text(properties.get("description")),
        entity_type="Domain",
    )


def _lifecycle(value: object) -> NativeEntity | None:
    if value is None:
        return None
    entity = _mapping(value, "lifecycle stage")
    return NativeEntity(
        urn=_text(entity.get("urn"), "lifecycle URN"),
        name=_optional_text(entity.get("name")),
        description=_optional_text(entity.get("description")),
        entity_type="LifecycleStage",
    )


def _custom_properties(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise DataHubDiscoveryError("DataHub custom properties are invalid")
    result: dict[str, str] = {}
    for raw in value:
        item = _mapping(raw, "custom property")
        key, property_value = item.get("key"), item.get("value")
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(property_value, str)
            or key in result
        ):
            raise DataHubDiscoveryError("DataHub custom property is invalid or duplicated")
        result[key] = property_value
    return result


def _data_field(payload: object, field: str, urn: str | None = None) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    value = data.get(field) if isinstance(data, dict) else None
    if not isinstance(value, dict) or (urn is not None and value.get("urn") != urn):
        raise DataHubDiscoveryError(f"DataHub GraphQL field is missing: {field}")
    return value


def _mapping(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DataHubDiscoveryError(f"{context} must be an object")
    return value


def _optional_mapping(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    return _mapping(value, "optional DataHub value")


def _list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise DataHubDiscoveryError(f"{context} must be an array")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataHubDiscoveryError(f"{context} must be non-empty text")
    return value


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
