\set ON_ERROR_STOP on

-- V4.3 합성 PMS에서 cutoff 종료 시점에 알 수 있었던 예약·취소와 목표일
-- 재고·행사 계획만 계산한다. 실제 호텔 정확도 근거로 사용할 수 없다.
BEGIN;

CREATE OR REPLACE VIEW
ml_evaluation.room_demand_unverified_final_state_v43_20260901 AS
WITH bounds AS (
    SELECT max(business_date) AS max_business_date
    FROM walkerhill_v4_3.pms_room_inventory_daily
    WHERE NOT is_forecast
), grid AS (
    SELECT
        inventory.hotel_code AS property_id,
        inventory.room_type_code,
        inventory.business_date AS cutoff_date,
        inventory.business_date + horizon AS target_date,
        horizon AS horizon_days,
        inventory.physical_rooms AS cutoff_physical_rooms,
        inventory.available_room_nights AS cutoff_sellable_rooms,
        inventory.out_of_order_rooms AS cutoff_out_of_order_rooms,
        inventory.house_use_rooms AS cutoff_house_use_rooms,
        ((inventory.business_date + 1)::timestamp AT TIME ZONE 'Asia/Seoul') AS cutoff_end_at
    FROM walkerhill_v4_3.pms_room_inventory_daily AS inventory
    CROSS JOIN generate_series(1, 7) AS horizon
    CROSS JOIN bounds
    WHERE NOT inventory.is_forecast
      AND inventory.business_date >= DATE '2025-01-07'
      AND inventory.business_date + 7 <= bounds.max_business_date
), capacity AS (
    SELECT
        grid.*,
        target.available_room_nights AS target_sellable_rooms,
        target.out_of_order_rooms AS target_out_of_order_rooms
    FROM grid
    JOIN walkerhill_v4_3.pms_room_inventory_daily AS target
      ON target.hotel_code = grid.property_id
     AND target.room_type_code = grid.room_type_code
     AND target.business_date = grid.target_date
     AND NOT target.is_forecast
), reservation_signals AS (
    SELECT
        capacity.property_id,
        capacity.room_type_code,
        capacity.cutoff_date,
        capacity.target_date,
        capacity.horizon_days,
        count(reservation.reservation_id) FILTER (
            WHERE reservation.booked_at < capacity.cutoff_end_at
              AND (
                  reservation.cancelled_at IS NULL
                  OR reservation.cancelled_at >= capacity.cutoff_end_at
              )
        ) AS booking_on_hand,
        count(reservation.reservation_id) FILTER (
            WHERE reservation.booked_at >= capacity.cutoff_end_at - INTERVAL '1 day'
              AND reservation.booked_at < capacity.cutoff_end_at
        ) AS booking_pickup_1d,
        count(reservation.reservation_id) FILTER (
            WHERE reservation.booked_at >= capacity.cutoff_end_at - INTERVAL '7 days'
              AND reservation.booked_at < capacity.cutoff_end_at
        ) AS booking_pickup_7d,
        count(reservation.reservation_id) FILTER (
            WHERE reservation.booked_at < capacity.cutoff_end_at
              AND reservation.cancelled_at < capacity.cutoff_end_at
        ) AS cancellations_on_hand,
        count(reservation.reservation_id) FILTER (
            WHERE reservation.cancelled_at >= capacity.cutoff_end_at - INTERVAL '7 days'
              AND reservation.cancelled_at < capacity.cutoff_end_at
        ) AS cancellations_7d,
        count(reservation.reservation_id) FILTER (
            WHERE reservation.booked_at < capacity.cutoff_end_at
              AND (
                  reservation.cancelled_at IS NULL
                  OR reservation.cancelled_at >= capacity.cutoff_end_at
              )
              AND reservation.banquet_event_id IS NOT NULL
        ) AS banquet_room_nights_on_hand
    FROM capacity
    LEFT JOIN walkerhill_v4_3.pms_reservations AS reservation
      ON reservation.hotel_code = capacity.property_id
     AND reservation.room_type_code = capacity.room_type_code
     AND reservation.checkin_date <= capacity.target_date
     AND capacity.target_date < reservation.checkout_date
     AND reservation.booked_at < capacity.cutoff_end_at
    GROUP BY 1, 2, 3, 4, 5
), event_signals AS (
    SELECT
        capacity.property_id,
        capacity.room_type_code,
        capacity.cutoff_date,
        capacity.target_date,
        capacity.horizon_days,
        count(DISTINCT event.event_id) AS event_count,
        COALESCE(
            sum(effect.uplift_mode) FILTER (WHERE event.event_id IS NOT NULL),
            0
        ) AS event_demand_uplift
    FROM capacity
    LEFT JOIN walkerhill_v4_3.hotel_event_effect AS effect
      ON effect.hotel_code = capacity.property_id
     AND effect.domain = 'ROOMS'
     AND effect.metric_name = 'OCCUPANCY_RATE'
    LEFT JOIN walkerhill_v4_3.event_master AS event
      ON event.event_id = effect.event_id
     AND capacity.target_date BETWEEN
         event.start_date - effect.lead_days
         AND event.end_date + effect.lag_days
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    capacity.property_id,
    capacity.room_type_code,
    capacity.cutoff_date,
    capacity.target_date,
    capacity.horizon_days,
    capacity.target_sellable_rooms::double precision AS target_sellable_rooms,
    capacity.target_out_of_order_rooms::double precision AS target_out_of_order_rooms,
    reservation.booking_on_hand::double precision AS booking_on_hand,
    reservation.booking_on_hand::double precision
        / NULLIF(capacity.target_sellable_rooms, 0) AS booking_on_hand_ratio,
    reservation.booking_pickup_1d::double precision AS booking_pickup_1d,
    reservation.booking_pickup_7d::double precision AS booking_pickup_7d,
    (
        reservation.booking_pickup_1d * 7
        - reservation.booking_pickup_7d
    )::double precision AS booking_pickup_acceleration,
    reservation.cancellations_on_hand::double precision AS cancellations_on_hand,
    reservation.cancellations_7d::double precision AS cancellations_7d,
    (
        reservation.booking_pickup_7d
        - reservation.cancellations_7d
    )::double precision AS net_booking_pickup_7d,
    reservation.banquet_room_nights_on_hand::double precision
        AS banquet_room_nights_on_hand,
    event.event_count::double precision AS event_count,
    event.event_demand_uplift::double precision AS event_demand_uplift,
    capacity.cutoff_end_at AS reservation_as_of_at,
    NULL::timestamp with time zone AS capacity_as_of_at,
    NULL::timestamp with time zone AS event_as_of_at,
    'UNVERIFIED_FINAL_STATE'::text AS signal_source_kind,
    true AS signal_is_synthetic
FROM capacity
JOIN reservation_signals AS reservation USING (
    property_id, room_type_code, cutoff_date, target_date, horizon_days
)
JOIN event_signals AS event USING (
    property_id, room_type_code, cutoff_date, target_date, horizon_days
);

COMMENT ON VIEW ml_evaluation.room_demand_unverified_final_state_v43_20260901 IS
    'V4.3 합성 PMS 신호. 목표일 재고·행사의 과거 snapshot 시각이 없어 UNVERIFIED_FINAL_STATE이며 운영 추론·학습에서 차단됨';

GRANT SELECT ON ml_evaluation.room_demand_unverified_final_state_v43_20260901
    TO :"readonly_role";

COMMIT;
