-- Trino analytics views for 1.0.0.
-- Catalogs: serving (internal), pms, pos, crm, facility, banquet.
-- Setup-only DDL. Runtime users remain read-only.
CREATE SCHEMA IF NOT EXISTS serving.analytics;
CREATE SCHEMA IF NOT EXISTS serving.reference;

CREATE OR REPLACE VIEW serving.reference.market_benchmark_annual AS
SELECT *
FROM (
    VALUES
      (2022,'HOTEL_INDUSTRY',cast(0.587900 AS decimal(10,6)),cast(138874 AS decimal(18,2)),cast(81642 AS decimal(18,2))),
      (2023,'HOTEL_INDUSTRY',cast(0.660300 AS decimal(10,6)),cast(148547 AS decimal(18,2)),cast(98079 AS decimal(18,2))),
      (2024,'HOTEL_INDUSTRY',cast(0.679000 AS decimal(10,6)),cast(169171 AS decimal(18,2)),cast(114918 AS decimal(18,2))),
      (2025,'HOTEL_INDUSTRY',cast(NULL AS decimal(10,6)),cast(NULL AS decimal(18,2)),cast(NULL AS decimal(18,2))),
      (2026,'HOTEL_INDUSTRY',cast(NULL AS decimal(10,6)),cast(NULL AS decimal(18,2)),cast(NULL AS decimal(18,2)))
) AS t(benchmark_year,population_code,occupancy_rate,adr_krw,revpar_krw);

CREATE OR REPLACE VIEW serving.analytics.hotel_daily_metrics AS
WITH inventory AS (
    SELECT property_id,business_date,room_type_code,data_period_status,is_forecast,
           sum(available_room_nights) available_room_nights,
           max(source_updated_at) pms_inventory_watermark
    FROM pms.public.pms_room_inventory_daily
    GROUP BY 1,2,3,4,5
),
stay_days AS (
    SELECT s.property_id,d business_date,s.room_type_code,s.data_period_status,s.is_forecast,
           count(DISTINCT s.room_unit_code) rooms_sold,
           sum(s.room_revenue/nullif(s.occupied_room_nights,0)) room_revenue,
           max(s.source_updated_at) pms_stay_watermark
    FROM pms.public.pms_stays s
    CROSS JOIN UNNEST(sequence(
        cast(at_timezone(s.actual_checkin_at,'Asia/Seoul') AS date),
        date_add('day',-1,cast(at_timezone(s.actual_checkout_at,'Asia/Seoul') AS date))
    )) AS x(d)
    WHERE s.stay_status='COMPLETED'
      AND s.is_forecast=false
      AND s.complimentary_flag=false
      AND s.house_use_flag=false
    GROUP BY 1,2,3,4,5
),
checkouts AS (
    SELECT property_id,
           cast(at_timezone(actual_checkout_at,'Asia/Seoul') AS date) business_date,
           room_type_code,data_period_status,is_forecast,
           sum(room_revenue) recognized_room_revenue
    FROM pms.public.pms_stays
    WHERE stay_status='COMPLETED'
      AND is_forecast=false
      AND complimentary_flag=false
      AND house_use_flag=false
    GROUP BY 1,2,3,4,5
)
SELECT i.property_id,i.business_date,i.room_type_code,i.data_period_status,i.is_forecast,
       'ROOMS' business_unit_code,
       i.available_room_nights,coalesce(s.rooms_sold,0) rooms_sold,
       cast(coalesce(s.room_revenue,0) AS decimal(18,2)) room_revenue,
       cast(coalesce(c.recognized_room_revenue,0) AS decimal(18,2)) recognized_room_revenue,
       cast(coalesce(s.rooms_sold,0)/nullif(i.available_room_nights,0) AS decimal(18,6)) occupancy_rate,
       cast(coalesce(s.room_revenue,0)/nullif(s.rooms_sold,0) AS decimal(18,6)) adr,
       cast(coalesce(s.room_revenue,0)/nullif(i.available_room_nights,0) AS decimal(18,6)) revpar,
       if(i.available_room_nights=0,'ZERO_DENOMINATOR',NULL) reason_code,
       i.pms_inventory_watermark,s.pms_stay_watermark
FROM inventory i
LEFT JOIN stay_days s
  ON i.property_id=s.property_id AND i.business_date=s.business_date
 AND i.room_type_code=s.room_type_code AND i.data_period_status=s.data_period_status
 AND i.is_forecast=s.is_forecast
