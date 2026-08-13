-- Gold 1: PMS daily completed-stay revenue
SELECT r.checkin_date, s.room_type_code, count(*) completed_stays, sum(s.room_revenue) room_revenue FROM pms.public.pms_stays s JOIN pms.public.pms_reservations r ON s.reservation_id=r.reservation_id WHERE s.property_id='SYNTHETIC_HOTEL_001' GROUP BY 1,2 ORDER BY 1,2;
