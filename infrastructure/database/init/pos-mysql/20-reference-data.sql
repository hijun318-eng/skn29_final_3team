INSERT INTO outlet (outlet_id, outlet_name, location_code)
VALUES
    (1, 'The Buffet Synthetic', 'B1-BUFFET'),
    (2, 'Lobby Lounge Synthetic', 'L1-LOUNGE'),
    (3, 'Pool Bar Synthetic', 'OUT-POOL')
ON DUPLICATE KEY UPDATE
    outlet_name = VALUES(outlet_name),
    location_code = VALUES(location_code);

INSERT INTO menu_item (menu_item_id, item_name, category, unit_price, active)
VALUES
    (101, 'Breakfast Buffet', 'buffet', 78000.00, TRUE),
    (102, 'Seasonal Dinner Buffet', 'buffet', 168000.00, TRUE),
    (201, 'Signature Coffee', 'beverage', 16000.00, TRUE),
    (202, 'Fresh Juice', 'beverage', 19000.00, TRUE),
    (301, 'Club Sandwich', 'food', 35000.00, TRUE)
ON DUPLICATE KEY UPDATE
    item_name = VALUES(item_name),
    category = VALUES(category),
    unit_price = VALUES(unit_price),
    active = VALUES(active);
