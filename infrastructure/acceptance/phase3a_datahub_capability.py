"""Probe pinned DataHub v1.7 Metric and AI Context support in one isolated GMS.

The workflow is hard-bound to ``answervice-phase2b-datahub`` on loopback port
38081.  It writes one stable, non-authoritative probe Metric, verifies exact
Rest.li and GraphQL read-back, rehearses retire/restore, and leaves the probe
retired.  Credentials are read only from process memory and are never returned.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from time import monotonic, time_ns
from typing import Any

import httpx


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(HERE), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from metadata_rest import aspect_value, assert_contains  # noqa: E402
from metadata_wire import validated_audit_stamp  # noqa: E402
from phase2b_datahub_candidate import (  # noqa: E402
    AcceptanceError,
    IsolatedSystemClient,
    TARGET_PORT,
    TARGET_PROJECT,
)
from src.data.governance_contract import (  # noqa: E402
    canonical_json,
    canonical_sha256,
)


PINNED_GMS_IMAGE = (
    "acryldata/datahub-gms:v1.7.0@"
    "sha256:54bc4431402846a72d1c1bdb69fae1148f74a59425144aa947fdf1c3506461f7"
)
METRIC_INFO_SCHEMA_VERSION = 4
AI_CONTEXT_SCHEMA_VERSION = 1
PROBE_PATH = "answervice.capability_probe"
PROBE_ID = "phase3a_metric_v1"
PROBE_URN = f"urn:li:metric:(urn:li:dataPlatform:datahub,{PROBE_PATH},{PROBE_ID})"
PROBE_NAME = "Answervice Phase 3A capability probe"
PROBE_DESCRIPTION = "Isolated metadata capability probe; never runtime authority."
PROBE_EXPRESSION = {
    "dialects": [{"dialect": "ANSI_SQL", "expression": "SUM(probe_value)"}]
}
PROBE_AI_CONTEXT = {
    "synonyms": ["phase 3 capability probe"],
    "instructions": "Interpret only as an isolated metadata capability probe.",
    "examples": ["Validate a metadata capability without executing a query."],
    "customInstructions": "Never use this probe for a runtime decision.",
}

_TYPE_QUERY = """
query Phase3TypeProbe($name: String!) {
  __type(name: $name) {
    name
    kind
    fields { name }
    enumValues { name }
  }
}
""".strip()

_METRIC_QUERY = """
query Phase3MetricReadback($urn: String!) {
  metric(urn: $urn) {
    urn
    type
    id
    path
    exists
    info {
      name
      description
      expression { dialects { dialect expression } }
    }
    aiContext { synonyms instructions examples customInstructions }
    status { removed }
  }
}
""".strip()


class Phase3CapabilityError(AcceptanceError):
    """The pinned capability cannot be proved without lowering the Phase 3A Gate."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("check", "probe"), required=True)
    parser.add_argument("--target-project", default=TARGET_PROJECT)
    parser.add_argument(
        "--target-server", default=f"https://127.0.0.1:{TARGET_PORT}"
    )
    parser.add_argument(
        "--ca-file",
        type=Path,
        default=os.getenv("DATAHUB_TLS_CA_HOST_FILE"),
    )
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--expected-catalog-sha256", required=True)
    parser.add_argument("--expected-canonical-sha256", required=True)
    parser.add_argument("--verify-timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def _validate_boundary(args: argparse.Namespace) -> Path:
    url = httpx.URL(args.target_server)
    if (
        args.target_project != TARGET_PROJECT
        or url.scheme != "https"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.port != TARGET_PORT
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise Phase3CapabilityError("Phase 3A target is not the approved isolated GMS")
    if args.verify_timeout <= 0:
        raise Phase3CapabilityError("Phase 3A verify timeout must be positive")
    if not isinstance(args.expected_release, str) or not args.expected_release.strip():
        raise Phase3CapabilityError("Phase 3A release identity is required")
    for value in (
        args.expected_catalog_sha256,
        args.expected_canonical_sha256,
    ):
        if not _is_sha256(value):
            raise Phase3CapabilityError("Phase 3A release checksum is invalid")
    if not isinstance(args.ca_file, Path):
        raise Phase3CapabilityError("Phase 3A CA file is required")
    try:
        ca_file = args.ca_file.resolve(strict=True)
    except OSError as error:
        raise Phase3CapabilityError("Phase 3A CA file is unavailable") from error
    if not ca_file.is_file():
        raise Phase3CapabilityError("Phase 3A CA file is unavailable")
    return ca_file


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


async def probe_pinned_schema(client: Any) -> dict[str, Any]:
    """Require the exact pinned GraphQL surface corresponding to the image PDL."""

    observed: dict[str, dict[str, Any]] = {}
    for name in (
        "Metric",
        "MetricInfo",
        "AiContext",
        "MetricExpression",
        "DialectExpression",
        "Dialect",
    ):
        payload = await client.graphql(_TYPE_QUERY, {"name": name})
        schema_type = payload.get("data", {}).get("__type")
        if not isinstance(schema_type, dict) or schema_type.get("name") != name:
            raise Phase3CapabilityError(f"pinned DataHub type {name} is unavailable")
        fields = schema_type.get("fields")
        enum_values = schema_type.get("enumValues")
        observed[name] = {
            "kind": schema_type.get("kind"),
            "fields": sorted(
                item["name"]
                for item in fields or []
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ),
            "enum_values": sorted(
                item["name"]
                for item in enum_values or []
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ),
        }

    metric_fields = set(observed["Metric"]["fields"])
    metric_info_fields = set(observed["MetricInfo"]["fields"])
    if not {"info", "aiContext", "status"} <= metric_fields:
        raise Phase3CapabilityError("Metric GraphQL surface lacks Phase 3 fields")
    if "expression" not in metric_info_fields or "aiContext" in metric_info_fields:
        raise Phase3CapabilityError("MetricInfo does not match pinned schema version 4")
    if set(observed["AiContext"]["fields"]) != {
        "synonyms",
        "instructions",
        "examples",
        "customInstructions",
    }:
        raise Phase3CapabilityError("AiContext does not match pinned schema version 1")
    if set(observed["MetricExpression"]["fields"]) != {"dialects"}:
        raise Phase3CapabilityError("MetricExpression schema differs")
    if set(observed["DialectExpression"]["fields"]) != {
        "dialect",
        "expression",
    }:
        raise Phase3CapabilityError("DialectExpression schema differs")
    if "ANSI_SQL" not in observed["Dialect"]["enum_values"]:
        raise Phase3CapabilityError("ANSI_SQL Metric dialect is unavailable")

    normalized = {
        "datahub_model_version": "v1.7.0",
        "metric_info_schema_version": METRIC_INFO_SCHEMA_VERSION,
        "ai_context_schema_version": AI_CONTEXT_SCHEMA_VERSION,
        "metric_has_ai_context": True,
        "metric_info_has_expression": True,
        "metric_info_embeds_ai_context": False,
        "ai_context_fields": observed["AiContext"]["fields"],
        "metric_expression_fields": observed["MetricExpression"]["fields"],
        "dialect_expression_fields": observed["DialectExpression"]["fields"],
        "ansi_sql_dialect": True,
    }
    return {**normalized, "schema_receipt_sha256": canonical_sha256(normalized)}


def _probe_aspects(*, removed: bool) -> dict[str, dict[str, Any]]:
    return {
        "metricKey": {
            "platform": "urn:li:dataPlatform:datahub",
            "path": PROBE_PATH,
            "id": PROBE_ID,
        },
        "metricInfo": {
            "name": PROBE_NAME,
            "description": PROBE_DESCRIPTION,
            "expression": PROBE_EXPRESSION,
        },
        "aiContext": PROBE_AI_CONTEXT,
        "status": {"removed": removed},
    }


async def _read_graph(client: Any) -> Mapping[str, Any] | None:
    payload = await client.graphql(_METRIC_QUERY, {"urn": PROBE_URN})
    metric = payload.get("data", {}).get("metric")
    if metric is None:
        return None
    if not isinstance(metric, Mapping):
        raise Phase3CapabilityError("Phase 3A GraphQL Metric response is malformed")
    return metric


async def _preflight_probe_identity(client: Any) -> str:
    metric = await _read_graph(client)
    if metric is None or metric.get("exists") is False:
        return "ABSENT"
    info = metric.get("info")
    status = metric.get("status")
    if (
        metric.get("urn") == PROBE_URN
        and isinstance(info, Mapping)
        and info.get("name") == PROBE_NAME
        and isinstance(status, Mapping)
        and status.get("removed") is True
    ):
        return "RETIRED_REUSABLE"
    raise Phase3CapabilityError("Phase 3A probe URN is occupied or active")


def _assert_graph(metric: Mapping[str, Any], *, removed: bool) -> None:
    info = metric.get("info")
    status = metric.get("status")
    if (
        metric.get("urn") != PROBE_URN
        or metric.get("type") != "METRIC"
        or metric.get("id") != PROBE_ID
        or metric.get("path") != PROBE_PATH
        or metric.get("exists") is not True
        or not isinstance(info, Mapping)
        or info.get("name") != PROBE_NAME
        or info.get("description") != PROBE_DESCRIPTION
        or info.get("expression") != PROBE_EXPRESSION
        or metric.get("aiContext") != PROBE_AI_CONTEXT
        or not isinstance(status, Mapping)
        or status.get("removed") is not removed
    ):
        raise Phase3CapabilityError("Phase 3A GraphQL exact read-back differs")


async def _assert_rest(client: Any, *, removed: bool) -> None:
    expected = _probe_aspects(removed=removed)
    entity = await client.get_entity(PROBE_URN, tuple(expected))
    assert_contains(aspect_value(entity, "metricKey"), expected["metricKey"], "metricKey")
    assert_contains(
        aspect_value(entity, "metricInfo"), expected["metricInfo"], "metricInfo"
    )
    if aspect_value(entity, "aiContext") != expected["aiContext"]:
        raise Phase3CapabilityError("Phase 3A Rest.li aiContext differs")
    if aspect_value(entity, "status").get("removed") is not removed:
        raise Phase3CapabilityError("Phase 3A Rest.li retirement state differs")


async def _wait_exact_state(
    client: Any,
    *,
    removed: bool,
    timeout_seconds: float,
) -> None:
    deadline = monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while True:
        try:
            await _assert_rest(client, removed=removed)
            metric = await _read_graph(client)
            if metric is None:
                raise Phase3CapabilityError("Phase 3A Metric is absent after mutation")
            _assert_graph(metric, removed=removed)
            return
        except (AcceptanceError, ValueError) as error:
            last_error = error
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise Phase3CapabilityError("Phase 3A read-back did not converge") from last_error
        await asyncio.sleep(min(0.5, remaining))


async def _set_retired(
    client: Any,
    *,
    actor_urn: str,
    removed: bool,
    timeout_seconds: float,
) -> None:
    audit = validated_audit_stamp({"actor": actor_urn, "time": time_ns() // 1_000_000})
    await client.upsert_entity("metric", PROBE_URN, {"status": {"removed": removed}}, audit)
    await _wait_exact_state(
        client, removed=removed, timeout_seconds=timeout_seconds
    )


async def execute_capability_probe(
    client: Any,
    *,
    actor_urn: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Write one probe, rehearse retirement rollback, and leave it retired."""

    audit = validated_audit_stamp({"actor": actor_urn, "time": time_ns() // 1_000_000})
    mutation_started = False
    try:
        await client.upsert_entity(
            "metric", PROBE_URN, _probe_aspects(removed=False), audit
        )
        mutation_started = True
        await _wait_exact_state(client, removed=False, timeout_seconds=timeout_seconds)
        await _set_retired(
            client,
            actor_urn=actor_urn,
            removed=True,
            timeout_seconds=timeout_seconds,
        )
        await _set_retired(
            client,
            actor_urn=actor_urn,
            removed=False,
            timeout_seconds=timeout_seconds,
        )
        await _set_retired(
            client,
            actor_urn=actor_urn,
            removed=True,
            timeout_seconds=timeout_seconds,
        )
    except BaseException as error:
        if mutation_started:
            try:
                await _set_retired(
                    client,
                    actor_urn=actor_urn,
                    removed=True,
                    timeout_seconds=timeout_seconds,
                )
            except BaseException as cleanup_error:
                raise Phase3CapabilityError(
                    "Phase 3A failed and the probe could not be retired"
                ) from cleanup_error
        raise error
    return {
        "rest_exact_readback": True,
        "graphql_exact_readback": True,
        "retirement_verified": True,
        "rollback_restore_verified": True,
        "final_probe_retired": True,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    ca_file = _validate_boundary(args)
    client_id = os.getenv("DATAHUB_SYSTEM_CLIENT_ID", "")
    client_secret = os.getenv("DATAHUB_SYSTEM_CLIENT_SECRET", "")
    if not client_id or not client_secret or ":" in client_id:
        raise Phase3CapabilityError("isolated DataHub system credentials are required")
    actor_urn = f"urn:li:corpuser:{client_id}"
    async with IsolatedSystemClient(
        args.target_server,
        ca_file=ca_file,
        client_id=client_id,
        client_secret=client_secret,
        timeout_seconds=args.verify_timeout,
    ) as client:
        schema = await probe_pinned_schema(client)
        preflight_state = await _preflight_probe_identity(client)
        base = {
            "target_project": args.target_project,
            "target_port": TARGET_PORT,
            "pinned_gms_image": PINNED_GMS_IMAGE,
            "release_id": args.expected_release,
            "catalog_sha256": args.expected_catalog_sha256,
            "canonical_sha256": args.expected_canonical_sha256,
            "stable_metric_urn_sha256": canonical_sha256(PROBE_URN),
            "stable_urn_catalog_independent": (
                args.expected_catalog_sha256 not in PROBE_URN
            ),
            "release_membership_mode": (
                "EXTERNAL_CHECKSUM_MANIFEST_PLUS_EXPLICIT_STATUS_FILTER"
            ),
            "release_membership_sha256": canonical_sha256(
                {
                    "release_id": args.expected_release,
                    "catalog_sha256": args.expected_catalog_sha256,
                    "canonical_sha256": args.expected_canonical_sha256,
                    "metric_urns": [PROBE_URN],
                }
            ),
            "preflight_probe_state": preflight_state,
            "schema": schema,
            "runtime_authority_activated": False,
        }
        if args.mode == "check":
            return {**base, "status": "READY_FOR_CAPABILITY_PROBE"}
        transition = await execute_capability_probe(
            client,
            actor_urn=actor_urn,
            timeout_seconds=args.verify_timeout,
        )
        return {
            **base,
            **transition,
            "status": "SUPPORTED",
            "native_metric": "SUPPORTED",
            "metric_expression": "SUPPORTED",
            "ai_context": "SUPPORTED",
            "native_versioned_membership": "EXTERNAL_MANIFEST_REQUIRED",
        }


async def async_main(argv: list[str] | None = None) -> int:
    print(canonical_json(await run(parse_args(argv))))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(async_main(argv))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "ERROR", "error_type": type(error).__name__},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
