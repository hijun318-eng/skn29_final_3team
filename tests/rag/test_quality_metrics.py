from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.rag.evaluation_service import QualityEvaluator


class FakePolicy:
    def decide(self, role, top_k):
        return SimpleNamespace(minimum_score=0.45, top_k=top_k)


class FakeEmbedding:
    def embed_queries(self, queries):
        return list(queries)


class FakeRetrieval:
    def __init__(self, results):
        self._results = results

    def retrieve(self, query, vector, decision):
        return self._results[query]


def result(manual_id: str):
    return SimpleNamespace(
        manual_id=manual_id,
        version="1.0",
        page_start=1,
        page_end=1,
        citation=f"[{manual_id} v1.0 p.1-1 테스트]",
    )


def report_result(manual_id: str):
    return SimpleNamespace(
        manual_id=manual_id,
        version="2026-08",
        page_start=None,
        page_end=None,
        locator_kind="EXPLICIT_BREAK_SEGMENT",
        locator_start=2,
        locator_end=2,
        citation=f"[{manual_id} v2026-08 explicit-segment.2 본문]",
    )


class QualityMetricsTest(unittest.TestCase):
    def test_explicit_report_segment_is_a_complete_non_page_citation(self) -> None:
        evaluator = QualityEvaluator(
            FakePolicy(),
            FakeRetrieval({"월간 보고서": [report_result("REPORT-ONE")]}),
            FakeEmbedding(),
        )

        report = evaluator.evaluate(
            [
                {
                    "query_id": "R1",
                    "query": "월간 보고서",
                    "expected_manual_id": "REPORT-ONE",
                    "query_type": "REPORT",
                }
            ],
            "SYNTHETIC_TEST",
            "1.0",
        )

        self.assertEqual(report["citation_metadata_completeness"], 1.0)

    def test_recall5_ndcg10_and_citation_completeness_are_reported(self) -> None:
        evaluator = QualityEvaluator(
            FakePolicy(),
            FakeRetrieval(
                {
                    "질문1": [result("DOC-1")],
                    "질문2": [result("OTHER"), result("DOC-2")],
                    "범위밖": [],
                }
            ),
            FakeEmbedding(),
        )
        report = evaluator.evaluate(
            [
                {"query_id": "Q1", "query": "질문1", "expected_manual_id": "DOC-1", "query_type": "TEST"},
                {"query_id": "Q2", "query": "질문2", "expected_manual_id": "DOC-2", "query_type": "TEST"},
                {"query_id": "N1", "query": "범위밖", "expected_manual_id": None, "query_type": "OUT"},
            ],
            "SYNTHETIC_TEST",
            "1.0",
            1,
        )
        self.assertEqual(report["recall_at_5"], 1.0)
        self.assertEqual(report["ndcg_at_10"], 0.8155)
        self.assertEqual(report["citation_metadata_completeness"], 1.0)
        self.assertEqual(
            report["citation_location_accuracy"],
            "NOT_MEASURABLE_MISSING_GOLD_PAGE",
        )
        self.assertEqual(report["synthetic_technical_gate"], "PASSED")

    def test_recall_at_k_uses_the_named_rank_boundary(self) -> None:
        evaluator = QualityEvaluator(
            FakePolicy(),
            FakeRetrieval(
                {
                    "질문": [
                        result("OTHER-1"), result("OTHER-2"), result("OTHER-3"),
                        result("DOC-1"),
                    ]
                }
            ),
            FakeEmbedding(),
        )
        report = evaluator.evaluate(
            [
                {
                    "query_id": "Q1",
                    "query": "질문",
                    "expected_manual_id": "DOC-1",
                    "query_type": "TEST",
                }
            ],
            "SYNTHETIC_TEST",
            "1.0",
        )
        self.assertEqual(report["recall_at_1"], 0.0)
        self.assertEqual(report["recall_at_3"], 0.0)
        self.assertEqual(report["recall_at_5"], 1.0)


if __name__ == "__main__":
    unittest.main()
