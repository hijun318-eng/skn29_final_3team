"""같은 대화의 주제 전환과 복합 단일 지표 질문에 대한 슬롯 경계 회귀 테스트.

이 모듈은 새 주제가 직전 지표·분해·필터는 잘못 상속하지 않으면서 생략된 기간 문맥은
이어받는지와, 하나의 승인 지표에 여러 조건이 결합돼도 슬롯을 잃지 않는지를 검증한다.
"""

from datetime import date
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.conversation.slot_resolver import ConversationSlotResolver


def _previous_room_revenue_turn() -> dict[str, object]:
    """기간·차원·필터가 확정된 직전 객실 매출 턴을 반환한다."""

    return {
        "turn_id": "turn-room-revenue",
        "route": "ANALYSIS",
        "artifact_id": "artifact-room-revenue",
        "resolved_slots": {
            "metric_id": "room_revenue",
            "dimension_fields": [
                {"asset_fqn": "serving.room_daily", "column": "hotel_code"},
            ],
            "user_filters": [
                {
                    "asset_fqn": "serving.room_daily",
                    "column": "hotel_code",
                    "operator": "eq",
                    "value_text": "선셋",
                },
            ],
            "time_range": {
                "start": "2025-08-01",
                "end_exclusive": "2025-09-01",
                "source_text": "2025년 8월",
            },
            "target_chart_type": "BAR",
        },
    }


def _period(start: str, end_exclusive: str, source_text: str) -> list[dict[str, str]]:
    """Node 1이 확정한 반개구간 기간 후보를 만든다."""

    return [
        {
            "start": start,
            "end_exclusive": end_exclusive,
            "source_text": source_text,
        }
    ]


def test_complete_new_topic_without_period_inherits_only_the_period() -> None:
    """완결된 새 지표 질문은 지표를 바꾸되 생략된 대화 기간은 이어받는다."""

    slots = ConversationSlotResolver.resolve(
        user_message="식음 매출을 보여줘",
        node1_output={
            "selected_metric_id": "fnb_revenue",
            "metric_ids": ["fnb_revenue"],
            "is_elliptical": False,
            "requested_route": "ANALYSIS",
        },
        previous_turns=[_previous_room_revenue_turn()],
        as_of=date(2026, 8, 20),
    )

    assert slots.metric_id == "fnb_revenue"
    assert slots.dimension_fields == ()
    assert slots.user_filters == ()
    assert slots.time_range is not None
    assert slots.time_range.start == date(2025, 8, 1)
    assert slots.time_range.end_exclusive == date(2025, 9, 1)
    assert slots.source_turn_ids == ("turn-room-revenue",)
    assert slots.is_inherited_metric is False
    assert slots.is_inherited_dimension is False
    assert slots.is_inherited_period is True


def test_complete_new_topic_with_period_uses_only_new_slots() -> None:
    """새 주제가 자체 기간과 차원을 제시하면 그 슬롯만으로 분석 요청을 구성한다."""

    slots = ConversationSlotResolver.resolve(
        user_message="2025년 7월 호텔별 식음 매출을 보여줘",
        node1_output={
            "selected_metric_id": "fnb_revenue",
            "metric_ids": ["fnb_revenue"],
            "dimension_fields": [
                {"asset_fqn": "serving.fnb_daily", "column": "hotel_code"},
            ],
            "period_candidates": _period("2025-07-01", "2025-08-01", "2025년 7월"),
            "is_elliptical": False,
            "requested_route": "ANALYSIS",
        },
        previous_turns=[_previous_room_revenue_turn()],
        as_of=date(2026, 8, 20),
    )

    assert slots.metric_id == "fnb_revenue"
    assert [item["column"] for item in slots.dimension_fields] == ["hotel_code"]
    assert slots.user_filters == ()
    assert slots.time_range is not None
    assert slots.time_range.start == date(2025, 7, 1)
    assert slots.time_range.end_exclusive == date(2025, 8, 1)
    assert slots.source_turn_ids == ()


