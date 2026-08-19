-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=MySQL 8.4; target_database=walkerhill_v4_3
-- domain=POS; script_type=ORDER_ITEM_SEED; execution_order=31
-- dependencies=30_mysql_pos_order_seed.sql; expected_rows=1829312
-- execution_default=NOT_RUN; destructive_operation=false
-- next=32_mysql_pos_payment_refund_seed.sql

USE walkerhill_v4_3;
SET time_zone='+09:00';
DELIMITER //
CREATE PROCEDURE assert_empty_pos_order_items()
BEGIN
  IF EXISTS(SELECT 1 FROM pos_order_items LIMIT 1) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='candidate POS order item table must be empty';
  END IF;
END//
DELIMITER ;
CALL assert_empty_pos_order_items();

INSERT INTO pos_order_items(order_item_id,order_id,item_code,quantity,unit_price,gross_amount,discount_amount,net_amount,is_synthetic)
WITH item_slots(item_no) AS (SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4),
plan AS (
 SELECT o.order_id,o.outlet_id,o.business_date,i.item_no,
        CASE WHEN CAST(SUBSTRING(o.order_id,3) AS UNSIGNED)<=2916 THEN 1 ELSE 1+FLOOR(v43_u01(CONCAT('item-count|',CAST(SUBSTRING(o.order_id,3) AS UNSIGNED)))*4) END item_count,
        CASE WHEN CAST(SUBSTRING(o.order_id,3) AS UNSIGNED)<=2916 THEN 1 ELSE 1+FLOOR(v43_u01(CONCAT('menu-slot|',CAST(SUBSTRING(o.order_id,3) AS UNSIGNED),'|',i.item_no))*6) END menu_slot,
        CASE WHEN CAST(SUBSTRING(o.order_id,3) AS UNSIGNED)<=2916 THEN 1 ELSE 1+FLOOR(v43_u01(CONCAT('quantity|',CAST(SUBSTRING(o.order_id,3) AS UNSIGNED),'|',i.item_no))*3) END quantity,
        CASE WHEN CAST(SUBSTRING(o.order_id,3) AS UNSIGNED)<=2916 THEN 0
             WHEN v43_u01(CONCAT('discount-rate|',CAST(SUBSTRING(o.order_id,3) AS UNSIGNED)))<0.62 THEN 0
             WHEN v43_u01(CONCAT('discount-rate|',CAST(SUBSTRING(o.order_id,3) AS UNSIGNED)))<0.88 THEN 0.05 ELSE 0.10 END discount_rate
 FROM pos_orders o CROSS JOIN item_slots i
), priced AS (
 SELECT p.*,m.item_code,h.unit_price_krw,p.quantity*h.unit_price_krw gross
 FROM plan p JOIN pos_menu_items m ON m.outlet_id=p.outlet_id AND m.menu_slot=p.menu_slot
 JOIN pos_menu_price_history h ON h.item_code=m.item_code AND p.business_date>=h.valid_from AND (h.valid_to IS NULL OR p.business_date<=h.valid_to)
 WHERE p.item_no<=p.item_count
)
SELECT CONCAT('OI_',SUBSTRING(order_id,3),'_',item_no),order_id,item_code,quantity,unit_price_krw,gross,
       ROUND(gross*discount_rate,0),gross-ROUND(gross*discount_rate,0),true
FROM priced;
