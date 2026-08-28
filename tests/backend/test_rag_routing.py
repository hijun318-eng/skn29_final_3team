from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.rag_router import RagQueryRequest, _approved_rag_snapshot


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
