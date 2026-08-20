-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING_EVENT; script_type=VIEW_AND_VALIDATION; execution_order=31
-- dependency=30_trino_cross_source_validation.sql; execution_default=NOT_RUN
-- counterfactual=surrounding non-event dates for the same hotel and metric; it is a scenario comparator, not causal proof

CREATE OR REPLACE VIEW serving.analytics_v4_3.event_counterfactual_daily AS
WITH effects AS (
 SELECT e.event_id,e.event_name,e.start_date,e.end_date,x.hotel_code,x.domain,x.metric_name,
        x.lead_days,x.lag_days,x.uplift_min,x.uplift_mode,x.uplift_max,x.confidence
 FROM pms.walkerhill_v4_3.event_master e JOIN pms.walkerhill_v4_3.hotel_event_effect x ON x.event_id=e.event_id
), actual AS (
 SELECT e.event_id,e.event_name,e.start_date,e.end_date,e.hotel_code,e.domain,e.metric_name,
        e.uplift_min,e.uplift_mode,e.uplift_max,e.confidence,COUNT(*) actual_days,
        AVG(CASE e.metric_name WHEN 'OCCUPANCY_RATE' THEN d.occupancy_rate WHEN 'ADR' THEN d.adr_krw
             WHEN 'ORDER_COUNT' THEN CAST(d.fnb_orders AS double) WHEN 'BOOKING_COUNT' THEN CAST(d.banquet_events AS double)
             WHEN 'USAGE_COUNT' THEN CAST(d.facility_uses AS double) END) actual_metric_mean
 FROM effects e JOIN serving.analytics_v4_3.hotel_operations_daily d
 ON d.hotel_code=e.hotel_code
 AND d.business_date BETWEEN DATE_ADD('day',-e.lead_days,e.start_date) AND DATE_ADD('day',e.lag_days,e.end_date)
 GROUP BY 1,2,3,4,5,6,7,8,9,10,11
), baseline AS (
 SELECT e.event_id,e.hotel_code,e.metric_name,
        AVG(CASE e.metric_name WHEN 'OCCUPANCY_RATE' THEN d.occupancy_rate WHEN 'ADR' THEN d.adr_krw
             WHEN 'ORDER_COUNT' THEN CAST(d.fnb_orders AS double) WHEN 'BOOKING_COUNT' THEN CAST(d.banquet_events AS double)
             WHEN 'USAGE_COUNT' THEN CAST(d.facility_uses AS double) END) counterfactual_metric_mean,
        COUNT(*) baseline_days
 FROM effects e JOIN serving.analytics_v4_3.hotel_operations_daily d ON d.hotel_code=e.hotel_code
 AND d.business_date BETWEEN DATE_ADD('day',-(e.lead_days+35),e.start_date) AND DATE_ADD('day',e.lag_days+35,e.end_date)
 AND NOT EXISTS (
   SELECT 1 FROM effects z
   WHERE z.hotel_code=e.hotel_code AND z.domain=e.domain AND z.metric_name=e.metric_name
     AND d.business_date BETWEEN DATE_ADD('day',-z.lead_days,z.start_date) AND DATE_ADD('day',z.lag_days,z.end_date)
 )
 GROUP BY 1,2,3
)
SELECT a.event_id,a.event_name,a.start_date,a.end_date,a.hotel_code,a.domain,a.metric_name,
       a.actual_days,b.baseline_days,a.actual_metric_mean,b.counterfactual_metric_mean,
       a.actual_metric_mean/NULLIF(b.counterfactual_metric_mean,0)-1 realized_uplift_rate,
       CASE WHEN COALESCE(b.baseline_days,0)>=14 THEN 'USABLE' ELSE 'INSUFFICIENT' END baseline_quality,
       a.uplift_min,a.uplift_mode,a.uplift_max,a.confidence
FROM actual a LEFT JOIN baseline b
  ON b.event_id=a.event_id AND b.hotel_code=a.hotel_code AND b.metric_name=a.metric_name;
