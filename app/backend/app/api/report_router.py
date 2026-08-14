from __future__ import annotations

import os
import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.context import analysis_context
from app.contracts import RequestContext, Role
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


def report_draft_context(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> RequestContext:
    if context.role not in {Role.HOTEL_ANALYST, Role.REPORT_ADMIN}:
        raise HTTPException(status_code=403, detail="Report 초안 권한이 없습니다.")
    return context


def report_admin_context(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> RequestContext:
    if context.role is not Role.REPORT_ADMIN:
        raise HTTPException(status_code=403, detail="Report 실행 관리 권한이 없습니다.")
    return context


def _router(context: RequestContext):
    from app.adapters.report_repository import PostgresReportRepository
    from src.report.router import create_report_router

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="Report 저장소를 사용할 수 없습니다.")
    return create_report_router(
        PostgresReportRepository(
            database_url,
            context.user_id,
            manage_all=context.role is Role.REPORT_ADMIN,
        )
    )


def _call(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    from src.report.router import ReportRouteError

    try:
        return action()
    except ReportRouteError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _repository_call(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@report_router.post(
    "/reports/definitions",
    operation_id="reportCreateDefinition",
    response_model=ReportDefinitionResponse,
)
def create_definition(
    payload: CreateReportDefinitionRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    return _call(
        lambda: _router(context).create_definition(
            payload.model_dump(mode="json", exclude_none=True)
        )
    )


@report_router.post(
    "/reports/drafts/from-analysis-artifact",
    operation_id="reportCreateDraftFromAnalysisArtifact",
    response_model=ReportDefinitionResponse,
)
def create_draft_from_analysis_artifact(
    payload: CreateReportFromArtifactRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    from src.report.domain import BlockType, DefinitionStatus, ReportBlock, ReportDefinitionVersion

    router = _router(context)
    artifact = _repository_call(
        lambda: router.repository.get_transfer_artifact(str(payload.artifact_id))
    )
    artifact_id = str(artifact["artifact_id"])
    query_id = str(artifact["trino_query_id"])
    blocks = [
        ReportBlock(
            str(uuid4()), "분석 요약", None, 12, None,
            BlockType.TEXT, 0, 0, 12, 4, str(artifact["narrative_markdown"]),
        )
    ]
    y = 4
    if artifact["chart_spec_json"]:
        blocks.append(ReportBlock(
            str(uuid4()), "핵심 추이", artifact_id, 12, query_id,
            BlockType.CHART, 0, y, 12, 6, json.dumps({"showLegend": True}),
        ))
        y += 6
    blocks.append(ReportBlock(
        str(uuid4()), "상세 데이터", artifact_id, 12, query_id,
        BlockType.TABLE, 0, y, 12, 5, json.dumps({"density": "comfortable"}),
    ))
    draft = ReportDefinitionVersion(
        str(uuid4()), 1, DefinitionStatus.DRAFT, payload.title.strip(), tuple(blocks)
    )
    _repository_call(lambda: router.repository.add_draft(draft))
    return router._response(draft)


@report_router.get(
    "/reports/definitions/{definition_id}/versions/{version}/artifacts/{artifact_id}",
    operation_id="reportGetArtifact",
    response_model=ReportArtifactResponse,
)
def get_report_artifact(
    definition_id: str,
    version: int,
    artifact_id: str,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    from src.report.domain import REPORT_CONTRACT_VERSION

    artifact = _repository_call(
        lambda: _router(context).repository.get_report_artifact(
            definition_id, version, artifact_id
        )
    )
    return {
        "contract_version": REPORT_CONTRACT_VERSION,
        "artifact_id": artifact["artifact_id"],
        "query_id": artifact["trino_query_id"],
        "title": artifact["title"],
        "summary": artifact["narrative_markdown"],
        "table": artifact["data_snapshot_json"],
        "chart": artifact["chart_spec_json"] or None,
        "evidence": artifact["evidence_json"],
        "artifact_checksum": artifact["artifact_checksum"],
    }


@report_router.get(
    "/reports/definitions",
    operation_id="reportListDefinitions",
    response_model=ReportDefinitionListResponse,
)
def list_definitions(
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).list_definitions())


@report_router.post(
    "/reports/definitions/{definition_id}/versions/{version}/approve",
    operation_id="reportApproveVersion",
    response_model=ReportDefinitionResponse,
)
def approve_version(
    definition_id: str,
    version: int,
    payload: ApproveReportVersionRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    return _call(
        lambda: _router(context).approve_version(
            definition_id, version, payload.approved_at.isoformat()
        )
    )


@report_router.post(
    "/reports/definitions/{definition_id}/versions/{version}/drafts",
    operation_id="reportCreateNextDraft",
    response_model=ReportDefinitionResponse,
)
def create_next_draft(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).create_next_draft(definition_id, version))


@report_router.get(
    "/reports/definitions/{definition_id}/versions/{version}",
    operation_id="reportGetDefinitionVersion",
    response_model=ReportDefinitionResponse,
)
def get_version(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).get_version(definition_id, version))


@report_router.put(
    "/reports/definitions/{definition_id}/versions/{version}/blocks",
    operation_id="reportReplaceDraftBlocks",
    response_model=ReportDefinitionResponse,
)
def replace_draft_blocks(
    definition_id: str,
    version: int,
    payload: ReplaceReportBlocksRequest,
    context: Annotated[RequestContext, Depends(report_draft_context)],
) -> dict[str, Any]:
    return _call(
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
def list_runs(
    context: Annotated[RequestContext, Depends(report_admin_context)],
    definition_id: str | None = None,
) -> dict[str, Any]:
    return _call(lambda: _router(context).list_runs(definition_id))


@report_router.post(
    "/reports/runs/manual",
    operation_id="reportCreateManualRunCommand",
    response_model=ManualRunCommandResponse,
)
def create_manual_run_command(
    payload: CreateManualRunRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    router = _router(context)
    command = _call(
        lambda: router.create_manual_run_command(payload.model_dump(mode="json"))
    )
    execute = getattr(router.repository, "execute_manual_run", None)
    if execute is None:
        return command
    run = _call(lambda: router._run_response(execute(command["command_id"])))
    return {**command, "status": run["status"], "run_id": run["run_id"]}


@report_router.get(
    "/reports/runs/{run_id}",
    operation_id="reportGetRun",
    response_model=ReportRunResponse,
)
def get_run(
    run_id: str,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).get_run(run_id))


@report_router.post(
    "/reports/schedules",
    operation_id="reportCreateSchedule",
    response_model=ReportScheduleResponse,
)
def create_schedule(
    payload: CreateReportScheduleRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    repository = _router(context).repository
    return _repository_call(
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
def list_schedules(
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    repository = _router(context).repository
    return {"items": list(_repository_call(repository.list_schedules))}


@report_router.put(
    "/reports/schedules/{schedule_id}",
    operation_id="reportUpdateSchedule",
    response_model=ReportScheduleResponse,
)
def update_schedule(
    schedule_id: str,
    payload: UpdateReportScheduleRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    repository = _router(context).repository
    return _repository_call(
        lambda: repository.set_schedule_enabled(schedule_id, payload.enabled)
    )


@report_router.post(
    "/reports/schedules/{schedule_id}/run-due",
    operation_id="reportRunDueSchedule",
    response_model=RunDueReportScheduleResponse,
)
def run_due_schedule(
    schedule_id: str,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    router = _router(context)
    schedule, run = _repository_call(
        lambda: router.repository.run_due_schedule(
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
def create_assistant_draft(
    payload: CreateReportAssistantDraftRequest,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    from app.adapters.report_assistant import (
        ReportAssistantModelError,
        generate_report_draft,
    )
    from src.ai.prompt_registry import get_prompt
    from src.report.domain import (
        BlockType,
        DefinitionStatus,
        ReportBlock,
        ReportDefinitionVersion,
    )

    router = _router(context)
    repository = router.repository
    artifact = _repository_call(
        lambda: repository.get_assistant_artifact(str(payload.artifact_id))
    )
    assistant_request_id = str(uuid4())
    definition_id = str(uuid4())
    prompt = get_prompt("report.assistant")
    instruction_hash = hashlib.sha256(payload.instruction.encode("utf-8")).hexdigest()
    _repository_call(
        lambda: repository.start_assistant_request(
            assistant_request_id,
            str(payload.artifact_id),
            instruction_hash,
            prompt.prompt_id,
            prompt.version,
            str(prompt.metadata()["hash"]),
        )
    )
    model_payload = {
        "instruction": payload.instruction,
        "artifact": {
            "artifact_id": str(artifact["artifact_id"]),
            "query_id": artifact["trino_query_id"],
            "title": artifact["title"],
            "narrative": artifact["narrative_markdown"],
            "evidence": artifact["evidence_json"],
            "chart_spec": artifact["chart_spec_json"],
            "checksum": artifact["artifact_checksum"],
        },
    }
    try:
        proposal, trace = generate_report_draft(model_payload)
        draft = ReportDefinitionVersion(
            definition_id,
            1,
            DefinitionStatus.DRAFT,
            proposal["title"],
            (
                ReportBlock(
                    str(uuid4()), proposal["executive_summary"][:120] or "요약",
                    None, 12, None, BlockType.TEXT, 0, 0, 12, 2,
                    proposal["executive_summary"],
                ),
                ReportBlock(
                    str(uuid4()), proposal["table_title"],
                    str(artifact["artifact_id"]), 12, artifact["trino_query_id"],
                    BlockType.TABLE, 0, 2, 12, 4,
                ),
                ReportBlock(
                    str(uuid4()), proposal["chart_title"],
                    str(artifact["artifact_id"]), 12, artifact["trino_query_id"],
                    BlockType.CHART, 0, 6, 12, 4,
                ),
            ),
        )
        repository.add_draft(draft)
        output_hash = hashlib.sha256(
            json.dumps(proposal, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        repository.complete_assistant_request(
            assistant_request_id,
            definition_id,
            1,
            str(trace["model_version"]),
            output_hash,
        )
    except ReportAssistantModelError as error:
        repository.fail_assistant_request(assistant_request_id, "MODEL_FAILED")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "REPORT_ASSISTANT_MODEL_FAILED",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    except (ValueError, KeyError) as error:
        repository.fail_assistant_request(assistant_request_id, "DRAFT_INVALID")
        raise HTTPException(
            status_code=422,
            detail={
                "code": "REPORT_ASSISTANT_DRAFT_INVALID",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    except Exception as error:
        repository.fail_assistant_request(assistant_request_id, "INTERNAL_FAILED")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "REPORT_ASSISTANT_INTERNAL_FAILED",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    return {
        "assistant_request_id": assistant_request_id,
        "status": "success",
        "definition": router._response(draft),
        "trace": trace,
    }


def create_run_internal(
    payload: dict[str, Any],
    context: RequestContext,
) -> dict[str, Any]:
    """Trusted worker adapter hook; intentionally not registered as HTTP."""
    return _call(lambda: _router(context).create_run(payload))
