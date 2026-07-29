-- POS deterministic synthetic load v2.2 for contract 1.0.0
-- seed=20260729; schema_version=1.0.0; scenario_version=1.0.0
-- fixture_version=1.0.0; synthetic=true; property_id=SYNTHETIC_HOTEL_001
SET SESSION time_zone = '+00:00';
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';
SET SESSION max_execution_time = 1800000;
SET SESSION cte_max_recursion_depth = 1000000;
START TRANSACTION;

SET @unsafe_rows = (
    SELECT SUM(cnt) FROM (
        SELECT COUNT(*) cnt FROM pos_stores WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false
        UNION ALL SELECT COUNT(*) FROM pos_service_periods WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false
        UNION ALL SELECT COUNT(*) FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false
        UNION ALL SELECT COUNT(*) FROM pos_order_items WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false
    ) x
);
SET @guard_sql = IF(@unsafe_rows=0, 'SELECT 1', 'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT=''SCHEMA_CONTRACT_MISMATCH''');
PREPARE guard_stmt FROM @guard_sql;
EXECUTE guard_stmt;
DEALLOCATE PREPARE guard_stmt;

DELETE i FROM pos_order_items i JOIN pos_orders o ON o.order_id=i.order_id
WHERE o.property_id='SYNTHETIC_HOTEL_001';
DELETE FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001';
DELETE FROM pos_service_periods WHERE property_id='SYNTHETIC_HOTEL_001';
DELETE FROM pos_stores WHERE property_id='SYNTHETIC_HOTEL_001';

INSERT INTO pos_stores (
    property_id, store_id, store_name, store_category, seat_capacity,
    open_time, close_time, is_active, is_synthetic, source_updated_at
)
VALUES
('SYNTHETIC_HOTEL_001','STORE-01','Synthetic Breakfast 01','BREAKFAST',120,'06:00','12:00',true,true,'2026-07-28 05:00:00'),
('SYNTHETIC_HOTEL_001','STORE-02','Synthetic Dining 02','DINING',100,'11:00','23:00',true,true,'2026-07-28 05:00:00'),
('SYNTHETIC_HOTEL_001','STORE-03','Synthetic Dining 03','DINING',80,'11:00','23:00',true,true,'2026-07-28 05:00:00'),
('SYNTHETIC_HOTEL_001','STORE-04','Synthetic Bar 04','BAR',60,'16:00','23:59',true,true,'2026-07-28 05:00:00'),
('SYNTHETIC_HOTEL_001','STORE-05','Synthetic Cafe 05','CAFE',55,'08:00','22:00',true,true,'2026-07-28 05:00:00'),
('SYNTHETIC_HOTEL_001','STORE-06','Synthetic Lounge 06','LOUNGE',70,'10:00','23:00',true,true,'2026-07-28 05:00:00'),
('SYNTHETIC_HOTEL_001','STORE-07','Synthetic Dining 07','DINING',90,'11:00','22:00',true,true,'2026-07-28 05:00:00'),
('SYNTHETIC_HOTEL_001','STORE-08','Synthetic Cafe 08','CAFE',45,'07:00','20:00',true,true,'2026-07-28 05:00:00');

