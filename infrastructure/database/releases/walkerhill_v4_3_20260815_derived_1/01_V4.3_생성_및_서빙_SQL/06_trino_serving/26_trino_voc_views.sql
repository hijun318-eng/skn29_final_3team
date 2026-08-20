-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING_VOC; script_type=VIEW; execution_order=26
-- dependency=crm.walkerhill_v4_3.crm_voc_reviews,crm.walkerhill_v4_3.crm_voc_analysis; execution_default=NOT_RUN

CREATE OR REPLACE VIEW serving.analytics_v4_3.voc_review_detail AS
SELECT r.voc_review_id,
       r.source_business_date business_date,
       r.submitted_at,r.hotel_code,r.source_channel,r.touchpoint,r.selected_category,
       r.rating_overall,r.rating_service,r.rating_cleanliness,r.rating_food,r.rating_facility,r.rating_value,
       r.review_title,r.review_text_original,r.language_code,r.is_external,
       a.sentiment_label,a.sentiment_score,a.primary_topic,a.urgency_level,a.requires_followup,a.analysis_confidence,
       r.related_source,r.related_id,r.member_no,r.outlet_id,r.facility_id,r.visit_cohort,r.prior_visit_count
FROM crm.walkerhill_v4_3.crm_voc_reviews r
JOIN crm.walkerhill_v4_3.crm_voc_analysis a ON a.voc_review_id=r.voc_review_id;
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

CREATE OR REPLACE VIEW serving.analytics_v4_3.voc_daily AS
SELECT r.source_business_date business_date,
       r.hotel_code,r.source_channel,COUNT(*) review_count,
       ROUND(AVG(CAST(r.rating_overall AS double)),4) average_rating,
       COUNT_IF(r.rating_overall<=2) low_rating_reviews,
       COUNT_IF(a.sentiment_label='NEGATIVE') negative_reviews,
       COUNT_IF(a.sentiment_label='POSITIVE') positive_reviews,
       COUNT_IF(a.requires_followup) followup_reviews
FROM crm.walkerhill_v4_3.crm_voc_reviews r
JOIN crm.walkerhill_v4_3.crm_voc_analysis a ON a.voc_review_id=r.voc_review_id
GROUP BY 1,2,3;
COMMENT ON VIEW serving.analytics_v4_3.voc_daily IS '호텔·제출일·채널별 합성 VOC 평점과 감성·후속조치 건수를 집계한 일별 뷰';
COMMENT ON COLUMN serving.analytics_v4_3.voc_daily.business_date IS '리뷰가 평가하는 원 운영 객체의 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.voc_daily.hotel_code IS '리뷰 대상 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.voc_daily.source_channel IS '리뷰 수집 채널';
COMMENT ON COLUMN serving.analytics_v4_3.voc_daily.review_count IS '일별 합성 리뷰 수';
COMMENT ON COLUMN serving.analytics_v4_3.voc_daily.average_rating IS '1~5 종합 평점 평균';
COMMENT ON COLUMN serving.analytics_v4_3.voc_daily.low_rating_reviews IS '1~2점 리뷰 수';
COMMENT ON COLUMN serving.analytics_v4_3.voc_daily.negative_reviews IS 'NEGATIVE 감성 리뷰 수';
COMMENT ON COLUMN serving.analytics_v4_3.voc_daily.positive_reviews IS 'POSITIVE 감성 리뷰 수';
COMMENT ON COLUMN serving.analytics_v4_3.voc_daily.followup_reviews IS '후속 확인 필요 리뷰 수';

CREATE OR REPLACE VIEW serving.analytics_v4_3.hotel_voc_signal_daily AS
WITH voc AS (
 SELECT business_date,hotel_code,SUM(review_count) review_count,
        SUM(average_rating*review_count)/NULLIF(SUM(review_count),0) average_rating,
        SUM(low_rating_reviews) low_rating_reviews,SUM(negative_reviews) negative_reviews,
        SUM(followup_reviews) followup_reviews
 FROM serving.analytics_v4_3.voc_daily GROUP BY 1,2
)
SELECT o.business_date,o.hotel_code,o.event_id,o.occupancy_rate,o.adr_krw,o.fnb_orders,
       o.banquet_events,o.facility_uses,o.overtime_hours,o.total_operating_revenue_krw,
       COALESCE(v.review_count,0) review_count,v.average_rating,
       COALESCE(v.low_rating_reviews,0) low_rating_reviews,
       COALESCE(v.negative_reviews,0) negative_reviews,
       COALESCE(v.followup_reviews,0) followup_reviews
FROM serving.analytics_v4_3.hotel_operations_daily o
LEFT JOIN voc v ON v.business_date=o.business_date AND v.hotel_code=o.hotel_code;
COMMENT ON VIEW serving.analytics_v4_3.hotel_voc_signal_daily IS '운영 부하·매출과 VOC 평점·저평점·후속 확인을 호텔·일자 한 행에서 비교하는 합성 분석 뷰';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.business_date IS '운영과 VOC를 결합한 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.hotel_code IS 'GRAND·VISTA·DOUGLAS 합성 보고 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.event_id IS '해당 호텔·일자에 연결된 대표 이벤트 코드';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.occupancy_rate IS '일별 합성 객실 점유율';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.adr_krw IS '일별 합성 평균객실단가';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.fnb_orders IS '일별 완료 식음 주문 수';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.banquet_events IS '일별 확정 연회 건수';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.facility_uses IS '일별 시설 이용 이벤트 수';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.overtime_hours IS '일별 합성 초과근로시간';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.total_operating_revenue_krw IS '객실·식음·연회·시설 일별 합성 매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.review_count IS '호텔·일자 합성 VOC 리뷰 수';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.average_rating IS '리뷰 건수로 가중한 1~5 합성 평균평점';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.low_rating_reviews IS '1~2점 합성 리뷰 수';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.negative_reviews IS 'NEGATIVE 감성 합성 리뷰 수';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_voc_signal_daily.followup_reviews IS '후속 확인 필요 합성 리뷰 수';
