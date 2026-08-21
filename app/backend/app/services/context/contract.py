"""런타임 거버넌스 조인(GovernedJoin) 및 RuntimeContextPackage 계약 모듈.

[핵심 목적]
1. 거버넌스 조인 엣지(GovernedJoin) 정의: 두 자산 간의 동등 조인 조건, 시계열 유효기간 조건, 사전 집계(Preaggregation Grain) 요건을 정규화합니다.
2. RuntimeContextPackage 패키징: 기본 `ContextPackage`에 런타임 제약 계약(`runtime_contracts`), 조인 그래프(`join_graph`),
   그리고 결정론적 쿼리 전략(`query_strategy`)을 결합하고 canonical SHA-256 해시를 갱신합니다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from typing import Any

from app.services.context.builder import ContextBuildError, ContextBuildErrorCode, ContextPackage
from app.services.context.query_planner import determine_query_strategy


@dataclass(frozen=True)
class GovernedJoin:
    """DataHub 승인을 받은 두 데이터셋 간의 조인 관계를 나타내는 거버넌스 조인 엣지 클래스.

    Attributes:
        id: 조인 고유 식별자
        left: 좌측 테이블 FQN
        right: 우측 테이블 FQN
        kind: 조인 유형 ('inner', 'left', 'right', 'full')
        cardinality: 카디널리티 ('one_to_one', 'many_to_one', 'one_to_many', 'many_to_many')
        equality_conditions: 동등 조인 조건 컬럼 쌍 (left_col, right_col)
        temporal_conditions: 유효기간 조건 (event_col, valid_from, valid_to, end_exclusive)
        preaggregation_required: 사전 집계 필수 여부 (1:N 팬아웃 방지용)
        preaggregation_grain: 사전 집계 그룹화 기준 컬럼 목록
        preaggregation_keys: 사전 집계 조인 키 컬럼 목록
    """

    id: str
    left: str
    right: str
    kind: str
    cardinality: str
    equality_conditions: tuple[tuple[str, str], ...]
    temporal_conditions: tuple[tuple[str, str, str, bool], ...]
    preaggregation_required: bool
    preaggregation_grain: tuple[str, ...]
    preaggregation_keys: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        approved_assets: dict[str, frozenset[str]],
    ) -> GovernedJoin:
        """딕셔너리 매핑 데이터를 검증하여 GovernedJoin 객체를 생성합니다."""
        required = {
            "id",
            "left",
            "right",
            "kind",
            "cardinality",
            "equality_conditions",
            "temporal_conditions",
            "preaggregation",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise _invalid("런타임 join_graph 엣지 필드가 불완전하거나 알 수 없는 필드가 포함되었습니다.")
        left = str(value["left"])
        right = str(value["right"])
        equality = tuple(
            _equality(item, left, right, approved_assets)
            for item in _array(value["equality_conditions"], "equality_conditions")
        )
        temporal = tuple(
            _temporal(item, approved_assets)
            for item in _array(value["temporal_conditions"], "temporal_conditions")
        )
        preaggregation = value["preaggregation"]
        if not isinstance(preaggregation, dict) or set(preaggregation) != {
            "required",
            "grain",
            "keys",
        }:
            raise _invalid("런타임 조인 사전집계 계약이 유효하지 않습니다.")
        grain = tuple(
            _qualified_field(item, approved_assets)
            for item in _array(preaggregation["grain"], "preaggregation.grain")
        )
        keys = tuple(
            _qualified_field(item, approved_assets)
            for item in _array(preaggregation["keys"], "preaggregation.keys")
        )
        join = cls(
            id=str(value["id"]),
            left=left,
            right=right,
            kind=str(value["kind"]),
            cardinality=str(value["cardinality"]),
            equality_conditions=equality,
            temporal_conditions=temporal,
            preaggregation_required=preaggregation["required"],
            preaggregation_grain=grain,
            preaggregation_keys=keys,
        )
        if (
            not join.id
            or join.left == join.right
            or join.left not in approved_assets
            or join.right not in approved_assets
            or join.kind not in {"inner", "left", "right", "full"}
            or join.cardinality
            not in {"one_to_one", "many_to_one", "one_to_many", "many_to_many"}
            or not isinstance(join.preaggregation_required, bool)
            or not equality
            or not grain
            or not keys
        ):
            raise _invalid("런타임 join_graph 식별자 또는 의미론적 정의가 유효하지 않습니다.")
        endpoints = {join.left, join.right}
        if any(_field_asset(item) not in endpoints for pair in equality for item in pair):
            raise _invalid("조인 동등 조건이 관련 없는 자산을 참조하고 있습니다.")
        if any(
            _field_asset(item) not in endpoints
            for condition in temporal
            for item in condition[:3]
        ):
            raise _invalid("조인 시계열 조건이 관련 없는 자산을 참조하고 있습니다.")
        preaggregation_assets = {
            _field_asset(item) for item in (*grain, *keys)
        }
        if len(preaggregation_assets) != 1:
            raise _invalid("조인 사전집계 필드는 정확히 한쪽 자산에만 속해야 합니다.")
        many_endpoint = {
            "many_to_one": join.left,
            "one_to_many": join.right,
        }.get(join.cardinality)
        if (
            join.preaggregation_required
            and many_endpoint is not None
            and preaggregation_assets != {many_endpoint}
        ):
            raise _invalid("조인 사전집계는 카디널리티의 many 측 자산을 대상으로 해야 합니다.")
        return join

    def as_dict(self) -> dict[str, Any]:
        """GovernedJoin 객체를 JSON 직렬화 가능한 딕셔너리로 변환합니다."""
        return {
            "id": self.id,
            "left": self.left,
            "right": self.right,
            "kind": self.kind,
            "cardinality": self.cardinality,
            "equality_conditions": [
                {
                    "left_column": left.rsplit(".", 1)[-1],
                    "right_column": right.rsplit(".", 1)[-1],
                }
                for left, right in self.equality_conditions
            ],
            "temporal_conditions": [
                {
                    "event_field": _qualified_payload(event),
                    "validity_asset_fqn": _field_asset(valid_from),
                    "valid_from_column": valid_from.rsplit(".", 1)[-1],
                    "valid_to_column": valid_to.rsplit(".", 1)[-1],
                    "end_exclusive": end_exclusive,
                }
                for event, valid_from, valid_to, end_exclusive in self.temporal_conditions
            ],
            "preaggregation": {
                "required": self.preaggregation_required,
                "grain": [_qualified_payload(item) for item in self.preaggregation_grain],
                "keys": [_qualified_payload(item) for item in self.preaggregation_keys],
            },
        }


@dataclass(frozen=True)
class RuntimeContextPackage(ContextPackage):
    """기본 ContextPackage에 런타임 제약 계약 및 검증된 조인 그래프를 결합한 최종 실행 컨텍스트 스냅샷."""

    runtime_contracts: dict[str, Any] | None = None
    join_graph: tuple[GovernedJoin, ...] = ()
    query_strategy: str = ""


def enrich_context_package(
    package: ContextPackage,
    runtime_contracts: dict[str, Any],
    joins: tuple[GovernedJoin, ...],
) -> RuntimeContextPackage:
    """기본 ContextPackage에 runtime_contracts 및 검증된 join_graph를 결합하고 해시를 갱신합니다."""
    approved_ids = set(package.approved_join_ids)
    if {item.id for item in joins} != approved_ids:
        raise _invalid("모든 승인된 조인 ID는 1개의 완전한 런타임 join_graph 엣지를 필요로 합니다.")
    package_hash = hashlib.sha256(
        json.dumps(
            {
                "context_package_hash": package.package_hash,
                "runtime_contracts": runtime_contracts,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    values = {field.name: getattr(package, field.name) for field in fields(ContextPackage)}
    values["package_hash"] = package_hash
    return RuntimeContextPackage(
        **values,
        runtime_contracts=runtime_contracts,
        join_graph=joins,
        query_strategy=determine_query_strategy(package, runtime_contracts),
    )


def _equality(
    value: object,
    left_asset: str,
    right_asset: str,
    approved_assets: dict[str, frozenset[str]],
) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"left_column", "right_column"}:
        raise _invalid("조인 동등 조건 정의가 유효하지 않습니다.")
    return (
        _qualified_column(f"{left_asset}.{value['left_column']}", approved_assets),
        _qualified_column(f"{right_asset}.{value['right_column']}", approved_assets),
    )


def _temporal(
    value: object,
    approved_assets: dict[str, frozenset[str]],
) -> tuple[str, str, str, bool]:
    required = {
        "event_field",
        "validity_asset_fqn",
        "valid_from_column",
        "valid_to_column",
        "end_exclusive",
    }
    if not isinstance(value, dict) or set(value) != required or value["end_exclusive"] is not True:
        raise _invalid("조인 시계열 유효기간 조건 정의가 유효하지 않습니다.")
    event = _qualified_field(value["event_field"], approved_assets)
    validity = str(value["validity_asset_fqn"])
    if validity not in approved_assets:
        raise _invalid("시계열 유효기간 자산이 승인된 schema_context 범위 밖입니다.")
    start = _qualified_column(f"{validity}.{value['valid_from_column']}", approved_assets)
    end = _qualified_column(f"{validity}.{value['valid_to_column']}", approved_assets)
    return event, start, end, True


def _qualified_field(value: object, approved_assets: dict[str, frozenset[str]]) -> str:
    if not isinstance(value, dict) or set(value) != {"asset_fqn", "column"}:
        raise _invalid("수식 필드 형식이 올바르지 않습니다.")
    return _qualified_column(f"{value['asset_fqn']}.{value['column']}", approved_assets)


def _qualified_column(value: object, approved_assets: dict[str, frozenset[str]]) -> str:
    text = str(value)
    matches = [asset for asset in approved_assets if text.startswith(f"{asset}.")]
    if len(matches) != 1:
        raise _invalid("조인 필드가 승인된 schema_context 범위 밖입니다.")
    asset = matches[0]
    column = text.removeprefix(f"{asset}.")
    if column not in approved_assets[asset]:
        raise _invalid("조인 필드 컬럼이 승인된 schema_context 범위 밖입니다.")
    return text


def _qualified_payload(value: str) -> dict[str, str]:
    return {"asset_fqn": _field_asset(value), "column": value.rsplit(".", 1)[-1]}


def _field_asset(value: str) -> str:
    return value.rsplit(".", 1)[0]


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list) or len(value) > 32:
        raise _invalid(f"런타임 조인 {name} 배열 크기가 한도를 초과했습니다.")
    return value


def _invalid(message: str) -> ContextBuildError:
    return ContextBuildError(ContextBuildErrorCode.INVALID_METADATA, message)
