#!/usr/bin/env python3
"""Start or clean up the exact isolated Phase 10 candidate services.

The ephemeral DataHub token remains only in process/container memory.  The
lease file contains the revocable token ID and service-account URN, never the
token value or system credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Mapping

import httpx
import psycopg
from dotenv import dotenv_values
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
HERE = Path(__file__).resolve().parent
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.capability_contracts import ProductReleaseEvidenceManifest  # noqa: E402
from phase10_candidate_release import (  # noqa: E402
    PHASE10_PREFIX,
    TARGET_DATABASE,
    _source_receipt,
)
from phase2b_datahub_candidate import (  # noqa: E402
    AcceptanceError,
    IsolatedSystemClient,
)
from src.data.governance_contract import canonical_sha256  # noqa: E402


TARGET_PROJECT = "answervice-phase2b-datahub"
TARGET_SERVER = "https://127.0.0.1:38081"
TARGET_NETWORK = "answervice-phase2b-datahub_datahub-network"
TARGET_DB_HOST = "127.0.0.1"
TARGET_DB_PORT = 55440
TARGET_DB_USER = "phase10_runtime"
COMPOSE_FILE = ROOT / "infrastructure" / "acceptance" / "phase10-candidate.compose.yml"
ENV_FILE = ROOT / "infrastructure" / "database" / ".env"
LEASE_FILE = ROOT / ".tmp" / "phase10-candidate-services.json"
BACKEND_IMAGE = "answervice-phase10-backend:candidate"
FRONTEND_IMAGE = "answervice-phase10-frontend:candidate"
CONTAINERS = (
    "answervice-phase2b-datahub-phase10-backend",
    "answervice-phase2b-datahub-phase10-frontend",
)
PORTS = (48000, 43000)
SCOPE_LABEL = "phase10-same-release-candidate"
LEASE_VERSION = "answervice.phase10_candidate_service_lease.v1"


class Phase10CandidateServiceError(RuntimeError):
    """Candidate services cannot be changed inside the approved boundary."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--target-project", required=True)
    start.add_argument("--target-server", required=True)
    start.add_argument("--env-file", type=Path, required=True)
    start.add_argument("--timeout", type=float, default=180.0)
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--target-project", required=True)
    cleanup.add_argument("--target-server", required=True)
    cleanup.add_argument("--env-file", type=Path, required=True)
    cleanup.add_argument("--timeout", type=float, default=60.0)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--target-project", required=True)
    verify.add_argument("--target-server", required=True)
    verify.add_argument("--env-file", type=Path, required=True)
    verify.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def validate_boundary(args: argparse.Namespace) -> None:
    if args.target_project != TARGET_PROJECT:
        raise Phase10CandidateServiceError(
            "Phase 10 target project is outside the approved boundary"
        )
    endpoint = httpx.URL(args.target_server)
    if (
        args.target_server.rstrip("/") != TARGET_SERVER
        or endpoint.scheme != "https"
        or endpoint.host not in {"127.0.0.1", "localhost", "::1"}
        or endpoint.port != 38081
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
        or endpoint.path not in {"", "/"}
    ):
        raise Phase10CandidateServiceError(
            "Phase 10 DataHub endpoint is outside the isolated boundary"
        )
    try:
        env_file = args.env_file.resolve(strict=True)
    except OSError as error:
        raise Phase10CandidateServiceError(
            "Phase 10 environment file is unavailable"
        ) from error
    if env_file != ENV_FILE.resolve(strict=True) or not env_file.is_file():
        raise Phase10CandidateServiceError(
            "Phase 10 environment file differs from the sealed boundary"
        )
    if args.timeout <= 0 or args.timeout > 300:
        raise Phase10CandidateServiceError("Phase 10 timeout is outside the bound")


