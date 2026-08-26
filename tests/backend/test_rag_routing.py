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


def test_abstract_multi_domain_policy_requires_clarification() -> None:
    decision = RagQueryRouter().classify(
        "[내부 지침] 고객 보상은 어떤 조건에서 가능한가?",
        "DOCUMENT_ONLY",
    )

    assert decision.clarification is not None
    assert decision.clarification_options


def test_unknown_topic_requires_clarification_instead_of_random_document() -> None:
    decision = RagQueryRouter().classify(
        "[내부 지침] 분실물 접수 후 처리 순서를 알려줘",
        "DOCUMENT_ONLY",
    )

    assert decision.domains == ()
    assert decision.clarification is not None


def test_follow_up_inherits_previous_rag_domains() -> None:
    decision = RagQueryRouter().classify(
        "[내부 지침] 각각의 즉시 보고 기준을 알려줘",
        "DOCUMENT_ONLY",
        ("시설 장애와 안전사고 대응은 어떻게 달라?",),
    )

    assert decision.requires_context is True
    assert decision.domains == ("FACILITY", "SAFETY")
    assert decision.clarification is None
