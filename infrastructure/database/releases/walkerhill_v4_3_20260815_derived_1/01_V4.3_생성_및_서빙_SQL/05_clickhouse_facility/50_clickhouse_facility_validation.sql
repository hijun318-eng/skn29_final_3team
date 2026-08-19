-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=ClickHouse 24.8+; domain=FACILITY; script_type=VALIDATION_READONLY; execution_order=50
-- dependency=40_clickhouse_facility_indexes_settings.sql; execution_default=NOT_RUN

SELECT dataset,row_count,expected_min,expected_max,if(row_count BETWEEN expected_min AND expected_max,'PASS','FAIL') status
FROM (
 SELECT 'facility_master' dataset,count() row_count,toUInt64(10) expected_min,toUInt64(10) expected_max FROM walkerhill_v4_3.facility_master
 UNION ALL SELECT 'facility_usage_events',count(),733000,733000 FROM walkerhill_v4_3.facility_usage_events
 UNION ALL SELECT 'facility_incidents',count(),6662,6662 FROM walkerhill_v4_3.facility_incidents
 UNION ALL SELECT 'hotel_staffing_daily',count(),43830,43830 FROM walkerhill_v4_3.hotel_staffing_daily
 UNION ALL SELECT 'facility_resource_daily',count(),9203,9203 FROM walkerhill_v4_3.facility_resource_daily
);

SELECT 'usage_orphan_facility' check_name,count() violations FROM walkerhill_v4_3.facility_usage_events u LEFT JOIN walkerhill_v4_3.facility_master f ON f.facility_id=u.facility_id WHERE isNull(f.facility_id) OR f.facility_id=''
UNION ALL SELECT 'facility_reporting_hotel_code',count() FROM walkerhill_v4_3.facility_master WHERE reporting_hotel_code NOT IN('GRAND','VISTA','DOUGLAS')
UNION ALL SELECT 'incident_orphan_facility',count() FROM walkerhill_v4_3.facility_incidents i LEFT JOIN walkerhill_v4_3.facility_master f ON f.facility_id=i.facility_id WHERE isNull(f.facility_id) OR f.facility_id=''
UNION ALL SELECT 'resource_orphan_facility',count() FROM walkerhill_v4_3.facility_resource_daily r LEFT JOIN walkerhill_v4_3.facility_master f ON f.facility_id=r.facility_id WHERE isNull(f.facility_id) OR f.facility_id=''
UNION ALL SELECT 'negative_usage_amount',count() FROM walkerhill_v4_3.facility_usage_events WHERE gross_amount<0
UNION ALL SELECT 'golf_before_open',count() FROM walkerhill_v4_3.facility_usage_events WHERE facility_id='F_GOLF' AND toDate(event_time)<'2025-06-21'
UNION ALL SELECT 'usage_outside_operating_hours',count() FROM walkerhill_v4_3.facility_usage_events u JOIN walkerhill_v4_3.facility_master m ON m.facility_id=u.facility_id WHERE toHour(u.event_time)*60+toMinute(u.event_time)<m.open_minute OR toHour(u.event_time)*60+toMinute(u.event_time)>=m.close_minute
UNION ALL SELECT 'duplicate_facility_id',count() FROM (SELECT facility_id FROM walkerhill_v4_3.facility_master GROUP BY facility_id HAVING count()>1)
UNION ALL SELECT 'duplicate_usage_event_id',count() FROM (SELECT usage_event_id FROM walkerhill_v4_3.facility_usage_events GROUP BY usage_event_id HAVING count()>1)
UNION ALL SELECT 'duplicate_incident_id',count() FROM (SELECT incident_id FROM walkerhill_v4_3.facility_incidents GROUP BY incident_id HAVING count()>1)
UNION ALL SELECT 'duplicate_staffing_grain',count() FROM (SELECT business_date,hotel_code,department,shift_code FROM walkerhill_v4_3.hotel_staffing_daily GROUP BY business_date,hotel_code,department,shift_code HAVING count()>1)
UNION ALL SELECT 'duplicate_resource_grain',count() FROM (SELECT business_date,facility_id FROM walkerhill_v4_3.facility_resource_daily GROUP BY business_date,facility_id HAVING count()>1)
UNION ALL SELECT 'incident_resolution_time_mismatch',count() FROM walkerhill_v4_3.facility_incidents WHERE (resolution_status='RESOLVED' AND (closed_at IS NULL OR closed_at<opened_at)) OR (resolution_status IN('OPEN','MONITORING') AND closed_at IS NOT NULL)
UNION ALL SELECT 'high_incident_resolved_missing',if(countIf(severity='HIGH' AND resolution_status='RESOLVED')=0,1,0) FROM walkerhill_v4_3.facility_incidents;

SELECT dataset,min_date,max_date,distinct_days,if(min_date='2024-01-01' AND max_date='2026-08-31' AND distinct_days=974,'PASS','FAIL') status
FROM (
 SELECT 'hotel_staffing_daily' dataset,min(business_date) min_date,max(business_date) max_date,countDistinct(business_date) distinct_days FROM walkerhill_v4_3.hotel_staffing_daily
 UNION ALL SELECT 'facility_resource_daily',min(business_date),max(business_date),countDistinct(business_date) FROM walkerhill_v4_3.facility_resource_daily
);

SELECT toYYYYMM(event_time) month,facility_id,count() uses,sum(party_size) guests,sum(gross_amount) gross_amount
FROM walkerhill_v4_3.facility_usage_events GROUP BY month,facility_id ORDER BY month,facility_id;

SELECT u.event_id,m.hotel_code,count() uses,sum(u.party_size) guests,sum(u.gross_amount) gross_amount
FROM walkerhill_v4_3.facility_usage_events u JOIN walkerhill_v4_3.facility_master m ON m.facility_id=u.facility_id
WHERE u.event_id IS NOT NULL GROUP BY u.event_id,m.hotel_code ORDER BY u.event_id,m.hotel_code;