COMMENT ON VIEW serving.analytics_v4_3.event_counterfactual_daily IS '동일 호텔의 행사 전후 비행사일 평균을 기준선으로 둔 합성 이벤트 반사실 비교. 인과 추정치가 아님';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.event_id IS '공개 행사 또는 합성 시나리오 이벤트 코드';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.event_name IS '이벤트 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.start_date IS '이벤트 영향 분석 시작일';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.end_date IS '이벤트 영향 분석 종료일';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.hotel_code IS '이벤트 효과를 다르게 적용받는 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.domain IS 'ROOMS·FNB·BANQUET·FACILITY 중 영향 도메인';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.metric_name IS 'OCCUPANCY_RATE·ADR·ORDER_COUNT·BOOKING_COUNT·USAGE_COUNT 중 비교 지표';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.actual_days IS 'lead·행사·lag 영향 구간에서 관측된 합성 영업일 수';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.baseline_days IS '영향 구간 전후 35일 중 다른 이벤트 영향일까지 제외한 기준 영업일 수';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.actual_metric_mean IS '행사 구간의 일평균 합성 지표';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.counterfactual_metric_mean IS '동일 호텔 행사 전후 비행사일의 일평균 합성 지표';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.realized_uplift_rate IS 'actual/counterfactual-1로 계산한 합성 상승률';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.baseline_quality IS '오염 제거 후 기준일이 14일 이상이면 USABLE, 아니면 INSUFFICIENT';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.uplift_min IS '모델 계약에 기록한 삼각 시나리오 최소 상승률';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.uplift_mode IS '모델 계약에 기록한 삼각 시나리오 최빈 상승률';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.uplift_max IS '모델 계약에 기록한 삼각 시나리오 최대 상승률';
COMMENT ON COLUMN serving.analytics_v4_3.event_counterfactual_daily.confidence IS '이벤트 근거와 모델링 규칙에 부여한 0~1 신뢰도';

SELECT event_id,hotel_code,metric_name,actual_metric_mean,counterfactual_metric_mean,realized_uplift_rate,
       uplift_min,uplift_mode,uplift_max,
       CASE WHEN baseline_quality='INSUFFICIENT' OR counterfactual_metric_mean IS NULL OR counterfactual_metric_mean=0 THEN 'REVIEW'
            WHEN realized_uplift_rate BETWEEN uplift_min*0.5 AND uplift_max*1.5 THEN 'PASS' ELSE 'REVIEW' END validation_status
FROM serving.analytics_v4_3.event_counterfactual_daily ORDER BY event_id,hotel_code,metric_name;

SELECT hotel_code,domain,COUNT(*) scenarios,
       AVG(realized_uplift_rate) average_realized_uplift,MIN(realized_uplift_rate) minimum_realized_uplift,
       MAX(realized_uplift_rate) maximum_realized_uplift
FROM serving.analytics_v4_3.event_counterfactual_daily GROUP BY hotel_code,domain ORDER BY hotel_code,domain;

WITH event_windows AS (
 SELECT e.event_id,e.event_name,e.start_date,e.end_date,x.hotel_code,
        MAX(x.lead_days) lead_days,MAX(x.lag_days) lag_days
 FROM pms.walkerhill_v4_3.event_master e
 JOIN pms.walkerhill_v4_3.hotel_event_effect x ON x.event_id=e.event_id
 GROUP BY 1,2,3,4,5
), event_voc AS (
 SELECT e.event_id,e.event_name,e.start_date,e.end_date,v.hotel_code,
        SUM(v.review_count) review_count,SUM(v.average_rating*v.review_count)/NULLIF(SUM(v.review_count),0) event_average_rating
 FROM event_windows e
 JOIN serving.analytics_v4_3.voc_daily v ON v.hotel_code=e.hotel_code
  AND v.business_date BETWEEN DATE_ADD('day',-e.lead_days,e.start_date) AND DATE_ADD('day',e.lag_days,e.end_date)
 GROUP BY 1,2,3,4,5
), baseline AS (
 SELECT e.event_id,v.hotel_code,SUM(v.review_count) review_count,
        SUM(v.average_rating*v.review_count)/NULLIF(SUM(v.review_count),0) baseline_average_rating
 FROM event_windows e
 JOIN serving.analytics_v4_3.voc_daily v ON v.hotel_code=e.hotel_code
  AND v.business_date BETWEEN DATE_ADD('day',-(e.lead_days+35),e.start_date) AND DATE_ADD('day',e.lag_days+35,e.end_date)
  AND NOT EXISTS (
    SELECT 1 FROM event_windows z WHERE z.hotel_code=e.hotel_code
      AND v.business_date BETWEEN DATE_ADD('day',-z.lead_days,z.start_date) AND DATE_ADD('day',z.lag_days,z.end_date)
  )
 GROUP BY 1,2
)
SELECT e.event_id,e.event_name,e.hotel_code,e.review_count event_reviews,b.review_count baseline_reviews,
       e.event_average_rating,b.baseline_average_rating,
       e.event_average_rating-b.baseline_average_rating rating_delta
FROM event_voc e LEFT JOIN baseline b ON b.event_id=e.event_id AND b.hotel_code=e.hotel_code
ORDER BY e.event_id,e.hotel_code;
