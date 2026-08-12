from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import date
from typing import Any, Callable

from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    ArtifactReference,
    ChartSpec,
    ErrorBody,
    ErrorCode,
    PipelineStage,
    RequestContext,
    RouteType,
    StageOutcome,
    TraceStep,
)
from app.ports.data_platform import DataPlatformAdapter
from app.ports.data_platform import DataPlatformAccessDenied, DataPlatformNoAssets, DataPlatformUnavailable
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
from app.telemetry import observe_stage
from app.adapters.context_registry_repository import PublishedContextRelease


class AnalysisService:
    """R4가 소유하는 결정론적 Gate·query·Artifact 제어 흐름."""

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        model: ModelAdapter,
        context_builder: ContextPackageBuilder | None = None,
        cache: IsolatedExecutionCache | None = None,
        release_resolver: Callable[[date], PublishedContextRelease] | None = None,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._support = PipelineSupport(
            adapter,
            context_builder or ContextPackageBuilder(),
            release_resolver,
        )
        self._responses = AnalysisResponseFactory()
        self._cache = cache or IsolatedExecutionCache()

    def _call_model(
        self,
        budget: ModelCallBudget,
        node: str,
        payload: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        with observe_stage(
            "model",
            context=context,
            attributes={"gen_ai.operation.name": node},
        ) as span:
            result = budget.call(self._model, node, payload)
            if isinstance(result, dict) and isinstance(result.get("model_version"), str):
                span.set_attribute("gen_ai.response.model", result["model_version"])
            return result

    def analyze(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        decision: RouteDecision,
        execution_sink: Callable[[dict[str, Any]], None] | None = None,
        progress_sink: Callable[[str, str], None] | None = None,
    ) -> AnalysisResponse:
        def progress(stage: str, outcome: str) -> None:
            if progress_sink is not None:
                progress_sink(stage, outcome)

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
            policy=context.access_policy_version or "policy-v1",
            access_profile=context.access_profile,
            entitlement_hash=context.entitlement_hash,
        )[:16]
        self._responses.record(trace, PipelineStage.CONTROLLER, f"audit={audit_id}")

        asset_query = (
            " ".join(sorted(decision.source_fqns))
            if decision.route_type is RouteType.TEMPLATE
            else payload.question
        )
        progress("DATAHUB", "STARTED")
        try:
            with observe_stage(
                "context",
                context=context,
                attributes={
                    "answervice.context.operation": "datahub_search",
                    "answervice.access_profile": context.access_profile or "default",
                },
            ):
                assets = self._adapter.search_assets(
                    asset_query,
                    context.model_dump(mode="json"),
                )
        except DataPlatformAccessDenied:
            progress("DATAHUB", "BLOCKED")
            return self._responses.error(
                context, machine, trace, PipelineStage.CONTEXT,
                AnalysisStatus.BLOCKED, ErrorCode.ACCESS_DENIED,
                "선택한 접근 Profile로 검색할 수 없습니다.", decision,
            )
        except DataPlatformUnavailable:
            progress("DATAHUB", "FAILED")
            return self._responses.error(
                context, machine, trace, PipelineStage.CONTEXT,
                AnalysisStatus.FAILED, ErrorCode.QUERY_SOURCE_FAILED,
                "DataHub 검색 상태를 확인할 수 없습니다.", decision,
                retryable=True,
            )
        except DataPlatformNoAssets:
            progress("DATAHUB", "BLOCKED")
            return self._responses.error(
                context, machine, trace, PipelineStage.CONTEXT,
                AnalysisStatus.BLOCKED, ErrorCode.INSUFFICIENT_EVIDENCE,
                "질문과 일치하는 검색 가능한 Dataset이 없습니다.", decision,
            )
        progress("DATAHUB", "PASSED")
        if decision.route_type is RouteType.TEMPLATE:
            assets = [
                item for item in assets if item.get("fqn") in decision.source_fqns
            ]
        progress("NODE1", "STARTED")
        try:
            node1 = self._call_model(
                budget,
                "node1",
                self._support.node1_request(payload, context, assets),
                context,
            )
        except (TimeoutError, TypeError, ValueError):
            progress("NODE1", "FAILED")
            return self._responses.model_error(context, machine, trace, decision)
        progress("NODE1", "PASSED")
        try:
            with observe_stage(
                "context",
                context=context,
                attributes={
                    "answervice.context.operation": "package_build",
                    "answervice.asset_count": len(assets),
                },
            ) as span:
                assets, normalized_question = self._support.select_metric(
                    payload, context, assets, node1
                )
                package = self._support.build_context(
                    payload,
                    context,
                    assets,
                    decision.route_type.value,
                    decision.template_id,
                )
                span.set_attribute(
                    "answervice.context_package_hash", package.package_hash
                )
        except ContextBuildError as error:
            message = (
                "요청 시점에 유효한 PUBLISHED Context release가 없습니다."
                if error.code is ContextBuildErrorCode.INACTIVE_RELEASE
                else "질문에서 권한이 있는 승인 지표 하나를 선택해 주세요."
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
            )
        self._responses.record(trace, PipelineStage.CONTEXT, package.package_hash)

        scenario = str(payload.parameters.get("scenario") or "")
        progress("G1", "STARTED")
        g1_error = self._support.g1_error(
            package,
            payload,
            context,
            decision.route_type.value,
            decision.template_id,
        )
        if g1_error:
            progress("G1", "BLOCKED")
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
        progress("G1", "PASSED")

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
            "role": context.role.value,
            "access_profile": getattr(package, "access_profile", "default"),
            "allowed_domains": getattr(package, "allowed_domains", ()),
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
        if plan is not None:
            progress("NODE2", "SKIPPED")
        elif decision.sql_text:
            progress("NODE2", "SKIPPED")
            plan = {
                "sql": decision.sql_text,
                "references": [
                    item
                    for item in references
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
            progress("NODE2", "STARTED")
            try:
                plan = self._call_model(
                    budget,
                    "node2",
                    {
                        "scenario": scenario,
                        "question": normalized_question,
                        "references": references,
                        "request_id": str(context.request_id),
                        "package": package,
                        "context": context,
                    },
                    context,
                )
            except (TimeoutError, TypeError, ValueError):
                progress("NODE2", "FAILED")
                return self._responses.model_error(context, machine, trace, decision)
            progress("NODE2", "PASSED")
        if self._support.model_plan_violation(plan):
            if not plan_cached and not decision.sql_text:
                progress("NODE2", "FAILED")
            return self._responses.model_error(context, machine, trace, decision)
        self._responses.record(
            trace,
            PipelineStage.MODEL,
            f"{plan.get('model_version')};plan_cache={'hit' if plan_cached else 'miss'}",
        )

        repair_count = 0
        progress("G2", "STARTED")
        violation = self._support.g2_violation(plan, package)
        if violation == "UNSAFE_SQL":
            progress("G2", "BLOCKED")
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
            progress("G2", "BLOCKED")
            self._responses.record(
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
                plan = self._call_model(
                    budget,
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
                    context,
                )
            except (TimeoutError, TypeError, ValueError):
                progress("NODE2", "FAILED")
                return self._responses.model_error(
                    context,
                    machine,
                    trace,
                    decision,
                    repair_count,
                )
            self._responses.record(trace, PipelineStage.REPAIR, "attempt=1")
            progress("G2", "STARTED")
            if (
                self._support.model_plan_violation(plan)
                or self._support.g2_violation(plan, package)
            ):
                progress("G2", "BLOCKED")
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
        progress("G2", "PASSED")

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
        progress("TRINO", "SKIPPED" if result_cached else "STARTED")
        try:
            with observe_stage(
                "trino",
                context=context,
                attributes={"answervice.cache_hit": result_cached},
            ) as span:
                if cached_query is None:
                    query = self._adapter.execute_query(
                        plan["sql"],
                        plan.get("parameters", {}),
                        gate_token,
                        getattr(package, "trino_principal", None),
                    )
                    query = self._adapter.get_query_status(query["query_id"])
                else:
                    query = cached_query
                span.set_attribute(
                    "answervice.query_status", str(query.get("status", "unknown"))
                )
                if query.get("query_id"):
                    span.set_attribute("answervice.query_id", str(query["query_id"]))
        except (KeyError, TimeoutError, TypeError, ValueError):
            progress("TRINO", "FAILED")
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
                progress("TRINO", "FAILED")
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
            progress("TRINO", "FAILED")
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
            progress("TRINO", "FAILED")
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
            progress("TRINO", "FAILED")
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
            progress("TRINO", "FAILED")
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
        if not result_cached:
            progress("TRINO", "PASSED")

        progress("G3", "STARTED")
        g3_violation = self._support.g3_violation(query, package)
        if g3_violation:
            progress("G3", "FAILED")
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
        progress("G3", "PASSED")
        if not result_cached:
            self._cache.put_result(result_key, query)

        if decision.route_type is RouteType.TEMPLATE:
            progress("NODE3", "SKIPPED")
            explanation = {
                "summary": f"승인된 분석에서 {len(query['rows'])}건을 조회했습니다.",
                "model_version": "TEMPLATE-RESULT-v1.0.0",
            }
        else:
            progress("NODE3", "STARTED")
            try:
                explanation = self._call_model(
                    budget,
                    "node3",
                    {
                        "scenario": scenario,
                        "query": query,
                        "assets": assets,
                        "context": context,
                    },
                    context,
                )
                if (
                    not isinstance(explanation, dict)
                    or not isinstance(explanation.get("summary"), str)
                    or not isinstance(explanation.get("model_version"), str)
                ):
                    raise ValueError("invalid node3 response")
            except (TimeoutError, TypeError, ValueError):
                progress("NODE3", "FAILED")
                return self._responses.model_error(
                    context,
                    machine,
                    trace,
                    decision,
                    repair_count,
                )
            progress("NODE3", "PASSED")
        progress("ARTIFACT", "STARTED")
        with observe_stage("artifact", context=context) as span:
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
            span.set_attribute("answervice.artifact_id", str(artifact_id))
        self._responses.record(trace, PipelineStage.ARTIFACT, str(artifact_id))
        progress("ARTIFACT", "PASSED")

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
