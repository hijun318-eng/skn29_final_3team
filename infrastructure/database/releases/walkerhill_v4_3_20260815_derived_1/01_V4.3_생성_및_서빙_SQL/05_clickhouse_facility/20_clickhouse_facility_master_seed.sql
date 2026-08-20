-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=ClickHouse 24.8+; domain=FACILITY; script_type=SEED; execution_order=20
-- expected_rows=10; dependency=10_clickhouse_facility_ddl.sql; execution_default=NOT_RUN
-- official_fact=Walkerhill Golf Club opens 2025-06-21; other capacity values are synthetic

SELECT throwIf(count()>0,'candidate facility master table must be empty') FROM walkerhill_v4_3.facility_master;

INSERT INTO walkerhill_v4_3.facility_master
(facility_id,facility_name,facility_type,hotel_code,reporting_hotel_code,effective_from,capacity,
 open_minute,close_minute,closed_iso_weekday,source_url,provenance_class,is_synthetic) VALUES
('F_GOLF','Walkerhill Golf Club','GOLF','CAMPUS','VISTA','2025-06-21',240,360,1320,0,'https://www.sknetworks.co.kr/pr/news-room/NDkFwvSVzMWc5qjY','OFFICIAL_NAME_SYNTHETIC_RULE',1),
('F_RIVERPARK','Riverpark','POOL','CAMPUS','GRAND','2024-01-01',800,540,1200,0,'https://www.walkerhill.com','OFFICIAL_NAME_SYNTHETIC_RULE',1),
('F_GRAND_FIT','Grand Fitness','FITNESS','GRAND','GRAND','2024-01-01',90,360,1320,0,'https://www.walkerhill.com','SYNTHETIC_ASSUMPTION',1),
('F_VISTA_WELL','Vista Wellness','WELLNESS','VISTA','VISTA','2024-01-01',75,420,1320,0,'https://www.walkerhill.com','SYNTHETIC_ASSUMPTION',1),
('F_DOUGLAS_LIB','Douglas Library','GUEST_SERVICE','DOUGLAS','DOUGLAS','2024-01-01',60,420,1380,0,'https://app.walkerhill.com/about/Brand','OFFICIAL_NAME_SYNTHETIC_RULE',1),
('F_SAUNA','Campus Sauna','WELLNESS','CAMPUS','GRAND','2024-01-01',130,360,1320,0,'https://www.walkerhill.com','SYNTHETIC_ASSUMPTION',1),
('F_TENNIS','Campus Tennis Court','FITNESS','CAMPUS','VISTA','2024-01-01',32,420,1260,0,'https://www.walkerhill.com','SYNTHETIC_ASSUMPTION',1),
('F_KIDS','Kids Program Center','GUEST_SERVICE','CAMPUS','DOUGLAS','2024-01-01',80,540,1140,0,'https://www.walkerhill.com','SYNTHETIC_ASSUMPTION',1),
('F_GARDEN','Outdoor Event Garden','EVENT_SUPPORT','CAMPUS','GRAND','2024-01-01',500,480,1320,0,'https://www.walkerhill.com/en/convention/Meeting','SYNTHETIC_ASSUMPTION',1),
('F_CONV','Convention Support','EVENT_SUPPORT','CAMPUS','GRAND','2024-01-01',1200,420,1380,0,'https://www.walkerhill.com/en/convention/Meeting','OFFICIAL_NAME_SYNTHETIC_RULE',1);
