from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
import hashlib
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.rag_router import get_internal_manual_source
from app.contracts import RequestContext
from app.services.rag_gateway import (
    InternalManualAgent,
    RagToolError,
    RAG_SOURCE_MAX_BODY_BYTES,
    RAG_TOOL_CODE,
    RAG_TOOL_DESCRIPTOR,
    RAG_TOOL_DESCRIPTION,
    RAG_TOOL_ID,
    RAG_TOOL_INPUT_SCHEMA,
    RAG_TOOL_OUTPUT_SCHEMA,
    RAG_TOOL_ROLES,
    RAG_TOOL_SEMANTIC_VERSION,
    RAG_TOOL_TIMEOUT_SECONDS,
    RAG_TOOL_TRANSPORT,
)
from src.rag.vector_application import VectorRagApplication


def _registry_receipt() -> dict[str, object]:
    return {
        "tool_id": RAG_TOOL_ID,
        "tool_code": RAG_TOOL_CODE,
        "semantic_version": RAG_TOOL_SEMANTIC_VERSION,
        "title": RAG_TOOL_DESCRIPTOR["title"],
        "description": RAG_TOOL_DESCRIPTION,
        "input_schema_json": RAG_TOOL_INPUT_SCHEMA,
        "output_schema_json": RAG_TOOL_OUTPUT_SCHEMA,
        "annotations_json": RAG_TOOL_DESCRIPTOR["annotations"],
        "transport": RAG_TOOL_TRANSPORT,
        "timeout_seconds": RAG_TOOL_TIMEOUT_SECONDS,
        "required_roles_json": list(RAG_TOOL_ROLES),
        "is_enabled": True,
    }


