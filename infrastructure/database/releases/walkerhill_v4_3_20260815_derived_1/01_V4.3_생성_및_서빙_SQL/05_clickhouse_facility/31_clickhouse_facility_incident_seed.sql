-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=ClickHouse 24.8+; domain=FACILITY; script_type=SEED; execution_order=31
-- expected_rows=6662; dependency=20_clickhouse_facility_master_seed.sql; execution_default=NOT_RUN
-- realism_rule=severity controls resolution duration and guest impact; weather incidents concentrate outdoors

SELECT throwIf(count()>0,'candidate facility incident table must be empty') FROM walkerhill_v4_3.facility_incidents;

INSERT INTO walkerhill_v4_3.facility_incidents
(incident_id,facility_id,opened_at,closed_at,severity,incident_type,impact_minutes,guest_impact_count,resolution_status,is_synthetic)
WITH
 ['F_GOLF','F_RIVERPARK','F_GRAND_FIT','F_VISTA_WELL','F_DOUGLAS_LIB','F_SAUNA','F_TENNIS','F_KIDS','F_GARDEN','F_CONV'] AS ids,
 ['F_RIVERPARK','F_GRAND_FIT','F_VISTA_WELL','F_DOUGLAS_LIB','F_SAUNA','F_TENNIS','F_KIDS','F_GARDEN','F_CONV'] AS pre_golf_ids,
 toDate('2024-01-01')+toUInt32(modulo(number*53,974)) AS d,
 if(d<'2025-06-21',arrayElement(pre_golf_ids,toUInt32(1+modulo(number*3571,9))),arrayElement(ids,toUInt32(1+modulo(number*3571,10)))) AS fid,
 (cityHash64(concat('incident-severity|',toString(number),'|20260814'))%1000000)/1000000.0 AS severity_u,
 (cityHash64(concat('incident-impact|',toString(number),'|20260814'))%1000000)/1000000.0 AS impact_u,
 (cityHash64(concat('incident-resolution|',toString(number),'|20260814'))%1000000)/1000000.0 AS resolution_u,
 multiIf(severity_u<0.83,'LOW',severity_u<0.975,'MEDIUM','HIGH') AS sev,
 toUInt32(multiIf(sev='LOW',15+floor(impact_u*90),sev='MEDIUM',90+floor(impact_u*360),360+floor(impact_u*1440))) AS impact,
 multiIf(resolution_u<0.92,'RESOLVED',resolution_u<0.98,'MONITORING','OPEN') AS result,
 toDateTime(d,'Asia/Seoul')+toIntervalMinute(m.open_minute+modulo(cityHash64(concat('incident-minute|',toString(number),'|20260814')),m.close_minute-m.open_minute)) AS opened
SELECT concat('FI_',leftPad(toString(number+1),8,'0')),fid,opened,
       if(result='RESOLVED',opened+toIntervalMinute(impact),NULL),sev,
       multiIf(fid IN ('F_GOLF','F_RIVERPARK','F_TENNIS','F_GARDEN') AND modulo(number,5)=0,'WEATHER',
               modulo(number,4)=0,'SAFETY',modulo(number,4)=1,'EQUIPMENT',modulo(number,4)=2,'CLEANLINESS','CAPACITY'),
       impact,toUInt32(floor((1+impact_u*18)*multiIf(sev='HIGH',3,sev='MEDIUM',1.7,1))),result,1
FROM numbers(6662) AS n JOIN walkerhill_v4_3.facility_master m ON m.facility_id=fid;
