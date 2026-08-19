-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=PMS; script_type=INVENTORY_SEED; execution_order=30
-- dependencies=21_postgresql_pms_event_seed.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=13491; execution_default=NOT_RUN; destructive_operation=false
-- evidence=public room product naming only; every count, rate and outage is synthetic
-- next=31_postgresql_pms_guest_reservation_seed.sql

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM walkerhill_v4_3.pms_room_types)
     OR EXISTS (SELECT 1 FROM walkerhill_v4_3.pms_rooms)
     OR EXISTS (SELECT 1 FROM walkerhill_v4_3.pms_room_inventory_daily) THEN
    RAISE EXCEPTION 'candidate inventory tables must be empty';
  END IF;
END $$;

INSERT INTO walkerhill_v4_3.pms_room_types
(hotel_code,room_type_code,public_name,synthetic_room_count,synthetic_max_occupancy,synthetic_base_rate_krw,source_url,provenance_class,is_active)
VALUES
('GRAND','G_DELUXE','Grand Deluxe',360,4,280000,'https://www.walkerhill.com/grandwalkerhillseoul/en/room/Intro','MIXED_REFERENCE_AND_ASSUMPTION',true),
('GRAND','G_CLUB','Grand Club',100,3,390000,'https://www.walkerhill.com/grandwalkerhillseoul/en/room/Intro','MIXED_REFERENCE_AND_ASSUMPTION',true),
('GRAND','G_SUITE','Grand Suite',45,5,620000,'https://www.walkerhill.com/grandwalkerhillseoul/en/room/Intro','MIXED_REFERENCE_AND_ASSUMPTION',true),
('VISTA','V_DELUXE','Vista Deluxe',190,4,350000,'https://www.walkerhill.com/vistawalkerhillseoul/en/room/','MIXED_REFERENCE_AND_ASSUMPTION',true),
('VISTA','V_SPA','Vista Spa',34,3,480000,'https://www.walkerhill.com/vistawalkerhillseoul/en/room/','MIXED_REFERENCE_AND_ASSUMPTION',true),
('VISTA','V_SUITE','Vista Suite',20,4,760000,'https://www.walkerhill.com/vistawalkerhillseoul/en/room/','MIXED_REFERENCE_AND_ASSUMPTION',true),
('DOUGLAS','D_DELUXE','Douglas Deluxe',45,2,330000,'https://app.walkerhill.com/about/Brand','MIXED_REFERENCE_AND_ASSUMPTION',true),
('DOUGLAS','D_TRAD','Douglas Traditional Suite',4,3,520000,'https://app.walkerhill.com/about/Brand','MIXED_REFERENCE_AND_ASSUMPTION',true),
('DOUGLAS','D_SUITE','Douglas Suite',3,4,650000,'https://app.walkerhill.com/about/Brand','MIXED_REFERENCE_AND_ASSUMPTION',true);

INSERT INTO walkerhill_v4_3.pms_rooms
(hotel_code,room_id,room_type_code,floor_no,is_active,provenance_class)
SELECT rt.hotel_code,
       rt.hotel_code || '-' || rt.room_type_code || '-' || lpad(n::text,4,'0'),
       rt.room_type_code,
       (2 + ((n-1) / 35))::smallint,
       true,'GENERATED_FACT'
FROM walkerhill_v4_3.pms_room_types rt
CROSS JOIN LATERAL generate_series(1,rt.synthetic_room_count) n;

