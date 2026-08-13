-- PMS validation: each UNION ALL returns concrete violating rows
SELECT 'PMS_TARGET_GUEST_COUNT' issue, count(*)::text detail FROM pms_guests WHERE property_id='SYNTHETIC_HOTEL_001' HAVING count(*)<>16000
UNION ALL SELECT 'PMS_TARGET_INVENTORY_COUNT',count(*)::text FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001' HAVING count(*)<>2308
UNION ALL SELECT 'PMS_TARGET_RESERVATION_COUNT',count(*)::text FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' HAVING count(*)<>43200
UNION ALL SELECT 'PMS_TARGET_COMPLETED_STAY_COUNT',count(*)::text FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001' HAVING count(*)<>37800
UNION ALL SELECT 'PMS_ORPHAN_RESERVATION',reservation_id FROM pms_reservations r LEFT JOIN pms_guests g ON g.guest_id=r.guest_id WHERE g.guest_id IS NULL
UNION ALL SELECT 'PMS_INVALID_STAY_INTERVAL',stay_id FROM pms_stays WHERE actual_checkout_at<=actual_checkin_at
UNION ALL SELECT 'PMS_STAY_OUTSIDE_INVENTORY',stay_id FROM pms_stays WHERE (actual_checkin_at AT TIME ZONE 'Asia/Seoul')::date < (SELECT min(business_date) FROM pms_room_inventory_daily) OR (actual_checkout_at AT TIME ZONE 'Asia/Seoul')::date > (SELECT max(business_date) FROM pms_room_inventory_daily)
UNION ALL SELECT 'PMS_CANCELLED_FINANCIAL_MISMATCH',reservation_id FROM pms_reservations WHERE reservation_status='CANCELLED' AND refund_amount+cancellation_fee<>booked_amount
UNION ALL SELECT 'PMS_FORECAST_MISMATCH',reservation_id FROM pms_reservations WHERE is_forecast<>(data_period_status='FORECAST_SCENARIO');
