"""Phase 8 acceptance entrypoint의 격리·probe·비회귀 경계를 검증한다."""

from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "infrastructure" / "acceptance"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
BACKEND = ROOT / "app" / "backend"
for entry in (
    str(ROOT),
    str(ACCEPTANCE),
    str(DATAHUB),
    str(BACKEND),
    str(ROOT / "tests" / "data"),
):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from phase2b_datahub_candidate import AcceptanceError  # noqa: E402
from phase8_native_semantic_shadow import (  # noqa: E402
    Phase8Error,
    _assert_runtime_nonregression,
    _preflight_identities,
    _relationship_probe,
    _validate_boundary,
    parse_args,
)
from test_datahub_metadata_publication import arbitrary_ratio_bundle  # noqa: E402


def _args(extra: list[str] | None = None):
    return parse_args(
        [
            "--target-project",
            "answervice-phase2b-datahub",
            "--target-server",
            "https://127.0.0.1:38081",
            "--trino-server",
            "https://127.0.0.1:18443",
            "--trino-ca-file",
            str(ROOT / "AGENTS.md"),
            "--database-url",
            "postgresql+psycopg://postgres@127.0.0.1:55440/phase4_runtime_catalog_acceptance",
            *(extra or []),
        ]
    )


def test_boundary_is_hard_bound_to_isolated_resources() -> None:
    _validate_boundary(_args())

    with pytest.raises(Phase8Error, match="target DataHub"):
        _validate_boundary(
            _args(["--target-server", "https://127.0.0.1:28081"])
        )
    with pytest.raises(Phase8Error, match="database"):
        _validate_boundary(
            _args(
                [
                    "--database-url",
                    "postgresql+psycopg://postgres@127.0.0.1:5432/answervice",
                ]
            )
        )


class AbsentClient:
    async def get_entity(self, _urn: str, _aspects: tuple[str, ...]) -> dict:
        raise AcceptanceError("isolated DataHub request failed with HTTP 404")


def test_preflight_treats_only_explicit_404_as_absent() -> None:
    bundle = arbitrary_ratio_bundle()
    result = asyncio.run(_preflight_identities(AbsentClient(), bundle))

    assert result["absent"] > 0
    assert result["matching"] == 0


class ProbeClient:
    def __init__(self) -> None:
        self.entities: dict[str, dict[str, dict]] = {}

    async def upsert_entity(
        self, _entity_type: str, urn: str, aspects: dict, _audit: dict
    ) -> None:
        self.entities.setdefault(urn, {}).update(deepcopy(aspects))

    async def get_entity(self, urn: str, aspects: tuple[str, ...]) -> dict:
        return {
            "aspects": {
                name: {"value": deepcopy(self.entities[urn][name])}
                for name in aspects
            }
        }


def test_relationship_probe_reads_n_one_and_leaves_probe_retired() -> None:
    client = ProbeClient()
    result = asyncio.run(
        _relationship_probe(
            client,
            actor_urn="urn:li:corpuser:phase8",
            timeout_seconds=1.0,
        )
    )

    assert result["cardinality"] == "N_ONE"
    assert result["relationship_count"] == 1
    assert all(entity["status"] == {"removed": True} for entity in client.entities.values())


def test_runtime_nonregression_requires_exact_node1_ast_and_result() -> None:
    probe = {
        "node1": {"exact": True, "selected_metric_ids": ["metric"]},
        "analysis": {"ast_sha256": "a" * 64, "result_sha256": "b" * 64},
        "readiness": {"catalog": "ready"},
        "node1_model_call_count": 1,
        "node1_source_or_release_missing_count": 0,
        "sql_execution_count": 1,
        "active_pointer_unchanged": True,
    }
    _assert_runtime_nonregression(probe, deepcopy(probe))

    changed = deepcopy(probe)
    changed["analysis"]["result_sha256"] = "c" * 64
    with pytest.raises(Phase8Error, match="non-regression"):
        _assert_runtime_nonregression(probe, changed)
