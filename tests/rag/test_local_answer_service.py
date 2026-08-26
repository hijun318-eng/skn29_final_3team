from __future__ import annotations

import unittest

from src.rag.local_answer_service import EvidenceBoundAnswerComposer


class EvidenceBoundAnswerComposerTest(unittest.TestCase):
    def test_answer_cites_only_extracted_evidence(self) -> None:
        composer = EvidenceBoundAnswerComposer()
        answer = composer.compose([{
            "role": "user",
            "content": "Question\n\nEvidence:\nID: EV-001\nReport the incident to the assigned owner.",
        }])

        self.assertEqual(answer["status"], "ANSWER")
        self.assertEqual(answer["citations"][0]["evidence_id"], "EV-001")
        self.assertEqual(answer["request_id"], "local-answer")
        self.assertEqual(answer["trace_id"], "local-answer")

    def test_empty_evidence_returns_no_evidence(self) -> None:
        answer = EvidenceBoundAnswerComposer().compose([{ "role": "user", "content": "Question only" }])

        self.assertEqual(answer["status"], "NO_EVIDENCE")
        self.assertEqual(answer["citations"], [])

    def test_explicit_intent_is_preserved_in_answer_type(self) -> None:
        answer = EvidenceBoundAnswerComposer().compose([{
            "role": "user",
            "content": (
                "질문: 고객이 쓰러졌습니다.\n"
                "요청 의도: IMMEDIATE_ACTION\n\n"
                "제공된 근거(evidence):\n"
                "ID: EV-SAFETY\n"
                "문서명: 14 안전\n"
                "지침번호: MANUAL-SAFETY\n"
                "영역: 즉시 대응\n"
                "근거: [14 안전]\n"
                "본문내용:\n현장을 통제하고 즉시 책임자에게 보고한다.\n\n"
                "END_EVIDENCE"
            ),
        }])

        self.assertEqual(answer["status"], "ANSWER")
        self.assertEqual(answer["answer_type"], "IMMEDIATE")
        self.assertEqual(answer["citations"][0]["evidence_id"], "EV-SAFETY")


if __name__ == "__main__":
    unittest.main()
