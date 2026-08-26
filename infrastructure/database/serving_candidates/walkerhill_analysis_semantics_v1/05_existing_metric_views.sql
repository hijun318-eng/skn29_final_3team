-- release_id=walkerhill-analysis-semantics-v1.20260826.1
-- source_release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 483; target_schema=serving.analytics_v4_3
-- state=REVIEW_REQUIRED; script_type=VIEW; execution_order=5; execution_default=NOT_RUN
-- purpose=새 의미 릴리스가 유지하는 기존 Metric source를 동일 SQL 근거로 재봉인한다.

CREATE OR REPLACE VIEW serving.analytics_v4_3.hotel_operations_daily AS
WITH keys AS (
    SELECT business_date, hotel_code FROM serving.analytics_v4_3.room_daily
    UNION SELECT business_date, hotel_code FROM serving.analytics_v4_3.fnb_daily
    UNION SELECT business_date, hotel_code FROM serving.analytics_v4_3.banquet_daily
    UNION SELECT business_date, hotel_code FROM serving.analytics_v4_3.facility_daily
    UNION SELECT business_date, hotel_code FROM serving.analytics_v4_3.staffing_daily
), event_day AS (
    SELECT
        c.business_date,
        h.hotel_code,
        max_by(e.event_id, ROW(e.confidence, e.event_id)) AS event_id,
        max_by(e.event_name, ROW(e.confidence, e.event_id)) AS event_name
    FROM pms.walkerhill_v4_3.calendar_daily c
    JOIN pms.walkerhill_v4_3.event_master e
      ON c.business_date BETWEEN e.start_date AND e.end_date
    JOIN (
        SELECT DISTINCT event_id, hotel_code
        FROM pms.walkerhill_v4_3.hotel_event_effect
    ) h
      ON h.event_id = e.event_id
    GROUP BY 1, 2
)
SELECT
    k.business_date,
    k.hotel_code,
    e.event_id,
    e.event_name,
    COALESCE(r.available_room_nights, 0) AS available_room_nights,
    COALESCE(r.occupied_room_nights, 0) AS occupied_room_nights,
    COALESCE(r.occupancy_rate, 0e0) AS occupancy_rate,
    COALESCE(r.adr_krw, 0e0) AS adr_krw,
    COALESCE(r.room_revenue_krw, DECIMAL '0') AS room_revenue_krw,
    COALESCE(f.completed_orders, 0) AS fnb_orders,
    COALESCE(f.net_revenue_krw, DECIMAL '0') AS fnb_revenue_krw,
    COALESCE(b.operating_events, 0) AS banquet_events,
    COALESCE(b.recognized_revenue_krw, DECIMAL '0') AS banquet_revenue_krw,
    COALESCE(x.usage_events, 0) AS facility_uses,
    COALESCE(x.facility_revenue_krw, DECIMAL '0') AS facility_revenue_krw,
    COALESCE(s.actual_hours, DECIMAL '0') AS staffing_hours,
    COALESCE(s.overtime_hours, DECIMAL '0') AS overtime_hours,
    COALESCE(r.room_revenue_krw, DECIMAL '0')
      + COALESCE(f.net_revenue_krw, DECIMAL '0')
      + COALESCE(b.recognized_revenue_krw, DECIMAL '0')
      + COALESCE(x.facility_revenue_krw, DECIMAL '0') AS total_operating_revenue_krw
FROM keys k
LEFT JOIN serving.analytics_v4_3.room_daily r
  ON r.business_date = k.business_date AND r.hotel_code = k.hotel_code
LEFT JOIN serving.analytics_v4_3.fnb_daily f
  ON f.business_date = k.business_date AND f.hotel_code = k.hotel_code
LEFT JOIN serving.analytics_v4_3.banquet_daily b
  ON b.business_date = k.business_date AND b.hotel_code = k.hotel_code
LEFT JOIN serving.analytics_v4_3.facility_daily x
  ON x.business_date = k.business_date AND x.hotel_code = k.hotel_code
LEFT JOIN serving.analytics_v4_3.staffing_daily s
  ON s.business_date = k.business_date AND s.hotel_code = k.hotel_code
LEFT JOIN event_day e
  ON e.business_date = k.business_date AND e.hotel_code = k.hotel_code;

