-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=MySQL 8.4; target_database=walkerhill_v4_3
-- domain=POS; script_type=PRICE_HISTORY_SEED; execution_order=21
-- dependencies=20_mysql_pos_outlet_menu_seed.sql; expected_rows=216
-- execution_default=NOT_RUN; destructive_operation=false
-- next=30_mysql_pos_order_seed.sql

USE walkerhill_v4_3;
SET time_zone='+09:00';
INSERT INTO pos_menu_price_history(item_code,valid_from,valid_to,unit_price_krw,price_reason,is_synthetic)
SELECT m.item_code,DATE '2024-01-01',DATE '2024-12-31',
       ROUND((CASE o.outlet_category WHEN 'BUFFET' THEN 125000 WHEN 'RESTAURANT' THEN 68000 WHEN 'BAR' THEN 32000 WHEN 'LOUNGE' THEN 26000 ELSE 42000 END
         *(0.72+0.16*m.menu_slot+0.12*v43_u01(CONCAT('menu-price|',m.item_code))))/1000,0)*1000,
       'INITIAL_SYNTHETIC',true
FROM pos_menu_items m JOIN pos_outlets o USING(outlet_id)
UNION ALL
SELECT m.item_code,DATE '2025-01-01',DATE '2025-12-31',
       ROUND((CASE o.outlet_category WHEN 'BUFFET' THEN 125000 WHEN 'RESTAURANT' THEN 68000 WHEN 'BAR' THEN 32000 WHEN 'LOUNGE' THEN 26000 ELSE 42000 END
         *(0.72+0.16*m.menu_slot+0.12*v43_u01(CONCAT('menu-price|',m.item_code)))*(1.03+0.04*v43_u01(CONCAT('menu-reprice|',m.item_code))))/1000,0)*1000,
       'ANNUAL_SYNTHETIC_REPRICE_2025',true
FROM pos_menu_items m JOIN pos_outlets o USING(outlet_id)
UNION ALL
SELECT m.item_code,DATE '2026-01-01',NULL,
       ROUND((CASE o.outlet_category WHEN 'BUFFET' THEN 125000 WHEN 'RESTAURANT' THEN 68000 WHEN 'BAR' THEN 32000 WHEN 'LOUNGE' THEN 26000 ELSE 42000 END
         *(0.72+0.16*m.menu_slot+0.12*v43_u01(CONCAT('menu-price|',m.item_code)))
         *(1.03+0.04*v43_u01(CONCAT('menu-reprice|',m.item_code)))
         *(1.025+0.035*v43_u01(CONCAT('menu-reprice-2026|',m.item_code))))/1000,0)*1000,
       'ANNUAL_SYNTHETIC_REPRICE_2026',true
FROM pos_menu_items m JOIN pos_outlets o USING(outlet_id);
