"""Phase 3B isolated native Metric shadow workflow 경계를 검증한다."""

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
for entry in (str(ROOT), str(ACCEPTANCE), str(DATAHUB), str(BACKEND), str(ROOT / "tests" / "data")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from native_metric_shadow import native_metric_shadow_projection, native_metric_urn  # noqa: E402
from phase3b_native_metric_shadow import (  # noqa: E402
    Phase3BError,
    RetryingIsolatedClient,
    _CANDIDATE_ENTITY_TYPES,
    _grouped_aspects,
    _preflight_identities,
    _search,
    _set_removed,
    _validate_boundary,
    parse_args,
)
from phase2b_datahub_candidate import AcceptanceError  # noqa: E402
from test_metric_governance_v2 import _v2_bundle  # noqa: E402


def _args(extra: list[str] | None = None):
    return parse_args(
        [
            "--mode",
            "check",
            "--target-project",
            "answervice-phase2b-datahub",
            "--source-server",
            "https://127.0.0.1:28081",
            "--target-server",
            "https://127.0.0.1:38081",
            "--expected-release",
            "release-v1",
            "--expected-catalog-sha256",
            "a" * 64,
            "--expected-canonical-sha256",
            "b" * 64,
            "--serving-schema",
            "analytics_v4_3",
            "--trino-ca-file",
            str(ROOT / "tests" / "fixtures" / "ca.pem"),
            *(extra or []),
        ]
    )


def test_boundary_is_hard_bound_to_current_read_and_isolated_write_ports() -> None:
    _validate_boundary(_args())

    with pytest.raises(Phase3BError, match="source endpoint"):
        _validate_boundary(
            _args(["--source-server", "https://127.0.0.1:38081"])
        )
    with pytest.raises(Phase3BError, match="target endpoint"):
        _validate_boundary(
            _args(["--target-server", "https://127.0.0.1:28081"])
        )


def test_projection_uses_stable_identity_expression_and_ai_context() -> None:
    bundle = _v2_bundle()
    projection = native_metric_shadow_projection(bundle)
    grouped = _grouped_aspects(bundle)

    assert projection["native_metric_path"] == "answervice.business_metrics"
    assert projection["native_metric_count"] == 2
    assert projection["native_expression_count"] == 2
    assert projection["native_ai_context_count"] == 2
    assert len(grouped) == 2
    assert all("expression" in aspects["metricInfo"] for aspects in grouped.values())
    assert all(set(aspects["aiContext"]) == {"synonyms"} for aspects in grouped.values())
    assert "METRIC" not in _CANDIDATE_ENTITY_TYPES


class StatusClient:
    def __init__(self, bundle: dict, *, removed: bool | None, wrong_name: bool = False):
        self.bundle = bundle
        self.removed = removed
        self.wrong_name = wrong_name
        self.writes: list[tuple[str, bool]] = []

    async def graphql(self, _query: str, variables: dict) -> dict:
        if self.removed is None:
            return {"data": {"metric": None}}
        metric_id = variables["urn"].rsplit(",", 1)[-1].removesuffix(")")
        terms = {item["id"]: item for item in self.bundle["metric_terms"]}
        name = "collision" if self.wrong_name else terms[metric_id]["name"]
        return {
            "data": {
                "metric": {
                    "urn": variables["urn"],
                    "exists": True,
                    "info": {"name": name},
                    "status": {"removed": self.removed},
                }
            }
        }

    async def upsert_entity(
        self, _entity_type: str, urn: str, aspects: dict, _audit: dict
    ) -> None:
        self.writes.append((urn, aspects["status"]["removed"]))


def test_preflight_allows_absent_or_matching_and_rejects_collision() -> None:
    bundle = _v2_bundle()

    assert asyncio.run(_preflight_identities(StatusClient(bundle, removed=None), bundle)) == {
        "absent": 2,
        "retired": 0,
        "active_matching": 0,
        "partial_matching": 0,
    }
    assert asyncio.run(_preflight_identities(StatusClient(bundle, removed=True), bundle)) == {
        "absent": 0,
        "retired": 2,
        "active_matching": 0,
        "partial_matching": 0,
    }
    with pytest.raises(Phase3BError, match="occupied"):
        asyncio.run(
            _preflight_identities(
                StatusClient(bundle, removed=False, wrong_name=True), bundle
            )
        )


def test_retirement_updates_only_explicit_native_metric_urns() -> None:
    bundle = _v2_bundle()
    client = StatusClient(bundle, removed=False)
    urns = sorted(
        native_metric_urn(bundle, item["id"]) for item in bundle["metric_terms"]
    )

    asyncio.run(
        _set_removed(
            client,
            urns,
            actor_urn="urn:li:corpuser:__datahub_system",
            removed=True,
        )
    )

    assert client.writes == [(urn, True) for urn in urns]


class SearchClient:
    def __init__(self, entity_type: str = "METRIC") -> None:
        self.entity_type = entity_type

    async def graphql(self, _query: str, _variables: dict) -> dict:
        return {
            "data": {
                "searchAcrossEntities": {
                    "total": 1,
                    "count": 1,
                    "start": 0,
                    "searchResults": [
                        {
                            "entity": {
                                "urn": "urn:li:metric:(urn:li:dataPlatform:datahub,path,id)",
                                "type": self.entity_type,
                            }
                        }
                    ],
                }
            }
        }


def test_search_parser_rejects_non_metric_entities() -> None:
    assert len(asyncio.run(_search(SearchClient(), "metric"))) == 1
    with pytest.raises(Phase3BError, match="identity"):
        asyncio.run(_search(SearchClient("DATASET"), "metric"))


class FlakyClient:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    async def graphql(self, _query: str, _variables: dict) -> dict:
        self.calls += 1
        if self.calls == 1:
            raise AcceptanceError(self.message)
        return {"data": {"ok": True}}


def test_retry_is_bounded_to_generic_transport_failures() -> None:
    transient = FlakyClient("isolated DataHub request failed")
    result = asyncio.run(
        RetryingIsolatedClient(transient).graphql("query { ok }", {})
    )
    assert result == {"data": {"ok": True}}
    assert transient.calls == 2

    validation = FlakyClient("isolated DataHub request failed with HTTP 422")
    with pytest.raises(AcceptanceError, match="HTTP 422"):
        asyncio.run(
            RetryingIsolatedClient(validation).graphql("query { ok }", {})
        )
    assert validation.calls == 1


def test_membership_changes_without_changing_logical_urn() -> None:
    baseline = _v2_bundle()
    successor = deepcopy(baseline)
    successor["catalog_version"] = "successor"

    metric_id = baseline["metric_terms"][0]["id"]
    assert native_metric_urn(baseline, metric_id) == native_metric_urn(
        successor, metric_id
    )
    assert native_metric_shadow_projection(baseline)["release_membership_sha256"] != (
        native_metric_shadow_projection(successor)["release_membership_sha256"]
    )
