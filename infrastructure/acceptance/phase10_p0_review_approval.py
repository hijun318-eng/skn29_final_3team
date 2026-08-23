#!/usr/bin/env python3
"""Record the explicit Phase 10 semantic and P0 Gold human approval.

This command changes only the versioned review candidate, the corrected v2
Gold cases, and their two repository manifests.  Product and semantic release
IDs deliberately remain absent until a later external same-release seal avoids
the source/product-ID circular reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from evals.p0_gold import canonical_sha256, validate_manifest  # noqa: E402
from metric_review_contract import validate_metric_review  # noqa: E402
from runtime_governance_draft import build_draft  # noqa: E402


REVIEWER = "urn:li:corpGroup:answervice_runtime_stewards"
SEMANTIC_PATH = ROOT / "evals" / "semantic_review" / "answervice_d2_metrics.v1.json"
GOLD_CASE_PATH = ROOT / "evals" / "p0_gold" / "answervice_v4_3.p0.candidate.v2.jsonl"
GOLD_MANIFEST_PATH = (
    ROOT / "evals" / "p0_gold" / "answervice_v4_3.p0.candidate.v2.manifest.json"
)
LEGACY_MANIFEST_PATH = (
    ROOT / "evals" / "p0_gold" / "answervice_v4_3.p0.draft.v1.manifest.json"
)
LEGACY_CASE_PATH = (
    ROOT / "evals" / "p0_gold" / "answervice_v4_3.p0.draft.v1.jsonl"
)
SQL_DIRECTORY = (
    ROOT
    / "infrastructure"
    / "database"
    / "releases"
    / "walkerhill_v4_3_20260815_derived_1"
    / "01_V4.3_생성_및_서빙_SQL"
    / "06_trino_serving"
)
ORIGINAL_SEMANTIC_SHA256 = (
    "73cbeb255572475dbcf84a7d8f2272c7b06daaaf24d9d80660ba37df7dcb3a1c"
)
ORIGINAL_CASE_SHA256 = (
    "df0a845af464ce2a837013ab9e7c87a05968d23694c6c5352801556b4796f5ab"
)


class Phase10ReviewApprovalError(RuntimeError):
    """The explicit approval scope or immutable candidate differs."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve", action="store_true", required=True)
    return parser.parse_args(argv)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Phase10ReviewApprovalError("approval input JSON is unavailable") from error
    if not isinstance(value, dict):
        raise Phase10ReviewApprovalError("approval input must be one JSON object")
    return value


def _cases(path: Path) -> list[dict[str, Any]]:
    try:
        values = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    except (OSError, json.JSONDecodeError) as error:
        raise Phase10ReviewApprovalError("approval Gold JSONL is unavailable") from error
    if not values or any(not isinstance(value, dict) for value in values):
        raise Phase10ReviewApprovalError("approval Gold cases are invalid")
    return values


def _timestamp(value: datetime | None = None) -> str:
    observed = value or datetime.now(ZoneInfo("Asia/Seoul"))
    if observed.tzinfo is None:
        raise Phase10ReviewApprovalError("approval timestamp requires a timezone")
    return observed.isoformat(timespec="seconds")


