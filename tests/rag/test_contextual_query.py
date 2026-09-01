from __future__ import annotations

import unittest

from src.rag.contextual_query import ContextualQueryBuilder


class ContextualQueryBuilderTest(unittest.TestCase):
    def test_recent_utterances_are_bounded_and_current_query_is_last(self) -> None:
        query = ContextualQueryBuilder.build(
            "그 다음에는?",
            ("첫 질문", "둘째 질문", "셋째 질문", "넷째 질문"),
        )
        self.assertNotIn("첫 질문", query)
        self.assertEqual(
            query.splitlines(),
            ["둘째 질문", "셋째 질문", "넷째 질문", "그 다음에는?"],
        )

    def test_selected_document_ids_are_bounded_and_non_empty(self) -> None:
        self.assertEqual(
            ContextualQueryBuilder.validate_document_ids((" SOP-FRT-003 ",)),
            ("SOP-FRT-003",),
        )
        with self.assertRaises(ValueError):
            ContextualQueryBuilder.validate_document_ids(("",))
        with self.assertRaises(ValueError):
            ContextualQueryBuilder.validate_document_ids(("잘못된 ID",))
        with self.assertRaises(ValueError):
            ContextualQueryBuilder.validate_document_ids(tuple(str(i) for i in range(11)))

    def test_report_periods_inherit_the_latest_explicit_year(self) -> None:
        self.assertEqual(
            ContextualQueryBuilder.report_periods(
                "2026년 7월과 8월의 객실 점유율 변화를 비교해줘"
            ),
            ("2026-07", "2026-08"),
        )


if __name__ == "__main__":
    unittest.main()
