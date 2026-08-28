from __future__ import annotations

import unittest

from src.rag.answer_templates import AnswerTemplateSelector, AnswerType


class AnswerTemplateSelectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.selector = AnswerTemplateSelector()

    def test_risk_classification_question_prefers_criteria(self) -> None:
        self.assertEqual(
            AnswerType.CRITERIA,
            self.selector.select("시설 문제를 위험 상황으로 보는 기준이 뭐야?"),
        )
        self.assertEqual(
            AnswerType.CRITERIA,
            self.selector.select("시설 문제를 긴급 장애로 보는 기준이 뭐야?"),
        )

    def test_immediate_action_question_remains_immediate(self) -> None:
        self.assertEqual(
            AnswerType.IMMEDIATE,
            self.selector.select("고객이 객실에서 쓰러졌어. 지금 뭘 해야 해?"),
        )
        self.assertEqual(
            AnswerType.IMMEDIATE,
            self.selector.select("즉시 보고 기준을 알려줘"),
        )


if __name__ == "__main__":
    unittest.main()
