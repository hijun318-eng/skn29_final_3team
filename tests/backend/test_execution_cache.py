from __future__ import annotations

from datetime import date
from pathlib import Path
from sys import path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.contracts import (  # noqa: E402
    AnalysisRequest,
    PeriodEvidence,
    RequestContext,
    Role,
    RouteType,
)
from app.services.analysis_service import AnalysisService  # noqa: E402
from app.services.execution_control import (  # noqa: E402
    IsolatedExecutionCache,
    secure_cache_key,
)
from app.services.routing_service import RouteDecision  # noqa: E402


def test_plan_and_result_ttl_expire_and_are_removed_without_shared_mutation():
    now = [10.0]
    cache = IsolatedExecutionCache(lambda: now[0])
    plan = {"sql": "SELECT 1"}
    result = {"rows": [{"value": 1}]}
    cache.put_plan("plan", plan)
    cache.put_result("result", result)
    plan["sql"] = "changed"
    result["rows"][0]["value"] = 2

    assert cache.get_plan("plan") == {"sql": "SELECT 1"}
    assert cache.get_result("result") == {"rows": [{"value": 1}]}
    now[0] += IsolatedExecutionCache.PLAN_TTL_SECONDS
    assert cache.get_plan("plan") is None
    assert "plan" not in cache._plans
    assert cache.get_result("result") is not None
    now[0] = 10.0 + IsolatedExecutionCache.RESULT_TTL_SECONDS
    assert cache.get_result("result") is None
    assert "result" not in cache._results


def test_cache_key_isolates_role_context_policy_time_watermark_and_mask():
    base = {
        "role": "hotel_analyst",
        "context": "context-v1",
        "policy": "policy-v1",
        "as_of": date(2026, 8, 12),
        "watermark": "watermark-v1",
        "mask": "mask-v1",
    }
    original = secure_cache_key("query-result", **base)
    changes = {
        "role": "report_admin",
        "context": "context-v2",
        "policy": "policy-v2",
        "as_of": date(2026, 8, 11),
        "watermark": "watermark-v2",
        "mask": "mask-v2",
    }
    for field, value in changes.items():
        assert secure_cache_key("query-result", **{**base, field: value}) != original


class _Adapter:
    def __init__(self) -> None:
        self.executions = 0

    def search_assets(self, _query, _context):
        return [{"urn": "urn:room", "fqn": "serving.analytics.room", "schema_version": "1", "seed_version": "1"}]

    def execute_query(self, _sql, _parameters, _gate_token):
        self.executions += 1
        return {"query_id": "query-1"}

    def get_query_status(self, _query_id):
        return {
            "query_id": "query-1",
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
            return {"normalized_question": "객실 현황", "ambiguity": "CLEAR"}
        raise AssertionError(f"template cache test must not call {node}")


def test_plan_and_result_hits_still_pass_g2_and_g3():
    adapter = _Adapter()
    cache = IsolatedExecutionCache()
    service = AnalysisService(adapter, _Model(), cache=cache)
    package = SimpleNamespace(
        package_hash="context-v1",
        policy_version="policy-v1",
        entitlement_hash="entitlement-v1",
        assets=(),
        metrics=(),
        parameter_bindings=(),
        context_release="context-v1",
    )
    support = MagicMock()
    support.node1_request.return_value = {}
    support.select_metric.return_value = (adapter.search_assets("", {}), "객실 현황")
    support.build_context.return_value = package
    support.g1_error.return_value = None
    support.model_plan_violation.return_value = None
    support.g2_violation.return_value = None
    support.gate_token.return_value = "gate-token"
    support.g3_violation.return_value = None
    support.artifact_id.return_value = UUID(int=1)
    support.sources.return_value = ()
    support.period.return_value = PeriodEvidence(
        start=date(2026, 8, 1), end_exclusive=date(2026, 8, 12)
    )
    service._support = support
    decision = RouteDecision(
        route_type=RouteType.TEMPLATE,
        template_id="room-template",
        requires_g1=True,
        requires_g2=True,
        sql_text="SELECT value FROM serving.analytics.room LIMIT 1",
        source_fqns=frozenset({"serving.analytics.room"}),
    )
    payload = AnalysisRequest(question="객실 현황")
    context = RequestContext(
        user_id=uuid4(), role=Role.HOTEL_ANALYST, as_of=date(2026, 8, 12)
    )

    first = service.analyze(payload, context, decision)
    second = service.analyze(payload, context.model_copy(update={"request_id": uuid4()}), decision)

    assert first.data.result.evidence.cached is False
    assert second.data.result.evidence.cached is True
    assert adapter.executions == 1
    assert support.g2_violation.call_count == 2
    assert support.g3_violation.call_count == 2
