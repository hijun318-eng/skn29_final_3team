-- Any returned row is an actual violation. Empty result is required.
SELECT 'BANQUET_TARGET_BOOKING_COUNT' AS issue,COUNT(*)::text AS detail FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' HAVING COUNT(*)<>2400
UNION ALL SELECT 'BANQUET_INVALID_FUNNEL_TIME',banquet_event_id FROM banquet_bookings WHERE quoted_at IS NOT NULL AND quoted_at<inquiry_at OR confirmed_at IS NOT NULL AND (quoted_at IS NULL OR confirmed_at<quoted_at) OR cancelled_at IS NOT NULL AND cancelled_at<inquiry_at
UNION ALL SELECT 'BANQUET_COMPLETED_ATTENDANCE',banquet_event_id FROM banquet_bookings WHERE booking_status='COMPLETED' AND actual_attendees IS NULL
UNION ALL SELECT 'BANQUET_REVENUE_ORPHAN',r.revenue_id FROM banquet_revenue r LEFT JOIN banquet_bookings b ON b.banquet_event_id=r.banquet_event_id WHERE b.banquet_event_id IS NULL
UNION ALL SELECT 'BANQUET_STATUS_REVENUE_MISMATCH',r.revenue_id FROM banquet_revenue r JOIN banquet_bookings b ON b.banquet_event_id=r.banquet_event_id WHERE (b.booking_status='COMPLETED' AND r.revenue_status<>'RECOGNIZED') OR (b.booking_status='CANCELLED' AND r.revenue_status<>'REVERSED') OR r.revenue_amount<0 OR r.reversal_amount<0
UNION ALL SELECT 'BANQUET_FORECAST_MISMATCH',banquet_event_id FROM banquet_bookings WHERE is_forecast<>(data_period_status='FORECAST_SCENARIO');
