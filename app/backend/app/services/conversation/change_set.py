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
    """새로운 사용자 발화와 이전 턴 정보를 바탕으로 `metric_id`의 변경 연산을 도출합니다.

    [판정 로직]
    1. 사용자가 새 지표를 언급한 경우 -> SET(새 지표)
    2. 새 지표 언급이 없고 후속 질의(is_followup)이며 이전 지표가 있는 경우 -> PRESERVE(이전 지표 유지)
    3. 그 외의 경우 -> CLEAR(지표 초기화)

    Args:
        candidate_metric: 이번 턴에서 추출된 후보 지표 ID (없으면 None)
        is_followup: 이전 대화 컨텍스트를 이어가는 후속 질의 여부
        inherited_metric_id: 이전 턴에서 확정되었던 지표 ID (없으면 None)

    Returns:
        도출된 metric_id 전용 SlotChange 객체
    """
    if candidate_metric:
        return SlotChange("metric_id", ChangeOperation.SET, candidate_metric)
    if is_followup and inherited_metric_id:
        return SlotChange("metric_id", ChangeOperation.PRESERVE, inherited_metric_id)
    return SlotChange("metric_id", ChangeOperation.CLEAR, None)


def apply_metric_change(change: SlotChange) -> tuple[str | None, bool]:
    """도출된 `metric_id` SlotChange 연산을 적용하여 최종 지표 ID와 상속 여부를 반환합니다.

    Args:
        change: 적용할 SlotChange 객체

    Returns:
        tuple[최종 지표 ID (str | None), 이전 턴 상속 여부 (bool)]

    Raises:
        ValueError: metric_id에 지원되지 않는 연산(ADD_VALUE, REMOVE_VALUE 등)이 들어온 경우
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
    """다중 값 슬롯(차원 목록 또는 유저 필터)의 이전 집합과 새 후보를 비교하여 변경분(ChangeSet)을 도출합니다.

    [상세 비교 알고리즘]
    1. 새 후보가 있는 경우:
       - 이전 집합의 진상위집합(Superset)인 경우: 새로 추가된 원소만 `ADD_VALUE`로 생성 (기존 유지 명시)
       - 이전 집합의 진부분집합(Subset)인 경우: 제거된 원소만 `REMOVE_VALUE`로 생성
       - 완전히 다르거나 겹치지 않는 경우: 전체 교체인 `SET`으로 생성
    2. 새 후보가 없으나 후속 질의인 경우:
       - 이전 집합을 그대로 유지하는 `PRESERVE` 생성
    3. 그 외 이전 집합이 존재했다면:
       - 슬롯을 비우는 `CLEAR` 생성

    Args:
        candidate_dims: 이번 턴에서 추출된 차원/필터 후보 튜플
        inherited_dims: 이전 턴에서 유지되던 차원/필터 튜플
        is_followup: 후속 질의 여부
        field: 대상 슬롯 필드명 ('dimension_fields' 또는 'user_filters')

    Returns:
        도출된 SlotChange들의 불변 튜플 (AnalysisChangeSet)
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
    """다중 값 슬롯 연산 목록(ChangeSet)을 순차 적용하여 최종 차원/필터 튜플과 상속 여부를 반환합니다.

    Args:
        changes: 적용할 SlotChange 튜플
        inherited_dims: 이전 턴의 기존 차원/필터 튜플
        field: 대상 슬롯 필드명

    Returns:
        tuple[최종 차원/필터 튜플, 상속된 원소가 포함되어 있는지 여부 (bool)]

    Raises:
        ValueError: 다른 필드명의 SlotChange가 섞여 들어온 경우
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
