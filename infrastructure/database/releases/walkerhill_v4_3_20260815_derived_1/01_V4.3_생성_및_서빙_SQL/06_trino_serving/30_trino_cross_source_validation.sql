-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING; script_type=VALIDATION_READONLY; execution_order=30
-- dependency=26_trino_voc_views.sql; execution_default=NOT_RUN
-- gate_rule=all violation_count values must be 0 before publishing the serving schema

SELECT 'duplicate_hotel_operations_daily_key' check_name,COUNT(*) violation_count,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END status
FROM (SELECT business_date,hotel_code FROM serving.analytics_v4_3.hotel_operations_daily GROUP BY 1,2 HAVING COUNT(*)>1);

SELECT 'duplicate_hotel_voc_signal_daily_key' check_name,COUNT(*) violation_count,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END status
FROM (SELECT business_date,hotel_code FROM serving.analytics_v4_3.hotel_voc_signal_daily GROUP BY 1,2 HAVING COUNT(*)>1);

SELECT 'occupancy_out_of_range' check_name,COUNT(*) violation_count,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END status
FROM serving.analytics_v4_3.room_daily WHERE occupancy_rate<0 OR occupancy_rate>1;

SELECT 'negative_integrated_revenue' check_name,COUNT(*) violation_count,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END status
FROM serving.analytics_v4_3.hotel_operations_daily WHERE total_operating_revenue_krw<0;

SELECT 'serving_ghost_hotel' check_name,COUNT(*) violation_count,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END status
FROM serving.analytics_v4_3.hotel_operations_daily WHERE hotel_code NOT IN('GRAND','VISTA','DOUGLAS');

WITH facility_scoped AS (
 SELECT u.usage_event_id,u.user_ref,u.facility_id,CAST(u.event_time AS date) business_date,
        m.reporting_hotel_code hotel_code
 FROM facility.walkerhill_v4_3.facility_usage_events u
 JOIN facility.walkerhill_v4_3.facility_master m ON m.facility_id=u.facility_id
), checks AS (
 SELECT 'pms_customer_map_orphan' check_name,COUNT(*) violation_count
 FROM crm.walkerhill_v4_3.crm_customer_map m LEFT JOIN pms.walkerhill_v4_3.pms_guests g ON g.guest_id=m.pms_guest_id
 WHERE m.pms_guest_id IS NOT NULL AND g.guest_id IS NULL
 UNION ALL SELECT 'pos_order_customer_map_orphan',COUNT(*)
 FROM pos.walkerhill_v4_3.pos_orders o LEFT JOIN crm.walkerhill_v4_3.crm_customer_map m ON m.pos_customer_ref=o.pos_customer_ref
 WHERE o.pos_customer_ref IS NOT NULL AND m.member_no IS NULL
 UNION ALL SELECT 'facility_user_customer_map_orphan',COUNT(*)
 FROM facility_scoped u LEFT JOIN crm.walkerhill_v4_3.crm_customer_map m ON m.facility_user_ref=u.user_ref
 WHERE u.user_ref IS NOT NULL AND m.member_no IS NULL
 UNION ALL SELECT 'banquet_customer_map_orphan',COUNT(*)
 FROM banquet.walkerhill_v4_3.banquet_bookings b LEFT JOIN crm.walkerhill_v4_3.crm_customer_map m ON m.banquet_customer_id=b.banquet_customer_id
 WHERE m.member_no IS NULL
 UNION ALL SELECT 'crm_point_pms_guest_orphan',COUNT(*)
 FROM crm.walkerhill_v4_3.crm_point_transactions p LEFT JOIN pms.walkerhill_v4_3.pms_guests g ON g.guest_id=p.related_id
 WHERE p.related_source='PMS_GUEST' AND g.guest_id IS NULL
)
SELECT check_name,violation_count,CASE WHEN violation_count=0 THEN 'PASS' ELSE 'FAIL' END status
FROM checks ORDER BY check_name;

