"""분석 progress·취소·정의·run·artifact 조회 endpoint를 인증 소유자 저장소에 연결한다."""

from __future__ import annotations

from importlib import import_module
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.analysis_contracts import (
    AnalysisArtifactLifecycleResponse,
    AnalysisDefinitionListResponse,
    AnalysisDefinitionResponse,
    AnalysisRunArtifactResponse,
    AnalysisRunListResponse,
    AnalysisRunResponse,
    CreateAnalysisDefinitionRequest,
)
from app.context import analysis_context, session_context
from app.contracts import (
    AnalysisProgressPollResponse,
    AnalysisProgressResponse,
    RequestContext,
    response_meta,
)
from app.services.analysis import AmbiguousTraceError


analysis_support_router = APIRouter()


def _router_facade():
    """Resolve dependencies through app.api.router to preserve its patch boundary."""
    return import_module("app.api.router")


def _analysis_repository(context: RequestContext):
    return _router_facade()._analysis_repository(context)


async def _repository_call(action):
    return await _router_facade()._repository_call(action)


def _analysis_progress():
    return _router_facade().analysis_progress


async def _active_product_release_receipt() -> tuple[str, str]:
    return await _router_facade()._active_product_release_receipt()


@analysis_support_router.get(
    "/analysis/progress/{trace_id}",
    response_model=AnalysisProgressResponse,
    operation_id="getAnalysisProgress",
)
def get_analysis_progress(
    trace_id: str,
    context: Annotated[RequestContext, Depends(session_context)],
) -> AnalysisProgressResponse:
    """인증 사용자의 유일한 trace 실행 snapshot을 API metadata와 함께 반환한다.

    trace 재사용으로 실행이 모호하면 request ID 사용을 요구하는 409를, 소유 실행이 없거나
    만료됐으면 자원 존재를 노출하지 않는 404를 반환한다.
    """
    try:
        data = _analysis_progress().get(trace_id, context.user_id)
    except AmbiguousTraceError as error:
        raise HTTPException(
            status_code=409,
            detail="동일한 추적 ID에 여러 분석 요청이 있습니다. 요청 ID로 조회해 주세요.",
        ) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail="진행 중인 분석을 찾을 수 없습니다.") from error
    return AnalysisProgressResponse(data=data, meta=response_meta(context))


@analysis_support_router.get(
    "/analysis/progress/{trace_id}/poll",
    response_model=AnalysisProgressPollResponse,
    operation_id="pollAnalysisProgress",
)
def poll_analysis_progress(
    trace_id: str,
    context: Annotated[RequestContext, Depends(session_context)],
) -> AnalysisProgressPollResponse:
    """대화 명령의 라우팅과 분석 등록 사이에는 빈 진행 상태를 정상 응답한다.

    소유 분석이 시작되면 strict progress와 같은 snapshot을 반환한다. 미등록 trace와
    다른 사용자 소유 trace는 모두 ``data: null``로 처리해 자원 존재를 노출하지 않는다.
    동일 소유자의 trace가 모호한 경우에는 request ID 조회를 요구하는 409를 유지한다.
    """
    try:
        data = _analysis_progress().get(trace_id, context.user_id)
    except AmbiguousTraceError as error:
        raise HTTPException(
            status_code=409,
            detail="동일한 추적 ID에 여러 분석 요청이 있습니다. 요청 ID로 조회해 주세요.",
        ) from error
    except KeyError:
        data = None
    return AnalysisProgressPollResponse(data=data, meta=response_meta(context))


