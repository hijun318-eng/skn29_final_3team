from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.api.mcp_router import _implemented_tool_descriptors
from app.contracts import Role
from app.ports.mcp_tool import MCPToolDispatchError
from app.services.mcp_agent_tools import (
    ML_PREDICT_NAME,
    ML_PREDICT_OUTPUT_SCHEMA,
    MCPInternalManualExecutor,
    MCPMLPredictionExecutor,
    RAG_TOOL_CODE,
    ml_predict_descriptor,
    rag_answer_descriptor,
)
from app.services.mcp_tool_registry import MCPToolDispatcher, MCPToolRegistry


def _run_async(function):
    """별도 pytest async plugin 없이 표준 asyncio로 coroutine test를 실행한다."""

    @wraps(function)
    def wrapper():
        return asyncio.run(function())

    return wrapper


def _receipt(descriptor: object) -> dict[str, object]:
    public = descriptor.public_definition()
    return {
        "tool_id": str(descriptor.tool_id),
        "tool_code": descriptor.name,
        "semantic_version": descriptor.semantic_version,
        "title": descriptor.title,
        "description": descriptor.description,
        "input_schema_json": public["inputSchema"],
        "output_schema_json": public["outputSchema"],
        "annotations_json": public["annotations"],
        "transport": descriptor.transport,
        "timeout_seconds": descriptor.timeout_seconds,
        "required_roles_json": [role.value for role in descriptor.roles],
        "is_enabled": True,
    }


def _ml_prediction(horizon_days: int = 2) -> dict[str, object]:
    as_of = date(2026, 8, 28)
    targets = [
        as_of + timedelta(days=offset)
        for offset in range(1, horizon_days + 1)
    ]
    return {
        "schema_version": "MLRoomDemandPrediction.v1",
        "status": "SUCCEEDED",
        "execution_id": "fdcb43b6-5479-4c1b-8745-55e370180071",
        "property_id": "GRAND",
        "as_of": as_of.isoformat(),
        "feature_as_of": as_of.isoformat(),
        "horizon_days": horizon_days,
        "model_version": "room-demand-timeseries-hgbr-v2.2.0",
        "model_hash": "a" * 64,
        "feature_contract_sha256": "b" * 64,
        "daily_forecasts": [
            {
                "target_date": target.isoformat(),
                "total_available_rooms": 100.0,
                "predicted_occupied_rooms": 60.0,
                "predicted_available_rooms": 40.0,
                "predicted_occupancy_rate": 0.6,
            }
            for target in targets
        ],
        "room_type_forecasts": [
            {
                "target_date": target.isoformat(),
                "room_type_code": "STANDARD",
                "available_rooms": 100.0,
                "predicted_rooms_raw": 60.0,
                "predicted_rooms": 60.0,
                "occupancy_rate": 0.6,
            }
            for target in targets
        ],
        "provenance": {
            "source": "TRINO_HISTORICAL_DAILY_FACTS",
            "history_table": "pms.ml_evaluation.approved_history",
            "trino_query_id": "trino-prediction-query-1",
            "feature_as_of": as_of.isoformat(),
            "request_as_of": as_of.isoformat(),
            "rag_called": False,
        },
    }


def test_public_mcp_server_assembles_enabled_rag_and_ml_handlers() -> None:
    with patch(
        "app.api.mcp_router.runtime_feature_enabled",
        return_value=True,
    ):
        names = tuple(item.name for item in _implemented_tool_descriptors())

    assert names == ("analysis.get_run", "rag.answer", "ml.predict")


@_run_async
async def test_rag_and_ml_descriptors_are_authorized_registry_tools() -> None:
    rag = rag_answer_descriptor(lambda: "postgresql://runtime")
    ml = ml_predict_descriptor(lambda: "postgresql://runtime")

    async def rows() -> tuple[dict[str, object], ...]:
        return (_receipt(rag), _receipt(ml))

    listed = await MCPToolRegistry((rag, ml), rows).list_authorized(Role.ANALYST)

    assert tuple(item.name for item in listed) == (ML_PREDICT_NAME, RAG_TOOL_CODE)
    assert rag.semantic_version == "1.2.0"
    assert ml.semantic_version == "1.0.0"
    assert "feature_contract_sha256" in ML_PREDICT_OUTPUT_SCHEMA["required"]
    assert "room_type_forecasts" in ML_PREDICT_OUTPUT_SCHEMA["required"]


def test_public_mcp_definition_contains_only_standard_tool_fields() -> None:
    definition = rag_answer_descriptor(lambda: "postgresql://runtime").public_definition()

    assert set(definition) == {
        "name",
        "title",
        "description",
        "inputSchema",
        "outputSchema",
        "annotations",
    }
    assert "roles" not in definition
    assert "handler" not in definition
    assert "timeout_seconds" not in definition


