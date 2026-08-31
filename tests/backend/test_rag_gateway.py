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


def _capability_search_response(
    query: str,
    *,
    dimension: int = 1024,
) -> dict[str, object]:
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
            "model_revision": f"embedding-release:d{dimension}",
            "embedding_dimension": dimension,
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
    assert candidate["model_revision"] == "embedding-release:d1024"
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


def test_search_capability_accepts_a_replacement_embedding_dimension() -> None:
    query = "객실 안전 점검 절차"

    candidate = InternalManualAgent._capability_candidate(
        _capability_search_response(query, dimension=1536),
        expected_query_hash=InternalManualAgent._capability_query_hash(query),
    )

    assert candidate["embedding_dimension"] == 1536
    assert candidate["model_revision"] == "embedding-release:d1536"


def test_runtime_receipt_requires_health_and_a_signed_catalog_call() -> None:
    agent = object.__new__(InternalManualAgent)
    calls: list[str] = []

    async def allow(_role: str) -> None:
        calls.append("registry")

    async def health(_path: str) -> dict[str, object]:
        calls.append("health")
        return {
            "status": "healthy",
            "embedding_api_configured": True,
            "model_revision": "embedding-release:d1536",
            "expected_dimension": 1536,
            "execution_state": {
                "p2_gate": "TECHNICALLY_VALIDATED",
                "production_integration": "LOCAL_DOCKER_VALIDATED",
            },
            "tool": {
                "tool_code": "internal-manual-search",
                "semantic_version": "1.2.0",
                "read_only": True,
                "destructive": False,
            },
        }

    async def signed_catalog(
        path: str,
        payload: dict[str, object],
        role: str,
    ) -> dict[str, object]:
        calls.append("signed-catalog")
        assert path == "/v1/tools/internal-manual-catalog"
        assert payload == {}
        assert role == "STAFF"
        return {"documents": []}

    agent._assert_enabled = allow  # type: ignore[method-assign]
    agent._get_json = health  # type: ignore[method-assign]
    agent._signed_post = signed_catalog  # type: ignore[method-assign]

    receipt = asyncio.run(agent.runtime_receipt("analyst"))

    assert calls == ["registry", "health", "signed-catalog"]
    assert receipt["embedding_dimension"] == 1536
    assert len(str(receipt["capability_hash"])) == 64
