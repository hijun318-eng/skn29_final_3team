-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING_FACILITY; script_type=VIEW; execution_order=24
-- dependency=facility.walkerhill_v4_3; execution_default=NOT_RUN

CREATE OR REPLACE VIEW serving.analytics_v4_3.facility_daily AS
WITH uses AS (
 SELECT CAST(u.event_time AS date) business_date,m.reporting_hotel_code hotel_code,COUNT(*) usage_events,SUM(u.party_size) facility_guests,SUM(u.gross_amount) facility_revenue_krw
 FROM facility.walkerhill_v4_3.facility_usage_events u JOIN facility.walkerhill_v4_3.facility_master m ON m.facility_id=u.facility_id GROUP BY 1,2
), incidents AS (
 SELECT CAST(i.opened_at AS date) business_date,m.reporting_hotel_code hotel_code,COUNT(*) incidents,
        COUNT(*) FILTER(WHERE i.severity='HIGH') high_severity_incidents,SUM(i.impact_minutes) incident_impact_minutes
 FROM facility.walkerhill_v4_3.facility_incidents i JOIN facility.walkerhill_v4_3.facility_master m ON m.facility_id=i.facility_id GROUP BY 1,2
), resources AS (
 SELECT r.business_date,m.reporting_hotel_code hotel_code,SUM(r.energy_kwh) energy_kwh,SUM(r.water_m3) water_m3,SUM(r.waste_kg) waste_kg
 FROM facility.walkerhill_v4_3.facility_resource_daily r JOIN facility.walkerhill_v4_3.facility_master m ON m.facility_id=r.facility_id GROUP BY 1,2
)
SELECT COALESCE(u.business_date,i.business_date,r.business_date) business_date,
       COALESCE(u.hotel_code,i.hotel_code,r.hotel_code) hotel_code,
       COALESCE(u.usage_events,0) usage_events,COALESCE(u.facility_guests,0) facility_guests,
       COALESCE(u.facility_revenue_krw,DECIMAL '0') facility_revenue_krw,
       COALESCE(i.incidents,0) incidents,COALESCE(i.high_severity_incidents,0) high_severity_incidents,
       COALESCE(i.incident_impact_minutes,0) incident_impact_minutes,
       COALESCE(r.energy_kwh,DECIMAL '0') energy_kwh,COALESCE(r.water_m3,DECIMAL '0') water_m3,COALESCE(r.waste_kg,DECIMAL '0') waste_kg
FROM uses u FULL OUTER JOIN incidents i
  ON i.business_date=u.business_date AND i.hotel_code=u.hotel_code
FULL OUTER JOIN resources r ON r.business_date=COALESCE(u.business_date,i.business_date) AND r.hotel_code=COALESCE(u.hotel_code,i.hotel_code);
COMMENT ON VIEW serving.analytics_v4_3.facility_daily IS '시설·사고·자원 원천을 호텔 운영일 수준으로 선집계한 합성 시설 KPI';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.business_date IS '시설 활동의 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.hotel_code IS '공용 시설까지 GRAND·VISTA·DOUGLAS 중 하나에 귀속한 합성 보고 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.usage_events IS '시설 이용 이벤트 수';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.facility_guests IS '시설 이용 합성 인원 합계';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.facility_revenue_krw IS '유료 시설 합성 총매출';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.incidents IS '시설 사고·불편 건수';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.high_severity_incidents IS 'HIGH 심각도 사고 건수';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.incident_impact_minutes IS '사고 운영 영향 시간 합계(분)';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.energy_kwh IS '합성 전력 사용량 합계(kWh)';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.water_m3 IS '합성 용수 사용량 합계(m³)';
COMMENT ON COLUMN serving.analytics_v4_3.facility_daily.waste_kg IS '합성 폐기물 발생량 합계(kg)';

CREATE OR REPLACE VIEW serving.analytics_v4_3.staffing_daily AS
SELECT business_date,hotel_code,SUM(planned_hours) planned_hours,SUM(actual_hours) actual_hours,
       SUM(guest_facing_fte) guest_facing_fte,SUM(overtime_hours) overtime_hours,MAX(event_load_index) event_load_index
FROM facility.walkerhill_v4_3.hotel_staffing_daily GROUP BY 1,2;
COMMENT ON VIEW serving.analytics_v4_3.staffing_daily IS '호텔·영업일 단위로 근무조와 부서를 합산한 합성 인력 KPI';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily.business_date IS '인력 실적 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily.hotel_code IS '인력이 배치된 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily.planned_hours IS '부서·근무조 계획 근로시간 합계';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily.actual_hours IS '부서·근무조 실제 근로시간 합계';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily.guest_facing_fte IS '8시간 기준 고객 접점 합성 FTE 합계';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily.overtime_hours IS '계획 대비 초과근로시간 합계';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily.event_load_index IS '해당 호텔 영업일의 최대 이벤트 부하 지수';
