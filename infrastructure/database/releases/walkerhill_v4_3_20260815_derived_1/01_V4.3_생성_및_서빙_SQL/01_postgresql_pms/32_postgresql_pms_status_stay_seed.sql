-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=PMS; script_type=STATUS_STAY_SEED; execution_order=32
-- dependencies=31_postgresql_pms_guest_reservation_seed.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=1601041; execution_default=NOT_RUN; destructive_operation=false
-- next=33_postgresql_pms_folio_seed.sql

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM walkerhill_v4_3.pms_reservation_status_history)
     OR EXISTS (SELECT 1 FROM walkerhill_v4_3.pms_stays)
     OR EXISTS (SELECT 1 FROM walkerhill_v4_3.pms_stay_nights) THEN
    RAISE EXCEPTION 'candidate status, stay and stay-night tables must be empty';
  END IF;
END $$;

INSERT INTO walkerhill_v4_3.pms_reservation_status_history
(status_history_id,reservation_id,status_code,status_at,reason_code,source_process,is_synthetic)
SELECT 'H_'||substr(encode(sha256(convert_to(r.reservation_id||'|'||h.status_code,'UTF8')),'hex'),1,32),
       r.reservation_id,h.status_code,h.status_at,NULL,'PMS_LIFECYCLE',true
FROM walkerhill_v4_3.pms_reservations r
CROSS JOIN LATERAL (
  VALUES ('BOOKED',r.booked_at),
         ('CHECKED_IN',(r.checkin_date::timestamp+TIME '15:00') AT TIME ZONE 'Asia/Seoul'),
         ('CHECKED_OUT',(r.checkout_date::timestamp+TIME '11:00') AT TIME ZONE 'Asia/Seoul')
) h(status_code,status_at)
WHERE r.reservation_status='CHECKED_OUT';

INSERT INTO walkerhill_v4_3.pms_reservation_status_history
(status_history_id,reservation_id,status_code,status_at,reason_code,source_process,is_synthetic)
SELECT 'H_'||substr(encode(sha256(convert_to(r.reservation_id||'|'||h.status_code,'UTF8')),'hex'),1,32),
       r.reservation_id,h.status_code,h.status_at,
       CASE WHEN h.status_code='CANCELLED' THEN r.cancellation_reason_code END,'PMS_LIFECYCLE',true
FROM walkerhill_v4_3.pms_reservations r
CROSS JOIN LATERAL (VALUES ('BOOKED',r.booked_at),('CANCELLED',r.cancelled_at)) h(status_code,status_at)
WHERE r.reservation_status='CANCELLED';

INSERT INTO walkerhill_v4_3.pms_stays
(stay_id,reservation_id,guest_id,hotel_code,room_id,room_type_code,actual_checkin_at,actual_checkout_at,
 occupied_room_nights,guest_count,room_revenue,other_room_charges,stay_status,complimentary_flag,house_use_flag,
 is_forecast,is_synthetic)
SELECT CASE WHEN r.reservation_id LIKE 'R_BRIDGE_%' OR r.reservation_id LIKE 'R_JOURNEY_%'
            THEN regexp_replace(r.reservation_id,'^R_','S_')
            ELSE 'S_'||substr(encode(sha256(convert_to(r.reservation_id,'UTF8')),'hex'),1,30) END,
       r.reservation_id,r.guest_id,r.hotel_code,r.assigned_room_id,r.room_type_code,
       (r.checkin_date::timestamp+TIME '15:00'+make_interval(mins=>floor(walkerhill_v4_3.v43_u01('checkin|'||r.reservation_id)*90)::int)) AT TIME ZONE 'Asia/Seoul',
       (r.checkout_date::timestamp+TIME '11:00'+make_interval(mins=>floor(walkerhill_v4_3.v43_u01('checkout|'||r.reservation_id)*45)::int)) AT TIME ZONE 'Asia/Seoul',
       r.checkout_date-r.checkin_date,
       (1+floor(walkerhill_v4_3.v43_u01('party|'||r.reservation_id)*rt.synthetic_max_occupancy))::smallint,
       r.booked_amount,
       round((8000+walkerhill_v4_3.v43_u01('other|'||r.reservation_id)*72000)::numeric,-3)
       +CASE WHEN r.reservation_id LIKE 'R_JOURNEY_%' THEN
          (SELECT sum(walkerhill_v4_3.v43_journey_pos_amount(substring(r.reservation_id,11)::int,meal_no))
           FROM generate_series(1,3) meal_no)
        ELSE 0 END,
       'CHECKED_OUT',false,false,false,true
