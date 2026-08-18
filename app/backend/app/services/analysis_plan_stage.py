"""runtime package와 승인 template 또는 model 출력으로 계획 후보를 얻고, SQLGlot G2와 한 번의 제한된 repair를 통과한 SQL만 실행 상태에 남긴다."""

from __future__ import annotations

import hashlib
import logging
from typing import cast

from app.contracts import (
    AnalysisResponse,
    AnalysisStatus,
    ErrorCode,
    PipelineStage,
    RouteType,
    StageOutcome,
)
from app.ports.model import ModelAdapter
from app.services.analysis_model_support import model_failure_code, model_trace_detail
from app.services.analysis_pipeline_state import AnalysisPipelineState
from app.services.analysis_responses import AnalysisResponseFactory
from app.services.context_builder import ContextPackage
from app.services.execution_control import IsolatedExecutionCache, secure_cache_key
from app.services.pipeline_support import PipelineSupport


logger = logging.getLogger("uvicorn.error")


class AnalysisPlanStage:
    """AnalysisPlanStage는 분석 계획 단계 단계의 입력, 상태 전이, 다음 처리 결과를 조정한다."""
    def __init__(
        self,
        model: ModelAdapter,
        support: PipelineSupport,
        responses: AnalysisResponseFactory,
        cache: IsolatedExecutionCache,
    ) -> None:
        self._model = model
        self._support = support
        self._responses = responses
        self._cache = cache

    async def run(self, state: AnalysisPipelineState) -> AnalysisResponse | None:
        """runtime context에 근거한 SQL 계획을 선택하고 G2를 통과한 계획만 상태에 저장한다.

        격리 key가 맞는 cache, 같은 DB 행에서 승인된 template SQL, 또는 node2 출력만 후보로
        사용한다. SQLGlot·lineage 검증 실패는 일반 route에서 한 번만 동적 repair하며, 재실패·
        unsafe SQL·모델 장애는 typed 응답으로 반환한다. 성공 시 ``None``을 반환한다.
        """
        package = cast(ContextPackage, state.package)
        context = state.context
        decision = state.decision
        plan_key = secure_cache_key(
            "sql-plan",
            question=state.normalized_question,
            template=decision.template_id,
            parameters=state.payload.parameters,
            **state.common_key,
        )
        plan = self._cache.get_plan(plan_key)
        plan_cached = plan is not None
        node2_trace_detail = None
        if plan is not None:
            pass
        elif decision.sql_text:
            plan = {
                "sql": decision.sql_text,
                "references": [
                    item
                    for item in state.references
                    if item["fqn"] in decision.source_fqns
                ],
                "parameters": {
                    item.name: {
                        "value_type": item.value_type,
                        "value": item.value,
                    }
                    for item in package.parameter_bindings
                },
                "model_version": "TEMPLATE-I2-v1.0.0",
            }
        else:
            try:
                plan = await state.budget.call(
                    self._model,
                    "node2",
                    {
                        "question": state.normalized_question,
                        "structured_request": state.structured_request,
                        "references": state.references,
                        "request_id": str(context.request_id),
                        "package": package,
                        "context": context,
                    },
                )
                node2_trace_detail = model_trace_detail(self._model)
                plan["_model_trace_detail"] = node2_trace_detail
            except (TimeoutError, OSError, TypeError, ValueError) as error:
                logger.warning(
                    "node2 generation failed: type=%s detail=%s",
                    type(error).__name__,
                    error,
                )
                return self._responses.model_error(
                    context,
                    state.machine,
                    state.trace,
                    decision,
                    code=model_failure_code(error),
                )
        plan_violation = self._support.model_plan_violation(plan)
        if plan_violation:
            logger.warning(
                "node2 plan rejected: reason=%s keys=%s",
                plan_violation,
                sorted(plan) if isinstance(plan, dict) else [],
            )
            return self._responses.model_error(
                context, state.machine, state.trace, decision
            )
        state.record(
            PipelineStage.MODEL,
            (
                f"{node2_trace_detail};plan_cache=miss"
                if node2_trace_detail
                else (
                    f"{plan['_model_trace_detail']};plan_cache=hit"
                    if plan_cached
                    and isinstance(plan.get("_model_trace_detail"), str)
                    else f"node=node2;model={plan.get('model_version')};plan_cache={'hit' if plan_cached else 'template'}"
                )
            ),
        )

        repair_count = 0
        violation = self._support.g2_violation(plan, package)
        if violation == "UNSAFE_SQL":
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.G2,
                AnalysisStatus.BLOCKED,
                ErrorCode.SQL_POLICY_BLOCKED,
                "조회 전용 SQL만 허용합니다.",
                decision,
            )
        if violation:
            referenced_assets = {
                str(item.get("fqn"))
                for item in plan.get("references", ())
                if isinstance(item, dict) and item.get("fqn")
            }
            approved_assets = {item.fqn for item in package.assets}
            referenced_join_ids = {
                str(join_id)
                for item in plan.get("references", ())
                if isinstance(item, dict)
                for join_id in item.get("join_ids", ())
            }
            logger.warning(
                "node2 G2 rejected: reason=%s missing_assets=%s extra_assets=%s "
                "approved_joins=%s referenced_joins=%s",
                violation,
                sorted(approved_assets - referenced_assets),
                sorted(referenced_assets - approved_assets),
                sorted(package.approved_join_ids),
                sorted(referenced_join_ids),
            )
            state.record(
                PipelineStage.G2,
                violation,
                StageOutcome.BLOCKED,
            )
            if decision.route_type is RouteType.TEMPLATE:
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.G2,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.SQL_POLICY_BLOCKED,
                    "승인된 Template SQL이 현재 G2 정책을 통과하지 못했습니다.",
                    decision,
                )
            repair_count = 1
            try:
                plan = await state.budget.call(
                    self._model,
                    "node2_repair",
                    {
                        "attempt": repair_count,
                        "references": state.references,
                        "trace_id": context.trace_id,
                        "rejected_sql": str(plan["sql"]),
                        "normalized_question": state.normalized_question,
                        "structured_request": state.structured_request,
                        "violation": violation,
                        "violation_detail": self._support.g2_repair_hint(
                            violation, package
                        ),
                        "package": package,
                        "context": context,
                    },
                )
                repair_trace_detail = model_trace_detail(self._model)
                plan["_model_trace_detail"] = repair_trace_detail
            except (TimeoutError, OSError, TypeError, ValueError) as error:
                logger.warning("node2 repair failed: type=%s", type(error).__name__)
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.REPAIR,
                    AnalysisStatus.FAILED,
                    ErrorCode.SQL_REPAIR_FAILED,
                    "SQL 수정 결과를 검증하지 못했습니다.",
                    decision,
                    repair_count,
                    retryable=bool(
                        getattr(error, "retryable", isinstance(error, TimeoutError))
                    ),
                )
            state.record(
                PipelineStage.REPAIR,
                f"{repair_trace_detail};controller_attempt=1",
            )
            repaired_plan_violation = self._support.model_plan_violation(plan)
            repaired_g2_violation = self._support.g2_violation(plan, package)
            if repaired_plan_violation or repaired_g2_violation:
                final_violation = repaired_plan_violation or repaired_g2_violation
                logger.warning(
                    "node2 repair rejected: reason=%s sql_sha256=%s",
                    final_violation,
                    hashlib.sha256(
                        str(
                            plan.get("sql") if isinstance(plan, dict) else ""
                        ).encode("utf-8")
                    ).hexdigest()[:16],
                )
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.REPAIR,
                    AnalysisStatus.FAILED,
                    ErrorCode.SQL_REPAIR_FAILED,
                    "한 차례 수정한 SQL도 안전성 검증을 통과하지 못했습니다.",
                    decision,
                    repair_count,
                    detail=str(final_violation),
                )
        state.record(PipelineStage.G2)
        cancelled = state.cancelled(PipelineStage.G2)
        if cancelled is not None:
            return cancelled

        self._cache.put_plan(plan_key, plan)
        state.plan_key = plan_key
        state.plan = plan
        state.plan_cached = plan_cached
        state.repair_count = repair_count
        return None
