from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.rag.manual_question_evaluation import (
    ManualQuestion,
    ManualQuestionEvaluationService,
    MarkdownQuestionSuite,
)
from src.rag.manual_evaluation_metrics import ManualEvaluationMetrics


class MarkdownQuestionSuiteTest(unittest.TestCase):
    def test_positive_and_negative_rows_are_loaded(self) -> None:
        content = """# test

| ID | 유형 | 난이도 | 검색 질문 | 주 예상 문서 | 허용 보조 문서 | 실제 상위 문서 | 판정 |
|---|---|---|---|---|---|---|---|
| P001-01 | 정확 제목 | L1 | 매뉴얼을 찾아줘 | INDEX-001 | SOP-FRT-003, SOP-FRT-001 | 미실행 | 평가 전 |

| ID | 유형 | 난이도 | 검색 질문 | 기대 동작 | 실제 동작 | 판정 |
|---|---|---|---|---|---|---|
| N001 | 범위 밖 | L1 | 오늘 날씨를 알려줘 | 0건 | 미실행 | 평가 전 |
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.md"
            path.write_text(content, encoding="utf-8")
            questions = MarkdownQuestionSuite.load(path)

        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0].expected_manual_id, "INDEX-001")
        self.assertEqual(
            questions[0].allowed_manual_ids, ("SOP-FRT-003", "SOP-FRT-001")
        )
        self.assertTrue(questions[1].is_strict_out_of_scope)

    def test_follow_up_query_includes_previous_question_from_same_group(self) -> None:
        questions = [
            ManualQuestion("P001-01", "행동 중심", "L2", "예약을 확인해", "DOC-1", ()),
            ManualQuestion("P001-02", "후속 대화", "L4", "그 다음은?", "DOC-1", ()),
        ]
        effective = ManualQuestionEvaluationService._effective_queries(questions)
        self.assertEqual(effective[0], "예약을 확인해")
        self.assertEqual(effective[1], "예약을 확인해\n그 다음은?")

    def test_optional_gold_page_and_suite_version_are_loaded(self) -> None:
        content = """# test

| 문서 버전 | `v3.0` |

| ID | 유형 | 난이도 | 검색 질문 | 주 예상 문서 | 허용 보조 문서 | 정답 페이지 | 실제 상위 문서 | 판정 |
|---|---|---|---|---|---|---|---|---|
| P001-01 | 정확 제목 | L1 | 매뉴얼을 찾아줘 | INDEX-001 | - | p.3-4 | 미실행 | 평가 전 |
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.md"
            path.write_text(content, encoding="utf-8")
            question = MarkdownQuestionSuite.load(path)[0]
            version = MarkdownQuestionSuite.version(path)

        self.assertEqual(version, "v3.0")
        self.assertEqual(question.expected_page_start, 3)
        self.assertEqual(question.expected_page_end, 4)

    def test_manual_metrics_report_ndcg_and_missing_gold_page_separately(self) -> None:
        items = [
            {
                "primary_rank": 2,
                "allowed_rank": 1,
                "retrieved_manual_ids": ["DOC-2", "DOC-1"],
                "gold_page_hit": None,
                "citation_count": 2,
                "complete_citation_count": 2,
            }
        ]
        metrics = ManualEvaluationMetrics.retrieval(items)
        self.assertEqual(metrics["recall_at_1"], 0.0)
        self.assertEqual(metrics["recall_at_3"], 1.0)
        self.assertEqual(metrics["ndcg_at_10"], 0.6309)
        self.assertEqual(
            ManualEvaluationMetrics.gold_page_accuracy(items),
            "NOT_MEASURABLE_MISSING_GOLD_PAGE",
        )

    def test_openai_release_evaluation_uses_openai_embedding_provider(self) -> None:
        service = object.__new__(ManualQuestionEvaluationService)
        service._settings = SimpleNamespace(  # type: ignore[attr-defined]
            embedding_provider="openai",
            embedding_api_key="test-key",
            model_id="text-embedding-3-large",
            dimension=1024,
            embedding_endpoint="https://api.openai.com/v1/embeddings",
            embedding_timeout_seconds=30.0,
            embedding_maximum_attempts=3,
        )
        provider = object()

        with (
            patch(
                "src.rag.manual_question_evaluation.OpenAIEmbeddingProvider",
                return_value=provider,
            ) as openai,
            patch(
                "src.rag.manual_question_evaluation.QwenEmbeddingProvider"
            ) as qwen,
        ):
            selected = service._build_embedding_provider()

        self.assertIs(selected, provider)
        openai.assert_called_once_with(
            "test-key",
            "text-embedding-3-large",
            1024,
            "https://api.openai.com/v1/embeddings",
            30.0,
            3,
        )
        qwen.assert_not_called()

    def test_qwen_release_evaluation_uses_qwen_embedding_provider(self) -> None:
        service = object.__new__(ManualQuestionEvaluationService)
        model_path = Path("models/Qwen3-Embedding-0.6B")
        service._settings = SimpleNamespace(  # type: ignore[attr-defined]
            embedding_provider="qwen",
            model_path=model_path,
            device="cpu",
            dimension=1024,
            max_sequence_length=2048,
            query_prompt_name="query",
        )
        provider = object()

        with (
            patch(
                "src.rag.manual_question_evaluation.OpenAIEmbeddingProvider"
            ) as openai,
            patch(
                "src.rag.manual_question_evaluation.QwenEmbeddingProvider",
                return_value=provider,
            ) as qwen,
        ):
            selected = service._build_embedding_provider()

        self.assertIs(selected, provider)
        qwen.assert_called_once_with(model_path, "cpu", 1024, 2048, "query")
        openai.assert_not_called()


if __name__ == "__main__":
    unittest.main()
