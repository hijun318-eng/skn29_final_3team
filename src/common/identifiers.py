"""Framework 독립 식별자 생성 모듈.

DSG v2.0의 명명 규칙에 따른 결정론적 식별자 생성 함수를 제공한다.
모든 함수는 같은 입력에 대해 항상 같은 출력을 보장한다.

식별자 형식:
    - hotel_id:  HTL-{seq:03d}        (예: HTL-001)
    - voc_id:    VOC-{year:04d}-{seq:05d} (예: VOC-2026-00001)
    - incident_id: INC-{year:04d}-{seq:05d} (예: INC-2026-00001)
    - job_id:    UUID v5 (결정론적 해시 기반)

References:
    - docs/markdown/ai_docs/02_data_standard_guide.md (DSG v2.0 §3, 명의·형식)
"""

from __future__ import annotations

import uuid

# 프로젝트 고유 namespace UUID (UUID5 결정론 생성용)
_SENSEPLACE_NS = uuid.UUID("a3f8c7d1-4b2e-4a9f-8c6d-5e1f0b3a7d9c")


def make_hotel_id(seq: int) -> str:
    """호텔 식별자를 생성한다.

    Args:
        seq: 호텔 일련번호 (1 이상)

    Returns:
        HTL-{seq:03d} 형식 문자열 (예: HTL-001)

    Raises:
        ValueError: seq가 1 미만인 경우
    """
    if seq < 1:
        msg = "hotel seq는 1 이상이어야 합니다."
        raise ValueError(msg)
    return f"HTL-{seq:03d}"


def make_voc_id(year: int, seq: int) -> str:
    """VOC 식별자를 생성한다.

    Args:
        year: 생성 연도 (4자리, 예: 2026)
        seq: VOC 일련번호 (1 이상)

    Returns:
        VOC-{year:04d}-{seq:05d} 형식 문자열 (예: VOC-2026-00001)

    Raises:
        ValueError: year가 4자리가 아니거나 seq가 1 미만인 경우
    """
    if year < 1000 or year > 9999:
        msg = "year는 1000~9999 범위여야 합니다."
        raise ValueError(msg)
    if seq < 1:
        msg = "voc seq는 1 이상이어야 합니다."
        raise ValueError(msg)
    return f"VOC-{year:04d}-{seq:05d}"


def make_incident_id(year: int, seq: int) -> str:
    """Incident 식별자를 생성한다.

    Args:
        year: 생성 연도 (4자리, 예: 2026)
        seq: Incident 일련번호 (1 이상)

    Returns:
        INC-{year:04d}-{seq:05d} 형식 문자열 (예: INC-2026-00001)

    Raises:
        ValueError: year가 4자리가 아니거나 seq가 1 미만인 경우
    """
    if year < 1000 or year > 9999:
        msg = "year는 1000~9999 범위여야 합니다."
        raise ValueError(msg)
    if seq < 1:
        msg = "incident seq는 1 이상이어야 합니다."
        raise ValueError(msg)
    return f"INC-{year:04d}-{seq:05d}"


def make_job_id(key: str) -> str:
    """UUID v5 기반 결정론적 작업 식별자를 생성한다.

    같은 key를 넣으면 항상 같은 UUID가 생성된다.

    Args:
        key: 작업 고유 키 (예: dataset_version + query hash 조합)

    Returns:
        UUID v5 문자열 (예: "f47ac10b-58cc-4372-a567-0e02b2c3d479")

    Raises:
        ValueError: key가 빈 문자열인 경우
    """
    if not key:
        msg = "job key는 비어 있을 수 없습니다."
        raise ValueError(msg)
    return str(uuid.uuid5(_SENSEPLACE_NS, key))
