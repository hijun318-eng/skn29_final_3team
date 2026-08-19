-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=PMS; script_type=VALIDATION_READONLY; execution_order=50
-- dependencies=40_postgresql_pms_constraints_indexes.sql; expected_rows=24 checks
-- execution_default=NOT_RUN; destructive_operation=false
-- next=02_postgresql_banquet/00_postgresql_banquet_preflight_readonly.sql

WITH room_sequence AS (
  SELECT stay_id,room_id,actual_checkin_at,actual_checkout_at,
         lag(actual_checkout_at) OVER(PARTITION BY room_id ORDER BY actual_checkin_at,stay_id) AS previous_checkout
  FROM walkerhill_v4_3.pms_stays
), sold AS (
  SELECT s.hotel_code,s.room_type_code,d::date business_date,count(*) rooms_sold
  FROM walkerhill_v4_3.pms_stays s
  CROSS JOIN LATERAL generate_series((s.actual_checkin_at AT TIME ZONE 'Asia/Seoul')::date,
                                     (s.actual_checkout_at AT TIME ZONE 'Asia/Seoul')::date-1,INTERVAL '1 day') d
  GROUP BY 1,2,3
), folio AS (
  SELECT stay_id,sum(net_amount) amount FROM walkerhill_v4_3.pms_folio_postings GROUP BY stay_id
), nightly AS (
  SELECT stay_id,count(*) night_count,sum(net_room_revenue) room_revenue
  FROM walkerhill_v4_3.pms_stay_nights GROUP BY stay_id
), occupancy AS (
  SELECT i.hotel_code,sum(coalesce(s.rooms_sold,0))::numeric/nullif(sum(i.available_room_nights),0) occ
  FROM walkerhill_v4_3.pms_room_inventory_daily i
  LEFT JOIN sold s USING(hotel_code,room_type_code,business_date)
  GROUP BY i.hotel_code
), checks(check_name,violation_count,details) AS (
  SELECT 'pms_pk_duplicate',count(*),'reservation_id must be unique' FROM (SELECT reservation_id FROM walkerhill_v4_3.pms_reservations GROUP BY 1 HAVING count(*)>1) q
  UNION ALL
  SELECT 'pms_rate_day_mapping',count(*),'room rate day type must map Sunday-Thursday, Friday and Saturday separately' FROM walkerhill_v4_3.calendar_daily WHERE room_rate_day_type<>CASE day_of_week WHEN 5 THEN 'FRIDAY' WHEN 6 THEN 'SATURDAY' ELSE 'SUN_THU' END
  UNION ALL
  SELECT 'pms_2026_constitution_day_holiday',CASE WHEN EXISTS(SELECT 1 FROM walkerhill_v4_3.calendar_daily WHERE business_date=DATE '2026-07-17' AND is_holiday AND holiday_name='KOREA_PUBLIC_HOLIDAY') THEN 0 ELSE 1 END,'2026-07-17 must be stored as a Korean public holiday'
  UNION ALL
  SELECT 'pms_composite_room_type_fk',count(*),'hotel_code and room_type_code tuple must exist' FROM walkerhill_v4_3.pms_reservations r LEFT JOIN walkerhill_v4_3.pms_room_types t USING(hotel_code,room_type_code) WHERE t.room_type_code IS NULL
  UNION ALL
  SELECT 'pms_date_order',count(*),'booking, check-in and check-out order must be valid' FROM walkerhill_v4_3.pms_reservations WHERE booked_at>=(checkin_date::timestamp AT TIME ZONE 'Asia/Seoul') OR checkin_date>=checkout_date
  UNION ALL
  SELECT 'pms_cancelled_has_stay',count(*),'cancelled reservation cannot have stay' FROM walkerhill_v4_3.pms_reservations r JOIN walkerhill_v4_3.pms_stays s USING(reservation_id) WHERE r.reservation_status='CANCELLED'
  UNION ALL
  SELECT 'pms_room_overlap',count(*),'same room stay intervals cannot overlap' FROM room_sequence WHERE previous_checkout>actual_checkin_at
  UNION ALL
  SELECT 'pms_room_capacity',count(*),'rooms sold cannot exceed available rooms' FROM sold s JOIN walkerhill_v4_3.pms_room_inventory_daily i USING(hotel_code,room_type_code,business_date) WHERE s.rooms_sold>i.available_room_nights
  UNION ALL
  SELECT 'pms_ooo_sale_conflict',count(*),'out-of-order room cannot be occupied' FROM walkerhill_v4_3.pms_stays s JOIN walkerhill_v4_3.pms_room_out_of_order_periods o USING(room_id) WHERE tstzrange(s.actual_checkin_at,s.actual_checkout_at,'[)') && tstzrange(o.started_at,o.ended_at,'[)')
  UNION ALL
  SELECT 'pms_ooo_period_overlap',count(*),'out-of-order periods for the same room cannot overlap' FROM walkerhill_v4_3.pms_room_out_of_order_periods a JOIN walkerhill_v4_3.pms_room_out_of_order_periods b ON a.room_id=b.room_id AND a.out_of_order_id<b.out_of_order_id AND tstzrange(a.started_at,a.ended_at,'[)') && tstzrange(b.started_at,b.ended_at,'[)')
  UNION ALL
  SELECT 'pms_folio_equation',count(*),'posting components must reconcile' FROM walkerhill_v4_3.pms_folio_postings WHERE net_amount<>gross_amount-discount_amount+service_charge_amount+tax_amount-refund_amount
  UNION ALL
  SELECT 'pms_stay_folio_reconciliation',count(*),'folio net must equal stay room and other charges' FROM walkerhill_v4_3.pms_stays s LEFT JOIN folio f USING(stay_id) WHERE coalesce(f.amount,0)<>s.room_revenue+s.other_room_charges
  UNION ALL
  SELECT 'pms_stay_night_completeness',count(*),'one stay-night row must exist per occupied room night' FROM walkerhill_v4_3.pms_stays s LEFT JOIN nightly n USING(stay_id) WHERE coalesce(n.night_count,0)<>s.occupied_room_nights
  UNION ALL
  SELECT 'pms_stay_night_revenue_reconciliation',count(*),'stay-night net revenue must sum to stay room revenue' FROM walkerhill_v4_3.pms_stays s LEFT JOIN nightly n USING(stay_id) WHERE coalesce(n.room_revenue,0)<>s.room_revenue
  UNION ALL
  SELECT 'pms_stay_night_day_mapping',count(*),'stored room rate day type must match the calendar' FROM walkerhill_v4_3.pms_stay_nights n JOIN walkerhill_v4_3.calendar_daily c USING(business_date) WHERE n.room_rate_day_type<>c.room_rate_day_type
  UNION ALL
  SELECT 'pms_stay_guest_capacity',count(*),'registered guests must not exceed the room-type synthetic maximum' FROM walkerhill_v4_3.pms_stays s JOIN walkerhill_v4_3.pms_room_types t USING(hotel_code,room_type_code) WHERE s.guest_count>t.synthetic_max_occupancy
  UNION ALL
  SELECT 'pms_bridge_stay_coverage',abs(count(*)-2922),'three deterministic bridge stays must exist for every release date' FROM walkerhill_v4_3.pms_stays WHERE stay_id LIKE 'S_BRIDGE_%'
  UNION ALL
  SELECT 'pms_journey_stay_coverage',abs(count(*)-972),'972 deterministic multi-touch journeys must exist' FROM walkerhill_v4_3.pms_stays WHERE stay_id LIKE 'S_JOURNEY_%'
  UNION ALL
  SELECT 'pms_journey_multi_night',count(*),'journey stays must occupy two or three room nights' FROM walkerhill_v4_3.pms_stays WHERE stay_id LIKE 'S_JOURNEY_%' AND occupied_room_nights NOT BETWEEN 2 AND 3
  UNION ALL
  SELECT 'pms_folio_source_duplicate',count(*),'external source transaction must map to one folio posting' FROM (SELECT source_system,source_transaction_id FROM walkerhill_v4_3.pms_folio_postings WHERE source_transaction_id IS NOT NULL GROUP BY 1,2 HAVING count(*)<>1) q
  UNION ALL
  SELECT 'pms_banquet_bridge_coverage',abs(count(*)-2919),'one picked-up PMS reservation must exist for each seeded banquet room block' FROM walkerhill_v4_3.pms_reservations WHERE banquet_event_id IS NOT NULL
  UNION ALL
  SELECT 'pms_hotel_kpi_not_cloned',CASE WHEN count(DISTINCT round(occ,4))=count(*) THEN 0 ELSE 1 END,'hotel occupancy ratios must differ' FROM occupancy
  UNION ALL
  SELECT 'pms_reporting_scope_double_count',count(*),'rollup entity cannot be active physical inventory' FROM walkerhill_v4_3.hotel_entities WHERE inventory_scope='ROLLUP_ONLY' AND is_active
  UNION ALL
  SELECT 'pms_deterministic_known_vector',CASE WHEN walkerhill_v4_3.v43_u01('known-vector')=0.95631247857761910672::numeric THEN 0 ELSE 1 END,'known child key must reproduce the frozen SHA-256 vector'
)
SELECT check_name,violation_count,
       CASE WHEN violation_count=0 THEN 'PASS' ELSE 'FAIL' END AS status,details
