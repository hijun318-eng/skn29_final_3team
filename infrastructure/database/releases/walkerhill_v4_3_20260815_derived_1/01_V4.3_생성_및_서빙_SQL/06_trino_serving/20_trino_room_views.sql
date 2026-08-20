-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING_ROOM; script_type=VIEW; execution_order=20
-- dependency=10_trino_serving_schema.sql,pms.walkerhill_v4_3; execution_default=NOT_RUN

CREATE OR REPLACE VIEW serving.analytics_v4_3.room_daily AS
WITH inventory AS (
 SELECT business_date,hotel_code,SUM(available_room_nights) available_room_nights
 FROM pms.walkerhill_v4_3.pms_room_inventory_daily GROUP BY 1,2
), stay_nights AS (
 SELECT n.business_date,s.hotel_code,s.stay_id,n.net_room_revenue room_revenue_krw
 FROM pms.walkerhill_v4_3.pms_stay_nights n JOIN pms.walkerhill_v4_3.pms_stays s ON s.stay_id=n.stay_id
 WHERE s.stay_status='CHECKED_OUT' AND NOT s.complimentary_flag AND NOT s.house_use_flag
), actual AS (
 SELECT business_date,hotel_code,COUNT(DISTINCT stay_id) occupied_room_nights,SUM(room_revenue_krw) room_revenue_krw
 FROM stay_nights GROUP BY 1,2
)
SELECT i.business_date,i.hotel_code,i.available_room_nights,
       COALESCE(a.occupied_room_nights,0) occupied_room_nights,
       COALESCE(a.room_revenue_krw,DECIMAL '0') room_revenue_krw,
       CAST(COALESCE(a.occupied_room_nights,0) AS double)/NULLIF(i.available_room_nights,0) occupancy_rate,
       CAST(COALESCE(a.room_revenue_krw,DECIMAL '0') AS double)/NULLIF(a.occupied_room_nights,0) adr_krw,
       CAST(COALESCE(a.room_revenue_krw,DECIMAL '0') AS double)/NULLIF(i.available_room_nights,0) revpar_krw
FROM inventory i LEFT JOIN actual a
  ON a.business_date=i.business_date AND a.hotel_code=i.hotel_code;
COMMENT ON VIEW serving.analytics_v4_3.room_daily IS '호텔·영업일 단위 객실 공급, 판매, 매출과 OCC·ADR·RevPAR를 제공하는 합성 서빙 뷰';
COMMENT ON COLUMN serving.analytics_v4_3.room_daily.business_date IS '객실 실적 귀속 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.room_daily.hotel_code IS 'GRAND·VISTA·DOUGLAS 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_daily.available_room_nights IS '물리 객실에서 고장·하우스유즈를 제외한 판매 가능 객실박 수';
COMMENT ON COLUMN serving.analytics_v4_3.room_daily.occupied_room_nights IS '무료·하우스유즈를 제외한 실제 합성 점유 객실박 수';
COMMENT ON COLUMN serving.analytics_v4_3.room_daily.room_revenue_krw IS '숙박일별 요금·할인을 물리 원장에서 합산한 일별 원화 합성 객실매출';
COMMENT ON COLUMN serving.analytics_v4_3.room_daily.occupancy_rate IS 'occupied_room_nights / available_room_nights';
COMMENT ON COLUMN serving.analytics_v4_3.room_daily.adr_krw IS 'room_revenue_krw / occupied_room_nights';
COMMENT ON COLUMN serving.analytics_v4_3.room_daily.revpar_krw IS 'room_revenue_krw / available_room_nights';

CREATE OR REPLACE VIEW serving.analytics_v4_3.room_monthly_kpi AS
SELECT date_trunc('month',business_date) month_start,hotel_code,
       SUM(available_room_nights) available_room_nights,SUM(occupied_room_nights) occupied_room_nights,
       SUM(room_revenue_krw) room_revenue_krw,
       CAST(SUM(occupied_room_nights) AS double)/NULLIF(SUM(available_room_nights),0) occupancy_rate,
       CAST(SUM(room_revenue_krw) AS double)/NULLIF(SUM(occupied_room_nights),0) adr_krw,
       CAST(SUM(room_revenue_krw) AS double)/NULLIF(SUM(available_room_nights),0) revpar_krw
FROM serving.analytics_v4_3.room_daily GROUP BY 1,2;
COMMENT ON VIEW serving.analytics_v4_3.room_monthly_kpi IS '일별 객실 실적을 월·호텔 단위로 가중 재집계한 합성 객실 KPI';
COMMENT ON COLUMN serving.analytics_v4_3.room_monthly_kpi.month_start IS 'KPI 집계월의 첫날';
COMMENT ON COLUMN serving.analytics_v4_3.room_monthly_kpi.hotel_code IS '합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_monthly_kpi.available_room_nights IS '월간 판매 가능 객실박 합계';
COMMENT ON COLUMN serving.analytics_v4_3.room_monthly_kpi.occupied_room_nights IS '월간 점유 객실박 합계';
COMMENT ON COLUMN serving.analytics_v4_3.room_monthly_kpi.room_revenue_krw IS '월간 합성 객실매출';
COMMENT ON COLUMN serving.analytics_v4_3.room_monthly_kpi.occupancy_rate IS '월간 점유 객실박/판매 가능 객실박';
COMMENT ON COLUMN serving.analytics_v4_3.room_monthly_kpi.adr_krw IS '월간 객실매출/점유 객실박';
COMMENT ON COLUMN serving.analytics_v4_3.room_monthly_kpi.revpar_krw IS '월간 객실매출/판매 가능 객실박';
