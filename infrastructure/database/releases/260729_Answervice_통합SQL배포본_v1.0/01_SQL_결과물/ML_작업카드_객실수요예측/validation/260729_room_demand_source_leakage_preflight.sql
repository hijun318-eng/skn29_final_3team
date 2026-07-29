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
-- owner=ML_WORKCARD_OWNER
-- work_card=ML-ROOM-DEMAND
-- read-only source and leakage preflight. Feature Query 실행 전에 수행한다.

SELECT 'forecast_completed_stay_label' check_name,count(*) violation_count
FROM pms.public.pms_stays
WHERE is_forecast=true AND stay_status='COMPLETED'
UNION ALL
SELECT 'completed_stay_missing_time',count(*)
FROM pms.public.pms_stays
WHERE stay_status='COMPLETED' AND (actual_checkin_at IS NULL OR actual_checkout_at IS NULL)
UNION ALL
SELECT 'reservation_time_reversal',count(*)
FROM pms.public.pms_reservations
WHERE booked_at>=CAST(checkin_date AS timestamp) OR checkin_date>=checkout_date
UNION ALL
SELECT 'source_update_after_snapshot_label',count(*)
FROM pms.public.pms_stays
WHERE source_updated_at>TIMESTAMP '2026-07-28 05:00:00 UTC'
  AND data_period_status<>'FORECAST_SCENARIO';

SELECT room_type_code,count(*) completed_stay_count,
       min(CAST(at_timezone(actual_checkin_at,'Asia/Seoul') AS date)) min_date,
       max(CAST(at_timezone(actual_checkout_at,'Asia/Seoul') AS date)) max_date
FROM pms.public.pms_stays
WHERE stay_status='COMPLETED' AND is_forecast=false
GROUP BY room_type_code ORDER BY room_type_code;
