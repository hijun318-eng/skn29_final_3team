from datetime import date
from pathlib import Path
from sys import path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.contracts import (  # noqa: E402
    AnalysisRequest,
    AnalysisStatus,
    ErrorCode,
    PipelineStage,
    RequestContext,
    Role,
    RouteType,
)
from app.services.analysis_service import AnalysisService  # noqa: E402
from app.services.execution_control import IsolatedExecutionCache  # noqa: E402
from app.services.pipeline_support import PipelineSupport  # noqa: E402
from app.services.routing_service import RouteDecision  # noqa: E402


class _Adapter:
    def __init__(self, query):
        self.query = query

    def search_assets(self, _query, _context):
        return [
            {
                "urn": "urn:room",
                "fqn": "serving.analytics.room",
                "schema_version": "1",
                "seed_version": "1",
            }
        ]

    def execute_query(self, _sql, _parameters, _gate_token):
        return {"query_id": self.query["query_id"]}

    def get_query_status(self, _query_id):
        return self.query


class _Model:
    def __init__(self):
        self.calls = []

    def generate(self, node, _payload):
        self.calls.append(node)
        if node == "node1":
            return {"normalized_question": "객실 현황", "ambiguity": "CLEAR"}
        if node == "node2":
            return {
                "sql": "SELECT value FROM serving.analytics.room LIMIT 1000",
                "parameters": {},
                "references": [],
                "model_version": "test-node2",
            }
        raise AssertionError("G3 실패 뒤 Node3를 호출하면 안 됩니다.")


def _query(rows, **updates):
    return {
        "query_id": "query-g3-negative",
        "status": "SUCCEEDED",
        "rows": rows,
        "evidence_complete": True,
        "zero_result_suspicious": False,
        "filters": {},
        "sampling": {},
        "masking": {},
        **updates,
    }


@pytest.mark.parametrize(
    ("expected_violation", "query"),
    (
        ("EVIDENCE_INCOMPLETE", _query([{"value": 1}], evidence_complete=False)),
        ("SUSPICIOUS_EMPTY_RESULT", _query([], zero_result_suspicious=True)),
        (
            "RESULT_RANGE_EXCEEDED",
            _query([{"value": index} for index in range(101)]),
        ),
        (
            "RESULT_RANGE_EXCEEDED",
            _query([{f"column_{index}": index for index in range(21)}]),
        ),
        (
            "RESULT_RANGE_EXCEEDED",
            _query(
                [
                    {f"column_{column}": row for column in range(21)}
                    for row in range(100)
                ]
            ),
        ),
    ),
    ids=("evidence", "suspicious-empty", "rows", "columns", "cells"),
)
def test_g3_negative_stops_node3_result_cache_execution_and_artifact(
    expected_violation, query
):
    adapter = _Adapter(query)
    model = _Model()
    cache = MagicMock(wraps=IsolatedExecutionCache())
    service = AnalysisService(adapter, model, cache=cache)
    package = SimpleNamespace(
        package_hash="context-v1",
        policy_version="policy-v1",
        entitlement_hash="entitlement-v1",
        context_release="context-v1",
        assets=(
            SimpleNamespace(
                urn="urn:room",
                fqn="serving.analytics.room",
                columns=("value",),
                join_ids=(),
            ),
        ),
        metrics=(),
        parameter_bindings=(),
    )
    support = MagicMock()
    support.node1_request.return_value = {}
    support.select_metric.return_value = (adapter.search_assets("", {}), "객실 현황")
    support.build_context.return_value = package
    support.g1_error.return_value = None
    support.model_plan_violation.return_value = None
    support.g2_violation.return_value = None
    support.gate_token.return_value = "gate-token"
    support.g3_violation.side_effect = PipelineSupport.g3_violation
    service._support = support
    execution_sink = MagicMock()

    response = service.analyze(
        AnalysisRequest(question="객실 현황"),
        RequestContext(
            user_id=uuid4(), role=Role.HOTEL_ANALYST, as_of=date(2026, 8, 12)
        ),
        RouteDecision(RouteType.GENERAL, None, True, True),
        execution_sink,
    )

    assert support.g3_violation(query) == expected_violation
    assert response.data.status is AnalysisStatus.FAILED
    assert response.error.code is ErrorCode.RESULT_EVIDENCE_MISSING
    assert response.data.result is None
    assert response.data.artifact is None
    assert [step.stage for step in response.data.trace][-1] is PipelineStage.G3
    assert PipelineStage.ARTIFACT not in {step.stage for step in response.data.trace}
    assert model.calls == ["node1", "node2"]
    assert model.calls.count("node3") == 0
    support.artifact_id.assert_not_called()
    cache.put_result.assert_not_called()
    execution_sink.assert_not_called()
