from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.rag_routing import RagIntent, RagQueryRouter


def test_immediate_safety_intent_overrides_location_domain() -> None:
    decision = RagQueryRouter().classify(
        "[내부 지침] 고객이 객실에서 쓰러졌어. 지금 뭘 해야 해?",
        "DOCUMENT_ONLY",
    )

    assert decision.intent is RagIntent.IMMEDIATE_ACTION
    assert decision.domains == ("SAFETY",)


def test_risk_classification_question_uses_decision_criteria() -> None:
    for question in (
        "[내부 지침] 시설 문제를 위험 상황으로 보는 기준이 뭐야?",
        "[내부 지침] 시설 문제를 긴급 장애로 보는 기준이 뭐야?",
    ):
        decision = RagQueryRouter().classify(question, "DOCUMENT_ONLY")

        assert decision.intent is RagIntent.DECISION_CRITERIA
        assert decision.domains == ("FACILITY",)


def test_compensation_policy_routes_without_clarification() -> None:
    decision = RagQueryRouter().classify(
        "[내부 지침] 고객 보상은 어떤 조건에서 가능한가?",
        "DOCUMENT_ONLY",
    )

    assert decision.domains == ("CANCELLATION_REFUND_COMPENSATION",)
    assert decision.clarification is None


def test_lost_property_routes_to_parking_event_lobby_domain() -> None:
    decision = RagQueryRouter().classify(
        "[내부 지침] 분실물 접수 후 처리 순서를 알려줘",
        "DOCUMENT_ONLY",
    )

    assert decision.domains == ("PARKING_EVENT_LOBBY",)
    assert decision.clarification is None


def test_follow_up_inherits_previous_rag_domains() -> None:
    router = RagQueryRouter()
    decision = router.classify(
        "[내부 지침] 각각의 즉시 보고 기준을 알려줘",
        "DOCUMENT_ONLY",
        ("시설 장애와 안전사고 대응은 어떻게 달라?",),
    )

    assert decision.requires_context is True
    assert decision.domains == ("FACILITY", "SAFETY")
    assert decision.clarification is None
    assert router.context_document_limit(decision) == 2
