"""Terra Responses API Supervisor의 strict 계획·보안 경계를 검증한다."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.adapters.openai_supervisor import (  # noqa: E402
    OpenAISupervisorPlanner,
    openai_supervisor_planner_from_env,
)
from app.contracts import RequestContext  # noqa: E402
from app.conversation_contracts import ConversationCommandRequest  # noqa: E402
from app.ports.agent import AgentKind, AgentRequest  # noqa: E402
from app.services.agent_supervisor import AgentDispatchError  # noqa: E402
from app.services.supervisor_planner import (  # noqa: E402
    SupervisorCapabilityCatalog,
    SupervisorMLPropertyScope,
    materialize_supervisor_plan,
)


def _request(message: str = "지난달 객실 매출을 분석해줘") -> AgentRequest:
    conversation_id = uuid4()
    return AgentRequest(
        conversation_id=conversation_id,
        command=ConversationCommandRequest(
            user_message=message,
            idempotency_key=f"supervisor-{uuid4()}",
            expected_head_turn_id=None,
        ),
        context=RequestContext(
            conversation_id=conversation_id,
            user_id=uuid4(),
            command_id=uuid4(),
            permission_snapshot_id="permission-v1",
            product_release_id="product-v1",
            semantic_release_id="semantic-v1",
        ),
    )


def _response(plan: dict[str, object]) -> dict[str, object]:
    return {
        "id": "resp_supervisor_test",
        "status": "completed",
        "error": None,
        "model": "gpt-5.6-terra",
        "output": [
            {
                "type": "message",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": json.dumps(plan)}
                ],
            }
        ],
    }


def test_terra_planner_uses_responses_strict_schema_without_storage() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_response(
                {
                    "schema_version": "SupervisorExecutionPlan.v2",
                    "status": "EXECUTABLE",
                    "tasks": [
                        {
                            "agent": "ANALYSIS_WORKFLOW",
                            "objective": "승인된 객실 매출 지표 분석",
                            "ml_prediction": None,
                        }
                    ],
                    "unavailable_reason": None,
                }
            ),
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            planner = OpenAISupervisorPlanner(
                "https://api.openai.com",
                "test-token",
                client=client,
            )
            request = _request()
            result = await planner.plan(
                request,
                SupervisorCapabilityCatalog(
                    available_agents=(
                        AgentKind.ANALYSIS_WORKFLOW,
                        AgentKind.INTERNAL_GUIDELINE,
                    ),
                    unavailable_agents=(AgentKind.ML_PREDICTION,),
                ),
                previous_route=None,
            )
            return request, result

    request, result = asyncio.run(run())

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["authorization"] == "Bearer test-token"
    assert payload["model"] == "gpt-5.6-terra"
    assert payload["reasoning"] == {"effort": "medium", "context": "current_turn"}
    assert payload["store"] is False
    assert payload["truncation"] == "disabled"
    assert payload["text"]["format"]["strict"] is True
    model_input = json.loads(payload["input"])
    assert model_input["question"] == request.command.user_message
    assert "user_id" not in model_input
    assert result.plan.tasks[0].agent is AgentKind.ANALYSIS_WORKFLOW
    assert re.fullmatch(r"model-supervisor:sha256:[0-9a-f]{64}", result.evidence_ref)


def test_ml_plan_is_materialized_only_from_dynamic_runtime_scope() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(
                {
                    "schema_version": "SupervisorExecutionPlan.v2",
                    "status": "EXECUTABLE",
                    "tasks": [
                        {
                            "agent": "ML_PREDICTION",
                            "objective": "지원 범위의 30일 객실 수요 예측",
                            "ml_prediction": {
                                "property_id": "GRAND",
                                "as_of": "2026-08-28",
                                "horizon_days": 30,
                            },
                        }
                    ],
                    "unavailable_reason": None,
                }
            ),
        )

    catalog = SupervisorCapabilityCatalog(
        available_agents=(
            AgentKind.ANALYSIS_WORKFLOW,
            AgentKind.ML_PREDICTION,
        ),
        unavailable_agents=(AgentKind.INTERNAL_GUIDELINE,),
        ml_properties=(
            SupervisorMLPropertyScope(
                property_id="GRAND",
                min_as_of="2026-01-01",
                max_as_of="2026-08-28",
            ),
        ),
        ml_min_horizon_days=1,
        ml_max_horizon_days=90,
    )
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            planner = OpenAISupervisorPlanner(
                "https://api.openai.com",
                "test-token",
                client=client,
            )
            request = _request("다음 30일 객실 수요를 예측해줘")
            result = await planner.plan(request, catalog, previous_route="ANALYSIS")
            return request, result

    request, result = asyncio.run(run())
    materialized = materialize_supervisor_plan(request, result, catalog)
    planned_request = materialized.requests[0]

    assert planned_request.command.requested_route is None
    assert planned_request.target_agent is AgentKind.ML_PREDICTION
    assert planned_request.invocation is not None
    assert planned_request.invocation.property_id == "GRAND"
    assert planned_request.invocation.horizon_days == 30
    assert planned_request.task_objective == "지원 범위의 30일 객실 수요 예측"
    assert planned_request.supervisor_plan_ref == result.evidence_ref


def test_invalid_model_contract_fails_without_agent_fallback() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(
                {
                    "schema_version": "SupervisorExecutionPlan.v2",
                    "status": "EXECUTABLE",
                    "tasks": [
                        {
                            "agent": "INTERNAL_GUIDELINE",
                            "objective": "문서 검색",
                            "ml_prediction": None,
                        }
                    ],
                    "unavailable_reason": None,
                    "unexpected": "not allowed",
                }
            ),
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            planner = OpenAISupervisorPlanner(
                "https://api.openai.com",
                "test-token",
                client=client,
            )
            await planner.plan(
                _request(),
                SupervisorCapabilityCatalog(
                    available_agents=(AgentKind.ANALYSIS_WORKFLOW,),
                    unavailable_agents=(
                        AgentKind.INTERNAL_GUIDELINE,
                        AgentKind.ML_PREDICTION,
                    ),
                ),
                previous_route=None,
            )

    with pytest.raises(AgentDispatchError) as captured:
        asyncio.run(run())

    assert captured.value.code == "AGENT_SUPERVISOR_CONTRACT_INVALID"


def test_environment_builder_requires_explicit_terra_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPERVISOR_OPENAI_ENDPOINT", "https://api.openai.com")
    monkeypatch.setenv("SUPERVISOR_OPENAI_API_KEY", "test-token")
    monkeypatch.setenv("SUPERVISOR_OPENAI_MODEL", "gpt-5.6-sol")

    with pytest.raises(AgentDispatchError) as captured:
        openai_supervisor_planner_from_env()

    assert captured.value.code == "AGENT_SUPERVISOR_CONFIGURATION_INVALID"
