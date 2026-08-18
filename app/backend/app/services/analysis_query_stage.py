"""G2가 승인한 실행 SQL과 capability만 adapter에 전달하고, 원격 취소·terminal 상태·G3 결과 증거가 확인된 query만 격리 cache에 저장한다."""

from __future__ import annotations

from typing import Any, cast

from app.contracts import (
    AnalysisResponse,
    AnalysisStatus,
    ErrorCode,
    PipelineStage,
    StageOutcome,
)
from app.ports.data_platform import DataPlatformAdapter, UnsupportedSemanticError
from app.services.analysis_pipeline_state import AnalysisPipelineState
from app.services.analysis_responses import AnalysisResponseFactory
from app.services.context_builder import ContextPackage
from app.services.execution_control import IsolatedExecutionCache, secure_cache_key
from app.services.pipeline_support import PipelineSupport


class AnalysisQueryStage:
    """AnalysisQueryStage는 분석 쿼리 단계 단계의 입력, 상태 전이, 다음 처리 결과를 조정한다."""
    def __init__(
        self,
        adapter: DataPlatformAdapter,
        support: PipelineSupport,
        responses: AnalysisResponseFactory,
        cache: IsolatedExecutionCache,
    ) -> None:
        self._adapter = adapter
        self._support = support
        self._responses = responses
        self._cache = cache

    async def run(self, state: AnalysisPipelineState) -> AnalysisResponse | None:
        """G2가 만든 실행 SQL과 capability로 Trino를 호출하고 결과 증거를 G3에서 검증한다.

        동일 context·policy·watermark key의 cache만 재사용하며 timeout이면 원격 취소 종단 상태까지
        확인한다. 연결·정책·schema·masking 위반은 typed 응답으로 닫고, 검증 완료 결과만 cache와
        ``state``에 기록한 뒤 ``None``을 반환한다.
        """
        package = cast(ContextPackage, state.package)
        plan = cast(dict[str, Any], state.plan)
        context = state.context
        decision = state.decision
        repair_count = state.repair_count
        executable_sql = plan.get("executable_sql")
        if not isinstance(executable_sql, str) or not executable_sql:
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.G2,
                AnalysisStatus.BLOCKED,
                ErrorCode.SQL_POLICY_BLOCKED,
                "실행 가능한 SQL 안전성 증거가 없습니다.",
                decision,
                repair_count,
            )
        gate_token = self._support.gate_token(package, executable_sql)
        result_key = secure_cache_key(
            "query-result",
            sql=executable_sql,
            **state.common_key,
        )
        cached_query = self._cache.get_result(result_key)
        result_cached = cached_query is not None
        try:
            if cached_query is None:
                bind_cancellation = getattr(self._adapter, "bind_cancellation", None)
                if bind_cancellation is not None:
                    bind_cancellation(state.cancel_check)
                try:
                    query = await self._adapter.execute_query(
                        executable_sql,
                        {},
                        gate_token,
                    )
                finally:
                    if bind_cancellation is not None:
                        bind_cancellation(None)
                query = await self._adapter.get_query_status(query["query_id"])
            else:
                query = cached_query
        except UnsupportedSemanticError as error:
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.QUERY,
                AnalysisStatus.BLOCKED,
                ErrorCode.SQL_POLICY_BLOCKED,
                str(error),
                decision,
                repair_count,
                detail=str(error),
            )
        except TimeoutError:
            return self._responses.error(
                context,
                state.machine,
                state.trace,
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
                state.machine,
                state.trace,
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
                state.machine,
                state.trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "원천 조회 상태를 확인할 수 없습니다.",
                decision,
                repair_count,
                retryable=True,
            )

        query_id = str(query.get("query_id", ""))
        state.record(PipelineStage.QUERY, query_id)
        query_status = query.get("status")
        if query_status == "TIMEOUT":
            try:
                terminal = await self._adapter.cancel_query(query_id)
            except (KeyError, TimeoutError, TypeError, ValueError):
                terminal = {}
            if terminal.get("status") != "CANCELLED":
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.QUERY,
                    AnalysisStatus.FAILED,
                    ErrorCode.QUERY_TIMEOUT,
                    "시간 초과 조회의 종료 상태를 확인할 수 없습니다.",
                    decision,
                    repair_count,
                )
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_TIMEOUT,
                "조회 시간이 초과되어 취소했습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        if query_status == "CANCELLED":
            if state.progress_sink is not None:
                state.progress_sink(PipelineStage.QUERY, StageOutcome.FAILED)
            return self._responses.error(
                context,
                state.machine,
                state.trace,
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
                state.machine,
                state.trace,
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
                state.machine,
                state.trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.QUERY_SOURCE_FAILED,
                "원천 조회가 정상 종료 상태가 아닙니다.",
                decision,
                repair_count,
                retryable=True,
            )
        query = dict(query)
        query.update(self._support.execution_evidence(package))
        cancelled = state.cancelled(PipelineStage.QUERY)
        if cancelled is not None:
            return cancelled

        query = self._support.normalize_empty_aggregate(query, package)
        g3_violation = self._support.g3_violation(query, plan, package)
        if g3_violation:
            error_code = (
                ErrorCode.RESULT_EVIDENCE_MISSING
                if g3_violation == "EVIDENCE_INCOMPLETE"
                else ErrorCode.RESULT_VALIDATION_FAILED
            )
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.G3,
                AnalysisStatus.FAILED,
                error_code,
                "근거 또는 결과 범위가 유효하지 않아 Artifact를 생성하지 않았습니다.",
                decision,
                repair_count,
                detail=g3_violation,
            )
        state.record(PipelineStage.G3)
        cancelled = state.cancelled(PipelineStage.G3)
        if cancelled is not None:
            return cancelled
        if not result_cached:
            self._cache.put_result(result_key, query)

        state.result_key = result_key
        state.query = query
        state.result_cached = result_cached
        return None