WITH banquet_pickup AS (
 SELECT banquet_event_id,hotel_code,MIN(checkin_date) checkin_date,MAX(checkout_date) checkout_date,
        SUM(DATE_DIFF('day',checkin_date,checkout_date)) pickup_room_nights
 FROM pms.walkerhill_v4_3.pms_reservations
 WHERE banquet_event_id IS NOT NULL AND reservation_status='CHECKED_OUT'
 GROUP BY 1,2
), checks AS (
 SELECT 'crm_point_pos_semantic_mismatch' check_name,COUNT(*) violation_count
 FROM crm.walkerhill_v4_3.crm_point_transactions p
 LEFT JOIN pos.walkerhill_v4_3.pos_orders o ON o.order_id=p.related_id
 LEFT JOIN crm.walkerhill_v4_3.crm_customer_map m ON m.pos_customer_ref=o.pos_customer_ref
 WHERE p.related_source='POS_ORDER' AND (o.order_id IS NULL OR o.pos_customer_ref IS NULL
    OR m.member_no IS DISTINCT FROM p.member_no
    OR CAST(p.event_at AT TIME ZONE 'Asia/Seoul' AS date) < o.business_date
    OR CAST(p.event_at AT TIME ZONE 'Asia/Seoul' AS date) > o.business_date+INTERVAL '2' DAY)
 UNION ALL SELECT 'journey_pos_point_amount_mismatch',COUNT(*)
 FROM crm.walkerhill_v4_3.crm_point_transactions p
 JOIN pos.walkerhill_v4_3.pos_orders o ON o.order_id=p.related_id
 WHERE p.related_source='POS_ORDER' AND o.linked_stay_id LIKE 'S_JOURNEY_%'
   AND p.points_delta<>CAST((o.item_gross_amount-o.discount_amount)*DECIMAL '0.05' AS bigint)
 UNION ALL SELECT 'pos_linked_stay_semantic_mismatch',COUNT(*)
 FROM pos.walkerhill_v4_3.pos_orders o JOIN pos.walkerhill_v4_3.pos_outlets x ON x.outlet_id=o.outlet_id
 LEFT JOIN pms.walkerhill_v4_3.pms_stays s ON s.stay_id=o.linked_stay_id
 WHERE o.linked_stay_id IS NOT NULL AND (s.stay_id IS NULL OR s.hotel_code<>x.hotel_code
     OR o.business_date NOT BETWEEN CAST(s.actual_checkin_at AT TIME ZONE 'Asia/Seoul' AS date)
                                AND CAST(s.actual_checkout_at AT TIME ZONE 'Asia/Seoul' AS date)-INTERVAL '1' DAY)
 UNION ALL SELECT 'pos_room_charge_folio_mismatch',COUNT(*)
 FROM pos.walkerhill_v4_3.pos_payment_lines p
 JOIN pos.walkerhill_v4_3.pos_orders o ON o.order_id=p.order_id
 LEFT JOIN pms.walkerhill_v4_3.pms_folio_postings f
   ON f.source_system='POS' AND f.source_transaction_id=o.order_id
 WHERE p.transaction_type='SALE' AND p.tender_type='ROOM_CHARGE'
   AND (o.linked_stay_id IS NULL OR f.folio_posting_id IS NULL OR f.stay_id<>o.linked_stay_id
     OR f.posting_type<>'POS_ROOM_CHARGE' OR f.net_amount<>o.net_amount)
 UNION ALL SELECT 'journey_touchpoint_completeness',COUNT(*)
 FROM (
   SELECT s.stay_id
   FROM pms.walkerhill_v4_3.pms_stays s
   LEFT JOIN pos.walkerhill_v4_3.pos_orders o ON o.linked_stay_id=s.stay_id
   LEFT JOIN crm.walkerhill_v4_3.crm_voc_reviews v ON v.related_source='PMS_STAY' AND v.related_id=s.stay_id
   WHERE s.stay_id LIKE 'S_JOURNEY_%'
   GROUP BY s.stay_id
   HAVING COUNT(DISTINCT o.order_id)<>3 OR COUNT(DISTINCT o.business_date)<>2 OR COUNT(DISTINCT v.voc_review_id)<>1
 ) q
 UNION ALL SELECT 'banquet_room_block_pickup_mismatch',COUNT(*)
 FROM banquet.walkerhill_v4_3.banquet_room_blocks b
 LEFT JOIN banquet.walkerhill_v4_3.banquet_bookings e ON e.banquet_event_id=b.banquet_event_id
 LEFT JOIN banquet_pickup p ON p.banquet_event_id=b.banquet_event_id AND p.hotel_code=b.hotel_code
 WHERE e.banquet_event_id IS NULL OR p.banquet_event_id IS NULL OR e.booking_status<>'COMPLETED'
    OR b.checkin_date<>p.checkin_date OR b.checkout_date<>p.checkout_date OR b.pickup_room_nights<>p.pickup_room_nights
 UNION ALL SELECT 'facility_event_orphan',COUNT(*)
 FROM facility.walkerhill_v4_3.facility_usage_events u LEFT JOIN pms.walkerhill_v4_3.event_master e ON e.event_id=u.event_id
 WHERE u.event_id IS NOT NULL AND e.event_id IS NULL
)
SELECT check_name,violation_count,CASE WHEN violation_count=0 THEN 'PASS' ELSE 'FAIL' END status
FROM checks ORDER BY check_name;

