"""Phase 10 approved semantic core와 external release seal 계약을 검증한다."""

from __future__ import annotations

import copy

import pytest

from evals.p0_gold import canonical_sha256
from infrastructure.acceptance import phase10_p0_release_seal as seal


def _candidate() -> dict:
    return {
        "metrics": [
            {
                "id": "sample_revenue",
                "name": "Sample Revenue",
                "visibility": "BUSINESS",
                "review_status": "APPROVED",
                "definition": "승인 기간의 synthetic sample revenue 합계다.",
                "formula": {
                    "kind": "COLUMN",
                    "aggregation": "sum",
                    "reduction": "sum",
                },
                "source": {
                    "kind": "COLUMN",
                    "asset_fqn": "serving.sample.daily",
                    "column": "revenue",
                },
                "grain": {
                    "kind": "periodic",
                    "keys": ["business_date", "hotel_code"],
                    "dimensions": ["hotel_code"],
                },
                "time": {
                    "field": "business_date",
                    "semantics": "BUSINESS_DATE",
                    "timezone": "Asia/Seoul",
                    "interval": "[start,end)",
                    "bucket": "day",
                    "timezone_mode": "preserve",
                },
                "join": {"required": False, "allowed_edge_ids": []},
                "aliases": ["sample revenue"],
                "permission": {
                    "roles": ["analyst"],
                    "contains_pii": False,
                    "synthetic": True,
                },
                "unit": "KRW",
                "result_field": "sample_revenue_krw",
                "query_strategies": ["VIEW_REUSE"],
            }
        ]
    }


def _bundle() -> dict:
    return {
        "metric_rules": [
            {
                "id": "sample_revenue",
                "aggregation": "sum",
                "reduction": "sum",
                "result_field": "sample_revenue_krw",
                "unit": "KRW",
                "source": {
                    "kind": "column",
                    "field": {
                        "asset_fqn": "serving.sample.daily",
                        "column": "revenue",
                    },
                },
                "governance": {
                    "visibility": "BUSINESS",
                    "semantic": {
                        "name": "Sample Revenue",
                        "definition": "승인 기간의 synthetic sample revenue 합계다.",
                        "aliases": ["Sample Revenue", "sample revenue"],
                    },
                    "grain": {
                        "kind": "periodic",
                        "keys": ["hotel_code", "business_date"],
                        "dimensions": ["hotel_code"],
                    },
                    "time": {
                        "field": "business_date",
                        "semantics": "BUSINESS_DATE",
                        "timezone": "Asia/Seoul",
                        "interval": "[start,end)",
                    },
                    "join": {
                        "required": False,
                        "allowed_edge_ids": ["phase9_sample_edge"],
                    },
                    "permission": {
                        "roles": ["analyst"],
                        "contains_pii": False,
                        "synthetic": True,
                    },
                    "query_strategies": [
                        "RAW_APPROVED_DETAIL",
                        "VIEW_REUSE",
                    ],
                },
            }
        ],
        "metric_terms": [
            {
                "id": "sample_revenue",
                "name": "Sample Revenue",
                "definition": "승인 기간의 synthetic sample revenue 합계다.",
                "aliases": ["Sample Revenue", "sample revenue"],
                "unit": "KRW",
                "approval_status": "APPROVED",
                "owner_urn": seal.REVIEWER,
            }
        ],
        "time_rules": {
            "timezone": "Asia/Seoul",
            "interval": "[start,end)",
            "fields": [
                {
                    "field": {
                        "asset_fqn": "serving.sample.daily",
                        "column": "business_date",
                    },
                    "bucket": "day",
                    "timezone_mode": "preserve",
                }
            ],
        },
    }


def test_binding_keeps_approved_core_exact_and_exposes_phase9_addition() -> None:
    binding = seal.semantic_runtime_binding(_candidate(), _bundle())

    assert binding["core_exact"] is True
    assert binding["approved_core_sha256"] == binding["runtime_core_sha256"]
    assert binding["capability_extension"]["mode"] == (
        "APPROVED_CORE_PLUS_PHASE9_ADDITIVE_CAPABILITY"
    )
    assert binding["capability_extension"]["metrics"] == [
        {
            "metric_id": "sample_revenue",
            "added_join_ids": ["phase9_sample_edge"],
            "added_query_strategies": ["RAW_APPROVED_DETAIL"],
        }
    ]


def test_binding_rejects_semantic_change_or_runtime_narrowing() -> None:
    changed = _bundle()
    changed["metric_rules"][0]["governance"]["semantic"]["definition"] = "changed"
    with pytest.raises(seal.Phase10P0ReleaseSealError, match="definition"):
        seal.semantic_runtime_binding(_candidate(), changed)

    narrowed = _bundle()
    narrowed["metric_rules"][0]["governance"]["query_strategies"] = [
        "RAW_APPROVED_DETAIL"
    ]
    with pytest.raises(seal.Phase10P0ReleaseSealError, match="narrows"):
        seal.semantic_runtime_binding(_candidate(), narrowed)


def test_release_seal_receipt_checksum_rejects_tampering() -> None:
    binding = seal.semantic_runtime_binding(_candidate(), _bundle())
    document = {
        "schema_version": seal.SEAL_VERSION,
        "status": "SEALED",
        "target_project": seal.TARGET_PROJECT,
        "content_notice": seal.SYNTHETIC_NOTICE,
        "semantic_binding": binding,
        "gold": {"status": "VALID_SEALED_GOLD", "scorable": True},
        "historical_evidence_mixed": False,
        "skipped_evidence_count": 0,
    }
    document["receipt_sha256"] = canonical_sha256(document)
    seal.validate_release_seal_receipt(document)

    tampered = copy.deepcopy(document)
    tampered["gold"]["scorable"] = False
    with pytest.raises(seal.Phase10P0ReleaseSealError, match="receipt"):
        seal.validate_release_seal_receipt(tampered)


def test_boundary_rejects_the_existing_answervice_database() -> None:
    accepted = seal.parse_args(
        [
            "--target-project",
            seal.TARGET_PROJECT,
            "--database-url",
            "postgresql+psycopg://phase10_runtime@127.0.0.1:55440/"
            "phase10_p0_same_release_acceptance",
        ]
    )
    seal.validate_boundary(accepted)

    rejected = seal.parse_args(
        [
            "--target-project",
            "answervice",
            "--database-url",
            "postgresql+psycopg://phase10_runtime@127.0.0.1:55440/"
            "phase10_p0_same_release_acceptance",
        ]
    )
    with pytest.raises(seal.Phase10P0ReleaseSealError, match="target project"):
        seal.validate_boundary(rejected)