def test_rag_descriptor_includes_current_mcp_public_metadata() -> None:
    assert RAG_TOOL_DESCRIPTOR["title"] == "Answer from Internal Documents"
    assert RAG_TOOL_DESCRIPTOR["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }


def test_gateway_answer_evidence_matches_runtime_closed_contract() -> None:
    projected = InternalManualAgent._evidence_block(
        {
            "evidence_id": "MANUAL-ONE:1.0:1:chunk-1",
            "content": "승인된 근거 본문",
            "title": "업무 매뉴얼",
            "manual_id": "MANUAL-ONE",
            "version": "1.0",
            "document_type": "MANUAL",
            "owner_team": "OPERATIONS",
            "section_title": "1. 승인 절차",
            "page_start": 1,
            "citation": "MANUAL-ONE p.1",
        }
    )

    assert set(projected) == {
        "evidence_id",
        "text",
        "title",
        "manual_id",
        "version",
        "document_type",
        "owner_team",
        "section_title",
        "citation",
    }
    assert VectorRagApplication._validated_answer_evidence([projected]) == [
        projected
    ]


def test_gateway_binds_normalized_query_trace_and_actor_across_search_answer() -> None:
    agent = object.__new__(InternalManualAgent)
    calls: list[tuple[str, dict[str, object], str]] = []
    actor_id = uuid4()
    trace_id = "trace-rag-user-request"
    retrieval_request_id = str(uuid4())

    async def allow(_role: str) -> None:
        return None

    async def record(*_args: object, **_kwargs: object) -> None:
        return None

    async def signed_post(
        path: str,
        payload: dict[str, object],
        role: str,
    ) -> dict[str, object]:
        calls.append((path, payload, role))
        if path.endswith("internal-manual-search"):
            return {
                "request_id": retrieval_request_id,
                "trace_id": trace_id,
                "answer_query": payload["resolved_question"],
                "retrieval_release": {
                    "schema_version": "RagRetrievalRelease.v2",
                    "release_id": str(uuid4()),
                    "model_revision": "text-embedding-3-large:d1024",
                    "embedding_dimension": 1024,
                    "corpus_manifest_sha256": "b" * 64,
                    "processing_profile_sha256": "c" * 64,
                },
                "no_evidence": False,
                "results": [
                    {
                        "evidence_id": "MANUAL-ONE:1.0:1:chunk-1",
                        "manual_id": "MANUAL-ONE",
                        "title": "업무 매뉴얼",
                        "version": "1.0",
                        "document_type": "MANUAL",
                        "owner_team": "OPERATIONS",
                        "page_start": 1,
                        "page_end": 1,
                        "section_title": "승인 절차",
                        "content": "승인된 근거 본문",
                        "snippet": "승인된 근거 본문",
                        "citation": "[업무 매뉴얼 v1.0 p.1 승인 절차]",
                        "score": 0.9,
                        "validity_status": "VALID",
                    }
                ],
                "processing_steps": ["DOCUMENT_SEARCHED"],
                "agent": "INTERNAL_GUIDELINE",
            }
        return {
            "status": "ANSWER",
            "request_id": str(uuid4()),
            "trace_id": trace_id,
            "answer": "승인된 근거 답변",
            "answer_type": "POLICY",
            "citations": [
                {
                    "evidence_id": "MANUAL-ONE:1.0:1:chunk-1",
                    "citation": "[업무 매뉴얼 v1.0 p.1 승인 절차]",
                }
            ],
        }

    agent._assert_enabled = allow  # type: ignore[method-assign]
    agent._record = record  # type: ignore[method-assign]
    agent._signed_post = signed_post  # type: ignore[method-assign]

    result = asyncio.run(
        agent.execute(
            "  객실 승인 절차  ",
            actor_id,
            "analyst",
            trace_id,
        )
    )

    expected_actor_hash = hashlib.sha256(
        str(actor_id).encode("utf-8")
    ).hexdigest()
    assert result["status"] == "ANSWER"
    assert [path for path, _payload, _role in calls] == [
        "/v1/tools/internal-manual-search",
        "/v1/tools/internal-manual-answer",
    ]
    assert calls[0][1]["resolved_question"] == "객실 승인 절차"
    assert calls[0][1]["top_k"] == 3
    assert calls[1][1]["query"] == calls[0][1]["resolved_question"]
    assert calls[1][1]["retrieval_request_id"] == retrieval_request_id
    assert calls[0][1]["trace_id"] == calls[1][1]["trace_id"] == trace_id
    assert (
        calls[0][1]["actor_hash"]
        == calls[1][1]["actor_hash"]
        == expected_actor_hash
    )


def test_gateway_adds_context_labels_only_when_previous_utterances_exist() -> None:
    agent = object.__new__(InternalManualAgent)
    calls: list[dict[str, object]] = []
    trace_id = "trace-rag-follow-up"

    async def signed_post(
        path: str,
        payload: dict[str, object],
        _role: str,
    ) -> dict[str, object]:
        calls.append(payload)
        if path.endswith("internal-manual-search"):
            return {
                "request_id": str(uuid4()),
                "trace_id": trace_id,
                "answer_query": payload["resolved_question"],
                "retrieval_release": {
                    "schema_version": "RagRetrievalRelease.v2",
                    "release_id": str(uuid4()),
                    "model_revision": "text-embedding-3-large:d1024",
                    "embedding_dimension": 1024,
                    "corpus_manifest_sha256": "b" * 64,
                    "processing_profile_sha256": "c" * 64,
                },
                "no_evidence": True,
                "results": [],
                "processing_steps": ["DOCUMENT_SEARCHED"],
            }
        raise AssertionError("근거 없음 검색은 answer endpoint를 호출하지 않아야 합니다.")

    agent._signed_post = signed_post  # type: ignore[method-assign]

    asyncio.run(
        agent._execute_runtime(
            "원인을 찾아줘",
            uuid4(),
            "analyst",
            trace_id,
            recent_utterances=("2026년 7월과 8월 객실 점유율 분석",),
        )
    )

    assert calls[0]["resolved_question"] == (
        "이전 질문: 2026년 7월과 8월 객실 점유율 분석\n"
        "현재 질문: 원인을 찾아줘"
    )


def test_gateway_removes_internal_evidence_ids_from_answer_body() -> None:
    assert InternalManualAgent._answer_body(
        "- 원인 설명 [REPORT-2026-08-ROOMS:2026-08:3:chunk-1]"
    ) == "- 원인 설명"


def _runtime_health() -> dict[str, object]:
    return {
        "status": "healthy",
        "embedding_api_configured": True,
        "embedding_provider": "openai",
        "model_id": "embedding-model",
        "model_revision": "embedding-release:d1536",
        "expected_dimension": 1536,
        "corpus_manifest_sha256": "b" * 64,
        "processing_profile_sha256": "c" * 64,
        "active_corpus_release": {
            "release_id": str(uuid4()),
            "provider": "openai",
            "model": "embedding-model",
            "dimensions": 1536,
            "version": "embedding-release:d1536",
            "corpus_manifest_sha256": "b" * 64,
            "processing_profile_sha256": "c" * 64,
            "document_count": 1,
            "approved_document_count": 1,
            "chunk_count": 2,
        },
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
            "schema_version": "RagRetrievalRelease.v2",
            "release_id": str(uuid4()),
            "model_revision": f"embedding-release:d{dimension}",
            "embedding_dimension": dimension,
            "corpus_manifest_sha256": "b" * 64,
            "processing_profile_sha256": "c" * 64,
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


def test_public_tool_output_projects_rich_answer_to_closed_contract() -> None:
    rich_output = {
        "status": "ANSWER",
        "response_status": "ANSWERED",
        "answer_type": "POLICY",
        "answer_id": str(uuid4()),
        "answer": {"text": "승인된 근거 답변", "internal": "drop"},
        "agent": "INTERNAL_GUIDELINE",
        "processing_steps": ["SEARCHED", "ANSWERED"],
        "evidence_bundle": [
            {
                "evidence_id": "POL-PRIVACY-001:1.0:1:chunk-1",
                "document_id": "POL-PRIVACY-001",
                "document_name": "개인정보 보고 지침",
                "document_version": "1.0",
                "page_start": 1,
                "page_end": 1,
                "section": "1. 보고",
                "snippet": "즉시 보고한다.",
                "score": 0.91,
                "confidence": "MEDIUM",
            }
        ],
        "citations": [
            {
                "evidence_id": "POL-PRIVACY-001:1.0:1:chunk-1",
                "citation": "POL-PRIVACY-001 p.1",
                "internal": "drop",
            }
        ],
        "request_id": str(uuid4()),
        "trace_id": "trace-rag-answer",
        "routing": {"intent": "REGULATION_CHECK"},
        "document": {"body": "승인된 근거 답변"},
    }

    public = InternalManualAgent.public_tool_output(rich_output)

    Draft202012Validator(RAG_TOOL_OUTPUT_SCHEMA).validate(public)
    assert public == {
        "status": "ANSWER",
        "trace_id": "trace-rag-answer",
        "answer": {"text": "승인된 근거 답변"},
        "citations": [
            {
                "evidence_id": "POL-PRIVACY-001:1.0:1:chunk-1",
                "citation": "POL-PRIVACY-001 p.1",
            }
        ],
        "evidence_bundle": [
            {
                "evidence_id": "POL-PRIVACY-001:1.0:1:chunk-1",
                "document_id": "POL-PRIVACY-001",
                "document_name": "개인정보 보고 지침",
                "section": "1. 보고",
                "snippet": "즉시 보고한다.",
                "score": 0.91,
            }
        ],
    }


@pytest.mark.parametrize(
    "rich_output",
    [
        {
            "status": "NO_EVIDENCE",
            "response_status": "NO_EVIDENCE",
            "answer_type": "SUMMARY",
            "answer": {"text": "근거를 찾지 못했습니다."},
            "document": {"body": "근거를 찾지 못했습니다."},
            "citations": [],
            "evidence_bundle": [],
            "processing_steps": ["NO_EVIDENCE_RETURNED"],
            "trace_id": "trace-no-evidence",
        },
        {
            "status": "CONFLICT",
            "answer_id": str(uuid4()),
            "trace_id": "trace-conflict",
            "processing_steps": ["CONFLICT_DETECTED"],
            "conflicts": [
                {
                    "description": "두 지침의 적용 시점이 다릅니다.",
                    "evidence_ids": ["evidence-old", "evidence-new"],
                    "internal": "drop",
                }
            ],
            "evidence_bundle": [],
        },
    ],
)
def test_public_tool_output_projects_non_answer_states(
    rich_output: dict[str, object],
) -> None:
    public = InternalManualAgent.public_tool_output(rich_output)

    Draft202012Validator(RAG_TOOL_OUTPUT_SCHEMA).validate(public)
    assert "response_status" not in public
    assert "processing_steps" not in public


def test_public_tool_output_rejects_unadvertised_error_as_success_payload() -> None:
    with pytest.raises(RagToolError) as captured:
        InternalManualAgent.public_tool_output(
            {
                "status": "ERROR",
                "trace_id": "trace-error",
                "answer": {"text": "dependency failed"},
                "citations": [],
                "evidence_bundle": [],
            }
        )

    assert captured.value.code == "RAG_PUBLIC_OUTPUT_INVALID"
    assert captured.value.status_code == 502


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
    assert isinstance(calls[0][1]["trace_id"], str)
    assert len(str(calls[0][1]["actor_hash"])) == 64
    assert candidate["matched"] is True
    assert candidate["model_revision"] == "embedding-release:d1024"
    assert "content" not in candidate
    assert "내부 문서 본문" not in repr(candidate)


def test_search_capability_retries_one_transient_registry_read() -> None:
    agent = object.__new__(InternalManualAgent)
    registry_attempts = 0
    search_attempts = 0

    async def transient_registry(_role: str) -> None:
        nonlocal registry_attempts
        registry_attempts += 1
        if registry_attempts == 1:
            raise RagToolError(
                "RAG_REGISTRY_UNAVAILABLE",
                "RAG Tool Registry를 확인하지 못했습니다.",
            )

    async def signed_post(
        _path: str,
        payload: dict[str, object],
        _role: str,
    ) -> dict[str, object]:
        nonlocal search_attempts
        search_attempts += 1
        return _capability_search_response(str(payload["query"]))

    agent._assert_enabled = transient_registry  # type: ignore[method-assign]
    agent._signed_post = signed_post  # type: ignore[method-assign]

    candidate = asyncio.run(
        agent.search_capability("개인정보 유출 보고 절차", "analyst")
    )

    assert candidate["matched"] is True
    assert registry_attempts == 2
    assert search_attempts == 1


def test_search_capability_retries_one_transient_transport_failure() -> None:
    agent = object.__new__(InternalManualAgent)
    search_attempts = 0

    async def allow(_role: str) -> None:
        return None

    async def transient_post(
        _path: str,
        payload: dict[str, object],
        _role: str,
    ) -> dict[str, object]:
        nonlocal search_attempts
        search_attempts += 1
        if search_attempts == 1:
            raise httpx.ConnectError("temporary RAG connection failure")
        return _capability_search_response(str(payload["query"]))

    agent._assert_enabled = allow  # type: ignore[method-assign]
    agent._signed_post = transient_post  # type: ignore[method-assign]

    candidate = asyncio.run(
        agent.search_capability("개인정보 유출 보고 절차", "analyst")
    )

    assert candidate["matched"] is True
    assert search_attempts == 2


def test_search_capability_does_not_retry_non_transient_registry_rejection() -> None:
    agent = object.__new__(InternalManualAgent)
    registry_attempts = 0

    async def disabled_registry(_role: str) -> None:
        nonlocal registry_attempts
        registry_attempts += 1
        raise RagToolError("RAG_TOOL_DISABLED", "RAG Tool이 승인되지 않았습니다.")

    agent._assert_enabled = disabled_registry  # type: ignore[method-assign]

    with pytest.raises(RagToolError) as captured:
        asyncio.run(agent.search_capability("개인정보 유출 보고 절차", "analyst"))

    assert captured.value.code == "RAG_TOOL_DISABLED"
    assert registry_attempts == 1


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "RagRetrievalRelease.v1"),
        ("release_id", "not-a-uuid"),
        ("model_revision", ""),
        ("embedding_dimension", True),
        ("embedding_dimension", 0),
        ("corpus_manifest_sha256", "B" * 64),
        ("processing_profile_sha256", "short"),
    ],
)
def test_search_contract_rejects_invalid_v2_release_fields(
    field: str,
    value: object,
) -> None:
    search = _capability_search_response("객실 안전 점검 절차")
    search["retrieval_release"][field] = value  # type: ignore[index]

    with pytest.raises(RagToolError) as captured:
        InternalManualAgent._validate_search_contract(search)

    assert captured.value.code == "RAG_OUTPUT_INVALID"
    assert captured.value.status_code == 502