COMMENT ON VIEW serving.analytics_v4_3.hotel_operations_daily IS '도메인 선집계 결과를 호텔·영업일 키로 결합한 V4.3 합성 통합 운영 마트';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.business_date IS '통합 운영 실적 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.hotel_code IS 'GRAND·VISTA·DOUGLAS 합성 보고 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.event_id IS '해당 날짜·호텔에 가장 높은 신뢰도로 연결된 행사 코드';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.event_name IS '연결된 공개 행사 또는 합성 외부 이벤트 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.available_room_nights IS '일별 판매 가능 객실박';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.occupied_room_nights IS '일별 점유 객실박';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.occupancy_rate IS '일별 객실 점유율';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.adr_krw IS '일별 합성 평균객실단가';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.room_revenue_krw IS '일별 합성 객실매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.fnb_orders IS '일별 완료 POS 주문 수';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.fnb_revenue_krw IS '일별 합성 식음 순매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.banquet_events IS '일별 완료·확정 운영 연회 건수';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.banquet_revenue_krw IS '일별 합성 연회 인식매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.facility_uses IS '일별 시설 이용 이벤트 수';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.facility_revenue_krw IS '일별 합성 유료시설 매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.staffing_hours IS '일별 합성 실제 근로시간';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.overtime_hours IS '일별 합성 초과근로시간';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_daily.total_operating_revenue_krw IS '객실+식음+연회+시설 합성 매출 합계. 실제 워커힐 실적이 아님';

CREATE OR REPLACE VIEW serving.analytics_v4_3.voc_review_detail AS
SELECT
    r.voc_review_id,
    r.source_business_date AS business_date,
    r.submitted_at,
    r.hotel_code,
    r.source_channel,
    r.touchpoint,
    r.selected_category,
    r.rating_overall,
    r.rating_service,
    r.rating_cleanliness,
    r.rating_food,
    r.rating_facility,
    r.rating_value,
    r.review_title,
    r.review_text_original,
    r.language_code,
    r.is_external,
    a.sentiment_label,
    a.sentiment_score,
    a.primary_topic,
    a.urgency_level,
    a.requires_followup,
    a.analysis_confidence,
    r.related_source,
    r.related_id,
    r.member_no,
    r.outlet_id,
    r.facility_id,
    r.visit_cohort,
    r.prior_visit_count
FROM crm.walkerhill_v4_3.crm_voc_reviews r
JOIN crm.walkerhill_v4_3.crm_voc_analysis a
  ON a.voc_review_id = r.voc_review_id;

COMMENT ON VIEW serving.analytics_v4_3.voc_review_detail IS '원본 합성 평점·리뷰와 별도 감성·주제 분석을 1:1 결합한 VOC 검토 뷰';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.voc_review_id IS '합성 VOC 리뷰 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.business_date IS '리뷰가 평가하는 원 운영 객체의 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.submitted_at IS '오프셋을 보존한 리뷰 제출 시각';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.hotel_code IS '리뷰 대상 GRAND·VISTA·DOUGLAS 코드';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.source_channel IS '내부 설문·QR 또는 외부 형식 합성 리뷰 채널';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.touchpoint IS 'ROOM·FNB·FACILITY 등 고객 여정 접점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.selected_category IS '합성 고객이 선택한 원본 의견 범주';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.rating_overall IS '1~5 합성 종합 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.rating_service IS '1~5 합성 서비스 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.rating_cleanliness IS '객실 접점의 1~5 합성 청결 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.rating_food IS '식음·연회 접점의 1~5 합성 음식 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.rating_facility IS '시설 접점의 1~5 합성 시설 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.rating_value IS '1~5 합성 가격 대비 가치 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.review_title IS '평점 방향과 선택 범주를 반영한 합성 제목';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.review_text_original IS '실제 외부 문장을 복제하지 않은 한국어 합성 리뷰 원문';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.language_code IS '원문 ISO 639-1 언어 코드';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.is_external IS '외부 리뷰 형식 여부. 실제 수집 여부가 아님';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.sentiment_label IS 'POSITIVE·NEUTRAL·NEGATIVE 합성 감성 라벨';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.sentiment_score IS '-1~1 합성 감성 점수';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.primary_topic IS '규칙 분석기가 분류한 주요 운영 주제';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.urgency_level IS 'LOW·MEDIUM·HIGH 운영 확인 긴급도';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.requires_followup IS '저평점 후속 확인 필요 여부';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.analysis_confidence IS '0~1 합성 분석 신뢰도. 실제 모델 성능이 아님';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.related_source IS '관련 PMS·POS·시설·연회 객체 유형';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.related_id IS '관련 원천의 합성 논리 키';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.member_no IS '동의 기반 교차 도메인 분석용 합성 회원 키. 비회원은 NULL';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.outlet_id IS 'FNB 리뷰가 참조하는 합성 POS 업장 키';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.facility_id IS '시설 리뷰가 참조하는 합성 시설 키';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.visit_cohort IS 'NEW·RETURNING 합성 방문 코호트';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_detail.prior_visit_count IS '이번 이용 이전의 합성 방문 횟수';
