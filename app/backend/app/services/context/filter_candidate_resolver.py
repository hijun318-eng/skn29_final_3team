"""DataHub 메타데이터 기반의 차원 필터 후보(Filter Candidate) 해석 및 유효성 검증 모듈.

[핵심 목적]
사용자 발화에서 LLM(Node 1)이 추출한 필터 후보(`filter_candidates`) 또는 이전 턴에서 상속된 필터가
DataHub에 등록된 승인 차원(Dimension Business Terms)의 자산 및 컬럼 계약 범위 내에 존재하는지 사전 검증합니다.
"""

from __future__ import annotations

from typing import Any

# 허용된 필터 비교 연산자 (동등/부정)
_ALLOWED_OPERATORS = frozenset({"eq", "neq"})


def dimension_terms(assets: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """DataHub 자산 메타데이터로부터 비즈니스 차원 용어별 별칭 및 물리 컬럼 정의를 추출합니다.

    Args:
        assets: DataHub에서 조회된 자산 메타데이터 목록

    Returns:
        dict[dimension_id, {'kind': 'dimension', 'aliases': [...], 'field': {'asset_fqn': '...', 'column': '...'}}]
    """
    terms: dict[str, dict[str, object]] = {}
    for asset in assets:
        for dimension in asset.get("dimensions", ()):
            if not isinstance(dimension, dict):
                continue
            identifier = dimension.get("id") or dimension.get("field")
            aliases = dimension.get("aliases")
            if not isinstance(identifier, str) or not identifier:
                continue
            if not isinstance(aliases, (list, tuple)) or not aliases:
                continue
            terms[identifier] = {
                "kind": "dimension",
                "aliases": [str(alias) for alias in aliases if str(alias).strip()],
                "field": {
                    "asset_fqn": str(dimension.get("asset_fqn") or asset.get("fqn") or ""),
                    "column": str(dimension.get("column") or dimension.get("field") or ""),
                },
            }
    return terms


def validated_pre_filters(
    user_filters: tuple[dict[str, Any], ...],
    dimension_terms: dict[str, dict[str, object]],
    allowed_dimensions: set[str],
) -> list[dict[str, str]]:
    """상속 필터 전체를 현재 승인 차원에 재결속하며 부분 성공을 허용하지 않는다."""

    dim_field_keys = {
        (str(term.get("field", {}).get("asset_fqn")), str(term.get("field", {}).get("column")))
        for identifier, term in dimension_terms.items()
        if identifier in allowed_dimensions
    }
    required = {"asset_fqn", "column", "operator", "value_text"}
    resolved: list[dict[str, str]] = []
    signatures: set[tuple[str, str, str]] = set()
    for item in user_filters:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError("상속 필터는 승인된 typed predicate 형식이어야 합니다.")
        asset_fqn = str(item["asset_fqn"]).strip()
        column = str(item["column"]).strip()
        operator = str(item["operator"]).strip()
        value_text = str(item["value_text"]).strip()
        signature = (asset_fqn, column, operator)
        if (
            (asset_fqn, column) not in dim_field_keys
            or operator not in _ALLOWED_OPERATORS
            or not value_text
            or signature in signatures
        ):
            raise ValueError("상속 필터가 현재 승인 차원 predicate와 일치하지 않습니다.")
        signatures.add(signature)
        resolved.append(
            {
                "asset_fqn": asset_fqn,
                "column": column,
                "operator": operator,
                "value_text": value_text,
            }
        )
    return resolved


def resolve_filter_candidates(
    filter_candidates: object,
    allowed_dimensions: set[str],
    dimension_terms: dict[str, dict[str, object]],
) -> list[dict[str, str]]:
    """Node 1이 추출한 필터 후보(dimension_id, value_text, exclude)를 승인된 필드 형태로 변환합니다."""
    if not isinstance(filter_candidates, (list, tuple)):
        raise ValueError("Node1 filter_candidates 는 구조화된 배열이어야 합니다.")
    resolved: list[dict[str, str]] = []
    for candidate in filter_candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Node1 필터 후보 항목은 딕셔너리 객체여야 합니다.")
        dimension_id = candidate.get("dimension_id")
        value_text = candidate.get("value_text")
        exclude = candidate.get("exclude")
        if (
            not isinstance(dimension_id, str)
            or dimension_id not in allowed_dimensions
            or not isinstance(value_text, str)
            or not value_text.strip()
            or not isinstance(exclude, bool)
        ):
            raise ValueError("Node1 필터 후보가 승인되지 않은 차원 또는 잘못된 값을 참조하고 있습니다.")
        field = dimension_terms[dimension_id]["field"]
        resolved.append(
            {
                "asset_fqn": str(field["asset_fqn"]),
                "column": str(field["column"]),
                "operator": "neq" if exclude else "eq",
                "value_text": value_text.strip(),
            }
        )
    return resolved
