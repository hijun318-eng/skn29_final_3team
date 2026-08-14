SELECT
    date_format(
        date_trunc('month', s.actual_checkout_at AT TIME ZONE 'Asia/Seoul'),
        '%Y-%m'
    ) AS month,
    cast(sum(s.room_revenue) AS decimal(18,2)) AS recognized_room_revenue_krw
FROM pms.public.pms_stays s
JOIN pms.public.pms_reservations r
  ON s.property_id = r.property_id
 AND s.reservation_id = r.reservation_id
JOIN pms.public.pms_guests g
  ON r.property_id = g.property_id
 AND r.guest_id = g.guest_id
JOIN crm.dbo.crm_customer_map m
  ON g.property_id = m.property_id
 AND g.guest_id = m.pms_guest_id
 AND m.valid_from <= s.actual_checkout_at
 AND (m.valid_to IS NULL OR s.actual_checkout_at < m.valid_to)
JOIN crm.dbo.crm_member_grade_history h
  ON m.property_id = h.property_id
 AND m.member_no = h.member_no
 AND h.valid_from <= s.actual_checkout_at
 AND (h.valid_to IS NULL OR s.actual_checkout_at < h.valid_to)
WHERE s.stay_status = :required_filter_1
  AND s.room_revenue > 0
  AND s.complimentary_flag = :required_filter_2
  AND s.house_use_flag = :required_filter_3
  AND s.is_forecast = :required_filter_4
  AND h.grade_code = 'GOLD'
  AND s.actual_checkout_at >= from_iso8601_timestamp(:period_start)
  AND s.actual_checkout_at < from_iso8601_timestamp(:period_end_exclusive)
GROUP BY 1
ORDER BY 1
LIMIT 1000
