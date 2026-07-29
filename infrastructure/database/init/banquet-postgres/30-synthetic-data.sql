INSERT INTO banquet.event
    (event_id, venue_id, event_type, event_date, attendees, status, contracted_amount)
VALUES
    (20001, 1, 'wedding', '2026-07-12', 420, 'completed', 48600000.00),
    (20002, 2, 'corporate', '2026-07-25', 180, 'completed', 21800000.00),
    (20003, 3, 'family', '2026-08-08', 85, 'contracted', 9900000.00)
ON CONFLICT (event_id) DO UPDATE
SET venue_id = EXCLUDED.venue_id,
    event_type = EXCLUDED.event_type,
    event_date = EXCLUDED.event_date,
    attendees = EXCLUDED.attendees,
    status = EXCLUDED.status,
    contracted_amount = EXCLUDED.contracted_amount;

INSERT INTO banquet.sales_line (sales_line_id, event_id, category, net_amount)
VALUES
    (21001, 20001, 'food', 31000000.00),
    (21002, 20001, 'beverage', 7600000.00),
    (21003, 20001, 'venue', 10000000.00),
    (21004, 20002, 'food', 13800000.00),
    (21005, 20002, 'venue', 8000000.00),
    (21006, 20003, 'food', 6400000.00),
    (21007, 20003, 'venue', 3500000.00)
ON CONFLICT (sales_line_id) DO UPDATE
SET event_id = EXCLUDED.event_id,
    category = EXCLUDED.category,
    net_amount = EXCLUDED.net_amount;
