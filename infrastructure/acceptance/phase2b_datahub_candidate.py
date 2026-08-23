"""Stage and verify one checksum-bound Phase 2B release in isolated DataHub.

The current DataHub and Trino endpoints are read-only sources. Every write is
hard-bound to the isolated ``answervice-phase2b-datahub`` project endpoint.
Credentials are accepted only from the process environment and never returned.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import locale
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DATAHUB))

from http_client import DataHubMetadataAdminClient  # noqa: E402
from metadata_aspects import aspect_counts, iter_aspects  # noqa: E402
from metadata_graphql import SEARCH_QUERY, verify_graphql  # noqa: E402
from metadata_rest import (  # noqa: E402
    aspect_value,
    preflight_owner_entities,
    verify_rest_aspects,
)
from metadata_wire import metadata_change_proposals, validated_audit_stamp  # noqa: E402
from release_builder import build_active_release_bundle  # noqa: E402
from release_datahub import DataHubDiscoveryClient  # noqa: E402
from release_scope import load_release_scopes_with_serving  # noqa: E402
from release_trino import TrinoMetadataClient  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import catalog_hash  # noqa: E402


TARGET_PROJECT = "answervice-phase2b-datahub"
TARGET_PORT = 38081
_PAGE_SIZE = 100
_MAX_SEARCH_TOTAL = 10_000

CREATE_SERVICE_ACCOUNT = """
mutation Phase2BCreateServiceAccount($input: CreateServiceAccountInput!) {
  createServiceAccount(input: $input) { urn }
}
""".strip()

DELETE_SERVICE_ACCOUNT = """
mutation Phase2BDeleteServiceAccount($urn: String!) {
  deleteServiceAccount(urn: $urn)
}
""".strip()

CREATE_ACCESS_TOKEN = """
mutation Phase2BCreateAccessToken($input: CreateAccessTokenInput!) {
  createAccessToken(input: $input) {
    accessToken
    metadata { id actorUrn expiresAt }
  }
}
""".strip()

REVOKE_ACCESS_TOKEN = """
mutation Phase2BRevokeAccessToken($tokenId: String!) {
  revokeAccessToken(tokenId: $tokenId)
}
""".strip()


class AcceptanceError(RuntimeError):
    """The isolated candidate cannot be proved without lowering a gate."""


def _epoch_ms() -> int:
    return time.time_ns() // 1_000_000


def _local_https_origin(value: str, context: str) -> str:
    url = httpx.URL(value)
    if (
        url.scheme != "https"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise AcceptanceError(f"{context} must be an uncredentialed loopback HTTPS origin")
    return str(url).rstrip("/")


def _validate_boundary(args: argparse.Namespace) -> None:
    source = httpx.URL(_local_https_origin(args.source_server, "source server"))
    target = httpx.URL(_local_https_origin(args.target_server, "target server"))
    if args.target_project != TARGET_PROJECT:
        raise AcceptanceError("target project is not the approved isolated project")
    if target.port != TARGET_PORT:
        raise AcceptanceError("target port is not the approved isolated port")
    if source == target:
        raise AcceptanceError("read-only source and isolated mutation target must differ")


def _runtime_environment() -> dict[str, str]:
    environment = dict(os.environ)
    defaults = {
        "DATAHUB_DATASET_ENV": "PROD",
        "PMS_DATAHUB_PLATFORM_INSTANCE": "pms",
        "BANQUET_DATAHUB_PLATFORM_INSTANCE": "banquet",
        "POS_DATAHUB_PLATFORM_INSTANCE": "pos",
        "CRM_DATAHUB_PLATFORM_INSTANCE": "crm",
        "FACILITY_DATAHUB_PLATFORM_INSTANCE": "facility",
        "SERVING_DATAHUB_CATALOG": "serving",
        "SERVING_DATAHUB_PLATFORM_INSTANCE": "serving",
    }
    for name, value in defaults.items():
        environment.setdefault(name, value)
    return environment


class IsolatedSystemClient:
    """Minimal GMS client whose mutation boundary is the approved target port."""

    def __init__(
        self,
        server: str,
        *,
        ca_file: Path,
        client_id: str,
        client_secret: str,
        timeout_seconds: float,
    ) -> None:
        server = _local_https_origin(server, "target server")
        if httpx.URL(server).port != TARGET_PORT:
            raise AcceptanceError("system client refused a non-isolated target")
        if not client_id or not client_secret:
            raise AcceptanceError("isolated DataHub system credentials are required")
        self.server = server
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-RestLi-Protocol-Version": "2.0.0",
            "Authorization": f"Basic {client_id}:{client_secret}",
        }
        self._http = httpx.AsyncClient(
            verify=str(ca_file),
            timeout=httpx.Timeout(timeout_seconds),
            trust_env=False,
        )

    async def _request(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        body: object | None = None,
        expect_json: bool,
    ) -> object | None:
        try:
            response = await self._http.request(
                method,
                url,
                headers=self._headers,
                json=body,
            )
            response.raise_for_status()
            return response.json() if expect_json else None
        except httpx.HTTPStatusError as error:
            raise AcceptanceError(
                f"isolated DataHub request failed with HTTP {error.response.status_code}"
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise AcceptanceError("isolated DataHub request failed") from error

    async def get_entity(self, urn: str, aspects: tuple[str, ...]) -> dict[str, Any]:
        path = f"{self.server}/entitiesV2/{quote(urn, safe='')}"
        url = httpx.URL(path).copy_with(
            query=f"aspects=List({','.join(aspects)})".encode("ascii")
        )
        payload = await self._request("GET", url, expect_json=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("aspects"), dict):
            raise AcceptanceError("isolated DataHub entity response is invalid")
        return payload

    async def graphql(
        self, query: str, variables: Mapping[str, Any]
    ) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            f"{self.server}/api/graphql",
            body={"query": query, "variables": dict(variables)},
            expect_json=True,
        )
        if not isinstance(payload, dict) or payload.get("errors"):
            raise AcceptanceError("isolated DataHub GraphQL response is invalid")
        return payload

    async def upsert_entity(
        self,
        entity_type: str,
        urn: str,
        aspects: Mapping[str, Mapping[str, Any]],
        audit_stamp: Mapping[str, Any],
    ) -> None:
        for proposal in metadata_change_proposals(
            entity_type, urn, aspects, audit_stamp
        ):
            await self._ingest_proposal(proposal)

    async def create_temporary_access_token(
        self, actor_urn: str
    ) -> tuple[str, str]:
        """Create a one-hour isolated token and return it only to process memory."""

        if not actor_urn.startswith("urn:li:corpuser:service_"):
            raise AcceptanceError("temporary token actor is not a service account")
        nonce = _epoch_ms()
        payload = await self.graphql(
            CREATE_ACCESS_TOKEN,
            {
                "input": {
                    "type": "SERVICE_ACCOUNT",
                    "actorUrn": actor_urn,
                    "duration": "ONE_HOUR",
                    "name": f"phase2b-acceptance-{nonce}",
                    "description": "Ephemeral isolated Phase 2B acceptance token.",
                }
            },
        )
        value = payload.get("data", {}).get("createAccessToken")
        metadata = value.get("metadata") if isinstance(value, dict) else None
        token = value.get("accessToken") if isinstance(value, dict) else None
        token_id = metadata.get("id") if isinstance(metadata, dict) else None
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(token_id, str)
            or not token_id
            or metadata.get("actorUrn") != actor_urn
            or not isinstance(metadata.get("expiresAt"), int)
        ):
            raise AcceptanceError("isolated temporary token response is invalid")
        return token, token_id

    async def create_temporary_service_account(self) -> str:
        payload = await self.graphql(
            CREATE_SERVICE_ACCOUNT,
            {
                "input": {
                    "displayName": f"Phase 2B Acceptance {_epoch_ms()}",
                    "description": "Ephemeral isolated Phase 2B acceptance identity.",
                }
            },
        )
        value = payload.get("data", {}).get("createServiceAccount")
        urn = value.get("urn") if isinstance(value, dict) else None
        if not isinstance(urn, str) or not urn.startswith("urn:li:corpuser:"):
            raise AcceptanceError("isolated temporary service account response is invalid")
        return urn

    async def delete_service_account(self, urn: str) -> None:
        if not urn.startswith("urn:li:corpuser:"):
            raise AcceptanceError("temporary service account URN is invalid")
        payload = await self.graphql(DELETE_SERVICE_ACCOUNT, {"urn": urn})
        if payload.get("data", {}).get("deleteServiceAccount") is not True:
            raise AcceptanceError("isolated temporary service account delete failed")

    async def revoke_access_token(self, token_id: str) -> None:
        if not token_id:
            raise AcceptanceError("temporary token id is missing")
        payload = await self.graphql(REVOKE_ACCESS_TOKEN, {"tokenId": token_id})
        if payload.get("data", {}).get("revokeAccessToken") is not True:
            raise AcceptanceError("isolated temporary token revoke failed")

    async def upsert_raw_entity(
        self,
        entity_type: str,
        urn: str,
        aspects: Mapping[str, Mapping[str, Any]],
    ) -> None:
        if entity_type not in {"corpuser", "corpGroup"} or not aspects:
            raise AcceptanceError("identity bootstrap entity is outside the approved scope")
        for name, value in aspects.items():
            proposal = {
                "aspect": {
                    "value": json.dumps(
                        value,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "contentType": "application/json",
                },
                "aspectName": name,
                "entityType": entity_type,
                "entityUrn": urn,
                "changeType": "UPSERT",
            }
            await self._ingest_proposal(proposal)

    async def _ingest_proposal(self, proposal: Mapping[str, Any]) -> None:
        await self._request(
            "POST",
            f"{self.server}/aspects?action=ingestProposal",
            body={"proposal": dict(proposal), "async": "false"},
            expect_json=False,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "IsolatedSystemClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()


async def _build_bundle(
    args: argparse.Namespace,
    read_settings: DataHubConnectionSettings,
) -> dict[str, Any]:
    trino_password = os.getenv("TRINO_DATAHUB_PASSWORD", "")
    trino_user = os.getenv("TRINO_DATAHUB_USER", "")
    trino_ca = Path(args.trino_ca_file).resolve(strict=True)
    if not trino_user or not trino_password:
        raise AcceptanceError("read-only Trino metadata credentials are required")
    recipes = tuple(sorted(args.recipe_dir.resolve().glob("*.runtime.yml")))
    scopes = load_release_scopes_with_serving(
        recipes,
        _runtime_environment(),
        args.serving_schema,
    )
    async with (
        TrinoMetadataClient(
            args.trino_server,
            trino_user,
            trino_password,
            ca_file=trino_ca,
            timeout_seconds=args.timeout,
        ) as trino,
        DataHubDiscoveryClient(
            read_settings.base_url,
            token=read_settings.token,
            ca_file=read_settings.ca_file,
            timeout_seconds=args.timeout,
        ) as source,
    ):
        bundle = await build_active_release_bundle(scopes, trino, source)
    if bundle.get("catalog_version") != args.expected_release:
        raise AcceptanceError("active release identity differs from the approved candidate")
    if catalog_hash(bundle) != args.expected_catalog_sha256:
        raise AcceptanceError("active release checksum differs from the approved candidate")
    return bundle


async def _search_urns(
    client: IsolatedSystemClient,
    entity_type: str,
) -> set[str]:
    start, total = 0, None
    urns: set[str] = set()
    while total is None or start < total:
        payload = await client.graphql(
            SEARCH_QUERY,
            {
                "input": {
                    "types": [entity_type],
                    "query": "*",
                    "start": start,
                    "count": _PAGE_SIZE,
                }
            },
        )
        page = payload.get("data", {}).get("searchAcrossEntities")
        rows = page.get("searchResults") if isinstance(page, dict) else None
        observed_total = page.get("total") if isinstance(page, dict) else None
        if (
            not isinstance(rows, list)
            or not isinstance(observed_total, int)
            or observed_total < 0
            or observed_total > _MAX_SEARCH_TOTAL
            or page.get("start") != start
        ):
            raise AcceptanceError("isolated DataHub search pagination is invalid")
        if total is None:
            total = observed_total
        elif total != observed_total:
            raise AcceptanceError("isolated DataHub search total changed during preflight")
        for row in rows:
            entity = row.get("entity") if isinstance(row, dict) else None
            urn = entity.get("urn") if isinstance(entity, dict) else None
            if (
                not isinstance(urn, str)
                or entity.get("type") != entity_type
                or urn in urns
            ):
                raise AcceptanceError("isolated DataHub search identity is invalid")
            urns.add(urn)
        if not rows:
            break
        start += len(rows)
    if total is None or len(urns) != total:
        raise AcceptanceError("isolated DataHub search coverage is incomplete")
    return urns


async def _target_scope(
    client: IsolatedSystemClient,
    bundle: Mapping[str, Any],
    *,
    require_complete: bool,
) -> tuple[set[str], set[str]]:
    expected_datasets = {
        str(asset["urn"]) for asset in bundle["schema_context"]["assets"]
    }
    expected_terms = {str(term["urn"]) for term in bundle["metric_terms"]}
    datasets = await _search_urns(client, "DATASET")
    terms = await _search_urns(client, "GLOSSARY_TERM")
    if datasets - expected_datasets or terms - expected_terms:
        raise AcceptanceError("isolated target contains entities outside the candidate release")
    if require_complete and (datasets != expected_datasets or terms != expected_terms):
        raise AcceptanceError("isolated target does not contain the complete candidate release")
    return datasets, terms


async def _clone_identity(
    source: DataHubMetadataAdminClient,
    target: IsolatedSystemClient,
    *,
    urn: str,
    entity_type: str,
    key_aspect: str,
    info_aspect: str,
) -> None:
    entity = await source.get_entity(urn, (key_aspect, info_aspect, "status"))
    available = entity["aspects"]
    aspects = {
        name: value["value"]
        for name, value in available.items()
        if name in {key_aspect, info_aspect, "status"}
        and isinstance(value, dict)
        and isinstance(value.get("value"), dict)
    }
    if key_aspect not in aspects or info_aspect not in aspects:
        raise AcceptanceError("source service or owner identity is incomplete")
    if aspects.get("status", {}).get("removed") is True:
        raise AcceptanceError("source service or owner identity is removed")
    await target.upsert_raw_entity(entity_type, urn, aspects)


async def _source_schemas(
    source: DataHubMetadataAdminClient,
    bundle: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    semaphore = asyncio.Semaphore(8)

    async def one(urn: str) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            entity = await source.get_entity(urn, ("schemaMetadata",))
        return urn, aspect_value(entity, "schemaMetadata")

    return dict(
        await asyncio.gather(
            *(one(str(asset["urn"])) for asset in bundle["schema_context"]["assets"])
        )
    )


async def _probe_bearer(
    server: str,
    ca_file: Path,
    token: str,
    timeout: float,
) -> bool:
    async with httpx.AsyncClient(
        verify=str(ca_file), timeout=timeout, trust_env=False
    ) as client:
        response = await client.post(
            f"{server}/api/graphql",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "query { __typename }"},
        )
    return response.status_code == 200


async def _verify_with_freshness(
    client: IsolatedSystemClient,
    bundle: Mapping[str, Any],
    *,
    timeout_seconds: float,
) -> int:
    await preflight_owner_entities(client, bundle)
    await verify_rest_aspects(client, bundle)
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            await verify_graphql(client, bundle)
            return _epoch_ms()
        except (AcceptanceError, ValueError) as error:
            last_error = error
            await asyncio.sleep(1)
    raise AcceptanceError("isolated search index did not reach exact release coverage") from last_error


async def _stage(
    args: argparse.Namespace,
    bundle: dict[str, Any],
    read_settings: DataHubConnectionSettings,
    target: IsolatedSystemClient,
) -> dict[str, Any]:
    before_datasets, before_terms = await _target_scope(
        target, bundle, require_complete=False
    )
    published_at = _epoch_ms()
    publish_actor = os.getenv("DATAHUB_PUBLISH_ACTOR_URN", "")
    read_actor = os.getenv("DATAHUB_READ_ACTOR_URN", "")
    if not publish_actor.startswith("urn:li:corpuser:service_") or not read_actor.startswith(
        "urn:li:corpuser:service_"
    ):
        raise AcceptanceError("DataHub service actor identities are invalid")
    audit = validated_audit_stamp({"actor": publish_actor, "time": published_at})
    async with DataHubMetadataAdminClient(
        read_settings.base_url,
        token=read_settings.token,
        ca_file=read_settings.ca_file,
        timeout_seconds=args.timeout,
    ) as source:
        for actor in sorted({publish_actor, read_actor}):
            await _clone_identity(
                source,
                target,
                urn=actor,
                entity_type="corpuser",
                key_aspect="corpUserKey",
                info_aspect="corpUserInfo",
            )
        for owner in bundle["governance_entities"]["owners"]:
            await _clone_identity(
                source,
                target,
                urn=str(owner["urn"]),
                entity_type="corpGroup",
                key_aspect="corpGroupKey",
                info_aspect="corpGroupInfo",
            )
        schemas = await _source_schemas(source, bundle)
    for asset in bundle["schema_context"]["assets"]:
        urn = str(asset["urn"])
        await target.upsert_entity(
            "dataset",
            urn,
            {
                "datasetKey": dict(asset["dataset_key"]),
                "schemaMetadata": schemas[urn],
            },
            audit,
        )
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for entity_type, urn, name, value in iter_aspects(bundle):
        grouped.setdefault((entity_type, urn), {})[name] = value
    for (entity_type, urn), aspects in grouped.items():
        await target.upsert_entity(entity_type, urn, aspects, audit)
    verified_at = await _verify_with_freshness(
        target, bundle, timeout_seconds=args.verify_timeout
    )
    temporary_account = await target.create_temporary_service_account()
    temporary_token_id: str | None = None
    cleanup_errors: list[AcceptanceError] = []
    try:
        temporary_token, temporary_token_id = await target.create_temporary_access_token(
            temporary_account
        )
        if not await _probe_bearer(
            args.target_server,
            read_settings.ca_file,
            temporary_token,
            args.timeout,
        ):
            raise AcceptanceError("isolated temporary read token did not authenticate")
    finally:
        if temporary_token_id is not None:
            try:
                await target.revoke_access_token(temporary_token_id)
            except AcceptanceError as error:
                cleanup_errors.append(error)
        try:
            await target.delete_service_account(temporary_account)
        except AcceptanceError as error:
            cleanup_errors.append(error)
    if cleanup_errors:
        raise cleanup_errors[0]
    await _target_scope(target, bundle, require_complete=True)
    return {
        "status": "STAGED_AND_VERIFIED",
        "target_project": args.target_project,
        "release_id": bundle["catalog_version"],
        "catalog_sha256": catalog_hash(bundle),
        **aspect_counts(bundle),
        "preexisting_candidate_datasets": len(before_datasets),
        "preexisting_candidate_terms": len(before_terms),
        "published_at_epoch_ms": published_at,
        "verified_at_epoch_ms": verified_at,
        "freshness_latency_ms": verified_at - published_at,
        "dataset_search_coverage": "100%",
        "glossary_search_coverage": "100%",
        "temporary_read_token_authenticated": True,
        "temporary_read_token_revoked": True,
        "temporary_service_account_deleted": True,
    }


def _retrieval_measurement_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in (
        "catalog_exact_self_consistency",
        "definition_overlap_retrieval",
        "natural_language_paraphrase",
        "negative_closure",
    ):
        measurement = value.get(name)
        if not isinstance(measurement, Mapping):
            continue
        result[name] = {
            key: measurement[key]
            for key in (
                "top1_accuracy",
                "recall_at_k",
                "mean_reciprocal_rank",
                "closure_rate",
                "contamination_rate",
                "retrieval_error_count",
                "infrastructure_error_count",
            )
            if key in measurement
        }
    return result


def _runner_result(stdout: bytes) -> dict[str, Any]:
    """Select one bounded machine-readable result without emitting runtime logs."""

    if len(stdout) > 5_000_000:
        raise AcceptanceError("isolated retrieval output exceeded its bound")
    for encoding in dict.fromkeys(("utf-8", locale.getpreferredencoding(False))):
        try:
            lines = stdout.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
        for line in reversed(lines):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    raise AcceptanceError("isolated retrieval output has no result object")


async def _run_canary(
    args: argparse.Namespace,
    bundle: Mapping[str, Any],
    target: IsolatedSystemClient,
    ca_file: Path,
) -> dict[str, Any]:
    """Run the canonical sealed evaluator with an environment-only token."""

    await _target_scope(target, bundle, require_complete=True)
    account = await target.create_temporary_service_account()
    token_id: str | None = None
    cleanup_errors: list[AcceptanceError] = []
    try:
        token, token_id = await target.create_temporary_access_token(account)
        environment = dict(os.environ)
        environment.update(
            {
                "DATAHUB_GMS_URL": args.target_server,
                "DATAHUB_READ_API_TOKEN": token,
                "DATAHUB_READ_ACTOR_URN": account,
                "DATAHUB_TLS_CA_FILE": str(ca_file),
            }
        )
        command = (
            sys.executable,
            str(ROOT / "evals" / "metric_retrieval_runner.py"),
            "--role",
            "analyst",
            "--expected-context-release",
            args.expected_release,
            "--search-mode",
            "datahub_lexical",
            "--phase2a-gold-manifest",
            str(args.gold_manifest.resolve()),
            "--candidate-search-count",
            "20",
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(ROOT),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(), timeout=args.canary_timeout
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise AcceptanceError("isolated retrieval canary exceeded its timeout") from error
        if process.returncode != 0:
            raise AcceptanceError("isolated retrieval canary did not pass")
        result = _runner_result(stdout)
        if (
            not isinstance(result, dict)
            or result.get("status") != "PASSED"
            or result.get("context_release") != args.expected_release
            or result.get("catalog_checksum") != args.expected_catalog_sha256
            or not isinstance(result.get("checks"), dict)
            or not all(result["checks"].values())
        ):
            raise AcceptanceError("isolated retrieval canary Gate failed")
    finally:
        if token_id is not None:
            try:
                await target.revoke_access_token(token_id)
            except AcceptanceError as error:
                cleanup_errors.append(error)
        try:
            await target.delete_service_account(account)
        except AcceptanceError as error:
            cleanup_errors.append(error)
    if cleanup_errors:
        raise cleanup_errors[0]
    measurements = result["measurements"]
    latency = result["warm_candidate_latency_ms"]
    return {
        "status": "CANARY_PASSED",
        "target_project": args.target_project,
        "release_id": result["context_release"],
        "catalog_sha256": result["catalog_checksum"],
        "canonical_sha256": result["canonical_checksum"],
        "gold_manifest": result["gold_manifest"],
        "checks": result["checks"],
        "production_diff_count": result["production_diff_count"],
        "unauthorized_exposure_count": result["unauthorized_exposure_count"],
        "candidate_infrastructure_error_count": result[
            "candidate_infrastructure_error_count"
        ],
        "candidate_search_count": result["candidate_search_count"],
        "measurements": {
            mode: _retrieval_measurement_summary(value)
            for mode, value in measurements.items()
        },
        "warm_candidate_latency_ms": latency,
        "temporary_read_token_revoked": True,
        "temporary_service_account_deleted": True,
    }


async def _run_rollback(
    args: argparse.Namespace,
    bundle: Mapping[str, Any],
    target: IsolatedSystemClient,
    ca_file: Path,
) -> dict[str, Any]:
    """Rehearse the explicit lexical mode against the same isolated release."""

    await _target_scope(target, bundle, require_complete=True)
    account = await target.create_temporary_service_account()
    token_id: str | None = None
    cleanup_errors: list[AcceptanceError] = []
    try:
        token, token_id = await target.create_temporary_access_token(account)
        environment = dict(os.environ)
        environment.update(
            {
                "DATAHUB_GMS_URL": args.target_server,
                "DATAHUB_READ_API_TOKEN": token,
                "DATAHUB_READ_ACTOR_URN": account,
                "DATAHUB_TLS_CA_FILE": str(ca_file),
                "DATAHUB_SEARCH_MODE": "lexical",
            }
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(ROOT / "evals" / "metric_retrieval_runner.py"),
            "--role",
            "analyst",
            "--expected-context-release",
            args.expected_release,
            "--search-mode",
            "lexical",
            cwd=str(ROOT),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(), timeout=args.canary_timeout
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise AcceptanceError("isolated lexical rollback exceeded its timeout") from error
        if process.returncode != 0:
            raise AcceptanceError("isolated lexical rollback did not pass")
        result = _runner_result(stdout)
        if (
            not isinstance(result, dict)
            or result.get("status") != "PASSED"
            or result.get("search_mode") != "lexical"
            or result.get("context_release") != args.expected_release
            or result.get("catalog_checksum") != args.expected_catalog_sha256
            or result.get("planned_datahub_request_count") != 0
        ):
            raise AcceptanceError("isolated lexical rollback Gate failed")
    finally:
        if token_id is not None:
            try:
                await target.revoke_access_token(token_id)
            except AcceptanceError as error:
                cleanup_errors.append(error)
        try:
            await target.delete_service_account(account)
        except AcceptanceError as error:
            cleanup_errors.append(error)
    if cleanup_errors:
        raise cleanup_errors[0]
    return {
        "status": "ROLLBACK_PASSED",
        "target_project": args.target_project,
        "release_id": result["context_release"],
        "catalog_sha256": result["catalog_checksum"],
        "canonical_sha256": result["canonical_checksum"],
        "search_mode": result["search_mode"],
        "planned_datahub_request_count": result["planned_datahub_request_count"],
        "measurements": _retrieval_measurement_summary(result),
        "warm_candidate_latency_ms": result["warm_candidate_latency_ms"],
        "temporary_read_token_revoked": True,
        "temporary_service_account_deleted": True,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_boundary(args)
    environment = dict(os.environ)
    environment["DATAHUB_GMS_URL"] = args.source_server
    read_settings = DataHubConnectionSettings.from_env(environment)
    bundle = await _build_bundle(args, read_settings)
    ca_file = read_settings.ca_file
    async with IsolatedSystemClient(
        args.target_server,
        ca_file=ca_file,
        client_id=os.getenv("DATAHUB_SYSTEM_CLIENT_ID", ""),
        client_secret=os.getenv("DATAHUB_SYSTEM_CLIENT_SECRET", ""),
        timeout_seconds=args.timeout,
    ) as target:
        if args.mode == "check":
            datasets, terms = await _target_scope(
                target, bundle, require_complete=False
            )
            return {
                "status": "READY_TO_STAGE",
                "target_project": args.target_project,
                "release_id": bundle["catalog_version"],
                "catalog_sha256": catalog_hash(bundle),
                **aspect_counts(bundle),
                "candidate_datasets_present": len(datasets),
                "candidate_terms_present": len(terms),
            }
        if args.mode == "stage":
            return await _stage(args, bundle, read_settings, target)
        if args.mode == "canary":
            return await _run_canary(
                args, bundle, target, read_settings.ca_file
            )
        if args.mode == "rollback":
            return await _run_rollback(
                args, bundle, target, read_settings.ca_file
            )
        verified_at = await _verify_with_freshness(
            target, bundle, timeout_seconds=args.verify_timeout
        )
        await _target_scope(target, bundle, require_complete=True)
        return {
            "status": "VERIFIED",
            "target_project": args.target_project,
            "release_id": bundle["catalog_version"],
            "catalog_sha256": catalog_hash(bundle),
            **aspect_counts(bundle),
            "verified_at_epoch_ms": verified_at,
            "dataset_search_coverage": "100%",
            "glossary_search_coverage": "100%",
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("check", "stage", "verify", "canary", "rollback"),
        required=True,
    )
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--source-server", required=True)
    parser.add_argument("--target-server", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--expected-catalog-sha256", required=True)
    parser.add_argument("--serving-schema", required=True)
    parser.add_argument(
        "--recipe-dir", type=Path, default=DATAHUB / "recipes"
    )
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
    parser.add_argument(
        "--gold-manifest",
        type=Path,
        default=ROOT
        / "evals"
        / "metric_retrieval_gold"
        / "answervice_ko_retrieval.v1.json",
    )
    parser.add_argument("--canary-timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    if (
        args.trino_ca_file is None
        or args.timeout <= 0
        or args.verify_timeout <= 0
        or args.canary_timeout <= 0
    ):
        parser.error("Trino CA file and positive timeouts are required")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        result = asyncio.run(run(parse_args(argv)))
    except (AcceptanceError, OSError, RuntimeError, ValueError) as error:
        output = {"status": "FAILED", "error_type": type(error).__name__}
        if isinstance(error, AcceptanceError):
            # AcceptanceError messages are deliberately bounded, secret-free codes.
            output["reason"] = str(error)
        print(
            json.dumps(output, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
