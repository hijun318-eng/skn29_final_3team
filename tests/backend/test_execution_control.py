import asyncio
import unittest
from datetime import date
from pathlib import Path
from sys import path
from uuid import UUID


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from tests.support.analysis_runtime_fixture import (
    AnalysisRuntimeDataPlatformFake,
    MetadataDrivenAnalysisModel,
)
from app.contracts import AnalysisRequest, PipelineStage, RequestContext, Role
from app.services.analysis import AnalysisService
from app.services.execution_control import ConcurrentExecutionGate, ModelCallBudget
from app.services.routing_service import RoutingService


class CountingAdapter(AnalysisRuntimeDataPlatformFake):
    def __init__(self) -> None:
        super().__init__()
        self.execute_count = 0

    async def execute_query(self, sql, parameters, gate_token):
        self.execute_count += 1
        return await super().execute_query(sql, parameters, gate_token)


class CountingModel(MetadataDrivenAnalysisModel):
    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    async def generate(self, node, payload):
        self.call_count += 1
        response = await super().generate(node, payload)
        self.last_trace = {
            "node": node,
            "model_version": response["model_version"],
            "prompt_id": f"{node}-prompt",
            "prompt_version": "v1",
        }
        return response


class ExecutionControlTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.adapter = CountingAdapter()
        self.model = CountingModel()
        self.service = AnalysisService(self.adapter, self.model)
        self.payload = AnalysisRequest(question="room demand")
        self.decision = await RoutingService().decide(self.payload)

    @staticmethod
    def context(role=Role.ANALYST, user=2, *, require_fresh_query=False):
        return RequestContext(
            request_id=UUID(int=user + 10),
            trace_id=f"trace-{user}",
            user_id=UUID(int=user),
            role=role,
            as_of=date(2026, 7, 30),
            require_fresh_query=require_fresh_query,
        )

    async def test_plan_and_result_cache_are_separate_and_gates_still_run(self) -> None:
        first = await self.service.analyze(self.payload, self.context(), self.decision)
        second = await self.service.analyze(self.payload, self.context(), self.decision)

        self.assertEqual(1, self.adapter.execute_count)
        self.assertTrue(second.data.result.evidence.cached)
        plan_trace = next(
            step
            for step in second.data.trace
            if step.stage is PipelineStage.MODEL
            and step.detail
            and "plan_cache=" in step.detail
        )
        self.assertIn("plan_cache=hit", plan_trace.detail)
        self.assertIn("prompt=node2-prompt@v1", plan_trace.detail)
        self.assertIn("node2", {item.node for item in second.data.result.evidence.models})
        self.assertIn(PipelineStage.G1, [step.stage for step in second.data.trace])
        self.assertIn(PipelineStage.G2, [step.stage for step in second.data.trace])
        self.assertIn(PipelineStage.G3, [step.stage for step in second.data.trace])
        self.assertFalse(first.data.result.evidence.cached)
        audit_detail = second.data.trace[1].detail
        self.assertTrue(audit_detail.startswith("audit="))
        self.assertNotIn(str(self.context().user_id), audit_detail)

    async def test_cache_key_isolated_by_entitlement_and_mask_scope(self) -> None:
        await self.service.analyze(self.payload, self.context(user=2), self.decision)
        await self.service.analyze(self.payload, self.context(user=3), self.decision)
        denied = await self.service.analyze(
            self.payload,
            self.context(role=Role.DATA_ADMIN, user=2),
            self.decision,
        )

        self.assertEqual("BLOCKED", denied.data.status.value)
        self.assertEqual(2, self.adapter.execute_count)

    async def test_saved_definition_replay_bypasses_result_cache(self) -> None:
        first = await self.service.analyze(self.payload, self.context(), self.decision)
        replay = await self.service.analyze(
            self.payload,
            self.context(require_fresh_query=True),
            self.decision,
        )

        self.assertEqual(2, self.adapter.execute_count)
        self.assertFalse(first.data.result.evidence.cached)
        self.assertFalse(replay.data.result.evidence.cached)

    async def test_model_calls_never_exceed_budget(self) -> None:
        response = await self.service.analyze(
            self.payload,
            self.context(),
            self.decision,
        )

        self.assertEqual("SUCCEEDED", response.data.status.value)
        self.assertLessEqual(self.model.call_count, ModelCallBudget.MAX_CALLS)

    async def test_concurrent_execution_limit_is_two_with_wait_or_reject(self) -> None:
        gate = ConcurrentExecutionGate()

        self.assertTrue(await gate.acquire())
        self.assertTrue(await gate.acquire())
        heartbeat = asyncio.create_task(asyncio.sleep(0))
        self.assertFalse(await gate.acquire(0.01))
        await heartbeat
        self.assertTrue(heartbeat.done())
        gate.release()
        self.assertTrue(await gate.acquire(0.01))
        gate.release()
        gate.release()


if __name__ == "__main__":
    unittest.main()
