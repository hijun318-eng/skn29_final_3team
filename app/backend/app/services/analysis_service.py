from __future__ import annotations

import hashlib
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    ArtifactReference,
    ChartSpec,
    ClarificationType,
    ErrorBody,
    ErrorCode,
    PipelineStage,
    RequestContext,
    Role,
    RouteType,
    StageOutcome,
    TraceStep,
)
from app.ports.data_platform import DataPlatformAdapter, NoEntitledAssetsError
from app.ports.model import ModelAdapter
from app.services.analysis_responses import AnalysisResponseFactory
from app.services.context_builder import (
    ContextBuildError,
    ContextBuildErrorCode,
    ContextPackageBuilder,
)
from app.services.execution_control import (
    IsolatedExecutionCache,
    ModelCallBudget,
    secure_cache_key,
)
from app.services.pipeline_support import PipelineSupport
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


logger = logging.getLogger("uvicorn.error")


def _model_trace_detail(model: ModelAdapter) -> str:
    trace = getattr(model, "last_trace", {})
    return ";".join(
        (
            f"node={trace.get('node', 'unknown')}",
            f"model={trace.get('model_version') or 'unknown'}",
            f"prompt={trace.get('prompt_id', 'unknown')}@{trace.get('prompt_version', 'unknown')}",
            f"prompt_hash={trace.get('prompt_hash', 'unknown')}",
            f"duration_ms={trace.get('duration_ms')}",
            f"attempts={trace.get('attempts', 1)}",
            f"status={trace.get('status', 'SUCCESS')}",
        )
    )


