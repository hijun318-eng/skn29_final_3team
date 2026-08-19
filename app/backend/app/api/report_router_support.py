"""보고서 역할 dependency, repository/service 조립, artifact·HTML·PDF 응답 보안 header를 제공한다."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from typing import Annotated, Any, Awaitable, Callable
from uuid import uuid4

from fastapi import Depends, HTTPException, Response
from fastapi.responses import HTMLResponse

from app.context import analysis_context
from app.contracts import RequestContext, Role
from app.report_contracts import (
    CreateReportAssistantDraftRequest,
    CreateReportFromArtifactRequest,
)


RepositoryCall = Callable[[Callable[[], Any]], Awaitable[Any]]


def report_draft_context(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> RequestContext:
    """호텔 분석가와 보고서 관리자만 draft 작업에 사용할 Context를 통과시킨다."""
    if context.role not in {Role.HOTEL_ANALYST, Role.REPORT_ADMIN}:
        raise HTTPException(status_code=403, detail="Report 초안 권한이 없습니다.")
    return context


def report_admin_context(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> RequestContext:
    """승인·실행 관리 작업을 ``REPORT_ADMIN`` 주체로만 제한한다."""
    if context.role is not Role.REPORT_ADMIN:
        raise HTTPException(status_code=403, detail="Report 실행 관리 권한이 없습니다.")
    return context


def build_report_router(context: RequestContext):
    """요청 사용자와 역할 범위가 적용된 PostgreSQL repository로 보고서 router를 조립한다.

    ``REPORT_ADMIN``에만 전체 관리 범위를 부여하며 runtime DB URL이 없으면 메모리 대체재를
    만들지 않고 503으로 fail closed 한다.
    """
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


def build_execution_service(repository):
    """보고서 repository와 분석 replay controller·동시 실행 gate를 실행 service에 주입한다.

    replay도 동일 runtime PostgreSQL을 사용하며 DB URL 부재는 503으로 거부한다. queue 대기
    시간은 환경 계약에서 읽고 임의 기본 분석 결과를 생성하지 않는다.
    """
    from app.api.router import _controller, execution_gate
    from app.services.report.execution import (
        AnalysisDefinitionReplay,
        ReportExecutionService,
    )

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="Report repository is unavailable.")
    replay = AnalysisDefinitionReplay(
        database_url,
        _controller(),
        execution_gate,
        queue_wait_seconds=float(os.getenv("ANALYSIS_QUEUE_WAIT_SECONDS", "0")),
    )
    return ReportExecutionService(repository, replay)


def _artifact_visible_views(artifact: Mapping[str, Any]) -> list[str]:
    views: list[str] = []
    if str(artifact.get("narrative_markdown") or "").strip():
        views.append("summary")
    evidence = artifact.get("evidence_json")
    metrics = evidence.get("metric_values") if isinstance(evidence, Mapping) else None
    if isinstance(metrics, (list, tuple)) and metrics:
        views.append("kpi")
    snapshot = artifact.get("data_snapshot_json")
    rows = snapshot.get("rows") if isinstance(snapshot, Mapping) else None
    has_rows = isinstance(rows, (list, tuple)) and bool(rows)
    if artifact.get("chart_spec_json") and has_rows:
        views.append("chart")
    if has_rows:
        views.append("table")
    return views


async def create_artifact_draft(
    router: Any,
    payload: CreateReportFromArtifactRequest,
    repository_call: RepositoryCall,
) -> dict[str, Any]:
    """소유권이 검증된 분석 artifact를 참조하는 landscape 보고서 초안을 저장한다.

    실제 artifact 내용으로 노출 가능한 summary·KPI·chart·table view만 선언하고 artifact 및
    Trino query ID를 block lineage에 보존한다. 조회·저장 실패는 ``repository_call``의 HTTP
    오류 계약을 따르며 성공 시 version 1 definition 응답을 반환한다.
    """
    from src.report.domain import BlockType, DefinitionStatus, ReportBlock, ReportDefinitionVersion

    artifact = await repository_call(
        lambda: router.repository.get_transfer_artifact(str(payload.artifact_id))
    )
    artifact_id = str(artifact["artifact_id"])
    query_id = str(artifact["trino_query_id"])
    report_title = payload.title.strip()
    content = json.dumps({
        "schemaVersion": "ANSWER-ARTIFACT-BLOCK-v1",
        "presentationMode": "standard",
        "sizeMode": "auto",
        "visibleViews": _artifact_visible_views(artifact),
    }, ensure_ascii=False, separators=(",", ":"))
    blocks = (ReportBlock(
        str(uuid4()), report_title, artifact_id, 12, query_id,
        BlockType.ARTIFACT, 0, 0, 12, 12, content,
    ),)
    draft = ReportDefinitionVersion(
        str(uuid4()), 1, DefinitionStatus.DRAFT, report_title, blocks,
        orientation="landscape", currency_display_unit="auto",
    )
    await repository_call(lambda: router.repository.add_draft(draft))
    return router._response(draft)


def report_artifact_response(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """영속된 분석 artifact를 보고서 전송 계약으로 투영하고 lineage checksum을 보존한다."""
    from src.report.domain import REPORT_CONTRACT_VERSION

    return {
        "contract_version": REPORT_CONTRACT_VERSION,
        "artifact_id": artifact["artifact_id"],
        "query_id": artifact["trino_query_id"],
        "title": artifact["title"],
        "summary": artifact["narrative_markdown"],
        "metrics": (artifact["evidence_json"] or {}).get("metric_values", []),
        "table": artifact["data_snapshot_json"],
        "chart": artifact["chart_spec_json"] or None,
        "evidence": artifact["evidence_json"],
        "artifact_checksum": artifact["artifact_checksum"],
    }


async def approve_report_version(
    router: Any,
    definition_id: str,
    version: int,
    approved_at: Any,
    orientation: str | None,
) -> dict[str, Any]:
    """지정 draft를 저장 source 기반 HTML·PDF/A 문서로 렌더한 뒤 승인 응답으로 변환한다.

    renderer 실패는 draft를 승인하지 않은 채 503, 미존재는 404, orientation·상태 충돌은
    409로 매핑한다. 성공할 때만 repository의 문서 포함 승인 transaction이 완료된다.
    """
    from app.services.report.document import (
        ReportDocumentRenderError,
        approve_report_document,
    )

    try:
        approved = await approve_report_document(
            router.repository,
            definition_id,
            version,
            approved_at,
            orientation,
        )
        return router._response(approved)
    except ReportDocumentRenderError as error:
        raise HTTPException(
            status_code=503,
            detail="Report PDF renderer is unavailable; the draft was not approved.",
        ) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _document_response(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "definition_id": document["definition_id"],
        "definition_version": document["definition_version"],
        "orientation": document["orientation"],
        "currency_display_unit": document["currency_display_unit"],
        "renderer_version": document["renderer_version"],
        "source_checksum": document["source_checksum"],
        "html_checksum": document["html_checksum"],
        "pdf_checksum": document["pdf_checksum"],
        "artifact_versions": document["artifact_versions"],
        "confirmed_at": document["confirmed_at"],
    }


def final_html_response(document: Mapping[str, Any]) -> HTMLResponse:
    """승인 시점 HTML snapshot을 checksum ETag와 제한적 CSP를 포함해 반환한다.

    문서는 checksum으로 불변 식별되므로 private immutable cache를 허용하되 외부 script와
    resource 로딩은 CSP로 차단한다.
    """
    return HTMLResponse(
        content=document["html_snapshot"],
        headers={
            "ETag": f'"{document["html_checksum"]}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


def final_pdf_response(
    document: Mapping[str, Any],
    definition_id: str,
    version: int,
) -> Response:
    """승인된 PDF bytes를 버전 파일명과 checksum ETag가 있는 inline 응답으로 전달한다."""
    return Response(
        content=document["pdf_bytes"],
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="report-{definition_id}-v{version}.pdf"',
            "ETag": f'"{document["pdf_checksum"]}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def create_assistant_report_draft(
    router: Any,
    payload: CreateReportAssistantDraftRequest,
    repository_call: RepositoryCall,
) -> dict[str, Any]:
    """승인 artifact와 사용자 지시를 model에 전달해 근거 연결된 보고서 초안을 저장한다.

    호출 전 prompt·지시 hash로 assistant request를 시작하고 성공 시 definition·model trace·
    output hash를 기록한다. model transport, 제안 계약, 내부 저장 실패를 서로 다른 실패 code와
    HTTP 상태로 영속화하며 artifact 값 외의 분석 결과를 보정하거나 생성하지 않는다.
    """
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

    repository = router.repository
    artifact = await repository_call(
        lambda: repository.get_assistant_artifact(str(payload.artifact_id))
    )
    assistant_request_id = str(uuid4())
    definition_id = str(uuid4())
    prompt = get_prompt("report.assistant")
    instruction_hash = hashlib.sha256(payload.instruction.encode("utf-8")).hexdigest()
    await repository_call(
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
        proposal, trace = await generate_report_draft(model_payload)
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
        await repository.add_draft(draft)
        output_hash = hashlib.sha256(
            json.dumps(proposal, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        await repository.complete_assistant_request(
            assistant_request_id,
            definition_id,
            1,
            str(trace["model_version"]),
            output_hash,
        )
    except ReportAssistantModelError as error:
        await repository.fail_assistant_request(assistant_request_id, "MODEL_FAILED")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "REPORT_ASSISTANT_MODEL_FAILED",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    except (ValueError, KeyError) as error:
        await repository.fail_assistant_request(assistant_request_id, "DRAFT_INVALID")
        raise HTTPException(
            status_code=422,
            detail={
                "code": "REPORT_ASSISTANT_DRAFT_INVALID",
                "assistant_request_id": assistant_request_id,
            },
        ) from error
    except Exception as error:
        await repository.fail_assistant_request(assistant_request_id, "INTERNAL_FAILED")
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
