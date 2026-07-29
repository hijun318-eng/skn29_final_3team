SET NAMES utf8mb4;
SET time_zone = '+09:00';

CREATE TABLE IF NOT EXISTS pos_stores (
    property_id varchar(64) NOT NULL,
    store_id varchar(32) NOT NULL,
    store_name varchar(100) NOT NULL,
    store_category varchar(24) NOT NULL,
    seat_capacity int NOT NULL,
    open_time time NOT NULL,
    close_time time NOT NULL,
    is_active boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at datetime(3) NOT NULL,
    PRIMARY KEY (store_id),
    CONSTRAINT ck_pos_stores_property CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_pos_stores_category CHECK (
        store_category IN ('BREAKFAST', 'DINING', 'BAR', 'CAFE', 'LOUNGE')
    ),
    CONSTRAINT ck_pos_stores_capacity CHECK (seat_capacity > 0),
    CONSTRAINT ck_pos_stores_synthetic CHECK (is_synthetic = true)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS pos_service_periods (
    property_id varchar(64) NOT NULL,
    service_period_id bigint NOT NULL,
    store_id varchar(32) NOT NULL,
    business_date date NOT NULL,
    service_period varchar(16) NOT NULL,
    seat_capacity int NOT NULL,
    open_minutes int NOT NULL,
    covers int NOT NULL,
    seat_hours_available decimal(14,2) NOT NULL,
    seat_hours_used decimal(14,2) NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at datetime(3) NOT NULL,
    PRIMARY KEY (service_period_id),
    UNIQUE KEY uq_pos_service_period (store_id, business_date, service_period),
    CONSTRAINT fk_pos_service_period_store FOREIGN KEY (store_id)
        REFERENCES pos_stores (store_id),
    CONSTRAINT ck_pos_service_period_property CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_pos_service_period_name CHECK (
        service_period IN ('BREAKFAST', 'LUNCH', 'AFTERNOON', 'DINNER', 'LATE_NIGHT')
    ),
    CONSTRAINT ck_pos_service_period_counts CHECK (
        seat_capacity > 0 AND open_minutes >= 0 AND covers >= 0
        AND seat_hours_available >= 0 AND seat_hours_used >= 0
    ),
    CONSTRAINT ck_pos_service_period_status CHECK (
        data_period_status IN (
            'REFERENCE_CALIBRATED', 'SYNTHETIC_ACTUAL_LIKE',
            'YTD_SYNTHETIC', 'FORECAST_SCENARIO'
        )
    ),
    CONSTRAINT ck_pos_service_period_forecast CHECK (
        is_forecast = (data_period_status = 'FORECAST_SCENARIO')
    ),
    CONSTRAINT ck_pos_service_period_synthetic CHECK (is_synthetic = true)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS pos_orders (
    property_id varchar(64) NOT NULL,
    order_id varchar(36) NOT NULL,
    store_id varchar(32) NOT NULL,
    pos_customer_ref varchar(36),
    ordered_at datetime(3) NOT NULL,
    check_opened_at datetime(3) NOT NULL,
    check_closed_at datetime(3),
    guest_count int NOT NULL,
    service_period varchar(16) NOT NULL,
    order_status varchar(20) NOT NULL,
    gross_amount decimal(14,2) NOT NULL,
    discount_amount decimal(14,2) NOT NULL,
    refund_amount decimal(14,2) NOT NULL,
    net_amount decimal(14,2) NOT NULL,
    payment_status varchar(20) NOT NULL,
    payment_amount decimal(14,2) NOT NULL,
    void_flag boolean NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at datetime(3) NOT NULL,
    PRIMARY KEY (order_id),
    KEY ix_pos_orders_store_ordered_at (store_id, ordered_at),
    KEY ix_pos_orders_customer_ordered_at (pos_customer_ref, ordered_at),
    CONSTRAINT fk_pos_orders_store FOREIGN KEY (store_id) REFERENCES pos_stores (store_id),
    CONSTRAINT ck_pos_orders_property CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_pos_orders_guest_count CHECK (guest_count > 0),
    CONSTRAINT ck_pos_orders_period CHECK (
        service_period IN ('BREAKFAST', 'LUNCH', 'AFTERNOON', 'DINNER', 'LATE_NIGHT')
    ),
    CONSTRAINT ck_pos_orders_status CHECK (
        order_status IN ('OPEN', 'PAID', 'VOID', 'PARTIAL_REFUND', 'REFUNDED')
    ),
    CONSTRAINT ck_pos_orders_payment CHECK (
        payment_status IN ('PAID', 'PARTIAL_REFUND', 'REFUNDED', 'FAILED')
    ),
    CONSTRAINT ck_pos_orders_amounts CHECK (
        gross_amount >= 0 AND discount_amount >= 0 AND refund_amount >= 0
        AND net_amount >= 0 AND payment_amount >= 0
        AND net_amount = gross_amount - discount_amount - refund_amount
    ),
    CONSTRAINT ck_pos_orders_period_status CHECK (
        data_period_status IN (
            'REFERENCE_CALIBRATED', 'SYNTHETIC_ACTUAL_LIKE',
            'YTD_SYNTHETIC', 'FORECAST_SCENARIO'
        )
    ),
    CONSTRAINT ck_pos_orders_forecast CHECK (
        is_forecast = (data_period_status = 'FORECAST_SCENARIO')
    ),
    CONSTRAINT ck_pos_orders_synthetic CHECK (is_synthetic = true)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS pos_order_items (
    property_id varchar(64) NOT NULL,
    order_item_id varchar(36) NOT NULL,
    order_id varchar(36) NOT NULL,
    item_code varchar(32) NOT NULL,
    item_category varchar(32) NOT NULL,
    quantity int NOT NULL,
    unit_price decimal(14,2) NOT NULL,
    gross_amount decimal(14,2) NOT NULL,
    discount_amount decimal(14,2) NOT NULL,
    net_amount decimal(14,2) NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at datetime(3) NOT NULL,
    PRIMARY KEY (order_item_id),
    KEY ix_pos_order_items_order (order_id),
    CONSTRAINT fk_pos_order_items_order FOREIGN KEY (order_id) REFERENCES pos_orders (order_id),
    CONSTRAINT ck_pos_order_items_property CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_pos_order_items_quantity CHECK (quantity > 0),
    CONSTRAINT ck_pos_order_items_amounts CHECK (
        unit_price >= 0 AND gross_amount = unit_price * quantity
        AND discount_amount >= 0 AND net_amount = gross_amount - discount_amount
    ),
    CONSTRAINT ck_pos_order_items_synthetic CHECK (is_synthetic = true)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
