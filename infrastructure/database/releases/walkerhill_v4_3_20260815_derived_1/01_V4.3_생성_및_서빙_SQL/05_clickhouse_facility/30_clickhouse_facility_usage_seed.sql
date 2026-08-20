-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=ClickHouse 24.8+; domain=FACILITY; script_type=SEED; execution_order=30
-- expected_rows=733000; dependency=20_clickhouse_facility_master_seed.sql; execution_default=NOT_RUN
-- deterministic_rule=cityHash64(entity|process|seed) prevents event removal from shifting unrelated rows

SELECT throwIf(count()>0,'candidate facility usage table must be empty') FROM walkerhill_v4_3.facility_usage_events;

INSERT INTO walkerhill_v4_3.facility_usage_events
(usage_event_id,facility_id,event_time,usage_type,user_ref,party_size,duration_minutes,gross_amount,event_id,is_synthetic)
WITH
 ['F_GOLF','F_RIVERPARK','F_GRAND_FIT','F_VISTA_WELL','F_DOUGLAS_LIB','F_SAUNA','F_TENNIS','F_KIDS','F_GARDEN','F_CONV'] AS ids,
 ['F_RIVERPARK','F_GRAND_FIT','F_VISTA_WELL','F_DOUGLAS_LIB','F_SAUNA','F_TENNIS','F_KIDS','F_GARDEN','F_CONV'] AS pre_golf_ids,
 toDate('2024-01-01')+toUInt32(modulo(number*37,974)) AS d,
 if(d<'2025-06-21',arrayElement(pre_golf_ids,toUInt32(1+modulo(number*7919,9))),arrayElement(ids,toUInt32(1+modulo(number*7919,10)))) AS fid,
 multiIf(d BETWEEN '2026-06-26' AND '2026-08-30','E2026_RIVERPARK',
         d BETWEEN '2026-05-11' AND '2026-08-31','E2026_EARLY_SUMMER',
         d BETWEEN '2026-04-22' AND '2026-06-07','E2026_SPRING_JAZZ',
         d BETWEEN '2025-06-21' AND '2025-07-20','E2025_GOLF_OPEN',
         d BETWEEN '2025-12-01' AND '2025-12-31','E2025_YEAR_END',
         d BETWEEN '2025-09-01' AND '2025-11-30','E2025_AUTUMN',
         d BETWEEN '2025-07-14' AND '2025-12-31','E2025_GOLF_PACKAGE',
         d BETWEEN '2025-02-11' AND '2025-05-31','E2025_SPRING_ART',
         d='2024-12-17','E2024_CORP_1217',
         d BETWEEN '2024-12-01' AND '2024-12-31','E2024_YEAR_END',
         d BETWEEN '2024-09-01' AND '2024-10-31','E2024_AUTUMN',
         d BETWEEN '2024-03-15' AND '2024-05-31','E2024_SPRING',
         d BETWEEN '2024-01-01' AND '2024-03-31','E2024_BUFFET_HALO',NULL) AS eid,
 multiIf(isNull(eid),1.0,fid='F_GOLF',1.55,fid IN ('F_CONV','F_GARDEN'),1.42,
         fid='F_RIVERPARK',1.30,fid IN ('F_GRAND_FIT','F_VISTA_WELL'),1.22,1.12) AS event_multiplier,
 (cityHash64(concat('usage-value|',toString(number),'|20260814'))%1000000)/1000000.0 AS u
SELECT concat('FUEV_',leftPad(toString(number+1),10,'0')),
       fid,toDateTime(d,'Asia/Seoul')+toIntervalMinute(m.open_minute+modulo(cityHash64(concat('usage-minute|',toString(number),'|20260814')),m.close_minute-m.open_minute)),
       multiIf(fid IN ('F_GOLF','F_TENNIS'),'SESSION',fid='F_RIVERPARK','ENTRY',fid IN ('F_KIDS','F_GARDEN'),'PROGRAM',u<0.75,'ENTRY','RENTAL'),
       if(modulo(number,100)<68,concat('FUSR_',leftPad(toString(1+modulo(number*3571,110000)),8,'0')),NULL),
       toUInt16(1+floor(u*least(6.0,event_multiplier*4.0))),
       toUInt16(multiIf(fid='F_GOLF',120+floor(u*120),fid='F_RIVERPARK',60+floor(u*180),30+floor(u*90))),
       toDecimal64(multiIf(fid='F_GOLF',round((90000+u*210000)*event_multiplier,-3),
                           fid IN ('F_RIVERPARK','F_KIDS'),round((18000+u*62000)*event_multiplier,-3),
                           fid IN ('F_TENNIS','F_SAUNA'),round((12000+u*43000)*event_multiplier,-3),0),2),
       eid,1
FROM numbers(733000) AS n JOIN walkerhill_v4_3.facility_master m ON m.facility_id=fid;
