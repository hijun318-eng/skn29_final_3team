#!/usr/bin/env python3
"""Seal one inspected Phase 10 browser run without storing cookies or secrets.

The browser assertion itself is an explicit operator attestation.  This tool
binds that assertion and a PNG screenshot to the exact immutable product
release, source receipt, request, Trino query, artifact, and release bindings
in the dedicated Phase 10 database.  It never stores page traces, network
captures, raw rows, SQL, credentials, or authentication state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import URL, make_url


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
HERE = Path(__file__).resolve().parent
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.capability_contracts import (  # noqa: E402
    ProductReleaseEvidenceManifest,
    SourceReceipt,
)
from phase10_candidate_release import PHASE10_PREFIX, TARGET_DATABASE  # noqa: E402
from phase4_runtime_catalog_projection import _source_receipt  # noqa: E402
from src.data.governance_contract import canonical_sha256  # noqa: E402


TARGET_PROJECT = "answervice-phase2b-datahub"
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 55440
TARGET_USER = "phase10_runtime"
FRONTEND_URL = "http://127.0.0.1:43000"
SCREENSHOT_ROOT = ROOT / "output" / "playwright"
OUTPUT_ROOT = ROOT / ".tmp"
RECEIPT_VERSION = "answervice.phase10_browser_receipt.v1"


class Phase10BrowserReceiptError(RuntimeError):
    """The browser attestation or its durable same-release evidence differs."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--frontend-url", required=True)
    parser.add_argument("--request-id", type=UUID, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--completion-visible", action="store_true")
    parser.add_argument("--evidence-visible", action="store_true")
    return parser.parse_args(argv)


def _database_url(value: str) -> URL:
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {TARGET_HOST, "localhost", "::1"}
        or url.port != TARGET_PORT
        or url.database != TARGET_DATABASE
        or url.username != TARGET_USER
        or url.password is not None
        or url.query
    ):
        raise Phase10BrowserReceiptError(
            "Phase 10 browser database is outside the isolated boundary"
        )
    return url


def _inside(path: Path, root: Path, label: str, *, must_exist: bool) -> Path:
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=must_exist)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise Phase10BrowserReceiptError(
            f"Phase 10 browser {label} is outside the repository boundary"
        ) from error
    return resolved


def validate_boundary(args: argparse.Namespace) -> URL:
    if args.target_project != TARGET_PROJECT:
        raise Phase10BrowserReceiptError(
            "Phase 10 browser target project is outside the approved boundary"
        )
    if args.frontend_url.rstrip("/") != FRONTEND_URL:
        raise Phase10BrowserReceiptError(
            "Phase 10 browser frontend is outside the isolated boundary"
        )
    _inside(args.screenshot, SCREENSHOT_ROOT, "screenshot", must_exist=True)
    output = _inside(args.output, OUTPUT_ROOT, "receipt output", must_exist=False)
    if output.suffix.lower() != ".json":
        raise Phase10BrowserReceiptError(
            "Phase 10 browser receipt output must be JSON"
        )
    if not args.completion_visible or not args.evidence_visible:
        raise Phase10BrowserReceiptError(
            "Phase 10 browser visible assertions are incomplete"
        )
    return _database_url(args.database_url)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _screenshot_receipt(path: Path) -> dict[str, Any]:
    resolved = _inside(path, SCREENSHOT_ROOT, "screenshot", must_exist=True)
    prefix = resolved.read_bytes()[:8]
    size = resolved.stat().st_size
    if resolved.suffix.lower() != ".png" or prefix != b"\x89PNG\r\n\x1a\n" or size < 1024:
        raise Phase10BrowserReceiptError("Phase 10 browser screenshot is invalid")
    return {
        "path": resolved.relative_to(ROOT.resolve()).as_posix(),
        "sha256": _file_sha256(resolved),
        "size_bytes": size,
    }


def _connect(url: URL) -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        row_factory=dict_row,
    )


