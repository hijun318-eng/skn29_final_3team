"""검증된 context·query·trace에서 filter, metric 축약, model 호출과 G1~G3 이력을 추출해 응답의 감사 근거를 구성한다."""

from __future__ import annotations

from decimal import Decimal

from app.contracts import (
    GateEvidence,
    GateHistoryEvidence,
    ModelInvocationEvidence,
    PipelineStage,
    TraceStep,
)
from app.services.context_builder import ContextMetricTerm, ContextPackage


def _evidence_filters(
    filters: object,
    package: ContextPackage,
) -> dict[str, object]:
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
    try:
        return next(term for term in package.metric_terms if term.id == metric_id)
    except StopIteration as error:
        raise ValueError(
            f"Approved Context is missing DataHub Metric Glossary Term: {metric_id}"
        ) from error


def _model_invocations(trace: list[TraceStep]) -> tuple[ModelInvocationEvidence, ...]:
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
            f"successful analysis is missing gate evidence: {', '.join(missing)}"
        )
    return GateEvidence(
        g1=outcomes[PipelineStage.G1],
        g2=outcomes[PipelineStage.G2],
        g3=outcomes[PipelineStage.G3],
    )


def _gate_history(trace: list[TraceStep]) -> GateHistoryEvidence:
    return GateHistoryEvidence(
        g1=tuple(step.outcome for step in trace if step.stage == PipelineStage.G1),
        g2=tuple(step.outcome for step in trace if step.stage == PipelineStage.G2),
        g3=tuple(step.outcome for step in trace if step.stage == PipelineStage.G3),
    )


def _reduce_metric_values(reduction: str, values: list[object]) -> Decimal | None:
    if not values:
        return None
    decimals = [Decimal(str(value)) for value in values]
    if reduction == "sum":
        return sum(decimals, Decimal(0))
    if reduction == "min":
        return min(decimals, default=None)
    if reduction == "max":
        return max(decimals, default=None)
    if reduction == "average" and decimals:
        return sum(decimals, Decimal(0)) / len(decimals)
    if reduction == "scalar" and len(decimals) == 1:
        return decimals[0]
    # Unknown reduction modes are not executable in the active metric contract.
    return None
