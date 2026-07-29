-- ============================================================================
-- Answervice 팀공유 SQL 산출물
-- ownership_contract=team-ownership-v2.1
-- schema_version=schema-v4.6-websql
-- snapshot_as_of_at=2026-07-28T05:00:00Z
-- generation_as_of_at=2026-07-28T05:00:00Z
-- evaluation_as_of=2026-07-28T14:00:00+09:00
-- GENERATE_FILES=true / RUN_STATIC_VALIDATION=true / EXECUTE_DB=false
-- 접속정보·healthy 컨테이너는 실행 승인으로 간주하지 않는다.
-- 실제 실행 전 해당 owner의 approval_id가 필요하다.
-- ============================================================================
-- owner=ML_WORKCARD_OWNER
-- work_card=ML-ROOM-DEMAND
-- variant=PMS_ONLY_FALLBACK / read_only=true / training_data_persistence=false

-- room-demand-feature-v1.4
-- read-only Trino SQL. Source에 DDL/DML을 수행하지 않는다.
-- template tokens are rendered only after strict type validation.

WITH
params AS (
    SELECT
        {{MODE}} AS mode,
        {{AS_OF_AT}} AS as_of_at_utc,
        {{TRAIN_START}} AS train_start,
        {{TRAIN_END}} AS train_end,
        {{PROPERTY_ID}} AS property_id
),
room_types AS (
    SELECT DISTINCT property_id, room_type_code
    FROM pms.public.pms_room_inventory_daily
    CROSS JOIN params p
    WHERE property_id = p.property_id
),
target_dates AS (
    SELECT d AS target_date
    FROM params p
    CROSS JOIN UNNEST(
        CASE
            WHEN p.mode = 'train'
                THEN SEQUENCE(p.train_start, p.train_end, INTERVAL '1' DAY)
            ELSE SEQUENCE(
                CAST(at_timezone(p.as_of_at_utc, 'Asia/Seoul') AS date) + INTERVAL '1' DAY,
                CAST(at_timezone(p.as_of_at_utc, 'Asia/Seoul') AS date) + INTERVAL '7' DAY,
                INTERVAL '1' DAY
            )
        END
    ) AS t(d)
),
grid_base AS (
    SELECT
        r.property_id,
        d.target_date,
        r.room_type_code,
        h AS horizon_days,
        date_add('day', -h, d.target_date) AS prediction_cutoff_date
    FROM room_types r
    CROSS JOIN target_dates d
    CROSS JOIN UNNEST(SEQUENCE(1, 7)) AS u(h)
    CROSS JOIN params p
    WHERE
        (p.mode = 'train')
        OR (
            p.mode = 'predict'
            AND h = date_diff(
                'day',
                CAST(at_timezone(p.as_of_at_utc, 'Asia/Seoul') AS date),
                d.target_date
            )
        )
),
target_grid AS (
    SELECT
        g.*,
        at_timezone(
            with_timezone(
                CAST(g.prediction_cutoff_date AS timestamp),
                'Asia/Seoul'
            ),
            'UTC'
        ) AS prediction_cutoff_at_utc
    FROM grid_base g
),
stay_nights AS (
    SELECT
        s.property_id,
        s.room_type_code,
        s.room_unit_code,
        s.room_revenue,
        s.occupied_room_nights,
        d AS business_date
    FROM pms.public.pms_stays s
    CROSS JOIN UNNEST(
        SEQUENCE(
            CAST(at_timezone(s.actual_checkin_at, 'Asia/Seoul') AS date),
            CAST(at_timezone(s.actual_checkout_at, 'Asia/Seoul') AS date) - INTERVAL '1' DAY,
            INTERVAL '1' DAY
        )
    ) AS u(d)
    WHERE s.is_forecast = false
      AND s.data_period_status IN (
          'REFERENCE_CALIBRATED',
          'SYNTHETIC_ACTUAL_LIKE',
          'YTD_SYNTHETIC'
      )
      AND s.stay_status = 'COMPLETED'
      AND s.complimentary_flag = false
      AND s.house_use_flag = false
      AND s.actual_checkin_at IS NOT NULL
      AND s.actual_checkout_at IS NOT NULL
),
pms_daily_actual AS (
    SELECT
        property_id,
        business_date,
        room_type_code,
        count(DISTINCT room_unit_code) AS rooms_sold,
        sum(room_revenue / NULLIF(occupied_room_nights, 0)) AS daily_room_revenue
    FROM stay_nights
    GROUP BY 1,2,3
),
inventory_features AS (
    SELECT
        g.property_id,
        g.target_date,
        g.room_type_code,
        g.horizon_days,
        coalesce(
            max(i.available_room_nights) FILTER (
                WHERE i.business_date = g.target_date
                  AND i.source_updated_at < g.prediction_cutoff_at_utc
            ),
            max(i.physical_rooms) FILTER (
                WHERE i.business_date < g.prediction_cutoff_date
                  AND i.source_updated_at < g.prediction_cutoff_at_utc
            )
        ) AS available_room_nights,
        CASE WHEN count_if(
            i.business_date = g.target_date
            AND i.source_updated_at < g.prediction_cutoff_at_utc
        ) > 0 THEN 1 ELSE 0 END AS inventory_plan_known
    FROM target_grid g
    LEFT JOIN pms.public.pms_room_inventory_daily i
      ON i.property_id = g.property_id
     AND i.room_type_code = g.room_type_code
    GROUP BY 1,2,3,4
),
booking_features AS (
    SELECT
        g.property_id,
        g.target_date,
        g.room_type_code,
        g.horizon_days,
        count_if(
            r.booked_at < g.prediction_cutoff_at_utc
            AND r.source_updated_at < g.prediction_cutoff_at_utc
            AND (r.cancelled_at IS NULL OR r.cancelled_at >= g.prediction_cutoff_at_utc)
            AND r.checkin_date <= g.target_date
            AND g.target_date < r.checkout_date
        ) AS booking_on_hand,
        count_if(
            r.booked_at < g.prediction_cutoff_at_utc
            AND r.source_updated_at < g.prediction_cutoff_at_utc
            AND r.cancelled_at < g.prediction_cutoff_at_utc
            AND r.checkin_date <= g.target_date
            AND g.target_date < r.checkout_date
        ) AS cancelled_on_hand
    FROM target_grid g
    LEFT JOIN pms.public.pms_reservations r
      ON r.property_id = g.property_id
     AND r.room_type_code = g.room_type_code
    GROUP BY 1,2,3,4
),
pms_history_features AS (
    SELECT
        g.property_id,
        g.target_date,
        g.room_type_code,
        g.horizon_days,
        max(a.rooms_sold) FILTER (
            WHERE a.business_date = g.prediction_cutoff_date - INTERVAL '1' DAY
        ) AS rooms_sold_cutoff_lag_1,
        max(a.rooms_sold) FILTER (
            WHERE a.business_date = g.prediction_cutoff_date - INTERVAL '7' DAY
        ) AS rooms_sold_cutoff_lag_7,
        max(a.rooms_sold) FILTER (
            WHERE a.business_date = g.prediction_cutoff_date - INTERVAL '14' DAY
        ) AS rooms_sold_cutoff_lag_14,
        avg(a.rooms_sold) FILTER (
            WHERE a.business_date >= g.prediction_cutoff_date - INTERVAL '7' DAY
              AND a.business_date < g.prediction_cutoff_date
        ) AS rooms_sold_cutoff_rolling_mean_7,
        avg(a.rooms_sold) FILTER (
            WHERE a.business_date >= g.prediction_cutoff_date - INTERVAL '28' DAY
              AND a.business_date < g.prediction_cutoff_date
        ) AS rooms_sold_cutoff_rolling_mean_28,
        max(a.daily_room_revenue / NULLIF(a.rooms_sold, 0)) FILTER (
            WHERE a.business_date = g.prediction_cutoff_date - INTERVAL '7' DAY
        ) AS adr_cutoff_lag_7
    FROM target_grid g
    LEFT JOIN pms_daily_actual a
      ON a.property_id = g.property_id
     AND a.room_type_code = g.room_type_code
     AND a.business_date >= g.prediction_cutoff_date - INTERVAL '28' DAY
     AND a.business_date < g.prediction_cutoff_date
    GROUP BY 1,2,3,4
),
cancellation_features AS (
    SELECT
        g.property_id,
        g.target_date,
        g.room_type_code,
        g.horizon_days,
        CAST(count_if(
            r.cancelled_at < g.prediction_cutoff_at_utc
        ) AS double)
        / NULLIF(CAST(count(r.reservation_id) AS double), 0.0)
        AS cancellation_rate_cutoff_lag_28
    FROM target_grid g
    LEFT JOIN pms.public.pms_reservations r
      ON r.property_id = g.property_id
     AND r.room_type_code = g.room_type_code
     AND r.booked_at < g.prediction_cutoff_at_utc
     AND r.source_updated_at < g.prediction_cutoff_at_utc
     AND r.checkin_date >= g.prediction_cutoff_date - INTERVAL '28' DAY
     AND r.checkin_date < g.prediction_cutoff_date
    GROUP BY 1,2,3,4
),
pos_features AS (SELECT property_id,target_date,room_type_code,horizon_days,CAST(NULL AS double) fnb_covers_lag_7d,CAST(NULL AS double) fnb_net_amount_lag_7d,0 pos_source_available FROM target_grid),
crm_features AS (SELECT property_id,target_date,room_type_code,horizon_days,CAST(NULL AS double) member_booking_ratio,CAST(NULL AS double) vip_booking_ratio,0 crm_source_available FROM target_grid),
facility_features AS (SELECT property_id,target_date,room_type_code,horizon_days,CAST(NULL AS double) facility_downtime_lag_7d,0 facility_source_available FROM target_grid),
banquet_features AS (SELECT property_id,target_date,room_type_code,horizon_days,CAST(NULL AS double) confirmed_banquet_count,CAST(NULL AS double) confirmed_banquet_expected_guests,CAST(NULL AS double) confirmed_room_block_count,CAST(NULL AS double) confirmed_expected_room_nights,0 banquet_source_available FROM target_grid),
labels AS (
    SELECT
        g.property_id,
        g.target_date,
        g.room_type_code,
        g.horizon_days,
        coalesce(max(a.rooms_sold), 0) AS rooms_sold
    FROM target_grid g
    LEFT JOIN pms_daily_actual a
      ON a.property_id = g.property_id
     AND a.business_date = g.target_date
     AND a.room_type_code = g.room_type_code
    GROUP BY 1,2,3,4
)
SELECT
    g.property_id,
    g.target_date,
    g.room_type_code,
    g.horizon_days,
    g.prediction_cutoff_date,
    g.prediction_cutoff_at_utc,
    CAST(i.available_room_nights AS double) AS available_room_nights,
    i.inventory_plan_known,
    CAST(b.booking_on_hand AS double) AS booking_on_hand,
    CAST(b.cancelled_on_hand AS double) AS cancelled_on_hand,
    CAST(b.booking_on_hand AS double)
        / NULLIF(CAST(i.available_room_nights AS double), 0.0)
        AS booking_on_hand_ratio,
    CAST(h.rooms_sold_cutoff_lag_1 AS double) AS rooms_sold_cutoff_lag_1,
    CAST(h.rooms_sold_cutoff_lag_7 AS double) AS rooms_sold_cutoff_lag_7,
    CAST(h.rooms_sold_cutoff_lag_14 AS double) AS rooms_sold_cutoff_lag_14,
    CAST(h.rooms_sold_cutoff_rolling_mean_7 AS double)
        AS rooms_sold_cutoff_rolling_mean_7,
    CAST(h.rooms_sold_cutoff_rolling_mean_28 AS double)
        AS rooms_sold_cutoff_rolling_mean_28,
    CAST(h.adr_cutoff_lag_7 AS double) AS adr_cutoff_lag_7,
    CAST(c.cancellation_rate_cutoff_lag_28 AS double)
        AS cancellation_rate_cutoff_lag_28,
    p.fnb_covers_lag_7d,
    p.fnb_net_amount_lag_7d,
    p.pos_source_available,
    cr.member_booking_ratio,
    cr.vip_booking_ratio,
    cr.crm_source_available,
    f.facility_downtime_lag_7d,
    f.facility_source_available,
    bn.confirmed_banquet_count,
    bn.confirmed_banquet_expected_guests,
    bn.confirmed_room_block_count,
    bn.confirmed_expected_room_nights,
    bn.banquet_source_available,
    day_of_week(g.target_date) AS target_day_of_week,
    month(g.target_date) AS target_month,
    CASE WHEN day_of_week(g.target_date) IN (6, 7) THEN 1 ELSE 0 END
        AS target_is_weekend,
    CASE WHEN day(g.target_date) = 1 THEN 1 ELSE 0 END AS target_is_month_start,
    CASE WHEN g.target_date = last_day_of_month(g.target_date) THEN 1 ELSE 0 END
        AS target_is_month_end,
    CASE WHEN pa.mode = 'train' THEN CAST(l.rooms_sold AS double)
         ELSE CAST(NULL AS double) END AS rooms_sold
