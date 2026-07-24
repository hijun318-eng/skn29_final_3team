"""Framework 독립 예외 계층 모듈.

AIC v2.0 §13의 오류 코드와 대응하는 예외 클래스 계층을 정의한다.
모든 예외는 SensePlaceError를 기반으로 하며, ErrorCode 상수를
error_code 속성으로 보유한다.

예외 계층:
    SensePlaceError
    ├── AuthError          (E_AUTH, HTTP 401)
    ├── ScopeError         (E_SCOPE, HTTP 403)
    ├── NotFoundError      (E_NOTFOUND, HTTP 404)
    ├── ValidationError    (E_VALIDATION, HTTP 400)
    ├── RateLimitError     (E_RATELIMIT, HTTP 429)
    ├── ConflictError      (E_CONFLICT, HTTP 409)
    ├── InternalError      (E_INTERNAL, HTTP 500)
    ├── UpstreamError      (E_UPSTREAM, HTTP 504)
    ├── NoDataError        (E_NODATA, HTTP 422)
    └── LLMError           (E_LLM, HTTP 502)

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md (AIC v2.0 §13)
"""

from __future__ import annotations

from src.common.contracts import ErrorCode


class SensePlaceError(Exception):
    """SensePlace 플랫폼 전체 예외 기반 클래스.

    Attributes:
        error_code: ErrorCode 상수 문자열
        message: 사용자에게 노출되는 한글 오류 메시지
        detail: 추가 오류 상세 (선택)
    """

    error_code: str = ErrorCode.E_INTERNAL

    def __init__(
        self,
        message: str = "내부 오류가 발생했습니다.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, str | None]:
        """API 응답용 딕셔너리로 변환한다."""
        return {
            "code": self.error_code,
            "message": self.message,
        }


class AuthError(SensePlaceError):
    """인증 필요 오류 (AIC §13, HTTP 401).

    로그인이 필요한 요청에서 인증 정보가 누락되었을 때 발생한다.
    """

    error_code: str = ErrorCode.E_AUTH

    def __init__(
        self,
        message: str = "로그인이 필요합니다.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)


class ScopeError(SensePlaceError):
    """권한 범위 위반 오류 (AIC §13, HTTP 403).

    사용자의 역할이 요청한 리소스에 대한 접근 권한이 없을 때 발생한다.
    SQL은 실행되지 않고 허용 범위 안내가 제공된다.
    """

    error_code: str = ErrorCode.E_SCOPE

    def __init__(
        self,
        message: str = "해당 리소스에 대한 접근 권한이 없습니다.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)


class NotFoundError(SensePlaceError):
    """리소스 미존재 오류 (AIC §13, HTTP 404).

    요청한 리소스가 존재하지 않을 때 발생한다.
    권한 밖 객체도 상세를 노출하지 않는다.
    """

    error_code: str = ErrorCode.E_NOTFOUND

    def __init__(
        self,
        message: str = "요청한 리소스를 찾을 수 없습니다.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)


class ValidationError(SensePlaceError):
    """요청값 검증 실패 오류 (AIC §13, HTTP 400).

    요청 본문의 필수 필드 누락, 형식 오류 등 검증 실패 시 발생한다.
    """

    error_code: str = ErrorCode.E_VALIDATION

    def __init__(
        self,
        message: str = "요청값을 확인하세요.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)


class RateLimitError(SensePlaceError):
    """요청 빈도 초과 오류 (HTTP 429).

    클라이언트의 요청 빈도가 허용 범위를 초과했을 때 발생한다.
    """

    error_code: str = ErrorCode.E_RATELIMIT

    def __init__(
        self,
        message: str = "요청 빈도를 초과했습니다. 잠시 후 다시 시도하세요.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)


class ConflictError(SensePlaceError):
    """버전 충돌 오류 (AIC §13, HTTP 409).

    낙관적 잠금이 실패하여 최신 버전의 report·dataset 재조회가
    필요할 때 발생한다.
    """

    error_code: str = ErrorCode.E_CONFLICT

    def __init__(
        self,
        message: str = "버전 충돌이 발생했습니다. 최신 데이터를 다시 확인하세요.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)


class InternalError(SensePlaceError):
    """내부 서버 오류 (AIC §13, HTTP 500).

    예상하지 못한 내부 오류 발생 시 사용된다.
    request_id는 제공되나 내부 상세는 미노출된다.
    """

    error_code: str = ErrorCode.E_INTERNAL

    def __init__(
        self,
        message: str = "내부 오류가 발생했습니다.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)


class UpstreamError(SensePlaceError):
    """상위 서비스 타임아웃 오류 (AIC §13, HTTP 504).

    worker→FastAPI 또는 FastAPI→LLM 호출 타임아웃 시 발생한다.
    제한된 retry 후 최종 상태가 저장된다.
    """

    error_code: str = ErrorCode.E_UPSTREAM

    def __init__(
        self,
        message: str = "상위 서비스 응답 시간을 초과했습니다.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)


class NoDataError(SensePlaceError):
    """데이터 품질 실패 오류 (AIC §13, HTTP 422).

    품질 Gate 실패, 필수 bucket 누락 등으로 분석에 필요한
    데이터가 불충분할 때 발생한다.
    """

    error_code: str = ErrorCode.E_NODATA

    def __init__(
        self,
        message: str = "데이터 품질 기준을 충족하지 않습니다.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)


class LLMError(SensePlaceError):
    """AI 출력 유효성 실패 오류 (AIC §13, HTTP 502).

    LLM이 유효한 JSON을 반환하지 않았거나, 재생성에도 실패했을 때
    발생한다. 수치·trigger·evidence는 보존되고 AI 설명만 미완(PARTIAL)이다.
    """

    error_code: str = ErrorCode.E_LLM

    def __init__(
        self,
        message: str = "AI 출력 처리에 실패했습니다.",
        detail: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message=message, detail=detail)
