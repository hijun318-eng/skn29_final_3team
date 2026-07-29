-- Deterministic reference rows for 1.0.0.
-- These are synthetic calibration inputs, not hotel observations.
SET timezone = 'Asia/Seoul';

INSERT INTO reference.market_benchmark_annual (
    benchmark_year, population_code, occupancy_rate, adr_krw, revpar_krw,
    reference_status, source_name, source_url, published_at, extracted_at, notes
)
VALUES
    (2022, 'HOTEL_INDUSTRY', 0.587900, 138874, 81642, 'PUBLISHED', 'PUBLIC_MARKET_REFERENCE', 'https://know.tour.go.kr/', DATE '2023-12-31', TIMESTAMPTZ '2026-07-28 05:00:00+00', 'Synthetic calibration anchor'),
    (2023, 'HOTEL_INDUSTRY', 0.660300, 148547, 98079, 'PUBLISHED', 'PUBLIC_MARKET_REFERENCE', 'https://know.tour.go.kr/', DATE '2024-12-31', TIMESTAMPTZ '2026-07-28 05:00:00+00', 'Synthetic calibration anchor'),
    (2024, 'HOTEL_INDUSTRY', 0.679000, 169171, 114918, 'PUBLISHED', 'PUBLIC_MARKET_REFERENCE', 'https://know.tour.go.kr/', DATE '2025-12-31', TIMESTAMPTZ '2026-07-28 05:00:00+00', 'Synthetic calibration anchor'),
    (2025, 'HOTEL_INDUSTRY', NULL, NULL, NULL, 'NOT_AVAILABLE', 'PUBLIC_MARKET_REFERENCE', 'https://know.tour.go.kr/', NULL, TIMESTAMPTZ '2026-07-28 05:00:00+00', 'No published benchmark used'),
    (2026, 'HOTEL_INDUSTRY', NULL, NULL, NULL, 'NOT_AVAILABLE', 'PUBLIC_MARKET_REFERENCE', 'https://know.tour.go.kr/', NULL, TIMESTAMPTZ '2026-07-28 05:00:00+00', 'No published benchmark used')
ON CONFLICT (benchmark_year, population_code) DO NOTHING;

WITH month_weight(month_no, weight) AS (
    VALUES (1,0.86),(2,0.90),(3,1.02),(4,1.07),(5,1.10),(6,1.05),
           (7,1.08),(8,1.12),(9,1.02),(10,1.10),(11,0.99),(12,1.06)
)
INSERT INTO reference.demand_index_monthly (
    year, month, demand_type, index_value, yoy_growth_rate, influence_weight,
    population_code, data_status, source_name, source_url, published_at, extracted_at
)
SELECT y, month_no, demand_type, weight, NULL, 0.30, 'SYNTHETIC_DEMAND_SCENARIO',
       CASE WHEN y = 2026 AND month_no > 6 THEN 'FORECAST' ELSE 'FINAL' END,
       'PUBLIC_TOURISM_REFERENCE', 'https://know.tour.go.kr/', NULL,
       TIMESTAMPTZ '2026-07-28 05:00:00+00'
FROM generate_series(2022, 2026) AS y
CROSS JOIN month_weight
CROSS JOIN (VALUES ('DOMESTIC'),('INBOUND'),('EVENT')) AS d(demand_type)
ON CONFLICT (year, month, demand_type) DO NOTHING;

INSERT INTO reference.calendar_daily (
    business_date, year, quarter, month, week_of_year, day_of_week,
    is_weekend, is_public_holiday, is_holiday_eve, season_code,
    school_vacation_code, domestic_travel_index, inbound_travel_index,
    event_demand_index, weather_scenario_code, data_period_status,
    is_forecast, created_at
)
SELECT d::date,
       extract(year FROM d)::smallint,
       extract(quarter FROM d)::smallint,
       extract(month FROM d)::smallint,
       extract(week FROM d)::smallint,
       extract(isodow FROM d)::smallint,
       extract(isodow FROM d) IN (6,7),
       false,
       false,
       CASE
           WHEN extract(month FROM d) IN (3,4,5) THEN 'SPRING'
           WHEN extract(month FROM d) IN (6,7,8) THEN 'SUMMER'
           WHEN extract(month FROM d) IN (9,10,11) THEN 'AUTUMN'
           ELSE 'WINTER'
       END,
       CASE WHEN extract(month FROM d) IN (1,2,7,8) THEN 'SCHOOL_BREAK' END,
       1.0, 1.0, 1.0, 'NEUTRAL',
       CASE
           WHEN d < DATE '2025-01-01' THEN 'REFERENCE_CALIBRATED'
           WHEN d < DATE '2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE'
           WHEN d <= DATE '2026-07-28' THEN 'YTD_SYNTHETIC'
           ELSE 'FORECAST_SCENARIO'
       END,
       d > DATE '2026-07-28',
       TIMESTAMPTZ '2026-07-28 05:00:00+00'
FROM generate_series(DATE '2022-01-01', DATE '2026-12-31', INTERVAL '1 day') AS g(d)
ON CONFLICT (business_date) DO NOTHING;
