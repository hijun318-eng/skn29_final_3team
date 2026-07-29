-- ============================================================================
-- Answervice 팀공유 SQL 산출물
-- ownership_contract=team-ownership-v2.1
-- schema_version=schema-v4.6-websql
-- snapshot_as_of_at=2026-07-28T05:00:00Z
-- generation_as_of_at=2026-07-28T05:00:00Z
-- evaluation_as_of=2026-07-28T14:00:00+09:00
-- GENERATE_FILES=true / RUN_STATIC_VALIDATION=true / EXECUTE_DB=false
-- 접속정보·healthy 컨테이너는 실행 승인으로 간주하지 않는다.
-- 실제 실행 전 해당 owner의 approval_id가 필요하다.
-- ============================================================================
-- owner=R2_정승
-- work_card=R2-DB
-- output=260729_02_hotel_pos_mysql_ddl.sql

-- ============================================================================
-- 260729_02_hotel_pos_mysql_ddl.sql
-- Answervice POS schema contract v4.6
-- MySQL 8.0+ / mysql client
-- source_id=pos
-- engine=MySQL
-- database/schema=hotel_pos/hotel_pos
-- ingestion_role=pos_ingest
-- query_role=pos_query
-- datahub_platform_instance=hotel_pos
-- trino_catalog=pos
-- schema_version=schema-v4.6-websql
-- DDL·제약조건·인덱스·주석·검증만 포함한다.
-- ============================================================================
SET SESSION sql_mode =
  'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';
SET SESSION time_zone = '+00:00';
SET SESSION group_concat_max_len = 1048576;

CREATE DATABASE IF NOT EXISTS hotel_pos
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE hotel_pos;

DROP PROCEDURE IF EXISTS answervice_assert_table_contract_v46;
DELIMITER $$
CREATE PROCEDURE answervice_assert_table_contract_v46(
  IN p_table VARCHAR(64),
  IN p_expected LONGTEXT
)
SQL SECURITY INVOKER
BEGIN
  DECLARE v_exists INT DEFAULT 0;
  DECLARE v_actual LONGTEXT;
  SELECT COUNT(*) INTO v_exists
  FROM information_schema.tables
  WHERE table_schema=DATABASE() AND table_name=p_table AND table_type='BASE TABLE';

  IF v_exists > 0 THEN
    SELECT GROUP_CONCAT(
             CONCAT(column_name, ':', LOWER(column_type), ':', is_nullable)
             ORDER BY ordinal_position SEPARATOR '|'
           )
      INTO v_actual
    FROM information_schema.columns
    WHERE table_schema=DATABASE() AND table_name=p_table;

    IF BINARY v_actual <> BINARY p_expected THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT='SCHEMA_CONTRACT_MISMATCH: existing MySQL table columns differ';
    END IF;
  END IF;
END$$
DELIMITER ;

-- S05 pos_stores: 합성 F&B 매장 1건
CALL answervice_assert_table_contract_v46('pos_stores', 'property_id:varchar(64):NO|store_id:varchar(32):NO|store_name:varchar(100):NO|store_category:varchar(24):NO|seat_capacity:int:NO|open_time:time:NO|close_time:time:NO|is_active:tinyint(1):NO|is_synthetic:tinyint(1):NO|source_updated_at:datetime(3):NO');

CREATE TABLE IF NOT EXISTS `pos_stores` (
  `property_id` varchar(64) NOT NULL COMMENT '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
  `store_id` varchar(32) NOT NULL COMMENT '매장 ID. PK [classification=SYNTHETIC]',
  `store_name` varchar(100) NOT NULL COMMENT '합성 매장명.  [classification=SYNTHETIC]',
  `store_category` varchar(24) NOT NULL COMMENT '매장 유형. BREAKFAST/DINING/BAR/CAFE/LOUNGE [classification=SYNTHETIC]',
  `seat_capacity` INT NOT NULL COMMENT '좌석 수. 1 이상 [classification=SYNTHETIC]',
  `open_time` time NOT NULL COMMENT '영업 시작.  [classification=SYNTHETIC]',
  `close_time` time NOT NULL COMMENT '영업 종료.  [classification=SYNTHETIC]',
  `is_active` BOOLEAN NOT NULL COMMENT '활성 여부.  [classification=SYNTHETIC]',
  `is_synthetic` BOOLEAN NOT NULL COMMENT '합성 여부. 항상 true [classification=POLICY]',
  `source_updated_at` datetime(3) NOT NULL COMMENT '원천 수정시각. watermark [classification=SYNTHETIC]',
  PRIMARY KEY (`store_id`),
  CONSTRAINT `uq_pos_stores_property_id_store_id` UNIQUE (`property_id`, `store_id`),
  CONSTRAINT `ck_pos_stores_1` CHECK (`seat_capacity` > 0),
  CONSTRAINT `ck_pos_stores_2` CHECK (`open_time` <> `close_time`),
  CONSTRAINT `ck_pos_stores_3` CHECK (`is_synthetic`=TRUE),
  CONSTRAINT `ck_pos_stores_4` CHECK (`store_category` IN ('BREAKFAST','DINING','BAR','CAFE','LOUNGE'))
) ENGINE=InnoDB COMMENT='합성 F&B 매장 1건';

