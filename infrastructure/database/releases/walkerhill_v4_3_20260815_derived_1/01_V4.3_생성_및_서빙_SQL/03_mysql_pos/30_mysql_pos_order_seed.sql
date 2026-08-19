-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=MySQL 8.4; target_database=walkerhill_v4_3
-- domain=POS; script_type=ORDER_SEED; execution_order=30
-- dependencies=21_mysql_pos_menu_price_history_seed.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814; expected_rows=733000
-- execution_default=NOT_RUN; destructive_operation=false
-- assumption=order volume and event uplift are synthetic and property-specific
-- next=31_mysql_pos_order_item_seed.sql

USE walkerhill_v4_3;
SET time_zone='+09:00';
DELIMITER //
CREATE PROCEDURE assert_empty_pos_orders()
BEGIN
  IF EXISTS(SELECT 1 FROM pos_orders LIMIT 1) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='candidate POS order table must be empty';
  END IF;
END//
DELIMITER ;
CALL assert_empty_pos_orders();

INSERT INTO pos_orders
(order_id,outlet_id,business_date,ordered_at,pos_customer_ref,linked_stay_id,guest_count,service_period,order_status,
 item_gross_amount,discount_amount,service_charge_amount,tax_amount,refund_amount,void_amount,net_amount,payment_status,
 currency_code,is_forecast,is_synthetic)
