"""Approved Semantic Request replay 테스트에 사용하는 결정론적 fixture를 만든다."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from uuid import UUID

from app.services.analysis.semantic_request import (
    ApprovedSemanticRequestSnapshot,
    create_approved_semantic_request_snapshot,
)
from app.services.context.package_types import ContextParameterBinding


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def approved_semantic_snapshot_fixture(
    *,
    execution_as_of: date = date(2026, 8, 2),
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-02",
    product_release_id: str = "fixture-product-release",
    semantic_release_id: str = "fixture-context-v1",
    permission_snapshot_id: str = "fixture-permission-at-approval",
) -> ApprovedSemanticRequestSnapshot:
    """공통 analysis runtime fixture와 동일한 metric·time·filter plan을 봉인한다."""

    identity: dict[str, object] = {
        "version": "ANSWERVICE-ANALYSIS-PLAN-v4",
        "operation": "aggregate",
        "output_metric_ids": ["reviewed_measure"],
        "dependency_metric_ids": ["reviewed_measure"],
        "dimension_fields": [],
        "filter_fields": [],
        "time_mode": "range",
        "time_fields": [
            {
                "asset_fqn": "serving.semantic.measure_events",
                "column": "recorded_on",
            }
        ],
        "time_bucket": "none",
        "period_parameters": [
            {"start_parameter": "window_start", "end_parameter": "window_end"}
        ],
        "snapshot_parameter": None,
        "result_limit": None,
        "query_strategy": "VIEW_REUSE",
        "joins": [],
        "context_package_hash": "a" * 64,
    }
    plan = {**identity, "checksum": _canonical_hash(identity)}
    return create_approved_semantic_request_snapshot(
        source_request_id=UUID("10000000-0000-0000-0000-000000000001"),
        query_execution_id=UUID("20000000-0000-0000-0000-000000000002"),
        artifact_id=UUID("30000000-0000-0000-0000-000000000003"),
        execution_as_of=execution_as_of,
        analysis_plan=plan,
        parameter_bindings=(
            ContextParameterBinding("window_start", "date", period_start),
            ContextParameterBinding("window_end", "date", period_end),
        ),
        dimension_member_receipts=(),
        release_receipt={
            "product_release_id": product_release_id,
            "permission_snapshot_id": permission_snapshot_id,
            "semantic_release_id": semantic_release_id,
            "context_release": semantic_release_id,
            "policy_version": "fixture-policy-v1",
            "catalog_checksum": "1" * 64,
            "canonical_checksum": "2" * 64,
            "runtime_projection_checksum": "3" * 64,
        },
    )