def test_search_contract_rejects_open_v2_release_object() -> None:
    search = _capability_search_response("객실 안전 점검 절차")
    search["retrieval_release"]["unexpected"] = "drift"  # type: ignore[index]

    with pytest.raises(RagToolError) as captured:
        InternalManualAgent._validate_search_contract(search)

    assert captured.value.code == "RAG_OUTPUT_INVALID"


def test_runtime_receipt_requires_health_and_a_signed_catalog_call() -> None:
    agent = object.__new__(InternalManualAgent)
    calls: list[str] = []

    async def allow(_role: str) -> None:
        calls.append("registry")

    async def health(_path: str) -> dict[str, object]:
        calls.append("health")
        return _runtime_health()

    async def signed_catalog(
        path: str,
        payload: dict[str, object],
        role: str,
    ) -> dict[str, object]:
        calls.append("signed-catalog")
        assert path == "/v1/tools/internal-manual-catalog"
        assert payload == {}
        assert role == "STAFF"
        return {"documents": [{"manual_id": "MANUAL-ONE"}]}

    agent._assert_enabled = allow  # type: ignore[method-assign]
    agent._get_json = health  # type: ignore[method-assign]
    agent._signed_post = signed_catalog  # type: ignore[method-assign]

    receipt = asyncio.run(agent.runtime_receipt("analyst"))

    assert calls == ["registry", "health", "signed-catalog"]
    assert receipt["embedding_dimension"] == 1536
    assert receipt["corpus_manifest_sha256"] == "b" * 64
    assert receipt["processing_profile_sha256"] == "c" * 64
    assert len(str(receipt["capability_hash"])) == 64


