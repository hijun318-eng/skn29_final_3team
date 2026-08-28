"""기술형 Glossary retirement gate가 mutation 전 상태 변화를 차단하는지 검증한다."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DATAHUB))

from check_catalog_term_retirement import (  # noqa: E402
    build_retirement_check,
    validate_retirement_check,
)
from export_catalog_baseline import (  # noqa: E402
    BASELINE_SCHEMA_VERSION,
    BASELINE_SCOPE,
)
from src.data.governance_contract import canonical_sha256  # noqa: E402


TECHNICAL_URN = (
    "urn:li:glossaryTerm:answervice_release_x_dataset_"
    "0123456789abcdef01234567"
)


def _baseline(*, datasets: list[dict[str, object]] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "scope": BASELINE_SCOPE,
        "inventory": {
            "scanned_datasets": 10,
            "scanned_glossary_terms": 20,
            "affected_datasets": len(datasets or []),
            "technical_terms": 1,
        },
        "terms": [
            {
                "urn": TECHNICAL_URN,
                "kind": "dataset",
                "removed": False,
                "name": "technical fixture",
            }
        ],
        "datasets": datasets or [],
    }
    return {**payload, "content_sha256": canonical_sha256(payload)}


def _reseal(document: dict[str, object]) -> None:
    payload = copy.deepcopy(document)
    payload.pop("content_sha256")
    document["content_sha256"] = canonical_sha256(payload)


def test_check_is_deterministic_and_ignores_unrelated_inventory_growth() -> None:
    baseline = _baseline()
    current = copy.deepcopy(baseline)
    current["inventory"]["scanned_datasets"] = 11
    current["inventory"]["scanned_glossary_terms"] = 21
    _reseal(current)

    first = build_retirement_check(baseline, current)
    second = build_retirement_check(baseline, current)

    assert first == second
    assert first["status"] == "CHECKED_WITHOUT_MUTATION"
    assert first["technical_terms"] == 1
    assert first["affected_datasets"] == 0
    validate_retirement_check(first)


def test_check_rejects_a_changed_target_even_when_identity_is_unchanged() -> None:
    baseline = _baseline()
    current = copy.deepcopy(baseline)
    current["terms"][0]["removed"] = True
    _reseal(current)

    with pytest.raises(ValueError, match="differs from the baseline"):
        build_retirement_check(baseline, current)


def test_check_rejects_targets_that_still_have_dataset_associations() -> None:
    dataset = {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:trino,serving.fixture,PROD)",
        "dataset_term_urns": [TECHNICAL_URN],
        "schema_fields": [],
        "editable_fields": [],
    }
    baseline = _baseline(datasets=[dataset])

    with pytest.raises(ValueError, match="still associated"):
        build_retirement_check(baseline, copy.deepcopy(baseline))


def test_check_rejects_tampering() -> None:
    checked = build_retirement_check(_baseline(), _baseline())
    checked["technical_terms"] = 2

    with pytest.raises(ValueError, match="checksum"):
        validate_retirement_check(checked)


def test_check_rejects_unknown_contract_fields_even_when_resealed() -> None:
    checked = build_retirement_check(_baseline(), _baseline())
    checked["unexpected_action"] = "IGNORE"
    payload = copy.deepcopy(checked)
    payload.pop("check_sha256")
    checked["check_sha256"] = canonical_sha256(payload)

    with pytest.raises(ValueError, match="fields"):
        validate_retirement_check(checked)
