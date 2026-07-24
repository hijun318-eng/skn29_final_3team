-- ==========================================================================
-- SensePlace DSG v2.0 — Read-only Analytics Views (§8)
--
-- FastAPI가 직접 fact table 조합을 임의 생성하지 않도록 allowlist view를
-- 제공한다. view는 dataset_version과 권한 필터에 필요한 dimension을 노출한다.
-- PII 또는 자유로운 raw text export view를 만들지 않는다.
--
-- 기본: PostgreSQL 문법. SQLite 호환 주석 포함.
-- ==========================================================================

-- --------------------------------------------------------------------------
-- 1. v_rooms_daily
--    객실 일별 운영 집계 + dim_date 차원 결합
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_rooms_daily AS
SELECT
    r.dataset_version,
    r.service_date,
    d.day_of_week,
    d.is_weekend,
    d.virtual_week_id,
    r.room_inventory,
    r.rooms_out_of_order,
    r.rooms_available,
    r.rooms_sold,
    r.inhouse_guests,
    r.breakfast_entitled_guests,
    -- derived: rooms_unsold (검사용)
    (r.rooms_available - r.rooms_sold) AS rooms_unsold
FROM fact_rooms_daily r
LEFT JOIN dim_date d
    ON r.service_date = d.service_date;

-- --------------------------------------------------------------------------
-- 2. v_breakfast_15m
--    조식 15분 집계 + 서비스 구역 차원
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_breakfast_15m AS
SELECT
    b.dataset_version,
    b.service_area_id,
    sa.display_name AS service_area_name,
    b.bucket_start,
    b.expected_arrivals,
    b.actual_arrivals,
    b.service_capacity,
    b.seated_guests,
    b.avg_wait_min,
    b.p90_wait_min,
    b.max_queue_length
FROM fact_breakfast_15m b
LEFT JOIN dim_service_area sa
    ON b.service_area_id = sa.service_area_id;

-- --------------------------------------------------------------------------
-- 3. v_breakfast_daily
--    조식 일별 집계 + 서비스 구역 차원
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_breakfast_daily AS
SELECT
    bd.dataset_version,
    bd.service_area_id,
    sa.display_name AS service_area_name,
    bd.service_date,
    d.day_of_week,
    d.is_weekend,
    d.virtual_week_id,
    bd.arrivals_total,
    bd.capacity_total,
    bd.avg_wait_min,
    bd.p90_wait_min,
    bd.voc_negative_count
FROM fact_breakfast_daily bd
LEFT JOIN dim_service_area sa
    ON bd.service_area_id = sa.service_area_id
LEFT JOIN dim_date d
    ON bd.service_date = d.service_date;

-- --------------------------------------------------------------------------
-- 4. v_staff_shift
--    인력 시프트별 집계 + 서비스 구역 차원
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_staff_shift AS
SELECT
    ss.dataset_version,
    ss.service_date,
    d.day_of_week,
    d.is_weekend,
    d.virtual_week_id,
    ss.service_area_id,
    sa.display_name AS service_area_name,
    ss.shift_code,
    ss.planned_headcount,
    ss.actual_headcount,
    ss.absence_count,
    ss.labor_minutes
FROM fact_staff_shift ss
LEFT JOIN dim_service_area sa
    ON ss.service_area_id = sa.service_area_id
LEFT JOIN dim_date d
    ON ss.service_date = d.service_date;

-- --------------------------------------------------------------------------
-- 5. v_voc_summary
--    VOC 일별·구역별·감성별 집계 (원문 텍스트 미노출)
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_voc_summary AS
SELECT
    v.dataset_version,
    v.service_area_id,
    sa.display_name AS service_area_name,
    CAST(v.received_at AS DATE) AS service_date,
    v.topic_code,
    v.sentiment_label,
    v.is_synthetic,
    COUNT(*)                    AS voc_count,
    SUM(CASE WHEN v.sentiment_label = 'NEGATIVE' THEN 1 ELSE 0 END)
                                AS negative_count,
    SUM(CASE WHEN v.sentiment_label = 'POSITIVE' THEN 1 ELSE 0 END)
                                AS positive_count
FROM fact_voc v
LEFT JOIN dim_service_area sa
    ON v.service_area_id = sa.service_area_id
GROUP BY
    v.dataset_version,
    v.service_area_id,
    sa.display_name,
    CAST(v.received_at AS DATE),
    v.topic_code,
    v.sentiment_label,
    v.is_synthetic;

-- --------------------------------------------------------------------------
-- 6. v_incident_evidence
--    분석 실행 + 근거 결합 (incident → evidence 추적)
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_incident_evidence AS
SELECT
    ar.analysis_run_id,
    ar.job_id,
    ar.dataset_version,
    ar.scenario_id,
    ar.rule_id,
    ar.rule_version,
    ar.status              AS analysis_status,
    ar.started_at,
    ar.completed_at,
    e.evidence_id,
    e.evidence_type,
    e.source_table,
    e.source_key,
    e.metric_code,
    e.observed_window,
    e.comparison_window,
    e.value,
    e.unit,
    e.sample_size,
    e.is_counter_evidence,
    e.limitations
FROM analysis_run ar
LEFT JOIN evidence e
    ON ar.analysis_run_id = e.analysis_run_id;
