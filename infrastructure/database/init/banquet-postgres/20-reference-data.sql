INSERT INTO banquet.venue (venue_id, venue_name, capacity)
VALUES
    (1, 'Grand Hall Synthetic', 800),
    (2, 'Vista Hall Synthetic', 300),
    (3, 'Garden Room Synthetic', 120)
ON CONFLICT (venue_id) DO UPDATE
SET venue_name = EXCLUDED.venue_name,
    capacity = EXCLUDED.capacity;
