from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from uuid import uuid4

from fastapi import HTTPException
import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.rag_router import (
    RagQueryRequest,
    _approved_rag_snapshot,
    get_internal_manual_pdf,
    list_internal_manuals,
)
from app.api.rag_router_runtime import internal_manual_query_service
from app.contracts import RequestContext
from app.services.internal_manual_query import (
    InternalManualQuery,
    InternalManualQueryError,
    InternalManualQueryService,
)


def test_rag_query_is_an_explicit_document_request_by_default() -> None:
    request = RagQueryRequest(question="승인된 내부 문서를 검색해줘")

    assert request.mode == "DOCUMENT_ONLY"
    assert request.inherit_previous_context is False


def test_rag_context_excludes_analysis_turns_and_uses_saved_rag_state() -> None:
    turns = [
        {
            "route": "ANALYSIS",
            "user_message": "지난달 매출을 분석해줘",
            "resolved_slots": {"metric_id": "revenue"},
        },
        {
            "route": "INTERNAL_GUIDELINE",
            "user_message": "내부 문서의 처리 절차를 알려줘",
            "resolved_slots": {
                "rag": {
                    "routing": {
                        "snapshot_question": "승인된 내부 문서의 처리 절차",
                        "selected_document_ids": ["MANUAL-FACILITY", "MANUAL-SAFETY"],
                    },
                    "evidence_bundle": [
                        {"document_id": "MANUAL-FACILITY"},
                        {"document_id": "MANUAL-SAFETY"},
                    ],
                }
            },
        },
    ]

    assert _approved_rag_snapshot(turns) == (
        ("승인된 내부 문서의 처리 절차",),
        ("MANUAL-FACILITY", "MANUAL-SAFETY"),
    )


def test_rag_context_never_falls_back_to_conversation_raw_text() -> None:
    turns = [
        {
            "route": "INTERNAL_GUIDELINE",
            "user_message": "이 항목을 더 자세히 알려줘",
            "resolved_slots": {"rag": {"status": "ANSWER"}},
        }
    ]

    assert _approved_rag_snapshot(turns) == ((), ())


def test_rag_context_requires_the_immediately_previous_turn_to_be_rag() -> None:
    turns = [
        {
            "route": "INTERNAL_GUIDELINE",
            "resolved_slots": {
                "rag": {
                    "routing": {
                        "snapshot_question": "시설과 안전 기준 비교",
                        "selected_document_ids": ["MANUAL-FACILITY", "MANUAL-SAFETY"],
                    }
                }
            },
        },
        {
            "route": "ANALYSIS",
            "user_message": "지난달 매출",
            "resolved_slots": {"metric_id": "revenue"},
        },
    ]

    assert _approved_rag_snapshot(turns) == ((), ())


def test_rag_runtime_factory_fails_closed_when_feature_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_RUNTIME_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAG_FEATURE_ENABLED", raising=False)

    service = internal_manual_query_service()

    with pytest.raises(InternalManualQueryError) as captured:
        asyncio.run(
            service.execute(
                InternalManualQuery(
                    question="승인된 내부 문서를 검색해줘",
                    mode="DOCUMENT_ONLY",
                ),
                RequestContext(),
            )
        )

    assert captured.value.code == "RAG_FEATURE_DISABLED"
    assert captured.value.status_code == 503


def test_feature_off_rejects_before_conversation_database_reads() -> None:
    class Repository:
        reads = 0

        async def get_conversation(self, *_args: object):
            self.reads += 1
            return {}

        async def list_turns(self, *_args: object):
            self.reads += 1
            return []

    repository = Repository()
    service = InternalManualQueryService(
        repository,
        lambda: object(),
        enabled=False,
    )

    with pytest.raises(InternalManualQueryError) as captured:
        asyncio.run(
            service.execute(
                InternalManualQuery(
                    question="승인된 내부 문서를 검색해줘",
                    mode="DOCUMENT_ONLY",
                    conversation_id=uuid4(),
                    inherit_previous_context=True,
                ),
                RequestContext(),
            )
        )

    assert captured.value.code == "RAG_FEATURE_DISABLED"
    assert captured.value.status_code == 503
    assert repository.reads == 0


def test_rag_document_endpoints_share_the_disabled_feature_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_RUNTIME_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAG_FEATURE_ENABLED", raising=False)

    async def exercise() -> None:
        with pytest.raises(HTTPException) as catalog_error:
            await list_internal_manuals(RequestContext())
        assert catalog_error.value.status_code == 503
        assert catalog_error.value.detail == "내부지침 검색 기능이 비활성화되었습니다."

        with pytest.raises(HTTPException) as pdf_error:
            await get_internal_manual_pdf("MANUAL-SAFETY", RequestContext())
        assert pdf_error.value.status_code == 503
        assert pdf_error.value.detail == "내부지침 검색 기능이 비활성화되었습니다."

    asyncio.run(exercise())