@analysis_support_router.post(
    "/analysis/progress/{trace_id}/cancel",
    response_model=AnalysisProgressResponse,
    operation_id="cancelAnalysisProgress",
)
def cancel_analysis_progress(
    trace_id: str,
    context: Annotated[RequestContext, Depends(session_context)],
) -> AnalysisProgressResponse:
    """인증 사용자의 유일한 trace 실행에 협력적 취소 event를 설정해 snapshot을 반환한다.

    모호한 trace는 409로 request ID 취소를 요구하고, 미존재는 404, 이미 종단 상태인 실행은
    새 취소가 불가능하므로 409로 변환한다.
    """
    try:
        data = _analysis_progress().cancel(trace_id, context.user_id)
    except AmbiguousTraceError as error:
        raise HTTPException(
            status_code=409,
            detail="동일한 추적 ID에 여러 분석 요청이 있습니다. 요청 ID로 취소해 주세요.",
        ) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail="진행 중인 분석을 찾을 수 없습니다.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail="이미 종료된 분석입니다.") from error
    return AnalysisProgressResponse(data=data, meta=response_meta(context))


@analysis_support_router.get(
    "/analysis/requests/{request_id}/progress",
    response_model=AnalysisProgressResponse,
    operation_id="getAnalysisProgressByRequest",
)
def get_analysis_progress_by_request(
    request_id: UUID,
    context: Annotated[RequestContext, Depends(session_context)],
) -> AnalysisProgressResponse:
    """request ID가 인증 사용자에게 속할 때만 진행 snapshot과 응답 metadata를 반환한다.

    레지스트리에 없거나 다른 사용자 소유인 요청은 모두 404로 처리한다.
    """
    try:
        data = _analysis_progress().get_request(request_id, context.user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="진행 중인 분석을 찾을 수 없습니다.") from error
    return AnalysisProgressResponse(data=data, meta=response_meta(context))


