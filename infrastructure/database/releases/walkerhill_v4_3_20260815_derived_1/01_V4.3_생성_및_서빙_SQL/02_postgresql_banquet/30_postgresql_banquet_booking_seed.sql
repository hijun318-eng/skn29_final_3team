-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=banquet_db; target_schema=walkerhill_v4_3
-- domain=BANQUET; script_type=BOOKING_SEED; execution_order=30
-- dependencies=20_postgresql_banquet_venue_seed.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814; expected_rows=10660
-- execution_default=NOT_RUN; destructive_operation=false
-- next=31_postgresql_banquet_status_history_seed.sql

DO $$ BEGIN IF EXISTS(SELECT 1 FROM walkerhill_v4_3.banquet_bookings) THEN RAISE EXCEPTION 'candidate booking table must be empty'; END IF; END $$;
WITH venues AS (
  SELECT v.*,row_number() OVER(ORDER BY venue_id) rn FROM walkerhill_v4_3.banquet_venues v
), plan AS (
  SELECT n,mod((n-2920)*7919,13636) AS slot_id,
         14+mod(n*37,211) AS lead_days,
         walkerhill_v4_3.v43_u01('event-size|'||n) size_u,
         walkerhill_v4_3.v43_u01('event-type|'||n) type_u
  FROM generate_series(1,10660) n
), shaped AS (
  SELECT p.*,v.venue_id,v.hotel_code,v.synthetic_capacity,
         CASE WHEN p.n<=2919 THEN DATE '2024-01-02'+((p.n-1)/3)
              ELSE DATE '2024-01-01'+floor(p.slot_id/14)::int END AS event_date,
         CASE WHEN p.n<=2919 THEN 'EVENING'
              WHEN mod(floor(p.slot_id/7)::int,2)=0 THEN 'MORNING' ELSE 'AFTERNOON' END AS event_slot,
         greatest(10,least(v.synthetic_capacity,floor(v.synthetic_capacity*(0.08+0.78*p.size_u))::int)) expected_guests,
         CASE WHEN p.n<=2919 OR mod(p.n*17,100)<86 THEN 'COMPLETED' ELSE 'CANCELLED' END booking_status
  FROM plan p JOIN venues v ON v.venue_id=
    CASE WHEN p.n<=2919 THEN CASE mod(p.n-1,3) WHEN 0 THEN 'VENUE_GRAND_HALL' WHEN 1 THEN 'VENUE_VISTA_HALL' ELSE 'VENUE_FOREST' END
         ELSE (SELECT venue_id FROM venues WHERE rn=1+mod(p.slot_id,7)) END
), amounts AS (
  SELECT s.*,round((3500000+expected_guests*(65000+walkerhill_v4_3.v43_u01('per-head|'||n)*115000))::numeric,-3) quoted_amount
  FROM shaped s
), contracted AS (
  SELECT a.*,round(a.quoted_amount*(0.94+0.04*walkerhill_v4_3.v43_u01('contract|'||a.n)),-3) contracted_amount
  FROM amounts a
)
INSERT INTO walkerhill_v4_3.banquet_bookings
(banquet_event_id,banquet_customer_id,venue_id,inquiry_at,quoted_at,confirmed_at,cancelled_at,event_date,event_slot,starts_at,ends_at,event_type,
 booking_status,expected_guests,actual_attendees,quoted_amount,contracted_amount,deposit_amount,balance_amount,cancellation_fee_amount,currency_code,is_synthetic)
SELECT 'BE_'||lpad(n::text,10,'0'),'B'||lpad((1+mod(n*3571,100000))::text,9,'0'),venue_id,
       ((event_date-lead_days)::timestamp+TIME '10:00') AT TIME ZONE 'Asia/Seoul',
       ((event_date-lead_days+3)::timestamp+TIME '14:00') AT TIME ZONE 'Asia/Seoul',
       ((event_date-greatest(7,lead_days/2))::timestamp+TIME '11:00') AT TIME ZONE 'Asia/Seoul',
       CASE WHEN booking_status='CANCELLED' THEN ((event_date-greatest(2,lead_days/3))::timestamp+TIME '16:00') AT TIME ZONE 'Asia/Seoul' END,
       event_date,event_slot,
       (event_date::timestamp+CASE event_slot WHEN 'MORNING' THEN TIME '09:00' WHEN 'AFTERNOON' THEN TIME '13:00' ELSE TIME '18:00' END) AT TIME ZONE 'Asia/Seoul',
       (event_date::timestamp+CASE event_slot WHEN 'MORNING' THEN TIME '12:00' WHEN 'AFTERNOON' THEN TIME '17:00' ELSE TIME '22:00' END) AT TIME ZONE 'Asia/Seoul',
       CASE WHEN type_u<0.34 THEN 'CORPORATE' WHEN type_u<0.56 THEN 'WEDDING' WHEN type_u<0.74 THEN 'SOCIAL' WHEN type_u<0.90 THEN 'CONFERENCE' ELSE 'CULTURE' END,
       booking_status,expected_guests,
       CASE WHEN booking_status='COMPLETED' THEN least(synthetic_capacity,round(expected_guests*(0.84+0.20*walkerhill_v4_3.v43_u01('attendance|'||n)))::int) END,
       quoted_amount,contracted_amount,round(contracted_amount*0.30,0),
       CASE WHEN booking_status='COMPLETED' THEN contracted_amount-round(contracted_amount*0.30,0) ELSE 0 END,
       CASE WHEN booking_status='CANCELLED' THEN round(contracted_amount*0.10,0) ELSE 0 END,
       'KRW',true
FROM contracted;
