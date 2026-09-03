"""멀티턴 대화 슬롯의 턴별 변경분을 관리하는 typed ChangeSet 모듈.

[핵심 설계 원칙]
1. 결정론적 상태 전이: LLM(Node 1)이 생성한 비신뢰 후보 데이터를 대화 상태(`ResolvedSlots`)에
   무조건 덮어쓰지 않고, 사전에 정의된 5대 연산(SET, CLEAR, ADD_VALUE, REMOVE_VALUE, PRESERVE)으로만
   상태를 전이시킵니다. 이를 통해 임의의 JSON Patch가 전체 상태를 오염시키는 문제를 원천 차단합니다.
2. 단일 값 슬롯 vs 다중 값 슬롯:
   - 단일 값 슬롯 (`metric_id` 등): SET(새 값 설정), CLEAR(초기화), PRESERVE(이전 턴 값 유지)
   - 다중 값 슬롯 (`dimension_fields`, `user_filters` 등): ADD_VALUE(원소 추가), REMOVE_VALUE(원소 제거),
     SET(전체 교체), PRESERVE(전체 유지), CLEAR(전체 비우기)
3. 순수 함수 기반: 외부 상태나 데이터베이스 의존성 없이 순수 입력값만으로 결정론적인 연산 결과를 산출합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ChangeOperation(str, Enum):
    """슬롯의 개별 필드에 적용 가능한 5가지 결정론적 상태 전이 연산."""

    SET = "SET"  # 새로운 값으로 완전히 교체
    CLEAR = "CLEAR"  # 슬롯 값을 비움 (None 또는 빈 튜플)
    ADD_VALUE = "ADD_VALUE"  # 다중 값 슬롯에 새 원소 추가
    REMOVE_VALUE = "REMOVE_VALUE"  # 다중 값 슬롯에서 특정 원소 제거
    PRESERVE = "PRESERVE"  # 이전 턴의 슬롯 값을 그대로 유지(상속)


@dataclass(frozen=True)
class SlotChange:
    """단일 슬롯 필드에 대한 변경 연산과 해당 값을 나타내는 불변 데이터 클래스.

    Attributes:
        field: 변경 대상 슬롯 이름 (예: 'metric_id', 'dimension_fields', 'user_filters')
        op: 적용할 변경 연산 (ChangeOperation)
        value: 연산에 수반되는 값 (SET/ADD_VALUE/REMOVE_VALUE/PRESERVE 시 사용)
    """

    field: str
    op: ChangeOperation
    value: Any = None


# 여러 슬롯 필드의 변경 연산 묶음을 나타내는 타입 별칭
AnalysisChangeSet = tuple[SlotChange, ...]


def _dimension_key(dimension: dict[str, Any]) -> tuple[str, str, str, str]:
    """차원 또는 필터 딕셔너리의 고유 식별 키를 생성하는 내부 헬퍼 함수.

    Args:
        dimension: 자산 FQN, 컬럼명, 연산자, 비교값을 담은 딕셔너리

    Returns:
        (asset_fqn, column, operator, value_text) 형태의 고유 튜플
    """
    return (
        str(dimension.get("asset_fqn", "")),
        str(dimension.get("column", "")),
        str(dimension.get("operator", "")),
        str(dimension.get("value_text", "")),
    )


def derive_metric_change(
    candidate_metric: str | None,
    is_followup: bool,
    inherited_metric_id: str | None,
) -> SlotChange:
    """[책임] 사용자 발화의 지표 후보와 이전 대화 컨텍스트를 대조하여 metric_id의 변경 연산을 도출한다.
    - 입출력: candidate_metric, is_followup, inherited_metric_id 수신 → SET / PRESERVE / CLEAR 연산의 SlotChange 반환
    - 주의조건: 새 지표가 없고 후속 질의가 아니면 CLEAR 연산으로 도출하여 이전 턴의 지표 오염을 방지
    """
    if candidate_metric:
        return SlotChange("metric_id", ChangeOperation.SET, candidate_metric)
    if is_followup and inherited_metric_id:
        return SlotChange("metric_id", ChangeOperation.PRESERVE, inherited_metric_id)
    return SlotChange("metric_id", ChangeOperation.CLEAR, None)


def apply_metric_change(change: SlotChange) -> tuple[str | None, bool]:
    """[책임] 도출된 metric_id SlotChange 연산을 평가하여 이번 턴의 최종 지표 ID와 상속 여부를 확정한다.
    - 입출력: SlotChange 객체 수신 → (최종 지표 ID 문자열 | None, 상속 여부 boolean) 튜플 반환
    - 주의조건: 단일 값 슬롯에 다중 값 연산(ADD_VALUE, REMOVE_VALUE)이 인입될 경우 ValueError 발생
    """
    if change.op in (ChangeOperation.SET, ChangeOperation.CLEAR):
        return change.value, False
    if change.op is ChangeOperation.PRESERVE:
        return change.value, True
    raise ValueError(f"metric_id는 {change.op} 연산을 지원하지 않습니다.")


def derive_dimension_changes(
    candidate_dims: tuple[dict[str, Any], ...],
    inherited_dims: tuple[dict[str, Any], ...],
    is_followup: bool,
    field: str = "dimension_fields",
) -> AnalysisChangeSet:
    """[책임] 다중 값 슬롯(차원 또는 필터)의 새 후보와 이전 집합을 대조하여 변경분 AnalysisChangeSet을 도출한다.
    - 입출력: candidate_dims, inherited_dims, is_followup, field 수신 → ADD_VALUE, REMOVE_VALUE, SET 튜플 반환
    - 주의조건: 새 후보와 이전 집합의 포함 관계(Superset/Subset)를 엄격히 비교하여 부분 갱신과 전체 교체를 구분
    """
    if candidate_dims:
        candidate_keys = {_dimension_key(d): d for d in candidate_dims}
        inherited_keys = {_dimension_key(d): d for d in inherited_dims} if is_followup else {}

        # 1. 원소 추가 감지 (기존 항목 포함 + 새 항목 추가)
        if inherited_keys and inherited_keys.keys() < candidate_keys.keys():
            added = [d for key, d in candidate_keys.items() if key not in inherited_keys]
            return tuple(SlotChange(field, ChangeOperation.ADD_VALUE, d) for d in added)

        # 2. 원소 제거 감지 (기존 항목 중 일부만 유지)
        if candidate_keys.keys() < inherited_keys.keys():
            removed = [d for key, d in inherited_keys.items() if key not in candidate_keys]
            return tuple(SlotChange(field, ChangeOperation.REMOVE_VALUE, d) for d in removed)

        # 3. 전체 교체
        return (SlotChange(field, ChangeOperation.SET, tuple(candidate_dims)),)

    # 4. 후속 질의 상속 유지
    if is_followup and inherited_dims:
        return (SlotChange(field, ChangeOperation.PRESERVE, tuple(inherited_dims)),)

    # 5. 기존 항목 초기화
    if inherited_dims:
        return (SlotChange(field, ChangeOperation.CLEAR, None),)

    return ()


def apply_dimension_changes(
    changes: AnalysisChangeSet,
    inherited_dims: tuple[dict[str, Any], ...],
    field: str = "dimension_fields",
) -> tuple[tuple[dict[str, Any], ...], bool]:
    """[책임] 슬롯 변경 연산 목록(AnalysisChangeSet)을 순차 적용하여 최종 차원/필터 집합을 결정론적으로 계산한다.
    - 입출력: changes 튜플, inherited_dims, field 수신 → (최종 차원/필터 튜플, 상속 여부 boolean) 반환
    - 주의조건: 지정된 field와 일치하지 않는 다른 필드의 SlotChange가 혼입된 경우 ValueError 발생
    """
    if not changes:
        return (), False

    current = {_dimension_key(d): d for d in inherited_dims}
    inherited = False

    for change in changes:
        if change.field != field:
            raise ValueError(f"{field} 적용기가 다른 필드 변경을 받았습니다: {change.field}")

        # 전체 설정: 이전 값을 버리고 새 값만 사용
        if change.op is ChangeOperation.SET:
            return tuple(change.value), False

        # 전체 보존: 이전 값을 그대로 사용
        if change.op is ChangeOperation.PRESERVE:
            return tuple(change.value), True

        # 전체 초기화
        if change.op is ChangeOperation.CLEAR:
            return (), False

        # 개별 원소 추가: 기존 상속 상태 유지
        if change.op is ChangeOperation.ADD_VALUE:
            current[_dimension_key(change.value)] = change.value
            inherited = True

        # 개별 원소 제거: 기존 상속 상태 유지
        elif change.op is ChangeOperation.REMOVE_VALUE:
            current.pop(_dimension_key(change.value), None)
            inherited = True

    return tuple(current.values()), inherited
