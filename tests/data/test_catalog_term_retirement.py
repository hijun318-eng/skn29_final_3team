"""기술형 Glossary status 전환의 재개·복원·fail-closed 계약을 검증한다."""

from __future__ import annotations

import asyncio
import copy
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DATAHUB))

from check_catalog_term_retirement import build_retirement_check  # noqa: E402
from export_catalog_baseline import (  # noqa: E402
    BASELINE_SCHEMA_VERSION,
    BASELINE_SCOPE,
)
from retire_catalog_terms import (  # noqa: E402
    apply_catalog_term_status,
    validate_status_receipt,
    verify_catalog_term_status,
)
from src.data.governance_contract import canonical_sha256  # noqa: E402


DATASET_TERM_URN = (
    "urn:li:glossaryTerm:answervice_release_x_dataset_"
    "0123456789abcdef01234567"
)
FIELD_TERM_URN = (
    "urn:li:glossaryTerm:answervice_release_x_field_"
    "abcdef0123456789abcdef01"
)


def _baseline() -> dict[str, Any]:
    terms = sorted(
        [
            {
                "urn": DATASET_TERM_URN,
                "kind": "dataset",
                "removed": False,
                "name": "dataset fixture",
            },
            {
                "urn": FIELD_TERM_URN,
                "kind": "field",
                "removed": False,
                "name": "field fixture",
            },
        ],
        key=lambda term: term["urn"],
    )
    payload = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "scope": BASELINE_SCOPE,
        "inventory": {
            "scanned_datasets": 10,
            "scanned_glossary_terms": 20,
            "affected_datasets": 0,
            "technical_terms": len(terms),
        },
        "terms": terms,
        "datasets": [],
    }
    return {**payload, "content_sha256": canonical_sha256(payload)}


class StatusAdmin:
    def __init__(
        self, states: dict[str, bool], *, fail_once_on: str | None = None
    ) -> None:
        self.states = states
        self.fail_once_on = fail_once_on
        self.writes: list[tuple[str, bool]] = []

    async def upsert_entity(
        self,
        entity_type: str,
        urn: str,
        aspects: Mapping[str, Mapping[str, Any]],
        _audit: Mapping[str, Any],
    ) -> None:
        assert entity_type == "glossaryTerm"
        removed = aspects["status"]["removed"]
        assert isinstance(removed, bool)
        if urn == self.fail_once_on:
            self.fail_once_on = None
            raise RuntimeError("injected failure")
        self.states[urn] = removed
        self.writes.append((urn, removed))


def _scope_reader(
    baseline: Mapping[str, Any],
    states: dict[str, bool],
    *,
    changed_name: bool = False,
    associated: bool = False,
):
    async def read(_reader: Any, urns: Sequence[str]) -> dict[str, Any]:
        assert tuple(urns) == tuple(term["urn"] for term in baseline["terms"])
        terms = copy.deepcopy(baseline["terms"])
        for term in terms:
            term["removed"] = states[term["urn"]]
        if changed_name:
            terms[0]["name"] = "changed outside retirement"
        datasets: list[dict[str, Any]] = []
        if associated:
            datasets.append(
                {
                    "urn": (
                        "urn:li:dataset:(urn:li:dataPlatform:trino,"
                        "serving.fixture,PROD)"
                    ),
                    "dataset_term_urns": [terms[0]["urn"]],
                    "schema_fields": [],
                    "editable_fields": [],
                }
            )
        return {"scope": BASELINE_SCOPE, "terms": terms, "datasets": datasets}

    return read


def _checked(baseline: Mapping[str, Any]) -> dict[str, Any]:
    return build_retirement_check(baseline, baseline)


def _visibility_reader(states: Mapping[str, bool]):
    async def read(_reader: Any) -> tuple[str, ...]:
        return tuple(sorted(urn for urn, removed in states.items() if not removed))

    return read


