import unittest
from datetime import date
from pathlib import Path
from sys import path
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.contract_model import ContractModelAdapter
from tests.support.fakes import (
    ContractFakeModelAdapter as R3FakeModelAdapter,
    FakeDataPlatformAdapter,
    FakeModelAdapter,
    _result_metadata,
)
from app.contracts import (
    AnalysisRequest,
    AnalysisStatus,
    ClarificationType,
    ErrorCode,
    PipelineStage,
    RequestContext,
    Role,
    StageOutcome,
)
from app.services.analysis_service import AnalysisService
from app.services.analysis_responses import _evidence_filters
from app.services.context_builder import ContextRequiredFilter
from app.services.execution_control import IsolatedExecutionCache
from app.services.pipeline_support import PipelineSupport, _validated_model_periods
from app.ports.data_platform import NoEntitledAssetsError
from app.services.routing_service import (
    ACCESS_POLICY_VERSION,
    ApprovedTemplate,
    RoutingService,
    _template_role_policy,
)
from src.modelops.runtime import ProductionModelClient
from src.ai.node1 import normalize_question


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


class ContextUnavailableAdapter(CountingDataPlatformAdapter):
    def search_assets(self, query, context):
        raise TimeoutError("context unavailable")


class TrinoUnavailableAdapter(CountingDataPlatformAdapter):
    def execute_query(self, sql, parameters, gate_token):
        raise ConnectionError("trino unavailable")


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
        result["result_metadata"] = _result_metadata(result["rows"])
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
        self.nodes = []

    def generate(self, node, payload):
        self.calls += 1
        self.nodes.append(node)
        return super().generate(node, payload)


class CountingCache(IsolatedExecutionCache):
    def __init__(self) -> None:
        super().__init__()
        self.result_puts = 0

    def put_result(self, key, value):
        self.result_puts += 1
        return super().put_result(key, value)


class TraceEvidenceModel(FakeModelAdapter):
    def generate(self, node, payload):
        response = super().generate(node, payload)
        self.last_trace = {
            "node": node,
            "model_version": response["model_version"],
            "prompt_id": f"{node}-prompt",
            "prompt_version": "v1.0.0",
        }
        return response


class ChartTraceEvidenceModel(TraceEvidenceModel):
    def generate(self, node, payload):
        if node != "node2":
            return super().generate(node, payload)
        response = {
            "sql": (
                "SELECT CAST(guest_id AS VARCHAR) AS month, "
                "0 AS room_revenue_krw, 0 AS fnb_revenue_krw, "
                "0 AS total_guest_revenue_krw "
                "FROM pms.public.pms_guests LIMIT 1000"
            ),
            "references": payload["references"],
            "parameters": {},
            "model_version": "DRAFT-FAKE-BASE-v0.1",
        }
        self.last_trace = {
            "node": node,
            "model_version": response["model_version"],
            "prompt_id": f"{node}-prompt",
            "prompt_version": "v1.0.0",
        }
        return response


class RelativePeriodModel(CountingModel):
    def __init__(self):
        super().__init__()
        self.requests = []

    def normalize_question(self, payload):
        return normalize_question(payload)

    def generate(self, node, payload):
        self.requests.append((node, payload))
        return super().generate(node, payload)


class WrongRelativePeriodModel(RelativePeriodModel):
    def normalize_question(self, payload):
        response = normalize_question(payload)
        response["period_candidates"][0]["start"] = "2026-07-01T00:00:00+09:00"
        return response


