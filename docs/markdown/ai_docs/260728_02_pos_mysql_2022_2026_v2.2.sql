-- 호텔 데이터허브 합성 Source 데이터 적재 SQL
-- seed=20260728 / schema_version=schema-v4.6-websql / scenario_version=scenario-v4.6
-- fixture_version=source-fixture-v4.6 / property_id=SYNTHETIC_HOTEL_001 / synthetic=true
-- generated_at=2026-07-28T05:00:00Z / simulation_as_of_date=2026-07-28
-- source_id=pos / engine=MySQL 8.0 / database=hotel_pos
-- ingestion_role=pos_ingest / query_role=pos_query / trino_catalog=pos
-- 검증 상태: STATIC_REVALIDATED_PASS / DB_EXECUTION_NOT_RUN
-- DDL 생성 금지. v4.6 DDL이 먼저 적용되어 있어야 한다.

USE hotel_pos;
SET SESSION time_zone = '+00:00';
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';
SET SESSION max_execution_time = 1800000;
SET SESSION cte_max_recursion_depth = 2000000;

-- 전체 57개 컬럼 계약 검사.
SET @missing_columns := (
 SELECT COUNT(*) FROM (
   SELECT 'pos_stores' t,'property_id' c
   UNION ALL SELECT 'pos_stores' t,'store_id' c
   UNION ALL SELECT 'pos_stores' t,'store_name' c
   UNION ALL SELECT 'pos_stores' t,'store_category' c
   UNION ALL SELECT 'pos_stores' t,'seat_capacity' c
   UNION ALL SELECT 'pos_stores' t,'open_time' c
   UNION ALL SELECT 'pos_stores' t,'close_time' c
   UNION ALL SELECT 'pos_stores' t,'is_active' c
   UNION ALL SELECT 'pos_stores' t,'is_synthetic' c
   UNION ALL SELECT 'pos_stores' t,'source_updated_at' c
   UNION ALL SELECT 'pos_service_periods' t,'property_id' c
   UNION ALL SELECT 'pos_service_periods' t,'service_period_id' c
   UNION ALL SELECT 'pos_service_periods' t,'store_id' c
   UNION ALL SELECT 'pos_service_periods' t,'business_date' c
   UNION ALL SELECT 'pos_service_periods' t,'service_period' c
   UNION ALL SELECT 'pos_service_periods' t,'seat_capacity' c
   UNION ALL SELECT 'pos_service_periods' t,'open_minutes' c
   UNION ALL SELECT 'pos_service_periods' t,'covers' c
   UNION ALL SELECT 'pos_service_periods' t,'seat_hours_available' c
   UNION ALL SELECT 'pos_service_periods' t,'seat_hours_used' c
   UNION ALL SELECT 'pos_service_periods' t,'data_period_status' c
   UNION ALL SELECT 'pos_service_periods' t,'is_forecast' c
   UNION ALL SELECT 'pos_service_periods' t,'is_synthetic' c
   UNION ALL SELECT 'pos_service_periods' t,'source_updated_at' c
   UNION ALL SELECT 'pos_orders' t,'property_id' c
   UNION ALL SELECT 'pos_orders' t,'order_id' c
   UNION ALL SELECT 'pos_orders' t,'store_id' c
   UNION ALL SELECT 'pos_orders' t,'pos_customer_ref' c
   UNION ALL SELECT 'pos_orders' t,'ordered_at' c
   UNION ALL SELECT 'pos_orders' t,'check_opened_at' c
   UNION ALL SELECT 'pos_orders' t,'check_closed_at' c
   UNION ALL SELECT 'pos_orders' t,'guest_count' c
   UNION ALL SELECT 'pos_orders' t,'service_period' c
   UNION ALL SELECT 'pos_orders' t,'order_status' c
   UNION ALL SELECT 'pos_orders' t,'gross_amount' c
   UNION ALL SELECT 'pos_orders' t,'discount_amount' c
   UNION ALL SELECT 'pos_orders' t,'refund_amount' c
   UNION ALL SELECT 'pos_orders' t,'net_amount' c
   UNION ALL SELECT 'pos_orders' t,'payment_status' c
   UNION ALL SELECT 'pos_orders' t,'payment_amount' c
   UNION ALL SELECT 'pos_orders' t,'void_flag' c
   UNION ALL SELECT 'pos_orders' t,'data_period_status' c
   UNION ALL SELECT 'pos_orders' t,'is_forecast' c
   UNION ALL SELECT 'pos_orders' t,'is_synthetic' c
   UNION ALL SELECT 'pos_orders' t,'source_updated_at' c
   UNION ALL SELECT 'pos_order_items' t,'property_id' c
   UNION ALL SELECT 'pos_order_items' t,'order_item_id' c
   UNION ALL SELECT 'pos_order_items' t,'order_id' c
   UNION ALL SELECT 'pos_order_items' t,'item_code' c
   UNION ALL SELECT 'pos_order_items' t,'item_category' c
   UNION ALL SELECT 'pos_order_items' t,'quantity' c
   UNION ALL SELECT 'pos_order_items' t,'unit_price' c
   UNION ALL SELECT 'pos_order_items' t,'gross_amount' c
   UNION ALL SELECT 'pos_order_items' t,'discount_amount' c
   UNION ALL SELECT 'pos_order_items' t,'net_amount' c
   UNION ALL SELECT 'pos_order_items' t,'is_synthetic' c
   UNION ALL SELECT 'pos_order_items' t,'source_updated_at' c
 ) req
 WHERE NOT EXISTS (
   SELECT 1 FROM information_schema.columns c
   WHERE c.table_schema=DATABASE() AND c.table_name=req.t AND c.column_name=req.c
 )
);
SET @contract_sql := IF(@missing_columns=0,'SELECT ''SCHEMA_CONTRACT_PASS'' status','SELECT * FROM __SCHEMA_CONTRACT_MISMATCH__');
PREPARE contract_stmt FROM @contract_sql; EXECUTE contract_stmt; DEALLOCATE PREPARE contract_stmt;