LEFT JOIN checkouts c
  ON i.property_id=c.property_id AND i.business_date=c.business_date
 AND i.room_type_code=c.room_type_code AND i.data_period_status=c.data_period_status
 AND i.is_forecast=c.is_forecast;

CREATE OR REPLACE VIEW serving.analytics.fnb_daypart_metrics AS
WITH orders AS (
    SELECT property_id,store_id,cast(ordered_at AS date) business_date,service_period,
           data_period_status,is_forecast=1 is_forecast,
           sum(net_amount) fnb_net_revenue,sum(guest_count) covers,
           count(*) order_count,max(source_updated_at) pos_order_watermark
    FROM pos.pos_db.pos_orders
    WHERE order_status<>'OPEN'
    GROUP BY 1,2,3,4,5,6
),
periods AS (
    SELECT property_id,store_id,business_date,service_period,data_period_status,
           is_forecast=1 is_forecast,
           sum(seat_hours_available) seat_hours_available,
           sum(seat_hours_used) seat_hours_used,max(source_updated_at) pos_period_watermark
    FROM pos.pos_db.pos_service_periods
    GROUP BY 1,2,3,4,5,6
)
SELECT p.property_id,p.store_id,p.business_date,p.service_period,p.data_period_status,p.is_forecast,
       'FNB' business_unit_code,
       cast(coalesce(o.fnb_net_revenue,0) AS decimal(18,2)) fnb_net_revenue,
       coalesce(o.covers,0) covers,coalesce(o.order_count,0) order_count,
       cast(p.seat_hours_available AS decimal(18,2)) seat_hours_available,
       cast(p.seat_hours_used AS decimal(18,2)) seat_hours_used,
       cast(coalesce(o.fnb_net_revenue,0)/nullif(p.seat_hours_available,0) AS decimal(18,6)) revpash,
       cast(coalesce(o.fnb_net_revenue,0)/nullif(o.covers,0) AS decimal(18,6)) average_check,
       if(p.seat_hours_available=0,'ZERO_DENOMINATOR',NULL) reason_code,
       o.pos_order_watermark,p.pos_period_watermark
FROM periods p
LEFT JOIN orders o
  ON p.property_id=o.property_id AND p.store_id=o.store_id
 AND p.business_date=o.business_date AND p.service_period=o.service_period
 AND p.data_period_status=o.data_period_status AND p.is_forecast=o.is_forecast;

CREATE OR REPLACE VIEW serving.analytics.facility_daily_metrics AS
SELECT property_id,facility_id,cast(cast(event_at AS timestamp(3)) AS date) business_date,data_period_status,
       is_forecast=1 is_forecast,
       'FACILITY' business_unit_code,
       count_if(event_type='USAGE' AND event_status='COMPLETED') completed_usage_count,
       count_if(event_type='INCIDENT') incident_count,
       sum(if(event_type='INCIDENT',downtime_minutes,0)) downtime_minutes,
       cast(sum(if(event_type='USAGE' AND event_status='COMPLETED',amount,0)) AS decimal(18,2)) facility_revenue,
       cast(
           sum(if(event_type='USAGE' AND event_status='COMPLETED',amount,0))
           /nullif(count_if(event_type='USAGE' AND event_status='COMPLETED'),0)
           AS decimal(18,6)
       ) revenue_per_usage,
       if(count_if(event_type='USAGE' AND event_status='COMPLETED')=0,'ZERO_DENOMINATOR',NULL) reason_code,
       max(cast(source_updated_at AS timestamp(3))) facility_watermark
FROM facility.facility.facility_events
GROUP BY 1,2,3,4,5;

CREATE OR REPLACE VIEW serving.analytics.banquet_monthly_metrics AS
WITH bookings AS (
    SELECT property_id,date_trunc('month',cast(event_date AS timestamp)) year_month,
           product_category,data_period_status,is_forecast,
           count(*) booking_count,count_if(booking_status='CONFIRMED') confirmed_count,
           count_if(booking_status='CANCELLED') cancelled_count,
           sum(coalesce(actual_attendees,0)) actual_attendees,
           max(source_updated_at) banquet_booking_watermark
    FROM banquet.public.banquet_bookings
    GROUP BY 1,2,3,4,5
),
revenue AS (
    SELECT property_id,date_trunc('month',cast(recognized_date AS timestamp)) year_month,
           data_period_status,is_forecast,
           sum(if(revenue_status='RECOGNIZED',revenue_amount,0))
             - sum(if(revenue_status='REVERSED',reversal_amount,0)) recognized_revenue,
           sum(if(revenue_status='EXPECTED',revenue_amount,0)) expected_revenue,
           max(source_updated_at) banquet_revenue_watermark
    FROM banquet.public.banquet_revenue
    GROUP BY 1,2,3,4
)
SELECT b.property_id,b.year_month,b.product_category,b.data_period_status,b.is_forecast,
       'BANQUET' business_unit_code,b.booking_count,b.confirmed_count,b.cancelled_count,b.actual_attendees,
       cast(coalesce(r.recognized_revenue,0) AS decimal(18,2)) recognized_revenue,
       cast(coalesce(r.expected_revenue,0) AS decimal(18,2)) expected_revenue,
       b.banquet_booking_watermark,r.banquet_revenue_watermark
