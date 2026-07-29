SET @generated_at_local = CONVERT_TZ(
    STR_TO_DATE(REPLACE(REPLACE(@generated_at, 'T', ' '), 'Z', ''), '%Y-%m-%d %H:%i:%s'),
    '+00:00',
    '+09:00'
);
SET @store_id = CONCAT('STR-', UPPER(SUBSTRING(SHA2(CONCAT(@synthetic_data_seed, ':pos:store:1'), 256), 1, 8)));
SET @order_id = CONCAT('ORD-', UPPER(SUBSTRING(SHA2(CONCAT(@synthetic_data_seed, ':pos:order:1'), 256), 1, 8)));
SET @order_item_id = CONCAT('ITM-', UPPER(SUBSTRING(SHA2(CONCAT(@synthetic_data_seed, ':pos:item:1'), 256), 1, 8)));
SET @customer_ref = CONCAT('PSC-', UPPER(SUBSTRING(SHA2(CONCAT(@synthetic_data_seed, ':cross:customer:1'), 256), 1, 8)));

INSERT INTO pos_stores VALUES (
    'SYNTHETIC_HOTEL_001', @store_id, 'Synthetic All Day Dining', 'DINING',
    80, '06:30:00', '22:00:00', true, true, @generated_at_local
) AS new
ON DUPLICATE KEY UPDATE
    store_name = new.store_name,
    seat_capacity = new.seat_capacity,
    is_synthetic = true,
    source_updated_at = new.source_updated_at;

INSERT INTO pos_service_periods VALUES (
    'SYNTHETIC_HOTEL_001',
    CAST(CONV(SUBSTRING(SHA2(CONCAT(@synthetic_data_seed, ':pos:period:1'), 256), 1, 12), 16, 10) AS UNSIGNED),
    @store_id, '2026-07-28', 'DINNER', 80, 240, 96, 320.00, 144.00,
    'YTD_SYNTHETIC', false, true, @generated_at_local
) AS new
ON DUPLICATE KEY UPDATE
    covers = new.covers,
    seat_hours_available = new.seat_hours_available,
    seat_hours_used = new.seat_hours_used,
    is_synthetic = true,
    source_updated_at = new.source_updated_at;

INSERT INTO pos_orders VALUES (
    'SYNTHETIC_HOTEL_001', @order_id, @store_id, @customer_ref,
    '2026-07-28 19:00:00.000', '2026-07-28 18:55:00.000', '2026-07-28 20:20:00.000',
    2, 'DINNER', 'PAID', 88000.00, 8000.00, 0.00, 80000.00,
    'PAID', 80000.00, false, 'YTD_SYNTHETIC', false, true, @generated_at_local
) AS new
ON DUPLICATE KEY UPDATE
    order_status = new.order_status,
    net_amount = new.net_amount,
    payment_status = new.payment_status,
    is_synthetic = true,
    source_updated_at = new.source_updated_at;

INSERT INTO pos_order_items VALUES (
    'SYNTHETIC_HOTEL_001', @order_item_id, @order_id, 'DINNER-SET', 'FOOD',
    2, 44000.00, 88000.00, 8000.00, 80000.00, true, @generated_at_local
) AS new
ON DUPLICATE KEY UPDATE
    quantity = new.quantity,
    gross_amount = new.gross_amount,
    discount_amount = new.discount_amount,
    net_amount = new.net_amount,
    is_synthetic = true,
    source_updated_at = new.source_updated_at;
