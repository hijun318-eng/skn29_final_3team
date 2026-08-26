"""보고서 draft·승인 문서·run·schedule·assistant 명령을 역할별 repository/service에 연결한다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from inspect import isawaitable
import json
import logging
import os
import re
from typing import Annotated, Any, Awaitable, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse

from app.api.report_router_support import (
    _artifact_visible_views,
    _document_response,
    approve_report_version as _approve_report_version,
    build_execution_service as _build_execution_service,
    build_report_router as _build_report_router,
    create_artifact_draft as _create_artifact_draft,
    create_assistant_report_draft as _create_assistant_report_draft,
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
    RequestContext,
)
from app.report_contracts import (
    ApproveReportVersionRequest,
    CreateReportAssistantSessionRequest,
    CreateManualRunRequest,
    CreateReportAssistantDraftRequest,
    CreateReportDefinitionRequest,
    CreateReportFromArtifactRequest,
    CreateReportScheduleRequest,
    ManualRunCommandResponse,
    ReplaceReportBlocksRequest,
    ReportDefinitionListResponse,
    ReportDefinitionResponse,
    ReportDocumentResponse,
    ReportArtifactResponse,
    ReportRunListResponse,
    ReportRunResponse,
    ReportAssistantDraftResponse,
    ReportAssistantAnalysisPlan,
    ReportAssistantApprovalRequest,
    ReportAssistantMessageRequest,
    ReportAssistantPatch,
    ReportAssistantProposalResponse,
    ReportAssistantSessionResponse,
    ReportAssistantEvaluationResponse,
    ReportAssistantFailureListResponse,
    ReportAssistantOperationsSummaryResponse,
    ReportAssistantRequiredAction,
    ReportScheduleListResponse,
    ReportScheduleResponse,
    RunDueReportScheduleResponse,
    UpdateReportScheduleRequest,
    report_assistant_retry_policy,
)


report_router = APIRouter()
logger = logging.getLogger(__name__)


def _assistant_session_response(session: dict[str, Any]) -> dict[str, Any]:
    """저장소 column 이름을 공개 Assistant 세션 계약으로 변환한다."""

    raw_patch = session.get("report_patch_json")
    patch = ReportAssistantPatch.model_validate(raw_patch) if raw_patch else None
    retry_policy = report_assistant_retry_policy(
        session.get("error_code") if session.get("phase") == "failed" else None
    )
    return {
        "assistant_request_id": session["assistant_request_id"],
        "phase": session["phase"],
        "definition_id": session["session_definition_id"],
        "definition_version": session["session_definition_version"],
        "base_revision": session["base_revision"],
        "artifact_id": session["artifact_id"],
        "analysis_plan": session.get("analysis_plan_json"),
        "patch_request_id": session.get("patch_request_id"),
        "patch_summary": patch.summary if patch else None,
        "patch_operations": tuple(operation.op for operation in patch.operations) if patch else (),
        "result_artifact_id": session.get("result_artifact_id"),
        "result_revision": session.get("result_revision"),
        "error_code": session.get("error_code"),
        "retryable": retry_policy.retryable,
        "required_action": retry_policy.required_action,
        "retry_of_assistant_request_id": session.get("retry_of_assistant_request_id"),
    }


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
) -> None:
    """핵심 실패 전이를 먼저 저장한 뒤 평가 실패 결과를 별도 transaction으로 갱신한다."""

    await repository.fail_assistant_request(
        assistant_request_id, error_code, data_request_id
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


def _report_turn_payload(
    definition: Any,
    artifact: dict[str, Any],
    instruction: str,
    history: tuple[dict[str, str], ...] = (),
) -> dict[str, Any]:
    """현재 draft와 검증 Artifact를 실제 ID 대신 서버 별칭으로 모델 입력에 직렬화한다."""

    return {
        "instruction": instruction,
        "history": list(history[-12:]),
        "artifact": {
            "artifact_id": "source_artifact",
            "query_id": "source_query",
            "title": artifact["title"],
            "narrative": artifact["narrative_markdown"],
            "evidence": artifact["evidence_json"],
            "chart_spec": artifact["chart_spec_json"],
            "checksum": artifact["artifact_checksum"],
        },
        "report": {
            "title": definition.title,
            "orientation": definition.orientation,
            "currency_display_unit": definition.currency_display_unit,
            "blocks": [
                {
                    "block_id": block.block_id,
                    "title": block.title,
                    "type": block.type.value,
                    "content": block.content,
                    "artifact_ref": (
                        "source_artifact"
                        if block.artifact_id == str(artifact["artifact_id"])
                        else None
                    ),
                    "x": block.x,
                    "y": block.y,
                    "w": block.w,
                    "h": block.h,
                }
                for block in definition.blocks
            ],
        },
    }


async def _apply_existing_artifact_patch(
    repository: Any,
    definition: Any,
    artifact: dict[str, Any],
    patch: ReportAssistantPatch,
) -> Any:
    """저장 patch를 현재 owner draft와 검증 Artifact에 dry-run해 저장 가능한 정의를 만든다."""

    from app.report_patch import VerifiedArtifactBinding, apply_report_assistant_patch

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
            "source_artifact": VerifiedArtifactBinding(
                str(artifact["artifact_id"]),
                str(artifact["trino_query_id"]),
                str(artifact["artifact_checksum"]),
            )
        },
        previous_definition,
    )


async def _compose_assistant_revision(
    repository: Any,
    assistant_request_id: str,
    data_request_id: str,
    session: dict[str, Any],
    plan: ReportAssistantAnalysisPlan,
) -> dict[str, Any]:
    """새 분석 Artifact를 strict 모델 patch로 합성하고 동일 CAS 저장 경계에서 완료한다.

    이 함수는 분석을 실행하지 않는다. ``saving_revision``에 이미 고정된 Artifact만 다시 읽고,
    모델이 새 분석을 재요청하거나 허용되지 않은 patch를 반환하면 저장 없이 실패한다.
    """

    from app.adapters.report_assistant import (
        ReportAssistantModelError,
        generate_report_change_proposal,
    )
    from app.report_patch import VerifiedArtifactBinding, apply_report_assistant_patch

    if session.get("phase") != "saving_revision" or not session.get("result_artifact_id"):
        raise ValueError("ASSISTANT_STATE_CONFLICT")
    try:
        definition = await repository.get_version(
            str(session["session_definition_id"]),
            int(session["session_definition_version"]),
        )
    except KeyError as error:
        raise ValueError("REPORT_REVISION_CONFLICT") from error
    artifact = await repository.get_assistant_artifact(str(session["result_artifact_id"]))
    history = await repository.get_assistant_turn_history(assistant_request_id)
    proposal, trace = await generate_report_change_proposal(
        _report_turn_payload(definition, artifact, plan.question, history)
    )
    if proposal["change_kind"] != "existing_artifact" or proposal["analysis_plan"] is not None:
        raise ReportAssistantModelError("새 분석 Artifact 합성 모델이 추가 분석을 요청했습니다.")
    patch = ReportAssistantPatch.model_validate(proposal["patch"])
    if patch.operations[0].op == "restore_previous_revision":
        raise ReportAssistantModelError("새 분석 Artifact 합성에서는 이전 revision을 복원할 수 없습니다.")
    patched = apply_report_assistant_patch(
        definition,
        patch,
        {
            "source_artifact": VerifiedArtifactBinding(
                str(artifact["artifact_id"]),
                str(artifact["trino_query_id"]),
                str(artifact["artifact_checksum"]),
            )
        },
    )
    decision = {
        "change_kind": "existing_artifact",
        "message": proposal["message"],
        "analysis_plan": plan.model_dump(mode="json"),
        "patch": patch.model_dump(mode="json"),
    }
    decision_hash = hashlib.sha256(
        json.dumps(decision, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return await repository.finalize_existing_assistant_patch(
        assistant_request_id,
        None,
        decision_hash,
        str(trace["model_version"]),
        str(trace["prompt_id"]),
        str(trace["prompt_version"]),
        str(trace["prompt_hash"]),
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
    """검증된 title·block grid·표시 설정으로 소유자 범위의 version 1 draft를 저장한다.

    도메인 필드 오류와 저장 상태 충돌은 ``_call``을 통해 공개 가능한 HTTP 오류로 변환한다.
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
    """분석 산출물 입력의 소유권과 필드를 검증해 draft 산출물을 생성한다."""
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
) -> dict[str, Any]:
    """분석가에게 자기 보고서만, 관리자에게 허용된 전체 definition version을 최신순으로 반환한다."""
    return await _call(lambda: _router(context).list_definitions())


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
        f"{payload.definition_id}:{payload.definition_version}:{payload.artifact_id}"
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
    except (KeyError, ValueError):
        raise _assistant_retry_error(
            assistant_request_id,
            "REPORT_REVISION_CONFLICT",
            ReportAssistantRequiredAction.REOPEN_LATEST_REPORT,
        ) from None
    if (
        definition.status.value != "draft"
        or definition.revision != int(session["base_revision"])
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
        f"{session['artifact_id']}:retry:{assistant_request_id}"
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
    "/reports/assistant/sessions/{assistant_request_id}/messages",
    operation_id="reportAssistantSubmitMessage",
    response_model=ReportAssistantProposalResponse,
)
async def submit_assistant_message(
    assistant_request_id: str,
    payload: ReportAssistantMessageRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    """ready 세션의 지시를 strict 모델 계약으로 분류하고 새 분석 계획만 승인 대기로 저장한다.

    모델 호출 전 세션과 artifact 소유권을 확인하며, 이 경계에서는 분석 controller나 데이터
    platform을 호출하지 않는다. 동시 요청으로 phase가 바뀌면 기존 계획을 덮지 않고 409다.
    """

    from app.adapters.report_assistant import (
        ReportAssistantModelError,
        generate_report_change_proposal,
    )

    repository = _router(context).repository
    session = await _repository_call(
        lambda: repository.get_assistant_session(assistant_request_id)
    )
    if session["phase"] != "ready":
        raise HTTPException(status_code=409, detail="ready Assistant 세션만 지시를 받을 수 있습니다.")
    artifact = await _repository_call(
        lambda: repository.get_assistant_artifact(str(session["artifact_id"]))
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
    model_payload = _report_turn_payload(
        definition, artifact, payload.instruction, history
    )
    from app.api.router import execution_gate
    from src.modelops.runtime import estimate_token_count

    try:
        max_input_tokens = int(os.getenv("REPORT_ASSISTANT_MAX_INPUT_TOKENS", "16000"))
        max_output_tokens = int(os.getenv("REPORT_ASSISTANT_MAX_OUTPUT_TOKENS", "4096"))
    except ValueError as error:
        raise HTTPException(status_code=500, detail="Assistant token 제한 설정이 유효하지 않습니다.") from error
    estimated_input_tokens = estimate_token_count(
        json.dumps(model_payload, ensure_ascii=False, separators=(",", ":"))
    )
    if max_input_tokens < 1 or max_output_tokens < 1:
        raise HTTPException(status_code=500, detail="Assistant token 제한 설정이 유효하지 않습니다.")
    if estimated_input_tokens > max_input_tokens:
        await _observe_assistant(
            repository, "upsert_assistant_evaluation", assistant_request_id,
            contract_valid=False, error_code="ASSISTANT_TOKEN_BUDGET_EXCEEDED",
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_TOKEN_BUDGET_EXCEEDED", "assistant_request_id": assistant_request_id},
        )
    if not await execution_gate.acquire(0):
        await _observe_assistant(
            repository, "upsert_assistant_evaluation", assistant_request_id,
            contract_valid=False, error_code="ASSISTANT_CONCURRENCY_LIMITED",
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_CONCURRENCY_LIMITED", "assistant_request_id": assistant_request_id},
        )
    try:
        try:
            proposal, trace = await generate_report_change_proposal(model_payload)
        finally:
            execution_gate.release()
    except ReportAssistantModelError as error:
        await _observe_assistant(
            repository,
            "upsert_assistant_evaluation",
            assistant_request_id,
            contract_valid=False,
            error_code="REPORT_ASSISTANT_TURN_MODEL_FAILED",
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "REPORT_ASSISTANT_TURN_MODEL_FAILED",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    if trace.get("output_tokens") is not None and int(trace["output_tokens"]) > max_output_tokens:
        await _observe_assistant(
            repository, "upsert_assistant_evaluation", assistant_request_id,
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

    plan = None
    if proposal["change_kind"] == "new_data":
        try:
            plan = ReportAssistantAnalysisPlan.model_validate(
                {"request_id": uuid4(), **dict(proposal["analysis_plan"])}
            ).model_dump(mode="json")
        except (TypeError, ValueError) as error:
            await _observe_assistant(
                repository,
                "upsert_assistant_evaluation",
                assistant_request_id,
                route="new_data",
                contract_valid=False,
                model_attempts=(int(trace["attempts"]) if trace.get("attempts") is not None else None),
                latency_ms=(float(trace["duration_ms"]) if trace.get("duration_ms") is not None else None),
                input_tokens=trace.get("input_tokens"),
                output_tokens=trace.get("output_tokens"),
                error_code="REPORT_ASSISTANT_TURN_MODEL_INVALID",
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
            )
        else:
            patch = ReportAssistantPatch.model_validate(proposal["patch"])
            await _apply_existing_artifact_patch(repository, definition, artifact, patch)
            saved = await repository.record_existing_assistant_patch_proposal(
                assistant_request_id,
                str(uuid4()),
                instruction_hash,
                decision_hash,
                str(trace["model_version"]),
                str(trace["prompt_id"]),
                str(trace["prompt_version"]),
                str(trace["prompt_hash"]),
                patch.model_dump(mode="json"),
                payload.instruction,
                str(proposal["message"]),
            )
    except ValueError as error:
        error_code = (
            "REPORT_REVISION_CONFLICT"
            if str(error) == "REPORT_REVISION_CONFLICT"
            else "REPORT_ASSISTANT_PATCH_INVALID"
        )
        await _observe_assistant(
            repository,
            "upsert_assistant_evaluation",
            assistant_request_id,
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
        raise HTTPException(
            status_code=502,
            detail={
                "code": error_code,
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    from app.services.report_assistant_operations import estimate_model_cost

    input_tokens = trace.get("input_tokens")
    output_tokens = trace.get("output_tokens")
    try:
        estimated_cost = estimate_model_cost(input_tokens, output_tokens)
    except RuntimeError:
        estimated_cost = None
    raw_cost_limit = os.getenv("REPORT_ASSISTANT_MAX_ESTIMATED_COST_USD", "1.00")
    try:
        from decimal import Decimal

        cost_limit = Decimal(raw_cost_limit)
    except Exception as error:
        raise HTTPException(status_code=500, detail="Assistant 비용 제한 설정이 유효하지 않습니다.") from error
    if cost_limit <= 0:
        raise HTTPException(status_code=500, detail="Assistant 비용 제한 설정이 유효하지 않습니다.")
    if estimated_cost is not None and estimated_cost > cost_limit:
        await repository.fail_assistant_request(
            assistant_request_id, "ASSISTANT_COST_BUDGET_EXCEEDED"
        )
        await _observe_assistant(
            repository, "upsert_assistant_evaluation", assistant_request_id,
            route=(proposal["change_kind"] if proposal["change_kind"] != "clarification" else None),
            contract_valid=True,
            model_attempts=(int(trace["attempts"]) if trace.get("attempts") is not None else None),
            latency_ms=(float(trace["duration_ms"]) if trace.get("duration_ms") is not None else None),
            input_tokens=input_tokens,
            output_tokens=output_tokens, estimated_cost=estimated_cost,
            error_code="ASSISTANT_COST_BUDGET_EXCEEDED",
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "ASSISTANT_COST_BUDGET_EXCEEDED", "assistant_request_id": assistant_request_id},
        )
    await _observe_assistant(
        repository,
        "upsert_assistant_evaluation",
        assistant_request_id,
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
    return {
        "change_kind": proposal["change_kind"],
        "message": proposal["message"],
        "session": _assistant_session_response(saved),
    }


@report_router.post(
    "/reports/assistant/sessions/{assistant_request_id}/patch-approval",
    operation_id="reportAssistantDecidePatch",
    response_model=ReportAssistantSessionResponse,
)
async def decide_assistant_patch(
    assistant_request_id: str,
    payload: ReportAssistantApprovalRequest,
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
        decided, claimed = await repository.decide_existing_assistant_patch(
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
    if decided["phase"] == "completed":
        await _observe_assistant(
            repository, "finalize_assistant_evaluation", assistant_request_id,
            approval_decision="approved", revision_created=True,
            duplicate_revision_prevented=not claimed,
        )
        return _assistant_session_response(decided)
    if decided["phase"] != "saving_revision":
        raise HTTPException(
            status_code=409,
            detail={"code": "ASSISTANT_STATE_CONFLICT", "assistant_request_id": assistant_request_id},
        )
    try:
        patch = ReportAssistantPatch.model_validate(decided.get("report_patch_json"))
        definition = await repository.get_version(
            str(decided["session_definition_id"]),
            int(decided["session_definition_version"]),
        )
        artifact = await repository.get_assistant_artifact(str(decided["artifact_id"]))
        patched = await _apply_existing_artifact_patch(
            repository, definition, artifact, patch
        )
        completed = await repository.finalize_existing_assistant_patch(
            assistant_request_id,
            str(decided["instruction_hash"]),
            str(decided["decision_hash"]),
            str(decided["model_version"]),
            str(decided["prompt_id"]),
            str(decided["prompt_version"]),
            str(decided["prompt_hash"]),
            patch.model_dump(mode="json"),
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
    return _assistant_session_response(completed)


@report_router.post(
    "/reports/assistant/sessions/{assistant_request_id}/approval",
    operation_id="reportAssistantDecidePlan",
    response_model=ReportAssistantSessionResponse,
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
            saved = await repository.save_assistant_result_artifact(
                assistant_request_id, str(payload.request_id), artifact
            )
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
            code = (
                "ARTIFACT_CHECKSUM_INVALID"
                if "checksum" in str(error).lower()
                else "ARTIFACT_LINEAGE_MISMATCH"
            )
            await _fail_observed_assistant(
                repository,
                assistant_request_id, code, str(payload.request_id)
            )
            raise HTTPException(
                status_code=409,
                detail={"code": code, "assistant_request_id": assistant_request_id},
            ) from error
    elif saved["phase"] != "saving_revision":
        return _assistant_session_response(saved)

    try:
        completed = await _compose_assistant_revision(
            repository,
            assistant_request_id,
            str(payload.request_id),
            saved,
            plan,
        )
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
        code = (
            "REPORT_REVISION_CONFLICT"
            if str(error) == "REPORT_REVISION_CONFLICT"
            else "REPORT_ASSISTANT_PATCH_INVALID"
        )
        await _fail_observed_assistant(
            repository,
            assistant_request_id, code, str(payload.request_id)
        )
        raise HTTPException(
            status_code=409 if code == "REPORT_REVISION_CONFLICT" else 502,
            detail={"code": code, "assistant_request_id": assistant_request_id},
        ) from error
    except Exception as error:
        await _fail_observed_assistant(
            repository,
            assistant_request_id, "REPORT_ASSISTANT_COMPOSE_FAILED", str(payload.request_id)
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "REPORT_ASSISTANT_COMPOSE_FAILED",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    await _observe_assistant(
        repository, "finalize_assistant_evaluation", assistant_request_id,
        approval_decision="approved", revision_created=True,
        duplicate_revision_prevented=not claimed,
    )
    return _assistant_session_response(completed)


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
    operation_id="reportAssistantCreateDraft",
    response_model=ReportAssistantDraftResponse,
)
async def create_assistant_draft(
    payload: CreateReportAssistantDraftRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    """관리자 지시와 승인 artifact로 model 기반 보고서 draft를 생성하고 감사 trace를 반환한다.

    artifact 소유권, model 출력 schema, request 상태 기록은 지원 계층이 검증하며 실패 종류별
    HTTP 상태를 보존한다.
    """
    return await _create_assistant_report_draft(
        _router(context), payload, _repository_call
    )


async def create_run_internal(
    payload: dict[str, Any],
    context: RequestContext,
) -> dict[str, Any]:
    """신뢰된 worker가 전달한 실행 payload를 사용자 범위 router로 검증·영속화한다.

    HTTP route에는 등록되지 않은 내부 adapter hook이며, block evidence와 definition version
    오류는 공개 router와 동일한 ``ReportRouteError`` 계약으로 정규화한다.
    """
    return await _call(lambda: _router(context).create_run(payload))
