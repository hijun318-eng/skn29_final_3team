import copy
import unittest
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from sys import path
from uuid import UUID


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.contracts import (
    AnalysisRequest,
    AnalysisStatus,
    ClarificationType,
    ErrorCode,
    PipelineStage,
    RequestContext,
    ResolvedSlots,
    Role,
)
from app.ports.data_platform import (
    AssetCandidateSet,
    ExecutionAssetSelection,
    NoEntitledAssetsError,
    NoMetricMatchError,
    ReleaseReceiptChangedError,
    UnsupportedSemanticError,
)
from app.services.analysis import AnalysisService
from app.services.analysis.pipeline_support import PipelineSupport
from app.services.analysis.result_validator import PipelineResultValidator
from app.services.context.builder import ContextPackageBuilder
from app.services.execution_control import ModelCallBudget
from app.services.routing_service import RoutingService
from src.ai.schema import validate_payload
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2


ASSET_FQN = "orion_catalog.analytics.observations"
ASSET_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:trino,"
    "orion_catalog.analytics.observations,PROD)"
)
METRIC_ID = "observed_measure"
RESULT_FIELD = "observed_total"
REQUEST_TEXT = "summarize the governed observation measure"

SCHEMA = {
    "urn": ASSET_URN,
    "columns": [
        {"name": "observation_id", "native_type": "varchar", "nullable": False, "role": "identifier"},
        {"name": "observed_on", "native_type": "date", "nullable": False, "role": "time"},
        {"name": "amount", "native_type": "double", "nullable": False, "role": "measure"},
        {"name": "state_code", "native_type": "varchar", "nullable": False, "role": "attribute"},
    ],
}

METRIC = {
    "id": METRIC_ID,
    "asset_fqn": ASSET_FQN,
    "field": "amount",
    "aggregation": "sum",
    "time_field": "observed_on",
    "result_field": RESULT_FIELD,
    "unit": "arbitrary_unit",
    "reduction": "sum",
    "dimensions": [],
    "visibility": "BUSINESS",
    "governance_version": RUNTIME_GOVERNANCE_VERSION_V2,
    "allowed_roles": ["analyst"],
    "contains_pii": False,
    "allowed_join_ids": [],
    "join_required": False,
    "query_strategies": ["RAW_APPROVED_DETAIL"],
    "required_filters": [
        {
            "field": "state_code",
            "operator": "eq",
            "value_type": "string",
            "value": "accepted",
            "parameter": "state_filter",
        }
    ],
}

ASSET = {
    "urn": ASSET_URN,
    "fqn": ASSET_FQN,
    "name": "Arbitrary observation stream",
    "schema_version": "schema-v7",
    "seed_version": "release-v4",
    "synthetic": True,
    "context_release": "context-v3",
    "policy_version": "policy-v3",
    "grain": {"kind": "event", "keys": ["observation_id"]},
    "join_ids": [],
    "metrics": [METRIC],
    "required_filters": [],
    "time_metadata": {
        "calendar_id": "gregorian-test",
        "start_parameter": "window_start",
        "end_parameter": "window_end",
        "fields": [
            {
                "field": {"asset_fqn": ASSET_FQN, "column": "observed_on"},
                "native_type": "date",
                "bucket": "day",
                "timezone_mode": "context",
            }
        ],
    },
    "query_policy": {
        "dialect": "trino",
        "statement_type": "select",
        "read_only": True,
        "require_limit": True,
        "max_limit": 100,
        "allowed_functions": ["sum", "cast"],
        "allowed_catalogs": ["orion_catalog"],
    },
}

METRIC_TERM = {
    "id": METRIC_ID,
    "urn": f"urn:li:glossaryTerm:{METRIC_ID}",
    "label": "Observed measure",
    "aliases": ["Observed measure", "governed observation measure"],
    "definition": "A reviewed aggregate over arbitrary observations.",
    "unit": "arbitrary_unit",
    "version": "term-v2",
    "checksum": "term-checksum-v2",
}

NODE1_RESPONSE = {
    "normalized_question": "aggregate the resolved observation measure",
    "intent_candidates": ["aggregate"],
    "measurement_source_text": "governed observation measure",
    "measurement_source_texts": ["governed observation measure"],
    "metric_candidates": [METRIC_ID],
    "metric_resolution": "selected",
    "selected_metric_id": METRIC_ID,
    "selected_metric_ids": [METRIC_ID],
    "analysis_operation": "aggregate",
    "analysis_time_bucket": None,
    "result_limit": None,
    "dimension_candidates": [],
    "filter_candidates": [],
    "period_candidates": [
        {
            "start": "2042-06-01T00:00:00+09:00",
            "end_exclusive": "2042-07-01T00:00:00+09:00",
            "source_text": "reviewed-window",
        }
    ],
    "period_relationship": "single",
    "ambiguity": {
        "is_ambiguous": False,
        "reasons": [],
        "clarification_question": None,
    },
}

VALID_SQL = (
    f"SELECT SUM(o.amount) AS {RESULT_FIELD} FROM {ASSET_FQN} AS o "
    "WHERE o.observed_on >= CAST(:window_start AS DATE) "
    "AND o.observed_on < CAST(:window_end AS DATE) "
    "AND o.state_code = :state_filter LIMIT 100"
)
VALID_PLAN = {
    "sql": VALID_SQL,
    "model_version": "programmable-v1",
    "declared_assets": [ASSET_FQN],
    "declared_columns": [
        {"asset_fqn": ASSET_FQN, "column": "amount"},
        {"asset_fqn": ASSET_FQN, "column": "observed_on"},
        {"asset_fqn": ASSET_FQN, "column": "state_code"},
    ],
    "declared_joins": [],
    "declared_metrics": [METRIC_ID],
}
MISSING_FILTER_PLAN = {
    **VALID_PLAN,
    "sql": (
        f"SELECT SUM(o.amount) AS {RESULT_FIELD} FROM {ASSET_FQN} AS o "
        "WHERE o.observed_on >= CAST(:window_start AS DATE) "
        "AND o.observed_on < CAST(:window_end AS DATE) LIMIT 100"
    ),
    "declared_columns": [
        {"asset_fqn": ASSET_FQN, "column": "amount"},
        {"asset_fqn": ASSET_FQN, "column": "observed_on"},
    ],
}
COMPARISON_ASSET = copy.deepcopy(ASSET)
COMPARISON_ASSET["time_metadata"]["comparison_window"] = {
    "start_parameter": "comparison_start",
    "end_parameter": "comparison_end",
}

