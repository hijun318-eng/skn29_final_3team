"""분석 저장 전 UUID 정규화, 질문 PII 마스킹, canonical hash와 parameter type 추출을 제공한다."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\d[ -]?){9,12}(?!\d)")


def _uuid(value: str | UUID, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{field}는 UUID 형식이어야 합니다.") from error


def _redact_question(question: str) -> str:
    return _PHONE.sub("[REDACTED_PHONE]", _EMAIL.sub("[REDACTED_EMAIL]", question)).strip()


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parameter_types(parameters: dict[str, object]) -> dict[str, str]:
    types = {}
    for name, value in parameters.items():
        if value is None:
            types[name] = "null"
        elif isinstance(value, bool):
            types[name] = "boolean"
        elif isinstance(value, (int, float)):
            types[name] = "number"
        else:
            types[name] = "string"
    return types


class AnalysisRepositoryUnavailable(RuntimeError):
    """PostgreSQL 연결·transaction 실패로 분석 영속성을 보장할 수 없음을 알린다."""
    pass
