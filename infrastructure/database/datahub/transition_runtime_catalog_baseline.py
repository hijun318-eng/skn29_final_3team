"""RuntimeCatalog 범위의 DataHub baseline을 checksum-bound 방식으로 전환한다.

``--check``는 source/target baseline과 활성 projection scope의 exact diff만 봉인한다.
``--apply``는 같은 plan checksum을 재검증하고, live 값이 source/target 중 하나일 때만
남은 aspect를 upsert한 뒤 target scope 전체를 독립 read-back한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import DataHubCatalogClient  # noqa: E402
from export_datahub_metadata_baseline import (  # noqa: E402
    _MAX_ENTITY_COUNT,
    build_datahub_metadata_baseline,
    validate_datahub_metadata_baseline,
)
from export_runtime_catalog_baseline import (  # noqa: E402
    validate_runtime_catalog_baseline,
)
from http_client import DataHubMetadataAdminClient  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402


PLAN_SCHEMA_VERSION = "answervice.runtime-catalog-datahub-transition-plan.v1"
CHECK_SCHEMA_VERSION = "answervice.runtime-catalog-datahub-transition-check.v1"
RECEIPT_SCHEMA_VERSION = "answervice.runtime-catalog-datahub-transition-receipt.v1"
_ALLOWED_ASPECTS = {
    "dataset": frozenset(
        {"datasetProperties", "editableSchemaMetadata", "upstreamLineage"}
    ),
    "glossaryTerm": frozenset({"glossaryTermInfo"}),
}


def runtime_catalog_scope_urns(runtime_baseline: Mapping[str, Any]) -> tuple[str, ...]:
    """검증된 baseline의 active projection이 실제로 결속한 entity URN을 반환한다."""

    validate_runtime_catalog_baseline(runtime_baseline)
    pointer = _mapping(runtime_baseline.get("active_pointer"), "active pointer")
    projection_id = _text(pointer.get("projection_id"), "active projection ID")
    projections = _list(
        runtime_baseline.get("runtime_projections"), "runtime projections"
    )
    matches = [
        _mapping(item, "runtime projection")
        for item in projections
        if _mapping(item, "runtime projection").get("projection_id") == projection_id
    ]
    if len(matches) != 1:
        raise ValueError("active runtime projection is unavailable or ambiguous")
    snapshot = _mapping(matches[0].get("snapshot"), "runtime projection snapshot")
    urns: set[str] = set()
    for collection_name in ("datasets", "terms", "dimension_member_terms"):
        for raw in _list(snapshot.get(collection_name), collection_name):
            urns.add(_text(_mapping(raw, collection_name).get("urn"), "scope URN"))
    governance = _mapping(
        snapshot.get("governance_entities"), "governance entities"
    )
    for collection_name in ("domains", "owners", "approved_lifecycles"):
        for raw in _list(governance.get(collection_name), collection_name):
            if isinstance(raw, str):
                urns.add(_text(raw, "governance URN"))
            else:
                urns.add(
                    _text(
                        _mapping(raw, collection_name).get("urn"),
                        "governance URN",
                    )
                )
    if not urns:
        raise ValueError("runtime catalog DataHub scope is empty")
    return tuple(sorted(urns))


def build_runtime_catalog_transition_plan(
    source_baseline: Mapping[str, Any],
    target_baseline: Mapping[str, Any],
    scope_urns: Sequence[str],
) -> dict[str, Any]:
    """두 검증 baseline 사이의 허용 aspect 차이만 결정론적 plan으로 봉인한다."""

    validate_datahub_metadata_baseline(source_baseline)
    validate_datahub_metadata_baseline(target_baseline)
    scope = _canonical_scope(scope_urns)
    source_entities = _scoped_entities(source_baseline, scope)
    target_entities = _scoped_entities(target_baseline, scope)
    source_by_urn = {str(item["urn"]): item for item in source_entities}
    target_by_urn = {str(item["urn"]): item for item in target_entities}
    mutations: list[dict[str, Any]] = []
    for urn in scope:
        source = source_by_urn[urn]
        target = target_by_urn[urn]
        entity_type = _text(source.get("entity_type"), "source entity type")
        if target.get("entity_type") != entity_type:
            raise ValueError("runtime catalog entity type differs between baselines")
        source_aspects = _mapping(source.get("aspects"), "source aspects")
        target_aspects = _mapping(target.get("aspects"), "target aspects")
        if set(source_aspects) != set(target_aspects):
            raise ValueError("runtime catalog aspect membership differs between baselines")
        for aspect in sorted(source_aspects):
            before = _mapping(source_aspects[aspect], f"source {aspect}")
            after = _mapping(target_aspects[aspect], f"target {aspect}")
            before_sha256 = canonical_sha256(before)
            after_sha256 = canonical_sha256(after)
            if before_sha256 == after_sha256:
                continue
            if aspect not in _ALLOWED_ASPECTS.get(entity_type, frozenset()):
                raise ValueError(
                    "runtime catalog transition contains an unsupported aspect"
                )
            mutations.append(
                {
                    "entity_type": entity_type,
                    "urn": urn,
                    "aspect": aspect,
                    "before_sha256": before_sha256,
                    "after_sha256": after_sha256,
                    "value": deepcopy(dict(after)),
                }
            )
    content = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "source_baseline_sha256": source_baseline["content_sha256"],
        "target_baseline_sha256": target_baseline["content_sha256"],
        "scope_urns": list(scope),
        "scope_sha256": canonical_sha256(list(scope)),
        "source_scope_sha256": canonical_sha256(source_entities),
        "target_scope_sha256": canonical_sha256(target_entities),
        "mutations": mutations,
        "mutation_count": len(mutations),
    }
    return {**content, "plan_sha256": canonical_sha256(content)}


def pending_runtime_catalog_mutations(
    plan: Mapping[str, Any],
    source_baseline: Mapping[str, Any],
    target_baseline: Mapping[str, Any],
    live_baseline: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """부분 재시도에서 source 값인 aspect만 반환하고 제3의 live 값은 차단한다."""

    _validate_plan(plan)
    validate_datahub_metadata_baseline(source_baseline)
    validate_datahub_metadata_baseline(target_baseline)
    validate_datahub_metadata_baseline(live_baseline)
    if (
        source_baseline.get("content_sha256") != plan.get("source_baseline_sha256")
        or target_baseline.get("content_sha256")
        != plan.get("target_baseline_sha256")
    ):
        raise ValueError("runtime catalog transition baseline identity differs")
    scope = tuple(map(str, _list(plan.get("scope_urns"), "transition scope")))
    source = {item["urn"]: item for item in _scoped_entities(source_baseline, scope)}
    target = {item["urn"]: item for item in _scoped_entities(target_baseline, scope)}
    live = {item["urn"]: item for item in _scoped_entities(live_baseline, scope)}
    mutation_by_key = {
        (item["urn"], item["aspect"]): item
        for item in _list(plan.get("mutations"), "transition mutations")
    }
    pending: list[dict[str, Any]] = []
    for urn in scope:
        source_aspects = _mapping(source[urn].get("aspects"), "source aspects")
        target_aspects = _mapping(target[urn].get("aspects"), "target aspects")
        live_aspects = _mapping(live[urn].get("aspects"), "live aspects")
        if set(live_aspects) != set(source_aspects) or set(target_aspects) != set(
            source_aspects
        ):
            raise ValueError("live runtime catalog aspect membership drifted")
        for aspect in sorted(source_aspects):
            source_sha256 = canonical_sha256(source_aspects[aspect])
            target_sha256 = canonical_sha256(target_aspects[aspect])
            live_sha256 = canonical_sha256(live_aspects[aspect])
            if source_sha256 == target_sha256:
                if live_sha256 != source_sha256:
                    raise ValueError("unchanged runtime catalog aspect drifted")
                continue
            mutation = mutation_by_key.get((urn, aspect))
            if mutation is None:
                raise ValueError("runtime catalog transition mutation is incomplete")
            if (
                mutation.get("before_sha256") != source_sha256
                or mutation.get("after_sha256") != target_sha256
            ):
                raise ValueError("runtime catalog transition mutation provenance differs")
            if live_sha256 == source_sha256:
                pending.append(deepcopy(dict(mutation)))
            elif live_sha256 != target_sha256:
                raise ValueError("runtime catalog transition found a third live value")
    return tuple(pending)


async def apply_runtime_catalog_transition(
    client: Any,
    plan: Mapping[str, Any],
    pending: Sequence[Mapping[str, Any]],
    *,
    actor_urn: str,
    clock_ms: int,
) -> int:
    """검증된 plan에 속한 pending aspect만 동일 actor audit로 upsert한다."""

    _validate_plan(plan)
    if (
        not actor_urn.startswith("urn:li:corpuser:service_")
        or not isinstance(clock_ms, int)
        or isinstance(clock_ms, bool)
        or clock_ms <= 0
    ):
        raise ValueError("runtime catalog transition deployment identity is invalid")
    approved = {
        (item["urn"], item["aspect"], item["after_sha256"])
        for item in _list(plan.get("mutations"), "transition mutations")
    }
    normalized = [dict(_mapping(item, "pending mutation")) for item in pending]
    identities = [
        (item.get("urn"), item.get("aspect"), item.get("after_sha256"))
        for item in normalized
    ]
    if len(set(identities)) != len(identities) or any(
        identity not in approved for identity in identities
    ):
        raise ValueError("pending runtime catalog mutation is not in the approved plan")
    for mutation in normalized:
        value = _mapping(mutation.get("value"), "transition aspect value")
        if canonical_sha256(value) != mutation.get("after_sha256"):
            raise ValueError("pending runtime catalog mutation value differs")
        await client.upsert_entity(
            str(mutation["entity_type"]),
            str(mutation["urn"]),
            {str(mutation["aspect"]): dict(value)},
            {"actor": actor_urn, "time": clock_ms},
        )
    return len(normalized)


def assert_runtime_catalog_target(
    plan: Mapping[str, Any], live_baseline: Mapping[str, Any]
) -> None:
    """독립 full read의 projection scope가 target baseline과 정확히 같은지 확인한다."""

    _validate_plan(plan)
    validate_datahub_metadata_baseline(live_baseline)
    scope = tuple(map(str, _list(plan.get("scope_urns"), "transition scope")))
    if canonical_sha256(_scoped_entities(live_baseline, scope)) != plan.get(
        "target_scope_sha256"
    ):
        raise ValueError("runtime catalog DataHub target scope did not converge")


def _validate_plan(plan: Mapping[str, Any]) -> None:
    """전환 plan의 checksum, scope, mutation membership을 다시 검증한다."""

    expected_keys = {
        "schema_version",
        "source_baseline_sha256",
        "target_baseline_sha256",
        "scope_urns",
        "scope_sha256",
        "source_scope_sha256",
        "target_scope_sha256",
        "mutations",
        "mutation_count",
        "plan_sha256",
    }
    if not isinstance(plan, Mapping) or set(plan) != expected_keys:
        raise ValueError("runtime catalog transition plan fields differ")
    content = dict(plan)
    supplied = content.pop("plan_sha256")
    if (
        plan.get("schema_version") != PLAN_SCHEMA_VERSION
        or supplied != canonical_sha256(content)
    ):
        raise ValueError("runtime catalog transition plan checksum differs")
    scope = _canonical_scope(_list(plan.get("scope_urns"), "transition scope"))
    if list(scope) != plan.get("scope_urns") or canonical_sha256(
        list(scope)
    ) != plan.get("scope_sha256"):
        raise ValueError("runtime catalog transition scope differs")
    mutations = _list(plan.get("mutations"), "transition mutations")
    if len(mutations) != plan.get("mutation_count"):
        raise ValueError("runtime catalog transition mutation count differs")
    keys: list[tuple[str, str]] = []
    for raw in mutations:
        mutation = _mapping(raw, "transition mutation")
        entity_type = _text(mutation.get("entity_type"), "mutation entity type")
        urn = _text(mutation.get("urn"), "mutation URN")
        aspect = _text(mutation.get("aspect"), "mutation aspect")
        if urn not in scope or aspect not in _ALLOWED_ASPECTS.get(
            entity_type, frozenset()
        ):
            raise ValueError("runtime catalog transition mutation is out of scope")
        value = _mapping(mutation.get("value"), "mutation value")
        if canonical_sha256(value) != mutation.get("after_sha256"):
            raise ValueError("runtime catalog transition mutation checksum differs")
        keys.append((urn, aspect))
    if keys != sorted(set(keys)):
        raise ValueError("runtime catalog transition mutations are not canonical")


def _scoped_entities(
    baseline: Mapping[str, Any], scope: Sequence[str]
) -> list[dict[str, Any]]:
    """Baseline에서 exact projection scope를 canonical 순서로 추출한다."""

    entities = {
        _text(_mapping(item, "baseline entity").get("urn"), "entity URN"): item
        for item in _list(baseline.get("entities"), "baseline entities")
    }
    missing = sorted(set(scope) - set(entities))
    if missing:
        raise ValueError("runtime catalog scope entity is missing from a baseline")
    return [deepcopy(dict(_mapping(entities[urn], "scoped entity"))) for urn in scope]


def _canonical_scope(scope_urns: Sequence[object]) -> tuple[str, ...]:
    """중복 없는 정렬 URN scope를 검증한다."""

    scope = tuple(sorted(_text(item, "scope URN") for item in scope_urns))
    if not scope or len(set(scope)) != len(scope):
        raise ValueError("runtime catalog DataHub scope is empty or duplicated")
    return scope


async def _read_live_baseline(
    settings: DataHubConnectionSettings, timeout: float
) -> dict[str, Any]:
    """조회 전용 identity로 현재 DataHub baseline을 독립 full-read한다."""

    async with DataHubCatalogClient(
        settings.base_url,
        settings.token,
        ca_file=settings.ca_file,
        expected_actor_urn=settings.actor_urn,
        timeout_seconds=timeout,
        page_size=100,
        max_entities=_MAX_ENTITY_COUNT,
    ) as catalog, DataHubMetadataAdminClient(
        settings.base_url,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout_seconds=timeout,
    ) as reader:
        if not await catalog.health():
            raise RuntimeError("DataHub read service identity is unavailable")
        return await build_datahub_metadata_baseline(
            catalog,
            reader,
            actor_urn=settings.actor_urn,
            read_at=datetime.now(timezone.utc),
        )


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """전환 mode와 immutable baseline 입력을 파싱한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--source-baseline", type=Path, required=True)
    parser.add_argument("--target-baseline", type=Path, required=True)
    parser.add_argument("--runtime-baseline", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def _load_document(path: Path, context: str) -> dict[str, Any]:
    """기존 절대경로 JSON 문서 하나만 읽는다."""

    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"{context} must be an existing absolute file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{context} must contain one JSON object")
    return value