def approve_documents(
    semantic: Mapping[str, Any],
    manifest: Mapping[str, Any],
    cases: list[Mapping[str, Any]],
    *,
    reviewed_at: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Return exact approved copies after checking the authorized candidate scope."""

    semantic_copy = deepcopy(dict(semantic))
    manifest_copy = deepcopy(dict(manifest))
    case_copies = [deepcopy(dict(case)) for case in cases]
    if (
        canonical_sha256(semantic_copy) != ORIGINAL_SEMANTIC_SHA256
        or semantic_copy.get("review_status") != "REVIEW_REQUIRED"
        or semantic_copy.get("review_owner_candidate_urn") != REVIEWER
        or len(semantic_copy.get("metrics", ())) != 14
        or sum(
            item.get("visibility") == "BUSINESS"
            for item in semantic_copy.get("metrics", ())
        )
        != 10
        or sum(
            item.get("visibility") == "SUPPORT"
            for item in semantic_copy.get("metrics", ())
        )
        != 4
        or any(
            item.get("review_status") != "REVIEW_REQUIRED"
            or item.get("permission", {}).get("synthetic") is not True
            for item in semantic_copy.get("metrics", ())
        )
    ):
        raise Phase10ReviewApprovalError("semantic approval candidate scope differs")
    case_payload = _case_payload(case_copies)
    if (
        hashlib.sha256(case_payload).hexdigest() != ORIGINAL_CASE_SHA256
        or len(case_copies) != 55
        or any(
            case.get("review_status") != "REVIEW_REQUIRED"
            or case.get("reviewer") is not None
            or case.get("reviewed_at") is not None
            or case.get("blocker") is not None
            or case.get("is_synthetic") is not True
            or case.get("expected_result", {}).get("kind") == "UNSEALED"
            for case in case_copies
        )
        or manifest_copy.get("status") != "DRAFT"
        or manifest_copy.get("semantic_release_id") is not None
        or manifest_copy.get("product_release_id") is not None
        or manifest_copy.get("semantic_candidate_sha256")
        != ORIGINAL_SEMANTIC_SHA256
        or manifest_copy.get("case_content_sha256") != ORIGINAL_CASE_SHA256
    ):
        raise Phase10ReviewApprovalError("P0 Gold approval candidate scope differs")

    try:
        parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise Phase10ReviewApprovalError("approval timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise Phase10ReviewApprovalError("approval timestamp requires a timezone")

    semantic_copy.update(
        {
            "review_status": "APPROVED",
            "reviewer": REVIEWER,
            "reviewed_at": reviewed_at,
        }
    )
    for metric in semantic_copy["metrics"]:
        metric["review_status"] = "APPROVED"
    semantic_sha256 = canonical_sha256(semantic_copy)

    for case in case_copies:
        case.update(
            {
                "review_status": "APPROVED",
                "reviewer": REVIEWER,
                "reviewed_at": reviewed_at,
            }
        )
    approved_case_payload = _case_payload(case_copies)
    case_sha256 = hashlib.sha256(approved_case_payload).hexdigest()
    manifest_copy.update(
        {
            "semantic_candidate_sha256": semantic_sha256,
            "case_content_sha256": case_sha256,
        }
    )
    manifest_copy["provenance"]["notes"] = (
        "Domain-owner approved semantic mappings, intent and safety decisions, "
        "and independent result assertions; external same-release binding remains required."
    )
    summary = validate_manifest(
        manifest_copy,
        case_copies,
        semantic_copy,
        observed_case_content_sha256=case_sha256,
    )
    if (
        summary["status"] != "VALID_DRAFT"
        or summary["review_counts"] != {"APPROVED": 55}
        or summary["unsealed_result_count"] != 0
        or summary["scorable"] is not False
    ):
        raise Phase10ReviewApprovalError("approved P0 Gold draft validation differs")
    return semantic_copy, manifest_copy, case_copies


def _case_payload(cases: list[Mapping[str, Any]]) -> bytes:
    return "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for case in cases
    ).encode("utf-8")


def _write_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_bytes(
        path,
        (
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8"),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        parse_args(argv)
        semantic_source = _json(SEMANTIC_PATH)
        manifest_source = _json(GOLD_MANIFEST_PATH)
        case_source = _cases(GOLD_CASE_PATH)
        legacy = _json(LEGACY_MANIFEST_PATH)
        legacy_cases = _cases(LEGACY_CASE_PATH)
        if (
            legacy.get("status") != "DRAFT"
            or legacy.get("semantic_candidate_sha256")
            != ORIGINAL_SEMANTIC_SHA256
            or legacy.get("product_release_id") is not None
            or legacy.get("semantic_release_id") is not None
        ):
            raise Phase10ReviewApprovalError("legacy Gold semantic binding differs")
        reviewed_at = _timestamp()
        semantic, manifest, cases = approve_documents(
            semantic_source,
            manifest_source,
            case_source,
            reviewed_at=reviewed_at,
        )
        evidence = build_draft(
            SQL_DIRECTORY,
            str(semantic["serving_schema"]),
            str(semantic["release_id"]),
        )
        validation = validate_metric_review(semantic, evidence)
        if (
            validation["status"] != "VALID_APPROVED_REVIEW"
            or validation["business_metric_count"] != 10
            or validation["support_metric_count"] != 4
            or validation["publishable"] is not True
        ):
            raise Phase10ReviewApprovalError("approved semantic validation differs")

        approved_semantic_sha256 = canonical_sha256(semantic)
        legacy["semantic_candidate_sha256"] = approved_semantic_sha256
        legacy_case_sha256 = hashlib.sha256(
            LEGACY_CASE_PATH.read_bytes()
        ).hexdigest()
        legacy_validation = validate_manifest(
            legacy,
            legacy_cases,
            semantic,
            observed_case_content_sha256=legacy_case_sha256,
        )
        if legacy_validation["status"] != "VALID_DRAFT":
            raise Phase10ReviewApprovalError("legacy Gold draft validation differs")

        # 모든 입력·계약을 먼저 검증한 뒤에만 versioned 문서를 변경한다.
        _write_json(SEMANTIC_PATH, semantic)
        _write_bytes(GOLD_CASE_PATH, _case_payload(cases))
        _write_json(GOLD_MANIFEST_PATH, manifest)
        _write_json(LEGACY_MANIFEST_PATH, legacy)
        print(
            json.dumps(
                {
                    "status": "PHASE10_P0_REVIEW_APPROVED",
                    "reviewer": REVIEWER,
                    "reviewed_at": reviewed_at,
                    "semantic_candidate_sha256": approved_semantic_sha256,
                    "gold_case_sha256": hashlib.sha256(
                        _case_payload(cases)
                    ).hexdigest(),
                    "business_metric_count": 10,
                    "support_metric_count": 4,
                    "gold_case_count": 55,
                    "repository_manifest_status": "DRAFT_PENDING_EXTERNAL_RELEASE_SEAL",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "PHASE10_P0_REVIEW_APPROVAL_ERROR",
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
