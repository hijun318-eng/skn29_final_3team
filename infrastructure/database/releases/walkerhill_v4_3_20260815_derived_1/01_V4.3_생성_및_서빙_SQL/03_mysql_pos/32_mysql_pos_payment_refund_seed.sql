-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=MySQL 8.4; target_database=walkerhill_v4_3
-- domain=POS; script_type=PAYMENT_REFUND_SEED; execution_order=32
-- dependencies=31_mysql_pos_order_item_seed.sql; expected_rows=762203
-- execution_default=NOT_RUN; destructive_operation=false
-- next=40_mysql_pos_constraints_indexes.sql

USE walkerhill_v4_3;
SET time_zone='+09:00';
DELIMITER //
CREATE PROCEDURE assert_empty_pos_payment_lines()
BEGIN
  IF EXISTS(SELECT 1 FROM pos_payment_lines LIMIT 1) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='candidate POS payment line table must be empty';
  END IF;
END//
DELIMITER ;
CALL assert_empty_pos_payment_lines();

INSERT INTO pos_payment_lines(payment_line_id,order_id,paid_at,transaction_type,tender_type,signed_amount,payment_status,is_synthetic)
SELECT CONCAT('PL_',SUBSTRING(order_id,3),'_SALE'),order_id,TIMESTAMPADD(MINUTE,45,ordered_at),'SALE',
       CASE WHEN linked_stay_id LIKE 'S_JOURNEY_%' THEN 'ROOM_CHARGE'
            WHEN linked_stay_id LIKE 'S_BRIDGE_%' AND v43_u01(CONCAT('payment-tender|',order_id))<0.62 THEN 'CREDIT_CARD'
            WHEN linked_stay_id LIKE 'S_BRIDGE_%' AND v43_u01(CONCAT('payment-tender|',order_id))<0.78 THEN 'MOBILE_PAY'
            WHEN linked_stay_id LIKE 'S_BRIDGE_%' THEN 'CASH'
            WHEN v43_u01(CONCAT('tender|',order_id))<0.62 THEN 'CREDIT_CARD'
            WHEN v43_u01(CONCAT('tender|',order_id))<0.78 THEN 'MOBILE_PAY'
            ELSE 'CASH' END,
       item_gross_amount-discount_amount+service_charge_amount+tax_amount,'SETTLED',true
FROM pos_orders WHERE order_status<>'VOID'
UNION ALL
SELECT CONCAT('PL_',SUBSTRING(order_id,3),'_REFUND'),order_id,TIMESTAMPADD(DAY,1,ordered_at),'REFUND',
       'ORIGINAL_TENDER',-refund_amount,'SETTLED',true
FROM pos_orders WHERE refund_amount>0;