INSERT INTO pos_service_periods (
    property_id, service_period_id, store_id, business_date, service_period,
    seat_capacity, open_minutes, covers, seat_hours_available, seat_hours_used,
    data_period_status, is_forecast, is_synthetic, source_updated_at
)
WITH RECURSIVE dates AS (
    SELECT DATE('2022-01-01') AS d
    UNION ALL
    SELECT DATE_ADD(d, INTERVAL 1 DAY) FROM dates WHERE d < DATE('2026-07-28')
),
stores AS (
    SELECT 1 n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
),
periods AS (
    SELECT 1 p, 'BREAKFAST' period_name, 180 open_minutes UNION ALL
    SELECT 2, 'LUNCH', 240 UNION ALL SELECT 3, 'AFTERNOON', 180 UNION ALL
    SELECT 4, 'DINNER', 300
)
SELECT 'SYNTHETIC_HOTEL_001',
       DATEDIFF(d,'2022-01-01')*32 + (n-1)*4 + p + 1,
       CONCAT('STORE-',LPAD(n,2,'0')),
       d, period_name,
       CASE n WHEN 1 THEN 120 WHEN 2 THEN 100 WHEN 3 THEN 80 WHEN 4 THEN 60
              WHEN 5 THEN 55 WHEN 6 THEN 70 WHEN 7 THEN 90 ELSE 45 END,
       open_minutes,
       20 + MOD(DATEDIFF(d,'2022-01-01')*7+n*11+p*13,80),
       ROUND((CASE n WHEN 1 THEN 120 WHEN 2 THEN 100 WHEN 3 THEN 80 WHEN 4 THEN 60
                    WHEN 5 THEN 55 WHEN 6 THEN 70 WHEN 7 THEN 90 ELSE 45 END) * open_minutes/60,2),
       LEAST(
           ROUND((20 + MOD(DATEDIFF(d,'2022-01-01')*7+n*11+p*13,80))*1.25,2),
           ROUND((CASE n WHEN 1 THEN 120 WHEN 2 THEN 100 WHEN 3 THEN 80 WHEN 4 THEN 60
                         WHEN 5 THEN 55 WHEN 6 THEN 70 WHEN 7 THEN 90 ELSE 45 END) * open_minutes/60,2)
       ),
       CASE WHEN d<'2025-01-01' THEN 'REFERENCE_CALIBRATED'
            WHEN d<'2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE'
            ELSE 'YTD_SYNTHETIC' END,
       false,true,TIMESTAMP(DATE_ADD(d,INTERVAL 23 HOUR))
FROM dates CROSS JOIN stores CROSS JOIN periods;

INSERT INTO pos_orders (
    property_id, order_id, store_id, pos_customer_ref, ordered_at,
    check_opened_at, check_closed_at, guest_count, service_period, order_status,
    gross_amount, discount_amount, refund_amount, net_amount, payment_status,
    payment_amount, void_flag, data_period_status, is_forecast, is_synthetic,
    source_updated_at
)
WITH digits AS (
    SELECT 0 d UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
),
seq AS (
    SELECT a.d+10*b.d+100*c.d+1000*d.d+10000*e.d+100000*f.d AS n
    FROM digits a CROSS JOIN digits b CROSS JOIN digits c
    CROSS JOIN digits d CROSS JOIN digits e CROSS JOIN digits f
),
base AS (
    SELECT n,
           DATE_ADD('2022-01-01',INTERVAL MOD(n,1670) DAY) AS business_date,
           1+MOD(n,8) AS store_no,
           1+MOD(FLOOR(n/8),4) AS period_no,
           CASE WHEN MOD(n,100)=0 THEN 'VOID'
                WHEN MOD(n,80)=0 THEN 'REFUNDED'
                WHEN MOD(n,50)=0 THEN 'PARTIAL_REFUND'
                ELSE 'PAID' END AS order_status,
           CASE WHEN MOD(n,100)=0 THEN 69000
                WHEN MOD(n,10)=0 THEN 6900 ELSE 0 END AS order_discount
    FROM seq WHERE n<320000
),
amounts AS (
    SELECT *,
           69000-order_discount AS pre_refund,
           CASE WHEN order_status='REFUNDED' THEN 69000-order_discount
                WHEN order_status='PARTIAL_REFUND' THEN 10000 ELSE 0 END AS refund_amount
    FROM base
)
SELECT 'SYNTHETIC_HOTEL_001',
       CONCAT('ORD-',SUBSTRING(SHA2(CONCAT('SYNTHETIC_HOTEL_001|',n),256),1,32)),
       CONCAT('STORE-',LPAD(store_no,2,'0')),
       CASE WHEN MOD(n,100)<62 THEN CONCAT('POSC-',LPAD(1+MOD(n,80000),8,'0')) END,
       TIMESTAMP(business_date) + INTERVAL (6+period_no*3) HOUR + INTERVAL (MOD(n,120)) MINUTE,
       TIMESTAMP(business_date) + INTERVAL (6+period_no*3) HOUR + INTERVAL (MOD(n,120)-5) MINUTE,
       TIMESTAMP(business_date) + INTERVAL (6+period_no*3) HOUR + INTERVAL (MOD(n,120)+45) MINUTE,
       1+MOD(n,4),
       ELT(period_no,'BREAKFAST','LUNCH','AFTERNOON','DINNER'),
       order_status,69000,order_discount,refund_amount,
       CASE WHEN order_status='VOID' THEN 0 ELSE pre_refund-refund_amount END,
       CASE WHEN order_status='VOID' THEN 'FAILED'
            WHEN order_status='REFUNDED' THEN 'REFUNDED'
            WHEN order_status='PARTIAL_REFUND' THEN 'PARTIAL_REFUND' ELSE 'PAID' END,
       CASE WHEN order_status='VOID' THEN 0 ELSE pre_refund-refund_amount END,
       order_status='VOID',
       CASE WHEN business_date<'2025-01-01' THEN 'REFERENCE_CALIBRATED'
            WHEN business_date<'2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE'
            ELSE 'YTD_SYNTHETIC' END,
       false,true,
       TIMESTAMP(business_date) + INTERVAL (6+period_no*3) HOUR + INTERVAL (MOD(n,120)+60) MINUTE