WITH facility_scoped AS (
 SELECT u.usage_event_id,u.user_ref,u.facility_id,CAST(u.event_time AS date) business_date,
        m.reporting_hotel_code hotel_code
 FROM facility.walkerhill_v4_3.facility_usage_events u
 JOIN facility.walkerhill_v4_3.facility_master m ON m.facility_id=u.facility_id
), checks AS (
 SELECT 'voc_hotel_orphan' check_name,COUNT(*) violation_count
 FROM crm.walkerhill_v4_3.crm_voc_reviews v LEFT JOIN pms.walkerhill_v4_3.hotel_entities h ON h.hotel_code=v.hotel_code
 WHERE h.hotel_code IS NULL
 UNION ALL SELECT 'voc_pms_stay_semantic_mismatch',COUNT(*)
 FROM crm.walkerhill_v4_3.crm_voc_reviews v
 LEFT JOIN pms.walkerhill_v4_3.pms_stays s ON s.stay_id=v.related_id
 LEFT JOIN crm.walkerhill_v4_3.crm_customer_map m ON m.pms_guest_id=s.guest_id
 WHERE v.related_source='PMS_STAY' AND (s.stay_id IS NULL OR v.hotel_code<>s.hotel_code
    OR v.source_business_date NOT BETWEEN CAST(s.actual_checkin_at AT TIME ZONE 'Asia/Seoul' AS date)
                                      AND CAST(s.actual_checkout_at AT TIME ZONE 'Asia/Seoul' AS date)
    OR CAST(v.submitted_at AT TIME ZONE 'Asia/Seoul' AS date)<CAST(s.actual_checkout_at AT TIME ZONE 'Asia/Seoul' AS date)
    OR v.member_no IS DISTINCT FROM m.member_no)
 UNION ALL SELECT 'voc_pos_order_semantic_mismatch',COUNT(*)
 FROM crm.walkerhill_v4_3.crm_voc_reviews v
 LEFT JOIN pos.walkerhill_v4_3.pos_orders o ON o.order_id=v.related_id
 LEFT JOIN pos.walkerhill_v4_3.pos_outlets x ON x.outlet_id=o.outlet_id
 LEFT JOIN crm.walkerhill_v4_3.crm_customer_map m ON m.pos_customer_ref=o.pos_customer_ref
 WHERE v.related_source='POS_ORDER' AND (o.order_id IS NULL OR o.order_status='VOID' OR v.hotel_code<>x.hotel_code
    OR v.outlet_id IS DISTINCT FROM o.outlet_id
    OR v.source_business_date<>o.business_date
    OR CAST(v.submitted_at AT TIME ZONE 'Asia/Seoul' AS date) NOT BETWEEN o.business_date AND o.business_date+INTERVAL '1' DAY
    OR v.member_no IS DISTINCT FROM m.member_no)
 UNION ALL SELECT 'voc_facility_usage_semantic_mismatch',COUNT(*)
 FROM crm.walkerhill_v4_3.crm_voc_reviews v
 LEFT JOIN facility_scoped u ON u.usage_event_id=v.related_id
 LEFT JOIN crm.walkerhill_v4_3.crm_customer_map m ON m.facility_user_ref=u.user_ref
 WHERE v.related_source='FACILITY_USAGE' AND (u.usage_event_id IS NULL OR v.hotel_code<>u.hotel_code
    OR v.facility_id IS DISTINCT FROM u.facility_id
    OR v.source_business_date<>u.business_date OR CAST(v.submitted_at AT TIME ZONE 'Asia/Seoul' AS date)<>u.business_date+INTERVAL '1' DAY
    OR v.member_no IS DISTINCT FROM m.member_no)
 UNION ALL SELECT 'voc_banquet_booking_semantic_mismatch',COUNT(*)
 FROM crm.walkerhill_v4_3.crm_voc_reviews v
 LEFT JOIN banquet.walkerhill_v4_3.banquet_bookings b ON b.banquet_event_id=v.related_id
 LEFT JOIN banquet.walkerhill_v4_3.banquet_venues x ON x.venue_id=b.venue_id
 LEFT JOIN crm.walkerhill_v4_3.crm_customer_map m ON m.banquet_customer_id=b.banquet_customer_id
 WHERE v.related_source='BANQUET_BOOKING' AND (b.banquet_event_id IS NULL OR b.booking_status<>'COMPLETED'
    OR v.hotel_code<>x.hotel_code OR v.source_business_date<>b.event_date
    OR CAST(v.submitted_at AT TIME ZONE 'Asia/Seoul' AS date)<>b.event_date
    OR v.member_no IS DISTINCT FROM m.member_no)
)
SELECT check_name,violation_count,CASE WHEN violation_count=0 THEN 'PASS' ELSE 'FAIL' END status
FROM checks ORDER BY check_name;

