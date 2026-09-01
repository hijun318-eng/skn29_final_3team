"""파이프라인 2단계: 계획 수립 및 G2 SQL 가드 검증 단계(PlanStage) 모듈.

[핵심 목적]
1. 템플릿 또는 LLM(Node 2) 우선 SQL 계획 생성과 Compiler 복구
2. G2 AST 거버넌스 가드(`g2_violation`)를 통한 정책/스키마/지표/조인/시간 검증
3. MODEL_ONLY 평가 모드의 1회 한정 자가 수리(`node2_repair`)
4. 안전성이 입증된 계획(`canonical_sql`, `executable_sql`)을 격리 캐시에 저장
"""

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
from app.services.analysis.model_support import model_failure_code, model_trace_detail
from app.services.analysis.pipeline_state import AnalysisPipelineState
from app.services.analysis.responses import AnalysisResponseFactory
from app.services.analysis.logical_plan import (
    AnalysisPlanError,
    AnalysisPlanErrorCode,
)
from app.services.analysis.typed_sql_compiler import TYPED_SQL_COMPILER_VERSION
from app.services.analysis.sql_generation_mode import SqlGenerationMode
from app.services.analysis.semantic_request import semantic_plan_identity
from app.services.context.builder import ContextPackage
from app.services.execution_control import IsolatedExecutionCache, secure_cache_key
from app.services.analysis.pipeline_support import PipelineSupport

logger = logging.getLogger("uvicorn.error")


