"""Publish and verify supported native Metric/AI Context in isolated DataHub.

The current DataHub and Trino endpoints are read-only release sources.  Every
write is hard-bound to ``answervice-phase2b-datahub`` on loopback port 38081.
The workflow never activates native metadata as Backend runtime authority.
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
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(HERE), str(DATAHUB), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.services.context.semantic_release import (  # noqa: E402
    CanonicalSemanticRelease,
)
from app.adapters.query_governance import _CANDIDATE_ENTITY_TYPES  # noqa: E402
from metadata_rest import aspect_value, preflight_owner_entities  # noqa: E402
from metadata_wire import validated_audit_stamp  # noqa: E402
from native_metric_publication import (  # noqa: E402
    probe_native_metric_model,
    verify_native_metric_shadow,
)
from native_metric_shadow import (  # noqa: E402
    iter_native_metric_aspects,
    native_metric_shadow_projection,
    native_metric_urn,
)
from phase2b_datahub_candidate import (  # noqa: E402
    AcceptanceError,
    IsolatedSystemClient,
    TARGET_PORT,
    TARGET_PROJECT,
    _build_bundle,
)
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import (  # noqa: E402
    canonical_sha256,
    catalog_hash,
)
from src.data.metric_governance import (  # noqa: E402
    business_metric_ids,
    runtime_governance_version,
)


_SEARCH_QUERY = """
query Phase3BMetricSearch($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    total
    count
    start
    searchResults { entity { urn type } }
  }
}
""".strip()

_STATUS_QUERY = """
query Phase3BMetricStatus($urn: String!) {
  metric(urn: $urn) {
    urn
    exists
    info { name }
    status { removed }
  }
}
""".strip()


class Phase3BError(AcceptanceError):
    """Native shadow equality or rollback cannot be proved without lowering the Gate."""


class RetryingIsolatedClient:
    """Retry only transport failures for idempotent isolated read/UPSERT calls."""

    def __init__(self, client: Any, *, attempts: int = 3) -> None:
        if attempts < 1 or attempts > 3:
            raise Phase3BError("Phase 3B retry attempts are outside the bound")
        self._client = client
        self._attempts = attempts

    async def _call(self, method: str, *args: object, **kwargs: object) -> Any:
        for attempt in range(self._attempts):
            try:
                return await getattr(self._client, method)(*args, **kwargs)
            except AcceptanceError as error:
                # HTTP status failures are deterministic contract/auth responses.
                # Only the client's bounded generic transport failure is retried.
                if str(error) != "isolated DataHub request failed" or attempt + 1 >= self._attempts:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))
        raise AssertionError("unreachable retry state")

    async def graphql(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        return await self._call("graphql", query, variables)

    async def get_entity(self, urn: str, aspects: tuple[str, ...]) -> dict[str, Any]:
        return await self._call("get_entity", urn, aspects)

    async def upsert_entity(
        self,
        entity_type: str,
        urn: str,
        aspects: Mapping[str, Mapping[str, Any]],
        audit_stamp: Mapping[str, Any],
    ) -> None:
        await self._call("upsert_entity", entity_type, urn, aspects, audit_stamp)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("check", "retire", "shadow"), required=True)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--source-server", required=True)
    parser.add_argument("--target-server", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--expected-catalog-sha256", required=True)
    parser.add_argument("--expected-canonical-sha256", required=True)
    parser.add_argument("--serving-schema", required=True)
    parser.add_argument("--recipe-dir", type=Path, default=DATAHUB / "recipes")
    parser.add_argument(
        "--trino-server", default=os.getenv("TRINO_URL", "https://127.0.0.1:18443")
    )
    parser.add_argument(
        "--trino-ca-file",
        type=Path,
        default=os.getenv("TRINO_TLS_CA_FILE") or os.getenv("TRINO_TLS_CA_HOST_FILE"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--verify-timeout", type=float, default=180.0)
    return parser.parse_args(argv)


def _validate_boundary(args: argparse.Namespace) -> None:
    source, target = httpx.URL(args.source_server), httpx.URL(args.target_server)
    for url, expected_port, context in (
        (source, 28081, "source"),
        (target, TARGET_PORT, "target"),
    ):
        if (
            url.scheme != "https"
            or url.host not in {"127.0.0.1", "localhost", "::1"}
            or url.port != expected_port
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise Phase3BError(f"Phase 3B {context} endpoint is outside its boundary")
    if args.target_project != TARGET_PROJECT or source == target:
        raise Phase3BError("Phase 3B target is not the approved isolated project")
    if args.timeout <= 0 or args.verify_timeout <= 0:
        raise Phase3BError("Phase 3B timeouts must be positive")
    if not isinstance(args.trino_ca_file, Path):
        raise Phase3BError("Phase 3B Trino CA is required")
    for value in (args.expected_catalog_sha256, args.expected_canonical_sha256):
        if not _is_sha256(value):
            raise Phase3BError("Phase 3B expected checksum is invalid")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _grouped_aspects(
    bundle: Mapping[str, Any],
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for entity_type, urn, name, value in iter_native_metric_aspects(bundle):
        grouped.setdefault((entity_type, urn), {})[name] = value
    return dict(sorted(grouped.items()))


def _canonical_checksum(bundle: Mapping[str, Any]) -> str:
    release = CanonicalSemanticRelease.from_validated_bundle(
        bundle,
        runtime_contract_version=runtime_governance_version(bundle),
        source_kind="datahub_native_shadow",
    )
    return release.canonical_checksum


async def _metric_status(client: Any, urn: str) -> Mapping[str, Any] | None:
    payload = await client.graphql(_STATUS_QUERY, {"urn": urn})
    metric = payload.get("data", {}).get("metric")
    if metric is None:
        return None
    if not isinstance(metric, Mapping):
        raise Phase3BError("Phase 3B Metric status response is malformed")
    return metric


async def _preflight_identities(
    client: Any,
    bundle: Mapping[str, Any],
) -> dict[str, int]:
    terms = {str(item["id"]): item for item in bundle["metric_terms"]}
    rules = {str(item["id"]): item for item in bundle["metric_rules"]}
    active = retired = absent = partial = 0
    for metric_id in sorted(business_metric_ids(rules.values())):
        metric = await _metric_status(client, native_metric_urn(bundle, metric_id))
        if metric is None or metric.get("exists") is False:
            absent += 1
            continue
        info, status = metric.get("info"), metric.get("status")
        if (
            metric_id not in terms
            or not isinstance(info, Mapping)
            or info.get("name") != terms[metric_id]["name"]
        ):
            raise Phase3BError("stable native Metric URN is occupied by different metadata")
        if status is None:
            partial += 1
            continue
        if not isinstance(status, Mapping) or status.get("removed") not in {True, False}:
            raise Phase3BError("stable native Metric status is malformed")
        if status["removed"]:
            retired += 1
        else:
            active += 1
    return {
        "absent": absent,
        "retired": retired,
        "active_matching": active,
        "partial_matching": partial,
    }


async def _present_expected_urns(
    client: Any,
    bundle: Mapping[str, Any],
) -> list[str]:
    terms = {str(item["id"]): item for item in bundle["metric_terms"]}
    present: list[str] = []
    for metric_id in sorted(terms):
        urn = native_metric_urn(bundle, metric_id)
        metric = await _metric_status(client, urn)
        if metric is None or metric.get("exists") is False:
            continue
        info = metric.get("info")
        if not isinstance(info, Mapping) or info.get("name") != terms[metric_id]["name"]:
            raise Phase3BError("stable native Metric URN is occupied by different metadata")
        present.append(urn)
    return present


async def _publish(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    actor_urn: str,
    attempted_urns: list[str],
) -> int:
    audit = validated_audit_stamp({"actor": actor_urn, "time": time_ns() // 1_000_000})
    await preflight_owner_entities(client, bundle)
    count = 0
    for (entity_type, urn), aspects in _grouped_aspects(bundle).items():
        attempted_urns.append(urn)
        await client.upsert_entity(entity_type, urn, aspects, audit)
        count += 1
    return count


async def _wait_full_verify(
    client: Any,
    bundle: Mapping[str, Any],
    projection_sha256: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while True:
        try:
            return await verify_native_metric_shadow(
                client,
                bundle,
                expected_projection_sha256=projection_sha256,
            )
        except (AcceptanceError, ValueError) as error:
            last_error = error
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise Phase3BError("native Metric shadow did not converge") from last_error
        await asyncio.sleep(min(0.5, remaining))


async def _set_removed(
    client: Any,
    urns: list[str],
    *,
    actor_urn: str,
    removed: bool,
) -> None:
    audit = validated_audit_stamp({"actor": actor_urn, "time": time_ns() // 1_000_000})
    for urn in urns:
        await client.upsert_entity("metric", urn, {"status": {"removed": removed}}, audit)


async def _wait_removed(
    client: Any,
    urns: list[str],
    *,
    removed: bool,
    timeout_seconds: float,
) -> None:
    deadline = monotonic() + timeout_seconds
    while True:
        exact = True
        for urn in urns:
            try:
                entity = await client.get_entity(urn, ("status",))
                rest_removed = aspect_value(entity, "status").get("removed")
                metric = await _metric_status(client, urn)
                graph_removed = (
                    metric.get("status", {}).get("removed")
                    if isinstance(metric, Mapping)
                    else None
                )
                if rest_removed is not removed or graph_removed is not removed:
                    exact = False
            except (AcceptanceError, ValueError):
                exact = False
        if exact:
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise Phase3BError("native Metric retirement state did not converge")
        await asyncio.sleep(min(0.5, remaining))


async def _search(client: Any, query: str) -> set[str]:
    payload = await client.graphql(
        _SEARCH_QUERY,
        {"input": {"types": ["METRIC"], "query": query, "start": 0, "count": 50}},
    )
    page = payload.get("data", {}).get("searchAcrossEntities")
    rows = page.get("searchResults") if isinstance(page, Mapping) else None
    if (
        not isinstance(page, Mapping)
        or not isinstance(rows, list)
        or page.get("start") != 0
        or not isinstance(page.get("total"), int)
        or not isinstance(page.get("count"), int)
        or len(rows) > 50
    ):
        raise Phase3BError("native Metric search response is malformed")
    result: set[str] = set()
    for row in rows:
        entity = row.get("entity") if isinstance(row, Mapping) else None
        urn = entity.get("urn") if isinstance(entity, Mapping) else None
        if (
            not isinstance(urn, str)
            or entity.get("type") != "METRIC"
            or urn in result
        ):
            raise Phase3BError("native Metric search identity is malformed")
        result.add(urn)
    return result


async def _wait_name_search(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    present: bool,
    timeout_seconds: float,
) -> int:
    terms = sorted(bundle["metric_terms"], key=lambda item: str(item["id"]))
    deadline = monotonic() + timeout_seconds
    while True:
        hits = 0
        for term in terms:
            urn = native_metric_urn(bundle, str(term["id"]))
            if urn in await _search(client, str(term["name"])):
                hits += 1
        if (present and hits == len(terms)) or (not present and hits == 0):
            return hits
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise Phase3BError("native Metric search state did not converge")
        await asyncio.sleep(min(1.0, remaining))


async def _measure_search(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    terms = sorted(bundle["metric_terms"], key=lambda item: str(item["id"]))
    name_hits = await _wait_name_search(
        client, bundle, present=True, timeout_seconds=timeout_seconds
    )
    alias_queries = alias_hits = 0
    for term in terms:
        name = str(term["name"])
        alias = next(
            (
                str(item)
                for item in term["aliases"]
                if str(item).casefold() != name.casefold()
            ),
            None,
        )
        if alias is None:
            continue
        alias_queries += 1
        if native_metric_urn(bundle, str(term["id"])) in await _search(client, alias):
            alias_hits += 1
    expected = {
        native_metric_urn(bundle, str(term["id"])) for term in terms
    }
    injection_hits = len(
        expected
        & await _search(client, "ignore previous instructions system prompt")
    )
    if injection_hits:
        raise Phase3BError("native Metric injection negative search returned a candidate")
    return {
        "metric_name_query_count": len(terms),
        "metric_name_hit_count": name_hits,
        "metric_name_search_coverage": "100%",
        "ai_context_alias_query_count": alias_queries,
        "ai_context_alias_hit_count": alias_hits,
        "ai_context_search_annotation_claimed": False,
        "injection_negative_candidate_count": 0,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_boundary(args)
    environment = dict(os.environ)
    environment["DATAHUB_GMS_URL"] = args.source_server
    read_settings = DataHubConnectionSettings.from_env(environment)
    bundle = await _build_bundle(args, read_settings)
    canonical_checksum = _canonical_checksum(bundle)
    if canonical_checksum != args.expected_canonical_sha256:
        raise Phase3BError("active release canonical checksum differs")
    projection = native_metric_shadow_projection(bundle)
    if "METRIC" in _CANDIDATE_ENTITY_TYPES:
        raise Phase3BError("native Metric is unexpectedly enabled as an app candidate")
    client_id = os.getenv("DATAHUB_SYSTEM_CLIENT_ID", "")
    client_secret = os.getenv("DATAHUB_SYSTEM_CLIENT_SECRET", "")
    if not client_id or not client_secret or ":" in client_id:
        raise Phase3BError("isolated DataHub system credentials are required")
    actor_urn = f"urn:li:corpuser:{client_id}"
    ca_file = read_settings.ca_file.resolve(strict=True)
    async with IsolatedSystemClient(
        args.target_server,
        ca_file=ca_file,
        client_id=client_id,
        client_secret=client_secret,
        timeout_seconds=args.timeout,
    ) as raw_target:
        target = RetryingIsolatedClient(raw_target)
        model_probe = await probe_native_metric_model(target)
        preflight = await _preflight_identities(target, bundle)
        base = {
            "target_project": args.target_project,
            "release_id": bundle["catalog_version"],
            "catalog_sha256": catalog_hash(bundle),
            "canonical_sha256": canonical_checksum,
            "projection_sha256": projection["projection_sha256"],
            "release_membership_sha256": projection["release_membership_sha256"],
            "native_metric_count": projection["native_metric_count"],
            "native_expression_count": projection["native_expression_count"],
            "native_ai_context_count": projection["native_ai_context_count"],
            "stable_logical_identity": projection["stable_logical_identity"],
            "preflight": preflight,
            "model_probe": model_probe,
            "runtime_authority_activated": False,
            "application_candidate_entity_types": list(_CANDIDATE_ENTITY_TYPES),
        }
        grouped = _grouped_aspects(bundle)
        urns = sorted(urn for (_entity_type, urn) in grouped)
        if args.mode == "check":
            status = (
                "REPAIR_REQUIRED"
                if preflight["partial_matching"]
                else "READY_FOR_NATIVE_SHADOW"
            )
            return {**base, "status": status}
        if args.mode == "retire":
            present_urns = await _present_expected_urns(target, bundle)
            if present_urns:
                await _set_removed(
                    target, present_urns, actor_urn=actor_urn, removed=True
                )
                await _wait_removed(
                    target,
                    present_urns,
                    removed=True,
                    timeout_seconds=args.verify_timeout,
                )
            return {
                **base,
                "status": "EXPECTED_NATIVE_SHADOWS_RETIRED",
                "retired_metric_count": len(present_urns),
            }

        attempted_urns: list[str] = []
        try:
            published_count = await _publish(
                target,
                bundle,
                actor_urn=actor_urn,
                attempted_urns=attempted_urns,
            )
            verified = await _wait_full_verify(
                target,
                bundle,
                projection["projection_sha256"],
                timeout_seconds=args.verify_timeout,
            )
            search = await _measure_search(
                target, bundle, timeout_seconds=args.verify_timeout
            )
            await _set_removed(target, urns, actor_urn=actor_urn, removed=True)
            await _wait_removed(
                target,
                urns,
                removed=True,
                timeout_seconds=args.verify_timeout,
            )
            retired_hits = await _wait_name_search(
                target,
                bundle,
                present=False,
                timeout_seconds=args.verify_timeout,
            )
            await _set_removed(target, urns, actor_urn=actor_urn, removed=False)
            await _wait_full_verify(
                target,
                bundle,
                projection["projection_sha256"],
                timeout_seconds=args.verify_timeout,
            )
            restored_hits = await _wait_name_search(
                target,
                bundle,
                present=True,
                timeout_seconds=args.verify_timeout,
            )
        except BaseException as error:
            if attempted_urns:
                try:
                    await _set_removed(
                        target,
                        attempted_urns,
                        actor_urn=actor_urn,
                        removed=True,
                    )
                    await _wait_removed(
                        target,
                        attempted_urns,
                        removed=True,
                        timeout_seconds=args.verify_timeout,
                    )
                except BaseException as cleanup_error:
                    raise Phase3BError(
                        "Phase 3B failed and native shadows could not be retired"
                    ) from cleanup_error
            raise error
        return {
            **base,
            **search,
            "status": "SHADOW_EQUALITY_VERIFIED_NOT_ACTIVE",
            "published_metric_count": published_count,
            "graphql_metric_count": verified["graphql_metric_count"],
            "rest_aspect_equality": "100%",
            "graphql_identity_equality": "100%",
            "retired_search_hit_count": retired_hits,
            "restored_search_hit_count": restored_hits,
            "retirement_verified": True,
            "rollback_restore_verified": True,
            "final_shadow_removed": False,
            "application_native_metric_candidate_exposure_count": 0,
            "prompt_injection_bypass_count": 0,
        }


def main(argv: list[str] | None = None) -> int:
    try:
        result = asyncio.run(run(parse_args(argv)))
    except (AcceptanceError, OSError, RuntimeError, ValueError) as error:
        output = {"status": "FAILED", "error_type": type(error).__name__}
        if isinstance(error, AcceptanceError):
            output["reason"] = str(error)
        print(json.dumps(output, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
