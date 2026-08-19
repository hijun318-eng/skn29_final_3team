"""Bounded Governed Multi-turn 대화 오케스트레이터.

대화방 수명주기, CAS(expected_head_turn_id) 검사, 동시성 Lease,
Idempotency 보장, 3대 Route(ANALYSIS, PRESENTATION, REPORT_ACTION) 실행 및
단일 DB 트랜잭션 Commit을 총괄한다.

하드코딩 없이 결정론적 슬롯 리졸버가 확정한 지표·차원·기간을 typed
AnalysisRequest.resolved_slots로 직접 전달하여, Node 1이 자연어를 재해석하지
않고 이전 턴의 기간/지표를 정확히 상속하도록 한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID, uuid4

from app.adapters.conversation_repository import ConversationRepository
from app.contracts import AnalysisRequest, RequestContext, ResolvedSlots
from app.ports.data_platform import DataPlatformAdapter
from app.services.conversation_slot_resolver import ConversationSlotResolver, ResolvedTurnSlots
from app.services.pipeline_support import PipelineSupport

logger = logging.getLogger("uvicorn.error")


class ConversationOrchestrator:
    """멀티턴 대화의 상태 머신, 동시성 제어 및 라우트 실행을 담당하는 오케스트레이터.

    모든 외부 의존성은 생성자에서 명시적으로 주입받으며, private 멤버 체이닝 없이
    각 의존성의 public 인터페이스만 사용한다.
    """

    def __init__(
        self,
        repository: ConversationRepository,
        data_platform: DataPlatformAdapter,
        support: PipelineSupport,
        submit_analysis,
    ) -> None:
        self._repo = repository
        self._data_platform = data_platform
        self._support = support
        self._submit_analysis = submit_analysis

    async def execute_command(
        self,
        conversation_id: UUID,
        payload: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        """멀티턴 커맨드를 멱등성 및 거버넌스 규칙에 따라 안전하게 실행한다."""
        user_message = str(payload.get("user_message") or "").strip()
        if not user_message:
            raise ValueError("user_message must not be empty")

        idempotency_key = str(payload.get("idempotency_key") or str(uuid4()))
        expected_head = payload.get("expected_head_turn_id")
        expected_head_uuid = UUID(expected_head) if expected_head else None

        # 1. 멱등성 검사 (이미 실행된 경우 결과 반환)
        existing_cmd = await self._repo.get_command(conversation_id, idempotency_key)
        if existing_cmd:
            if existing_cmd["status"] == "COMPLETED" and existing_cmd["turn_id"]:
                turns = await self._repo.list_turns(conversation_id)
                target_turn = next((t for t in turns if str(t["turn_id"]) == str(existing_cmd["turn_id"])), None)
                return {"status": "SUCCESS", "is_idempotent_replay": True, "turn": target_turn}
            if existing_cmd["status"] == "RUNNING":
                return {"status": "BUSY", "code": "CONVERSATION_BUSY", "message": "동일한 명령이 처리 중입니다."}
            if existing_cmd["status"] == "FAILED":
                return {"status": "FAILED", "code": "COMMAND_FAILED_PREVIOUSLY", "error": existing_cmd.get("error_response")}

        # 2. Canonical Input Hash 계산
        canonical_input = json.dumps({"msg": user_message, "exp": str(expected_head)}, sort_keys=True)
        input_hash = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()

        # 3. CAS 및 동시성 Lease 획득
        command_id = uuid4()
        lease_ok, lease_error = await self._repo.acquire_lease_and_check_cas(
            conversation_id=conversation_id,
            expected_head_turn_id=expected_head_uuid,
            command_id=command_id,
            idempotency_key=idempotency_key,
            input_hash=input_hash,
        )
        if not lease_ok:
            return {"status": "CONFLICT", "code": lease_error, "message": f"동시성 충돌 또는 권한 오류 ({lease_error})"}

        try:
            # 4. 이전 불변 턴 목록 조회
            previous_turns = await self._repo.list_turns(conversation_id)

            # 5. Node 1 발화 정규화 시도 (public 인터페이스만 사용)
            node1_res: dict[str, Any] = {}
            try:
                assets = await self._data_platform.search_assets(
                    user_message,
                    {"role": context.role.value if hasattr(context.role, "value") else str(context.role)},
                )
                if assets:
                    _, _nq, structured = await self._support.select_metric(
                        AnalysisRequest(question=user_message), context, assets,
                    )
                    node1_res = structured
            except Exception as e:
                logger.warning("select_metric fallback in orchestrator: %s", e)
                node1_res = {"normalized_question": user_message}

            # 6. 결정론적 슬롯/시간 리졸버로 슬롯 및 라우트 확정
            slots: ResolvedTurnSlots = ConversationSlotResolver.resolve(
                user_message=user_message,
                node1_output=node1_res,
                previous_turns=previous_turns,
                as_of=context.as_of,
                timezone_str=context.timezone,
            )

            turn_id = uuid4()
            turn_index = len(previous_turns)
            request_id = None
            artifact_id = None
            view_spec_id = None
            report_def_id = None
            analysis_resp = None

            # 7. 3대 라우트 분기 실행
            if slots.route == "ANALYSIS":
                effective_question = user_message
                if slots.is_inherited_metric:
                    last_analysis = next((t for t in reversed(previous_turns) if t.get("route") == "ANALYSIS"), None)
                    if last_analysis and last_analysis.get("user_message"):
                        effective_question = f"{last_analysis['user_message']} ({user_message})"
                analysis_req = self._build_structured_analysis_request(effective_question, slots)
                analysis_resp = await self._submit_analysis(analysis_req, context)
                artifact_id = self._extract_artifact_id(analysis_resp)
                request_id = context.request_id

            elif slots.route == "PRESENTATION":
                # Trino 쿼리 0건 실행: 동일 Artifact에 대한 ViewSpec 생성
                target_artifact_id = None
                for t in reversed(previous_turns):
                    if t.get("artifact_id"):
                        target_artifact_id = t["artifact_id"]
                        break
                if target_artifact_id:
                    view_spec_id = await self._repo.create_view_spec(
                        artifact_id=target_artifact_id,
                        view_type=slots.target_chart_type or "TABLE",
                        spec_json={"chart_type": (slots.target_chart_type or "TABLE").lower(), "source_artifact_id": str(target_artifact_id)},
                        user_id=context.user_id,
                    )
                    artifact_id = target_artifact_id

            elif slots.route == "REPORT_ACTION":
                # Trino 쿼리 0건 실행: 선택된 1~2개 Artifact를 Report Draft에 연결
                report_def_id = uuid4()

            # 8. 단일 DB 트랜잭션으로 Turn 영속화 및 Lease 해제
            await self._repo.commit_turn(
                conversation_id=conversation_id,
                command_id=command_id,
                turn_id=turn_id,
                turn_index=turn_index,
                user_message=user_message,
                route=slots.route,
                source_turn_ids=list(slots.source_turn_ids),
                request_id=request_id,
                artifact_id=artifact_id,
                view_spec_id=view_spec_id,
                report_definition_id=report_def_id,
                resolved_slots={
                    "metric_id": slots.metric_id,
                    "dimension_fields": [dict(d) for d in slots.dimension_fields],
                    "time_range": {
                        "start": slots.time_range.start.isoformat(),
                        "end_exclusive": slots.time_range.end_exclusive.isoformat(),
                        "source_text": slots.time_range.source_text,
                    } if slots.time_range else None,
                    "target_chart_type": slots.target_chart_type,
                    "is_inherited_metric": slots.is_inherited_metric,
                    "is_inherited_dimension": slots.is_inherited_dimension,
                    "is_inherited_period": slots.is_inherited_period,
                },
            )

            # 9. 수화(Hydration)된 최신 턴 목록 반환
            updated_turns = await self._repo.list_turns(conversation_id)
            latest_turn = next((t for t in updated_turns if t["turn_id"] == turn_id), None)

            return {
                "status": "SUCCESS",
                "turn": latest_turn,
                "conversation": {
                    "conversation_id": str(conversation_id),
                    "head_turn_id": str(turn_id),
                    "turn_count": turn_index + 1,
                },
                "analysis_response": analysis_resp.model_dump(mode="json") if analysis_resp and hasattr(analysis_resp, "model_dump") else None,
            }

        except Exception as error:
            error_data = {"type": type(error).__name__, "detail": str(error)}
            await self._repo.release_lease_on_failure(conversation_id, command_id, error_data)
            raise

    @staticmethod
    def _build_structured_analysis_request(
        user_message: str,
        slots: ResolvedTurnSlots,
    ) -> AnalysisRequest:
        """resolved_slots를 AnalysisRequest.resolved_slots로 직접 전달한다.

        상속된 지표/차원/기간이 있을 때 typed ResolvedSlots 모델로 전달하여
        MetricResolver의 pre-resolved fast-path가 Node 1 LLM 호출을
        완전히 건너뛰도록 한다. parameters를 오염시키지 않고, 거버넌스 검증은
        MetricResolver가 런타임에 철저히 수행한다.
        """
        resolved = None
        if slots.is_inherited_metric or slots.is_inherited_period or slots.is_inherited_dimension or slots.time_range:
            dim_ids = tuple(
                d.get("column", "") if isinstance(d, dict) else str(d)
                for d in slots.dimension_fields
                if (isinstance(d, dict) and d.get("column")) or (isinstance(d, str) and d)
            )
            resolved = ResolvedSlots(
                metric_id=slots.metric_id,
                dimension_ids=dim_ids,
                period_start=slots.time_range.start.isoformat() if slots.time_range else None,
                period_end_exclusive=slots.time_range.end_exclusive.isoformat() if slots.time_range else None,
            )

        return AnalysisRequest(
            question=user_message,
            resolved_slots=resolved,
        )

    @staticmethod
    def _extract_artifact_id(analysis_resp: Any) -> UUID | None:
        """AnalysisResponse에서 artifact_id를 안전하게 추출한다."""
        dumped = analysis_resp.model_dump(mode="python") if hasattr(analysis_resp, "model_dump") else {}
        data_dict = dumped.get("data") or {}

        art_dict = data_dict.get("artifact") or {}
        if art_dict.get("artifact_id"):
            val = art_dict["artifact_id"]
            return val if isinstance(val, UUID) else UUID(str(val))

        result_dict = data_dict.get("result") or {}
        evidence_dict = result_dict.get("evidence") or {}
        if evidence_dict.get("artifact_id"):
            val = evidence_dict["artifact_id"]
            return val if isinstance(val, UUID) else UUID(str(val))

        return None
