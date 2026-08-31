from __future__ import annotations

import unittest

from src.rag.answer_prompt import build_answer_prompt
from src.rag.local_answer_service import EvidenceBoundAnswerComposer


class EvidenceBoundAnswerComposerTest(unittest.TestCase):
    def test_answer_cites_only_extracted_evidence(self) -> None:
        composer = EvidenceBoundAnswerComposer()
        answer = composer.compose(build_answer_prompt(
            "시설 사고 처리 순서를 알려줘",
            [{
                "evidence_id": "EV-001",
                "manual_id": "MANUAL-FACILITY",
                "title": "11 시설",
                "version": "1.0",
                "page_start": 1,
                "score": 0.8,
                "document_status": "WORKING_KNOWLEDGE",
                "approval_status": "APPROVED",
                "validity_status": "VALID",
                "citation": "[11 시설 v1.0 p.1]",
                "content": "제4조 처리 순서 • 사고 현장을 통제하고 담당자에게 보고한다",
            }],
            "PROCESS",
        ))

        self.assertEqual(answer["status"], "ANSWER")
        self.assertEqual(answer["citations"][0]["evidence_id"], "EV-001")
        self.assertEqual(answer["request_id"], "local-answer")
        self.assertEqual(answer["trace_id"], "local-answer")

    def test_empty_evidence_returns_no_evidence(self) -> None:
        answer = EvidenceBoundAnswerComposer().compose([{ "role": "user", "content": "Question only" }])

        self.assertEqual(answer["status"], "NO_EVIDENCE")
        self.assertEqual(answer["citations"], [])

    def test_explicit_intent_is_preserved_in_answer_type(self) -> None:
        answer = EvidenceBoundAnswerComposer().compose(build_answer_prompt(
            "고객이 쓰러졌을 때 즉시 무엇을 해야 해?",
            [{
                "evidence_id": "EV-SAFETY",
                "manual_id": "MANUAL-SAFETY",
                "title": "14 안전",
                "version": "1.0",
                "page_start": 1,
                "score": 0.8,
                "document_status": "WORKING_KNOWLEDGE",
                "approval_status": "APPROVED",
                "validity_status": "VALID",
                "citation": "[14 안전]",
                "content": "제4조 처리 순서 • 현장을 통제하고 즉시 책임자에게 보고한다",
            }],
            "IMMEDIATE_ACTION",
        ))

        self.assertEqual(answer["status"], "ANSWER")
        self.assertEqual(answer["answer_type"], "IMMEDIATE")
        self.assertEqual(answer["citations"][0]["evidence_id"], "EV-SAFETY")


if __name__ == "__main__":
    unittest.main()
