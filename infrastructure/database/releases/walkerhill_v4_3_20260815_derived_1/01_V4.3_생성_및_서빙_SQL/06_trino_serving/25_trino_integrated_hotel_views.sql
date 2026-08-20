-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING_INTEGRATED; script_type=VIEW; execution_order=25
-- dependency=20..24 domain views; execution_default=NOT_RUN
-- anti_fanout=each source is aggregated to business_date+hotel_code before joining

CREATE OR REPLACE VIEW serving.analytics_v4_3.hotel_operations_daily AS
WITH keys AS (
 SELECT business_date,hotel_code FROM serving.analytics_v4_3.room_daily
 UNION SELECT business_date,hotel_code FROM serving.analytics_v4_3.fnb_daily
 UNION SELECT business_date,hotel_code FROM serving.analytics_v4_3.banquet_daily
 UNION SELECT business_date,hotel_code FROM serving.analytics_v4_3.facility_daily
 UNION SELECT business_date,hotel_code FROM serving.analytics_v4_3.staffing_daily
), event_day AS (
 SELECT c.business_date,h.hotel_code,
        max_by(e.event_id,ROW(e.confidence,e.event_id)) event_id,
        max_by(e.event_name,ROW(e.confidence,e.event_id)) event_name
 FROM pms.walkerhill_v4_3.calendar_daily c
 JOIN pms.walkerhill_v4_3.event_master e ON c.business_date BETWEEN e.start_date AND e.end_date
 JOIN (SELECT DISTINCT event_id,hotel_code FROM pms.walkerhill_v4_3.hotel_event_effect) h ON h.event_id=e.event_id
 GROUP BY 1,2
)
SELECT k.business_date,k.hotel_code,e.event_id,e.event_name,
       COALESCE(r.available_room_nights,0) available_room_nights,COALESCE(r.occupied_room_nights,0) occupied_room_nights,
       COALESCE(r.occupancy_rate,0e0) occupancy_rate,COALESCE(r.adr_krw,0e0) adr_krw,
       COALESCE(r.room_revenue_krw,DECIMAL '0') room_revenue_krw,
       COALESCE(f.completed_orders,0) fnb_orders,COALESCE(f.net_revenue_krw,DECIMAL '0') fnb_revenue_krw,
       COALESCE(b.operating_events,0) banquet_events,COALESCE(b.recognized_revenue_krw,DECIMAL '0') banquet_revenue_krw,
       COALESCE(x.usage_events,0) facility_uses,COALESCE(x.facility_revenue_krw,DECIMAL '0') facility_revenue_krw,
       COALESCE(s.actual_hours,DECIMAL '0') staffing_hours,COALESCE(s.overtime_hours,DECIMAL '0') overtime_hours,
       COALESCE(r.room_revenue_krw,DECIMAL '0')+COALESCE(f.net_revenue_krw,DECIMAL '0')+
       COALESCE(b.recognized_revenue_krw,DECIMAL '0')+COALESCE(x.facility_revenue_krw,DECIMAL '0') total_operating_revenue_krw
FROM keys k LEFT JOIN serving.analytics_v4_3.room_daily r
  ON r.business_date=k.business_date AND r.hotel_code=k.hotel_code
LEFT JOIN serving.analytics_v4_3.fnb_daily f
  ON f.business_date=k.business_date AND f.hotel_code=k.hotel_code
LEFT JOIN serving.analytics_v4_3.banquet_daily b
  ON b.business_date=k.business_date AND b.hotel_code=k.hotel_code
LEFT JOIN serving.analytics_v4_3.facility_daily x
  ON x.business_date=k.business_date AND x.hotel_code=k.hotel_code
LEFT JOIN serving.analytics_v4_3.staffing_daily s
  ON s.business_date=k.business_date AND s.hotel_code=k.hotel_code
LEFT JOIN event_day e
  ON e.business_date=k.business_date AND e.hotel_code=k.hotel_code;
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

CREATE OR REPLACE VIEW serving.analytics_v4_3.hotel_operations_monthly AS
SELECT date_trunc('month',business_date) month_start,hotel_code,
       SUM(available_room_nights) available_room_nights,SUM(occupied_room_nights) occupied_room_nights,
       CAST(SUM(occupied_room_nights) AS double)/NULLIF(SUM(available_room_nights),0) occupancy_rate,
       CAST(SUM(room_revenue_krw) AS double)/NULLIF(SUM(occupied_room_nights),0) adr_krw,
       SUM(room_revenue_krw) room_revenue_krw,SUM(fnb_revenue_krw) fnb_revenue_krw,
       SUM(banquet_revenue_krw) banquet_revenue_krw,SUM(facility_revenue_krw) facility_revenue_krw,
       SUM(total_operating_revenue_krw) total_operating_revenue_krw,SUM(staffing_hours) staffing_hours,SUM(overtime_hours) overtime_hours
FROM serving.analytics_v4_3.hotel_operations_daily GROUP BY 1,2;
COMMENT ON VIEW serving.analytics_v4_3.hotel_operations_monthly IS '호텔 통합 운영 일별 마트를 월 단위로 가중 재집계한 합성 KPI';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.month_start IS '집계월 첫날';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.hotel_code IS 'GRAND·VISTA·DOUGLAS 합성 보고 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.available_room_nights IS '월간 판매 가능 객실박';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.occupied_room_nights IS '월간 점유 객실박';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.occupancy_rate IS '월간 가중 객실 점유율';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.adr_krw IS '월간 가중 평균객실단가';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.room_revenue_krw IS '월간 합성 객실매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.fnb_revenue_krw IS '월간 합성 식음 순매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.banquet_revenue_krw IS '월간 합성 연회 인식매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.facility_revenue_krw IS '월간 합성 유료시설 매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.total_operating_revenue_krw IS '월간 4개 영업 도메인 합성 매출';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.staffing_hours IS '월간 합성 실제 근로시간';
COMMENT ON COLUMN serving.analytics_v4_3.hotel_operations_monthly.overtime_hours IS '월간 합성 초과근로시간';
