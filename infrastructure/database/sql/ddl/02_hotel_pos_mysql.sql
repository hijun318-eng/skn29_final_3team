-- source_id=pos; engine=MySQL; database=pos_db
-- ingestion_role=pos_ingest; query_role=pos_readonly
-- datahub_platform_instance=pos_db; trino_catalog=pos
-- schema_version=1.0.0
SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;
SET time_zone = '+09:00';

CREATE ROLE IF NOT EXISTS 'pos_ingest', 'pos_readonly';

CREATE TABLE IF NOT EXISTS pos_stores (
    property_id varchar(64) NOT NULL,
    store_id varchar(32) PRIMARY KEY,
    store_name varchar(100) NOT NULL,
    store_category varchar(24) NOT NULL,
    seat_capacity integer NOT NULL CHECK (seat_capacity >= 1),
    open_time time NOT NULL,
    close_time time NOT NULL,
    is_active boolean NOT NULL,
    is_synthetic boolean NOT NULL CHECK (is_synthetic = true),
    source_updated_at datetime(3) NOT NULL,
    UNIQUE KEY uq_pos_store_property (property_id, store_id)
) ENGINE=InnoDB COMMENT='Synthetic F&B store master';

CREATE TABLE IF NOT EXISTS pos_service_periods (
    property_id varchar(64) NOT NULL,
    service_period_id bigint PRIMARY KEY,
    store_id varchar(32) NOT NULL,
    business_date date NOT NULL,
    service_period varchar(16) NOT NULL,
    seat_capacity integer NOT NULL CHECK (seat_capacity >= 1),
    open_minutes integer NOT NULL CHECK (open_minutes > 0),
    covers integer NOT NULL CHECK (covers >= 0),
    seat_hours_available decimal(14,2) NOT NULL CHECK (seat_hours_available >= 0),
    seat_hours_used decimal(14,2) NOT NULL CHECK (seat_hours_used >= 0),
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL CHECK (is_synthetic = true),
    source_updated_at datetime(3) NOT NULL,
    CONSTRAINT fk_pos_period_store FOREIGN KEY (store_id) REFERENCES pos_stores(store_id),
    UNIQUE KEY uq_pos_period (property_id, store_id, business_date, service_period),
    CONSTRAINT ck_pos_period_seat_hours CHECK (seat_hours_used <= seat_hours_available),
    CONSTRAINT ck_pos_period_forecast CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO'))
) ENGINE=InnoDB COMMENT='Daily store and service-period seat operation';

CREATE TABLE IF NOT EXISTS pos_orders (
    property_id varchar(64) NOT NULL,
    order_id varchar(36) PRIMARY KEY,
    store_id varchar(32) NOT NULL,
    pos_customer_ref varchar(36),
    ordered_at datetime(3) NOT NULL,
    check_opened_at datetime(3) NOT NULL,
    check_closed_at datetime(3),
    guest_count integer NOT NULL CHECK (guest_count >= 1),
    service_period varchar(16) NOT NULL,
    order_status varchar(20) NOT NULL,
    gross_amount decimal(14,2) NOT NULL CHECK (gross_amount >= 0),
    discount_amount decimal(14,2) NOT NULL CHECK (discount_amount >= 0),
    refund_amount decimal(14,2) NOT NULL CHECK (refund_amount >= 0),
    net_amount decimal(14,2) NOT NULL CHECK (net_amount >= 0),
    payment_status varchar(20) NOT NULL,
    payment_amount decimal(14,2) NOT NULL CHECK (payment_amount >= 0),
    void_flag boolean NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL CHECK (is_synthetic = true),
    source_updated_at datetime(3) NOT NULL,
    CONSTRAINT fk_pos_order_store FOREIGN KEY (store_id) REFERENCES pos_stores(store_id),
    CONSTRAINT ck_pos_order_status CHECK (order_status IN ('OPEN','PAID','VOID','PARTIAL_REFUND','REFUNDED')),
    CONSTRAINT ck_pos_payment_status CHECK (payment_status IN ('PAID','PARTIAL_REFUND','REFUNDED','FAILED')),
    CONSTRAINT ck_pos_order_times CHECK (
        check_opened_at <= ordered_at
        AND (check_closed_at IS NULL OR check_closed_at >= ordered_at)
        AND (check_closed_at IS NULL OR check_closed_at <= source_updated_at)
        AND ordered_at <= source_updated_at
    ),
    CONSTRAINT ck_pos_order_forecast CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    INDEX idx_pos_orders_store_time (store_id, ordered_at),
    INDEX idx_pos_orders_customer_time (pos_customer_ref, ordered_at)
) ENGINE=InnoDB COMMENT='Synthetic F&B order and payment';

CREATE TABLE IF NOT EXISTS pos_order_items (
    property_id varchar(64) NOT NULL,
    order_item_id varchar(36) PRIMARY KEY,
    order_id varchar(36) NOT NULL,
    item_code varchar(32) NOT NULL,
    item_category varchar(32) NOT NULL,
    quantity integer NOT NULL CHECK (quantity >= 1),
    unit_price decimal(14,2) NOT NULL CHECK (unit_price >= 0),
    gross_amount decimal(14,2) NOT NULL CHECK (gross_amount >= 0),
    discount_amount decimal(14,2) NOT NULL CHECK (discount_amount >= 0),
    net_amount decimal(14,2) NOT NULL CHECK (net_amount >= 0),
    is_synthetic boolean NOT NULL CHECK (is_synthetic = true),
    source_updated_at datetime(3) NOT NULL,
    CONSTRAINT fk_pos_item_order FOREIGN KEY (order_id) REFERENCES pos_orders(order_id),
    CONSTRAINT ck_pos_item_net CHECK (net_amount = gross_amount - discount_amount),
    INDEX idx_pos_items_order (order_id)
) ENGINE=InnoDB COMMENT='Synthetic F&B order item';

CREATE TABLE IF NOT EXISTS schema_version (version varchar(32) PRIMARY KEY);
CREATE TABLE IF NOT EXISTS seed_metadata (seed integer PRIMARY KEY, data_class varchar(16) NOT NULL);
INSERT IGNORE INTO schema_version(version) VALUES ('1.0.0');
INSERT IGNORE INTO seed_metadata(seed, data_class) VALUES (20260729, 'synthetic');

GRANT SELECT, INSERT, UPDATE, DELETE ON pos_db.* TO 'pos_ingest';
GRANT SELECT ON pos_db.* TO 'pos_readonly';

SELECT COUNT(*) AS pos_table_count
FROM information_schema.tables
WHERE table_schema = 'pos_db' AND table_type = 'BASE TABLE';
