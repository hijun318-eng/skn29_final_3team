from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.rag.request_auth import GatewayRequestAuthenticator, canonical_search_request
from src.rag.e2e.contracts import DynamicE2EConfig, E2EConfigurationError
from src.rag.e2e.manual_rag_e2e import (
    ManualRagE2EConfig,
    ManualRagE2EError,
    ManualRagE2EOrchestrator,
)


class FakeManualRagHttpClient:
    def __init__(
        self,
        answer_citation: str = "EV-001",
        answer_citation_text: str = "[장애 보고 매뉴얼 v1.0 p.1]",
    ) -> None:
        self.answer_citation = answer_citation
        self.answer_citation_text = answer_citation_text
        self.posts: list[tuple[str, dict, dict]] = []

    def get(self, url: str) -> dict:
        return {"status": "healthy" if url.endswith("/health/live") else "ready"}

    def post(self, url: str, payload: dict, headers: dict) -> dict:
        self.posts.append((url, payload, headers))
        if url.endswith("internal-manual-search"):
            return {
                "request_id": "11111111-1111-4111-8111-111111111111",
                "answer_query": "장애 보고 절차",
                "no_evidence": False,
                "results": [
                    {
                        "evidence_id": "EV-001",
                        "content": "장애는 즉시 보고한다.",
                        "title": "장애 보고 매뉴얼",
                        "manual_id": "MANUAL-001",
                        "version": "1.0",
                        "document_type": "MANUAL",
                        "owner_team": "OPERATIONS",
                        "section_title": "보고 절차",
                        "citation": "[장애 보고 매뉴얼 v1.0 p.1]",
                    }
                ],
            }
        return {
            "status": "ANSWER",
            "trace_id": payload["trace_id"],
            "answer": "즉시 보고한다.",
            "citations": [
                {
                    "evidence_id": self.answer_citation,
                    "citation": self.answer_citation_text,
                }
            ],
        }


