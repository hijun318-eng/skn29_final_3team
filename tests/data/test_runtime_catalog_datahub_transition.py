"""RuntimeCatalog 범위 DataHub baseline 전환의 fail-closed 계약을 검증한다."""

from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
TEST_DATA = Path(__file__).resolve().parent
for entry in (str(ROOT), str(DATAHUB), str(TEST_DATA)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import transition_runtime_catalog_baseline as transition  # noqa: E402
from test_canonical_metadata_sync import (  # noqa: E402
    DATASET,
    TERM,
    UNMANAGED,
    _apply_plan_to_baseline,
    _baseline,
)


def _source_and_target() -> tuple[dict[str, object], dict[str, object]]:
    source = _baseline(upstream_urns=(UNMANAGED,))
    entities = {
        item["urn"]: item
        for item in source["entities"]
        if isinstance(item, dict)
    }
    dataset_aspects = entities[DATASET]["aspects"]
    term_aspects = entities[TERM]["aspects"]

    properties = copy.deepcopy(dataset_aspects["datasetProperties"])
    properties["name"] = "승인된 일별 호텔 매출"
    editable = copy.deepcopy(dataset_aspects["editableSchemaMetadata"])
    editable["editableSchemaFieldInfo"][0]["description"] = "승인된 영업일자"
    term_info = copy.deepcopy(term_aspects["glossaryTermInfo"])
    term_info["definition"] = "승인된 객실 매출 합계"
    target = _apply_plan_to_baseline(
        source,
        {
            "mutations": [
                {"urn": DATASET, "aspect": "datasetProperties", "value": properties},
                {
                    "urn": DATASET,
                    "aspect": "editableSchemaMetadata",
                    "value": editable,
                },
                {
                    "urn": DATASET,
                    "aspect": "upstreamLineage",
                    "value": {"upstreams": []},
                },
                {"urn": TERM, "aspect": "glossaryTermInfo", "value": term_info},
            ]
        },
    )
    return source, target


def test_plan_is_deterministic_bidirectional_and_exactly_scoped() -> None:
    source, target = _source_and_target()
    scope = (DATASET, TERM)

    first = transition.build_runtime_catalog_transition_plan(source, target, scope)
    second = transition.build_runtime_catalog_transition_plan(
        copy.deepcopy(source), copy.deepcopy(target), tuple(reversed(scope))
    )
    reverse = transition.build_runtime_catalog_transition_plan(target, source, scope)

    assert first == second
    assert first["mutation_count"] == reverse["mutation_count"] == 4
    assert {(item["urn"], item["aspect"]) for item in first["mutations"]} == {
        (DATASET, "datasetProperties"),
        (DATASET, "editableSchemaMetadata"),
        (DATASET, "upstreamLineage"),
        (TERM, "glossaryTermInfo"),
    }
    assert UNMANAGED not in first["scope_urns"]


def test_partial_retry_only_returns_source_values_and_blocks_third_value() -> None:
    source, target = _source_and_target()
    plan = transition.build_runtime_catalog_transition_plan(
        source, target, (DATASET, TERM)
    )
    partial = _apply_plan_to_baseline(
        source, {"mutations": copy.deepcopy(plan["mutations"][:2])}
    )

    pending = transition.pending_runtime_catalog_mutations(
        plan, source, target, partial
    )
    assert pending == tuple(plan["mutations"][2:])
    assert (
        transition.pending_runtime_catalog_mutations(plan, source, target, target)
        == ()
    )

    third = copy.deepcopy(plan["mutations"][0])
    third["value"]["name"] = "승인되지 않은 제3의 값"
    drifted = _apply_plan_to_baseline(source, {"mutations": [third]})
    with pytest.raises(ValueError, match="third live value"):
        transition.pending_runtime_catalog_mutations(
            plan, source, target, drifted
        )


def test_unsupported_aspect_and_tampered_plan_are_fail_closed() -> None:
    source, _target = _source_and_target()
    entities = {
        item["urn"]: item
        for item in source["entities"]
        if isinstance(item, dict)
    }
    ownership = copy.deepcopy(entities[DATASET]["aspects"]["ownership"])
    ownership["owners"][0]["type"] = "BUSINESS_OWNER"
    unsupported_target = _apply_plan_to_baseline(
        source,
        {"mutations": [{"urn": DATASET, "aspect": "ownership", "value": ownership}]},
    )
    with pytest.raises(ValueError, match="unsupported aspect"):
        transition.build_runtime_catalog_transition_plan(
            source, unsupported_target, (DATASET, TERM)
        )

    _, target = _source_and_target()
    plan = transition.build_runtime_catalog_transition_plan(
        source, target, (DATASET, TERM)
    )
    tampered = copy.deepcopy(plan)
    tampered["plan_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="plan checksum differs"):
        transition.pending_runtime_catalog_mutations(
            tampered, source, target, source
        )


def test_apply_writes_each_approved_aspect_once_and_requires_full_readback() -> None:
    source, target = _source_and_target()
    plan = transition.build_runtime_catalog_transition_plan(
        source, target, (DATASET, TERM)
    )
    pending = transition.pending_runtime_catalog_mutations(
        plan, source, target, source
    )

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        async def upsert_entity(self, *args: object) -> None:
            self.calls.append(args)

    client = RecordingClient()
    count = asyncio.run(
        transition.apply_runtime_catalog_transition(
            client,
            plan,
            pending,
            actor_urn="urn:li:corpuser:service_catalog_publisher",
            clock_ms=1,
        )
    )

    assert count == plan["mutation_count"] == len(client.calls)
    transition.assert_runtime_catalog_target(plan, target)
    with pytest.raises(ValueError, match="did not converge"):
        transition.assert_runtime_catalog_target(plan, source)

    unapproved = copy.deepcopy(pending[0])
    unapproved["after_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="not in the approved plan"):
        asyncio.run(
            transition.apply_runtime_catalog_transition(
                client,
                plan,
                (unapproved,),
                actor_urn="urn:li:corpuser:service_catalog_publisher",
                clock_ms=1,
            )
        )