FROM bookings b
LEFT JOIN revenue r
  ON b.property_id=r.property_id AND b.year_month=r.year_month
 AND b.data_period_status=r.data_period_status AND b.is_forecast=r.is_forecast;

CREATE OR REPLACE VIEW serving.analytics.hotel_monthly_metrics AS
WITH rooms AS (
    SELECT property_id,date_trunc('month',cast(business_date AS timestamp)) year_month,
           data_period_status,is_forecast,'ROOMS' business_unit_code,
           sum(room_revenue) operating_revenue,sum(rooms_sold) rooms_sold,
           sum(available_room_nights) available_room_nights,
           greatest(max(pms_inventory_watermark),max(pms_stay_watermark)) source_watermark
    FROM serving.analytics.hotel_daily_metrics GROUP BY 1,2,3,4
),
fnb AS (
    SELECT property_id,date_trunc('month',cast(business_date AS timestamp)) year_month,
           data_period_status,is_forecast,'FNB' business_unit_code,
           sum(fnb_net_revenue) operating_revenue,cast(NULL AS bigint) rooms_sold,
           cast(NULL AS bigint) available_room_nights,
           greatest(max(pos_order_watermark),max(pos_period_watermark)) source_watermark
    FROM serving.analytics.fnb_daypart_metrics GROUP BY 1,2,3,4
),
facility_month AS (
    SELECT property_id,date_trunc('month',cast(business_date AS timestamp)) year_month,
           data_period_status,is_forecast,'FACILITY' business_unit_code,
           sum(facility_revenue) operating_revenue,cast(NULL AS bigint) rooms_sold,
           cast(NULL AS bigint) available_room_nights,max(facility_watermark) source_watermark
    FROM serving.analytics.facility_daily_metrics GROUP BY 1,2,3,4
),
banquet_month AS (
    SELECT property_id,year_month,data_period_status,is_forecast,'BANQUET' business_unit_code,
           sum(recognized_revenue) operating_revenue,cast(NULL AS bigint) rooms_sold,
           cast(NULL AS bigint) available_room_nights,
           greatest(max(banquet_booking_watermark),max(banquet_revenue_watermark)) source_watermark
    FROM serving.analytics.banquet_monthly_metrics GROUP BY 1,2,3,4
)
SELECT property_id,year_month,business_unit_code,data_period_status,is_forecast,
       cast(sum(operating_revenue) AS decimal(18,2)) total_operating_revenue,
       sum(rooms_sold) rooms_sold,sum(available_room_nights) available_room_nights,
       cast(sum(operating_revenue)/nullif(sum(available_room_nights),0) AS decimal(18,6)) trevpar,
       cast(sum(operating_revenue)/nullif(sum(rooms_sold),0) AS decimal(18,6)) revpor,
       if(sum(available_room_nights)=0,'ZERO_DENOMINATOR',NULL) reason_code,
       max(source_watermark) source_watermark
FROM (
    SELECT * FROM rooms UNION ALL SELECT * FROM fnb
    UNION ALL SELECT * FROM facility_month UNION ALL SELECT * FROM banquet_month
) u
GROUP BY 1,2,3,4,5;

CREATE OR REPLACE VIEW serving.analytics.hotel_yearly_metrics AS
SELECT m.property_id,year(m.year_month) year,m.business_unit_code,m.data_period_status,m.is_forecast,
       cast(sum(m.total_operating_revenue) AS decimal(18,2)) total_operating_revenue,
       sum(m.rooms_sold) rooms_sold,sum(m.available_room_nights) available_room_nights,
       cast(sum(m.total_operating_revenue)/nullif(sum(m.available_room_nights),0) AS decimal(18,6)) trevpar,
       b.occupancy_rate benchmark_occupancy_rate,b.adr_krw benchmark_adr_krw,b.revpar_krw benchmark_revpar_krw,
       if(sum(m.available_room_nights)=0,'ZERO_DENOMINATOR',NULL) reason_code,
       max(m.source_watermark) source_watermark
