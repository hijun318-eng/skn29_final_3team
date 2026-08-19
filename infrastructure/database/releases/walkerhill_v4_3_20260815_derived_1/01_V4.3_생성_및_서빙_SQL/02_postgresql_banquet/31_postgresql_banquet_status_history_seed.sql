-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=banquet_db; target_schema=walkerhill_v4_3
-- domain=BANQUET; script_type=STATUS_HISTORY_SEED; execution_order=31
-- dependencies=30_postgresql_banquet_booking_seed.sql; expected_rows=42640
-- execution_default=NOT_RUN; destructive_operation=false
-- next=32_postgresql_banquet_revenue_block_seed.sql

DO $$ BEGIN IF EXISTS(SELECT 1 FROM walkerhill_v4_3.banquet_status_history) THEN RAISE EXCEPTION 'candidate status history must be empty'; END IF; END $$;
INSERT INTO walkerhill_v4_3.banquet_status_history
(status_history_id,banquet_event_id,status_code,status_at,reason_code,is_synthetic)
SELECT 'BH_'||substr(encode(sha256(convert_to(b.banquet_event_id||'|'||h.status_code,'UTF8')),'hex'),1,32),
       b.banquet_event_id,h.status_code,h.status_at,h.reason_code,true
FROM walkerhill_v4_3.banquet_bookings b
CROSS JOIN LATERAL (
  VALUES ('INQUIRY',b.inquiry_at,NULL::varchar),('QUOTED',b.quoted_at,NULL::varchar),
         ('CONFIRMED',b.confirmed_at,NULL::varchar),
         (CASE WHEN b.booking_status='COMPLETED' THEN 'COMPLETED' WHEN b.booking_status='CANCELLED' THEN 'CANCELLED' ELSE NULL END,
          CASE WHEN b.booking_status='COMPLETED' THEN (b.event_date::timestamp+TIME '23:00') AT TIME ZONE 'Asia/Seoul' ELSE b.cancelled_at END,
          CASE WHEN b.booking_status='CANCELLED' THEN 'CLIENT_CHANGE' END)
) h(status_code,status_at,reason_code)
WHERE h.status_code IS NOT NULL AND h.status_at IS NOT NULL;
