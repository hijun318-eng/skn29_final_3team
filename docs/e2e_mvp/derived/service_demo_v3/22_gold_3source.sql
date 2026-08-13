-- Gold 3: PMS+CRM+POS member revenue
WITH stay_counts AS (
  SELECT cm.member_no, count(DISTINCT s.stay_id) stays
  FROM crm.dbo.crm_customer_map cm
  JOIN pms.public.pms_stays s ON cm.pms_guest_id=s.guest_id AND s.actual_checkin_at>=cm.valid_from AND (cm.valid_to IS NULL OR s.actual_checkin_at<cm.valid_to)
  WHERE cm.mapping_status='ACTIVE'
  GROUP BY cm.member_no
), order_totals AS (
  SELECT cm.member_no, count(DISTINCT o.order_id) orders, sum(o.net_amount) pos_net_amount
  FROM crm.dbo.crm_customer_map cm
  JOIN pos.pos_db.pos_orders o ON cm.pos_customer_ref=o.pos_customer_ref AND o.ordered_at>=cm.valid_from AND (cm.valid_to IS NULL OR o.ordered_at<cm.valid_to)
  WHERE cm.mapping_status='ACTIVE'
  GROUP BY cm.member_no
)
SELECT m.membership_grade, sum(coalesce(s.stays,0)) stays, sum(coalesce(o.orders,0)) orders, sum(coalesce(o.pos_net_amount,0)) pos_net_amount
FROM crm.dbo.crm_members m
LEFT JOIN stay_counts s ON m.member_no=s.member_no
LEFT JOIN order_totals o ON m.member_no=o.member_no
GROUP BY 1
ORDER BY 1;