@analysis_support_router.post(
    "/analysis/requests/{request_id}/cancel",
    response_model=AnalysisProgressResponse,
    operation_id="cancelAnalysisProgressByRequest",
)
def cancel_analysis_progress_by_request(
    request_id: UUID,
    context: Annotated[RequestContext, Depends(session_context)],
) -> AnalysisProgressResponse:
    """인증 사용자 소유 request에 취소 event를 설정하고 반영된 진행 snapshot을 반환한다.

    미존재·타 사용자 요청은 404로 감추고 이미 종단 상태인 요청은 409로 거부한다.
    """
    try:
        data = _analysis_progress().cancel_request(request_id, context.user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="진행 중인 분석을 찾을 수 없습니다.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail="이미 종료된 분석입니다.") from error
    return AnalysisProgressResponse(data=data, meta=response_meta(context))


@analysis_support_router.post(
    "/analysis/definitions",
    operation_id="analysisCreateDefinition",
    response_model=AnalysisDefinitionResponse,
)
async def create_analysis_definition(
    payload: CreateAnalysisDefinitionRequest,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    """소유한 완료 run을 source로 지정 title의 재실행 가능한 분석 definition을 저장한다.

    source request의 존재·소유권·artifact 계약과 중복 여부는 repository transaction에서
    검증되며, 공통 repository 오류 매핑을 거친 definition 응답을 반환한다.
    """
    repository = _analysis_repository(context)
    return await _repository_call(
        lambda: repository.create_definition_from_run(payload.source_request_id, payload.title)
    )


@analysis_support_router.get(
    "/analysis/definitions",
    operation_id="analysisListDefinitions",
    response_model=AnalysisDefinitionListResponse,
)
async def list_analysis_definitions(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    """현재 분석 주체가 저장한 definition만 생성 시각 역순으로 반환한다."""
    repository = _analysis_repository(context)
    product_release_id, semantic_release_id = await _active_product_release_receipt()
    return {
        "items": await _repository_call(
            lambda: repository.list_definitions(
                product_release_id=product_release_id,
                semantic_release_id=semantic_release_id,
            )
        )
    }


@analysis_support_router.get(
    "/analysis/definitions/{definition_id}",
    operation_id="analysisGetDefinition",
    response_model=AnalysisDefinitionResponse,
)
async def get_analysis_definition(
    definition_id: UUID,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    """definition ID로 인증 주체가 조회할 수 있는 저장 분석과 재실행 계약을 반환한다.

    repository가 소유권 범위를 적용하며 미존재·비소유 결과는 공통 404 응답으로 닫힌다.
    """
    repository = _analysis_repository(context)
    return await _repository_call(lambda: repository.get_definition(definition_id))


@analysis_support_router.get(
    "/analysis/runs",
    operation_id="analysisListRuns",
    response_model=AnalysisRunListResponse,
)
async def list_analysis_runs(
    context: Annotated[RequestContext, Depends(analysis_context)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    approved_only: bool = False,
    archived: bool = False,
) -> dict[str, Any]:
    """현재 분석 주체의 active 또는 명시한 archived run을 시작 시각 역순으로 반환한다."""
    repository = _analysis_repository(context)
    return {
        "items": await _repository_call(
            lambda: repository.list_runs(
                limit=limit,
                approved_only=approved_only,
                archived=archived,
            )
        )
    }


@analysis_support_router.get(
    "/analysis/runs/{request_id}",
    operation_id="analysisGetRun",
    response_model=AnalysisRunResponse,
)
async def get_analysis_run(
    request_id: UUID,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    """request ID로 인증 주체 소유 run의 상태·query·lineage evidence를 반환한다.

    저장소가 사용자 범위를 강제하며 조회할 수 없는 run은 공통 404로 변환된다.
    """
    repository = _analysis_repository(context)
    return await _repository_call(lambda: repository.get_run(request_id))


@analysis_support_router.get(
    "/analysis/runs/{request_id}/artifact",
    operation_id="analysisGetRunArtifact",
    response_model=AnalysisRunArtifactResponse,
)
async def get_analysis_run_artifact(
    request_id: UUID,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    """인증 주체 소유 run의 승인 artifact snapshot과 checksum 근거를 반환한다.

    artifact가 없거나 request가 다른 사용자에게 속하면 repository 오류 매핑을 통해 404로
    닫아 분석 결과의 존재 여부를 노출하지 않는다.
    """
    repository = _analysis_repository(context)
    return await _repository_call(lambda: repository.get_run_artifact(request_id))


def _artifact_lifecycle_response(lifecycle) -> dict[str, Any]:
    """도메인 lifecycle을 UUID 외 정보가 없는 공개 응답으로 투영한다."""

    return {
        "artifact_id": lifecycle.artifact_id,
        "archived": lifecycle.archived,
        "archived_at": lifecycle.archived_at,
        "archived_by": lifecycle.archived_by,
    }


@analysis_support_router.post(
    "/analysis/artifacts/{artifact_id}/archive",
    operation_id="analysisArchiveArtifact",
    response_model=AnalysisArtifactLifecycleResponse,
)
async def archive_analysis_artifact(
    artifact_id: UUID,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    """소유한 승인 Artifact를 비파괴 보관하며 진행 중 Assistant 충돌은 409로 닫는다."""

    repository = _analysis_repository(context)
    lifecycle = await _repository_call(
        lambda: repository.archive_artifact(
            artifact_id,
            actor_role=context.role.value,
            trace_id=context.trace_id,
        )
    )
    return _artifact_lifecycle_response(lifecycle)


@analysis_support_router.post(
    "/analysis/artifacts/{artifact_id}/restore",
    operation_id="analysisRestoreArtifact",
    response_model=AnalysisArtifactLifecycleResponse,
)
async def restore_analysis_artifact(
    artifact_id: UUID,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    """소유한 보관 Artifact를 active 목록과 신규 보고서 결속에 다시 노출한다."""

    repository = _analysis_repository(context)
    lifecycle = await _repository_call(
        lambda: repository.restore_artifact(
            artifact_id,
            actor_role=context.role.value,
            trace_id=context.trace_id,
        )
    )
    return _artifact_lifecycle_response(lifecycle)
