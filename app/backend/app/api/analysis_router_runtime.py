"""분석 endpoint가 사용할 DB router·DataHub/Trino·모델·owner repository 운영 의존성을 조립한다."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.contracts import RequestContext
from app.services.routing_service import RoutingService
from app.services.analysis.sql_generation_mode import (
    SqlGenerationMode,
    configured_sql_generation_mode,
)
from src.modelops.runtime_config import (
    active_route_for_node,
    resolve_active_model_routes,
)


def routing_service() -> RoutingService:
    """DB가 구성되면 승인 template 저장소를 쓰고, 없으면 일반 분석만 허용하는 라우터를 만든다."""
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if database_url:
        return RoutingService.from_database(database_url)
    return RoutingService()


def data_platform():
    """Active RuntimeCatalogProjection, DataHub Search와 TLS Trino 어댑터를 구성한다.

    Trino 사용자·비밀번호·CA가 비어 있거나 HTTPS 검증을 구성할 수 없으면 어댑터 생성이
    실패한다. 요청 catalog는 DB active pointer에서만 읽고 DataHub 전체 read-back은
    readiness parity에만 사용한다. 질문 경로는 bounded Search만 수행하며 projection 부재를
    live catalog fallback으로 숨기지 않는다.
    """
    from app.adapters.governed_data_platform import GovernedDataPlatformAdapter
    from app.adapters.runtime_catalog_repository import (
        PostgresRuntimeCatalogProjectionRepository,
    )
    from app.database import get_sessionmaker
    from src.data.analysis_capability_contract import (
        load_analysis_capability_release,
    )

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("RuntimeCatalogProjection 저장소가 구성되지 않았습니다.")
    expected_release = os.getenv("ANALYTICS_CONTEXT_RELEASE") or None
    analysis_capability = load_analysis_capability_release(
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "analysis_capability.product.v1.json",
        expected_catalog_release=expected_release,
    )
    projection_repository = PostgresRuntimeCatalogProjectionRepository(
        get_sessionmaker(database_url)
    )

    return GovernedDataPlatformAdapter(
        os.getenv("TRINO_URL", "https://trino:8443"),
        os.getenv("TRINO_RUNTIME_USER", ""),
        trino_password=os.getenv("TRINO_RUNTIME_PASSWORD", ""),
        trino_ca_file=os.getenv("TRINO_TLS_CA_FILE", "/run/secrets/trino-ca.pem"),
        expected_context_release=expected_release,
        projection_repository=projection_repository,
        analysis_capability=analysis_capability,
    )


async def active_analytics_context_release() -> str:
    """DataHub에서 활성 분석 Context release를 읽고 성공·실패와 무관하게 연결을 닫는다."""
    adapter = data_platform()
    try:
        return await adapter.get_active_context_release()
    finally:
        await adapter.aclose()


def model():
    """versioned route manifest와 환경을 결합해 실제 모델 어댑터를 선택한다.

    Node 2 route가 완전히 선언되면 전용 자격 증명을 사용하고, 전용 변수 전체가 비어
    있을 때만 primary route를 공유한다. 부분 설정·미등록 model·provider 불일치는 외부
    호출 전에 typed runtime 설정 경계에서 거부한다.
    """
    from app.adapters.contract_model import ContractModelAdapter

    routes = resolve_active_model_routes()
    primary = active_route_for_node(routes, "node1")
    if configured_sql_generation_mode() is SqlGenerationMode.COMPILER_ONLY:
        return ContractModelAdapter.from_openai(
            endpoint=primary.endpoint,
            token=primary.token,
            model=primary.model,
            timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "60")),
        )
    node2 = active_route_for_node(routes, "node2")
    if node2.route_id != primary.route_id:
        return ContractModelAdapter.from_endpoints(
            openai_endpoint=primary.endpoint,
            openai_token=primary.token,
            openai_model=primary.model,
            node2_endpoint=node2.endpoint,
            node2_token=node2.token,
            node2_model=node2.model,
            node2_provider=node2.provider,
            timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "60")),
            node2_timeout_seconds=float(
                os.getenv("NODE2_MODEL_TIMEOUT_SECONDS", "90")
            ),
        )
    return ContractModelAdapter.from_openai(
        endpoint=primary.endpoint,
        token=primary.token,
        model=primary.model,
        timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "60")),
    )


def analysis_repository(context: RequestContext):
    """인증 주체가 소유한 분석만 보이도록 owner-scoped PostgreSQL 저장소를 생성한다.

    운영 DB가 구성되지 않았으면 임시 저장소로 대체하지 않고 HTTP 503을 반환한다.
    """
    from app.adapters.analysis_repository import PostgresAnalysisRepository

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="Analysis 저장소를 사용할 수 없습니다.")
    return PostgresAnalysisRepository(database_url, context.user_id)


async def repository_call(action: Callable[[], Awaitable[Any]]) -> Any:
    """저장소의 도메인 실패를 404·409·503 HTTP 경계로 일관되게 변환한다."""
    from app.adapters.analysis_repository import AnalysisRepositoryUnavailable

    try:
        return await action()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except AnalysisRepositoryUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def conversation_orchestrator(controller: Any) -> Any:
    """public 인터페이스만 사용하여 ConversationOrchestrator를 생성한다.

    ``controller``는 ``_controller()``가 만든 process-lifetime singleton이므로,
    private 멤버를 체이닝하는 대신 ``AnalysisController.data_platform``/``support``
    public property로 같은 connection pool을 그대로 재사용한다.
    """
    from app.adapters.analysis_repository import PostgresAnalysisRepository
    from app.adapters.conversation_repository import ConversationRepository
    from app.adapters.report_repository import PostgresReportRepository
    from app.database import get_sessionmaker
    from app.services.conversation import ConversationOrchestrator

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="App Database가 구성되지 않았습니다.")

    sessionmaker = get_sessionmaker(database_url)
    repo = ConversationRepository(sessionmaker)

    def _report_repo_factory(
        context: RequestContext,
        manage_all: bool = False,
    ) -> Any:
        return PostgresReportRepository(
            database_url=database_url,
            owner_id=context.user_id,
            manage_all=manage_all,
            product_release_id=context.product_release_id,
            permission_snapshot_id=context.permission_snapshot_id,
            semantic_release_id=context.semantic_release_id,
            session_factory=sessionmaker,
        )

    def _analysis_repo_factory(owner_id: Any) -> Any:
        return PostgresAnalysisRepository(
            database_url=database_url,
            owner_id=owner_id,
            session_factory=sessionmaker,
        )

    return ConversationOrchestrator(
        repository=repo,
        data_platform=controller.data_platform,
        support=controller.support,
        submit_analysis=controller.submit,
        report_repository_factory=_report_repo_factory,
        analysis_repository_factory=_analysis_repo_factory,
    )
