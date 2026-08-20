"""분석 파이프라인의 모델 호출, 거버넌스 게이트(G1~G3) 이력 및 감사 증거 조립 모듈.

[핵심 목적]
요청 처리 과정에서 생성된 `TraceStep`과 `ContextPackage`, 실행 쿼리 결과로부터:
1. G1(라우팅/컨텍스트), G2(SQL 가드), G3(결과 검증) 게이트 판정 결과 및 수리(Repair) 이력 집계
2. LLM 모델 호출 버전, 프롬프트 ID/버전 추적 증거(`ModelInvocationEvidence`) 생성
3. 지표 값의 축약(Reduction: sum, average, min, max 등) 계산
을 수행하여 완전한 감사 추적성(Audit Traceability)을 보장합니다.
"""

from __future__ import annotations

from decimal import Decimal

from app.contracts import (
    GateEvidence,
    GateHistoryEvidence,
    ModelInvocationEvidence,
    PipelineStage,
    TraceStep,
)
from app.services.context.builder import ContextMetricTerm, ContextPackage


def _evidence_filters(
    filters: object,
    package: ContextPackage,
) -> dict[str, object]:
    """사용자 필터 파라미터를 표시용 FQN 컬럼명 매핑 딕셔너리로 변환합니다."""
    if not isinstance(filters, dict):
        return {}
    contracts = getattr(package, "runtime_contracts", None) or {}
    approved = {
        item["parameter"]: (
            f"{item['field']['asset_fqn']}.{item['field']['column']}"
        )
        for metric in contracts.get("metric_rules", ())
        for item in metric.get("required_filters", ())
    }
    displayed = {}
    for name, value in filters.items():
        field = approved.get(str(name), str(name))
        displayed[field] = value
    return displayed


def _metric_term(package: ContextPackage, metric_id: str) -> ContextMetricTerm:
    """ContextPackage에서 지정된 metric_id에 해당하는 Glossary Term을 조회합니다."""
    try:
        return next(term for term in package.metric_terms if term.id == metric_id)
    except StopIteration as error:
        raise ValueError(
            f"승인된 컨텍스트에 DataHub Metric Glossary Term이 누락되었습니다: {metric_id}"
        ) from error


def _model_invocations(trace: list[TraceStep]) -> tuple[ModelInvocationEvidence, ...]:
    """트레이스 단계들로부터 LLM 모델 호출 증거(노드, 모델 버전, 프롬프트 ID/버전)를 추출합니다."""
    invocations: list[ModelInvocationEvidence] = []
    for step in trace:
        if (
            step.stage not in {PipelineStage.MODEL, PipelineStage.REPAIR}
            or not step.detail
        ):
            continue
        fields = {}
        for item in step.detail.split(";"):
            key, separator, value = item.partition("=")
            if separator:
                fields[key] = value
        prompt_id, separator, prompt_version = fields.get("prompt", "").rpartition("@")
        node = fields.get("node")
        model_version = fields.get("model")
        if (
            not separator
            or not node
            or not model_version
            or not prompt_id
            or not prompt_version
        ):
            continue
        if "unknown" in {node, model_version, prompt_id, prompt_version}:
            continue
        invocations.append(
            ModelInvocationEvidence(
                node=node,
                model_version=model_version,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
            )
        )
    return tuple(invocations)


def _gate_evidence(trace: list[TraceStep]) -> GateEvidence:
    """성공한 파이프라인 트레이스로부터 최종 G1, G2, G3 게이트 통과 결과를 추출합니다."""
    outcomes = {
        step.stage: step.outcome
        for step in trace
        if step.stage in {PipelineStage.G1, PipelineStage.G2, PipelineStage.G3}
    }
    missing = [
        stage.value
        for stage in (PipelineStage.G1, PipelineStage.G2, PipelineStage.G3)
        if stage not in outcomes
    ]
    if missing:
        raise ValueError(
            f"성공한 분석 응답에 필수 게이트 증거가 누락되었습니다: {', '.join(missing)}"
        )
    return GateEvidence(
        g1=outcomes[PipelineStage.G1],
        g2=outcomes[PipelineStage.G2],
        g3=outcomes[PipelineStage.G3],
    )


def _gate_history(trace: list[TraceStep]) -> GateHistoryEvidence:
    """수리(Repair) 시도를 포함한 전체 게이트 실행 히스토리를 반환합니다."""
    return GateHistoryEvidence(
        g1=tuple(
            step.outcome for step in trace if step.stage is PipelineStage.G1
        ),
        g2=tuple(
            step.outcome for step in trace if step.stage is PipelineStage.G2
        ),
        g3=tuple(
            step.outcome for step in trace if step.stage is PipelineStage.G3
        ),
    )


def _reduce_metric_values(reduction: str, values: list[object]) -> Decimal | None:
    """지표의 축약(Reduction) 규칙에 따라 행 데이터 값들을 단일 스칼라 값으로 집계합니다."""
    if not values:
        return None
    numbers = [Decimal(str(v)) for v in values if v is not None]
    if not numbers:
        return None
    if reduction == "sum":
        return sum(numbers)
    if reduction == "min":
        return min(numbers)
    if reduction == "max":
        return max(numbers)
    if reduction == "average":
        return sum(numbers) / Decimal(len(numbers))
    if reduction == "scalar":
        return numbers[0] if len(numbers) == 1 else None
    return numbers[0] if len(numbers) == 1 else None