COMPARISON_NODE1_RESPONSE = copy.deepcopy(NODE1_RESPONSE)
COMPARISON_NODE1_RESPONSE["period_candidates"] = [
    {
        "start": "2042-06-01T00:00:00+09:00",
        "end_exclusive": "2042-07-01T00:00:00+09:00",
        "source_text": "reviewed-window",
    },
    {
        "start": "2042-05-01T00:00:00+09:00",
        "end_exclusive": "2042-06-01T00:00:00+09:00",
        "source_text": "prior-reviewed-window",
    },
]
COMPARISON_NODE1_RESPONSE["period_relationship"] = "comparison"
COMPARISON_NODE1_RESPONSE["intent_candidates"] = ["period_comparison"]
COMPARISON_NODE1_RESPONSE["analysis_operation"] = "period_comparison"

COMPARISON_SQL = (
    f"SELECT SUM(o.amount) FILTER (WHERE o.observed_on >= CAST(:window_start AS DATE) "
    "AND o.observed_on < CAST(:window_end AS DATE)) AS "
    f"{RESULT_FIELD}, "
    "SUM(o.amount) FILTER (WHERE o.observed_on >= CAST(:comparison_start AS DATE) "
    "AND o.observed_on < CAST(:comparison_end AS DATE)) AS "
    f"{RESULT_FIELD}__comparison "
    f"FROM {ASSET_FQN} AS o WHERE o.state_code = :state_filter LIMIT 100"
)
COMPARISON_PLAN = {**VALID_PLAN, "sql": COMPARISON_SQL}
COMPARISON_RESULT = {
    "query_id": "query-arbitrary-comparison-1",
    "status": "SUCCEEDED",
    "rows": [{RESULT_FIELD: 17, f"{RESULT_FIELD}__comparison": 11}],
    "result_metadata": {
        "columns": [
            {"name": RESULT_FIELD, "type": "integer"},
            {"name": f"{RESULT_FIELD}__comparison", "type": "integer"},
        ],
        "row_count": 1,
        "checksum": "2f10ad5af815d065ef29da49b3f45734e879b205e7152adbc2abe0bbf675ecff",
    },
    "evidence_complete": True,
    "zero_result_suspicious": False,
    "filters": {"state_code": "accepted"},
    "sampling": {"applied": False, "returned_rows": 1, "total_rows": 1},
    "masking": {"applied": False, "fields": []},
}

NODE3_RESPONSE = {
    "summary": "Reviewed explanation for the governed result.",
    "model_version": "programmable-v1",
}
QUERY_RESULT = {
    "query_id": "query-arbitrary-1",
    "status": "SUCCEEDED",
    "rows": [{RESULT_FIELD: 17}],
    "result_metadata": {
        "columns": [{"name": RESULT_FIELD, "type": "integer"}],
        "row_count": 1,
        "checksum": "2f597509081eeab2659cefdbe4e058b8dc633eed9e5f5e1dc7a75b800865bf64",
    },
    "evidence_complete": True,
    "zero_result_suspicious": False,
    "filters": {"state_code": "accepted"},
    "sampling": {"applied": False, "returned_rows": 1, "total_rows": 1},
    "masking": {"applied": False, "fields": []},
}


class AsyncProgrammableModel:
    def __init__(self, responses):
        self._responses = defaultdict(deque)
        for node, values in responses.items():
            self._responses[node].extend(values)
        self.calls = []
        self.last_trace = {}
        self.closed = False

    async def normalize_question(self, payload):
        response = await self._next("node1", payload)
        validate_payload("node1_response", response)
        return response

    async def generate(self, node, payload):
        return await self._next(node, payload)

    async def _next(self, node, payload):
        self.calls.append((node, copy.deepcopy(payload)))
        self.last_trace = {
            "node": node,
            "model_version": "programmable-v1",
            "prompt_id": f"test.{node}",
            "prompt_version": "test-v1",
            "prompt_hash": "0" * 64,
            "duration_ms": 0,
            "attempts": 1,
            "status": "SUCCESS",
        }
        if not self._responses[node]:
            raise AssertionError(f"no programmed response for {node}")
        programmed = self._responses[node].popleft()
        if isinstance(programmed, BaseException):
            raise programmed
        value = programmed(node, copy.deepcopy(payload)) if callable(programmed) else programmed
        return copy.deepcopy(value)

    async def aclose(self):
        self.closed = True


