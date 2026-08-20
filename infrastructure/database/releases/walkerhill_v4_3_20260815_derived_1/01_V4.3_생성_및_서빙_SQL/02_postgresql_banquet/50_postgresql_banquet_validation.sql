-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=banquet_db; target_schema=walkerhill_v4_3
-- domain=BANQUET; script_type=VALIDATION_READONLY; execution_order=50
-- dependencies=40_postgresql_banquet_constraints_indexes.sql; expected_rows=14 checks
-- execution_default=NOT_RUN; destructive_operation=false
-- next=03_mysql_pos/00_mysql_pos_preflight_readonly.sql

WITH history_order AS (
  SELECT banquet_event_id,status_code,status_at,
         CASE status_code WHEN 'INQUIRY' THEN 1 WHEN 'QUOTED' THEN 2 WHEN 'CONFIRMED' THEN 3 ELSE 4 END status_rank,
         lag(CASE status_code WHEN 'INQUIRY' THEN 1 WHEN 'QUOTED' THEN 2 WHEN 'CONFIRMED' THEN 3 ELSE 4 END)
           OVER(PARTITION BY banquet_event_id ORDER BY status_at,status_history_id) previous_rank
  FROM walkerhill_v4_3.banquet_status_history
), revenue_mix AS (
  SELECT banquet_event_id,sum(gross_amount) gross_total,
         max(gross_amount) FILTER(WHERE revenue_category='VENUE')/nullif(sum(gross_amount),0) venue_share,
         max(gross_amount) FILTER(WHERE revenue_category='EQUIPMENT_SERVICE')/nullif(sum(gross_amount),0) equipment_share
  FROM walkerhill_v4_3.banquet_revenue_lines GROUP BY banquet_event_id
), checks(check_name,violation_count,details) AS (
  SELECT 'banquet_pk_duplicate',count(*),'banquet_event_id must be unique' FROM (SELECT banquet_event_id FROM walkerhill_v4_3.banquet_bookings GROUP BY 1 HAVING count(*)>1) q
  UNION ALL SELECT 'banquet_venue_fk',count(*),'venue must exist' FROM walkerhill_v4_3.banquet_bookings b LEFT JOIN walkerhill_v4_3.banquet_venues v USING(venue_id) WHERE v.venue_id IS NULL
  UNION ALL SELECT 'banquet_capacity',count(*),'attendees cannot exceed synthetic venue capacity' FROM walkerhill_v4_3.banquet_bookings b JOIN walkerhill_v4_3.banquet_venues v USING(venue_id) WHERE greatest(b.expected_guests,coalesce(b.actual_attendees,0))>v.synthetic_capacity
  UNION ALL SELECT 'banquet_status_transition',count(*),'lifecycle must progress INQUIRY to QUOTED to CONFIRMED to COMPLETED or CANCELLED' FROM history_order WHERE previous_rank IS NOT NULL AND status_rank<>previous_rank+1
  UNION ALL SELECT 'banquet_status_terminal_match',count(*),'exactly four lifecycle rows and the last status must match booking_status' FROM walkerhill_v4_3.banquet_bookings b WHERE (SELECT count(*) FROM walkerhill_v4_3.banquet_status_history h WHERE h.banquet_event_id=b.banquet_event_id)<>4 OR (SELECT h.status_code FROM walkerhill_v4_3.banquet_status_history h WHERE h.banquet_event_id=b.banquet_event_id ORDER BY h.status_at DESC,h.status_history_id DESC LIMIT 1)<>b.booking_status
  UNION ALL SELECT 'banquet_venue_time_overlap',count(*),'same venue event intervals cannot overlap' FROM walkerhill_v4_3.banquet_bookings a JOIN walkerhill_v4_3.banquet_bookings b ON a.venue_id=b.venue_id AND a.banquet_event_id<b.banquet_event_id AND tstzrange(a.starts_at,a.ends_at,'[)') && tstzrange(b.starts_at,b.ends_at,'[)')
  UNION ALL SELECT 'banquet_cancelled_revenue',count(*),'cancelled event cannot have recognized revenue' FROM walkerhill_v4_3.banquet_bookings b JOIN walkerhill_v4_3.banquet_revenue_lines r USING(banquet_event_id) WHERE b.booking_status='CANCELLED' AND r.recognized_amount<>0
  UNION ALL SELECT 'banquet_revenue_equation',count(*),'recognized amount must reconcile' FROM walkerhill_v4_3.banquet_revenue_lines WHERE recognized_amount<>gross_amount-discount_amount-reversal_amount
  UNION ALL SELECT 'banquet_revenue_gross_contract',count(*),'completed event revenue-line gross must equal contracted amount' FROM walkerhill_v4_3.banquet_bookings b LEFT JOIN revenue_mix r USING(banquet_event_id) WHERE b.booking_status='COMPLETED' AND coalesce(r.gross_total,0)<>b.contracted_amount
  UNION ALL SELECT 'banquet_revenue_mix_diversity',CASE WHEN count(DISTINCT round(venue_share,3))>=20 AND count(DISTINCT round(equipment_share,3))>=20 THEN 0 ELSE 1 END,'venue and equipment shares must vary by event type and deterministic child seed' FROM revenue_mix
  UNION ALL SELECT 'banquet_room_block_pickup',count(*),'pickup cannot exceed reserved room nights' FROM walkerhill_v4_3.banquet_room_blocks WHERE pickup_room_nights>reserved_room_nights
  UNION ALL SELECT 'banquet_room_block_pickup_diversity',CASE WHEN count(DISTINCT pickup_room_nights)>=3 AND count(DISTINCT reserved_room_nights)>=6 THEN 0 ELSE 1 END,'pickup and reserved room nights must not be cloned' FROM walkerhill_v4_3.banquet_room_blocks
  UNION ALL SELECT 'banquet_cashflow_reconciliation',count(*),'completed deposit plus balance equals contract; cancelled balance is zero and fee cannot exceed deposit' FROM walkerhill_v4_3.banquet_bookings WHERE (booking_status='COMPLETED' AND (deposit_amount+balance_amount<>contracted_amount OR cancellation_fee_amount<>0)) OR (booking_status='CANCELLED' AND (balance_amount<>0 OR cancellation_fee_amount>deposit_amount))
  UNION ALL SELECT 'banquet_hotel_codes',count(*),'room block hotel must be in approved scope' FROM walkerhill_v4_3.banquet_room_blocks WHERE hotel_code NOT IN('GRAND','VISTA','DOUGLAS')
)
SELECT check_name,violation_count,CASE WHEN violation_count=0 THEN 'PASS' ELSE 'FAIL' END status,details FROM checks ORDER BY check_name;

