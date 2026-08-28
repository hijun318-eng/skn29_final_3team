"""live DataHub 스키마와 릴리스 SQL로 카탈로그 거버넌스를 결정론적으로 발행한다."""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import unquote

import sqlglot
from sqlglot import exp

from http_client import DataHubMetadataAdminClient
from release_scope import ReleaseScope, load_release_scopes_with_serving


TECHNICAL_OWNER = "urn:li:ownershipType:__system__technical_owner"
SEARCH_QUERY = """
query CatalogDatasets($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    start count total
    searchResults { entity { urn type } }
  }
}
""".strip()
DATASET_QUERY = """
query CatalogDataset($urn: String!) {
  dataset(urn: $urn) {
    urn exists status { removed }
    properties { name description }
    ownership {
      owners {
        owner { ... on CorpUser { urn } ... on CorpGroup { urn } }
        type ownershipType { urn }
      }
    }
    domain { domain { urn } }
    tags { tags { tag { urn } } }
    glossaryTerms { terms { term { urn } } }
    schemaMetadata {
      name
      fields {
        fieldPath nativeDataType nullable description
        glossaryTerms { terms { term { urn } } }
      }
    }
    editableSchemaMetadata {
      editableSchemaFieldInfo {
        fieldPath description
        glossaryTerms { terms { term { urn } } }
      }
    }
    lineage(input: {direction: UPSTREAM, start: 0, count: 100}) {
      relationships { entity { urn type } }
    }
  }
}
""".strip()
ADD_OWNER = """
mutation AddCatalogOwner($input: AddOwnerInput!) { addOwner(input: $input) }
""".strip()
SET_DOMAIN = """
mutation SetCatalogDomain($entityUrn: String!, $domainUrn: String!) {
  setDomain(entityUrn: $entityUrn, domainUrn: $domainUrn)
}
""".strip()
ADD_TAG = """
mutation AddCatalogTag($input: TagAssociationInput!) { addTag(input: $input) }
""".strip()
UPDATE_LINEAGE = """
mutation UpdateCatalogLineage($input: UpdateLineageInput!) { updateLineage(input: $input) }
""".strip()


@dataclass(frozen=True)
class CatalogField:
    """DataHub가 발행한 컬럼 식별자와 설명을 용어 연결용 불변값으로 보존한다."""

    name: str
    description: str


@dataclass(frozen=True)
class CatalogDataset:
    """한 release scope에 속하는 활성 dataset과 필드 목록을 표현한다."""

    urn: str
    logical_fqn: str
    display_name: str
    description: str
    scope: ReleaseScope
    fields: tuple[CatalogField, ...]


@dataclass(frozen=True)
class GovernancePlan:
    """발행할 참조 엔터티·연결·lineage의 정확한 기대 집합을 묶는다."""

    datasets: tuple[CatalogDataset, ...]
    owner_urn: str
    domains: Mapping[ReleaseScope, str]
    tags: Mapping[str, tuple[str, str]]
    lineage_edges: tuple[tuple[str, str], ...]


def recipe_paths(directory: Path) -> tuple[Path, ...]:
    """운영 runtime recipe 전체를 이름순으로 반환하고 누락 시 중단한다."""

    paths = tuple(sorted(directory.glob("*.runtime.yml")))
    if not paths:
        raise ValueError("runtime ingestion recipes are missing")
    return paths


async def discover_catalog(
    client: DataHubMetadataAdminClient,
    scopes: tuple[ReleaseScope, ...],
) -> tuple[CatalogDataset, ...]:
    """모든 활성 dataset을 페이지 끝까지 읽고 정확히 한 scope에 귀속시킨다."""

    urns: list[str] = []
    start = 0
    total: int | None = None
    while total is None or start < total:
        data = await client.graphql(
            SEARCH_QUERY,
            {"input": {"types": ["DATASET"], "query": "*", "start": start, "count": 100}},
        )
        graph = _mapping(data.get("data"), "GraphQL data")
        page = _mapping(graph.get("searchAcrossEntities"), "dataset search")
        total = _integer(page.get("total"), "dataset search total")
        hits = page.get("searchResults")
        if not isinstance(hits, list) or (not hits and start < total):
            raise ValueError("DataHub dataset pagination stopped early")
        for hit in hits:
            entity = _mapping(_mapping(hit, "search hit").get("entity"), "search entity")
            urns.append(_text(entity.get("urn"), "dataset URN"))
        start += len(hits)
    if len(urns) != total or len(set(urns)) != total:
        raise ValueError("DataHub dataset pagination is incomplete or duplicate")
    datasets = []
    for urn in urns:
        data = await client.graphql(DATASET_QUERY, {"urn": urn})
        graph = _mapping(data.get("data"), "GraphQL data")
        raw = _mapping(graph.get("dataset"), "dataset")
        if raw.get("exists") is False or _mapping(raw.get("status"), "status").get("removed") is not False:
            raise ValueError("active search returned a removed or missing dataset")
        schema = _mapping(raw.get("schemaMetadata"), "schema metadata")
        scope, table = _dataset_scope(urn, _text(schema.get("name"), "schema name"), scopes)
        properties = _mapping(raw.get("properties"), "dataset properties")
        fields = tuple(
            CatalogField(
                _text(_mapping(field, "schema field").get("fieldPath"), "field path"),
                _text(_mapping(field, "schema field").get("description"), "field description"),
            )
            for field in _list(schema.get("fields"), "schema fields")
        )
        if len({field.name for field in fields}) != len(fields):
            raise ValueError("DataHub schema contains duplicate field paths")
        datasets.append(
            CatalogDataset(
                urn=urn,
                logical_fqn=f"{scope.catalog}.{scope.schema}.{table}",
                display_name=_text(properties.get("name"), "dataset name"),
                description=_text(properties.get("description"), "dataset description"),
                scope=scope,
                fields=fields,
            )
        )
    return tuple(sorted(datasets, key=lambda item: item.logical_fqn))