FROM walkerhill_v4_3.pms_reservations r
JOIN walkerhill_v4_3.pms_room_types rt USING(hotel_code,room_type_code)
WHERE r.reservation_status='CHECKED_OUT';

WITH nightly AS (
  SELECT s.stay_id,s.reservation_id,r.hotel_code,r.room_type_code,r.discount_amount,r.booked_amount,
         d::date business_date,c.room_rate_day_type,
         round((rt.synthetic_base_rate_krw
           *CASE c.season_code WHEN 'SUMMER' THEN 1.12 WHEN 'AUTUMN' THEN 1.10 WHEN 'WINTER' THEN 1.05 ELSE 1.00 END
           *CASE c.room_rate_day_type WHEN 'FRIDAY' THEN 1.10 WHEN 'SATURDAY' THEN 1.28 ELSE 1.00 END
           *CASE WHEN c.is_holiday THEN 1.18 ELSE 1.00 END
           *(1+coalesce(ev.uplift_mode,0))
           *(CASE WHEN r.reservation_id LIKE 'R_BRIDGE_%'
                  THEN 0.96+0.08*walkerhill_v4_3.v43_u01('bridge-rate|'||r.hotel_code||'|'||to_char(r.checkin_date,'YYYY-MM-DD'))
                  ELSE 0.92+0.18*walkerhill_v4_3.v43_u01('rate|'||r.assigned_room_id||'|'||to_char(r.checkin_date,'YYYY-MM-DD')) END)
          )/1000,0)*1000 AS gross_room_rate,
         ev.event_id,
         row_number() OVER(PARTITION BY s.stay_id ORDER BY d DESC) AS reverse_night_no
  FROM walkerhill_v4_3.pms_stays s JOIN walkerhill_v4_3.pms_reservations r USING(reservation_id)
  JOIN walkerhill_v4_3.pms_room_types rt ON rt.hotel_code=r.hotel_code AND rt.room_type_code=r.room_type_code
  CROSS JOIN LATERAL generate_series(r.checkin_date,r.checkout_date-1,INTERVAL '1 day') d
  JOIN walkerhill_v4_3.calendar_daily c ON c.business_date=d::date
  LEFT JOIN LATERAL (
    SELECT em.event_id,he.uplift_mode
    FROM walkerhill_v4_3.event_master em JOIN walkerhill_v4_3.hotel_event_effect he USING(event_id)
    WHERE he.hotel_code=r.hotel_code AND he.domain='ROOMS' AND he.metric_name='ADR'
      AND d::date BETWEEN em.start_date-he.lead_days AND em.end_date+he.lag_days
    ORDER BY he.uplift_mode DESC,em.event_id LIMIT 1
  ) ev ON true
), allocated AS (
  SELECT n.*,
         round(n.gross_room_rate*n.discount_amount/nullif(n.discount_amount+n.booked_amount,0),0) AS rounded_discount
  FROM nightly n
), final AS (
  SELECT a.*,
         CASE WHEN reverse_night_no=1
              THEN discount_amount-(sum(rounded_discount) OVER(PARTITION BY stay_id)-rounded_discount)
              ELSE rounded_discount END AS nightly_discount
  FROM allocated a
)
INSERT INTO walkerhill_v4_3.pms_stay_nights
(stay_id,reservation_id,business_date,room_rate_day_type,gross_room_rate,discount_amount,net_room_revenue,event_id,is_synthetic)
SELECT stay_id,reservation_id,business_date,room_rate_day_type,gross_room_rate,nightly_discount,
       gross_room_rate-nightly_discount,event_id,true
FROM final;
