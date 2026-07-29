INSERT INTO pos_transaction
    (transaction_id, outlet_id, menu_item_id, quantity, gross_amount, paid_at, payment_method)
VALUES
    (30001, 1, 101, 2, 156000.00, '2026-07-28 08:15:00', 'card'),
    (30002, 2, 201, 1, 16000.00, '2026-07-28 10:32:00', 'room_charge'),
    (30003, 3, 202, 3, 57000.00, '2026-07-28 14:05:00', 'card'),
    (30004, 2, 301, 1, 35000.00, '2026-07-28 19:20:00', 'cash'),
    (30005, 1, 102, 2, 336000.00, '2026-07-28 20:10:00', 'card')
ON DUPLICATE KEY UPDATE
    outlet_id = VALUES(outlet_id),
    menu_item_id = VALUES(menu_item_id),
    quantity = VALUES(quantity),
    gross_amount = VALUES(gross_amount),
    paid_at = VALUES(paid_at),
    payment_method = VALUES(payment_method);
