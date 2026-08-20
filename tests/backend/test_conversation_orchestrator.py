"""Bounded Governed Multi-turn ConversationOrchestrator 테스트.

CAS(expected_head_turn_id) 검사, 동시성 Lease, Idempotency 보장,
3대 Route(ANALYSIS, PRESENTATION, REPORT_ACTION) 실행 및 Fail-closed 검증.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
from app.services.conversation.orchestrator import ConversationOrchestrator


class FakeConversationRepository:
    """ConversationOrchestrator 계약을 만족하는 테스트용 불변/동시성 저장소."""

    def __init__(self) -> None:
        self.conversations: dict[UUID, dict[str, Any]] = {}
        self.turns: dict[UUID, list[dict[str, Any]]] = {}
        self.commands: dict[tuple[UUID, str], dict[str, Any]] = {}
        self.view_specs: dict[UUID, dict[str, Any]] = {}
        self.existing_artifacts: set[UUID] = set()

    async def get_conversation(self, conversation_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        conv = self.conversations.get(conversation_id)
        if conv and conv.get("owner_user_id") == user_id:
            return conv
        return None

    async def create_conversation(self, user_id: UUID, title: str) -> dict[str, Any]:
        conv_id = uuid4()
        conv = {
            "conversation_id": conv_id,
            "owner_user_id": user_id,
            "title": title,
            "status": "ACTIVE",
            "head_turn_id": None,
            "turn_count": 0,
            "active_command_id": None,
            "lease_expires_at": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        self.conversations[conv_id] = conv
        self.turns[conv_id] = []
        return conv

    async def list_turns(self, conversation_id: UUID) -> list[dict[str, Any]]:
        return list(self.turns.get(conversation_id, []))

    async def get_command(self, conversation_id: UUID, idempotency_key: str) -> dict[str, Any] | None:
        return self.commands.get((conversation_id, idempotency_key))

    async def acquire_lease_and_check_cas(
        self,
        conversation_id: UUID,
        expected_head_turn_id: UUID | None,
        command_id: UUID,
        idempotency_key: str,
        input_hash: str,
        lease_seconds: int = 60,
    ) -> tuple[bool, str | None]:
        conv = self.conversations.get(conversation_id)
        if not conv:
            return False, "CONVERSATION_NOT_FOUND"
        if conv["status"] == "ARCHIVED":
            return False, "CONVERSATION_ARCHIVED"

        # CAS check
        if expected_head_turn_id is not None and conv["head_turn_id"] != expected_head_turn_id:
            return False, "CONVERSATION_CONFLICT"

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
    ) -> None:
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
            "report_definition_id": report_definition_id,
            "resolved_slots": resolved_slots,
            "created_at": datetime.now(timezone.utc),
        }
        self.turns[conversation_id].append(turn)

        conv = self.conversations[conversation_id]
        conv["head_turn_id"] = turn_id
        conv["turn_count"] += 1
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
    ) -> None:
        """운영 저장소와 동일하게 typed 실패 turn과 command를 원자적으로 남긴다."""

        turn = {
            "turn_id": turn_id,
            "conversation_id": conversation_id,
            "turn_index": turn_index,
            "user_message": user_message,
            "route": "ANALYSIS",
            "source_turn_ids": [],
            "request_id": None,
            "artifact_id": None,
            "view_spec_id": None,
            "report_definition_id": None,
            "resolved_slots": {},
            "command_status": "FAILED",
            "command_error": error_response,
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
    ) -> UUID:
        if artifact_id not in self.existing_artifacts:
            raise ValueError(f"Referenced artifact {artifact_id} does not exist.")

        view_spec_id = uuid4()
        self.view_specs[view_spec_id] = {
            "view_spec_id": view_spec_id,
            "artifact_id": artifact_id,
            "view_type": view_type,
            "spec_json": spec_json,
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
        self.queries: list[str] = []
        # 특정 발화에서 운영과 동일한 typed 실패를 재현하기 위한 프로그래밍 지점.
        self.search_error: Exception | None = None

    def program_search(self, query: str, assets: list[dict[str, Any]]) -> None:
        """특정 검색어에 반환할 승인 자산을 등록한다."""

        self.assets_by_query[query] = list(assets)

    async def search_assets(self, query: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        self.queries.append(query)
        if self.search_error is not None:
            raise self.search_error
        if query in self.assets_by_query:
            return list(self.assets_by_query[query])
        return list(self.assets)


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
        # 발화별로 Node1이 낼 신호(route, presentation_type 등)를 프로그래밍한다. 운영에서
        # route는 Node1 응답 계약으로만 전달되므로, 테스트도 문장이 아니라 이 신호로 라우팅한다.
        self.signals_by_message: dict[str, dict[str, Any]] = {}
        self.errors_by_message: dict[str, Exception] = {}

    def program(self, message: str, **signals: Any) -> None:
        """특정 발화에 대해 Node1이 반환할 신호를 등록한다."""
        self.signals_by_message[message] = dict(signals)

    def program_error(self, message: str, error: Exception) -> None:
        self.errors_by_message[message] = error

    async def select_metric(self, req: AnalysisRequest, context: RequestContext, assets: list[dict[str, Any]]):
        self.questions.append(req.question)
        if req.question in self.errors_by_message:
            raise self.errors_by_message[req.question]
        structured = dict(self.structured)
        structured.update(self.signals_by_message.get(req.question, {}))
        return assets, req.question, structured


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

        async def mock_submit_analysis(req: AnalysisRequest, ctx: RequestContext):
            self.submitted_requests.append(req)
            artifact_id = uuid4()
            self.repo.existing_artifacts.add(artifact_id)
            self.report_repo.register_artifact(
                artifact_id,
                title=f"{req.question[:30]} 분석",
                narrative=f"{req.question}에 대한 데이터 분석 결과입니다.",
            )
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
            report_repository_factory=lambda user_id, is_admin: self.report_repo,
        )

    async def test_analysis_route_passes_untampered_question_and_slots(self) -> None:
        """ANALYSIS 라우트 실행 시 질문 문자열을 변조하지 않고 원본 발화와 typed slots를 전달하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "매출 분석")
        conv_id = conv["conversation_id"]

        result = await self.orchestrator.execute_command(
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

    async def test_presentation_route_creates_view_spec_with_zero_queries(self) -> None:
        """PRESENTATION 라우트 실행 시 추가 쿼리 없이 선행 아티팩트의 ViewSpec을 생성하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "시각화 전환")
        conv_id = conv["conversation_id"]

        # Turn 1: ANALYSIS
        res1 = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head1 = res1["turn"]["turn_id"]
        art_id = res1["turn"]["artifact_id"]

        # Turn 2: PRESENTATION ("표로 보여줘")
        res2 = await self.orchestrator.execute_command(
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
        # submit_analysis는 Turn 1에서만 1회 호출됨
        self.assertEqual(len(self.submitted_requests), 1)

    async def test_idempotent_command_replay(self) -> None:
        """동일한 idempotency_key로 요청 시 중복 실행 없이 이전 결과를 그대로 반환하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "멱등성 테스트")
        conv_id = conv["conversation_id"]

        idemp_key = "idemp-unique-123"
        res1 = await self.orchestrator.execute_command(
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
        res2 = await self.orchestrator.execute_command(
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

    async def test_cas_conflict_detection(self) -> None:
        """expected_head_turn_id 불일치 시 409 CONFLICT를 반환하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "CAS 테스트")
        conv_id = conv["conversation_id"]

        # Turn 1
        res1 = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출"},
            context=self.context,
        )

        # Stale CAS attempt (expected_head is wrong)
        wrong_head = uuid4()
        res_conflict = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "다음 달은?",
                "expected_head_turn_id": str(wrong_head),
            },
            context=self.context,
        )
        self.assertEqual(res_conflict["status"], "CONFLICT")
        self.assertEqual(res_conflict["code"], "CONVERSATION_CONFLICT")

    async def test_fail_closed_without_antecedent_artifact(self) -> None:
        """선행 분석 결과가 없을 때 시각화 전환 요청이 Fail-closed 원칙에 따라 거부되는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "선행결과 없음")
        conv_id = conv["conversation_id"]

        with self.assertRaises(ValueError):
            await self.orchestrator.execute_command(
                conversation_id=conv_id,
                payload={"user_message": "차트로 나타내줘"},
                context=self.context,
            )

    async def test_report_action_creates_real_draft_report_and_blocks_with_zero_queries(self) -> None:
        """REPORT_ACTION 요청 시 Trino 쿼리 재실행(0건) 없이 PostgresReportRepository에 실제 draft 보고서와 artifact 블록들을 생성하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "2025년 8월 매출 분석")
        conv_id = conv["conversation_id"]

        # Turn 1: ANALYSIS ("2025년 8월 객실 매출 보여줘")
        res1 = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head1 = res1["turn"]["turn_id"]
        art_id = res1["turn"]["artifact_id"]
        self.assertEqual(len(self.submitted_requests), 1)

        # Turn 2: REPORT_ACTION ("현재 내용을 보고서에 담아줘")
        res2 = await self.orchestrator.execute_command(
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
        self.assertTrue(len(draft.blocks) >= 2)

        block_types = [b.type for b in draft.blocks]
        self.assertIn(BlockType.TEXT, block_types)
        self.assertIn(BlockType.CHART, block_types)
        self.assertIn(BlockType.TABLE, block_types)

        text_block = next(b for b in draft.blocks if b.type == BlockType.TEXT)
        self.assertIn("데이터 분석 결과", text_block.content)

        chart_block = next(b for b in draft.blocks if b.type == BlockType.CHART)
        self.assertEqual(chart_block.artifact_id, str(art_id))
        self.assertEqual(chart_block.query_id, "trino-query-123")

        table_block = next(b for b in draft.blocks if b.type == BlockType.TABLE)
        self.assertEqual(table_block.artifact_id, str(art_id))
        self.assertEqual(table_block.query_id, "trino-query-123")

    async def test_report_action_updates_existing_draft_in_subsequent_report_actions(self) -> None:
        """대화방에 이미 연결된 draft 보고서가 있을 때 후속 REPORT_ACTION이 새 uuid 생성 대신 기존 draft blocks를 원자적으로 갱신하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "연속 보고서 추가")
        conv_id = conv["conversation_id"]

        # Turn 1: ANALYSIS 1
        res1 = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head1 = res1["turn"]["turn_id"]

        # Turn 2: REPORT_ACTION 1
        res2 = await self.orchestrator.execute_command(
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
        res3 = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": "2025년 7월 식음 매출 보여줘",
                "expected_head_turn_id": str(head2),
            },
            context=self.context,
        )
        head3 = res3["turn"]["turn_id"]

        # Turn 4: REPORT_ACTION 2 ("이 내용도 보고서에 담아줘")
        res4 = await self.orchestrator.execute_command(
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
        self.assertTrue(len(draft.blocks) >= 4)

    async def test_report_action_fails_closed_when_artifact_lookup_fails(self) -> None:
        """보고서 저장소에서 아티팩트 조회가 실패할 때 에러를 발생시키고 Lease를 안전하게 해제하는지 검증."""
        conv = await self.repo.create_conversation(self.user_id, "조회 실패 테스트")
        conv_id = conv["conversation_id"]

        # Turn 1: ANALYSIS
        res1 = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head1 = res1["turn"]["turn_id"]
        art_id = res1["turn"]["artifact_id"]

        # Remove artifact from report_repo to simulate missing artifact
        del self.report_repo.artifacts[str(art_id)]

        with self.assertRaises(KeyError):
            await self.orchestrator.execute_command(
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
            report_repository_factory=lambda user_id, is_admin: self.report_repo,
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
        first = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": first_message},
            context=self.context,
        )
        head = first["turn"]["turn_id"]

        # 새 주제 원문 검색은 비지만, 직전 지표를 붙인 보조 검색에서는 자산을 찾는 상황.
        self.data_platform.assets = []
        self.data_platform.program_search(second_message, [])
        self.data_platform.program_search(f"room_revenue {second_message}", [room_asset])
        self.support.program(
            second_message,
            selected_metric_id=None,
            metric_ids=["fnb_revenue"],
            is_elliptical=False,
            requested_route="ANALYSIS",
        )

        second = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={
                "user_message": second_message,
                "expected_head_turn_id": str(head),
            },
            context=self.context,
        )

        self.assertEqual(
            self.data_platform.queries[-2:],
            [second_message, f"room_revenue {second_message}"],
        )
        self.assertEqual(self.support.questions[-1], second_message)
        slots = second["turn"]["resolved_slots"]
        self.assertIsNone(slots["metric_id"])
        self.assertFalse(slots["is_inherited_metric"])
        self.assertTrue(slots["is_inherited_period"])

    async def test_off_topic_message_does_not_inherit_the_previous_analysis(self) -> None:
        """분석과 무관한 발화가 직전 분석을 물려받아 엉뚱한 답을 내지 않는지 검증.

        승인 자산을 찾지 못하면 운영 DataPlatform은 NoEntitledAssetsError로 닫는다. 이때
        생략문 신호도 없으므로 지표를 상속해서는 안 된다. 상속하면 사용자가 묻지 않은
        이전 분석이 그대로 재실행되어, 무관한 질문에 그럴듯한 수치가 답으로 나간다.
        """
        conv = await self.repo.create_conversation(self.user_id, "오프토픽")
        conv_id = conv["conversation_id"]

        first = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )
        head = first["turn"]["turn_id"]
        self.assertEqual("room_revenue", first["turn"]["resolved_slots"]["metric_id"])

        # 운영에서 무관한 질문은 승인 자산 검색 자체가 typed 실패로 닫힌다.
        from app.ports.data_platform import NoEntitledAssetsError

        self.data_platform.search_error = NoEntitledAssetsError("no governed asset matches")

        second = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "오늘 날씨 어때?", "expected_head_turn_id": str(head)},
            context=self.context,
        )

        slots = second["turn"]["resolved_slots"]
        self.assertIsNone(slots["metric_id"])
        self.assertFalse(slots["is_inherited_metric"])
        self.assertFalse(slots["is_inherited_dimension"])


    async def test_interpretation_failure_fails_closed_instead_of_empty_signals(self) -> None:
        """해석 런타임 실패를 빈 신호로 우회하지 않고 typed 실패로 닫는지 검증.

        빈 node1_res로 계속 진행하면 route·상속·기간이 조용히 기본값으로 떨어져
        사용자가 요청하지 않은 분석이 실행된다.
        """
        conv = await self.repo.create_conversation(self.user_id, "런타임 실패")
        conv_id = conv["conversation_id"]

        from app.ports.data_platform import MetadataUnavailableError

        self.data_platform.search_error = MetadataUnavailableError("catalog unavailable")

        result = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "2025년 8월 객실 매출 보여줘"},
            context=self.context,
        )

        self.assertEqual("FAILED", result["status"])
        self.assertEqual(ErrorCode.CONTEXT_SOURCE_FAILED.value, result["code"])
        self.assertTrue(result["retryable"])
        self.assertEqual("CONTACT_SUPPORT", result["required_action"])
        self.assertEqual("FAILED", result["turn"]["command_status"])
        self.assertEqual(
            ErrorCode.CONTEXT_SOURCE_FAILED.value,
            result["turn"]["command_error"]["code"],
        )
        self.assertEqual(1, self.repo.conversations[conv_id]["turn_count"])
        # 분석은 실행되지 않아야 한다.
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

        result = await self.orchestrator.execute_command(
            conversation_id=conv_id,
            payload={"user_message": "매출 보여줘"},
            context=self.context,
        )

        self.assertEqual("CLARIFICATION_REQUIRED", result["status"])
        self.assertEqual(1, len(result["disambiguation_options"]))
        self.assertEqual("room_revenue", result["disambiguation_options"][0]["metric_id"])
        self.assertEqual([], self.submitted_requests)

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
        first = await self.orchestrator.execute_command(
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

        second = await self.orchestrator.execute_command(
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
        result = await self.orchestrator.execute_command(
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
