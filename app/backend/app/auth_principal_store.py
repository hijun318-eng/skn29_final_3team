"""인증 경계가 전달하는 최소 Principal과 공개 가능한 인증 오류를 정의한다.

사람 계정의 권위 원본은 App PostgreSQL ``security.accounts``이며 이 모듈은 username,
비밀번호 verifier, token 원문을 보관하거나 외부 파일에서 읽지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.contracts import Role


@dataclass(frozen=True)
class Principal:
    """검증된 계정의 불변 subject와 현재 허용 ``Role``만 요청 경계로 전달한다."""

    subject: UUID
    role: Role


class AuthenticationError(ValueError):
    """인증 거부(401), 권한 거부(403), 인증 저장소 장애(503)를 안전하게 전달한다."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def authentication_error(status_code: int = 401) -> AuthenticationError:
    """credential 정보를 포함하지 않는 상태별 인증 오류를 생성한다."""

    message = "인증 정보를 확인할 수 없습니다."
    if status_code == 503:
        message = "인증 서비스를 사용할 수 없습니다."
    return AuthenticationError(message, status_code)