def build_plan(
    datasets: tuple[CatalogDataset, ...],
    scopes: tuple[ReleaseScope, ...],
    release_version: str,
    owner_urn: str,
    release_directory: Path,
) -> GovernancePlan:
    """live catalog에서 domain·tag·lineage 기대값만 구성한다."""

    if not owner_urn.startswith("urn:li:corpuser:"):
        raise ValueError("catalog owner must be an explicit DataHub corp user")
    version = _text(release_version, "release version")
    if {dataset.scope for dataset in datasets} != set(scopes):
        raise ValueError("every release scope must contain at least one dataset")
    domains = {
        scope: f"urn:li:domain:answervice_{_slug(scope.catalog)}"
        for scope in scopes
    }
    tags: dict[str, tuple[str, str]] = {
        "synthetic": (
            "Synthetic Data",
            "실제 고객·운영 원천이 아닌 재현 가능한 합성 데이터임을 표시한다.",
        ),
        f"release_{_slug(version)}": (
            version,
            f"검증된 {version} 데이터 릴리스에 속하는 카탈로그 엔터티다.",
        ),
    }
    for scope in scopes:
        tags[f"scope_{_slug(scope.catalog)}"] = (
            _scope_name(scope),
            f"{scope.catalog}.{scope.schema} 물리 scope에서 발견된 데이터셋이다.",
        )
    fqn_to_urn = {dataset.logical_fqn: dataset.urn for dataset in datasets}
    lineage_edges = _lineage_edges(release_directory, fqn_to_urn)
    serving = {item.urn for item in datasets if item.scope.catalog == "serving"}
    if {downstream for downstream, _ in lineage_edges} != serving:
        raise ValueError("release SQL must define lineage for every serving dataset")
    return GovernancePlan(
        datasets=datasets,
        owner_urn=owner_urn,
        domains=domains,
        tags=tags,
        lineage_edges=lineage_edges,
    )


