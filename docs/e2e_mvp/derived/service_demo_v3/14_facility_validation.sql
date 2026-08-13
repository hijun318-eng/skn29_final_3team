-- ClickHouse: any returned row is an actual violation.
SELECT 'FACILITY_EVENT_TARGET' AS issue,toString(count()) AS detail FROM facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' HAVING count()!=20000
UNION ALL SELECT 'FACILITY_EVENT_ORPHAN',event_id FROM facility.facility_events e LEFT JOIN facility.facility_master m ON e.facility_id=m.facility_id WHERE m.facility_id=''
UNION ALL SELECT 'FACILITY_INVALID_EVENT_METRIC',event_id FROM facility.facility_events WHERE duration_minutes<0 OR amount<0 OR downtime_minutes>duration_minutes
UNION ALL SELECT 'FACILITY_MASTER_HOURS',facility_id FROM facility.facility_master WHERE close_hour<=open_hour
UNION ALL SELECT 'FACILITY_FORECAST_MISMATCH',event_id FROM facility.facility_events WHERE is_forecast!=(data_period_status='FORECAST_SCENARIO')
UNION ALL SELECT 'FACILITY_STAFFING_COVERAGE',toString(count()) FROM facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001' HAVING count()!=5770
UNION ALL SELECT 'FACILITY_RESOURCE_COVERAGE',toString(count()) FROM facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001' HAVING count()!=4616;
