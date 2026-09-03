"""파이프라인 3단계: Trino 엔진 쿼리 실행 및 G3 거버넌스 검증 단계(QueryStage) 모듈.

[핵심 목적]
1. G2 가드를 통과한 `executable_sql`과 발급된 capability 토큰을 Trino 엔진에 전달하여 비동기 실행
2. 타임아웃/취소(Cancellation) 신호 처리 및 원격 Trino 세션 안전 종료
3. 반환된 원시 데이터에 대한 G3 거버넌스 검증(`g3_violation`) 및 빈 집계 정규화
4. 실제 query 실행 근거를 후속 영속화 경계에 전달하고 검증 완료 결과를 격리 캐시에 저장
"""

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
from app.services.analysis.pipeline_state import AnalysisPipelineState
from app.services.analysis.responses import AnalysisResponseFactory
from app.services.analysis.sql_generation_mode import plan_generation_evidence_mode
from app.services.context.builder import ContextPackage
from app.services.execution_control import IsolatedExecutionCache, secure_cache_key
from app.services.analysis.pipeline_support import PipelineSupport


class AnalysisQueryStage:
    """[책임] G2 검증된 SQL을 Trino 엔진에 비동기 전달하고 실행 결과에 대한 G3 거버넌스 검증을 총괄한다.
    - 입출력: state.plan의 SQL 및 gate_token 수신 → Trino 실행 결과 레코드를 검증하여 ResultStage로 인계
    - 주의조건: 타임아웃 초과, 사용자 취소 발생, G3 스키마 불일치/마스킹 누락 시 롤백 및 fail-closed 반환
    """

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        support: PipelineSupport,
        responses: AnalysisResponseFactory,
        cache: IsolatedExecutionCache,
    ) -> None:
        """[책임] 데이터 플랫폼 어댑터, 실행 제어 캐시 및 응답 팩토리를 주입받아 쿼리 실행 스테이지를 초기화한다.
        - 입출력: DataPlatformAdapter, PipelineSupport, AnalysisResponseFactory, IsolatedExecutionCache 수신 → 멤버 변수 설정
        - 주의조건: Trino 연결 및 격리 캐시 인스턴스가 유효해야 정상적인 쿼리 발행 및 결과 재사용이 가능함
        """
        self._adapter = adapter
        self._support = support
        self._responses = responses
        self._cache = cache

    async def run(self, state: AnalysisPipelineState) -> AnalysisResponse | None:
        """[책임] 검증된 SQL을 Trino 연합 쿼리 엔진에 발행하고 반환된 결과에 대해 G3 거버넌스를 검증한다.
        - 입출력: AnalysisPipelineState(plan, gate_token) 수신 → Trino 실행 결과 레코드를 state에 저장 후 ResultStage로 전달
        - 주의조건: 쿼리 실행 타임아웃, 취소 신호 수신, G3 스키마/단위 불일치 시 트랜잭션을 롤백하고 fail-closed 응답 반환
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
        cached_query = (
            None
            if context.require_fresh_query
            else self._cache.get_result(result_key)
        )
        result_cached = cached_query is not None

        # 1. Trino 쿼리 실행 (캐시 미스 시)
        try:
            if cached_query is None:
                bind_cancellation = getattr(self._adapter, "bind_cancellation", None)
                bind_generation_mode = getattr(
                    self._adapter,
                    "bind_query_generation_mode",
                    None,
                )
                if bind_cancellation is not None:
                    bind_cancellation(state.cancel_check)
                if bind_generation_mode is not None:
                    bind_generation_mode(plan_generation_evidence_mode(plan).value)
                try:
                    query = await self._adapter.execute_query(
                        executable_sql,
                        {},
                        gate_token,
                    )
                finally:
                    if bind_cancellation is not None:
                        bind_cancellation(None)
                    if bind_generation_mode is not None:
                        bind_generation_mode(None)
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

        # 2. 쿼리 상태별 에러 처리
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
        if query_status == "PARTIAL":
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.QUERY,
                AnalysisStatus.FAILED,
                ErrorCode.RESULT_EVIDENCE_MISSING,
                "부분 결과의 범위 근거를 확인할 수 없어 Artifact를 생성하지 않았습니다.",
                decision,
                repair_count,
                retryable=True,
            )
        if query_status != "SUCCEEDED":
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

        # 3. G3 결과 거버넌스 무결성 검증
        query = self._support.normalize_empty_aggregate(query, package)
        if state.execution_sink is not None:
            # 외부 query가 정상 종료된 시점의 실행 근거다. G3가 Artifact 생성을
            # 차단하더라도 0행·검증 실패 사실 자체는 terminal run에 남아야 한다.
            state.execution_sink(
                {
                    "plan": plan,
                    "query": query,
                    "package": package,
                    "semantic_candidate_receipt": state.semantic_candidate_receipt,
                }
            )
        g3_violation = self._support.g3_violation(query, plan, package)
        if g3_violation:
            if g3_violation == "EMPTY_RESULT":
                return self._responses.empty_result(
                    support=self._support,
                    context=context,
                    machine=state.machine,
                    trace=state.trace,
                    decision=decision,
                    package=package,
                    assets=state.assets,
                    query=query,
                    repair_count=repair_count,
                )
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