FROM target_grid g
CROSS JOIN params pa
JOIN inventory_features i USING (
    property_id, target_date, room_type_code, horizon_days
)
JOIN booking_features b USING (
    property_id, target_date, room_type_code, horizon_days
)
JOIN pms_history_features h USING (
    property_id, target_date, room_type_code, horizon_days
)
JOIN cancellation_features c USING (
    property_id, target_date, room_type_code, horizon_days
)
JOIN pos_features p USING (
    property_id, target_date, room_type_code, horizon_days
)
JOIN crm_features cr USING (
    property_id, target_date, room_type_code, horizon_days
)
JOIN facility_features f USING (
    property_id, target_date, room_type_code, horizon_days
)
JOIN banquet_features bn USING (
    property_id, target_date, room_type_code, horizon_days
)
JOIN labels l USING (
    property_id, target_date, room_type_code, horizon_days
)
WHERE
    (pa.mode = 'predict')
    OR (
        pa.mode = 'train'
        AND g.target_date <= DATE '2026-07-27'
        AND l.rooms_sold IS NOT NULL
    )
ORDER BY 1,2,3,4

-- VALIDATION_QUERIES
-- 아래 SELECT는 Feature Query 실행 후 별도로 수행한다.
-- 1) source row count / watermark
-- SELECT 'pms_reservations', count(*), max(source_updated_at)
-- FROM pms.public.pms_reservations;
-- 2) forecast label 0건
-- SELECT count(*) FROM pms.public.pms_stays
-- WHERE is_forecast = true AND stay_status = 'COMPLETED';
-- 3) dataset grain 중복 0건과 안정 정렬 checksum은 Python metadata에 기록한다.
