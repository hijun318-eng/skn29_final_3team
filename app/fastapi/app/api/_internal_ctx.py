"""공통 내부 컨텍스트 모델.

AIC v2.0 §5의 공통 내부 context를 정의한다.
Django worker가 FastAPI에 전달하는 요청별 메타 정보다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §5
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScopeSnapshot(BaseModel):
    """RBAC 스코프 스냅샷."""

    property_ids: list[str] = Field(default_factory=list)
    metric_groups: list[str] = Field(default_factory=list)
    allowed_views: list[str] = Field(default_factory=list)


class InternalContext(BaseModel):
    """Django worker → FastAPI 공통 내부 컨텍스트 (AIC §5).

    FastAPI는 client가 보낸 role·scope를 받지 않는다.
    Django가 인증 후 저장한 snapshot만 worker가 전달한다.
    """

    request_id: str = Field(..., description="요청 고유 식별자 (UUID)")
    run_id: str = Field(default="", description="분석 실행 식별자")
    job_id: str = Field(default="", description="작업 식별자")
    idempotency_key: str = Field(default="", description="멱등성 키")
    actor_id: str = Field(default="", description="행위자 식별자")
    role_code: str = Field(default="", description="행위자 역할 코드")
    scope_snapshot: ScopeSnapshot = Field(
        default_factory=ScopeSnapshot,
        description="RBAC 스코프 스냅샷",
    )
    dataset_version: str = Field(
        default="gw-synthetic-1.0.0",
        description="데이터셋 버전",
    )
    virtual_as_of_date: str = Field(
        default="2026-08-16",
        description="가상 기준일",
    )
