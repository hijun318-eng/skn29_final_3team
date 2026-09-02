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

import asyncio
import inspect
import logging
import math
import os
import re
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Callable
from uuid import UUID, uuid4

from app.adapters.conversation_repository import ConversationRepository
from app.authorization import has_capability, permission_snapshot_id
from app.conversation_contracts import (
    ConversationCommandRequest,
    canonical_command_input_hash,
)
from app.contracts import AnalysisRequest, AnalysisStatus, Capability, ErrorCode, RequestContext, ResolvedSlots
from app.ports.data_platform import (
    DataPlatformAdapter,
    MetadataUnavailableError,
    NoEntitledAssetsError,
    ReleaseReceiptChangedError,
)
from app.services.context.builder import ContextBuildError, ContextBuildErrorCode
from app.services.context.model_signals import client_action_signals
from app.services.conversation.analysis_request import (
    build_structured_analysis_request,
    extract_artifact_id,
)
from app.services.conversation.report_actions import (
    apply_report_action_plan,
    plan_report_action,
)
from app.services.conversation.slot_resolver import ConversationSlotResolver, ResolvedTurnSlots
from app.services.analysis.pipeline_support import PipelineSupport
from app.services.execution_control import ConcurrentExecutionGate, ModelCallBudget

if TYPE_CHECKING:
    from app.ports.agent import AgentRequest
    from app.services.agent_supervisor import AgentRouteResolver

logger = logging.getLogger("uvicorn.error")

_WRITE_SQL_KEYWORD = re.compile(
    r"(?<![A-Za-z0-9_])(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

_OUT_OF_SCOPE_MESSAGE = (
    "해당 요청은 지원하지 않습니다. 이 서비스는 호텔 운영 데이터 분석, 승인된 내부 업무지침 확인, "
    "분석 결과의 보고서 작업만 지원합니다. 지원 범위에 맞게 요청해 주세요."
)


@dataclass(frozen=True)
class _AdmittedConversationCommand:
    """기존 turn_commands lease를 획득한 단일 실행의 서버 확정값이다."""

    context: RequestContext
    command_id: UUID
    canonical_input_hash: str
    product_release_id: str
    permission_snapshot_id: str
    semantic_release_id: str


def _explicit_write_sql_intent(user_message: str) -> bool:
    """명시적인 SQL write keyword가 포함된 요청을 모델·metadata 전에 차단한다."""

    return _WRITE_SQL_KEYWORD.search(user_message) is not None


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
            and (
                # 표현 전환은 새 분석 슬롯이 없어야 정상이며, 선행 Artifact 존재와
                # immutable ViewSpec 생성 전제는 PRESENTATION 실행 분기가 다시 확인한다.
                slots.route == "PRESENTATION"
                or ConversationSlotResolver.has_grounded_analysis_slot_delta(partial)
            )
        )
    if error.code is ContextBuildErrorCode.PERIOD_REQUIRED:
        return (
            not partial.get("period_candidates")
            and slots.is_inherited_period
            and slots.time_range is not None
        )
    return False


def _clarification_resolved_by_range_correction(
    error: ContextBuildError,
    slots: ResolvedTurnSlots,
    previous_turns: list[dict[str, Any]],
) -> bool:
    """Allow one exact absolute-period correction to reuse pending Metric intent.

    A range-blocked Turn is never data lineage.  It may supply only its already
    validated Metric/dimension/filter intent to the immediately following Turn,
    and only when Node 1 has independently produced a new absolute period.
    """

    last_turn = previous_turns[-1] if previous_turns else None
    return bool(
        error.code is ContextBuildErrorCode.INVALID_METRIC
        and last_turn is not None
        and last_turn.get("route") == "ANALYSIS"
        and last_turn.get("terminal_status") == "BLOCKED"
        and last_turn.get("reason_code") == ErrorCode.OUT_OF_DATA_RANGE.value
        and slots.is_inherited_metric
        and bool(slots.metric_ids)
        and slots.time_range is not None
        and not slots.is_inherited_period
        and not slots.source_turn_ids
    )


def _analysis_terminal(response: Any) -> tuple[str, str | None]:
    """Map the typed Analysis result to the persisted terminal Turn contract."""

    status = getattr(getattr(response, "data", None), "status", None)
    dumped = (
        response.model_dump(mode="json")
        if response is not None and hasattr(response, "model_dump")
        else {}
    )
    if status is None and isinstance(dumped, dict):
        data = dumped.get("data")
        if isinstance(data, dict):
            status = data.get("status")
    value = status.value if hasattr(status, "value") else str(status or "FAILED")
    if value == "CLARIFICATION_REQUIRED":
        value = "BLOCKED"
    if value not in {"SUCCEEDED", "BLOCKED", "PARTIAL", "FAILED", "CANCELLED"}:
        value = "FAILED"
    error = getattr(response, "error", None)
    code = getattr(error, "code", None)
    if code is None and isinstance(dumped, dict):
        dumped_error = dumped.get("error")
        if isinstance(dumped_error, dict):
            code = dumped_error.get("code")
    reason = code.value if hasattr(code, "value") else str(code) if code else None
    return value, reason


def _view_contract(
    response: Any,
    artifact_id: UUID,
    requested_type: str | None = None,
) -> dict[str, Any]:
    """Create the immutable default View payload from the Safe Artifact response."""

    chart = getattr(
        getattr(getattr(response, "data", None), "result", None),
        "chart",
        None,
    )
    if chart is None and response is not None and hasattr(response, "model_dump"):
        dumped = response.model_dump(mode="json")
        data = dumped.get("data") if isinstance(dumped, dict) else None
        result = data.get("result") if isinstance(data, dict) else None
        chart = result.get("chart") if isinstance(result, dict) else None
    raw_type = str(
        (
            chart.get("chart_type")
            if isinstance(chart, dict)
            else getattr(chart, "chart_type", "")
        )
        or "TABLE"
    ).upper()
    artifact_view_type = {
        "HORIZONTAL_BAR": "BAR",
        "DONUT": "PIE",
    }.get(raw_type, raw_type)
    requested_view_type = {
        "HORIZONTAL_BAR": "BAR",
        "DONUT": "PIE",
        # SUMMARY는 대화 renderer의 복합 모드이며 영속 ViewSpec enum은 아니다.
        # 사용자가 별도 표현을 요청하지 않은 초기 결과는 중립적인 TABLE로 보존한다.
        "SUMMARY": "TABLE",
    }.get(str(requested_type or "").upper(), str(requested_type or "").upper())
    view_type = requested_view_type or artifact_view_type
    if view_type not in {"TABLE", "BAR", "LINE", "PIE", "AREA", "SCATTER", "KPI"}:
        view_type = "TABLE"
    spec = {
        "chart_type": view_type.lower(),
        "source_artifact_id": str(artifact_id),
    }
    if chart is not None:
        x_field = (
            chart.get("x_field")
            if isinstance(chart, dict)
            else getattr(chart, "x_field", None)
        )
        y_fields = (
            chart.get("y_fields", ())
            if isinstance(chart, dict)
            else getattr(chart, "y_fields", ())
        )
        spec.update(
            {
                "x_field": str(x_field) if x_field is not None else None,
                "y_fields": list(y_fields or ()),
            }
        )
    return {"view_type": view_type, "spec_json": spec}


def _presentation_view_contract(
    source_turn: dict[str, Any],
    requested_type: str,
) -> dict[str, Any]:
    """Safe Artifact의 저장 schema 역할 안에서만 새 표현 계약을 만든다."""

    artifact_id = source_turn.get("artifact_id")
    snapshot = source_turn.get("data_snapshot_json")
    chart = source_turn.get("chart_spec_json")
    if (
        not artifact_id
        or not isinstance(snapshot, dict)
        or not isinstance(chart, dict)
    ):
        raise ValueError("이전 분석 결과의 표·차트 구성 정보를 확인할 수 없습니다.")
    raw_columns = snapshot.get("columns")
    if not isinstance(raw_columns, list) or any(
        not isinstance(column, str) or not column for column in raw_columns
    ):
        raise ValueError("이전 분석 결과에서 표시할 열을 확인할 수 없습니다.")
    columns = tuple(dict.fromkeys(raw_columns))
    if len(columns) != len(raw_columns) or not columns:
        raise ValueError("이전 분석 결과의 표시 열이 비어 있거나 중복되었습니다.")

    normalized_requested_type = requested_type.upper()
    view_type = {
        "HORIZONTAL_BAR": "BAR",
        "DONUT": "PIE",
        "SUMMARY": "TABLE",
    }.get(normalized_requested_type, normalized_requested_type)
    if view_type not in {"TABLE", "BAR", "LINE", "PIE", "AREA"}:
        raise ValueError("요청한 표현 방식은 현재 지원하지 않습니다.")
    spec: dict[str, Any] = {
        "chart_type": {
            "HORIZONTAL_BAR": "horizontal-bar",
            "DONUT": "donut",
        }.get(normalized_requested_type, view_type.lower()),
        "source_artifact_id": str(artifact_id),
        "columns": list(columns),
        "sort": [],
        "format": {},
    }
    if view_type == "TABLE":
        return {"view_type": view_type, "spec_json": spec}

    x_field = chart.get("x_field")
    raw_y_fields = chart.get("y_fields")
    if (
        not isinstance(x_field, str)
        or x_field not in columns
        or not isinstance(raw_y_fields, (list, tuple))
        or not raw_y_fields
        or any(
            not isinstance(field, str)
            or field == x_field
            or field not in columns
            for field in raw_y_fields
        )
    ):
        raise ValueError("현재 결과에는 그래프 비교에 필요한 기간 또는 분류 축이 없습니다.")
    if view_type in {"LINE", "AREA"} and x_field != "period":
        raise ValueError("현재 결과에는 시간 흐름을 나타내는 기간 축이 없습니다.")
    spec.update(
        {
            "x_field": x_field,
            "y_fields": list(dict.fromkeys(raw_y_fields)),
            "sort": (
                [{"field": x_field, "direction": "ASC"}]
                if x_field == "period"
                else []
            ),
        }
    )
    return {"view_type": view_type, "spec_json": spec}


def _slot_provenance(
    slots: ResolvedTurnSlots,
) -> dict[str, dict[str, Any]]:
    """Persist field-level SET/INHERIT provenance without copying transcript text."""

    source = slots.source_turn_ids[-1] if slots.source_turn_ids else None

    def item(inherited: bool, present: bool) -> dict[str, Any]:
        return {
            "operation": "INHERIT" if inherited else "SET" if present else "REMOVE",
            "source_turn_id": source if inherited else None,
            "provenance": "USER_REQUESTED",
        }

    return {
        "metric_ids": item(slots.is_inherited_metric, bool(slots.metric_ids)),
        "dimension_fields": item(
            slots.is_inherited_dimension,
            bool(slots.dimension_fields),
        ),
        "user_filters": item(
            any(
                change.field == "user_filters" and change.op.value == "PRESERVE"
                for change in slots.change_set
            ),
            bool(slots.user_filters),
        ),
        "time_range": item(slots.is_inherited_period, slots.time_range is not None),
    }


def _source_business_terms(node1_output: Mapping[str, Any]) -> list[str]:
    """Return only bounded, unique measurement spans already validated upstream."""

    raw = node1_output.get("measurement_source_texts")
    if isinstance(raw, list) and 0 < len(raw) <= 4 and all(
        isinstance(item, str) and item.strip() for item in raw
    ):
        values = [item.strip() for item in raw]
        if len(values) == len(set(values)):
            return values
    return []


