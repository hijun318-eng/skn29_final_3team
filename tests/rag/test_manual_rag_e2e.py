from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.rag.request_auth import GatewayRequestAuthenticator, canonical_search_request
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
                "request_id": "11111111-1111-4111-8111-111111111111",
                "answer_query": "장애 보고 절차",
                "no_evidence": False,
                "results": [
                    {
                        "evidence_id": "EV-001",
                        "content": "장애는 즉시 보고한다.",
                    }
                ],
            }
        return {
            "status": "ANSWER",
            "trace_id": payload["trace_id"],
            "answer": "즉시 보고한다.",
            "citations": [{"evidence_id": self.answer_citation}],
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
        self.assertIn("not returned by the search", report.error or "")


if __name__ == "__main__":
    unittest.main()
