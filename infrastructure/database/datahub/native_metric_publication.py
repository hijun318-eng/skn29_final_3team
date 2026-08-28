"""DataHub v1.7 native Metric shadow의 외부 발행과 exact read-back을 소유한다.

순수 Metric/aspect 투영은 ``native_metric_shadow``가 담당한다. 이 모듈은 별도
publish/read identity, bounded HTTP transport, Rest.li aspect 대조, GraphQL 관계 index
검증만 수행하며 read-back 성공을 Backend runtime activation으로 해석하지 않는다.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

from http_client import DataHubMetadataAdminClient
from metadata_rest import assert_contains, aspect_value, preflight_owner_entities
from metadata_wire import validated_audit_stamp
from native_metric_shadow import (
    DATAHUB_NATIVE_MODEL_VERSION,
    NativeMetricShadowError,
    iter_native_metric_aspects,
    native_metric_shadow_projection,
)


_METRIC_ENTITY_PROBE = """
query NativeMetricEntityProbe {
  searchAcrossEntities(
    input: {types: [METRIC], query: "*", start: 0, count: 1}
  ) {
    total
    count
    start
  }
}
"""
_NATIVE_METRIC_QUERY = """
query NativeMetricReadback($urn: String!) {
  metric(urn: $urn) {
    urn
    type
    id
    path
    exists
    platform { urn }
    info {
      name
      description
      expression { dialects { dialect expression } }
    }
    aiContext { synonyms instructions examples customInstructions }
    status { removed lifecycleStage { urn } }
    ownership {
      owners {
        type
        associatedUrn
        ownershipType { urn }
        owner { ... on CorpUser { urn } ... on CorpGroup { urn } }
      }
    }
    domain { domain { urn } }
    glossaryTerms { terms { term { urn } } }
    metricRelationships {
      derivedFrom { destination { urn type } }
      relatedMetrics { destination { urn type } }
    }
    metricUpstreams {
      datasetUpstreams { destination { urn type } }
      fieldUpstreams { destination { urn type } }
    }
  }
}
"""


def _epoch_ms() -> int:
    return time.time_ns() // 1_000_000


async def probe_native_metric_model(client: Any) -> dict[str, Any]:
    """현재 GMS가 pinned native Metric entity type을 실제 GraphQL에 등록했는지 확인한다."""

    payload = await client.graphql(_METRIC_ENTITY_PROBE, {})
    data = payload.get("data") if isinstance(payload, Mapping) else None
    result = data.get("searchAcrossEntities") if isinstance(data, Mapping) else None
    if not isinstance(result, Mapping):
        raise NativeMetricShadowError(
            "DataHub native Metric entity probe returned no result"
        )
    total, count, start = result.get("total"), result.get("count"), result.get("start")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or not isinstance(start, int)
        or isinstance(start, bool)
        or total < 0
        or count < 0
        or start != 0
    ):
        raise NativeMetricShadowError(
            "DataHub native Metric entity probe is malformed"
        )
    return {
        "status": "NATIVE_METRIC_ENTITY_AVAILABLE",
        "datahub_model_version": DATAHUB_NATIVE_MODEL_VERSION,
        "existing_metric_count": total,
    }


async def publish_native_metric_shadow(
    server: str,
    bundle: dict[str, object],
    *,
    actor_urn: str,
    expected_projection_sha256: str,
    token: str | None = None,
    ca_file: str | Path | None = None,
    timeout: float = 30.0,
    http: httpx.AsyncClient | None = None,
    clock: Callable[[], int] = _epoch_ms,
) -> dict[str, Any]:
    """사전 check의 exact projection hash가 일치할 때만 out-of-place shadow를 발행한다."""

    projection = native_metric_shadow_projection(bundle)
    if projection["projection_sha256"] != expected_projection_sha256:
        raise NativeMetricShadowError(
            "native Metric shadow projection differs from the checked release"
        )
    audit_stamp = validated_audit_stamp({"actor": actor_urn, "time": clock()})
    async with DataHubMetadataAdminClient(
        server,
        token=token,
        ca_file=ca_file,
        timeout_seconds=timeout,
        http=http,
    ) as client:
        model_probe = await probe_native_metric_model(client)
        await preflight_owner_entities(client, bundle)
        for (entity_type, urn), aspects in _grouped_aspects(bundle).items():
            await client.upsert_entity(entity_type, urn, aspects, audit_stamp)
    return {
        **projection,
        "status": "SHADOW_PUBLISHED_NOT_ACTIVE",
        "model_probe": model_probe,
    }


async def verify_native_metric_shadow(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    expected_projection_sha256: str,
) -> dict[str, Any]:
    """read identity로 native Metric aspect와 GraphQL 관계 전체를 checked projection과 대조한다."""

    projection = native_metric_shadow_projection(bundle)
    if projection["projection_sha256"] != expected_projection_sha256:
        raise NativeMetricShadowError(
            "native Metric read-back projection differs from the checked release"
        )
    for (_entity_type, urn), expected_aspects in _grouped_aspects(bundle).items():
        entity = await client.get_entity(urn, tuple(expected_aspects))
        for name, expected in expected_aspects.items():
            assert_contains(aspect_value(entity, name), expected, f"{urn}.{name}")
    graph_metric_count = await _verify_native_metric_graph(client, bundle)
    return {
        **projection,
        "status": "SHADOW_READBACK_VERIFIED_NOT_ACTIVE",
        "runtime_cutover_ready": False,
        "graphql_metric_count": graph_metric_count,
    }


async def _verify_native_metric_graph(
    client: Any,
    bundle: Mapping[str, Any],
) -> int:
    """Metric identity와 native lineage edge가 GraphQL graph에 반영됐는지 대조한다."""

    grouped = _grouped_aspects(bundle)
    for (_entity_type, urn), aspects in grouped.items():
        payload = await client.graphql(_NATIVE_METRIC_QUERY, {"urn": urn})
        data = payload.get("data") if isinstance(payload, Mapping) else None
        metric = data.get("metric") if isinstance(data, Mapping) else None
        key = aspects["metricKey"]
        info = aspects["metricInfo"]
        if (
            not isinstance(metric, Mapping)
            or metric.get("urn") != urn
            or metric.get("type") != "METRIC"
            or metric.get("id") != key["id"]
            or metric.get("path") != key["path"]
            or metric.get("exists") is not True
            or _nested_urn(metric.get("platform")) != key["platform"]
            or not isinstance(metric.get("info"), Mapping)
            or metric["info"].get("name") != info["name"]
            or metric["info"].get("description") != info["description"]
            or metric["info"].get("expression") != info["expression"]
        ):
            raise NativeMetricShadowError(
                "DataHub native Metric GraphQL identity differs"
            )
        _assert_native_ai_context_graph(metric.get("aiContext"), aspects["aiContext"])
        _assert_native_governance_graph(metric, aspects, urn)
        _assert_native_lineage_graph(metric, aspects)
    return len(grouped)


def _assert_native_ai_context_graph(
    actual: object,
    expected: Mapping[str, Any],
) -> None:
    """GraphQL optional field의 명시적 null과 Rest.li key 부재를 동등하게 대조한다."""

    if not isinstance(actual, Mapping):
        raise NativeMetricShadowError("DataHub native Metric AI Context differs")
    try:
        assert_contains(actual, expected, "metric.aiContext")
    except ValueError as error:
        raise NativeMetricShadowError(
            "DataHub native Metric AI Context differs"
        ) from error
    optional = {"synonyms", "instructions", "examples", "customInstructions"}
    if any(actual.get(name) is not None for name in optional - set(expected)):
        raise NativeMetricShadowError("DataHub native Metric AI Context differs")


def _assert_native_governance_graph(
    metric: Mapping[str, Any],
    aspects: Mapping[str, Mapping[str, Any]],
    urn: str,
) -> None:
    """Metric의 lifecycle·owner·domain·Glossary 연결을 native graph와 대조한다."""

    status = metric.get("status")
    lifecycle = status.get("lifecycleStage") if isinstance(status, Mapping) else None
    owners_value = metric.get("ownership")
    owners = owners_value.get("owners") if isinstance(owners_value, Mapping) else None
    expected_owner = aspects["ownership"]["owners"][0]
    domain = metric.get("domain")
    glossary = metric.get("glossaryTerms")
    terms = glossary.get("terms") if isinstance(glossary, Mapping) else None
    if (
        not isinstance(status, Mapping)
        or status.get("removed") is not False
        or _nested_urn(lifecycle) != aspects["status"].get("lifecycleStage")
        or not isinstance(owners, list)
        or len(owners) != 1
        or not isinstance(owners[0], Mapping)
        or owners[0].get("type") != expected_owner["type"]
        or owners[0].get("associatedUrn") != urn
        or _nested_urn(owners[0].get("ownershipType"))
        != "urn:li:ownershipType:__system__technical_owner"
        or _nested_urn(owners[0].get("owner")) != expected_owner["owner"]
        or _nested_urn(domain.get("domain") if isinstance(domain, Mapping) else None)
        != aspects["domains"]["domains"][0]
        or not isinstance(terms, list)
        or {_nested_urn(item.get("term")) for item in terms if isinstance(item, Mapping)}
        != {item["urn"] for item in aspects["glossaryTerms"]["terms"]}
        or len(terms) != len(aspects["glossaryTerms"]["terms"])
    ):
        raise NativeMetricShadowError(
            "DataHub native Metric GraphQL governance differs"
        )


def _assert_native_lineage_graph(
    metric: Mapping[str, Any],
    aspects: Mapping[str, Mapping[str, Any]],
) -> None:
    """Metric→Dataset/SchemaField/Metric edge 집합을 중복 없이 정확히 대조한다."""

    upstreams = metric.get("metricUpstreams")
    relationships = metric.get("metricRelationships")
    expected_upstreams = aspects["metricUpstreams"]
    expected_relationships = aspects.get(
        "metricRelationships",
        {"derivedFrom": [], "relatedMetrics": []},
    )
    _assert_edge_set(
        upstreams.get("datasetUpstreams") if isinstance(upstreams, Mapping) else None,
        expected_upstreams["datasetUpstreams"],
        "DATASET",
    )
    _assert_edge_set(
        upstreams.get("fieldUpstreams") if isinstance(upstreams, Mapping) else None,
        expected_upstreams["fieldUpstreams"],
        "SCHEMA_FIELD",
    )
    _assert_edge_set(
        relationships.get("derivedFrom")
        if isinstance(relationships, Mapping)
        else None,
        expected_relationships["derivedFrom"],
        "METRIC",
    )
    _assert_edge_set(
        relationships.get("relatedMetrics")
        if isinstance(relationships, Mapping)
        else None,
        expected_relationships["relatedMetrics"],
        "METRIC",
    )


def _assert_edge_set(
    actual: object,
    expected: list[Mapping[str, Any]],
    expected_type: str,
) -> None:
    """GraphQL EntityEdge의 목적지 URN과 entity type을 순서와 무관하게 검증한다."""

    rows = [] if actual is None else actual
    if not isinstance(rows, list):
        raise NativeMetricShadowError("DataHub native Metric graph edge is malformed")
    observed: list[str] = []
    for row in rows:
        destination = row.get("destination") if isinstance(row, Mapping) else None
        urn = _nested_urn(destination)
        if (
            not isinstance(destination, Mapping)
            or destination.get("type") != expected_type
            or urn is None
        ):
            raise NativeMetricShadowError(
                "DataHub native Metric graph edge identity differs"
            )
        observed.append(urn)
    expected_urns = [str(item["destinationUrn"]) for item in expected]
    if len(observed) != len(set(observed)) or set(observed) != set(expected_urns):
        raise NativeMetricShadowError(
            "DataHub native Metric graph edge membership differs"
        )


def _nested_urn(value: object) -> str | None:
    """GraphQL entity 참조 객체에서 유효한 URN 문자열만 반환한다."""

    urn = value.get("urn") if isinstance(value, Mapping) else None
    return urn if isinstance(urn, str) and urn.startswith("urn:li:") else None


def _grouped_aspects(
    bundle: Mapping[str, Any],
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """Metric entity별 aspect를 안정된 발행·재조회 순서로 묶는다."""

    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for entity_type, urn, name, value in iter_native_metric_aspects(bundle):
        grouped.setdefault((entity_type, urn), {})[name] = value
    return dict(sorted(grouped.items()))
