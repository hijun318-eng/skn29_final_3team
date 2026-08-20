-- Walkerhill V4.3 facility realism pilot. ClickHouse 24.8+. Read-only.

SELECT m.reporting_hotel_code AS hotel_code,m.facility_type,
       if(toDayOfWeek(u.event_time)=5,'FRIDAY',if(toDayOfWeek(u.event_time)=6,'SATURDAY','SUN_THU')) AS day_type,
       if(isNull(u.event_id),'NON_EVENT','EVENT') AS event_flag,
       count() AS usage_count,min(u.party_size) AS min_party_size,avg(u.party_size) AS average_party_size,
       if(count()>=30,'USABLE','INSUFFICIENT') AS sample_status,
       quantileExact(0.10)(u.party_size) AS p10_party_size,median(u.party_size) AS median_party_size,
       quantileExact(0.90)(u.party_size) AS p90_party_size,max(u.party_size) AS max_party_size,
       stddevSamp(u.party_size) AS stddev_party_size,
       avg(u.duration_minutes) AS average_duration_minutes,sum(u.gross_amount) AS gross_amount_krw
FROM walkerhill_v4_3.facility_usage_events u
INNER JOIN walkerhill_v4_3.facility_master m ON m.facility_id=u.facility_id
GROUP BY hotel_code,m.facility_type,day_type,event_flag
ORDER BY hotel_code,m.facility_type,day_type,event_flag;

SELECT m.reporting_hotel_code AS hotel_code,m.facility_type,toStartOfMonth(r.business_date) AS month_start,
       count() AS sample_days,
       if(count()>=14,'USABLE','INSUFFICIENT') AS sample_status,
       min(r.energy_kwh) AS min_energy_kwh,avg(r.energy_kwh) AS average_energy_kwh,
       median(r.energy_kwh) AS median_energy_kwh,quantileExact(0.90)(r.energy_kwh) AS p90_energy_kwh,
       max(r.energy_kwh) AS max_energy_kwh,stddevSamp(r.energy_kwh) AS stddev_energy_kwh,
       sum(r.water_m3) AS water_m3,sum(r.waste_kg) AS waste_kg,
       corr(toFloat64(r.occupied_room_equivalent),toFloat64(r.energy_kwh)) AS occupancy_energy_correlation
FROM walkerhill_v4_3.facility_resource_daily r
INNER JOIN walkerhill_v4_3.facility_master m ON m.facility_id=r.facility_id
GROUP BY hotel_code,m.facility_type,month_start
ORDER BY month_start,hotel_code,m.facility_type;

SELECT m.reporting_hotel_code AS hotel_code,i.severity,i.incident_type,i.resolution_status,
       count() AS incident_count,min(i.impact_minutes) AS min_impact_minutes,
       if(count()>=30,'USABLE','INSUFFICIENT') AS sample_status,
       avg(i.impact_minutes) AS average_impact_minutes,median(i.impact_minutes) AS median_impact_minutes,
       quantileExact(0.90)(i.impact_minutes) AS p90_impact_minutes,max(i.impact_minutes) AS max_impact_minutes,
       stddevSamp(i.impact_minutes) AS stddev_impact_minutes,sum(i.guest_impact_count) AS impacted_guests
FROM walkerhill_v4_3.facility_incidents i
INNER JOIN walkerhill_v4_3.facility_master m ON m.facility_id=i.facility_id
GROUP BY hotel_code,i.severity,i.incident_type,i.resolution_status
ORDER BY hotel_code,i.severity,i.incident_type,i.resolution_status;

WITH checks AS (
  SELECT 'usage_outside_capacity_or_duration' AS check_name,count() AS violation_count
  FROM walkerhill_v4_3.facility_usage_events u
  INNER JOIN walkerhill_v4_3.facility_master m ON m.facility_id=u.facility_id
  WHERE u.party_size=0 OR u.party_size>m.capacity OR u.duration_minutes=0
  UNION ALL
  SELECT 'usage_outside_open_hours',count()
  FROM walkerhill_v4_3.facility_usage_events u
  INNER JOIN walkerhill_v4_3.facility_master m ON m.facility_id=u.facility_id
  WHERE toHour(u.event_time)*60+toMinute(u.event_time)<m.open_minute
     OR toHour(u.event_time)*60+toMinute(u.event_time)>=m.close_minute
  UNION ALL
  SELECT 'incident_time_order_violation',count()
  FROM walkerhill_v4_3.facility_incidents
  WHERE NOT isNull(closed_at) AND closed_at<opened_at
  UNION ALL
  SELECT 'negative_resource_measure',count()
  FROM walkerhill_v4_3.facility_resource_daily
  WHERE energy_kwh<0 OR water_m3<0 OR waste_kg<0 OR occupied_room_equivalent<0
  UNION ALL
  SELECT 'negative_staffing_measure',count()
  FROM walkerhill_v4_3.hotel_staffing_daily
  WHERE planned_hours<0 OR actual_hours<0 OR guest_facing_fte<0 OR overtime_hours<0
)
SELECT check_name,violation_count,if(violation_count=0,'PASS','FAIL') AS status
FROM checks ORDER BY check_name;

SELECT hotel_code,department,shift_code,
       count() AS sample_days,avg(planned_hours) AS average_planned_hours,
       if(count()>=14,'USABLE','INSUFFICIENT') AS sample_status,
       avg(actual_hours) AS average_actual_hours,median(actual_hours) AS median_actual_hours,
       quantileExact(0.90)(actual_hours) AS p90_actual_hours,stddevSamp(actual_hours) AS stddev_actual_hours,
       avg(event_load_index) AS average_event_load,corr(toFloat64(event_load_index),toFloat64(actual_hours)) AS event_hours_correlation
FROM walkerhill_v4_3.hotel_staffing_daily
GROUP BY hotel_code,department,shift_code
ORDER BY hotel_code,department,shift_code;
