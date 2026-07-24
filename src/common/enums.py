"""Framework 독립 공통 Enum 정의 모듈.

DSG v2.0(데이터 표준 가이드)과 CPS v2.0(공통 명세서)의 표준값을
Python enum으로 매핑한다. 모든 도메인 모듈이 이 모듈에서 import하여
값 일관성을 보장한다.

References:
    - docs/markdown/ai_docs/02_data_standard_guide.md (DSG v2.0)
    - docs/markdown/ai_docs/common_project_specification.md (CPS v2.0)
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """시스템 역할 코드 (CPS v2.0 §7, 3역할 RBAC).

    - OPERATIONS_MANAGER: 전체 운영 집계·보고서 결정·현장 확인 가능
    - FACILITY_MANAGER: F&B·조식 범위, 담당 이슈 현장 확인 가능
    - EXTERNAL_REVIEWER: 객실·허용 요약 조회, 담당 이슈 현장 확인 가능
    """

    OPERATIONS_MANAGER = "OPERATIONS_MANAGER"
    FACILITY_MANAGER = "FACILITY_MANAGER"
    EXTERNAL_REVIEWER = "EXTERNAL_REVIEWER"


class Severity(str, Enum):
    """이슈 심각도 분류.

    Incident 분석에서 감지된 이슈의 심각도를 나타낸다.
    DSG v2.0의 sentiment 분류 체계를 차용한다.
    """

    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"


class JobStatus(str, Enum):
    """비동기 작업 상태값 (CPS v2.0 §8).

    흐름: PENDING → RUNNING → SUCCEEDED | PARTIAL | NEEDS_DATA | FAILED

    - PENDING: 작업 생성, 실행 대기
    - RUNNING: worker가 FastAPI를 호출 중
    - SUCCEEDED: 정상 완료
    - PARTIAL: LLM 실패 등으로 수치·evidence는 유지, 서술만 미완
    - NEEDS_DATA: 품질 Gate 실패, 필수 bucket 누락
    - FAILED: 치명적 오류로 작업 실패
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    NEEDS_DATA = "NEEDS_DATA"
    FAILED = "FAILED"


class SentimentLabel(str, Enum):
    """고객 감성 레이블 (DSG v2.0 fact_voc).

    fact_voc.sentiment_label에 저장되는 값.
    """

    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"


class DataSource(str, Enum):
    """데이터 출처 시스템 (DSG v2.0 §5).

    합성 데이터의 원본 시스템 유형을 나타낸다.
    """

    PMS = "PMS"
    POS = "POS"
    CRM = "CRM"
    IOT = "IoT"
    VOC = "VOC"
    REVIEW = "REVIEW"
    WEATHER = "WEATHER"


class VocCategory(str, Enum):
    """VOC 주제 분류 (DSG v2.0 fact_voc 기준).

    fact_voc.topic_code에 대응하는 범주형 값이다.
    """

    GUEST_ROOM = "객실"
    FACILITY = "시설"
    SERVICE = "서비스"
    FOOD_BEVERAGE = "식음료"
    ETC = "기타"
