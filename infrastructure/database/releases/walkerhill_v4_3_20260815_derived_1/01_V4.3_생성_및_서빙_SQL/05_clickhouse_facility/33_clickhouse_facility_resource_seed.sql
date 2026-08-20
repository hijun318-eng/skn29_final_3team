-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=ClickHouse 24.8+; domain=FACILITY; script_type=SEED; execution_order=33
-- expected_rows=9203; grain=business_date+facility_id; dependency=20_clickhouse_facility_master_seed.sql
-- execution_default=NOT_RUN; caveat=engineering estimates, not actual Walkerhill meter readings or HCMI/HWMI reporting

SELECT throwIf(count()>0,'candidate facility resource table must be empty') FROM walkerhill_v4_3.facility_resource_daily;

INSERT INTO walkerhill_v4_3.facility_resource_daily
(business_date,facility_id,energy_kwh,water_m3,waste_kg,occupied_room_equivalent,weather_index,is_synthetic)
WITH
 ['F_GOLF','F_RIVERPARK','F_GRAND_FIT','F_VISTA_WELL','F_DOUGLAS_LIB','F_SAUNA','F_TENNIS','F_KIDS','F_GARDEN','F_CONV'] AS ids,
 toUInt32(intDiv(number,10)) AS day_i,
 toDate('2024-01-01')+day_i AS d,
 arrayElement(ids,toUInt32(1+modulo(number,10))) AS fid,
 1.0+0.22*cos(2*pi()*(toDayOfYear(d)-205)/365.25) AS weather,
 multiIf(toDayOfWeek(d)=5,1.10,toDayOfWeek(d)=6,1.18,toDayOfWeek(d)=7,1.08,1.0) AS lodging_operational_load,
 multiIf(d BETWEEN '2024-09-01' AND '2024-10-31',multiIf(fid IN ('F_CONV','F_GARDEN'),1.45,fid='F_RIVERPARK',1.22,1.12),
         d BETWEEN '2025-06-21' AND '2025-07-20',multiIf(fid='F_GOLF',1.60,fid IN ('F_VISTA_WELL','F_TENNIS'),1.28,1.10),
         d BETWEEN '2025-09-01' AND '2025-11-30',multiIf(fid IN ('F_CONV','F_GARDEN'),1.42,fid='F_GOLF',1.35,1.12),
         d BETWEEN '2026-04-22' AND '2026-06-07',multiIf(fid IN ('F_CONV','F_GARDEN'),1.34,fid='F_RIVERPARK',1.18,1.10),
         d BETWEEN '2026-06-26' AND '2026-08-30',multiIf(fid='F_RIVERPARK',1.55,fid IN ('F_GOLF','F_VISTA_WELL'),1.30,1.14),1.0) AS event_load,
 ((cityHash64(concat('resource|',toString(number),'|20260814'))%1000000)/1000000.0) AS u,
 multiIf(fid='F_RIVERPARK',4200.0,fid='F_SAUNA',1600.0,fid='F_GOLF',2100.0,fid='F_CONV',1800.0,420.0) AS base_energy,
 multiIf(fid='F_RIVERPARK',310.0,fid='F_SAUNA',150.0,fid='F_GOLF',95.0,28.0) AS base_water
SELECT d,fid,toDecimal64(base_energy*weather*lodging_operational_load*event_load*(0.92+u*0.16),3),
       toDecimal64(base_water*lodging_operational_load*event_load*(0.90+u*0.20),3),
       toDecimal64((12+base_energy/95)*lodging_operational_load*event_load*(0.88+u*0.24),3),
       toDecimal64((460+u*230)*lodging_operational_load*event_load,3),toDecimal64(weather,4),1
FROM numbers(9740)
WHERE fid!='F_GOLF' OR d>='2025-06-21';