def test_runtime_receipt_rejects_empty_policy_filtered_catalog() -> None:
    agent = object.__new__(InternalManualAgent)

    async def allow(_role: str) -> None:
        return None

    async def health(_path: str) -> dict[str, object]:
        return _runtime_health()

    async def empty_catalog(
        _path: str,
        _payload: dict[str, object],
        _role: str,
    ) -> dict[str, object]:
        return {"documents": []}

    agent._assert_enabled = allow  # type: ignore[method-assign]
    agent._get_json = health  # type: ignore[method-assign]
    agent._signed_post = empty_catalog  # type: ignore[method-assign]

    with pytest.raises(RagToolError) as captured:
        asyncio.run(agent.runtime_receipt("analyst"))

    assert captured.value.code == "RAG_RUNTIME_RECEIPT_INVALID"


@pytest.mark.parametrize(
    ("field", "drift"),
    [
        ("tool_id", uuid4()),
        ("tool_code", "rag.other"),
        ("semantic_version", "1.2.1-candidate"),
        ("title", "Drifted RAG title"),
        ("description", "drifted"),
        ("input_schema_json", {"type": "object"}),
        ("output_schema_json", {"type": "object"}),
        ("annotations_json", {"readOnlyHint": False}),
        ("transport", "HTTP"),
        ("timeout_seconds", 31),
        ("required_roles_json", ["analyst", "platform_admin"]),
        ("is_enabled", False),
    ],
)
def test_registry_activation_requires_the_exact_candidate_descriptor(
    field: str,
    drift: object,
) -> None:
    receipt = _registry_receipt()
    assert InternalManualAgent._registry_contract_matches(receipt) is True

    receipt[field] = drift

    assert InternalManualAgent._registry_contract_matches(receipt) is False


