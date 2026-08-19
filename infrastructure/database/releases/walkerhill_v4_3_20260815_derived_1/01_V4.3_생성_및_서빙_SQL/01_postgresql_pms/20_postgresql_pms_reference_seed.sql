-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=REFERENCE; script_type=SEED; execution_order=20
-- dependencies=11_postgresql_pms_operation_ddl.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=993; execution_default=NOT_RUN; destructive_operation=false
-- evidence=official names only; all capacity, demand and weather values are synthetic assumptions
-- next=21_postgresql_pms_event_seed.sql

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM walkerhill_v4_3.hotel_entities)
     OR EXISTS (SELECT 1 FROM walkerhill_v4_3.calendar_daily)
     OR EXISTS (SELECT 1 FROM walkerhill_v4_3.evidence_registry) THEN
    RAISE EXCEPTION 'candidate reference tables must be empty';
  END IF;
END $$;

INSERT INTO walkerhill_v4_3.hotel_entities
(resort_id, hotel_code, parent_hotel_code, public_name, entity_type, source_url, source_as_of,
 synthetic_room_capacity, inventory_scope, reporting_scope, effective_from, effective_to,
 provenance_class, is_active)
VALUES
('WH_COMPLEX','WH_COMPLEX',NULL,'Walkerhill Hotels & Resorts','RESORT','https://www.walkerhill.com/kr/',DATE '2026-08-14',801,'ROLLUP_ONLY','CAMPUS_ROLLUP',DATE '2024-01-01',NULL,'MIXED_REFERENCE_AND_ASSUMPTION',false),
('WH_COMPLEX','GRAND','WH_COMPLEX','Grand Walkerhill Seoul','HOTEL','https://www.walkerhill.com/grandwalkerhillseoul/en/room/Intro',DATE '2026-08-14',505,'EXCLUDES_DOUGLAS','STANDALONE_PROPERTY',DATE '2024-01-01',NULL,'MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','VISTA','WH_COMPLEX','Vista Walkerhill Seoul','HOTEL','https://www.walkerhill.com/vistawalkerhillseoul/en/room/',DATE '2026-08-14',244,'STANDALONE','STANDALONE_PROPERTY',DATE '2024-01-01',NULL,'MIXED_REFERENCE_AND_ASSUMPTION',true),
('WH_COMPLEX','DOUGLAS','WH_COMPLEX','Douglas House','LODGING_PRODUCT','https://app.walkerhill.com/about/Brand',DATE '2026-08-14',52,'STANDALONE_SYNTHETIC','STANDALONE_PROPERTY',DATE '2024-01-01',NULL,'MIXED_REFERENCE_AND_ASSUMPTION',true);

INSERT INTO walkerhill_v4_3.evidence_registry
(evidence_id,evidence_grade,publisher,title,source_url,published_date,accessed_at,supported_fact,
 affected_table,affected_column,modeling_rule,confidence,notes)