def _environment(path: Path) -> dict[str, str]:
    values = {
        str(key): str(value)
        for key, value in dotenv_values(path).items()
        if value is not None
    }
    required = (
        "DATAHUB_SYSTEM_CLIENT_ID",
        "DATAHUB_SYSTEM_CLIENT_SECRET",
        "DATAHUB_TLS_CA_HOST_FILE",
    )
    if any(not values.get(name, "").strip() for name in required):
        raise Phase10CandidateServiceError(
            "Phase 10 isolated DataHub credentials are incomplete"
        )
    ca_file = Path(values["DATAHUB_TLS_CA_HOST_FILE"])
    try:
        resolved = ca_file.resolve(strict=True)
    except OSError as error:
        raise Phase10CandidateServiceError(
            "Phase 10 DataHub CA is unavailable"
        ) from error
    if not ca_file.is_absolute() or not resolved.is_file():
        raise Phase10CandidateServiceError(
            "Phase 10 DataHub CA is outside the explicit boundary"
        )
    values["PHASE10_DATAHUB_CA_FILE"] = str(resolved)
    return values


def _docker(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        ["docker", *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    if check and process.returncode != 0:
        raise Phase10CandidateServiceError("isolated Docker operation failed")
    return process


def _container_identity(name: str) -> tuple[str, str, str] | None:
    process = _docker(
        [
            "inspect",
            name,
            "--format",
            "{{index .Config.Labels \"com.docker.compose.project\"}}|"
            "{{index .Config.Labels \"io.answervice.scope\"}}|"
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
        ],
        check=False,
    )
    if process.returncode != 0:
        return None
    parts = process.stdout.strip().split("|")
    if len(parts) != 3:
        raise Phase10CandidateServiceError("candidate container identity is invalid")
    return parts[0], parts[1], parts[2]


def _container_image_id(name: str) -> str | None:
    process = _docker(
        ["inspect", name, "--format", "{{.Image}}"],
        check=False,
    )
    if process.returncode != 0:
        return None
    image_id = process.stdout.strip()
    if not image_id.startswith("sha256:"):
        raise Phase10CandidateServiceError("candidate container image identity is invalid")
    return image_id


def _image_identity(name: str) -> tuple[str, str, str, str, str]:
    process = _docker(
        [
            "image",
            "inspect",
            name,
            "--format",
            "{{.Id}}|{{index .Config.Labels \"io.answervice.component\"}}|"
            "{{index .Config.Labels \"io.answervice.source.commit-sha\"}}|"
            "{{index .Config.Labels \"io.answervice.source.dirty\"}}|"
            "{{index .Config.Labels \"io.answervice.source.patch-sha256\"}}",
        ]
    )
    parts = process.stdout.strip().split("|")
    if len(parts) != 5:
        raise Phase10CandidateServiceError("candidate image identity is invalid")
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def _assert_ports_free() -> None:
    sockets: list[socket.socket] = []
    try:
        for port in PORTS:
            handle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                handle.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            handle.bind(("127.0.0.1", port))
            sockets.append(handle)
    except OSError as error:
        raise Phase10CandidateServiceError(
            "Phase 10 candidate port is already in use"
        ) from error
    finally:
        for handle in sockets:
            handle.close()


def _preflight() -> ProductReleaseEvidenceManifest:
    if LEASE_FILE.exists():
        raise Phase10CandidateServiceError(
            "Phase 10 candidate lease already exists"
        )
    if any(_container_identity(name) is not None for name in CONTAINERS):
        raise Phase10CandidateServiceError(
            "Phase 10 candidate container already exists"
        )
    _assert_ports_free()
    network = _docker(
        [
            "network",
            "inspect",
            TARGET_NETWORK,
            "--format",
            "{{index .Labels \"com.docker.compose.project\"}}",
        ]
    ).stdout.strip()
    if network != TARGET_PROJECT:
        raise Phase10CandidateServiceError(
            "Phase 10 target network identity differs"
        )

    source, _created_at = _source_receipt()
    images = {
        "backend": _image_identity(BACKEND_IMAGE),
        "frontend": _image_identity(FRONTEND_IMAGE),
    }
    for component, identity in images.items():
        expected = (
            f"phase10-{component}",
            source.commit_sha,
            str(source.dirty).lower(),
            source.dirty_patch_sha256 or "",
        )
        if identity[1:] != expected:
            raise Phase10CandidateServiceError(
                f"Phase 10 {component} image source provenance differs"
            )

    try:
        with psycopg.connect(
            host=TARGET_DB_HOST,
            port=TARGET_DB_PORT,
            dbname=TARGET_DATABASE,
            user=TARGET_DB_USER,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT m.manifest_json
                FROM governance.runtime_catalog_active_pointer a
                JOIN governance.product_release_manifests m
                  ON m.product_release_id = a.product_release_id
                WHERE a.pointer_name = 'analysis'
                """
            ).fetchone()
    except psycopg.Error as error:
        raise Phase10CandidateServiceError(
            "Phase 10 active candidate manifest could not be read"
        ) from error
    if row is None:
        raise Phase10CandidateServiceError(
            "Phase 10 active candidate manifest is unavailable"
        )
    try:
        manifest = ProductReleaseEvidenceManifest.model_validate(row["manifest_json"])
    except (KeyError, TypeError, ValueError) as error:
        raise Phase10CandidateServiceError(
            "Phase 10 active candidate manifest is invalid"
        ) from error
    image_map = {
        image.component: image.digest for image in manifest.evidence.images
    }
    if (
        not manifest.product_release_id.startswith(PHASE10_PREFIX)
        or manifest.evidence.source != source
        or image_map.get("backend") != images["backend"][0]
        or image_map.get("frontend") != images["frontend"][0]
    ):
        raise Phase10CandidateServiceError(
            "Phase 10 active candidate does not bind the current source/images"
        )
    return manifest


def _seal_lease(actor_urn: str, token_id: str, product_release_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": LEASE_VERSION,
        "target_project": TARGET_PROJECT,
        "target_server": TARGET_SERVER,
        "actor_urn": actor_urn,
        "token_id": token_id,
        "product_release_id": product_release_id,
        "containers": list(CONTAINERS),
    }
    payload["lease_sha256"] = canonical_sha256(payload)
    return payload


def validate_lease(document: Mapping[str, Any]) -> None:
    checksum = document.get("lease_sha256")
    payload = {key: value for key, value in document.items() if key != "lease_sha256"}
    if (
        document.get("schema_version") != LEASE_VERSION
        or document.get("target_project") != TARGET_PROJECT
        or document.get("target_server") != TARGET_SERVER
        or document.get("containers") != list(CONTAINERS)
        or not isinstance(document.get("actor_urn"), str)
        or not str(document["actor_urn"]).startswith("urn:li:corpuser:service_")
        or not isinstance(document.get("token_id"), str)
        or not document["token_id"]
        or not isinstance(document.get("product_release_id"), str)
        or not str(document["product_release_id"]).startswith(PHASE10_PREFIX)
        or not isinstance(checksum, str)
        or checksum != canonical_sha256(payload)
    ):
        raise Phase10CandidateServiceError("Phase 10 candidate lease is invalid")


def _write_lease(document: Mapping[str, Any]) -> None:
    LEASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        LEASE_FILE,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except BaseException:
        LEASE_FILE.unlink(missing_ok=True)
        raise


def _read_lease() -> dict[str, Any]:
    try:
        document = json.loads(LEASE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Phase10CandidateServiceError(
            "Phase 10 candidate lease is unavailable"
        ) from error
    if not isinstance(document, dict):
        raise Phase10CandidateServiceError("Phase 10 candidate lease is invalid")
    validate_lease(document)
    return document


def _active_manifest() -> tuple[ProductReleaseEvidenceManifest, int]:
    try:
        with psycopg.connect(
            host=TARGET_DB_HOST,
            port=TARGET_DB_PORT,
            dbname=TARGET_DATABASE,
            user=TARGET_DB_USER,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT a.generation, m.manifest_json
                FROM governance.runtime_catalog_active_pointer a
                JOIN governance.product_release_manifests m
                  ON m.product_release_id = a.product_release_id
                WHERE a.pointer_name = 'analysis'
                """
            ).fetchone()
    except psycopg.Error as error:
        raise Phase10CandidateServiceError(
            "Phase 10 active candidate manifest could not be read"
        ) from error
    if row is None:
        raise Phase10CandidateServiceError(
            "Phase 10 active candidate manifest is unavailable"
        )
    try:
        manifest = ProductReleaseEvidenceManifest.model_validate(row["manifest_json"])
    except (KeyError, TypeError, ValueError) as error:
        raise Phase10CandidateServiceError(
            "Phase 10 active candidate manifest is invalid"
        ) from error
    return manifest, int(row["generation"])


async def inspect_candidate_services(args: argparse.Namespace) -> dict[str, Any]:
    """Re-read exact running container, image, HTTP, lease, and release identities."""

    lease = _read_lease()
    source, _created_at = _source_receipt()
    manifest, generation = _active_manifest()
    image_receipts = {
        image.component: image.digest for image in manifest.evidence.images
    }
    expected_images = {
        CONTAINERS[0]: _image_identity(BACKEND_IMAGE)[0],
        CONTAINERS[1]: _image_identity(FRONTEND_IMAGE)[0],
    }
    observed: dict[str, dict[str, str]] = {}
    for name in CONTAINERS:
        identity = _container_identity(name)
        image_id = _container_image_id(name)
        if (
            identity is None
            or image_id is None
            or identity != (TARGET_PROJECT, SCOPE_LABEL, "healthy")
            or image_id != expected_images[name]
        ):
            raise Phase10CandidateServiceError(
                "Phase 10 running candidate identity differs"
            )
        observed[name] = {"health": identity[2], "image_id": image_id}
    if (
        lease["product_release_id"] != manifest.product_release_id
        or not manifest.product_release_id.startswith(PHASE10_PREFIX)
        or manifest.evidence.source != source
        or image_receipts.get("backend") != expected_images[CONTAINERS[0]]
        or image_receipts.get("frontend") != expected_images[CONTAINERS[1]]
    ):
        raise Phase10CandidateServiceError(
            "Phase 10 running candidate release binding differs"
        )
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=args.timeout) as client:
            backend = await client.get("http://127.0.0.1:48000/readiness")
            frontend = await client.get("http://127.0.0.1:43000/")
        backend.raise_for_status()
        frontend.raise_for_status()
        payload = backend.json()
    except (httpx.HTTPError, ValueError) as error:
        raise Phase10CandidateServiceError(
            "Phase 10 candidate HTTP readiness failed"
        ) from error
    data = payload.get("data") if isinstance(payload, dict) else None
    dependencies = data.get("dependencies") if isinstance(data, dict) else None
    if (
        data is None
        or data.get("status") != "ready"
        or not isinstance(dependencies, dict)
        or not dependencies
        or any(value not in {"ready", "not_required"} for value in dependencies.values())
        or "ANSWERVICE" not in frontend.text
    ):
        raise Phase10CandidateServiceError(
            "Phase 10 candidate readiness contract differs"
        )
    receipt = {
        "verified": True,
        "target_project": TARGET_PROJECT,
        "product_release_id": manifest.product_release_id,
        "active_generation": generation,
        "source_sha256": canonical_sha256(source.model_dump(mode="json")),
        "containers": observed,
        "backend_dependency_count": len(dependencies),
        "frontend_http_status": frontend.status_code,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def _compose_up(token: str, actor_urn: str) -> None:
    source, _created_at = _source_receipt()
    environment = os.environ.copy()
    environment.update(
        {
            "PHASE10_DATAHUB_READ_API_TOKEN": token,
            "PHASE10_DATAHUB_READ_ACTOR_URN": actor_urn,
            "PHASE10_SOURCE_COMMIT_SHA": source.commit_sha,
            "PHASE10_SOURCE_DIRTY": str(source.dirty).lower(),
            "PHASE10_SOURCE_PATCH_SHA256": source.dirty_patch_sha256 or "",
        }
    )
    process = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            TARGET_PROJECT,
            "--env-file",
            str(ENV_FILE),
            "-f",
            str(COMPOSE_FILE),
            "up",
            "-d",
            "--no-build",
            "phase10-backend",
            "phase10-frontend",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )
    if process.returncode != 0:
        raise Phase10CandidateServiceError(
            "Phase 10 candidate Compose start failed"
        )


def _wait_healthy(timeout: float) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        identities = [_container_identity(name) for name in CONTAINERS]
        if all(identity is not None for identity in identities):
            if any(
                identity[0] != TARGET_PROJECT or identity[1] != SCOPE_LABEL
                for identity in identities
                if identity is not None
            ):
                raise Phase10CandidateServiceError(
                    "Phase 10 candidate container identity differs"
                )
            if all(identity[2] == "healthy" for identity in identities if identity):
                return
            if any(identity[2] == "unhealthy" for identity in identities if identity):
                raise Phase10CandidateServiceError(
                    "Phase 10 candidate container became unhealthy"
                )
        sleep(2)
    raise Phase10CandidateServiceError(
        "Phase 10 candidate health timeout expired"
    )


def _remove_containers() -> int:
    existing: list[str] = []
    for name in CONTAINERS:
        identity = _container_identity(name)
        if identity is None:
            continue
        if identity[0] != TARGET_PROJECT or identity[1] != SCOPE_LABEL:
            raise Phase10CandidateServiceError(
                "candidate cleanup target identity differs"
            )
        existing.append(name)
    if existing:
        _docker(["rm", "--force", *existing])
    return len(existing)


async def start(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _preflight()
    values = _environment(args.env_file)
    actor_urn: str | None = None
    token_id: str | None = None
    lease_written = False
    try:
        async with IsolatedSystemClient(
            args.target_server,
            ca_file=Path(values["PHASE10_DATAHUB_CA_FILE"]),
            client_id=values["DATAHUB_SYSTEM_CLIENT_ID"],
            client_secret=values["DATAHUB_SYSTEM_CLIENT_SECRET"],
            timeout_seconds=min(args.timeout, 60.0),
        ) as client:
            actor_urn = await client.create_temporary_service_account()
            token, token_id = await client.create_temporary_access_token(actor_urn)
            lease = _seal_lease(
                actor_urn,
                token_id,
                manifest.product_release_id,
            )
            _write_lease(lease)
            lease_written = True
            _compose_up(token, actor_urn)
            _wait_healthy(args.timeout)
        return {
            "status": "PHASE10_CANDIDATE_SERVICES_READY",
            "target_project": TARGET_PROJECT,
            "product_release_id": manifest.product_release_id,
            "containers": list(CONTAINERS),
            "ports": list(PORTS),
            "temporary_identity_recorded": True,
            "token_secret_recorded": False,
        }
    except BaseException:
        _remove_containers()
        identity_cleaned = False
        if actor_urn:
            try:
                async with IsolatedSystemClient(
                    args.target_server,
                    ca_file=Path(values["PHASE10_DATAHUB_CA_FILE"]),
                    client_id=values["DATAHUB_SYSTEM_CLIENT_ID"],
                    client_secret=values["DATAHUB_SYSTEM_CLIENT_SECRET"],
                    timeout_seconds=min(args.timeout, 60.0),
                ) as client:
                    if token_id:
                        await client.revoke_access_token(token_id)
                    await client.delete_service_account(actor_urn)
                identity_cleaned = True
            except Exception:
                pass
        if lease_written and identity_cleaned:
            LEASE_FILE.unlink(missing_ok=True)
        raise


async def cleanup(args: argparse.Namespace) -> dict[str, Any]:
    lease = _read_lease()
    values = _environment(args.env_file)
    removed = _remove_containers()
    async with IsolatedSystemClient(
        args.target_server,
        ca_file=Path(values["PHASE10_DATAHUB_CA_FILE"]),
        client_id=values["DATAHUB_SYSTEM_CLIENT_ID"],
        client_secret=values["DATAHUB_SYSTEM_CLIENT_SECRET"],
        timeout_seconds=min(args.timeout, 60.0),
    ) as client:
        await client.revoke_access_token(str(lease["token_id"]))
        await client.delete_service_account(str(lease["actor_urn"]))
    LEASE_FILE.unlink()
    return {
        "status": "PHASE10_CANDIDATE_SERVICES_CLEANED",
        "target_project": TARGET_PROJECT,
        "removed_container_count": removed,
        "token_revoked": True,
        "service_account_deleted": True,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    validate_boundary(args)
    if args.command == "start":
        return await start(args)
    if args.command == "cleanup":
        return await cleanup(args)
    receipt = await inspect_candidate_services(args)
    return {
        "status": "PHASE10_CANDIDATE_SERVICES_VERIFIED",
        **receipt,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                result = runner.run(run(args))
        else:
            result = asyncio.run(run(args))
    except (OSError, RuntimeError, ValueError, AcceptanceError, psycopg.Error) as error:
        message = (
            str(error)
            if isinstance(error, Phase10CandidateServiceError)
            else "Phase 10 candidate service operation failed"
        )
        print(
            json.dumps(
                {
                    "status": "PHASE10_CANDIDATE_SERVICES_ERROR",
                    "error": message,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
