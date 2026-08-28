"""DataHub 메타데이터 기반의 차원 필터 후보(Filter Candidate) 해석 및 유효성 검증 모듈.

[핵심 목적]
사용자 발화에서 LLM(Node 1)이 추출한 필터 후보(`filter_candidates`) 또는 이전 턴에서 상속된 필터가
DataHub에 등록된 승인 차원(Dimension Business Terms)의 자산 및 컬럼 계약 범위 내에 존재하는지 사전 검증합니다.
"""

from __future__ import annotations

from typing import Any
import unicodedata

from app.services.context.builder_errors import (
    ContextBuildError,
    ContextBuildErrorCode,
)
from src.data.governance_contract import canonical_sha256

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
                "members": [
                    {
                        "id": str(member["id"]),
                        "term_urn": str(member["urn"]),
                        "canonical_value": str(member["canonical_value"]),
                        "aliases": list(map(str, member["aliases"])),
                        "version": str(member["version"]),
                        "semantic_sha256": canonical_sha256(
                            {
                                "dimension_id": identifier,
                                "asset_fqn": str(
                                    dimension.get("asset_fqn")
                                    or asset.get("fqn")
                                    or ""
                                ),
                                "column": str(
                                    dimension.get("column")
                                    or dimension.get("field")
                                    or ""
                                ),
                                **member,
                            }
                        ),
                    }
                    for member in dimension.get("members", ())
                    if isinstance(member, dict)
                ],
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
        canonical_value = value_text.strip()
        members = dimension_terms[dimension_id].get("members")
        if isinstance(members, list) and members:
            member = _member_for_text(canonical_value, members)
            if member is None:
                dimension_label = str(
                    next(
                        iter(dimension_terms[dimension_id].get("aliases", ())),
                        dimension_id,
                    )
                )
                approved_values = tuple(
                    dict.fromkeys(str(item["canonical_value"]) for item in members)
                )
                raise ContextBuildError(
                    ContextBuildErrorCode.FILTER_VALUE_NOT_FOUND,
                    (
                        f"요청한 {dimension_label} 값은 현재 승인된 값과 일치하지 않습니다. "
                        f"승인된 값: {', '.join(approved_values)}."
                    ),
                )
            canonical_value = str(member["canonical_value"])
        resolved.append(
            {
                "asset_fqn": str(field["asset_fqn"]),
                "column": str(field["column"]),
                "operator": "neq" if exclude else "eq",
                "value_text": canonical_value,
            }
        )
    return resolved


def dimension_member_receipts(
    filter_fields: list[dict[str, str]],
    dimension_terms: dict[str, dict[str, object]],
) -> list[dict[str, str]]:
    """승인 member로 해석된 filter만 immutable Context receipt로 투영한다."""

    by_field = {
        (
            str(term.get("field", {}).get("asset_fqn")),
            str(term.get("field", {}).get("column")),
        ): (dimension_id, term)
        for dimension_id, term in dimension_terms.items()
        if isinstance(term.get("field"), dict)
    }
    receipts = []
    for item in filter_fields:
        matched = by_field.get((item["asset_fqn"], item["column"]))
        if matched is None:
            continue
        dimension_id, term = matched
        members = term.get("members")
        if not isinstance(members, list) or not members:
            continue
        member = _member_for_text(item["value_text"], members)
        if member is None:
            raise ValueError(
                "승인 Dimension Member receipt와 필터 값이 일치하지 않습니다."
            )
        receipts.append(
            {
                "dimension_id": dimension_id,
                "member_id": str(member["id"]),
                "term_urn": str(member["term_urn"]),
                "canonical_value": str(member["canonical_value"]),
                "version": str(member["version"]),
                "semantic_sha256": str(member["semantic_sha256"]),
                "asset_fqn": item["asset_fqn"],
                "column": item["column"],
            }
        )
    return receipts


def _member_for_text(
    value: str,
    members: list[dict[str, object]],
) -> dict[str, object] | None:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    matches = [
        member
        for member in members
        if normalized
        in {
            unicodedata.normalize("NFKC", str(alias)).casefold().strip()
            for alias in member.get("aliases", ())
        }
    ]
    if len(matches) > 1:
        raise ValueError("Dimension Member alias가 중복되어 단일 값으로 해석되지 않습니다.")
    return matches[0] if matches else None
