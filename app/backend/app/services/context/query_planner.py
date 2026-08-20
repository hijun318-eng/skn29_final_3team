"""검증된 ContextPackage의 자산 카탈로그와 Grain 기반 쿼리 실행 전략 플래너 모듈.

[핵심 목적]
자연어 질문 문구나 지표명에 의존하지 않고, 지표가 참조하는 테이블의 카탈로그 접두사(`serving` vs 원본 소스)와
DataHub에 등록된 사전 집계 단위(Grain keys)만으로 가장 비용 효율적인 3대 쿼리 전략을 결정론적으로 선택합니다.

[3대 쿼리 실행 전략]
1. VIEW_REUSE: 필요한 지표가 단 1개의 사전 집계된 `serving` 뷰에 존재할 때, 별도의 복잡한 조인 없이 뷰를 직접 재사용
2. VIEW_COMPOSE: 필요한 지표들이 여러 개의 `serving` 뷰에 분산되어 있으나 집계 Grain(예: 일자, 호텔ID)이 동일하여 안전하게 조인 합성 가능할 때
3. RAW_APPROVED_DETAIL: 원본 소스 테이블(`raw`, `dwh` 등)을 직접 집계해야 하거나, 뷰 간 Grain이 달라 원천 집계가 필수적인 경우
"""

from __future__ import annotations

from typing import Any

from app.services.context.builder import (
    ContextBuildError,
    ContextBuildErrorCode,
    ContextPackage,
)

VIEW_REUSE = "VIEW_REUSE"
VIEW_COMPOSE = "VIEW_COMPOSE"
RAW_APPROVED_DETAIL = "RAW_APPROVED_DETAIL"

_SERVED_CATALOG = "serving"


def determine_query_strategy(
    package: ContextPackage,
    runtime_contracts: dict[str, Any],
) -> str:
    """ContextPackage의 지표 및 자산 구성과 runtime_contracts를 분석하여 최적의 쿼리 전략을 결정합니다.

    [판정 알고리즘]
    1. 지표가 참조하는 물리 테이블 FQN 목록 수집 (Ratio 지표는 분자/분모 지표의 물리 테이블로 대체)
    2. 모든 참조 테이블의 카탈로그가 `serving` 접두사를 가지는지 검사:
       - `serving`이 아닌 원본 테이블이 하나라도 포함되면 -> RAW_APPROVED_DETAIL
    3. 모든 참조 asset의 Grain이 존재하고 어느 것도 원본 row Grain이 아니어야 view 경로를 허용한다.
    4. 참조 `serving` 테이블이 정확히 1개이면 -> VIEW_REUSE (단일 뷰 재사용)
    5. 참조 `serving` 테이블이 여러 개이고 모든 테이블의 Grain 키 집합이 완전히 일치하면 -> VIEW_COMPOSE (뷰 간 합성)
    6. 그 외 Grain 누락·row Grain·Grain 불일치는 -> RAW_APPROVED_DETAIL

    Args:
        package: 검증된 ContextPackage 인스턴스
        runtime_contracts: 스키마 및 자산 Grain 메타데이터 사전

    Returns:
        결정된 쿼리 전략 문자열 ('VIEW_REUSE' | 'VIEW_COMPOSE' | 'RAW_APPROVED_DETAIL')

    Raises:
        ValueError: 해결된 지표 자산이 전혀 없는 경우
    """
    metrics_by_id = {metric.id: metric for metric in package.metrics}
    asset_fqns: set[str] = set()

    for metric in package.metrics:
        if metric.aggregation.lower() == "ratio":
            for ref_id in (metric.numerator_metric_id, metric.denominator_metric_id):
                ref = metrics_by_id.get(ref_id)
                if ref is not None:
                    asset_fqns.add(ref.asset_fqn)
            continue
        asset_fqns.add(metric.asset_fqn)

    if not asset_fqns:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "쿼리 전략 결정을 위해 최소 1개 이상의 지표 참조 자산이 필요합니다.",
        )

    catalogs = {fqn.split(".", 1)[0] for fqn in asset_fqns}
    if catalogs != {_SERVED_CATALOG}:
        return _enforce_metric_strategy(package, RAW_APPROVED_DETAIL)

    grain_by_fqn = {
        item["fqn"]: {
            "kind": str(item["grain"].get("kind") or "").casefold(),
            "keys": tuple(sorted(item["grain"]["keys"])),
        }
        for item in runtime_contracts.get("schema_context", {}).get("assets", ())
        if isinstance(item, dict)
        and isinstance(item.get("fqn"), str)
        and isinstance(item.get("grain"), dict)
        and isinstance(item["grain"].get("keys"), (list, tuple))
    }
    # Grain이 없는 asset을 일부만 비교하면 서로 다른 계산 범위를 같은 grain으로
    # 오인할 수 있다. 모든 참조 asset이 검증된 grain을 제공할 때만 view 경로를 연다.
    if not asset_fqns <= set(grain_by_fqn):
        return _enforce_metric_strategy(package, RAW_APPROVED_DETAIL)

    # ``serving`` catalog에도 원본 1행 grain을 보존한 승인 detail view가 존재할 수 있다.
    # catalog 이름만 보고 사전 집계 view로 승격하지 않고 grain 의미를 우선한다.
    if any(grain_by_fqn[fqn]["kind"] == "row" for fqn in asset_fqns):
        return _enforce_metric_strategy(package, RAW_APPROVED_DETAIL)

    if len(asset_fqns) == 1:
        return _enforce_metric_strategy(package, VIEW_REUSE)

    grains = {grain_by_fqn[fqn]["keys"] for fqn in asset_fqns}
    if len(grains) == 1:
        return _enforce_metric_strategy(package, VIEW_COMPOSE)

    return _enforce_metric_strategy(package, RAW_APPROVED_DETAIL)


def _enforce_metric_strategy(package: ContextPackage, strategy: str) -> str:
    """구조적으로 계산한 전략이 모든 v2 실행 Metric의 허용 집합 안인지 확인한다."""

    governed = [metric for metric in package.metrics if metric.query_strategies]
    if any(strategy not in metric.query_strategies for metric in governed):
        raise ContextBuildError(
            ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED,
            "계산된 Query Strategy가 DataHub Metric governance 범위를 벗어났습니다.",
        )
    return strategy
