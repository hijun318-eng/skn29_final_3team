INSERT INTO pms.reservation
    (reservation_id, guest_token, hotel_id, room_type_code, check_in_date, check_out_date, status, total_amount, created_at)
VALUES
    (10001, 'guest-0001', 1, 'DLX', '2026-07-10', '2026-07-12', 'checked_out', 640000.00, '2026-06-15 11:20:00+09'),
    (10002, 'guest-0002', 1, 'STE', '2026-07-29', '2026-08-01', 'checked_in', 1650000.00, '2026-07-01 18:10:00+09'),
    (10003, 'guest-0003', 2, 'FAM', '2026-08-03', '2026-08-05', 'booked', 980000.00, '2026-07-20 09:00:00+09'),
    (10004, 'guest-0004', 2, 'DLX', '2026-08-10', '2026-08-11', 'cancelled', 0.00, '2026-07-22 15:40:00+09')
ON CONFLICT (reservation_id) DO UPDATE
SET guest_token = EXCLUDED.guest_token,
    hotel_id = EXCLUDED.hotel_id,
    room_type_code = EXCLUDED.room_type_code,
    check_in_date = EXCLUDED.check_in_date,
    check_out_date = EXCLUDED.check_out_date,
    status = EXCLUDED.status,
    total_amount = EXCLUDED.total_amount,
    created_at = EXCLUDED.created_at;