FROM amounts;

INSERT INTO pos_order_items (
    property_id, order_item_id, order_id, item_code, item_category,
    quantity, unit_price, gross_amount, discount_amount, net_amount,
    is_synthetic, source_updated_at
)
WITH digits AS (
    SELECT 0 d UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
),
seq AS (
    SELECT a.d+10*b.d+100*c.d+1000*d.d+10000*e.d+100000*f.d AS n
    FROM digits a CROSS JOIN digits b CROSS JOIN digits c
    CROSS JOIN digits d CROSS JOIN digits e CROSS JOIN digits f
),
items AS (
    SELECT n,1 item_no,20000 price FROM seq WHERE n<320000
    UNION ALL SELECT n,2,23000 FROM seq WHERE n<320000
    UNION ALL SELECT n,3,26000 FROM seq WHERE n<320000
)
SELECT 'SYNTHETIC_HOTEL_001',
       CONCAT('ITM-',SUBSTRING(SHA2(CONCAT('SYNTHETIC_HOTEL_001|',n,'|',item_no),256),1,32)),
       CONCAT('ORD-',SUBSTRING(SHA2(CONCAT('SYNTHETIC_HOTEL_001|',n),256),1,32)),
       CONCAT('ITEM-',LPAD(item_no,3,'0')),
       ELT(item_no,'FOOD','BEVERAGE','SERVICE'),
       1,price,price,0,price,true,
       TIMESTAMP(DATE_ADD('2022-01-01',INTERVAL MOD(n,1670) DAY))
         + INTERVAL (6+(1+MOD(FLOOR(n/8),4))*3) HOUR + INTERVAL (MOD(n,120)+60) MINUTE
FROM items;

-- The generated-at cutoff is 2026-07-28 05:00:00 UTC. Orders that fall later
-- on the cutoff date are moved back one day with their item watermark.
UPDATE pos_orders
SET ordered_at=DATE_SUB(ordered_at,INTERVAL 1 DAY),
    check_opened_at=DATE_SUB(check_opened_at,INTERVAL 1 DAY),
    check_closed_at=DATE_SUB(check_closed_at,INTERVAL 1 DAY),
    source_updated_at=DATE_SUB(source_updated_at,INTERVAL 1 DAY)
WHERE property_id='SYNTHETIC_HOTEL_001'
  AND ordered_at>TIMESTAMP('2026-07-28 05:00:00');

UPDATE pos_order_items
SET source_updated_at=DATE_SUB(source_updated_at,INTERVAL 1 DAY)
WHERE property_id='SYNTHETIC_HOTEL_001'
  AND source_updated_at>TIMESTAMP('2026-07-28 05:00:00');

UPDATE pos_service_periods
SET source_updated_at=LEAST(source_updated_at,TIMESTAMP('2026-07-28 05:00:00'))
WHERE property_id='SYNTHETIC_HOTEL_001';

COMMIT;

SELECT 'pos_stores' table_name,COUNT(*) row_count,MAX(source_updated_at) watermark,
       SHA2(GROUP_CONCAT(store_id ORDER BY store_id),256) checksum
FROM pos_stores WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'pos_service_periods',COUNT(*),MAX(source_updated_at),SHA2(SUM(service_period_id),256)
FROM pos_service_periods WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'pos_orders',COUNT(*),MAX(source_updated_at),SHA2(SUM(CRC32(order_id)),256)
FROM pos_orders WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'pos_order_items',COUNT(*),MAX(source_updated_at),SHA2(SUM(CRC32(order_item_id)),256)
FROM pos_order_items WHERE property_id='SYNTHETIC_HOTEL_001';