SET @nonsynth := (
 SELECT (SELECT COUNT(*) FROM pos_stores WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=FALSE)
      + (SELECT COUNT(*) FROM pos_service_periods WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=FALSE)
      + (SELECT COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=FALSE)
      + (SELECT COUNT(*) FROM pos_order_items WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=FALSE)
);
SET @safety_sql := IF(@nonsynth=0,'SELECT ''SYNTHETIC_SCOPE_PASS'' status','SELECT * FROM __NON_SYNTHETIC_ROW_PRESENT__');
PREPARE safety_stmt FROM @safety_sql; EXECUTE safety_stmt; DEALLOCATE PREPARE safety_stmt;

START TRANSACTION;
DELETE FROM pos_order_items WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=TRUE;
DELETE FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=TRUE;
DELETE FROM pos_service_periods WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=TRUE;
DELETE FROM pos_stores WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=TRUE;

INSERT INTO pos_stores(property_id,store_id,store_name,store_category,seat_capacity,open_time,close_time,is_active,is_synthetic,source_updated_at)
VALUES
('SYNTHETIC_HOTEL_001','STR-01','Synthetic Breakfast 01','BREAKFAST',180,'06:00:00','11:00:00',TRUE,TRUE,'2026-07-28 04:00:00.000'),
('SYNTHETIC_HOTEL_001','STR-02','Synthetic Dining 01','DINING',140,'11:00:00','23:00:00',TRUE,TRUE,'2026-07-28 04:00:00.000'),
('SYNTHETIC_HOTEL_001','STR-03','Synthetic Dining 02','DINING',90,'11:00:00','22:00:00',TRUE,TRUE,'2026-07-28 04:00:00.000'),
('SYNTHETIC_HOTEL_001','STR-04','Synthetic Bar 01','BAR',80,'17:00:00','02:00:00',TRUE,TRUE,'2026-07-28 04:00:00.000'),
('SYNTHETIC_HOTEL_001','STR-05','Synthetic Cafe 01','CAFE',70,'08:00:00','21:00:00',TRUE,TRUE,'2026-07-28 04:00:00.000'),
('SYNTHETIC_HOTEL_001','STR-06','Synthetic Lounge 01','LOUNGE',110,'09:00:00','23:00:00',TRUE,TRUE,'2026-07-28 04:00:00.000'),
('SYNTHETIC_HOTEL_001','STR-07','Synthetic Breakfast 02','BREAKFAST',120,'06:30:00','11:30:00',TRUE,TRUE,'2026-07-28 04:00:00.000'),
('SYNTHETIC_HOTEL_001','STR-08','Synthetic Cafe 02','CAFE',60,'07:00:00','20:00:00',TRUE,TRUE,'2026-07-28 04:00:00.000');

