from __future__ import annotations

import unittest

from src.rag.answer_prompt import build_answer_prompt
from src.rag.answer_safety import AnswerSafetySettings
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

    def test_internal_report_uses_heading_and_table_evidence_without_articles(self) -> None:
        answer = EvidenceBoundAnswerComposer().compose(build_answer_prompt(
            "객실 매출 하락 근거를 요약해줘",
            [{
                "evidence_id": "EV-REPORT",
                "manual_id": "REPORT-2026-08-ROOMS",
                "title": "8월 객실 운영 보고서",
                "version": "2026-08",
                "document_type": "INTERNAL_REPORT",
                "owner_team": "ROOMS",
                "section_title": "[DOCX EXPLICIT_BREAK_SEGMENT 2] 객실 매출",
                "page_start": 2,
                "score": 0.82,
                "document_status": "WORKING_KNOWLEDGE",
                "approval_status": "APPROVED",
                "validity_status": "VALID",
                "citation": "[8월 객실 운영 보고서 v2026-08 explicit-segment.2 객실 매출]",
                "content": (
                    "[TABLE index=1 style=Grid]\n"
                    "[r1c1 span=1] 월 | [r1c2 span=1] 객실 매출\n"
                    "[r2c1 span=1] 2026-08 | [r2c2 span=1] 314.5억 원\n"
                    "[/TABLE]"
                ),
            }],
            "SUMMARY",
        ))

        self.assertEqual(answer["status"], "ANSWER")
        self.assertEqual(answer["sections"][0]["article_number"], None)
        self.assertEqual(answer["sections"][0]["document_id"], "REPORT-2026-08-ROOMS")
        self.assertEqual(
            answer["sections"][0]["claims"][0]["evidence_ids"],
            ["EV-REPORT"],
        )
        self.assertEqual(answer["citations"][0]["evidence_id"], "EV-REPORT")
        self.assertIn("객실 매출", answer["answer"])
        self.assertNotIn("제3조", answer["answer"])

    def test_internal_report_hides_docx_parser_markers_from_answer(self) -> None:
        answer = EvidenceBoundAnswerComposer().compose(build_answer_prompt(
            "2026년 8월 객실팀 보고서의 취소율과 취소 사유를 알려줘",
            [{
                "evidence_id": "EV-REPORT-ROOMS",
                "manual_id": "REPORT-2026-08-ROOMS",
                "title": "8월 객실 운영 보고서",
                "version": "2026-08",
                "document_type": "INTERNAL_REPORT",
                "owner_team": "ROOMS",
                "section_title": "[DOCX DOCUMENT_START 1] 객실 운영 결론",
                "page_start": 1,
                "score": 0.91,
                "document_status": "WORKING_KNOWLEDGE",
                "approval_status": "APPROVED",
                "validity_status": "VALID",
                "citation": "[8월 객실 운영 보고서 v2026-08 p.1 객실 운영 결론]",
                "content": (
                    "[DOCX DOCUMENT_START 1] [PARAGRAPH style=Title] 객실 운영보고서\n"
                    "[PARAGRAPH style=UNSTYLED] 전체 취소율은 17.59%다.\n"
                    "[TABLE index=1 style=Grid]\n"
                    "[r1c1 span=1] 주요 취소 사유 | [r1c2 span=1] 비중\n"
                    "[r2c1 span=1] 일정 변경 | [r2c2 span=1] 53.95%\n"
                    "[/TABLE]"
                ),
            }],
            "SUMMARY",
        ))

        self.assertEqual(answer["status"], "ANSWER")
        self.assertIn("전체 취소율은 17.59%다.", answer["answer"])
        self.assertIn("일정 변경 | 53.95%", answer["answer"])
        for marker in ("[DOCX", "[PARAGRAPH", "[TABLE", "[/TABLE]", "[r1c1"):
            self.assertNotIn(marker, answer["answer"])

    def test_internal_report_hides_section_boundary_and_limits_total_points(self) -> None:
        composer = EvidenceBoundAnswerComposer(
            AnswerSafetySettings(maximum_points_per_article=3)
        )
        answer = composer.compose(build_answer_prompt(
            "객실 취소 현황과 후속 조치를 알려줘",
            [
                {
                    "evidence_id": "EV-REPORT-A",
                    "manual_id": "REPORT-ROOMS",
                    "title": "객실 운영 보고서",
                    "version": "2026-08",
                    "document_type": "INTERNAL_REPORT",
                    "owner_team": "ROOMS",
                    "section_title": "취소 현황",
                    "score": 0.91,
                    "document_status": "APPROVED",
                    "approval_status": "APPROVED",
                    "validity_status": "VALID",
                    "citation": "[객실 운영 보고서 취소 현황]",
                    "content": (
                        "[PARAGRAPH] 전체 취소율은 17.59%입니다.\n"
                        "[PARAGRAPH] 일정 변경 비중은 53.95%입니다.\n"
                        "[SECTION_BOUNDARY index=1 type=nextPage]\n"
                    ),
                },
                {
                    "evidence_id": "EV-REPORT-B",
                    "manual_id": "REPORT-ROOMS",
                    "title": "객실 운영 보고서",
                    "version": "2026-08",
                    "document_type": "INTERNAL_REPORT",
                    "owner_team": "ROOMS",
                    "section_title": "후속 조치",
                    "score": 0.88,
                    "document_status": "APPROVED",
                    "approval_status": "APPROVED",
                    "validity_status": "VALID",
                    "citation": "[객실 운영 보고서 후속 조치]",
                    "content": (
                        "[PARAGRAPH] 일정 변경 상품을 우선 제안합니다.\n"
                        "[PARAGRAPH] 취소율을 주간 단위로 관리합니다.\n"
                    ),
                },
            ],
            "SUMMARY",
        ))

        claims = [
            claim
            for section in answer["sections"]
            for claim in section["claims"]
        ]
        self.assertEqual(len(claims), 3)
        self.assertNotIn("SECTION_BOUNDARY", answer["answer"])

    def test_internal_report_keeps_retrieval_rank_over_incidental_word_hits(self) -> None:
        def report(
            evidence_id: str,
            month: str,
            score: float,
            content: str,
        ) -> dict[str, object]:
            return {
                "evidence_id": evidence_id,
                "manual_id": f"REPORT-2026-{month}-ROOMS",
                "title": f"2026년 {int(month)}월 객실 운영보고서",
                "version": f"2026-{month}",
                "document_type": "INTERNAL_REPORT",
                "owner_team": "ROOMS",
                "section_title": "객실 점유율 변동 원인",
                "score": score,
                "document_status": "WORKING_KNOWLEDGE",
                "approval_status": "APPROVED",
                "validity_status": "VALID",
                "citation": f"[2026년 {int(month)}월 객실 운영보고서]",
                "content": content,
            }

        answer = EvidenceBoundAnswerComposer().compose(build_answer_prompt(
            "2026년 7월과 8월 객실 점유율 하락 원인을 알려줘",
            [
                report("EV-AUGUST", "08", 0.91, "8월 점유율 하락 원인은 단체 수요 감소다."),
                report("EV-JULY", "07", 0.82, "7월과 8월 객실 점유율 하락 원인 비교 자료다."),
            ],
            "SUMMARY",
        ))

        self.assertEqual(answer["status"], "ANSWER")
        self.assertEqual(answer["citations"][0]["evidence_id"], "EV-AUGUST")


if __name__ == "__main__":
    unittest.main()
