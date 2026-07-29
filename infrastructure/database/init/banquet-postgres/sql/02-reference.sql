\set ON_ERROR_STOP on

BEGIN;

CREATE OR REPLACE VIEW public.banquet_reference_codes AS
SELECT category::varchar(32) AS category, code::varchar(32) AS code
FROM (
    VALUES
        ('BOOKING_STATUS', 'INQUIRY'),
        ('BOOKING_STATUS', 'QUOTED'),
        ('BOOKING_STATUS', 'TENTATIVE'),
        ('BOOKING_STATUS', 'CONFIRMED'),
        ('BOOKING_STATUS', 'CANCELLED'),
        ('BOOKING_STATUS', 'COMPLETED'),
        ('BOOKING_CATEGORY', 'WEDDING'),
        ('BOOKING_CATEGORY', 'CONFERENCE'),
        ('BOOKING_CATEGORY', 'MEETING'),
        ('BOOKING_CATEGORY', 'CORPORATE_EVENT'),
        ('BOOKING_CATEGORY', 'SOCIAL_EVENT'),
        ('REVENUE_STATUS', 'EXPECTED'),
        ('REVENUE_STATUS', 'RECOGNIZED'),
        ('REVENUE_STATUS', 'REVERSED'),
        ('REVENUE_CATEGORY', 'VENUE'),
        ('REVENUE_CATEGORY', 'FOOD_BEVERAGE'),
        ('REVENUE_CATEGORY', 'EQUIPMENT'),
        ('REVENUE_CATEGORY', 'DECORATION'),
        ('REVENUE_CATEGORY', 'SERVICE'),
        ('REVENUE_CATEGORY', 'ACCOMMODATION_PACKAGE'),
        ('DATA_PERIOD_STATUS', 'REFERENCE_CALIBRATED'),
        ('DATA_PERIOD_STATUS', 'SYNTHETIC_ACTUAL_LIKE'),
        ('DATA_PERIOD_STATUS', 'YTD_SYNTHETIC'),
        ('DATA_PERIOD_STATUS', 'FORECAST_SCENARIO')
) AS reference_code(category, code);

COMMENT ON VIEW public.banquet_reference_codes IS
    'Read-only documented banquet code set; it contains no customer data.';

COMMIT;