INSERT INTO pos_service_periods(property_id,service_period_id,store_id,business_date,service_period,seat_capacity,open_minutes,covers,seat_hours_available,seat_hours_used,data_period_status,is_forecast,is_synthetic,source_updated_at)
WITH RECURSIVE dates AS (
 SELECT DATE('2022-01-01') d UNION ALL SELECT DATE_ADD(d,INTERVAL 1 DAY) FROM dates WHERE d<DATE('2026-07-28')
), periods AS (
 SELECT 'BREAKFAST' service_period,240 open_minutes,1 pord UNION ALL
 SELECT 'LUNCH',240,2 UNION ALL SELECT 'AFTERNOON',180,3 UNION ALL SELECT 'DINNER',300,4
), base AS (
 SELECT s.store_id,d.d business_date,p.service_period,p.open_minutes,p.pord,s.seat_capacity,
        FLOOR(s.seat_capacity*(.25 + MOD(CRC32(CONCAT(s.store_id,'|',DATE_FORMAT(d.d,'%Y-%m-%d'),'|',p.service_period)),55)/100.0)) covers
 FROM pos_stores s CROSS JOIN dates d CROSS JOIN periods p
 WHERE s.property_id='SYNTHETIC_HOTEL_001'
)
SELECT 'SYNTHETIC_HOTEL_001',DATEDIFF(business_date,'2022-01-01')*100+pord*10+CAST(SUBSTRING(store_id,5) AS UNSIGNED),
       store_id,business_date,service_period,seat_capacity,open_minutes,covers,
       ROUND(seat_capacity*open_minutes/60,2),
       LEAST(ROUND(seat_capacity*open_minutes/60,2),ROUND(covers*(.70+(pord%3)*.18),2)),
       CASE WHEN business_date<='2024-12-31' THEN 'REFERENCE_CALIBRATED' WHEN business_date<='2025-12-31' THEN 'SYNTHETIC_ACTUAL_LIKE' ELSE 'YTD_SYNTHETIC' END,
       FALSE,TRUE,LEAST(TIMESTAMP('2026-07-28 05:00:00.000'),TIMESTAMP(business_date,'23:30:00'))
FROM base;

