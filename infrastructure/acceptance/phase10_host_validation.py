#!/usr/bin/env python3
"""Run and seal the mandatory current-host Phase 10 validation lane.

Only deterministic command metadata and output hashes are retained.  Raw test
logs, environment values, credentials, SQL, and application results are never
written into the receipt.  Live DataHub/Trino and browser evidence remain
separate Phase 10 axes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Mapping

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
ENV_FILE = ROOT / "infrastructure" / "database" / ".env"
OUTPUT_ROOT = ROOT / ".tmp"
WORK_ROOT = OUTPUT_ROOT / "phase10-host-validation"
RECEIPT_VERSION = "answervice.phase10_host_validation_receipt.v1"


class Phase10HostValidationError(RuntimeError):
    """The host validation boundary, command lane, or receipt differs."""


@dataclass(frozen=True)
class ValidationCheck:
    """One fixed, non-secret host validation command."""

    identifier: str
    command: tuple[str, ...]
    cwd: Path = ROOT
    timeout_seconds: float = 1800.0
    environment: Mapping[str, str] | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
        raise Phase10HostValidationError(
            "Phase 10 host validation database is outside the isolated boundary"
        )
    return url


def _inside(path: Path, root: Path, label: str, *, must_exist: bool) -> Path:
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=must_exist)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise Phase10HostValidationError(
            f"Phase 10 host validation {label} is outside the repository boundary"
        ) from error
    return resolved


def validate_boundary(args: argparse.Namespace) -> URL:
    if args.target_project != TARGET_PROJECT:
        raise Phase10HostValidationError(
            "Phase 10 host validation target project is outside the approved boundary"
        )
    try:
        env_file = args.env_file.resolve(strict=True)
    except OSError as error:
        raise Phase10HostValidationError(
            "Phase 10 host validation environment file is unavailable"
        ) from error
    if env_file != ENV_FILE.resolve(strict=True) or not env_file.is_file():
        raise Phase10HostValidationError(
            "Phase 10 host validation environment file differs"
        )
    output = _inside(args.output, OUTPUT_ROOT, "receipt output", must_exist=False)
    if output.suffix.lower() != ".json":
        raise Phase10HostValidationError(
            "Phase 10 host validation receipt output must be JSON"
        )
    return _database_url(args.database_url)


def _connect(url: URL) -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        row_factory=dict_row,
    )


def _active_release(url: URL) -> tuple[ProductReleaseEvidenceManifest, int]:
    with _connect(url) as connection:
        row = connection.execute(
            """
            SELECT a.generation, m.manifest_json
            FROM governance.runtime_catalog_active_pointer a
            JOIN governance.product_release_manifests m
              ON m.product_release_id = a.product_release_id
            WHERE a.pointer_name = 'analysis'
            """
        ).fetchone()
    if row is None:
        raise Phase10HostValidationError("Phase 10 active product release is unavailable")
    try:
        manifest = ProductReleaseEvidenceManifest.model_validate(row["manifest_json"])
    except (KeyError, TypeError, ValueError) as error:
        raise Phase10HostValidationError(
            "Phase 10 active product release is invalid"
        ) from error
    if not manifest.product_release_id.startswith(PHASE10_PREFIX):
        raise Phase10HostValidationError("Phase 10 active product release identity differs")
    return manifest, int(row["generation"])


def _compose_command(*arguments: str) -> tuple[str, ...]:
    return (
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        *arguments,
        "config",
        "--quiet",
    )


def validation_checks(source: SourceReceipt) -> tuple[ValidationCheck, ...]:
    """Return the immutable host lane required by the execution strategy."""

    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    npm = "npm.cmd" if os.name == "nt" else "npm"
    compile_environment = {
        "PYTHONPYCACHEPREFIX": str(WORK_ROOT / "pycache"),
    }
    candidate_environment = {
        "PHASE10_SOURCE_COMMIT_SHA": source.commit_sha,
        "PHASE10_SOURCE_DIRTY": str(source.dirty).lower(),
        "PHASE10_SOURCE_PATCH_SHA256": source.dirty_patch_sha256 or "",
        "PHASE10_DATAHUB_READ_API_TOKEN": "validation-only-not-a-token",
        "PHASE10_DATAHUB_READ_ACTOR_URN": "urn:li:corpuser:validation-only",
    }
    return (
        ValidationCheck(
            "openapi_contract",
            (python, "app/backend/scripts/export_openapi.py", "--check"),
        ),
        ValidationCheck(
            "code_documentation",
            (python, "scripts/check_code_documentation.py"),
        ),
        ValidationCheck(
            "architecture_invariants",
            (python, "scripts/lint_architectural_invariants.py"),
        ),
        ValidationCheck(
            "repository_integrity",
            (python, "scripts/audit_repository_integrity.py"),
        ),
        ValidationCheck(
            "python_compileall",
            (
                python,
                "-m",
                "compileall",
                "-q",
                "app/backend",
                "src",
                "infrastructure/database/datahub",
                "infrastructure/acceptance",
                "scripts",
                "evals",
                "tests",
            ),
            environment=compile_environment,
        ),
        ValidationCheck(
            "python_full_suite",
            (
                python,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(WORK_ROOT / "pytest"),
                "tests",
                "-q",
                "-ra",
            ),
            timeout_seconds=2400.0,
        ),
        ValidationCheck(
            "frontend_full_suite",
            (npm, "run", "test"),
            cwd=ROOT / "app" / "frontend",
            timeout_seconds=600.0,
        ),
        ValidationCheck(
            "frontend_production_build",
            (
                npm,
                "run",
                "build",
                "--",
                "--outDir",
                str(WORK_ROOT / "frontend-dist"),
                "--emptyOutDir",
            ),
            cwd=ROOT / "app" / "frontend",
            timeout_seconds=600.0,
        ),
        ValidationCheck("compose_dev", _compose_command("--profile", "dev")),
        ValidationCheck("compose_full", _compose_command("--profile", "full")),
        ValidationCheck(
            "compose_split_host",
            _compose_command("--profile", "split-host"),
        ),
        ValidationCheck(
            "compose_semantic_search",
            _compose_command(
                "-f",
                str(ROOT / "compose.yml"),
                "-f",
                str(
                    ROOT
                    / "infrastructure"
                    / "database"
                    / "datahub"
                    / "compose.semantic-search.yml"
                ),
                "--profile",
                "full",
                "--profile",
                "semantic-search",
            ),
        ),
        ValidationCheck(
            "compose_metadata_ingestion",
            _compose_command("--profile", "full", "--profile", "metadata-ingestion"),
        ),
        ValidationCheck(
            "compose_phase10_candidate",
            (
                "docker",
                "compose",
                "-p",
                TARGET_PROJECT,
                "--env-file",
                str(ENV_FILE),
                "-f",
                str(ROOT / "infrastructure" / "acceptance" / "phase10-candidate.compose.yml"),
                "config",
                "--quiet",
            ),
            environment=candidate_environment,
        ),
        ValidationCheck("git_diff_check", ("git", "diff", "--check")),
    )


def _output_sha256(stdout: str | None, stderr: str | None) -> str:
    return hashlib.sha256(
        ((stdout or "") + "\n" + (stderr or "")).encode("utf-8")
    ).hexdigest()


def _run_check(check: ValidationCheck) -> dict[str, Any]:
    print(f"CHECK_START {check.identifier}", flush=True)
    environment = os.environ.copy()
    if check.environment:
        environment.update(check.environment)
    started = monotonic()
    process = subprocess.run(
        list(check.command),
        cwd=check.cwd,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=check.timeout_seconds,
    )
    duration_ms = int((monotonic() - started) * 1000)
    result = {
        "check_id": check.identifier,
        "status": "PASSED" if process.returncode == 0 else "FAILED",
        "exit_code": process.returncode,
        "duration_ms": duration_ms,
        "output_sha256": _output_sha256(process.stdout, process.stderr),
    }
    print(f"CHECK_{result['status']} {check.identifier} {duration_ms}ms", flush=True)
    return result


def run_validation(url: URL) -> dict[str, Any]:
    source, _created_at = _source_receipt()
    manifest, generation = _active_release(url)
    if manifest.evidence.source != source:
        raise Phase10HostValidationError(
            "Phase 10 host source differs from the active candidate release"
        )
    checks = [_run_check(check) for check in validation_checks(source)]
    failed = sorted(
        check["check_id"] for check in checks if check["status"] != "PASSED"
    )
    payload: dict[str, Any] = {
        "schema_version": RECEIPT_VERSION,
        "verified": not failed,
        "target_project": TARGET_PROJECT,
        "product_release_id": manifest.product_release_id,
        "active_generation": generation,
        "source": source.model_dump(mode="json"),
        "checks": checks,
        "failed_check_ids": failed,
        "historical_evidence_mixed": False,
        "skipped_evidence_count": 0,
        "sealed_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["receipt_sha256"] = canonical_sha256(payload)
    return payload


def validate_receipt(
    document: Mapping[str, Any],
    *,
    active_manifest: ProductReleaseEvidenceManifest,
    active_generation: int,
    current_source: SourceReceipt,
) -> None:
    checksum = document.get("receipt_sha256")
    payload = {key: value for key, value in document.items() if key != "receipt_sha256"}
    checks = document.get("checks")
    expected_ids = {check.identifier for check in validation_checks(current_source)}
    observed_ids = {
        str(check.get("check_id"))
        for check in checks
        if isinstance(check, Mapping)
    } if isinstance(checks, list) else set()
    if (
        document.get("schema_version") != RECEIPT_VERSION
        or document.get("verified") is not True
        or document.get("target_project") != TARGET_PROJECT
        or document.get("product_release_id") != active_manifest.product_release_id
        or document.get("active_generation") != active_generation
        or document.get("source") != current_source.model_dump(mode="json")
        or observed_ids != expected_ids
        or not isinstance(checks, list)
        or any(
            not isinstance(check, Mapping)
            or check.get("status") != "PASSED"
            or check.get("exit_code") != 0
            or not isinstance(check.get("output_sha256"), str)
            or len(check["output_sha256"]) != 64
            for check in checks
        )
        or document.get("failed_check_ids") != []
        or document.get("historical_evidence_mixed") is not False
        or document.get("skipped_evidence_count") != 0
        or not isinstance(checksum, str)
        or checksum != canonical_sha256(payload)
    ):
        raise Phase10HostValidationError("Phase 10 host validation receipt differs")


def _write_receipt(path: Path, document: Mapping[str, Any]) -> None:
    resolved = _inside(path, OUTPUT_ROOT, "receipt output", must_exist=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_suffix(resolved.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, resolved)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        url = validate_boundary(args)
        receipt = run_validation(url)
        _write_receipt(args.output, receipt)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, psycopg.Error) as error:
        message = (
            str(error)
            if isinstance(error, Phase10HostValidationError)
            else "Phase 10 host validation operation failed"
        )
        print(
            json.dumps(
                {"status": "PHASE10_HOST_VALIDATION_ERROR", "error": message},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": (
                    "PHASE10_HOST_VALIDATION_VERIFIED"
                    if receipt["verified"]
                    else "PHASE10_HOST_VALIDATION_FAILED"
                ),
                "target_project": TARGET_PROJECT,
                "product_release_id": receipt["product_release_id"],
                "active_generation": receipt["active_generation"],
                "check_count": len(receipt["checks"]),
                "failed_check_ids": receipt["failed_check_ids"],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if receipt["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
