"""멀티턴 대화의 수명주기 및 3대 라우트 실행을 총괄하는 Bounded Governed 오케스트레이터 모듈.

[핵심 목적]
대화방(Conversation) 생성부터 멀티턴 질의 실행, 동시성 제어(CAS & Lease), 멱등성 보장,
3대 라우트(ANALYSIS, PRESENTATION, REPORT_ACTION) 분기 실행, 그리고 단일 트랜잭션 DB 커밋까지
멀티턴 시스템의 전체 흐름을 일관되고 안전하게 조정합니다.

[주요 아키텍처 원칙]
1. 동시성 제어 (CAS Lease): 동일 대화방에 동시에 들어오는 요청에 대해 `expected_head_turn_id`를 검사하고
   DB 분산 Lease를 획득하여 경합 및 데이터 오염을 방지합니다.
2. 멱등성 (Idempotency): 클라이언트가 동일한 `idempotency_key`로 재요청할 경우 기존 완료 결과를 즉시 재생(Replay)합니다.
3. 결정론적 슬롯 전달: 슬롯 리졸버(`ConversationSlotResolver`)가 확정한 지표/차원/기간을 typed
   `AnalysisRequest.resolved_slots`로 하류 엔진에 전달하여, Node 1 LLM의 불필요한 재해석이나 환각을 차단합니다.
4. 비용 최적화 (Zero-Query Presentation): 차트/테이블 뷰 전환(PRESENTATION)이나 보고서 초안 추가(REPORT_ACTION)는
   Trino 원천 쿼리를 0건 실행하고 기존 Artifact 메타데이터만 재활용합니다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Callable
from uuid import UUID, uuid4

from app.adapters.conversation_repository import ConversationRepository
from app.authorization import has_capability
from app.contracts import AnalysisRequest, AnalysisStatus, Capability, ErrorCode, RequestContext, ResolvedSlots
from app.ports.data_platform import DataPlatformAdapter, NoEntitledAssetsError
from app.services.context.builder import ContextBuildError, ContextBuildErrorCode
from app.services.context.model_signals import client_action_signals
from app.services.conversation.analysis_request import (
    build_structured_analysis_request,
    extract_artifact_id,
)
from app.services.conversation.report_actions import execute_report_action
from app.services.conversation.slot_resolver import ConversationSlotResolver, ResolvedTurnSlots
from app.services.analysis.pipeline_support import PipelineSupport

logger = logging.getLogger("uvicorn.error")


def _clarification_resolved_by_inheritance(
    error: ContextBuildError,
    slots: ResolvedTurnSlots,
) -> bool:
    """Node 1이 명시한 생략형 질문만 이전 확정 슬롯으로 명확화가 끝났는지 판정한다.

    지표가 모호하거나 새 질문에 필요한 기간이 없는 상태를 임의로 상속하면 다른 분석을
    실행할 수 있다. 따라서 ``is_elliptical``이 참이고, 누락 원인과 같은 종류의 슬롯을
    ``ConversationSlotResolver``가 실제로 상속한 경우에만 preflight 차단을 해제한다.
    하류 분석 파이프라인은 이 슬롯을 active release와 다시 대조한다.
    """

    partial = getattr(error, "partial_context", None)
    if not isinstance(partial, dict) or not (
        ConversationSlotResolver.is_context_dependent_followup(partial)
    ):
        return False
    if error.code is ContextBuildErrorCode.INVALID_METRIC:
        return (
            partial.get("metric_resolution") == "missing"
            and slots.is_inherited_metric
            and bool(slots.metric_ids)
        )
    if error.code is ContextBuildErrorCode.PERIOD_REQUIRED:
        return (
            not partial.get("period_candidates")
            and slots.is_inherited_period
            and slots.time_range is not None
        )
    return False


class ConversationOrchestrator:
    """멀티턴 대화의 상태 머신, 동시성 제어 및 라우트 실행을 담당하는 오케스트레이터."""

    def __init__(
        self,
        repository: ConversationRepository,
        data_platform: DataPlatformAdapter,
        support: PipelineSupport,
        submit_analysis: Callable[..., Any],
        report_repository_factory: Callable[[UUID, bool], Any] | Any | None = None,
        analysis_repository_factory: Callable[[UUID], Any] | Any | None = None,
    ) -> None:
        """대화 오케스트레이터의 필수 의존성을 주입받아 초기화합니다.

        Args:
            repository: 대화 세션 및 턴을 영속화하는 PostgreSQL 저장소 어댑터
            data_platform: DataHub 메타데이터 및 Trino 쿼리 플랫폼 어댑터
            support: 분석 파이프라인 서포트 파사드 (지표 선택 등)
            submit_analysis: 단일 턴 분석 파이프라인 실행 진입점 함수
            report_repository_factory: 사용자별 권한이 적용된 ReportRepository 팩토리
            analysis_repository_factory: 사용자별 권한이 적용된 AnalysisRepository 팩토리
        """
        self._repo = repository
        self._data_platform = data_platform
        self._support = support
        self._submit_analysis = submit_analysis
        self._report_repository_factory = report_repository_factory
        self._analysis_repository_factory = analysis_repository_factory

    def _get_analysis_repository(self, context: RequestContext) -> Any:
        """요청 사용자의 권한과 격리 범위가 적용된 AnalysisRepository 인스턴스를 반환합니다."""
        if self._analysis_repository_factory is not None:
            if callable(self._analysis_repository_factory):
                return self._analysis_repository_factory(context.user_id)
            return self._analysis_repository_factory
        database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
        if not database_url:
            return None
        from app.adapters.analysis_repository import PostgresAnalysisRepository

        return PostgresAnalysisRepository(
            database_url=database_url,
            owner_id=context.user_id,
            session_factory=self._repo._sessionmaker,
        )

    def _get_report_repository(self, context: RequestContext) -> Any:
        """요청 사용자의 권한과 격리 범위가 적용된 ReportRepository 인스턴스를 반환합니다."""
        if self._report_repository_factory is not None:
            if callable(self._report_repository_factory):
                is_admin = has_capability(context.role, Capability.MANAGE_REPORT)
                return self._report_repository_factory(context.user_id, is_admin)
            return self._report_repository_factory
        from app.adapters.report_repository import PostgresReportRepository

        database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
        if not database_url:
            raise ValueError("Report 저장소(APP_RUNTIME_DATABASE_URL)가 구성되지 않았습니다.")
        is_admin = has_capability(context.role, Capability.MANAGE_REPORT)
        return PostgresReportRepository(
            database_url=database_url,
            owner_id=context.user_id,
            manage_all=is_admin,
            session_factory=self._repo._sessionmaker,
        )

    async def execute_command(
        self,
        conversation_id: UUID,
        payload: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        """사용자의 멀티턴 명령을 멱등성 및 거버넌스 규칙에 따라 안전하게 실행합니다.

        [실행 단계]
        1. 멱등성 검사 (Idempotency Replay): 동일 idempotency_key가 이미 완료된 경우 기존 턴 반환
        2. CAS 및 Lease 획득: expected_head_turn_id 불일치 시 충돌(CONFLICT) 반환
        3. 이전 불변 턴 목록 조회
        4. Node 1 사전 발화 정규화 (지표/자산 검색)
        5. 슬롯/라우트 결정론적 해석 (`ConversationSlotResolver.resolve`)
        6. 3대 라우트 분기 실행:
           - ANALYSIS: 원천 데이터 쿼리 및 분석 파이프라인 호출
           - PRESENTATION: 동일 결과에 대한 ViewSpec 생성 (쿼리 0건)
           - REPORT_ACTION: 분석 결과를 리포트 초안 블록으로 조립 (쿼리 0건)
        7. 모호성 해소(Disambiguation) 필요 여부 판별
        8. 단일 트랜잭션 DB 커밋 및 Lease 해제
        9. 수화(Hydration)된 최신 상태 응답 반환

        Args:
            conversation_id: 대상 대화방 UUID
            payload: 사용자 요청 페이로드 (user_message, idempotency_key, expected_head_turn_id 등)
            context: 요청 컨텍스트 (user_id, role, as_of, timezone 등)

        Returns:
            대화 턴 실행 결과 딕셔너리 (status, turn, conversation, disambiguation_options 등)
        """
        user_message = str(payload.get("user_message") or "").strip()
        if not user_message:
            raise ValueError("user_message must not be empty")

        idempotency_key = str(payload.get("idempotency_key") or str(uuid4()))
        expected_head = payload.get("expected_head_turn_id")
        expected_head_uuid = UUID(expected_head) if expected_head else None

        # 1. 멱등성 검사 (이미 실행된 커맨드인 경우 즉시 캐시 결과 반환)
        existing_cmd = await self._repo.get_command(conversation_id, idempotency_key)
        if existing_cmd:
            if existing_cmd["status"] == "COMPLETED" and existing_cmd["turn_id"]:
                turns = await self._repo.list_turns(conversation_id)
                target_turn = next((t for t in turns if str(t["turn_id"]) == str(existing_cmd["turn_id"])), None)
                return {"status": "SUCCESS", "is_idempotent_replay": True, "turn": target_turn}
            if existing_cmd["status"] == "RUNNING":
                return {"status": "BUSY", "code": "CONVERSATION_BUSY", "message": "동일한 명령이 처리 중입니다."}
            if existing_cmd["status"] == "FAILED":
                error = existing_cmd.get("error_response") or {}
                turns = await self._repo.list_turns(conversation_id)
                target_turn = next(
                    (
                        turn
                        for turn in turns
                        if str(turn["turn_id"]) == str(existing_cmd.get("turn_id"))
                    ),
                    None,
                )
                return {
                    "status": "FAILED",
                    "code": error.get("code", ErrorCode.CONTEXT_SOURCE_FAILED.value),
                    "message": error.get(
                        "message",
                        "질문 해석에 필요한 데이터 카탈로그를 검증하지 못했습니다.",
                    ),
                    "retryable": bool(error.get("retryable", True)),
                    "required_action": error.get("required_action", "CONTACT_SUPPORT"),
                    "turn": target_turn,
                    "is_idempotent_replay": True,
                }

        # 2. 정규 입력 해시(Canonical Input Hash) 생성
        canonical_input = json.dumps({"msg": user_message, "exp": str(expected_head)}, sort_keys=True)
        input_hash = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()

        # 3. CAS(Compare-And-Swap) 검사 및 동시성 Lease 획득
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

            # 5. Node 1 사전 발화 정규화 (DataHub 자산 검색)
            node1_res: dict[str, Any] = {}
            preflight_clarification: ContextBuildError | None = None
            try:
                # 1차: user_message 원문으로 검색
                search_context = {
                    "role": (
                        context.role.value
                        if hasattr(context.role, "value")
                        else str(context.role)
                    )
                }
                try:
                    candidate_set = (
                        await self._data_platform.search_asset_candidates(
                            user_message,
                            search_context,
                        )
                    )
                    assets = list(candidate_set.assets)
                except NoEntitledAssetsError:
                    # 검색 결과가 없거나 현재 role에 보이는 후보가 없으면 같은 principal로만
                    # 직전 승인 Metric을 결합해 recall을 재시도한다. metadata 장애는 전파한다.
                    assets = []

                # 2차: 자산 미발견 시 이전 분석 지표를 typed 후보 우선순위로 전달한다.
                # 질문 문자열에 Metric ID를 붙이면 DataHub lexical rank가 다른 revenue 자산까지
                # 끌어와 bounded scope를 깨뜨리고, Node 1의 생략문 판정 증거도 오염된다.
                if not assets:
                    last_analysis_metric_ids = next(
                        (
                            tuple(
                                item
                                for item in (
                                    t.get("resolved_slots", {}).get("metric_ids")
                                    or (
                                        [t.get("resolved_slots", {}).get("metric_id")]
                                        if t.get("resolved_slots", {}).get("metric_id")
                                        else []
                                    )
                                )
                                if isinstance(item, str) and item
                            )
                            for t in reversed(previous_turns)
                            if ConversationSlotResolver.is_resolved_analysis_turn(t)
                            and (
                                t.get("resolved_slots", {}).get("metric_id")
                                or t.get("resolved_slots", {}).get("metric_ids")
                            )
                        ),
                        (),
                    )
                    if last_analysis_metric_ids:
                        candidate_set = await self._data_platform.search_asset_candidates(
                            user_message,
                            {
                                **search_context,
                                "preferred_metric_ids": list(last_analysis_metric_ids),
                            },
                        )
                        assets = list(candidate_set.assets)

                if not assets:
                    raise NoEntitledAssetsError(
                        "conversation preflight found no entitled candidate"
                    )

                if assets:
                    preflight_slots = None
                    last_resolved_analysis = next(
                        (
                            turn
                            for turn in reversed(previous_turns)
                            if ConversationSlotResolver.is_resolved_analysis_turn(
                                turn
                            )
                        ),
                        None,
                    )
                    last_analysis_slots = (
                        last_resolved_analysis.get("resolved_slots", {})
                        if last_resolved_analysis
                        else {}
                    )
                    last_time = last_analysis_slots.get("time_range")
                    comparison_time = last_analysis_slots.get(
                        "comparison_time_range"
                    )
                    dimension_ids = tuple(
                        str(item["column"])
                        for item in last_analysis_slots.get(
                            "dimension_fields", ()
                        )
                        if isinstance(item, dict) and item.get("column")
                    )
                    if last_analysis_slots:
                        preflight_slots = ResolvedSlots(
                            dimension_ids=dimension_ids,
                            period_start=(
                                last_time.get("start")
                                if isinstance(last_time, dict)
                                else None
                            ),
                            period_end_exclusive=(
                                last_time.get("end_exclusive")
                                if isinstance(last_time, dict)
                                else None
                            ),
                            comparison_period_start=(
                                comparison_time.get("start")
                                if isinstance(comparison_time, dict)
                                else None
                            ),
                            comparison_period_end_exclusive=(
                                comparison_time.get("end_exclusive")
                                if isinstance(comparison_time, dict)
                                else None
                            ),
                            analysis_operation=last_analysis_slots.get(
                                "analysis_operation"
                            ),
                            result_limit=last_analysis_slots.get("result_limit"),
                        )
                    # 직전 Metric 결합은 짧은 후속 발화의 자산 recall을 높이는 검색 전용 힌트다.
                    # 의도·생략 여부·새 주제 판정은 사용자가 실제로 쓴 원문을 기준으로 해야
                    # 하므로 모델 입력까지 보강 문자열로 바꾸지 않는다.
                    _, _nq, structured = await self._support.select_metric(
                        AnalysisRequest(question=user_message, resolved_slots=preflight_slots), context, assets,
                    )
                    node1_res = structured
            except NoEntitledAssetsError:
                # 이 사전 검색은 역할만으로 좁힌 근사치이고, 권위 있는 자산 탐색은 분석
                # 파이프라인이 전체 Context로 다시 수행한다. 여기서 못 찾았다고 닫으면
                # 파이프라인이라면 답했을 질문까지 막으므로, 신호 없이 ANALYSIS로 진행해
                # 파이프라인이 typed 결과(DATA_ASSET_NOT_FOUND 등)를 내도록 맡긴다.
                node1_res = {}
            except ContextBuildError as error:
                # 지표·기간이 여러 갈래로 해석되는 상태다. 빈 신호로 계속 진행하면 같은
                # 모호성을 파이프라인에서 다시 만난다. 운영 resolver가 함께 반환한 확정
                # 슬롯은 clarification turn에 저장해 다음 선택이 같은 요청을 완결하게 한다.
                if error.code in {
                    ContextBuildErrorCode.METRIC_NOT_AVAILABLE,
                    ContextBuildErrorCode.OUT_OF_DATA_RANGE,
                }:
                    public_code = (
                        ErrorCode.METRIC_NOT_AVAILABLE
                        if error.code is ContextBuildErrorCode.METRIC_NOT_AVAILABLE
                        else ErrorCode.OUT_OF_DATA_RANGE
                    )
                    public_error = {
                        "status": "FAILED",
                        "code": public_code.value,
                        "message": str(error),
                        "retryable": False,
                        "required_action": "MODIFY_REQUEST",
                    }
                    turn_id = uuid4()
                    await self._repo.commit_failed_turn(
                        conversation_id,
                        command_id,
                        turn_id,
                        len(previous_turns),
                        user_message,
                        {
                            "type": type(error).__name__,
                            "detail": str(error),
                            **public_error,
                        },
                    )
                    updated_turns = await self._repo.list_turns(conversation_id)
                    return {
                        **public_error,
                        "turn": next(
                            turn for turn in updated_turns if turn["turn_id"] == turn_id
                        ),
                    }
                clarification_type = (
                    "period"
                    if error.code is ContextBuildErrorCode.PERIOD_REQUIRED
                    else "metric"
                )
                public_message = (
                    "분석을 시작하려면 분석할 기간을 함께 입력해 주세요."
                    if error.code is ContextBuildErrorCode.PERIOD_REQUIRED
                    else "분석할 지표를 확정하지 못했습니다. 하나의 지표를 선택하거나 질문에 포함해 주세요."
                )
                partial_context = getattr(error, "partial_context", None)
                if (
                    error.code in {
                        ContextBuildErrorCode.INVALID_METRIC,
                        ContextBuildErrorCode.PERIOD_REQUIRED,
                    }
                    and isinstance(partial_context, dict)
                ):
                    node1_res = dict(partial_context)
                    preflight_clarification = error
                else:
                    # Legacy/test producers without partial typed slots cannot be
                    # persisted safely; retain the stateless typed response.
                    await self._repo.release_lease_on_failure(
                        conversation_id,
                        command_id,
                        {"type": type(error).__name__, "detail": str(error)},
                    )
                    return {
                        "status": "CLARIFICATION_REQUIRED",
                        "code": ErrorCode.CONTEXT_INCOMPLETE.value,
                        "message": public_message,
                        "clarification_type": clarification_type,
                        "retryable": False,
                        "required_action": "PROVIDE_CONTEXT",
                        "disambiguation_options": [
                            option.model_dump(mode="json") if hasattr(option, "model_dump") else option
                            for option in (getattr(error, "disambiguation_options", ()) or ())
                        ],
                        "suggestions": list(getattr(error, "suggestions", ()) or ()),
                    }
            except Exception as error:
                # 메타데이터·모델·전송 실패는 해석 자체를 신뢰할 수 없다는 뜻이다. 빈
                # 신호로 진행하면 route·상속·기간이 조용히 기본값으로 떨어져 사용자가
                # 요청하지 않은 분석이 실행되므로 typed 실패로 닫는다.
                logger.warning(
                    "conversation preflight interpretation failed: type=%s",
                    type(error).__name__,
                )
                public_error = {
                    "status": "FAILED",
                    "code": ErrorCode.CONTEXT_SOURCE_FAILED.value,
                    "message": "질문 문제가 아니라 데이터 카탈로그 검증 실패로 분석을 시작하지 못했습니다.",
                    "retryable": True,
                    "required_action": "CONTACT_SUPPORT",
                }
                turn_id = uuid4()
                await self._repo.commit_failed_turn(
                    conversation_id,
                    command_id,
                    turn_id,
                    len(previous_turns),
                    user_message,
                    {
                        "type": type(error).__name__,
                        "detail": str(error),
                        **public_error,
                    },
                )
                updated_turns = await self._repo.list_turns(conversation_id)
                return {
                    **public_error,
                    "turn": next(
                        turn for turn in updated_turns if turn["turn_id"] == turn_id
                    ),
                }

            # 5-1. UI가 이미 아는 동작은 자연어로 바꾸지 않고 typed action으로 받는다.
            # 신호는 후보일 뿐이며 재사용 가능 여부는 아래 라우팅 계약이 다시 확인한다.
            node1_res = {**node1_res, **client_action_signals(payload)}

            # 6. 결정론적 슬롯/시간 리졸버로 슬롯 및 라우트 확정
            slots: ResolvedTurnSlots = ConversationSlotResolver.resolve(
                user_message=user_message,
                node1_output=node1_res,
                previous_turns=previous_turns,
                as_of=context.as_of,
                timezone_str=context.timezone,
            )
            if (
                preflight_clarification is not None
                and _clarification_resolved_by_inheritance(
                    preflight_clarification,
                    slots,
                )
            ):
                preflight_clarification = None

            turn_id = uuid4()
            turn_index = len(previous_turns)
            request_id = None
            artifact_id = None
            view_spec_id = None
            report_def_id = None
            analysis_resp = None

            # 7. 3대 라우트 분기 실행
            if slots.route == "ANALYSIS" and preflight_clarification is None:
                # 라우트 1: ANALYSIS (실제 데이터 쿼리 파이프라인 실행)
                analysis_req = build_structured_analysis_request(user_message, slots)
                execution: dict[str, Any] = {}
                analysis_repo = self._get_analysis_repository(context)
                if analysis_repo is not None:
                    await analysis_repo.begin_request(user_message, {}, context)
                try:
                    import inspect
                    if callable(self._submit_analysis):
                        sig = inspect.signature(self._submit_analysis)
                        if "execution_sink" in sig.parameters or len(sig.parameters) >= 3:
                            analysis_resp = await self._submit_analysis(analysis_req, context, execution.update)
                        else:
                            analysis_resp = await self._submit_analysis(analysis_req, context)
                    else:
                        analysis_resp = await self._submit_analysis(analysis_req, context)

                    if analysis_repo is not None and analysis_resp is not None:
                        await analysis_repo.finish_run(context.request_id, analysis_resp, execution)
                except Exception as err:
                    if analysis_repo is not None:
                        try:
                            await analysis_repo.fail_run(context.request_id)
                        except Exception:
                            pass
                    raise err

                artifact_id = extract_artifact_id(analysis_resp)
                request_id = context.request_id

            elif slots.route == "PRESENTATION":
                # 라우트 2: PRESENTATION (Trino 쿼리 0건 실행, 동일 Artifact에 대한 ViewSpec 생성)
                target_artifact_id = None
                for t in reversed(previous_turns):
                    if t.get("artifact_id"):
                        target_artifact_id = t["artifact_id"]
                        break
                if not target_artifact_id:
                    raise ValueError("시각화를 전환할 선행 분석 결과(Artifact)가 없습니다.")

                view_spec_id = await self._repo.create_view_spec(
                    artifact_id=target_artifact_id,
                    view_type=slots.target_chart_type or "TABLE",
                    spec_json={
                        "chart_type": (slots.target_chart_type or "TABLE").lower(),
                        "source_artifact_id": str(target_artifact_id),
                    },
                    user_id=context.user_id,
                )
                artifact_id = target_artifact_id

            elif slots.route == "REPORT_ACTION":
                # 라우트 3: REPORT_ACTION (Trino 쿼리 0건 실행, 선행 Artifact들을 Report Draft에 연결)
                report_repo = self._get_report_repository(context)
                report_def_id, artifact_id = await execute_report_action(report_repo, previous_turns)

            # 모호성 해소 요구사항 확인. Preflight에서 이미 확정된 typed 선택지는
            # 분석을 중복 실행하지 않고 그대로 turn 상태로 승격한다.
            is_clarification = preflight_clarification is not None
            disambiguation_options = (
                getattr(preflight_clarification, "disambiguation_options", ())
                if preflight_clarification is not None
                else ()
            )
            clarification_type = (
                "period"
                if preflight_clarification is not None
                and preflight_clarification.code is ContextBuildErrorCode.PERIOD_REQUIRED
                else "metric" if preflight_clarification is not None else None
            )

            if analysis_resp is not None:
                resp_status = getattr(getattr(analysis_resp, "data", None), "status", None)
                resp_error = getattr(analysis_resp, "error", None)
                has_opts = bool(
                    getattr(getattr(analysis_resp, "data", None), "disambiguation_options", None)
                    or (getattr(resp_error, "disambiguation_options", None) if resp_error else None)
                )
                if (
                    resp_status == AnalysisStatus.CLARIFICATION_REQUIRED
                    or has_opts
                    or (resp_error and getattr(resp_error, "code", None) == ErrorCode.CONTEXT_INCOMPLETE)
                ):
                    is_clarification = True
                    disambiguation_options = (
                        getattr(getattr(analysis_resp, "data", None), "disambiguation_options", ())
                        or (getattr(resp_error, "disambiguation_options", ()) if resp_error else ())
                    )
                    clarification_type = getattr(resp_error, "clarification_type", None) if resp_error else None
                    if hasattr(clarification_type, "value"):
                        clarification_type = clarification_type.value

            last_slots = previous_turns[-1].get("resolved_slots", {}) if previous_turns else {}
            ambiguity_status = "NEEDS_CLARIFICATION" if is_clarification else (
                "RESOLVED" if last_slots.get("ambiguity_status") == "NEEDS_CLARIFICATION" else "CLEAR"
            )

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
                    "metric_ids": list(slots.metric_ids),
                    "dimension_fields": [dict(d) for d in slots.dimension_fields],
                    "user_filters": [dict(f) for f in slots.user_filters],
                    "time_range": {
                        "start": slots.time_range.start.isoformat(),
                        "end_exclusive": slots.time_range.end_exclusive.isoformat(),
                        "source_text": slots.time_range.source_text,
                    } if slots.time_range else None,
                    "comparison_time_range": {
                        "start": slots.comparison_time_range.start.isoformat(),
                        "end_exclusive": slots.comparison_time_range.end_exclusive.isoformat(),
                        "source_text": slots.comparison_time_range.source_text,
                    } if slots.comparison_time_range else None,
                    "target_chart_type": slots.target_chart_type,
                    "analysis_operation": slots.analysis_operation,
                    "result_limit": slots.result_limit,
                    "ambiguity_status": ambiguity_status,
                    "clarification_type": clarification_type or last_slots.get("clarification_type"),
                    "disambiguation_options": [
                        opt.model_dump(mode="json") if hasattr(opt, "model_dump") else opt
                        for opt in disambiguation_options
                    ] if is_clarification else [],
                    "pending_user_message": user_message if is_clarification else None,
                    "is_inherited_metric": slots.is_inherited_metric,
                    "is_inherited_dimension": slots.is_inherited_dimension,
                    "is_inherited_period": slots.is_inherited_period,
                },
            )

            # 9. 수화(Hydration)된 최신 턴 목록 반환
            updated_turns = await self._repo.list_turns(conversation_id)
            latest_turn = next((t for t in updated_turns if t["turn_id"] == turn_id), None)

            return {
                "status": "CLARIFICATION_REQUIRED" if is_clarification else "SUCCESS",
                "turn": latest_turn,
                "conversation": {
                    "conversation_id": str(conversation_id),
                    "head_turn_id": str(turn_id),
                    "turn_count": turn_index + 1,
                },
                "disambiguation_options": [
                    opt.model_dump(mode="json") if hasattr(opt, "model_dump") else opt
                    for opt in disambiguation_options
                ] if is_clarification else [],
                "code": ErrorCode.CONTEXT_INCOMPLETE.value if is_clarification else None,
                "message": (
                    "분석을 시작하려면 분석할 기간을 함께 입력해 주세요."
                    if clarification_type == "period"
                    else "분석할 지표를 확정하지 못했습니다. 하나의 지표를 선택하거나 질문에 포함해 주세요."
                ) if is_clarification else None,
                "clarification_type": clarification_type if is_clarification else None,
                "retryable": False if is_clarification else None,
                "required_action": "PROVIDE_CONTEXT" if is_clarification else None,
                "suggestions": list(
                    getattr(preflight_clarification, "suggestions", ()) or ()
                ) if preflight_clarification is not None else [],
                "analysis_response": analysis_resp.model_dump(mode="json") if analysis_resp and hasattr(analysis_resp, "model_dump") else None,
            }

        except Exception as error:
            error_data = {"type": type(error).__name__, "detail": str(error)}
            await self._repo.release_lease_on_failure(conversation_id, command_id, error_data)
            raise
