-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=MySQL 8.4; target_database=walkerhill_v4_3
-- domain=POS; script_type=VALIDATION_READONLY; execution_order=50
-- dependencies=40_mysql_pos_constraints_indexes.sql; expected_rows=19 checks
-- execution_default=NOT_RUN; destructive_operation=false
-- next=04_sqlserver_crm/00_sqlserver_crm_preflight_readonly.sql

USE walkerhill_v4_3;
WITH item_totals AS (
 SELECT order_id,SUM(gross_amount) gross,SUM(discount_amount) discount FROM pos_order_items GROUP BY order_id
), payment_totals AS (
 SELECT order_id,SUM(signed_amount) paid FROM pos_payment_lines GROUP BY order_id
), hotel_stats AS (
 SELECT x.hotel_code,COUNT(*) orders,SUM(o.net_amount) revenue FROM pos_orders o JOIN pos_outlets x USING(outlet_id) GROUP BY x.hotel_code
), checks AS (
 SELECT 'pos_pk_duplicate' check_name,COUNT(*) violation_count,'order_id must be unique' details FROM (SELECT order_id FROM pos_orders GROUP BY order_id HAVING COUNT(*)>1) q
 UNION ALL SELECT 'pos_outlet_fk',COUNT(*),'outlet must exist' FROM pos_orders o LEFT JOIN pos_outlets x USING(outlet_id) WHERE x.outlet_id IS NULL
 UNION ALL SELECT 'pos_item_header_reconciliation',COUNT(*),'item gross and discount must match order header' FROM pos_orders o LEFT JOIN item_totals i USING(order_id) WHERE COALESCE(i.gross,0)<>o.item_gross_amount OR COALESCE(i.discount,0)<>o.discount_amount
 UNION ALL SELECT 'pos_order_equation',COUNT(*),'order components must reconcile' FROM pos_orders WHERE net_amount<>item_gross_amount-discount_amount+service_charge_amount+tax_amount-refund_amount-void_amount
 UNION ALL SELECT 'pos_payment_reconciliation',COUNT(*),'signed payments must equal order net' FROM pos_orders o LEFT JOIN payment_totals p USING(order_id) WHERE COALESCE(p.paid,0)<>o.net_amount
 UNION ALL SELECT 'pos_menu_price_effective',COUNT(*),'ordered item must have an effective menu price' FROM pos_order_items i JOIN pos_orders o USING(order_id) LEFT JOIN pos_menu_price_history h ON h.item_code=i.item_code AND o.business_date>=h.valid_from AND (h.valid_to IS NULL OR o.business_date<=h.valid_to) WHERE h.item_code IS NULL
 UNION ALL SELECT 'pos_order_outside_outlet_hours',COUNT(*),'ordered_at must fall inside the outlet business interval, including overnight service' FROM pos_orders o JOIN pos_outlets x USING(outlet_id) WHERE NOT (o.ordered_at>=TIMESTAMP(o.business_date,x.open_time) AND o.ordered_at<TIMESTAMP(CASE WHEN x.close_time<=x.open_time THEN DATE_ADD(o.business_date,INTERVAL 1 DAY) ELSE o.business_date END,x.close_time))
 UNION ALL SELECT 'pos_service_period_time_mismatch',COUNT(*),'service period must be derived from ordered_at and late-opening outlets cannot emit breakfast' FROM pos_orders WHERE service_period<>CASE WHEN HOUR(ordered_at) BETWEEN 6 AND 10 THEN 'BREAKFAST' WHEN HOUR(ordered_at) BETWEEN 11 AND 14 THEN 'LUNCH' WHEN HOUR(ordered_at) BETWEEN 15 AND 21 THEN 'DINNER' ELSE 'LATE_NIGHT' END
 UNION ALL SELECT 'pos_room_charge_without_stay',COUNT(*),'ROOM_CHARGE payment must carry a PMS stay id' FROM pos_payment_lines p JOIN pos_orders o USING(order_id) WHERE p.transaction_type='SALE' AND p.tender_type='ROOM_CHARGE' AND o.linked_stay_id IS NULL
 UNION ALL SELECT 'pos_room_charge_non_journey',COUNT(*),'ROOM_CHARGE is reserved for folio-backed journey stays' FROM pos_payment_lines p JOIN pos_orders o USING(order_id) WHERE p.transaction_type='SALE' AND p.tender_type='ROOM_CHARGE' AND o.linked_stay_id NOT LIKE 'S_JOURNEY_%'
 UNION ALL SELECT 'pos_journey_without_room_charge',COUNT(*),'every journey order must have a SALE ROOM_CHARGE payment' FROM pos_orders o LEFT JOIN pos_payment_lines p ON p.order_id=o.order_id AND p.transaction_type='SALE' AND p.tender_type='ROOM_CHARGE' WHERE o.linked_stay_id LIKE 'S_JOURNEY_%' AND p.payment_line_id IS NULL
 UNION ALL SELECT 'pos_bridge_room_charge',COUNT(*),'bridge stay links represent in-stay usage and must use a non-room tender' FROM pos_orders o JOIN pos_payment_lines p ON p.order_id=o.order_id AND p.transaction_type='SALE' AND p.tender_type='ROOM_CHARGE' WHERE o.linked_stay_id LIKE 'S_BRIDGE_%'
 UNION ALL SELECT 'pos_journey_linked_order_count',ABS(COUNT(*)-2916),'972 multi-night journeys must have three linked orders each' FROM pos_orders WHERE linked_stay_id LIKE 'S_JOURNEY_%'
 UNION ALL SELECT 'pos_bridge_linked_order_count',ABS(COUNT(*)-101573),'deterministic in-stay bridge linkage must remain intact' FROM pos_orders WHERE linked_stay_id LIKE 'S_BRIDGE_%'
 UNION ALL SELECT 'pos_journey_multi_day_pattern',COUNT(*),'each journey must contain three orders across check-in day and the following stay day' FROM (SELECT linked_stay_id FROM pos_orders WHERE linked_stay_id LIKE 'S_JOURNEY_%' GROUP BY linked_stay_id HAVING COUNT(*)<>3 OR COUNT(DISTINCT business_date)<>2) q
 UNION ALL SELECT 'pos_amount_diversity',IF(COUNT(DISTINCT item_gross_amount)>=1000,0,1),'order amounts must not be cloned' FROM pos_orders
 UNION ALL SELECT 'pos_hotel_profiles_not_cloned',IF(COUNT(DISTINCT orders)=COUNT(*),0,1),'hotel order volumes must differ' FROM hotel_stats
 UNION ALL SELECT 'pos_date_range',COUNT(*),'business date must be inside the release period' FROM pos_orders WHERE business_date<DATE '2024-01-01' OR business_date>DATE '2026-08-31'
 UNION ALL SELECT 'pos_deterministic_known_vector',IF(v43_u01('known-vector')=CAST(0.956312478577619107 AS DECIMAL(20,18)),0,1),'known child key must reproduce the frozen SHA-256 vector'
)
SELECT check_name,violation_count,IF(violation_count=0,'PASS','FAIL') status,details FROM checks ORDER BY check_name;