WITH planned AS (
  SELECT r.room_id, cycle_no,
         DATE '2024-01-01' + (cycle_no-1)*195
           + floor(walkerhill_v4_3.v43_u01('ooo-date|' || r.room_id || '|' || cycle_no) * 183)::int AS start_date,
         (1 + floor(walkerhill_v4_3.v43_u01('ooo-duration|' || r.room_id || '|' || cycle_no) * 3))::int AS duration_days
  FROM walkerhill_v4_3.pms_rooms r CROSS JOIN generate_series(1,5) cycle_no
  WHERE r.room_id NOT IN (
    'GRAND-G_DELUXE-0355','GRAND-G_DELUXE-0356','GRAND-G_DELUXE-0357','GRAND-G_DELUXE-0358','GRAND-G_DELUXE-0359','GRAND-G_DELUXE-0360',
    'VISTA-V_DELUXE-0185','VISTA-V_DELUXE-0186','VISTA-V_DELUXE-0187','VISTA-V_DELUXE-0188','VISTA-V_DELUXE-0189','VISTA-V_DELUXE-0190',
    'DOUGLAS-D_DELUXE-0040','DOUGLAS-D_DELUXE-0041','DOUGLAS-D_DELUXE-0042','DOUGLAS-D_DELUXE-0043','DOUGLAS-D_DELUXE-0044','DOUGLAS-D_DELUXE-0045')
)
INSERT INTO walkerhill_v4_3.pms_room_out_of_order_periods
(out_of_order_id,room_id,started_at,ended_at,reason_code,work_order_ref,is_synthetic)
SELECT 'OOO_' || substr(encode(sha256(convert_to(room_id || '|' || cycle_no,'UTF8')),'hex'),1,28),
       room_id,(start_date::timestamp + TIME '09:00') AT TIME ZONE 'Asia/Seoul',
       ((start_date + duration_days)::timestamp + TIME '15:00') AT TIME ZONE 'Asia/Seoul',
       CASE floor(walkerhill_v4_3.v43_u01('ooo-reason|' || room_id || '|' || cycle_no)*4)::int
         WHEN 0 THEN 'PREVENTIVE' WHEN 1 THEN 'PLUMBING' WHEN 2 THEN 'HVAC' ELSE 'INTERIOR' END,
       'WO_' || substr(encode(sha256(convert_to('wo|' || room_id || '|' || cycle_no,'UTF8')),'hex'),1,24),true
FROM planned;

WITH outage AS (
  SELECT r.hotel_code,r.room_type_code,c.business_date,count(DISTINCT r.room_id)::int AS out_of_order_rooms
  FROM walkerhill_v4_3.pms_rooms r
  JOIN walkerhill_v4_3.pms_room_out_of_order_periods o USING(room_id)
  JOIN walkerhill_v4_3.calendar_daily c
    ON c.business_date >= (o.started_at AT TIME ZONE 'Asia/Seoul')::date
   AND c.business_date <  (o.ended_at AT TIME ZONE 'Asia/Seoul')::date
  GROUP BY r.hotel_code,r.room_type_code,c.business_date
), base AS (
  SELECT rt.hotel_code,c.business_date,rt.room_type_code,rt.synthetic_room_count AS physical_rooms,
         coalesce(o.out_of_order_rooms,0) AS out_of_order_rooms,
         CASE WHEN rt.synthetic_room_count>coalesce(o.out_of_order_rooms,0)
                   AND walkerhill_v4_3.v43_u01('house-use|' || rt.hotel_code || '|' || rt.room_type_code || '|' || to_char(c.business_date,'YYYY-MM-DD')) < 0.012
                   AND NOT EXISTS (
                     SELECT 1
                     FROM walkerhill_v4_3.pms_room_out_of_order_periods o2
                     WHERE o2.room_id=(
                       SELECT min(r2.room_id) FROM walkerhill_v4_3.pms_rooms r2
                       WHERE r2.hotel_code=rt.hotel_code AND r2.room_type_code=rt.room_type_code
                     )
                       AND c.business_date >= (o2.started_at AT TIME ZONE 'Asia/Seoul')::date
                       AND c.business_date <  (o2.ended_at AT TIME ZONE 'Asia/Seoul')::date
                   )
              THEN 1 ELSE 0 END AS house_use_rooms
  FROM walkerhill_v4_3.pms_room_types rt CROSS JOIN walkerhill_v4_3.calendar_daily c
  LEFT JOIN outage o USING(hotel_code,room_type_code,business_date)
)
INSERT INTO walkerhill_v4_3.pms_room_inventory_daily
(hotel_code,business_date,room_type_code,physical_rooms,out_of_order_rooms,house_use_rooms,available_room_nights,is_forecast,provenance_class)
SELECT hotel_code,business_date,room_type_code,physical_rooms,out_of_order_rooms,house_use_rooms,
       greatest(0,physical_rooms-out_of_order_rooms-house_use_rooms),false,'GENERATED_FACT'
FROM base;
