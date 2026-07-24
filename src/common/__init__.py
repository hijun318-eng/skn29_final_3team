"""SensePlace 공통 계약 모듈.

framework 독립적으로 Django, FastAPI, React 등 모든 계층이
공유하는 enum, 계약 모델, 식별자, 예외 클래스를 제공한다.

Usage::

    from src.common import enums, contracts, identifiers, errors
    from src.common.enums import Role, JobStatus
    from src.common.contracts import APIResponse, ErrorCode
    from src.common.identifiers import make_voc_id
    from src.common.errors import SensePlaceError, AuthError
"""

from src.common import contracts, enums, errors, identifiers

__all__ = [
    "contracts",
    "enums",
    "errors",
    "identifiers",
]
