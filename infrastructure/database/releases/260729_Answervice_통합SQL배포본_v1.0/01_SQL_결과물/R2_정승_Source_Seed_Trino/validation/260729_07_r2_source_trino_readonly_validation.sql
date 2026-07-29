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
-- owner=R2_정승
-- work_card=R2-TRINO
-- Trino read-only 통합 확인. catalog가 연결된 뒤 실행한다.

WITH expected(catalog_name, schema_name, table_name) AS (
  VALUES
  ('pms','public','pms_guests'),('pms','public','pms_room_inventory_daily'),
  ('pms','public','pms_reservations'),('pms','public','pms_stays'),
  ('pos','hotel_pos','pos_stores'),('pos','hotel_pos','pos_service_periods'),
  ('pos','hotel_pos','pos_orders'),('pos','hotel_pos','pos_order_items'),
  ('crm','dbo','crm_members'),('crm','dbo','crm_member_grade_history'),
  ('crm','dbo','crm_point_transactions'),('crm','dbo','crm_customer_map'),
  ('facility','hotel_facility','facility_master'),('facility','hotel_facility','facility_events'),
  ('facility','hotel_facility','hotel_staffing_daily'),('facility','hotel_facility','facility_resource_daily'),
  ('banquet','public','banquet_bookings'),('banquet','public','banquet_revenue')
), actual AS (
  SELECT 'pms' catalog_name, table_schema schema_name, table_name FROM pms.information_schema.tables
  UNION ALL SELECT 'pos', table_schema, table_name FROM pos.information_schema.tables
  UNION ALL SELECT 'crm', table_schema, table_name FROM crm.information_schema.tables
  UNION ALL SELECT 'facility', table_schema, table_name FROM facility.information_schema.tables
  UNION ALL SELECT 'banquet', table_schema, table_name FROM banquet.information_schema.tables
)
SELECT 'missing_source_table' AS check_name, count(*) AS violation_count
FROM expected e
LEFT JOIN actual a USING(catalog_name,schema_name,table_name)
WHERE a.table_name IS NULL;

SELECT 'pms.pms_guests' asset, count(*) row_count, max(source_updated_at) watermark FROM pms.public.pms_guests
UNION ALL SELECT 'pms.pms_room_inventory_daily',count(*),max(source_updated_at) FROM pms.public.pms_room_inventory_daily
UNION ALL SELECT 'pms.pms_reservations',count(*),max(source_updated_at) FROM pms.public.pms_reservations
UNION ALL SELECT 'pms.pms_stays',count(*),max(source_updated_at) FROM pms.public.pms_stays
UNION ALL SELECT 'pos.pos_orders',count(*),max(source_updated_at) FROM pos.hotel_pos.pos_orders
UNION ALL SELECT 'crm.crm_members',count(*),max(source_updated_at) FROM crm.dbo.crm_members
UNION ALL SELECT 'facility.facility_events',count(*),max(source_updated_at) FROM facility.hotel_facility.facility_events
UNION ALL SELECT 'banquet.banquet_bookings',count(*),max(source_updated_at) FROM banquet.public.banquet_bookings;

SELECT table_name
FROM app.information_schema.views
WHERE table_schema='analytics'
  AND table_name IN (
    'hotel_daily_metrics','hotel_monthly_metrics','hotel_yearly_metrics','fnb_daypart_metrics',
    'facility_daily_metrics','banquet_monthly_metrics','workforce_monthly_metrics','resource_monthly_metrics'
  )
ORDER BY table_name;
