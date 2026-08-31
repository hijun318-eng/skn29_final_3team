\set ON_ERROR_STOP on

-- Local integration source only. Every contributing PMS row is synthetic and
-- this view must not be presented as evidence of accuracy on real hotel data.
BEGIN;

CREATE SCHEMA IF NOT EXISTS ml_evaluation;

CREATE OR REPLACE VIEW ml_evaluation.room_demand_daily_facts_v43_20260830 AS
WITH stay_actual AS (
    SELECT
        stay.hotel_code AS property_id,
        night.business_date,
        stay.room_type_code,
        count(*) AS rooms_sold,
        sum(night.net_room_revenue) AS room_revenue
    FROM walkerhill_v4_3.pms_stay_nights AS night
    JOIN walkerhill_v4_3.pms_stays AS stay
      ON stay.stay_id = night.stay_id
    WHERE stay.stay_status = 'CHECKED_OUT'
      AND NOT stay.complimentary_flag
      AND NOT stay.house_use_flag
      AND NOT stay.is_forecast
    GROUP BY 1, 2, 3
), cancellation AS (
    SELECT
        hotel_code AS property_id,
        checkin_date AS business_date,
        room_type_code,
        count(*) FILTER (WHERE reservation_status = 'CANCELLED')::double precision
          / NULLIF(count(*)::double precision, 0.0) AS cancellation_rate
    FROM walkerhill_v4_3.pms_reservations
    WHERE NOT is_forecast
    GROUP BY 1, 2, 3
)
SELECT
    inventory.hotel_code::text AS property_id,
    inventory.business_date,
    inventory.room_type_code::text AS room_type_code,
    inventory.physical_rooms::integer AS physical_rooms,
    inventory.available_room_nights::integer AS available_room_nights,
    coalesce(actual.rooms_sold, 0)::integer AS rooms_sold,
    coalesce(
        actual.room_revenue::double precision
          / NULLIF(actual.rooms_sold::double precision, 0.0),
        0.0
    ) AS daily_adr,
    coalesce(cancellation.cancellation_rate, 0.0)::double precision
        AS cancellation_rate,
    true AS is_synthetic
FROM walkerhill_v4_3.pms_room_inventory_daily AS inventory
LEFT JOIN stay_actual AS actual
  ON actual.property_id = inventory.hotel_code
 AND actual.business_date = inventory.business_date
 AND actual.room_type_code = inventory.room_type_code
LEFT JOIN cancellation
  ON cancellation.property_id = inventory.hotel_code
 AND cancellation.business_date = inventory.business_date
 AND cancellation.room_type_code = inventory.room_type_code
WHERE NOT inventory.is_forecast;

COMMENT ON VIEW ml_evaluation.room_demand_daily_facts_v43_20260830 IS
    'Synthetic V4.3 room-demand history for local conditional ML integration; not real hotel performance evidence';

GRANT USAGE ON SCHEMA ml_evaluation TO :"readonly_role";
GRANT SELECT ON ml_evaluation.room_demand_daily_facts_v43_20260830
    TO :"readonly_role";

DO $$
DECLARE
    invalid_rows bigint;
    invalid_series bigint;
BEGIN
    SELECT count(*)
      INTO invalid_rows
      FROM ml_evaluation.room_demand_daily_facts_v43_20260830
     WHERE property_id IS NULL
        OR business_date IS NULL
        OR room_type_code IS NULL
        OR physical_rooms <= 0
        OR available_room_nights < 0
        OR available_room_nights > physical_rooms
        OR rooms_sold < 0
        OR rooms_sold > available_room_nights
        OR daily_adr < 0
        OR cancellation_rate < 0
        OR cancellation_rate > 1
        OR NOT is_synthetic;
    IF invalid_rows <> 0 THEN
        RAISE EXCEPTION 'ML_HISTORY_INVALID_ROWS: %', invalid_rows;
    END IF;

    SELECT count(*)
      INTO invalid_series
      FROM (
          SELECT
              property_id,
              room_type_code,
              count(*) AS row_count,
              max(business_date) - min(business_date) + 1 AS calendar_days
          FROM ml_evaluation.room_demand_daily_facts_v43_20260830
          GROUP BY 1, 2
      ) AS series
     WHERE row_count <> calendar_days
        OR row_count < 372;
    IF invalid_series <> 0 THEN
        RAISE EXCEPTION 'ML_HISTORY_INVALID_SERIES: %', invalid_series;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM ml_evaluation.room_demand_daily_facts_v43_20260830
    ) THEN
        RAISE EXCEPTION 'ML_HISTORY_EMPTY';
    END IF;
END
$$;

COMMIT;
