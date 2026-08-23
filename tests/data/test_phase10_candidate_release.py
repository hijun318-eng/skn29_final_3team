from __future__ import annotations

from argparse import Namespace

import pytest

from infrastructure.acceptance.phase10_candidate_release import (
    EXPECTED_IMAGE_COMPONENTS,
    Phase10CandidateReleaseError,
    parse_images,
    validate_boundary,
)


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "target_project": "answervice-phase2b-datahub",
        "source_database_url": (
            "postgresql+psycopg://postgres@127.0.0.1:55440/"
            "phase4_runtime_catalog_acceptance"
        ),
        "target_database_url": (
            "postgresql+psycopg://phase10_migrator@127.0.0.1:55440/"
            "phase10_p0_same_release_acceptance"
        ),
    }
    values.update(overrides)
    return Namespace(**values)


def test_candidate_release_boundary_accepts_only_distinct_isolated_databases() -> None:
    source, target = validate_boundary(_args())

    assert source.database == "phase4_runtime_catalog_acceptance"
    assert target.database == "phase10_p0_same_release_acceptance"


@pytest.mark.parametrize(
    "override",
    [
        {"target_project": "answervice"},
        {
            "source_database_url": (
                "postgresql+psycopg://postgres@127.0.0.1:25432/answervice"
            )
        },
        {
            "target_database_url": (
                "postgresql+psycopg://phase10_migrator@127.0.0.1:55440/"
                "phase4_runtime_catalog_acceptance"
            )
        },
    ],
)
def test_candidate_release_boundary_rejects_current_or_wrong_targets(
    override: dict[str, str],
) -> None:
    with pytest.raises(Phase10CandidateReleaseError):
        validate_boundary(_args(**override))


def test_image_receipts_require_the_exact_same_release_inventory() -> None:
    values = [f"{name}=sha256:{index:064x}" for index, name in enumerate(
        sorted(EXPECTED_IMAGE_COMPONENTS), start=1
    )]

    receipts = parse_images(values)

    assert {receipt.component for receipt in receipts} == EXPECTED_IMAGE_COMPONENTS
    with pytest.raises(Phase10CandidateReleaseError, match="inventory"):
        parse_images(values[:-1])
    with pytest.raises(Phase10CandidateReleaseError, match="duplicated"):
        parse_images([*values, values[0]])