def test_repeated_topic_switches_preserve_period_without_leaking_other_slots() -> None:
    """주제 전환 횟수와 무관하게 기간만 유지하고 나머지 슬롯은 현재 턴으로 교체한다."""

    previous_turns: list[dict[str, object]] = [_previous_room_revenue_turn()]

    # 특정 업무 어휘나 몇 개의 예문에 종속되지 않도록 합성 슬롯으로 연속 전이를 검증한다.
    for index in range(12):
        metric_id = f"synthetic_metric_{index}"
        dimension_id = f"synthetic_dimension_{index}"
        filter_value = f"synthetic_filter_{index}"
        slots = ConversationSlotResolver.resolve(
            user_message=f"독립된 분석 주제 {index}",
            node1_output={
                "selected_metric_id": metric_id,
                "metric_ids": [metric_id],
                "dimension_fields": [
                    {"asset_fqn": "serving.synthetic_daily", "column": dimension_id},
                ],
                "filter_fields": [
                    {
                        "asset_fqn": "serving.synthetic_daily",
                        "column": "segment_id",
                        "operator": "eq",
                        "value_text": filter_value,
                    },
                ],
                "is_elliptical": False,
                "requested_route": "ANALYSIS",
            },
            previous_turns=previous_turns,
            as_of=date(2026, 8, 20),
        )

        assert slots.metric_id == metric_id
        assert [item["column"] for item in slots.dimension_fields] == [dimension_id]
        assert [item["value_text"] for item in slots.user_filters] == [filter_value]
        assert slots.time_range is not None
        assert slots.time_range.start == date(2025, 8, 1)
        assert slots.time_range.end_exclusive == date(2025, 9, 1)
        assert slots.is_inherited_metric is False
        assert slots.is_inherited_dimension is False
        assert slots.is_inherited_period is True

        previous_turns.append(
            {
                "turn_id": f"turn-{index}",
                "route": "ANALYSIS",
                "artifact_id": f"artifact-{index}",
                "resolved_slots": {
                    "metric_id": slots.metric_id,
                    "dimension_fields": list(slots.dimension_fields),
                    "user_filters": list(slots.user_filters),
                    "time_range": {
                        "start": slots.time_range.start.isoformat(),
                        "end_exclusive": slots.time_range.end_exclusive.isoformat(),
                        "source_text": slots.time_range.source_text,
                    },
                    "target_chart_type": slots.target_chart_type,
                },
            }
        )


def test_elliptical_followup_keeps_the_previous_measurement_and_period() -> None:
    """측정값과 기간이 생략된 진짜 후속 질문만 직전 분석을 이어 간다."""

    slots = ConversationSlotResolver.resolve(
        user_message="객실 타입별로도 보여줘",
        node1_output={
            "metric_ids": ["room_revenue"],
            "dimension_fields": [
                {"asset_fqn": "serving.room_daily", "column": "hotel_code"},
                {"asset_fqn": "serving.room_daily", "column": "room_type"},
            ],
            "is_elliptical": True,
            "requested_route": "ANALYSIS",
        },
        previous_turns=[_previous_room_revenue_turn()],
        as_of=date(2026, 8, 20),
    )

    assert slots.metric_id == "room_revenue"
    assert {item["column"] for item in slots.dimension_fields} == {"hotel_code", "room_type"}
    assert slots.time_range is not None
    assert slots.time_range.start == date(2025, 8, 1)
    assert slots.source_turn_ids == ("turn-room-revenue",)
    assert slots.is_inherited_metric is True
    assert slots.is_inherited_period is True


def test_complex_single_metric_question_keeps_dimensions_filter_period_and_view() -> None:
    """여러 조건이 결합돼도 단일 승인 지표 질문은 필요한 슬롯을 모두 보존한다."""

    slots = ConversationSlotResolver.resolve(
        user_message="2025년 7월 선셋 호텔의 접점과 카테고리별 VOC 평균 평점을 표로 보여줘",
        node1_output={
            "selected_metric_id": "voc_average_rating",
            "metric_ids": ["voc_average_rating"],
            "dimension_fields": [
                {"asset_fqn": "serving.voc_review_detail", "column": "touchpoint"},
                {"asset_fqn": "serving.voc_review_detail", "column": "selected_category"},
            ],
            "filter_fields": [
                {
                    "asset_fqn": "serving.voc_review_detail",
                    "column": "hotel_code",
                    "operator": "eq",
                    "value_text": "선셋",
                },
            ],
            "period_candidates": _period("2025-07-01", "2025-08-01", "2025년 7월"),
            "presentation_type": "TABLE",
            "is_elliptical": False,
            "requested_route": "ANALYSIS",
        },
        previous_turns=[_previous_room_revenue_turn()],
        as_of=date(2026, 8, 20),
    )

    assert slots.metric_id == "voc_average_rating"
    assert [item["column"] for item in slots.dimension_fields] == [
        "touchpoint",
        "selected_category",
    ]
    assert [item["value_text"] for item in slots.user_filters] == ["선셋"]
    assert slots.time_range is not None
    assert slots.time_range.start == date(2025, 7, 1)
    assert slots.target_chart_type == "TABLE"
    assert slots.source_turn_ids == ()


def test_multiple_new_metric_candidates_never_reuse_the_old_metric() -> None:
    """여러 새 지표를 요청한 턴은 직전 지표로 축소하지 않고 상위 명확화 경계로 보낸다."""

    slots = ConversationSlotResolver.resolve(
        user_message="2025년 7월 객실 매출과 식음 매출을 비교해줘",
        node1_output={
            "selected_metric_id": None,
            "metric_ids": ["room_revenue", "fnb_revenue"],
            "period_candidates": _period("2025-07-01", "2025-08-01", "2025년 7월"),
            "is_elliptical": False,
            "requested_route": "ANALYSIS",
        },
        previous_turns=[_previous_room_revenue_turn()],
        as_of=date(2026, 8, 20),
    )

    assert slots.metric_id is None
    assert slots.is_inherited_metric is False
    assert slots.time_range is not None
    assert slots.time_range.start == date(2025, 7, 1)
    assert slots.source_turn_ids == ()
