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

    def test_comparison_follow_up_selects_requested_article(self) -> None:
        blocks = [
            ("EV-FAC-6", "11 시설", "MANUAL-FACILITY", "제6조 반드시 남길 기록", "제6 조. 반드시 남길 기록 • 시설 점검 결과"),
            ("EV-FAC-5", "11 시설", "MANUAL-FACILITY", "제5조 책임자에게 바로 보고할 상황", "제5 조. 책임자에게 바로 보고할 상황 • 고객 고립 또는 인명 위험"),
            ("EV-SAFE-6", "14 안전", "MANUAL-SAFETY", "제6조 반드시 남길 기록", "제6 조. 반드시 남길 기록 • 발견 위치·시각"),
            ("EV-SAFE-5", "14 안전", "MANUAL-SAFETY", "제5조 책임자에게 바로 보고할 상황", "제5 조. 책임자에게 바로 보고할 상황 • 의식·호흡 이상"),
        ]
        evidence = "\n\n".join(
            "\n".join((
                f"ID: {evidence_id}",
                f"문서명: {title}",
                f"지침번호: {manual_id}",
                f"영역: {section_title}",
                f"근거: [{title}]",
                "본문내용:",
                body,
                "END_EVIDENCE",
            ))
            for evidence_id, title, manual_id, section_title, body in blocks
        )
        answer = EvidenceBoundAnswerComposer().compose([{
            "role": "user",
            "content": (
                "질문: 이전 내부지침 문맥: 시설 문제와 안전사고 대응 비교\n"
                "현재 후속 질문: 즉시 보고 기준을 알려줘\n"
                "요청 의도: IMMEDIATE_ACTION\n\n"
                "제공된 근거(evidence):\n" + evidence
            ),
        }])

        self.assertIn("고객 고립 또는 인명 위험", answer["answer"])
        self.assertIn("의식·호흡 이상", answer["answer"])
        self.assertNotIn("시설 점검 결과", answer["answer"])
        self.assertNotIn("발견 위치·시각", answer["answer"])
        self.assertEqual(
            {item["evidence_id"] for item in answer["citations"]},
            {"EV-FAC-5", "EV-SAFE-5"},
        )


if __name__ == "__main__":
    unittest.main()
