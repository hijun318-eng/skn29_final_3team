"""Bounded Governed Multi-turn ConversationOrchestrator 테스트.

CAS(expected_head_turn_id) 검사, 동시성 Lease, Idempotency 보장,
3대 Route(ANALYSIS, PRESENTATION, REPORT_ACTION) 실행 및 Fail-closed 검증.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent_contracts import AgentDecisionSource, AgentExecutionPhase
from app.contracts import (
    AnalysisData,
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    ClarificationType,
    DisambiguationOption,
    ErrorBody,
    ErrorCode,
    RequestContext,
    Role,
)
from app.authorization import permission_snapshot_id as compute_permission_snapshot_id
from app.conversation_contracts import ConversationCommandRequest
from app.ports.agent import (
    AgentKind,
    AgentPortReadiness,
    AgentRequest,
    MLPredictionInvocation,
)
from app.ports.data_platform import AssetCandidateSet, NoEntitledAssetsError
from app.services.agent_supervisor import (
    AgentDispatchError,
    SupervisorDecision,
)
from app.services.conversation.orchestrator import (
    ConversationOrchestrator,
    _business_terms_for_turn,
    _safe_analysis_observation,
    _view_contract,
)
from app.services.execution_control import ConcurrentExecutionGate
from app.services.supervisor_planner import (
    SupervisorExecutionPlan,
    SupervisorPlanResult,
    SupervisorTaskPlan,
)


TEST_PRODUCT_RELEASE = "product-release:test"
TEST_SEMANTIC_RELEASE = "semantic-release:test"


class _MLMCPExecutor:
    """Orchestrator unit test가 명시적으로 주입하는 MCP Tool test double이다."""

    def __init__(self, service: Any) -> None:
        self._service = service

    async def readiness(self, _role: Role) -> AgentPortReadiness:
        return await self._service.readiness()

    async def execute(self, payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        prediction = dict(await self._service.generate_prediction(payload))
        prediction["mcp_tool_run_id"] = str(uuid4())
        await self._service.persist_prediction(object(), prediction)
        return prediction


def _ml_mcp_executor_factory(service: Any) -> _MLMCPExecutor:
    return _MLMCPExecutor(service)


def test_initial_summary_view_does_not_persist_an_unsolicited_chart() -> None:
    """초기 SUMMARY 요청은 Artifact의 추천 chart와 무관하게 중립 ViewSpec을 남긴다."""

    response = SimpleNamespace(
        data=SimpleNamespace(
            result=SimpleNamespace(
                chart=SimpleNamespace(
                    chart_type="bar",
                    x_field="period",
                    y_fields=("room_revenue",),
                )
            )
        )
    )

    view = _view_contract(response, uuid4(), "SUMMARY")

    assert view["view_type"] == "TABLE"
    assert view["spec_json"]["chart_type"] == "table"


def test_safe_analysis_observation_excludes_sql_rows_and_parameters() -> None:
    metric = SimpleNamespace(
        id="sample_revenue",
        asset_fqn="serving.sample.daily",
        numerator_metric_id="",
        denominator_metric_id="",
    )
    result = _safe_analysis_observation(
        {
            "plan": {
                "sql": "SELECT secret",
                "parameters": {"hidden": "value"},
                "analysis_plan": {
                    "output_metric_ids": ["sample_revenue"],
                    "joins": [
                        {
                            "join_id": "approved_join",
                            "plan": "PREAGGREGATE",
                            "reason": "MULTI_FACT_COMMON_GRAIN",
                        }
                    ],
                    "query_strategy": "VIEW_REUSE",
                    "time_bucket": "month",
                    "checksum": "a" * 64,
                },
            },
            "package": SimpleNamespace(metrics=(metric,)),
            "query": {"rows": [{"secret": "value"}]},
        }
    )

    assert result == {
        "query_strategy": "VIEW_REUSE",
        "source_assets": ["serving.sample.daily"],
        "join_ids": ["approved_join"],
        "join_plans": [
            {"join_id": "approved_join", "plan": "PREAGGREGATE"}
        ],
        "time_bucket": "month",
        "analysis_plan_sha256": "a" * 64,
    }
    assert "sql" not in result and "rows" not in result and "parameters" not in result


def test_business_term_evidence_uses_observed_or_inherited_spans_only() -> None:
    current = SimpleNamespace(is_inherited_metric=False, route="ANALYSIS")
    inherited = SimpleNamespace(is_inherited_metric=True, route="PRESENTATION")

    assert _business_terms_for_turn(
        {"measurement_source_texts": ["객실 매출"]}, {}, current
    ) == ["객실 매출"]
    assert _business_terms_for_turn(
        {"measurement_source_texts": []},
        {"business_terms": ["객실 매출"]},
        inherited,
    ) == ["객실 매출"]
    assert _business_terms_for_turn(
        {"measurement_source_texts": ["duplicate", "duplicate"]}, {}, current
    ) == []


class FakeConversationRepository:
    """ConversationOrchestrator 계약을 만족하는 테스트용 불변/동시성 저장소."""

    def __init__(self) -> None:
        self.conversations: dict[UUID, dict[str, Any]] = {}
        self.turns: dict[UUID, list[dict[str, Any]]] = {}
        self.commands: dict[tuple[UUID, str], dict[str, Any]] = {}
        self.view_specs: dict[UUID, dict[str, Any]] = {}
        self.existing_artifacts: set[UUID] = set()
        self.artifact_payloads: dict[UUID, dict[str, Any]] = {}

    async def get_conversation(self, conversation_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        conv = self.conversations.get(conversation_id)
        if conv and conv.get("owner_user_id") == user_id:
            return conv
        return None

    async def create_conversation(
        self,
        user_id: UUID,
        title: str,
        *,
        product_release_id: str = TEST_PRODUCT_RELEASE,
        permission_snapshot_id: str | None = None,
        semantic_release_id: str = TEST_SEMANTIC_RELEASE,
        wall_clock_anchor: date | None = None,
    ) -> dict[str, Any]:
        conv_id = uuid4()
        permission_receipt = permission_snapshot_id or compute_permission_snapshot_id(
            user_id,
            Role.ANALYST,
        )
        conv = {
            "conversation_id": conv_id,
            "owner_user_id": user_id,
            "title": title,
            "status": "ACTIVE",
            "head_turn_id": None,
            "turn_count": 0,
            "active_command_id": None,
            "lease_expires_at": None,
            "product_release_id": product_release_id,
            "permission_snapshot_id": permission_receipt,
            "semantic_release_id": semantic_release_id,
            "wall_clock_anchor": wall_clock_anchor or date(2026, 8, 18),
            "data_focus_turn_id": None,
            "data_focus_artifact_id": None,
            "view_focus_turn_id": None,
            "view_focus_spec_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        self.conversations[conv_id] = conv
        self.turns[conv_id] = []
        return conv

    async def list_turns(self, conversation_id: UUID) -> list[dict[str, Any]]:
        return [
            {
                **turn,
                **self.artifact_payloads.get(turn.get("artifact_id"), {}),
            }
            for turn in self.turns.get(conversation_id, [])
        ]

    async def get_command(self, conversation_id: UUID, idempotency_key: str) -> dict[str, Any] | None:
        return self.commands.get((conversation_id, idempotency_key))

    async def acquire_lease_and_check_cas(
        self,
        conversation_id: UUID,
        expected_head_turn_id: UUID | None,
        command_id: UUID,
        idempotency_key: str,
        input_hash: str,
        effective_subject_id: UUID,
        product_release_id: str,
        permission_snapshot_id: str,
        semantic_release_id: str,
        lease_seconds: int = 60,
    ) -> tuple[bool, str | None]:
        conv = self.conversations.get(conversation_id)
        if not conv:
            return False, "CONVERSATION_NOT_FOUND"
        if conv["status"] == "ARCHIVED":
            return False, "CONVERSATION_ARCHIVED"

        # CAS check
        if conv["head_turn_id"] != expected_head_turn_id:
            return False, "CONVERSATION_CONFLICT"

        if conv["product_release_id"] != product_release_id:
            return False, "PRODUCT_RELEASE_MISMATCH"
        if conv["permission_snapshot_id"] != permission_snapshot_id:
            return False, "PERMISSION_SNAPSHOT_MISMATCH"
        if conv["semantic_release_id"] != semantic_release_id:
            return False, "SEMANTIC_RELEASE_MISMATCH"

        existing = self.commands.get((conversation_id, idempotency_key))
        if existing is not None:
            return (
                False,
                "IDEMPOTENCY_EXISTS"
                if existing["canonical_input_hash"] == input_hash
                else "IDEMPOTENCY_PAYLOAD_MISMATCH",
            )

        # Lease check
        now = datetime.now(timezone.utc)
        if conv["active_command_id"] and conv["lease_expires_at"] and conv["lease_expires_at"] > now:
            return False, "CONVERSATION_BUSY"

        # Register command
        self.commands[(conversation_id, idempotency_key)] = {
            "command_id": command_id,
            "conversation_id": conversation_id,
            "idempotency_key": idempotency_key,
            "canonical_input_hash": input_hash,
            "status": "RUNNING",
            "turn_id": None,
            "error_response": None,
            "expected_head_turn_id": expected_head_turn_id,
            "effective_subject_id": effective_subject_id,
            "product_release_id": product_release_id,
            "permission_snapshot_id": permission_snapshot_id,
            "semantic_release_id": semantic_release_id,
        }

        # Acquire lease
        from datetime import timedelta
        conv["active_command_id"] = command_id
        conv["lease_expires_at"] = now + timedelta(seconds=lease_seconds)
        return True, None

    async def commit_turn(
        self,
        conversation_id: UUID,
        command_id: UUID,
        turn_id: UUID,
        turn_index: int,
        user_message: str,
        route: str,
        source_turn_ids: list[str],
        request_id: UUID | None,
        artifact_id: UUID | None,
        view_spec_id: UUID | None,
        report_definition_id: UUID | None,
        resolved_slots: dict[str, Any],
        product_release_id: str,
        permission_snapshot_id: str,
        semantic_release_id: str,
        terminal_writer: Any = None,
        *,
        terminal_status: str = "SUCCEEDED",
        reason_code: str | None = None,
        clarifies_turn_id: UUID | None = None,
        view_spec: dict[str, Any] | None = None,
    ) -> None:
        if terminal_writer is not None:
            await terminal_writer(None)
        if view_spec is not None:
            if view_spec_id is None or artifact_id not in self.existing_artifacts:
                raise ValueError("ViewSpec requires an existing Artifact")
            self.view_specs[view_spec_id] = {
                "view_spec_id": view_spec_id,
                "artifact_id": artifact_id,
                "view_type": view_spec["view_type"],
                "spec_json": view_spec["spec_json"],
                "product_release_id": product_release_id,
                "permission_snapshot_id": permission_snapshot_id,
                "semantic_release_id": semantic_release_id,
            }
        turn = {
            "turn_id": turn_id,
            "conversation_id": conversation_id,
            "turn_index": turn_index,
            "user_message": user_message,
            "route": route,
            "source_turn_ids": source_turn_ids,
            "request_id": request_id,
            "artifact_id": artifact_id,
            "view_spec_id": view_spec_id,
            "view_type": view_spec.get("view_type") if view_spec else None,
            "view_spec_json": view_spec.get("spec_json") if view_spec else None,
            "report_definition_id": report_definition_id,
            "resolved_slots": resolved_slots,
            "product_release_id": product_release_id,
            "permission_snapshot_id": permission_snapshot_id,
            "semantic_release_id": semantic_release_id,
            "reply_to_turn_id": self.conversations[conversation_id]["head_turn_id"],
            "clarifies_turn_id": clarifies_turn_id,
            "terminal_status": terminal_status,
            "reason_code": reason_code,
            "command_status": "COMPLETED",
            "command_error": None,
            "created_at": datetime.now(timezone.utc),
        }
        self.turns[conversation_id].append(turn)

        conv = self.conversations[conversation_id]
        conv["head_turn_id"] = turn_id
        conv["turn_count"] += 1
        if terminal_status == "SUCCEEDED" and route == "ANALYSIS" and artifact_id:
            conv["data_focus_turn_id"] = turn_id
            conv["data_focus_artifact_id"] = artifact_id
        if terminal_status == "SUCCEEDED" and view_spec_id:
            conv["view_focus_turn_id"] = turn_id
            conv["view_focus_spec_id"] = view_spec_id
        conv["active_command_id"] = None
        conv["lease_expires_at"] = None

        for key, cmd in self.commands.items():
            if cmd["command_id"] == command_id:
                cmd["status"] = "COMPLETED"
                cmd["turn_id"] = turn_id

    async def release_lease_on_failure(
        self,
        conversation_id: UUID,
        command_id: UUID,
        error_response: dict[str, Any],
    ) -> None:
        conv = self.conversations.get(conversation_id)
        if conv:
            conv["active_command_id"] = None
            conv["lease_expires_at"] = None

        for key, cmd in self.commands.items():
            if cmd["command_id"] == command_id:
                cmd["status"] = "FAILED"
                cmd["error_response"] = error_response

    async def commit_failed_turn(
        self,
        conversation_id: UUID,
        command_id: UUID,
        turn_id: UUID,
        turn_index: int,
        user_message: str,
        error_response: dict[str, Any],
        *,
        request_id: UUID | None = None,
        terminal_writer: Any = None,
    ) -> None:
        """운영 저장소와 동일하게 typed 실패 turn과 command를 원자적으로 남긴다."""

        if terminal_writer is not None:
            await terminal_writer(None)

        turn = {
            "turn_id": turn_id,
            "conversation_id": conversation_id,
            "turn_index": turn_index,
            "user_message": user_message,
            "route": "ANALYSIS",
            "source_turn_ids": [],
            "request_id": request_id,
            "artifact_id": None,
            "view_spec_id": None,
            "report_definition_id": None,
            "resolved_slots": {},
            "command_status": "FAILED",
            "command_error": error_response,
            "reply_to_turn_id": self.conversations[conversation_id]["head_turn_id"],
            "clarifies_turn_id": None,
            "terminal_status": "FAILED",
            "reason_code": error_response.get("code") or "CONVERSATION_COMMAND_FAILED",
            "product_release_id": self.conversations[conversation_id]["product_release_id"],
            "permission_snapshot_id": self.conversations[conversation_id]["permission_snapshot_id"],
            "semantic_release_id": self.conversations[conversation_id]["semantic_release_id"],
            "created_at": datetime.now(timezone.utc),
        }
        self.turns[conversation_id].append(turn)
        conv = self.conversations[conversation_id]
        conv["head_turn_id"] = turn_id
        conv["turn_count"] += 1
        conv["active_command_id"] = None
        conv["lease_expires_at"] = None
        for cmd in self.commands.values():
            if cmd["command_id"] == command_id:
                cmd["status"] = "FAILED"
                cmd["turn_id"] = turn_id
                cmd["error_response"] = error_response

    async def create_view_spec(
        self,
        artifact_id: UUID,
        view_type: str,
        spec_json: dict[str, Any],
        user_id: UUID | None = None,
        *,
        product_release_id: str,
        permission_snapshot_id: str,
        semantic_release_id: str,
    ) -> UUID:
        if artifact_id not in self.existing_artifacts:
            raise ValueError(f"Referenced artifact {artifact_id} does not exist.")

        view_spec_id = uuid4()
        self.view_specs[view_spec_id] = {
            "view_spec_id": view_spec_id,
            "artifact_id": artifact_id,
            "view_type": view_type,
            "spec_json": spec_json,
            "product_release_id": product_release_id,
            "permission_snapshot_id": permission_snapshot_id,
            "semantic_release_id": semantic_release_id,
        }
        return view_spec_id


class FakeDataPlatformAdapter:
    """자산 검색 결과를 테스트가 직접 프로그래밍하는 DataPlatform 대역.

    기본값은 빈 목록이며, 이 경우 오케스트레이터는 Node1 정규화를 건너뛴다. Node1
    경로까지 태우려는 테스트만 `assets`를 채워 승인 자산이 발견된 상황을 만든다.
    """

    def __init__(self, assets: list[dict[str, Any]] | None = None) -> None:
        self.assets: list[dict[str, Any]] = list(assets or ())
        self.assets_by_query: dict[str, list[dict[str, Any]]] = {}
        self.assets_by_preference: dict[
            tuple[str, tuple[str, ...]], list[dict[str, Any]]
        ] = {}
        self.queries: list[str] = []
        self.search_contexts: list[dict[str, Any]] = []
        self.query_lifecycle_sink: Any = None
        self.lifecycle_bindings: list[bool] = []
        # 특정 발화에서 운영과 동일한 typed 실패를 재현하기 위한 프로그래밍 지점.
        self.search_error: Exception | None = None
        self.active_product_release = TEST_PRODUCT_RELEASE
        self.active_semantic_release = TEST_SEMANTIC_RELEASE
        self.unavailable_product_releases: set[str] = set()

    def bind_query_lifecycle(self, sink: Any) -> None:
        self.query_lifecycle_sink = sink
        self.lifecycle_bindings.append(sink is not None)

    def program_search(self, query: str, assets: list[dict[str, Any]]) -> None:
        """특정 검색어에 반환할 승인 자산을 등록한다."""

        self.assets_by_query[query] = list(assets)

    def program_preferred_search(
        self,
        query: str,
        preferred_metric_ids: tuple[str, ...],
        assets: list[dict[str, Any]],
    ) -> None:
        """구조화된 이전 Metric 우선순위가 있을 때의 후보 검색 결과를 등록한다."""

        self.assets_by_preference[(query, preferred_metric_ids)] = list(assets)

    async def _candidate_assets(self, query: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        self.queries.append(query)
        self.search_contexts.append(dict(filters))
        if self.search_error is not None:
            raise self.search_error
        preferred = tuple(filters.get("preferred_metric_ids") or ())
        if (query, preferred) in self.assets_by_preference:
            return list(self.assets_by_preference[(query, preferred)])
        if query in self.assets_by_query:
            return list(self.assets_by_query[query])
        return list(self.assets)

    async def search_asset_candidates(
        self,
        query: str,
        filters: dict[str, Any],
    ) -> AssetCandidateSet:
        """프로그래밍된 후보를 production과 같은 non-empty receipt 계약으로 감싼다."""

        assets = await self._candidate_assets(query, filters)
        if not assets:
            raise NoEntitledAssetsError("no programmed entitled candidates")
        return AssetCandidateSet(
            assets=tuple(assets),
            context_release=str(assets[0].get("context_release") or "test-release"),
            catalog_checksum="1" * 64,
            canonical_checksum="2" * 64,
            product_release_id=TEST_PRODUCT_RELEASE,
            runtime_projection_checksum="3" * 64,
            source_authority="DATAHUB_NATIVE_METRIC_V1",
            retrieval_mode="lexical",
        )

    async def get_active_context_release(self) -> str:
        return self.active_semantic_release

    async def get_catalog_readiness(self) -> tuple[dict[str, str], str | None]:
        return (
            {"catalog": "ready", "semantic": "ready", "query": "ready"},
            self.active_product_release,
        )

    async def get_product_release_readiness(
        self,
        product_release_id: str,
    ) -> tuple[dict[str, str], str | None, str | None]:
        stages = {"catalog": "ready", "semantic": "ready", "query": "ready"}
        if product_release_id in self.unavailable_product_releases:
            return ({name: "not_ready" for name in stages}, None, None)
        return stages, product_release_id, TEST_SEMANTIC_RELEASE


from src.report.domain import (
    BlockType,
    DefinitionStatus,
    ReportBlock,
    ReportDefinitionVersion,
)


class FakeReportRepository:
    """ConversationOrchestrator REPORT_ACTION 검증을 위한 인메모리 ReportRepository."""

    def __init__(self) -> None:
        self.definitions: dict[tuple[str, int], ReportDefinitionVersion] = {}
        self.artifacts: dict[str, dict[str, Any]] = {}

    def register_artifact(
        self,
        artifact_id: UUID | str,
        *,
        title: str = "분석 결과",
        narrative: str = "2025년 8월 객실 매출은 120,000,000원입니다.",
        snapshot: dict[str, Any] | None = None,
        chart_spec: dict[str, Any] | None = None,
        trino_query_id: str = "trino-query-123",
        checksum: str = "checksum-abc",
    ) -> None:
        self.artifacts[str(artifact_id)] = {
            "artifact_id": str(artifact_id),
            "title": title,
            "narrative_markdown": narrative,
            "data_snapshot_json": snapshot or {"columns": ["hotel", "rev"], "rows": [{"hotel": "Grand", "rev": 120000000}]},
            "chart_spec_json": chart_spec or {"chart_type": "bar", "x_field": "hotel", "y_fields": ["rev"]},
            "evidence_json": {"metric_values": [{"label": "매출", "value": 120000000, "unit": "KRW"}]},
            "trino_query_id": trino_query_id,
            "artifact_checksum": checksum,
        }

    async def get_transfer_artifact(self, artifact_id: str) -> dict[str, object]:
        if artifact_id not in self.artifacts:
            raise KeyError(f"본인의 승인된 Analysis Artifact를 찾을 수 없습니다: {artifact_id}")
        return dict(self.artifacts[artifact_id])

    async def add_draft(self, draft: ReportDefinitionVersion) -> ReportDefinitionVersion:
        key = (draft.definition_id, draft.version)
        if key in self.definitions:
            raise ValueError("같은 Report definition version이 이미 존재합니다.")
        self.definitions[key] = draft
        return draft

    async def get_version(self, definition_id: str, version: int) -> ReportDefinitionVersion:
        key = (definition_id, version)
        if key not in self.definitions:
            raise KeyError("Report definition version을 찾을 수 없습니다.")
        return self.definitions[key]

    async def replace_draft_blocks(
        self,
        definition_id: str,
        version: int,
        blocks: tuple[ReportBlock, ...],
        *,
        title: str | None = None,
        orientation: str | None = None,
        currency_display_unit: str | None = None,
    ) -> ReportDefinitionVersion:
        key = (definition_id, version)
        if key not in self.definitions:
            raise KeyError("Report definition version을 찾을 수 없습니다.")
        current = self.definitions[key]
        if current.status != DefinitionStatus.DRAFT:
            raise ValueError("draft Report version만 block layout을 교체할 수 있습니다.")
        updated = ReportDefinitionVersion(
            definition_id=current.definition_id,
            version=current.version,
            status=current.status,
            title=current.title if title is None else title,
            blocks=blocks,
            orientation=orientation or current.orientation,
            currency_display_unit=currency_display_unit or current.currency_display_unit,
        )
        self.definitions[key] = updated
        return updated


class FakePipelineSupport:
    """MetricResolver가 반환하는 structured_request를 테스트가 프로그래밍하는 대역.

    운영에서 질문의 기간 해석은 Node1이 수행하고 그 결과가 `period_candidates`로 실려
    온다. 서버는 이 후보를 확정만 하므로, 기간을 검증하는 테스트는 문장을 파싱하는 대신
    여기에 typed 후보를 실어 Node1이 해석을 마친 상황을 재현한다.
    """

    def __init__(self, structured: dict[str, Any] | None = None) -> None:
        self.structured: dict[str, Any] = dict(structured or {"selected_metric_id": "room_revenue"})
        self.questions: list[str] = []
        self.budgets: list[Any] = []
        # 발화별로 Node1이 낼 신호(route, presentation_type 등)를 프로그래밍한다. 운영에서
        # route는 Node1 응답 계약으로만 전달되므로, 테스트도 문장이 아니라 이 신호로 라우팅한다.
        self.signals_by_message: dict[str, dict[str, Any]] = {}
        self.errors_by_message: dict[str, Exception] = {}

    def program(self, message: str, **signals: Any) -> None:
        """특정 발화에 대해 Node1이 반환할 신호를 등록한다."""
        self.signals_by_message[message] = dict(signals)

    def program_error(self, message: str, error: Exception) -> None:
        self.errors_by_message[message] = error

    async def select_metric(
        self,
        req: AnalysisRequest,
        context: RequestContext,
        candidates: AssetCandidateSet,
        *,
        budget=None,
    ):
        self.questions.append(req.question)
        self.budgets.append(budget)
        if req.question in self.errors_by_message:
            raise self.errors_by_message[req.question]
        structured = dict(self.structured)
        structured.update(self.signals_by_message.get(req.question, {}))
        return list(candidates.assets), req.question, structured


class ConversationOrchestratorTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repo = FakeConversationRepository()
        self.report_repo = FakeReportRepository()
        # 운영에서는 승인 자산이 발견되어 Node1 정규화가 항상 수행된다. 자산을 비워 두면
        # Node1 경로 자체가 건너뛰어져 route 계약이 검증되지 않으므로 기본으로 채워 둔다.
        self.data_platform = FakeDataPlatformAdapter(
            [{"urn": "urn:li:dataset:(serving,room_daily,PROD)"}]
        )
        self.support = FakePipelineSupport()
        self.submitted_requests: list[AnalysisRequest] = []
        self.submitted_contexts: list[RequestContext] = []
        self.support.program("표로 보여줘", requested_route="PRESENTATION", selected_metric_id=None, presentation_type="TABLE")
        self.support.program("차트로 나타내줘", requested_route="PRESENTATION", selected_metric_id=None, presentation_type="BAR")
        self.support.program("현재 내용을 보고서에 담아줘", requested_route="REPORT_ACTION", selected_metric_id=None)
        self.support.program("이 내용도 보고서에 담아줘", requested_route="REPORT_ACTION", selected_metric_id=None)
        self.user_id = UUID("00000000-0000-0000-0000-000000000001")
        self.context = RequestContext(
            request_id=UUID("00000000-0000-0000-0000-000000000002"),
            trace_id="test-trace",
            user_id=self.user_id,
            role=Role.ANALYST,
            as_of=date(2026, 8, 18),
            timezone="Asia/Seoul",
        )

        self.submitted_controls: list[tuple[Any, Any, Any]] = []
        self.submitted_budgets: list[Any] = []

        async def mock_submit_analysis(
            req: AnalysisRequest,
            ctx: RequestContext,
            execution_sink=None,
            progress_sink=None,
            cancel_check=None,
            model_budget=None,
        ):
            self.submitted_requests.append(req)
            self.submitted_contexts.append(ctx)
            self.submitted_controls.append(
                (execution_sink, progress_sink, cancel_check)
            )
            self.submitted_budgets.append(model_budget)
            artifact_id = uuid4()
            self.repo.existing_artifacts.add(artifact_id)
            self.report_repo.register_artifact(
                artifact_id,
                title=f"{req.question[:30]} 분석",
                narrative=f"{req.question}에 대한 데이터 분석 결과입니다.",
                snapshot={
                    "columns": ["period", "room_revenue_krw"],
                    "rows": [
                        {"period": "2025-07-01", "room_revenue_krw": 120000000}
                    ],
                },
                chart_spec={
                    "chart_type": "bar",
                    "x_field": "period",
                    "y_fields": ["room_revenue_krw"],
                },
            )
            artifact_payload = self.report_repo.artifacts[str(artifact_id)]
            self.repo.artifact_payloads[artifact_id] = {
                "data_snapshot_json": artifact_payload["data_snapshot_json"],
                "chart_spec_json": artifact_payload["chart_spec_json"],
                "narrative_markdown": artifact_payload["narrative_markdown"],
                "evidence_json": artifact_payload["evidence_json"],
                "query_id": artifact_payload["trino_query_id"],
            }
            # Minimal mock response with artifact
            class FakeResp:
                def model_dump(self, **kwargs):
                    return {
                        "data": {
                            "artifact": {"artifact_id": str(artifact_id)},
                            "status": "SUCCEEDED",
                        }
                    }
            return FakeResp()

        self.orchestrator = ConversationOrchestrator(
            repository=self.repo,
            data_platform=self.data_platform,
            support=self.support,
            submit_analysis=mock_submit_analysis,
            report_repository_factory=lambda request_context, is_admin: self.report_repo,
        )

    async def execute_command(
        self,
        *,
        conversation_id: UUID,
        payload: dict[str, Any],
        context: RequestContext,
        analysis_gate: Any = None,
    ) -> dict[str, Any]:
        """기존 시나리오를 새 mandatory admission 필드로 명시적으로 감싼다."""

        command = dict(payload)
        command.setdefault("idempotency_key", f"test-{uuid4()}")
        command.setdefault("expected_head_turn_id", None)
        return await self.orchestrator.execute_command(
            conversation_id=conversation_id,
            payload=command,
            context=context,
            analysis_gate=analysis_gate,
        )

    async def test_unmatched_request_uses_fixed_scope_rejection_without_model(self) -> None:
        conversation = await self.repo.create_conversation(self.user_id, "범위 밖 요청")
        self.data_platform.search_error = NoEntitledAssetsError(
            "no governed asset matches"
        )
        result = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": "안녕하세요"},
            context=self.context,
        )

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("OUT_OF_SCOPE", result["type"])
        self.assertEqual("OUT_OF_SCOPE", result["turn"]["route"])
        self.assertEqual(
            "해당 요청은 지원하지 않습니다. 이 서비스는 호텔 운영 데이터 분석, 승인된 내부 업무지침 확인, "
            "분석 결과의 보고서 작업만 지원합니다. 지원 범위에 맞게 요청해 주세요.",
            result["message"],
        )
        self.assertEqual([], self.support.questions)
        self.assertEqual([], self.submitted_requests)
        self.assertIsNone(
            self.repo.conversations[conversation["conversation_id"]][
                "data_focus_turn_id"
            ]
        )

    async def test_node1_missing_metric_is_rejected_without_general_reply(self) -> None:
        conversation = await self.repo.create_conversation(self.user_id, "지원 범위 확인")
        self.support.program(
            "오늘 날씨 어때?",
            metric_resolution="missing",
            selected_metric_id=None,
            selected_metric_ids=[],
            requested_route=None,
            is_elliptical=False,
        )

        result = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": "오늘 날씨 어때?"},
            context=self.context,
        )

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("OUT_OF_SCOPE", result["type"])
        self.assertEqual("DATA_ASSET_NOT_FOUND", result["code"])
        self.assertNotIn("general_chat", result["turn"]["resolved_slots"])
        self.assertEqual(["오늘 날씨 어때?"], self.support.questions)
        self.assertEqual([], self.submitted_requests)

    async def test_analysis_route_passes_untampered_question_and_slots(self) -> None:
        """ANALYSIS 라우트 실행 시 질문 문자열을 변조하지 않고 원본 발화와 typed slots를 전달하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "매출 분석")
        conv_id = conv["conversation_id"]

        result = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "2025년 8월 1일 ~ 8월 15일 객실 매출 보여줘",
            },
            context=self.context,
        )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["turn"]["route"], "ANALYSIS")
        self.assertEqual(result["turn"]["user_message"], "2025년 8월 1일 ~ 8월 15일 객실 매출 보여줘")
        self.assertEqual(len(self.submitted_requests), 1)
        self.assertEqual(self.submitted_requests[0].question, "2025년 8월 1일 ~ 8월 15일 객실 매출 보여줘")

    async def test_analysis_gate_rejection_is_retryable_and_idempotent(self) -> None:
        class RejectingGate:
            def __init__(self) -> None:
                self.acquire_count = 0

            async def acquire(self, _wait_seconds: float) -> bool:
                self.acquire_count += 1
                return False

            def release(self) -> None:
                raise AssertionError("획득하지 못한 gate를 반환하면 안 됩니다.")

        conversation = await self.repo.create_conversation(
            self.user_id,
            "gate admission",
        )
        gate = RejectingGate()
        payload = {
            "user_message": "2025년 8월 객실 매출 보여줘",
            "idempotency_key": "rate-limited-command",
        }

        first = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload=payload,
            context=self.context,
            analysis_gate=gate,
        )
        replay = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload=payload,
            context=self.context,
            analysis_gate=gate,
        )

        self.assertEqual("BUSY", first["status"])
        self.assertEqual(ErrorCode.RATE_LIMITED.value, first["code"])
        self.assertTrue(first["retryable"])
        self.assertEqual("BUSY", replay["status"])
        self.assertTrue(replay["is_idempotent_replay"])
        self.assertEqual(1, gate.acquire_count)
        self.assertEqual([], self.submitted_requests)
        self.assertEqual([], await self.repo.list_turns(conversation["conversation_id"]))

    async def test_analysis_gate_does_not_block_resolved_presentation(self) -> None:
        class RejectingGate:
            def __init__(self) -> None:
                self.acquire_count = 0

            async def acquire(self, _wait_seconds: float) -> bool:
                self.acquire_count += 1
                return False

            def release(self) -> None:
                raise AssertionError("PRESENTATION은 analysis gate를 사용하면 안 됩니다.")

        conversation = await self.repo.create_conversation(
            self.user_id,
            "presentation gate bypass",
        )
        analysis = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        gate = RejectingGate()

        presentation = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": "표로 보여줘",
                "expected_head_turn_id": str(analysis["turn"]["turn_id"]),
            },
            context=self.context,
            analysis_gate=gate,
        )

        self.assertEqual("SUCCESS", presentation["status"])
        self.assertEqual("PRESENTATION", presentation["turn"]["route"])
        self.assertEqual(0, gate.acquire_count)

    async def test_analysis_route_forwards_progress_and_cancel_controls(self) -> None:
        conversation = await self.repo.create_conversation(
            self.user_id,
            "분석 실행 제어",
        )
        progress_sink = lambda _stage, _outcome: None
        cancel_check = lambda: False

        result = await self.orchestrator.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": "2025년 8월 객실 매출 보여줘",
                "idempotency_key": "execution-controls",
                "expected_head_turn_id": None,
            },
            context=self.context,
            progress_sink=progress_sink,
            cancel_check=cancel_check,
        )

        self.assertEqual("SUCCESS", result["status"])
        execution_sink, forwarded_progress, forwarded_cancel = self.submitted_controls[-1]
        self.assertTrue(callable(execution_sink))
        self.assertIs(progress_sink, forwarded_progress)
        self.assertIs(cancel_check, forwarded_cancel)
        self.assertIs(self.support.budgets[-1], self.submitted_budgets[-1])

    async def test_cancelled_command_releases_lease_with_timeout_reason(self) -> None:
        conversation = await self.repo.create_conversation(
            self.user_id,
            "전체 deadline",
        )
        submitted = asyncio.Event()

        async def slow_submit(_request, _context):
            submitted.set()
            await asyncio.Event().wait()

        self.orchestrator._submit_analysis = slow_submit
        task = asyncio.create_task(
            self.execute_command(
                conversation_id=conversation["conversation_id"],
                payload={"user_message": "2025년 8월 객실 매출 보여줘"},
                context=self.context,
            )
        )
        await asyncio.wait_for(submitted.wait(), timeout=1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        command = next(iter(self.repo.commands.values()))
        self.assertEqual("FAILED", command["status"])
        self.assertEqual(
            ErrorCode.QUERY_TIMEOUT.value,
            command["error_response"]["code"],
        )
        self.assertIsNone(conversation["active_command_id"])
        self.assertIsNone(conversation["lease_expires_at"])

    async def test_pipeline_exception_separates_public_and_durable_error_codes(self) -> None:
        """시스템 예외는 공개 command code와 별개인 RECOVERY Run 실패로 닫힌다."""

        class AnalysisRepositoryStub:
            def __init__(self) -> None:
                self.begun: list[UUID] = []
                self.failures: list[tuple[UUID, str]] = []

            async def begin_request(self, _question, _parameters, context) -> None:
                self.begun.append(context.request_id)

            async def fail_run_in_session(
                self,
                _session,
                request_id,
                error_type,
            ) -> None:
                self.failures.append((request_id, error_type))

        analysis_repository = AnalysisRepositoryStub()

        async def submit_failure(
            _request,
            context,
            run_admission_sink,
            context_receipt_sink,
        ):
            self.assertTrue(callable(context_receipt_sink))
            await run_admission_sink(context)
            raise ValueError("injected pipeline failure")

        orchestrator = ConversationOrchestrator(
            repository=self.repo,
            data_platform=self.data_platform,
            support=self.support,
            submit_analysis=submit_failure,
            analysis_repository_factory=analysis_repository,
        )
        conversation = await self.repo.create_conversation(
            self.user_id,
            "pipeline failure",
        )

        with self.assertRaisesRegex(ValueError, "injected pipeline failure"):
            await orchestrator.execute_command(
                conversation["conversation_id"],
                {
                    "user_message": "2025년 8월 객실 매출 보여줘",
                    "idempotency_key": "pipeline-failure",
                    "expected_head_turn_id": None,
                },
                self.context,
            )

        self.assertEqual([self.context.request_id], analysis_repository.begun)
        self.assertEqual(
            [(self.context.request_id, "RECOVERY")],
            analysis_repository.failures,
        )
        command = next(iter(self.repo.commands.values()))
        self.assertEqual("FAILED", command["status"])
        self.assertEqual(
            "CONVERSATION_COMMAND_FAILED",
            command["error_response"]["code"],
        )
        turns = await self.repo.list_turns(conversation["conversation_id"])
        self.assertEqual(1, len(turns))
        self.assertEqual("FAILED", turns[0]["terminal_status"])
        self.assertEqual("CONVERSATION_COMMAND_FAILED", turns[0]["reason_code"])

    async def test_lease_heartbeat_renews_current_command(self) -> None:
        renewed: list[tuple[UUID, UUID]] = []

        async def renew_lease(conversation_id, command_id):
            renewed.append((conversation_id, command_id))
            return True

        self.repo.renew_lease = renew_lease
        conversation_id = uuid4()
        command_id = uuid4()
        stop = asyncio.Event()
        lost = asyncio.Event()
        task = asyncio.create_task(
            self.orchestrator._renew_command_lease(
                conversation_id,
                command_id,
                stop,
                lost,
            )
        )
        await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

        self.assertEqual([(conversation_id, command_id)], renewed)
        self.assertFalse(lost.is_set())

    async def test_explicit_write_sql_is_blocked_before_model_and_query_pipeline(self) -> None:
        conversation = await self.repo.create_conversation(
            self.user_id,
            "SQL write 차단",
        )

        result = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": "DELETE FROM voc_review를 실행해줘"},
            context=self.context,
        )

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual(ErrorCode.SQL_POLICY_BLOCKED.value, result["code"])
        self.assertEqual("BLOCKED", result["turn"]["terminal_status"])
        self.assertEqual(
            ErrorCode.SQL_POLICY_BLOCKED.value,
            result["turn"]["reason_code"],
        )
        self.assertEqual(
            ["SQL 쓰기"],
            result["turn"]["resolved_slots"]["business_terms"],
        )
        self.assertEqual([], self.support.questions)
        self.assertEqual([], self.submitted_requests)

    async def test_analysis_route_binds_and_clears_durable_query_lifecycle(self) -> None:
        """실제 query service가 내는 lifecycle event가 admitted Run 저장소로 연결된다."""

        class AnalysisRepositoryStub:
            def __init__(self) -> None:
                self.begun: list[UUID] = []
                self.events: list[dict[str, Any]] = []
                self.context_receipts: list[tuple[RequestContext, Any]] = []
                self.finished = 0

            async def begin_request(self, _question, _parameters, context) -> None:
                self.begun.append(context.request_id)

            async def record_query_lifecycle(self, _request_id, event) -> None:
                self.events.append(dict(event))

            async def persist_context_receipt(self, context, package) -> None:
                self.context_receipts.append((context, package))

            async def finish_run_in_session(
                self,
                _session,
                _request_id,
                _response,
                _execution,
            ) -> None:
                self.finished += 1

            async def fail_run_in_session(self, *_args) -> None:
                raise AssertionError("success path must not fail the run")

        analysis_repository = AnalysisRepositoryStub()

        async def submit_with_lifecycle(
            req,
            _context,
            execution_sink,
            run_admission_sink,
            context_receipt_sink,
        ):
            self.submitted_requests.append(req)
            await run_admission_sink(_context)
            await context_receipt_sink(_context, {"package_hash": "context-receipt"})
            sink = self.data_platform.query_lifecycle_sink
            self.assertIsNotNone(sink)
            await sink(
                {
                    "event_type": "SUBMITTED",
                    "query_id": "query-wired",
                    "cancel_uri": "https://trino:8443/next/query-wired",
                    "sql_hash": "a" * 64,
                    "status": "RUNNING",
                }
            )
            await sink(
                {
                    "event_type": "TERMINAL",
                    "query_id": "query-wired",
                    "sql_hash": "a" * 64,
                    "status": "SUCCEEDED",
                    "row_count": 1,
                    "scan_bytes": 0,
                }
            )
            execution_sink({})
            artifact_id = uuid4()
            self.repo.existing_artifacts.add(artifact_id)

            class FakeResp:
                def model_dump(self, **_kwargs):
                    return {
                        "data": {
                            "artifact": {"artifact_id": str(artifact_id)},
                            "status": "SUCCEEDED",
                        }
                    }

            return FakeResp()

        orchestrator = ConversationOrchestrator(
            repository=self.repo,
            data_platform=self.data_platform,
            support=self.support,
            submit_analysis=submit_with_lifecycle,
            analysis_repository_factory=analysis_repository,
        )
        conversation = await self.repo.create_conversation(self.user_id, "lifecycle wire")
        result = await orchestrator.execute_command(
            conversation["conversation_id"],
            {
                "user_message": "2025년 8월 객실 매출 보여줘",
                "idempotency_key": "lifecycle-wire-1",
                "expected_head_turn_id": None,
            },
            self.context,
        )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual([item["event_type"] for item in analysis_repository.events], [
            "SUBMITTED",
            "TERMINAL",
        ])
        self.assertEqual(analysis_repository.finished, 1)
        self.assertEqual(len(analysis_repository.context_receipts), 1)
        self.assertEqual(
            analysis_repository.context_receipts[0][0].request_id,
            self.context.request_id,
        )
        self.assertEqual(self.data_platform.lifecycle_bindings[-2:], [True, False])
        self.assertIsNone(self.data_platform.query_lifecycle_sink)

    async def test_pipeline_clarification_does_not_create_analysis_run(self) -> None:
        """Context 명확화 응답은 durable Run이나 query lifecycle을 만들지 않는다."""

        class AnalysisRepositoryStub:
            def __init__(self) -> None:
                self.begun: list[UUID] = []

            async def begin_request(self, _question, _parameters, context) -> None:
                self.begun.append(context.request_id)

            async def finish_run_in_session(self, *_args) -> None:
                raise AssertionError("clarification must not finish a Run")

            async def fail_run_in_session(self, *_args) -> None:
                raise AssertionError("clarification must not fail a Run")

        analysis_repository = AnalysisRepositoryStub()

        async def submit_clarification(
            _request,
            _context,
            run_admission_sink,
            context_receipt_sink,
        ):
            self.assertTrue(callable(run_admission_sink))
            self.assertTrue(callable(context_receipt_sink))

            class FakeClarificationResp:
                data = AnalysisData(
                    status=AnalysisStatus.CLARIFICATION_REQUIRED,
                    transitions=(
                        AnalysisStatus.RECEIVED,
                        AnalysisStatus.ROUTED,
                        AnalysisStatus.CLARIFICATION_REQUIRED,
                    ),
                )
                error = ErrorBody(
                    code=ErrorCode.CONTEXT_INCOMPLETE,
                    message="분석할 지표를 선택해 주세요.",
                    clarification_type=ClarificationType.METRIC,
                )

                def model_dump(self, **_kwargs):
                    return {
                        "data": {"status": "CLARIFICATION_REQUIRED"},
                        "error": {"code": ErrorCode.CONTEXT_INCOMPLETE.value},
                    }

            return FakeClarificationResp()

        orchestrator = ConversationOrchestrator(
            repository=self.repo,
            data_platform=self.data_platform,
            support=self.support,
            submit_analysis=submit_clarification,
            analysis_repository_factory=analysis_repository,
        )
        conversation = await self.repo.create_conversation(
            self.user_id,
            "Run 없는 명확화",
        )

        result = await orchestrator.execute_command(
            conversation["conversation_id"],
            {
                "user_message": "2025년 8월 객실 매출 보여줘",
                "idempotency_key": "clarification-without-run",
                "expected_head_turn_id": None,
            },
            self.context,
        )

        self.assertEqual("CLARIFICATION_REQUIRED", result["status"])
        self.assertEqual([], analysis_repository.begun)
        self.assertIsNone(result["turn"]["request_id"])
        self.assertEqual([], self.data_platform.lifecycle_bindings)

    async def test_existing_conversation_uses_immutable_wall_clock_anchor(self) -> None:
        """새 요청의 clock이 달라도 기존 Conversation의 서버 anchor만 하류에 전달한다."""

        anchor = date(2025, 9, 2)
        conversation = await self.repo.create_conversation(
            self.user_id,
            "wall clock anchor",
            wall_clock_anchor=anchor,
        )
        question = "이번 달 객실 매출"
        self.support.program(
            question,
            selected_metric_id="room_revenue",
            selected_metric_ids=["room_revenue"],
            metric_ids=["room_revenue"],
            period_candidates=[
                {
                    "start": "2025-09-01",
                    "end_exclusive": "2025-10-01",
                    "source_text": "이번 달",
                }
            ],
            analysis_operation="aggregate",
            requested_route="ANALYSIS",
        )

        result = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": question},
            context=self.context.model_copy(update={"as_of": date(2026, 8, 22)}),
        )

        self.assertEqual("SUCCESS", result["status"])
        self.assertEqual(anchor, self.submitted_contexts[-1].as_of)
        self.assertEqual(
            "2025-09-01",
            result["turn"]["resolved_slots"]["time_range"]["start"],
        )

    async def test_focus_transitions_follow_terminal_route_contract(self) -> None:
        """Analysis·Presentation만 각 허용 focus를 바꾸고 Report·BLOCKED는 보존한다."""

        conversation = await self.repo.create_conversation(self.user_id, "focus")
        conv_id = conversation["conversation_id"]
        analysis = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출"},
            context=self.context,
        )
        first_turn = analysis["turn"]["turn_id"]
        first_artifact = analysis["turn"]["artifact_id"]
        first_view = analysis["turn"]["view_spec_id"]
        self.assertEqual(first_turn, conversation["data_focus_turn_id"])
        self.assertEqual(first_artifact, conversation["data_focus_artifact_id"])
        self.assertEqual(first_turn, conversation["view_focus_turn_id"])
        self.assertEqual(first_view, conversation["view_focus_spec_id"])

        presentation = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "표로 보여줘",
                "expected_head_turn_id": str(first_turn),
            },
            context=self.context,
        )
        presentation_turn = presentation["turn"]["turn_id"]
        presentation_view = presentation["turn"]["view_spec_id"]
        self.assertEqual(first_turn, conversation["data_focus_turn_id"])
        self.assertEqual(first_artifact, conversation["data_focus_artifact_id"])
        self.assertEqual(presentation_turn, conversation["view_focus_turn_id"])
        self.assertEqual(presentation_view, conversation["view_focus_spec_id"])

        report = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "현재 내용을 보고서에 담아줘",
                "expected_head_turn_id": str(presentation_turn),
            },
            context=self.context,
        )
        self.assertEqual(first_turn, conversation["data_focus_turn_id"])
        self.assertEqual(presentation_turn, conversation["view_focus_turn_id"])

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        blocked_message = "이번 달 객실 매출"
        self.support.program_error(
            blocked_message,
            ContextBuildError(
                ContextBuildErrorCode.OUT_OF_DATA_RANGE,
                "승인된 데이터 범위 밖입니다.",
            ),
        )
        blocked = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": blocked_message,
                "expected_head_turn_id": str(report["turn"]["turn_id"]),
            },
            context=self.context,
        )
        self.assertEqual("BLOCKED", blocked["status"])
        self.assertEqual(first_turn, conversation["data_focus_turn_id"])
        self.assertEqual(presentation_turn, conversation["view_focus_turn_id"])

    async def test_clarification_resolution_links_parent_without_using_it_as_source(self) -> None:
        """확인 응답은 clarifies lineage만 남기고 BLOCKED Turn을 데이터 source로 쓰지 않는다."""

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        conversation = await self.repo.create_conversation(self.user_id, "clarification")
        question = "매출을 보여줘"
        option = DisambiguationOption(
            label="객실 매출",
            metric_id="room_revenue",
            description="객실 운영 매출",
            clarification_type=ClarificationType.METRIC,
            value="room_revenue",
        )
        self.support.program_error(
            question,
            ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "지표를 선택해 주세요.",
                ("객실 매출",),
                disambiguation_options=(option,),
                partial_context={
                    "metric_resolution": "ambiguous",
                    "metric_ids": ["room_revenue"],
                    "metric_candidates": ["room_revenue"],
                    "selected_metric_ids": [],
                    "period_candidates": [
                        {
                            "start": "2025-08-01",
                            "end_exclusive": "2025-09-01",
                            "source_text": "2025년 8월",
                        }
                    ],
                    "analysis_operation": "aggregate",
                    "is_elliptical": False,
                },
            ),
        )
        clarification = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": question},
            context=self.context,
        )
        clarification_turn = clarification["turn"]["turn_id"]
        self.assertEqual("BLOCKED", clarification["turn"]["terminal_status"])
        self.assertEqual([], clarification["turn"]["source_turn_ids"])

        resolved = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": "객실 매출",
                "expected_head_turn_id": str(clarification_turn),
            },
            context=self.context,
        )

        self.assertEqual("SUCCESS", resolved["status"])
        self.assertEqual(clarification_turn, resolved["turn"]["clarifies_turn_id"])
        self.assertEqual([], resolved["turn"]["source_turn_ids"])

    async def test_golden_dialogue_period_comparison_uses_exactly_two_analysis_sources(self) -> None:
        """8월→그 전 달→비교가 세 Run과 ordered 두 source Turn으로 수렴한다."""

        conversation = await self.repo.create_conversation(self.user_id, "GD-01")
        conv_id = conversation["conversation_id"]
        first_message = "2025년 8월 인식 객실 매출을 보여줘."
        second_message = "그 전 달은?"
        third_message = "두 달 비교 분석해줘."
        self.support.program(
            first_message,
            selected_metric_id="room_revenue",
            selected_metric_ids=["room_revenue"],
            metric_ids=["room_revenue"],
            period_candidates=[
                {
                    "start": "2025-08-01",
                    "end_exclusive": "2025-09-01",
                    "source_text": "2025년 8월",
                }
            ],
            analysis_operation="aggregate",
            requested_route="ANALYSIS",
            is_elliptical=False,
        )
        self.support.program(
            second_message,
            selected_metric_id=None,
            selected_metric_ids=[],
            metric_ids=[],
            metric_resolution="missing",
            measurement_source_texts=[],
            period_candidates=[
                {
                    "start": "2025-07-01",
                    "end_exclusive": "2025-08-01",
                    "source_text": "그 전 달",
                }
            ],
            analysis_operation="aggregate",
            requested_route="ANALYSIS",
            is_elliptical=True,
        )
        self.support.program(
            third_message,
            selected_metric_id=None,
            selected_metric_ids=[],
            metric_ids=[],
            metric_resolution="missing",
            measurement_source_texts=[],
            period_candidates=[],
            analysis_operation="period_comparison",
            requested_route="ANALYSIS",
            is_elliptical=True,
        )

        first = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": first_message},
            context=self.context,
        )
        second = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": second_message,
                "expected_head_turn_id": str(first["turn"]["turn_id"]),
            },
            context=self.context,
        )
        self.assertIn(
            {
                "field": "time_range",
                "operation": "SET",
                "value": {
                    "start": "2025-07-01",
                    "end_exclusive": "2025-08-01",
                    "source_text": "그 전 달",
                },
            },
            second["turn"]["resolved_slots"]["change_set"],
        )
        third = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": third_message,
                "expected_head_turn_id": str(second["turn"]["turn_id"]),
            },
            context=self.context,
        )

        self.assertEqual(3, len(self.submitted_requests))
        self.assertEqual(
            [
                str(first["turn"]["turn_id"]),
                str(second["turn"]["turn_id"]),
            ],
            third["turn"]["source_turn_ids"],
        )
        self.assertEqual(
            "2025-07-01",
            third["turn"]["resolved_slots"]["time_range"]["start"],
        )
        self.assertEqual(
            "2025-08-01",
            third["turn"]["resolved_slots"]["comparison_time_range"]["start"],
        )

        searches_after_comparison = len(self.data_platform.queries)
        node1_calls_after_comparison = len(self.support.questions)
        table = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "표로 보여줘",
                "expected_head_turn_id": str(third["turn"]["turn_id"]),
            },
            context=self.context,
        )

        self.assertEqual("SUCCESS", table["status"])
        self.assertEqual("PRESENTATION", table["turn"]["route"])
        self.assertEqual("TABLE", table["turn"]["view_type"])
        self.assertEqual(third["turn"]["artifact_id"], table["turn"]["artifact_id"])
        self.assertEqual(3, len(self.submitted_requests))
        self.assertEqual(searches_after_comparison + 1, len(self.data_platform.queries))
        self.assertEqual(node1_calls_after_comparison + 1, len(self.support.questions))
        self.assertEqual(
            third["turn"]["resolved_slots"]["comparison_time_range"],
            table["turn"]["resolved_slots"]["comparison_time_range"],
        )

    async def test_golden_dialogue_view_sequence_and_two_report_blocks(self) -> None:
        """GD-02는 한 Artifact에서 line→bar→table 후 마지막 두 View만 보고서에 담는다."""

        conversation = await self.repo.create_conversation(self.user_id, "GD-02")
        conv_id = conversation["conversation_id"]
        messages = [
            "2025년 7월 인식 객실 매출을 보여줘.",
            "그래프로 띄워줘.",
            "다른 그래프로 띄워줘.",
            "표로도 띄워줘.",
            "현재 그래프와 표를 보고서에 담아줘.",
        ]
        self.support.program(
            messages[0],
            selected_metric_id="room_revenue",
            selected_metric_ids=["room_revenue"],
            metric_ids=["room_revenue"],
            period_candidates=[
                {
                    "start": "2025-07-01",
                    "end_exclusive": "2025-08-01",
                    "source_text": "2025년 7월",
                }
            ],
            analysis_operation="time_trend",
            analysis_time_bucket="day",
            requested_route="ANALYSIS",
            is_elliptical=False,
        )
        for message, presentation_type in zip(
            messages[1:4],
            ("LINE", "BAR", "TABLE"),
            strict=True,
        ):
            self.support.program(
                message,
                requested_route="PRESENTATION",
                selected_metric_id=None,
                selected_metric_ids=[],
                presentation_type=presentation_type,
                is_elliptical=True,
            )
        self.support.program(
            messages[4],
            requested_route="REPORT_ACTION",
            selected_metric_id=None,
            selected_metric_ids=[],
            is_elliptical=True,
        )

        results = []
        expected_head = None
        for message in messages:
            result = await self.execute_command(
                conversation_id=conv_id,
                payload={
                    "user_message": message,
                    "expected_head_turn_id": (
                        str(expected_head) if expected_head is not None else None
                    ),
                },
                context=self.context,
            )
            self.assertEqual("SUCCESS", result["status"])
            results.append(result)
            expected_head = result["turn"]["turn_id"]

        artifact_id = results[0]["turn"]["artifact_id"]
        self.assertEqual(1, len(self.submitted_requests))
        self.assertEqual(5, len(self.repo.turns[conv_id]))
        self.assertEqual(4, len(self.repo.view_specs))
        self.assertEqual(
            ["LINE", "BAR", "TABLE"],
            [result["turn"]["view_type"] for result in results[1:4]],
        )
        self.assertTrue(
            all(result["turn"]["artifact_id"] == artifact_id for result in results)
        )

        report_definition_id = results[4]["turn"]["report_definition_id"]
        draft = await self.report_repo.get_version(str(report_definition_id), 1)
        self.assertEqual(2, len(draft.blocks))
        self.assertEqual([BlockType.CHART, BlockType.TABLE], [b.type for b in draft.blocks])
        self.assertEqual(
            [
                str(results[2]["turn"]["view_spec_id"]),
                str(results[3]["turn"]["view_spec_id"]),
            ],
            [block.view_spec_id for block in draft.blocks],
        )

    async def test_presentation_route_creates_view_spec_with_zero_queries(self) -> None:
        """자연어 보기 명령도 추가 해석·쿼리 없이 선행 Artifact를 재사용하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "시각화 전환")
        conv_id = conv["conversation_id"]

        # Turn 1: ANALYSIS
        res1 = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head1 = res1["turn"]["turn_id"]
        art_id = res1["turn"]["artifact_id"]
        searches_after_analysis = len(self.data_platform.queries)
        node1_calls_after_analysis = len(self.support.questions)

        # Turn 2: PRESENTATION ("표로 보여줘")
        res2 = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "표로 보여줘",
                "expected_head_turn_id": str(head1),
            },
            context=self.context,
        )

        self.assertEqual(res2["status"], "SUCCESS")
        self.assertEqual(res2["turn"]["route"], "PRESENTATION")
        self.assertEqual(res2["turn"]["artifact_id"], art_id)
        self.assertIsNotNone(res2["turn"]["view_spec_id"])
        self.assertEqual(
            res2["turn"]["resolved_slots"]["change_set"],
            [
                {
                    "field": "target_chart_type",
                    "operation": "SET",
                    "value": "TABLE",
                }
            ],
        )
        # submit_analysis는 Turn 1에서만 1회 호출됨
        self.assertEqual(len(self.submitted_requests), 1)
        self.assertEqual(searches_after_analysis + 1, len(self.data_platform.queries))
        self.assertEqual(node1_calls_after_analysis + 1, len(self.support.questions))

    async def test_incompatible_presentation_commits_blocked_turn_without_focus_change(self) -> None:
        """시간축 없는 Artifact의 LINE 요청은 typed BLOCKED 이력으로 닫는다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "표현 schema 차단",
        )
        conversation_id = conversation["conversation_id"]
        analysis = await self.execute_command(
            conversation_id=conversation_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        artifact_id = analysis["turn"]["artifact_id"]
        analysis_view_id = analysis["turn"]["view_spec_id"]
        self.repo.artifact_payloads[artifact_id].update(
            {
                "data_snapshot_json": {
                    "columns": ["hotel", "room_revenue_krw"],
                    "rows": [
                        {"hotel": "Grand", "room_revenue_krw": 120000000}
                    ],
                },
                "chart_spec_json": {
                    "chart_type": "bar",
                    "x_field": "hotel",
                    "y_fields": ["room_revenue_krw"],
                },
            }
        )
        self.support.program(
            "선 그래프로 보여줘",
            requested_route="PRESENTATION",
            selected_metric_id=None,
            selected_metric_ids=[],
            presentation_type="LINE",
            is_elliptical=True,
        )

        blocked = await self.execute_command(
            conversation_id=conversation_id,
            payload={
                "user_message": "선 그래프로 보여줘",
                "expected_head_turn_id": str(analysis["turn"]["turn_id"]),
            },
            context=self.context,
        )

        self.assertEqual("BLOCKED", blocked["status"])
        self.assertEqual(
            ErrorCode.PRESENTATION_NOT_SUPPORTED.value,
            blocked["code"],
        )
        self.assertEqual(
            "현재 결과에는 시간 흐름을 나타내는 기간 축이 없습니다.",
            blocked["message"],
        )
        self.assertEqual("PRESENTATION", blocked["turn"]["route"])
        self.assertEqual("BLOCKED", blocked["turn"]["terminal_status"])
        self.assertIsNone(blocked["turn"]["view_spec_id"])
        self.assertEqual(1, len(self.submitted_requests))
        self.assertEqual(
            analysis["turn"]["turn_id"],
            self.repo.conversations[conversation_id]["view_focus_turn_id"],
        )
        self.assertEqual(
            analysis_view_id,
            self.repo.conversations[conversation_id]["view_focus_spec_id"],
        )

    async def test_idempotent_command_replay(self) -> None:
        """동일한 idempotency_key로 요청 시 중복 실행 없이 이전 결과를 그대로 반환하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "멱등성 테스트")
        conv_id = conv["conversation_id"]

        idemp_key = "idemp-unique-123"
        res1 = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "2025년 8월 객실 매출",
                "idempotency_key": idemp_key,
            },
            context=self.context,
        )
        self.assertEqual(res1["status"], "SUCCESS")
        self.assertFalse(res1.get("is_idempotent_replay", False))

        # Re-execute with identical key
        res2 = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "2025년 8월 객실 매출",
                "idempotency_key": idemp_key,
            },
            context=self.context,
        )
        self.assertEqual(res2["status"], "SUCCESS")
        self.assertTrue(res2.get("is_idempotent_replay"))
        self.assertEqual(res1["turn"]["turn_id"], res2["turn"]["turn_id"])
        # Analysis should only have executed once
        self.assertEqual(len(self.submitted_requests), 1)

    async def test_agent_dispatch_admits_once_and_replays_analysis_result(self) -> None:
        """공개 dispatch는 admission-bound Supervisor를 거치며 replay에서 Agent를 재실행하지 않는다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Agent 분석 dispatch",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="2025년 8월 객실 매출",
                idempotency_key="agent-analysis-replay",
                expected_head_turn_id=None,
                requested_route="ANALYSIS",
            ),
            context=self.context,
        )
        unavailable_factory_calls = 0

        def unavailable_rag_factory():
            nonlocal unavailable_factory_calls
            unavailable_factory_calls += 1
            raise AssertionError("분석 route가 RAG service를 만들면 안 됩니다.")

        first = await self.orchestrator.dispatch_agent_command(
            request,
            ConcurrentExecutionGate(),
            unavailable_rag_factory,
        )
        replay = await self.orchestrator.dispatch_agent_command(
            request,
            ConcurrentExecutionGate(),
            unavailable_rag_factory,
        )

        self.assertEqual(first["status"], "SUCCESS")
        self.assertEqual(first["data"]["turn"]["route"], "ANALYSIS")
        self.assertTrue(replay["data"]["is_idempotent_replay"])
        self.assertEqual(
            first["data"]["turn"]["turn_id"],
            replay["data"]["turn"]["turn_id"],
        )
        self.assertEqual(len(self.submitted_requests), 1)
        self.assertEqual(unavailable_factory_calls, 0)
        self.assertIsNotNone(self.submitted_contexts[0].command_id)

    async def test_agent_dispatch_replays_rag_without_rebuilding_gateway(self) -> None:
        """명시 RAG도 같은 admission·Turn 계약을 쓰고 terminal replay는 Gateway와 분리된다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Agent RAG dispatch",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="시설 안전 절차를 알려줘",
                idempotency_key="agent-rag-replay",
                expected_head_turn_id=None,
                requested_route="INTERNAL_GUIDELINE",
            ),
            context=self.context,
        )
        factory_calls = 0
        execution_contexts: list[RequestContext] = []

        class Service:
            async def readiness(
                self,
                context: RequestContext,
            ) -> AgentPortReadiness:
                return AgentPortReadiness(
                    agent=AgentKind.INTERNAL_GUIDELINE,
                    status="ready",
                    capability_version="RagRuntimeReceipt.test.v1",
                    release_refs=("rag-capability:test",),
                )

            async def execute(
                self,
                query,
                context: RequestContext,
                *,
                persist_turn: bool,
            ) -> dict[str, Any]:
                self.assert_query(query, persist_turn)
                execution_contexts.append(context)
                return {
                    "status": "ANSWER",
                    "routing": {
                        "snapshot_question": "승인된 시설 안전 절차",
                        "selected_document_ids": ["MANUAL-SAFETY"],
                    },
                }

            @staticmethod
            def assert_query(query, persist_turn: bool) -> None:
                if persist_turn or query.mode != "DOCUMENT_ONLY":
                    raise AssertionError("RAG Agent 실행 계약이 올바르지 않습니다.")

        def service_factory() -> Service:
            nonlocal factory_calls
            factory_calls += 1
            return Service()

        with patch.dict(os.environ, {"RAG_FEATURE_ENABLED": "1"}):
            first = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                service_factory,
            )
            replay = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                service_factory,
            )

        self.assertEqual(first["data"]["type"], "INTERNAL_GUIDELINE")
        self.assertEqual(
            first["data"]["turn"]["turn_id"],
            replay["data"]["turn"]["turn_id"],
        )
        self.assertEqual(factory_calls, 1)
        self.assertEqual(len(execution_contexts), 1)
        self.assertIsNotNone(execution_contexts[0].command_id)

    async def test_terra_plan_can_route_unmodified_command_to_rag(self) -> None:
        """원본 멱등 command를 바꾸지 않고 모델 계획과 RAG 검색 receipt를 결속한다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Supervisor RAG dispatch",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="시설 안전 절차를 알려줘",
                idempotency_key="model-supervisor-rag-route",
                expected_head_turn_id=None,
            ),
            context=self.context,
        )
        planner_calls = 0
        search_calls = 0

        class Planner:
            async def plan(self, admitted_request, catalog, *, previous_route):
                nonlocal planner_calls
                planner_calls += 1
                return SupervisorPlanResult(
                    plan=SupervisorExecutionPlan(
                        status="EXECUTABLE",
                        tasks=(
                            SupervisorTaskPlan(
                                agent=AgentKind.INTERNAL_GUIDELINE,
                                objective="승인된 시설 안전 문서 검색",
                            ),
                        ),
                    ),
                    evidence_ref=f"model-supervisor:sha256:{'c' * 64}",
                    model="gpt-5.6-terra",
                    response_id="resp_test_rag",
                )

        class Searcher:
            async def search_capability(self, query: str, app_role: str):
                nonlocal search_calls
                search_calls += 1
                return {
                    "schema_version": "RagCapabilityCandidate.v1",
                    "matched": True,
                    "retrieval_request_id": str(uuid4()),
                    "query_hash": "d" * 64,
                    "tool_code": "internal-manual-search",
                    "tool_version": "1.0.0",
                    "model_revision": "text-embedding-3-large:d1024",
                    "embedding_dimension": 1024,
                    "evidence_ids": ["EV-SAFETY-1"],
                    "document_ids": ["MANUAL-SAFETY"],
                    "maximum_score": 0.9,
                }

        class Service:
            async def readiness(self, _context):
                return AgentPortReadiness(
                    agent=AgentKind.INTERNAL_GUIDELINE,
                    status="ready",
                    capability_version="RagRuntimeReceipt.test.v1",
                    release_refs=("rag-capability:test",),
                )

            async def execute(self, query, context, *, persist_turn):
                return {
                    "status": "ANSWER",
                    "routing": {
                        "snapshot_question": query.question,
                        "selected_document_ids": ["MANUAL-SAFETY"],
                    },
                }

        with patch.dict(
            os.environ,
            {"RAG_FEATURE_ENABLED": "1", "ML_FEATURE_ENABLED": "0"},
        ):
            first = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                lambda: Service(),
                supervisor_planner_factory=Planner,
                supervisor_routing_enabled=True,
                internal_guideline_capability_searcher_factory=Searcher,
            )
            replay = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                lambda: Service(),
                supervisor_planner_factory=Planner,
                supervisor_routing_enabled=True,
                internal_guideline_capability_searcher_factory=Searcher,
            )

        self.assertEqual(first["data"]["type"], "INTERNAL_GUIDELINE")
        self.assertEqual(first["data"]["turn"]["route"], "INTERNAL_GUIDELINE")
        self.assertEqual(
            first["data"]["turn"]["turn_id"],
            replay["data"]["turn"]["turn_id"],
        )
        self.assertEqual(planner_calls, 1)
        self.assertEqual(search_calls, 1)

    async def test_agent_dispatch_persists_typed_ml_result_once_and_replays(self) -> None:
        """명시 ML action은 capability·readiness 후 예측·감사 저장을 한 턴으로 확정한다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Agent ML dispatch",
        )
        invocation = MLPredictionInvocation(
            property_id="GRAND",
            as_of="2026-08-18",
            horizon_days=30,
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="30일 객실 수요를 예측해줘",
                idempotency_key="agent-ml-replay",
                expected_head_turn_id=None,
                requested_route="ML_PREDICTION",
                ml_prediction={
                    "property_id": invocation.property_id,
                    "as_of": invocation.as_of,
                    "horizon_days": invocation.horizon_days,
                },
            ),
            context=self.context,
            target_agent=AgentKind.ML_PREDICTION,
            invocation=invocation,
        )
        factory_calls = 0
        capability_calls = 0
        readiness_calls = 0
        generation_calls = 0
        persisted: list[dict[str, Any]] = []

        class Service:
            async def capabilities(self) -> dict[str, Any]:
                nonlocal capability_calls
                capability_calls += 1
                return {
                    "schema_version": "MLRuntimeCapability.v2",
                    "prediction_contract_version": "MLRoomDemandPrediction.v1",
                    "model_version": "approved-demand-release",
                    "model_hash": "a" * 64,
                    "feature_contract_sha256": "b" * 64,
                    "model_type": "daily-demand-forecast",
                    "estimator_type": "ApprovedRegressor",
                    "approval": "APPROVED",
                    "approval_status": "APPROVED",
                    "min_horizon_days": 1,
                    "max_horizon_days": 90,
                    "model_max_horizon_days": 90,
                    "properties": [
                        {
                            "property_id": "GRAND",
                            "min_as_of": "2025-01-01",
                            "max_as_of": "2026-12-31",
                            "feature_max_as_of": "2026-08-18",
                            "history_rows": 500,
                        }
                    ],
                    "synthetic_training_data": False,
                    "history_source": {
                        "table": "pms.ml_evaluation.approved_history",
                        "row_count": 500,
                        "property_count": 1,
                        "series_count": 1,
                        "min_date": "2024-01-01",
                        "max_date": "2026-08-18",
                        "synthetic_only": False,
                        "summary_query_id": "summary-query",
                        "continuity_query_id": "continuity-query",
                    },
                    "query_id": "capability-query",
                }

            async def readiness(self) -> AgentPortReadiness:
                nonlocal readiness_calls
                readiness_calls += 1
                return AgentPortReadiness(
                    agent=AgentKind.ML_PREDICTION,
                    status="ready",
                    capability_version="MLRuntimeCapability.v2",
                    release_refs=("ml-model:sha256:" + "a" * 64,),
                )

            async def generate_prediction(
                self,
                payload: dict[str, Any],
            ) -> dict[str, Any]:
                nonlocal generation_calls
                generation_calls += 1
                return {
                    "schema_version": "MLRoomDemandPrediction.v1",
                    "status": "SUCCEEDED",
                    **payload,
                }

            async def persist_prediction(
                self,
                session: Any,
                prediction: dict[str, Any],
            ) -> None:
                persisted.append(dict(prediction))

        def service_factory() -> Service:
            nonlocal factory_calls
            factory_calls += 1
            return Service()

        with patch.dict(
            os.environ,
            {"RAG_FEATURE_ENABLED": "0", "ML_FEATURE_ENABLED": "1"},
        ):
            first = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                lambda: None,
                ml_prediction_service_factory=service_factory,
                ml_prediction_executor_factory=_ml_mcp_executor_factory,
            )
            replay = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                lambda: None,
                ml_prediction_service_factory=service_factory,
                ml_prediction_executor_factory=_ml_mcp_executor_factory,
            )

        self.assertEqual(first["data"]["type"], "ML_PREDICTION")
        self.assertEqual(first["data"]["turn"]["route"], "ML_PREDICTION")
        self.assertEqual(
            first["data"]["turn"]["resolved_slots"]["ml_prediction"],
            first["data"]["ml_prediction"],
        )
        self.assertEqual(
            first["data"]["turn"]["turn_id"],
            replay["data"]["turn"]["turn_id"],
        )
        self.assertTrue(replay["data"]["is_idempotent_replay"])
        self.assertEqual(factory_calls, 1)
        self.assertEqual(capability_calls, 1)
        self.assertEqual(readiness_calls, 1)
        self.assertEqual(generation_calls, 1)
        self.assertEqual(persisted, [first["data"]["ml_prediction"]])

    async def test_terra_plan_reuses_previous_ml_scope_and_rechecks_invocation(self) -> None:
        """ML 후속 요청은 저장된 입력 범위를 Supervisor에 전달하고 다시 검증해 실행한다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Supervisor ML dispatch",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="다음 30일 객실 수요를 예측해줘",
                idempotency_key="model-supervisor-ml-route",
                expected_head_turn_id=None,
            ),
            context=self.context,
        )
        capability_calls = 0
        generation_payloads: list[dict[str, Any]] = []
        planner_requests: list[AgentRequest] = []
        previous_routes: list[str | None] = []

        class Planner:
            async def plan(self, admitted_request, catalog, *, previous_route):
                self.catalog = catalog
                planner_requests.append(admitted_request)
                previous_routes.append(previous_route)
                return SupervisorPlanResult(
                    plan=SupervisorExecutionPlan(
                        status="EXECUTABLE",
                        tasks=(
                            SupervisorTaskPlan(
                                agent=AgentKind.ML_PREDICTION,
                                objective="지원 property의 30일 객실 수요 예측",
                                ml_prediction={
                                    "property_id": "GRAND",
                                    "as_of": "2026-08-18",
                                    "horizon_days": 30,
                                },
                            ),
                        ),
                    ),
                    evidence_ref=f"model-supervisor:sha256:{'e' * 64}",
                    model="gpt-5.6-terra",
                    response_id="resp_test_ml",
                )

        class Service:
            async def capabilities(self):
                nonlocal capability_calls
                capability_calls += 1
                return {
                    "schema_version": "MLRuntimeCapability.v2",
                    "prediction_contract_version": "MLRoomDemandPrediction.v1",
                    "model_version": "approved-demand-release",
                    "model_hash": "a" * 64,
                    "feature_contract_sha256": "b" * 64,
                    "model_type": "daily-demand-forecast",
                    "estimator_type": "ApprovedRegressor",
                    "approval": "APPROVED",
                    "approval_status": "APPROVED",
                    "min_horizon_days": 1,
                    "max_horizon_days": 90,
                    "model_max_horizon_days": 90,
                    "properties": [
                        {
                            "property_id": "GRAND",
                            "min_as_of": "2025-01-01",
                            "max_as_of": "2026-12-31",
                            "feature_max_as_of": "2026-08-18",
                            "history_rows": 500,
                        }
                    ],
                    "synthetic_training_data": False,
                    "history_source": {
                        "table": "pms.ml_evaluation.approved_history",
                        "row_count": 500,
                        "property_count": 1,
                        "series_count": 1,
                        "min_date": "2024-01-01",
                        "max_date": "2026-08-18",
                        "synthetic_only": False,
                        "summary_query_id": "summary-query",
                        "continuity_query_id": "continuity-query",
                    },
                    "query_id": "capability-query",
                }

            async def readiness(self):
                return AgentPortReadiness(
                    agent=AgentKind.ML_PREDICTION,
                    status="ready",
                    capability_version="MLRuntimeCapability.v2",
                    release_refs=("ml-model:sha256:" + "a" * 64,),
                )

            async def generate_prediction(self, payload):
                generation_payloads.append(dict(payload))
                return {
                    "schema_version": "MLRoomDemandPrediction.v1",
                    "status": "SUCCEEDED",
                    **payload,
                }

            async def persist_prediction(self, _session, _prediction):
                return None

        service = Service()
        planner = Planner()
        with patch.dict(
            os.environ,
            {"RAG_FEATURE_ENABLED": "0", "ML_FEATURE_ENABLED": "1"},
        ):
            result = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                lambda: None,
                supervisor_planner_factory=lambda: planner,
                supervisor_routing_enabled=True,
                ml_prediction_service_factory=lambda: service,
                ml_prediction_executor_factory=_ml_mcp_executor_factory,
            )
            followup_request = AgentRequest(
                conversation_id=conversation["conversation_id"],
                command=ConversationCommandRequest(
                    user_message=(
                        "예측 결과를 날짜별 그래프로 보여주고 사용한 모델을 알려줘"
                    ),
                    idempotency_key="model-supervisor-ml-followup",
                    expected_head_turn_id=result["data"]["turn"]["turn_id"],
                ),
                context=self.context,
            )
            followup = await self.orchestrator.dispatch_agent_command(
                followup_request,
                ConcurrentExecutionGate(),
                lambda: None,
                supervisor_planner_factory=lambda: planner,
                supervisor_routing_enabled=True,
                ml_prediction_service_factory=lambda: service,
                ml_prediction_executor_factory=_ml_mcp_executor_factory,
            )

        self.assertEqual(result["data"]["type"], "ML_PREDICTION")
        self.assertEqual(result["data"]["turn"]["route"], "ML_PREDICTION")
        self.assertEqual(followup["data"]["turn"]["route"], "ML_PREDICTION")
        self.assertEqual(
            generation_payloads,
            [
                {
                    "property_id": "GRAND",
                    "as_of": "2026-08-18",
                    "horizon_days": 30,
                },
                {
                    "property_id": "GRAND",
                    "as_of": "2026-08-18",
                    "horizon_days": 30,
                },
            ],
        )
        self.assertEqual(capability_calls, 4)
        self.assertIn(AgentKind.ML_PREDICTION, planner.catalog.available_agents)
        self.assertIsNone(planner_requests[0].previous_ml)
        self.assertIsNotNone(planner_requests[1].previous_ml)
        self.assertEqual(planner_requests[1].previous_ml.property_id, "GRAND")
        self.assertEqual(planner_requests[1].previous_ml.as_of.isoformat(), "2026-08-18")
        self.assertEqual(planner_requests[1].previous_ml.horizon_days, 30)
        self.assertEqual(previous_routes, [None, "ML_PREDICTION"])

    async def test_ml_audit_failure_does_not_commit_partial_turn(self) -> None:
        """감사 저장 실패를 예측 턴 성공으로 남기지 않는다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "ML audit failure",
        )

        async def generate(_context: RequestContext) -> dict[str, Any]:
            return {
                "schema_version": "MLRoomDemandPrediction.v1",
                "status": "SUCCEEDED",
                "property_id": "GRAND",
                "as_of": "2026-08-18",
                "horizon_days": 30,
            }

        async def persist(_session: Any, _prediction: dict[str, Any]) -> None:
            raise RuntimeError("audit write failed")

        with self.assertRaises(RuntimeError):
            await self.orchestrator.execute_ml_prediction_command(
                conversation["conversation_id"],
                {
                    "user_message": "30일 객실 수요를 예측해줘",
                    "idempotency_key": "agent-ml-audit-failure",
                    "expected_head_turn_id": None,
                    "requested_route": "ML_PREDICTION",
                    "ml_prediction": {
                        "property_id": "GRAND",
                        "as_of": "2026-08-18",
                        "horizon_days": 30,
                    },
                },
                self.context,
                generate,
                persist,
            )

        self.assertEqual(self.repo.turns[conversation["conversation_id"]], [])
        self.assertIsNone(conversation["active_command_id"])
        command = self.repo.commands[
            (conversation["conversation_id"], "agent-ml-audit-failure")
        ]
        self.assertEqual(command["status"], "FAILED")
        self.assertEqual(
            command["error_response"]["code"],
            "AGENT_DISPATCH_FAILED",
        )

    async def test_agent_route_failure_releases_lease_and_replays_terminal_error(self) -> None:
        """admission 뒤 route 확정 실패도 RUNNING command를 남기지 않는다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Agent route 실패",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="승인된 범위에서 분석해줘",
                idempotency_key="agent-route-failure",
                expected_head_turn_id=None,
            ),
            context=self.context,
        )
        resolver_calls = 0

        class FailingResolver:
            decision_sources = frozenset(
                {AgentDecisionSource.GOVERNED_DEFAULT}
            )

            async def resolve(self, admitted_request: AgentRequest):
                nonlocal resolver_calls
                resolver_calls += 1
                if admitted_request.context.command_id is None:
                    raise AssertionError("route resolver 전에 admission이 필요합니다.")
                raise AgentDispatchError(
                    "AGENT_ROUTE_NOT_RESOLVED",
                    "요청을 처리할 승인된 Agent를 확정하지 못했습니다.",
                    evidence_refs=("capability-receipt:none",),
                )

        with self.assertRaises(AgentDispatchError):
            await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                lambda: None,
                route_resolver=FailingResolver(),
            )

        command = self.repo.commands[
            (conversation["conversation_id"], "agent-route-failure")
        ]
        self.assertEqual(command["status"], "FAILED")
        self.assertEqual(
            command["error_response"]["code"],
            "AGENT_ROUTE_NOT_RESOLVED",
        )
        self.assertEqual(
            command["error_response"]["evidence_refs"],
            ["capability-receipt:none"],
        )
        self.assertEqual(command["error_response"]["status_code"], 422)
        self.assertFalse(command["error_response"]["retryable"])
        self.assertEqual(
            command["error_response"]["required_action"],
            "MODIFY_REQUEST",
        )
        self.assertIsNone(conversation["active_command_id"])

        replay = await self.orchestrator.dispatch_agent_command(
            request,
            ConcurrentExecutionGate(),
            lambda: None,
            route_resolver=FailingResolver(),
        )
        self.assertEqual(replay["data"]["status"], "FAILED")
        self.assertTrue(replay["data"]["is_idempotent_replay"])
        self.assertEqual(resolver_calls, 1)

    async def test_capability_route_requires_and_accepts_explicit_dispatch_gate(self) -> None:
        """승인된 probe 교체 시에만 dispatch에서 capability 결정을 명시적으로 연다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Capability route 연결",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="2025년 8월 객실 매출",
                idempotency_key="agent-capability-route-enabled",
                expected_head_turn_id=None,
            ),
            context=self.context,
        )

        class CapabilityResolver:
            decision_sources = frozenset(
                {AgentDecisionSource.CAPABILITY_EVIDENCE}
            )

            async def resolve(
                self,
                admitted_request: AgentRequest,
            ) -> SupervisorDecision:
                if admitted_request.context.command_id is None:
                    raise AssertionError("route resolver 전에 admission이 필요합니다.")
                return SupervisorDecision(
                    agent=AgentKind.ANALYSIS_WORKFLOW,
                    reason="ANALYSIS_CAPABILITY_MATCH",
                    source=AgentDecisionSource.CAPABILITY_EVIDENCE,
                    evidence_refs=("analysis-probe:approved-replacement",),
                )

        result = await self.orchestrator.dispatch_agent_command(
            request,
            ConcurrentExecutionGate(),
            lambda: None,
            route_resolver=CapabilityResolver(),
            supervisor_routing_enabled=True,
        )

        self.assertEqual(result["data"]["status"], "SUCCESS")
        self.assertEqual(len(self.submitted_requests), 1)

    async def test_terra_plan_is_rechecked_by_selected_analysis_capability(self) -> None:
        """모델 계획은 admission 뒤 생성되고 선택 Agent의 catalog receipt를 다시 통과한다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Supervisor route 연결",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="2025년 8월 객실 매출",
                idempotency_key="model-supervisor-analysis-route",
                expected_head_turn_id=None,
            ),
            context=self.context,
        )
        self.data_platform.assets = [
            {
                "urn": "urn:li:dataset:(serving,room_daily,PROD)",
                "context_release": TEST_SEMANTIC_RELEASE,
                "metrics": [
                    {
                        "id": "room_revenue_krw",
                        "visibility": "BUSINESS",
                        "candidate_selectable": True,
                    }
                ],
            }
        ]
        planner_calls: list[tuple[UUID | None, str | None]] = []

        class Planner:
            async def plan(self, admitted_request, catalog, *, previous_route):
                planner_calls.append(
                    (admitted_request.context.command_id, previous_route)
                )
                self.catalog = catalog
                return SupervisorPlanResult(
                    plan=SupervisorExecutionPlan(
                        status="EXECUTABLE",
                        tasks=(
                            SupervisorTaskPlan(
                                agent=AgentKind.ANALYSIS_WORKFLOW,
                                objective="승인된 객실 매출 지표 분석",
                            ),
                        ),
                    ),
                    evidence_ref=f"model-supervisor:sha256:{'b' * 64}",
                    model="gpt-5.6-terra",
                    response_id="resp_test_supervisor",
                )

        planner = Planner()
        with patch.dict(
            "os.environ",
            {"RAG_FEATURE_ENABLED": "0", "ML_FEATURE_ENABLED": "0"},
        ):
            result = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                lambda: None,
                supervisor_planner_factory=lambda: planner,
                supervisor_routing_enabled=True,
            )

        self.assertEqual(result["data"]["status"], "SUCCESS")
        self.assertEqual(len(self.submitted_requests), 1)
        self.assertEqual(len(planner_calls), 1)
        self.assertIsNotNone(planner_calls[0][0])
        self.assertIsNone(planner_calls[0][1])
        self.assertIn(
            AgentKind.ANALYSIS_WORKFLOW,
            planner.catalog.available_agents,
        )

    async def test_terra_composite_plan_executes_three_agents_in_one_terminal(self) -> None:
        """복합 계획은 task별 실제 경계를 통과하고 한 Turn으로 저장·재생한다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Supervisor composite dispatch",
        )
        original_message = (
            "2025년 7월과 8월 점유율 하락 원인을 내부 자료와 함께 분석하고 "
            "9월 객실 수요를 예측해줘"
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message=original_message,
                idempotency_key="model-supervisor-composite-route",
                expected_head_turn_id=None,
            ),
            context=self.context,
        )
        self.data_platform.assets = [
            {
                "urn": "urn:li:dataset:(serving,room_daily,PROD)",
                "context_release": TEST_SEMANTIC_RELEASE,
                "metrics": [
                    {
                        "id": "occupancy_rate",
                        "visibility": "BUSINESS",
                        "candidate_selectable": True,
                    }
                ],
            }
        ]
        analysis_objective = "2025년 7월과 8월 객실 점유율 변화 분석"
        rag_objective = "점유율 하락 원인과 관련된 승인 내부 자료 검색"
        ml_objective = "GRAND property의 2025년 9월 30일 객실 수요 예측"
        planner_calls = 0
        rag_queries: list[tuple[str, bool]] = []
        generated: list[dict[str, Any]] = []
        persisted: list[dict[str, Any]] = []

        class Planner:
            async def plan(self, admitted_request, catalog, *, previous_route):
                nonlocal planner_calls
                planner_calls += 1
                return SupervisorPlanResult(
                    plan=SupervisorExecutionPlan(
                        status="EXECUTABLE",
                        tasks=(
                            SupervisorTaskPlan(
                                agent=AgentKind.ANALYSIS_WORKFLOW,
                                objective=analysis_objective,
                            ),
                            SupervisorTaskPlan(
                                agent=AgentKind.INTERNAL_GUIDELINE,
                                objective=rag_objective,
                            ),
                            SupervisorTaskPlan(
                                agent=AgentKind.ML_PREDICTION,
                                objective=ml_objective,
                                ml_prediction={
                                    "property_id": "GRAND",
                                    "as_of": "2026-08-18",
                                    "horizon_days": 30,
                                },
                            ),
                        ),
                    ),
                    evidence_ref=f"model-supervisor:sha256:{'f' * 64}",
                    model="gpt-5.6-terra",
                    response_id="resp_test_composite",
                )

        class Searcher:
            async def search_capability(self, query: str, app_role: str):
                return {
                    "schema_version": "RagCapabilityCandidate.v1",
                    "matched": True,
                    "retrieval_request_id": str(uuid4()),
                    "query_hash": "1" * 64,
                    "tool_code": "internal-manual-search",
                    "tool_version": "1.0.0",
                    "model_revision": "text-embedding-3-large:d1024",
                    "embedding_dimension": 1024,
                    "evidence_ids": ["EV-OCCUPANCY-1"],
                    "document_ids": ["MONTHLY-MANAGEMENT-REPORT"],
                    "maximum_score": 0.91,
                }

        class RAGService:
            async def readiness(self, _context):
                return AgentPortReadiness(
                    agent=AgentKind.INTERNAL_GUIDELINE,
                    status="ready",
                    capability_version="RagRuntimeReceipt.test.v1",
                    release_refs=("rag-capability:test",),
                )

            async def execute(self, query, _context, *, persist_turn):
                rag_queries.append((query.question, persist_turn))
                return {
                    "status": "ANSWER",
                    "answer": "승인 문서 근거 답변",
                    "evidence_ids": ["EV-OCCUPANCY-1"],
                }

        class MLService:
            async def capabilities(self):
                return {
                    "schema_version": "MLRuntimeCapability.v2",
                    "prediction_contract_version": "MLRoomDemandPrediction.v1",
                    "model_version": "approved-demand-release",
                    "model_hash": "a" * 64,
                    "feature_contract_sha256": "b" * 64,
                    "model_type": "daily-demand-forecast",
                    "estimator_type": "ApprovedRegressor",
                    "approval": "APPROVED",
                    "approval_status": "APPROVED",
                    "min_horizon_days": 1,
                    "max_horizon_days": 90,
                    "model_max_horizon_days": 90,
                    "properties": [
                        {
                            "property_id": "GRAND",
                            "min_as_of": "2025-01-01",
                            "max_as_of": "2026-12-31",
                            "feature_max_as_of": "2026-08-18",
                            "history_rows": 500,
                        }
                    ],
                    "synthetic_training_data": False,
                    "history_source": {
                        "table": "pms.ml_evaluation.approved_history",
                        "row_count": 500,
                        "property_count": 1,
                        "series_count": 1,
                        "min_date": "2024-01-01",
                        "max_date": "2026-08-18",
                        "synthetic_only": False,
                        "summary_query_id": "summary-query",
                        "continuity_query_id": "continuity-query",
                    },
                    "query_id": "capability-query",
                }

            async def readiness(self):
                return AgentPortReadiness(
                    agent=AgentKind.ML_PREDICTION,
                    status="ready",
                    capability_version="MLRuntimeCapability.v2",
                    release_refs=("ml-model:sha256:" + "a" * 64,),
                )

            async def generate_prediction(self, payload):
                generated.append(dict(payload))
                return {
                    "schema_version": "MLRoomDemandPrediction.v1",
                    "status": "SUCCEEDED",
                    **payload,
                }

            async def persist_prediction(self, _session, prediction):
                persisted.append(dict(prediction))

        ml_service = MLService()
        with patch.dict(
            os.environ,
            {"RAG_FEATURE_ENABLED": "1", "ML_FEATURE_ENABLED": "1"},
        ):
            first = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                RAGService,
                supervisor_planner_factory=Planner,
                supervisor_routing_enabled=True,
                internal_guideline_capability_searcher_factory=Searcher,
                ml_prediction_service_factory=lambda: ml_service,
                ml_prediction_executor_factory=_ml_mcp_executor_factory,
            )
            replay = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                RAGService,
                supervisor_planner_factory=Planner,
                supervisor_routing_enabled=True,
                internal_guideline_capability_searcher_factory=Searcher,
                ml_prediction_service_factory=lambda: ml_service,
                ml_prediction_executor_factory=_ml_mcp_executor_factory,
            )

        data = first["data"]
        self.assertEqual(data["type"], "COMPOSITE")
        self.assertEqual(data["turn"]["route"], "ANALYSIS")
        self.assertEqual(data["turn"]["user_message"], original_message)
        self.assertEqual(self.submitted_requests[-1].question, analysis_objective)
        self.assertEqual(rag_queries, [(rag_objective, False)])
        self.assertEqual(len(generated), 1)
        self.assertEqual(persisted, [data["ml_prediction"]])
        self.assertEqual(
            data["composition"]["agents"],
            [
                "ANALYSIS_WORKFLOW",
                "INTERNAL_GUIDELINE",
                "ML_PREDICTION",
            ],
        )
        self.assertEqual(
            replay["data"]["turn"]["turn_id"],
            data["turn"]["turn_id"],
        )
        self.assertEqual(replay["data"]["type"], "COMPOSITE")
        self.assertEqual(planner_calls, 1)
        self.assertEqual(len(rag_queries), 1)
        self.assertEqual(len(generated), 1)

    async def test_agent_route_renews_lease_before_port_execution(self) -> None:
        """장시간 resolver 구간도 admitted command lease heartbeat로 보호한다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Agent route heartbeat",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="2025년 8월 객실 매출",
                idempotency_key="agent-route-heartbeat",
                expected_head_turn_id=None,
            ),
            context=self.context,
        )
        renewal_observed = asyncio.Event()
        renewals: list[tuple[UUID, UUID]] = []

        async def renew_lease(conversation_id: UUID, command_id: UUID) -> bool:
            renewals.append((conversation_id, command_id))
            renewal_observed.set()
            return True

        self.repo.renew_lease = renew_lease

        class WaitingResolver:
            decision_sources = frozenset(
                {AgentDecisionSource.GOVERNED_DEFAULT}
            )

            async def resolve(
                self,
                admitted_request: AgentRequest,
            ) -> SupervisorDecision:
                await asyncio.wait_for(renewal_observed.wait(), timeout=0.5)
                return SupervisorDecision(
                    agent=AgentKind.ANALYSIS_WORKFLOW,
                    reason="GOVERNED_CONVERSATION_ROUTE",
                    source=AgentDecisionSource.GOVERNED_DEFAULT,
                )

        result = await self.orchestrator.dispatch_agent_command(
            request,
            ConcurrentExecutionGate(),
            lambda: None,
            route_resolver=WaitingResolver(),
        )

        self.assertEqual(result["data"]["status"], "SUCCESS")
        self.assertTrue(renewals)
        self.assertEqual(renewals[0][0], conversation["conversation_id"])
        self.assertEqual(
            renewals[0][1],
            self.repo.commands[
                (conversation["conversation_id"], "agent-route-heartbeat")
            ]["command_id"],
        )

    async def test_agent_route_timeout_releases_admitted_command(self) -> None:
        """resolver 제한 시간 초과는 port 실행 없이 lease와 command를 종결한다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Agent route timeout",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="승인된 범위에서 분석해줘",
                idempotency_key="agent-route-timeout",
                expected_head_turn_id=None,
            ),
            context=self.context,
        )

        class HangingResolver:
            decision_sources = frozenset(
                {AgentDecisionSource.GOVERNED_DEFAULT}
            )

            async def resolve(self, admitted_request: AgentRequest):
                await asyncio.Event().wait()

        with patch.dict(
            os.environ,
            {"CONVERSATION_AGENT_ROUTE_TIMEOUT_SECONDS": "0.01"},
        ):
            with self.assertRaises(AgentDispatchError) as raised:
                await self.orchestrator.dispatch_agent_command(
                    request,
                    ConcurrentExecutionGate(),
                    lambda: None,
                    route_resolver=HangingResolver(),
                )

        command = self.repo.commands[
            (conversation["conversation_id"], "agent-route-timeout")
        ]
        self.assertEqual(raised.exception.code, "AGENT_ROUTE_TIMEOUT")
        self.assertEqual(
            raised.exception.agent_execution_state.phase,
            AgentExecutionPhase.FAILED,
        )
        self.assertEqual(command["status"], "FAILED")
        self.assertEqual(command["error_response"]["code"], "AGENT_ROUTE_TIMEOUT")
        self.assertIsNone(conversation["active_command_id"])
        self.assertEqual(self.submitted_requests, [])

    async def test_agent_route_lease_loss_blocks_port_execution(self) -> None:
        """routing heartbeat가 소유권 상실을 감지하면 선택된 port도 실행하지 않는다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Agent route lease loss",
        )
        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message="2025년 8월 객실 매출",
                idempotency_key="agent-route-lease-loss",
                expected_head_turn_id=None,
            ),
            context=self.context,
        )
        renewal_attempted = asyncio.Event()

        async def lose_lease(conversation_id: UUID, command_id: UUID) -> bool:
            renewal_attempted.set()
            return False

        self.repo.renew_lease = lose_lease

        class WaitingResolver:
            decision_sources = frozenset(
                {AgentDecisionSource.GOVERNED_DEFAULT}
            )

            async def resolve(
                self,
                admitted_request: AgentRequest,
            ) -> SupervisorDecision:
                await asyncio.wait_for(renewal_attempted.wait(), timeout=0.5)
                await asyncio.sleep(0)
                return SupervisorDecision(
                    agent=AgentKind.ANALYSIS_WORKFLOW,
                    reason="GOVERNED_CONVERSATION_ROUTE",
                    source=AgentDecisionSource.GOVERNED_DEFAULT,
                )

        with self.assertRaises(AgentDispatchError) as raised:
            await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                lambda: None,
                route_resolver=WaitingResolver(),
            )

        self.assertEqual(raised.exception.code, "AGENT_ROUTE_LEASE_LOST")
        self.assertEqual(self.submitted_requests, [])
        command = self.repo.commands[
            (conversation["conversation_id"], "agent-route-lease-loss")
        ]
        self.assertEqual(command["status"], "FAILED")
        self.assertIsNone(conversation["active_command_id"])

    async def test_internal_guideline_uses_shared_command_admission_and_replay(self) -> None:
        """RAG Agent도 turn_commands terminal 결과를 재생하고 Gateway를 중복 호출하지 않는다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "내부지침 멱등성",
        )
        conversation_id = conversation["conversation_id"]
        calls: list[RequestContext] = []

        async def execute_rag(context: RequestContext) -> dict[str, Any]:
            calls.append(context)
            return {
                "status": "ANSWER",
                "turn_id": "untrusted-gateway-turn",
                "routing": {
                    "snapshot_question": "승인된 시설 안전 절차",
                    "selected_document_ids": ["MANUAL-SAFETY"],
                },
            }

        payload = {
            "user_message": "시설 안전 절차를 알려줘",
            "idempotency_key": "rag-command-replay",
            "expected_head_turn_id": None,
            "requested_route": "INTERNAL_GUIDELINE",
        }
        first = await self.orchestrator.execute_internal_guideline_command(
            conversation_id,
            payload,
            self.context,
            execute_rag,
        )
        replay = await self.orchestrator.execute_internal_guideline_command(
            conversation_id,
            payload,
            self.context,
            execute_rag,
        )

        self.assertEqual(first["status"], "SUCCESS")
        self.assertEqual(first["turn"]["route"], "INTERNAL_GUIDELINE")
        self.assertEqual(first["turn"]["resolved_slots"]["rag"]["status"], "ANSWER")
        self.assertNotIn("turn_id", first["turn"]["resolved_slots"]["rag"])
        self.assertEqual(first["rag_response"]["turn_id"], str(first["turn"]["turn_id"]))
        self.assertTrue(replay["is_idempotent_replay"])
        self.assertEqual(first["turn"]["turn_id"], replay["turn"]["turn_id"])
        self.assertEqual(first["rag_response"], replay["rag_response"])
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(calls[0].command_id)
        command = self.repo.commands[(conversation_id, "rag-command-replay")]
        self.assertEqual(command["status"], "COMPLETED")

    async def test_internal_guideline_rejects_changed_idempotency_payload(self) -> None:
        """같은 RAG key에 질문이 달라지면 저장 결과를 재생하지 않는다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "내부지침 hash",
        )
        conversation_id = conversation["conversation_id"]
        calls = 0

        async def execute_rag(context: RequestContext) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            return {"status": "ANSWER", "routing": {"snapshot_question": "안전"}}

        base = {
            "user_message": "안전 절차를 알려줘",
            "idempotency_key": "rag-command-hash",
            "expected_head_turn_id": None,
            "requested_route": "INTERNAL_GUIDELINE",
        }
        await self.orchestrator.execute_internal_guideline_command(
            conversation_id,
            base,
            self.context,
            execute_rag,
        )
        conflict = await self.orchestrator.execute_internal_guideline_command(
            conversation_id,
            {**base, "user_message": "시설 점검 절차를 알려줘"},
            self.context,
            execute_rag,
        )

        self.assertEqual(conflict["status"], "CONFLICT")
        self.assertEqual(conflict["code"], ErrorCode.IDEMPOTENCY_CONFLICT.value)
        self.assertEqual(calls, 1)

    async def test_internal_guideline_failure_is_terminal_and_replayed(self) -> None:
        """RAG 실행 실패도 lease를 해제하고 같은 key에서 실패를 결정론적으로 재생한다."""

        class RagUnavailable(RuntimeError):
            code = "RAG_FEATURE_DISABLED"
            status_code = 503

        conversation = await self.repo.create_conversation(
            self.user_id,
            "내부지침 실패",
        )
        conversation_id = conversation["conversation_id"]
        calls = 0

        async def execute_rag(context: RequestContext) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            raise RagUnavailable("내부지침 검색 기능이 비활성화되었습니다.")

        payload = {
            "user_message": "안전 절차를 알려줘",
            "idempotency_key": "rag-command-failure",
            "expected_head_turn_id": None,
            "requested_route": "INTERNAL_GUIDELINE",
        }
        with self.assertRaises(RagUnavailable):
            await self.orchestrator.execute_internal_guideline_command(
                conversation_id,
                payload,
                self.context,
                execute_rag,
            )
        replay = await self.orchestrator.execute_internal_guideline_command(
            conversation_id,
            payload,
            self.context,
            execute_rag,
        )

        command = self.repo.commands[(conversation_id, "rag-command-failure")]
        self.assertEqual(command["status"], "FAILED")
        self.assertEqual(command["error_response"]["code"], "RAG_FEATURE_DISABLED")
        self.assertIsNone(self.repo.conversations[conversation_id]["active_command_id"])
        self.assertEqual(replay["status"], "FAILED")
        self.assertEqual(replay["_http_status_code"], 503)
        self.assertEqual(calls, 1)

    async def test_command_requires_explicit_idempotency_key_and_head_field(self) -> None:
        """첫 턴도 key와 명시적 null CAS가 없으면 admission 전에 거부한다."""

        conv = await self.repo.create_conversation(self.user_id, "필수 admission")
        with self.assertRaises(ValidationError):
            await self.orchestrator.execute_command(
                conv["conversation_id"],
                {"user_message": "2025년 8월 객실 매출"},
                self.context,
            )
        self.assertEqual(self.repo.commands, {})
        self.assertEqual(self.submitted_requests, [])

    async def test_same_idempotency_key_with_changed_payload_never_replays_or_queries(self) -> None:
        """저장 hash 비교가 replay보다 앞서고 mismatch는 두 번째 실행을 만들지 않는다."""

        conv = await self.repo.create_conversation(self.user_id, "hash mismatch")
        conv_id = conv["conversation_id"]
        key = "stable-client-command"
        first = await self.orchestrator.execute_command(
            conv_id,
            {
                "user_message": "2025년 8월 객실 매출",
                "idempotency_key": key,
                "expected_head_turn_id": None,
            },
            self.context,
        )
        mismatch = await self.orchestrator.execute_command(
            conv_id,
            {
                "user_message": "2025년 8월 식음 매출",
                "idempotency_key": key,
                "expected_head_turn_id": None,
            },
            self.context,
        )

        self.assertEqual(first["status"], "SUCCESS")
        self.assertEqual(mismatch["status"], "CONFLICT")
        self.assertEqual(mismatch["code"], ErrorCode.IDEMPOTENCY_CONFLICT.value)
        self.assertEqual(len(self.submitted_requests), 1)
        self.assertEqual(len(self.repo.turns[conv_id]), 1)

    async def test_path_identity_must_equal_prebound_request_context(self) -> None:
        """client 또는 상류가 다른 conversation identity를 주입해도 실행하지 않는다."""

        conv = await self.repo.create_conversation(self.user_id, "path binding")
        mismatched = self.context.model_copy(update={"conversation_id": uuid4()})
        with self.assertRaises(ValueError):
            await self.orchestrator.execute_command(
                conv["conversation_id"],
                {
                    "user_message": "2025년 8월 객실 매출",
                    "idempotency_key": "path-mismatch",
                    "expected_head_turn_id": None,
                },
                mismatched,
            )
        self.assertEqual(self.repo.commands, {})
        self.assertEqual(self.submitted_requests, [])

    async def test_cas_conflict_detection(self) -> None:
        """expected_head_turn_id 불일치 시 409 CONFLICT를 반환하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "CAS 테스트")
        conv_id = conv["conversation_id"]

        # Turn 1
        res1 = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출"},
            context=self.context,
        )

        # Stale CAS attempt (expected_head is wrong)
        wrong_head = uuid4()
        res_conflict = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "다음 달은?",
                "expected_head_turn_id": str(wrong_head),
            },
            context=self.context,
        )
        self.assertEqual(res_conflict["status"], "CONFLICT")
        self.assertEqual(res_conflict["code"], "CONVERSATION_CONFLICT")

    async def test_active_pointer_change_keeps_executable_pinned_conversation(self) -> None:
        """active 전진만으로 고정 Conversation을 다른 release로 재해석하거나 막지 않는다."""

        conv = await self.repo.create_conversation(self.user_id, "pinned release")
        self.data_platform.active_product_release = "product-release:new-active"
        self.data_platform.active_semantic_release = "semantic-release:new-active"

        result = await self.execute_command(
            conversation_id=conv["conversation_id"],
            payload={"user_message": "2025년 8월 객실 매출"},
            context=self.context,
        )

        self.assertEqual("SUCCESS", result["status"])
        self.assertEqual(
            TEST_PRODUCT_RELEASE,
            result["turn"]["product_release_id"],
        )
        self.assertEqual(TEST_SEMANTIC_RELEASE, result["turn"]["semantic_release_id"])

    async def test_unavailable_pinned_release_blocks_before_command_and_run(self) -> None:
        """고정 release가 실제로 실행 불가할 때만 새 Conversation 전환을 요구한다."""

        conv = await self.repo.create_conversation(self.user_id, "retired release")
        self.data_platform.unavailable_product_releases.add(TEST_PRODUCT_RELEASE)

        result = await self.execute_command(
            conversation_id=conv["conversation_id"],
            payload={"user_message": "2025년 8월 객실 매출"},
            context=self.context,
        )

        self.assertEqual("CONFLICT", result["status"])
        self.assertEqual(ErrorCode.RESOURCE_CONFLICT.value, result["code"])
        self.assertEqual({}, self.repo.commands)
        self.assertEqual([], self.submitted_requests)

    async def test_fail_closed_without_antecedent_artifact(self) -> None:
        """선행 분석 결과가 없을 때 시각화 전환 요청이 Fail-closed 원칙에 따라 거부되는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "선행결과 없음")
        conv_id = conv["conversation_id"]

        with self.assertRaises(ValueError):
            await self.execute_command(
                conversation_id=conv_id,
                payload={"user_message": "차트로 나타내줘"},
                context=self.context,
            )

    async def test_report_action_creates_real_draft_report_and_blocks_with_zero_queries(self) -> None:
        """REPORT_ACTION 요청 시 Trino 쿼리 재실행(0건) 없이 PostgresReportRepository에 실제 draft 보고서와 artifact 블록들을 생성하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "2025년 8월 매출 분석")
        conv_id = conv["conversation_id"]

        # Turn 1: ANALYSIS ("2025년 8월 객실 매출 보여줘")
        res1 = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head1 = res1["turn"]["turn_id"]
        art_id = res1["turn"]["artifact_id"]
        self.assertEqual(len(self.submitted_requests), 1)

        # Turn 2: REPORT_ACTION ("현재 내용을 보고서에 담아줘")
        res2 = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "현재 내용을 보고서에 담아줘",
                "expected_head_turn_id": str(head1),
            },
            context=self.context,
        )

        self.assertEqual(res2["status"], "SUCCESS")
        self.assertEqual(res2["turn"]["route"], "REPORT_ACTION")
        self.assertEqual(res2["turn"]["artifact_id"], art_id)
        report_def_id = res2["turn"]["report_definition_id"]
        self.assertIsNotNone(report_def_id)

        # 0 Trino queries for REPORT_ACTION
        self.assertEqual(len(self.submitted_requests), 1)

        # Check the created draft definition and blocks in report_repo
        draft = await self.report_repo.get_version(str(report_def_id), 1)
        self.assertEqual(draft.definition_id, str(report_def_id))
        self.assertEqual(draft.version, 1)
        self.assertEqual(draft.status, DefinitionStatus.DRAFT)
        self.assertEqual(1, len(draft.blocks))
        current_view_block = draft.blocks[0]
        self.assertEqual(BlockType.TABLE, current_view_block.type)
        self.assertEqual(current_view_block.artifact_id, str(art_id))
        self.assertEqual(current_view_block.query_id, "trino-query-123")
        self.assertEqual(
            str(res1["turn"]["view_spec_id"]),
            current_view_block.view_spec_id,
        )

    async def test_typed_reuse_routes_skip_analysis_preflight(self) -> None:
        """명시적 View/Report action은 새 Metric 해석 없이 기존 lineage만 재사용한다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "typed zero-query actions",
        )
        analysis = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        presentation_message = "현재 결과를 선 그래프로 전환"
        report_message = "현재 그래프를 보고서에 추가"
        self.support.program_error(
            presentation_message,
            AssertionError("typed Presentation must skip analysis preflight"),
        )
        self.support.program_error(
            report_message,
            AssertionError("typed Report action must skip analysis preflight"),
        )

        presentation = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": presentation_message,
                "expected_head_turn_id": str(analysis["turn"]["turn_id"]),
                "requested_route": "PRESENTATION",
                "presentation_type": "LINE",
            },
            context=self.context,
        )
        report = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": report_message,
                "expected_head_turn_id": str(presentation["turn"]["turn_id"]),
                "requested_route": "REPORT_ACTION",
            },
            context=self.context,
        )

        self.assertEqual("SUCCESS", presentation["status"])
        self.assertEqual("SUCCESS", report["status"])
        self.assertEqual("PRESENTATION", presentation["turn"]["route"])
        self.assertEqual("REPORT_ACTION", report["turn"]["route"])
        self.assertEqual(["2025년 8월 객실 매출 보여줘"], self.support.questions)
        self.assertEqual(1, len(self.submitted_requests))
        self.assertEqual(
            analysis["turn"]["artifact_id"],
            presentation["turn"]["artifact_id"],
        )
        self.assertEqual(
            analysis["turn"]["query_id"],
            presentation["turn"]["query_id"],
        )
        self.assertNotEqual(
            analysis["turn"]["view_spec_id"],
            presentation["turn"]["view_spec_id"],
        )

    async def test_report_action_updates_existing_draft_in_subsequent_report_actions(self) -> None:
        """대화방에 이미 연결된 draft 보고서가 있을 때 후속 REPORT_ACTION이 새 uuid 생성 대신 기존 draft blocks를 원자적으로 갱신하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "연속 보고서 추가")
        conv_id = conv["conversation_id"]

        # Turn 1: ANALYSIS 1
        res1 = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head1 = res1["turn"]["turn_id"]

        # Turn 2: REPORT_ACTION 1
        res2 = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "현재 내용을 보고서에 담아줘",
                "expected_head_turn_id": str(head1),
            },
            context=self.context,
        )
        head2 = res2["turn"]["turn_id"]
        report_def_id_1 = res2["turn"]["report_definition_id"]

        # Turn 3: ANALYSIS 2 ("2025년 7월 식음 매출 보여줘")
        res3 = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "2025년 7월 식음 매출 보여줘",
                "expected_head_turn_id": str(head2),
            },
            context=self.context,
        )
        head3 = res3["turn"]["turn_id"]

        # Turn 4: REPORT_ACTION 2 ("이 내용도 보고서에 담아줘")
        res4 = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "이 내용도 보고서에 담아줘",
                "expected_head_turn_id": str(head3),
            },
            context=self.context,
        )
        report_def_id_2 = res4["turn"]["report_definition_id"]

        # Same draft report definition is updated
        self.assertEqual(str(report_def_id_1), str(report_def_id_2))

        # submit_analysis only called twice (for Turn 1 and Turn 3)
        self.assertEqual(len(self.submitted_requests), 2)

        # Updated draft now contains blocks from both turns
        draft = await self.report_repo.get_version(str(report_def_id_1), 1)
        self.assertEqual(2, len(draft.blocks))

    async def test_report_action_fails_closed_when_artifact_lookup_fails(self) -> None:
        """보고서 저장소에서 아티팩트 조회가 실패할 때 에러를 발생시키고 Lease를 안전하게 해제하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "조회 실패 테스트")
        conv_id = conv["conversation_id"]

        # Turn 1: ANALYSIS
        res1 = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head1 = res1["turn"]["turn_id"]
        art_id = res1["turn"]["artifact_id"]

        # Remove artifact from report_repo to simulate missing artifact
        del self.report_repo.artifacts[str(art_id)]

        with self.assertRaises(KeyError):
            await self.execute_command(
                conversation_id=conv_id,
                payload={
                    "user_message": "현재 내용을 보고서에 담아줘",
                    "expected_head_turn_id": str(head1),
                },
                context=self.context,
            )

        # Ensure lease was released on failure
        conv_after = await self.repo.get_conversation(conv_id, self.user_id)
        self.assertIsNone(conv_after["active_command_id"])

    async def test_disambiguation_loop_two_step_interaction(self) -> None:
        """모호한 질의 수신 시 CLARIFICATION_REQUIRED와 선택지를 반환하고, 후속 턴 선택으로 슬롯이 완결되어 분석이 실행되는 2단계 루프 검증."""
        conv = await self.repo.create_conversation(self.user_id, "모호성 해소 대화")
        conv_id = conv["conversation_id"]

        turn1_options = (
            DisambiguationOption(
                label="객실 매출",
                metric_id="room_revenue",
                description="판매된 객실의 총 숙박 매출",
                clarification_type=ClarificationType.METRIC,
                value="room_revenue",
            ),
            DisambiguationOption(
                label="식음 매출",
                metric_id="fnb_revenue",
                description="레스토랑 및 연회 식음 매출",
                clarification_type=ClarificationType.METRIC,
                value="fnb_revenue",
            ),
        )

        call_count = 0

        async def dynamic_submit_analysis(req: AnalysisRequest, ctx: RequestContext):
            nonlocal call_count
            call_count += 1
            self.submitted_requests.append(req)

            # Turn 1: 모호한 질의 -> CLARIFICATION_REQUIRED 응답
            if call_count == 1:
                class FakeClarificationResp:
                    def __init__(self, opts):
                        self.data = AnalysisData(
                            status=AnalysisStatus.CLARIFICATION_REQUIRED,
                            transitions=(AnalysisStatus.RECEIVED, AnalysisStatus.ROUTED, AnalysisStatus.CLARIFICATION_REQUIRED),
                            disambiguation_options=opts,
                        )
                        self.error = ErrorBody(
                            code=ErrorCode.CONTEXT_INCOMPLETE,
                            message="질문이 여러 지표로 해석될 수 있습니다. 분석할 기준을 선택해 주세요.",
                            clarification_type=ClarificationType.METRIC,
                            disambiguation_options=opts,
                            suggestions=("객실 매출", "식음 매출"),
                        )
                    def model_dump(self, **kwargs):
                        return {
                            "data": {
                                "status": "CLARIFICATION_REQUIRED",
                                "disambiguation_options": [o.model_dump() for o in self.data.disambiguation_options],
                            },
                            "error": {
                                "code": "CONTEXT_INCOMPLETE",
                                "clarification_type": "metric",
                            },
                        }
                return FakeClarificationResp(turn1_options)

            # Turn 2: 슬롯이 확정된 후 성공 응답
            artifact_id = uuid4()
            self.repo.existing_artifacts.add(artifact_id)
            self.report_repo.register_artifact(
                artifact_id,
                title=f"{req.question[:30]} 분석",
                narrative=f"{req.question}에 대한 데이터 분석 결과입니다.",
            )
            class FakeSuccessResp:
                def __init__(self, art_id):
                    self.data = AnalysisData(
                        status=AnalysisStatus.SUCCEEDED,
                        transitions=(AnalysisStatus.RECEIVED, AnalysisStatus.ROUTED, AnalysisStatus.SUCCEEDED),
                    )
                    self.error = None
                    self._art_id = art_id
                def model_dump(self, **kwargs):
                    return {
                        "data": {
                            "status": "SUCCEEDED",
                            "artifact": {"artifact_id": str(self._art_id)},
                        }
                    }
            return FakeSuccessResp(artifact_id)

        # dynamic_submit_analysis로 오케스트레이터 구성
        orchestrator = ConversationOrchestrator(
            repository=self.repo,
            data_platform=self.data_platform,
            support=self.support,
            submit_analysis=dynamic_submit_analysis,
            report_repository_factory=lambda request_context, is_admin: self.report_repo,
        )

        # Node1이 "2025년 8월"을 반개구간으로 해석해 typed 후보로 돌려주는 상황을 만든다.
        self.support.structured = {
            "selected_metric_id": "room_revenue",
            "period_relationship": "single",
            "period_candidates": [
                {
                    "start": "2025-08-01T00:00:00+09:00",
                    "end_exclusive": "2025-09-01T00:00:00+09:00",
                    "source_text": "2025년 8월",
                }
            ],
        }

        # -------------------------------------------------------------
        # Step 1 (Turn 1): "2025년 8월 매출 보여줘" (모호한 질의)
        # -------------------------------------------------------------
        res1 = await orchestrator.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "2025년 8월 매출 보여줘",
                "expected_head_turn_id": None,
                "idempotency_key": f"test-{uuid4()}",
            },
            context=self.context,
        )

        self.assertEqual(res1["status"], "CLARIFICATION_REQUIRED")
        self.assertEqual(len(res1["disambiguation_options"]), 2)
        self.assertEqual(res1["disambiguation_options"][0]["metric_id"], "room_revenue")
        self.assertEqual(res1["disambiguation_options"][0]["label"], "객실 매출")

        turn1_id = res1["turn"]["turn_id"]
        turn1_slots = res1["turn"]["resolved_slots"]
        self.assertEqual(turn1_slots["ambiguity_status"], "NEEDS_CLARIFICATION")
        self.assertEqual(len(turn1_slots["disambiguation_options"]), 2)

        # -------------------------------------------------------------
        # Step 2 (Turn 2): "객실 매출" 선택
        # -------------------------------------------------------------
        res2 = await orchestrator.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "객실 매출",
                "expected_head_turn_id": str(turn1_id),
                "idempotency_key": f"test-{uuid4()}",
            },
            context=self.context,
        )

        self.assertEqual(res2["status"], "SUCCESS")
        turn2 = res2["turn"]
        self.assertEqual(turn2["route"], "ANALYSIS")
        self.assertEqual(turn2["resolved_slots"]["ambiguity_status"], "RESOLVED")
        self.assertEqual(turn2["resolved_slots"]["metric_id"], "room_revenue")
        self.assertIsNotNone(turn2["artifact_id"])

        # 검증: Step 2 실행 시 Request에 정확히 1턴의 기간과 선택된 지표가 구조화 전달됨
        last_req = self.submitted_requests[-1]
        self.assertIsNotNone(last_req.resolved_slots)
        self.assertEqual(last_req.resolved_slots.metric_id, "room_revenue")
        self.assertEqual(last_req.resolved_slots.period_start, "2025-08-01")
        self.assertEqual(last_req.resolved_slots.period_end_exclusive, "2025-09-01")




    async def test_search_fallback_never_rewrites_the_user_message_for_interpretation(self) -> None:
        """검색 보강용 직전 지표가 새 턴의 의미와 생략 여부를 오염시키지 않는지 검증.

        자산 검색은 짧은 후속 발화를 찾기 위해 직전 지표를 보조 힌트로 쓸 수 있다.
        그러나 모델이 보는 질문까지 보강 문자열로 바꾸면 새 주제가 이전 지표로 변하거나,
        생략문이 완결문으로 바뀐다. 검색어와 해석 원문은 별도 계약이어야 한다.
        """
        conv = await self.repo.create_conversation(self.user_id, "검색 보강 경계")
        conv_id = conv["conversation_id"]
        first_message = "2025년 8월 객실 매출 보여줘"
        second_message = "식음 매출을 보여줘"
        room_asset = {"urn": "urn:li:dataset:(serving,room_daily,PROD)"}

        self.support.program(
            first_message,
            selected_metric_id="room_revenue",
            metric_ids=["room_revenue"],
            period_candidates=[
                {
                    "start": "2025-08-01",
                    "end_exclusive": "2025-09-01",
                    "source_text": "2025년 8월",
                }
            ],
            is_elliptical=False,
            requested_route="ANALYSIS",
        )
        first = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": first_message},
            context=self.context,
        )
        head = first["turn"]["turn_id"]

        # 새 주제 원문 검색은 비지만, 직전 지표를 typed 우선순위로 준 검색에서는 자산을 찾는 상황.
        self.data_platform.assets = []
        self.data_platform.program_search(second_message, [])
        self.data_platform.program_preferred_search(
            second_message,
            ("room_revenue",),
            [room_asset],
        )
        self.support.program(
            second_message,
            selected_metric_id=None,
            metric_ids=["fnb_revenue"],
            is_elliptical=False,
            requested_route="ANALYSIS",
        )

        second = await self.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": second_message,
                "expected_head_turn_id": str(head),
            },
            context=self.context,
        )

        self.assertEqual(
            self.data_platform.queries[-2:],
            [second_message, second_message],
        )
        self.assertNotIn(
            "preferred_metric_ids",
            self.data_platform.search_contexts[-2],
        )
        self.assertEqual(
            ["room_revenue"],
            self.data_platform.search_contexts[-1]["preferred_metric_ids"],
        )
        self.assertEqual(self.support.questions[-1], second_message)
        slots = second["turn"]["resolved_slots"]
        self.assertIsNone(slots["metric_id"])
        self.assertFalse(slots["is_inherited_metric"])
        self.assertTrue(slots["is_inherited_period"])

    async def test_search_hint_does_not_turn_off_topic_message_into_runtime_failure(self) -> None:
        """직전 지표 검색 힌트 뒤에도 완결형 미일치 발화는 고정 범위 거절로 닫는다."""

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        conversation = await self.repo.create_conversation(
            self.user_id,
            "검색 보강 뒤 범위 밖 요청",
        )
        conversation_id = conversation["conversation_id"]
        first_message = "2026년 8월 객실 매출을 알려줘"
        second_message = "오늘 서울 날씨를 알려줘"
        room_asset = {"urn": "urn:li:dataset:(serving,room_daily,PROD)"}

        self.support.program(
            first_message,
            selected_metric_id="room_revenue",
            selected_metric_ids=["room_revenue"],
            metric_ids=["room_revenue"],
            period_candidates=[
                {
                    "start": "2026-08-01",
                    "end_exclusive": "2026-08-19",
                    "source_text": "2026년 8월",
                }
            ],
            analysis_operation="aggregate",
            intent_candidates=["aggregate"],
            is_elliptical=False,
            requested_route="ANALYSIS",
        )
        first = await self.execute_command(
            conversation_id=conversation_id,
            payload={"user_message": first_message},
            context=self.context,
        )
        head_turn_id = first["turn"]["turn_id"]

        self.data_platform.assets = []
        self.data_platform.program_search(second_message, [])
        self.data_platform.program_preferred_search(
            second_message,
            ("room_revenue",),
            [room_asset],
        )
        missing_context = {
            "metric_resolution": "missing",
            "metric_ids": [],
            "metric_candidates": [],
            "selected_metric_id": None,
            "selected_metric_ids": [],
            "intent_candidates": [],
            "analysis_operation": None,
            "analysis_time_bucket": None,
            "result_limit": None,
            "dimension_candidates": [],
            "dimension_fields": [],
            "filter_fields": [],
            "period_candidates": [],
            "period_relationship": "single",
            "requested_route": None,
            "presentation_type": None,
            "is_elliptical": False,
        }
        self.support.program_error(
            second_message,
            ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에 분석할 지표가 포함되지 않았습니다.",
                partial_context=missing_context,
            ),
        )

        second = await self.execute_command(
            conversation_id=conversation_id,
            payload={
                "user_message": second_message,
                "expected_head_turn_id": str(head_turn_id),
            },
            context=self.context,
        )

        self.assertEqual("BLOCKED", second["status"])
        self.assertEqual("OUT_OF_SCOPE", second["type"])
        self.assertEqual("DATA_ASSET_NOT_FOUND", second["code"])
        self.assertEqual("OUT_OF_SCOPE", second["turn"]["route"])
        self.assertEqual(
            "NO_APPROVED_METRIC_MATCH",
            second["turn"]["resolved_slots"]["scope_rejection"]["reason"],
        )
        self.assertEqual(1, len(self.submitted_requests))
        self.assertEqual(
            [second_message, second_message],
            self.data_platform.queries[-2:],
        )

    async def test_period_only_followup_uses_typed_metric_hint_and_executes_inherited_metric(self) -> None:
        """기간만 바꾼 생략문이 이전 Metric을 상속한 뒤 전체 분석 Gate를 다시 통과한다."""

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        conversation = await self.repo.create_conversation(
            self.user_id,
            "기간 변경 후속 질문",
        )
        first_message = "2026년 3월 호텔별 객실 매출"
        second_message = "3월부터 5월은?"
        room_asset = {"urn": "urn:li:dataset:(serving,room_daily,PROD)"}
        self.support.program(
            first_message,
            selected_metric_id="room_revenue",
            selected_metric_ids=["room_revenue"],
            metric_ids=["room_revenue"],
            period_candidates=[
                {
                    "start": "2026-03-01",
                    "end_exclusive": "2026-04-01",
                    "source_text": "2026년 3월",
                }
            ],
            dimension_fields=[
                {
                    "asset_fqn": "serving.analytics_v4_3.hotel_operations_daily",
                    "column": "hotel_code",
                }
            ],
            analysis_operation="breakdown",
            is_elliptical=False,
            requested_route="ANALYSIS",
        )
        first = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": first_message},
            context=self.context,
        )

        self.data_platform.assets = []
        self.data_platform.program_search(second_message, [])
        self.data_platform.program_preferred_search(
            second_message,
            ("room_revenue",),
            [room_asset],
        )
        partial_context = {
            "intent_candidates": [],
            "metric_ids": [],
            "metric_candidates": [],
            "metric_resolution": "missing",
            "measurement_source_text": None,
            "measurement_source_texts": [],
            "selected_metric_id": None,
            "selected_metric_ids": [],
            "analysis_operation": None,
            "result_limit": None,
            "dimension_candidates": [],
            "dimension_fields": [],
            "filter_fields": [],
            "period_candidates": [
                {
                    "start": "2026-03-01T00:00:00+09:00",
                    "end_exclusive": "2026-06-01T00:00:00+09:00",
                    "source_text": "3월부터 5월",
                }
            ],
            "period_relationship": "single",
            "requested_route": "ANALYSIS",
            "presentation_type": None,
            "is_elliptical": True,
        }
        self.support.program_error(
            second_message,
            ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에 분석할 지표가 포함되지 않았습니다.",
                partial_context=partial_context,
            ),
        )

        second = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": second_message,
                "expected_head_turn_id": str(first["turn"]["turn_id"]),
            },
            context=self.context,
        )

        self.assertEqual("SUCCESS", second["status"])
        self.assertEqual(
            [second_message, second_message],
            self.data_platform.queries[-2:],
        )
        self.assertEqual(
            ["room_revenue"],
            self.data_platform.search_contexts[-1]["preferred_metric_ids"],
        )
        slots = second["turn"]["resolved_slots"]
        self.assertEqual("room_revenue", slots["metric_id"])
        self.assertEqual(["room_revenue"], slots["metric_ids"])
        self.assertTrue(slots["is_inherited_metric"])
        self.assertTrue(slots["is_inherited_dimension"])
        self.assertFalse(slots["is_inherited_period"])
        self.assertEqual("breakdown", slots["analysis_operation"])
        self.assertEqual(
            [
                {
                    "asset_fqn": "serving.analytics_v4_3.hotel_operations_daily",
                    "column": "hotel_code",
                }
            ],
            slots["dimension_fields"],
        )
        self.assertEqual("2026-03-01", slots["time_range"]["start"])
        self.assertEqual("2026-06-01", slots["time_range"]["end_exclusive"])
        request = self.submitted_requests[-1]
        self.assertIsNotNone(request.resolved_slots)
        self.assertEqual("2026-03-01", request.resolved_slots.period_start)
        self.assertEqual("2026-06-01", request.resolved_slots.period_end_exclusive)
        self.assertEqual(2, len(self.submitted_requests))

    async def test_supervisor_dispatch_preserves_typed_analysis_context_for_period_followup(self) -> None:
        """Supervisor가 기간 생략문을 분석 capability까지 안전하게 전달한다."""

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        conversation = await self.repo.create_conversation(
            self.user_id,
            "Supervisor 기간 변경 후속 질문",
        )
        first_message = "2026년 6월 객실 매출"
        second_message = "3월부터 5월은?"
        self.support.program(
            first_message,
            selected_metric_id="room_revenue",
            selected_metric_ids=["room_revenue"],
            metric_ids=["room_revenue"],
            period_candidates=[
                {
                    "start": "2026-06-01T00:00:00+09:00",
                    "end_exclusive": "2026-07-01T00:00:00+09:00",
                    "source_text": "2026년 6월",
                }
            ],
            analysis_operation="aggregate",
            requested_route="ANALYSIS",
            is_elliptical=False,
        )
        first = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": first_message},
            context=self.context,
        )

        room_asset = {
            "urn": "urn:li:dataset:(serving,room_daily,PROD)",
            "context_release": TEST_SEMANTIC_RELEASE,
            "metrics": [
                {
                    "id": "room_revenue",
                    "visibility": "BUSINESS",
                    "candidate_selectable": True,
                }
            ],
        }
        self.data_platform.assets = []
        self.data_platform.program_search(second_message, [])
        self.data_platform.program_preferred_search(
            second_message,
            ("room_revenue",),
            [room_asset],
        )
        self.support.program_error(
            second_message,
            ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에 분석할 지표가 포함되지 않았습니다.",
                partial_context={
                    "metric_resolution": "missing",
                    "metric_ids": [],
                    "metric_candidates": [],
                    "measurement_source_text": None,
                    "measurement_source_texts": [],
                    "selected_metric_id": None,
                    "selected_metric_ids": [],
                    "intent_candidates": [],
                    "analysis_operation": None,
                    "analysis_time_bucket": None,
                    "result_limit": None,
                    "dimension_candidates": [],
                    "dimension_fields": [],
                    "filter_fields": [],
                    "period_candidates": [
                        {
                            "start": "2026-03-01T00:00:00+09:00",
                            "end_exclusive": "2026-06-01T00:00:00+09:00",
                            "source_text": "3월부터 5월",
                        }
                    ],
                    "period_relationship": "single",
                    "requested_route": "ANALYSIS",
                    "presentation_type": None,
                    "is_elliptical": True,
                },
            ),
        )
        planner_requests: list[AgentRequest] = []

        class Planner:
            async def plan(self, admitted_request, catalog, *, previous_route):
                planner_requests.append(admitted_request)
                return SupervisorPlanResult(
                    plan=SupervisorExecutionPlan(
                        status="EXECUTABLE",
                        tasks=(
                            SupervisorTaskPlan(
                                agent=AgentKind.ANALYSIS_WORKFLOW,
                                objective=second_message,
                            ),
                        ),
                    ),
                    evidence_ref=f"model-supervisor:sha256:{'d' * 64}",
                    model="gpt-5.6-terra",
                    response_id="resp_multiturn_analysis",
                )

        request = AgentRequest(
            conversation_id=conversation["conversation_id"],
            command=ConversationCommandRequest(
                user_message=second_message,
                idempotency_key="supervisor-analysis-period-followup",
                expected_head_turn_id=first["turn"]["turn_id"],
            ),
            context=self.context,
        )
        with patch.dict(
            os.environ,
            {"RAG_FEATURE_ENABLED": "0", "ML_FEATURE_ENABLED": "0"},
        ):
            second = await self.orchestrator.dispatch_agent_command(
                request,
                ConcurrentExecutionGate(),
                lambda: None,
                supervisor_planner_factory=Planner,
                supervisor_routing_enabled=True,
            )

        self.assertEqual(second["status"], "SUCCESS")
        self.assertEqual(second["data"]["turn"]["route"], "ANALYSIS")
        self.assertEqual(len(planner_requests), 1)
        previous_analysis = planner_requests[0].previous_analysis
        self.assertIsNotNone(previous_analysis)
        self.assertEqual(previous_analysis.metric_ids, ("room_revenue",))
        self.assertEqual(previous_analysis.period_start.isoformat(), "2026-06-01")
        slots = second["data"]["turn"]["resolved_slots"]
        self.assertEqual(slots["metric_id"], "room_revenue")
        self.assertTrue(slots["is_inherited_metric"])
        self.assertEqual(slots["time_range"]["start"], "2026-03-01")
        self.assertEqual(slots["time_range"]["end_exclusive"], "2026-06-01")
        self.assertEqual(
            self.data_platform.search_contexts[-1]["preferred_metric_ids"],
            ["room_revenue"],
        )

    async def test_unresolved_period_only_followup_never_replays_previous_period(self) -> None:
        """기간 재해석이 비어 있으면 직전 기간으로 같은 분석을 조용히 재실행하지 않는다."""

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        conversation = await self.repo.create_conversation(
            self.user_id,
            "기간 해석 실패",
        )
        first_message = "6월 객실 매출"
        second_message = "3월부터 5월은?"
        self.support.program(
            first_message,
            selected_metric_id="room_revenue",
            selected_metric_ids=["room_revenue"],
            metric_ids=["room_revenue"],
            metric_resolution="selected",
            measurement_source_texts=["객실 매출"],
            period_candidates=[
                {
                    "start": "2026-06-01T00:00:00+09:00",
                    "end_exclusive": "2026-07-01T00:00:00+09:00",
                    "source_text": "6월",
                }
            ],
            period_relationship="single",
            analysis_operation="aggregate",
            intent_candidates=["aggregate"],
            requested_route="ANALYSIS",
            is_elliptical=False,
        )
        first = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": first_message},
            context=self.context,
        )

        unresolved = {
            "metric_resolution": "missing",
            "metric_ids": [],
            "metric_candidates": [],
            "measurement_source_text": None,
            "measurement_source_texts": [],
            "selected_metric_id": None,
            "selected_metric_ids": [],
            "intent_candidates": ["aggregate"],
            "analysis_operation": "aggregate",
            "analysis_time_bucket": None,
            "result_limit": None,
            "dimension_candidates": [],
            "dimension_fields": [],
            "filter_fields": [],
            "period_candidates": [],
            "period_relationship": "single",
            "requested_route": "ANALYSIS",
            "presentation_type": None,
            "is_elliptical": True,
        }
        self.support.program_error(
            second_message,
            ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에 분석할 지표가 포함되지 않았습니다.",
                partial_context=unresolved,
            ),
        )

        second = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": second_message,
                "expected_head_turn_id": str(first["turn"]["turn_id"]),
            },
            context=self.context,
        )

        self.assertEqual("CLARIFICATION_REQUIRED", second["status"])
        self.assertEqual(ErrorCode.CONTEXT_INCOMPLETE.value, second["code"])
        self.assertEqual("BLOCKED", second["turn"]["terminal_status"])
        self.assertIsNone(second["turn"]["resolved_slots"]["time_range"])
        self.assertFalse(
            second["turn"]["resolved_slots"]["is_inherited_period"]
        )
        self.assertEqual(1, len(self.submitted_requests))

    async def test_latest_snapshot_topic_does_not_inherit_previous_range(self) -> None:
        """새 snapshot 지표는 직전 range를 질문에 없던 cutoff로 재해석하지 않는다."""

        conversation = await self.repo.create_conversation(
            self.user_id,
            "시간 mode 전환",
        )
        first_message = "show the governed period metric for August 2025"
        self.support.program(
            first_message,
            selected_metric_id="period_metric",
            metric_ids=["period_metric"],
            period_candidates=[
                {
                    "start": "2025-08-01",
                    "end_exclusive": "2025-09-01",
                    "source_text": "August 2025",
                }
            ],
            time_mode="range",
            is_elliptical=False,
            requested_route="ANALYSIS",
        )
        first = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": first_message},
            context=self.context,
        )

        second_message = "show the current snapshot metric by governed category"
        self.support.program(
            second_message,
            selected_metric_id="current_snapshot_metric",
            metric_ids=["current_snapshot_metric"],
            dimension_fields=[
                {
                    "asset_fqn": "orion_catalog.analytics.current_snapshot",
                    "column": "category_code",
                }
            ],
            period_candidates=[],
            time_mode="latest_snapshot",
            is_elliptical=False,
            requested_route="ANALYSIS",
        )
        second = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": second_message,
                "expected_head_turn_id": str(first["turn"]["turn_id"]),
            },
            context=self.context,
        )

        slots = second["turn"]["resolved_slots"]
        self.assertEqual("current_snapshot_metric", slots["metric_id"])
        self.assertIsNone(slots["time_range"])
        self.assertFalse(slots["is_inherited_period"])
        request = self.submitted_requests[-1]
        self.assertIsNotNone(request.resolved_slots)
        self.assertIsNone(request.resolved_slots.period_start)
        self.assertIsNone(request.resolved_slots.period_end_exclusive)

    async def test_off_topic_message_does_not_inherit_the_previous_analysis(self) -> None:
        """분석과 무관한 발화가 직전 분석을 물려받아 엉뚱한 답을 내지 않는지 검증.

        승인 자산을 찾지 못하면 운영 DataPlatform은 NoEntitledAssetsError로 닫는다. 이때
        생략문 신호도 없으므로 지표를 상속해서는 안 된다. 상속하면 사용자가 묻지 않은
        이전 분석이 그대로 재실행되어, 무관한 질문에 그럴듯한 수치가 답으로 나간다.
        """
        conv = await self.repo.create_conversation(self.user_id, "오프토픽")
        conv_id = conv["conversation_id"]

        first = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head = first["turn"]["turn_id"]
        self.assertEqual("room_revenue", first["turn"]["resolved_slots"]["metric_id"])

        # 운영에서 무관한 질문은 승인 자산 검색 자체가 typed 실패로 닫힌다.
        from app.ports.data_platform import NoEntitledAssetsError

        self.data_platform.search_error = NoEntitledAssetsError("no governed asset matches")

        second = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "오늘 날씨 어때?", "expected_head_turn_id": str(head)},
            context=self.context,
        )

        self.assertEqual("BLOCKED", second["status"])
        self.assertEqual("OUT_OF_SCOPE", second["type"])
        self.assertEqual("OUT_OF_SCOPE", second["turn"]["route"])
        slots = second["turn"]["resolved_slots"]
        self.assertNotIn("metric_id", slots)
        self.assertEqual(
            "NO_APPROVED_CAPABILITY_MATCH",
            slots["scope_rejection"]["reason"],
        )
        self.assertEqual(1, len(self.submitted_requests))


    async def test_interpretation_failure_fails_closed_instead_of_empty_signals(self) -> None:
        """해석 런타임 실패를 빈 신호로 우회하지 않고 typed 실패로 닫는지 검증.

        빈 node1_res로 계속 진행하면 route·상속·기간이 조용히 기본값으로 떨어져
        사용자가 요청하지 않은 분석이 실행된다.
        """
        conv = await self.repo.create_conversation(self.user_id, "런타임 실패")
        conv_id = conv["conversation_id"]

        from app.ports.data_platform import MetadataUnavailableError

        self.data_platform.search_error = MetadataUnavailableError("catalog unavailable")

        result = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )

        self.assertEqual("FAILED", result["status"])
        self.assertEqual(ErrorCode.CONTEXT_SOURCE_FAILED.value, result["code"])
        self.assertTrue(result["retryable"])
        self.assertEqual("CONTACT_SUPPORT", result["required_action"])
        self.assertEqual("FAILED", result["turn"]["command_status"])
        self.assertEqual("FAILED", result["turn"]["terminal_status"])
        self.assertEqual(
            ErrorCode.CONTEXT_SOURCE_FAILED.value,
            result["turn"]["command_error"]["code"],
        )
        self.assertEqual(1, self.repo.conversations[conv_id]["turn_count"])
        # 분석은 실행되지 않아야 한다.
        self.assertEqual([], self.submitted_requests)

    async def test_dimensionless_breakdown_is_blocked_as_incomplete_context(self) -> None:
        """재검토 뒤에도 차원이 없는 breakdown은 분석 Run 없이 수정 요청으로 닫는다."""

        conv = await self.repo.create_conversation(self.user_id, "결과 형태 확인")
        question = "선택 기간의 지표를 분류해서 보여줘"
        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        self.support.program_error(
            question,
            ContextBuildError(
                ContextBuildErrorCode.ANALYSIS_SHAPE_REQUIRED,
                (
                    "분석 결과 형태를 확정하지 못했습니다. 전체 값, 기간별 추이, "
                    "승인된 분류 기준별 값 또는 순위 중 원하는 형태를 질문에 "
                    "명확히 포함해 주세요."
                ),
                partial_context={
                    "metric_ids": ["room_revenue"],
                    "metric_candidates": ["room_revenue"],
                    "metric_resolution": "selected",
                    "measurement_source_texts": ["지표"],
                    "selected_metric_id": "room_revenue",
                    "selected_metric_ids": ["room_revenue"],
                    "analysis_operation": "breakdown",
                    "analysis_time_bucket": None,
                    "dimension_fields": [],
                    "period_candidates": [
                        {
                            "start": "2025-08-01",
                            "end_exclusive": "2025-09-01",
                            "source_text": "선택 기간",
                        }
                    ],
                    "period_relationship": "single",
                    "is_elliptical": False,
                },
            ),
        )

        result = await self.execute_command(
            conversation_id=conv["conversation_id"],
            payload={"user_message": question},
            context=self.context,
        )

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual(ErrorCode.CONTEXT_INCOMPLETE.value, result["code"])
        self.assertEqual("MODIFY_REQUEST", result["required_action"])
        self.assertEqual("BLOCKED", result["turn"]["terminal_status"])
        self.assertEqual(
            ErrorCode.CONTEXT_INCOMPLETE.value,
            result["turn"]["reason_code"],
        )
        self.assertEqual("breakdown", result["turn"]["resolved_slots"]["analysis_operation"])
        self.assertEqual([], self.submitted_requests)

    async def test_ambiguous_interpretation_returns_clarification_options(self) -> None:
        """지표·기간 모호성은 빈 신호로 진행하지 않고 선택지와 함께 재질의로 닫는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "모호성")
        conv_id = conv["conversation_id"]

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        self.data_platform.search_error = ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "질문이 여러 지표로 해석될 수 있습니다.",
            ("객실 매출", "식음 매출"),
            disambiguation_options=(
                DisambiguationOption(
                    label="객실 매출",
                    metric_id="room_revenue",
                    description="객실 매출 분석",
                    clarification_type=ClarificationType.METRIC,
                    value="room_revenue",
                ),
            ),
        )

        result = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "매출 보여줘"},
            context=self.context,
        )

        self.assertEqual("CLARIFICATION_REQUIRED", result["status"])
        self.assertEqual(1, len(result["disambiguation_options"]))
        self.assertEqual("room_revenue", result["disambiguation_options"][0]["metric_id"])
        self.assertEqual([], self.submitted_requests)

    async def test_support_metric_request_is_failed_without_public_metric_fallback(self) -> None:
        """내부 계산 지표 요청을 공개 지표 전체 선택 화면으로 바꾸지 않는다."""
        conv = await self.repo.create_conversation(self.user_id, "내부 지표 요청")
        conv_id = conv["conversation_id"]

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        self.data_platform.search_error = ContextBuildError(
            ContextBuildErrorCode.METRIC_NOT_AVAILABLE,
            "요청한 '예약된 객실 수' 지표는 다른 지표 계산을 위한 내부 값이므로 직접 분석할 수 없습니다.",
        )

        result = await self.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "이번 달 예약된 객실 수를 알려줘"},
            context=self.context,
        )

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual(ErrorCode.METRIC_NOT_AVAILABLE.value, result["code"])
        self.assertEqual("MODIFY_REQUEST", result["required_action"])
        self.assertNotIn("suggestions", result)
        self.assertEqual("COMPLETED", result["turn"]["command_status"])
        self.assertEqual("BLOCKED", result["turn"]["terminal_status"])
        self.assertEqual([], self.submitted_requests)

    async def test_unapproved_dimension_member_is_a_typed_filter_error(self) -> None:
        """승인되지 않은 member는 서비스 장애가 아니라 수정 가능한 조건 오류로 남긴다."""

        conv = await self.repo.create_conversation(self.user_id, "승인 조건 확인")
        from app.services.context.builder import (
            ContextBuildError,
            ContextBuildErrorCode,
        )

        self.data_platform.search_error = ContextBuildError(
            ContextBuildErrorCode.FILTER_VALUE_NOT_FOUND,
            (
                "요청한 Observation Segment 값은 현재 승인된 값과 일치하지 않습니다. "
                "승인된 값: OMEGA, SIGMA."
            ),
        )

        result = await self.execute_command(
            conversation_id=conv["conversation_id"],
            payload={"user_message": "선택 기간 DELTA 구간의 수율을 알려줘"},
            context=self.context,
        )

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual(ErrorCode.FILTER_VALUE_NOT_FOUND.value, result["code"])
        self.assertEqual("MODIFY_REQUEST", result["required_action"])
        self.assertIn("OMEGA, SIGMA", result["message"])
        self.assertEqual("COMPLETED", result["turn"]["command_status"])
        self.assertEqual("BLOCKED", result["turn"]["terminal_status"])
        self.assertEqual(
            ErrorCode.FILTER_VALUE_NOT_FOUND.value,
            result["turn"]["reason_code"],
        )
        self.assertEqual([], self.submitted_requests)

    async def test_future_period_is_failed_with_typed_range_error(self) -> None:
        """데이터 기준일 이후 기간은 서비스 장애가 아니라 수정 가능한 범위 오류로 보존한다."""

        conv = await self.repo.create_conversation(self.user_id, "미래 기간")
        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        self.data_platform.search_error = ContextBuildError(
            ContextBuildErrorCode.OUT_OF_DATA_RANGE,
            "요청 기간은 데이터 기준일보다 이전에 시작해야 합니다.",
        )

        result = await self.execute_command(
            conversation_id=conv["conversation_id"],
            payload={"user_message": "다음 분기 매출을 알려줘"},
            context=self.context,
        )

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual(ErrorCode.OUT_OF_DATA_RANGE.value, result["code"])
        self.assertEqual("MODIFY_REQUEST", result["required_action"])
        self.assertEqual("COMPLETED", result["turn"]["command_status"])
        self.assertEqual("BLOCKED", result["turn"]["terminal_status"])
        self.assertEqual([], self.submitted_requests)

    async def test_out_of_range_turn_resumes_with_absolute_period_without_source_lineage(self) -> None:
        """범위만 고친 다음 Turn은 pending Metric을 쓰되 차단 Turn을 source로 삼지 않는다."""

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        first_message = "이번 달 인식 객실 매출을 보여줘."
        second_message = "2025년 8월로 볼게."
        first_partial = {
            "intent_candidates": ["aggregate"],
            "metric_ids": ["room_revenue"],
            "metric_candidates": ["room_revenue"],
            "metric_resolution": "selected",
            "measurement_source_text": "인식 객실 매출",
            "measurement_source_texts": ["인식 객실 매출"],
            "selected_metric_id": "room_revenue",
            "selected_metric_ids": ["room_revenue"],
            "analysis_operation": "aggregate",
            "result_limit": None,
            "dimension_candidates": [],
            "dimension_fields": [],
            "filter_fields": [],
            "period_candidates": [
                {
                    "start": "2026-08-01",
                    "end_exclusive": "2026-08-18",
                    "source_text": "이번 달",
                }
            ],
            "period_relationship": "single",
            "requested_route": "ANALYSIS",
            "presentation_type": None,
            "is_elliptical": False,
        }
        second_partial = {
            **first_partial,
            "intent_candidates": [],
            "metric_ids": [],
            "metric_candidates": [],
            "metric_resolution": "missing",
            "measurement_source_text": None,
            "measurement_source_texts": [],
            "selected_metric_id": None,
            "selected_metric_ids": [],
            "analysis_operation": None,
            "period_candidates": [
                {
                    "start": "2025-08-01",
                    "end_exclusive": "2025-09-01",
                    "source_text": "2025년 8월",
                }
            ],
            # 실제 모델이 이 flag를 놓쳐도 직전 range-block + 새 절대 기간이라는
            # 서버 소유 증거만으로 pending Metric을 정확히 한 번 복구한다.
            "is_elliptical": False,
        }
        approved_asset = dict(self.data_platform.assets[0])
        self.data_platform.program_search(second_message, [])
        self.data_platform.program_preferred_search(
            second_message,
            ("room_revenue",),
            [approved_asset],
        )
        self.support.program_error(
            first_message,
            ContextBuildError(
                ContextBuildErrorCode.OUT_OF_DATA_RANGE,
                "요청 기간이 승인된 데이터 가용 범위 밖입니다.",
                partial_context=first_partial,
            ),
        )
        self.support.program_error(
            second_message,
            ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에 분석할 지표가 포함되지 않았습니다.",
                partial_context=second_partial,
            ),
        )
        conversation = await self.repo.create_conversation(
            self.user_id,
            "GD-03",
        )
        first = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": first_message},
            context=self.context,
        )
        self.assertEqual("BLOCKED", first["status"])
        self.assertEqual(
            ["인식 객실 매출"],
            first["turn"]["resolved_slots"]["business_terms"],
        )
        self.assertEqual([], self.submitted_requests)

        second = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": second_message,
                "expected_head_turn_id": str(first["turn"]["turn_id"]),
            },
            context=self.context,
        )

        self.assertEqual("SUCCESS", second["status"])
        self.assertEqual([], second["turn"]["source_turn_ids"])
        self.assertEqual(
            first["turn"]["turn_id"],
            second["turn"]["clarifies_turn_id"],
        )
        self.assertEqual("room_revenue", second["turn"]["resolved_slots"]["metric_id"])
        self.assertEqual(
            "2025-08-01",
            second["turn"]["resolved_slots"]["time_range"]["start"],
        )
        self.assertEqual(1, len(self.submitted_requests))
        self.assertIn(
            {"role": "analyst", "product_release_id": TEST_PRODUCT_RELEASE,
             "semantic_release_id": TEST_SEMANTIC_RELEASE,
             "preferred_metric_ids": ["room_revenue"]},
            self.data_platform.search_contexts,
        )

    async def test_preflight_clarification_persists_period_and_filter_for_metric_choice(self) -> None:
        """운영 preflight의 부분 슬롯이 다음 선택에서 같은 분석 요청으로 이어진다."""

        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        question = "8월 비스타 호텔 매출"
        filter_field = {
            "asset_fqn": "serving.analytics_v4_3.hotel_operations_daily",
            "column": "hotel_code",
        }
        options = (
            DisambiguationOption(
                label="Room Revenue",
                metric_id="room_revenue",
                description="객실 운영 매출",
                clarification_type=ClarificationType.METRIC,
                value="room_revenue",
            ),
            DisambiguationOption(
                label="Total Operating Revenue",
                metric_id="total_operating_revenue_krw",
                description="호텔 전체 운영 매출",
                clarification_type=ClarificationType.METRIC,
                value="total_operating_revenue_krw",
            ),
        )
        partial_context = {
            "intent_candidates": ["general"],
            "metric_ids": ["room_revenue", "total_operating_revenue_krw"],
            "metric_candidates": ["room_revenue", "total_operating_revenue_krw"],
            "selected_metric_id": None,
            "dimension_fields": [filter_field],
            "filter_fields": [
                {
                    **filter_field,
                    "operator": "eq",
                    "value_text": "비스타 호텔",
                }
            ],
            "period_candidates": [
                {
                    "start": "2026-08-01T00:00:00+09:00",
                    "end_exclusive": "2026-09-01T00:00:00+09:00",
                    "source_text": "8월",
                }
            ],
            "period_relationship": "single",
            "requested_route": "ANALYSIS",
            "is_elliptical": False,
        }
        self.support.program_error(
            question,
            ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문이 여러 지표로 해석될 수 있습니다.",
                disambiguation_options=options,
                partial_context=partial_context,
            ),
        )
        self.support.program(
            "Total Operating Revenue",
            selected_metric_id="total_operating_revenue_krw",
            metric_ids=["total_operating_revenue_krw"],
            period_candidates=partial_context["period_candidates"],
            period_relationship="single",
            requested_route="ANALYSIS",
            is_elliptical=False,
        )

        conversation = await self.repo.create_conversation(self.user_id, "부분 슬롯 재질의")
        first = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={"user_message": question},
            context=self.context,
        )

        self.assertEqual("CLARIFICATION_REQUIRED", first["status"])
        self.assertEqual([], self.submitted_requests)
        first_slots = first["turn"]["resolved_slots"]
        self.assertEqual("2026-08-01", first_slots["time_range"]["start"])
        self.assertEqual("2026-08-18", first_slots["time_range"]["end_exclusive"])
        self.assertEqual("비스타 호텔", first_slots["user_filters"][0]["value_text"])

        second = await self.execute_command(
            conversation_id=conversation["conversation_id"],
            payload={
                "user_message": "Total Operating Revenue",
                "expected_head_turn_id": str(first["turn"]["turn_id"]),
            },
            context=self.context,
        )

        self.assertEqual("SUCCESS", second["status"])
        resolved = self.submitted_requests[-1].resolved_slots
        self.assertIsNotNone(resolved)
        self.assertEqual("total_operating_revenue_krw", resolved.metric_id)
        self.assertEqual("2026-08-01", resolved.period_start)
        self.assertEqual("2026-08-18", resolved.period_end_exclusive)
        self.assertEqual("비스타 호텔", resolved.user_filters[0]["value_text"])

    async def test_preflight_period_requirement_preserves_typed_cause(self) -> None:
        """사전 해석에서 기간만 빠져도 metric 기본값으로 바꾸지 않는다."""

        conv = await self.repo.create_conversation(self.user_id, "기간 보완")
        from app.services.context.builder import ContextBuildError, ContextBuildErrorCode

        self.data_platform.search_error = ContextBuildError(
            ContextBuildErrorCode.PERIOD_REQUIRED,
            "조회 기간이 필요합니다.",
        )
        result = await self.execute_command(
            conversation_id=conv["conversation_id"],
            payload={"user_message": "객실 매출을 보여줘"},
            context=self.context,
        )

        self.assertEqual("CLARIFICATION_REQUIRED", result["status"])
        self.assertEqual("period", result["clarification_type"])
        self.assertEqual(
            "분석을 시작하려면 분석할 기간을 함께 입력해 주세요.",
            result["message"],
        )
        self.assertEqual("PROVIDE_CONTEXT", result["required_action"])
        self.assertEqual([], self.submitted_requests)