WITH digits(n) AS (SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9),
seq AS (SELECT 1+a.n+10*b.n+100*c.n+1000*d.n+10000*e.n+100000*f.n n FROM digits a CROSS JOIN digits b CROSS JOIN digits c CROSS JOIN digits d CROSS JOIN digits e CROSS JOIN digits f WHERE 1+a.n+10*b.n+100*c.n+1000*d.n+10000*e.n+100000*f.n<=733000),
tagged AS (
 SELECT n,CASE WHEN n<=2916 THEN 1+FLOOR((n-1)/3) END journey_seq,
        CASE WHEN n<=2916 THEN 1+MOD(n-1,3) END meal_no
 FROM seq
),
base_plan AS (
 SELECT t.n,t.journey_seq,t.meal_no,CONCAT('O_',LPAD(t.n,10,'0')) order_id,
        CASE WHEN t.journey_seq IS NULL THEN 1+MOD((t.n-1)*7919,12)
             WHEN MOD(t.journey_seq-1,3)=0 THEN CASE t.meal_no WHEN 1 THEN 2 WHEN 2 THEN 6 ELSE 3 END
             WHEN MOD(t.journey_seq-1,3)=1 THEN CASE t.meal_no WHEN 1 THEN 7 WHEN 2 THEN 10 ELSE 8 END
             ELSE CASE t.meal_no WHEN 1 THEN 11 WHEN 2 THEN 12 ELSE 11 END END outlet_seq,
        MOD(t.n*17,1000) event_pick,MOD(t.n*23,100) event_window,MOD(t.n*37,974) date_slot,
        CASE WHEN t.journey_seq IS NOT NULL THEN 1 ELSE 1+FLOOR(v43_u01(CONCAT('item-count|',t.n))*4) END item_count,
        CASE WHEN t.journey_seq IS NOT NULL THEN 'PAID' WHEN MOD(t.n*19,100)<94 THEN 'PAID'
             WHEN MOD(t.n*19,100)<98 THEN 'PARTIAL_REFUND'
             WHEN MOD(t.n*19,100)<99 THEN 'REFUNDED' ELSE 'VOID' END order_status
 FROM tagged t
), order_plan AS (
 SELECT b.n,b.journey_seq,b.meal_no,b.order_id,b.outlet_seq,
        CASE WHEN b.journey_seq IS NOT NULL THEN DATE_ADD(DATE '2024-01-01',INTERVAL (FLOOR((b.journey_seq-1)/3)*3+CASE WHEN b.meal_no=1 THEN 0 ELSE 1 END) DAY)
             WHEN b.event_pick < CASE WHEN b.outlet_seq<=6 THEN 140 WHEN b.outlet_seq<=10 THEN 170 ELSE 70 END
             THEN CASE WHEN b.event_window<18 THEN DATE_ADD(DATE '2024-09-01',INTERVAL MOD(b.date_slot,61) DAY)
                       WHEN b.event_window<28 THEN DATE_ADD(DATE '2024-12-01',INTERVAL MOD(b.date_slot,31) DAY)
                       WHEN b.event_window<39 THEN DATE_ADD(DATE '2025-06-21',INTERVAL MOD(b.date_slot,30) DAY)
                       WHEN b.event_window<54 THEN DATE_ADD(DATE '2025-09-01',INTERVAL MOD(b.date_slot,91) DAY)
                       WHEN b.event_window<68 THEN DATE_ADD(DATE '2026-04-22',INTERVAL MOD(b.date_slot,47) DAY)
                       WHEN b.event_window<82 THEN DATE_ADD(DATE '2026-05-11',INTERVAL MOD(b.date_slot,113) DAY)
                       ELSE DATE_ADD(DATE '2026-06-26',INTERVAL MOD(b.date_slot,66) DAY) END
             ELSE DATE_ADD(DATE '2024-01-01',INTERVAL b.date_slot DAY) END business_date,
        b.item_count,b.order_status
 FROM base_plan b
), item_slots(item_no) AS (SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4),
item_plan AS (
 SELECT p.*,o.outlet_id,o.hotel_code,o.outlet_category,o.open_time,o.close_time,i.item_no,
        CASE WHEN p.journey_seq IS NOT NULL THEN 1 ELSE 1+FLOOR(v43_u01(CONCAT('menu-slot|',p.n,'|',i.item_no))*6) END menu_slot,
        CASE WHEN p.journey_seq IS NOT NULL THEN 1 ELSE 1+FLOOR(v43_u01(CONCAT('quantity|',p.n,'|',i.item_no))*3) END quantity,
        CASE WHEN p.journey_seq IS NOT NULL THEN 0 WHEN v43_u01(CONCAT('discount-rate|',p.n))<0.62 THEN 0 WHEN v43_u01(CONCAT('discount-rate|',p.n))<0.88 THEN 0.05 ELSE 0.10 END discount_rate
 FROM order_plan p JOIN pos_outlets o ON o.outlet_seq=p.outlet_seq JOIN item_slots i ON i.item_no<=p.item_count
), priced AS (
 SELECT p.*,m.item_code,h.unit_price_krw,p.quantity*h.unit_price_krw gross,
        ROUND(p.quantity*h.unit_price_krw*p.discount_rate,0) item_discount
 FROM item_plan p JOIN pos_menu_items m ON m.outlet_id=p.outlet_id AND m.menu_slot=p.menu_slot
 JOIN pos_menu_price_history h ON h.item_code=m.item_code AND p.business_date>=h.valid_from AND (h.valid_to IS NULL OR p.business_date<=h.valid_to)
), header AS (
 SELECT n,journey_seq,meal_no,order_id,outlet_id,hotel_code,outlet_category,open_time,close_time,business_date,order_status,SUM(gross) item_gross,SUM(item_discount) item_discount
 FROM priced GROUP BY n,journey_seq,meal_no,order_id,outlet_id,hotel_code,outlet_category,open_time,close_time,business_date,order_status
), components AS (
 SELECT h.*,ROUND((h.item_gross-h.item_discount)*0.10,0) service_charge,
        ROUND(((h.item_gross-h.item_discount)+ROUND((h.item_gross-h.item_discount)*0.10,0))*0.10,0) tax_amount
 FROM header h
), final_amounts AS (
 SELECT c.*,(c.item_gross-c.item_discount+c.service_charge+c.tax_amount) charged,
        CASE c.order_status WHEN 'PARTIAL_REFUND' THEN ROUND((c.item_gross-c.item_discount+c.service_charge+c.tax_amount)*0.25,0)
             WHEN 'REFUNDED' THEN c.item_gross-c.item_discount+c.service_charge+c.tax_amount ELSE 0 END refund_amount,
        CASE WHEN c.order_status='VOID' THEN c.item_gross-c.item_discount+c.service_charge+c.tax_amount ELSE 0 END void_amount
 FROM components c
), scheduled AS (
 SELECT f.*,CASE WHEN f.journey_seq IS NOT NULL
              THEN TIMESTAMP(f.business_date,CASE f.meal_no WHEN 1 THEN TIME '19:00:00' WHEN 2 THEN TIME '08:00:00' ELSE TIME '19:00:00' END)
              ELSE TIMESTAMPADD(SECOND,
                FLOOR(v43_u01(CONCAT('order-second|',f.n))*
                  (TIME_TO_SEC(f.close_time)-TIME_TO_SEC(f.open_time)+CASE WHEN f.close_time<=f.open_time THEN 86400 ELSE 0 END)),
                TIMESTAMP(f.business_date,f.open_time)) END ordered_at
 FROM final_amounts f
)
SELECT f.order_id,f.outlet_id,f.business_date,f.ordered_at,
       CASE WHEN f.journey_seq IS NOT NULL THEN CONCAT('C',LPAD(f.journey_seq,9,'0'))
            WHEN MOD(f.n,10)<7 THEN CONCAT('C',LPAD(1+MOD(f.n-1,75000),9,'0')) END,
       CASE WHEN f.journey_seq IS NOT NULL THEN CONCAT('S_JOURNEY_',LPAD(f.journey_seq,10,'0'))
            WHEN f.order_status<>'VOID' AND v43_u01(CONCAT('tender|',f.order_id))>=0.78 AND v43_u01(CONCAT('tender|',f.order_id))<0.92
            THEN CONCAT('S_BRIDGE_',f.hotel_code,'_',DATE_FORMAT(f.business_date,'%Y%m%d')) END,
       1+FLOOR(v43_u01(CONCAT('covers|',f.n))*CASE WHEN f.outlet_category='BAR' THEN 3 ELSE 5 END),
       CASE WHEN HOUR(f.ordered_at) BETWEEN 6 AND 10 THEN 'BREAKFAST'
            WHEN HOUR(f.ordered_at) BETWEEN 11 AND 14 THEN 'LUNCH'
            WHEN HOUR(f.ordered_at) BETWEEN 15 AND 21 THEN 'DINNER' ELSE 'LATE_NIGHT' END,
       f.order_status,f.item_gross,f.item_discount,f.service_charge,f.tax_amount,f.refund_amount,f.void_amount,
       f.charged-f.refund_amount-f.void_amount,
       CASE WHEN f.order_status='VOID' THEN 'VOIDED' WHEN f.order_status IN('PARTIAL_REFUND','REFUNDED') THEN 'REFUNDED' ELSE 'SETTLED' END,
       'KRW',false,true
FROM scheduled f;
