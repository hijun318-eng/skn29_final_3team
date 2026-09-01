"""보고서 역할 dependency, repository/service 조립, artifact·HTML·PDF 응답 보안 header를 제공한다."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
import os
from typing import Annotated, Any, Awaitable, Callable
from uuid import uuid4

from fastapi import Depends, HTTPException, Response
from fastapi.responses import HTMLResponse

from app.authorization import has_capability, permission_snapshot_id
from app.context import analysis_context
from app.contracts import Capability, RequestContext
from app.report_contracts import CreateReportFromArtifactRequest


RepositoryCall = Callable[[Callable[[], Any]], Awaitable[Any]]


def report_draft_context(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> RequestContext:
    """호텔 분석가와 보고서 관리자만 draft 작업에 사용할 Context를 통과시킨다."""
    if not has_capability(context.role, Capability.DRAFT_REPORT):
        raise HTTPException(status_code=403, detail="Report 초안 권한이 없습니다.")
    return context


def report_admin_context(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> RequestContext:
    """승인·실행 관리 작업을 ``REPORT_ADMIN`` 주체로만 제한한다."""
    if not has_capability(context.role, Capability.MANAGE_REPORT):
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
            manage_all=has_capability(context.role, Capability.MANAGE_REPORT),
            product_release_id=context.product_release_id,
            permission_snapshot_id=(
                context.permission_snapshot_id
                or permission_snapshot_id(context.user_id, context.role)
            ),
            semantic_release_id=context.semantic_release_id,
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
    """실제 렌더링 가능한 원자 view만 고정된 사용자 순서로 반환한다."""

    views: list[str] = []
    if str(artifact.get("narrative_markdown") or "").strip():
        views.append("summary")
    evidence = artifact.get("evidence_json")
    metrics = evidence.get("metric_values") if isinstance(evidence, Mapping) else None
    if isinstance(metrics, (list, tuple)) and any(
        isinstance(metric, Mapping)
        and bool(str(metric.get("label") or "").strip())
        and _is_public_scalar(metric.get("value"))
        and metric.get("value") is not None
        for metric in metrics
    ):
        views.append("kpi")
    columns, has_scalar_row, _ = _artifact_snapshot_shape(artifact)
    chart_spec = artifact.get("chart_spec_json")
    chart_fields_match = False
    if isinstance(chart_spec, Mapping) and columns and has_scalar_row:
        x_field = chart_spec.get("x_field")
        y_fields = chart_spec.get("y_fields")
        chart_fields_match = (
            isinstance(x_field, str)
            and x_field in columns
            and isinstance(y_fields, (list, tuple))
            and bool(y_fields)
            and all(isinstance(field, str) and field in columns for field in y_fields)
        )
    if chart_fields_match:
        views.append("chart")
    if columns and has_scalar_row:
        views.append("table")
    return views


_TABLE_SNAPSHOT_MAX_COLUMNS = 16


def _is_public_scalar(value: object) -> bool:
    """외부 모델 경계에서 구조체·비정상 수치를 제외한 분석 scalar만 식별한다."""

    return (
        value is None
        or isinstance(value, (bool, int, str))
        or isinstance(value, float) and math.isfinite(value)
    )


def _artifact_snapshot_shape(
    artifact: Mapping[str, Any],
) -> tuple[tuple[str, ...], bool, int]:
    """원문 값을 복사하지 않고 실제 scalar column·row 존재와 전체 행 수만 확인한다."""

    snapshot = artifact.get("data_snapshot_json")
    raw_columns = snapshot.get("columns") if isinstance(snapshot, Mapping) else None
    raw_rows = snapshot.get("rows") if isinstance(snapshot, Mapping) else None
    source_rows = list(raw_rows) if isinstance(raw_rows, (list, tuple)) else []
    candidates: list[str] = []
    if isinstance(raw_columns, (list, tuple)):
        for column in raw_columns:
            name = column.get("name") if isinstance(column, Mapping) else column
            if isinstance(name, str) and name.strip() and name.strip() not in candidates:
                candidates.append(name.strip())
    if not candidates:
        for row in source_rows[:20]:
            if not isinstance(row, Mapping):
                continue
            for name in row:
                if isinstance(name, str) and name.strip() and name.strip() not in candidates:
                    candidates.append(name.strip())

    scalar_columns = tuple(
        name
        for name in candidates
        if any(
            isinstance(row, Mapping)
            and name in row
            and _is_public_scalar(row[name])
            for row in source_rows[:20]
        )
    )
    has_scalar_row = any(
        isinstance(row, Mapping)
        and any(name in row and _is_public_scalar(row[name]) for name in scalar_columns)
        for row in source_rows[:20]
    )
    return scalar_columns, has_scalar_row, len(source_rows)


def _artifact_table_snapshot(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """외부 모델에는 원문 column명·cell 값 없이 bounded 구조 메타데이터만 제공한다.

    Assistant는 view를 선택할 뿐 표 데이터를 다시 생성하지 않으며 실제 renderer는 승인된
    Artifact를 직접 읽는다. 따라서 schema 폭과 행 수만 익명화하고 raw rows는 fail-closed로
    전송하지 않는다.
    """

    source_columns, _, row_count = _artifact_snapshot_shape(artifact)
    visible_column_count = min(len(source_columns), _TABLE_SNAPSHOT_MAX_COLUMNS)
    return {
        "columns": [f"column_{index}" for index in range(1, visible_column_count + 1)],
        "rows": [],
        "row_count": row_count,
        "truncated": row_count > 0 or len(source_columns) > visible_column_count,
    }


async def create_artifact_draft(
    router: Any,
    payload: CreateReportFromArtifactRequest,
    repository_call: RepositoryCall,
) -> dict[str, Any]:
    """소유권이 검증된 분석 artifact를 참조하는 landscape 보고서 초안을 저장한다.

    실제 artifact 내용으로 노출 가능한 summary·KPI·chart·table을 원자 block으로 분리하고
    artifact 및 Trino query ID를 block lineage에 보존한다. 조회·저장 실패는
    ``repository_call``의 HTTP 오류 계약을 따르며 성공 시 version 1 definition을 반환한다.
    """
    from app.report_patch import artifact_view_default_height, artifact_view_title
    from src.report.domain import BlockType, DefinitionStatus, ReportBlock, ReportDefinitionVersion

    artifact = await repository_call(
        lambda: router.repository.get_transfer_artifact(str(payload.artifact_id))
    )
    artifact_id = str(artifact["artifact_id"])
    query_id = str(artifact["trino_query_id"])
    report_title = payload.title.strip()
    source_title = str(artifact.get("title") or "").strip()
    views = _artifact_visible_views(artifact)
    if not source_title or not views:
        raise ValueError("승인 Artifact에 보고서로 만들 수 있는 원자 view가 없습니다.")
    blocks: list[ReportBlock] = []
    view_widths = {"summary": 6, "kpi": 6, "chart": 12, "table": 12}
    row_x = row_y = row_height = 0
    for view in views:
        block_type = (
            BlockType.ARTIFACT if view in {"summary", "kpi"} else BlockType(view)
        )
        settings: dict[str, object] = {"sizeMode": "auto"}
        if view in {"summary", "kpi"}:
            settings.update({
                "schemaVersion": "ANSWER-ARTIFACT-BLOCK-v1",
                "presentationMode": "standard",
                "visibleViews": [view],
            })
        elif view == "chart":
            settings.update({"visibleViews": ["chart"], "showLegend": True})
        else:
            settings.update({
                "visibleViews": ["table"],
                "density": "comfortable",
                "showRowNumbers": False,
            })
        width = view_widths[view]
        height = artifact_view_default_height(view)
        if row_x and row_x + width > 12:
            row_y += row_height
            row_x = row_height = 0
        blocks.append(ReportBlock(
            str(uuid4()), artifact_view_title(source_title, view), artifact_id, width,
            query_id, block_type, row_x, row_y, width, height,
            json.dumps(
                settings, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        ))
        row_x += width
        row_height = max(row_height, height)
        if row_x == 12:
            row_y += row_height
            row_x = row_height = 0
    draft = ReportDefinitionVersion(
        str(uuid4()), 1, DefinitionStatus.DRAFT, report_title, tuple(blocks),
        orientation="landscape", currency_display_unit="auto",
    )
    await repository_call(lambda: router.repository.add_draft(draft))
    return router._response(draft)


def report_artifact_response(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """영속 artifact를 query ID·checksum 없는 보고서 공개 계약으로 투영한다."""
    from src.report.domain import REPORT_CONTRACT_VERSION

    evidence = dict(artifact["evidence_json"] or {})
    evidence.pop("query_id", None)
    return {
        "contract_version": REPORT_CONTRACT_VERSION,
        "artifact_id": artifact["artifact_id"],
        "title": artifact["title"],
        "summary": artifact["narrative_markdown"],
        "metrics": evidence.get("metric_values", []),
        "table": artifact["data_snapshot_json"],
        "chart": artifact["chart_spec_json"] or None,
        "evidence": evidence,
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