-- 주문 자연키 = property + store + business_date + service_period + local order_slot.
INSERT INTO pos_orders(property_id,order_id,store_id,pos_customer_ref,ordered_at,check_opened_at,check_closed_at,guest_count,service_period,order_status,gross_amount,discount_amount,refund_amount,net_amount,payment_status,payment_amount,void_flag,data_period_status,is_forecast,is_synthetic,source_updated_at)
WITH RECURSIVE nums AS (SELECT 1 n UNION ALL SELECT n+1 FROM nums WHERE n<320000),
item_seed AS (
 SELECT n.n,seq.i,1+MOD(n.n,4) qty,
        ROUND((7000 + MOD(CRC32(CONCAT(n.n,'|',seq.i,'|PRICE')),33000))/1000)*1000 unit_price,
        CASE WHEN MOD(n.n+seq.i,11)=0 THEN .10 WHEN MOD(n.n+seq.i,7)=0 THEN .05 ELSE 0 END disc_rate
 FROM nums n CROSS JOIN (SELECT 1 i UNION ALL SELECT 2 UNION ALL SELECT 3) seq
), agg AS (
 SELECT n,SUM(qty*unit_price) gross_amount,SUM(ROUND(qty*unit_price*disc_rate,2)) discount_amount FROM item_seed GROUP BY n
), model AS (
 SELECT a.*,DATE_ADD('2022-01-01',INTERVAL MOD(a.n*37,1669) DAY) business_date,
        CONCAT('STR-',LPAD(1+MOD(a.n-1,8),2,'0')) store_id,
        CASE MOD(a.n,4) WHEN 0 THEN 'BREAKFAST' WHEN 1 THEN 'LUNCH' WHEN 2 THEN 'AFTERNOON' ELSE 'DINNER' END service_period,
        CASE WHEN MOD(a.n,100)<94 THEN 'PAID' WHEN MOD(a.n,100)<97 THEN 'PARTIAL_REFUND' WHEN MOD(a.n,100)<99 THEN 'REFUNDED' ELSE 'VOID' END order_status
 FROM agg a
), keyed AS (
 SELECT m.*,ROW_NUMBER() OVER(PARTITION BY business_date,store_id,service_period ORDER BY n) order_slot
 FROM model m
), timed AS (
 SELECT *,TIMESTAMP(business_date,CASE service_period WHEN 'BREAKFAST' THEN '08:00:00' WHEN 'LUNCH' THEN '13:00:00' WHEN 'AFTERNOON' THEN '16:00:00' ELSE '19:00:00' END)+INTERVAL MOD(n,90) MINUTE ordered_at
 FROM keyed
)
SELECT 'SYNTHETIC_HOTEL_001',
       CONCAT('ORD-',MD5(CONCAT('SYNTHETIC_HOTEL_001|',store_id,'|',DATE_FORMAT(business_date,'%Y-%m-%d'),'|',service_period,'|',order_slot))),
       store_id,
       CASE WHEN MOD(n,100)<68 AND business_date>=DATE('2022-04-11')
            THEN CONCAT('POSC-',LPAD(32+MOD(CRC32(CONCAT(store_id,'|',DATE_FORMAT(business_date,'%Y-%m-%d'),'|',order_slot)),68),8,'0')) ELSE NULL END,
       ordered_at,ordered_at-INTERVAL 5 MINUTE,ordered_at+INTERVAL 45 MINUTE,1+MOD(n,4),service_period,order_status,
       gross_amount,discount_amount,
       CASE order_status WHEN 'PARTIAL_REFUND' THEN ROUND((gross_amount-discount_amount)*.25,2) WHEN 'REFUNDED' THEN gross_amount-discount_amount ELSE 0 END,
       CASE order_status WHEN 'VOID' THEN 0 WHEN 'REFUNDED' THEN 0 WHEN 'PARTIAL_REFUND' THEN ROUND((gross_amount-discount_amount)*.75,2) ELSE gross_amount-discount_amount END,
       CASE order_status WHEN 'VOID' THEN 'FAILED' WHEN 'REFUNDED' THEN 'REFUNDED' WHEN 'PARTIAL_REFUND' THEN 'PARTIAL_REFUND' ELSE 'PAID' END,
       CASE order_status WHEN 'VOID' THEN 0 WHEN 'REFUNDED' THEN 0 WHEN 'PARTIAL_REFUND' THEN ROUND((gross_amount-discount_amount)*.75,2) ELSE gross_amount-discount_amount END,
       order_status='VOID',
       CASE WHEN business_date<='2024-12-31' THEN 'REFERENCE_CALIBRATED' WHEN business_date<='2025-12-31' THEN 'SYNTHETIC_ACTUAL_LIKE' ELSE 'YTD_SYNTHETIC' END,
       FALSE,TRUE,ordered_at+INTERVAL 50 MINUTE
FROM timed;

