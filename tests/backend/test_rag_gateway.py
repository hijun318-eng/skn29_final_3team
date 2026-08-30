from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.rag_gateway import InternalManualAgent, RagToolError


def _capability_search_response(query: str) -> dict[str, object]:
    return {
        "request_id": str(uuid4()),
        "query_hash": InternalManualAgent._capability_query_hash(query),
        "execution_state": {
            "p2_gate": "TECHNICALLY_VALIDATED",
            "production_integration": "LOCAL_DOCKER_VALIDATED",
        },
        "tool": {
            "tool_code": "internal-manual-search",
            "semantic_version": "1.0.0-rc1",
        },
        "retrieval_release": {
            "schema_version": "RagRetrievalRelease.v1",
            "model_revision": "text-embedding-3-large:d1024",
            "embedding_dimension": 1024,
        },
        "no_evidence": False,
        "results": [
            {
                "evidence_id": "POL-PRIVACY-001:1.0:1:chunk-1",
                "manual_id": "POL-PRIVACY-001",
                "approval_status": "APPROVED",
                "document_status": "WORKING_KNOWLEDGE",
                "score": 0.87,
                "content": "route receipt에는 포함되면 안 되는 내부 문서 본문",
            }
        ],
    }


def test_two_document_follow_up_preserves_approved_snapshot() -> None:
    assert InternalManualAgent.selected_document_limit(
        "REGULATION_CHECK",
        ("MANUAL-FACILITY", "MANUAL-SAFETY"),
    ) == 2
    assert InternalManualAgent.selected_document_limit(
        "REGULATION_CHECK",
        ("MANUAL-FACILITY",),
    ) == 1


def test_search_capability_calls_search_only_and_drops_document_body() -> None:
    agent = object.__new__(InternalManualAgent)
    calls: list[tuple[str, dict[str, object], str]] = []

    async def allow(_role: str) -> None:
        return None

    async def signed_post(
        path: str,
        payload: dict[str, object],
        role: str,
    ) -> dict[str, object]:
        calls.append((path, payload, role))
        return _capability_search_response(str(payload["query"]))

    agent._assert_enabled = allow  # type: ignore[method-assign]
    agent._signed_post = signed_post  # type: ignore[method-assign]

    candidate = asyncio.run(
        agent.search_capability("개인정보 유출 보고 절차", "analyst")
    )

    assert [item[0] for item in calls] == [
        "/v1/tools/internal-manual-search"
    ]
    assert calls[0][2] == "STAFF"
    assert candidate["matched"] is True
    assert candidate["model_revision"] == "text-embedding-3-large:d1024"
    assert "content" not in candidate
    assert "내부 문서 본문" not in repr(candidate)


def test_search_capability_rejects_unapproved_document_evidence() -> None:
    query = "개인정보 유출 보고 절차"
    response = _capability_search_response(query)
    response["results"][0]["approval_status"] = "NOT_APPROVED"  # type: ignore[index]

    with pytest.raises(RagToolError) as captured:
        InternalManualAgent._capability_candidate(
            response,
            expected_query_hash=InternalManualAgent._capability_query_hash(query),
        )

    assert captured.value.code == "RAG_CAPABILITY_EVIDENCE_INVALID"


def test_search_capability_rejects_response_for_another_query() -> None:
    response = _capability_search_response("개인정보 유출 보고 절차")

    with pytest.raises(RagToolError) as captured:
        InternalManualAgent._capability_candidate(
            response,
            expected_query_hash=InternalManualAgent._capability_query_hash(
                "객실 안전 점검 절차"
            ),
        )

    assert captured.value.code == "RAG_CAPABILITY_EVIDENCE_INVALID"
