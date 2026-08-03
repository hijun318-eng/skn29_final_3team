import unittest
from datetime import date
from pathlib import Path
from sys import path
from uuid import UUID


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.fake_data_platform import FakeDataPlatformAdapter
from app.adapters.fake_model import FakeModelAdapter
from app.contracts import (
    AnalysisRequest,
    AnalysisStatus,
    PipelineStage,
    RequestContext,
    Role,
    StageOutcome,
)
from app.services.analysis_service import AnalysisService
from app.services.routing_service import (
    ACCESS_POLICY_VERSION,
    ApprovedTemplate,
    RoutingService,
    _template_role_policy,
)


class CountingDataPlatformAdapter(FakeDataPlatformAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.execute_count = 0

    def execute_query(self, sql, parameters, gate_token):
        self.execute_count += 1
        return super().execute_query(sql, parameters, gate_token)


class InvalidRepairModel(FakeModelAdapter):
    def generate(self, node, payload):
        response = super().generate(node, payload)
        if node == "node2_repair":
            response["sql"] = "DELETE FROM pms.public.pms_stays"
        return response


class MisleadingReferenceModel(FakeModelAdapter):
    def generate(self, node, payload):
        response = super().generate(node, payload)
        if node == "node2":
            response["sql"] = "SELECT * FROM secret.private_table"
        return response


class MissingLimitModel(FakeModelAdapter):
    def generate(self, node, payload):
        response = super().generate(node, payload)
        if node == "node2":
            response["sql"] = "SELECT 1 FROM pms.public.pms_guests"
        return response


class AnalysisPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CountingDataPlatformAdapter()
        self.service = AnalysisService(self.adapter, FakeModelAdapter())
        self.context = RequestContext(
            request_id=UUID("00000000-0000-0000-0000-000000000001"),
            trace_id="pipeline-trace",
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            role=Role.HOTEL_ANALYST,
            as_of=date(2026, 7, 30),
        )

    @staticmethod
    def decision(payload: AnalysisRequest):
        return RoutingService().decide(payload)

    def analyze(self, scenario: str | None = None):
        parameters = {} if scenario is None else {"scenario": scenario}
        payload = AnalysisRequest(
            question="합성 객실 운영 현황을 알려줘",
            parameters=parameters,
        )
        return self.service.analyze(
            payload,
            self.context,
            self.decision(payload),
        )

    def test_success_has_fixed_trace_and_artifact(self) -> None:
        response = self.analyze()

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(
            [
                PipelineStage.ROUTER,
                PipelineStage.CONTROLLER,
                PipelineStage.CONTEXT,
                PipelineStage.G1,
                PipelineStage.MODEL,
                PipelineStage.G2,
                PipelineStage.QUERY,
                PipelineStage.G3,
                PipelineStage.ARTIFACT,
            ],
            [step.stage for step in response.data.trace],
        )
        self.assertIsNotNone(response.data.artifact)
        self.assertEqual(
            response.data.artifact.artifact_id,
            response.data.result.evidence.artifact_id,
        )
        self.assertEqual(1, self.adapter.execute_count)

    def test_approved_template_reaches_template_route_and_both_gates(self) -> None:
        template = ApprovedTemplate(
            template_id="weekly-room-operations",
            parameter_names=frozenset({"week_start"}),
            allowed_roles=frozenset({Role.HOTEL_ANALYST}),
            sql_text=(
                "SELECT 1 AS synthetic_value "
                "FROM pms.public.pms_guests LIMIT 1"
            ),
            source_fqns=frozenset({"pms.public.pms_guests"}),
        )
        payload = AnalysisRequest(
            question="weekly room operations",
            template_id=template.template_id,
            parameters={"week_start": "2026-07-27"},
        )
        decision = RoutingService((template,)).decide(payload)

        response = self.service.analyze(payload, self.context, decision)

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual("TEMPLATE", response.data.route.value)
        self.assertEqual(template.template_id, response.data.template_id)
        self.assertTrue(response.data.gates.g1_required)
        self.assertTrue(response.data.gates.g2_required)

    def test_template_role_is_blocked_before_query(self) -> None:
        template = ApprovedTemplate(
            template_id="weekly-room-operations",
            parameter_names=frozenset(),
            allowed_roles=frozenset({Role.HOTEL_ANALYST}),
            sql_text="SELECT 1 FROM pms.public.pms_guests LIMIT 1",
            source_fqns=frozenset({"pms.public.pms_guests"}),
        )

        with self.assertRaisesRegex(ValueError, "권한"):
            RoutingService((template,)).decide(
                AnalysisRequest(
                    question="weekly room operations",
                    template_id=template.template_id,
                ),
                Role.DATA_ADMIN,
            )
        self.assertEqual(0, self.adapter.execute_count)

    def test_template_role_policy_uses_the_approved_config(self) -> None:
        policy = _template_role_policy()

        self.assertEqual("ACCESS-POLICY-v1.0.0", ACCESS_POLICY_VERSION)
        self.assertEqual(
            {Role.HOTEL_ANALYST},
            set(policy["weekly-room-operations"]),
        )

    def test_g1_clarification_blocks_before_model_and_query(self) -> None:
        response = self.analyze("clarification")

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(PipelineStage.G1, response.data.trace[-1].stage)
        self.assertEqual(StageOutcome.BLOCKED, response.data.trace[-1].outcome)
        self.assertIsNone(response.data.artifact)
        self.assertEqual(0, self.adapter.execute_count)

    def test_g1_distinguishes_access_and_inactive_context(self) -> None:
        expected = {
            "access_denied": "ACCESS_DENIED",
            "inactive_context": "CONTEXT_INCOMPLETE",
        }
        for scenario, error_code in expected.items():
            with self.subTest(scenario=scenario):
                response = self.analyze(scenario)
                self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
                self.assertEqual(error_code, response.error.code.value)
                self.assertEqual(0, self.adapter.execute_count)

    def test_invalid_or_timed_out_model_response_is_safe_failure(self) -> None:
        for scenario in ("invalid_model_schema", "model_timeout"):
            with self.subTest(scenario=scenario):
                response = self.analyze(scenario)
                self.assertEqual(AnalysisStatus.FAILED, response.data.status)
                self.assertEqual("INTERNAL_ERROR", response.error.code.value)
                self.assertEqual(PipelineStage.MODEL, response.data.trace[-1].stage)
                self.assertIsNone(response.data.artifact)
                self.assertEqual(0, self.adapter.execute_count)

    def test_g2_blocks_unsafe_sql_without_query(self) -> None:
        response = self.analyze("g2_blocked")

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(PipelineStage.G2, response.data.trace[-1].stage)
        self.assertEqual(0, response.data.repair_count)
        self.assertEqual(0, self.adapter.execute_count)

    def test_g2_repairs_sql_that_hides_an_out_of_context_table(self) -> None:
        service = AnalysisService(self.adapter, MisleadingReferenceModel())
        payload = AnalysisRequest(question="합성 객실 운영 현황")

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(1, response.data.repair_count)
        self.assertEqual(1, self.adapter.execute_count)

    def test_g2_requires_a_hard_limit_before_query(self) -> None:
        service = AnalysisService(self.adapter, MissingLimitModel())
        payload = AnalysisRequest(question="합성 객실 운영 현황")

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(1, response.data.repair_count)
        self.assertEqual(1, self.adapter.execute_count)

    def test_repair_runs_once_then_succeeds(self) -> None:
        response = self.analyze("repair_once")

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(1, response.data.repair_count)
        self.assertEqual(
            1,
            sum(step.stage == PipelineStage.REPAIR for step in response.data.trace),
        )
        self.assertEqual(1, self.adapter.execute_count)

    def test_second_repair_is_never_attempted(self) -> None:
        service = AnalysisService(self.adapter, InvalidRepairModel())
        payload = AnalysisRequest(
            question="합성 객실 운영 현황을 알려줘",
            parameters={"scenario": "repair_once"},
        )

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(1, response.data.repair_count)
        self.assertEqual(0, self.adapter.execute_count)

    def test_query_failure_and_g3_failure_never_create_artifact(self) -> None:
        for scenario, last_stage in (
            ("query_failed", PipelineStage.QUERY),
            ("g3_failed", PipelineStage.G3),
        ):
            with self.subTest(scenario=scenario):
                response = self.analyze(scenario)
                self.assertEqual(AnalysisStatus.FAILED, response.data.status)
                self.assertEqual(last_stage, response.data.trace[-1].stage)
                self.assertIsNone(response.data.artifact)
                if scenario == "query_failed":
                    self.assertTrue(
                        any(
                            step.stage == PipelineStage.QUERY
                            and (step.detail or "").startswith("fake-")
                            for step in response.data.trace
                        )
                    )

    def test_query_timeout_is_cancelled_and_terminally_verified(self) -> None:
        response = self.analyze("query_timeout")

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual("QUERY_SOURCE_FAILED", response.error.code.value)
        self.assertEqual(1, len(self.adapter.cancelled_query_ids))
        query_id = self.adapter.cancelled_query_ids[0]
        self.assertEqual(
            "CANCELLED",
            self.adapter.get_query_status(query_id)["status"],
        )
        self.assertIsNone(response.data.artifact)

    def test_cancelled_query_is_not_reported_as_success(self) -> None:
        response = self.analyze("query_cancelled")

        self.assertEqual(AnalysisStatus.CANCELLED, response.data.status)
        self.assertIsNone(response.data.artifact)

    def test_normal_empty_and_suspicious_empty_are_distinguished(self) -> None:
        empty = self.analyze("empty")
        suspicious = self.analyze("suspicious_zero")

        self.assertEqual(AnalysisStatus.SUCCEEDED, empty.data.status)
        self.assertIsNotNone(empty.data.artifact)
        self.assertEqual(AnalysisStatus.FAILED, suspicious.data.status)
        self.assertIsNone(suspicious.data.artifact)

    def test_partial_result_keeps_artifact_and_error(self) -> None:
        response = self.analyze("partial")

        self.assertEqual(AnalysisStatus.PARTIAL, response.data.status)
        self.assertIsNotNone(response.data.artifact)
        self.assertEqual("PARTIAL_FAILURE", response.error.code.value)

    def test_success_exposes_wave2_display_evidence_and_linked_trace(self) -> None:
        response = self.analyze()
        result = response.data.result

        self.assertEqual("건", result.metrics[0].unit)
        self.assertEqual(date(2026, 7, 1), result.evidence.period.start)
        self.assertEqual(self.context.as_of, result.evidence.period.end_exclusive)
        self.assertEqual({"dataset": "synthetic"}, result.evidence.filters)
        self.assertEqual(1, result.evidence.sampling.returned_rows)
        self.assertEqual(
            response.data.artifact.context_hash,
            next(
                step.detail
                for step in response.data.trace
                if step.stage == PipelineStage.CONTEXT
            ),
        )
        self.assertEqual(
            response.data.artifact.query_id,
            next(
                step.detail
                for step in response.data.trace
                if step.stage == PipelineStage.QUERY
            ),
        )
        self.assertEqual(
            str(response.data.artifact.artifact_id),
            response.data.trace[-1].detail,
        )


if __name__ == "__main__":
    unittest.main()