INSERT INTO pos_order_items(property_id,order_item_id,order_id,item_code,item_category,quantity,unit_price,gross_amount,discount_amount,net_amount,is_synthetic,source_updated_at)
WITH RECURSIVE nums AS (SELECT 1 n UNION ALL SELECT n+1 FROM nums WHERE n<320000),
model AS (
 SELECT n,DATE_ADD('2022-01-01',INTERVAL MOD(n*37,1669) DAY) business_date,
        CONCAT('STR-',LPAD(1+MOD(n-1,8),2,'0')) store_id,
        CASE MOD(n,4) WHEN 0 THEN 'BREAKFAST' WHEN 1 THEN 'LUNCH' WHEN 2 THEN 'AFTERNOON' ELSE 'DINNER' END service_period
 FROM nums
), keyed AS (
 SELECT m.*,ROW_NUMBER() OVER(PARTITION BY business_date,store_id,service_period ORDER BY n) order_slot FROM model m
), orders AS (
 SELECT *,CONCAT('ORD-',MD5(CONCAT('SYNTHETIC_HOTEL_001|',store_id,'|',DATE_FORMAT(business_date,'%Y-%m-%d'),'|',service_period,'|',order_slot))) order_id,
        TIMESTAMP(business_date,CASE service_period WHEN 'BREAKFAST' THEN '08:00:00' WHEN 'LUNCH' THEN '13:00:00' WHEN 'AFTERNOON' THEN '16:00:00' ELSE '19:00:00' END)+INTERVAL MOD(n,90) MINUTE ordered_at
 FROM keyed
), items AS (
 SELECT o.*,seq.i,1+MOD(o.n,4) qty,
        ROUND((7000 + MOD(CRC32(CONCAT(o.n,'|',seq.i,'|PRICE')),33000))/1000)*1000 unit_price,
        CASE WHEN MOD(o.n+seq.i,11)=0 THEN .10 WHEN MOD(o.n+seq.i,7)=0 THEN .05 ELSE 0 END disc_rate
 FROM orders o CROSS JOIN (SELECT 1 i UNION ALL SELECT 2 UNION ALL SELECT 3) seq
)
SELECT 'SYNTHETIC_HOTEL_001',CONCAT('ITM-',MD5(CONCAT(order_id,'|',i))),order_id,
       CONCAT('ITEM-',LPAD(1+MOD(n*3+i,120),3,'0')),
       CASE MOD(n+i,5) WHEN 0 THEN 'FOOD' WHEN 1 THEN 'BEVERAGE' WHEN 2 THEN 'ALCOHOL' WHEN 3 THEN 'DESSERT' ELSE 'SERVICE' END,
       qty,unit_price,qty*unit_price,ROUND(qty*unit_price*disc_rate,2),qty*unit_price-ROUND(qty*unit_price*disc_rate,2),TRUE,
       ordered_at+INTERVAL 50 MINUTE
FROM items;
COMMIT;

-- 모든 violation_count는 0이어야 한다.
SELECT 'store_orphan' check_name,COUNT(*) violation_count FROM pos_orders o LEFT JOIN pos_stores s ON s.property_id=o.property_id AND s.store_id=o.store_id WHERE o.property_id='SYNTHETIC_HOTEL_001' AND s.store_id IS NULL
UNION ALL SELECT 'order_item_orphan',COUNT(*) FROM pos_order_items i LEFT JOIN pos_orders o ON o.property_id=i.property_id AND o.order_id=i.order_id WHERE i.property_id='SYNTHETIC_HOTEL_001' AND o.order_id IS NULL
UNION ALL SELECT 'parent_child_property_mismatch',COUNT(*) FROM pos_order_items i JOIN pos_orders o ON o.order_id=i.order_id WHERE i.property_id='SYNTHETIC_HOTEL_001' AND i.property_id<>o.property_id
UNION ALL SELECT 'nonpositive_quantity',COUNT(*) FROM pos_order_items WHERE property_id='SYNTHETIC_HOTEL_001' AND quantity<=0
UNION ALL SELECT 'ordered_after_source_update',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND ordered_at>source_updated_at
UNION ALL SELECT 'closed_after_source_update',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND check_closed_at>source_updated_at
UNION ALL SELECT 'future_order',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND ordered_at>='2026-07-29'
UNION ALL SELECT 'gross_under_discount_refund',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND gross_amount<discount_amount+refund_amount
UNION ALL SELECT 'net_formula_mismatch',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND order_status NOT IN('VOID','OPEN') AND net_amount<>gross_amount-discount_amount-refund_amount
UNION ALL SELECT 'void_payment',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND order_status='VOID' AND payment_amount>0
UNION ALL SELECT 'refunded_net',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND order_status='REFUNDED' AND net_amount>0
UNION ALL SELECT 'paid_refund',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND order_status='PAID' AND refund_amount>0
UNION ALL SELECT 'partial_payment_mismatch',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND order_status='PARTIAL_REFUND' AND payment_amount<>net_amount
UNION ALL SELECT 'void_payment_status',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND order_status='VOID' AND payment_status<>'FAILED'
UNION ALL SELECT 'seat_hours_over_capacity',COUNT(*) FROM pos_service_periods WHERE property_id='SYNTHETIC_HOTEL_001' AND seat_hours_used>seat_hours_available
UNION ALL SELECT 'forecast_transaction',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND is_forecast=TRUE
UNION ALL SELECT 'customer_mapping_time_violation',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND pos_customer_ref IS NOT NULL AND DATE(ordered_at)<DATE_ADD('2022-01-01',INTERVAL CAST(RIGHT(pos_customer_ref,8) AS UNSIGNED)+1 DAY)
UNION ALL SELECT 'customer_ref_format',COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND pos_customer_ref IS NOT NULL AND pos_customer_ref NOT REGEXP '^POSC-[0-9]{8}$'
UNION ALL SELECT 'pii_pattern_violation',COUNT(*) FROM pos_stores WHERE property_id='SYNTHETIC_HOTEL_001' AND store_name REGEXP '[@]|[0-9]{2,3}[- ][0-9]{3,4}[- ][0-9]{4}';

