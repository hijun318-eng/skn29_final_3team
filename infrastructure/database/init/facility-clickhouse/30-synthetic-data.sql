INSERT INTO facility.work_order
    (work_order_id, facility_id, opened_at, closed_at, priority, status, description)
VALUES
    (50001, 1, '2026-07-27 08:20:00', '2026-07-27 11:10:00', 'high', 'closed', 'Cooling pressure inspection'),
    (50002, 2, '2026-07-28 09:15:00', NULL, 'medium', 'in_progress', 'Door sensor calibration'),
    (50003, 3, '2026-07-28 14:40:00', '2026-07-28 16:05:00', 'low', 'closed', 'Filter replacement');

INSERT INTO facility.sensor_reading
    (facility_id, measured_at, metric, value, unit)
VALUES
    (1, '2026-07-29 00:00:00', 'supply_temperature', 7.2, 'C'),
    (1, '2026-07-29 00:05:00', 'supply_temperature', 7.1, 'C'),
    (2, '2026-07-29 00:00:00', 'door_cycles', 128.0, 'count'),
    (3, '2026-07-29 00:00:00', 'flow_rate', 42.5, 'L/min');
