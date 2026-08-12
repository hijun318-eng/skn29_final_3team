from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.contracts import (
    AnalysisRequest,
    AnalysisStatus,
    ErrorCode,
    PipelineStage,
    RequestContext,
    RouteType,
    StageOutcome,
)
from app.services.analysis_service import AnalysisService
from app.services.routing_service import RouteDecision
from src.modelops.runtime import ModelUnavailableError
from src.modelops.runtime import ProductionModelClient


def test_missing_model_response_field_becomes_model_unavailable():
    model = ProductionModelClient(lambda _node, _payload, _timeout: {})

    try:
        model.generate("node2", {
            "question_id": "question-1",
            "normalized_question": "객실 현황",
            "context_package": {
                "context_version": "context-v1",
                "policy_version": "policy-v1",
                "execution_time": {
                    "as_of": "2026-08-12T00:00:00+09:00",
                    "timezone": "Asia/Seoul",
                    "calendar_id": "gregorian-kr",
                    "period_start": "2026-08-01T00:00:00+09:00",
                    "period_end_exclusive": "2026-08-12T00:00:00+09:00",
                },
                "assets": [{
                    "urn": "urn:room",
                    "trino_fqn": "serving.analytics.room",
                    "columns": ["value"],
                }],
                "metrics": [{
                    "id": "room_value",
                    "field": "serving.analytics.room.value",
                    "aggregation": "sum",
                    "time_field": "serving.analytics.room.business_date",
                    "required_filters": [{
                        "field": "is_forecast",
                        "operator": "eq",
                        "value_type": "boolean",
                        "value": False,
                    }],
                }],
                "joins": [],
            },
        })
    except ModelUnavailableError:
        pass
    else:
        raise AssertionError("missing response fields must fail as unavailable")

    assert model.last_trace["status"] == "SCHEMA_INVALID"


def test_node2_model_unavailable_is_a_safe_failed_response():
    asset = {
        "urn": "urn:room",
        "fqn": "serving.analytics.room",
        "schema_version": "1",
        "seed_version": "1",
    }

    class Adapter:
        @staticmethod
        def search_assets(_query, _context):
            return [asset]

    class Model:
        @staticmethod
        def generate(node, _payload):
            if node == "node1":
                return {"normalized_question": "객실 현황", "ambiguity": "CLEAR"}
            raise ModelUnavailableError(
                "production model unavailable: SCHEMA_INVALID raw-secret"
            )

    package_asset = SimpleNamespace(
        urn=asset["urn"],
        fqn=asset["fqn"],
        columns=("value",),
        join_ids=(),
    )
    package = SimpleNamespace(
        package_hash="context-v1",
        policy_version="policy-v1",
        entitlement_hash="entitlement-v1",
        context_release="context-v1",
        assets=(package_asset,),
        metrics=(),
        parameter_bindings=(),
        access_profile="pms_only",
        allowed_domains=("PMS",),
        approved_join_ids=(),
        trino_principal="pms_reader",
    )
    service = AnalysisService(Adapter(), Model())
    support = MagicMock()
    support.node1_request.return_value = {}
    support.select_metric.return_value = ([asset], "객실 현황")
    support.build_context.return_value = package
    support.g1_error.return_value = None
    service._support = support
    progress = MagicMock()

    response = service.analyze(
        AnalysisRequest(question="객실 현황"),
        RequestContext(user_id=uuid4(), as_of=date(2026, 8, 12)),
        RouteDecision(RouteType.GENERAL, None, True, True),
        progress_sink=progress,
    )

    assert response.data.status is AnalysisStatus.FAILED
    assert response.error.code is ErrorCode.INTERNAL_ERROR
    assert response.error.retryable is True
    assert "raw-secret" not in response.error.message
    assert response.data.trace[-1].stage is PipelineStage.MODEL
    assert response.data.trace[-1].outcome is StageOutcome.FAILED
    progress.assert_any_call("NODE2", "FAILED")