VALUES
('EV_BRAND','A','Walkerhill','Walkerhill brand guide','https://app.walkerhill.com/about/Brand',NULL,TIMESTAMPTZ '2026-08-14 12:00:00+09','Grand, Vista and Douglas are separately presented public lodging brands.','hotel_entities','public_name','Names and hierarchy only; capacity remains synthetic.',0.98,'No claim about internal inventory.'),
('EV_ROOMS','A','Walkerhill','Grand and Vista room pages','https://www.walkerhill.com/grandwalkerhillseoul/en/room/Intro',NULL,TIMESTAMPTZ '2026-08-14 12:00:00+09','Public room product names are visible.','pms_room_types','public_name','Use public names but synthetic counts and rates.',0.95,'Douglas double-count risk is handled by reporting_scope.'),
('EV_DINING','A','Walkerhill','Dining reservation','https://app.walkerhill.com/book/Dining',NULL,TIMESTAMPTZ '2026-08-14 12:00:00+09','Multiple dining concepts and outlets are publicly presented.','pos_outlets','public_name','Outlet names may be public; capacities and sales are synthetic.',0.95,NULL),
('EV_MEETING','A','Walkerhill','Meeting and convention','https://www.walkerhill.com/en/convention/Meeting',NULL,TIMESTAMPTZ '2026-08-14 12:00:00+09','Walkerhill provides meeting and convention venues.','banquet_venues','public_name','Venue names may be public; operational facts are synthetic.',0.94,NULL),
('EV_FY2024','A','SK Networks','Hotels and Resorts business','https://www.sknetworks.co.kr/business/hotel-and-resort',DATE '2024-12-31',TIMESTAMPTZ '2026-08-14 12:00:00+09','FY2024 hotel and resort segment sales are published as KRW 300.6 billion and include broader business scope.','total_operating_daily_metrics','total_operating_revenue','Use only as a broad scope sanity reference, never a campus revenue target.',0.90,'Includes activities outside the three-property synthetic scope.'),
('EV_2024_Q1','A','SK Networks','2024 first-quarter result release','https://www.sknetworks.co.kr/pr/news-room/15851?currentPage=&searchWord=',DATE '2024-05-13',TIMESTAMPTZ '2026-08-14 12:00:00+09','The Buffet reopening and seasonal activities were associated with more hotel and F&B visitors.','event_master','event_id','Presence is factual; exact uplift and active window are explicit assumptions.',0.86,NULL),
('EV_2024_Q3','A','SK Networks','2024 third-quarter result release','https://www.sknetworks.co.kr/pr/news-room/scpm59RylbxdyymG',DATE '2024-11-13',TIMESTAMPTZ '2026-08-14 12:00:00+09','Camknic, Park Concert and Pizza Hill autumn festival were reported as attracting guests and raising occupancy.','event_master','event_id','Event presence is factual; daily timing and uplift are modeled.',0.88,NULL),
('EV_2025_GOLF','A','SK Networks','Walkerhill Golf Club grand opening','https://www.sknetworks.co.kr/pr/news-room/NDkFwvSVzMWc5qjY',DATE '2025-06-19',TIMESTAMPTZ '2026-08-14 12:00:00+09','Walkerhill Golf Club opened on 2025-06-21.','event_master','start_date','Opening date is factual; traffic and revenue response are modeled.',0.98,NULL),
('EV_2025_GOLF_PACKAGE','A','SK Networks','Walkerhill golf-linked stay package','https://www.sknetworks.co.kr/pr/news-room/aBjjJAKmW61iYTG9',DATE '2025-07-14',TIMESTAMPTZ '2026-08-15 12:00:00+09','A Walkerhill Golf Club linked stay package was announced for 2025-07-14 through 2025-12-31.','event_master','start_date,end_date','Package availability dates are factual; demand and revenue uplift are modeled.',0.96,NULL),
('EV_2026_SPRING','A','Walkerhill','Spring Forest and Jazz Picnic offers','https://www.walkerhill.com/Promotion?tag=%EC%97%B0%EC%9D%B8',DATE '2026-04-22',TIMESTAMPTZ '2026-08-15 12:00:00+09','Walkerhill publicly listed Spring Forest and Jazz Picnic offers through 2026-06-07.','event_master','start_date,end_date','Offer dates are factual; demand and revenue effects are synthetic.',0.88,NULL),
('EV_2026_EARLY_SUMMER','A','Walkerhill','Summer Pairing and Just Summer offers','https://www.walkerhill.com/en/offers/Overview',DATE '2026-05-11',TIMESTAMPTZ '2026-08-15 12:00:00+09','Walkerhill publicly listed early-summer room offers through 2026-08-31.','event_master','start_date,end_date','Offer dates are factual; hotel-specific uplift is synthetic.',0.90,NULL),
('EV_2026_RIVERPARK','A','Walkerhill','Riverpark summer offers','https://www.walkerhill.com/en/offers/Overview',DATE '2026-06-26',TIMESTAMPTZ '2026-08-15 12:00:00+09','Grand, Vista and Douglas publicly listed Riverpark-linked summer offers for 2026-06-26 through 2026-08-30.','event_master','start_date,end_date','Offer dates and property participation are factual; effect sizes are synthetic.',0.95,NULL),
('EV_2026_CONSTITUTION_DAY','A','Ministry of the Interior and Safety','Constitution Day reinstated as a public holiday','https://www.mois.go.kr/video/bbs/type019/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000255&nttId=123641&searchCode1=A06',DATE '2026-02-04',TIMESTAMPTZ '2026-08-15 12:00:00+09','Constitution Day on July 17 is a public holiday again from 2026.','calendar_daily','is_holiday,holiday_name','The holiday date is factual; synthetic demand and room-rate effects remain explicit modeling assumptions.',0.99,NULL),
('EV_RATE_DAY','A','Walkerhill','Asiana mileage room package rate table','https://www.walkerhill.com/asianaairlinesmileage',NULL,TIMESTAMPTZ '2026-08-14 12:00:00+09','Walkerhill publicly separates lodging package amounts into Sunday-Thursday, Friday and Saturday.','calendar_daily','room_rate_day_type','Preserve the three day types; the synthetic ADR multipliers are assumptions and do not copy package prices.',0.95,'Holiday-eve overrides require a separate dated offer and are modeled through is_holiday only.'),
('EV_KTO','B','Korea Tourism Data Lab','Korea Tourism Data Lab','https://datalab.visitkorea.or.kr/',NULL,TIMESTAMPTZ '2026-08-14 12:00:00+09','Public tourism aggregates can anchor seasonality without exposing hotel internal data.','calendar_daily','synthetic_demand_index','Use only aggregate patterns; no fabricated hotel actuals.',0.80,NULL);

