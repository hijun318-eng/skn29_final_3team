"""Phase 8 승인 bundle에서 Phase 9 인수 전용 multi-asset JOIN 후보를 작성한다."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from metadata_contract import validate_bundle, validate_metric_query_policy


HOTEL_ASSET = "serving.analytics_v4_3.hotel_operations_daily"
VOC_ASSET = "serving.analytics_v4_3.voc_review_detail"
PHASE9_JOIN_ID = "voc_review_to_hotel_operations_daily"
PHASE9_METRIC_IDS = frozenset(
    {
        "room_revenue",
        "occupied_room_nights",
        "available_room_nights",
        "adr",
        "occupancy_rate",
        "revpar",
        "voc_rating_points",
        "voc_average_rating_review_count",
        "voc_average_rating",
    }
)


class Phase9JoinAuthoringError(ValueError):
    """활성 release가 Phase 9의 좁은 authoring 전제와 다름을 나타낸다."""


def author_phase9_join_bundle(source_bundle: Mapping[str, Any]) -> dict[str, Any]:
    """검증된 predecessor에 한 edge와 필요한 Metric 권한만 추가한다.

    관계는 VOC review의 ``(business_date, hotel_code)`` many side와 호텔 일 집계의
    동일 복합 unique key를 연결한다. 단일 자산 질문에는 JOIN을 강제하지 않으며, 실제
    다중 자산 필드가 요청됐을 때만 실행 component가 edge를 선택한다.
    """

    validate_bundle(source_bundle)
    candidate = json.loads(
        json.dumps(
            source_bundle,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    if candidate["join_graph"] != {"edges": []}:
        raise Phase9JoinAuthoringError(
            "Phase 9 predecessor must not already contain a JOIN edge"
        )
    assets = {
        str(item["fqn"]): item for item in candidate["schema_context"]["assets"]
    }
    _validate_asset(
        assets.get(HOTEL_ASSET),
        expected_grain={"kind": "periodic", "keys": ["business_date", "hotel_code"]},
        required_columns={"business_date", "hotel_code", "room_revenue_krw"},
    )
    _validate_asset(
        assets.get(VOC_ASSET),
        expected_grain={"kind": "row", "keys": ["voc_review_id"]},
        required_columns={
            "voc_review_id",
            "business_date",
            "hotel_code",
            "rating_overall",
            "sentiment_label",
        },
    )
    _require_dimension(candidate, HOTEL_ASSET, "hotel_code")
    _add_global_dimension(
        candidate,
        identifier="voc_sentiment_label",
        aliases=["VOC sentiment", "sentiment_label", "VOC 감성"],
        definition="VOC 리뷰에 검증되어 저장된 감성 분류값",
        asset_fqn=VOC_ASSET,
        column="sentiment_label",
    )

    candidate["catalog_version"] = f"{candidate['catalog_version']}-phase9-joins.1"
    candidate["policy_version"] = f"{candidate['policy_version']}-phase9-joins.1"
    candidate["join_graph"] = {
        "edges": [
            {
                "id": PHASE9_JOIN_ID,
                "left": VOC_ASSET,
                "right": HOTEL_ASSET,
                "kind": "inner",
                "cardinality": "many_to_one",
                "equality_conditions": [
                    {
                        "left_column": "business_date",
                        "right_column": "business_date",
                    },
                    {
                        "left_column": "hotel_code",
                        "right_column": "hotel_code",
                    },
                ],
                "temporal_conditions": [],
                "preaggregation": {
                    "required": False,
                    "grain": [
                        {"asset_fqn": VOC_ASSET, "column": "business_date"}
                    ],
                    "keys": [
                        {"asset_fqn": VOC_ASSET, "column": "hotel_code"}
                    ],
                },
            }
        ]
    }

    metrics = {str(item["id"]): item for item in candidate["metric_rules"]}
    if not PHASE9_METRIC_IDS.issubset(metrics):
        raise Phase9JoinAuthoringError("Phase 9 predecessor Metric set is incomplete")
    for metric_id in PHASE9_METRIC_IDS:
        metric = metrics[metric_id]
        governance = metric.get("governance")
        join = governance.get("join") if isinstance(governance, dict) else None
        if join != {"allowed_edge_ids": [], "required": False}:
            raise Phase9JoinAuthoringError(
                f"Metric {metric_id!r} predecessor JOIN policy differs"
            )
        join["allowed_edge_ids"] = [PHASE9_JOIN_ID]
        join["required"] = False

    for metric_id in (
        "room_revenue",
        "occupied_room_nights",
        "available_room_nights",
        "adr",
        "occupancy_rate",
        "revpar",
    ):
        strategies = metrics[metric_id]["governance"].get("query_strategies")
        if strategies != ["VIEW_REUSE"]:
            raise Phase9JoinAuthoringError(
                f"Metric {metric_id!r} query strategy predecessor differs"
            )
        metrics[metric_id]["governance"]["query_strategies"] = [
            "RAW_APPROVED_DETAIL",
            "VIEW_REUSE",
        ]
    for metric_id in (
        "voc_rating_points",
        "voc_average_rating_review_count",
    ):
        _add_metric_dimension(metrics[metric_id], HOTEL_ASSET, "hotel_code")

    # Ratio governance는 두 실행 operand와 exact equality여야 한다.
    ratio_governance = metrics["voc_average_rating"]["governance"]
    for metric_id in (
        "voc_rating_points",
        "voc_average_rating_review_count",
    ):
        operand = metrics[metric_id]["governance"]
        if any(
            ratio_governance[name] != operand[name]
            for name in ("grain", "time", "join", "permission", "query_strategies")
        ):
            raise Phase9JoinAuthoringError(
                "VOC ratio and operand governance must remain identical"
            )

    validate_bundle(candidate)
    validate_metric_query_policy(candidate)
    return candidate


def _validate_asset(
    asset: object,
    *,
    expected_grain: dict[str, Any],
    required_columns: set[str],
) -> None:
    if not isinstance(asset, dict) or asset.get("grain") != expected_grain:
        raise Phase9JoinAuthoringError("Phase 9 asset grain evidence differs")
    columns = {
        str(item.get("name"))
        for item in asset.get("columns", ())
        if isinstance(item, dict)
    }
    if not required_columns.issubset(columns):
        raise Phase9JoinAuthoringError("Phase 9 asset columns are incomplete")


def _require_dimension(
    bundle: Mapping[str, Any],
    asset_fqn: str,
    column: str,
) -> None:
    matches = [
        item
        for item in bundle["dimensions"]
        if isinstance(item, dict)
        and item.get("asset_fqn") == asset_fqn
        and item.get("column") == column
    ]
    if len(matches) != 1:
        raise Phase9JoinAuthoringError(
            "Phase 9 field must resolve one governed global dimension"
        )


def _add_metric_dimension(
    metric: dict[str, Any],
    asset_fqn: str,
    column: str,
) -> None:
    dimensions = metric.get("dimensions")
    if not isinstance(dimensions, list):
        raise Phase9JoinAuthoringError("Metric dimension contract is unavailable")
    value = {"asset_fqn": asset_fqn, "column": column}
    if value not in dimensions:
        dimensions.append(value)
    dimensions.sort(key=lambda item: (item["asset_fqn"], item["column"]))


def _add_global_dimension(
    bundle: dict[str, Any],
    *,
    identifier: str,
    aliases: list[str],
    definition: str,
    asset_fqn: str,
    column: str,
) -> None:
    dimensions = bundle.get("dimensions")
    if not isinstance(dimensions, list):
        raise Phase9JoinAuthoringError("global dimension registry is unavailable")
    field_matches = [
        item
        for item in dimensions
        if isinstance(item, dict)
        and item.get("asset_fqn") == asset_fqn
        and item.get("column") == column
    ]
    if field_matches:
        if len(field_matches) != 1 or field_matches[0].get("id") != identifier:
            raise Phase9JoinAuthoringError("global dimension field is ambiguous")
        return
    if any(
        isinstance(item, dict) and item.get("id") == identifier
        for item in dimensions
    ):
        raise Phase9JoinAuthoringError("global dimension ID is already occupied")
    dimensions.append(
        {
            "id": identifier,
            "aliases": aliases,
            "definition": definition,
            "asset_fqn": asset_fqn,
            "column": column,
        }
    )
    dimensions.sort(key=lambda item: str(item["id"]))
