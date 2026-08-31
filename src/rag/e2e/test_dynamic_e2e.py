"""명시적으로 활성화된 경우에만 실제 Analysis·RAG·ML 전체 경로의 성공을 검증한다."""

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
    """mock이나 fallback 없이 환경에 지정된 실제 세 런타임의 최종 성공만 허용한다."""

    def test_live_rag_ml_analysis_flow(self) -> None:
        """실설정으로 오케스트레이터를 실행해 최종 단계가 SUCCEEDED인지 확인한다."""

        config = DynamicE2EConfig.from_environment()
        report = DynamicE2EOrchestrator(config).run()
        self.assertEqual(
            report.final_stage,
            E2EStage.SUCCEEDED,
            msg=report.to_dict(),
        )


if __name__ == "__main__":
    unittest.main()
