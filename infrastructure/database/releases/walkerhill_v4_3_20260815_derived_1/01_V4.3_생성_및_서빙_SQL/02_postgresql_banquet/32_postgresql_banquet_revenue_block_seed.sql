-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=banquet_db; target_schema=walkerhill_v4_3
-- domain=BANQUET; script_type=REVENUE_BLOCK_SEED; execution_order=32
-- dependencies=31_postgresql_banquet_status_history_seed.sql; expected_rows=31647
-- execution_default=NOT_RUN; destructive_operation=false
-- next=40_postgresql_banquet_constraints_indexes.sql

DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM walkerhill_v4_3.banquet_revenue_lines) OR EXISTS(SELECT 1 FROM walkerhill_v4_3.banquet_room_blocks) THEN
    RAISE EXCEPTION 'candidate revenue and block tables must be empty';
  END IF;
END $$;

WITH mix AS (
  SELECT b.*,
         greatest(0.15::numeric,least(0.34::numeric,
           CASE b.event_type WHEN 'CORPORATE' THEN 0.28 WHEN 'WEDDING' THEN 0.20 ELSE 0.23 END
           +(walkerhill_v4_3.v43_u01('banquet-venue-mix|'||b.banquet_event_id)-0.5)*0.08)) venue_ratio,
         greatest(0.08::numeric,least(0.22::numeric,
           CASE b.event_type WHEN 'CORPORATE' THEN 0.17 WHEN 'WEDDING' THEN 0.10 ELSE 0.14 END
           +(walkerhill_v4_3.v43_u01('banquet-equipment-mix|'||b.banquet_event_id)-0.5)*0.06)) equipment_ratio
  FROM walkerhill_v4_3.banquet_bookings b WHERE b.booking_status='COMPLETED'
), gross_mix AS (
  SELECT m.*,round(m.contracted_amount*m.venue_ratio,0) venue_gross,
         round(m.contracted_amount*m.equipment_ratio,0) equipment_gross
  FROM mix m
), lines AS (
  SELECT b.*,c.category,c.line_no,c.gross,
         round(c.gross*(0.01+0.04*walkerhill_v4_3.v43_u01('banquet-discount|'||b.banquet_event_id||'|'||c.line_no)),0) discount
  FROM gross_mix b CROSS JOIN LATERAL (VALUES
    ('VENUE',1,b.venue_gross),
    ('FOOD_BEVERAGE',2,b.contracted_amount-b.venue_gross-b.equipment_gross),
    ('EQUIPMENT_SERVICE',3,b.equipment_gross)
  ) c(category,line_no,gross)
)
INSERT INTO walkerhill_v4_3.banquet_revenue_lines
(revenue_line_id,banquet_event_id,recognized_date,revenue_category,gross_amount,discount_amount,reversal_amount,recognized_amount,cost_amount,revenue_status,is_synthetic)
SELECT 'BR_'||substr(encode(sha256(convert_to(banquet_event_id||'|'||line_no,'UTF8')),'hex'),1,32),banquet_event_id,event_date,category,
       gross,discount,0,gross-discount,round((gross-discount)*(0.34+0.18*walkerhill_v4_3.v43_u01('banquet-cost|'||banquet_event_id||'|'||line_no)),0),'RECOGNIZED',true
FROM lines;

INSERT INTO walkerhill_v4_3.banquet_room_blocks
(room_block_id,banquet_event_id,hotel_code,checkin_date,checkout_date,reserved_room_nights,pickup_room_nights,is_synthetic)
SELECT 'BB_'||substr(encode(sha256(convert_to(b.banquet_event_id,'UTF8')),'hex'),1,32),b.banquet_event_id,
       v.hotel_code,b.event_date-1,
       b.event_date-1+p.pickup_nights,
       p.pickup_nights
         +greatest(1,ceil(b.expected_guests/50.0)::int)+mod(substring(b.banquet_event_id,4)::int,4),
       p.pickup_nights,true
FROM walkerhill_v4_3.banquet_bookings b JOIN walkerhill_v4_3.banquet_venues v USING(venue_id)
CROSS JOIN LATERAL (
  SELECT least(
    1+mod(((substring(b.banquet_event_id,4)::int-1)/3)+(1+mod(substring(b.banquet_event_id,4)::int-1,3)),3),
    DATE '2026-09-01'-(b.event_date-1)
  ) AS pickup_nights
) p
WHERE substring(b.banquet_event_id,4)::int<=2919;
