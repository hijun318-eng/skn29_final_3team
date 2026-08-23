#!/usr/bin/env python3
"""Phase 10 P0 same-release 증거를 판정하고 불완전한 봉인을 fail-closed 한다.

이 entrypoint는 과거 Phase PASS 문서나 저장된 projection receipt를 현재 브라우저 E2E로
승계하지 않는다. 현재 source, candidate image, model, DataHub, Trino, App DB, Browser와
host validation이 하나의 product release에 결속되고 PRD의 모든 P0 Requirement/Gate가
VERIFIED일 때만 최종 상태를 VERIFIED로 만들 수 있다. 통과한 증거 축과 미완료 PRD는
별도로 보고해 실제 blocker를 image/browser 부재로 잘못 표현하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (
    str(ROOT),
    str(BACKEND),
    str(DATAHUB),
    str(Path(__file__).resolve().parent),
):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.capability_contracts import ProductReleaseEvidenceManifest  # noqa: E402
from app.adapters.runtime_catalog_projection import (  # noqa: E402
    RuntimeCatalogProjection,
)
from app.adapters.trino_async import TrinoAsyncClient  # noqa: E402
from app.adapters.trino_schema import TrinoSchemaInspector  # noqa: E402
from app.database import dispose_database, get_sessionmaker  # noqa: E402
from native_semantic_publication import verify_native_semantic_shadow  # noqa: E402
from native_semantic_shadow import native_semantic_shadow_projection  # noqa: E402
from phase10_browser_receipt import (  # noqa: E402
    Phase10BrowserReceiptError,
    validate_receipt as validate_browser_receipt,
)
from phase10_candidate_release import PHASE10_PREFIX, TARGET_DATABASE  # noqa: E402
from phase10_candidate_services import inspect_candidate_services  # noqa: E402
from phase10_host_validation import (  # noqa: E402
    Phase10HostValidationError,
    validate_receipt as validate_host_receipt,
)
from phase10_p0_product_eval import (  # noqa: E402
    OUTPUT_OBSERVATIONS as PRODUCT_EVAL_OBSERVATIONS,
    SEALED_RECEIPT as P0_SEAL_RECEIPT,
    Phase10P0ProductEvalError,
    validate_evaluation_receipt,
)
from phase10_p0_release_seal import (  # noqa: E402
    Phase10P0ReleaseSealError,
    validate_release_seal_receipt,
)
from phase2b_datahub_candidate import (  # noqa: E402
    IsolatedSystemClient,
    _verify_with_freshness,
)
from phase3b_native_metric_shadow import RetryingIsolatedClient  # noqa: E402
from phase4_runtime_catalog_projection import (  # noqa: E402
    _migration_chain_sha256,
    _source_receipt,
)
from phase9_multi_asset_join import _target_scope_with_native  # noqa: E402
from src.ai.model_contracts import model_release_checksum  # noqa: E402
from src.data.governance_contract import canonical_sha256  # noqa: E402


TARGET_PROJECT = "answervice-phase2b-datahub"
DATABASE_PORT = 55440
DATABASE_NAME = TARGET_DATABASE
DATABASE_USER = "phase10_runtime"
ASSESSMENT_VERSION = "answervice.phase10_p0_same_release_assessment.v3"

REQUIREMENT_PREFIXES = frozenset(
    {"DATA", "GOV", "AUTH", "ANL", "CONV", "FAIL", "SAVE", "RPT", "OPS", "SEC", "QA"}
)
EXPECTED_RELEASE_GATES = frozenset(
    {
        "P0-DATA-CUTOVER",
        "P0-DATAHUB-SEARCH",
        "P0-GLOSSARY",
        "P0-GOLD",
        "P0-E2E-REAL",
        "P0-REPORT-RERUN",
        "P0-GOLDEN-DIALOGUE",
        "P0-SECURITY",
        "P0-FAILURE",
        "P0-EVIDENCE",
        "P0-QUANT",
    }
)
REQUIRED_EVIDENCE_AXES = (
    "source",
    "backend_image",
    "frontend_image",
    "model",
    "datahub",
    "trino",
    "app_db",
    "browser",
    "host_validation",
    "product_eval",
)
PRD_STATUSES = frozenset(
    {"NOT_STARTED", "PARTIAL", "BLOCKED", "READY_TO_VERIFY", "VERIFIED"}
)

_REQUIREMENT_ROW = re.compile(
    r"^\|\s*`?([A-Z]+-\d{3})`?\s*\|.*\|\s*`([A-Z_]+)`\s*\|\s*$"
)
_RELEASE_GATE_ROW = re.compile(
    r"^\|\s*`?(P0-[A-Z0-9-]+)`?\s*\|.*\|\s*`([A-Z_]+)`\s*\|\s*$"
)
_MAPPING_ROW = re.compile(r"^\|\s*`?(P0-[A-Z0-9-]+)`?\s*\|\s*(.*?)\s*\|\s*$")
_MAPPED_REQUIREMENT = re.compile(r"(?:[A-Z]+-\d{3})(?:~[A-Z]+-\d{3})?")


class Phase10Error(RuntimeError):
    """Phase 10 경계·PRD·receipt가 불완전하거나 모순임을 나타낸다."""


@dataclass(frozen=True)
class PrdInventory:
    """PRD에서 exact 추출한 P0 Requirement와 Release Gate 상태다."""

    requirements: dict[str, str]
    release_gates: dict[str, str]
    mapping_rows: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ActiveReceipt:
    """격리 App DB의 active pointer와 immutable product manifest snapshot이다."""

    generation: int
    manifest: ProductReleaseEvidenceManifest
    migration_revision: str
    projection: RuntimeCatalogProjection | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--prd", type=Path, default=ROOT / "docs" / "product" / "01_PRD.md")
    parser.add_argument("--target-server")
    parser.add_argument("--trino-server")
    parser.add_argument("--trino-ca-file", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--browser-receipt", type=Path)
    parser.add_argument("--host-validation-receipt", type=Path)
    parser.add_argument("--product-eval-receipt", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--verify-timeout", type=float, default=180.0)
    return parser.parse_args(argv)


def _validate_boundary(args: argparse.Namespace) -> None:
    if args.target_project != TARGET_PROJECT:
        raise Phase10Error("Phase 10 target project is outside the approved boundary")
    database = make_url(args.database_url)
    if (
        database.drivername != "postgresql+psycopg"
        or database.host not in {"127.0.0.1", "localhost", "::1"}
        or database.port != DATABASE_PORT
        or database.database != DATABASE_NAME
        or database.username != DATABASE_USER
        or database.password is not None
    ):
        raise Phase10Error("Phase 10 database is outside the isolated acceptance boundary")
    try:
        prd = args.prd.resolve(strict=True)
        prd.relative_to(ROOT.resolve())
    except (OSError, ValueError) as error:
        raise Phase10Error("Phase 10 PRD is outside the repository boundary") from error
    if prd != (ROOT / "docs" / "product" / "01_PRD.md").resolve():
        raise Phase10Error("Phase 10 requires the canonical P0 PRD")
    probe_values = (
        args.target_server,
        args.trino_server,
        args.trino_ca_file,
        args.env_file,
        args.browser_receipt,
        args.host_validation_receipt,
        args.product_eval_receipt,
    )
    if any(value is not None for value in probe_values):
        if any(value is None for value in probe_values):
            raise Phase10Error("Phase 10 current probes require all endpoint inputs")
        for value, port, label in (
            (args.target_server, 38081, "target DataHub"),
            (args.trino_server, 18443, "Trino"),
        ):
            endpoint = httpx.URL(value)
            if (
                endpoint.scheme != "https"
                or endpoint.host not in {"127.0.0.1", "localhost", "::1"}
                or endpoint.port != port
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
                or endpoint.path not in {"", "/"}
            ):
                raise Phase10Error(f"Phase 10 {label} is outside the approved boundary")
        try:
            ca_file = args.trino_ca_file.resolve(strict=True)
            env_file = args.env_file.resolve(strict=True)
        except OSError as error:
            raise Phase10Error("Phase 10 probe files are unavailable") from error
        if not ca_file.is_file() or not args.trino_ca_file.is_absolute():
            raise Phase10Error("Phase 10 Trino CA is outside the explicit boundary")
        if env_file != (ROOT / "infrastructure" / "database" / ".env").resolve():
            raise Phase10Error("Phase 10 requires the approved isolated environment file")
        for value, label in (
            (args.browser_receipt, "browser receipt"),
            (args.host_validation_receipt, "host validation receipt"),
            (args.product_eval_receipt, "product evaluation receipt"),
        ):
            try:
                receipt = value.resolve(strict=True)
                receipt.relative_to((ROOT / ".tmp").resolve(strict=True))
            except (OSError, ValueError) as error:
                raise Phase10Error(
                    f"Phase 10 {label} is outside the repository temporary boundary"
                ) from error
            if receipt.suffix.lower() != ".json" or not receipt.is_file():
                raise Phase10Error(f"Phase 10 {label} is invalid")
    if args.timeout <= 0 or args.verify_timeout <= 0:
        raise Phase10Error("Phase 10 probe timeouts must be positive")
    if args.output is not None:
        try:
            output = args.output.resolve(strict=False)
            output.relative_to((ROOT / ".tmp").resolve(strict=True))
        except (OSError, ValueError) as error:
            raise Phase10Error(
                "Phase 10 assessment output is outside the repository temporary boundary"
            ) from error
        if output.suffix.lower() != ".json":
            raise Phase10Error("Phase 10 assessment output must be JSON")


def parse_prd(text_value: str) -> PrdInventory:
    """PRD 표에서 Requirement/Gate 상태를 추출하고 누락·중복을 거부한다."""

    requirements: dict[str, str] = {}
    release_gates: dict[str, str] = {}
    mapping_rows: dict[str, tuple[str, ...]] = {}
    for line in text_value.splitlines():
        requirement = _REQUIREMENT_ROW.match(line)
        if requirement and requirement.group(1).split("-", 1)[0] in REQUIREMENT_PREFIXES:
            _insert_status(requirements, requirement.group(1), requirement.group(2))
            continue
        release_gate = _RELEASE_GATE_ROW.match(line)
        if release_gate:
            _insert_status(release_gates, release_gate.group(1), release_gate.group(2))
            continue
        mapping = _MAPPING_ROW.match(line)
        if mapping and mapping.group(1) in EXPECTED_RELEASE_GATES:
            references = tuple(_MAPPED_REQUIREMENT.findall(mapping.group(2)))
            if references:
                if mapping.group(1) in mapping_rows:
                    raise Phase10Error("PRD Requirement-to-Gate mapping is duplicated")
                mapping_rows[mapping.group(1)] = references

    observed_prefixes = {item.split("-", 1)[0] for item in requirements}
    if observed_prefixes != REQUIREMENT_PREFIXES:
        raise Phase10Error("PRD P0 Requirement categories are incomplete")
    if set(release_gates) != EXPECTED_RELEASE_GATES:
        raise Phase10Error("PRD P0 Release Gate inventory is incomplete")
    if set(mapping_rows) != EXPECTED_RELEASE_GATES:
        raise Phase10Error("PRD Requirement-to-Gate mapping inventory is incomplete")
    _validate_mapping_references(requirements, mapping_rows)
    return PrdInventory(requirements, release_gates, mapping_rows)


def _insert_status(target: dict[str, str], identifier: str, status: str) -> None:
    if status not in PRD_STATUSES:
        raise Phase10Error(f"PRD status is unsupported: {identifier}")
    if identifier in target:
        raise Phase10Error(f"PRD identifier is duplicated: {identifier}")
    target[identifier] = status


def _expand_reference(reference: str) -> tuple[str, ...]:
    if "~" not in reference:
        return (reference,)
    start, end = reference.split("~", 1)
    start_prefix, start_number = start.split("-", 1)
    end_prefix, end_number = end.split("-", 1)
    if start_prefix != end_prefix or int(start_number) > int(end_number):
        raise Phase10Error("PRD Requirement range is invalid")
    return tuple(
        f"{start_prefix}-{number:03d}"
        for number in range(int(start_number), int(end_number) + 1)
    )


def _validate_mapping_references(
    requirements: Mapping[str, str],
    mapping_rows: Mapping[str, tuple[str, ...]],
) -> None:
    referenced = {
        requirement
        for references in mapping_rows.values()
        for reference in references
        for requirement in _expand_reference(reference)
    }
    missing = referenced.difference(requirements)
    if missing:
        raise Phase10Error("PRD Requirement-to-Gate mapping references unknown IDs")


async def _load_active_receipt(database_url: str) -> ActiveReceipt:
    sessionmaker = get_sessionmaker(database_url)
    try:
        async with sessionmaker() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT a.generation, m.manifest_json,
                               p.projection_json, p.projection_sha256,
                               (SELECT version_num FROM governance.alembic_version)
                                   AS migration_revision
                        FROM governance.runtime_catalog_active_pointer a
                        JOIN governance.runtime_catalog_projections p
                          ON p.projection_id = a.projection_id
                        JOIN governance.product_release_manifests m
                          ON m.product_release_id = a.product_release_id
                        WHERE a.pointer_name = 'analysis'
                        """
                    )
                )
            ).mappings().one_or_none()
    except Exception as error:
        raise Phase10Error("isolated active product receipt could not be read") from error
    finally:
        await dispose_database()
    if row is None:
        raise Phase10Error("isolated active product release is unavailable")
    try:
        manifest = ProductReleaseEvidenceManifest.model_validate(row["manifest_json"])
        projection = RuntimeCatalogProjection.from_document(
            row["projection_json"],
            expected_projection_sha256=str(row["projection_sha256"]),
        )
    except Exception as error:  # Pydantic의 상세 payload는 secret-safe 출력에 포함하지 않는다.
        raise Phase10Error("isolated active product manifest is invalid") from error
    if (
        manifest.evidence.catalog.release_id != projection.catalog_release_id
        or manifest.evidence.catalog.manifest_sha256 != projection.manifest_sha256
        or manifest.evidence.catalog.projection_sha256 != projection.projection_sha256
    ):
        raise Phase10Error("isolated active product/projection receipt differs")
    revision = str(row["migration_revision"] or "")
    if not revision:
        raise Phase10Error("isolated App DB migration revision is unavailable")
    return ActiveReceipt(int(row["generation"]), manifest, revision, projection)


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
        "TRINO_DATAHUB_USER",
        "TRINO_DATAHUB_PASSWORD",
        "TRINO_ADMIN_USER",
        "TRINO_ADMIN_PASSWORD",
    )
    if any(not values.get(name, "").strip() for name in required):
        raise Phase10Error("Phase 10 isolated probe credentials are incomplete")
    datahub_ca = Path(values["DATAHUB_TLS_CA_HOST_FILE"])
    try:
        resolved = datahub_ca.resolve(strict=True)
    except OSError as error:
        raise Phase10Error("Phase 10 DataHub CA is unavailable") from error
    if not datahub_ca.is_absolute() or not resolved.is_file():
        raise Phase10Error("Phase 10 DataHub CA is outside the explicit boundary")
    values["PHASE10_DATAHUB_CA_FILE"] = str(resolved)
    return values


