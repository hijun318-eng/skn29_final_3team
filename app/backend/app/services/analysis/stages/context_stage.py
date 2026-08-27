"""파이프라인 1단계: 컨텍스트 및 G1 거버넌스 검증 단계(ContextStage) 모듈.

[핵심 목적]
사용자 인증 및 세션 정보를 바탕으로:
1. DataHub 권한 자산 검색(`search_assets`)
2. Node 1을 통한 질문 정규화 및 지표/차원/기간 해석(`select_metric`)
3. `ContextPackage` 및 `RuntimeContextPackage` 불변 스냅샷 빌드
4. G1 게이트 통과 기록 및 캐시 키(`common_key`) 생성
을 수행합니다.
"""

from __future__ import annotations

import logging

from app.contracts import (
    AnalysisResponse,
    AnalysisStatus,
    ClarificationType,
    ErrorCode,
    PipelineStage,
)
from app.ports.data_platform import (
    DataPlatformAdapter,
    MetadataUnavailableError,
    NoEntitledAssetsError,
    NoMetricMatchError,
    UnsupportedSemanticError,
)
from app.ports.model import ModelAdapter
from app.services.analysis.model_support import model_failure_code, model_trace_detail
from app.services.analysis.pipeline_state import AnalysisPipelineState
from app.services.analysis.responses import AnalysisResponseFactory
from app.services.context.builder import ContextBuildError, ContextBuildErrorCode
from app.services.execution_control import secure_cache_key
from app.services.analysis.pipeline_support import PipelineSupport

logger = logging.getLogger("uvicorn.error")