def _durable_evidence(
    url: URL,
    request_id: UUID,
) -> tuple[ProductReleaseEvidenceManifest, int, dict[str, Any]]:
    with _connect(url) as connection:
        active = connection.execute(
            """
            SELECT a.generation, m.manifest_json
            FROM governance.runtime_catalog_active_pointer a
            JOIN governance.product_release_manifests m
              ON m.product_release_id = a.product_release_id
            WHERE a.pointer_name = 'analysis'
            """
        ).fetchone()
        row = connection.execute(
            """
            SELECT r.request_id, r.status AS run_status, r.started_at,
                   r.product_release_id, r.permission_snapshot_id,
                   r.semantic_release_id, q.trino_query_id,
                   q.execution_status AS query_status, q.row_count,
                   a.artifact_id, a.status AS artifact_status,
                   (a.evidence_json->>'cached')::boolean AS cached,
                   (a.product_release_id, a.permission_snapshot_id,
                    a.semantic_release_id)
                     IS NOT DISTINCT FROM
                   (r.product_release_id, r.permission_snapshot_id,
                    r.semantic_release_id) AS artifact_receipt_match,
                   (br.product_release_id, br.permission_snapshot_id,
                    br.semantic_release_id)
                     IS NOT DISTINCT FROM
                   (r.product_release_id, r.permission_snapshot_id,
                    r.semantic_release_id) AS run_binding_match,
                   (ba.product_release_id, ba.permission_snapshot_id,
                    ba.semantic_release_id)
                     IS NOT DISTINCT FROM
                   (r.product_release_id, r.permission_snapshot_id,
                    r.semantic_release_id) AS artifact_binding_match,
                   (SELECT count(*) FROM query.query_executions q2
                     WHERE q2.request_id = r.request_id) AS query_count,
                   (SELECT count(*) FROM artifact.analysis_artifacts a2
                     WHERE a2.request_id = r.request_id) AS artifact_count
            FROM chat.analysis_requests r
            JOIN analysis_v1.analysis_run_links l ON l.request_id = r.request_id
            JOIN query.query_executions q ON q.request_id = r.request_id
            JOIN artifact.analysis_artifacts a ON a.request_id = r.request_id
            JOIN governance.product_release_bindings br
              ON br.object_kind = 'RUN' AND br.object_id = r.request_id::text
            JOIN governance.product_release_bindings ba
              ON ba.object_kind = 'ARTIFACT' AND ba.object_id = a.artifact_id::text
            WHERE r.request_id = %s
            """,
            (request_id,),
        ).fetchone()
    if active is None:
        raise Phase10BrowserReceiptError("Phase 10 active product release is unavailable")
    if row is None:
        raise Phase10BrowserReceiptError("Phase 10 browser request evidence is unavailable")
    try:
        manifest = ProductReleaseEvidenceManifest.model_validate(active["manifest_json"])
    except (KeyError, TypeError, ValueError) as error:
        raise Phase10BrowserReceiptError(
            "Phase 10 active product release is invalid"
        ) from error
    checks = (
        manifest.product_release_id.startswith(PHASE10_PREFIX),
        row["run_status"] == "SUCCEEDED",
        row["query_status"] == "SUCCEEDED",
        row["artifact_status"] == "APPROVED",
        row["cached"] is False,
        int(row["row_count"]) > 0,
        int(row["query_count"]) == 1,
        int(row["artifact_count"]) == 1,
        all(
            row[name]
            for name in (
                "product_release_id",
                "permission_snapshot_id",
                "semantic_release_id",
                "trino_query_id",
                "artifact_id",
            )
        ),
        row["product_release_id"] == manifest.product_release_id,
        bool(row["artifact_receipt_match"]),
        bool(row["run_binding_match"]),
        bool(row["artifact_binding_match"]),
        row["started_at"] >= manifest.created_at,
    )
    if not all(checks):
        raise Phase10BrowserReceiptError(
            "Phase 10 browser request is not complete same-release evidence"
        )
    evidence = {
        "request_id": str(row["request_id"]),
        "run_status": str(row["run_status"]),
        "query_id": str(row["trino_query_id"]),
        "query_status": str(row["query_status"]),
        "row_count": int(row["row_count"]),
        "artifact_id": str(row["artifact_id"]),
        "artifact_status": str(row["artifact_status"]),
        "cached": bool(row["cached"]),
        "receipt_complete": True,
        "binding_match": True,
    }
    return manifest, int(active["generation"]), evidence


