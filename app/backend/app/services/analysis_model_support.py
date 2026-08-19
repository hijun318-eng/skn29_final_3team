"""model adapter의 예외와 호출 추적을 공개 오류·감사 형식으로 제한하고, 알 수 없는 값은 계약 위반으로 보수적으로 분류한다."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.contracts import ErrorCode
from app.ports.model import ModelAdapter


def model_failure_code(error: BaseException) -> ErrorCode:
    """모델 adapter 예외를 외부 API가 허용하는 ``ErrorCode``로 축약한다.

    예외가 유효한 문자열 ``code``를 제공하면 이를 우선 신뢰하고, 알 수 없는 값은
    timeout·endpoint 장애 타입만 구분한 뒤 계약 위반으로 닫아 내부 예외를 노출하지 않는다.
    """
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
    """adapter의 마지막 호출 추적값을 감사 로그용 단일 문자열로 직렬화한다.

    누락된 식별자는 ``unknown``으로 표시하며 prompt·schema hash와 release 정보를 함께
    남겨, 성공 응답이라도 어떤 모델 계약과 컨텍스트가 사용됐는지 역추적할 수 있게 한다.
    """
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
    """numeric 조건 충족 여부를 typed boolean 값으로 판정한다."""
    if isinstance(value, bool) or value is None:
        return False
    try:
        Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return True


_model_failure_code = model_failure_code
_model_trace_detail = model_trace_detail