class AnalysisPlanStage:
    """SQL 생성, G2 가드 검증 및 1회성 Repair를 총괄하는 단계 처리기 클래스."""

    def __init__(
        self,
        model: ModelAdapter,
        support: PipelineSupport,
        responses: AnalysisResponseFactory,
        cache: IsolatedExecutionCache,
        sql_generation_mode: SqlGenerationMode = SqlGenerationMode.HYBRID,
    ) -> None:
        self._model = model
        self._support = support
        self._responses = responses
        self._cache = cache
        self._sql_generation_mode = sql_generation_mode

    async def run(self, state: AnalysisPipelineState) -> AnalysisResponse | None:
        """계획 수립 단계를 실행하여 state에 검증된 plan을 저장합니다 (실패 시 AnalysisResponse 반환)."""
        package = cast(ContextPackage, state.package)
        context = state.context
        decision = state.decision

        # SQL 문자열을 생성하기 전에 지표·연산·차원·시간·JOIN 물리 전략을 서버가
        # 확정한다. 질문 문구나 모델 추정은 권한 및 팬아웃 결정을 열 수 없다.
        try:
            analysis_plan = self._support.analysis_plan(
                state.structured_request,
                package,
            )
        except AnalysisPlanError as error:
            logger.warning(
                "logical analysis plan rejected: reason=%s detail=%s",
                error.code.value,
                error,
            )
            state.record(
                PipelineStage.G2,
                error.code.value,
                StageOutcome.BLOCKED,
            )
            if error.code is AnalysisPlanErrorCode.JOIN_PERMISSION_DENIED:
                public_code = ErrorCode.ACCESS_DENIED
                message = "선택한 분석 조합에 필요한 데이터 관계 권한이 없습니다."
            elif error.code in {
                AnalysisPlanErrorCode.FANOUT_UNSAFE,
                AnalysisPlanErrorCode.JOIN_PATH_UNAVAILABLE,
            }:
                public_code = ErrorCode.GRAIN_VIOLATION
                message = "선택한 지표와 차원을 안전한 집계 단위로 결합할 수 없습니다."
            else:
                public_code = ErrorCode.SQL_POLICY_BLOCKED
                message = "선택한 지표·차원·기간으로 안전한 분석 계획을 만들 수 없습니다."
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.G2,
                AnalysisStatus.BLOCKED,
                public_code,
                message,
                decision,
                detail=error.code.value,
            )
        analysis_plan_payload = analysis_plan.as_dict()
        if state.approved_analysis_plan is not None and semantic_plan_identity(
            analysis_plan_payload
        ) != semantic_plan_identity(state.approved_analysis_plan):
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.G2,
                AnalysisStatus.BLOCKED,
                ErrorCode.SCHEMA_VERSION_MISMATCH,
                "저장된 Semantic Request가 현재 승인 카탈로그에서 같은 의미 계획으로 재검증되지 않았습니다.",
                decision,
                detail="APPROVED_SEMANTIC_PLAN_MISMATCH",
            )
        state.analysis_plan = analysis_plan_payload
        structured_for_model = {
            **state.structured_request,
            "metric_ids": list(analysis_plan.dependency_metric_ids),
            "selected_metric_ids": list(analysis_plan.output_metric_ids),
            "selected_metric_id": (
                analysis_plan.output_metric_ids[0]
                if len(analysis_plan.output_metric_ids) == 1
                else None
            ),
            "dimension_fields": [
                item.as_dict() for item in analysis_plan.dimension_fields
            ],
            "filter_fields": [item.as_dict() for item in analysis_plan.filter_fields],
            "analysis_operation": analysis_plan.operation.value,
            "analysis_time_bucket": analysis_plan.time_bucket,
            "analysis_result_limit": analysis_plan.result_limit,
        }

        # 1. 격리된 실행 캐시 확인
        plan_key = secure_cache_key(
            "sql-plan",
            question=state.normalized_question,
            template=decision.template_id,
            parameters=state.payload.parameters,
            analysis_plan_checksum=analysis_plan.checksum,
            typed_sql_compiler=TYPED_SQL_COMPILER_VERSION,
            sql_generation_mode=self._sql_generation_mode.value,
            **state.common_key,
        )
        plan = self._cache.get_plan(plan_key)
        plan_cached = plan is not None
        node2_trace_detail = None
        node2_fallback_reason = None

        if plan is not None:
            pass
        elif decision.sql_text:
            # 2-A. 사전 승인된 템플릿 SQL 계획 사용
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
            # 2-B. 저장된 semantic snapshot은 재현성을 위해 Compiler 경로를 유지한다.
            # 일반 HYBRID 요청은 Node 2 후보를 먼저 받고, 계약/G2 실패 때만 동일한
            # 서버 소유 논리 계획을 Compiler가 복구한다.
            compiler_first = (
                self._sql_generation_mode is SqlGenerationMode.COMPILER_ONLY
                or state.approved_semantic_snapshot is not None
            )
            if compiler_first:
                plan = self._support.typed_sql_plan(analysis_plan, package)
                if plan is None:
                    return self._responses.error(
                        context,
                        state.machine,
                        state.trace,
                        PipelineStage.G2,
                        AnalysisStatus.BLOCKED,
                        ErrorCode.SQL_POLICY_BLOCKED,
                        "현재 승인된 SQL 컴파일 범위에서 이 분석 구조를 실행할 수 없습니다.",
                        decision,
                        detail="COMPILER_SCOPE_UNSUPPORTED",
                    )
            else:
                try:
                    plan = await state.budget.call(
                        self._model,
                        "node2",
                        {
                            "question": state.normalized_question,
                            "structured_request": structured_for_model,
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
                    if self._sql_generation_mode is SqlGenerationMode.MODEL_ONLY:
                        return self._responses.model_error(
                            context,
                            state.machine,
                            state.trace,
                            decision,
                            code=model_failure_code(error),
                        )
                    node2_fallback_reason = f"call_{type(error).__name__}"
                    plan = None

                if plan is not None:
                    if isinstance(plan, dict):
                        plan["analysis_plan"] = analysis_plan_payload
                    node2_plan_violation = self._support.model_plan_violation(plan)
                    if node2_plan_violation:
                        logger.warning(
                            "node2 plan rejected before G2: reason=%s keys=%s",
                            node2_plan_violation,
                            sorted(plan) if isinstance(plan, dict) else [],
                        )
                        if self._sql_generation_mode is SqlGenerationMode.MODEL_ONLY:
                            return self._responses.model_error(
                                context, state.machine, state.trace, decision
                            )
                        node2_fallback_reason = f"contract_{node2_plan_violation}"
                        plan = None

                if plan is None:
                    plan = self._support.typed_sql_plan(analysis_plan, package)
                    if plan is None:
                        return self._responses.error(
                            context,
                            state.machine,
                            state.trace,
                            PipelineStage.G2,
                            AnalysisStatus.BLOCKED,
                            ErrorCode.SQL_POLICY_BLOCKED,
                            "모델 SQL을 사용할 수 없고 현재 Compiler 복구 범위에도 포함되지 않습니다.",
                            decision,
                            detail=(
                                f"NODE2_{node2_fallback_reason};"
                                "COMPILER_SCOPE_UNSUPPORTED"
                            ),
                        )

        if isinstance(plan, dict):
            # 모델이나 캐시가 이 값을 소유하지 못하도록 G2 직전에 현재 Context에서
            # 컴파일한 payload로 항상 덮어쓴다.
            plan["analysis_plan"] = analysis_plan_payload
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

        # 3. G2 SQL AST 거버넌스 가드 검증
        repair_count = 0
        violation = self._support.g2_violation(plan, package)

        if (
            violation
            and self._sql_generation_mode is SqlGenerationMode.HYBRID
            and decision.route_type is not RouteType.TEMPLATE
            and plan.get("plan_source") != "typed_sql_compiler"
        ):
            logger.warning(
                "node2 G2 rejected; attempting compiler recovery: reason=%s",
                violation,
            )
            compiler_plan = self._support.typed_sql_plan(analysis_plan, package)
            if compiler_plan is None:
                state.record(
                    PipelineStage.MODEL,
                    f"{node2_trace_detail};plan_cache=miss"
                    if node2_trace_detail
                    else "node=node2;plan_cache=miss",
                )
                state.record(PipelineStage.G2, str(violation), StageOutcome.BLOCKED)
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.G2,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.SQL_POLICY_BLOCKED,
                    "모델 SQL이 안전성 검증을 통과하지 못했고 현재 Compiler 복구 범위에도 포함되지 않습니다.",
                    decision,
                    detail=f"NODE2_G2_{violation};COMPILER_SCOPE_UNSUPPORTED",
                )
            compiler_plan["analysis_plan"] = analysis_plan_payload
            plan = compiler_plan
            node2_fallback_reason = f"g2_{violation}"
            compiler_plan_violation = self._support.model_plan_violation(plan)
            violation = (
                compiler_plan_violation
                or self._support.g2_violation(plan, package)
            )

        model_stage_detail = (
            (
                f"node={plan.get('plan_source', 'typed_sql_compiler')};"
                f"model={plan.get('model_version')};plan_cache=miss;"
                f"fallback_from_node2={node2_fallback_reason}"
            )
            if node2_fallback_reason
            else (
                f"{node2_trace_detail};plan_cache=miss"
                if node2_trace_detail
                else (
                    f"{plan['_model_trace_detail']};plan_cache=hit"
                    if plan_cached
                    and isinstance(plan.get("_model_trace_detail"), str)
                    else (
                        f"node={plan.get('plan_source', 'node2')};"
                        f"model={plan.get('model_version')};"
                        f"plan_cache={'hit' if plan_cached else 'template' if decision.sql_text else 'miss'}"
                    )
                )
            )
        )
        state.record(PipelineStage.MODEL, model_stage_detail)

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
                if violation == "GRAIN_VIOLATION":
                    return self._responses.error(
                        context,
                        state.machine,
                        state.trace,
                        PipelineStage.G2,
                        AnalysisStatus.BLOCKED,
                        ErrorCode.GRAIN_VIOLATION,
                        "서로 다른 grain의 자산을 사전집계 없이 직접 JOIN하면 매출이 부풀려질 수 있어 차단했습니다.",
                        decision,
                    )
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

            # 결정론적 컴파일러 결과의 실패는 모델에게 SQL을 다시 쓰게 해서 우회하지
            # 않는다. 이는 compiler 또는 release 계약 결함이므로 동일 G2 원인으로 닫는다.
            if plan.get("plan_source") == "typed_sql_compiler":
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.G2,
                    AnalysisStatus.BLOCKED,
                    (
                        ErrorCode.GRAIN_VIOLATION
                        if violation == "GRAIN_VIOLATION"
                        else ErrorCode.SQL_POLICY_BLOCKED
                    ),
                    "승인된 분석 계획을 실행 SQL로 변환했지만 현재 SQL 정책을 통과하지 못했습니다.",
                    decision,
                    detail=str(violation),
                )

            # 4. 1회 한정 자가 수리 (Repair Loop)
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
                        "structured_request": structured_for_model,
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
                plan["analysis_plan"] = analysis_plan_payload
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
                if final_violation == "GRAIN_VIOLATION":
                    return self._responses.error(
                        context,
                        state.machine,
                        state.trace,
                        PipelineStage.REPAIR,
                        AnalysisStatus.FAILED,
                        ErrorCode.GRAIN_VIOLATION,
                        "수정한 SQL도 서로 다른 grain을 사전집계 없이 JOIN해 차단했습니다.",
                        decision,
                        repair_count,
                        detail=str(final_violation),
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

        # 5. 캐시에 성공 계획 보관 및 state 갱신
        self._cache.put_plan(plan_key, plan)
        state.plan_key = plan_key
        state.plan = plan
        state.plan_cached = plan_cached
        state.repair_count = repair_count
        return None