class FlakyRelativePeriodModel(RelativePeriodModel):
    def __init__(self):
        super().__init__()
        self.normalize_calls = 0

    def normalize_question(self, payload):
        self.normalize_calls += 1
        response = normalize_question(payload)
        if self.normalize_calls == 1:
            response["period_candidates"][0]["end_exclusive"] = (
                "2026-07-31T00:00:00+09:00"
            )
        return response


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

    def test_multiple_natural_language_periods_return_period_choices(self) -> None:
        adapter = MetricCandidateAdapter()
        model = CountingModel()
        service = AnalysisService(adapter, model)
        payload = AnalysisRequest(
            question="2026년 5월 또는 6월 체크아웃 기준 객실 매출을 보여줘"
        )

        response = service.analyze(
            payload,
            self.context,
            self.decision(payload),
        )

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ErrorCode.CONTEXT_INCOMPLETE, response.error.code)
        self.assertEqual(ClarificationType.PERIOD, response.error.clarification_type)
        self.assertEqual(("2026년 5월", "6월"), response.error.suggestions)
        self.assertEqual(0, model.calls)
        self.assertEqual(0, adapter.execute_count)

    def test_missing_period_is_requested_before_metric_execution(self) -> None:
        adapter = MetricCandidateAdapter()
        model = CountingModel()
        service = AnalysisService(adapter, model)
        payload = AnalysisRequest(question="체크아웃 기준 객실 매출을 보여줘")

        response = service.analyze(
            payload,
            self.context,
            self.decision(payload),
        )

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ClarificationType.PERIOD, response.error.clarification_type)
        self.assertEqual((), response.error.suggestions)
        self.assertIn("예: 2026년 6월", response.error.message)
        self.assertEqual(0, model.calls)
        self.assertEqual(0, adapter.execute_count)

    def test_node1_relative_week_period_reaches_node2_context(self) -> None:
        adapter = MetricCandidateAdapter()
        model = RelativePeriodModel()
        service = AnalysisService(adapter, model)
        payload = AnalysisRequest(question="지난 주 인식 객실 매출을 보여줘")

        response = service.analyze(payload, self.context, self.decision(payload))

        node2 = next(item for node, item in model.requests if node == "node2")
        bindings = {item.name: item.value for item in node2["package"].parameter_bindings}
        self.assertEqual("2026-07-20", bindings["period_start"])
        self.assertEqual("2026-07-27", bindings["period_end_exclusive"])
        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.SQL_REPAIR_FAILED, response.error.code)
        self.assertEqual(PipelineStage.REPAIR, response.data.trace[-1].stage)
        self.assertEqual(0, adapter.execute_count)

    def test_node1_relative_period_outside_calendar_contract_never_reaches_node2(self) -> None:
        adapter = MetricCandidateAdapter()
        model = WrongRelativePeriodModel()
        service = AnalysisService(adapter, model)
        payload = AnalysisRequest(question="지난 주 인식 객실 매출을 보여줘")

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(PipelineStage.MODEL, response.data.trace[-1].stage)
        self.assertEqual(0, model.calls)
        self.assertEqual(0, adapter.execute_count)

    def test_node1_retries_one_calendar_contract_violation_before_node2(self) -> None:
        adapter = MetricCandidateAdapter()
        model = FlakyRelativePeriodModel()
        service = AnalysisService(adapter, model)
        payload = AnalysisRequest(question="이번 주 인식 객실 매출을 보여줘")

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(2, model.normalize_calls)
        self.assertIn("node2", [node for node, _payload in model.requests])
        self.assertEqual(ErrorCode.SQL_REPAIR_FAILED, response.error.code)

    def test_node1_rejects_semantic_period_without_a_deterministic_match(self) -> None:
        candidates = [{
            "start": "2026-01-01T00:00:00+09:00",
            "end_exclusive": "2026-08-13T00:00:00+09:00",
            "source_text": "올해 초부터 지금까지",
        }]

        with self.assertRaisesRegex(ValueError, "no deterministic calendar match"):
            _validated_model_periods(
                "올해 초부터 지금까지 인식 객실 매출을 분석해 줘",
                candidates,
                [],
                ZoneInfo("Asia/Seoul"),
            )

    def test_node1_accepts_contiguous_model_periods_equal_to_one_calendar_range(self) -> None:
        expected = [{
            "start": "2026-05-01T00:00:00+09:00",
            "end_exclusive": "2026-07-01T00:00:00+09:00",
            "source_text": "2026년 5월과 6월",
        }]
        model = [
            {
                "start": "2026-05-01T00:00:00+09:00",
                "end_exclusive": "2026-06-01T00:00:00+09:00",
                "source_text": "2026년 5월",
            },
            {
                "start": "2026-06-01T00:00:00+09:00",
                "end_exclusive": "2026-07-01T00:00:00+09:00",
                "source_text": "2026년 6월",
            },
        ]

        validated = _validated_model_periods(
            "2026년 5월과 6월 통합 매출을 비교해 줘",
            model,
            expected,
            ZoneInfo("Asia/Seoul"),
        )

        self.assertEqual(expected, validated)

    def test_node1_rejects_model_periods_with_gap_inside_calendar_range(self) -> None:
        expected = [{
            "start": "2026-05-01T00:00:00+09:00",
            "end_exclusive": "2026-08-01T00:00:00+09:00",
            "source_text": "2026년 5월부터 7월",
        }]
        model = [
            {
                "start": "2026-05-01T00:00:00+09:00",
                "end_exclusive": "2026-06-01T00:00:00+09:00",
                "source_text": "2026년 5월",
            },
            {
                "start": "2026-07-01T00:00:00+09:00",
                "end_exclusive": "2026-08-01T00:00:00+09:00",
                "source_text": "7월",
            },
        ]

        with self.assertRaisesRegex(ValueError, "candidate count"):
            _validated_model_periods(
                "2026년 5월부터 7월 통합 매출을 비교해 줘",
                model,
                expected,
                ZoneInfo("Asia/Seoul"),
            )

    def test_evidence_filters_expose_approved_fields_not_internal_parameter_names(self) -> None:
        package = SimpleNamespace(
            required_filters=(
                ContextRequiredFilter("crm.grade_code", "eq", "GOLD"),
                ContextRequiredFilter("pms.is_forecast", "eq", False),
            ),
            metrics=(),
        )

        displayed = _evidence_filters(
            {"required_filter_1": "GOLD", "required_filter_2": False},
            package,
        )

        self.assertEqual(
            {"crm.grade_code": "GOLD", "pms.is_forecast": False},
            displayed,
        )

    def test_null_sql_aggregate_becomes_empty_result_not_fake_zero(self) -> None:
        query = {
            "query_id": "query-null-aggregate",
            "status": "SUCCEEDED",
            "rows": [{"recognized_room_revenue": None}],
            "sampling": {"returned_rows": 1, "total_rows": 1},
        }
        package = SimpleNamespace(
            metrics=(SimpleNamespace(id="recognized_room_revenue"),)
        )

        normalized = PipelineSupport.normalize_empty_aggregate(query, package)

        self.assertEqual([], normalized["rows"])
        self.assertEqual({"returned_rows": 0, "total_rows": 0}, normalized["sampling"])
        self.assertIsNone(query["rows"][0]["recognized_room_revenue"])

    def test_explicit_period_with_ambiguous_metrics_returns_metric_choices(self) -> None:
        adapter = MetricCandidateAdapter()
        model = CountingModel()
        service = AnalysisService(adapter, model)
        payload = AnalysisRequest(
            question="2026년 6월 객실 매출과 식음 순매출을 비교해 줘"
        )

        response = service.analyze(
            payload,
            self.context,
            self.decision(payload),
        )

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ClarificationType.METRIC, response.error.clarification_type)
        self.assertEqual(
            ("인식 객실 매출", "식음 순매출"),
            response.error.suggestions,
        )
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
        self.assertEqual("DATA_ASSET_NOT_FOUND", response.error.code.value)
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

    def test_context_source_failure_is_retryable_and_distinct_from_no_asset(self) -> None:
        adapter = ContextUnavailableAdapter()
        payload = AnalysisRequest(question="승인 데이터로 객실 운영 현황을 알려줘")

        response = AnalysisService(adapter, CountingModel()).analyze(
            payload, self.context, self.decision(payload)
        )

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.CONTEXT_SOURCE_FAILED, response.error.code)
        self.assertTrue(response.error.retryable)
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
        expected_codes = {
            "invalid_model_schema": ErrorCode.MODEL_CONTRACT_INVALID,
            "model_timeout": ErrorCode.MODEL_TIMEOUT,
        }
        for scenario, expected_code in expected_codes.items():
            with self.subTest(scenario=scenario):
                response = self.analyze(scenario)
                self.assertEqual(AnalysisStatus.FAILED, response.data.status)
                self.assertEqual(expected_code, response.error.code)
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
        self.assertEqual(ErrorCode.MODEL_TIMEOUT, response.error.code)
        self.assertEqual(PipelineStage.MODEL, response.data.trace[-1].stage)
        self.assertIsNone(response.data.artifact)
        self.assertEqual(0, adapter.execute_count)
        self.assertFalse(client.last_trace["fallback"])

    def test_g2_blocks_unsafe_sql_without_query(self) -> None:
        response = self.analyze("g2_blocked")

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ErrorCode.SQL_POLICY_BLOCKED, response.error.code)
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
        self.assertEqual(
            (StageOutcome.BLOCKED, StageOutcome.PASSED),
            response.data.result.evidence.gate_history.g2,
        )

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

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.SQL_REPAIR_FAILED, response.error.code)
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
                else:
                    self.assertEqual(
                        "EVIDENCE_INCOMPLETE",
                        response.data.trace[-1].detail,
                    )

    def test_g3_failure_prevents_node3_result_cache_artifact_and_ui_result(self) -> None:
        adapter = CountingDataPlatformAdapter()
        adapter.scenario = "g3_failed"
        model = CountingModel()
        cache = CountingCache()
        service = AnalysisService(adapter, model, cache=cache)
        payload = AnalysisRequest(question="합성 객실 운영 현황을 알려줘")

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertNotIn("node3", model.nodes)
        self.assertEqual(0, cache.result_puts)
        self.assertIsNone(response.data.artifact)
        self.assertIsNone(response.data.result)

    def test_query_timeout_is_cancelled_and_terminally_verified(self) -> None:
        response = self.analyze("query_timeout")

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.QUERY_TIMEOUT, response.error.code)
        self.assertEqual(1, len(self.adapter.cancelled_query_ids))
        query_id = self.adapter.cancelled_query_ids[0]
        self.assertEqual(
            "CANCELLED",
            self.adapter.get_query_status(query_id)["status"],
        )
        self.assertIsNone(response.data.artifact)

    def test_trino_connection_failure_is_retryable_and_distinct(self) -> None:
        adapter = TrinoUnavailableAdapter()
        service = AnalysisService(adapter, FakeModelAdapter())
        payload = AnalysisRequest(question="합성 객실 운영 현황을 알려줘")

        response = service.analyze(payload, self.context, self.decision(payload))

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.TRINO_CONNECTION_FAILED, response.error.code)
        self.assertTrue(response.error.retryable)
        self.assertIsNone(response.data.artifact)

    def test_cancelled_query_is_not_reported_as_success(self) -> None:
        response = self.analyze("query_cancelled")

        self.assertEqual(AnalysisStatus.CANCELLED, response.data.status)
        self.assertIsNone(response.data.artifact)

    def test_user_cancellation_stops_before_the_next_expensive_phase(self) -> None:
        payload = AnalysisRequest(question="합성 객실 운영 현황을 알려줘")
        progress = []

        response = self.service.analyze(
            payload,
            self.context,
            self.decision(payload),
            progress_sink=lambda stage, outcome: progress.append((stage, outcome)),
            cancel_check=lambda: True,
        )

        self.assertEqual(AnalysisStatus.CANCELLED, response.data.status)
        self.assertEqual(ErrorCode.REQUEST_CANCELLED, response.error.code)
        self.assertEqual(0, self.adapter.search_count)
        self.assertEqual(0, self.adapter.execute_count)
        self.assertIsNone(response.data.artifact)
        self.assertEqual(
            (PipelineStage.CONTROLLER, StageOutcome.FAILED),
            progress[-1],
        )

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
        self.assertEqual(ErrorCode.RESULT_VALIDATION_FAILED, suspicious.error.code)
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
        service = AnalysisService(ChartDataPlatformAdapter(), ChartTraceEvidenceModel())
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
        evidence = response.data.result.evidence
        self.assertEqual("Asia/Seoul", evidence.timezone)
        self.assertEqual("total_guest_revenue_krw", evidence.metrics[0].metric_id)
        self.assertEqual("객실·식음 통합 매출", evidence.metrics[0].label)
        self.assertTrue(evidence.metrics[0].definition)
        self.assertEqual("KRW", evidence.metrics[0].unit)
        self.assertEqual(response.data.result.metrics, evidence.metric_values)
        self.assertEqual("total_guest_revenue_krw", evidence.metric_values[0].result_field)
        self.assertEqual(475972400, evidence.metric_values[0].value)
        self.assertEqual(
            {"node2", "node3"},
            {invocation.node for invocation in evidence.models},
        )
        self.assertTrue(
            all(invocation.prompt_id.endswith("-prompt") for invocation in evidence.models)
        )
        self.assertEqual(StageOutcome.PASSED, evidence.gates.g1)
        self.assertEqual(StageOutcome.PASSED, evidence.gates.g2)
        self.assertEqual(StageOutcome.PASSED, evidence.gates.g3)
        self.assertEqual((StageOutcome.PASSED,), evidence.gate_history.g1)
        self.assertEqual((StageOutcome.PASSED,), evidence.gate_history.g2)
        self.assertEqual((StageOutcome.PASSED,), evidence.gate_history.g3)

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