WITH days AS (
  SELECT d::date AS business_date
  FROM generate_series(DATE '2024-01-01', DATE '2026-08-31', INTERVAL '1 day') d
), labeled AS (
  SELECT business_date,
         extract(isodow FROM business_date)::smallint AS day_of_week,
         extract(isodow FROM business_date) IN (6,7) AS is_weekend,
         CASE extract(isodow FROM business_date)
           WHEN 5 THEN 'FRIDAY' WHEN 6 THEN 'SATURDAY' ELSE 'SUN_THU'
         END AS room_rate_day_type,
         CASE
           WHEN business_date IN (DATE '2024-01-01',DATE '2024-02-09',DATE '2024-02-10',DATE '2024-02-11',DATE '2024-02-12',DATE '2024-03-01',DATE '2024-05-05',DATE '2024-05-06',DATE '2024-05-15',DATE '2024-06-06',DATE '2024-08-15',DATE '2024-09-16',DATE '2024-09-17',DATE '2024-09-18',DATE '2024-10-03',DATE '2024-10-09',DATE '2024-12-25',
                                  DATE '2025-01-01',DATE '2025-01-28',DATE '2025-01-29',DATE '2025-01-30',DATE '2025-03-01',DATE '2025-03-03',DATE '2025-05-05',DATE '2025-05-06',DATE '2025-06-06',DATE '2025-08-15',DATE '2025-10-03',DATE '2025-10-05',DATE '2025-10-06',DATE '2025-10-07',DATE '2025-10-08',DATE '2025-10-09',DATE '2025-12-25',
                                  DATE '2026-01-01',DATE '2026-02-16',DATE '2026-02-17',DATE '2026-02-18',DATE '2026-03-01',DATE '2026-03-02',DATE '2026-05-05',DATE '2026-05-24',DATE '2026-05-25',DATE '2026-06-03',DATE '2026-06-06',DATE '2026-07-17',DATE '2026-08-15',DATE '2026-08-17') THEN true ELSE false END AS is_holiday
  FROM days
)
INSERT INTO walkerhill_v4_3.calendar_daily
(business_date,day_of_week,is_weekend,room_rate_day_type,is_holiday,holiday_name,season_code,synthetic_weather_score,synthetic_demand_index,promotion_code,provenance_class)
SELECT business_date, day_of_week, is_weekend, room_rate_day_type, is_holiday,
       CASE WHEN is_holiday THEN 'KOREA_PUBLIC_HOLIDAY' END,
       CASE WHEN extract(month FROM business_date) IN (12,1,2) THEN 'WINTER'
            WHEN extract(month FROM business_date) IN (3,4,5) THEN 'SPRING'
            WHEN extract(month FROM business_date) IN (6,7,8) THEN 'SUMMER' ELSE 'AUTUMN' END,
       round((0.35 + 0.60 * walkerhill_v4_3.v43_u01('weather|' || to_char(business_date,'YYYY-MM-DD')))::numeric,4),
       round((0.78
          + CASE WHEN is_weekend THEN 0.18 ELSE 0 END
          + CASE WHEN is_holiday THEN 0.22 ELSE 0 END
          + CASE WHEN extract(month FROM business_date) IN (5,7,8,10,12) THEN 0.12 ELSE 0 END
          + 0.16 * walkerhill_v4_3.v43_u01('demand|' || to_char(business_date,'YYYY-MM-DD')))::numeric,4),
       CASE WHEN business_date BETWEEN DATE '2026-06-26' AND DATE '2026-08-30' THEN 'RIVERPARK_2026'
            WHEN business_date BETWEEN DATE '2026-05-11' AND DATE '2026-08-31' THEN 'EARLY_SUMMER_2026'
            WHEN business_date BETWEEN DATE '2026-04-22' AND DATE '2026-06-07' THEN 'SPRING_JAZZ_2026'
            WHEN business_date BETWEEN DATE '2025-06-21' AND DATE '2025-12-31' THEN 'GOLF_PACKAGE'
            WHEN extract(month FROM business_date)=12 THEN 'YEAR_END'
            WHEN extract(month FROM business_date) IN (9,10) THEN 'AUTUMN_CONTENT' END,
       'MIXED_PUBLIC_CALENDAR_AND_SYNTHETIC_DRIVER'
FROM labeled;
