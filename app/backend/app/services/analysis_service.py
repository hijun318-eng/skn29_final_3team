from __future__ import annotations

from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    ArtifactReference,
    ErrorBody,
    ErrorCode,
    PipelineStage,
    RequestContext,
    StageOutcome,
    TraceStep,
)
from app.ports.data_platform import DataPlatformAdapter
from app.ports.model import ModelAdapter
from app.services.analysis_responses import AnalysisResponseFactory
from app.services.context_builder import ContextPackageBuilder
from app.services.execution_control import (
    IsolatedExecutionCache,
    ModelCallBudget,
    secure_cache_key,
)
from app.services.pipeline_support import PipelineSupport
from app.services.routing_service import RouteDecision
from app.services.state_machine import AnalysisStateMachine


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
        )
        self._responses = AnalysisResponseFactory()
        self._cache = cache or IsolatedExecutionCache()

    def analyze(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        decision: RouteDecision,
    ) -> AnalysisResponse:
        machine = AnalysisStateMachine()
        trace: list[TraceStep] = []
        budget = ModelCallBudget()
        machine.transition(AnalysisStatus.ROUTED)
        self._responses.record(trace, PipelineStage.ROUTER)
        audit_id = secure_cache_key(
            "audit",
            trace_id=context.trace_id,
            entitlement=f"{context.user_id}:{context.role.value}",
            role=context.role.value,
            as_of=context.as_of,
            mask_scope=context.role.value,
            policy="policy-v1",
        )[:16]
        self._responses.record(trace, PipelineStage.CONTROLLER, f"audit={audit_id}")

        assets = self._adapter.search_assets(
            payload.question,
            context.model_dump(mode="json"),
        )
        package = self._support.build_context(payload, context, assets)
        self._responses.record(trace, PipelineStage.CONTEXT, package.package_hash)

        scenario = str(payload.parameters.get("scenario") or "")
        g1_error = self._support.g1_error(scenario)
        if g1_error:
            error_code, message = g1_error
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.G1,
                AnalysisStatus.BLOCKED,
                error_code,
                message,
                decision,
            )
        self._responses.record(trace, PipelineStage.G1)

        references = [
            {"urn": item.urn, "fqn": item.fqn, "columns": list(item.columns)}
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
            question=payload.question,
            template=decision.template_id,
            parameters=payload.parameters,
            **common_key,
        )
        plan = self._cache.get_plan(plan_key)
        plan_cached = plan is not None
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
                        "scenario": scenario,
                        "references": references,
                        "request_id": str(context.request_id),
                        "package": package,
                        "context": context,
                    },
                )
            except (TimeoutError, TypeError, ValueError):
                return self._responses.model_error(context, machine, trace, decision)
        if self._support.model_plan_violation(plan):
            return self._responses.model_error(context, machine, trace, decision)
        self._responses.record(
            trace,
            PipelineStage.MODEL,
            f"{plan.get('model_version')};plan_cache={'hit' if plan_cached else 'miss'}",
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
            self._responses.record(
                trace,
                PipelineStage.G2,
                violation,
                StageOutcome.BLOCKED,
            )
            repair_count = 1
            try:
                plan = budget.call(
                    self._model,
                    "node2_repair",
                    {
                        "scenario": scenario,
                        "attempt": repair_count,
                        "references": references,
                        "trace_id": context.trace_id,
                        "rejected_sql": str(plan["sql"]),
                        "violation": violation,
                        "package": package,
                        "context": context,
                    },
                )
            except (TimeoutError, TypeError, ValueError):
                return self._responses.model_error(
                    context,
                    machine,
                    trace,
                    decision,
                    repair_count,
                )
            self._responses.record(trace, PipelineStage.REPAIR, "attempt=1")
            if (
                self._support.model_plan_violation(plan)
                or self._support.g2_violation(plan, package)
            ):
                return self._responses.error(
                    context,
                    machine,
                    trace,
                    PipelineStage.G2,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.SQL_POLICY_BLOCKED,
                    "SQL repair 1회 후에도 정책 검증을 통과하지 못했습니다.",
                    decision,
                    repair_count,
                )
        self._responses.record(trace, PipelineStage.G2)

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
                query = self._adapter.execute_query(
                    plan["sql"],
                    plan.get("parameters", {}),
                    gate_token,
                )
                query = self._adapter.get_query_status(query["query_id"])
            else:
                query = cached_query
        except (KeyError, TimeoutError, TypeError, ValueError):
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
        self._responses.record(trace, PipelineStage.QUERY, query_id)
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
                    ErrorCode.INTERNAL_ERROR,
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
                ErrorCode.QUERY_SOURCE_FAILED,
                "조회 시간이 초과되어 취소했습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        if query_status == "CANCELLED":
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.QUERY,
                AnalysisStatus.CANCELLED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "요청이 취소되었습니다.",
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

        g3_violation = self._support.g3_violation(query)
        if g3_violation:
            return self._responses.error(
                context,
                machine,
                trace,
                PipelineStage.G3,
                AnalysisStatus.FAILED,
                ErrorCode.RESULT_EVIDENCE_MISSING,
                "근거 또는 결과 범위가 유효하지 않아 Artifact를 생성하지 않았습니다.",
                decision,
                repair_count,
            )
        self._responses.record(trace, PipelineStage.G3)
        if not result_cached:
            self._cache.put_result(result_key, query)

        try:
            explanation = budget.call(
                self._model,
                "node3",
                {
                    "scenario": scenario,
                    "query": query,
                    "assets": assets,
                    "context": context,
                },
            )
            if (
                not isinstance(explanation, dict)
                or not isinstance(explanation.get("summary"), str)
                or not isinstance(explanation.get("model_version"), str)
            ):
                raise ValueError("invalid node3 response")
        except (TimeoutError, TypeError, ValueError):
            return self._responses.model_error(
                context,
                machine,
                trace,
                decision,
                repair_count,
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
        self._responses.record(trace, PipelineStage.ARTIFACT, str(artifact_id))

        return self._responses.success(
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

    def blocked(self, context: RequestContext, error: ErrorBody) -> AnalysisResponse:
        return self._responses.blocked(context, error)