def test_platform_admin_inherits_rag_tool_access_without_descriptor_drift() -> None:
    class _RegistryResult:
        def mappings(self) -> _RegistryResult:
            return self

        def one_or_none(self) -> dict[str, object]:
            return _registry_receipt()

    class _RegistrySession:
        async def execute(self, *_args: object, **_kwargs: object) -> _RegistryResult:
            return _RegistryResult()

    @asynccontextmanager
    async def enabled_registry(_database_url: str):
        yield _RegistrySession()

    agent = object.__new__(InternalManualAgent)
    agent._database_url = "postgresql+asyncpg://registry-test"  # type: ignore[attr-defined]

    with patch("app.services.rag_gateway.session_scope", enabled_registry):
        asyncio.run(agent._assert_enabled("platform_admin"))

    assert RAG_TOOL_ROLES == ("analyst",)


def _source_agent() -> InternalManualAgent:
    """네트워크와 Registry를 test double로 교체할 원문 Gateway를 만든다."""

    agent = object.__new__(InternalManualAgent)
    agent._base_url = "http://rag-api:8000"  # type: ignore[attr-defined]
    agent._secret = "s" * 32  # type: ignore[attr-defined]
    agent._timeout = 3.0  # type: ignore[attr-defined]
    agent._source_max_body_bytes = RAG_SOURCE_MAX_BODY_BYTES  # type: ignore[attr-defined]

    async def allow(_role: str) -> None:
        return None

    agent._assert_enabled = allow  # type: ignore[method-assign]
    return agent


