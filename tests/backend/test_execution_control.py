import unittest
from datetime import date
from pathlib import Path
from sys import path
from uuid import UUID


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from tests.support.fakes import FakeDataPlatformAdapter, FakeModelAdapter
from app.contracts import AnalysisRequest, PipelineStage, RequestContext, Role
from app.services.analysis_service import AnalysisService
from app.services.execution_control import ConcurrentExecutionGate, ModelCallBudget
from app.services.routing_service import RoutingService


class CountingAdapter(FakeDataPlatformAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.execute_count = 0

    def execute_query(self, sql, parameters, gate_token):
        self.execute_count += 1
        return super().execute_query(sql, parameters, gate_token)


class CountingModel(FakeModelAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    def generate(self, node, payload):
        self.call_count += 1
        return super().generate(node, payload)


class ExecutionControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CountingAdapter()
        self.model = CountingModel()
        self.service = AnalysisService(self.adapter, self.model)
        self.payload = AnalysisRequest(question="room demand")
        self.decision = RoutingService().decide(self.payload)

    @staticmethod
    def context(role=Role.HOTEL_ANALYST, user=2):
        return RequestContext(
            request_id=UUID(int=user + 10),
            trace_id=f"trace-{user}",
            user_id=UUID(int=user),
            role=role,
            as_of=date(2026, 7, 30),
        )

    def test_plan_and_result_cache_are_separate_and_gates_still_run(self) -> None:
        first = self.service.analyze(self.payload, self.context(), self.decision)
        second = self.service.analyze(self.payload, self.context(), self.decision)

        self.assertEqual(1, self.adapter.execute_count)
        self.assertTrue(second.data.result.evidence.cached)
        self.assertIn("plan_cache=hit", second.data.trace[4].detail)
        self.assertIn(PipelineStage.G1, [step.stage for step in second.data.trace])
        self.assertIn(PipelineStage.G2, [step.stage for step in second.data.trace])
        self.assertIn(PipelineStage.G3, [step.stage for step in second.data.trace])
        self.assertFalse(first.data.result.evidence.cached)
        audit_detail = second.data.trace[1].detail
        self.assertTrue(audit_detail.startswith("audit="))
        self.assertNotIn(str(self.context().user_id), audit_detail)

    def test_cache_key_isolated_by_entitlement_and_mask_scope(self) -> None:
        self.service.analyze(self.payload, self.context(user=2), self.decision)
        self.service.analyze(self.payload, self.context(user=3), self.decision)
        denied = self.service.analyze(
            self.payload,
            self.context(role=Role.DATA_ADMIN, user=2),
            self.decision,
        )

        self.assertEqual("BLOCKED", denied.data.status.value)
        self.assertEqual(2, self.adapter.execute_count)

    def test_model_calls_never_exceed_budget(self) -> None:
        response = self.service.analyze(self.payload, self.context(), self.decision)

        self.assertEqual("SUCCEEDED", response.data.status.value)
        self.assertLessEqual(self.model.call_count, ModelCallBudget.MAX_CALLS)

    def test_concurrent_execution_limit_is_two_with_wait_or_reject(self) -> None:
        gate = ConcurrentExecutionGate()

        self.assertTrue(gate.acquire())
        self.assertTrue(gate.acquire())
        self.assertFalse(gate.acquire(0.01))
        gate.release()
        self.assertTrue(gate.acquire(0.01))
        gate.release()
        gate.release()


if __name__ == "__main__":
    unittest.main()
