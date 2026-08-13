SELECT 'POS_ITEM_COUNT_RANGE',x.order_id FROM (SELECT o.order_id,COUNT(i.order_item_id) item_count FROM pos_orders o LEFT JOIN pos_order_items i ON o.order_id=i.order_id WHERE o.property_id='SYNTHETIC_HOTEL_001' GROUP BY o.order_id) x WHERE x.item_count NOT BETWEEN 1 AND 6
UNION ALL SELECT 'POS_ITEM_AMOUNT_MISMATCH',order_item_id FROM pos_order_items WHERE net_amount<>gross_amount-discount_amount OR gross_amount<>quantity*unit_price
UNION ALL SELECT 'POS_SERVICE_PERIOD_CAPACITY',CAST(service_period_id AS CHAR) FROM pos_service_periods WHERE covers<0 OR seat_hours_available<0 OR seat_capacity<1
UNION ALL SELECT 'POS_SERVICE_PERIOD_FORECAST',CAST(service_period_id AS CHAR) FROM pos_service_periods WHERE is_forecast<>(data_period_status='FORECAST_SCENARIO');
