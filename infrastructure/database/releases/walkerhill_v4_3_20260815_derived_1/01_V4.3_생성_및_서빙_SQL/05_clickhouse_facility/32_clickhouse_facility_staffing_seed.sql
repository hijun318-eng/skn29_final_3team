-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=ClickHouse 24.8+; domain=FACILITY; script_type=SEED; execution_order=32
-- expected_rows=43830; grain=business_date+hotel_code+department+shift_code
-- dependency=10_clickhouse_facility_ddl.sql; execution_default=NOT_RUN

SELECT throwIf(count()>0,'candidate hotel staffing table must be empty') FROM walkerhill_v4_3.hotel_staffing_daily;

INSERT INTO walkerhill_v4_3.hotel_staffing_daily
(business_date,hotel_code,department,shift_code,planned_hours,actual_hours,guest_facing_fte,overtime_hours,event_load_index,is_synthetic)
WITH
 ['GRAND','VISTA','DOUGLAS'] AS hotels,['FRONT','HOUSEKEEPING','FNB','FACILITY','SECURITY'] AS deps,['DAY','EVENING','NIGHT'] AS shifts,
 toUInt32(intDiv(number,45)) AS day_i,
 toDate('2024-01-01')+day_i AS d,
 arrayElement(hotels,toUInt32(1+modulo(intDiv(number,15),3))) AS hotel,
 arrayElement(deps,toUInt32(1+modulo(intDiv(number,3),5))) AS dep,
 arrayElement(shifts,toUInt32(1+modulo(number,3))) AS shift,
 multiIf(toDayOfWeek(d)=5,1.08,toDayOfWeek(d)=6,1.15,toDayOfWeek(d)=7,1.08,1.0) AS lodging_operational_load,
 multiIf(d BETWEEN '2024-09-01' AND '2024-10-31',lodging_operational_load+multiIf(hotel='GRAND',0.32,hotel='VISTA',0.25,0.14),
         d BETWEEN '2024-12-01' AND '2024-12-31',lodging_operational_load+multiIf(hotel='GRAND',0.25,hotel='VISTA',0.30,0.16),
         d BETWEEN '2025-06-21' AND '2025-07-20',lodging_operational_load+multiIf(hotel='GRAND',0.18,hotel='VISTA',0.28,0.12),
         d BETWEEN '2025-09-01' AND '2025-11-30',lodging_operational_load+multiIf(hotel='GRAND',0.30,hotel='VISTA',0.24,0.13),
         d BETWEEN '2026-04-22' AND '2026-06-07',lodging_operational_load+multiIf(hotel='GRAND',0.24,hotel='VISTA',0.18,0.10),
         d BETWEEN '2026-06-26' AND '2026-08-30',lodging_operational_load+multiIf(hotel='GRAND',0.30,hotel='VISTA',0.34,0.18),lodging_operational_load) AS load,
 multiIf(hotel='GRAND',80.0,hotel='VISTA',48.0,24.0)*multiIf(dep='HOUSEKEEPING',1.25,dep='FNB',1.15,dep='SECURITY',0.55,1.0)*multiIf(shift='NIGHT',0.45,shift='EVENING',0.85,1.0)*load AS planned,
 ((cityHash64(concat('staff-var|',toString(number),'|20260814'))%20001)/100000.0-0.1) AS variance,
 greatest(8.0,planned*(1+variance)) AS actual
SELECT d,hotel,dep,shift,toDecimal64(planned,2),toDecimal64(actual,2),toDecimal64(actual/8,2),
       toDecimal64(greatest(0.0,actual-planned),2),toDecimal64(load,4),1
FROM numbers(43830);
