"""Framework 독립 API 계약 모듈.

AIC v2.0(API·AI 통합 계약) §2의 공통 응답 envelope, §13의 오류 코드,
그리고 페이지네이션 파라미터를 Pydantic v2로 정의한다.
모든 프레임워크(Django, FastAPI 등)가 공유하는 계약 계층이다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md (AIC v2.0)
    - docs/markdown/ai_docs/common_project_specification.md (CPS v2.0 §9)
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ErrorCode 상수 — AIC v2.0 §13 오류 코드 매핑
# ---------------------------------------------------------------------------

class ErrorCode:
    """10개 표준 오류 코드 상수.

    각 상수값은 AIC v2.0 §13의 code 필드 값이다.
    ErrorDetail.code는 이 값 중 하나를 사용한다.

    Attributes:
        E_AUTH: 인증 필요 (HTTP 401)
        E_SCOPE: 권한 범위 위반 (HTTP 403)
        E_NOTFOUND: 리소스 미존재 (HTTP 404)
        E_VALIDATION: 요청값 검증 실패 (HTTP 400)
        E_RATELIMIT: 요청 빈도 초과 (HTTP 429)
        E_CONFLICT: 버전 충돌 (HTTP 409)
        E_INTERNAL: 내부 서버 오류 (HTTP 500)
        E_UPSTREAM: 상위 서비스 타임아웃 (HTTP 504)
        E_NODATA: 데이터 품질 실패 (HTTP 422)
        E_LLM: AI 출력 유효성 실패 (HTTP 502)
    """

    E_AUTH: ClassVar[str] = "AUTHENTICATION_REQUIRED"
    E_SCOPE: ClassVar[str] = "FORBIDDEN_SCOPE"
    E_NOTFOUND: ClassVar[str] = "NOT_FOUND"
    E_VALIDATION: ClassVar[str] = "VALIDATION_ERROR"
    E_RATELIMIT: ClassVar[str] = "RATE_LIMITED"
    E_CONFLICT: ClassVar[str] = "VERSION_CONFLICT"
    E_INTERNAL: ClassVar[str] = "INTERNAL_ERROR"
    E_UPSTREAM: ClassVar[str] = "UPSTREAM_TIMEOUT"
    E_NODATA: ClassVar[str] = "DATA_QUALITY_FAILED"
    E_LLM: ClassVar[str] = "AI_OUTPUT_INVALID"


# ---------------------------------------------------------------------------
# 응답 계약 모델
# ---------------------------------------------------------------------------

class ResponseMeta(BaseModel):
    """공통 응답 메타데이터 (8개 식별자).

    모든 API 응답 envelope에 포함되는 표준 메타 정보다.
    페이지네이션 관련 필드는 cursor 기반 페이지네이션을 지원한다.

    Attributes:
        request_id: 요청 고유 식별자 (UUID)
        timestamp: 응답 시각 (ISO-8601 UTC)
        duration_ms: 요청 처리 소요 시간(밀리초)
        api_version: API 계약 버전
        page: 현재 페이지 번호 (1부터 시작)
        limit: 페이지당 항목 수
        total: 전체 항목 수
        cursor: 다음 페이지 커서 (없으면 None)
    """

    request_id: str = Field(..., description="요청 고유 식별자 (UUID)")
    timestamp: str = Field(..., description="응답 시각 (ISO-8601 UTC)")
    duration_ms: float = Field(
        default=0.0,
        ge=0,
        description="요청 처리 소요 시간(밀리초)",
    )
    api_version: str = Field(
        default="v1",
        description="API 계약 버전",
    )
    page: int = Field(default=1, ge=1, description="현재 페이지 번호")
    limit: int = Field(default=20, ge=1, le=100, description="페이지당 항목 수")
    total: int = Field(default=0, ge=0, description="전체 항목 수")
    cursor: str | None = Field(
        default=None,
        description="다음 페이지 커서",
    )


class ErrorDetail(BaseModel):
    """API 오류 상세 정보.

    ErrorCode 상수의 값 중 하나를 code에 전달한다.

    Attributes:
        code: 오류 코드 (ErrorCode 상수 참조)
        message: 사용자에게 노출되는 한글 오류 메시지
        detail: 추가 오류 상세 (선택)
    """

    code: str = Field(..., description="오류 코드")
    message: str = Field(..., description="오류 메시지")
    detail: list[dict[str, Any]] | None = Field(
        default=None,
        description="필드별 오류 상세",
    )


class APIResponse(BaseModel):
    """공통 API 응답 envelope (AIC v2.0 §2).

    성공 시 data에 결과, error에 None.
    실패 시 data에 None, error에 오류 정보.

    Attributes:
        data: 응답 본문 (실행 결과)
        meta: 응답 메타데이터
        error: 오류 정보 (성공 시 None)
    """

    data: Any = Field(default=None, description="응답 본문")
    meta: ResponseMeta = Field(..., description="응답 메타데이터")
    error: ErrorDetail | None = Field(
        default=None,
        description="오류 정보 (성공 시 None)",
    )


# ---------------------------------------------------------------------------
# 페이지네이션
# ---------------------------------------------------------------------------

class PaginationParams(BaseModel):
    """페이지네이션 요청 파라미터.

    offset 기반(page/limit)과 cursor 기반을 모두 지원한다.
    cursor가 제공되면 page는 무시한다.

    Attributes:
        page: 페이지 번호 (1부터 시작, 기본값 1)
        limit: 페이지당 항목 수 (기본값 20, 최대 100)
        cursor: 다음 페이지 커서 (선택)
    """

    page: int = Field(default=1, ge=1, description="페이지 번호 (1부터)")
    limit: int = Field(default=20, ge=1, le=100, description="페이지당 항목 수")
    cursor: str | None = Field(default=None, description="커서 기반 페이지네이션 토큰")