SELECT 'row_count' check_name,table_name,row_count,expected_rows,
       IF(row_count=expected_rows,'PASS','FAIL') status FROM (
 SELECT 'pos_outlets' table_name,COUNT(*) row_count,12 expected_rows FROM pos_outlets
 UNION ALL SELECT 'pos_menu_items',COUNT(*),72 FROM pos_menu_items
 UNION ALL SELECT 'pos_menu_price_history',COUNT(*),216 FROM pos_menu_price_history
 UNION ALL SELECT 'pos_orders',COUNT(*),733000 FROM pos_orders
 UNION ALL SELECT 'pos_order_items',COUNT(*),1829312 FROM pos_order_items
 UNION ALL SELECT 'pos_payment_lines',COUNT(*),762203 FROM pos_payment_lines
) q ORDER BY table_name;

SELECT x.hotel_code,
       CASE WHEN o.business_date BETWEEN DATE '2024-09-01' AND DATE '2024-10-31' THEN 'E2024_AUTUMN'
            WHEN o.business_date BETWEEN DATE '2024-12-01' AND DATE '2024-12-31' THEN 'E2024_YEAR_END'
            WHEN o.business_date BETWEEN DATE '2025-06-21' AND DATE '2025-07-20' THEN 'E2025_GOLF_OPEN'
            WHEN o.business_date BETWEEN DATE '2025-09-01' AND DATE '2025-11-30' THEN 'E2025_AUTUMN'
            WHEN o.business_date BETWEEN DATE '2026-04-22' AND DATE '2026-06-07' THEN 'E2026_SPRING_JAZZ'
            WHEN o.business_date BETWEEN DATE '2026-06-26' AND DATE '2026-08-30' THEN 'E2026_RIVERPARK'
            ELSE 'BASELINE' END event_bucket,
       COUNT(*) orders,COUNT(DISTINCT o.business_date) active_days,
       ROUND(COUNT(*)/COUNT(DISTINCT o.business_date),2) orders_per_day,
       ROUND(SUM(o.net_amount)/COUNT(DISTINCT o.business_date),0) revenue_per_day_krw
FROM pos_orders o JOIN pos_outlets x USING(outlet_id)
GROUP BY x.hotel_code,event_bucket ORDER BY x.hotel_code,event_bucket;
