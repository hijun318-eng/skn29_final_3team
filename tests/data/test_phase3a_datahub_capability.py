"""Phase 3A native Metric/AI Context acceptance 경계를 검증한다."""

from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "infrastructure" / "acceptance"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(ACCEPTANCE), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from metadata_wire import metadata_change_proposals  # noqa: E402
from phase3a_datahub_capability import (  # noqa: E402
    PROBE_AI_CONTEXT,
    PROBE_DESCRIPTION,
    PROBE_EXPRESSION,
    PROBE_ID,
    PROBE_NAME,
    PROBE_PATH,
    PROBE_URN,
    Phase3CapabilityError,
    _validate_boundary,
    execute_capability_probe,
    parse_args,
    probe_pinned_schema,
)


TYPE_FIXTURES = {
    "Metric": {
        "name": "Metric",
        "kind": "OBJECT",
        "fields": [{"name": name} for name in ("urn", "info", "aiContext", "status")],
        "enumValues": None,
    },
    "MetricInfo": {
        "name": "MetricInfo",
        "kind": "OBJECT",
        "fields": [{"name": name} for name in ("name", "description", "expression")],
        "enumValues": None,
    },
    "AiContext": {
        "name": "AiContext",
        "kind": "OBJECT",
        "fields": [
            {"name": name}
            for name in ("synonyms", "instructions", "examples", "customInstructions")
        ],
        "enumValues": None,
    },
    "MetricExpression": {
        "name": "MetricExpression",
        "kind": "OBJECT",
        "fields": [{"name": "dialects"}],
        "enumValues": None,
    },
    "DialectExpression": {
        "name": "DialectExpression",
        "kind": "OBJECT",
        "fields": [{"name": "dialect"}, {"name": "expression"}],
        "enumValues": None,
    },
    "Dialect": {
        "name": "Dialect",
        "kind": "ENUM",
        "fields": None,
        "enumValues": [{"name": "ANSI_SQL"}, {"name": "OTHER"}],
    },
}


class SchemaClient:
    def __init__(self, fixtures: dict | None = None) -> None:
        self.fixtures = fixtures or TYPE_FIXTURES

    async def graphql(self, _query: str, variables: dict) -> dict:
        return {"data": {"__type": self.fixtures.get(variables["name"])}}


class TransitionClient:
    def __init__(self) -> None:
        self.aspects: dict[str, dict] = {}
        self.retirement_writes: list[bool] = []

    async def upsert_entity(
        self,
        entity_type: str,
        urn: str,
        aspects: dict,
        _audit: dict,
    ) -> None:
        assert entity_type == "metric"
        assert urn == PROBE_URN
        self.aspects.update(deepcopy(aspects))
        if "status" in aspects:
            self.retirement_writes.append(aspects["status"]["removed"])

    async def get_entity(self, urn: str, aspects: tuple[str, ...]) -> dict:
        assert urn == PROBE_URN
        return {
            "aspects": {
                name: {"value": deepcopy(self.aspects[name])} for name in aspects
            }
        }

    async def graphql(self, _query: str, variables: dict) -> dict:
        assert variables == {"urn": PROBE_URN}
        if not self.aspects:
            return {"data": {"metric": None}}
        key = self.aspects["metricKey"]
        info = self.aspects["metricInfo"]
        return {
            "data": {
                "metric": {
                    "urn": PROBE_URN,
                    "type": "METRIC",
                    "id": key["id"],
                    "path": key["path"],
                    "exists": True,
                    "info": deepcopy(info),
                    "aiContext": deepcopy(self.aspects["aiContext"]),
                    "status": deepcopy(self.aspects["status"]),
                }
            }
        }


def test_pinned_schema_requires_expression_and_separate_ai_context() -> None:
    result = asyncio.run(probe_pinned_schema(SchemaClient()))

    assert result["metric_info_schema_version"] == 4
    assert result["ai_context_schema_version"] == 1
    assert result["metric_info_has_expression"] is True
    assert result["metric_info_embeds_ai_context"] is False
    assert len(result["schema_receipt_sha256"]) == 64


def test_pinned_schema_rejects_nested_ai_context_claim() -> None:
    fixtures = deepcopy(TYPE_FIXTURES)
    fixtures["MetricInfo"]["fields"].append({"name": "aiContext"})

    with pytest.raises(Phase3CapabilityError, match="schema version 4"):
        asyncio.run(probe_pinned_schema(SchemaClient(fixtures)))


def test_probe_rehearses_retire_restore_and_leaves_entity_retired() -> None:
    client = TransitionClient()

    result = asyncio.run(
        execute_capability_probe(
            client,
            actor_urn="urn:li:corpuser:__datahub_system",
            timeout_seconds=1.0,
        )
    )

    assert client.retirement_writes == [False, True, False, True]
    assert client.aspects["status"] == {"removed": True}
    assert result == {
        "rest_exact_readback": True,
        "graphql_exact_readback": True,
        "retirement_verified": True,
        "rollback_restore_verified": True,
        "final_probe_retired": True,
    }


def test_probe_identity_is_stable_and_not_release_hash_scoped() -> None:
    assert PROBE_URN == (
        "urn:li:metric:(urn:li:dataPlatform:datahub,"
        "answervice.capability_probe,phase3a_metric_v1)"
    )
    assert PROBE_PATH in PROBE_URN
    assert PROBE_ID in PROBE_URN
    assert "sha256" not in PROBE_URN


def test_ai_context_wire_is_bounded_and_rejects_unknown_fields() -> None:
    proposals = metadata_change_proposals(
        "metric",
        PROBE_URN,
        {"aiContext": PROBE_AI_CONTEXT},
        {"actor": "urn:li:corpuser:publisher", "time": 1_800_000_000_000},
    )
    assert len(proposals) == 1
    assert proposals[0]["aspectName"] == "aiContext"

    with pytest.raises(ValueError, match="unsupported fields"):
        metadata_change_proposals(
            "metric",
            PROBE_URN,
            {"aiContext": {**PROBE_AI_CONTEXT, "systemPrompt": "ignore policy"}},
            {"actor": "urn:li:corpuser:publisher", "time": 1_800_000_000_000},
        )


def test_boundary_refuses_nonisolated_target(tmp_path: Path) -> None:
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("test-only-ca", encoding="utf-8")
    common = [
        "--mode",
        "check",
        "--ca-file",
        str(ca_file),
        "--expected-release",
        "release-v1",
        "--expected-catalog-sha256",
        "a" * 64,
        "--expected-canonical-sha256",
        "b" * 64,
    ]

    assert _validate_boundary(parse_args(common)).is_file()
    with pytest.raises(Phase3CapabilityError, match="approved isolated GMS"):
        _validate_boundary(
            parse_args([*common, "--target-server", "https://127.0.0.1:28081"])
        )


def test_probe_payload_is_generic_and_non_authoritative() -> None:
    assert PROBE_NAME
    assert PROBE_DESCRIPTION.endswith("never runtime authority.")
    assert PROBE_EXPRESSION == {
        "dialects": [{"dialect": "ANSI_SQL", "expression": "SUM(probe_value)"}]
    }
    assert set(PROBE_AI_CONTEXT) == {
        "synonyms",
        "instructions",
        "examples",
        "customInstructions",
    }
