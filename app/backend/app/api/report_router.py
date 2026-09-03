"""보고서 draft·승인 문서·run·schedule·assistant 명령을 역할별 repository/service에 연결한다."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
from inspect import isawaitable
import json
import logging
import math
import os
import re
import threading
from typing import Annotated, Any, Awaitable, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse

from app.api.report_router_support import (
    _artifact_table_snapshot,
    _artifact_visible_views,
    _document_response,
    approve_report_version as _approve_report_version,
    build_execution_service as _build_execution_service,
    build_report_router as _build_report_router,
    create_artifact_draft as _create_artifact_draft,
    final_html_response as _final_html_response,
    final_pdf_response as _final_pdf_response,
    report_artifact_response as _report_artifact_response,
    report_admin_context,
    report_draft_context,
)
from app.authorization import has_capability
from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    Capability,
    ErrorResponse,
    RequestContext,
)
from app.report_contracts import (
    REPORT_MAX_BLOCKS,
    ApproveReportVersionRequest,
    CreateReportAssistantSessionRequest,
    CreateManualRunRequest,
    CreateReportDefinitionRequest,
    CreateReportFromArtifactRequest,
    CreateReportScheduleRequest,
    ManualRunCommandResponse,
    ReplaceReportBlocksRequest,
    ReportDefinitionListResponse,
    ReportDefinitionLifecycleResponse,
    ReportDefinitionPermanentDeleteResponse,
    ReportDefinitionResponse,
    ReportDocumentResponse,
    ReportArtifactResponse,
    ReportRunListResponse,
    ReportRunResponse,
    ReportAssistantAnalysisPlan,
    ReportAssistantApprovalRequest,
    ReportAssistantPatchApprovalRequest,
    ReportAssistantMessageRequest,
    ReportAssistantPatch,
    ReportAssistantProposalResponse,
    ReportAssistantReviewFinding,
    ReportAssistantReviewRequest,
    ReportAssistantReviewResponse,
    ReportAssistantSessionResponse,
    ReportAssistantEvaluationResponse,
    ReportAssistantExternalTransferConsentRequest,
    ReportAssistantExternalTransferConsentResponse,
    ReportAssistantExternalTransferDisclosureResponse,
    ReportAssistantExternalTransferErrorResponse,
    ReportAssistantFailureListResponse,
    ReportAssistantOperationsSummaryResponse,
    ReportAssistantRequiredAction,
    ReportScheduleListResponse,
    ReportScheduleResponse,
    RunDueReportScheduleResponse,
    UpdateReportScheduleRequest,
    report_assistant_retry_policy,
)
from src.report.domain import (
    MAX_REPORT_BLOCK_CONTENT_LENGTH,
    MAX_REPORT_BLOCK_HEIGHT,
    MAX_REPORT_BLOCK_ID_LENGTH,
    MAX_REPORT_BLOCK_REFERENCE_ID_LENGTH,
    MAX_REPORT_BLOCK_TITLE_LENGTH,
    MAX_REPORT_LAYOUT_ROWS,
)


report_router = APIRouter()
logger = logging.getLogger(__name__)


class _ReportAssistantPageRenderError(RuntimeError):
    """후보 페이지 layout 실패를 모델·patch 계약 오류와 분리한다."""


async def _consented_assistant_model_invocation(
    repository: Any,
    *,
    assistant_request_id: str,
    node: str,
    payload: dict[str, object],
    session: dict[str, Any],
    artifacts: tuple[dict[str, Any], ...],
    approved_new_analysis_artifact: bool = False,
) -> Any:
    """동의 gate를 먼저 통과한 뒤 정확한 provider 요청 비용 preflight를 수행한다."""

    from app.adapters.report_assistant import prepare_report_assistant_model_invocation
    from app.services.report_assistant_external_transfer import (
        ExternalTransferConsentRequired,
        authorize_report_assistant_transfer,
    )

    try:
        authorization = await authorize_report_assistant_transfer(
            repository,
            assistant_request_id=assistant_request_id,
            node=node,
            payload=payload,
            session=session,
            artifacts=artifacts,
            approved_new_analysis_artifact=approved_new_analysis_artifact,
        )
    except ExternalTransferConsentRequired as error:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "EXTERNAL_TRANSFER_CONSENT_REQUIRED",
                "assistant_request_id": assistant_request_id,
                "disclosure": error.disclosure.model_dump(mode="json"),
            },
        ) from error
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    return prepare_report_assistant_model_invocation(
        node,
        payload,
        authorization=authorization,
        repository=repository,
    )


def _assistant_model_execution_lease_seconds(invocation: Any) -> int:
    """모든 transport retry와 후속 검증·DB CAS를 포함하는 bounded lease를 계산한다."""

    try:
        duration = float(invocation.timeout) * int(invocation.max_attempts) + 180.0
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("Report Assistant model execution lease is invalid") from error
    if not math.isfinite(duration) or not 30 <= duration <= 3600:
        raise ValueError("Report Assistant model execution lease is invalid")
    return math.ceil(duration)


def _external_transfer_outcome_is_unknown(
    invocation: Any, error_code: str
) -> bool:
    """외부 POST가 처리됐을 수 있어 같은 세션에서 재전송하면 안 되는 오류를 판정한다."""

    return (
        getattr(getattr(invocation, "route", None), "data_boundary", None)
        == "external"
        and error_code in {
            "REPORT_ASSISTANT_MODEL_TIMEOUT",
            "REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED",
        }
    )


def _validated_assistant_model_trace(trace: Any) -> dict[str, Any]:
    """provider usage metadata를 DB·비용 계산 전에 bounded 숫자로 정규화한다."""

    if not isinstance(trace, dict):
        raise ValueError("Report Assistant model trace is invalid")
    normalized = dict(trace)
    for field in ("input_tokens", "output_tokens"):
        value = normalized.get(field)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 10_000_000
        ):
            raise ValueError("Report Assistant model usage is invalid")
    attempts = normalized.get("attempts")
    if (
        isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or not 1 <= attempts <= 4
    ):
        raise ValueError("Report Assistant model attempts are invalid")
    duration_ms = normalized.get("duration_ms")
    if (
        isinstance(duration_ms, bool)
        or not isinstance(duration_ms, (int, float))
        or not math.isfinite(float(duration_ms))
        or not 0 <= float(duration_ms) <= 3_600_000
    ):
        raise ValueError("Report Assistant model duration is invalid")
    normalized["duration_ms"] = float(duration_ms)
    return normalized


async def _claim_assistant_model_execution(
    repository: Any,
    *,
    assistant_request_id: str,
    node: str,
    session: dict[str, Any],
    invocation: Any,
    expected_phase: str | None = None,
) -> str:
    """process gate 뒤 DB CAS lease를 얻어 multi-instance 중복 transport를 막는다."""

    try:
        return await repository.claim_assistant_model_execution(
            assistant_request_id,
            node=node,
            expected_phase=expected_phase or str(session["phase"]),
            expected_message_revision=int(session["message_revision"]),
            expected_report_revision=int(session["base_revision"]),
            lease_seconds=_assistant_model_execution_lease_seconds(invocation),
        )
    except (KeyError, TypeError, ValueError) as error:
        code = str(error)
        execution_conflicts = {
            "ASSISTANT_MODEL_EXECUTION_CONFLICT",
            "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN",
        }
        raise HTTPException(
            status_code=(409 if code in execution_conflicts else 500),
            detail={
                "code": (
                    code
                    if code in execution_conflicts
                    else "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID"
                ),
                "assistant_request_id": assistant_request_id,
            },
        ) from error


_REPORT_PAGE_RENDER_MAX_CONCURRENCY = 2
_REPORT_PAGE_RENDER_PERMIT_WAIT_SECONDS = 0.1
_REPORT_PAGE_RENDER_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_REPORT_PAGE_RENDER_SEMAPHORE = threading.BoundedSemaphore(
    _REPORT_PAGE_RENDER_MAX_CONCURRENCY
)
_REPORT_PAGE_RENDER_TASKS: set[asyncio.Task[int]] = set()


def validate_report_assistant_page_render_runtime() -> float:
    """후보 renderer timeout 설정을 bounded 유한 초로 검증한다.

    잘못된 설정은 startup과 request 양쪽에서 실패하며 기본값으로 조용히 우회하지 않는다.
    """

    from decimal import Decimal, InvalidOperation

    raw_timeout = os.getenv("REPORT_ASSISTANT_PAGE_RENDER_TIMEOUT_SECONDS", "15")
    try:
        timeout = Decimal(raw_timeout.strip())
    except (AttributeError, InvalidOperation) as error:
        raise RuntimeError("Report Assistant renderer timeout 설정이 유효하지 않습니다.") from error
    if not timeout.is_finite() or not Decimal("0.05") <= timeout <= Decimal("120"):
        raise RuntimeError("Report Assistant renderer timeout 설정이 유효하지 않습니다.")
    return float(timeout)


async def _acquire_report_page_render_permit() -> bool:
    """event loop를 막지 않고 짧은 시간만 process-wide renderer permit을 기다린다."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + _REPORT_PAGE_RENDER_PERMIT_WAIT_SECONDS
    while True:
        if _REPORT_PAGE_RENDER_SEMAPHORE.acquire(blocking=False):
            return True
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.01, remaining))


def _render_page_count_with_permit(
    renderer: Callable[[dict[str, Any], str, datetime], int],
    semaphore: threading.BoundedSemaphore,
    source: dict[str, Any],
    orientation: str,
    rendered_at: datetime,
) -> int:
    """실제 worker가 끝난 뒤에만 permit을 반환해 timeout 우회를 막는다."""

    try:
        return renderer(source, orientation, rendered_at)
    finally:
        semaphore.release()


def _track_report_page_render_task(task: asyncio.Task[int]) -> None:
    """timeout 뒤에도 실행되는 worker task를 완료까지 강하게 참조한다."""

    _REPORT_PAGE_RENDER_TASKS.add(task)

    def complete(completed: asyncio.Task[int]) -> None:
        _REPORT_PAGE_RENDER_TASKS.discard(completed)
        if not completed.cancelled():
            completed.exception()

    task.add_done_callback(complete)


def _report_assistant_model_budget_limits() -> tuple[int, int, Any]:
    """Report Assistant의 입력·출력 token과 단일 호출 비용 상한을 함께 검증한다."""

    from app.services.report_assistant_operations import (
        report_assistant_model_cost_policy,
    )

    try:
        max_input_tokens = int(os.getenv("REPORT_ASSISTANT_MAX_INPUT_TOKENS", "16000"))
        max_output_tokens = int(os.getenv("REPORT_ASSISTANT_MAX_OUTPUT_TOKENS", "4096"))
        cost_policy = report_assistant_model_cost_policy()
    except (RuntimeError, ValueError) as error:
        raise ValueError("Assistant 실행 예산 설정이 유효하지 않습니다.") from error
    if max_input_tokens < 1 or max_output_tokens < 1:
        raise ValueError("Assistant 실행 예산 설정이 유효하지 않습니다.")
    return max_input_tokens, max_output_tokens, cost_policy


_PATCH_OPERATION_LABELS = {
    "set_report_title": "보고서 제목",
    "set_report_orientation": "용지 방향",
    "set_currency_display_unit": "통화 표시 단위",
    "compact_report_layout": "전체 레이아웃 정리",
    "add_report_page": "빈 페이지 추가",
    "update_block_title": "블록 제목",
    "resize_block": "블록 크기",
    "update_chart_settings": "차트 표현 설정",
    "update_table_settings": "표 표현 설정",
    "set_block_size_mode": "블록 크기 모드",
    "add_text": "텍스트 블록 추가",
    "update_text": "텍스트 블록 수정",
    "add_artifact_view": "Artifact 보기 추가",
    "reposition_block": "블록 배치 변경",
    "remove_block": "블록 삭제",
    "duplicate_block": "블록 복제",
    "restore_previous_revision": "직전 Revision 복원",
}


def _patch_operation_impact(operation: Any) -> dict[str, object]:
    """typed operation을 내부 식별자 없는 영향 분류와 근거 개수로 변환한다."""

    if operation.op in {"remove_block", "restore_previous_revision"}:
        category = "DESTRUCTIVE"
    elif operation.op in {
        "set_report_orientation", "compact_report_layout", "add_report_page", "resize_block",
        "set_block_size_mode", "add_artifact_view", "reposition_block", "duplicate_block",
    }:
        category = "LAYOUT"
    else:
        category = "CONTENT"
    evidence_required = operation.op == "add_text" or (
        operation.op == "update_text" and operation.content is not None
    )
    return {
        "impact_category": category,
        "evidence_required": evidence_required,
        "evidence_count": len(getattr(operation, "evidence_refs", ())),
    }


def _legacy_patch_preview(patch: ReportAssistantPatch | None) -> tuple[dict[str, Any], ...]:
    """migration 이전 승인 대기 session도 식별자 노출 없이 조회 가능하게 한다."""

    if patch is None:
        return ()
    from app.report_patch import report_patch_operation_dependencies

    dependencies = report_patch_operation_dependencies(patch)
    return tuple(
        {
            "index": index,
            "depends_on_indexes": dependencies[index],
            "page_index": None,
            "operation": operation.op,
            "target": _PATCH_OPERATION_LABELS[operation.op],
            "before": None,
            "after": None,
            **_patch_operation_impact(operation),
        }
        for index, operation in enumerate(patch.operations)
    )


def _approved_patch_operation_indexes(
    session: dict[str, Any],
    patch: ReportAssistantPatch | None,
) -> tuple[int, ...]:
    """migration 이전 patch 승인은 NULL 선택값을 기존 전체 승인 의미로 복구한다."""

    stored = tuple(session.get("approved_operation_indexes") or ())
    if stored or patch is None:
        return stored
    if session.get("patch_request_id") and session.get("approved_at") is not None:
        return tuple(range(len(patch.operations)))
    return ()


def _assistant_session_response(session: dict[str, Any]) -> dict[str, Any]:
    """저장소 column 이름을 공개 Assistant 세션 계약으로 변환한다."""

    raw_patch = session.get("report_patch_json")
    patch = ReportAssistantPatch.model_validate(raw_patch) if raw_patch else None
    evidence_refs = tuple(dict.fromkeys(
        evidence_ref
        for operation in patch.operations if patch
        for evidence_ref in getattr(operation, "evidence_refs", ())
    )) if patch else ()
    retry_policy = report_assistant_retry_policy(
        session.get("error_code") if session.get("phase") == "failed" else None
    )
    artifact_ids = tuple(
        binding["artifact_id"] for binding in session.get("artifact_bindings", ())
    ) or (session["artifact_id"],)
    if session.get("result_artifact_id") is not None and all(
        str(artifact_id) != str(session["result_artifact_id"])
        for artifact_id in artifact_ids
    ):
        artifact_ids = (*artifact_ids, session["result_artifact_id"])
    patch_preview = tuple(session.get("patch_preview_json") or ())
    if patch and len(patch_preview) != len(patch.operations):
        patch_preview = _legacy_patch_preview(patch)
    elif patch:
        from app.report_patch import report_patch_operation_dependencies

        dependencies = report_patch_operation_dependencies(patch)
        patch_preview = tuple(
            {
                **item,
                "index": index,
                "operation": patch.operations[index].op,
                "depends_on_indexes": dependencies[index],
                "page_index": item.get("page_index"),
                **_patch_operation_impact(patch.operations[index]),
            }
            for index, item in enumerate(patch_preview)
        )
    response = {
        "assistant_request_id": session["assistant_request_id"],
        "phase": session["phase"],
        "operation_scope": session.get("operation_scope", "full_report"),
        "definition_id": session["session_definition_id"],
        "definition_version": session["session_definition_version"],
        "base_revision": session["base_revision"],
        "artifact_id": session["artifact_id"],
        "artifact_ids": artifact_ids,
        "turn_history": tuple(session.get("turn_history") or ()),
        "analysis_plan": session.get("analysis_plan_json"),
        "patch_request_id": session.get("patch_request_id"),
        "patch_summary": patch.summary if patch else None,
        "patch_operations": tuple(operation.op for operation in patch.operations) if patch else (),
        "patch_evidence_refs": evidence_refs,
        "patch_preview": patch_preview,
        "approved_operation_indexes": _approved_patch_operation_indexes(session, patch),
        "exact_page_count": session.get("exact_page_count"),
        "verified_page_count": session.get("verified_page_count"),
        "result_artifact_id": session.get("result_artifact_id"),
        "result_revision": session.get("result_revision"),
        "error_code": session.get("error_code"),
        "retryable": retry_policy.retryable,
        "required_action": retry_policy.required_action,
        "retry_of_assistant_request_id": session.get("retry_of_assistant_request_id"),
    }
    ReportAssistantSessionResponse.model_validate(response)
    return response


