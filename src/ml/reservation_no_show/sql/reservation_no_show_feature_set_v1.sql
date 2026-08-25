-- reservation-no-show-feature-v1.0
-- PostgreSQL reference query. Bind :reservation_id and :feature_as_of.
WITH request AS (
    SELECT
        CAST(:reservation_id AS text) AS reservation_id,
        CAST(:feature_as_of AS timestamptz) AS feature_as_of
),
target AS (
    SELECT r.*, q.feature_as_of
    FROM pms_reservations r
    JOIN request q ON q.reservation_id = r.reservation_id
    WHERE r.booked_at <= q.feature_as_of
      AND q.feature_as_of = (
          (r.checkin_date - 1)::timestamp + time '18:00'
      ) AT TIME ZONE 'Asia/Seoul'
),
history AS (
    SELECT
        t.reservation_id,
        count(h.reservation_id) AS previous_booking_count
    FROM target t
    LEFT JOIN pms_reservations h
      ON h.guest_id = t.guest_id
     AND h.checkin_date < t.checkin_date
     AND h.booked_at <= t.feature_as_of
    GROUP BY t.reservation_id
)
SELECT
    t.reservation_id,
    t.feature_as_of,
    greatest(t.checkin_date - (t.booked_at AT TIME ZONE 'Asia/Seoul')::date, 0)::double precision AS lead_time_days,
    greatest(t.checkout_date - t.checkin_date, 1)::double precision AS length_of_stay,
    t.adult_count::double precision,
    t.child_count::double precision,
    t.quoted_room_rate::double precision,
    t.booked_amount::double precision,
    CASE WHEN t.gross_room_amount > 0
        THEN (t.discount_amount / t.gross_room_amount)::double precision
        ELSE 0::double precision
    END AS discount_ratio,
    h.previous_booking_count::double precision,
    extract(month FROM t.checkin_date)::double precision AS arrival_month,
    extract(isodow FROM t.checkin_date)::double precision - 1 AS arrival_day_of_week,
    CASE WHEN extract(isodow FROM t.checkin_date) IN (6, 7) THEN 1 ELSE 0 END::double precision AS arrival_weekend_flag,
    t.room_type_code,
    t.rate_plan_code,
    t.market_segment,
    t.booking_channel,
    coalesce(g.country_group, 'UNKNOWN') AS country_group,
    t.is_synthetic
FROM target t
JOIN history h ON h.reservation_id = t.reservation_id
LEFT JOIN pms_guests g ON g.guest_id = t.guest_id;