async def publish_plan(
    client: DataHubMetadataAdminClient,
    plan: GovernancePlan,
    release_version: str,
) -> dict[str, int]:
    """참조 엔터티를 먼저 생성한 뒤 dataset 연결과 lineage를 발행한다."""

    stamp = {"actor": plan.owner_urn, "time": time.time_ns() // 1_000_000}
    for scope, urn in sorted(plan.domains.items(), key=lambda item: item[0]):
        await client.upsert_entity(
            "domain",
            urn,
            {
                "domainKey": {"id": urn.removeprefix("urn:li:domain:")},
                "domainProperties": {
                    "name": _scope_name(scope),
                    "description": f"{scope.catalog}.{scope.schema}의 검증된 카탈로그 데이터 도메인",
                },
            },
            stamp,
        )
    tag_urns: dict[str, str] = {}
    for tag_id, (name, description) in sorted(plan.tags.items()):
        urn = f"urn:li:tag:answervice_{tag_id}"
        tag_urns[tag_id] = urn
        await client.upsert_entity(
            "tag",
            urn,
            {
                "tagKey": {"name": urn.removeprefix("urn:li:tag:")},
                "tagProperties": {"name": name, "description": description},
            },
            stamp,
        )
    mutation_groups: list[list[tuple[str, Mapping[str, Any]]]] = []
    for dataset in plan.datasets:
        dataset_mutations: list[tuple[str, Mapping[str, Any]]] = [
                (
                    ADD_OWNER,
                    {"input": {"ownerUrn": plan.owner_urn, "ownerEntityType": "CORP_USER", "ownershipTypeUrn": TECHNICAL_OWNER, "resourceUrn": dataset.urn}},
                ),
                (SET_DOMAIN, {"entityUrn": dataset.urn, "domainUrn": plan.domains[dataset.scope]}),
                (ADD_TAG, {"input": {"tagUrn": tag_urns["synthetic"], "resourceUrn": dataset.urn}}),
                (ADD_TAG, {"input": {"tagUrn": tag_urns[f"release_{_slug(release_version)}"], "resourceUrn": dataset.urn}}),
                (ADD_TAG, {"input": {"tagUrn": tag_urns[f"scope_{_slug(dataset.scope.catalog)}"], "resourceUrn": dataset.urn}}),
            ]
        mutation_groups.append(dataset_mutations)
    await _run_mutation_groups(client, mutation_groups)
    await client.graphql(
        UPDATE_LINEAGE,
        {"input": {"edgesToAdd": [{"downstreamUrn": downstream, "upstreamUrn": upstream} for downstream, upstream in plan.lineage_edges], "edgesToRemove": []}},
    )
    return {
        "datasets": len(plan.datasets),
        "fields": sum(len(dataset.fields) for dataset in plan.datasets),
        "domains": len(plan.domains),
        "tags": len(tag_urns),
        "glossary_terms": 0,
        "lineage_edges": len(plan.lineage_edges),
    }


async def _run_mutation_groups(
    client: DataHubMetadataAdminClient,
    groups: Sequence[Sequence[tuple[str, Mapping[str, Any]]]],
    concurrency: int = 12,
) -> None:
    """dataset끼리는 병렬, 같은 dataset의 aspect mutation은 순차 실행한다."""

    semaphore = asyncio.Semaphore(concurrency)

    async def run(group: Sequence[tuple[str, Mapping[str, Any]]]) -> None:
        async with semaphore:
            # WHY: tags와 editableSchemaMetadata는 동일 aspect를 read-modify-write하므로
            # 같은 dataset에서 병렬 실행하면 정상 응답이어도 마지막 write가 앞선 연결을 잃는다.
            for query, variables in group:
                await client.graphql(query, variables)

    await asyncio.gather(*(run(group) for group in groups))


def _lineage_edges(
    release_directory: Path,
    fqn_to_urn: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    """CREATE VIEW AST에서만 직접 upstream dataset edge를 추출한다."""

    if not release_directory.is_dir():
        raise ValueError("release directory is unavailable")
    edges: set[tuple[str, str]] = set()
    views: set[str] = set()
    sql_paths = tuple(
        sorted(
            path
            for path in release_directory.rglob("*.sql")
            if "06_trino_serving" in path.parts
        )
    )
    if not sql_paths:
        raise ValueError("release directory contains no Trino serving SQL")
    # WHY: 다른 DB dialect의 DDL·seed를 Trino로 오해하지 않고, 운영 serving view만
    # SQLGlot AST로 해석해야 lineage가 질문별 문자열 규칙으로 퇴행하지 않는다.
    for path in sql_paths:
        try:
            statements = sqlglot.parse(path.read_text(encoding="utf-8"), read="trino")
        except (OSError, sqlglot.errors.ParseError) as error:
            raise ValueError(f"release SQL is not parseable: {path.name}") from error
        for statement in statements:
            if not isinstance(statement, exp.Create) or str(statement.args.get("kind", "")).upper() != "VIEW":
                continue
            target = statement.this.sql(dialect="trino")
            if target not in fqn_to_urn:
                continue
            views.add(target)
            aliases = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
            for table in statement.expression.find_all(exp.Table):
                if table.name in aliases:
                    continue
                source = ".".join(part for part in (table.catalog, table.db, table.name) if part)
                if source not in fqn_to_urn:
                    raise ValueError(f"view lineage references an unknown dataset: {source}")
                edges.add((fqn_to_urn[target], fqn_to_urn[source]))
    if not views:
        raise ValueError("release SQL contains no governed views")
    return tuple(sorted(edges))


def _dataset_scope(
    urn: str,
    schema_name: str,
    scopes: tuple[ReleaseScope, ...],
) -> tuple[ReleaseScope, str]:
    decoded = unquote(urn)
    match = re.fullmatch(r"urn:li:dataset:\(urn:li:dataPlatform:[^,]+,(.+),[^,]+\)", decoded)
    if match is None:
        raise ValueError("dataset URN has an unsupported shape")
    key_name = match.group(1)
    matches = [
        scope
        for scope in scopes
        if key_name.startswith(f"{scope.platform_instance}.")
        and schema_name.startswith(f"{scope.datahub_namespace}.")
    ]
    if len(matches) != 1:
        raise ValueError("dataset does not resolve to exactly one runtime scope")
    scope = matches[0]
    return scope, schema_name.removeprefix(f"{scope.datahub_namespace}.")


def _scope_name(scope: ReleaseScope) -> str:
    name = scope.catalog.replace("_", " ")
    return name.upper() if len(name) <= 8 else name.title()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not slug:
        raise ValueError("catalog identity cannot be converted to a stable slug")
    return slug


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return value


def _list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a non-empty list")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be non-empty text")
    return value.strip()


def _integer(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def runtime_scopes(
    recipe_directory: Path,
    serving_schema: str,
) -> tuple[ReleaseScope, ...]:
    """source recipes와 명시된 active serving schema에서 release scope를 해석한다."""

    return load_release_scopes_with_serving(
        recipe_paths(recipe_directory),
        os.environ,
        serving_schema,
    )
