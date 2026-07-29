\set ON_ERROR_STOP on

BEGIN;

CREATE OR REPLACE VIEW public.pms_reference_codes AS
SELECT category::varchar(32) AS category, code::varchar(32) AS code
FROM (
    VALUES
        ('GUEST_SEGMENT', 'LEISURE'),
        ('GUEST_SEGMENT', 'BUSINESS'),
        ('GUEST_SEGMENT', 'GROUP'),
        ('BOOKING_CHANNEL', 'DIRECT'),
        ('BOOKING_CHANNEL', 'OTA'),
        ('BOOKING_CHANNEL', 'CORPORATE'),
        ('RESERVATION_STATUS', 'BOOKED'),
        ('RESERVATION_STATUS', 'CANCELLED'),
        ('RESERVATION_STATUS', 'CHECKED_IN'),
        ('RESERVATION_STATUS', 'CHECKED_OUT'),
        ('RESERVATION_STATUS', 'NO_SHOW'),
        ('STAY_STATUS', 'EXPECTED'),
        ('STAY_STATUS', 'IN_HOUSE'),
        ('STAY_STATUS', 'COMPLETED'),
        ('STAY_STATUS', 'CANCELLED'),
        ('STAY_STATUS', 'NO_SHOW'),
        ('DATA_PERIOD_STATUS', 'REFERENCE_CALIBRATED'),
        ('DATA_PERIOD_STATUS', 'SYNTHETIC_ACTUAL_LIKE'),
        ('DATA_PERIOD_STATUS', 'YTD_SYNTHETIC'),
        ('DATA_PERIOD_STATUS', 'FORECAST_SCENARIO')
) AS reference_code(category, code);

COMMENT ON VIEW public.pms_reference_codes IS
    'Read-only documented PMS code set; it contains no customer data.';

COMMIT;
