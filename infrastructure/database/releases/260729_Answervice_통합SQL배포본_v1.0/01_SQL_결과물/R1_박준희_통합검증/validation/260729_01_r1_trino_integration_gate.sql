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
-- owner=R1_박준희
-- work_card=R1-INTEGRATION-GATE
-- Trino read-only gate. Source·View를 수정하지 않는다.

WITH view_list AS (
  SELECT table_name FROM app.information_schema.views
  WHERE table_schema='analytics'
), expected(name) AS (
  VALUES ('hotel_daily_metrics'),('hotel_monthly_metrics'),('hotel_yearly_metrics'),
         ('fnb_daypart_metrics'),('facility_daily_metrics'),('banquet_monthly_metrics'),
         ('workforce_monthly_metrics'),('resource_monthly_metrics')
)
SELECT 'missing_analytics_view' check_name,count(*) violation_count
FROM expected e LEFT JOIN view_list v ON v.table_name=e.name
WHERE v.table_name IS NULL;

SELECT 'forecast_label_stay' check_name,count(*) violation_count
FROM pms.public.pms_stays
WHERE is_forecast=true AND stay_status='COMPLETED'
UNION ALL
SELECT 'source_after_snapshot',count(*)
FROM (
  SELECT source_updated_at FROM pms.public.pms_stays
  UNION ALL SELECT source_updated_at FROM pos.hotel_pos.pos_orders
  UNION ALL SELECT source_updated_at FROM crm.dbo.crm_point_transactions
  UNION ALL SELECT source_updated_at FROM facility.hotel_facility.facility_events
  UNION ALL SELECT source_updated_at FROM banquet.public.banquet_revenue
) x
WHERE source_updated_at > TIMESTAMP '2026-07-28 05:00:00 UTC';

SELECT 'hotel_daily_zero_denominator_not_null' check_name,count(*) violation_count
FROM app.analytics.hotel_daily_metrics
WHERE available_room_nights=0 AND (occ IS NOT NULL OR revpar IS NOT NULL);
