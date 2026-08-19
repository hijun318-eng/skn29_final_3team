-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=MySQL 8.4; target_database=walkerhill_v4_3
-- domain=POS; script_type=MASTER_SEED; execution_order=20
-- dependencies=10_mysql_pos_ddl.sql; expected_rows=84
-- execution_default=NOT_RUN; destructive_operation=false
-- evidence=public dining concepts only; capacities and menu records are synthetic
-- next=21_mysql_pos_menu_price_history_seed.sql

USE walkerhill_v4_3;
SET time_zone='+09:00';
DELIMITER //
CREATE PROCEDURE assert_empty_pos_master()
BEGIN
  IF EXISTS(SELECT 1 FROM pos_outlets LIMIT 1) OR EXISTS(SELECT 1 FROM pos_menu_items LIMIT 1) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='candidate POS master tables must be empty';
  END IF;
END//
DELIMITER ;
CALL assert_empty_pos_master();

INSERT INTO pos_outlets
(resort_id,outlet_id,outlet_seq,hotel_code,public_name,outlet_category,open_time,close_time,synthetic_seat_capacity,source_url,provenance_class,is_active)
VALUES
('WH_COMPLEX','OUTLET_BUFFET',1,'GRAND','The Buffet','BUFFET','07:00','22:00',320,'https://app.walkerhill.com/book/Dining','MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','OUTLET_PIZZA',2,'GRAND','Pizza Hill','RESTAURANT','11:00','22:00',150,'https://app.walkerhill.com/book/Dining','MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','OUTLET_MYUNGWOL',3,'GRAND','Myungwolgwan','RESTAURANT','12:00','22:00',180,'https://app.walkerhill.com/book/Dining','MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','OUTLET_GEUMRYONG',4,'GRAND','Geumryong','RESTAURANT','12:00','22:00',120,'https://app.walkerhill.com/book/Dining','MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','OUTLET_PAVILION',5,'GRAND','The Pavilion','LOUNGE','08:00','23:00',95,'https://app.walkerhill.com/book/Dining','MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','OUTLET_GRAND_ROOM',6,'GRAND','Grand Room Service','ROOM_SERVICE','00:00','23:59',80,'https://app.walkerhill.com/book/Dining','GENERATED_REFERENCE',true),
('WH_COMPLEX','OUTLET_MOEGI',7,'VISTA','Moegi','RESTAURANT','12:00','22:00',110,'https://app.walkerhill.com/book/Dining','MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','OUTLET_DELVINO',8,'VISTA','Del Vino','RESTAURANT','12:00','23:00',90,'https://app.walkerhill.com/book/Dining','MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','OUTLET_REBAR',9,'VISTA','Re:BAR','BAR','17:00','01:00',75,'https://app.walkerhill.com/book/Dining','MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','OUTLET_VISTA_ROOM',10,'VISTA','Vista Room Service','ROOM_SERVICE','00:00','23:59',60,'https://app.walkerhill.com/book/Dining','GENERATED_REFERENCE',true),
('WH_COMPLEX','OUTLET_DOUGLAS',11,'DOUGLAS','Douglas Lounge','LOUNGE','07:00','23:00',48,'https://app.walkerhill.com/book/Dining','MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','OUTLET_DOUGLAS_ROOM',12,'DOUGLAS','Douglas Room Service','ROOM_SERVICE','00:00','23:59',24,'https://app.walkerhill.com/book/Dining','GENERATED_REFERENCE',true);

INSERT INTO pos_menu_items(item_code,outlet_id,menu_slot,item_name,item_category,provenance_class,is_active)
WITH RECURSIVE slots(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM slots WHERE n<6)
SELECT CONCAT('MI_',LPAD(o.outlet_seq,2,'0'),'_',LPAD(s.n,2,'0')),o.outlet_id,s.n,
       CONCAT('Synthetic ',o.outlet_category,' Item ',LPAD(s.n,2,'0')),
       CASE s.n WHEN 1 THEN 'SIGNATURE' WHEN 2 THEN 'MAIN' WHEN 3 THEN 'MAIN' WHEN 4 THEN 'SIDE' WHEN 5 THEN 'BEVERAGE' ELSE 'DESSERT' END,
       'GENERATED_FACT',true
FROM pos_outlets o CROSS JOIN slots s;
