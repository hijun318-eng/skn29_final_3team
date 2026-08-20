-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=REFERENCE; script_type=EVENT_SEED; execution_order=21
-- dependencies=20_postgresql_pms_reference_seed.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=208; execution_default=NOT_RUN; destructive_operation=false
-- assumption=attendance and all uplift values are synthetic triangular-scenario parameters
-- next=30_postgresql_pms_inventory_seed.sql

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM walkerhill_v4_3.event_master)
     OR EXISTS (SELECT 1 FROM walkerhill_v4_3.hotel_event_effect) THEN
    RAISE EXCEPTION 'candidate event tables must be empty';
  END IF;
END $$;

INSERT INTO walkerhill_v4_3.event_master
(event_id,event_name,event_type,start_date,end_date,location,estimated_attendance,evidence_id,fact_or_assumption,confidence)
VALUES
('E2024_BUFFET_HALO','The Buffet reopening halo','PRODUCT_HALO',DATE '2024-01-01',DATE '2024-03-31','Walkerhill campus',NULL,'EV_2024_Q1','MIXED',0.80),
('E2024_SPRING','Spring hotel activities','SEASONAL_PACKAGE',DATE '2024-03-15',DATE '2024-05-31','Walkerhill campus',NULL,'EV_2024_Q1','MIXED',0.72),
('E2024_AUTUMN','Camknic, Park Concert and autumn festival','MEGA_CONTENT',DATE '2024-09-01',DATE '2024-10-31','Walkerhill campus',NULL,'EV_2024_Q3','MIXED',0.78),
('E2024_YEAR_END','Christmas package and year-end demand','SEASONAL_PACKAGE',DATE '2024-12-01',DATE '2024-12-31','Walkerhill campus',NULL,'EV_2024_Q3','ASSUMPTION',0.65),
('E2024_CORP_1217','Cheiron launch banquet','CORPORATE_EVENT',DATE '2024-12-17',DATE '2024-12-17','Walkerhill campus',NULL,'EV_2024_Q3','MIXED',0.70),
('E2025_SPRING_ART','Spring art collaboration package','SEASONAL_PACKAGE',DATE '2025-02-11',DATE '2025-05-31','Walkerhill campus',NULL,'EV_BRAND','MIXED',0.70),
('E2025_GOLF_OPEN','Walkerhill Golf Club opening','FACILITY_OPENING',DATE '2025-06-21',DATE '2025-07-20','Walkerhill campus',NULL,'EV_2025_GOLF','MIXED',0.92),
('E2025_GOLF_PACKAGE','Golf club linked room package','SEASONAL_PACKAGE',DATE '2025-07-14',DATE '2025-12-31','Walkerhill campus',NULL,'EV_2025_GOLF_PACKAGE','MIXED',0.92),
('E2025_AUTUMN','Camknic autumn package','SEASONAL_PACKAGE',DATE '2025-09-01',DATE '2025-11-30','Walkerhill campus',NULL,'EV_2024_Q3','MIXED',0.72),
('E2025_YEAR_END','Year-end hotel packages','SEASONAL_PACKAGE',DATE '2025-12-01',DATE '2025-12-31','Walkerhill campus',NULL,'EV_BRAND','ASSUMPTION',0.62),
('E2026_SPRING_JAZZ','Spring Forest and Jazz Picnic','SEASONAL_PACKAGE',DATE '2026-04-22',DATE '2026-06-07','Walkerhill campus',NULL,'EV_2026_SPRING','MIXED',0.88),
('E2026_EARLY_SUMMER','Summer Pairing and Just Summer','SEASONAL_PACKAGE',DATE '2026-05-11',DATE '2026-08-31','Walkerhill campus',NULL,'EV_2026_EARLY_SUMMER','MIXED',0.90),
('E2026_RIVERPARK','Riverpark summer season','MEGA_CONTENT',DATE '2026-06-26',DATE '2026-08-30','Walkerhill campus',NULL,'EV_2026_RIVERPARK','MIXED',0.95);

WITH hotel_weights(hotel_code,occ_weight,adr_weight,fnb_weight,banquet_weight,facility_weight,capacity_limit) AS (
  VALUES ('GRAND',1.00,0.75,1.00,1.20,0.90,0.97),
         ('VISTA',0.82,1.25,1.12,0.78,0.85,0.96),
         ('DOUGLAS',0.52,1.05,0.48,0.18,0.42,0.94)
), metrics(domain,metric_name,base_mode) AS (
  VALUES ('ROOMS','OCCUPANCY_RATE',0.0900),('ROOMS','ADR',0.0700),
         ('FNB','ORDER_COUNT',0.1200),('BANQUET','BOOKING_COUNT',0.0900),
         ('FACILITY','USAGE_COUNT',0.1000)
), expanded AS (
  SELECT e.event_id,e.event_type,h.*,m.domain,m.metric_name,m.base_mode,
         CASE m.metric_name WHEN 'OCCUPANCY_RATE' THEN h.occ_weight WHEN 'ADR' THEN h.adr_weight
              WHEN 'ORDER_COUNT' THEN h.fnb_weight WHEN 'BOOKING_COUNT' THEN h.banquet_weight
              ELSE h.facility_weight END AS hotel_weight
  FROM walkerhill_v4_3.event_master e CROSS JOIN hotel_weights h CROSS JOIN metrics m
)
INSERT INTO walkerhill_v4_3.hotel_event_effect
(event_id,hotel_code,domain,metric_name,lead_days,lag_days,effect_curve,uplift_min,uplift_mode,uplift_max,capacity_limit,confidence,evidence_id)
SELECT x.event_id,x.hotel_code,x.domain,x.metric_name,
       CASE WHEN x.event_type='MEGA_CONTENT' THEN 21 WHEN x.event_type='CORPORATE_EVENT' THEN 7 ELSE 14 END,
       CASE WHEN x.event_type='FACILITY_OPENING' THEN 30 ELSE 3 END,
       CASE WHEN x.event_type IN ('FACILITY_OPENING','PRODUCT_HALO') THEN 'DECAY' ELSE 'TRIANGULAR' END,
       round((x.base_mode*x.hotel_weight*0.55)::numeric,4),
       round((x.base_mode*x.hotel_weight*CASE WHEN x.event_type='MEGA_CONTENT' THEN 1.55 WHEN x.event_type='FACILITY_OPENING' THEN 1.35 ELSE 1.00 END)::numeric,4),
       round((x.base_mode*x.hotel_weight*CASE WHEN x.event_type='MEGA_CONTENT' THEN 2.10 WHEN x.event_type='FACILITY_OPENING' THEN 1.80 ELSE 1.45 END)::numeric,4),
       x.capacity_limit,e.confidence,e.evidence_id
FROM expanded x JOIN walkerhill_v4_3.event_master e USING(event_id);
