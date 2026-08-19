"""OpenAPI 문서 생성에만 쓰는 결정론적 계약 예시를 제공한다.

이 모듈의 값은 endpoint 실행, 분석 결과 생성, fallback에 참여하지 않는다. 구체 값은
배포된 OpenAPI snapshot의 직렬화 호환성을 위한 문서 데이터이며 운영 데이터 원본이 아니다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from app.contracts import (
    CONTRACT_VERSION,
    AnalysisData,
    AnalysisResponse,
    AnalysisResult,
    AnalysisStatus,
    ArtifactReference,
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
from app.trace_examples import example_trace


ANALYSIS_REQUEST_EXAMPLES = {
    "general": {
        "summary": "일반 분석 질문",
        "value": {"question": "승인된 기간의 선택 지표를 분석해 주세요"},
    },
    "template": {
        "summary": "승인 Template 요청",
        "value": {
            "question": "승인된 Template을 실행해 주세요",
            "template_id": "approved-analysis-template",
            "parameters": {
                "period_start": "2041-03-01",
                "period_end_exclusive": "2041-04-01",
            },
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
        "CLARIFICATION_REQUIRED": {"api": "blocked", "ui": "EMPTY"},
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
        as_of=date(2041, 4, 2),
        contract_version=CONTRACT_VERSION,
        timestamp=datetime(2041, 4, 2, tzinfo=timezone.utc),
    )


def _source() -> SourceReference:
    return SourceReference(
        urn="urn:example:dataset:catalog-alpha:fact-observations",
        fqn="catalog_alpha.schema_beta.fact_observations",
        name="Governed observations",
        schema_version="1.0.0",
        seed_version="example-release-v1",
        synthetic=True,
    )


def _result(
    name: str,
    *,
    rows: tuple[dict[str, object], ...],
    cached: bool = False,
) -> AnalysisResult:
    artifact_id = UUID(int=sum(map(ord, name)))
    return AnalysisResult(
        summary="문서 예시 계약에 맞는 분석 결과입니다.",
        table=TableResult(
            columns=("bucket_start", "measure_value"),
            rows=rows,
        ),
        chart=ChartSpec(
            chart_type="line",
            x_field="bucket_start",
            y_fields=("measure_value",),
        ),
        evidence=Evidence(
            as_of=date(2041, 4, 2),
            period=PeriodEvidence(
                start=date(2041, 3, 1),
                end_exclusive=date(2041, 4, 1),
            ),
            filters={"scope_code": "example"},
            sources=(_source(),),
            query_id=f"fixture-query-{name}",
            artifact_id=artifact_id,
            context_release="context-v1",
            policy_version="policy-v1",
            sampling=SamplingEvidence(
                applied=False,
                returned_rows=len(rows),
                total_rows=len(rows),
            ),
            masking=MaskingEvidence(applied=True, fields=("subject_identifier",)),
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
    artifact = None
    if result and result.evidence.artifact_id and result.evidence.query_id:
        artifact = ArtifactReference(
            artifact_id=result.evidence.artifact_id,
            query_id=result.evidence.query_id,
            context_hash=f"fixture-context-{name}",
        )
    return AnalysisResponse(
        data=AnalysisData(
            status=status,
            transitions=transitions,
            route=RouteType.GENERAL,
            gates=GateRequirements(g1_required=True, g2_required=True),
            result=result,
            trace=example_trace(name),
            repair_count=1 if name == "repaired" else 0,
            artifact=artifact,
        ),
        meta=_meta(f"fixture-{name}"),
        error=error,
    )


def contract_examples() -> dict[str, AnalysisResponse]:
    """OpenAPI 상태별 응답 예시를 새 객체로 구성해 반환한다."""

    routed = (AnalysisStatus.RECEIVED, AnalysisStatus.ROUTED)
    return {
        "success": _response(
            "success",
            AnalysisStatus.SUCCEEDED,
            (*routed, AnalysisStatus.SUCCEEDED),
            result=_result(
                "success",
                rows=(
                    {
                        "bucket_start": "2041-03-01",
                        "measure_value": 120,
                    },
                )
            ),
        ),
        "empty": _response(
            "empty",
            AnalysisStatus.SUCCEEDED,
            (*routed, AnalysisStatus.SUCCEEDED),
            result=_result("empty", rows=()),
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
                code=ErrorCode.QUERY_TIMEOUT,
                message="조회 시간이 초과되었습니다.",
                retryable=True,
            ),
        ),
        "partial": _response(
            "partial",
            AnalysisStatus.PARTIAL,
            (*routed, AnalysisStatus.PARTIAL),
            result=_result("partial", rows=()),
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
                code=ErrorCode.REQUEST_CANCELLED,
                message="요청이 취소되었습니다.",
            ),
        ),
        "cached": _response(
            "cached",
            AnalysisStatus.SUCCEEDED,
            (*routed, AnalysisStatus.SUCCEEDED),
            result=_result("cached", rows=(), cached=True),
        ),
        "repaired": _response(
            "repaired",
            AnalysisStatus.SUCCEEDED,
            (*routed, AnalysisStatus.SUCCEEDED),
            result=_result(
                "repaired",
                rows=(
                    {
                        "bucket_start": "2041-03-01",
                        "measure_value": 120,
                    },
                ),
            ),
        ),
    }


def contract_fixtures() -> dict[str, AnalysisResponse]:
    """기존 OpenAPI export 호출자를 위한 문서 예시 호환 이름을 제공한다."""

    return contract_examples()


ANALYSIS_RESPONSE_EXAMPLES = {
    name: {
        "summary": name.replace("_", " "),
        "value": response.model_dump(mode="json"),
    }
    for name, response in contract_examples().items()
}
