from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from app.contracts import (
    CONTRACT_VERSION,
    AnalysisData,
    AnalysisResponse,
    AnalysisResult,
    AnalysisStatus,
    ChartSpec,
    ErrorBody,
    ErrorCode,
    Evidence,
    GateRequirements,
    MaskingEvidence,
    PeriodEvidence,
    ResponseMeta,
    RouteType,
    SamplingEvidence,
    SourceReference,
    TableResult,
)


ANALYSIS_REQUEST_EXAMPLES = {
    "general": {
        "summary": "일반 분석 질문",
        "value": {"question": "이번 달 객실 운영 상태를 요약해줘"},
    },
    "template": {
        "summary": "승인 Template 요청",
        "value": {
            "question": "주간 객실 운영 현황",
            "template_id": "weekly-room-operations",
            "parameters": {"week_start": "2026-07-27"},
        },
    },
}

STATE_MAPPING = {
    "contract_version": CONTRACT_VERSION,
    "controller_to_api_ui": {
        "RECEIVED": {"api": "queued", "ui": "LOADING"},
        "ROUTED": {"api": "running", "ui": "LOADING"},
        "SUCCEEDED": {"api": "success", "ui": "READY"},
        "BLOCKED": {"api": "blocked", "ui": "ERROR"},
        "PARTIAL": {"api": "partial", "ui": "PARTIAL"},
        "FAILED": {"api": "failed", "ui": "ERROR"},
        "CANCELLED": {"api": "cancelled", "ui": "CANCELLED"},
    },
    "outcome_overrides": {
        "EMPTY": {"api": "success", "ui": "EMPTY"},
        "CACHED": {"api": "success", "ui": "READY"},
        "CONTEXT_INCOMPLETE": {"api": "blocked", "ui": "EMPTY"},
        "ACCESS_DENIED": {"api": "blocked", "ui": "FORBIDDEN"},
        "RESULT_EVIDENCE_MISSING": {
            "api": "failed",
            "ui": "INSUFFICIENT_EVIDENCE",
        },
        "RATE_LIMITED": {"api": "queued", "ui": "DELAYED"},
    },
}


def _meta(trace_id: str) -> ResponseMeta:
    return ResponseMeta(
        request_id=UUID("00000000-0000-0000-0000-000000000100"),
        trace_id=trace_id,
        as_of=date(2026, 7, 30),
        contract_version=CONTRACT_VERSION,
        timestamp=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )


def _source() -> SourceReference:
    return SourceReference(
        urn="urn:answervice:dataset:pms.public.reservations",
        fqn="pms.public.reservations",
        name="PMS reservations",
        schema_version="1.0.0",
        seed_version="20260729",
    )


def _result(*, rows: tuple[dict[str, object], ...], cached: bool = False) -> AnalysisResult:
    return AnalysisResult(
        summary="검증된 합성 데이터 분석 결과입니다.",
        table=TableResult(
            columns=("business_date", "occupied_rooms"),
            rows=rows,
        ),
        chart=ChartSpec(
            chart_type="line",
            x_field="business_date",
            y_fields=("occupied_rooms",),
        ),
        evidence=Evidence(
            as_of=date(2026, 7, 30),
            period=PeriodEvidence(
                start=date(2026, 7, 1),
                end_exclusive=date(2026, 8, 1),
            ),
            filters={"hotel": "synthetic"},
            sources=(_source(),),
            context_release="context-v1",
            policy_version="policy-v1",
            sampling=SamplingEvidence(
                applied=False,
                returned_rows=len(rows),
                total_rows=len(rows),
            ),
            masking=MaskingEvidence(applied=True, fields=("guest_id",)),
            cached=cached,
        ),
    )


def _response(
    name: str,
    status: AnalysisStatus,
    transitions: tuple[AnalysisStatus, ...],
    *,
    result: AnalysisResult | None = None,
    error: ErrorBody | None = None,
) -> AnalysisResponse:
    return AnalysisResponse(
        data=AnalysisData(
            status=status,
            transitions=transitions,
            route=RouteType.GENERAL,
            gates=GateRequirements(g1_required=True, g2_required=True),
            result=result,
        ),
        meta=_meta(f"fixture-{name}"),
        error=error,
    )


def contract_fixtures() -> dict[str, AnalysisResponse]:
    routed = (AnalysisStatus.RECEIVED, AnalysisStatus.ROUTED)
    return {
        "success": _response(
            "success",
            AnalysisStatus.SUCCEEDED,
            (*routed, AnalysisStatus.SUCCEEDED),
            result=_result(
                rows=(
                    {
                        "business_date": "2026-07-29",
                        "occupied_rooms": 120,
                    },
                )
            ),
        ),
        "empty": _response(
            "empty",
            AnalysisStatus.SUCCEEDED,
            (*routed, AnalysisStatus.SUCCEEDED),
            result=_result(rows=()),
        ),
        "g1_clarification": _response(
            "g1-clarification",
            AnalysisStatus.BLOCKED,
            (AnalysisStatus.RECEIVED, AnalysisStatus.BLOCKED),
            error=ErrorBody(
                code=ErrorCode.CONTEXT_INCOMPLETE,
                message="분석 기간을 입력해 주세요.",
            ),
        ),
        "g2_blocked": _response(
            "g2-blocked",
            AnalysisStatus.BLOCKED,
            (*routed, AnalysisStatus.BLOCKED),
            error=ErrorBody(
                code=ErrorCode.SQL_POLICY_BLOCKED,
                message="허용된 조회 범위에서 질문을 수정해 주세요.",
            ),
        ),
        "g3_failed": _response(
            "g3-failed",
            AnalysisStatus.FAILED,
            (*routed, AnalysisStatus.FAILED),
            error=ErrorBody(
                code=ErrorCode.RESULT_EVIDENCE_MISSING,
                message="결과 근거가 충분하지 않아 설명을 생성하지 않았습니다.",
            ),
        ),
        "timeout": _response(
            "timeout",
            AnalysisStatus.FAILED,
            (*routed, AnalysisStatus.FAILED),
            error=ErrorBody(
                code=ErrorCode.QUERY_SOURCE_FAILED,
                message="조회 시간이 초과되었습니다.",
                retryable=True,
            ),
        ),
        "partial": _response(
            "partial",
            AnalysisStatus.PARTIAL,
            (*routed, AnalysisStatus.PARTIAL),
            result=_result(rows=()),
            error=ErrorBody(
                code=ErrorCode.PARTIAL_FAILURE,
                message="일부 데이터 소스를 조회하지 못했습니다.",
                retryable=True,
            ),
        ),
        "cancelled": _response(
            "cancelled",
            AnalysisStatus.CANCELLED,
            (*routed, AnalysisStatus.CANCELLED),
            error=ErrorBody(
                code=ErrorCode.QUERY_SOURCE_FAILED,
                message="요청이 취소되었습니다.",
            ),
        ),
        "cached": _response(
            "cached",
            AnalysisStatus.SUCCEEDED,
            (*routed, AnalysisStatus.SUCCEEDED),
            result=_result(rows=(), cached=True),
        ),
    }


ANALYSIS_RESPONSE_EXAMPLES = {
    name: {
        "summary": name.replace("_", " "),
        "value": response.model_dump(mode="json"),
    }
    for name, response in contract_fixtures().items()
}