def _mock_source_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[..., httpx.AsyncClient]:
    """실제 AsyncClient 옵션을 검증하면서 MockTransport만 주입한다."""

    original_client = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original_client(
            **kwargs,
            transport=httpx.MockTransport(handler),
        )

    return factory


def test_fetch_document_preserves_docx_media_and_normalizes_filename() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=b"docx-source",
            headers={
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                "Content-Disposition": (
                    "attachment; filename*=UTF-8''2026%EB%85%84%208%EC%9B%94.docx"
                ),
            },
        )

    with patch(
        "app.services.rag_gateway.httpx.AsyncClient",
        side_effect=_mock_source_client(handler),
    ):
        content, disposition, media_type = asyncio.run(
            _source_agent().fetch_document("REPORT-AUGUST", "analyst")
        )

    assert content == b"docx-source"
    assert media_type.endswith("wordprocessingml.document")
    assert disposition == (
        "attachment; filename*=UTF-8''2026%EB%85%84%208%EC%9B%94.docx"
    )
    assert requests[0].url.path == "/v1/documents/REPORT-AUGUST/source"
    assert requests[0].headers["X-Verified-Role"] == "STAFF"
    assert requests[0].headers["X-Request-Signature"]


def test_fetch_pdf_keeps_legacy_path_and_pdf_only_contract() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            content=b"%PDF-source",
            headers={
                "Content-Type": "application/pdf",
                "Content-Disposition": "inline; filename=manual.pdf",
            },
        )

    with patch(
        "app.services.rag_gateway.httpx.AsyncClient",
        side_effect=_mock_source_client(handler),
    ):
        content, disposition = asyncio.run(
            _source_agent().fetch_pdf("MANUAL-SAFETY", "analyst")
        )

    assert paths == ["/v1/documents/MANUAL-SAFETY/source.pdf"]
    assert content == b"%PDF-source"
    assert disposition == "inline; filename*=UTF-8''manual.pdf"


def test_fetch_pdf_rejects_docx_without_mislabelling_or_conversion() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"docx-source",
            headers={
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                "Content-Disposition": "attachment; filename=report.docx",
            },
        )

    with patch(
        "app.services.rag_gateway.httpx.AsyncClient",
        side_effect=_mock_source_client(handler),
    ), pytest.raises(RagToolError) as captured:
        asyncio.run(_source_agent().fetch_pdf("REPORT-AUGUST", "analyst"))

    assert captured.value.code == "RAG_DOCUMENT_MEDIA_TYPE_INVALID"