def test_soft_delete_resumes_only_the_remaining_targets_after_failure() -> None:
    baseline = _baseline()
    checked = _checked(baseline)
    urns = [term["urn"] for term in baseline["terms"]]
    states = {urn: False for urn in urns}
    admin = StatusAdmin(states, fail_once_on=urns[1])
    reader = _scope_reader(baseline, states)

    with pytest.raises(RuntimeError, match="injected failure"):
        asyncio.run(
            apply_catalog_term_status(
                baseline,
                checked,
                expected_check_sha256=checked["check_sha256"],
                reader=object(),
                admin=admin,
                actor_urn="urn:li:corpuser:service_retirement",
                removed=True,
                scope_reader=reader,
                visibility_reader=_visibility_reader(states),
            )
        )
    assert states == {urns[0]: True, urns[1]: False}

    receipt = asyncio.run(
        apply_catalog_term_status(
            baseline,
            checked,
            expected_check_sha256=checked["check_sha256"],
            reader=object(),
            admin=admin,
            actor_urn="urn:li:corpuser:service_retirement",
            removed=True,
            scope_reader=reader,
            visibility_reader=_visibility_reader(states),
        )
    )

    assert states == {urn: True for urn in urns}
    assert receipt["status"] == "SOFT_DELETED_AND_VERIFIED"
    assert receipt["changed_terms"] == 1
    assert admin.writes == [(urns[0], True), (urns[1], True)]
    validate_status_receipt(receipt)


def test_restore_reactivates_the_exact_same_urns() -> None:
    baseline = _baseline()
    checked = _checked(baseline)
    states = {term["urn"]: True for term in baseline["terms"]}
    admin = StatusAdmin(states)

    receipt = asyncio.run(
        apply_catalog_term_status(
            baseline,
            checked,
            expected_check_sha256=checked["check_sha256"],
            reader=object(),
            admin=admin,
            actor_urn="urn:li:corpuser:service_retirement",
            removed=False,
            scope_reader=_scope_reader(baseline, states),
            visibility_reader=_visibility_reader(states),
        )
    )

    assert all(value is False for value in states.values())
    assert receipt["status"] == "RESTORED_AND_VERIFIED"
    assert receipt["active_terms_after"] == 2
    validate_status_receipt(receipt)


@pytest.mark.parametrize("failure", ["metadata", "association"])
def test_status_change_rejects_scope_drift_before_any_write(failure: str) -> None:
    baseline = _baseline()
    checked = _checked(baseline)
    states = {term["urn"]: False for term in baseline["terms"]}
    admin = StatusAdmin(states)

    with pytest.raises(ValueError, match="metadata|associations"):
        asyncio.run(
            apply_catalog_term_status(
                baseline,
                checked,
                expected_check_sha256=checked["check_sha256"],
                reader=object(),
                admin=admin,
                actor_urn="urn:li:corpuser:service_retirement",
                removed=True,
                scope_reader=_scope_reader(
                    baseline,
                    states,
                    changed_name=failure == "metadata",
                    associated=failure == "association",
                ),
                visibility_reader=_visibility_reader(states),
            )
        )

    assert admin.writes == []
    assert all(value is False for value in states.values())


def test_read_only_verification_requires_every_target_to_match() -> None:
    baseline = _baseline()
    checked = _checked(baseline)
    states = {term["urn"]: True for term in baseline["terms"]}
    reader = _scope_reader(baseline, states)

    receipt = asyncio.run(
        verify_catalog_term_status(
            baseline,
            checked,
            expected_check_sha256=checked["check_sha256"],
            reader=object(),
            removed=True,
            scope_reader=reader,
            visibility_reader=_visibility_reader(states),
        )
    )
    assert receipt["status"] == "RETIRED_STATE_VERIFIED"
    assert receipt["actor_urn"] is None

    states[next(iter(states))] = False
    with pytest.raises(ValueError, match="differs from expectation"):
        asyncio.run(
            verify_catalog_term_status(
                baseline,
                checked,
                expected_check_sha256=checked["check_sha256"],
                reader=object(),
                removed=True,
                scope_reader=reader,
                visibility_reader=_visibility_reader(states),
            )
        )


def test_status_change_rejects_search_visibility_drift_before_write() -> None:
    baseline = _baseline()
    checked = _checked(baseline)
    states = {term["urn"]: False for term in baseline["terms"]}
    admin = StatusAdmin(states)

    async def missing_visible_target(_reader: Any) -> tuple[str, ...]:
        return (next(iter(states)),)

    with pytest.raises(ValueError, match="visibility"):
        asyncio.run(
            apply_catalog_term_status(
                baseline,
                checked,
                expected_check_sha256=checked["check_sha256"],
                reader=object(),
                admin=admin,
                actor_urn="urn:li:corpuser:service_retirement",
                removed=True,
                scope_reader=_scope_reader(baseline, states),
                visibility_reader=missing_visible_target,
            )
        )

    assert admin.writes == []
