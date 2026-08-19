"""권한이 반영된 catalog 검색과 구조화 질의 해석으로 runtime context를 만들고, metadata·모호성 실패를 typed 분석 응답으로 닫는다."""

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
    UnsupportedSemanticError,
)
from app.ports.model import ModelAdapter
from app.services.analysis_model_support import model_failure_code, model_trace_detail
from app.services.analysis_pipeline_state import AnalysisPipelineState
from app.services.analysis_responses import AnalysisResponseFactory
from app.services.context_builder import ContextBuildError, ContextBuildErrorCode
from app.services.execution_control import secure_cache_key
from app.services.pipeline_support import PipelineSupport


logger = logging.getLogger("uvicorn.error")


class AnalysisContextStage:
    """AnalysisContextStage는 분석 컨텍스트 단계 단계의 입력, 상태 전이, 다음 처리 결과를 조정한다."""
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
        """인증 context로 승인 asset·metric·기간 계약을 발견해 파이프라인 상태에 고정한다.

        DataHub/Trino metadata와 모델의 구조화 해석은 adapter와 resolver에서만 받고, 권한 없음·
        모호성·metadata 장애를 각각 typed 응답으로 닫는다. 성공하면 package hash와 cache
        격리 차원을 ``state``에 기록하고 ``None``을 반환해 다음 stage 실행을 허용한다.
        """
        payload = state.payload
        context = state.context
        decision = state.decision
        try:
            assets = await self._adapter.search_assets(
                payload.question,
                {
                    **context.model_dump(mode="json"),
                    "template_id": decision.template_id,
                    "parameters": payload.parameters,
                },
            )
        except MetadataUnavailableError as error:
            logger.warning(
                "runtime catalog lookup failed: type=%s detail=%s",
                type(error).__name__,
                error,
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
                AnalysisStatus.FAILED,
                ErrorCode.CONTEXT_SOURCE_FAILED,
                "승인된 DataHub Business Glossary를 조회하지 못했습니다.",
                decision,
                retryable=True,
            )
        except ContextBuildError as error:
            message = (
                "질문에 시작일·종료일 또는 하나의 상대 기간을 명확히 포함해 주세요."
                if error.code is ContextBuildErrorCode.PERIOD_REQUIRED
                else "질문이 여러 지표로 해석될 수 있습니다. 분석할 기준을 선택해 주세요."
            )
            return self._responses.error(
                context,
                state.machine,
                state.trace,
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
