-- Gold smoke: all five catalogs must contribute matching synthetic property
SELECT * FROM (
  SELECT 'pms' source, count(*) rows FROM pms.public.pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001'
  UNION ALL SELECT 'pos',count(*) FROM pos.pos_db.pos_orders WHERE property_id='SYNTHETIC_HOTEL_001'
  UNION ALL SELECT 'crm',count(*) FROM crm.dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001'
  UNION ALL SELECT 'banquet',count(*) FROM banquet.public.banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001'
  UNION ALL SELECT 'facility',count(*) FROM facility.facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001'
) ORDER BY source;
