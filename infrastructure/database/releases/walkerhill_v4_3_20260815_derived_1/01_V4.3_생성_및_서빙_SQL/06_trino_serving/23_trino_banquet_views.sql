-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING_BANQUET; script_type=VIEW; execution_order=23
-- dependency=banquet.walkerhill_v4_3; execution_default=NOT_RUN

CREATE OR REPLACE VIEW serving.analytics_v4_3.banquet_daily AS
WITH bookings AS (
 SELECT b.event_date business_date,v.hotel_code,
        COUNT(*) FILTER(WHERE b.booking_status IN ('COMPLETED','CONFIRMED')) operating_events,
        COUNT(*) FILTER(WHERE b.booking_status='COMPLETED') completed_events,
        COUNT(*) FILTER(WHERE b.booking_status='CONFIRMED') confirmed_events,
        COUNT(*) FILTER(WHERE b.booking_status='CANCELLED') cancelled_events,
        SUM(CASE WHEN b.booking_status='COMPLETED' THEN b.actual_attendees WHEN b.booking_status='CONFIRMED' THEN b.expected_guests ELSE 0 END) attendees,
        SUM(CASE WHEN b.booking_status IN ('COMPLETED','CONFIRMED') THEN b.contracted_amount ELSE 0 END) contracted_amount_krw
 FROM banquet.walkerhill_v4_3.banquet_bookings b
 JOIN banquet.walkerhill_v4_3.banquet_venues v ON v.venue_id=b.venue_id GROUP BY 1,2
), revenue AS (
 SELECT r.recognized_date business_date,v.hotel_code,
        SUM(r.gross_amount) gross_amount_krw,SUM(r.discount_amount) discount_amount_krw,
        SUM(r.reversal_amount) reversal_amount_krw,SUM(r.recognized_amount) recognized_revenue_krw,
        SUM(r.cost_amount) estimated_cost_krw
 FROM banquet.walkerhill_v4_3.banquet_revenue_lines r
 JOIN banquet.walkerhill_v4_3.banquet_bookings b ON b.banquet_event_id=r.banquet_event_id
 JOIN banquet.walkerhill_v4_3.banquet_venues v ON v.venue_id=b.venue_id GROUP BY 1,2
)
SELECT COALESCE(b.business_date,r.business_date) business_date,COALESCE(b.hotel_code,r.hotel_code) hotel_code,
       COALESCE(b.operating_events,0) operating_events,COALESCE(b.completed_events,0) completed_events,
       COALESCE(b.confirmed_events,0) confirmed_events,COALESCE(b.cancelled_events,0) cancelled_events,
       COALESCE(b.attendees,0) attendees,COALESCE(b.contracted_amount_krw,DECIMAL '0') contracted_amount_krw,
       COALESCE(r.gross_amount_krw,DECIMAL '0') gross_amount_krw,COALESCE(r.discount_amount_krw,DECIMAL '0') discount_amount_krw,
       COALESCE(r.reversal_amount_krw,DECIMAL '0') reversal_amount_krw,COALESCE(r.recognized_revenue_krw,DECIMAL '0') recognized_revenue_krw,
       COALESCE(r.estimated_cost_krw,DECIMAL '0') estimated_cost_krw
FROM bookings b FULL OUTER JOIN revenue r
  ON r.business_date=b.business_date AND r.hotel_code=b.hotel_code;
COMMENT ON VIEW serving.analytics_v4_3.banquet_daily IS '호텔·영업일 단위 연회 예약·참석·계약액·인식매출 합성 KPI';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.business_date IS '행사일 또는 매출 인식일';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.hotel_code IS '행사장 소속 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.operating_events IS '완료·확정 상태를 합한 운영 연회 건수';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.completed_events IS '실제 행사일을 지나 COMPLETED로 종료된 합성 연회 건수';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.confirmed_events IS '확정 상태 합성 연회 건수';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.cancelled_events IS '취소 상태 합성 연회 건수';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.attendees IS '확정 연회의 실제 또는 예상 합성 참석자 수';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.contracted_amount_krw IS '확정 연회의 합성 계약금액';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.gross_amount_krw IS '할인·취소 전 연회 매출 총액';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.discount_amount_krw IS '연회 할인 합계';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.reversal_amount_krw IS '연회 취소·환입 합계';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.recognized_revenue_krw IS '회계 인식 기준 합성 연회 순매출';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_daily.estimated_cost_krw IS '합성 원가율로 산출한 분석용 추정 원가';
