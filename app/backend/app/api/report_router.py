"""보고서 draft·승인 문서·run·schedule·assistant 명령을 역할별 repository/service에 연결한다."""

from __future__ import annotations

from datetime import datetime, timezone
from inspect import isawaitable
from typing import Annotated, Any, Awaitable, Callable
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
from app.contracts import RequestContext
from app.report_contracts import (
    ApproveReportVersionRequest,
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
    ReportScheduleListResponse,
    ReportScheduleResponse,
    RunDueReportScheduleResponse,
    UpdateReportScheduleRequest,
)


report_router = APIRouter()


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
    """draft blocks 변경을 현재 상태와 충돌 여부를 확인한 뒤 원자적으로 반영한다."""
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
