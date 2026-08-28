from __future__ import annotations

import os
import unittest

from src.rag.e2e.contracts import DynamicE2EConfig, E2EStage
from src.rag.e2e.orchestrator import DynamicE2EOrchestrator


@unittest.skipUnless(
    os.getenv("DYNAMIC_RAG_ML_E2E") == "true",
    "Dynamic E2E is disabled. Set DYNAMIC_RAG_ML_E2E=true with real runtime endpoints.",
)
class DynamicRagMlE2ETest(unittest.TestCase):
    """Uses only configured live endpoints; no mock, fixture or fallback is allowed."""

    def test_live_rag_ml_analysis_flow(self) -> None:
        config = DynamicE2EConfig.from_environment()
        report = DynamicE2EOrchestrator(config).run()
        self.assertEqual(
            report.final_stage,
            E2EStage.SUCCEEDED,
            msg=report.to_dict(),
        )


if __name__ == "__main__":
    unittest.main()
