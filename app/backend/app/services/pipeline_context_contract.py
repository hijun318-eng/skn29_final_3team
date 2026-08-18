"""runtime join edge의 column·temporal·preaggregation 조건을 승인 schema에 대조하고, 완전한 graph와 metadata를 ContextPackage hash에 결합한다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from typing import Any

from app.services.context_builder import ContextBuildError, ContextBuildErrorCode, ContextPackage


@dataclass(frozen=True)
class GovernedJoin:
    """DataHub가 승인한 두 asset 사이의 join edge를 SQL 의미 검증용으로 정규화한다.

    endpoint, join kind·cardinality, equality·temporal 조건과 필요한 preaggregation grain/key를
    함께 보존한다. mapping이 승인 asset·column을 벗어나거나 필수 키가 다르면 생성하지 않아
    SQLGlot 검증기가 이름 유사성으로 join을 추정할 수 없게 한다.
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
        """mapping 입력을 검증해 GovernedJoin 인스턴스를 구성한다."""
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
            raise _invalid("Runtime join_graph edge fields are incomplete or unknown.")
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
            raise _invalid("Runtime join preaggregation contract is invalid.")
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
            raise _invalid("Runtime join_graph identity or semantics are invalid.")
        endpoints = {join.left, join.right}
        if any(_field_asset(item) not in endpoints for pair in equality for item in pair):
            raise _invalid("Join equality condition references an unrelated asset.")
        if any(
            _field_asset(item) not in endpoints
            for condition in temporal
            for item in condition[:3]
        ):
            raise _invalid("Join temporal condition references an unrelated asset.")
        return join

    def as_dict(self) -> dict[str, Any]:
        """GovernedJoin 값을 JSON 직렬화 가능한 dict 구조로 변환한다."""
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
    """기본 context snapshot에 원본 runtime 계약과 검증된 join graph를 결속한 Node2 입력이다.

    상속한 asset·metric·parameter·hash와 ``runtime_contracts``/``join_graph``가 한 요청에서
    함께 이동하므로 계획 생성과 G2 검증이 동일한 metadata를 사용한다. 누락된 runtime
    구조는 호출자가 임의 기본값으로 보강하지 않고 fail-closed 처리한다.
    """
    runtime_contracts: dict[str, Any] | None = None
    join_graph: tuple[GovernedJoin, ...] = ()


def enrich_context_package(
    package: ContextPackage,
    runtime_contracts: dict[str, Any],
    joins: tuple[GovernedJoin, ...],
) -> RuntimeContextPackage:
    """검증된 기본 context에 runtime 계약과 완전한 join graph를 결합한다.

    승인 join ID와 전달된 edge ID가 정확히 같지 않으면 ``ContextBuildError``로 닫는다.
    기존 package hash와 runtime metadata를 함께 다시 해시해 이후 SQL 검증이 동일 계약
    snapshot에 묶이도록 한 ``RuntimeContextPackage``를 반환한다.
    """
    approved_ids = set(package.approved_join_ids)
    if {item.id for item in joins} != approved_ids:
        raise _invalid("Every approved join ID requires one complete runtime join_graph edge.")
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
    )


def _equality(
    value: object,
    left_asset: str,
    right_asset: str,
    approved_assets: dict[str, frozenset[str]],
) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"left_column", "right_column"}:
        raise _invalid("Join equality condition is invalid.")
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
        raise _invalid("Join temporal condition is invalid.")
    event = _qualified_field(value["event_field"], approved_assets)
    validity = str(value["validity_asset_fqn"])
    if validity not in approved_assets:
        raise _invalid("Temporal validity asset is outside schema_context.")
    start = _qualified_column(f"{validity}.{value['valid_from_column']}", approved_assets)
    end = _qualified_column(f"{validity}.{value['valid_to_column']}", approved_assets)
    return event, start, end, True


def _qualified_field(value: object, approved_assets: dict[str, frozenset[str]]) -> str:
    if not isinstance(value, dict) or set(value) != {"asset_fqn", "column"}:
        raise _invalid("Qualified field is invalid.")
    return _qualified_column(f"{value['asset_fqn']}.{value['column']}", approved_assets)


def _qualified_column(value: object, approved_assets: dict[str, frozenset[str]]) -> str:
    text = str(value)
    matches = [asset for asset in approved_assets if text.startswith(f"{asset}.")]
    if len(matches) != 1:
        raise _invalid("Join field is outside schema_context.")
    asset = matches[0]
    column = text.removeprefix(f"{asset}.")
    if column not in approved_assets[asset]:
        raise _invalid("Join field column is outside schema_context.")
    return text


def _qualified_payload(value: str) -> dict[str, str]:
    return {"asset_fqn": _field_asset(value), "column": value.rsplit(".", 1)[-1]}


def _field_asset(value: str) -> str:
    return value.rsplit(".", 1)[0]


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list) or len(value) > 32:
        raise _invalid(f"Runtime join {name} must be a bounded array.")
    return value


def _invalid(message: str) -> ContextBuildError:
    return ContextBuildError(ContextBuildErrorCode.INVALID_METADATA, message)