async def _probe_current_dependencies(
    args: argparse.Namespace,
    active: ActiveReceipt,
    current_source: object,
) -> dict[str, Any]:
    """현재 same-release dependency를 historical receipt 없이 다시 관측한다."""

    if active.projection is None or args.env_file is None:
        raise Phase10Error("Phase 10 active projection probe input is unavailable")
    environment = _environment(args.env_file)
    bundle = active.projection.release.as_bundle()
    native_projection = native_semantic_shadow_projection(bundle)
    async with IsolatedSystemClient(
        args.target_server,
        ca_file=Path(environment["PHASE10_DATAHUB_CA_FILE"]),
        client_id=environment["DATAHUB_SYSTEM_CLIENT_ID"],
        client_secret=environment["DATAHUB_SYSTEM_CLIENT_SECRET"],
        timeout_seconds=args.timeout,
    ) as raw_target:
        target = RetryingIsolatedClient(raw_target)
        await _verify_with_freshness(
            target,
            bundle,
            timeout_seconds=args.verify_timeout,
        )
        membership = await _target_scope_with_native(target, bundle)
        native_readback = await verify_native_semantic_shadow(
            target,
            bundle,
            expected_projection_sha256=native_projection["projection_sha256"],
        )

    trino = TrinoAsyncClient(
        args.trino_server,
        environment["TRINO_DATAHUB_USER"],
        environment["TRINO_DATAHUB_PASSWORD"],
        ca_file=args.trino_ca_file,
        request_timeout_seconds=args.timeout,
    )
    try:
        datasets = tuple(
            active.projection.snapshot.datasets_by_fqn[asset.fqn]
            for asset in active.projection.release.assets
        )
        observed = await TrinoSchemaInspector(
            trino,
            timeout_seconds=args.timeout,
        ).fingerprints(datasets)
    finally:
        await trino.aclose()
    expected_by_fqn = {
        str(item["fqn"]): dict(item)
        for item in active.projection.trino_fingerprints
    }
    observed_by_fqn = {str(item["fqn"]): dict(item) for item in observed}
    if observed_by_fqn != expected_by_fqn:
        raise Phase10Error("Phase 10 current Trino fingerprint differs")

    query_user = environment["TRINO_DATAHUB_USER"]
    if not re.fullmatch(r"[A-Za-z0-9_]{1,128}", query_user):
        raise Phase10Error("Phase 10 Trino query principal is invalid")
    admin_user = environment["TRINO_ADMIN_USER"]
    if not re.fullmatch(r"[A-Za-z0-9_]{1,128}", admin_user):
        raise Phase10Error("Phase 10 Trino audit principal is invalid")
    try:
        tls = ssl.create_default_context(cafile=str(args.trino_ca_file))
        async with httpx.AsyncClient(verify=tls, trust_env=False) as client:
            response = await client.get(
                f"{args.trino_server.rstrip('/')}/v1/query",
                headers={"X-Trino-User": admin_user},
                auth=httpx.BasicAuth(
                    admin_user,
                    environment["TRINO_ADMIN_PASSWORD"],
                ),
                timeout=args.timeout,
            )
            response.raise_for_status()
            query_infos = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise Phase10Error("Phase 10 Trino query audit could not be read") from error
    if not isinstance(query_infos, list) or any(
        not isinstance(item, dict) for item in query_infos
    ):
        raise Phase10Error("Phase 10 Trino query audit response is invalid")
    nonterminal_count = 0
    for item in query_infos:
        session = item.get("session")
        user = session.get("user") if isinstance(session, dict) else None
        state = item.get("state")
        if user == query_user and state in {"QUEUED", "RUNNING", "FINISHING"}:
            nonterminal_count += 1
    if nonterminal_count != 0:
        raise Phase10Error("Phase 10 found a nonterminal acceptance Trino query")

    candidate = await inspect_candidate_services(args)
    try:
        browser_document = json.loads(args.browser_receipt.read_text(encoding="utf-8"))
        host_document = json.loads(
            args.host_validation_receipt.read_text(encoding="utf-8")
        )
        product_eval_document = json.loads(
            args.product_eval_receipt.read_text(encoding="utf-8")
        )
        p0_seal_document = json.loads(P0_SEAL_RECEIPT.read_text(encoding="utf-8"))
        observations_sha256 = hashlib.sha256(
            PRODUCT_EVAL_OBSERVATIONS.read_bytes()
        ).hexdigest()
    except (AttributeError, OSError, json.JSONDecodeError) as error:
        raise Phase10Error("Phase 10 current validation receipt is unavailable") from error
    if (
        not isinstance(browser_document, dict)
        or not isinstance(host_document, dict)
        or not isinstance(product_eval_document, dict)
        or not isinstance(p0_seal_document, dict)
    ):
        raise Phase10Error("Phase 10 current validation receipt is invalid")
    try:
        validate_browser_receipt(
            browser_document,
            database_url=args.database_url,
            active_manifest=active.manifest,
            active_generation=active.generation,
            current_source=current_source,
        )
        validate_host_receipt(
            host_document,
            active_manifest=active.manifest,
            active_generation=active.generation,
            current_source=current_source,
        )
        validate_release_seal_receipt(p0_seal_document)
        seal_product = p0_seal_document.get("product_release")
        seal_semantic = p0_seal_document.get("semantic_release")
        if (
            not isinstance(seal_product, Mapping)
            or not isinstance(seal_semantic, Mapping)
            or p0_seal_document.get("active_generation") != active.generation
            or seal_product.get("product_release_id")
            != active.manifest.product_release_id
            or seal_semantic.get("release_id")
            != active.manifest.evidence.catalog.release_id
        ):
            raise Phase10Error("Phase 10 P0 release seal differs from active release")
        validate_evaluation_receipt(
            product_eval_document,
            observations_sha256=observations_sha256,
            active_generation=active.generation,
            product_release_id=active.manifest.product_release_id,
            semantic_release_id=active.manifest.evidence.catalog.release_id,
            seal_receipt_sha256=str(p0_seal_document["receipt_sha256"]),
        )
    except (
        Phase10BrowserReceiptError,
        Phase10HostValidationError,
        Phase10P0ProductEvalError,
        Phase10P0ReleaseSealError,
    ) as error:
        raise Phase10Error("Phase 10 current validation receipt differs") from error

    return {
        "datahub": {
            "verified": True,
            **membership,
            "native_readback_sha256": native_readback[
                "readback_projection_sha256"
            ],
            "receipt_sha256": canonical_sha256(
                {
                    "membership": membership,
                    "native_readback_sha256": native_readback[
                        "readback_projection_sha256"
                    ],
                    "catalog_manifest_sha256": active.projection.manifest_sha256,
                }
            ),
        },
        "trino": {
            "verified": True,
            "fingerprint_count": len(observed_by_fqn),
            "fingerprint_sha256": canonical_sha256(
                [observed_by_fqn[name] for name in sorted(observed_by_fqn)]
            ),
            "nonterminal_acceptance_query_count": nonterminal_count,
        },
        "candidate_services": candidate,
        "browser": {
            "verified": True,
            "receipt_sha256": browser_document["receipt_sha256"],
            "request_id": browser_document["database_evidence"]["request_id"],
            "query_id": browser_document["database_evidence"]["query_id"],
            "screenshot_sha256": browser_document["screenshot"]["sha256"],
        },
        "host_validation": {
            "verified": True,
            "receipt_sha256": host_document["receipt_sha256"],
            "check_count": len(host_document["checks"]),
            "historical_evidence_mixed": False,
            "skipped_evidence_count": 0,
        },
        "product_eval": {
            "verified": product_eval_document["status"] == "PASSED",
            "status": product_eval_document["status"],
            "receipt_sha256": product_eval_document["receipt_sha256"],
            "observations_sha256": product_eval_document["observations_sha256"],
            "passed": product_eval_document["scoring"]["passed"],
            "deterministic": product_eval_document["scoring"]["deterministic"],
            "product_release_id": product_eval_document["product_release_id"],
            "semantic_release_id": product_eval_document["semantic_release_id"],
            "historical_evidence_mixed": False,
            "skipped_evidence_count": 0,
        },
    }


