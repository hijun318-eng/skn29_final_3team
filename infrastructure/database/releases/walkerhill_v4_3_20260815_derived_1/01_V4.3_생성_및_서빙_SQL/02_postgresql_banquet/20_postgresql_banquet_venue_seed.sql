-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=banquet_db; target_schema=walkerhill_v4_3
-- domain=BANQUET; script_type=MASTER_SEED; execution_order=20
-- dependencies=10_postgresql_banquet_ddl.sql; expected_rows=7
-- execution_default=NOT_RUN; destructive_operation=false
-- evidence=names are public; capacities below are explicitly synthetic assumptions
-- next=30_postgresql_banquet_booking_seed.sql

DO $$ BEGIN IF EXISTS(SELECT 1 FROM walkerhill_v4_3.banquet_venues) THEN RAISE EXCEPTION 'candidate venue table must be empty'; END IF; END $$;
INSERT INTO walkerhill_v4_3.banquet_venues
(venue_id,hotel_code,public_name,venue_category,synthetic_capacity,public_capacity_note,source_url,provenance_class,is_active)
VALUES
('VENUE_GRAND_HALL','GRAND','Grand Hall','BALLROOM',1000,'Synthetic capacity; verify before external use','https://www.walkerhill.com/en/convention/Meeting','MIXED_REFERENCE_AND_ASSUMPTION',true),
('VENUE_VISTA_HALL','VISTA','Vista Hall','BALLROOM',700,'Synthetic capacity','https://www.walkerhill.com/en/convention/Meeting','MIXED_REFERENCE_AND_ASSUMPTION',true),
('VENUE_WALKER_HALL','GRAND','Walker Hall','MEETING',450,'Synthetic capacity','https://www.walkerhill.com/en/convention/Meeting','MIXED_REFERENCE_AND_ASSUMPTION',true),
('VENUE_ART_HALL','VISTA','Art Hall','MEETING',250,'Synthetic capacity','https://www.walkerhill.com/en/convention/Meeting','MIXED_REFERENCE_AND_ASSUMPTION',true),
('VENUE_ASTON','GRAND','Aston House','WEDDING',300,'Synthetic capacity','https://www.walkerhill.com/en/convention/Meeting','MIXED_REFERENCE_AND_ASSUMPTION',true),
('VENUE_MYUNGWOL','GRAND','Myungwolgwan Garden','WEDDING',180,'Synthetic capacity','https://www.walkerhill.com/en/convention/Meeting','MIXED_REFERENCE_AND_ASSUMPTION',true),
('VENUE_FOREST','DOUGLAS','Forest Park Event Space','OUTDOOR',220,'Synthetic capacity','https://www.walkerhill.com/en/convention/Meeting','MIXED_REFERENCE_AND_ASSUMPTION',true);