def _business_terms_for_turn(
    node1_output: Mapping[str, Any],
    previous_slots: Mapping[str, Any],
    slots: ResolvedTurnSlots,
) -> list[str]:
    """Persist bounded Node 1 source spans or inherit the prior approved spans.

    These strings are evidence of the actual interpretation, not canonical
    labels synthesized from an expected answer.  Invalid or oversized model
    output is omitted so evaluation observes a mismatch instead of fabricated
    success.
    """

    source_terms = _source_business_terms(node1_output)
    if source_terms:
        return source_terms
    inherited = previous_slots.get("business_terms")
    if (
        (slots.is_inherited_metric or slots.route in {"PRESENTATION", "REPORT_ACTION"})
        and isinstance(inherited, list)
        and len(inherited) <= 4
        and all(isinstance(item, str) and item for item in inherited)
    ):
        return list(inherited)
    return []


def _safe_analysis_observation(execution: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only governed plan identity; never persist SQL, parameters, or rows."""

    plan = execution.get("plan")
    package = execution.get("package")
    analysis_plan = plan.get("analysis_plan") if isinstance(plan, Mapping) else None
    if not isinstance(analysis_plan, Mapping) or package is None:
        return {}
    output_ids = analysis_plan.get("output_metric_ids")
    raw_joins = analysis_plan.get("joins")
    if (
        not isinstance(output_ids, list)
        or not output_ids
        or any(not isinstance(item, str) or not item for item in output_ids)
        or not isinstance(raw_joins, list)
    ):
        return {}
    metrics = {
        str(getattr(metric, "id", "")): metric
        for metric in tuple(getattr(package, "metrics", ()))
        if getattr(metric, "id", None)
    }

    def assets(metric_id: str, trail: frozenset[str] = frozenset()) -> set[str]:
        if metric_id in trail:
            return set()
        metric = metrics.get(metric_id)
        if metric is None:
            return set()
        asset = str(getattr(metric, "asset_fqn", "") or "")
        if asset:
            return {asset}
        operands = (
            str(getattr(metric, "numerator_metric_id", "") or ""),
            str(getattr(metric, "denominator_metric_id", "") or ""),
        )
        if not all(operands):
            return set()
        return set().union(
            *(assets(operand, trail | {metric_id}) for operand in operands)
        )

    source_assets = sorted(
        set().union(*(assets(metric_id) for metric_id in output_ids))
    )
    join_ids = []
    join_plans = []
    for item in raw_joins:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("join_id"), str)
            or not item["join_id"]
            or not isinstance(item.get("plan"), str)
            or not item["plan"]
        ):
            return {}
        join_id = str(item["join_id"])
        join_ids.append(join_id)
        join_plans.append({"join_id": join_id, "plan": str(item["plan"])})
    query_strategy = analysis_plan.get("query_strategy")
    time_bucket = analysis_plan.get("time_bucket")
    checksum = analysis_plan.get("checksum")
    if (
        not source_assets
        or not isinstance(query_strategy, str)
        or not query_strategy
        or not isinstance(time_bucket, str)
        or not isinstance(checksum, str)
    ):
        return {}
    return {
        "query_strategy": query_strategy,
        "source_assets": source_assets,
        "join_ids": sorted(join_ids),
        "join_plans": sorted(
            join_plans,
            key=lambda item: (item["join_id"], item["plan"]),
        ),
        "time_bucket": time_bucket,
        "analysis_plan_sha256": checksum,
    }


class ConversationOrchestrator:
    """멀티턴 대화의 상태 머신, 동시성 제어 및 라우트 실행을 담당하는 오케스트레이터."""

    def __init__(
        self,
        repository: ConversationRepository,
        data_platform: DataPlatformAdapter,
        support: PipelineSupport,
        submit_analysis: Callable[..., Any],
        report_repository_factory: Callable[[RequestContext, bool], Any] | Any | None = None,
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

    async def get_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any] | None:
        """소유자 범위가 적용된 Conversation을 공개 읽기 경계로 반환한다."""

        return await self._repo.get_conversation(conversation_id, user_id)

    async def list_turns(self, conversation_id: UUID) -> list[dict[str, Any]]:
        """Conversation의 불변 Turn 목록을 공개 읽기 경계로 반환한다."""

        return await self._repo.list_turns(conversation_id)

    async def _renew_command_lease(
        self,
        conversation_id: UUID,
        command_id: UUID,
        stop: asyncio.Event,
        lost: asyncio.Event,
    ) -> None:
        """실행 중인 command의 lease를 갱신하고 소유권 상실을 취소 신호로 바꾼다."""
        renew = getattr(self._repo, "renew_lease", None)
        if not callable(renew):
            return
        try:
            interval = int(os.getenv("CONVERSATION_LEASE_HEARTBEAT_SECONDS", "20"))
        except ValueError:
            interval = 20
        interval = max(1, min(interval, 30))
        while not stop.is_set():
            try:
                if not await renew(conversation_id, command_id):
                    lost.set()
                    logger.error(
                        "Conversation lease heartbeat lost command ownership"
                    )
                    return
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                lost.set()
                logger.exception("Conversation lease heartbeat failed")
                return

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
                return self._report_repository_factory(context, is_admin)
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
            product_release_id=context.product_release_id,
            permission_snapshot_id=context.permission_snapshot_id,
            semantic_release_id=context.semantic_release_id,
            session_factory=self._repo._sessionmaker,
        )

    async def _release_receipt(
        self,
        product_release_id: str | None = None,
        semantic_release_id: str | None = None,
    ) -> tuple[str, str]:
        """새 대화는 active, 기존 대화는 pinned immutable release를 검증한다."""

        if product_release_id is not None:
            checker = getattr(
                self._data_platform,
                "get_product_release_readiness",
                None,
            )
            if callable(checker):
                stages, receipt, observed_semantic = await checker(
                    product_release_id
                )
                if (
                    receipt != product_release_id
                    or observed_semantic != semantic_release_id
                    or any(value != "ready" for value in stages.values())
                ):
                    raise ReleaseReceiptChangedError(
                        "pinned product release is no longer executable"
                    )
                return product_release_id, str(observed_semantic)

        semantic_before = await self._data_platform.get_active_context_release()
        stages, product_release = await self._data_platform.get_catalog_readiness()
        semantic_after = await self._data_platform.get_active_context_release()
        if (
            semantic_before != semantic_after
            or not product_release
            or any(value != "ready" for value in stages.values())
        ):
            raise ReleaseReceiptChangedError(
                "active product release receipt를 원자적으로 확정하지 못했습니다."
            )
        return product_release, semantic_after

    async def create_conversation(
        self,
        context: RequestContext,
        title: str,
    ) -> dict[str, Any]:
        """서버 권한·active release를 pin한 새 Conversation을 만든다."""

        product_release, semantic_release = await self._release_receipt()
        permission_receipt = permission_snapshot_id(context.user_id, context.role)
        return await self._repo.create_conversation(
            context.user_id,
            title,
            product_release_id=product_release,
            permission_snapshot_id=permission_receipt,
            semantic_release_id=semantic_release,
            wall_clock_anchor=context.as_of,
        )

    async def _existing_command_result(
        self,
        conversation_id: UUID,
        existing_command: dict[str, Any],
        canonical_hash: str,
    ) -> dict[str, Any]:
        """저장 hash가 일치한 뒤에만 terminal 또는 RUNNING command를 replay한다."""

        if str(existing_command["canonical_input_hash"]).strip() != canonical_hash:
            return {
                "status": "CONFLICT",
                "code": ErrorCode.IDEMPOTENCY_CONFLICT.value,
                "message": "같은 idempotency key의 authoritative payload가 다릅니다.",
            }
        if existing_command["status"] == "COMPLETED" and existing_command["turn_id"]:
            turns = await self._repo.list_turns(conversation_id)
            target_turn = next(
                (
                    turn
                    for turn in turns
                    if str(turn["turn_id"]) == str(existing_command["turn_id"])
                ),
                None,
            )
            terminal_status = (
                str(target_turn.get("terminal_status")) if target_turn else None
            )
            status = (
                "CLARIFICATION_REQUIRED"
                if target_turn
                and target_turn.get("resolved_slots", {}).get("ambiguity_status")
                == "NEEDS_CLARIFICATION"
                else "SUCCESS"
                if terminal_status in {None, "SUCCEEDED"}
                else terminal_status
            )
            result = {
                "status": status,
                "code": target_turn.get("reason_code") if target_turn else None,
                "is_idempotent_replay": True,
                "turn": target_turn,
            }
            if target_turn and target_turn.get("route") == "OUT_OF_SCOPE":
                scope_rejection = target_turn.get("resolved_slots", {}).get(
                    "scope_rejection",
                    {},
                )
                result.update(
                    {
                        "type": "OUT_OF_SCOPE",
                        "message": scope_rejection.get(
                            "message",
                            _OUT_OF_SCOPE_MESSAGE,
                        ),
                        "retryable": False,
                        "required_action": "MODIFY_REQUEST",
                    }
                )
            return result
        if existing_command["status"] == "RUNNING":
            return {
                "status": "BUSY",
                "code": "CONVERSATION_BUSY",
                "message": "동일한 명령이 처리 중입니다.",
            }
        error = existing_command.get("error_response") or {}
        turns = await self._repo.list_turns(conversation_id)
        target_turn = next(
            (
                turn
                for turn in turns
                if str(turn["turn_id"]) == str(existing_command.get("turn_id"))
            ),
            None,
        )
        error_code = error.get("code", ErrorCode.CONTEXT_SOURCE_FAILED.value)
        result = {
            "status": (
                "BUSY"
                if error_code == ErrorCode.RATE_LIMITED.value
                else "FAILED"
            ),
            "code": error_code,
            "message": error.get(
                "message",
                "질문 해석에 필요한 데이터 카탈로그를 검증하지 못했습니다.",
            ),
            "retryable": bool(error.get("retryable", True)),
            "required_action": error.get("required_action", "CONTACT_SUPPORT"),
            "turn": target_turn,
            "is_idempotent_replay": True,
        }
        if isinstance(error.get("status_code"), int):
            result["_http_status_code"] = error["status_code"]
        return result

    async def _admit_command(
        self,
        conversation_id: UUID,
        command: ConversationCommandRequest,
        context: RequestContext,
    ) -> tuple[_AdmittedConversationCommand | None, dict[str, Any] | None]:
        """공통 command hash·idempotency·CAS·lease를 한 경로에서 승인한다."""

        if context.conversation_id not in {None, conversation_id}:
            raise ValueError("RequestContext conversation_id가 path identity와 다릅니다.")
        conversation = await self._repo.get_conversation(
            conversation_id,
            context.user_id,
        )
        if conversation is None:
            return None, {
                "status": "CONFLICT",
                "code": "CONVERSATION_NOT_FOUND",
                "message": "대화방을 찾을 수 없거나 접근 권한이 없습니다.",
            }
        current_permission = permission_snapshot_id(context.user_id, context.role)
        if conversation["permission_snapshot_id"] != current_permission:
            return None, {
                "status": "CONFLICT",
                "code": ErrorCode.ACCESS_DENIED.value,
                "message": "Conversation 생성 이후 권한 snapshot이 변경되었습니다.",
            }
        try:
            current_product, current_semantic = await self._release_receipt(
                str(conversation["product_release_id"]),
                str(conversation["semantic_release_id"]),
            )
        except MetadataUnavailableError:
            return None, {
                "status": "CONFLICT",
                "code": ErrorCode.RESOURCE_CONFLICT.value,
                "message": "Conversation에 고정된 product release를 더 이상 실행할 수 없습니다.",
            }
        wall_clock_anchor = conversation["wall_clock_anchor"]
        if isinstance(wall_clock_anchor, str):
            wall_clock_anchor = date.fromisoformat(wall_clock_anchor)
        command_id = uuid4()
        admitted_context = context.model_copy(
            update={
                "conversation_id": conversation_id,
                "permission_snapshot_id": current_permission,
                "product_release_id": current_product,
                "semantic_release_id": current_semantic,
                "command_id": command_id,
                "as_of": wall_clock_anchor,
            }
        )
        input_hash = canonical_command_input_hash(
            command,
            conversation_id,
            admitted_context,
        )
        existing_command = await self._repo.get_command(
            conversation_id,
            command.idempotency_key,
        )
        if existing_command:
            return None, await self._existing_command_result(
                conversation_id,
                existing_command,
                input_hash,
            )

        lease_ok, lease_error = await self._repo.acquire_lease_and_check_cas(
            conversation_id=conversation_id,
            expected_head_turn_id=command.expected_head_turn_id,
            command_id=command_id,
            idempotency_key=command.idempotency_key,
            input_hash=input_hash,
            effective_subject_id=admitted_context.user_id,
            product_release_id=current_product,
            permission_snapshot_id=current_permission,
            semantic_release_id=current_semantic,
        )
        if not lease_ok:
            if lease_error == "IDEMPOTENCY_EXISTS":
                raced = await self._repo.get_command(
                    conversation_id,
                    command.idempotency_key,
                )
                if raced is not None:
                    return None, await self._existing_command_result(
                        conversation_id,
                        raced,
                        input_hash,
                    )
            return None, {
                "status": "CONFLICT",
                "code": lease_error,
                "message": f"동시성 충돌 또는 권한 오류 ({lease_error})",
            }

        return (
            _AdmittedConversationCommand(
                context=admitted_context,
                command_id=command_id,
                canonical_input_hash=input_hash,
                product_release_id=current_product,
                permission_snapshot_id=current_permission,
                semantic_release_id=current_semantic,
            ),
            None,
        )

    @staticmethod
    def _validate_admitted_command(
        conversation_id: UUID,
        command: ConversationCommandRequest,
        context: RequestContext,
        admission: _AdmittedConversationCommand,
    ) -> None:
        """pre-admitted lease가 같은 command·context를 가리킬 때만 재사용한다."""

        if (
            not isinstance(admission, _AdmittedConversationCommand)
            or admission.context != context
            or context.conversation_id != conversation_id
            or context.command_id != admission.command_id
            or context.product_release_id != admission.product_release_id
            or context.permission_snapshot_id != admission.permission_snapshot_id
            or context.semantic_release_id != admission.semantic_release_id
            or canonical_command_input_hash(command, conversation_id, context)
            != admission.canonical_input_hash
        ):
            raise ValueError("pre-admitted Conversation command가 요청과 일치하지 않습니다.")

    @staticmethod
    def _composite_public_fields_from_turn(turn: dict[str, Any]) -> dict[str, Any]:
        """저장된 조합 receipt와 선택 Agent 결과만 replay 공개 계약으로 수화한다."""

        slots = turn.get("resolved_slots")
        composition = (
            slots.get("supervisor_composition")
            if isinstance(slots, dict)
            else None
        )
        if composition is None:
            return {}
        if not isinstance(composition, dict):
            raise ValueError("저장된 복합 Agent receipt가 올바르지 않습니다.")
        agents = composition.get("agents")
        evidence_refs = composition.get("evidence_refs")
        if (
            composition.get("schema_version")
            != "SupervisorCompositionReceipt.v1"
            or not isinstance(agents, list)
            or not 2 <= len(agents) <= 3
            or len(agents) != len(set(agents))
            or any(
                agent
                not in {
                    "ANALYSIS_WORKFLOW",
                    "INTERNAL_GUIDELINE",
                    "ML_PREDICTION",
                }
                for agent in agents
            )
            or composition.get("primary_agent") not in agents
            or not isinstance(evidence_refs, list)
            or not evidence_refs
            or len(evidence_refs) != len(set(evidence_refs))
            or any(not isinstance(ref, str) or not ref for ref in evidence_refs)
            or not isinstance(composition.get("plan_ref"), str)
            or composition["plan_ref"] not in evidence_refs
        ):
            raise ValueError("저장된 복합 Agent receipt가 올바르지 않습니다.")
        return {
            "type": "COMPOSITE",
            "composition": dict(composition),
            "rag_response": slots.get("rag"),
            "ml_prediction": slots.get("ml_prediction"),
        }

    async def _hydrate_analysis_composite_replay(
        self,
        conversation_id: UUID,
        user_id: UUID,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """분석 대표 Turn의 보조 RAG·ML 결과를 멱등 replay에 복원한다."""

        if result.get("status") != "SUCCESS" or not isinstance(
            result.get("turn"),
            dict,
        ):
            return result
        fields = self._composite_public_fields_from_turn(result["turn"])
        if not fields:
            return result
        return {
            **result,
            "conversation": await self._repo.get_conversation(
                conversation_id,
                user_id,
            ),
            **fields,
        }

    async def _hydrate_internal_guideline_replay(
        self,
        conversation_id: UUID,
        user_id: UUID,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """저장된 RAG terminal 결과를 기존 공개 응답에 필요한 형태로만 수화한다."""

        if result.get("status") != "SUCCESS":
            return result
        turn = result.get("turn")
        slots = turn.get("resolved_slots") if isinstance(turn, dict) else None
        rag_response = slots.get("rag") if isinstance(slots, dict) else None
        if (
            not isinstance(turn, dict)
            or turn.get("route") != "INTERNAL_GUIDELINE"
            or not isinstance(rag_response, dict)
        ):
            return {
                "status": "FAILED",
                "code": "RAG_REPLAY_STATE_INVALID",
                "message": "저장된 내부지침 실행 결과를 검증하지 못했습니다.",
                "retryable": False,
                "required_action": "CONTACT_SUPPORT",
                "is_idempotent_replay": True,
            }
        composite_fields = self._composite_public_fields_from_turn(turn)
        return {
            **result,
            **composite_fields,
            "conversation": await self._repo.get_conversation(
                conversation_id,
                user_id,
            ),
            "rag_response": {
                **rag_response,
                "turn_id": str(turn["turn_id"]),
            },
        }

    async def _hydrate_ml_prediction_replay(
        self,
        conversation_id: UUID,
        user_id: UUID,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """저장된 ML terminal Turn에서 검증된 예측 payload만 재구성한다."""

        if result.get("status") != "SUCCESS":
            return result
        turn = result.get("turn")
        slots = turn.get("resolved_slots") if isinstance(turn, dict) else None
        prediction = slots.get("ml_prediction") if isinstance(slots, dict) else None
        if (
            not isinstance(turn, dict)
            or turn.get("route") != "ML_PREDICTION"
            or not isinstance(prediction, dict)
        ):
            return {
                "status": "FAILED",
                "code": "ML_PREDICTION_REPLAY_STATE_INVALID",
                "message": "저장된 ML 예측 실행 결과를 검증하지 못했습니다.",
                "retryable": False,
                "required_action": "CONTACT_SUPPORT",
                "is_idempotent_replay": True,
            }
        return {
            **result,
            "conversation": await self._repo.get_conversation(
                conversation_id,
                user_id,
            ),
            "ml_prediction": prediction,
        }

    async def _release_agent_dispatch_failure(
        self,
        conversation_id: UUID,
        admission: _AdmittedConversationCommand,
        error: BaseException,
    ) -> None:
        """Supervisor/route 단계 실패가 획득한 command lease를 남기지 않게 종결한다."""

        raw_code = getattr(error, "code", None)
        code = (
            raw_code.value
            if hasattr(raw_code, "value")
            else str(raw_code).strip()
            if raw_code is not None
            else "AGENT_DISPATCH_FAILED"
        )
        if not code:
            code = "AGENT_DISPATCH_FAILED"
        raw_status_code = getattr(error, "status_code", None)
        status_code = (
            raw_status_code
            if isinstance(raw_status_code, int)
            else 422
            if code
            in {
                "AGENT_ROUTE_NOT_RESOLVED",
                "AGENT_ROUTE_AMBIGUOUS",
                "AGENT_INVOCATION_MISMATCH",
            }
            else 504
            if isinstance(error, (asyncio.CancelledError, TimeoutError))
            else 503
        )
        execution_state = getattr(error, "agent_execution_state", None)
        if execution_state is None:
            execution_state = getattr(error, "state", None)
        selected_agent = getattr(execution_state, "selected_agent", None)
        evidence_refs = getattr(execution_state, "terminal_evidence_refs", ())
        if (
            not isinstance(evidence_refs, tuple)
            or len(evidence_refs) != len(set(evidence_refs))
            or any(not isinstance(ref, str) or not ref.strip() for ref in evidence_refs)
        ):
            evidence_refs = ()
        public_error = raw_code is not None
        error_response: dict[str, Any] = {
            "type": type(error).__name__,
            "code": code,
            "message": (
                str(error)
                if public_error
                else "Agent 명령 실행을 안전하게 종료했습니다."
            ),
            "retryable": status_code >= 500,
            "required_action": "RETRY" if status_code >= 500 else "MODIFY_REQUEST",
            "status_code": status_code,
        }
        if selected_agent is not None:
            error_response["selected_agent"] = (
                selected_agent.value
                if hasattr(selected_agent, "value")
                else str(selected_agent)
            )
        if evidence_refs:
            error_response["evidence_refs"] = list(evidence_refs)
        try:
            await self._repo.release_lease_on_failure(
                conversation_id,
                admission.command_id,
                error_response,
            )
        except Exception:
            logger.exception("Agent dispatch failure lease release failed")

    async def dispatch_agent_command(
        self,
        request: "AgentRequest",
        execution_gate: ConcurrentExecutionGate,
        internal_manual_query_service_factory: Callable[[], Any],
        *,
        route_resolver: "AgentRouteResolver | None" = None,
        supervisor_planner_factory: Callable[[], Any] | None = None,
        supervisor_routing_enabled: bool = False,
        internal_guideline_capability_searcher_factory: Callable[[], Any]
        | None = None,
        ml_prediction_service_factory: Callable[[], Any] | None = None,
        ml_prediction_executor_factory: Callable[[Any], Any] | None = None,
    ) -> dict[str, Any]:
        """공통 admission 후 명시적으로 승인된 Supervisor 결정만 실행한다.

        Supervisor가 일반 입력을 계획하더라도 선택 Agent의 capability/readiness와
        원본 command admission은 서버가 다시 검증한다. 명시 route는 모델을 우회한다.
        """

        from app.ports.agent import (
            AgentPreviousAnalysisContext,
            AgentPreviousMLContext,
            AgentRequest,
        )
        from app.contracts import RuntimeFeature
        from app.runtime_features import runtime_feature_enabled
        from app.services.agent_supervisor import AgentDispatchError
        from app.services.conversation_agent_ports import (
            analysis_agent_result,
            internal_guideline_agent_result,
            ml_prediction_agent_result,
        )
        from app.services.conversation_agent_registry import (
            build_conversation_agent_supervisor,
        )
        from app.services.langgraph_agent_runtime import LangGraphAgentRuntime
        from app.services.ml_prediction_service import (
            MLPredictionService,
            MLRuntimeCapability,
        )
        from app.services.supervisor_planner import (
            SupervisorCapabilityCatalog,
            materialize_supervisor_plan,
        )

        if not isinstance(request, AgentRequest):
            raise TypeError("dispatch_agent_command에는 AgentRequest가 필요합니다.")
        admission, early_result = await self._admit_command(
            request.conversation_id,
            request.command,
            request.context,
        )
        if early_result is not None:
            turn = early_result.get("turn")
            stored_route = turn.get("route") if isinstance(turn, dict) else None
            is_internal_guideline = (
                stored_route == "INTERNAL_GUIDELINE"
                or request.command.requested_route == "INTERNAL_GUIDELINE"
            )
            if is_internal_guideline:
                hydrated = await self._hydrate_internal_guideline_replay(
                    request.conversation_id,
                    request.context.user_id,
                    early_result,
                )
                return internal_guideline_agent_result(hydrated).payload
            is_ml_prediction = (
                stored_route == "ML_PREDICTION"
                or request.command.requested_route == "ML_PREDICTION"
            )
            if is_ml_prediction:
                hydrated = await self._hydrate_ml_prediction_replay(
                    request.conversation_id,
                    request.context.user_id,
                    early_result,
                )
                return ml_prediction_agent_result(hydrated).payload
            hydrated = await self._hydrate_analysis_composite_replay(
                request.conversation_id,
                request.context.user_id,
                early_result,
            )
            return analysis_agent_result(hydrated).payload
        if admission is None:
            raise RuntimeError("Agent command admission 결과가 없습니다.")

        previous_turns = await self._repo.list_turns(request.conversation_id)
        previous_analysis = None
        previous_ml = None
        if previous_turns and ConversationSlotResolver.is_resolved_analysis_turn(
            previous_turns[-1]
        ):
            previous_slots = previous_turns[-1].get("resolved_slots", {})
            previous_time = previous_slots.get("time_range")
            previous_metric_ids = tuple(
                metric_id
                for metric_id in (
                    previous_slots.get("metric_ids")
                    or (
                        [previous_slots.get("metric_id")]
                        if previous_slots.get("metric_id")
                        else []
                    )
                )
                if isinstance(metric_id, str) and metric_id.strip()
            )
            if (
                previous_metric_ids
                and isinstance(previous_time, dict)
                and previous_time.get("start")
                and previous_time.get("end_exclusive")
            ):
                previous_analysis = AgentPreviousAnalysisContext(
                    metric_ids=previous_metric_ids,
                    period_start=previous_time["start"],
                    period_end_exclusive=previous_time["end_exclusive"],
                )
        if previous_turns and previous_turns[-1].get("route") == "ML_PREDICTION":
            previous_slots = previous_turns[-1].get("resolved_slots", {})
            previous_prediction = previous_slots.get("ml_prediction")
            if isinstance(previous_prediction, dict):
                try:
                    previous_ml = AgentPreviousMLContext(
                        property_id=previous_prediction.get("property_id"),
                        as_of=previous_prediction.get("as_of"),
                        horizon_days=previous_prediction.get("horizon_days"),
                    )
                except (TypeError, ValueError):
                    logger.warning(
                        "Stored ML follow-up context is invalid: conversation_id=%s",
                        request.conversation_id,
                    )
        admitted_request = request.model_copy(
            update={
                "context": admission.context,
                "previous_analysis": previous_analysis,
                "previous_ml": previous_ml,
            }
        )
        try:
            materialized_plan = None
            shared_ml_service = (
                (ml_prediction_service_factory or MLPredictionService)()
                if runtime_feature_enabled(RuntimeFeature.ML_PREDICTION)
                else None
            )
            if (
                supervisor_routing_enabled
                and route_resolver is None
                and request.command.requested_route is None
            ):
                if supervisor_planner_factory is None:
                    raise AgentDispatchError(
                        "AGENT_SUPERVISOR_CONFIGURATION_INVALID",
                        "Supervisor planner가 구성되지 않았습니다.",
                    )
                ml_capability = None
                if shared_ml_service is not None:
                    try:
                        ml_capability = MLRuntimeCapability.model_validate(
                            await shared_ml_service.capabilities()
                        )
                    except Exception as error:
                        logger.warning(
                            "Supervisor ML capability is unavailable: error_type=%s",
                            type(error).__name__,
                        )
                        ml_capability = None
                catalog = SupervisorCapabilityCatalog.from_runtime(
                    rag_enabled=runtime_feature_enabled(
                        RuntimeFeature.INTERNAL_GUIDELINE
                    ),
                    ml_enabled=runtime_feature_enabled(
                        RuntimeFeature.ML_PREDICTION
                    ),
                    ml_capability=ml_capability,
                )
                previous_route = None
                if previous_turns:
                    raw_previous_route = previous_turns[-1].get("route")
                    if isinstance(raw_previous_route, str) and raw_previous_route:
                        previous_route = raw_previous_route
                planner = supervisor_planner_factory()
                planned = await planner.plan(
                    admitted_request,
                    catalog,
                    previous_route=previous_route,
                )
                materialized_plan = materialize_supervisor_plan(
                    admitted_request,
                    planned,
                    catalog,
                )
                if not materialized_plan.is_composite:
                    admitted_request = materialized_plan.requests[0]
            try:
                route_timeout_seconds = float(
                    os.getenv("CONVERSATION_AGENT_ROUTE_TIMEOUT_SECONDS", "15")
                )
            except ValueError as error:
                raise AgentDispatchError(
                    "AGENT_ROUTE_TIMEOUT_INVALID",
                    "Agent route 제한 시간 설정이 올바르지 않습니다.",
                ) from error
            if (
                not math.isfinite(route_timeout_seconds)
                or route_timeout_seconds <= 0
                or route_timeout_seconds > 15
            ):
                raise AgentDispatchError(
                    "AGENT_ROUTE_TIMEOUT_INVALID",
                    "Agent route 제한 시간은 0초보다 크고 15초 이하여야 합니다.",
                )
            if materialized_plan is not None and materialized_plan.is_composite:
                return await self._execute_composite_agent_plan(
                    materialized_plan,
                    admission,
                    execution_gate,
                    internal_manual_query_service_factory,
                    internal_guideline_capability_searcher_factory,
                    shared_ml_service,
                    ml_prediction_executor_factory,
                    route_timeout_seconds,
                )
            supervisor = build_conversation_agent_supervisor(
                self,
                execution_gate,
                internal_manual_query_service_factory,
                route_resolver=route_resolver,
                admission=admission,
                capability_routing_enabled=supervisor_routing_enabled,
                data_platform=self._data_platform,
                internal_guideline_capability_searcher_factory=(
                    internal_guideline_capability_searcher_factory
                ),
                ml_prediction_service_factory=(
                    (lambda: shared_ml_service)
                    if shared_ml_service is not None
                    else None
                ),
                ml_prediction_executor_factory=ml_prediction_executor_factory,
            )
            route_lease_stop = asyncio.Event()
            route_lease_lost = asyncio.Event()
            renew_lease = getattr(self._repo, "renew_lease", None)
            route_lease_task = (
                asyncio.create_task(
                    self._renew_command_lease(
                        request.conversation_id,
                        admission.command_id,
                        route_lease_stop,
                        route_lease_lost,
                    ),
                    name=f"conversation-agent-route-lease-{admission.command_id}",
                )
                if callable(renew_lease)
                else None
            )
            route_lease_closed = False

            async def _stop_route_lease() -> None:
                """route node 전용 heartbeat를 AgentPort 실행 전에 한 번만 종료한다."""

                nonlocal route_lease_closed
                if route_lease_closed:
                    return
                route_lease_closed = True
                route_lease_stop.set()
                if route_lease_task is not None:
                    route_lease_task.cancel()
                    try:
                        await route_lease_task
                    except asyncio.CancelledError:
                        pass

            async def _after_route(routing: Any) -> None:
                """route 소유권을 검증한 뒤 선택 Agent의 lease 구간으로 넘긴다."""

                if route_lease_lost.is_set():
                    raise AgentDispatchError(
                        "AGENT_ROUTE_LEASE_LOST",
                        "Agent route 결정 중 command 소유권을 잃었습니다.",
                        state=routing.state,
                    )
                await _stop_route_lease()

            runtime = LangGraphAgentRuntime(
                supervisor,
                route_timeout_seconds=route_timeout_seconds,
                after_route=_after_route,
            )
            try:
                outcome = await runtime.execute(admitted_request)
            finally:
                await _stop_route_lease()
            result = outcome.result
            return result.payload
        except asyncio.CancelledError as error:
            await self._release_agent_dispatch_failure(
                request.conversation_id,
                admission,
                error,
            )
            raise
        except Exception as error:
            await self._release_agent_dispatch_failure(
                request.conversation_id,
                admission,
                error,
            )
            raise

    async def _execute_composite_agent_plan(
        self,
        materialized_plan: Any,
        admission: _AdmittedConversationCommand,
        execution_gate: ConcurrentExecutionGate,
        internal_manual_query_service_factory: Callable[[], Any],
        internal_guideline_capability_searcher_factory: Callable[[], Any]
        | None,
        shared_ml_service: Any | None,
        ml_prediction_executor_factory: Callable[[Any], Any] | None,
        route_timeout_seconds: float,
    ) -> dict[str, Any]:
        """여러 Agent의 검증·실행 결과를 대표 Turn 하나에 원자적으로 확정한다."""

        from app.ports.agent import AgentKind
        from app.services.agent_supervisor import AgentDispatchError
        from app.services.composite_agent_execution import (
            CompositeExecutionAugmentation,
        )
        from app.services.conversation_agent_registry import (
            build_conversation_agent_supervisor,
        )
        from app.services.internal_manual_query import InternalManualQuery
        from app.services.mcp_agent_tools import MCPMLPredictionExecutor
        from app.services.analysis import analysis_progress
        from app.services.supervisor_planner import MaterializedSupervisorPlan

        if not isinstance(materialized_plan, MaterializedSupervisorPlan) or not (
            materialized_plan.is_composite
        ):
            raise AgentDispatchError(
                "AGENT_COMPOSITE_PLAN_INVALID",
                "복합 Agent 계획 계약이 올바르지 않습니다.",
            )
        requests = materialized_plan.requests
        by_agent = {request.target_agent: request for request in requests}
        if len(by_agent) != len(requests) or None in by_agent:
            raise AgentDispatchError(
                "AGENT_COMPOSITE_PLAN_INVALID",
                "복합 Agent 계획의 실행 대상이 올바르지 않습니다.",
                evidence_refs=(materialized_plan.evidence_ref,),
            )

        primary_agent = (
            AgentKind.ANALYSIS_WORKFLOW
            if AgentKind.ANALYSIS_WORKFLOW in by_agent
            else AgentKind.INTERNAL_GUIDELINE
            if AgentKind.INTERNAL_GUIDELINE in by_agent
            else None
        )
        if primary_agent is None:
            raise AgentDispatchError(
                "AGENT_COMPOSITE_PLAN_INVALID",
                "복합 실행을 확정할 대표 Agent가 없습니다.",
                evidence_refs=(materialized_plan.evidence_ref,),
            )

        progress_tasks = tuple(
            (request.target_agent.value, request.task_objective or "")
            for request in requests
        )
        analysis_progress.start_agent_plan(
            admission.context.trace_id,
            admission.context.user_id,
            admission.context.role,
            admission.context.request_id,
            progress_tasks,
        )

        shared_rag_service = (
            internal_manual_query_service_factory()
            if AgentKind.INTERNAL_GUIDELINE in by_agent
            else None
        )
        rag_service_factory = (
            (lambda: shared_rag_service)
            if shared_rag_service is not None
            else internal_manual_query_service_factory
        )
        supervisor = build_conversation_agent_supervisor(
            self,
            execution_gate,
            rag_service_factory,
            admission=admission,
            capability_routing_enabled=True,
            data_platform=self._data_platform,
            internal_guideline_capability_searcher_factory=(
                internal_guideline_capability_searcher_factory
            ),
            ml_prediction_service_factory=(
                (lambda: shared_ml_service)
                if shared_ml_service is not None
                else None
            ),
            ml_prediction_executor_factory=ml_prediction_executor_factory,
        )

        route_lease_stop = asyncio.Event()
        route_lease_lost = asyncio.Event()
        renew_lease = getattr(self._repo, "renew_lease", None)
        route_lease_task = (
            asyncio.create_task(
                self._renew_command_lease(
                    requests[0].conversation_id,
                    admission.command_id,
                    route_lease_stop,
                    route_lease_lost,
                ),
                name=f"conversation-composite-route-lease-{admission.command_id}",
            )
            if callable(renew_lease)
            else None
        )

        async def _stop_route_lease() -> None:
            route_lease_stop.set()
            if route_lease_task is not None:
                route_lease_task.cancel()
                try:
                    await route_lease_task
                except asyncio.CancelledError:
                    pass

        active_agent: AgentKind | None = None
        try:
            routings: dict[AgentKind, Any] = {}
            evidence_refs: list[str] = []
            for request in requests:
                routing = await supervisor.route_with_state(
                    request,
                    timeout_seconds=route_timeout_seconds,
                )
                if route_lease_lost.is_set():
                    raise AgentDispatchError(
                        "AGENT_ROUTE_LEASE_LOST",
                        "복합 Agent route 결정 중 command 소유권을 잃었습니다.",
                        state=routing.state,
                    )
                await supervisor.readiness_for(request, routing.decision.agent)
                routings[routing.decision.agent] = routing
                evidence_refs.extend(routing.decision.evidence_refs)

            rag_response: dict[str, Any] | None = None
            if (
                AgentKind.INTERNAL_GUIDELINE in by_agent
                and primary_agent is not AgentKind.INTERNAL_GUIDELINE
            ):
                rag_request = by_agent[AgentKind.INTERNAL_GUIDELINE]
                if shared_rag_service is None:
                    raise AgentDispatchError(
                        "AGENT_PORT_NOT_READY",
                        "RAG 실행 서비스가 구성되지 않았습니다.",
                    )
                active_agent = AgentKind.INTERNAL_GUIDELINE
                analysis_progress.record_agent(
                    admission.context.request_id,
                    active_agent.value,
                    "RUNNING",
                )
                rag_response = dict(
                    await shared_rag_service.execute(
                        InternalManualQuery(
                            # 복합 계획에서는 SQL·ML 요구를 제거한 Supervisor의 RAG 전용
                            # objective를 사용한다. 명시 RAG route는 기존 원문 계약을 유지한다.
                            question=(
                                rag_request.task_objective
                                or rag_request.command.user_message
                            ),
                            mode="DOCUMENT_ONLY",
                            conversation_id=rag_request.conversation_id,
                            expected_head_turn_id=(
                                rag_request.command.expected_head_turn_id
                            ),
                            expected_head_turn_id_is_set=True,
                            inherit_previous_context=False,
                        ),
                        admission.context,
                        persist_turn=False,
                    )
                )
                analysis_progress.record_agent(
                    admission.context.request_id,
                    active_agent.value,
                    "SUCCEEDED",
                )
                active_agent = None
                rag_response.pop("turn_id", None)
                rag_tool_run_id = rag_response.get("mcp_tool_run_id")
                if isinstance(rag_tool_run_id, str) and rag_tool_run_id:
                    evidence_refs.append(f"mcp-tool-run:{rag_tool_run_id}")

            ml_prediction: dict[str, Any] | None = None
            if AgentKind.ML_PREDICTION in by_agent:
                ml_request = by_agent[AgentKind.ML_PREDICTION]
                invocation = ml_request.invocation
                if shared_ml_service is None or invocation is None:
                    raise AgentDispatchError(
                        "AGENT_PORT_NOT_READY",
                        "ML 예측 실행 서비스가 구성되지 않았습니다.",
                    )
                if ml_prediction_executor_factory is not None:
                    ml_tool_executor = ml_prediction_executor_factory(
                        shared_ml_service
                    )
                else:
                    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()
                    if not database_url:
                        raise AgentDispatchError(
                            "AGENT_PORT_NOT_READY",
                            "ML MCP 실행에 APP_RUNTIME_DATABASE_URL이 필요합니다.",
                        )
                    ml_tool_executor = MCPMLPredictionExecutor(
                        database_url,
                        shared_ml_service,
                    )
                try:
                    active_agent = AgentKind.ML_PREDICTION
                    analysis_progress.record_agent(
                        admission.context.request_id,
                        active_agent.value,
                        "RUNNING",
                    )
                    ml_prediction = dict(
                        await ml_tool_executor.execute(
                            {
                                "property_id": invocation.property_id,
                                "as_of": invocation.as_of.isoformat(),
                                "horizon_days": invocation.horizon_days,
                            },
                            subject_id=admission.context.user_id,
                            role=admission.context.role,
                            trace_id=admission.context.trace_id,
                        )
                    )
                except asyncio.CancelledError:
                    raise
                except ValueError as error:
                    raise AgentDispatchError(
                        "AGENT_ROUTE_NOT_RESOLVED",
                        "요청한 ML 예측 범위는 현재 지원되지 않습니다.",
                    ) from error
                except Exception as error:
                    raise AgentDispatchError(
                        "AGENT_PORT_NOT_READY",
                        "ML 예측 실행 서비스를 확인하지 못했습니다.",
                    ) from error
                analysis_progress.record_agent(
                    admission.context.request_id,
                    active_agent.value,
                    "SUCCEEDED",
                )
                active_agent = None
                ml_tool_run_id = ml_prediction.get("mcp_tool_run_id")
                if isinstance(ml_tool_run_id, str) and ml_tool_run_id:
                    evidence_refs.append(f"mcp-tool-run:{ml_tool_run_id}")

            if route_lease_lost.is_set():
                raise AgentDispatchError(
                    "AGENT_ROUTE_LEASE_LOST",
                    "복합 Agent 준비 중 command 소유권을 잃었습니다.",
                    evidence_refs=tuple(dict.fromkeys(evidence_refs)),
                )
            await _stop_route_lease()

            augmentation = CompositeExecutionAugmentation(
                primary_agent=primary_agent,
                agents=tuple(request.target_agent for request in requests),
                plan_ref=materialized_plan.evidence_ref,
                evidence_refs=tuple(dict.fromkeys(evidence_refs)),
                rag_response=rag_response,
                ml_prediction=ml_prediction,
            )
            execution_supervisor = build_conversation_agent_supervisor(
                self,
                execution_gate,
                rag_service_factory,
                admission=admission,
                capability_routing_enabled=True,
                data_platform=self._data_platform,
                internal_guideline_capability_searcher_factory=(
                    internal_guideline_capability_searcher_factory
                ),
                ml_prediction_service_factory=(
                    (lambda: shared_ml_service)
                    if shared_ml_service is not None
                    else None
                ),
                ml_prediction_executor_factory=ml_prediction_executor_factory,
                composite_augmentation=augmentation,
            )
            active_agent = primary_agent
            analysis_progress.record_agent(
                admission.context.request_id,
                active_agent.value,
                "RUNNING",
            )
            outcome = await execution_supervisor.execute_routed_with_state(
                by_agent[primary_agent],
                routings[primary_agent],
            )
            analysis_progress.record_agent(
                admission.context.request_id,
                active_agent.value,
                "SUCCEEDED",
            )
            analysis_progress.finish(
                admission.context.request_id,
                AnalysisStatus.SUCCEEDED,
            )
            active_agent = None
            return outcome.result.payload
        except asyncio.CancelledError:
            if active_agent is not None:
                analysis_progress.record_agent(
                    admission.context.request_id,
                    active_agent.value,
                    "CANCELLED",
                )
            analysis_progress.finish(
                admission.context.request_id,
                AnalysisStatus.CANCELLED,
            )
            raise
        except Exception:
            if active_agent is not None:
                analysis_progress.record_agent(
                    admission.context.request_id,
                    active_agent.value,
                    "FAILED",
                )
            analysis_progress.finish(
                admission.context.request_id,
                AnalysisStatus.FAILED,
            )
            raise
        finally:
            await _stop_route_lease()

    async def execute_internal_guideline_command(
        self,
        conversation_id: UUID,
        payload: dict[str, Any],
        context: RequestContext,
        executor: Callable[[RequestContext], Awaitable[dict[str, Any]]],
        *,
        admission: _AdmittedConversationCommand | None = None,
        supervisor_plan_ref: str | None = None,
        composite_augmentation: Any | None = None,
    ) -> dict[str, Any]:
        """RAG Agent를 기존 command idempotency·CAS·lease·terminal 계약으로 실행한다."""

        command = ConversationCommandRequest.model_validate(payload)
        explicit_route = command.requested_route == "INTERNAL_GUIDELINE"
        planned_route = (
            supervisor_plan_ref is not None
            and command.requested_route is None
            and command.ml_prediction is None
        )
        if explicit_route == planned_route:
            raise ValueError(
                "내부지침 command에는 명시 route 또는 검증된 Supervisor 계획 하나가 필요합니다."
            )
        if composite_augmentation is not None:
            from app.ports.agent import AgentKind
            from app.services.composite_agent_execution import (
                CompositeExecutionAugmentation,
            )

            if (
                not isinstance(
                    composite_augmentation,
                    CompositeExecutionAugmentation,
                )
                or composite_augmentation.primary_agent
                is not AgentKind.INTERNAL_GUIDELINE
                or composite_augmentation.plan_ref != supervisor_plan_ref
            ):
                raise ValueError("RAG 복합 실행 계약이 올바르지 않습니다.")
        early_result: dict[str, Any] | None = None
        if admission is None:
            admission, early_result = await self._admit_command(
                conversation_id,
                command,
                context,
            )
        else:
            self._validate_admitted_command(
                conversation_id,
                command,
                context,
                admission,
            )
        if early_result is not None:
            return await self._hydrate_internal_guideline_replay(
                conversation_id,
                context.user_id,
                early_result,
            )
        if admission is None:
            raise RuntimeError("내부지침 command admission 결과가 없습니다.")

        previous_turns = await self._repo.list_turns(conversation_id)
        lease_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        renew_lease = getattr(self._repo, "renew_lease", None)
        lease_task = (
            asyncio.create_task(
                self._renew_command_lease(
                    conversation_id,
                    admission.command_id,
                    lease_stop,
                    lease_lost,
                ),
                name=f"conversation-rag-lease-{admission.command_id}",
            )
            if callable(renew_lease)
            else None
        )

        async def _release_failure(error_data: dict[str, Any]) -> None:
            try:
                await self._repo.release_lease_on_failure(
                    conversation_id,
                    admission.command_id,
                    error_data,
                )
            except Exception:
                logger.exception("RAG conversation command failure release failed")

        try:
            rag_response = dict(await executor(admission.context))
            rag_response.pop("turn_id", None)
            if lease_lost.is_set():
                raise RuntimeError("내부지침 command lease 소유권을 잃었습니다.")
            turn_id = uuid4()
            composite_slots = (
                composite_augmentation.resolved_slots()
                if composite_augmentation is not None
                else {}
            )
            terminal_writer = (
                composite_augmentation.chain_terminal_writer(None)
                if composite_augmentation is not None
                else None
            )
            await self._repo.commit_turn(
                conversation_id=conversation_id,
                command_id=admission.command_id,
                turn_id=turn_id,
                turn_index=len(previous_turns),
                user_message=command.user_message,
                route="INTERNAL_GUIDELINE",
                source_turn_ids=[],
                request_id=None,
                artifact_id=None,
                view_spec_id=None,
                report_definition_id=None,
                resolved_slots={"rag": rag_response, **composite_slots},
                product_release_id=admission.product_release_id,
                permission_snapshot_id=admission.permission_snapshot_id,
                semantic_release_id=admission.semantic_release_id,
                terminal_writer=terminal_writer,
            )
            updated_turns = await self._repo.list_turns(conversation_id)
            target_turn = next(
                (turn for turn in updated_turns if turn["turn_id"] == turn_id),
                None,
            )
            if target_turn is None:
                raise RuntimeError("확정된 내부지침 Turn을 다시 조회하지 못했습니다.")
            return {
                "status": "SUCCESS",
                "turn": target_turn,
                "conversation": await self._repo.get_conversation(
                    conversation_id,
                    admission.context.user_id,
                ),
                "rag_response": {
                    **rag_response,
                    "turn_id": str(turn_id),
                },
                "is_idempotent_replay": False,
                **(
                    composite_augmentation.public_fields()
                    if composite_augmentation is not None
                    else {}
                ),
            }
        except asyncio.CancelledError:
            await _release_failure(
                {
                    "type": "CancelledError",
                    "code": ErrorCode.QUERY_TIMEOUT.value,
                    "message": "내부지침 명령 실행이 취소되었습니다.",
                    "retryable": True,
                    "status_code": 504,
                }
            )
            raise
        except Exception as error:
            raw_code = getattr(error, "code", "CONVERSATION_COMMAND_FAILED")
            error_code = (
                raw_code.value if hasattr(raw_code, "value") else str(raw_code)
            )
            raw_status = getattr(error, "status_code", 503)
            status_code = raw_status if isinstance(raw_status, int) else 503
            public_error = hasattr(error, "code") and hasattr(error, "status_code")
            await _release_failure(
                {
                    "type": type(error).__name__,
                    "code": error_code,
                    "message": (
                        str(error)
                        if public_error
                        else "내부지침 명령 실행을 안전하게 종료했습니다."
                    ),
                    "retryable": status_code >= 500,
                    "required_action": (
                        "REQUEST_ACCESS"
                        if status_code == 403
                        else "MODIFY_REQUEST"
                        if status_code < 500
                        else "RETRY"
                    ),
                    "status_code": status_code,
                }
            )
            raise
        finally:
            lease_stop.set()
            if lease_task is not None:
                lease_task.cancel()
                try:
                    await lease_task
                except asyncio.CancelledError:
                    pass

    async def execute_ml_prediction_command(
        self,
        conversation_id: UUID,
        payload: dict[str, Any],
        context: RequestContext,
        executor: Callable[[RequestContext], Awaitable[dict[str, Any]]],
        persister: Callable[[Any, dict[str, Any]], Awaitable[None]] | None,
        *,
        admission: _AdmittedConversationCommand | None = None,
        supervisor_plan_ref: str | None = None,
    ) -> dict[str, Any]:
        """typed ML 예측과 Conversation Turn을 확정하고 legacy persister를 지원한다."""

        command = ConversationCommandRequest.model_validate(payload)
        explicit_route = (
            command.requested_route == "ML_PREDICTION"
            and command.ml_prediction is not None
        )
        planned_route = (
            supervisor_plan_ref is not None
            and command.requested_route is None
            and command.ml_prediction is None
        )
        if explicit_route == planned_route:
            raise ValueError(
                "ML command에는 명시 action 또는 검증된 Supervisor 계획 하나가 필요합니다."
            )
        early_result: dict[str, Any] | None = None
        if admission is None:
            admission, early_result = await self._admit_command(
                conversation_id,
                command,
                context,
            )
        else:
            self._validate_admitted_command(
                conversation_id,
                command,
                context,
                admission,
            )
        if early_result is not None:
            return await self._hydrate_ml_prediction_replay(
                conversation_id,
                context.user_id,
                early_result,
            )
        if admission is None:
            raise RuntimeError("ML command admission 결과가 없습니다.")

        previous_turns = await self._repo.list_turns(conversation_id)
        lease_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        renew_lease = getattr(self._repo, "renew_lease", None)
        lease_task = (
            asyncio.create_task(
                self._renew_command_lease(
                    conversation_id,
                    admission.command_id,
                    lease_stop,
                    lease_lost,
                ),
                name=f"conversation-ml-lease-{admission.command_id}",
            )
            if callable(renew_lease)
            else None
        )
        try:
            prediction = dict(await executor(admission.context))
            if lease_lost.is_set():
                raise RuntimeError("ML command lease 소유권을 잃었습니다.")

            terminal_writer = None
            if persister is not None:

                async def _write_ml_terminal(session: Any) -> None:
                    await persister(session, prediction)

                terminal_writer = _write_ml_terminal

            turn_id = uuid4()
            await self._repo.commit_turn(
                conversation_id=conversation_id,
                command_id=admission.command_id,
                turn_id=turn_id,
                turn_index=len(previous_turns),
                user_message=command.user_message,
                route="ML_PREDICTION",
                source_turn_ids=[],
                request_id=None,
                artifact_id=None,
                view_spec_id=None,
                report_definition_id=None,
                resolved_slots={"ml_prediction": prediction},
                product_release_id=admission.product_release_id,
                permission_snapshot_id=admission.permission_snapshot_id,
                semantic_release_id=admission.semantic_release_id,
                terminal_writer=terminal_writer,
            )
            updated_turns = await self._repo.list_turns(conversation_id)
            target_turn = next(
                (turn for turn in updated_turns if turn["turn_id"] == turn_id),
                None,
            )
            if target_turn is None:
                raise RuntimeError("확정된 ML 예측 Turn을 다시 조회하지 못했습니다.")
            return {
                "status": "SUCCESS",
                "turn": target_turn,
                "conversation": await self._repo.get_conversation(
                    conversation_id,
                    admission.context.user_id,
                ),
                "ml_prediction": prediction,
                "is_idempotent_replay": False,
            }
        except asyncio.CancelledError as error:
            await self._release_agent_dispatch_failure(
                conversation_id,
                admission,
                error,
            )
            raise
        except Exception as error:
            await self._release_agent_dispatch_failure(
                conversation_id,
                admission,
                error,
            )
            raise
        finally:
            lease_stop.set()
            if lease_task is not None:
                lease_task.cancel()
                try:
                    await lease_task
                except asyncio.CancelledError:
                    pass

    async def execute_command(
        self,
        conversation_id: UUID,
        payload: dict[str, Any],
        context: RequestContext,
        *,
        admission: _AdmittedConversationCommand | None = None,
        progress_sink: Callable[[object, object], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        analysis_gate: ConcurrentExecutionGate | None = None,
        analysis_queue_wait_seconds: float = 0.0,
        supervisor_plan_ref: str | None = None,
        task_objective: str | None = None,
        composite_augmentation: Any | None = None,
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
        command = ConversationCommandRequest.model_validate(payload)
        has_planned_execution = supervisor_plan_ref is not None
        if has_planned_execution != (task_objective is not None):
            raise ValueError(
                "분석 command의 Supervisor 계획 영수증과 objective가 일치하지 않습니다."
            )
        if task_objective is not None and not 1 <= len(task_objective.strip()) <= 240:
            raise ValueError("분석 command의 Supervisor objective가 올바르지 않습니다.")
        if composite_augmentation is not None:
            from app.ports.agent import AgentKind
            from app.services.composite_agent_execution import (
                CompositeExecutionAugmentation,
            )

            if (
                not isinstance(
                    composite_augmentation,
                    CompositeExecutionAugmentation,
                )
                or composite_augmentation.primary_agent
                is not AgentKind.ANALYSIS_WORKFLOW
                or composite_augmentation.plan_ref != supervisor_plan_ref
            ):
                raise ValueError("분석 복합 실행 계약이 올바르지 않습니다.")
        early_result: dict[str, Any] | None = None
        if admission is None:
            admission, early_result = await self._admit_command(
                conversation_id,
                command,
                context,
            )
        else:
            self._validate_admitted_command(
                conversation_id,
                command,
                context,
                admission,
            )
        if early_result is not None:
            return early_result
        if admission is None:
            raise RuntimeError("Conversation command admission 결과가 없습니다.")

        persisted_user_message = command.user_message
        user_message = task_objective.strip() if task_objective is not None else persisted_user_message
        context = admission.context
        command_id = admission.command_id
        current_product = admission.product_release_id
        current_permission = admission.permission_snapshot_id
        current_semantic = admission.semantic_release_id

        previous_turns: list[dict[str, Any]] = []
        analysis_repo: Any = None
        analysis_started = False
        model_budget = ModelCallBudget()
        lease_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        renew_lease = getattr(self._repo, "renew_lease", None)
        lease_task = (
            asyncio.create_task(
                self._renew_command_lease(
                    conversation_id,
                    command_id,
                    lease_stop,
                    lease_lost,
                ),
                name=f"conversation-lease-{command_id}",
            )
            if callable(renew_lease)
            else None
        )
        pipeline_cancel_check = cancel_check
        if lease_task is not None:
            pipeline_cancel_check = lambda: lease_lost.is_set() or bool(
                cancel_check and cancel_check()
            )

        async def _commit_command_failure(
            error_data: dict[str, Any],
            *,
            analysis_error_type: str,
        ) -> None:
            failure_committed = False
            if analysis_started and analysis_repo is not None:
                async def _write_analysis_failure(session: Any) -> None:
                    await analysis_repo.fail_run_in_session(
                        session,
                        context.request_id,
                        analysis_error_type,
                    )

                try:
                    await self._repo.commit_failed_turn(
                        conversation_id,
                        command_id,
                        uuid4(),
                        len(previous_turns),
                        persisted_user_message,
                        error_data,
                        request_id=context.request_id,
                        terminal_writer=_write_analysis_failure,
                    )
                    failure_committed = True
                except Exception as terminal_error:
                    logger.error(
                        "atomic conversation failure commit failed: type=%s",
                        type(terminal_error).__name__,
                    )
            if not failure_committed:
                await self._repo.release_lease_on_failure(
                    conversation_id,
                    command_id,
                    error_data,
                )

        async def _commit_scope_rejection(scope_reason: str) -> dict[str, Any]:
            """승인 capability에 매칭되지 않은 요청을 모델 호출 없이 고정 응답으로 닫는다."""

            turn_id = uuid4()
            await self._repo.commit_turn(
                conversation_id=conversation_id,
                command_id=command_id,
                turn_id=turn_id,
                turn_index=len(previous_turns),
                user_message=persisted_user_message,
                route="OUT_OF_SCOPE",
                source_turn_ids=[],
                request_id=None,
                artifact_id=None,
                view_spec_id=None,
                report_definition_id=None,
                resolved_slots={
                    "scope_rejection": {
                        "message": _OUT_OF_SCOPE_MESSAGE,
                        "reason": scope_reason,
                    }
                },
                product_release_id=current_product,
                permission_snapshot_id=current_permission,
                semantic_release_id=current_semantic,
                terminal_status="BLOCKED",
                reason_code=ErrorCode.DATA_ASSET_NOT_FOUND.value,
            )
            updated_turns = await self._repo.list_turns(conversation_id)
            latest_turn = next(
                turn for turn in updated_turns if turn["turn_id"] == turn_id
            )
            return {
                "status": "BLOCKED",
                "type": "OUT_OF_SCOPE",
                "code": ErrorCode.DATA_ASSET_NOT_FOUND.value,
                "message": _OUT_OF_SCOPE_MESSAGE,
                "retryable": False,
                "required_action": "MODIFY_REQUEST",
                "turn": latest_turn,
                "conversation": {
                    "conversation_id": str(conversation_id),
                    "head_turn_id": str(turn_id),
                    "turn_count": len(previous_turns) + 1,
                },
            }

        try:
            # 4. 이전 불변 턴 목록 조회
            previous_turns = await self._repo.list_turns(conversation_id)

            if _explicit_write_sql_intent(user_message):
                turn_id = uuid4()
                await self._repo.commit_turn(
                    conversation_id=conversation_id,
                    command_id=command_id,
                    turn_id=turn_id,
                    turn_index=len(previous_turns),
                    user_message=persisted_user_message,
                    route="ANALYSIS",
                    source_turn_ids=[],
                    request_id=None,
                    artifact_id=None,
                    view_spec_id=None,
                    report_definition_id=None,
                    resolved_slots={
                        "business_terms": ["SQL 쓰기"],
                        "metric_id": None,
                        "metric_ids": [],
                        "dimension_fields": [],
                        "user_filters": [],
                        "time_range": None,
                        "comparison_time_range": None,
                        "target_chart_type": None,
                        "analysis_operation": None,
                        "analysis_time_bucket": None,
                        "result_limit": None,
                        "ambiguity_status": "CLEAR",
                        "clarification_type": None,
                        "disambiguation_options": [],
                        "pending_user_message": None,
                        "is_inherited_metric": False,
                        "is_inherited_dimension": False,
                        "is_inherited_period": False,
                        "slot_provenance": {},
                        "change_set": [],
                        "analysis_plan_observation": {},
                    },
                    product_release_id=current_product,
                    permission_snapshot_id=current_permission,
                    semantic_release_id=current_semantic,
                    terminal_status="BLOCKED",
                    reason_code=ErrorCode.SQL_POLICY_BLOCKED.value,
                )
                updated_turns = await self._repo.list_turns(conversation_id)
                return {
                    "status": "BLOCKED",
                    "code": ErrorCode.SQL_POLICY_BLOCKED.value,
                    "message": "읽기 전용 분석에서는 SQL 쓰기 요청을 실행할 수 없습니다.",
                    "retryable": False,
                    "required_action": "MODIFY_REQUEST",
                    "turn": next(
                        turn for turn in updated_turns if turn["turn_id"] == turn_id
                    ),
                }

            # 5. Node 1 사전 발화 정규화 (DataHub 자산 검색)
            node1_res: dict[str, Any] = {}
            preflight_clarification: ContextBuildError | None = None
            action_signals = client_action_signals(payload)
            reuses_existing_result = action_signals.get("requested_route") in {
                "PRESENTATION",
                "REPORT_ACTION",
            }
            try:
                # 1차: user_message 원문으로 검색
                search_context = {
                    "role": (
                        context.role.value
                        if hasattr(context.role, "value")
                        else str(context.role)
                    ),
                    "product_release_id": current_product,
                    "semantic_release_id": current_semantic,
                }
                if reuses_existing_result:
                    # Typed Presentation/Report action은 이미 admission을 통과한 기존
                    # Artifact/View만 재사용한다. 새 Metric/기간 해석을 호출하면 불필요한
                    # clarification이나 metadata 장애가 zero-query action을 막을 수 있다.
                    assets = []
                else:
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
                if not reuses_existing_result and not assets:
                    last_turn = previous_turns[-1] if previous_turns else None
                    last_turn_slots = (
                        last_turn.get("resolved_slots", {}) if last_turn else {}
                    )
                    # OUT_OF_DATA_RANGE는 source/focus 자격이 없지만, 바로 다음
                    # 기간-only 수정에서 같은 승인 Asset을 다시 찾기 위한 검색 힌트는
                    # 제공할 수 있다. 이 값은 Node 1 후보 scope에만 쓰이며 resolver가
                    # 새 절대 기간을 독립적으로 확정하지 못하면 실행되지 않는다.
                    pending_range_metric_ids = (
                        tuple(
                            item
                            for item in (
                                last_turn_slots.get("metric_ids")
                                or (
                                    [last_turn_slots.get("metric_id")]
                                    if last_turn_slots.get("metric_id")
                                    else []
                                )
                            )
                            if isinstance(item, str) and item
                        )
                        if last_turn is not None
                        and last_turn.get("route") == "ANALYSIS"
                        and last_turn.get("terminal_status") == "BLOCKED"
                        and last_turn.get("reason_code")
                        == ErrorCode.OUT_OF_DATA_RANGE.value
                        else ()
                    )
                    last_analysis_metric_ids = pending_range_metric_ids or next(
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

                if reuses_existing_result:
                    node1_res = {}
                elif not assets:
                    raise NoEntitledAssetsError(
                        "conversation preflight found no entitled candidate"
                    )
                else:
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
                            analysis_time_bucket=last_analysis_slots.get(
                                "analysis_time_bucket"
                            ),
                            result_limit=last_analysis_slots.get("result_limit"),
                        )
                    # 직전 Metric 결합은 짧은 후속 발화의 자산 recall을 높이는 검색 전용 힌트다.
                    # 의도·생략 여부·새 주제 판정은 사용자가 실제로 쓴 원문을 기준으로 해야
                    # 하므로 모델 입력까지 보강 문자열로 바꾸지 않는다.
                    select_options: dict[str, Any] = {}
                    if "budget" in inspect.signature(
                        self._support.select_metric
                    ).parameters:
                        select_options["budget"] = model_budget
                    _, _nq, structured = await self._support.select_metric(
                        AnalysisRequest(question=user_message, resolved_slots=preflight_slots),
                        context,
                        candidate_set,
                        **select_options,
                    )
                    node1_res = structured
            except NoEntitledAssetsError:
                return await _commit_scope_rejection(
                    "NO_APPROVED_CAPABILITY_MATCH"
                )
            except ContextBuildError as error:
                # 지표·기간이 여러 갈래로 해석되는 상태다. 빈 신호로 계속 진행하면 같은
                # 모호성을 파이프라인에서 다시 만난다. 운영 resolver가 함께 반환한 확정
                # 슬롯은 clarification turn에 저장해 다음 선택이 같은 요청을 완결하게 한다.
                if error.code in {
                    ContextBuildErrorCode.METRIC_NOT_AVAILABLE,
                    ContextBuildErrorCode.OUT_OF_DATA_RANGE,
                    ContextBuildErrorCode.FILTER_VALUE_NOT_FOUND,
                    ContextBuildErrorCode.ANALYSIS_SHAPE_REQUIRED,
                }:
                    if error.code is ContextBuildErrorCode.METRIC_NOT_AVAILABLE:
                        public_code = ErrorCode.METRIC_NOT_AVAILABLE
                    elif error.code is ContextBuildErrorCode.OUT_OF_DATA_RANGE:
                        public_code = ErrorCode.OUT_OF_DATA_RANGE
                    elif error.code is ContextBuildErrorCode.FILTER_VALUE_NOT_FOUND:
                        public_code = ErrorCode.FILTER_VALUE_NOT_FOUND
                    else:
                        public_code = ErrorCode.CONTEXT_INCOMPLETE
                    public_error = {
                        "status": "BLOCKED",
                        "code": public_code.value,
                        "message": str(error),
                        "retryable": False,
                        "required_action": "MODIFY_REQUEST",
                    }
                    turn_id = uuid4()
                    partial_context = getattr(error, "partial_context", None)
                    blocked_slots = (
                        dict(partial_context)
                        if isinstance(partial_context, dict)
                        else {}
                    )
                    blocked_slots["business_terms"] = _source_business_terms(
                        blocked_slots
                    )
                    blocked_slots["ambiguity_status"] = "CLEAR"
                    await self._repo.commit_turn(
                        conversation_id=conversation_id,
                        command_id=command_id,
                        turn_id=turn_id,
                        turn_index=len(previous_turns),
                        user_message=persisted_user_message,
                        route="ANALYSIS",
                        source_turn_ids=[],
                        request_id=None,
                        artifact_id=None,
                        view_spec_id=None,
                        report_definition_id=None,
                        resolved_slots=blocked_slots,
                        product_release_id=current_product,
                        permission_snapshot_id=current_permission,
                        semantic_release_id=current_semantic,
                        terminal_status="BLOCKED",
                        reason_code=public_code.value,
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
            node1_res = {**node1_res, **action_signals}
            if (
                preflight_clarification is None
                and not action_signals
                and node1_res.get("metric_resolution") in {"missing", "unsupported"}
                and node1_res.get("is_elliptical") is not True
                and node1_res.get("requested_route")
                not in {"PRESENTATION", "REPORT_ACTION"}
            ):
                return await _commit_scope_rejection(
                    "NO_APPROVED_METRIC_MATCH"
                )

            # 6. 결정론적 슬롯/시간 리졸버로 슬롯 및 라우트 확정
            slots: ResolvedTurnSlots = ConversationSlotResolver.resolve(
                user_message=persisted_user_message,
                node1_output=node1_res,
                previous_turns=previous_turns,
                as_of=context.as_of,
                timezone_str=context.timezone,
            )
            if (
                preflight_clarification is not None
                and (
                    _clarification_resolved_by_inheritance(
                        preflight_clarification,
                        slots,
                    )
                    or _clarification_resolved_by_range_correction(
                        preflight_clarification,
                        slots,
                        previous_turns,
                    )
                )
            ):
                preflight_clarification = None

            if (
                preflight_clarification is not None
                and preflight_clarification.code
                is ContextBuildErrorCode.INVALID_METRIC
                and not action_signals
                and node1_res.get("metric_resolution") == "missing"
                and node1_res.get("is_elliptical") is not True
                and node1_res.get("requested_route")
                not in {"PRESENTATION", "REPORT_ACTION"}
            ):
                return await _commit_scope_rejection(
                    "NO_APPROVED_METRIC_MATCH"
                )

            turn_id = uuid4()
            turn_index = len(previous_turns)
            request_id = None
            artifact_id = None
            view_spec_id = None
            report_def_id = None
            analysis_resp = None
            terminal_writer = None
            view_spec = None
            route_block_message: str | None = None
            execution: dict[str, Any] = {}

            # 7. 3대 라우트 분기 실행
            if slots.route == "ANALYSIS" and preflight_clarification is None:
                # 라우트 1: ANALYSIS (실제 데이터 쿼리 파이프라인 실행)
                analysis_gate_acquired = False
                lifecycle_bound = False
                bind_query_lifecycle = None
                analysis_repo = None

                if analysis_gate is not None:
                    analysis_gate_acquired = await analysis_gate.acquire(
                        analysis_queue_wait_seconds
                    )
                    if not analysis_gate_acquired:
                        rate_limited = {
                            "type": "RateLimited",
                            "status": "BUSY",
                            "code": ErrorCode.RATE_LIMITED.value,
                            "message": "동시 분석은 최대 2건까지 실행할 수 있습니다.",
                            "retryable": True,
                            "required_action": "RETRY",
                        }
                        await _commit_command_failure(
                            rate_limited,
                            analysis_error_type="RECOVERY",
                        )
                        return rate_limited

                async def _admit_analysis_run(
                    admission_context: RequestContext,
                ) -> None:
                    nonlocal analysis_started, lifecycle_bound
                    if analysis_repo is None or analysis_started:
                        return
                    await analysis_repo.begin_request(
                        user_message,
                        {},
                        admission_context,
                    )
                    analysis_started = True
                    if not callable(bind_query_lifecycle):
                        return

                    async def _record_query_lifecycle(event: dict[str, Any]) -> None:
                        await analysis_repo.record_query_lifecycle(
                            admission_context.request_id,
                            event,
                        )

                    bind_query_lifecycle(_record_query_lifecycle)
                    lifecycle_bound = True

                async def _persist_context_receipt(
                    receipt_context: RequestContext,
                    package: Any,
                ) -> None:
                    if analysis_repo is None or not analysis_started:
                        raise RuntimeError("Analysis Run admission이 완료되지 않았습니다.")
                    await analysis_repo.persist_context_receipt(
                        receipt_context,
                        package,
                    )

                try:
                    analysis_req = build_structured_analysis_request(
                        user_message,
                        slots,
                    )
                    analysis_repo = self._get_analysis_repository(context)
                    bind_query_lifecycle = getattr(
                        self._data_platform,
                        "bind_query_lifecycle",
                        None,
                    )
                    submit_parameters = inspect.signature(
                        self._submit_analysis
                    ).parameters
                    submit_options: dict[str, Any] = {}
                    if "execution_sink" in submit_parameters:
                        submit_options["execution_sink"] = execution.update
                    if "progress_sink" in submit_parameters:
                        submit_options["progress_sink"] = progress_sink
                    if "cancel_check" in submit_parameters:
                        submit_options["cancel_check"] = pipeline_cancel_check
                    if "model_budget" in submit_parameters:
                        submit_options["model_budget"] = model_budget
                    if analysis_repo is not None:
                        if "run_admission_sink" not in submit_parameters:
                            raise RuntimeError(
                                "analysis submitter must support deferred Run admission"
                            )
                        if "context_receipt_sink" not in submit_parameters:
                            raise RuntimeError(
                                "analysis submitter must support runtime Context receipts"
                            )
                        submit_options["run_admission_sink"] = _admit_analysis_run
                        submit_options["context_receipt_sink"] = _persist_context_receipt
                    analysis_resp = await self._submit_analysis(
                        analysis_req,
                        context,
                        **submit_options,
                    )
                finally:
                    if lifecycle_bound and callable(bind_query_lifecycle):
                        bind_query_lifecycle(None)
                    if analysis_gate_acquired:
                        analysis_gate.release()

                artifact_id = extract_artifact_id(analysis_resp)
                request_id = context.request_id if analysis_started else None
                if analysis_started and analysis_repo is not None and analysis_resp is not None:
                    async def _write_analysis_terminal(session: Any) -> None:
                        await analysis_repo.finish_run_in_session(
                            session,
                            context.request_id,
                            analysis_resp,
                            execution,
                        )

                    terminal_writer = _write_analysis_terminal

            elif slots.route == "PRESENTATION":
                # 라우트 2: PRESENTATION (Trino 쿼리 0건 실행, 동일 Artifact에 대한 ViewSpec 생성)
                source_ids = set(slots.source_turn_ids)
                target_turn = next(
                    (
                        turn
                        for turn in reversed(previous_turns)
                        if str(turn.get("turn_id")) in source_ids
                        and ConversationSlotResolver.is_resolved_analysis_turn(turn)
                    ),
                    None,
                )
                target_artifact_id = (
                    target_turn.get("artifact_id") if target_turn else None
                )
                if not target_artifact_id:
                    raise ValueError("시각화를 전환할 선행 분석 결과(Artifact)가 없습니다.")

                view_spec_id = uuid4()
                artifact_id = target_artifact_id
                try:
                    view_spec = _presentation_view_contract(
                        target_turn,
                        slots.target_chart_type or "TABLE",
                    )
                except ValueError as error:
                    # A renderer request must not escape as an untyped command
                    # failure after the source Artifact was already resolved.
                    # Preserve the immutable source lineage, commit a terminal
                    # BLOCKED Turn, and leave both focus pointers unchanged.
                    view_spec_id = None
                    view_spec = None
                    route_block_message = str(error)

            elif slots.route == "REPORT_ACTION":
                # 라우트 3: REPORT_ACTION (Trino 쿼리 0건 실행, 선행 Artifact들을 Report Draft에 연결)
                report_repo = self._get_report_repository(context)
                report_plan = await plan_report_action(report_repo, previous_turns)
                report_def_id = report_plan.report_definition_id
                artifact_id = report_plan.artifact_id

                async def _write_report_terminal(session: Any) -> None:
                    await apply_report_action_plan(
                        report_repo,
                        report_plan,
                        session,
                    )

                terminal_writer = _write_report_terminal

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
            business_terms = _business_terms_for_turn(node1_res, last_slots, slots)
            analysis_observation = _safe_analysis_observation(execution)
            ambiguity_status = "NEEDS_CLARIFICATION" if is_clarification else (
                "RESOLVED" if last_slots.get("ambiguity_status") == "NEEDS_CLARIFICATION" else "CLEAR"
            )
            terminal_status, reason_code = (
                _analysis_terminal(analysis_resp)
                if analysis_resp is not None
                else ("SUCCEEDED", None)
            )
            if is_clarification:
                terminal_status, reason_code = "BLOCKED", "NEEDS_CLARIFICATION"
            elif route_block_message is not None:
                terminal_status = "BLOCKED"
                reason_code = ErrorCode.PRESENTATION_NOT_SUPPORTED.value
            if (
                slots.route == "ANALYSIS"
                and terminal_status == "SUCCEEDED"
                and artifact_id is not None
            ):
                view_spec_id = uuid4()
                view_spec = _view_contract(
                    analysis_resp,
                    artifact_id,
                    slots.target_chart_type,
                )
            clarifies_turn_id = (
                UUID(str(previous_turns[-1]["turn_id"]))
                if previous_turns
                and (
                    last_slots.get("ambiguity_status") == "NEEDS_CLARIFICATION"
                    or previous_turns[-1].get("reason_code")
                    == ErrorCode.OUT_OF_DATA_RANGE.value
                )
                and not is_clarification
                else None
            )

            composite_slots: dict[str, Any] = {}
            composite_public: dict[str, Any] = {}
            if composite_augmentation is not None and terminal_status == "SUCCEEDED":
                composite_slots = composite_augmentation.resolved_slots()
                composite_public = composite_augmentation.public_fields()
                terminal_writer = composite_augmentation.chain_terminal_writer(
                    terminal_writer
                )

            # 8. 단일 DB 트랜잭션으로 Turn 영속화 및 Lease 해제
            await self._repo.commit_turn(
                conversation_id=conversation_id,
                command_id=command_id,
                turn_id=turn_id,
                turn_index=turn_index,
                user_message=persisted_user_message,
                route=slots.route,
                source_turn_ids=list(slots.source_turn_ids),
                request_id=request_id,
                artifact_id=artifact_id,
                view_spec_id=view_spec_id,
                report_definition_id=report_def_id,
                resolved_slots={
                    "business_terms": business_terms,
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
                    "analysis_time_bucket": slots.analysis_time_bucket,
                    "result_limit": slots.result_limit,
                    "ambiguity_status": ambiguity_status,
                    "clarification_type": clarification_type or last_slots.get("clarification_type"),
                    "disambiguation_options": [
                        opt.model_dump(mode="json") if hasattr(opt, "model_dump") else opt
                        for opt in disambiguation_options
                    ] if is_clarification else [],
                    "pending_user_message": (
                        persisted_user_message if is_clarification else None
                    ),
                    "is_inherited_metric": slots.is_inherited_metric,
                    "is_inherited_dimension": slots.is_inherited_dimension,
                    "is_inherited_period": slots.is_inherited_period,
                    "slot_provenance": _slot_provenance(slots),
                    "change_set": [
                        {
                            "field": change.field,
                            "operation": change.op.value,
                            "value": change.value,
                        }
                        for change in slots.change_set
                    ],
                    "analysis_plan_observation": analysis_observation,
                    **composite_slots,
                },
                product_release_id=current_product,
                permission_snapshot_id=current_permission,
                semantic_release_id=current_semantic,
                terminal_writer=terminal_writer,
                terminal_status=terminal_status,
                reason_code=reason_code,
                clarifies_turn_id=clarifies_turn_id,
                view_spec=view_spec,
            )

            # 9. 수화(Hydration)된 최신 턴 목록 반환
            updated_turns = await self._repo.list_turns(conversation_id)
            latest_turn = next((t for t in updated_turns if t["turn_id"] == turn_id), None)

            return {
                "status": (
                    "CLARIFICATION_REQUIRED"
                    if is_clarification
                    else "SUCCESS"
                    if terminal_status == "SUCCEEDED"
                    else terminal_status
                ),
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
                "code": (
                    ErrorCode.CONTEXT_INCOMPLETE.value
                    if is_clarification
                    else reason_code
                ),
                "message": (
                    "분석을 시작하려면 분석할 기간을 함께 입력해 주세요."
                    if clarification_type == "period"
                    else "분석할 지표를 확정하지 못했습니다. 하나의 지표를 선택하거나 질문에 포함해 주세요."
                ) if is_clarification else route_block_message,
                "clarification_type": clarification_type if is_clarification else None,
                "retryable": False if is_clarification else None,
                "required_action": (
                    "PROVIDE_CONTEXT"
                    if is_clarification
                    else "MODIFY_REQUEST"
                    if route_block_message is not None
                    else None
                ),
                "suggestions": list(
                    getattr(preflight_clarification, "suggestions", ()) or ()
                ) if preflight_clarification is not None else [],
                "analysis_response": analysis_resp.model_dump(mode="json") if analysis_resp and hasattr(analysis_resp, "model_dump") else None,
                **composite_public,
            }

        except asyncio.CancelledError:
            await _commit_command_failure(
                {
                    "type": "TimeoutError",
                    "code": ErrorCode.QUERY_TIMEOUT.value,
                    "message": "분석 명령의 전체 실행 시간이 초과되었습니다.",
                    "retryable": True,
                },
                analysis_error_type="QUERY",
            )
            raise
        except Exception as error:
            error_data = {
                "type": type(error).__name__,
                "code": "CONVERSATION_COMMAND_FAILED",
                "message": "대화 명령 실행을 안전하게 종료했습니다.",
                "retryable": True,
            }
            await _commit_command_failure(
                error_data,
                analysis_error_type="RECOVERY",
            )
            raise
        finally:
            lease_stop.set()
            if lease_task is not None:
                lease_task.cancel()
                try:
                    await lease_task
                except asyncio.CancelledError:
                    pass