class AnalysisContextStage:
    """파이프라인의 컨텍스트 빌드 및 G1 게이트 검증을 총괄하는 단계 처리기 클래스."""

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        model: ModelAdapter,
        support: PipelineSupport,
        responses: AnalysisResponseFactory,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._support = support
        self._responses = responses

    async def run(self, state: AnalysisPipelineState) -> AnalysisResponse | None:
        """컨텍스트 단계를 실행하여 state에 package와 references를 채웁니다 (실패 시 AnalysisResponse 반환)."""
        payload = state.payload
        context = state.context
        decision = state.decision

        # ConversationSlotResolver가 기간 또는 지표만 확정한 typed 요청은 DataHub 검색
        # 실패로 뭉개지 않는다. 어떤 값이 비었는지는 서버가 이미 알고 있으므로 model이나
        # 자산 검색을 다시 호출하지 않고 정확한 clarification 원인으로 닫는다.
        resolved = payload.resolved_slots
        if resolved is not None and not resolved.resolved_metric_ids:
            return self._responses.clarification_required(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                "질문에 분석할 지표를 명확히 포함해 주세요.",
                decision,
                clarification_type=ClarificationType.METRIC,
            )
        if resolved is not None and not (
            resolved.period_start and resolved.period_end_exclusive
        ):
            return self._responses.clarification_required(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                "질문에 시작일·종료일 또는 하나의 상대 기간을 명확히 포함해 주세요.",
                decision,
                clarification_type=ClarificationType.PERIOD,
            )

        # 1. 사용자 질문에 부합하는 승인된 DataHub 자산 검색
        try:
            try:
                assets = await self._adapter.search_assets(
                    payload.question,
                    {
                        **context.model_dump(mode="json"),
                        "template_id": decision.template_id,
                        "parameters": payload.parameters,
                    },
                )
            except NoEntitledAssetsError:
                if payload.resolved_slots and payload.resolved_slots.metric_id:
                    fallback_query = f"{payload.resolved_slots.metric_id} {payload.question}"
                    assets = await self._adapter.search_assets(
                        fallback_query,
                        {
                            **context.model_dump(mode="json"),
                            "template_id": decision.template_id,
                            "parameters": payload.parameters,
                        },
                    )
                else:
                    raise
        except NoMetricMatchError:
            return self._responses.clarification_required(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                "새 분석을 시작하려면 분석할 지표를 함께 입력해 주세요.",
                decision,
                clarification_type=ClarificationType.METRIC,
            )
        except MetadataUnavailableError as error:
            logger.warning(
                "runtime catalog lookup failed: type=%s detail=%s",
                type(error).__name__,
                error,
            )
            unhealthy = await self._unhealthy_sources()
            if unhealthy:
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.CONTEXT,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.SOURCE_NOT_READY,
                    f"다음 데이터 원본이 아직 준비되지 않아 분석할 수 없습니다: {', '.join(unhealthy)}.",
                    decision,
                    retryable=True,
                    detail=",".join(unhealthy),
                )
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.FAILED,
                ErrorCode.CONTEXT_SOURCE_FAILED,
                "Governed runtime metadata is unavailable.",
                decision,
                retryable=True,
            )
        except UnsupportedSemanticError as error:
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.BLOCKED,
                ErrorCode.SQL_POLICY_BLOCKED,
                str(error),
                decision,
                detail=str(error),
            )
        except NoEntitledAssetsError:
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.BLOCKED,
                ErrorCode.DATA_ASSET_NOT_FOUND,
                "호텔 데이터 분석과 관련이 없거나 분석할 지표를 찾을 수 없습니다. 분석하고자 하는 호텔 지표(객실 매출, 투숙률, 식음료, 연회, 고객 리뷰 등)와 기간을 포함하여 질문해 주세요.",
                decision,
            )
        except (TimeoutError, OSError, ValueError) as error:
            logger.warning(
                "context lookup failed: type=%s detail=%s",
                type(error).__name__,
                error,
            )
            unhealthy = await self._unhealthy_sources()
            if unhealthy:
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.CONTEXT,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.SOURCE_NOT_READY,
                    f"다음 데이터 원본이 아직 준비되지 않아 분석할 수 없습니다: {', '.join(unhealthy)}.",
                    decision,
                    retryable=True,
                    detail=",".join(unhealthy),
                )
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.FAILED,
                ErrorCode.CONTEXT_SOURCE_FAILED,
                "승인된 데이터 컨텍스트를 조회하지 못했습니다.",
                decision,
                retryable=True,
            )

        cancelled = state.cancelled(PipelineStage.CONTEXT)
        if cancelled is not None:
            return cancelled

        # 2. 지표/차원/기간 해석 및 ContextPackage 빌드
        try:
            assets, normalized_question, structured_request = (
                await self._support.select_metric(payload, context, assets)
            )
            if getattr(self._model, "last_trace", {}).get("node") == "node1":
                state.record(PipelineStage.MODEL, model_trace_detail(self._model))
            package = await self._support.build_context(
                payload,
                context,
                assets,
                structured_request,
            )
        except MetadataUnavailableError as error:
            logger.warning(
                "DataHub Metric Glossary lookup failed: type=%s detail=%s",
                type(error).__name__,
                error,
            )
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.BLOCKED,
                ErrorCode.INSUFFICIENT_CONTEXT,
                "호텔 데이터 분석과 관련이 없거나 지원되지 않는 요청입니다. 분석할 지표(객실 매출, 투숙률, 식음료, 연회, VOC 등)를 포함하여 질문해 주세요.",
                decision,
            )
        except ContextBuildError as error:
            logger.warning(
                "governed context build rejected: code=%s detail=%s",
                error.code.value,
                error,
            )
            if error.code in {
                ContextBuildErrorCode.GOVERNANCE_VERSION_UNSUPPORTED,
                ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
            }:
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.CONTEXT,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.SEMANTIC_CONTRACT_INVALID,
                    str(error),
                    decision,
                    detail=str(error),
                )
            if error.code is ContextBuildErrorCode.OUT_OF_DATA_RANGE:
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.CONTEXT,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.OUT_OF_DATA_RANGE,
                    str(error),
                    decision,
                    detail=str(error),
                )
            if error.code is ContextBuildErrorCode.FILTER_VALUE_NOT_FOUND:
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.CONTEXT,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.FILTER_VALUE_NOT_FOUND,
                    str(error),
                    decision,
                    detail=str(error),
                )
            if error.code is ContextBuildErrorCode.METRIC_NOT_AVAILABLE:
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.CONTEXT,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.METRIC_NOT_AVAILABLE,
                    str(error),
                    decision,
                    detail=str(error),
                )
            message = (
                "질문에 시작일·종료일 또는 하나의 상대 기간을 명확히 포함해 주세요."
                if error.code is ContextBuildErrorCode.PERIOD_REQUIRED
                else "질문이 여러 지표로 해석될 수 있습니다. 분석할 기준을 선택해 주세요."
            )
            clarification_type = (
                ClarificationType.PERIOD
                if error.code is ContextBuildErrorCode.PERIOD_REQUIRED
                else ClarificationType.METRIC
            )
            return self._responses.clarification_required(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                message,
                decision,
                suggestions=error.suggestions,
                disambiguation_options=getattr(error, "disambiguation_options", ()),
                clarification_type=clarification_type,
            )
        except (TimeoutError, OSError, TypeError, ValueError) as error:
            logger.warning(
                "node1 generation failed: type=%s detail=%s",
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

        # 3. Context 및 G1 완료 상태 기록
        state.assets = assets
        state.normalized_question = normalized_question
        state.structured_request = structured_request
        state.package = package
        state.record(PipelineStage.CONTEXT, package.package_hash)
        state.record(PipelineStage.G1)
        cancelled = state.cancelled(PipelineStage.G1)
        if cancelled is not None:
            return cancelled

        state.references = [
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
        state.common_key = {
            "context": package.package_hash,
            "policy": package.policy_version,
            "entitlement": package.entitlement_hash,
            "as_of": context.as_of,
            "watermark": watermark,
            "mask": mask,
        }
        return None

    async def _unhealthy_sources(self) -> tuple[str, ...]:
        """비정상 상태의 데이터 소스 목록을 조회합니다."""
        try:
            health = await self._adapter.get_source_health()
        except (TimeoutError, OSError, ValueError):
            return ()
        return tuple(
            str(item.get("source"))
            for item in health
            if isinstance(item, dict) and item.get("status") != "HEALTHY"
        )
