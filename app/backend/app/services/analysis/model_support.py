"""LLM 모델 어댑터 호출 결과 추적, 예외 코드 매핑 및 수치 검증 헬퍼 모듈.

[핵심 목적]
1. LLM 호출 예외(TimeoutError, OSError 등)를 표준 `ErrorCode`로 결정론적 매핑
2. 모델 어댑터의 마지막 호출 메타데이터(`last_trace`)를 감사 로그용 세미콜론 구분 문자열로 직렬화
3. 결과 값의 수치형(Numeric) 판정 유틸리티 제공
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.contracts import ErrorCode
from app.ports.model import ModelAdapter


def model_failure_code(error: BaseException) -> ErrorCode:
    """LLM 모델 어댑터 실행 예외를 표준 ErrorCode로 변환합니다."""
    value = getattr(error, "code", None)
    if isinstance(value, str):
        try:
            return ErrorCode(value)
        except ValueError:
            pass
    if isinstance(error, TimeoutError):
        return ErrorCode.MODEL_TIMEOUT
    if isinstance(error, OSError):
        return ErrorCode.MODEL_ENDPOINT_UNAVAILABLE
    return ErrorCode.MODEL_CONTRACT_INVALID


def model_trace_detail(model: ModelAdapter) -> str:
    """ModelAdapter의 마지막 실행 추적 메타데이터를 단일 감사 문자열로 포맷팅합니다."""
    trace = getattr(model, "last_trace", {})
    return ";".join(
        (
            f"node={trace.get('node', 'unknown')}",
            f"model={trace.get('model_version') or 'unknown'}",
            f"prompt={trace.get('prompt_id', 'unknown')}@{trace.get('prompt_version', 'unknown')}",
            f"prompt_hash={trace.get('prompt_hash', 'unknown')}",
            f"duration_ms={trace.get('duration_ms')}",
            f"attempts={trace.get('attempts', 1)}",
            f"status={trace.get('status', 'SUCCESS')}",
            f"input_schema_hash={trace.get('input_schema_hash', 'unknown')}",
            f"output_schema_hash={trace.get('output_schema_hash', 'unknown')}",
            f"model_snapshot={trace.get('model_snapshot') or 'unknown'}",
            f"context_release={trace.get('context_release') or 'unknown'}",
            f"policy_version={trace.get('policy_version') or 'unknown'}",
            f"data_release={trace.get('data_release') or 'unknown'}",
            f"input_tokens={trace.get('input_tokens')}",
            f"output_tokens={trace.get('output_tokens')}",
        )
    )


def is_numeric(value: object) -> bool:
    """주어진 객체가 유효한 수치형(숫자) 값인지 검증합니다."""
    if isinstance(value, bool) or value is None:
        return False
    try:
        Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return True


_model_failure_code = model_failure_code
_model_trace_detail = model_trace_detail