WITH item_agg AS (
 SELECT property_id,order_id,SUM(gross_amount) item_gross,SUM(discount_amount) item_discount
 FROM pos_order_items WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY property_id,order_id
)
SELECT 'item_order_amount_mismatch' check_name,COUNT(*) violation_count
FROM pos_orders o JOIN item_agg i USING(property_id,order_id)
WHERE o.gross_amount<>i.item_gross OR o.discount_amount<>i.item_discount;

-- 주문과 좌석시간을 각각 월 grain으로 사전 집계한 뒤 1회 JOIN한다.
WITH order_month AS (
 SELECT DATE_FORMAT(ordered_at,'%Y-%m') year_month,store_id,service_period,data_period_status,is_forecast,
        SUM(net_amount) fnb_net_revenue,SUM(guest_count) covers,
        AVG(order_status IN('REFUNDED','PARTIAL_REFUND','VOID')) refund_void_rate
 FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001'
 GROUP BY 1,2,3,4,5
), seat_month AS (
 SELECT DATE_FORMAT(business_date,'%Y-%m') year_month,store_id,service_period,data_period_status,is_forecast,
        SUM(seat_hours_available) seat_hours_available,SUM(seat_hours_used) seat_hours_used
 FROM pos_service_periods WHERE property_id='SYNTHETIC_HOTEL_001'
 GROUP BY 1,2,3,4,5
)
SELECT o.year_month,o.store_id,o.service_period,o.data_period_status,o.is_forecast,
       o.fnb_net_revenue,o.covers,ROUND(o.fnb_net_revenue/NULLIF(o.covers,0),2) average_spend_per_guest,
       ROUND(o.fnb_net_revenue/NULLIF(s.seat_hours_available,0),2) revpash,
       ROUND(s.seat_hours_used/NULLIF(s.seat_hours_available,0),6) seat_hour_utilization,
       ROUND(o.refund_void_rate,6) refund_void_rate
FROM order_month o JOIN seat_month s USING(year_month,store_id,service_period,data_period_status,is_forecast)
ORDER BY 1,2,3;

SELECT 'pos_stores' table_name,COUNT(*) row_count,MAX(source_updated_at) watermark,MD5(CONCAT(COUNT(*),'|',MIN(store_id),'|',MAX(store_id),'|',SUM(CRC32(store_id)))) checksum FROM pos_stores WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'pos_service_periods',COUNT(*),MAX(source_updated_at),MD5(CONCAT(COUNT(*),'|',MIN(service_period_id),'|',MAX(service_period_id),'|',SUM(service_period_id))) FROM pos_service_periods WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'pos_orders',COUNT(*),MAX(source_updated_at),MD5(CONCAT(COUNT(*),'|',MIN(order_id),'|',MAX(order_id),'|',SUM(CRC32(order_id)))) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'pos_order_items',COUNT(*),MAX(source_updated_at),MD5(CONCAT(COUNT(*),'|',MIN(order_item_id),'|',MAX(order_item_id),'|',SUM(CRC32(order_item_id)))) FROM pos_order_items WHERE property_id='SYNTHETIC_HOTEL_001';

SELECT 20260728 seed,'schema-v4.6-websql' schema_version,'scenario-v4.6' scenario_version,'source-fixture-v4.6' fixture_version,'DB_EXECUTION_RESULT_ABOVE' execution_status;