FROM checks ORDER BY check_name;

SELECT 'row_count' AS check_name,table_name,row_count,expected_rows,
       CASE WHEN row_count=expected_rows THEN 'PASS' ELSE 'FAIL' END status
FROM (VALUES
 ('hotel_entities',(SELECT count(*) FROM walkerhill_v4_3.hotel_entities),4::bigint),
 ('calendar_daily',(SELECT count(*) FROM walkerhill_v4_3.calendar_daily),974::bigint),
 ('evidence_registry',(SELECT count(*) FROM walkerhill_v4_3.evidence_registry),15::bigint),
 ('event_master',(SELECT count(*) FROM walkerhill_v4_3.event_master),13::bigint),
 ('hotel_event_effect',(SELECT count(*) FROM walkerhill_v4_3.hotel_event_effect),195::bigint),
 ('pms_room_types',(SELECT count(*) FROM walkerhill_v4_3.pms_room_types),9::bigint),
 ('pms_rooms',(SELECT count(*) FROM walkerhill_v4_3.pms_rooms),801::bigint),
 ('pms_room_out_of_order_periods',(SELECT count(*) FROM walkerhill_v4_3.pms_room_out_of_order_periods),3915::bigint),
 ('pms_room_inventory_daily',(SELECT count(*) FROM walkerhill_v4_3.pms_room_inventory_daily),8766::bigint),
 ('pms_guests',(SELECT count(*) FROM walkerhill_v4_3.pms_guests),100000::bigint),
 ('pms_reservations',(SELECT count(*) FROM walkerhill_v4_3.pms_reservations),302466::bigint),
 ('pms_reservation_status_history',(SELECT count(*) FROM walkerhill_v4_3.pms_reservation_status_history),854098::bigint),
 ('pms_stays',(SELECT count(*) FROM walkerhill_v4_3.pms_stays),249166::bigint),
 ('pms_stay_nights',(SELECT count(*) FROM walkerhill_v4_3.pms_stay_nights),497777::bigint),
 ('pms_folio_postings',(SELECT count(*) FROM walkerhill_v4_3.pms_folio_postings),501248::bigint)
) v(table_name,row_count,expected_rows)
ORDER BY table_name;

SELECT e.event_id,s.hotel_code,count(*) occupied_room_nights,round(avg(n.net_room_revenue),0) adr_krw,
       round(sum(n.net_room_revenue),0) room_revenue_krw
FROM walkerhill_v4_3.pms_stay_nights n JOIN walkerhill_v4_3.pms_stays s USING(stay_id)
JOIN walkerhill_v4_3.event_master e ON n.business_date BETWEEN e.start_date AND e.end_date
GROUP BY e.event_id,s.hotel_code ORDER BY e.event_id,s.hotel_code;

SELECT n.room_rate_day_type,s.hotel_code,count(*) occupied_room_nights,
       round(avg(n.net_room_revenue),0) allocated_adr_krw
FROM walkerhill_v4_3.pms_stay_nights n JOIN walkerhill_v4_3.pms_stays s USING(stay_id)
GROUP BY n.room_rate_day_type,s.hotel_code ORDER BY s.hotel_code,n.room_rate_day_type;
