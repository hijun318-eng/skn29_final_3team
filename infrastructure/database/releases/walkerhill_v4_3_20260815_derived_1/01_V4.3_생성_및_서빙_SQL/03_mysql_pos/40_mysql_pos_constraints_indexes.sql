-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=MySQL 8.4; target_database=walkerhill_v4_3
-- domain=POS; script_type=CONSTRAINTS_INDEXES; execution_order=40
-- dependencies=32_mysql_pos_payment_refund_seed.sql; expected_rows=0
-- execution_default=NOT_RUN; destructive_operation=false
-- next=50_mysql_pos_validation.sql

USE walkerhill_v4_3;
ALTER TABLE pos_outlets ADD CONSTRAINT ck_v43_outlet_capacity CHECK(synthetic_seat_capacity>0);
ALTER TABLE pos_menu_items ADD CONSTRAINT fk_v43_menu_outlet FOREIGN KEY(outlet_id) REFERENCES pos_outlets(outlet_id);
ALTER TABLE pos_menu_price_history ADD CONSTRAINT fk_v43_price_item FOREIGN KEY(item_code) REFERENCES pos_menu_items(item_code),ADD CONSTRAINT ck_v43_price_dates CHECK(valid_to IS NULL OR valid_from<=valid_to),ADD CONSTRAINT ck_v43_price_amount CHECK(unit_price_krw>0);
ALTER TABLE pos_orders ADD CONSTRAINT fk_v43_order_outlet FOREIGN KEY(outlet_id) REFERENCES pos_outlets(outlet_id),ADD CONSTRAINT ck_v43_order_amount CHECK(net_amount=item_gross_amount-discount_amount+service_charge_amount+tax_amount-refund_amount-void_amount),ADD CONSTRAINT ck_v43_order_values CHECK(guest_count>0 AND item_gross_amount>=0 AND discount_amount>=0 AND refund_amount>=0 AND void_amount>=0),ADD CONSTRAINT ck_v43_order_status CHECK(order_status IN('PAID','PARTIAL_REFUND','REFUNDED','VOID'));
ALTER TABLE pos_order_items ADD CONSTRAINT fk_v43_item_order FOREIGN KEY(order_id) REFERENCES pos_orders(order_id),ADD CONSTRAINT fk_v43_item_menu FOREIGN KEY(item_code) REFERENCES pos_menu_items(item_code),ADD CONSTRAINT ck_v43_item_amount CHECK(quantity>0 AND unit_price>0 AND gross_amount=quantity*unit_price AND net_amount=gross_amount-discount_amount);
ALTER TABLE pos_payment_lines ADD CONSTRAINT fk_v43_payment_order FOREIGN KEY(order_id) REFERENCES pos_orders(order_id),ADD CONSTRAINT ck_v43_payment_sign CHECK((transaction_type='SALE' AND signed_amount>=0) OR (transaction_type='REFUND' AND signed_amount<0));
CREATE INDEX ix_v43_orders_outlet_date ON pos_orders(outlet_id,business_date,service_period);
CREATE INDEX ix_v43_orders_customer_date ON pos_orders(pos_customer_ref,business_date);
CREATE INDEX ix_v43_order_items_order ON pos_order_items(order_id,item_code);
CREATE INDEX ix_v43_payments_order ON pos_payment_lines(order_id,paid_at);
-- 외부 계정은 생성하지 않는다. pos_readonly GRANT는 운영 인증 구성에서 별도 적용한다.