SELECT 'PMS_STAYS' dataset,COUNT(*) row_count FROM pms.walkerhill_v4_3.pms_stays
UNION ALL SELECT 'POS_ORDERS',COUNT(*) FROM pos.walkerhill_v4_3.pos_orders
UNION ALL SELECT 'CRM_MEMBERS',COUNT(*) FROM crm.walkerhill_v4_3.crm_members
UNION ALL SELECT 'BANQUET_BOOKINGS',COUNT(*) FROM banquet.walkerhill_v4_3.banquet_bookings
UNION ALL SELECT 'FACILITY_USAGE',COUNT(*) FROM facility.walkerhill_v4_3.facility_usage_events
UNION ALL SELECT 'VOC_REVIEWS',COUNT(*) FROM crm.walkerhill_v4_3.crm_voc_reviews
UNION ALL SELECT 'SERVING_DAILY',COUNT(*) FROM serving.analytics_v4_3.hotel_operations_daily;

SELECT month_start,hotel_code,occupancy_rate,adr_krw,total_operating_revenue_krw,
       LAG(total_operating_revenue_krw,12) OVER(PARTITION BY hotel_code ORDER BY month_start) prior_year_revenue,
       total_operating_revenue_krw/NULLIF(LAG(total_operating_revenue_krw,12) OVER(PARTITION BY hotel_code ORDER BY month_start),0)-1 year_over_year_rate
FROM serving.analytics_v4_3.hotel_operations_monthly ORDER BY hotel_code,month_start;
