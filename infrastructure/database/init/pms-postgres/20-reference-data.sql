INSERT INTO pms.hotel (hotel_id, hotel_name, city, timezone)
VALUES
    (1, 'Grand Walker Synthetic', 'Seoul', 'Asia/Seoul'),
    (2, 'Vista Synthetic', 'Seoul', 'Asia/Seoul')
ON CONFLICT (hotel_id) DO UPDATE
SET hotel_name = EXCLUDED.hotel_name,
    city = EXCLUDED.city,
    timezone = EXCLUDED.timezone;

INSERT INTO pms.room_type (room_type_code, room_type_name, base_capacity)
VALUES
    ('DLX', 'Deluxe', 2),
    ('STE', 'Suite', 3),
    ('FAM', 'Family', 4)
ON CONFLICT (room_type_code) DO UPDATE
SET room_type_name = EXCLUDED.room_type_name,
    base_capacity = EXCLUDED.base_capacity;