class AnalysisService:
    """R4가 소유하는 결정론적 Gate·query·Artifact 제어 흐름."""

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        model: ModelAdapter,
        context_builder: ContextPackageBuilder | None = None,
        cache: IsolatedExecutionCache | None = None,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._support = PipelineSupport(
            adapter,
            context_builder or ContextPackageBuilder(),
            model,
        )
        self._responses = AnalysisResponseFactory()
        self._cache = cache or IsolatedExecutionCache()

    def analyze(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        decision: RouteDecision,
        execution_sink: Callable[[dict[str, Any]], None] | None = None,
        progress_sink: Callable[[PipelineStage, StageOutcome], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> AnalysisResponse:
        machine = AnalysisStateMachine()
        trace: list[TraceStep] = []
        budget = ModelCallBudget()
        def record(
            target_trace: list[TraceStep],
            stage: PipelineStage,
            detail: str | None = None,
            outcome: StageOutcome = StageOutcome.PASSED,
        ) -> None:
            self._responses.record(target_trace, stage, detail, outcome)
            if progress_sink is not None:
                progress_sink(stage, outcome)

        def cancelled(stage: PipelineStage) -> AnalysisResponse | None:
            if cancel_check is None or not cancel_check():
                return None
            if progress_sink is not None:
                progress_sink(stage, StageOutcome.FAILED)
            return self._responses.error(
                context,
                machine,
                trace,
                stage,
                AnalysisStatus.CANCELLED,
                ErrorCode.REQUEST_CANCELLED,
                "사용자가 분석 요청을 취소했습니다.",
                decision,
            )

        machine.transition(AnalysisStatus.ROUTED)
        record(trace, PipelineStage.ROUTER)
        audit_id = secure_cache_key(
            "audit",
            trace_id=context.trace_id,
            entitlement=f"{context.user_id}:{context.role.value}",
            role=context.role.value,
            as_of=context.as_of,
            mask_scope=context.role.value,
            policy="policy-v1",
        )[:16]
        record(trace, PipelineStage.CONTROLLER, f"audit={audit_id}")

        cancelled_response = cancelled(PipelineStage.CONTROLLER)
        if cancelled_response is not None:
            return cancelled_response

        if context.role is not Role.HOTEL_ANALYST:
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.CONTROLLER,
                AnalysisStatus.BLOCKED,
                ErrorCode.ACCESS_DENIED,
                "분석 Agent는 hotel_analyst 역할만 사용할 수 있습니다.",
                decision,
            )

        try:
            assets = self._adapter.search_assets(
                payload.question,
                {
                    **context.model_dump(mode="json"),
                    "template_id": decision.template_id,
                },
            )
        except NoEntitledAssetsError:
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.BLOCKED,
                ErrorCode.DATA_ASSET_NOT_FOUND,
                "질문과 권한 범위에 맞는 승인 데이터 자산을 찾지 못했습니다.",
                decision,
            )
        except (TimeoutError, OSError, ValueError) as error:
            logger.warning(
                "context lookup failed: type=%s detail=%s",
                type(error).__name__,
                error,
            )
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.FAILED,
                ErrorCode.CONTEXT_SOURCE_FAILED,
                "승인된 데이터 컨텍스트를 조회하지 못했습니다.",
                decision,
                retryable=True,
            )
        cancelled_response = cancelled(PipelineStage.CONTEXT)
        if cancelled_response is not None:
            return cancelled_response
        try:
            assets, normalized_question, structured_request = self._support.select_metric(
                payload, context, assets
            )
            if getattr(self._model, "last_trace", {}).get("node") == "node1":
                record(
                    trace,
                    PipelineStage.MODEL,
                    _model_trace_detail(self._model),
                )
            package = self._support.build_context(
                payload,
                context,
                assets,
                structured_request,
            )
        except ContextBuildError as error:
            message = (
                "질문에 분석 기간을 하나만 명확히 포함해 주세요. 예: 2026년 6월 객실 매출을 분석해 줘."
                if error.code is ContextBuildErrorCode.PERIOD_REQUIRED
                else "질문이 여러 지표로 해석될 수 있습니다. 분석할 기준을 선택해 주세요."
            )
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.BLOCKED,
                ErrorCode.CONTEXT_INCOMPLETE,
                message,
                decision,
                suggestions=error.suggestions,
                clarification_type=(
                    ClarificationType.PERIOD
                    if error.code is ContextBuildErrorCode.PERIOD_REQUIRED
                    else ClarificationType.METRIC
                ),
            )
        except TimeoutError as error:
            logger.warning(
                "node1 generation failed: type=%s detail=%s",
                type(error).__name__,
                error,
            )
            return self._responses.model_error(
                context, machine, trace, decision, timed_out=True
            )
        except (TypeError, ValueError) as error:
            logger.warning(
                "node1 generation failed: type=%s detail=%s",
                type(error).__name__,
                error,
            )
            return self._responses.model_error(context, machine, trace, decision)
        record(trace, PipelineStage.CONTEXT, package.package_hash)

        record(trace, PipelineStage.G1)
        cancelled_response = cancelled(PipelineStage.G1)
        if cancelled_response is not None:
            return cancelled_response

        references = [
            {
                "urn": item.urn,
                "fqn": item.fqn,
                "columns": list(item.columns),
                "join_ids": list(item.join_ids),
                "metric_ids": [
                    metric.id
                    for metric in package.metrics
                    if metric.asset_fqn == item.fqn
                ],
            }
            for item in package.assets
        ]
        watermark = secure_cache_key(
            "watermark",
            assets=[
                (item.get("urn"), item.get("schema_version"), item.get("seed_version"))
                for item in assets
            ],
        )
        mask = secure_cache_key(
            "mask",
            role=context.role.value,
            policy=package.policy_version,
        )
        common_key = {
            "context": package.package_hash,
            "policy": package.policy_version,
            "entitlement": package.entitlement_hash,
            "as_of": context.as_of,
            "watermark": watermark,
            "mask": mask,
        }
        plan_key = secure_cache_key(
            "sql-plan",
            question=normalized_question,
            template=decision.template_id,
            parameters=payload.parameters,
            **common_key,
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
                    for item in references
                    if item["fqn"] in decision.source_fqns
                ],
                "parameters": payload.parameters,
                "model_version": "TEMPLATE-I2-v1.0.0",
            }
        else:
            try:
                plan = budget.call(
                    self._model,
                    "node2",
                    {
                        "question": normalized_question,
                        "structured_request": structured_request,
                        "references": references,
                        "request_id": str(context.request_id),
                        "package": package,
                        "context": context,
                    },
                )
                node2_trace_detail = _model_trace_detail(self._model)
                plan["_model_trace_detail"] = node2_trace_detail
            except TimeoutError as error:
                logger.warning(
                    "node2 generation failed: type=%s detail=%s",
                    type(error).__name__,
                    error,
                )
                return self._responses.model_error(
                    context, machine, trace, decision, timed_out=True
                )
            except (TypeError, ValueError) as error:
                logger.warning(
                    "node2 generation failed: type=%s detail=%s",
                    type(error).__name__,
                    error,
                )
                return self._responses.model_error(context, machine, trace, decision)
        plan_violation = self._support.model_plan_violation(plan)
        if plan_violation:
            logger.warning(
                "node2 plan rejected: reason=%s keys=%s",
                plan_violation,
                sorted(plan) if isinstance(plan, dict) else [],
            )
            return self._responses.model_error(context, machine, trace, decision)
        record(
            trace,
            PipelineStage.MODEL,
            (
                f"{node2_trace_detail};plan_cache=miss"
                if node2_trace_detail
                else (
                    f"{plan['_model_trace_detail']};plan_cache=hit"
                    if plan_cached and isinstance(plan.get("_model_trace_detail"), str)
                    else f"node=node2;model={plan.get('model_version')};plan_cache={'hit' if plan_cached else 'template'}"
                )
            ),
        )

        repair_count = 0
        violation = self._support.g2_violation(plan, package)
        if violation == "UNSAFE_SQL":
            return self._responses.error(
                context,
                machine,
                trace,
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
            record(
                trace,
                PipelineStage.G2,
                violation,
                StageOutcome.BLOCKED,
            )
            if decision.route_type is RouteType.TEMPLATE:
                return self._responses.error(
                    context,
                    machine,
                    trace,
                    PipelineStage.G2,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.SQL_POLICY_BLOCKED,
                    "승인된 Template SQL이 현재 G2 정책을 통과하지 못했습니다.",
                    decision,
                )
            repair_count = 1
            try:
                plan = budget.call(
                    self._model,
                    "node2_repair",
                    {
                        "attempt": repair_count,
                        "references": references,
                        "trace_id": context.trace_id,
                        "rejected_sql": str(plan["sql"]),
                        "violation": violation,
                        "violation_detail": self._support.g2_repair_hint(
                            violation, package
                        ),
                        "package": package,
                        "context": context,
                    },
                )
                repair_trace_detail = _model_trace_detail(self._model)
                plan["_model_trace_detail"] = repair_trace_detail
            except (TimeoutError, TypeError, ValueError) as error:
                logger.warning("node2 repair failed: type=%s", type(error).__name__)
                return self._responses.error(
                    context,
                    machine,
                    trace,
                    PipelineStage.REPAIR,
                    AnalysisStatus.FAILED,
                    ErrorCode.SQL_REPAIR_FAILED,
                    "SQL 수정 결과를 검증하지 못했습니다.",
                    decision,
                    repair_count,
                    retryable=isinstance(error, TimeoutError),
                )
            record(
                trace,
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
                        str(plan.get("sql") if isinstance(plan, dict) else "").encode(
                            "utf-8"
                        )
                    ).hexdigest()[:16],
                )
                return self._responses.error(
                    context,
                    machine,
                    trace,
                    PipelineStage.REPAIR,
                    AnalysisStatus.FAILED,
                    ErrorCode.SQL_REPAIR_FAILED,
                    "한 차례 수정한 SQL도 안전성 검증을 통과하지 못했습니다.",
                    decision,
                    repair_count,
                    detail=str(final_violation),
                )
        record(trace, PipelineStage.G2)
        cancelled_response = cancelled(PipelineStage.G2)
        if cancelled_response is not None:
            return cancelled_response

        self._cache.put_plan(plan_key, plan)
        gate_token = self._support.gate_token(package, str(plan["sql"]))
        result_key = secure_cache_key(
            "query-result",
            sql=plan["sql"],
            parameters=plan.get("parameters", {}),
            **common_key,
        )
        cached_query = self._cache.get_result(result_key)
        result_cached = cached_query is not None
        try:
            if cached_query is None:
                bind_cancellation = getattr(self._adapter, "bind_cancellation", None)
                if bind_cancellation is not None:
                    bind_cancellation(cancel_check)
                try:
                    query = self._adapter.execute_query(
                        plan["sql"],
                        plan.get("parameters", {}),
                        gate_token,
                    )
                finally:
                    if bind_cancellation is not None:
                        bind_cancellation(None)
                query = self._adapter.get_query_status(query["query_id"])
            else:
                query = cached_query
        except TimeoutError:
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_TIMEOUT,
                "데이터 조회 시간이 초과되었습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        except (OSError, ConnectionError):
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.TRINO_CONNECTION_FAILED,
                "데이터 조회 서비스에 연결하지 못했습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        except (KeyError, TypeError, ValueError):
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "원천 조회 상태를 확인할 수 없습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        query_id = str(query.get("query_id", ""))
        record(trace, PipelineStage.QUERY, query_id)
        query_status = query.get("status")
        if query_status == "TIMEOUT":
            try:
                terminal = self._adapter.cancel_query(query_id)
            except (KeyError, TimeoutError, TypeError, ValueError):
                terminal = {}
            if terminal.get("status") != "CANCELLED":
                return self._responses.error(
                    context,
                    machine,
                    trace,
                    PipelineStage.QUERY,
                    AnalysisStatus.FAILED,
                    ErrorCode.QUERY_TIMEOUT,
                    "시간 초과 조회의 종료 상태를 확인할 수 없습니다.",
                    decision,
                    repair_count,
                )
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_TIMEOUT,
                "조회 시간이 초과되어 취소했습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        if query_status == "CANCELLED":
            if progress_sink is not None:
                progress_sink(PipelineStage.QUERY, StageOutcome.FAILED)
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.CANCELLED,
                ErrorCode.REQUEST_CANCELLED,
                "사용자가 분석 요청을 취소했습니다.",
                decision,
                repair_count,
            )
        if query_status == "FAILED":
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "원천 조회에 실패했습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        if query_status not in {"SUCCEEDED", "PARTIAL"}:
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "원천 조회가 정상 종료 상태가 아닙니다.",
                decision,
                repair_count,
                retryable=True,
            )
        cancelled_response = cancelled(PipelineStage.QUERY)
        if cancelled_response is not None:
            return cancelled_response

        query = self._support.normalize_empty_aggregate(query, package)

        g3_violation = self._support.g3_violation(query)
        if g3_violation:
            error_code = (
                ErrorCode.RESULT_EVIDENCE_MISSING
                if g3_violation == "EVIDENCE_INCOMPLETE"
                else ErrorCode.RESULT_VALIDATION_FAILED
            )
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.G3,
                AnalysisStatus.FAILED,
                error_code,
                "근거 또는 결과 범위가 유효하지 않아 Artifact를 생성하지 않았습니다.",
                decision,
                repair_count,
                detail=g3_violation,
            )
        record(trace, PipelineStage.G3)
        cancelled_response = cancelled(PipelineStage.G3)
        if cancelled_response is not None:
            return cancelled_response
        if not result_cached:
            self._cache.put_result(result_key, query)

        if decision.route_type is RouteType.TEMPLATE:
            explanation = {
                "summary": f"승인된 분석에서 {len(query['rows'])}건을 조회했습니다.",
                "model_version": "TEMPLATE-RESULT-v1.0.0",
            }
        else:
            try:
                explanation = budget.call(
                    self._model,
                    "node3",
                    {
                        "query": query,
                        "assets": assets,
                        "context": context,
                        "package": package,
                    },
                )
                record(
                    trace,
                    PipelineStage.MODEL,
                    _model_trace_detail(self._model),
                )
                if (
                    not isinstance(explanation, dict)
                    or not isinstance(explanation.get("summary"), str)
                    or not isinstance(explanation.get("model_version"), str)
                ):
                    raise ValueError("invalid node3 response")
            except TimeoutError:
                return self._responses.model_error(
                    context,
                    machine,
                    trace,
                    decision,
                    repair_count,
                    timed_out=True,
                )
            except (TypeError, ValueError):
                return self._responses.model_error(
                    context, machine, trace, decision, repair_count
                )
        artifact_id = self._support.artifact_id(
            context.trace_id,
            query["query_id"],
            package.package_hash,
        )
        artifact = ArtifactReference(
            artifact_id=artifact_id,
            query_id=query["query_id"],
            context_hash=package.package_hash,
        )
        record(trace, PipelineStage.ARTIFACT, str(artifact_id))

        response = self._responses.success(
            support=self._support,
            context=context,
            machine=machine,
            trace=trace,
            decision=decision,
            package=package,
            assets=assets,
            query=query,
            explanation=explanation,
            artifact=artifact,
            repair_count=repair_count,
            cached=result_cached,
        )
        rows = query["rows"]
        if rows and response.data.result is not None:
            columns = tuple(rows[0])
            numeric = tuple(
                column
                for column in columns[1:]
                if all(
                    self._is_numeric(row.get(column))
                    for row in rows
                )
            )
            if "total_guest_revenue_krw" in numeric:
                numeric = ("total_guest_revenue_krw",)
            if (
                decision.template_id == "weekly-room-operations"
                and "recognized_room_revenue_krw" in columns
            ):
                numeric = ("recognized_room_revenue_krw",)
            if columns and numeric:
                response.data.result.chart = ChartSpec(
                    chart_type="bar",
                    x_field="month" if "month" in columns else columns[0],
                    y_fields=numeric,
                )
        if execution_sink is not None:
            execution_sink({"plan": plan, "query": query, "package": package})
        return response

    @staticmethod
    def _is_numeric(value: object) -> bool:
        if isinstance(value, bool) or value is None:
            return False
        try:
            Decimal(str(value))
        except (InvalidOperation, ValueError):
            return False
        return True

    def blocked(self, context: RequestContext, error: ErrorBody) -> AnalysisResponse:
        return self._responses.blocked(context, error)
