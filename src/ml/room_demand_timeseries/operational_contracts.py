"""운영형 객실 수요 예측의 시점 특징·용량·출력 계약을 정의한다."""

from __future__ import annotations

from .contracts import CATEGORICAL_FEATURES, FEATURE_COLUMNS as HISTORICAL_FEATURE_COLUMNS


OPERATIONAL_MODEL_VERSION = "room-demand-operational-hgbr-v4.0.0"
OPERATIONAL_FEATURE_PROFILE = "point_in_time_demand_v1"
OPERATIONAL_MAX_HORIZON = 7
TARGET_CAPACITY_COLUMN = "target_sellable_rooms"

TARGET_HISTORY_FEATURES = [
    "target_rooms_sold_lag_7",
    "target_rooms_sold_lag_14",
    "target_rooms_sold_lag_21",
    "target_rooms_sold_lag_28",
    "target_same_weekday_mean_4w",
    "target_same_weekday_mean_8w",
    "target_same_weekday_mean_12w",
]

POINT_IN_TIME_SIGNAL_FEATURES = [
    TARGET_CAPACITY_COLUMN,
    "target_out_of_order_rooms",
    "booking_on_hand",
    "booking_on_hand_ratio",
    "booking_pickup_1d",
    "booking_pickup_7d",
    "booking_pickup_acceleration",
    "cancellations_on_hand",
    "cancellations_7d",
    "net_booking_pickup_7d",
    "banquet_room_nights_on_hand",
    "event_count",
    "event_demand_uplift",
]

OPERATIONAL_FEATURE_COLUMNS = list(
    dict.fromkeys(
        HISTORICAL_FEATURE_COLUMNS
        + TARGET_HISTORY_FEATURES
        + POINT_IN_TIME_SIGNAL_FEATURES
    )
)
OPERATIONAL_NUMERIC_FEATURES = [
    column
    for column in OPERATIONAL_FEATURE_COLUMNS
    if column not in CATEGORICAL_FEATURES
]

SIGNAL_IDENTITY_COLUMNS = [
    "property_id",
    "room_type_code",
    "cutoff_date",
    "target_date",
    "horizon_days",
]
SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS = [
    "reservation_as_of_at",
    "capacity_as_of_at",
    "event_as_of_at",
]
SIGNAL_PROVENANCE_COLUMNS = SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS + [
    "signal_source_kind",
    "signal_is_synthetic",
]
SIGNAL_REQUIRED_COLUMNS = (
    SIGNAL_IDENTITY_COLUMNS
    + POINT_IN_TIME_SIGNAL_FEATURES
    + SIGNAL_PROVENANCE_COLUMNS
)
OBSERVED_SIGNAL_SOURCE_KIND = "OBSERVED_PIT"
SYNTHETIC_SIGNAL_SOURCE_KIND = "SYNTHETIC_PIT"
ALLOWED_SIGNAL_SOURCE_KINDS = {
    OBSERVED_SIGNAL_SOURCE_KIND,
    SYNTHETIC_SIGNAL_SOURCE_KIND,
}

FACTOR_LABELS_KO = {
    "booking_on_hand": "현재 예약 잔량",
    "booking_on_hand_ratio": "판매 가능 객실 대비 예약률",
    "booking_pickup_1d": "최근 1일 예약 증가",
    "booking_pickup_7d": "최근 7일 예약 증가",
    "booking_pickup_acceleration": "예약 증가 속도",
    "cancellations_on_hand": "누적 취소",
    "cancellations_7d": "최근 7일 취소",
    "net_booking_pickup_7d": "최근 7일 순예약 증가",
    "banquet_room_nights_on_hand": "연회 연계 예약",
    "event_count": "예정 행사 수",
    "event_demand_uplift": "행사 수요 영향",
    "target_out_of_order_rooms": "공사·고장 판매중지 객실",
    "target_is_weekend": "주말 효과",
    "target_is_public_holiday": "공휴일 효과",
    "target_same_weekday_mean_4w": "최근 동일 요일 실적",
}

EXPLAINABLE_FEATURES = list(FACTOR_LABELS_KO)