class ManualRagE2EOrchestratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.config = ManualRagE2EConfig("http://rag-api:8000", "x" * 32, "MANAGER", "장애 보고 절차", 3, 2.0, Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_search_to_answer_e2e_preserves_evidence_boundary(self) -> None:
        http = FakeManualRagHttpClient()
        report = ManualRagE2EOrchestrator(self.config, http).run()
        self.assertEqual(report.final_stage, "SUCCEEDED")
        self.assertEqual(len(http.posts), 2)
        self.assertIn("X-Request-Signature", http.posts[0][2])
        payload, headers = http.posts[0][1], http.posts[0][2]
        canonical = canonical_search_request(
            payload["query"],
            payload["top_k"],
            tuple(payload["recent_utterances"]),
            tuple(payload["selected_document_ids"]),
            trace_id=payload["trace_id"],
            actor_hash=payload["actor_hash"],
        )
        expected = GatewayRequestAuthenticator.build_signature(self.config.gateway_secret, headers["X-Request-Timestamp"], headers["X-Request-Id"], self.config.role, canonical)
        self.assertEqual(headers["X-Request-Signature"], expected)
        self.assertEqual(http.posts[1][1]["evidence_blocks"][0]["evidence_id"], "EV-001")
        self.assertEqual(
            http.posts[1][1]["retrieval_request_id"],
            "11111111-1111-4111-8111-111111111111",
        )
        self.assertEqual(http.posts[1][1]["query"], "장애 보고 절차")
        self.assertEqual(
            http.posts[1][1]["actor_hash"],
            http.posts[0][1]["actor_hash"],
        )

    def test_answer_with_unknown_citation_fails_e2e(self) -> None:
        report = ManualRagE2EOrchestrator(self.config, FakeManualRagHttpClient("EV-UNKNOWN")).run()
        self.assertEqual(report.final_stage, "FAILED")
        self.assertIn("exactly match", report.error or "")

    def test_answer_with_forged_citation_text_fails_e2e(self) -> None:
        report = ManualRagE2EOrchestrator(
            self.config,
            FakeManualRagHttpClient(
                answer_citation_text="[다른 문서 v9.9 p.999]"
            ),
        ).run()

        self.assertEqual(report.final_stage, "FAILED")
        self.assertIn("exactly match", report.error or "")

    def test_malformed_or_duplicate_citation_never_passes_e2e(self) -> None:
        evidence = [
            {
                "evidence_id": "EV-001",
                "citation": "[장애 보고 매뉴얼 v1.0 p.1]",
            }
        ]
        for citations in (
            ["not-an-object"],
            [{"evidence_id": "", "citation": ""}],
            [
                {
                    "evidence_id": "EV-001",
                    "citation": "[장애 보고 매뉴얼 v1.0 p.1]",
                },
                {
                    "evidence_id": "EV-001",
                    "citation": "[장애 보고 매뉴얼 v1.0 p.1]",
                },
            ],
        ):
            with self.subTest(citations=citations), self.assertRaises(
                ManualRagE2EError
            ):
                ManualRagE2EOrchestrator._validate_answer(
                    {
                        "status": "ANSWER",
                        "answer": "검증 대상",
                        "citations": citations,
                    },
                    evidence,
                )

    def test_search_results_reject_malformed_missing_or_duplicate_evidence(self) -> None:
        valid = {
            "evidence_id": "EV-001",
            "content": "장애는 즉시 보고한다.",
            "citation": "[장애 보고 매뉴얼 v1.0 p.1]",
        }
        for results in (
            [valid, "not-an-object"],
            [valid, {"evidence_id": "EV-002", "content": "본문만 있음"}],
            [valid, dict(valid)],
            [{**valid, "evidence_id": 1}],
            [{**valid, "content": {"text": "본문"}}],
            [{**valid, "citation": ["잘못된 인용"]}],
        ):
            with self.subTest(results=results), self.assertRaises(ManualRagE2EError):
                ManualRagE2EOrchestrator._evidence_blocks(
                    {"no_evidence": False, "results": results}
                )

    def test_environment_rejects_non_finite_or_unbounded_timeout(self) -> None:
        base = {
            "RAG_E2E_BASE_URL": "http://rag-api:8000",
            "RAG_E2E_GATEWAY_HMAC_SECRET": "x" * 32,
            "RAG_E2E_QUERY": "장애 보고 절차",
        }
        for timeout in ("nan", "inf", "0", "301", "invalid"):
            with self.subTest(timeout=timeout), patch.dict(
                os.environ,
                {**base, "RAG_E2E_TIMEOUT_SECONDS": timeout},
                clear=True,
            ):
                with self.assertRaisesRegex(ManualRagE2EError, "timeout|numeric"):
                    ManualRagE2EConfig.from_environment()

    def test_dynamic_environment_rejects_non_finite_or_unbounded_timeout(self) -> None:
        base = {
            "ANALYSIS_E2E_BASE_URL": "http://analysis:8000",
            "RAG_E2E_BASE_URL": "http://rag:8000",
            "ML_E2E_BASE_URL": "http://ml:8000",
            "RAG_GATEWAY_HMAC_SECRET": "x" * 32,
            "DYNAMIC_E2E_USER_ID": "user-1",
            "DYNAMIC_E2E_ROLE": "analyst",
            "DYNAMIC_E2E_ANALYSIS_QUESTION": "매출 분석",
            "DYNAMIC_E2E_RAG_QUERY": "내부 보고서 근거",
            "DYNAMIC_E2E_ML_METRIC": "room_revenue",
            "DYNAMIC_E2E_ML_HOTEL_SCOPE": "hotel-1",
            "DYNAMIC_E2E_ML_HORIZON": "3",
            "DYNAMIC_E2E_OUTPUT_DIR": self.temporary.name,
        }
        for timeout in ("nan", "inf", "0", "301"):
            with self.subTest(timeout=timeout), patch.dict(
                os.environ,
                {**base, "DYNAMIC_E2E_TIMEOUT_SECONDS": timeout},
                clear=True,
            ):
                with self.assertRaisesRegex(E2EConfigurationError, "between"):
                    DynamicE2EConfig.from_environment()


if __name__ == "__main__":
    unittest.main()