-- S06 pos_service_periods: 매장·영업일자·서비스 시간대별 좌석 운영 1건
CALL answervice_assert_table_contract_v46('pos_service_periods', 'property_id:varchar(64):NO|service_period_id:bigint:NO|store_id:varchar(32):NO|business_date:date:NO|service_period:varchar(16):NO|seat_capacity:int:NO|open_minutes:int:NO|covers:int:NO|seat_hours_available:decimal(14,2):NO|seat_hours_used:decimal(14,2):NO|data_period_status:varchar(32):NO|is_forecast:tinyint(1):NO|is_synthetic:tinyint(1):NO|source_updated_at:datetime(3):NO');

CREATE TABLE IF NOT EXISTS `pos_service_periods` (
  `property_id` varchar(64) NOT NULL COMMENT '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
  `service_period_id` bigint NOT NULL COMMENT '서비스 시간대 ID. PK [classification=SYNTHETIC]',
  `store_id` varchar(32) NOT NULL COMMENT '매장 ID.  [classification=SYNTHETIC]',
  `business_date` date NOT NULL COMMENT '영업일자.  [classification=SYNTHETIC]',
  `service_period` varchar(16) NOT NULL COMMENT '서비스 시간대. BREAKFAST/LUNCH/AFTERNOON/DINNER/LATE_NIGHT [classification=SYNTHETIC]',
  `seat_capacity` INT NOT NULL COMMENT '좌석 수.  [classification=SYNTHETIC]',
  `open_minutes` INT NOT NULL COMMENT '영업 분.  [classification=SYNTHETIC]',
  `covers` INT NOT NULL COMMENT '이용 인원.  [classification=SYNTHETIC]',
  `seat_hours_available` decimal(14,2) NOT NULL COMMENT '가용 좌석시간.  [classification=SYNTHETIC]',
  `seat_hours_used` decimal(14,2) NOT NULL COMMENT '사용 좌석시간.  [classification=SYNTHETIC]',
  `data_period_status` varchar(32) NOT NULL COMMENT '기간 상태. 4개 고정 상태 [classification=POLICY]',
  `is_forecast` BOOLEAN NOT NULL COMMENT '전망 여부. 2026-07 이후 true [classification=POLICY]',
  `is_synthetic` BOOLEAN NOT NULL COMMENT '합성 여부. 항상 true [classification=POLICY]',
  `source_updated_at` datetime(3) NOT NULL COMMENT '원천 수정시각. watermark [classification=SYNTHETIC]',
  PRIMARY KEY (`service_period_id`),
  CONSTRAINT `uq_pos_service_periods_property_id_store_id_bu_96b78479` UNIQUE (`property_id`, `store_id`, `business_date`, `service_period`),
  CONSTRAINT `ck_pos_service_periods_1` CHECK (`service_period` IN ('BREAKFAST','LUNCH','AFTERNOON','DINNER','LATE_NIGHT')),
  CONSTRAINT `ck_pos_service_periods_2` CHECK (`seat_capacity` > 0),
  CONSTRAINT `ck_pos_service_periods_3` CHECK (`open_minutes` > 0),
  CONSTRAINT `ck_pos_service_periods_4` CHECK (`covers` >= 0),
  CONSTRAINT `ck_pos_service_periods_5` CHECK (`seat_hours_available` >= 0),
  CONSTRAINT `ck_pos_service_periods_6` CHECK (`seat_hours_used` >= 0),
  CONSTRAINT `ck_pos_service_periods_7` CHECK (`seat_hours_used` <= `seat_hours_available`),
  CONSTRAINT `ck_pos_service_periods_8` CHECK (`seat_hours_available` = ROUND(`seat_capacity` * `open_minutes` / 60, 2)),
  CONSTRAINT `ck_pos_service_periods_9` CHECK (`is_synthetic`=TRUE),
  CONSTRAINT `ck_pos_service_periods_10` CHECK (`data_period_status` IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
  CONSTRAINT `ck_pos_service_periods_11` CHECK (`is_forecast` = (`data_period_status`='FORECAST_SCENARIO')),
  CONSTRAINT `ck_pos_service_periods_12` CHECK (((`business_date` BETWEEN DATE '2022-01-01' AND DATE '2024-12-31' AND `data_period_status`='REFERENCE_CALIBRATED') OR (`business_date` BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' AND `data_period_status`='SYNTHETIC_ACTUAL_LIKE') OR (`business_date` BETWEEN DATE '2026-01-01' AND DATE '2026-07-28' AND `data_period_status`='YTD_SYNTHETIC') OR (`business_date` BETWEEN DATE '2026-07-29' AND DATE '2026-12-31' AND `data_period_status`='FORECAST_SCENARIO'))),
  CONSTRAINT `fk_pos_service_store` FOREIGN KEY (`property_id`,`store_id`) REFERENCES `pos_stores` (`property_id`,`store_id`)
) ENGINE=InnoDB COMMENT='매장·영업일자·서비스 시간대별 좌석 운영 1건';

-- S07 pos_orders: 합성 주문·결제 1건
CALL answervice_assert_table_contract_v46('pos_orders', 'property_id:varchar(64):NO|order_id:varchar(36):NO|store_id:varchar(32):NO|pos_customer_ref:varchar(36):YES|ordered_at:datetime(3):NO|check_opened_at:datetime(3):NO|check_closed_at:datetime(3):YES|guest_count:int:NO|service_period:varchar(16):NO|order_status:varchar(20):NO|gross_amount:decimal(14,2):NO|discount_amount:decimal(14,2):NO|refund_amount:decimal(14,2):NO|net_amount:decimal(14,2):NO|payment_status:varchar(20):NO|payment_amount:decimal(14,2):NO|void_flag:tinyint(1):NO|data_period_status:varchar(32):NO|is_forecast:tinyint(1):NO|is_synthetic:tinyint(1):NO|source_updated_at:datetime(3):NO');

CREATE TABLE IF NOT EXISTS `pos_orders` (
  `property_id` varchar(64) NOT NULL COMMENT '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
  `order_id` varchar(36) NOT NULL COMMENT '주문 ID. PK [classification=SYNTHETIC]',
  `store_id` varchar(32) NOT NULL COMMENT '매장 ID.  [classification=SYNTHETIC]',
  `pos_customer_ref` varchar(36) COMMENT 'POS 고객 참조.  [classification=SYNTHETIC]',
  `ordered_at` datetime(3) NOT NULL COMMENT '주문 시각.  [classification=SYNTHETIC]',
  `check_opened_at` datetime(3) NOT NULL COMMENT '체크 시작.  [classification=SYNTHETIC]',
  `check_closed_at` datetime(3) COMMENT '체크 종료.  [classification=SYNTHETIC]',
  `guest_count` INT NOT NULL COMMENT '이용 인원.  [classification=SYNTHETIC]',
  `service_period` varchar(16) NOT NULL COMMENT '서비스 시간대.  [classification=SYNTHETIC]',
  `order_status` varchar(20) NOT NULL COMMENT '주문 상태. OPEN/PAID/VOID/PARTIAL_REFUND/REFUNDED [classification=SYNTHETIC]',
  `gross_amount` decimal(14,2) NOT NULL COMMENT '총액.  [classification=SYNTHETIC]',
  `discount_amount` decimal(14,2) NOT NULL COMMENT '할인 금액.  [classification=SYNTHETIC]',
  `refund_amount` decimal(14,2) NOT NULL COMMENT '환불 금액.  [classification=SYNTHETIC]',
  `net_amount` decimal(14,2) NOT NULL COMMENT '순매출. 핵심 metric 원자값 [classification=SYNTHETIC]',
  `payment_status` varchar(20) NOT NULL COMMENT '결제 상태. PAID/PARTIAL_REFUND/REFUNDED/FAILED [classification=SYNTHETIC]',
  `payment_amount` decimal(14,2) NOT NULL COMMENT '결제 금액.  [classification=SYNTHETIC]',
  `void_flag` BOOLEAN NOT NULL COMMENT '무효 여부.  [classification=SYNTHETIC]',
  `data_period_status` varchar(32) NOT NULL COMMENT '기간 상태. 4개 고정 상태 [classification=POLICY]',
  `is_forecast` BOOLEAN NOT NULL COMMENT '전망 여부. 2026-07 이후 true [classification=POLICY]',
  `is_synthetic` BOOLEAN NOT NULL COMMENT '합성 여부. 항상 true [classification=POLICY]',
  `source_updated_at` datetime(3) NOT NULL COMMENT '원천 수정시각. watermark [classification=SYNTHETIC]',
  PRIMARY KEY (`order_id`),
  CONSTRAINT `uq_pos_orders_property_id_order_id` UNIQUE (`property_id`, `order_id`),
  CONSTRAINT `ck_pos_orders_1` CHECK (`service_period` IN ('BREAKFAST','LUNCH','AFTERNOON','DINNER','LATE_NIGHT')),
  CONSTRAINT `ck_pos_orders_2` CHECK (`order_status` IN ('OPEN','PAID','VOID','PARTIAL_REFUND','REFUNDED')),
  CONSTRAINT `ck_pos_orders_3` CHECK (`payment_status` IN ('PAID','PARTIAL_REFUND','REFUNDED','FAILED')),
  CONSTRAINT `ck_pos_orders_4` CHECK (`guest_count` >= 1),
  CONSTRAINT `ck_pos_orders_5` CHECK (`gross_amount` >= 0),
  CONSTRAINT `ck_pos_orders_6` CHECK (`discount_amount` >= 0),
  CONSTRAINT `ck_pos_orders_7` CHECK (`refund_amount` >= 0),
  CONSTRAINT `ck_pos_orders_8` CHECK (`net_amount` >= 0),
  CONSTRAINT `ck_pos_orders_9` CHECK (`payment_amount` >= 0),
  CONSTRAINT `ck_pos_orders_10` CHECK (`discount_amount` <= `gross_amount`),
  CONSTRAINT `ck_pos_orders_11` CHECK (`check_opened_at` <= `ordered_at`),
  CONSTRAINT `ck_pos_orders_12` CHECK (`check_closed_at` IS NULL OR `check_closed_at` >= `ordered_at`),
  CONSTRAINT `ck_pos_orders_13` CHECK (`source_updated_at` >= `ordered_at`),
  CONSTRAINT `ck_pos_orders_14` CHECK (`check_closed_at` IS NULL OR `source_updated_at` >= `check_closed_at`),
  CONSTRAINT `ck_pos_orders_15` CHECK (((`order_status`='VOID' AND `net_amount`=0 AND `payment_amount`=0 AND `refund_amount`=0 AND `void_flag`=TRUE AND `payment_status`='FAILED') OR (`order_status`='REFUNDED' AND `net_amount`=0 AND `payment_amount`=0 AND `refund_amount`=`gross_amount`-`discount_amount` AND `payment_status`='REFUNDED' AND `void_flag`=FALSE) OR (`order_status`='PARTIAL_REFUND' AND `refund_amount`>0 AND `refund_amount`<`gross_amount`-`discount_amount` AND `net_amount`=`gross_amount`-`discount_amount`-`refund_amount` AND `payment_amount`=`net_amount` AND `payment_status`='PARTIAL_REFUND' AND `void_flag`=FALSE) OR (`order_status`='PAID' AND `refund_amount`=0 AND `net_amount`=`gross_amount`-`discount_amount` AND `payment_amount`=`net_amount` AND `payment_status`='PAID' AND `void_flag`=FALSE) OR (`order_status`='OPEN' AND `check_closed_at` IS NULL AND `payment_amount`=0 AND `void_flag`=FALSE))),
  CONSTRAINT `ck_pos_orders_16` CHECK (`is_synthetic`=TRUE),
  CONSTRAINT `ck_pos_orders_17` CHECK (`data_period_status` IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
  CONSTRAINT `ck_pos_orders_18` CHECK (`is_forecast` = (`data_period_status`='FORECAST_SCENARIO')),
  CONSTRAINT `fk_pos_order_store` FOREIGN KEY (`property_id`,`store_id`) REFERENCES `pos_stores` (`property_id`,`store_id`)
) ENGINE=InnoDB COMMENT='합성 주문·결제 1건';

-- S08 pos_order_items: 합성 주문 품목 1건
CALL answervice_assert_table_contract_v46('pos_order_items', 'property_id:varchar(64):NO|order_item_id:varchar(36):NO|order_id:varchar(36):NO|item_code:varchar(32):NO|item_category:varchar(32):NO|quantity:int:NO|unit_price:decimal(14,2):NO|gross_amount:decimal(14,2):NO|discount_amount:decimal(14,2):NO|net_amount:decimal(14,2):NO|is_synthetic:tinyint(1):NO|source_updated_at:datetime(3):NO');

CREATE TABLE IF NOT EXISTS `pos_order_items` (
  `property_id` varchar(64) NOT NULL COMMENT '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
  `order_item_id` varchar(36) NOT NULL COMMENT '주문 품목 ID. PK [classification=SYNTHETIC]',
  `order_id` varchar(36) NOT NULL COMMENT '주문 ID.  [classification=SYNTHETIC]',
  `item_code` varchar(32) NOT NULL COMMENT '상품 코드.  [classification=SYNTHETIC]',
  `item_category` varchar(32) NOT NULL COMMENT '상품 카테고리.  [classification=SYNTHETIC]',
  `quantity` INT NOT NULL COMMENT '수량. 1 이상 [classification=SYNTHETIC]',
  `unit_price` decimal(14,2) NOT NULL COMMENT '단가.  [classification=SYNTHETIC]',
  `gross_amount` decimal(14,2) NOT NULL COMMENT '품목 총액.  [classification=SYNTHETIC]',
  `discount_amount` decimal(14,2) NOT NULL COMMENT '품목 할인.  [classification=SYNTHETIC]',
  `net_amount` decimal(14,2) NOT NULL COMMENT '품목 순매출.  [classification=SYNTHETIC]',
  `is_synthetic` BOOLEAN NOT NULL COMMENT '합성 여부. 항상 true [classification=POLICY]',
  `source_updated_at` datetime(3) NOT NULL COMMENT '원천 수정시각. watermark [classification=SYNTHETIC]',
  PRIMARY KEY (`order_item_id`),
  CONSTRAINT `uq_pos_order_items_property_id_order_item_id` UNIQUE (`property_id`, `order_item_id`),
  CONSTRAINT `ck_pos_order_items_1` CHECK (`quantity` >= 1),
  CONSTRAINT `ck_pos_order_items_2` CHECK (`unit_price` >= 0),
  CONSTRAINT `ck_pos_order_items_3` CHECK (`gross_amount` >= 0),
  CONSTRAINT `ck_pos_order_items_4` CHECK (`discount_amount` >= 0),
  CONSTRAINT `ck_pos_order_items_5` CHECK (`net_amount` >= 0),
  CONSTRAINT `ck_pos_order_items_6` CHECK (`gross_amount` = `quantity` * `unit_price`),
  CONSTRAINT `ck_pos_order_items_7` CHECK (`discount_amount` <= `gross_amount`),
  CONSTRAINT `ck_pos_order_items_8` CHECK (`net_amount` = `gross_amount` - `discount_amount`),
  CONSTRAINT `ck_pos_order_items_9` CHECK (`is_synthetic`=TRUE),
  CONSTRAINT `fk_pos_item_order` FOREIGN KEY (`property_id`,`order_id`) REFERENCES `pos_orders` (`property_id`,`order_id`)
) ENGINE=InnoDB COMMENT='합성 주문 품목 1건';

SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='pos_service_periods' AND index_name='ix_pos_service_period_store_date'
);
SET @idx_sql := IF(@idx_exists=0,
  'CREATE INDEX `ix_pos_service_period_store_date` ON `pos_service_periods` (`store_id`, `business_date`, `service_period`)',
  'SELECT 1');
PREPARE idx_stmt FROM @idx_sql;
EXECUTE idx_stmt;
DEALLOCATE PREPARE idx_stmt;

SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='pos_orders' AND index_name='ix_pos_orders_store_ordered'
);
SET @idx_sql := IF(@idx_exists=0,
  'CREATE INDEX `ix_pos_orders_store_ordered` ON `pos_orders` (`store_id`, `ordered_at`)',
  'SELECT 1');
PREPARE idx_stmt FROM @idx_sql;
EXECUTE idx_stmt;
DEALLOCATE PREPARE idx_stmt;

SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='pos_orders' AND index_name='ix_pos_orders_customer_ordered'
);
SET @idx_sql := IF(@idx_exists=0,
  'CREATE INDEX `ix_pos_orders_customer_ordered` ON `pos_orders` (`pos_customer_ref`, `ordered_at`)',
  'SELECT 1');
PREPARE idx_stmt FROM @idx_sql;
EXECUTE idx_stmt;
DEALLOCATE PREPARE idx_stmt;

SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='pos_order_items' AND index_name='ix_pos_order_items_order'
);
SET @idx_sql := IF(@idx_exists=0,
  'CREATE INDEX `ix_pos_order_items_order` ON `pos_order_items` (`order_id`)',
  'SELECT 1');
PREPARE idx_stmt FROM @idx_sql;
EXECUTE idx_stmt;
DEALLOCATE PREPARE idx_stmt;

CREATE OR REPLACE VIEW pos_orders_actual AS
SELECT *
FROM pos_orders
WHERE is_forecast=FALSE
  AND data_period_status<>'FORECAST_SCENARIO';

CREATE ROLE IF NOT EXISTS 'pos_ingest', 'pos_query';
GRANT SELECT, INSERT, UPDATE, DELETE ON hotel_pos.* TO 'pos_ingest';
GRANT SELECT ON hotel_pos.* TO 'pos_query';

-- Read-only negative test commands. query role만 연결된 별도 시험 계정에서 실행한다.
-- SET ROLE 'pos_query';
-- INSERT INTO hotel_pos.pos_stores(property_id,store_id,store_name,store_category,seat_capacity,open_time,close_time,is_active,is_synthetic,source_updated_at)
-- VALUES ('NEGATIVE_TEST','X','X','CAFE',1,'00:00:00','01:00:00',TRUE,TRUE,UTC_TIMESTAMP(3));
-- 예상 결과: INSERT 권한 거부.
-- UPDATE hotel_pos.pos_stores SET store_name=store_name WHERE 1=0;
-- DELETE FROM hotel_pos.pos_stores WHERE 1=0;
-- ALTER TABLE hotel_pos.pos_stores ADD COLUMN __negative_test INT;
-- 예상 결과: UPDATE, DELETE, DDL 모두 권한 거부.

SELECT COUNT(*) AS source_table_count,
       IF(COUNT(*)=4,'PASS','SCHEMA_CONTRACT_MISMATCH') AS status
FROM information_schema.tables
WHERE table_schema=DATABASE() AND table_type='BASE TABLE'
  AND table_name IN ('pos_stores','pos_service_periods','pos_orders','pos_order_items');

SELECT COUNT(*) AS source_column_count,
       IF(COUNT(*)=57,'PASS','SCHEMA_CONTRACT_MISMATCH') AS status
FROM information_schema.columns
WHERE table_schema=DATABASE()
  AND table_name IN ('pos_stores','pos_service_periods','pos_orders','pos_order_items');

SELECT o.property_id,o.order_id,
       o.gross_amount,o.discount_amount,o.refund_amount,o.net_amount,
       COALESCE(SUM(i.gross_amount),0) AS item_gross_sum,
       COALESCE(SUM(i.discount_amount),0) AS item_discount_sum,
       COALESCE(SUM(i.net_amount),0) AS item_net_sum
FROM pos_orders o
LEFT JOIN pos_order_items i
  ON i.property_id=o.property_id AND i.order_id=o.order_id
GROUP BY o.property_id,o.order_id,o.gross_amount,o.discount_amount,o.refund_amount,o.net_amount
HAVING COALESCE(SUM(i.gross_amount),0) <> o.gross_amount
    OR COALESCE(SUM(i.net_amount),0) - o.refund_amount <> o.net_amount;

SELECT 'pos' AS source_id, 'MySQL' AS engine, 'hotel_pos/hotel_pos' AS database_schema,
       'pos_ingest' AS ingestion_role, 'pos_query' AS query_role,
       'hotel_pos' AS datahub_platform_instance, 'pos' AS trino_catalog,
       'schema-v4.6-websql' AS schema_version;

DROP PROCEDURE IF EXISTS answervice_assert_table_contract_v46;
