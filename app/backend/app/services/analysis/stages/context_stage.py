"""파이프라인 1단계: 컨텍스트 및 G1 거버넌스 검증 단계(ContextStage) 모듈.

[핵심 목적]
사용자 인증 및 세션 정보를 바탕으로:
1. DataHub 권한 후보와 active release receipt 검색(`search_asset_candidates`)
2. Node 1을 통한 질문 정규화 및 지표/차원/기간 해석(`select_metric`)
3. 선택 결과를 동일 release에서 권한·JOIN·schema 검증된 실행 subgraph로 재해결
4. `ContextPackage` 및 `RuntimeContextPackage` 불변 스냅샷 빌드
5. G1 게이트 통과 기록 및 캐시 키(`common_key`) 생성
을 수행합니다.
"""

from __future__ import annotations

import logging

from app.authorization import permission_snapshot_id
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
    ReleaseReceiptChangedError,
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

        # ConversationSlotResolver가 기간만 확정하고 지표를 찾지 못한 typed 요청은
        # DataHub 검색 실패로 뭉개지 않는다. 반대로 기간 누락은 여기서 닫지 않는다.
        # 선택 지표의 DataHub time mode가 range인지 latest_snapshot인지 확인한 뒤에만
        # MetricResolver가 기간 필요 여부를 판정할 수 있다.
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
        # 1. 사용자 질문에 부합하는 승인된 DataHub 자산 검색
        candidate_search_context = {
            **context.model_dump(mode="json"),
            "template_id": decision.template_id,
            "parameters": payload.parameters,
            "preferred_metric_ids": list(
                resolved.resolved_metric_ids if resolved is not None else ()
            ),
        }
        try:
            candidates = await self._adapter.search_asset_candidates(
                payload.question,
                candidate_search_context,
            )
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
                ErrorCode.SEMANTIC_CONTRACT_INVALID,
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
                "요청과 일치하고 접근 권한이 있는 승인 데이터 자산 또는 지표를 찾지 못했습니다. 분석할 업무 지표와 필요한 경우 기간·분해 기준을 포함해 질문해 주세요.",
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
            if (
                context.product_release_id
                not in {None, candidates.product_release_id}
                or context.semantic_release_id
                not in {None, candidates.context_release}
            ):
                raise ReleaseReceiptChangedError(
                    "candidate release differs from the pinned request receipt"
                )
            _candidate_scope, normalized_question, structured_request = (
                await self._support.select_metric(
                    payload,
                    context,
                    candidates,
                    budget=state.budget,
                )
            )
            if getattr(self._model, "last_trace", {}).get("node") == "node1":
                state.record(PipelineStage.MODEL, model_trace_detail(self._model))
            context = context.model_copy(
                update={
                    "permission_snapshot_id": (
                        context.permission_snapshot_id
                        or permission_snapshot_id(context.user_id, context.role)
                    ),
                    "product_release_id": candidates.product_release_id,
                    "semantic_release_id": candidates.context_release,
                }
            )
            state.context = context
            # Node 1 후보가 entitlement/release/period 규칙에 exact rebind되어
            # 하나의 typed request로 확정된 뒤에만 durable Run을 만든다. 이후의
            # RuntimeContextPackage/schema/G1 실패는 이미 생성된 Run의 terminal
            # 상태로 남겨야 하므로 이 경계는 asset resolution보다 앞선다.
            if state.run_admission_sink is not None:
                await state.run_admission_sink(context)
            assets = await self._support.resolve_execution_assets(
                payload,
                context,
                candidates,
                structured_request,
            )
            package = await self._support.build_context(
                payload,
                context,
                assets,
                structured_request,
            )
        except ReleaseReceiptChangedError as error:
            logger.info(
                "semantic release changed during context resolution: type=%s",
                type(error).__name__,
            )
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.FAILED,
                ErrorCode.CONTEXT_SOURCE_FAILED,
                "분석 도중 승인 데이터 카탈로그가 갱신되었습니다. 잠시 후 같은 질문을 다시 분석해 주세요.",
                decision,
                retryable=True,
            )
        except UnsupportedSemanticError as error:
            logger.info(
                "execution semantic resolution rejected: type=%s detail=%s",
                type(error).__name__,
                error,
            )
            return self._responses.error(
                context,
                state.machine,
                state.trace,
                PipelineStage.CONTEXT,
                AnalysisStatus.BLOCKED,
                ErrorCode.SEMANTIC_CONTRACT_INVALID,
                "선택한 지표와 분해 기준을 함께 실행할 수 있는 승인 관계·분석 단위 계약이 없습니다.",
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
                "요청한 지표 조합을 실행하는 데 필요한 승인 데이터 범위에 접근할 수 없습니다.",
                decision,
            )
        except MetadataUnavailableError as error:
            logger.warning(
                "execution metadata or schema validation failed: type=%s detail=%s",
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
                "분석에 필요한 승인 메타데이터와 실제 데이터 스키마를 확인하지 못했습니다. 잠시 후 다시 분석해 주세요.",
                decision,
                retryable=True,
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
            if error.code is ContextBuildErrorCode.ANALYSIS_SHAPE_REQUIRED:
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.CONTEXT,
                    AnalysisStatus.BLOCKED,
                    ErrorCode.CONTEXT_INCOMPLETE,
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

        cancelled = state.cancelled(PipelineStage.CONTEXT)
        if cancelled is not None:
            return cancelled
        if state.context_receipt_sink is not None:
            try:
                await state.context_receipt_sink(context, package)
            except Exception as error:
                logger.error(
                    "runtime context receipt persistence failed: type=%s",
                    type(error).__name__,
                    exc_info=True,
                )
                return self._responses.error(
                    context,
                    state.machine,
                    state.trace,
                    PipelineStage.CONTEXT,
                    AnalysisStatus.FAILED,
                    ErrorCode.ARTIFACT_PERSIST_FAILED,
                    "실행 Context 영수증을 저장하지 못해 데이터 조회를 시작하지 않았습니다.",
                    decision,
                    retryable=True,
                )

        # 3. Context 영수증 저장 및 G1 완료 상태 기록
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
