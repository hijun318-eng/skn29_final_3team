import unittest
from datetime import date
from pathlib import Path
from sys import path
from uuid import UUID


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.contract_model import ContractModelAdapter
from tests.support.fakes import (
    ContractFakeModelAdapter as R3FakeModelAdapter,
    FakeDataPlatformAdapter,
    FakeModelAdapter,
)
from app.contracts import (
    AnalysisRequest,
    AnalysisStatus,
    ErrorCode,
    PipelineStage,
    RequestContext,
    Role,
    StageOutcome,
)
from app.services.analysis_service import AnalysisService
from app.ports.data_platform import NoEntitledAssetsError
from app.services.routing_service import (
    ACCESS_POLICY_VERSION,
    ApprovedTemplate,
    RoutingService,
    _template_role_policy,
)
from src.modelops.runtime import ProductionModelClient


class CountingDataPlatformAdapter(FakeDataPlatformAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.search_count = 0
        self.execute_count = 0

    def search_assets(self, query, context):
        self.search_count += 1
        return super().search_assets(query, context)

    def execute_query(self, sql, parameters, gate_token):
        self.execute_count += 1
        return super().execute_query(sql, parameters, gate_token)


class NoEntitledAssetsAdapter(CountingDataPlatformAdapter):
    def search_assets(self, query, context):
        raise NoEntitledAssetsError("no entitled assets")


class ChartDataPlatformAdapter(CountingDataPlatformAdapter):
    def execute_query(self, sql, parameters, gate_token):
        result = super().execute_query(sql, parameters, gate_token)
        result["rows"] = [
            {
                "month": "2026-05",
                "room_revenue_krw": "218275200.00",
                "fnb_revenue_krw": "39326900.00",
                "total_guest_revenue_krw": "257602100.00",
            },
            {
                "month": "2026-06",
                "room_revenue_krw": "180813600.00",
                "fnb_revenue_krw": "37556700.00",
                "total_guest_revenue_krw": "218370300.00",
            },
        ]
        result["sampling"] = {
            "applied": False,
            "returned_rows": 2,
            "total_rows": 2,
        }
        return result


class MetricCandidateAdapter(CountingDataPlatformAdapter):
    METRICS = {
        "recognized_room_revenue": {
            "id": "recognized_room_revenue",
            "asset_fqn": "pms.public.pms_guests",
            "field": "guest_id",
            "aggregation": "sum",
            "time_field": "guest_id",
            "required_filters": (
                {"field": "guest_id", "operator": "eq", "value": "synthetic"},
            ),
        },
        "fnb_net_revenue": {
            "id": "fnb_net_revenue",
            "asset_fqn": "pms.public.pms_guests",
            "field": "guest_id",
            "aggregation": "sum",
            "time_field": "guest_id",
            "required_filters": (
                {"field": "guest_id", "operator": "eq", "value": "synthetic"},
            ),
        },
    }

    def search_assets(self, query, context):
        metrics = tuple(self.METRICS.values())
        if query == "객실 매출":
            metrics = (self.METRICS["recognized_room_revenue"],) * 2
        return [{**self._asset, "metrics": metrics}]


class CountingModel(FakeModelAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def generate(self, node, payload):
        self.calls += 1
        return super().generate(node, payload)


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


class CapturingContractModel(ContractModelAdapter):
    def __init__(self) -> None:
        super().__init__(R3FakeModelAdapter())
        self.requests = []

    def _generate(self, node, payload):
        self.requests.append((node, payload))
        return super()._generate(node, payload)


class AnalysisPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CountingDataPlatformAdapter()
        self.model = FakeModelAdapter()
        self.service = AnalysisService(self.adapter, self.model)
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
        self.adapter.scenario = scenario
        self.model.scenario = scenario
        question = "합성 객실 운영 현황을 알려줘"
        if scenario:
            question = f"{question} ({scenario})"
        payload = AnalysisRequest(
            question=question,
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
                PipelineStage.MODEL,
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

    def test_general_question_reaches_node2_separately_from_request_id(self) -> None:
        model = CapturingContractModel()
        service = AnalysisService(self.adapter, model)
        payload = AnalysisRequest(question="지난달 객실 매출을 알려줘")

        service.analyze(payload, self.context, self.decision(payload))
        node2 = next(item for node, item in model.requests if node == "node2")

        self.assertEqual(payload.question, node2["normalized_question"])
        self.assertEqual(str(self.context.request_id), node2["question_id"])
        self.assertNotEqual(node2["normalized_question"], node2["question_id"])

    def test_approved_template_reaches_template_route_and_both_gates(self) -> None:
        model = CountingModel()
        service = AnalysisService(self.adapter, model)
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

        response = service.analyze(payload, self.context, decision)

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual("TEMPLATE", response.data.route.value)
        self.assertEqual(template.template_id, response.data.template_id)
        self.assertTrue(response.data.gates.g1_required)
        self.assertTrue(response.data.gates.g2_required)
        self.assertEqual(0, model.calls)
        self.assertEqual("TEMPLATE-RESULT-v1.0.0", response.data.result.evidence.model_version)

    def test_approved_template_g2_failure_does_not_call_model_repair(self) -> None:
        model = CountingModel()
        service = AnalysisService(self.adapter, model)
        template = ApprovedTemplate(
            template_id="weekly-room-operations",
            parameter_names=frozenset(),
            allowed_roles=frozenset({Role.HOTEL_ANALYST}),
            sql_text="SELECT 1 FROM secret.private_table LIMIT 1",
            source_fqns=frozenset({"pms.public.pms_guests"}),
        )
        payload = AnalysisRequest(
            question="weekly room operations",
            template_id=template.template_id,
        )

        response = service.analyze(
            payload,
            self.context,
            RoutingService((template,)).decide(payload),
        )

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ErrorCode.SQL_POLICY_BLOCKED, response.error.code)
        self.assertEqual(0, response.data.repair_count)
        self.assertEqual(0, model.calls)

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

    def test_invalid_metric_selection_blocks_before_model_and_query(self) -> None:
        for question in (
            "호텔 지표",
            "객실 매출과 식음 순매출",
            "소멸 포인트",
            "객실 매출",
        ):
            with self.subTest(question=question):
                adapter = MetricCandidateAdapter()
                model = CountingModel()
                service = AnalysisService(adapter, model)
                payload = AnalysisRequest(question=question)

                response = service.analyze(
                    payload,
                    self.context,
                    self.decision(payload),
                )

                self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
                self.assertEqual(PipelineStage.CONTEXT, response.data.trace[-1].stage)
                self.assertEqual("CONTEXT_INCOMPLETE", response.error.code.value)
                self.assertEqual(0, model.calls)
                self.assertEqual(0, adapter.execute_count)

    def test_missing_entitled_assets_is_context_block_not_internal_failure(self) -> None:
        adapter = NoEntitledAssetsAdapter()
        model = CountingModel()
        service = AnalysisService(adapter, model)
        payload = AnalysisRequest(question="권한 범위 밖의 지표")

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(PipelineStage.CONTEXT, response.data.trace[-1].stage)
        self.assertEqual("CONTEXT_INCOMPLETE", response.error.code.value)
        self.assertEqual(0, model.calls)
        self.assertEqual(0, adapter.execute_count)

    def test_report_admin_is_denied_before_context_or_model_calls(self) -> None:
        adapter = CountingDataPlatformAdapter()
        model = CountingModel()
        service = AnalysisService(adapter, model)
        payload = AnalysisRequest(question="GOLD 고객의 월별 매출")
        admin_context = self.context.model_copy(update={"role": Role.REPORT_ADMIN})

        response = service.analyze(
            payload,
            admin_context,
            self.decision(payload),
        )

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(PipelineStage.CONTROLLER, response.data.trace[-1].stage)
        self.assertEqual(ErrorCode.ACCESS_DENIED, response.error.code)
        self.assertEqual(0, adapter.search_count)
        self.assertEqual(0, model.calls)
        self.assertEqual(0, adapter.execute_count)

    def test_user_parameters_cannot_inject_pipeline_scenarios(self) -> None:
        for scenario in ("access_denied", "inactive_context", "g3_failed"):
            with self.subTest(scenario=scenario):
                payload = AnalysisRequest(
                    question="합성 객실 운영 현황을 알려줘",
                    parameters={"scenario": scenario},
                )
                response = self.service.analyze(
                    payload,
                    self.context,
                    self.decision(payload),
                )
                self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)

    def test_invalid_or_timed_out_model_response_is_safe_failure(self) -> None:
        for scenario in ("invalid_model_schema", "model_timeout"):
            with self.subTest(scenario=scenario):
                response = self.analyze(scenario)
                self.assertEqual(AnalysisStatus.FAILED, response.data.status)
                self.assertEqual("INTERNAL_ERROR", response.error.code.value)
                self.assertEqual(PipelineStage.MODEL, response.data.trace[-1].stage)
                self.assertIsNone(response.data.artifact)
                self.assertEqual(0, self.adapter.execute_count)

    def test_production_model_failure_is_not_accepted_as_analysis_success(self) -> None:
        client = ProductionModelClient(
            lambda _node, _payload, _timeout: (_ for _ in ()).throw(TimeoutError()),
            failure_threshold=1,
        )
        adapter = MetricCandidateAdapter()
        service = AnalysisService(adapter, ContractModelAdapter(client))
        payload = AnalysisRequest(question="합성 객실 운영 현황")

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual("INTERNAL_ERROR", response.error.code.value)
        self.assertEqual(PipelineStage.MODEL, response.data.trace[-1].stage)
        self.assertIsNone(response.data.artifact)
        self.assertEqual(0, adapter.execute_count)
        self.assertFalse(client.last_trace["fallback"])

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
        service = AnalysisService(self.adapter, InvalidRepairModel("repair_once"))
        payload = AnalysisRequest(question="합성 객실 운영 현황을 알려줘")

        with self.assertLogs("uvicorn.error", level="WARNING") as captured:
            response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(1, response.data.repair_count)
        self.assertEqual(0, self.adapter.execute_count)
        log_text = "\n".join(captured.output)
        self.assertIn("sql_sha256=", log_text)
        self.assertNotIn("DELETE FROM pms.public.pms_stays", log_text)

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
        suspicious_adapter = CountingDataPlatformAdapter()
        suspicious_adapter.scenario = "suspicious_zero"
        suspicious_model = FakeModelAdapter("suspicious_zero")
        suspicious_service = AnalysisService(suspicious_adapter, suspicious_model)
        suspicious_payload = AnalysisRequest(
            question="합성 객실 운영 현황을 알려줘"
        )
        suspicious = suspicious_service.analyze(
            suspicious_payload,
            self.context,
            self.decision(suspicious_payload),
        )

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

        self.assertEqual((), result.metrics)
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

    def test_g3_success_links_table_chart_explanation_evidence_and_artifact(self) -> None:
        service = AnalysisService(ChartDataPlatformAdapter(), FakeModelAdapter())
        payload = AnalysisRequest(question="합성 객실 운영 현황을 알려줘")

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual("month", response.data.result.chart.x_field)
        self.assertEqual(
            ("total_guest_revenue_krw",), response.data.result.chart.y_fields
        )
        self.assertEqual(475972400, response.data.result.metrics[0].value)
        self.assertEqual(2, len(response.data.result.table.rows))
        self.assertTrue(response.data.result.summary)
        self.assertEqual(
            response.data.result.evidence.artifact_id,
            response.data.artifact.artifact_id,
        )

    def test_persistence_sink_receives_internal_plan_query_and_context_only_after_g3(self) -> None:
        captured = {}
        success = self.service.analyze(
            AnalysisRequest(question="합성 객실 운영 현황을 알려줘"),
            self.context,
            self.decision(AnalysisRequest(question="합성 객실 운영 현황을 알려줘")),
            captured.update,
        )

        self.assertEqual(AnalysisStatus.SUCCEEDED, success.data.status)
        self.assertEqual({"plan", "query", "package"}, set(captured))

        captured.clear()
        self.adapter.scenario = "g3_failed"
        self.model.scenario = "g3_failed"
        failed_payload = AnalysisRequest(
            question="합성 객실 운영 현황 실패 검증"
        )
        failed = self.service.analyze(
            failed_payload,
            self.context,
            self.decision(failed_payload),
            captured.update,
        )
        self.assertEqual(AnalysisStatus.FAILED, failed.data.status)
        self.assertEqual({}, captured)


if __name__ == "__main__":
    unittest.main()
