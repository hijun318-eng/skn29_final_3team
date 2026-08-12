from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from sys import path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from opentelemetry.sdk.metrics.export import InMemoryMetricReader  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from app.contracts import (  # noqa: E402
    AnalysisRequest,
    PeriodEvidence,
    RequestContext,
    Role,
    RouteType,
)
from app.services.analysis_service import AnalysisService  # noqa: E402
from app.services.routing_service import RouteDecision  # noqa: E402
from app.telemetry import configure_telemetry, observe_stage  # noqa: E402


class _Adapter:
    def search_assets(self, _query, _context):
        return [{"urn": "urn:room", "fqn": "serving.analytics.room"}]

    def execute_query(self, _sql, _parameters, _gate_token, _principal=None):
        return {"query_id": "query-observability"}

    def get_query_status(self, _query_id):
        return {
            "query_id": "query-observability",
            "status": "SUCCEEDED",
            "rows": [{"value": 1}],
            "evidence_complete": True,
            "filters": {},
            "sampling": {},
            "masking": {},
        }


class _Model:
    def generate(self, node, _payload):
        if node == "node1":
            return {"normalized_question": "approved", "ambiguity": "CLEAR"}
        raise AssertionError(f"template request must not call {node}")


def test_pipeline_spans_metrics_and_logs_share_only_safe_correlation(caplog):
    exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    configure_telemetry(span_exporter=exporter, metric_reader=metric_reader)
    context = RequestContext(
        request_id=uuid4(),
        trace_id="external-trace-42",
        user_id=uuid4(),
        role=Role.HOTEL_ANALYST,
        as_of=date(2026, 8, 12),
    )
    service = AnalysisService(_Adapter(), _Model())
    package = SimpleNamespace(
        package_hash="context-hash",
        policy_version="policy-v1",
        entitlement_hash="entitlement-hash",
        assets=(),
        metrics=(),
        parameter_bindings=(),
        context_release="context-v1",
    )
    support = MagicMock()
    support.node1_request.return_value = {}
    support.select_metric.return_value = ([], "normalized")
    support.build_context.return_value = package
    support.g1_error.return_value = None
    support.model_plan_violation.return_value = None
    support.g2_violation.return_value = None
    support.gate_token.return_value = "secret-gate-token"
    support.g3_violation.return_value = None
    support.artifact_id.return_value = UUID(int=1)
    support.sources.return_value = ()
    support.period.return_value = PeriodEvidence(
        start=date(2026, 8, 1), end_exclusive=date(2026, 8, 12)
    )
    service._support = support

    with caplog.at_level(logging.INFO, logger="answervice.telemetry"):
        progress = []
        with observe_stage("request", context=context):
            response = service.analyze(
                AnalysisRequest(question="sensitive question", parameters={}),
                context,
                RouteDecision(
                    RouteType.TEMPLATE,
                    "room-template",
                    True,
                    True,
                    sql_text="SELECT value FROM serving.analytics.room LIMIT 1",
                    source_fqns=frozenset({"serving.analytics.room"}),
                ),
                progress_sink=lambda stage, outcome: progress.append((stage, outcome)),
            )

    assert response.data.artifact is not None
    assert progress == [
        ("NODE1", "STARTED"), ("NODE1", "PASSED"),
        ("DATAHUB", "STARTED"), ("DATAHUB", "PASSED"),
        ("G1", "STARTED"), ("G1", "PASSED"),
        ("NODE2", "SKIPPED"), ("G2", "STARTED"), ("G2", "PASSED"),
        ("TRINO", "STARTED"), ("TRINO", "PASSED"),
        ("G3", "STARTED"), ("G3", "PASSED"),
        ("NODE3", "SKIPPED"), ("ARTIFACT", "STARTED"), ("ARTIFACT", "PASSED"),
    ]
    spans = exporter.get_finished_spans()
    names = {span.name for span in spans}
    assert {
        "answervice.request",
        "answervice.context",
        "answervice.model",
        "answervice.trino",
        "answervice.artifact",
    }.issubset(names)
    request_span = next(span for span in spans if span.name == "answervice.request")
    children = [span for span in spans if span.parent and span.parent.span_id == request_span.context.span_id]
    assert children
    assert all(span.attributes["answervice.trace_id"] == "external-trace-42" for span in spans)
    serialized = repr([(span.attributes, span.events) for span in spans]) + caplog.text
    assert "sensitive question" not in serialized
    assert "secret-gate-token" not in serialized
    assert "SELECT value" not in serialized

    metrics = metric_reader.get_metrics_data()
    metric_names = {
        metric.name
        for resource in metrics.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    assert {"answervice.stage.count", "answervice.stage.duration"} <= metric_names
