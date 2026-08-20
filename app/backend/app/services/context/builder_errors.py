"""Context 조립 실패를 사용자 재질의로 연결하는 typed 오류 모듈.

[핵심 목적]
권한·스키마·지표 수식 위반을 문자열 메시지가 아니라 코드와 선택지를 가진 오류로 닫아,
상위 계층이 재질의(clarification)와 차단을 구분해 처리할 수 있게 한다.
"""

from __future__ import annotations

from enum import Enum

from app.contract_core import DisambiguationOption


class ContextBuildErrorCode(str, Enum):
    """ContextPackage 빌드 실패 원인을 분류하는 에러 코드 열거형."""

    INVALID_METADATA = "INVALID_METADATA"  # 메타데이터 형식 또는 권한 오류
    DUPLICATE_ASSET = "DUPLICATE_ASSET"  # 중복 자산 URN 포함
    DATASET_LIMIT_EXCEEDED = "DATASET_LIMIT_EXCEEDED"  # 최대 데이터셋 개수 초과
    COLUMN_LIMIT_EXCEEDED = "COLUMN_LIMIT_EXCEEDED"  # 최대 컬럼 개수 초과
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"  # 토큰 예산 초과
    INVALID_METRIC = "INVALID_METRIC"  # 지표 정의 또는 수식 무결성 오류
    DUPLICATE_METRIC = "DUPLICATE_METRIC"  # 중복 지표 ID 포함
    PERIOD_REQUIRED = "PERIOD_REQUIRED"  # 필수 기간 조건 누락
    OUT_OF_DATA_RANGE = "OUT_OF_DATA_RANGE"  # 허용 데이터 범위 벗어남
    FILTER_VALUE_NOT_FOUND = "FILTER_VALUE_NOT_FOUND"  # 필터 값 조회 실패
    GOVERNANCE_VERSION_UNSUPPORTED = "GOVERNANCE_VERSION_UNSUPPORTED"
    QUERY_STRATEGY_NOT_APPROVED = "QUERY_STRATEGY_NOT_APPROVED"


class ContextBuildError(ValueError):
    """런타임 메타데이터 또는 사용자 분석 범위가 컨텍스트 계약을 생성할 수 없을 때 발생하는 예외 클래스."""

    def __init__(
        self,
        code: ContextBuildErrorCode,
        message: str,
        suggestions: tuple[str, ...] = (),
        disambiguation_options: tuple[DisambiguationOption, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.suggestions = suggestions
        self.disambiguation_options = disambiguation_options