def _receipt_sha256(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return canonical_sha256(value)


def build_assessment(
    *,
    inventory: PrdInventory,
    active: ActiveReceipt,
    current_source: object,
    current_model_sha256: str,
    current_migration_sha256: str,
    current_probes: Mapping[str, Any] | None = None,
    assessed_at: datetime | None = None,
) -> dict[str, Any]:
    """현재 관측값만으로 Phase 10 상태를 만들고 historical/skip 대체를 금지한다."""

    active_manifest = active.manifest
    evidence = active_manifest.evidence
    source_document = current_source.model_dump(mode="json")
    source_matches = source_document == evidence.source.model_dump(mode="json")
    model_matches = current_model_sha256 == evidence.model.manifest_sha256
    app_db_matches = (
        active.migration_revision == evidence.migration.revision
        and current_migration_sha256 == evidence.migration.chain_sha256
    )

    datahub_probe_verified = bool(
        current_probes
        and isinstance(current_probes.get("datahub"), Mapping)
        and current_probes["datahub"].get("verified") is True
    )
    trino_probe_verified = bool(
        current_probes
        and isinstance(current_probes.get("trino"), Mapping)
        and current_probes["trino"].get("verified") is True
    )
    candidate_probe_verified = bool(
        current_probes
        and isinstance(current_probes.get("candidate_services"), Mapping)
        and current_probes["candidate_services"].get("verified") is True
        and current_probes["candidate_services"].get("product_release_id")
        == active_manifest.product_release_id
    )
    browser_probe_verified = bool(
        current_probes
        and isinstance(current_probes.get("browser"), Mapping)
        and current_probes["browser"].get("verified") is True
    )
    host_probe_verified = bool(
        current_probes
        and isinstance(current_probes.get("host_validation"), Mapping)
        and current_probes["host_validation"].get("verified") is True
    )
    product_eval_verified = bool(
        current_probes
        and isinstance(current_probes.get("product_eval"), Mapping)
        and current_probes["product_eval"].get("verified") is True
        and current_probes["product_eval"].get("product_release_id")
        == active_manifest.product_release_id
        and current_probes["product_eval"].get("semantic_release_id")
        == active_manifest.evidence.catalog.release_id
    )
    axes = {
        "source": "VERIFIED" if source_matches else "MISMATCH",
        "backend_image": "VERIFIED" if candidate_probe_verified else "MISSING",
        "frontend_image": "VERIFIED" if candidate_probe_verified else "MISSING",
        "model": "VERIFIED" if model_matches else "MISMATCH",
        "datahub": "VERIFIED" if datahub_probe_verified else "ACTIVE_RECEIPT_ONLY",
        "trino": "VERIFIED" if trino_probe_verified else "ACTIVE_RECEIPT_ONLY",
        "app_db": "VERIFIED" if app_db_matches else "MISMATCH",
        "browser": "VERIFIED" if browser_probe_verified else "MISSING",
        "host_validation": "VERIFIED" if host_probe_verified else "EXTERNAL_RECEIPT_MISSING",
        "product_eval": (
            "VERIFIED"
            if product_eval_verified
            else "FAILED"
            if current_probes and isinstance(current_probes.get("product_eval"), Mapping)
            else "MISSING"
        ),
    }
    non_verified_requirements = sorted(
        identifier
        for identifier, status in inventory.requirements.items()
        if status != "VERIFIED"
    )
    non_verified_gates = sorted(
        identifier
        for identifier, status in inventory.release_gates.items()
        if status != "VERIFIED"
    )
    blockers: list[str] = []
    if not active_manifest.product_release_id.startswith(PHASE10_PREFIX):
        blockers.append("ACTIVE_PRODUCT_RELEASE_IS_NOT_PHASE10")
    for axis in REQUIRED_EVIDENCE_AXES:
        if axes[axis] != "VERIFIED":
            blockers.append(f"EVIDENCE_AXIS_{axis.upper()}_{axes[axis]}")
    if non_verified_requirements:
        blockers.append("P0_REQUIREMENTS_NOT_VERIFIED")
    if non_verified_gates:
        blockers.append("P0_RELEASE_GATES_NOT_VERIFIED")

    payload: dict[str, Any] = {
        "schema_version": ASSESSMENT_VERSION,
        "status": "BLOCKED" if blockers else "VERIFIED",
        "assessed_at": (assessed_at or datetime.now(timezone.utc)).isoformat(),
        "target_project": TARGET_PROJECT,
        "active_product_release_id": active_manifest.product_release_id,
        "active_generation": active.generation,
        "active_manifest_sha256": active_manifest.manifest_sha256,
        "current_source": source_document,
        "current_model_manifest_sha256": current_model_sha256,
        "current_migration": {
            "revision": active.migration_revision,
            "chain_sha256": current_migration_sha256,
        },
        "active_receipts": {
            "source_sha256": _receipt_sha256(evidence.source),
            "image_components": sorted(image.component for image in evidence.images),
            "model_sha256": evidence.model.manifest_sha256,
            "catalog_release_id": evidence.catalog.release_id,
            "catalog_manifest_sha256": evidence.catalog.manifest_sha256,
            "catalog_projection_sha256": evidence.catalog.projection_sha256,
            "migration_revision": evidence.migration.revision,
            "migration_chain_sha256": evidence.migration.chain_sha256,
        },
        "current_dependency_probes": dict(current_probes or {}),
        "evidence_axes": axes,
        "requirement_statuses": dict(sorted(inventory.requirements.items())),
        "release_gate_statuses": dict(sorted(inventory.release_gates.items())),
        "non_verified_requirement_ids": non_verified_requirements,
        "non_verified_release_gate_ids": non_verified_gates,
        "historical_evidence_mixed": False,
        "skipped_evidence_count": 0,
        "blockers": sorted(blockers),
    }
    if payload["status"] == "VERIFIED":
        _validate_verified_assessment(payload)
    payload["assessment_sha256"] = canonical_sha256(payload)
    return payload


def _validate_verified_assessment(payload: Mapping[str, Any]) -> None:
    """VERIFIED 표기가 모든 same-release 전제와 exact 일치할 때만 통과시킨다."""

    axes = payload.get("evidence_axes")
    if (
        not isinstance(axes, Mapping)
        or set(axes) != set(REQUIRED_EVIDENCE_AXES)
        or set(axes.values()) != {"VERIFIED"}
        or payload.get("non_verified_requirement_ids") != []
        or payload.get("non_verified_release_gate_ids") != []
        or payload.get("historical_evidence_mixed") is not False
        or payload.get("skipped_evidence_count") != 0
        or payload.get("blockers") != []
    ):
        raise Phase10Error("Phase 10 VERIFIED assessment is incomplete")


def validate_assessment(document: Mapping[str, Any]) -> None:
    """저장하거나 전달받은 assessment의 schema와 canonical checksum을 재검증한다."""

    if document.get("schema_version") != ASSESSMENT_VERSION:
        raise Phase10Error("Phase 10 assessment schema differs")
    checksum = document.get("assessment_sha256")
    if not isinstance(checksum, str) or len(checksum) != 64:
        raise Phase10Error("Phase 10 assessment checksum is invalid")
    payload = {key: value for key, value in document.items() if key != "assessment_sha256"}
    if checksum != canonical_sha256(payload):
        raise Phase10Error("Phase 10 assessment checksum differs")
    if document.get("status") == "VERIFIED":
        _validate_verified_assessment(document)
    elif document.get("status") != "BLOCKED" or not document.get("blockers"):
        raise Phase10Error("Phase 10 assessment terminal status is invalid")


def _write_assessment(path: Path, document: Mapping[str, Any]) -> None:
    """Atomically retain the secret-safe assessment outside the source receipt."""

    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_boundary(args)
    inventory = parse_prd(args.prd.read_text(encoding="utf-8"))
    active = await _load_active_receipt(args.database_url)
    current_source, _commit_timestamp = _source_receipt()
    current_probes = None
    if args.target_server is not None:
        current_probes = await _probe_current_dependencies(
            args,
            active,
            current_source,
        )
    return build_assessment(
        inventory=inventory,
        active=active,
        current_source=current_source,
        current_model_sha256=model_release_checksum(),
        current_migration_sha256=_migration_chain_sha256(),
        current_probes=current_probes,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                assessment = runner.run(_run(args))
        else:
            assessment = asyncio.run(_run(args))
        validate_assessment(assessment)
        if args.output is not None:
            _write_assessment(args.output, assessment)
    except (OSError, RuntimeError, ValueError) as error:
        message = (
            str(error)
            if isinstance(error, Phase10Error)
            else "Phase 10 dependency probe failed"
        )
        print(
            json.dumps(
                {
                    "status": "PHASE10_P0_SAME_RELEASE_ERROR",
                    "error": message,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(assessment, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if assessment["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