def _with_artifact_bindings(
    state: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    """같은 세션의 phase mutation 결과에 조회 시 고정된 다중 Artifact 결속을 보존한다."""

    if not source.get("artifact_bindings"):
        return state
    return {**state, "artifact_bindings": source["artifact_bindings"]}


def _assistant_retry_error(
    assistant_request_id: str,
    code: str,
    required_action: ReportAssistantRequiredAction,
    status_code: int = 409,
) -> HTTPException:
    """재시도 거부 사유를 원문·내부 식별자 없이 typed 사용자 조치로 반환한다."""

    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "assistant_request_id": assistant_request_id,
            "retryable": False,
            "required_action": required_action.value,
        },
    )


def _router(context: RequestContext):
    return _build_report_router(context)


def _execution_service(repository):
    return _build_execution_service(repository)


async def _call(action: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    from src.report.router import ReportRouteError

    try:
        return await action()
    except ReportRouteError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


async def _repository_call(action: Callable[[], Awaitable[Any]]) -> Any:
    try:
        result = action()
        return await result if isawaitable(result) else result
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


async def _observe_assistant(repository: Any, method: str, *args: Any, **kwargs: Any) -> None:
    """평가 저장 장애를 핵심 Assistant·Revision 결과와 분리해 안전하게 기록한다."""

    action = getattr(repository, method, None)
    if not callable(action):
        return
    try:
        await action(*args, **kwargs)
    except Exception:
        logger.warning("Report Assistant evaluation write failed", exc_info=False)


async def _fail_observed_assistant(
    repository: Any,
    assistant_request_id: str,
    error_code: str,
    data_request_id: str | None = None,
    model_execution_id: str | None = None,
) -> None:
    """핵심 실패 전이를 먼저 저장한 뒤 평가 실패 결과를 별도 transaction으로 갱신한다."""

    failure_kwargs = (
        {"model_execution_id": model_execution_id}
        if model_execution_id is not None else {}
    )
    await repository.fail_assistant_request(
        assistant_request_id, error_code, data_request_id, **failure_kwargs
    )
    await _observe_assistant(
        repository,
        "finalize_assistant_evaluation",
        assistant_request_id,
        approval_decision="approved" if data_request_id else None,
        error_code=error_code,
    )


async def _execute_assistant_analysis(
    payload: AnalysisRequest,
    context: RequestContext,
) -> AnalysisResponse | Response:
    """기존 분석 API의 권한·gate·영속화 경계를 Assistant 승인 실행에서도 그대로 사용한다."""

    from app.api.router import analysis

    return await analysis(payload, context)


async def _recover_and_get_assistant_session(
    repository: Any,
    assistant_request_id: str,
) -> dict[str, Any]:
    """bounded timeout으로 중단된 분석을 실패 처리한 뒤 owner 범위의 최신 세션을 반환한다."""

    raw_timeout = os.getenv("REPORT_ASSISTANT_STALE_SECONDS", "900")
    try:
        timeout = int(raw_timeout)
    except ValueError as error:
        raise HTTPException(status_code=500, detail="Assistant timeout 설정이 유효하지 않습니다.") from error
    if not 60 <= timeout <= 86400:
        raise HTTPException(status_code=500, detail="Assistant timeout 설정이 유효하지 않습니다.")
    await repository.recover_stale_assistant_session(assistant_request_id, timeout)
    return await repository.get_assistant_session(assistant_request_id)


async def _session_artifacts(
    repository: Any,
    assistant_request_id: str,
    session: dict[str, Any],
    *,
    include_result: bool = True,
) -> tuple[dict[str, Any], ...]:
    """다중 결속 저장소를 우선 사용하고 기존 fake·단일 세션은 대표 Artifact로 호환한다."""

    loader = getattr(repository, "get_assistant_artifacts", None)
    if callable(loader):
        artifacts = tuple(await loader(assistant_request_id))
    else:
        artifacts = (await repository.get_assistant_artifact(str(session["artifact_id"])),)
    result_artifact_id = session.get("result_artifact_id") if include_result else None
    if result_artifact_id is not None and all(
        str(artifact["artifact_id"]) != str(result_artifact_id)
        for artifact in artifacts
    ):
        artifacts = (
            *artifacts,
            await repository.get_assistant_artifact(str(result_artifact_id)),
        )
    if not 1 <= len(artifacts) <= 6:
        raise ValueError("REPORT_ASSISTANT_PATCH_INVALID")
    return artifacts


def _report_turn_payload(
    definition: Any,
    artifacts: dict[str, Any] | tuple[dict[str, Any], ...],
    instruction: str,
    history: tuple[dict[str, str], ...] = (),
    current_patch: ReportAssistantPatch | None = None,
    selected_block_id: str | None = None,
    operation_scope: str = "full_report",
) -> dict[str, Any]:
    """현재 draft·Artifact·선택적 승인 대기 patch를 서버 별칭의 모델 입력으로 직렬화한다."""

    from app.adapters.report_assistant import report_evidence_catalog, report_patch_model_payload
    from app.services.report_assistant_external_transfer import (
        report_assistant_public_report_context,
    )

    artifact_items = (artifacts,) if isinstance(artifacts, dict) else artifacts
    primary = artifact_items[0]

    def artifact_payload(artifact: dict[str, Any], index: int) -> dict[str, Any]:
        alias = "source_artifact" if index == 1 else f"source_artifact_{index}"
        prefix = "" if index == 1 else f"artifact_{index}_"
        return {
            "artifact_id": alias,
            "title": artifact["title"],
            "narrative": artifact["narrative_markdown"],
            "evidence": {"catalog": list(report_evidence_catalog(artifact, prefix))},
            "chart_spec": artifact["chart_spec_json"],
            "available_views": _artifact_visible_views(artifact),
            "table_snapshot": _artifact_table_snapshot(artifact),
        }

    if len(definition.blocks) > REPORT_MAX_BLOCKS:
        raise ValueError("REPORT_BLOCK_LIMIT_EXCEEDED")
    primary_artifact_id = str(primary["artifact_id"])
    selected_block = None
    if selected_block_id is not None:
        block = next(
            (item for item in definition.blocks if item.block_id == selected_block_id),
            None,
        )
        if block is None:
            raise ValueError("ASSISTANT_STATE_CONFLICT")
        if (
            block.artifact_id is not None
            and str(block.artifact_id) != primary_artifact_id
        ):
            raise ValueError("ASSISTANT_STATE_CONFLICT")
        selected_block = {
            "block_id": block.block_id,
            "title": block.title,
            "type": block.type.value,
        }

    return {
        "instruction": instruction,
        "operation_scope": operation_scope,
        "history": list(history[-12:]),
        "current_patch": (
            report_patch_model_payload(current_patch)
            if current_patch is not None else None
        ),
        "selected_block": selected_block,
        "artifact": artifact_payload(primary, 1),
        "additional_artifacts": [
            artifact_payload(artifact, index)
            for index, artifact in enumerate(artifact_items[1:], start=2)
        ],
        "report": report_assistant_public_report_context(definition, artifact_items),
    }


def _validated_contextual_suggestions(
    raw_suggestions: object,
    definition: Any,
    artifacts: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    """모델 후속 제안을 세 개 이하의 공개 문장으로 제한하고 내부 별칭 노출을 거부한다."""

    from app.adapters.report_assistant import report_evidence_catalog

    if not isinstance(raw_suggestions, (list, tuple)) or len(raw_suggestions) > 3:
        raise ValueError("REPORT_ASSISTANT_SUGGESTIONS_INVALID")
    suggestions = tuple(str(item).strip() for item in raw_suggestions)
    if (
        any(not item or len(item) > 500 for item in suggestions)
        or len(set(suggestions)) != len(suggestions)
    ):
        raise ValueError("REPORT_ASSISTANT_SUGGESTIONS_INVALID")
    hidden_values = {
        block.block_id for block in definition.blocks
    } | {
        "source_artifact" if index == 1 else f"source_artifact_{index}"
        for index in range(1, len(artifacts) + 1)
    } | {
        str(item["ref"])
        for index, artifact in enumerate(artifacts, start=1)
        for item in report_evidence_catalog(
            artifact, "" if index == 1 else f"artifact_{index}_"
        )
    }
    if any(value and value in suggestion for suggestion in suggestions for value in hidden_values):
        raise ValueError("REPORT_ASSISTANT_SUGGESTIONS_INVALID")
    return suggestions


async def _apply_existing_artifact_patch(
    repository: Any,
    definition: Any,
    artifacts: dict[str, Any] | tuple[dict[str, Any], ...],
    patch: ReportAssistantPatch,
) -> Any:
    """저장 patch를 현재 owner draft와 검증 Artifact에 dry-run해 저장 가능한 정의를 만든다."""

    from app.adapters.report_assistant import report_evidence_catalog, validate_report_patch_evidence
    from app.report_patch import VerifiedArtifactBinding, apply_report_assistant_patch

    artifact_items = (artifacts,) if isinstance(artifacts, dict) else artifacts
    catalog = tuple(
        evidence
        for index, artifact in enumerate(artifact_items, start=1)
        for evidence in report_evidence_catalog(
            artifact, "" if index == 1 else f"artifact_{index}_"
        )
    )
    validate_report_patch_evidence(patch, catalog)

    previous_definition = None
    if patch.operations[0].op == "restore_previous_revision":
        if definition.version <= 1:
            raise ValueError("복원할 직전 Report revision을 찾을 수 없습니다.")
        try:
            previous_definition = await repository.get_version(
                definition.definition_id,
                definition.version - 1,
            )
        except KeyError as error:
            raise ValueError("복원할 직전 Report revision을 찾을 수 없습니다.") from error
    return apply_report_assistant_patch(
        definition,
        patch,
        {
            ("source_artifact" if index == 1 else f"source_artifact_{index}"):
                VerifiedArtifactBinding(
                    str(artifact["artifact_id"]),
                    str(artifact["trino_query_id"]),
                    str(artifact["artifact_checksum"]),
                    str(artifact["title"]),
                    frozenset(_artifact_visible_views(artifact)),
                )
            for index, artifact in enumerate(artifact_items, start=1)
        },
        previous_definition,
    )


def _model_exact_page_count(proposal: dict[str, Any]) -> int | None:
    """strict 모델의 nullable 정확 페이지 제약을 bool 없이 한 번 더 닫는다."""

    value = proposal.get("exact_page_count")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 20:
        raise ValueError("REPORT_ASSISTANT_TURN_MODEL_INVALID")
    return value


def _stored_exact_page_count(session: dict[str, Any]) -> int | None:
    """영속 receipt의 nullable 페이지 제약을 bool 없이 검증한다."""

    value = session.get("exact_page_count")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 20:
        raise ValueError("ASSISTANT_STATE_CONFLICT")
    return value


def _effective_page_constraint(
    session: dict[str, Any],
    proposal_exact_page_count: int | None,
    instruction: str,
) -> tuple[int | None, str | None]:
    """nullable 모델 출력이 이전 turn의 명시 제약을 조용히 지우지 않게 한다.

    session 제안 체인을 시작한 최초 user turn을 원지시로 고정한다. clarification 답변과
    patch refinement가 페이지 수를 다시 말하지 않으면 기존 제약과 그 출처를 그대로 이어
    간다. nullable 출력에는 제약 삭제 의미가 없으므로 별도 계약 없이는 해제하지 않는다.
    """

    stored_exact_page_count = _stored_exact_page_count(session)
    effective_exact_page_count = (
        stored_exact_page_count
        if stored_exact_page_count is not None
        else proposal_exact_page_count
    )
    stored_source_instruction = str(session.get("source_instruction") or "").strip()
    if stored_source_instruction and len(stored_source_instruction) > 500:
        raise ValueError("ASSISTANT_STATE_CONFLICT")
    if stored_exact_page_count is not None and not stored_source_instruction:
        raise ValueError("ASSISTANT_STATE_CONFLICT")
    source_instruction = stored_source_instruction or instruction
    if source_instruction is not None and not 1 <= len(source_instruction) <= 500:
        raise ValueError("ASSISTANT_STATE_CONFLICT")
    return effective_exact_page_count, source_instruction


def _validate_candidate_render_budget(definition: Any) -> None:
    """legacy 조회는 보존하되 Assistant renderer에 넘길 후보만 bounded source로 제한한다."""

    if len(definition.blocks) > REPORT_MAX_BLOCKS:
        raise _ReportAssistantPageRenderError(
            "Report Assistant 후보 block 수가 renderer 허용 범위를 초과했습니다."
        )
    for block in definition.blocks:
        references = (block.artifact_id, block.query_id, block.view_spec_id)
        layout = (block.columns, block.x, block.y, block.w, block.h)
        if (
            not isinstance(block.block_id, str)
            or not 1 <= len(block.block_id) <= MAX_REPORT_BLOCK_ID_LENGTH
            or not isinstance(block.title, str)
            or not 1 <= len(block.title) <= MAX_REPORT_BLOCK_TITLE_LENGTH
            or not isinstance(block.content, str)
            or len(block.content) > MAX_REPORT_BLOCK_CONTENT_LENGTH
            or any(
                reference is not None
                and (
                    not isinstance(reference, str)
                    or not 1 <= len(reference) <= MAX_REPORT_BLOCK_REFERENCE_ID_LENGTH
                )
                for reference in references
            )
            or any(isinstance(value, bool) or not isinstance(value, int) for value in layout)
            or not 1 <= block.h <= MAX_REPORT_BLOCK_HEIGHT
            or block.y < 0
            or block.y + block.h > MAX_REPORT_LAYOUT_ROWS
        ):
            raise _ReportAssistantPageRenderError(
                "Report Assistant 후보 block이 renderer 입력 계약을 벗어났습니다."
            )


async def _candidate_report_page_count(
    repository: Any,
    definition: Any,
    artifacts: tuple[dict[str, Any], ...],
) -> int:
    """검증 후보를 승인 renderer source로 복원해 PDF 생성 없이 한 번 layout한다."""

    from app.services.report.document import render_report_page_count

    _validate_candidate_render_budget(definition)
    artifact_by_id = {str(item["artifact_id"]): item for item in artifacts}
    for block in definition.blocks:
        if block.artifact_id is None or str(block.artifact_id) in artifact_by_id:
            continue
        loader = getattr(repository, "get_report_artifact", None)
        if not callable(loader):
            raise ValueError("REPORT_ASSISTANT_PATCH_INVALID")
        artifact_id = str(block.artifact_id)
        try:
            artifact_by_id[artifact_id] = await loader(
                str(definition.definition_id), int(definition.version), artifact_id
            )
        except KeyError:
            # ``restore_previous_revision``만 직전 persisted version의 block을 되살릴 수 있다.
            # active library 조회로 우회하지 않고 실제 report 참조를 다시 검증한다.
            if int(definition.version) <= 1:
                raise
            artifact_by_id[artifact_id] = await loader(
                str(definition.definition_id), int(definition.version) - 1, artifact_id
            )

    blocks: list[dict[str, Any]] = []
    for block in definition.blocks:
        artifact = None
        if block.artifact_id is not None:
            source = artifact_by_id.get(str(block.artifact_id))
            if source is None:
                raise ValueError("REPORT_ASSISTANT_PATCH_INVALID")
            artifact = {
                "artifact_id": str(source["artifact_id"]),
                "artifact_checksum": str(source["artifact_checksum"]),
                "query_id": str(source["trino_query_id"]),
                "table": source.get("data_snapshot_json"),
                "chart_spec": source.get("chart_spec_json"),
                "evidence": source.get("evidence_json"),
                "narrative": source.get("narrative_markdown"),
            }
        blocks.append({
            "block_id": block.block_id,
            "title": block.title,
            "type": block.type.value,
            "x": block.x,
            "y": block.y,
            "w": block.w,
            "h": block.h,
            "content": block.content,
            "artifact": artifact,
        })
    source = {
        "definition_id": definition.definition_id,
        # finalize_existing_assistant_patch는 현재 N을 N+1 revision으로 저장한다. 표지의
        # revision 문자열까지 최종 source와 같아야 후보 page receipt가 실제 문서와 같다.
        "version": int(definition.version) + 1,
        "title": definition.title,
        "orientation": definition.orientation,
        "currency_display_unit": definition.currency_display_unit,
        "blocks": blocks,
        "artifact_versions": [
            {
                "artifact_id": artifact_id,
                "artifact_checksum": str(artifact["artifact_checksum"]),
                "query_id": str(artifact["trino_query_id"]),
            }
            for artifact_id, artifact in sorted(artifact_by_id.items())
        ],
    }
    try:
        source_size = len(json.dumps(
            {"orientation": definition.orientation, "source": source},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise _ReportAssistantPageRenderError(
            "Report Assistant 후보 source를 직렬화할 수 없습니다."
        ) from error
    if source_size > _REPORT_PAGE_RENDER_MAX_SOURCE_BYTES:
        raise _ReportAssistantPageRenderError(
            "Report Assistant 후보 source가 renderer 허용 크기를 초과했습니다."
        )
    try:
        render_timeout = validate_report_assistant_page_render_runtime()
    except RuntimeError as error:
        raise _ReportAssistantPageRenderError(
            "Report Assistant renderer 설정이 유효하지 않습니다."
        ) from error
    if not await _acquire_report_page_render_permit():
        raise _ReportAssistantPageRenderError(
            "Report Assistant 후보 renderer가 사용 중입니다."
        )
    semaphore = _REPORT_PAGE_RENDER_SEMAPHORE
    try:
        task = asyncio.create_task(
            asyncio.to_thread(
                _render_page_count_with_permit,
                render_report_page_count,
                semaphore,
                source,
                definition.orientation,
                datetime.now(timezone.utc),
            )
        )
    except BaseException:
        semaphore.release()
        raise
    _track_report_page_render_task(task)
    try:
        page_count = await asyncio.wait_for(asyncio.shield(task), render_timeout)
    except TimeoutError as error:
        raise _ReportAssistantPageRenderError(
            "Report Assistant 후보 페이지 렌더링 시간이 초과되었습니다."
        ) from error
    except RuntimeError as error:
        raise _ReportAssistantPageRenderError(
            "Report Assistant 후보 페이지를 렌더링할 수 없습니다."
        ) from error
    if (
        isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count < 1
    ):
        raise ValueError("REPORT_ASSISTANT_PATCH_INVALID")
    return page_count


def _report_page_renderer_fingerprint() -> str:
    """현재 renderer runtime과 Report HTML/CSS source의 검증된 SHA-256 receipt를 반환한다."""

    from app.services.report.document import report_renderer_contract_fingerprint

    try:
        fingerprint = report_renderer_contract_fingerprint()
    except RuntimeError as error:
        raise _ReportAssistantPageRenderError(
            "Report Assistant renderer 계약을 확인할 수 없습니다."
        ) from error
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise _ReportAssistantPageRenderError(
            "Report Assistant renderer 계약 receipt가 유효하지 않습니다."
        )
    return fingerprint


async def _candidate_report_page_receipt(
    repository: Any,
    definition: Any,
    artifacts: tuple[dict[str, Any], ...],
) -> tuple[int, str]:
    """후보 실제 페이지 수와 그 layout에 사용한 renderer/CSS 계약을 함께 고정한다."""

    fingerprint = _report_page_renderer_fingerprint()
    page_count = await _candidate_report_page_count(repository, definition, artifacts)
    return page_count, fingerprint


def _patch_preview_text(value: object | None) -> str | None:
    """공개 미리보기 문자열을 계약 길이 안으로 제한한다."""

    if value is None:
        return None
    text_value = str(value)
    return text_value if len(text_value) <= 4000 else f"{text_value[:3997]}..."


def _preview_block_settings(block: Any) -> dict[str, Any]:
    """공개 미리보기에 필요한 허용 renderer 설정만 안전하게 읽는다."""

    if not block.content or block.type.value == "text":
        return {}
    try:
        parsed = json.loads(block.content)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    allowed = {"chartType", "showLegend", "density", "showRowNumbers", "sizeMode"}
    return {key: value for key, value in parsed.items() if key in allowed}


def _report_layout_pages(
    definition: Any,
    orientation: str | None = None,
) -> list[list[dict[str, Any]]]:
    """renderer와 같은 paginate 계약으로 현재 draft의 실제 A4 페이지를 계산한다."""

    from app.services.report.layout import _paginate_layout

    blocks = [
        {
            "block_id": block.block_id,
            "type": block.type.value,
            "x": block.x,
            "y": block.y,
            "w": block.w,
            "h": block.h,
        }
        for block in definition.blocks
    ]
    return _paginate_layout(blocks, orientation or definition.orientation)


def _report_page_count(definition: Any, orientation: str | None = None) -> int:
    """renderer paginate 결과에서 1 이상의 실제 A4 페이지 수를 반환한다."""

    return len(_report_layout_pages(definition, orientation))


def _report_block_page_indexes(
    definition: Any,
    orientation: str | None = None,
) -> dict[str, int]:
    """renderer에 실제 배치되는 현재 block의 1-based 페이지를 서버에서 계산한다."""

    return {
        str(block["block_id"]): page_index
        for page_index, page in enumerate(
            _report_layout_pages(definition, orientation), start=1
        )
        for block in page
    }


def _report_patch_preview(
    definition: Any,
    patch: ReportAssistantPatch,
) -> tuple[dict[str, Any], ...]:
    """서버가 검증한 patch를 내부 ID 없이 operation별 변경 전후로 설명한다."""

    blocks = {block.block_id: block for block in definition.blocks}
    items: list[dict[str, Any]] = []
    view_labels = {
        "summary": "요약",
        "kpi": "핵심 지표",
        "chart": "차트",
        "table": "표",
        "artifact": "복합 보기",
    }
    from app.report_patch import report_patch_operation_dependencies

    dependencies = report_patch_operation_dependencies(patch)
    preview_orientation = definition.orientation
    added_page_count = 0
    page_count = _report_page_count(definition, preview_orientation)
    block_page_indexes = _report_block_page_indexes(definition, preview_orientation)
    latest_added_page_index: int | None = None
    for index, operation in enumerate(patch.operations):
        target = _PATCH_OPERATION_LABELS[operation.op]
        before: str | None = None
        after: str | None = None
        page_index: int | None = None
        if operation.op == "set_report_title":
            before, after = definition.title, operation.title
        elif operation.op == "set_report_orientation":
            labels = {"portrait": "A4 세로", "landscape": "A4 가로"}
            before, after = labels[definition.orientation], labels[operation.orientation]
            preview_orientation = operation.orientation
            page_count = _report_page_count(definition, preview_orientation) + added_page_count
            block_page_indexes = _report_block_page_indexes(
                definition, preview_orientation
            )
        elif operation.op == "set_currency_display_unit":
            labels = {
                "auto": "자동", "one": "원", "thousand": "천원", "million": "백만원",
                "hundredMillion": "억원", "billion": "십억원",
            }
            before = labels[definition.currency_display_unit]
            after = labels[operation.currency_display_unit]
        elif operation.op == "compact_report_layout":
            target, before, after = "보고서 전체", "현재 블록 배치", "빈 공간 없이 정리"
        elif operation.op == "add_report_page":
            target, before = "보고서 끝", f"현재 {page_count}페이지"
            added_page_count += 1
            page_count += 1
            latest_added_page_index = page_count
            page_index = latest_added_page_index
            after = f"{page_count}페이지 · 빈 A4 페이지 1장 추가"
        elif operation.op == "update_block_title":
            source = blocks[operation.block_id]
            target, before, after = source.title, source.title, operation.title
        elif operation.op == "resize_block":
            source = blocks[operation.block_id]
            target = source.title
            before = f"{source.w}/12 × {source.h}단"
            after = f"{operation.block_width}/12 × {operation.block_height}단"
        elif operation.op == "update_chart_settings":
            source = blocks[operation.block_id]
            target = source.title
            settings = _preview_block_settings(source)
            chart_labels = {
                "bar": "세로 막대", "horizontal-bar": "가로 막대", "line": "선",
                "area": "영역", "stacked-bar": "누적 막대", "donut": "도넛", "pie": "원형",
            }
            before_parts: list[str] = []
            after_parts: list[str] = []
            if operation.chart_type is not None:
                before_parts.append(f"차트 유형: {chart_labels.get(settings.get('chartType'), '기본 차트')}")
                after_parts.append(f"차트 유형: {chart_labels[operation.chart_type]}")
            if operation.show_legend is not None:
                before_parts.append(f"범례: {'표시' if settings.get('showLegend') is not False else '숨김'}")
                after_parts.append(f"범례: {'표시' if operation.show_legend else '숨김'}")
            if operation.size_mode is not None:
                before_parts.append(f"크기 모드: {'내용에 맞춤' if settings.get('sizeMode') == 'auto' else '수동'}")
                after_parts.append(f"크기 모드: {'내용에 맞춤' if operation.size_mode == 'auto' else '수동'}")
            before, after = " · ".join(before_parts), " · ".join(after_parts)
        elif operation.op == "update_table_settings":
            source = blocks[operation.block_id]
            target = source.title
            settings = _preview_block_settings(source)
            before_parts = []
            after_parts = []
            if operation.density is not None:
                before_parts.append(f"표 밀도: {'간결' if settings.get('density') == 'compact' else '보통'}")
                after_parts.append(f"표 밀도: {'간결' if operation.density == 'compact' else '보통'}")
            if operation.show_row_numbers is not None:
                before_parts.append(f"행 번호: {'표시' if settings.get('showRowNumbers') is True else '숨김'}")
                after_parts.append(f"행 번호: {'표시' if operation.show_row_numbers else '숨김'}")
            if operation.size_mode is not None:
                before_parts.append(f"크기 모드: {'내용에 맞춤' if settings.get('sizeMode') == 'auto' else '수동'}")
                after_parts.append(f"크기 모드: {'내용에 맞춤' if operation.size_mode == 'auto' else '수동'}")
            before, after = " · ".join(before_parts), " · ".join(after_parts)
        elif operation.op == "set_block_size_mode":
            source = blocks[operation.block_id]
            target = source.title
            settings = _preview_block_settings(source)
            before = "내용에 맞춤" if settings.get("sizeMode") == "auto" else "수동 크기"
            after = "내용에 맞춤" if operation.size_mode == "auto" else "수동 크기"
        elif operation.op == "add_text":
            target, after = operation.title, operation.content
            if operation.placement.after_block_id is not None:
                page_index = block_page_indexes.get(
                    operation.placement.after_block_id
                )
            elif latest_added_page_index is not None:
                page_index = latest_added_page_index
        elif operation.op == "update_text":
            source = blocks[operation.block_id]
            target = source.title
            before_parts = []
            after_parts = []
            if operation.title is not None:
                before_parts.append(f"제목: {source.title}")
                after_parts.append(f"제목: {operation.title}")
            if operation.content is not None:
                before_parts.append(f"본문: {source.content}")
                after_parts.append(f"본문: {operation.content}")
            before, after = "\n".join(before_parts), "\n".join(after_parts)
        elif operation.op == "add_artifact_view":
            target = operation.title
            if operation.placement.after_block_id is not None:
                page_index = block_page_indexes.get(
                    operation.placement.after_block_id
                )
            elif latest_added_page_index is not None:
                page_index = latest_added_page_index
            details = [f"{view_labels[operation.view]} 블록 추가"]
            if operation.chart_type is not None:
                details.append(f"차트 유형 {operation.chart_type}")
            if operation.show_legend is not None:
                details.append(f"범례 {'표시' if operation.show_legend else '숨김'}")
            if operation.density is not None:
                details.append(f"표 밀도 {'간결' if operation.density == 'compact' else '보통'}")
            if operation.show_row_numbers is not None:
                details.append(f"행 번호 {'표시' if operation.show_row_numbers else '숨김'}")
            after = " · ".join(details)
        elif operation.op == "reposition_block":
            source = blocks[operation.block_id]
            anchor = blocks.get(operation.after_block_id) if operation.after_block_id else None
            ordered_blocks = sorted(
                definition.blocks,
                key=lambda block: (block.y, block.x, block.block_id),
            )
            source_index = next(
                index
                for index, block in enumerate(ordered_blocks)
                if block.block_id == source.block_id
            )
            current_anchor = ordered_blocks[source_index - 1] if source_index else None
            target = source.title
            before = (
                f"{source.w}/12 폭 · "
                f"{current_anchor.title + ' 뒤' if current_anchor else '보고서 처음'}"
            )
            after = (
                f"{'6/12' if operation.width == 'half' else '12/12'} 폭 · "
                f"{anchor.title + ' 뒤' if anchor else '보고서 끝'}"
            )
            if operation.after_block_id is not None:
                page_index = block_page_indexes.get(operation.after_block_id)
            elif latest_added_page_index is not None:
                page_index = latest_added_page_index
        elif operation.op == "remove_block":
            target = blocks[operation.block_id].title
            before, after = "현재 블록 유지", "블록 삭제"
        elif operation.op == "duplicate_block":
            target = blocks[operation.block_id].title
            before, after = "원본 1개", "원본과 복제본 2개"
        elif operation.op == "restore_previous_revision":
            target = "보고서 전체"
            before = f"현재 Revision {definition.version}"
            after = f"Revision {definition.version - 1} 내용으로 복원"
        if page_index is None:
            target_block_id = getattr(operation, "block_id", None)
            if target_block_id is not None and operation.op != "reposition_block":
                page_index = block_page_indexes.get(target_block_id)
        items.append(
            {
                "index": index,
                "depends_on_indexes": dependencies[index],
                "page_index": page_index,
                "operation": operation.op,
                "target": target,
                "before": _patch_preview_text(before),
                "after": _patch_preview_text(after),
                **_patch_operation_impact(operation),
            }
        )
    return tuple(items)


def _validated_report_review(
    review: dict[str, object],
    definition: Any,
    artifacts: tuple[dict[str, Any], ...],
) -> tuple[ReportAssistantReviewFinding, ...]:
    """모델 finding이 현재 Report block과 현재 Artifact의 공개 근거 별칭만 참조하게 한다."""

    from app.adapters.report_assistant import report_evidence_catalog

    block_ids = {block.block_id for block in definition.blocks}
    evidence_refs = {
        str(item["ref"])
        for index, artifact in enumerate(artifacts, start=1)
        for item in report_evidence_catalog(
            artifact, "" if index == 1 else f"artifact_{index}_"
        )
    }
    try:
        findings = tuple(
            ReportAssistantReviewFinding.model_validate(item)
            for item in review["findings"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("REPORT_ASSISTANT_REVIEW_INVALID") from error
    for finding in findings:
        if finding.block_id is not None and finding.block_id not in block_ids:
            raise ValueError("REPORT_ASSISTANT_REVIEW_INVALID")
        if any(reference not in evidence_refs for reference in finding.evidence_refs):
            raise ValueError("REPORT_ASSISTANT_REVIEW_INVALID")
    return findings


async def _prepare_assistant_revision(
    repository: Any,
    assistant_request_id: str,
    session: dict[str, Any],
    artifact: dict[str, Any],
    plan: ReportAssistantAnalysisPlan,
) -> dict[str, Any]:
    """검증된 새 Artifact를 한 번만 모델에 전달해 복구 가능한 typed patch를 만든다.

    반환값은 원지시·기존 결속·새 Artifact와 함께 patch 승인 대기에 저장된다. 모델이 새
    분석을 재요청하거나 원래 페이지 제약을 바꾸면 상태 전이 전에 실패한다.
    """

    from app.adapters.report_assistant import (
        ReportAssistantModelError,
        bind_report_assistant_model_execution,
        generate_report_change_proposal,
    )
    try:
        definition = await repository.get_version(
            str(session["session_definition_id"]),
            int(session["session_definition_version"]),
        )
    except KeyError as error:
        raise ValueError("REPORT_REVISION_CONFLICT") from error
    source_instruction = str(session.get("source_instruction") or "").strip()
    if not source_instruction or len(source_instruction) > 500:
        raise ValueError("ASSISTANT_STATE_CONFLICT")
    exact_page_count = session.get("exact_page_count")
    if (
        exact_page_count is not None
        and (
            isinstance(exact_page_count, bool)
            or not isinstance(exact_page_count, int)
            or not 1 <= exact_page_count <= 20
        )
    ):
        raise ValueError("ASSISTANT_STATE_CONFLICT")
    initial_artifacts = await _session_artifacts(
        repository, assistant_request_id, session, include_result=False
    )
    if len(initial_artifacts) >= 6 or any(
        str(item["artifact_id"]) == str(artifact["artifact_id"])
        for item in initial_artifacts
    ):
        raise ValueError("REPORT_ASSISTANT_PATCH_INVALID")
    composition_artifacts = (*initial_artifacts, artifact)
    history = await repository.get_assistant_turn_history(assistant_request_id)
    model_payload = _report_turn_payload(
        definition,
        composition_artifacts,
        source_instruction,
        history,
    )

    try:
        model_invocation = await _consented_assistant_model_invocation(
            repository,
            assistant_request_id=assistant_request_id,
            node="report_assistant_turn",
            payload=model_payload,
            session=session,
            artifacts=composition_artifacts,
            approved_new_analysis_artifact=True,
        )
    except HTTPException:
        raise
    except ReportAssistantModelError as error:
        raise HTTPException(
            status_code=(429 if error.code == "ASSISTANT_COST_BUDGET_EXCEEDED" else 500),
            detail={"code": error.code, "assistant_request_id": assistant_request_id},
        ) from error

    from app.api.router import execution_gate
    from app.services.report_assistant_operations import estimate_model_cost
    from src.modelops.runtime import estimate_token_count

    try:
        max_input_tokens, max_output_tokens, cost_policy = (
            _report_assistant_model_budget_limits()
        )
    except ValueError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    message_revision = session.get("message_revision")
    observation_revision = (
        message_revision
        if isinstance(message_revision, int) and not isinstance(message_revision, bool)
        and message_revision >= 0
        else None
    )

    async def observe_composition(**observations: Any) -> None:
        kwargs = dict(observations)
        if observation_revision is not None:
            kwargs["expected_message_revision"] = observation_revision
        await _observe_assistant(
            repository,
            "upsert_assistant_evaluation",
            assistant_request_id,
            **kwargs,
        )
    estimated_input_tokens = estimate_token_count(
        json.dumps(model_payload, ensure_ascii=False, separators=(",", ":"))
    )
    if estimated_input_tokens > max_input_tokens:
        await observe_composition(
            contract_valid=False,
            error_code="ASSISTANT_TOKEN_BUDGET_EXCEEDED",
        )
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ASSISTANT_TOKEN_BUDGET_EXCEEDED",
                "assistant_request_id": assistant_request_id,
            },
        )
    if not await execution_gate.acquire(0):
        await observe_composition(
            contract_valid=False,
            error_code="ASSISTANT_CONCURRENCY_LIMITED",
        )
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ASSISTANT_CONCURRENCY_LIMITED",
                "assistant_request_id": assistant_request_id,
            },
        )
    model_execution_id: str | None = None

    async def fail_composition_execution(error_code: str) -> None:
        nonlocal model_execution_id
        if model_execution_id is None:
            return
        await repository.fail_assistant_request(
            assistant_request_id,
            error_code,
            str(plan.request_id),
            expected_phase="waiting_artifact",
            expected_message_revision=observation_revision,
            model_execution_id=model_execution_id,
        )
        model_execution_id = None
    try:
        try:
            model_execution_id = await _claim_assistant_model_execution(
                repository,
                assistant_request_id=assistant_request_id,
                node="report_assistant_turn",
                session=session,
                invocation=model_invocation,
                expected_phase="waiting_artifact",
            )
            model_invocation = bind_report_assistant_model_execution(
                model_invocation, model_execution_id
            )
            proposal, trace = await generate_report_change_proposal(
                model_payload, invocation=model_invocation
            )
        finally:
            execution_gate.release()
    except ReportAssistantModelError as error:
        error_code = (
            "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN"
            if _external_transfer_outcome_is_unknown(model_invocation, error.code)
            else error.code
        )
        await fail_composition_execution(error_code)
        await observe_composition(
            contract_valid=False,
            model_attempts=error.attempts,
            latency_ms=error.duration_ms,
            error_code=error_code,
            accumulate_usage=True,
        )
        if error_code == "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": error_code,
                    "assistant_request_id": assistant_request_id,
                },
            ) from error
        if error.code in {
            "ASSISTANT_COST_BUDGET_EXCEEDED",
            "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
            "ASSISTANT_MODEL_EXECUTION_CONFLICT",
        }:
            raise HTTPException(
                status_code=(
                    429
                    if error.code == "ASSISTANT_COST_BUDGET_EXCEEDED"
                    else 409
                    if error.code == "ASSISTANT_MODEL_EXECUTION_CONFLICT"
                    else 500
                ),
                detail={
                    "code": error.code,
                    "assistant_request_id": assistant_request_id,
                },
            ) from error
        raise
    except BaseException:
        await fail_composition_execution(
            "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN"
            if getattr(model_invocation.route, "data_boundary", None) == "external"
            else "ASSISTANT_EXECUTION_INTERRUPTED"
        )
        raise
    try:
        trace = _validated_assistant_model_trace(trace)
    except ValueError as error:
        await fail_composition_execution("REPORT_ASSISTANT_MODEL_CONTRACT_INVALID")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    input_tokens = trace.get("input_tokens")
    output_tokens = trace.get("output_tokens")
    if (
        input_tokens is not None and int(input_tokens) > max_input_tokens
    ) or (
        output_tokens is not None and int(output_tokens) > max_output_tokens
    ):
        await fail_composition_execution("ASSISTANT_TOKEN_BUDGET_EXCEEDED")
        await observe_composition(
            contract_valid=False,
            model_attempts=trace.get("attempts"),
            latency_ms=trace.get("duration_ms"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_code="ASSISTANT_TOKEN_BUDGET_EXCEEDED",
            accumulate_usage=True,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ASSISTANT_TOKEN_BUDGET_EXCEEDED",
                "assistant_request_id": assistant_request_id,
            },
        )
    estimated_cost = estimate_model_cost(
        input_tokens, output_tokens, policy=cost_policy
    )
    if (
        estimated_cost is not None
        and estimated_cost > cost_policy.max_estimated_cost_usd
    ):
        await fail_composition_execution("ASSISTANT_COST_BUDGET_EXCEEDED")
        await observe_composition(
            contract_valid=True,
            model_attempts=trace.get("attempts"),
            latency_ms=trace.get("duration_ms"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            error_code="ASSISTANT_COST_BUDGET_EXCEEDED",
            accumulate_usage=True,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ASSISTANT_COST_BUDGET_EXCEEDED",
                "assistant_request_id": assistant_request_id,
            },
        )
    try:
        await observe_composition(
            contract_valid=True,
            model_attempts=trace.get("attempts"),
            latency_ms=trace.get("duration_ms"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            accumulate_usage=True,
        )
    except BaseException:
        await fail_composition_execution("ASSISTANT_EXECUTION_INTERRUPTED")
        raise
    if proposal["change_kind"] != "existing_artifact" or proposal["analysis_plan"] is not None:
        await fail_composition_execution("REPORT_ASSISTANT_MODEL_CONTRACT_INVALID")
        raise ReportAssistantModelError("새 분석 Artifact 합성 모델이 추가 분석을 요청했습니다.")
    try:
        patch = ReportAssistantPatch.model_validate(proposal["patch"])
    except (KeyError, TypeError, ValueError) as error:
        await fail_composition_execution("REPORT_ASSISTANT_MODEL_CONTRACT_INVALID")
        raise ReportAssistantModelError(
            "새 분석 Artifact 합성 patch가 유효하지 않습니다.",
            code="REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
        ) from error
    if patch.operations[0].op == "restore_previous_revision":
        await fail_composition_execution("REPORT_ASSISTANT_MODEL_CONTRACT_INVALID")
        raise ReportAssistantModelError("새 분석 Artifact 합성에서는 이전 revision을 복원할 수 없습니다.")
    try:
        composition_exact_page_count = _model_exact_page_count(proposal)
    except ValueError:
        await fail_composition_execution("REPORT_ASSISTANT_MODEL_CONTRACT_INVALID")
        raise
    if composition_exact_page_count not in {None, exact_page_count}:
        await fail_composition_execution("REPORT_ASSISTANT_MODEL_CONTRACT_INVALID")
        raise ReportAssistantModelError(
            "새 분석 Artifact 합성 모델이 원래 페이지 제약을 변경했습니다.",
            code="REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
        )
    try:
        patched = await _apply_existing_artifact_patch(
            repository, definition, composition_artifacts, patch
        )
        verified_page_count, page_renderer_fingerprint = await _candidate_report_page_receipt(
            repository, patched, composition_artifacts
        )
    except BaseException:
        await fail_composition_execution("REPORT_ASSISTANT_COMPOSE_FAILED")
        raise
    artifact_receipts = tuple(
        {
            "alias": "source_artifact" if index == 1 else f"source_artifact_{index}",
            "checksum": str(item["artifact_checksum"]),
        }
        for index, item in enumerate(composition_artifacts, start=1)
    )
    decision = {
        "change_kind": "existing_artifact",
        "message": proposal["message"],
        "analysis_plan": plan.model_dump(mode="json"),
        "patch": patch.model_dump(mode="json"),
        "source_instruction": source_instruction,
        "exact_page_count": exact_page_count,
        "verified_page_count": verified_page_count,
        "page_renderer_fingerprint": page_renderer_fingerprint,
        "artifact_receipts": artifact_receipts,
    }
    decision_hash = hashlib.sha256(
        json.dumps(decision, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "decision_hash": decision_hash,
        "model_version": str(trace["model_version"]),
        "prompt_id": str(trace["prompt_id"]),
        "prompt_version": str(trace["prompt_version"]),
        "prompt_hash": str(trace["prompt_hash"]),
        "patch": patch.model_dump(mode="json"),
        "patch_preview": _report_patch_preview(definition, patch),
        "verified_page_count": verified_page_count,
        "page_renderer_fingerprint": page_renderer_fingerprint,
        "model_execution_id": model_execution_id,
        "trace": trace,
    }


async def _resume_waiting_assistant_artifact(
    repository: Any,
    assistant_request_id: str,
    session: dict[str, Any],
    plan: ReportAssistantAnalysisPlan,
) -> dict[str, Any]:
    """staged Artifact lineage로 동의 후 합성을 재개하되 분석 실행은 반복하지 않는다."""

    artifact_id = session.get("result_artifact_id")
    query_id = session.get("result_query_id")
    checksum = session.get("result_artifact_checksum")
    if not artifact_id or not query_id or re.fullmatch(r"[0-9a-f]{64}", str(checksum)) is None:
        raise ValueError("ASSISTANT_STATE_CONFLICT")
    artifact = await repository.get_assistant_result_artifact(
        str(artifact_id), str(plan.request_id), str(query_id)
    )
    composition_artifact = await repository.get_assistant_artifact(str(artifact_id))
    if (
        str(artifact.get("artifact_checksum")) != str(checksum)
        or str(composition_artifact.get("trino_query_id")) != str(query_id)
        or str(composition_artifact.get("artifact_checksum")) != str(checksum)
    ):
        raise ValueError("ARTIFACT_LINEAGE_MISMATCH")
    prepared = await _prepare_assistant_revision(
        repository, assistant_request_id, session, composition_artifact, plan
    )
    try:
        return await repository.save_assistant_result_artifact(
            assistant_request_id,
            str(plan.request_id),
            artifact,
            patch_request_id=str(uuid4()),
            decision_hash=prepared["decision_hash"],
            model_version=prepared["model_version"],
            prompt_id=prepared["prompt_id"],
            prompt_version=prepared["prompt_version"],
            prompt_hash=prepared["prompt_hash"],
            patch=prepared["patch"],
            patch_preview=prepared["patch_preview"],
            verified_page_count=prepared["verified_page_count"],
            page_renderer_fingerprint=prepared["page_renderer_fingerprint"],
            model_execution_id=prepared["model_execution_id"],
        )
    except BaseException:
        await repository.fail_assistant_request(
            assistant_request_id,
            "REPORT_ASSISTANT_COMPOSE_FAILED",
            str(plan.request_id),
            expected_phase="waiting_artifact",
            expected_message_revision=session.get("message_revision"),
            model_execution_id=prepared["model_execution_id"],
        )
        raise


async def _compose_assistant_revision(
    repository: Any,
    assistant_request_id: str,
    data_request_id: str,
    session: dict[str, Any],
    _plan: ReportAssistantAnalysisPlan,
) -> dict[str, Any]:
    """``saving_revision``에 고정된 typed patch만 재검증해 CAS Revision을 완료한다."""

    if session.get("phase") != "saving_revision" or not session.get("result_artifact_id"):
        raise ValueError("ASSISTANT_STATE_CONFLICT")
    try:
        patch = ReportAssistantPatch.model_validate(session.get("report_patch_json"))
        definition = await repository.get_version(
            str(session["session_definition_id"]),
            int(session["session_definition_version"]),
        )
        artifacts = await _session_artifacts(repository, assistant_request_id, session)
        patched = await _apply_existing_artifact_patch(
            repository, definition, artifacts, patch
        )
    except (KeyError, TypeError, ValueError) as error:
        if str(error) == "REPORT_REVISION_CONFLICT":
            raise
        raise ValueError("REPORT_ASSISTANT_PATCH_INVALID") from error
    return await repository.finalize_existing_assistant_patch(
        assistant_request_id,
        None,
        str(session["decision_hash"]),
        str(session["model_version"]),
        str(session["prompt_id"]),
        str(session["prompt_version"]),
        str(session["prompt_hash"]),
        patch.model_dump(mode="json"),
        patched,
        data_request_id=data_request_id,
        expected_phase="saving_revision",
    )


@report_router.post(
    "/reports/definitions",
    operation_id="reportCreateDefinition",
    response_model=ReportDefinitionResponse,
)
async def create_definition(
    payload: CreateReportDefinitionRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """[책임] 검증된 제목, 블록 레이아웃 및 표시 설정으로 소유자 범위의 신규 보고서 정의(v1 draft)를 생성한다.
    - 입출력: CreateReportDefinitionRequest 및 RequestContext 수신 → 생성된 보고서 메타데이터 딕셔너리 반환
    - 주의조건: 블록 수(최대 50개) 초과, 레이아웃 행 수 초과 또는 권한 부재 시 HTTP 에러 반환
    """
    return await _call(
        lambda: _router(context).create_definition(
            payload.model_dump(mode="json", exclude_none=True)
        )
    )


@report_router.post(
    "/reports/drafts/from-analysis-artifact",
    operation_id="reportCreateDraftFromAnalysisArtifact",
    response_model=ReportDefinitionResponse,
)
async def create_draft_from_analysis_artifact(
    payload: CreateReportFromArtifactRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """[책임] 기존 완료된 분석 결과 아티팩트(Artifact)를 기반으로 신규 보고서 초안(Draft)을 자동 생성한다.
    - 입출력: CreateReportFromArtifactRequest 및 RequestContext 수신 → 아티팩트가 바인딩된 보고서 정의 반환
    - 주의조건: 아티팩트 소유권 불일치, 만료되었거나 존재하지 않는 artifact_id 인입 시 에러 발생
    """
    return await _create_artifact_draft(_router(context), payload, _repository_call)


@report_router.get(
    "/reports/definitions/{definition_id}/versions/{version}/artifacts/{artifact_id}",
    operation_id="reportGetArtifact",
    response_model=ReportArtifactResponse,
)
async def get_report_artifact(
    definition_id: str,
    version: int,
    artifact_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """definition version이 참조하고 사용자가 열람 가능한 분석 artifact만 전송 계약으로 반환한다.

    저장소가 definition·version·artifact 연결과 소유권을 함께 검사하며 부재는 404로 닫힌다.
    """
    artifact = await _repository_call(
        lambda: _router(context).repository.get_report_artifact(
            definition_id, version, artifact_id
        )
    )
    return _report_artifact_response(artifact)


@report_router.get(
    "/reports/definitions",
    operation_id="reportListDefinitions",
    response_model=ReportDefinitionListResponse,
)
async def list_definitions(
    context: Annotated[RequestContext, Depends(report_draft_context)],
    archived: bool = False,
) -> dict[str, Any]:
    """기본 active 목록 또는 명시한 archived 목록을 역할 범위와 소유권에 맞게 반환한다."""
    return await _call(
        lambda: _router(context).list_definitions(archived=archived)
    )


@report_router.post(
    "/reports/definitions/{definition_id}/archive",
    operation_id="reportArchiveDefinition",
    response_model=ReportDefinitionLifecycleResponse,
)
async def archive_definition(
    definition_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """권한 범위의 보고서를 비파괴 보관하고 진행 중 실행·Assistant가 있으면 409로 거부한다."""

    return await _call(
        lambda: _router(context).archive_definition(
            definition_id,
            actor_role=context.role.value,
            trace_id=context.trace_id,
        )
    )


@report_router.post(
    "/reports/definitions/{definition_id}/restore",
    operation_id="reportRestoreDefinition",
    response_model=ReportDefinitionLifecycleResponse,
)
async def restore_definition(
    definition_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """권한 범위의 보고서를 복원하되 보관 시 비활성화한 schedule은 자동으로 다시 켜지 않는다."""

    return await _call(
        lambda: _router(context).restore_definition(
            definition_id,
            actor_role=context.role.value,
            trace_id=context.trace_id,
        )
    )


@report_router.delete(
    "/reports/definitions/{definition_id}",
    operation_id="reportPermanentlyDeleteDefinition",
    response_model=ReportDefinitionPermanentDeleteResponse,
)
async def permanently_delete_definition(
    definition_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """휴지통의 권한 범위 보고서만 복원 불가능하게 제거하고 최소 감사 이벤트를 남긴다."""

    return await _call(
        lambda: _router(context).permanently_delete_definition(
            definition_id,
            actor_role=context.role.value,
            trace_id=context.trace_id,
        )
    )


@report_router.post(
    "/reports/definitions/{definition_id}/versions/{version}/approve",
    operation_id="reportApproveVersion",
    response_model=ReportDefinitionResponse,
)
async def approve_version(
    definition_id: str,
    version: int,
    payload: ApproveReportVersionRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    """관리자가 지정한 draft를 승인 시각에 불변 HTML·PDF 문서와 함께 확정한다.

    저장 orientation 불일치, 비-DRAFT 상태, 미존재 및 renderer 실패는 지원 계층의 구분된
    409·404·503 응답으로 반환되고 실패 시 승인 write는 남지 않는다.
    """
    return await _approve_report_version(
        _router(context),
        definition_id,
        version,
        payload.approved_at,
        payload.orientation,
    )


@report_router.get(
    "/reports/definitions/{definition_id}/versions/{version}/document",
    operation_id="reportGetFinalDocument",
    response_model=ReportDocumentResponse,
)
async def get_final_document(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """열람 권한이 있는 승인 version의 renderer·source·HTML·PDF checksum metadata를 반환한다.

    문서 bytes는 포함하지 않으며 저장소에서 찾을 수 없거나 비소유인 대상은 404로 처리한다.
    """
    document = await _repository_call(
        lambda: _router(context).repository.get_document(definition_id, version)
    )
    return _document_response(document)


@report_router.get(
    "/reports/definitions/{definition_id}/versions/{version}/document.html",
    operation_id="reportGetFinalHtml",
    response_class=HTMLResponse,
)
async def get_final_html(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> HTMLResponse:
    """승인 version의 저장 HTML snapshot을 checksum ETag·CSP가 포함된 응답으로 반환한다.

    repository가 definition 소유권과 문서 존재를 검증하며 동적 재렌더링은 수행하지 않는다.
    """
    document = await _repository_call(
        lambda: _router(context).repository.get_document(definition_id, version)
    )
    return _final_html_response(document)


@report_router.get(
    "/reports/definitions/{definition_id}/versions/{version}/document.pdf",
    operation_id="reportGetFinalPdf",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}}
            }
        }
    },
)
async def get_final_pdf(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> Response:
    """승인 version에 영속된 PDF/A bytes를 checksum ETag와 version 파일명으로 반환한다.

    요청 시점에 문서를 다시 만들지 않으며 미존재·비소유 대상은 공통 repository 404로 닫힌다.
    """
    document = await _repository_call(
        lambda: _router(context).repository.get_document(definition_id, version)
    )
    return _final_pdf_response(document, definition_id, version)


@report_router.post(
    "/reports/definitions/{definition_id}/versions/{version}/drafts",
    operation_id="reportCreateNextDraft",
    response_model=ReportDefinitionResponse,
)
async def create_next_draft(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """소유한 승인 version을 복제해 다음 번호의 편집 가능한 draft를 원자 생성한다.

    대상 부재는 404, 비승인 기준본이나 동시 version 충돌은 409로 변환한다.
    """
    return await _call(lambda: _router(context).create_next_draft(definition_id, version))


@report_router.get(
    "/reports/definitions/{definition_id}/versions/{version}",
    operation_id="reportGetDefinitionVersion",
    response_model=ReportDefinitionResponse,
)
async def get_version(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """사용자 역할 범위에서 definition ID와 version이 일치하는 보고서 계약을 반환한다.

    저장소가 소유권 필터를 적용하며 조회할 수 없는 대상은 404로 정규화한다.
    """
    return await _call(lambda: _router(context).get_version(definition_id, version))


@report_router.put(
    "/reports/definitions/{definition_id}/versions/{version}/blocks",
    operation_id="reportReplaceDraftBlocks",
    response_model=ReportDefinitionResponse,
)
async def replace_draft_blocks(
    definition_id: str,
    version: int,
    payload: ReplaceReportBlocksRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """draft 제목·blocks·표시 설정을 현재 상태와 충돌 확인 후 원자적으로 반영한다."""
    return await _call(
        lambda: _router(context).replace_draft_blocks(
            definition_id,
            version,
            payload.model_dump(mode="json", exclude_none=True),
        )
    )


@report_router.get(
    "/reports/runs",
    operation_id="reportListRuns",
    response_model=ReportRunListResponse,
)
async def list_runs(
    context: Annotated[RequestContext, Depends(report_admin_context)],
    definition_id: str | None = None,
) -> dict[str, Any]:
    """관리 권한 범위의 report run을 선택한 definition ID로 좁혀 생성 순서대로 반환한다."""
    return await _call(lambda: _router(context).list_runs(definition_id))


@report_router.post(
    "/reports/runs/manual",
    operation_id="reportCreateManualRunCommand",
    response_model=ManualRunCommandResponse,
)
async def create_manual_run_command(
    payload: CreateManualRunRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    """관리자의 definition version·멱등 키를 서버 기준일의 수동 실행 명령으로 등록한다.

    claim 가능한 영속 repository에서는 같은 멱등 키의 중복 실행을 막고 완료 run ID와 상태를
    응답한다. 일반 replay에는 client 기준일 입력을 허용하지 않으며, 입력·미존재·상태 충돌은
    router의 422·404·409 계약을 따른다.
    """
    router = _router(context)
    server_as_of = datetime.combine(
        context.as_of,
        datetime.min.time(),
        tzinfo=ZoneInfo(context.timezone),
    )
    command_payload = {
        **payload.model_dump(mode="json"),
        "as_of": server_as_of.isoformat(),
    }
    command = await _call(
        lambda: router.create_manual_run_command(command_payload)
    )
    if not hasattr(router.repository, "claim_manual_run"):
        return command
    service = _execution_service(router.repository)
    executed = await service.execute_manual_run(command["command_id"])
    run = router._run_response(executed)
    return {**command, "status": run["status"], "run_id": run["run_id"]}


@report_router.get(
    "/reports/runs/{run_id}",
    operation_id="reportGetRun",
    response_model=ReportRunResponse,
)
async def get_run(
    run_id: str,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    """관리 권한 범위에서 run ID에 해당하는 실행 상태와 block별 evidence를 반환한다.

    조회할 수 없는 run은 저장소의 ``KeyError``를 404로 변환해 존재 여부를 숨긴다.
    """
    return await _call(lambda: _router(context).get_run(run_id))


@report_router.post(
    "/reports/schedules",
    operation_id="reportCreateSchedule",
    response_model=ReportScheduleResponse,
)
async def create_schedule(
    payload: CreateReportScheduleRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    """관리자가 지정한 definition version·cadence·timezone·최초 실행 시각을 일정으로 저장한다.

    repository transaction이 대상 version과 schedule ID 고유성을 검증하며 오류는 404 또는
    422로 매핑된다.
    """
    repository = _router(context).repository
    return await _repository_call(
        lambda: repository.create_schedule(
            str(payload.schedule_id),
            str(payload.definition_id),
            payload.version,
            payload.cadence,
            payload.timezone,
            payload.next_run_at,
        )
    )


@report_router.get(
    "/reports/schedules",
    operation_id="reportListSchedules",
    response_model=ReportScheduleListResponse,
)
async def list_schedules(
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    """관리 권한 범위의 report schedule과 next-run 상태를 생성 순서대로 반환한다."""
    repository = _router(context).repository
    return {"items": list(await _repository_call(repository.list_schedules))}


@report_router.put(
    "/reports/schedules/{schedule_id}",
    operation_id="reportUpdateSchedule",
    response_model=ReportScheduleResponse,
)
async def update_schedule(
    schedule_id: str,
    payload: UpdateReportScheduleRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    """스케줄 변경을 현재 상태와 충돌 여부를 확인한 뒤 원자적으로 반영한다."""
    repository = _router(context).repository
    return await _repository_call(
        lambda: repository.set_schedule_enabled(schedule_id, payload.enabled)
    )


@report_router.post(
    "/reports/schedules/{schedule_id}/run-due",
    operation_id="reportRunDueSchedule",
    response_model=RunDueReportScheduleResponse,
)
async def run_due_schedule(
    schedule_id: str,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    """관리자가 지정한 schedule이 현재 DUE일 때만 한 번 실행하고 갱신 상태를 반환한다.

    저장소의 next-run claim과 실행 service를 같은 요청에서 사용해 중복 실행을 막으며,
    아직 DUE가 아니면 새 run을 만들지 않고 ``executed=false``로 응답한다.
    """
    router = _router(context)
    service = _execution_service(router.repository)
    schedule, run = await _repository_call(
        lambda: service.run_due_schedule(
            schedule_id, datetime.now(timezone.utc)
        )
    )
    return {
        "schedule": schedule,
        "executed": run is not None,
        "run": router._run_response(run) if run is not None else None,
    }


@report_router.post(
    "/reports/assistant/sessions",
    operation_id="reportAssistantCreateSession",
    response_model=ReportAssistantSessionResponse,
)
async def create_assistant_session(
    payload: CreateReportAssistantSessionRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """현재 draft와 그 안의 승인 artifact를 검증해 복구 가능한 Assistant 세션을 연다."""

    repository = _router(context).repository
    counter = getattr(repository, "count_recent_assistant_requests", None)
    if callable(counter):
        try:
            hourly_limit = int(os.getenv("REPORT_ASSISTANT_REQUESTS_PER_HOUR", "30"))
        except ValueError as error:
            raise HTTPException(status_code=500, detail="Assistant rate limit 설정이 유효하지 않습니다.") from error
        if hourly_limit < 1:
            raise HTTPException(status_code=500, detail="Assistant rate limit 설정이 유효하지 않습니다.")
        recent = await counter(datetime.now(timezone.utc) - timedelta(hours=1))
        if recent >= hourly_limit:
            raise HTTPException(
                status_code=429,
                detail={"code": "ASSISTANT_RATE_LIMITED"},
            )
    assistant_request_id = str(uuid4())
    from src.ai.prompt_registry import get_prompt

    prompt = get_prompt("report.assistant")
    binding = (
        f"{payload.definition_id}:{payload.definition_version}:"
        f"{payload.artifact_id}:{','.join(map(str, payload.additional_artifact_ids))}"
    )
    session = await _repository_call(
        lambda: repository.start_assistant_session(
            assistant_request_id,
            str(payload.definition_id),
            payload.definition_version,
            str(payload.artifact_id),
            hashlib.sha256(binding.encode("utf-8")).hexdigest(),
            prompt.prompt_id,
            prompt.version,
            str(prompt.metadata()["hash"]),
            tuple(map(str, payload.additional_artifact_ids)),
        )
    )
    return _assistant_session_response(session)


@report_router.get(
    "/reports/assistant/sessions/{assistant_request_id}",
    operation_id="reportAssistantGetSession",
    response_model=ReportAssistantSessionResponse,
)
async def get_assistant_session(
    assistant_request_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """새로고침 후에도 서버에 저장된 현재 Assistant phase와 승인 계획을 복구한다."""

    repository = _router(context).repository
    session = await _repository_call(
        lambda: _recover_and_get_assistant_session(repository, assistant_request_id)
    )
    return _assistant_session_response(session)


@report_router.get(
    "/reports/assistant/sessions/{assistant_request_id}/external-transfer-disclosure",
    operation_id="reportAssistantGetExternalTransferDisclosure",
    response_model=ReportAssistantExternalTransferDisclosureResponse,
)
async def get_assistant_external_transfer_disclosure(
    assistant_request_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> ReportAssistantExternalTransferDisclosureResponse:
    """새로고침 뒤 현재 owner 세션의 최신 미만료 외부 전송 공개문을 복구한다."""

    from app.services.report_assistant_external_transfer import (
        latest_report_assistant_transfer_disclosure,
    )

    repository = _router(context).repository
    try:
        return await latest_report_assistant_transfer_disclosure(
            repository, assistant_request_id
        )
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "EXTERNAL_TRANSFER_DISCLOSURE_NOT_FOUND",
                "assistant_request_id": assistant_request_id,
            },
        ) from error


@report_router.post(
    "/reports/assistant/sessions/{assistant_request_id}/external-transfer-consent",
    operation_id="reportAssistantAcceptExternalTransfer",
    response_model=ReportAssistantExternalTransferConsentResponse,
)
async def accept_assistant_external_transfer_consent(
    assistant_request_id: str,
    payload: ReportAssistantExternalTransferConsentRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> ReportAssistantExternalTransferConsentResponse:
    """기본 미동의 공개문을 현재 세션 결속과 재검증한 뒤 명시 수락 receipt로 저장한다."""

    from app.services.report_assistant_external_transfer import (
        accept_report_assistant_external_transfer,
    )

    repository = _router(context).repository
    try:
        session = await repository.get_assistant_session(assistant_request_id)
        artifacts = await _session_artifacts(repository, assistant_request_id, session)
        return await accept_report_assistant_external_transfer(
            repository,
            assistant_request_id=assistant_request_id,
            disclosure_id=str(payload.disclosure_id),
            disclosure_hash=payload.disclosure_hash,
            session=session,
            artifacts=artifacts,
        )
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "EXTERNAL_TRANSFER_DISCLOSURE_NOT_FOUND",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    except (OSError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXTERNAL_TRANSFER_DISCLOSURE_STALE",
                "assistant_request_id": assistant_request_id,
            },
        ) from error


@report_router.post(
    "/reports/assistant/sessions/{assistant_request_id}/cancel",
    operation_id="reportAssistantCancelSession",
    response_model=ReportAssistantSessionResponse,
)
async def cancel_assistant_session(
    assistant_request_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """대기 중인 소유자 세션만 취소하고 실행·Revision 저장 중인 요청은 그대로 둔다."""

    repository = _router(context).repository
    try:
        session, _claimed = await repository.cancel_assistant_session(assistant_request_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ASSISTANT_CANCEL_NOT_ALLOWED",
                "assistant_request_id": assistant_request_id,
                "retryable": False,
                "required_action": ReportAssistantRequiredAction.REFRESH.value,
            },
        ) from error
    await _observe_assistant(
        repository,
        "finalize_assistant_evaluation",
        assistant_request_id,
        error_code="ASSISTANT_CANCELLED" if session["phase"] == "cancelled" else None,
    )
    return _assistant_session_response(session)


@report_router.post(
    "/reports/assistant/sessions/{assistant_request_id}/retry",
    operation_id="reportAssistantRetrySession",
    response_model=ReportAssistantSessionResponse,
)
async def retry_assistant_session(
    assistant_request_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """재시도 가능한 실패를 동일 근거의 새 ``ready`` 세션으로만 이어 간다.

    원본 실패·승인·요청 ID를 변경하거나 복사하지 않으며 Report revision과 승인 Artifact
    lineage를 다시 확인한다. 이 요청은 모델, 분석 controller, Revision 저장을 호출하지 않는다.
    """

    repository = _router(context).repository
    session = await _repository_call(
        lambda: repository.get_assistant_session(assistant_request_id)
    )
    if session["phase"] != "failed" or session.get("status") != "failed":
        raise _assistant_retry_error(
            assistant_request_id,
            "ASSISTANT_STATE_CONFLICT",
            ReportAssistantRequiredAction.REFRESH,
        )
    policy = report_assistant_retry_policy(session.get("error_code"))
    if not policy.retryable:
        raise _assistant_retry_error(
            assistant_request_id,
            str(session.get("error_code") or "ASSISTANT_RETRY_NOT_ALLOWED"),
            policy.required_action,
        )

    try:
        definition = await repository.get_version(
            str(session["session_definition_id"]),
            int(session["session_definition_version"]),
        )
        current_revision = await repository.get_draft_revision(
            str(session["session_definition_id"]),
            int(session["session_definition_version"]),
        )
    except (KeyError, ValueError):
        raise _assistant_retry_error(
            assistant_request_id,
            "REPORT_REVISION_CONFLICT",
            ReportAssistantRequiredAction.REOPEN_LATEST_REPORT,
        ) from None
    if (
        definition.status.value != "draft"
        or current_revision != int(session["base_revision"])
    ):
        raise _assistant_retry_error(
            assistant_request_id,
            "REPORT_REVISION_CONFLICT",
            ReportAssistantRequiredAction.REOPEN_LATEST_REPORT,
        )

    try:
        artifact = await repository.get_assistant_artifact(str(session["artifact_id"]))
    except (KeyError, ValueError):
        raise _assistant_retry_error(
            assistant_request_id,
            "ARTIFACT_LINEAGE_MISMATCH",
            ReportAssistantRequiredAction.CONTACT_ADMIN,
        ) from None
    if (
        not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("artifact_checksum") or ""))
        or not artifact.get("trino_query_id")
    ):
        raise _assistant_retry_error(
            assistant_request_id,
            "ARTIFACT_LINEAGE_MISMATCH",
            ReportAssistantRequiredAction.CONTACT_ADMIN,
        )

    from src.ai.prompt_registry import get_prompt

    prompt = get_prompt("report.assistant")
    retry_request_id = str(uuid4())
    binding = (
        f"{session['session_definition_id']}:{session['session_definition_version']}:"
        f"{session['artifact_id']}:retry:{assistant_request_id}:"
        f"{session.get('source_instruction') or ''}:"
        f"{session.get('exact_page_count') or ''}:"
        + ",".join(
            f"{item.get('artifact_alias')}:{item.get('artifact_checksum')}"
            for item in session.get("artifact_bindings", ())
        )
    )
    try:
        retried = await repository.retry_assistant_session(
            assistant_request_id,
            retry_request_id,
            hashlib.sha256(binding.encode("utf-8")).hexdigest(),
            prompt.prompt_id,
            prompt.version,
            str(prompt.metadata()["hash"]),
        )
    except ValueError:
        raise _assistant_retry_error(
            assistant_request_id,
            "ASSISTANT_STATE_CONFLICT",
            ReportAssistantRequiredAction.REFRESH,
        ) from None
    return _assistant_session_response(retried)


@report_router.post(
    "/reports/assistant/sessions/{assistant_request_id}/review",
    operation_id="reportAssistantReview",
    response_model=ReportAssistantReviewResponse,
    responses={
        428: {
            "model": ReportAssistantExternalTransferErrorResponse,
            "description": "외부 모델 전송 명시 동의 필요",
        }
    },
)
async def review_assistant_report(
    assistant_request_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
    payload: ReportAssistantReviewRequest | None = None,
) -> dict[str, Any]:
    """현재 Report와 승인 Artifact를 읽기만 하고 typed 품질 finding을 반환한다."""

    from app.adapters.report_assistant import (
        ReportAssistantModelError,
        bind_report_assistant_model_execution,
        generate_report_quality_review,
    )
    from app.api.router import execution_gate
    from src.modelops.runtime import estimate_token_count

    repository = _router(context).repository
    session = await _repository_call(
        lambda: repository.get_assistant_session(assistant_request_id)
    )
    if session["phase"] != "ready":
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    message_revision = session.get("message_revision")
    if isinstance(message_revision, bool) or not isinstance(message_revision, int) or message_revision < 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    model_execution_id: str | None = None

    async def release_review_execution() -> None:
        nonlocal model_execution_id
        if model_execution_id is not None:
            await repository.release_assistant_model_execution(
                assistant_request_id, model_execution_id
            )
            model_execution_id = None

    async def fail_review_execution(error_code: str) -> None:
        """외부 전송 결과가 불명확하면 exact token CAS로 세션을 종결한다."""

        nonlocal model_execution_id
        if model_execution_id is None:
            return
        await repository.fail_assistant_request(
            assistant_request_id,
            error_code,
            expected_phase="ready",
            expected_message_revision=message_revision,
            model_execution_id=model_execution_id,
        )
        model_execution_id = None

    async def observe_review(**observations: Any) -> None:
        await _observe_assistant(
            repository,
            "upsert_assistant_evaluation",
            assistant_request_id,
            expected_message_revision=message_revision,
            **observations,
        )

    artifacts = await _repository_call(
        lambda: _session_artifacts(repository, assistant_request_id, session)
    )
    definition = await _repository_call(
        lambda: repository.get_version(
            str(session["session_definition_id"]),
            int(session["session_definition_version"]),
        )
    )
    try:
        model_payload = _report_turn_payload(
            definition,
            artifacts,
            "Review this report for supported quality issues without changing it.",
            selected_block_id=(payload.selected_block_id if payload else None),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        ) from error
    try:
        model_invocation = await _consented_assistant_model_invocation(
            repository,
            assistant_request_id=assistant_request_id,
            node="report_assistant_review",
            payload=model_payload,
            session=session,
            artifacts=artifacts,
        )
    except ReportAssistantModelError as error:
        await observe_review(
            contract_valid=False,
            model_attempts=error.attempts,
            latency_ms=error.duration_ms,
            error_code=error.code,
            accumulate_usage=True,
        )
        raise HTTPException(
            status_code=(429 if error.code == "ASSISTANT_COST_BUDGET_EXCEEDED" else 500),
            detail={"code": error.code, "assistant_request_id": assistant_request_id},
        ) from error
    try:
        max_input_tokens, max_output_tokens, cost_policy = (
            _report_assistant_model_budget_limits()
        )
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    if max_input_tokens < 1 or max_output_tokens < 1:
        raise HTTPException(status_code=500, detail="Assistant token 제한 설정이 유효하지 않습니다.")
    if estimate_token_count(json.dumps(model_payload, ensure_ascii=False)) > max_input_tokens:
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_TOKEN_BUDGET_EXCEEDED", "assistant_request_id": assistant_request_id},
        )
    if not await execution_gate.acquire(0):
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_CONCURRENCY_LIMITED", "assistant_request_id": assistant_request_id},
        )
    try:
        try:
            model_execution_id = await _claim_assistant_model_execution(
                repository,
                assistant_request_id=assistant_request_id,
                node="report_assistant_review",
                session=session,
                invocation=model_invocation,
            )
            model_invocation = bind_report_assistant_model_execution(
                model_invocation, model_execution_id
            )
            review, trace = await generate_report_quality_review(
                model_payload, invocation=model_invocation
            )
        finally:
            execution_gate.release()
    except ReportAssistantModelError as error:
        outcome_unknown = _external_transfer_outcome_is_unknown(
            model_invocation, error.code
        )
        error_code = (
            "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN" if outcome_unknown else error.code
        )
        if outcome_unknown:
            await fail_review_execution(error_code)
        else:
            await release_review_execution()
        await observe_review(
            contract_valid=False,
            model_attempts=error.attempts,
            latency_ms=error.duration_ms,
            error_code=error_code,
            accumulate_usage=True,
        )
        raise HTTPException(
            status_code=(
                429
                if error_code == "ASSISTANT_COST_BUDGET_EXCEEDED"
                else 409
                if error_code in {
                    "ASSISTANT_MODEL_EXECUTION_CONFLICT",
                    "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN",
                }
                else 500
                if error_code == "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID"
                else 502
            ),
            detail={"code": error_code, "assistant_request_id": assistant_request_id},
        ) from error
    except BaseException:
        if getattr(model_invocation.route, "data_boundary", None) == "external":
            await fail_review_execution("EXTERNAL_TRANSFER_OUTCOME_UNKNOWN")
        else:
            await release_review_execution()
        raise
    try:
        trace = _validated_assistant_model_trace(trace)
    except ValueError as error:
        await release_review_execution()
        raise HTTPException(
            status_code=502,
            detail={
                "code": "REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    if trace.get("output_tokens") is not None and int(trace["output_tokens"]) > max_output_tokens:
        await release_review_execution()
        await observe_review(
            contract_valid=False,
            model_attempts=trace.get("attempts"), latency_ms=trace.get("duration_ms"),
            input_tokens=trace.get("input_tokens"), output_tokens=trace.get("output_tokens"),
            error_code="ASSISTANT_TOKEN_BUDGET_EXCEEDED", accumulate_usage=True,
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_TOKEN_BUDGET_EXCEEDED", "assistant_request_id": assistant_request_id},
        )
    from app.services.report_assistant_operations import estimate_model_cost

    try:
        estimated_cost = estimate_model_cost(
            trace.get("input_tokens"),
            trace.get("output_tokens"),
            policy=cost_policy,
        )
    except BaseException:
        await release_review_execution()
        raise
    if (
        estimated_cost is not None
        and estimated_cost > cost_policy.max_estimated_cost_usd
    ):
        await release_review_execution()
        await observe_review(
            contract_valid=True,
            model_attempts=trace.get("attempts"), latency_ms=trace.get("duration_ms"),
            input_tokens=trace.get("input_tokens"), output_tokens=trace.get("output_tokens"),
            estimated_cost=estimated_cost, error_code="ASSISTANT_COST_BUDGET_EXCEEDED",
            accumulate_usage=True,
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_COST_BUDGET_EXCEEDED", "assistant_request_id": assistant_request_id},
        )
    try:
        summary = str(review["summary"]).strip()
        findings = _validated_report_review(review, definition, artifacts)
        suggestions = _validated_contextual_suggestions(
            review.get("suggestions", ()), definition, artifacts
        )
        if not summary:
            raise ValueError("REPORT_ASSISTANT_REVIEW_INVALID")
    except (KeyError, TypeError, ValueError) as error:
        await release_review_execution()
        await observe_review(
            contract_valid=False,
            model_attempts=trace.get("attempts"), latency_ms=trace.get("duration_ms"),
            input_tokens=trace.get("input_tokens"), output_tokens=trace.get("output_tokens"),
            estimated_cost=estimated_cost, error_code="REPORT_ASSISTANT_REVIEW_INVALID",
            accumulate_usage=True,
        )
        raise HTTPException(
            status_code=502,
            detail={"code": "REPORT_ASSISTANT_REVIEW_INVALID", "assistant_request_id": assistant_request_id},
        ) from error
    try:
        await observe_review(
            contract_valid=True,
            model_attempts=trace.get("attempts"), latency_ms=trace.get("duration_ms"),
            input_tokens=trace.get("input_tokens"), output_tokens=trace.get("output_tokens"),
            estimated_cost=estimated_cost, accumulate_usage=True,
        )
    finally:
        await release_review_execution()
    return {
        "assistant_request_id": assistant_request_id,
        "summary": summary,
        "findings": findings,
        "suggestions": suggestions,
        "trace": {
            "model_version": trace["model_version"],
            "prompt_id": trace["prompt_id"],
            "prompt_version": trace["prompt_version"],
            "prompt_hash": trace["prompt_hash"],
            "attempts": trace["attempts"],
            "duration_ms": trace["duration_ms"],
        },
    }


@report_router.post(
    "/reports/assistant/sessions/{assistant_request_id}/messages",
    operation_id="reportAssistantSubmitMessage",
    response_model=ReportAssistantProposalResponse,
    responses={
        428: {
            "model": ReportAssistantExternalTransferErrorResponse,
            "description": "외부 모델 전송 명시 동의 필요",
        }
    },
)
async def submit_assistant_message(
    assistant_request_id: str,
    payload: ReportAssistantMessageRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """새 지시 또는 승인 대기 patch 재수정을 strict 모델 계약으로 처리한다.

    모델 호출 전 세션과 artifact 소유권을 확인하며, 이 경계에서는 분석 controller나 데이터
    platform을 호출하지 않는다. 동시 요청으로 phase가 바뀌면 기존 계획을 덮지 않고 409다.
    """

    from app.adapters.report_assistant import (
        ReportAssistantModelError,
        bind_report_assistant_model_execution,
        generate_report_change_proposal,
        validate_report_change_operation_scope,
    )

    repository = _router(context).repository
    session = await _repository_call(
        lambda: repository.get_assistant_session(assistant_request_id)
    )
    expected_patch_request_id = payload.expected_patch_request_id
    refining_patch = session["phase"] == "waiting_patch_approval"
    current_patch = None
    operation_scope = payload.operation_scope
    stored_operation_scope = session.get("operation_scope", "full_report")
    message_revision = session.get("message_revision")
    model_execution_id: str | None = None
    if stored_operation_scope not in {"full_report", "report_title"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    if isinstance(message_revision, bool) or not isinstance(message_revision, int) or message_revision < 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    if session["phase"] == "ready":
        if expected_patch_request_id is not None:
            raise HTTPException(
                status_code=409,
                detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
            )
        if stored_operation_scope == "report_title":
            operation_scope = "report_title"
    elif refining_patch:
        if (
            expected_patch_request_id is None
            or str(session.get("patch_request_id")) != str(expected_patch_request_id)
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
            )
        try:
            current_patch = ReportAssistantPatch.model_validate(
                session.get("report_patch_json")
            )
        except (TypeError, ValueError) as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
            ) from error
        if (
            len(current_patch.operations) == 1
            and current_patch.operations[0].op == "set_report_title"
        ):
            operation_scope = "report_title"
    else:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )

    async def observe_message_turn(
        *, expected_revision: int = message_revision, **observations: Any
    ) -> None:
        await _observe_assistant(
            repository,
            "upsert_assistant_evaluation",
            assistant_request_id,
            expected_message_revision=expected_revision,
            **observations,
        )

    async def claim_or_preserve_refinement_failure(
        error_code: str, *, external_outcome_unknown: bool = False
    ) -> bool:
        """Ready turn은 실패를 claim하고, refinement는 승인 대기 patch를 보존한다."""

        nonlocal model_execution_id
        if refining_patch:
            if external_outcome_unknown and model_execution_id is not None:
                claimed = bool(await repository.fail_assistant_request(
                    assistant_request_id,
                    "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN",
                    operation_scope=operation_scope,
                    expected_phase="waiting_patch_approval",
                    expected_message_revision=message_revision,
                    model_execution_id=model_execution_id,
                ))
                if claimed:
                    model_execution_id = None
                return claimed
            if model_execution_id is not None:
                released = await repository.release_assistant_model_execution(
                    assistant_request_id, model_execution_id
                )
                model_execution_id = None
                if not released:
                    return False
            return True
        claimed = bool(await repository.fail_assistant_request(
            assistant_request_id,
            error_code,
            operation_scope=operation_scope,
            expected_phase="ready",
            expected_message_revision=message_revision,
            **(
                {"model_execution_id": model_execution_id}
                if model_execution_id is not None else {}
            ),
        ))
        if claimed:
            model_execution_id = None
        return claimed

    artifacts = await _repository_call(
        lambda: _session_artifacts(repository, assistant_request_id, session)
    )
    definition = await _repository_call(
        lambda: repository.get_version(
            str(session["session_definition_id"]),
            int(session["session_definition_version"]),
        )
    )
    history = await _repository_call(
        lambda: repository.get_assistant_turn_history(assistant_request_id)
    )
    try:
        model_payload = _report_turn_payload(
            definition,
            artifacts,
            payload.instruction,
            history,
            current_patch,
            payload.selected_block_id,
            operation_scope,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        ) from error
    try:
        model_invocation = await _consented_assistant_model_invocation(
            repository,
            assistant_request_id=assistant_request_id,
            node="report_assistant_turn",
            payload=model_payload,
            session=session,
            artifacts=artifacts,
        )
    except ReportAssistantModelError as error:
        error_code = error.code
        if await claim_or_preserve_refinement_failure(error_code):
            await observe_message_turn(
                contract_valid=False,
                model_attempts=error.attempts,
                latency_ms=error.duration_ms,
                error_code=error_code,
            )
        raise HTTPException(
            status_code=(429 if error_code == "ASSISTANT_COST_BUDGET_EXCEEDED" else 500),
            detail={"code": error_code, "assistant_request_id": assistant_request_id},
        ) from error
    from app.api.router import execution_gate
    from src.modelops.runtime import estimate_token_count

    try:
        max_input_tokens, max_output_tokens, cost_policy = (
            _report_assistant_model_budget_limits()
        )
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    estimated_input_tokens = estimate_token_count(
        json.dumps(model_payload, ensure_ascii=False, separators=(",", ":"))
    )
    if estimated_input_tokens > max_input_tokens:
        await observe_message_turn(
            contract_valid=False, error_code="ASSISTANT_TOKEN_BUDGET_EXCEEDED",
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_TOKEN_BUDGET_EXCEEDED", "assistant_request_id": assistant_request_id},
        )
    if not await execution_gate.acquire(0):
        await observe_message_turn(
            contract_valid=False, error_code="ASSISTANT_CONCURRENCY_LIMITED",
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_CONCURRENCY_LIMITED", "assistant_request_id": assistant_request_id},
        )
    try:
        try:
            model_execution_id = await _claim_assistant_model_execution(
                repository,
                assistant_request_id=assistant_request_id,
                node="report_assistant_turn",
                session=session,
                invocation=model_invocation,
            )
            model_invocation = bind_report_assistant_model_execution(
                model_invocation, model_execution_id
            )
            proposal, trace = await generate_report_change_proposal(
                model_payload, invocation=model_invocation
            )
        finally:
            execution_gate.release()
    except ReportAssistantModelError as error:
        external_outcome_unknown = _external_transfer_outcome_is_unknown(
            model_invocation, error.code
        )
        error_code = (
            "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN"
            if external_outcome_unknown else error.code
        )
        if await claim_or_preserve_refinement_failure(
            error_code, external_outcome_unknown=external_outcome_unknown
        ):
            await observe_message_turn(
                contract_valid=False,
                model_attempts=error.attempts,
                latency_ms=error.duration_ms,
                error_code=error_code,
            )
        raise HTTPException(
            status_code=(
                429
                if error_code == "ASSISTANT_COST_BUDGET_EXCEEDED"
                else 409
                if error_code in {
                    "ASSISTANT_MODEL_EXECUTION_CONFLICT",
                    "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN",
                }
                else 500
                if error_code == "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID"
                else 502
            ),
            detail={
                "code": error_code,
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    except BaseException:
        external_outcome_unknown = (
            getattr(model_invocation.route, "data_boundary", None) == "external"
        )
        await claim_or_preserve_refinement_failure(
            (
                "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN"
                if external_outcome_unknown else "ASSISTANT_EXECUTION_INTERRUPTED"
            ),
            external_outcome_unknown=external_outcome_unknown,
        )
        raise
    try:
        trace = _validated_assistant_model_trace(trace)
    except ValueError as error:
        error_code = "REPORT_ASSISTANT_MODEL_CONTRACT_INVALID"
        if await claim_or_preserve_refinement_failure(error_code):
            await observe_message_turn(
                contract_valid=False,
                error_code=error_code,
            )
        raise HTTPException(
            status_code=502,
            detail={"code": error_code, "assistant_request_id": assistant_request_id},
        ) from error
    try:
        validate_report_change_operation_scope(proposal, operation_scope)
    except ValueError as error:
        error_code = "REPORT_ASSISTANT_MODEL_CONTRACT_INVALID"
        if await claim_or_preserve_refinement_failure(error_code):
            await observe_message_turn(
                contract_valid=False,
                model_attempts=(int(trace["attempts"]) if trace.get("attempts") is not None else None),
                latency_ms=(float(trace["duration_ms"]) if trace.get("duration_ms") is not None else None),
                error_code=error_code,
            )
        raise HTTPException(
            status_code=502,
            detail={"code": error_code, "assistant_request_id": assistant_request_id},
        ) from error
    if refining_patch and proposal["change_kind"] != "existing_artifact":
        await claim_or_preserve_refinement_failure(
            "REPORT_ASSISTANT_TURN_MODEL_INVALID"
        )
        await observe_message_turn(
            contract_valid=False,
            error_code="REPORT_ASSISTANT_TURN_MODEL_INVALID",
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "REPORT_ASSISTANT_TURN_MODEL_INVALID",
                "assistant_request_id": assistant_request_id,
            },
        )
    if trace.get("output_tokens") is not None and int(trace["output_tokens"]) > max_output_tokens:
        await claim_or_preserve_refinement_failure(
            "ASSISTANT_TOKEN_BUDGET_EXCEEDED"
        )
        await observe_message_turn(
            contract_valid=False,
            model_attempts=(int(trace["attempts"]) if trace.get("attempts") is not None else None),
            latency_ms=(float(trace["duration_ms"]) if trace.get("duration_ms") is not None else None),
            input_tokens=trace.get("input_tokens"),
            output_tokens=trace.get("output_tokens"), error_code="ASSISTANT_TOKEN_BUDGET_EXCEEDED",
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_TOKEN_BUDGET_EXCEEDED", "assistant_request_id": assistant_request_id},
        )

    from app.services.report_assistant_operations import estimate_model_cost

    input_tokens = trace.get("input_tokens")
    output_tokens = trace.get("output_tokens")
    estimated_cost = estimate_model_cost(
        input_tokens, output_tokens, policy=cost_policy
    )
    if (
        estimated_cost is not None
        and estimated_cost > cost_policy.max_estimated_cost_usd
    ):
        error_code = "ASSISTANT_COST_BUDGET_EXCEEDED"
        if await claim_or_preserve_refinement_failure(error_code):
            await observe_message_turn(
                route=(proposal["change_kind"] if proposal["change_kind"] != "clarification" else None),
                contract_valid=True,
                model_attempts=(int(trace["attempts"]) if trace.get("attempts") is not None else None),
                latency_ms=(float(trace["duration_ms"]) if trace.get("duration_ms") is not None else None),
                input_tokens=input_tokens,
                output_tokens=output_tokens, estimated_cost=estimated_cost,
                error_code=error_code,
            )
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_COST_BUDGET_EXCEEDED", "assistant_request_id": assistant_request_id},
        )

    try:
        suggestions = _validated_contextual_suggestions(
            proposal.get("suggestions", ()), definition, artifacts
        )
    except ValueError as error:
        error_code = "REPORT_ASSISTANT_TURN_MODEL_INVALID"
        if await claim_or_preserve_refinement_failure(error_code):
            await observe_message_turn(
                contract_valid=False,
                error_code=error_code,
            )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "REPORT_ASSISTANT_TURN_MODEL_INVALID",
                "assistant_request_id": assistant_request_id,
            },
        ) from error

    try:
        proposal_exact_page_count = _model_exact_page_count(proposal)
        exact_page_count, source_instruction = _effective_page_constraint(
            session,
            proposal_exact_page_count,
            payload.instruction,
        )
    except ValueError as error:
        error_code = (
            "ASSISTANT_STATE_CONFLICT"
            if str(error) == "ASSISTANT_STATE_CONFLICT"
            else "REPORT_ASSISTANT_TURN_MODEL_INVALID"
        )
        if await claim_or_preserve_refinement_failure(error_code):
            await observe_message_turn(contract_valid=False, error_code=error_code)
        raise HTTPException(
            status_code=409 if error_code == "ASSISTANT_STATE_CONFLICT" else 502,
            detail={"code": error_code, "assistant_request_id": assistant_request_id},
        ) from error

    plan = None
    if proposal["change_kind"] == "new_data":
        try:
            plan = ReportAssistantAnalysisPlan.model_validate(
                {"request_id": uuid4(), **dict(proposal["analysis_plan"])}
            ).model_dump(mode="json")
        except (TypeError, ValueError) as error:
            error_code = "REPORT_ASSISTANT_TURN_MODEL_INVALID"
            if await claim_or_preserve_refinement_failure(error_code):
                await observe_message_turn(
                    route="new_data",
                    contract_valid=False,
                    model_attempts=(int(trace["attempts"]) if trace.get("attempts") is not None else None),
                    latency_ms=(float(trace["duration_ms"]) if trace.get("duration_ms") is not None else None),
                    input_tokens=trace.get("input_tokens"),
                    output_tokens=trace.get("output_tokens"),
                    error_code=error_code,
                )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "REPORT_ASSISTANT_TURN_MODEL_INVALID",
                    "assistant_request_id": assistant_request_id,
                },
            ) from error
    decision = {
        "change_kind": proposal["change_kind"],
        "message": proposal["message"],
        "analysis_plan": plan,
        "patch": proposal["patch"],
        "suggestions": suggestions,
        "source_instruction": source_instruction,
        "exact_page_count": exact_page_count,
    }
    decision_hash = hashlib.sha256(
        json.dumps(decision, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    instruction_hash = hashlib.sha256(payload.instruction.encode("utf-8")).hexdigest()
    patch = None
    try:
        if proposal["change_kind"] in {"clarification", "new_data"}:
            saved = await repository.record_assistant_proposal(
                assistant_request_id,
                instruction_hash,
                decision_hash,
                str(trace["model_version"]),
                str(trace["prompt_id"]),
                str(trace["prompt_version"]),
                str(trace["prompt_hash"]),
                plan,
                payload.instruction,
                str(proposal["message"]),
                str(proposal["change_kind"]),
                operation_scope,
                expected_message_revision=message_revision,
                source_instruction=source_instruction,
                exact_page_count=exact_page_count,
                model_execution_id=model_execution_id,
            )
        else:
            patch = ReportAssistantPatch.model_validate(proposal["patch"])
            from app.report_patch import ReportPatchNoChangesError

            try:
                patched = await _apply_existing_artifact_patch(
                    repository, definition, artifacts, patch
                )
            except ReportPatchNoChangesError as error:
                if refining_patch:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "REPORT_ASSISTANT_PATCH_INVALID",
                            "assistant_request_id": assistant_request_id,
                        },
                    ) from error
                no_change_message = (
                    "요청하신 상태가 현재 보고서에 이미 반영되어 있습니다. "
                    "다른 변경이 필요하면 알려 주세요."
                )
                proposal = {
                    **proposal,
                    "change_kind": "clarification",
                    "message": no_change_message,
                    "patch": None,
                }
                decision_hash = hashlib.sha256(
                    json.dumps(
                        {
                            "change_kind": "clarification",
                            "message": no_change_message,
                            "analysis_plan": None,
                            "patch": None,
                            "suggestions": suggestions,
                            "source_instruction": source_instruction,
                            "exact_page_count": exact_page_count,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()
                patch = None
                saved = await repository.record_assistant_proposal(
                    assistant_request_id,
                    instruction_hash,
                    decision_hash,
                    str(trace["model_version"]),
                    str(trace["prompt_id"]),
                    str(trace["prompt_version"]),
                    str(trace["prompt_hash"]),
                    None,
                    payload.instruction,
                    no_change_message,
                    "clarification",
                    operation_scope,
                    expected_message_revision=message_revision,
                    source_instruction=source_instruction,
                    exact_page_count=exact_page_count,
                    model_execution_id=model_execution_id,
                )
            else:
                verified_page_count, page_renderer_fingerprint = (
                    await _candidate_report_page_receipt(
                        repository, patched, artifacts
                    )
                )
                decision = {
                    **decision,
                    "verified_page_count": verified_page_count,
                    "page_renderer_fingerprint": page_renderer_fingerprint,
                    "artifact_receipts": tuple(
                        {
                            "alias": (
                                "source_artifact"
                                if index == 1 else f"source_artifact_{index}"
                            ),
                            "checksum": str(artifact["artifact_checksum"]),
                        }
                        for index, artifact in enumerate(artifacts, start=1)
                    ),
                }
                decision_hash = hashlib.sha256(
                    json.dumps(decision, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                patch_preview = _report_patch_preview(definition, patch)
                patch_request_id = str(uuid4())
                if refining_patch:
                    try:
                        saved = await repository.replace_existing_assistant_patch_proposal(
                            assistant_request_id,
                            str(expected_patch_request_id),
                            patch_request_id,
                            instruction_hash,
                            decision_hash,
                            str(trace["model_version"]),
                            str(trace["prompt_id"]),
                            str(trace["prompt_version"]),
                            str(trace["prompt_hash"]),
                            patch.model_dump(mode="json"),
                            patch_preview,
                            payload.instruction,
                            str(proposal["message"]),
                            operation_scope,
                            expected_message_revision=message_revision,
                            source_instruction=source_instruction,
                            exact_page_count=exact_page_count,
                            verified_page_count=verified_page_count,
                            page_renderer_fingerprint=page_renderer_fingerprint,
                            model_execution_id=model_execution_id,
                        )
                    except ValueError as error:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "code": "ASSISTANT_STATE_CONFLICT",
                                "assistant_request_id": assistant_request_id,
                            },
                        ) from error
                else:
                    saved = await repository.record_existing_assistant_patch_proposal(
                        assistant_request_id,
                        patch_request_id,
                        instruction_hash,
                        decision_hash,
                        str(trace["model_version"]),
                        str(trace["prompt_id"]),
                        str(trace["prompt_version"]),
                        str(trace["prompt_hash"]),
                        patch.model_dump(mode="json"),
                        patch_preview,
                        payload.instruction,
                        str(proposal["message"]),
                        operation_scope,
                        expected_message_revision=message_revision,
                        source_instruction=source_instruction,
                        exact_page_count=exact_page_count,
                        verified_page_count=verified_page_count,
                        page_renderer_fingerprint=page_renderer_fingerprint,
                        model_execution_id=model_execution_id,
                    )
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        await claim_or_preserve_refinement_failure(
            str(detail.get("code") or "ASSISTANT_STATE_CONFLICT")
        )
        raise
    except _ReportAssistantPageRenderError as error:
        error_code = "REPORT_ASSISTANT_PAGE_RENDER_FAILED"
        if await claim_or_preserve_refinement_failure(error_code):
            await observe_message_turn(
                route="existing_artifact",
                operation_types=(
                    tuple(operation.op for operation in patch.operations)
                    if patch is not None else ()
                ),
                contract_valid=True,
                error_code=error_code,
            )
        raise HTTPException(
            status_code=502,
            detail={"code": error_code, "assistant_request_id": assistant_request_id},
        ) from error
    except ValueError as error:
        conflict = str(error)
        error_code = (
            conflict
            if conflict in {"REPORT_REVISION_CONFLICT", "ASSISTANT_STATE_CONFLICT"}
            else "REPORT_ASSISTANT_PATCH_INVALID"
        )
        should_observe = False
        if (
            error_code not in {"REPORT_REVISION_CONFLICT", "ASSISTANT_STATE_CONFLICT"}
            or model_execution_id is not None
        ):
            should_observe = await claim_or_preserve_refinement_failure(error_code)
        if should_observe:
            await observe_message_turn(
                route=(proposal["change_kind"] if proposal["change_kind"] != "clarification" else None),
                operation_types=(
                    tuple(operation.op for operation in patch.operations)
                    if patch is not None else ()
                ),
                contract_valid=True,
                model_attempts=(int(trace["attempts"]) if trace.get("attempts") is not None else None),
                latency_ms=(float(trace["duration_ms"]) if trace.get("duration_ms") is not None else None),
                input_tokens=trace.get("input_tokens"),
                output_tokens=trace.get("output_tokens"),
                error_code=error_code,
            )
        if error_code == "REPORT_REVISION_CONFLICT":
            raise HTTPException(status_code=409, detail=str(error)) from error
        if error_code == "ASSISTANT_STATE_CONFLICT":
            raise HTTPException(
                status_code=409,
                detail={"code": error_code, "assistant_request_id": assistant_request_id},
            ) from error
        raise HTTPException(
            status_code=502,
            detail={
                "code": error_code,
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    except BaseException:
        await claim_or_preserve_refinement_failure(
            "REPORT_ASSISTANT_COMPOSE_FAILED"
        )
        raise
    model_execution_id = None
    saved_message_revision = saved.get("message_revision")
    if (
        isinstance(saved_message_revision, bool)
        or not isinstance(saved_message_revision, int)
        or saved_message_revision != message_revision + 1
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    await observe_message_turn(
        expected_revision=saved_message_revision,
        route=(proposal["change_kind"] if proposal["change_kind"] != "clarification" else None),
        operation_types=(
            tuple(operation.op for operation in patch.operations)
            if proposal["change_kind"] == "existing_artifact" else ()
        ),
        contract_valid=True,
        model_attempts=(int(trace["attempts"]) if trace.get("attempts") is not None else None),
        latency_ms=(float(trace["duration_ms"]) if trace.get("duration_ms") is not None else None),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
    )
    try:
        saved_session = await repository.get_assistant_session(
            assistant_request_id,
            expected_message_revision=saved_message_revision,
        )
    except (KeyError, ValueError) as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        ) from error
    return {
        "change_kind": proposal["change_kind"],
        "message": proposal["message"],
        "suggestions": suggestions,
        "session": _assistant_session_response(saved_session),
    }


@report_router.post(
    "/reports/assistant/sessions/{assistant_request_id}/patch-approval",
    operation_id="reportAssistantDecidePatch",
    response_model=ReportAssistantSessionResponse,
    responses={
        409: {
            "model": ErrorResponse,
            "description": "페이지 수 제약 불일치 또는 Assistant 세션 상태 충돌",
        },
        502: {
            "model": ErrorResponse,
            "description": "후보 보고서 페이지 renderer 실패",
        },
    },
)
async def decide_assistant_patch(
    assistant_request_id: str,
    payload: ReportAssistantPatchApprovalRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """기존 Artifact patch를 멱등 승인·취소하고 승인된 경우에만 CAS revision을 저장한다."""

    repository = _router(context).repository
    session = await _repository_call(
        lambda: _recover_and_get_assistant_session(repository, assistant_request_id)
    )
    if str(session.get("patch_request_id")) != str(payload.request_id):
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    original_patch: ReportAssistantPatch | None = None
    selected_patch: ReportAssistantPatch | None = None
    selected_indexes: tuple[int, ...] | None = None
    definition = None
    artifacts: tuple[dict[str, Any], ...] = ()
    patched = None
    verified_page_count: int | None = None
    page_renderer_fingerprint: str | None = None
    approval_decision_hash: str | None = None
    if payload.approved:
        try:
            original_patch = ReportAssistantPatch.model_validate(session.get("report_patch_json"))
            requested_indexes = getattr(payload, "operation_indexes", None)
            selected_indexes = (
                tuple(range(len(original_patch.operations)))
                if requested_indexes is None
                else requested_indexes
            )
            if any(index >= len(original_patch.operations) for index in selected_indexes):
                raise ValueError("ASSISTANT_STATE_CONFLICT")
            from app.report_patch import validate_report_patch_dependency_selection

            validate_report_patch_dependency_selection(original_patch, selected_indexes)
            selected_patch = ReportAssistantPatch(
                summary=original_patch.summary,
                operations=tuple(original_patch.operations[index] for index in selected_indexes),
            )
        except (IndexError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ASSISTANT_STATE_CONFLICT",
                    "assistant_request_id": assistant_request_id,
                },
            ) from error
    if session.get("status") != "running":
        decided_at = session.get("approved_at") if payload.approved else session.get("rejected_at")
        if decided_at is not None and session["phase"] in {"completed", "failed", "cancelled"}:
            if payload.approved and _approved_patch_operation_indexes(
                session, original_patch
            ) != selected_indexes:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "ASSISTANT_STATE_CONFLICT",
                        "assistant_request_id": assistant_request_id,
                    },
                )
            await _observe_assistant(
                repository, "finalize_assistant_evaluation", assistant_request_id,
                approval_decision="approved" if payload.approved else "rejected",
                revision_created=True if payload.approved and session["phase"] == "completed" else None,
                duplicate_revision_prevented=bool(payload.approved),
            )
            return _assistant_session_response(session)
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    if payload.approved:
        from app.report_patch import ReportPatchNoChangesError

        try:
            definition = await repository.get_version(
                str(session["session_definition_id"]),
                int(session["session_definition_version"]),
            )
            artifacts = await _session_artifacts(repository, assistant_request_id, session)
            patched = await _apply_existing_artifact_patch(
                repository, definition, artifacts, selected_patch
            )
            full_selection = tuple(range(len(original_patch.operations)))
            stored_verified_page_count = session.get("verified_page_count")
            stored_page_renderer_fingerprint = session.get("page_renderer_fingerprint")
            has_valid_stored_page_receipt = (
                isinstance(stored_verified_page_count, int)
                and not isinstance(stored_verified_page_count, bool)
                and stored_verified_page_count >= 1
                and isinstance(stored_page_renderer_fingerprint, str)
                and len(stored_page_renderer_fingerprint) == 64
                and not any(
                    character not in "0123456789abcdef"
                    for character in stored_page_renderer_fingerprint
                )
            )
            resumes_frozen_selection = (
                session.get("phase") == "saving_revision"
                and _approved_patch_operation_indexes(session, original_patch)
                == selected_indexes
            )
            current_page_renderer_fingerprint = _report_page_renderer_fingerprint()
            stored_page_receipt_is_current = (
                has_valid_stored_page_receipt
                and stored_page_renderer_fingerprint
                == current_page_renderer_fingerprint
            )
            if (
                stored_page_receipt_is_current
                and (
                    resumes_frozen_selection
                    or selected_indexes == full_selection
                )
            ):
                verified_page_count = stored_verified_page_count
                page_renderer_fingerprint = stored_page_renderer_fingerprint
            else:
                verified_page_count, page_renderer_fingerprint = (
                    await _candidate_report_page_receipt(
                        repository, patched, artifacts
                    )
                )
            exact_page_count = session.get("exact_page_count")
            if (
                exact_page_count is not None
                and (
                    isinstance(exact_page_count, bool)
                    or not isinstance(exact_page_count, int)
                    or not 1 <= exact_page_count <= 20
                )
            ):
                raise ValueError("ASSISTANT_STATE_CONFLICT")
            if exact_page_count is not None and exact_page_count != verified_page_count:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED",
                        "assistant_request_id": assistant_request_id,
                        "exact_page_count": exact_page_count,
                        "verified_page_count": verified_page_count,
                    },
                )
            approval_receipt = {
                "proposal_decision_hash": str(session.get("decision_hash") or ""),
                "patch_request_id": str(payload.request_id),
                "selected_operation_indexes": selected_indexes,
                "exact_page_count": exact_page_count,
                "verified_page_count": verified_page_count,
                "page_renderer_fingerprint": page_renderer_fingerprint,
                "artifact_receipts": tuple(
                    {
                        "alias": (
                            "source_artifact"
                            if index == 1 else f"source_artifact_{index}"
                        ),
                        "checksum": str(artifact["artifact_checksum"]),
                    }
                    for index, artifact in enumerate(artifacts, start=1)
                ),
            }
            approval_decision_hash = hashlib.sha256(
                json.dumps(
                    approval_receipt, ensure_ascii=False, sort_keys=True
                ).encode("utf-8")
            ).hexdigest()
        except ReportPatchNoChangesError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "REPORT_ASSISTANT_PATCH_INVALID",
                    "assistant_request_id": assistant_request_id,
                },
            ) from error
        except _ReportAssistantPageRenderError as error:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "REPORT_ASSISTANT_PAGE_RENDER_FAILED",
                    "assistant_request_id": assistant_request_id,
                },
            ) from error
        except (KeyError, TypeError, ValueError) as error:
            error_code = (
                "REPORT_REVISION_CONFLICT"
                if str(error) == "REPORT_REVISION_CONFLICT"
                else "REPORT_ASSISTANT_PATCH_INVALID"
            )
            raise HTTPException(
                status_code=409,
                detail={"code": error_code, "assistant_request_id": assistant_request_id},
            ) from error
    try:
        decided, claimed = await repository.decide_existing_assistant_patch(
            assistant_request_id,
            str(payload.request_id),
            payload.approved,
            selected_indexes,
            verified_page_count=verified_page_count,
            page_renderer_fingerprint=page_renderer_fingerprint,
            approval_decision_hash=approval_decision_hash,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        ) from error
    if not payload.approved:
        await _observe_assistant(
            repository, "finalize_assistant_evaluation", assistant_request_id,
            approval_decision="rejected",
        )
        return _assistant_session_response(_with_artifact_bindings(decided, session))
    if decided["phase"] == "completed":
        await _observe_assistant(
            repository, "finalize_assistant_evaluation", assistant_request_id,
            approval_decision="approved", revision_created=True,
            duplicate_revision_prevented=not claimed,
        )
        return _assistant_session_response(_with_artifact_bindings(decided, session))
    if decided["phase"] != "saving_revision":
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    try:
        if original_patch is None or selected_patch is None or patched is None:
            raise ValueError("ASSISTANT_STATE_CONFLICT")
        completed = await repository.finalize_existing_assistant_patch(
            assistant_request_id,
            str(decided["instruction_hash"]),
            str(decided["decision_hash"]),
            str(decided["model_version"]),
            str(decided["prompt_id"]),
            str(decided["prompt_version"]),
            str(decided["prompt_hash"]),
            original_patch.model_dump(mode="json"),
            patched,
            expected_phase="saving_revision",
        )
    except (KeyError, TypeError, ValueError) as error:
        error_code = (
            "REPORT_REVISION_CONFLICT"
            if str(error) == "REPORT_REVISION_CONFLICT"
            else "REPORT_ASSISTANT_PATCH_INVALID"
        )
        await repository.fail_assistant_request(assistant_request_id, error_code)
        await _observe_assistant(
            repository, "finalize_assistant_evaluation", assistant_request_id,
            approval_decision="approved", error_code=error_code,
        )
        raise HTTPException(
            status_code=409 if error_code == "REPORT_REVISION_CONFLICT" else 502,
            detail={"code": error_code, "assistant_request_id": assistant_request_id},
        ) from error
    await _observe_assistant(
        repository, "finalize_assistant_evaluation", assistant_request_id,
        approval_decision="approved", revision_created=True,
        duplicate_revision_prevented=False,
    )
    return _assistant_session_response(_with_artifact_bindings(completed, session))


@report_router.post(
    "/reports/assistant/sessions/{assistant_request_id}/approval",
    operation_id="reportAssistantDecidePlan",
    response_model=ReportAssistantSessionResponse,
    responses={
        428: {
            "model": ReportAssistantExternalTransferErrorResponse,
            "description": "새 분석 Artifact 외부 전송 명시 동의 필요",
        }
    },
)
async def decide_assistant_plan(
    assistant_request_id: str,
    payload: ReportAssistantApprovalRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """대기 계획을 멱등 승인·거절하고 최초 승인만 기존 분석 경계에서 Artifact까지 실행한다.

    승인 전 owner·request·phase·권한을 검증한다. 거절은 분석을 호출하지 않고 ready로 돌아가며,
    승인 성공은 반환 Artifact lineage를 재검증해 CAS 기반 새 draft revision까지 완료한다.
    """

    router = _router(context)
    repository = router.repository
    session = await _repository_call(
        lambda: _recover_and_get_assistant_session(repository, assistant_request_id)
    )
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="분석 실행 권한이 없습니다.")
    try:
        plan = ReportAssistantAnalysisPlan.model_validate(session.get("analysis_plan_json"))
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        ) from error
    if plan.request_id != payload.request_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    if session.get("status") != "running":
        decided_at = session.get("approved_at") if payload.approved else session.get("rejected_at")
        if decided_at is not None and session["phase"] in {"completed", "failed", "cancelled"}:
            await _observe_assistant(
                repository, "finalize_assistant_evaluation", assistant_request_id,
                approval_decision="approved" if payload.approved else "rejected",
                revision_created=True if payload.approved and session["phase"] == "completed" else None,
                duplicate_revision_prevented=bool(payload.approved),
            )
            return _assistant_session_response(session)
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    try:
        decided, claimed = await repository.decide_assistant_plan(
            assistant_request_id,
            str(payload.request_id),
            payload.approved,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        ) from error
    if not payload.approved:
        await _observe_assistant(
            repository, "finalize_assistant_evaluation", assistant_request_id,
            approval_decision="rejected",
        )
        return _assistant_session_response(decided)
    saved = decided
    if claimed:
        analysis_context = context.model_copy(update={"request_id": payload.request_id})
        try:
            analysis_response = await _execute_assistant_analysis(
                AnalysisRequest(question=plan.question),
                analysis_context,
            )
        except asyncio.CancelledError:
            await _fail_observed_assistant(
                repository,
                assistant_request_id,
                "ASSISTANT_EXECUTION_INTERRUPTED",
                str(payload.request_id),
            )
            raise
        except Exception as error:
            await _fail_observed_assistant(
                repository,
                assistant_request_id, "ANALYSIS_FAILED", str(payload.request_id)
            )
            raise HTTPException(
                status_code=502,
                detail={"code": "ANALYSIS_FAILED", "assistant_request_id": assistant_request_id},
            ) from error
        if not isinstance(analysis_response, AnalysisResponse):
            code = "ANALYSIS_RATE_LIMITED" if analysis_response.status_code == 429 else "ANALYSIS_FAILED"
            await _fail_observed_assistant(
                repository,
                assistant_request_id, code, str(payload.request_id)
            )
            raise HTTPException(
                status_code=analysis_response.status_code,
                detail={"code": code, "assistant_request_id": assistant_request_id},
            )
        artifact_reference = analysis_response.data.artifact
        if (
            analysis_response.data.status not in {AnalysisStatus.SUCCEEDED, AnalysisStatus.PARTIAL}
            or artifact_reference is None
        ):
            error_code = (
                "ANALYSIS_ACCESS_DENIED"
                if analysis_response.error is not None
                and analysis_response.error.code.value == "ACCESS_DENIED"
                else "ANALYSIS_FAILED"
            )
            await _fail_observed_assistant(
                repository,
                assistant_request_id, error_code, str(payload.request_id)
            )
            raise HTTPException(
                status_code=502,
                detail={"code": error_code, "assistant_request_id": assistant_request_id},
            )

        try:
            await repository.mark_assistant_waiting_artifact(
                assistant_request_id, str(payload.request_id)
            )
            artifact = await repository.get_assistant_result_artifact(
                str(artifact_reference.artifact_id),
                str(payload.request_id),
                artifact_reference.query_id,
            )
            composition_artifact = await repository.get_assistant_artifact(
                str(artifact_reference.artifact_id)
            )
            if (
                str(composition_artifact.get("trino_query_id")) != str(artifact["trino_query_id"])
                or str(composition_artifact.get("artifact_checksum"))
                != str(artifact["artifact_checksum"])
            ):
                raise ValueError("ARTIFACT_LINEAGE_MISMATCH")
            saved = await repository.stage_assistant_result_artifact(
                assistant_request_id, str(payload.request_id), artifact
            )
            saved = await _resume_waiting_assistant_artifact(
                repository, assistant_request_id, saved, plan
            )
        except HTTPException as error:
            if error.status_code == 428:
                raise
            detail = error.detail if isinstance(error.detail, dict) else {}
            error_code = str(
                detail.get("code") or "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID"
            )
            if error_code not in {
                "ASSISTANT_CONCURRENCY_LIMITED",
                "ASSISTANT_TOKEN_BUDGET_EXCEEDED",
                "ASSISTANT_COST_BUDGET_EXCEEDED",
                "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID",
            }:
                error_code = "REPORT_ASSISTANT_COMPOSE_FAILED"
            await _fail_observed_assistant(
                repository,
                assistant_request_id,
                error_code,
                str(payload.request_id),
            )
            raise
        except KeyError as error:
            await _fail_observed_assistant(
                repository,
                assistant_request_id, "ARTIFACT_NOT_FOUND", str(payload.request_id)
            )
            raise HTTPException(
                status_code=502,
                detail={"code": "ARTIFACT_NOT_FOUND", "assistant_request_id": assistant_request_id},
            ) from error
        except ValueError as error:
            message = str(error)
            code = "ARTIFACT_CHECKSUM_INVALID" if "checksum" in message.lower() else (
                "ARTIFACT_LINEAGE_MISMATCH"
                if "lineage" in message.lower()
                else "REPORT_ASSISTANT_PATCH_INVALID"
            )
            await _fail_observed_assistant(
                repository,
                assistant_request_id, code, str(payload.request_id)
            )
            raise HTTPException(
                status_code=409 if code.startswith("ARTIFACT_") else 502,
                detail={"code": code, "assistant_request_id": assistant_request_id},
            ) from error
        except _ReportAssistantPageRenderError as error:
            await _fail_observed_assistant(
                repository, assistant_request_id,
                "REPORT_ASSISTANT_PAGE_RENDER_FAILED", str(payload.request_id),
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "REPORT_ASSISTANT_PAGE_RENDER_FAILED",
                    "assistant_request_id": assistant_request_id,
                },
            ) from error
        except RuntimeError as error:
            from app.adapters.report_assistant import ReportAssistantModelError

            error_code = (
                error.code
                if isinstance(error, ReportAssistantModelError)
                else "REPORT_ASSISTANT_COMPOSE_FAILED"
            )
            await _fail_observed_assistant(
                repository, assistant_request_id, error_code, str(payload.request_id)
            )
            raise HTTPException(
                status_code=(
                    429
                    if error_code == "ASSISTANT_COST_BUDGET_EXCEEDED"
                    else 500
                    if error_code == "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID"
                    else 502
                ),
                detail={"code": error_code, "assistant_request_id": assistant_request_id},
            ) from error
    elif saved["phase"] == "waiting_artifact":
        try:
            saved = await _resume_waiting_assistant_artifact(
                repository, assistant_request_id, saved, plan
            )
        except HTTPException as error:
            if error.status_code == 428:
                raise
            detail = error.detail if isinstance(error.detail, dict) else {}
            error_code = str(
                detail.get("code") or "REPORT_ASSISTANT_COMPOSE_FAILED"
            )
            await _fail_observed_assistant(
                repository,
                assistant_request_id,
                error_code,
                str(payload.request_id),
            )
            raise
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            error_code = (
                error.code
                if hasattr(error, "code")
                else "REPORT_ASSISTANT_COMPOSE_FAILED"
            )
            await _fail_observed_assistant(
                repository,
                assistant_request_id,
                str(error_code),
                str(payload.request_id),
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": str(error_code),
                    "assistant_request_id": assistant_request_id,
                },
            ) from error
    elif saved["phase"] == "waiting_patch_approval":
        return _assistant_session_response(saved)
    else:
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    return _assistant_session_response(saved)


def _operations_period(start_at: datetime | None, end_at: datetime | None) -> tuple[datetime, datetime]:
    """운영 조회를 UTC 기준 최대 31일의 유효한 반개구간으로 제한한다."""

    end = end_at or datetime.now(timezone.utc)
    start = start_at or end - timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None or start >= end or end - start > timedelta(days=31):
        raise HTTPException(status_code=422, detail="운영 조회 기간은 timezone 포함 최대 31일이어야 합니다.")
    return start, end


@report_router.get(
    "/reports/assistant/operations/summary",
    operation_id="reportAssistantOperationsSummary",
    response_model=ReportAssistantOperationsSummaryResponse,
)
async def get_assistant_operations_summary(
    context: Annotated[RequestContext, Depends(report_admin_context)],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    """관리자에게만 기간·분모가 포함된 Assistant 품질·비용 집계를 반환한다."""

    start, end = _operations_period(start_at, end_at)
    rows = await _repository_call(
        lambda: _router(context).repository.list_assistant_evaluations(start, end)
    )
    from app.services.report_assistant_operations import summarize_evaluations

    summary = summarize_evaluations(rows)
    return {"period_start": start, "period_end": end, "denominator": len(rows), **summary}


@report_router.get(
    "/reports/assistant/operations/failures",
    operation_id="reportAssistantOperationsFailures",
    response_model=ReportAssistantFailureListResponse,
)
async def get_assistant_operation_failures(
    context: Annotated[RequestContext, Depends(report_admin_context)],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    """관리자에게만 raw prompt·SQL·trace가 제거된 실패 평가를 반환한다."""

    start, end = _operations_period(start_at, end_at)
    rows = await _repository_call(
        lambda: _router(context).repository.list_assistant_evaluations(
            start, end, failures_only=True, limit=100
        )
    )
    return {"period_start": start, "period_end": end, "items": rows}


@report_router.get(
    "/reports/assistant/sessions/{assistant_request_id}/evaluation",
    operation_id="reportAssistantGetEvaluation",
    response_model=ReportAssistantEvaluationResponse,
)
async def get_assistant_evaluation(
    assistant_request_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """분석가는 자신의 평가만, 관리자는 전체 평가를 안전한 계약으로 조회한다."""

    return await _repository_call(
        lambda: _router(context).repository.get_assistant_evaluation(assistant_request_id)
    )


@report_router.post(
    "/reports/assistant/drafts",
    operation_id="reportAssistantLegacyDraftGone",
    status_code=410,
    response_model=None,
    deprecated=True,
    responses={
        410: {
            "model": ErrorResponse,
            "description": (
                "외부 전송 동의와 단계별 승인을 우회하던 단발성 API는 폐기되었습니다. "
                "세션 기반 Report Assistant API를 사용해야 합니다."
            ),
        },
    },
)
async def retired_assistant_draft(
    _context: Annotated[RequestContext, Depends(report_admin_context)],
) -> None:
    """승인 경계를 우회하던 단발성 초안 API를 모델·저장소 접근 전에 영구 거부한다."""

    raise HTTPException(status_code=410)


async def create_run_internal(
    payload: dict[str, Any],
    context: RequestContext,
) -> dict[str, Any]:
    """신뢰된 worker가 전달한 실행 payload를 사용자 범위 router로 검증·영속화한다.

    HTTP route에는 등록되지 않은 내부 adapter hook이며, block evidence와 definition version
    오류는 공개 router와 동일한 ``ReportRouteError`` 계약으로 정규화한다.
    """
    return await _call(lambda: _router(context).create_run(payload))