@pytest.mark.parametrize(
    ("media_type", "disposition"),
    [
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "attachment; filename=report.pdf",
        ),
        ("text/html", "inline; filename=manual.pdf"),
        ("application/pdf", "inline; filename=../manual.pdf"),
        ("application/pdf", "inline; filename=manual.pdf\r\nX-Evil: yes"),
    ],
)
def test_source_metadata_rejects_mislabelling_and_unsafe_filename(
    media_type: str,
    disposition: str,
) -> None:
    with pytest.raises(RagToolError) as captured:
        InternalManualAgent._source_metadata(
            "MANUAL-SAFETY",
            media_type,
            disposition,
            frozenset(
                {
                    "application/pdf",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }
            ),
        )

    assert captured.value.code in {
        "RAG_DOCUMENT_MEDIA_TYPE_INVALID",
        "RAG_DOCUMENT_RESPONSE_INVALID",
    }


def test_source_fetch_rejects_redirect_without_following_location() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://attacker.example/file"})

    with patch(
        "app.services.rag_gateway.httpx.AsyncClient",
        side_effect=_mock_source_client(handler),
    ), pytest.raises(RagToolError) as captured:
        asyncio.run(_source_agent().fetch_document("REPORT-AUGUST", "analyst"))

    assert captured.value.code == "RAG_DOCUMENT_REDIRECT_REJECTED"
    assert len(requests) == 1


def test_source_fetch_rejects_declared_body_over_bound() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x",
            headers={
                "Content-Type": "application/pdf",
                "Content-Disposition": "inline; filename=manual.pdf",
                "Content-Length": str(RAG_SOURCE_MAX_BODY_BYTES + 1),
            },
        )

    with patch(
        "app.services.rag_gateway.httpx.AsyncClient",
        side_effect=_mock_source_client(handler),
    ), pytest.raises(RagToolError) as captured:
        asyncio.run(_source_agent().fetch_document("MANUAL-SAFETY", "analyst"))

    assert captured.value.code == "RAG_DOCUMENT_TOO_LARGE"


class _AsyncChunks(httpx.AsyncByteStream):
    """Content-Length가 없는 응답을 작은 chunk들로 재현한다."""

    async def __aiter__(self):
        yield b"123"
        yield b"45"


def test_source_fetch_bounds_stream_when_content_length_is_missing() -> None:
    agent = _source_agent()
    agent._source_max_body_bytes = 4  # type: ignore[attr-defined]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_AsyncChunks(),
            headers={
                "Content-Type": "application/pdf",
                "Content-Disposition": "inline; filename=manual.pdf",
            },
        )

    with patch(
        "app.services.rag_gateway.httpx.AsyncClient",
        side_effect=_mock_source_client(handler),
    ), pytest.raises(RagToolError) as captured:
        asyncio.run(agent.fetch_document("MANUAL-SAFETY", "analyst"))

    assert captured.value.code == "RAG_DOCUMENT_TOO_LARGE"


def test_app_generic_source_endpoint_keeps_runtime_media_type_and_security_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Gateway:
        """Router가 호출할 성공 원문 응답을 고정한다."""

        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://app"

        async def fetch_document(
            self,
            manual_id: str,
            app_role: str,
        ) -> tuple[bytes, str, str]:
            assert manual_id == "REPORT-AUGUST"
            assert app_role == "analyst"
            return (
                b"docx-source",
                "attachment; filename*=UTF-8''report.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

    monkeypatch.setenv("APP_RUNTIME_DATABASE_URL", "postgresql://app")
    with patch("app.api.rag_router._require_internal_guideline_enabled"), patch(
        "app.api.rag_router.RagGatewayTool", Gateway
    ):
        response = asyncio.run(
            get_internal_manual_source("REPORT-AUGUST", RequestContext())
        )

    assert response.body == b"docx-source"
    assert response.media_type.endswith("wordprocessingml.document")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