async def _async_main(argv: Sequence[str] | None = None) -> int:
    """Check/apply를 수행하고 비밀 없는 receipt만 표준 출력으로 반환한다."""

    arguments = _arguments(argv)
    if arguments.timeout <= 0:
        raise ValueError("runtime catalog transition timeout must be positive")
    if arguments.check and arguments.expected_plan_sha256 is not None:
        raise ValueError("check mode does not accept an expected plan checksum")
    if arguments.apply and not arguments.expected_plan_sha256:
        raise ValueError("apply mode requires the checked plan checksum")
    source = _load_document(arguments.source_baseline, "source baseline")
    target = _load_document(arguments.target_baseline, "target baseline")
    runtime = _load_document(arguments.runtime_baseline, "runtime baseline")
    scope = runtime_catalog_scope_urns(runtime)
    plan = build_runtime_catalog_transition_plan(source, target, scope)
    if (
        arguments.expected_plan_sha256 is not None
        and arguments.expected_plan_sha256 != plan["plan_sha256"]
    ):
        raise ValueError("runtime catalog transition check is stale")

    read_settings = DataHubConnectionSettings.from_env()
    live = await _read_live_baseline(read_settings, arguments.timeout)
    pending = pending_runtime_catalog_mutations(plan, source, target, live)
    if arguments.check:
        if len(pending) != plan["mutation_count"]:
            raise ValueError("runtime catalog transition source is already partial")
        result = {
            "schema_version": CHECK_SCHEMA_VERSION,
            "status": "READY",
            "source_baseline_sha256": plan["source_baseline_sha256"],
            "target_baseline_sha256": plan["target_baseline_sha256"],
            "scope_sha256": plan["scope_sha256"],
            "source_scope_sha256": plan["source_scope_sha256"],
            "target_scope_sha256": plan["target_scope_sha256"],
            "plan_sha256": plan["plan_sha256"],
            "planned_mutation_count": plan["mutation_count"],
            "mutation_count": 0,
        }
        print(canonical_json(result))
        return 0

    publish_settings = DataHubConnectionSettings.from_publish_env()
    if (
        publish_settings.base_url != read_settings.base_url
        or publish_settings.ca_file != read_settings.ca_file
        or publish_settings.actor_urn == read_settings.actor_urn
        or publish_settings.token == read_settings.token
    ):
        raise ValueError("DataHub read and publish identity boundaries differ")
    applied_at_ms = time_ns() // 1_000_000
    async with DataHubCatalogClient(
        publish_settings.base_url,
        publish_settings.token,
        ca_file=publish_settings.ca_file,
        expected_actor_urn=publish_settings.actor_urn,
        timeout_seconds=arguments.timeout,
        page_size=100,
        max_entities=_MAX_ENTITY_COUNT,
    ) as publication_identity, DataHubMetadataAdminClient(
        publish_settings.base_url,
        token=publish_settings.token,
        ca_file=publish_settings.ca_file,
        timeout_seconds=arguments.timeout,
    ) as publisher:
        if not await publication_identity.health():
            raise RuntimeError("DataHub publish service identity is unavailable")
        mutation_count = await apply_runtime_catalog_transition(
            publisher,
            plan,
            pending,
            actor_urn=publish_settings.actor_urn,
            clock_ms=applied_at_ms,
        )
    readback = await _read_live_baseline(read_settings, arguments.timeout)
    assert_runtime_catalog_target(plan, readback)
    content = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "APPLIED_AND_VERIFIED",
        "source_baseline_sha256": plan["source_baseline_sha256"],
        "target_baseline_sha256": plan["target_baseline_sha256"],
        "scope_sha256": plan["scope_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "planned_mutation_count": plan["mutation_count"],
        "mutation_count": mutation_count,
        "readback_scope_sha256": plan["target_scope_sha256"],
    }
    deployment = {
        "read_actor_urn": read_settings.actor_urn,
        "publish_actor_urn": publish_settings.actor_urn,
        "applied_at_epoch_ms": applied_at_ms,
        "mutation_count": mutation_count,
    }
    result = {
        **content,
        "content_sha256": canonical_sha256(content),
        "deployment_receipt": deployment,
        "deployment_receipt_sha256": canonical_sha256(deployment),
    }
    print(canonical_json(result))
    return 0


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


def main(argv: Sequence[str] | None = None) -> int:
    """운영 오류는 민감한 상세 대신 type만 stderr로 반환한다."""

    try:
        return asyncio.run(_async_main(argv))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "ERROR", "error_type": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