SELECT 'row_count' check_name,table_name,row_count,expected_rows,
       CASE WHEN row_count=expected_rows THEN 'PASS' ELSE 'FAIL' END status FROM (VALUES
 ('banquet_venues',(SELECT count(*) FROM walkerhill_v4_3.banquet_venues),7::bigint),
 ('banquet_bookings',(SELECT count(*) FROM walkerhill_v4_3.banquet_bookings),10660::bigint),
 ('banquet_status_history',(SELECT count(*) FROM walkerhill_v4_3.banquet_status_history),42640::bigint),
 ('banquet_revenue_lines',(SELECT count(*) FROM walkerhill_v4_3.banquet_revenue_lines),28728::bigint),
 ('banquet_room_blocks',(SELECT count(*) FROM walkerhill_v4_3.banquet_room_blocks),2919::bigint)
) v(table_name,row_count,expected_rows) ORDER BY table_name;

SELECT v.hotel_code,
       CASE WHEN b.event_date BETWEEN DATE '2024-09-01' AND DATE '2024-10-31' THEN 'E2024_AUTUMN'
            WHEN b.event_date BETWEEN DATE '2024-12-01' AND DATE '2024-12-31' THEN 'E2024_YEAR_END'
            WHEN b.event_date BETWEEN DATE '2025-09-01' AND DATE '2025-11-30' THEN 'E2025_AUTUMN'
            WHEN b.event_date BETWEEN DATE '2026-04-22' AND DATE '2026-06-07' THEN 'E2026_SPRING_JAZZ'
            WHEN b.event_date BETWEEN DATE '2026-06-26' AND DATE '2026-08-30' THEN 'E2026_RIVERPARK'
            ELSE 'BASELINE' END event_bucket,
       count(*) bookings,count(*) FILTER(WHERE b.booking_status='COMPLETED') completed_events,
       round(sum(CASE WHEN b.booking_status='COMPLETED' THEN b.contracted_amount ELSE 0 END),0) completed_contract_krw
FROM walkerhill_v4_3.banquet_bookings b JOIN walkerhill_v4_3.banquet_venues v USING(venue_id)
GROUP BY v.hotel_code,event_bucket ORDER BY v.hotel_code,event_bucket;
