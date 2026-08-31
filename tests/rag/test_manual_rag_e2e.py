from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.rag.request_auth import (
    GatewayRequestAuthenticator,
    canonical_answer_request,
    canonical_search_request,
)
from src.rag.e2e.manual_rag_e2e import (
    ManualRagE2EConfig,
    ManualRagE2EOrchestrator,
)


class FakeManualRagHttpClient:
    def __init__(self, answer_citation: str = "EV-001") -> None:
        self.answer_citation = answer_citation
        self.posts: list[tuple[str, dict, dict]] = []

    def get(self, url: str) -> dict:
        return {"status": "healthy" if url.endswith("/health/live") else "ready"}

    def post(self, url: str, payload: dict, headers: dict) -> dict:
        self.posts.append((url, payload, headers))
        if url.endswith("internal-manual-search"):
            return {
                "no_evidence": False,
                "request_id": "retrieval-001",
                "results": [{
                    "evidence_id": "EV-001",
                    "content": "제4조 처리 순서 • 장애는 즉시 보고한다.",
                    "manual_id": "MANUAL-001",
                    "title": "장애 대응 지침",
                    "version": "1.0",
                    "page_start": 2,
                    "chunk_index": 3,
                    "score": 0.91,
                    "document_status": "WORKING_KNOWLEDGE",
                    "approval_status": "APPROVED",
                    "validity_status": "VALID",
                    "citation": "[장애 대응 지침 v1.0 p.2]",
                }],
            }
        return {"status": "ANSWER", "answer": "즉시 보고한다.", "citations": [{"evidence_id": self.answer_citation}]}


class ManualRagE2EOrchestratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.config = ManualRagE2EConfig("http://rag-api:8000", "x" * 32, "MANAGER", "장애 보고 절차", 3, 2.0, Path(self.temporary.name), "PROCESS")

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
            None,
            (),
            "PROCESS",
        )
        expected = GatewayRequestAuthenticator.build_signature(self.config.gateway_secret, headers["X-Request-Timestamp"], headers["X-Request-Id"], self.config.role, canonical)
        self.assertEqual(headers["X-Request-Signature"], expected)
        answer_payload, answer_headers = http.posts[1][1], http.posts[1][2]
        evidence = answer_payload["evidence_blocks"][0]
        self.assertEqual(evidence["evidence_id"], "EV-001")
        self.assertEqual(evidence["score"], 0.91)
        self.assertEqual(evidence["version"], "1.0")
        self.assertEqual(evidence["approval_status"], "APPROVED")
        self.assertEqual(answer_payload["intent"], "PROCESS")
        self.assertEqual(answer_payload["retrieval_request_id"], "retrieval-001")
        expected_answer = GatewayRequestAuthenticator.build_signature(
            self.config.gateway_secret,
            answer_headers["X-Request-Timestamp"],
            answer_headers["X-Request-Id"],
            self.config.role,
            canonical_answer_request(
                answer_payload["query"],
                tuple(answer_payload["evidence_blocks"]),
                "PROCESS",
                "retrieval-001",
            ),
        )
        self.assertEqual(answer_headers["X-Request-Signature"], expected_answer)

    def test_answer_with_unknown_citation_fails_e2e(self) -> None:
        report = ManualRagE2EOrchestrator(self.config, FakeManualRagHttpClient("EV-UNKNOWN")).run()
        self.assertEqual(report.final_stage, "FAILED")
        self.assertIn("not returned by the search", report.error or "")


if __name__ == "__main__":
    unittest.main()