def seal_receipt(args: argparse.Namespace, url: URL) -> dict[str, Any]:
    source, _created_at = _source_receipt()
    manifest, generation, evidence = _durable_evidence(url, args.request_id)
    if manifest.evidence.source != source:
        raise Phase10BrowserReceiptError(
            "Phase 10 browser evidence source differs from the active release"
        )
    payload: dict[str, Any] = {
        "schema_version": RECEIPT_VERSION,
        "verified": True,
        "target_project": TARGET_PROJECT,
        "frontend_url": FRONTEND_URL,
        "product_release_id": manifest.product_release_id,
        "active_generation": generation,
        "source": source.model_dump(mode="json"),
        "operator_assertions": {
            "completion_visible": True,
            "evidence_visible": True,
            "browser_engine": "chromium",
            "trace_or_network_capture_retained": False,
        },
        "screenshot": _screenshot_receipt(args.screenshot),
        "database_evidence": evidence,
        "sealed_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["receipt_sha256"] = canonical_sha256(payload)
    return payload


def validate_receipt(
    document: Mapping[str, Any],
    *,
    database_url: str,
    active_manifest: ProductReleaseEvidenceManifest,
    active_generation: int,
    current_source: SourceReceipt,
) -> None:
    checksum = document.get("receipt_sha256")
    payload = {key: value for key, value in document.items() if key != "receipt_sha256"}
    if (
        document.get("schema_version") != RECEIPT_VERSION
        or document.get("verified") is not True
        or document.get("target_project") != TARGET_PROJECT
        or document.get("frontend_url") != FRONTEND_URL
        or document.get("product_release_id") != active_manifest.product_release_id
        or document.get("active_generation") != active_generation
        or document.get("source") != current_source.model_dump(mode="json")
        or not isinstance(checksum, str)
        or checksum != canonical_sha256(payload)
    ):
        raise Phase10BrowserReceiptError("Phase 10 browser receipt differs")
    assertions = document.get("operator_assertions")
    if not isinstance(assertions, Mapping) or assertions != {
        "completion_visible": True,
        "evidence_visible": True,
        "browser_engine": "chromium",
        "trace_or_network_capture_retained": False,
    }:
        raise Phase10BrowserReceiptError("Phase 10 browser assertions differ")
    screenshot = document.get("screenshot")
    if not isinstance(screenshot, Mapping):
        raise Phase10BrowserReceiptError("Phase 10 browser screenshot receipt differs")
    path = ROOT / str(screenshot.get("path") or "")
    observed = _screenshot_receipt(path)
    if observed != dict(screenshot):
        raise Phase10BrowserReceiptError("Phase 10 browser screenshot changed")
    try:
        request_id = UUID(str(document["database_evidence"]["request_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise Phase10BrowserReceiptError(
            "Phase 10 browser request identity is invalid"
        ) from error
    manifest, generation, evidence = _durable_evidence(_database_url(database_url), request_id)
    if (
        manifest != active_manifest
        or generation != active_generation
        or evidence != document.get("database_evidence")
    ):
        raise Phase10BrowserReceiptError("Phase 10 browser durable evidence changed")


def _write_receipt(path: Path, document: Mapping[str, Any]) -> None:
    resolved = _inside(path, OUTPUT_ROOT, "receipt output", must_exist=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_suffix(resolved.suffix + ".tmp")
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, resolved)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        url = validate_boundary(args)
        receipt = seal_receipt(args, url)
        _write_receipt(args.output, receipt)
    except (OSError, RuntimeError, ValueError, psycopg.Error) as error:
        message = (
            str(error)
            if isinstance(error, Phase10BrowserReceiptError)
            else "Phase 10 browser receipt operation failed"
        )
        print(
            json.dumps(
                {"status": "PHASE10_BROWSER_RECEIPT_ERROR", "error": message},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "PHASE10_BROWSER_RECEIPT_READY",
                "target_project": TARGET_PROJECT,
                "product_release_id": receipt["product_release_id"],
                "active_generation": receipt["active_generation"],
                "request_id": receipt["database_evidence"]["request_id"],
                "query_id": receipt["database_evidence"]["query_id"],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
