"""명시적인 Column 식별자 토큰만 사용해 보수적인 PII·민감도 분류를 제공한다."""

from __future__ import annotations

import re
from dataclasses import dataclass


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_IDENTITY_SUFFIXES = frozenset({"id", "no", "number", "ref"})
_PERSON_SUBJECTS = frozenset(
    {"guest", "member", "customer", "user", "person", "contact"}
)
_FREE_TEXT = frozenset(
    {"text", "title", "comment", "comments", "note", "notes", "message", "body"}
)


@dataclass(frozen=True)
class ColumnClassification:
    """추측 없이 확정된 Column PII 유형과 최소 공개 범위를 함께 보존한다."""

    pii_type: str
    sensitivity: str


def classify_column(column_name: str) -> ColumnClassification:
    """업무 대상+식별자 또는 명시적 자유문 필드만 PII로 분류한다.

    ``guest_count``나 ``facility_name``처럼 단어 일부만 겹치는 집계·마스터명은
    PII로 확대하지 않는다. 불명확한 의미 추론은 이 함수가 아니라 manifest의
    ``REVIEW_REQUIRED`` 절차가 소유한다.
    """

    if not isinstance(column_name, str) or not _IDENTIFIER.fullmatch(column_name):
        raise ValueError("Column classification requires a stable identifier")
    tokens = tuple(item for item in column_name.lower().split("_") if item)
    token_set = frozenset(tokens)
    pii_type = "NONE"
    if "email" in token_set:
        pii_type = "EMAIL"
    elif token_set & {"phone", "mobile", "telephone"}:
        pii_type = "PHONE"
    elif token_set & {"address", "zipcode", "postcode"}:
        pii_type = "ADDRESS"
    elif "name" in token_set and token_set & _PERSON_SUBJECTS:
        pii_type = "NAME"
    elif token_set & _FREE_TEXT:
        pii_type = "FREE_TEXT"
    elif token_set & {"reservation", "booking"} and token_set & _IDENTITY_SUFFIXES:
        pii_type = "RESERVATION_ID"
    elif token_set & _PERSON_SUBJECTS and token_set & _IDENTITY_SUFFIXES:
        pii_type = "CUSTOMER_ID"
    return ColumnClassification(
        pii_type=pii_type,
        sensitivity="RESTRICTED" if pii_type != "NONE" else "INTERNAL",
    )
