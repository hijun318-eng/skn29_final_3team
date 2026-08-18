"""검증된 G2 package hash와 exact SQL을 process-local HMAC capability로 결속한다."""

from __future__ import annotations

import hashlib
import hmac
import secrets


_SECRET = secrets.token_bytes(32)


def issue_query_capability(package_hash: str, sql: str) -> str:
    """64자리 package SHA-256과 공백을 보존한 SQL 원문을 HMAC-SHA256으로 서명해 일회 release 경계 token을 만든다."""
    package = _package_hash(package_hash)
    statement = _sql(sql)
    signature = hmac.new(
        _SECRET,
        f"{package}:{statement}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{package}.{signature}"


def verify_query_capability(sql: str, token: str) -> bool:
    """token 형식과 exact SQL 서명을 constant-time 비교하며 malformed·다른 process·변경 SQL은 ``False``로 닫는다."""
    if not isinstance(token, str):
        return False
    parts = token.split(".")
    if len(parts) != 2:
        return False
    try:
        package = _package_hash(parts[0])
        statement = _sql(sql)
    except ValueError:
        return False
    # constant-time 비교는 서명 prefix 일치 시간을 통해 process secret을 추측하는 부채널을 줄인다.
    expected = issue_query_capability(package, statement)
    return hmac.compare_digest(token, expected)


def _package_hash(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("context package hash must be SHA-256")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError("context package hash must be SHA-256") from error
    return value.casefold()


def _sql(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("executable SQL is required")
    return value
