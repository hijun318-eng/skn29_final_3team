-- Facility DB (ClickHouse) — 시설 이용, 이벤트
CREATE TABLE IF NOT EXISTS facility_events (
    event_id String,
    facility_id String,
    event_type String DEFAULT 'USAGE',
    event_datetime DateTime DEFAULT now(),
    user_count UInt32 DEFAULT 0,
    duration_min UInt32 DEFAULT 0,
    is_synthetic UInt8 DEFAULT 1
) ENGINE = MergeTree()
ORDER BY (facility_id, event_datetime);

INSERT INTO facility_events VALUES
('EVT-001','FAC-POOL','USAGE','2026-07-20 08:00:00',45,60,1),
('EVT-002','FAC-GYM','USAGE','2026-07-20 07:00:00',12,45,1),
('EVT-003','FAC-POOL','USAGE','2026-07-21 09:00:00',52,75,1),
('EVT-004','FAC-SPA','INSPECTION','2026-07-22 10:00:00',0,120,1),
('EVT-005','FAC-POOL','INCIDENT','2026-07-22 14:00:00',0,30,1),
('EVT-006','FAC-GYM','USAGE','2026-07-23 06:30:00',8,30,1),
('EVT-007','FAC-POOL','USAGE','2026-07-23 08:00:00',38,60,1),
('EVT-008','FAC-SPA','USAGE','2026-07-24 11:00:00',6,90,1);
