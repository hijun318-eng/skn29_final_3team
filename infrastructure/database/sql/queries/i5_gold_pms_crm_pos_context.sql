WITH pms_gold AS (
    SELECT
        s.property_id,
        date_format(date_trunc('month', s.actual_checkout_at AT TIME ZONE 'Asia/Seoul'), '%Y-%m') AS month,
        cast(sum(s.room_revenue) AS decimal(18,2)) AS room_revenue_krw
    FROM pms.public.pms_stays s
    JOIN pms.public.pms_reservations r
      ON s.property_id = r.property_id AND s.reservation_id = r.reservation_id
    JOIN pms.public.pms_guests g
      ON r.property_id = g.property_id AND r.guest_id = g.guest_id
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
    WHERE s.property_id = 'SYNTHETIC_HOTEL_001'
      AND s.stay_status = 'COMPLETED'
      AND s.room_revenue > 0
      AND s.complimentary_flag = false
      AND s.house_use_flag = false
      AND s.is_forecast = false
      AND h.grade_code = 'GOLD'
      AND s.actual_checkout_at >= TIMESTAMP '2026-05-01 00:00:00 Asia/Seoul'
      AND s.actual_checkout_at < TIMESTAMP '2026-07-01 00:00:00 Asia/Seoul'
    GROUP BY 1, 2
),
pos_gold AS (
    SELECT
        o.property_id,
        date_format(date_trunc('month', o.ordered_at), '%Y-%m') AS month,
        cast(sum(o.net_amount) AS decimal(18,2)) AS fnb_revenue_krw
    FROM pos.pos_db.pos_orders o
    JOIN crm.dbo.crm_customer_map m
      ON o.property_id = m.property_id
     AND o.pos_customer_ref = m.pos_customer_ref
     AND m.valid_from <= o.ordered_at
     AND (m.valid_to IS NULL OR o.ordered_at < m.valid_to)
    JOIN crm.dbo.crm_member_grade_history h
      ON m.property_id = h.property_id
     AND m.member_no = h.member_no
     AND h.valid_from <= o.ordered_at
     AND (h.valid_to IS NULL OR o.ordered_at < h.valid_to)
    WHERE o.property_id = 'SYNTHETIC_HOTEL_001'
      AND o.order_status IN ('PAID', 'PARTIAL_REFUND')
      AND o.payment_status IN ('PAID', 'PARTIAL_REFUND')
      AND o.void_flag = 0
      AND o.is_forecast = 0
      AND h.grade_code = 'GOLD'
      AND o.ordered_at >= TIMESTAMP '2026-05-01 00:00:00'
      AND o.ordered_at < TIMESTAMP '2026-07-01 00:00:00'
    GROUP BY 1, 2
)
SELECT
    coalesce(p.property_id, f.property_id) AS property_id,
    coalesce(p.month, f.month) AS month,
    coalesce(p.room_revenue_krw, DECIMAL '0.00') AS room_revenue_krw,
    coalesce(f.fnb_revenue_krw, DECIMAL '0.00') AS fnb_revenue_krw,
    coalesce(p.room_revenue_krw, DECIMAL '0.00') + coalesce(f.fnb_revenue_krw, DECIMAL '0.00') AS total_guest_revenue_krw
FROM pms_gold p
FULL OUTER JOIN pos_gold f
  ON p.property_id = f.property_id AND p.month = f.month
ORDER BY 1, 2