@_run_async
async def test_rag_descriptor_dispatches_gateway_once_and_projects_safe_output() -> None:
    gateway = AsyncMock()
    gateway.execute_mcp_handler.return_value = {
        "status": "ANSWER",
        "trace_id": "trace-rag",
        "answer": {"text": "승인 문서에 따른 답변"},
        "citations": [{"evidence_id": "ev-1", "citation": "문서 1쪽"}],
        "evidence_bundle": [
            {
                "evidence_id": "ev-1",
                "document_id": "FIN-001",
                "document_name": "회계 지침",
                "section": "매출",
                "snippet": "근거 본문",
                "score": 0.91,
                "internal_field": "노출 금지",
            }
        ],
        "internal_field": "노출 금지",
    }
    with patch(
        "app.services.mcp_agent_tools.InternalManualAgent",
        return_value=gateway,
    ):
        result = await MCPToolDispatcher().dispatch(
            rag_answer_descriptor(lambda: "postgresql://runtime"),
            subject_id=uuid4(),
            role=Role.ANALYST,
            trace_id="trace-rag",
            arguments={"query": "매출 하락 지침을 알려줘"},
        )

    gateway.execute_mcp_handler.assert_awaited_once()
    assert result.structured_content["status"] == "ANSWER"
    assert "internal_field" not in result.structured_content
    assert "internal_field" not in result.structured_content["evidence_bundle"][0]
    assert result.audit_output_ref["evidence_ids"] == ["ev-1"]


@_run_async
async def test_ml_descriptor_executes_hgbr_service_and_persists_audit() -> None:
    prediction = _ml_prediction()
    service = AsyncMock()
    service.generate_prediction.return_value = prediction
    session = object()

    @asynccontextmanager
    async def fake_session_scope(_database_url: str):
        yield session

    with patch(
        "app.services.mcp_agent_tools.session_scope",
        fake_session_scope,
    ):
        result = await MCPToolDispatcher().dispatch(
            ml_predict_descriptor(
                lambda: "postgresql://runtime",
                service_factory=lambda: service,
            ),
            subject_id=uuid4(),
            role=Role.ANALYST,
            trace_id="trace-ml",
            arguments={
                "property_id": "GRAND",
                "as_of": "2026-08-28",
                "horizon_days": 2,
            },
        )

    service.generate_prediction.assert_awaited_once_with(
        {
            "property_id": "GRAND",
            "as_of": "2026-08-28",
            "horizon_days": 2,
        }
    )
    service.persist_prediction.assert_awaited_once_with(session, prediction)
    assert result.structured_content["model_hash"] == "a" * 64
    assert result.audit_output_ref["feature_contract_sha256"] == "b" * 64


@_run_async
async def test_ml_descriptor_rejects_uncontracted_arguments_before_handler() -> None:
    service = AsyncMock()
    with pytest.raises(MCPToolDispatchError) as raised:
        await MCPToolDispatcher().dispatch(
            ml_predict_descriptor(
                lambda: "postgresql://runtime",
                service_factory=lambda: service,
            ),
            subject_id=uuid4(),
            role=Role.ANALYST,
            trace_id="trace-ml-invalid",
            arguments={
                "property_id": "GRAND",
                "as_of": "2026-08-28",
                "horizon_days": 2,
                "query": "하드코딩 우회",
            },
        )

    assert raised.value.code == "INVALID_ARGUMENT"
    service.generate_prediction.assert_not_awaited()


@_run_async
async def test_rag_agent_adapter_invokes_governed_mcp_and_keeps_run_receipt() -> None:
    tool_run_id = uuid4()
    governed = AsyncMock()
    governed.execute.return_value = SimpleNamespace(
        structured_content={
            "status": "ANSWER",
            "trace_id": "trace-rag-agent",
            "answer": {"text": "근거 답변"},
            "citations": [{"evidence_id": "ev-1", "citation": "1쪽"}],
            "evidence_bundle": [
                {
                    "evidence_id": "ev-1",
                    "document_id": "FIN-001",
                    "document_name": "회계 지침",
                    "section": "매출",
                    "snippet": "근거",
                    "score": 0.9,
                }
            ],
        },
        tool_run_id=tool_run_id,
    )
    actor_id = uuid4()
    adapter = MCPInternalManualExecutor(
        "postgresql://runtime",
        governed_executor=governed,
    )

    result = await adapter.execute(
        "매출 지침을 알려줘",
        actor_id,
        Role.ANALYST.value,
        "trace-rag-agent",
    )

    governed.execute.assert_awaited_once_with(
        RAG_TOOL_CODE,
        subject_id=actor_id,
        role=Role.ANALYST,
        trace_id="trace-rag-agent",
        arguments={
            "query": "매출 지침을 알려줘",
            "recent_utterances": [],
            "selected_document_ids": [],
        },
    )
    assert result["mcp_tool_run_id"] == str(tool_run_id)
    assert result["routing"]["selected_document_ids"] == ["FIN-001"]


@_run_async
async def test_ml_agent_adapter_invokes_governed_mcp_and_keeps_run_receipt() -> None:
    tool_run_id = uuid4()
    governed = AsyncMock()
    prediction = _ml_prediction()
    governed.execute.return_value = SimpleNamespace(
        structured_content=prediction,
        tool_run_id=tool_run_id,
    )
    actor_id = uuid4()
    adapter = MCPMLPredictionExecutor(
        "postgresql://runtime",
        service=AsyncMock(),
        governed_executor=governed,
    )

    result = await adapter.execute(
        {
            "property_id": "GRAND",
            "as_of": "2026-08-28",
            "horizon_days": 2,
        },
        subject_id=actor_id,
        role=Role.ANALYST,
        trace_id="trace-ml-agent",
    )

    governed.execute.assert_awaited_once_with(
        ML_PREDICT_NAME,
        subject_id=actor_id,
        role=Role.ANALYST,
        trace_id="trace-ml-agent",
        arguments={
            "property_id": "GRAND",
            "as_of": "2026-08-28",
            "horizon_days": 2,
        },
    )
    assert result["mcp_tool_run_id"] == str(tool_run_id)
