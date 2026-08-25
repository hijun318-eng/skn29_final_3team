-- reservation-no-show-feature-v1.0
-- Trino local verification query. Replace ${RESERVATION_ID} and ${FEATURE_AS_OF}.
WITH request(reservation_id, feature_as_of) AS (
    VALUES (
        CAST('${RESERVATION_ID}' AS varchar),
        from_iso8601_timestamp('${FEATURE_AS_OF}')
    )
),
target AS (
    SELECT r.*, q.feature_as_of
    FROM pms.walkerhill_v4_3.pms_reservations r
    JOIN request q ON q.reservation_id = r.reservation_id
    WHERE r.booked_at <= q.feature_as_of
      AND CAST(q.feature_as_of AT TIME ZONE 'Asia/Seoul' AS date)
          = r.checkin_date - INTERVAL '1' DAY
      AND hour(q.feature_as_of AT TIME ZONE 'Asia/Seoul') = 18
),
history AS (
    SELECT t.reservation_id, count(h.reservation_id) AS previous_booking_count
    FROM target t
    LEFT JOIN pms.walkerhill_v4_3.pms_reservations h
      ON h.guest_id = t.guest_id
     AND h.checkin_date < t.checkin_date
     AND h.booked_at <= t.feature_as_of
    GROUP BY t.reservation_id
)
SELECT
    t.reservation_id,
    CAST(t.feature_as_of AS varchar) AS feature_as_of,
    CAST(greatest(date_diff(
        'day', CAST(t.booked_at AT TIME ZONE 'Asia/Seoul' AS date), t.checkin_date
    ), 0) AS double) AS lead_time_days,
    CAST(greatest(date_diff('day', t.checkin_date, t.checkout_date), 1) AS double)
        AS length_of_stay,
    CAST(t.adult_count AS double) AS adult_count,
    CAST(t.child_count AS double) AS child_count,
    CAST(t.quoted_room_rate AS double) AS quoted_room_rate,
    CAST(t.booked_amount AS double) AS booked_amount,
    CASE WHEN t.gross_room_amount > 0
        THEN CAST(t.discount_amount AS double) / CAST(t.gross_room_amount AS double)
        ELSE 0.0
    END AS discount_ratio,
    CAST(h.previous_booking_count AS double) AS previous_booking_count,
    CAST(month(t.checkin_date) AS double) AS arrival_month,
    CAST(day_of_week(t.checkin_date) - 1 AS double) AS arrival_day_of_week,
    CAST(CASE WHEN day_of_week(t.checkin_date) IN (6, 7) THEN 1 ELSE 0 END AS double)
        AS arrival_weekend_flag,
    t.room_type_code,
    t.rate_plan_code,
    t.market_segment,
    t.booking_channel,
    coalesce(g.country_group, 'UNKNOWN') AS country_group,
    t.is_synthetic
FROM target t
JOIN history h ON h.reservation_id = t.reservation_id
LEFT JOIN pms.walkerhill_v4_3.pms_guests g ON g.guest_id = t.guest_id