FROM serving.analytics.hotel_monthly_metrics m
LEFT JOIN serving.reference.market_benchmark_annual b
  ON b.benchmark_year=year(m.year_month) AND b.population_code='HOTEL_INDUSTRY'
GROUP BY 1,2,3,4,5,10,11,12;

CREATE OR REPLACE VIEW serving.analytics.workforce_monthly_metrics AS
WITH staffing AS (
    SELECT property_id,date_trunc('month',cast(business_date AS timestamp)) year_month,
           department,data_period_status,is_forecast=1 is_forecast,
           sum(worked_hours) worked_hours,sum(labor_cost) labor_cost,avg(fte) average_fte,
           max(source_updated_at) staffing_watermark
    FROM facility.facility.hotel_staffing_daily GROUP BY 1,2,3,4,5
),
rooms AS (
    SELECT property_id,date_trunc('month',cast(business_date AS timestamp)) year_month,
           data_period_status,is_forecast,sum(rooms_sold) rooms_sold,max(pms_stay_watermark) pms_watermark
    FROM serving.analytics.hotel_daily_metrics GROUP BY 1,2,3,4
)
SELECT s.property_id,s.year_month,s.department,s.data_period_status,s.is_forecast,
       cast(s.worked_hours AS decimal(18,2)) worked_hours,
       cast(s.labor_cost AS decimal(18,2)) labor_cost,s.average_fte,r.rooms_sold,
       cast(s.worked_hours/nullif(r.rooms_sold,0) AS decimal(18,6)) hpor,
       cast(s.labor_cost/nullif(r.rooms_sold,0) AS decimal(18,6)) labor_cpor,
       if(r.rooms_sold=0,'ZERO_DENOMINATOR',NULL) reason_code,
       s.staffing_watermark,r.pms_watermark
FROM staffing s
LEFT JOIN rooms r
  ON s.property_id=r.property_id AND s.year_month=r.year_month
 AND s.data_period_status=r.data_period_status AND s.is_forecast=r.is_forecast;

CREATE OR REPLACE VIEW serving.analytics.resource_monthly_metrics AS
WITH resources AS (
    SELECT property_id,date_trunc('month',cast(business_date AS timestamp)) year_month,
           resource_scope,data_period_status,is_forecast=1 is_forecast,
           sum(energy_kwh) energy_kwh,sum(water_m3) water_m3,sum(waste_kg) waste_kg,
           sum(resource_cost) resource_cost,max(source_updated_at) resource_watermark
    FROM facility.facility.facility_resource_daily GROUP BY 1,2,3,4,5
),
rooms AS (
    SELECT property_id,date_trunc('month',cast(business_date AS timestamp)) year_month,
           data_period_status,is_forecast,sum(rooms_sold) occupied_room_nights,
           max(pms_stay_watermark) pms_watermark
    FROM serving.analytics.hotel_daily_metrics GROUP BY 1,2,3,4
)
SELECT r.property_id,r.year_month,r.resource_scope,r.data_period_status,r.is_forecast,
       r.energy_kwh,r.water_m3,r.waste_kg,cast(r.resource_cost AS decimal(18,2)) resource_cost,
       s.occupied_room_nights,
       r.energy_kwh/nullif(s.occupied_room_nights,0) energy_per_occupied_room,
       r.water_m3/nullif(s.occupied_room_nights,0) water_per_occupied_room,
       r.waste_kg/nullif(s.occupied_room_nights,0) waste_per_occupied_room,
       cast(r.resource_cost/nullif(s.occupied_room_nights,0) AS decimal(18,6)) cost_per_occupied_room,
       if(s.occupied_room_nights=0,'ZERO_DENOMINATOR',NULL) reason_code,
       r.resource_watermark,s.pms_watermark
FROM resources r
LEFT JOIN rooms s
  ON r.property_id=s.property_id AND r.year_month=s.year_month
 AND r.data_period_status=s.data_period_status AND r.is_forecast=s.is_forecast;

SELECT table_schema,table_name
FROM serving.information_schema.views
WHERE table_schema='analytics'
ORDER BY table_name;