class AsyncRuntimeDataPlatform:
    def __init__(
        self,
        *,
        search_error=None,
        resolve_error=None,
        execute_error=None,
        result=None,
        asset=None,
        schema=None,
        metric_terms=None,
        resolved_assets=None,
    ):
        self.search_error = search_error
        self.resolve_error = resolve_error
        self.execute_error = execute_error
        self.result = copy.deepcopy(result or QUERY_RESULT)
        self.asset = copy.deepcopy(asset or ASSET)
        self.schema = copy.deepcopy(schema or SCHEMA)
        self.metric_terms = copy.deepcopy(
            metric_terms or {METRIC_ID: METRIC_TERM}
        )
        self.resolved_assets = copy.deepcopy(
            resolved_assets if resolved_assets is not None else [self.asset]
        )
        self.search_count = 0
        self.search_contexts = []
        self.resolve_count = 0
        self.last_execution_selection = None
        self.execute_count = 0
        self.cancelled = []
        self.closed = False

    async def _candidate_assets(self, query, context):
        self.search_count += 1
        self.search_contexts.append(copy.deepcopy(context))
        if self.search_error is not None:
            raise self.search_error
        return [copy.deepcopy(self.asset)]

    async def search_asset_candidates(self, query, context):
        assets = tuple(await self._candidate_assets(query, context))
        rank = 1
        for asset in assets:
            for metric in asset.get("metrics", ()):
                if metric.get("visibility", "BUSINESS") == "BUSINESS":
                    metric["candidate_selectable"] = True
                    metric["candidate_rank"] = rank
                    metric["source_authority"] = "DATAHUB_NATIVE_METRIC_V1"
                    metric["source_urn"] = f"urn:li:metric:{metric['id']}"
                    rank += 1
        return AssetCandidateSet(
            assets=assets,
            context_release=str(self.asset["context_release"]),
            catalog_checksum="1" * 64,
            canonical_checksum="2" * 64,
            product_release_id="pipeline-test-product-release",
            runtime_projection_checksum="3" * 64,
            source_authority="DATAHUB_NATIVE_METRIC_V1",
            retrieval_mode="lexical",
        )

    async def resolve_execution_assets(
        self,
        selection: ExecutionAssetSelection,
        context,
    ):
        self.resolve_count += 1
        self.last_execution_selection = selection
        if self.resolve_error is not None:
            raise self.resolve_error
        return copy.deepcopy(self.resolved_assets)

    async def get_asset_schema(self, urn, context=None):
        if urn != ASSET_URN:
            raise ValueError("unknown runtime asset")
        return copy.deepcopy(self.schema)

    async def get_metric_terms(self, metric_ids, context=None):
        return {
            metric_id: copy.deepcopy(self.metric_terms[metric_id])
            for metric_id in metric_ids
            if metric_id in self.metric_terms
        }

    async def execute_query(self, sql, parameters, gate_token):
        self.execute_count += 1
        if self.execute_error is not None:
            raise self.execute_error
        return copy.deepcopy(self.result)

    async def get_query_status(self, query_id):
        return copy.deepcopy(self.result) if query_id == self.result["query_id"] else {"status": "NOT_FOUND"}

    async def cancel_query(self, query_id):
        self.cancelled.append(query_id)
        return {"query_id": query_id, "status": "CANCELLED"}

    async def get_source_health(self):
        return [{"source": "arbitrary-runtime", "status": "HEALTHY"}]

    async def aclose(self):
        self.closed = True


def model_with(*, node1=NODE1_RESPONSE, node2=VALID_PLAN, repair=None, node3=NODE3_RESPONSE):
    responses = {"node1": [node1], "node2": [node2], "node3": [node3]}
    if repair is not None:
        responses["node2_repair"] = [repair]
    return AsyncProgrammableModel(responses)


class AnalysisPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = RequestContext(
            request_id=UUID("10000000-0000-0000-0000-000000000001"),
            trace_id="arbitrary-pipeline-trace",
            user_id=UUID("20000000-0000-0000-0000-000000000002"),
            role=Role.ANALYST,
            as_of=date(2042, 6, 15),
        )
        self.payload = AnalysisRequest(question=REQUEST_TEXT)
        self.decision = await RoutingService().decide(self.payload)

    async def run_pipeline(self, *, adapter=None, model=None, context=None, **sinks):
        adapter = adapter or AsyncRuntimeDataPlatform()
        model = model or model_with()
        service = AnalysisService(adapter, model)
        response = await service.analyze(
            self.payload,
            context or self.context,
            self.decision,
            **sinks,
        )
        return response, adapter, model, service

    async def test_success_preserves_orchestration_gates_and_artifact_evidence(self):
        execution = {}
        progress = []
        admissions = []

        async def admit_run(admission_context):
            admissions.append(
                (
                    tuple(stage for stage, _outcome in progress),
                    admission_context,
                )
            )

        response, adapter, model, _service = await self.run_pipeline(
            execution_sink=execution.update,
            progress_sink=lambda stage, outcome: progress.append((stage, outcome)),
            run_admission_sink=admit_run,
        )

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        stages = [step.stage for step in response.data.trace]
        for required in (
            PipelineStage.CONTEXT,
            PipelineStage.G1,
            PipelineStage.G2,
            PipelineStage.QUERY,
            PipelineStage.G3,
            PipelineStage.ARTIFACT,
        ):
            self.assertIn(required, stages)
        self.assertLess(stages.index(PipelineStage.G1), stages.index(PipelineStage.G2))
        self.assertLess(stages.index(PipelineStage.G2), stages.index(PipelineStage.G3))
        self.assertEqual(response.data.artifact.artifact_id, response.data.result.evidence.artifact_id)
        self.assertEqual(17, response.data.result.metrics[0].value)
        self.assertEqual(1, adapter.resolve_count)
        self.assertEqual(
            (METRIC_ID,),
            adapter.last_execution_selection.output_metric_ids,
        )
        self.assertEqual(1, adapter.execute_count)
        self.assertEqual(["node1", "node2", "node3"], [node for node, _ in model.calls])
        self.assertEqual({"plan", "query", "package"}, set(execution))
        self.assertTrue(progress)
        self.assertEqual(1, len(admissions))
        self.assertNotIn(PipelineStage.CONTEXT, admissions[0][0])
        self.assertNotIn(PipelineStage.G1, admissions[0][0])
        self.assertNotIn(PipelineStage.G2, admissions[0][0])
        admitted_context = admissions[0][1]
        self.assertEqual(
            "pipeline-test-product-release",
            admitted_context.product_release_id,
        )
        self.assertEqual("context-v3", admitted_context.semantic_release_id)
        self.assertTrue(admitted_context.permission_snapshot_id)

    async def test_runtime_context_receipt_is_saved_after_admission_before_query(self):
        adapter = AsyncRuntimeDataPlatform()
        events = []

        async def admit_run(_context):
            events.append("admitted")

        async def persist_context(receipt_context, package):
            self.assertEqual(["admitted"], events)
            self.assertEqual(0, adapter.execute_count)
            self.assertEqual(receipt_context.semantic_release_id, package.context_release)
            self.assertEqual(receipt_context.product_release_id, package.product_release_id)
            events.append("context-receipt")

        response, adapter, _model, _service = await self.run_pipeline(
            adapter=adapter,
            run_admission_sink=admit_run,
            context_receipt_sink=persist_context,
        )

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(["admitted", "context-receipt"], events)
        self.assertEqual(1, adapter.execute_count)

    async def test_runtime_context_receipt_failure_submits_no_query(self):
        adapter = AsyncRuntimeDataPlatform()

        async def admit_run(_context):
            return None

        async def fail_context_receipt(_context, _package):
            raise RuntimeError("context receipt store unavailable")

        response, adapter, model, _service = await self.run_pipeline(
            adapter=adapter,
            run_admission_sink=admit_run,
            context_receipt_sink=fail_context_receipt,
        )

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.ARTIFACT_PERSIST_FAILED, response.error.code)
        self.assertEqual(0, adapter.execute_count)
        self.assertEqual(["node1"], [node for node, _payload in model.calls])

    async def test_empty_result_is_blocked_without_artifact(self):
        execution = {}
        empty_result = copy.deepcopy(QUERY_RESULT)
        empty_result["rows"] = []
        empty_result["result_metadata"] = PipelineResultValidator.result_metadata(
            [],
            (RESULT_FIELD,),
        )
        empty_result["sampling"] = {
            "applied": False,
            "returned_rows": 0,
            "total_rows": 0,
        }
        asset_filter = copy.deepcopy(ASSET)
        asset_filter["required_filters"] = copy.deepcopy(
            asset_filter["metrics"][0]["required_filters"]
        )
        asset_filter["metrics"][0]["required_filters"] = []
        adapter = AsyncRuntimeDataPlatform(
            result=empty_result,
            asset=asset_filter,
        )

        response, _adapter, model, _service = await self.run_pipeline(
            adapter=adapter,
            execution_sink=execution.update,
        )

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ErrorCode.EMPTY_RESULT, response.error.code)
        self.assertIsNone(response.data.result)
        self.assertIsNone(response.data.artifact)
        self.assertIsNotNone(response.data.evidence)
        self.assertEqual("query-arbitrary-1", response.data.evidence.query_id)
        self.assertEqual("2042-06-01", response.data.evidence.period.start.isoformat())
        self.assertEqual("2042-06-15", response.data.evidence.period.end_exclusive.isoformat())
        self.assertEqual(
            {f"{ASSET_FQN}.state_code": "accepted"},
            response.data.evidence.filters,
        )
        self.assertEqual(ASSET_URN, response.data.evidence.sources[0].urn)
        self.assertEqual({"plan", "query", "package"}, set(execution))
        self.assertEqual([], execution["query"]["rows"])
        self.assertNotIn("node3", [node for node, _ in model.calls])

    async def test_unproven_partial_query_does_not_create_artifact(self):
        partial_result = copy.deepcopy(QUERY_RESULT)
        partial_result["status"] = "PARTIAL"
        partial_result["warning_count"] = 1
        partial_result["critical_warning_count"] = 1

        response, _adapter, model, _service = await self.run_pipeline(
            adapter=AsyncRuntimeDataPlatform(result=partial_result),
        )

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.RESULT_EVIDENCE_MISSING, response.error.code)
        self.assertIsNone(response.data.result)
        self.assertIsNone(response.data.artifact)
        self.assertNotIn("node3", [node for node, _ in model.calls])

    async def test_completed_query_warning_is_evidence_not_partial_status(self):
        warned_result = copy.deepcopy(QUERY_RESULT)
        warned_result["warnings"] = ("planner notice",)
        warned_result["warning_count"] = 1
        warned_result["critical_warning_count"] = 0

        response, _adapter, _model, _service = await self.run_pipeline(
            adapter=AsyncRuntimeDataPlatform(result=warned_result),
        )

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertIsNone(response.error)
        self.assertEqual(1, response.data.result.evidence.execution.warning_count)
        self.assertEqual(
            0,
            response.data.result.evidence.execution.critical_warning_count,
        )

    async def test_node1_is_counted_by_the_shared_model_budget(self):
        budget = ModelCallBudget()
        budget.count = budget.MAX_CALLS

        response, adapter, model, _service = await self.run_pipeline(
            model_budget=budget,
        )

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.MODEL_CONTRACT_INVALID, response.error.code)
        self.assertEqual([], model.calls)
        self.assertEqual(0, adapter.execute_count)

    async def test_view_reuse_uses_typed_sql_without_calling_node2(self):
        """승인 단일 Serving View는 Node 1 결과를 다시 추측하지 않고 AST로 실행한다."""

        serving_fqn = "serving.semantic.observations"
        asset = copy.deepcopy(ASSET)
        asset["fqn"] = serving_fqn
        asset["metrics"][0]["asset_fqn"] = serving_fqn
        asset["metrics"][0]["query_strategies"] = ["VIEW_REUSE"]
        asset["time_metadata"]["fields"][0]["field"]["asset_fqn"] = serving_fqn
        asset["query_policy"]["allowed_catalogs"] = ["serving"]
        adapter = AsyncRuntimeDataPlatform(asset=asset)
        model = model_with()
        execution = {}

        response, adapter, model, _service = await self.run_pipeline(
            adapter=adapter,
            model=model,
            execution_sink=execution.update,
        )

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(1, adapter.execute_count)
        self.assertEqual(["node1", "node3"], [node for node, _ in model.calls])
        self.assertEqual("typed_sql_compiler", execution["plan"]["plan_source"])
        self.assertIn("SUM", execution["plan"]["sql"])
        model_traces = [
            step.detail
            for step in response.data.trace
            if step.stage is PipelineStage.MODEL
        ]
        self.assertTrue(
            any("node=typed_sql_compiler" in detail for detail in model_traces)
        )

    async def test_multi_metric_request_reaches_result_without_single_metric_collapse(self):
        count_metric_id = "observation_count"
        count_field = "observation_count"
        asset = copy.deepcopy(ASSET)
        count_metric = copy.deepcopy(asset["metrics"][0])
        count_metric.update(
            {
                "id": count_metric_id,
                "aggregation": "count",
                "result_field": count_field,
                "unit": "events",
                "reduction": "sum",
            }
        )
        asset["metrics"].append(count_metric)
        asset["query_policy"]["allowed_functions"].append("COUNT")
        count_term = {
            **METRIC_TERM,
            "id": count_metric_id,
            "urn": f"urn:li:glossaryTerm:{count_metric_id}",
            "label": "Observation count",
            "aliases": ["Observation count"],
            "definition": "Count of governed observations.",
            "unit": "events",
            "checksum": "count-term-checksum",
        }
        rows = [{RESULT_FIELD: 17, count_field: 3}]
        result = {
            **QUERY_RESULT,
            "rows": rows,
            "result_metadata": PipelineResultValidator.result_metadata(
                rows,
                (RESULT_FIELD, count_field),
            ),
            "sampling": {"applied": False, "returned_rows": 1, "total_rows": 1},
        }
        node1 = {
            **NODE1_RESPONSE,
            "normalized_question": "aggregate both governed observation measures",
            "measurement_source_text": None,
            "measurement_source_texts": [
                "governed observation measure",
                "observation count",
            ],
            "metric_candidates": [METRIC_ID, count_metric_id],
            "selected_metric_id": None,
            "selected_metric_ids": [METRIC_ID, count_metric_id],
        }
        plan = {
            **VALID_PLAN,
            "sql": (
                f"SELECT SUM(o.amount) AS {RESULT_FIELD}, "
                f"COUNT(o.amount) AS {count_field} FROM {ASSET_FQN} AS o "
                "WHERE o.observed_on >= CAST(:window_start AS DATE) "
                "AND o.observed_on < CAST(:window_end AS DATE) "
                "AND o.state_code = :state_filter LIMIT 100"
            ),
            "declared_metrics": [METRIC_ID, count_metric_id],
        }
        adapter = AsyncRuntimeDataPlatform(
            asset=asset,
            result=result,
            metric_terms={METRIC_ID: METRIC_TERM, count_metric_id: count_term},
        )
        original_payload = self.payload
        self.payload = AnalysisRequest(
            question="summarize the governed observation measure and observation count"
        )
        try:
            response, _adapter, model, _service = await self.run_pipeline(
                adapter=adapter,
                model=model_with(node1=node1, node2=plan),
            )
        finally:
            self.payload = original_payload

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(
            {METRIC_ID, count_metric_id},
            {metric.metric_id for metric in response.data.result.metrics},
        )
        self.assertIn("17", response.data.result.summary)
        self.assertIn("3", response.data.result.summary)
        self.assertEqual(
            "GROUNDED-MULTI-NARRATIVE-v1.0.0",
            response.data.result.evidence.model_version,
        )
        self.assertEqual(["node1", "node2"], [node for node, _ in model.calls])

    async def test_ungrounded_node3_numbers_are_replaced_with_evidence_summary(self):
        response, adapter, model, _service = await self.run_pipeline(
            model=model_with(
                node3={
                    "summary": "The governed total is 999,999.",
                    "model_version": "programmable-v1",
                }
            )
        )

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertNotIn("999,999", response.data.result.summary)
        self.assertIn("17", response.data.result.summary)
        self.assertEqual(
            "GROUNDED-NARRATIVE-v1.0.0",
            response.data.result.evidence.model_version,
        )
        self.assertEqual(1, adapter.execute_count)
        self.assertEqual(["node1", "node2", "node3"], [node for node, _ in model.calls])

    async def test_grounded_node3_numbers_are_preserved(self):
        summary = "Observed measure is 17 for the requested period."
        response, _adapter, _model, _service = await self.run_pipeline(
            model=model_with(
                node3={"summary": summary, "model_version": "programmable-v1"}
            )
        )

        self.assertEqual(summary, response.data.result.summary)
        self.assertEqual(
            "programmable-v1",
            response.data.result.evidence.model_version,
        )

    async def test_grounded_number_with_unsupported_cause_uses_safe_summary(self):
        response, _adapter, _model, _service = await self.run_pipeline(
            model=model_with(
                node3={
                    "summary": (
                        "Observed measure is 17 because a local event increased demand."
                    ),
                    "model_version": "programmable-v1",
                }
            )
        )

        self.assertNotIn("local event", response.data.result.summary)
        self.assertEqual(
            "GROUNDED-NARRATIVE-v1.0.0",
            response.data.result.evidence.model_version,
        )

    async def test_node3_contract_failure_uses_grounded_result_instead_of_hiding_query(self):
        response, adapter, _model, _service = await self.run_pipeline(
            model=model_with(node3=ValueError("invalid node3 contract"))
        )

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertIn("17", response.data.result.summary)
        self.assertEqual(
            "GROUNDED-NARRATIVE-v1.0.0",
            response.data.result.evidence.model_version,
        )
        self.assertEqual(1, adapter.execute_count)

    async def test_one_g2_repair_uses_only_the_programmed_repair_response(self):
        model = model_with(node2=MISSING_FILTER_PLAN, repair=VALID_PLAN)

        response, adapter, model, _service = await self.run_pipeline(model=model)

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(1, response.data.repair_count)
        self.assertEqual(
            ["node1", "node2", "node2_repair", "node3"],
            [node for node, _ in model.calls],
        )
        self.assertEqual(1, adapter.execute_count)
        repair = next(payload for node, payload in model.calls if node == "node2_repair")
        self.assertEqual(1, repair["attempt"])
        self.assertIn("REQUIRED_FILTER", repair["violation"])

    async def test_unsafe_candidate_is_blocked_by_g2_without_repair_or_query(self):
        unsafe = {
            **VALID_PLAN,
            "sql": f"DELETE FROM {ASSET_FQN}",
            "declared_columns": [],
        }
        response, adapter, model, _service = await self.run_pipeline(model=model_with(node2=unsafe))

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ErrorCode.SQL_POLICY_BLOCKED, response.error.code)
        self.assertEqual(0, response.data.repair_count)
        self.assertEqual(0, adapter.execute_count)
        self.assertEqual(["node1", "node2"], [node for node, _ in model.calls])

    async def test_missing_query_evidence_fails_g3_before_explanation(self):
        result = {**QUERY_RESULT, "evidence_complete": False}
        response, adapter, model, _service = await self.run_pipeline(
            adapter=AsyncRuntimeDataPlatform(result=result)
        )

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.RESULT_EVIDENCE_MISSING, response.error.code)
        self.assertEqual(PipelineStage.G3, response.data.trace[-1].stage)
        self.assertEqual(1, adapter.execute_count)
        self.assertEqual(["node1", "node2"], [node for node, _ in model.calls])

    async def test_role_is_denied_before_metadata_model_or_query_access(self):
        denied_context = self.context.model_copy(update={"role": Role.DATA_ADMIN})

        response, adapter, model, _service = await self.run_pipeline(context=denied_context)

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ErrorCode.ACCESS_DENIED, response.error.code)
        self.assertEqual(0, adapter.search_count)
        self.assertEqual([], model.calls)

    async def test_unentitled_assets_are_blocked_without_model_or_query_calls(self):
        adapter = AsyncRuntimeDataPlatform(
            search_error=NoEntitledAssetsError("no entitled runtime assets")
        )

        response, adapter, model, _service = await self.run_pipeline(adapter=adapter)

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ErrorCode.DATA_ASSET_NOT_FOUND, response.error.code)
        self.assertEqual([], model.calls)
        self.assertEqual(0, adapter.execute_count)

    async def test_release_change_during_execution_resolution_is_retryable(self):
        """후보 이후 release 교체는 입력 부족이 아니라 재시도 가능한 catalog 충돌이다."""

        adapter = AsyncRuntimeDataPlatform(
            resolve_error=ReleaseReceiptChangedError("release receipt changed")
        )
        admissions = []

        async def admit_run(_admission_context):
            admissions.append(True)

        response, adapter, model, _service = await self.run_pipeline(
            adapter=adapter,
            run_admission_sink=admit_run,
        )

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.CONTEXT_SOURCE_FAILED, response.error.code)
        self.assertTrue(response.error.retryable)
        self.assertIn("카탈로그가 갱신", response.error.message)
        self.assertEqual(["node1"], [node for node, _ in model.calls])
        self.assertEqual(0, adapter.execute_count)
        self.assertEqual([True], admissions)

    async def test_pre_resolved_request_cannot_overwrite_its_pinned_release(self):
        """Node 1 fast-path도 고정된 릴리스와 다른 후보 영수증으로 재결속하지 않는다."""

        self.payload = AnalysisRequest(
            question=REQUEST_TEXT,
            resolved_slots=ResolvedSlots(
                metric_id=METRIC_ID,
                period_start="2042-06-01",
                period_end_exclusive="2042-07-01",
            ),
        )
        pinned_context = self.context.model_copy(
            update={
                "product_release_id": "different-product-release",
                "semantic_release_id": "context-v3",
            }
        )
        admissions = []

        async def admit_run(_admission_context):
            admissions.append(True)

        response, adapter, model, _service = await self.run_pipeline(
            context=pinned_context,
            run_admission_sink=admit_run,
        )

        self.assertEqual(AnalysisStatus.FAILED, response.data.status)
        self.assertEqual(ErrorCode.CONTEXT_SOURCE_FAILED, response.error.code)
        self.assertTrue(response.error.retryable)
        self.assertEqual([], model.calls)
        self.assertEqual(0, adapter.resolve_count)
        self.assertEqual([], admissions)

    async def test_execution_graph_gap_is_a_semantic_contract_failure(self):
        """승인 JOIN·grain 부재를 모델 장애나 사용자 기간 누락으로 오분류하지 않는다."""

        adapter = AsyncRuntimeDataPlatform(
            resolve_error=UnsupportedSemanticError("no unique approved join path")
        )

        response, adapter, model, _service = await self.run_pipeline(adapter=adapter)

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ErrorCode.SEMANTIC_CONTRACT_INVALID, response.error.code)
        self.assertIn("승인 관계", response.error.message)
        self.assertEqual(["node1"], [node for node, _ in model.calls])
        self.assertEqual(0, adapter.execute_count)

    async def test_new_analysis_without_metric_requests_metric_context(self):
        adapter = AsyncRuntimeDataPlatform(
            search_error=NoMetricMatchError("no governed metric matches the request")
        )
        admissions = []

        async def admit_run(_admission_context):
            admissions.append(True)

        response, adapter, model, _service = await self.run_pipeline(
            adapter=adapter,
            run_admission_sink=admit_run,
        )

        self.assertEqual(AnalysisStatus.CLARIFICATION_REQUIRED, response.data.status)
        self.assertEqual(ErrorCode.CONTEXT_INCOMPLETE, response.error.code)
        self.assertEqual(ClarificationType.METRIC, response.error.clarification_type)
        self.assertIn("분석할 지표", response.error.message)
        self.assertEqual(1, adapter.search_count)
        self.assertEqual([], adapter.search_contexts[0]["preferred_metric_ids"])
        self.assertEqual([], model.calls)
        self.assertEqual(0, adapter.execute_count)
        self.assertEqual([], admissions)

    async def test_partial_conversation_slots_return_exact_clarification_cause(self):
        """지표 누락은 즉시, range 기간 누락은 선택 자산의 시간 계약 확인 후 구분한다."""

        adapter = AsyncRuntimeDataPlatform(
            search_error=NoEntitledAssetsError("must not search partial slots")
        )
        self.payload = AnalysisRequest(
            question="arbitrary period without a metric",
            resolved_slots=ResolvedSlots(
                period_start="2042-06-01",
                period_end_exclusive="2042-07-01",
            ),
        )
        metric_response, adapter, model, _service = await self.run_pipeline(
            adapter=adapter
        )

        self.assertEqual(
            AnalysisStatus.CLARIFICATION_REQUIRED,
            metric_response.data.status,
        )
        self.assertEqual(ErrorCode.CONTEXT_INCOMPLETE, metric_response.error.code)
        self.assertEqual(
            ClarificationType.METRIC,
            metric_response.error.clarification_type,
        )
        self.assertEqual(0, adapter.search_count)
        self.assertEqual([], model.calls)

        self.payload = AnalysisRequest(
            question="arbitrary metric without a period",
            resolved_slots=ResolvedSlots(metric_id=METRIC_ID),
        )
        period_response, adapter, model, _service = await self.run_pipeline()

        self.assertEqual(
            AnalysisStatus.CLARIFICATION_REQUIRED,
            period_response.data.status,
        )
        self.assertEqual(
            ClarificationType.PERIOD,
            period_response.error.clarification_type,
        )
        self.assertEqual(1, adapter.search_count)
        self.assertEqual(
            [METRIC_ID],
            adapter.search_contexts[0]["preferred_metric_ids"],
        )
        self.assertEqual([], model.calls)

    async def test_pre_resolved_latest_snapshot_without_period_reaches_typed_execution(self):
        """기간 없는 typed 슬롯도 승인 time mode가 snapshot이면 검색 이후 실행까지 도달한다."""

        snapshot_fqn = "serving.semantic.current_snapshot"
        snapshot_asset = copy.deepcopy(ASSET)
        snapshot_asset["fqn"] = snapshot_fqn
        snapshot_asset["metrics"][0]["asset_fqn"] = snapshot_fqn
        snapshot_asset["metrics"][0]["query_strategies"] = ["VIEW_REUSE"]
        snapshot_asset["time_metadata"] = {
            "calendar_id": "gregorian-test",
            "mode": "latest_snapshot",
            "selection": "max_source_value_lt_as_of",
            "as_of_parameter": "snapshot_as_of",
            "fields": copy.deepcopy(ASSET["time_metadata"]["fields"]),
        }
        snapshot_asset["time_metadata"]["fields"][0]["field"]["asset_fqn"] = (
            snapshot_fqn
        )
        snapshot_asset["query_policy"]["allowed_functions"].append("max")
        snapshot_asset["query_policy"]["allowed_catalogs"] = ["serving"]
        self.payload = AnalysisRequest(
            question="summarize the governed current observation measure",
            resolved_slots=ResolvedSlots(
                metric_id=METRIC_ID,
                metric_ids=(METRIC_ID,),
                analysis_operation="aggregate",
            ),
        )

        response, adapter, model, _service = await self.run_pipeline(
            adapter=AsyncRuntimeDataPlatform(asset=snapshot_asset),
        )

        self.assertEqual(
            AnalysisStatus.SUCCEEDED,
            response.data.status,
            response.model_dump(mode="json"),
        )
        self.assertEqual(1, adapter.search_count)
        self.assertEqual(1, adapter.resolve_count)
        self.assertEqual(1, adapter.execute_count)
        self.assertEqual(["node3"], [node for node, _ in model.calls])
        evidence = response.data.result.evidence
        self.assertIsNone(evidence.period)
        self.assertEqual(self.context.as_of, evidence.snapshot.cutoff)
        self.assertEqual(
            "max_source_value_lt_as_of",
            evidence.snapshot.selection,
        )

    async def test_pre_resolved_filter_only_asset_is_rebound_before_typed_request(self):
        """검색 후보 밖의 상속 필터도 동일 release 실행 subgraph에서 보존한다."""

        related_fqn = "orion_catalog.analytics.observation_flags"
        related_urn = (
            "urn:li:dataset:(urn:li:dataPlatform:trino,"
            "orion_catalog.analytics.observation_flags,PROD)"
        )
        join_id = "observations_to_flags"
        candidate = copy.deepcopy(ASSET)
        candidate["metrics"][0]["allowed_join_ids"] = [join_id]
        candidate["dimensions"] = []

        resolved_fact = copy.deepcopy(candidate)
        resolved_fact["join_ids"] = [join_id]
        resolved_fact["join_graph"] = {"edges": [{"id": join_id}]}
        related = {
            **copy.deepcopy(ASSET),
            "urn": related_urn,
            "fqn": related_fqn,
            "name": "Arbitrary observation flags",
            "grain": {"kind": "event", "keys": ["observation_id"]},
            "join_ids": [join_id],
            "join_graph": {"edges": [{"id": join_id}]},
            "metrics": [],
            "dimensions": [
                {
                    "id": "flag_state",
                    "asset_fqn": related_fqn,
                    "column": "flag_state",
                    "aliases": ["Flag state"],
                }
            ],
        }
        adapter = AsyncRuntimeDataPlatform(
            asset=candidate,
            resolved_assets=[resolved_fact, related],
        )
        model = model_with()
        payload = AnalysisRequest(
            question="summarize observations having an accepted related flag",
            resolved_slots=ResolvedSlots(
                metric_id=METRIC_ID,
                metric_ids=(METRIC_ID,),
                user_filters=(
                    {
                        "asset_fqn": related_fqn,
                        "column": "flag_state",
                        "operator": "eq",
                        "value_text": "accepted",
                    },
                ),
                period_start="2042-06-01",
                period_end_exclusive="2042-07-01",
                analysis_operation="aggregate",
            ),
        )
        candidates = await adapter.search_asset_candidates(
            payload.question,
            {
                **self.context.model_dump(mode="json"),
                "preferred_metric_ids": [METRIC_ID],
                "parameters": {},
            },
        )
        support = PipelineSupport(
            adapter,
            ContextPackageBuilder(),
            model,
        )

        _assets, normalized, structured = await support.select_metric(
            payload,
            self.context,
            candidates,
        )

        self.assertEqual(payload.question, normalized)
        self.assertEqual(
            [
                {
                    "asset_fqn": related_fqn,
                    "column": "flag_state",
                    "operator": "eq",
                    "value_text": "accepted",
                }
            ],
            structured["filter_fields"],
        )
        self.assertEqual(1, adapter.resolve_count)
        self.assertEqual(
            {(related_fqn, "flag_state")},
            {
                (item.asset_fqn, item.column)
                for item in adapter.last_execution_selection.field_references
            },
        )
        self.assertEqual([], model.calls)

    async def test_unapproved_query_strategy_is_semantic_not_model_failure(self):
        incompatible = copy.deepcopy(ASSET)
        incompatible["metrics"][0]["query_strategies"] = ["VIEW_REUSE"]

        response, adapter, model, _service = await self.run_pipeline(
            adapter=AsyncRuntimeDataPlatform(asset=incompatible)
        )

        self.assertEqual(AnalysisStatus.BLOCKED, response.data.status)
        self.assertEqual(ErrorCode.SEMANTIC_CONTRACT_INVALID, response.error.code)
        self.assertNotEqual(ErrorCode.MODEL_CONTRACT_INVALID, response.error.code)
        self.assertEqual(["node1"], [node for node, _ in model.calls])
        self.assertEqual(0, adapter.execute_count)

    async def test_multiple_programmed_periods_request_clarification(self):
        ambiguous = copy.deepcopy(NODE1_RESPONSE)
        ambiguous["period_candidates"].append(
            {
                "start": "2042-07-01T00:00:00+09:00",
                "end_exclusive": "2042-08-01T00:00:00+09:00",
                "source_text": "alternate-reviewed-window",
            }
        )
        ambiguous["ambiguity"] = {
            "is_ambiguous": True,
            "reasons": ["period_ambiguous"],
            "clarification_question": "select one governed window",
        }

        response, adapter, model, _service = await self.run_pipeline(
            model=model_with(node1=ambiguous)
        )

        self.assertEqual(AnalysisStatus.CLARIFICATION_REQUIRED, response.data.status)
        self.assertEqual(ErrorCode.CONTEXT_INCOMPLETE, response.error.code)
        self.assertEqual(ClarificationType.PERIOD, response.error.clarification_type)
        self.assertEqual(("reviewed-window", "alternate-reviewed-window"), response.error.suggestions)
        self.assertEqual(["node1"], [node for node, _ in model.calls])
        self.assertEqual(0, adapter.execute_count)

    async def test_comparison_period_relationship_projects_metric_over_two_windows(self):
        adapter = AsyncRuntimeDataPlatform(asset=COMPARISON_ASSET, result=COMPARISON_RESULT)

        response, adapter, model, _service = await self.run_pipeline(
            adapter=adapter,
            model=model_with(node1=COMPARISON_NODE1_RESPONSE, node2=COMPARISON_PLAN),
        )

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(1, adapter.execute_count)
        result = response.data.result
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(("period", RESULT_FIELD), result.table.columns)
        self.assertEqual(
            (
                {"period": "2042-06-01", RESULT_FIELD: 17},
                {"period": "2042-05-01", RESULT_FIELD: 11},
            ),
            result.table.rows,
        )
        self.assertIsNotNone(result.chart)
        assert result.chart is not None
        self.assertEqual("period", result.chart.x_field)
        self.assertEqual((RESULT_FIELD,), result.chart.y_fields)
        self.assertIsNotNone(result.evidence.comparison_period)
        assert result.evidence.comparison_period is not None
        self.assertEqual(
            "2042-05-01",
            result.evidence.comparison_period.start.isoformat(),
        )
        self.assertEqual(2, result.evidence.sampling.returned_rows)
        self.assertIn("17", result.summary)
        self.assertIn("11", result.summary)

    async def test_single_period_uses_comparison_capable_asset_without_second_window(self):
        adapter = AsyncRuntimeDataPlatform(asset=COMPARISON_ASSET, result=QUERY_RESULT)

        response, adapter, model, _service = await self.run_pipeline(
            adapter=adapter,
            model=model_with(node1=NODE1_RESPONSE, node2=VALID_PLAN),
        )

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(1, adapter.execute_count)
        result = response.data.result
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNone(result.evidence.comparison_period)

    async def test_pre_resolved_comparison_keeps_both_windows_and_skips_node1(self):
        original_payload = self.payload
        self.payload = AnalysisRequest(
            question="compare the two governed periods",
            resolved_slots=ResolvedSlots(
                metric_id=METRIC_ID,
                metric_ids=(METRIC_ID,),
                period_start="2042-06-01",
                period_end_exclusive="2042-07-01",
                comparison_period_start="2042-05-01",
                comparison_period_end_exclusive="2042-06-01",
                analysis_operation="period_comparison",
            ),
        )
        try:
            response, adapter, model, _service = await self.run_pipeline(
                adapter=AsyncRuntimeDataPlatform(
                    asset=COMPARISON_ASSET,
                    result=COMPARISON_RESULT,
                ),
                model=model_with(node2=COMPARISON_PLAN),
            )
        finally:
            self.payload = original_payload

        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)
        self.assertEqual(1, adapter.execute_count)
        self.assertEqual(["node2", "node3"], [node for node, _ in model.calls])

    async def test_comparison_relationship_without_a_governed_comparison_window_is_rejected(self):
        response, adapter, model, _service = await self.run_pipeline(
            model=model_with(node1=COMPARISON_NODE1_RESPONSE, node2=COMPARISON_PLAN),
        )

        self.assertEqual(AnalysisStatus.CLARIFICATION_REQUIRED, response.data.status)
        self.assertEqual(0, adapter.execute_count)

    async def test_model_timeout_and_query_connection_error_are_typed(self):
        timeout_model = model_with(node2=TimeoutError("deadline"))
        timeout_response, timeout_adapter, _model, _service = await self.run_pipeline(
            model=timeout_model
        )
        self.assertEqual(ErrorCode.MODEL_TIMEOUT, timeout_response.error.code)
        self.assertTrue(timeout_response.error.retryable)
        self.assertEqual(0, timeout_adapter.execute_count)

        failed_response, failed_adapter, _model, _service = await self.run_pipeline(
            adapter=AsyncRuntimeDataPlatform(execute_error=ConnectionError("offline"))
        )
        self.assertEqual(ErrorCode.TRINO_CONNECTION_FAILED, failed_response.error.code)
        self.assertTrue(failed_response.error.retryable)
        self.assertEqual(1, failed_adapter.execute_count)

    async def test_service_close_awaits_both_async_ports(self):
        response, adapter, model, service = await self.run_pipeline()
        self.assertEqual(AnalysisStatus.SUCCEEDED, response.data.status)

        await service.aclose()

        self.assertTrue(adapter.closed)
        self.assertTrue(model.closed)


if __name__ == "__main__":
    unittest.main()
