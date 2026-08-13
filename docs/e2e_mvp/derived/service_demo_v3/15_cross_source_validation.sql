-- Trino: actual violating identity/event-time rows
SELECT 'CRM_PMS_MAP_ORPHAN' AS issue, m.customer_map_id AS key FROM crm.dbo.crm_customer_map m LEFT JOIN pms.public.pms_guests g ON m.pms_guest_id=g.guest_id WHERE m.pms_guest_id IS NOT NULL AND g.guest_id IS NULL
UNION ALL SELECT 'POS_MEMBER_MAP_MULTIPLICATION',o.order_id FROM pos.pos_db.pos_orders o JOIN crm.dbo.crm_customer_map m ON o.pos_customer_ref=m.pos_customer_ref WHERE o.ordered_at>=m.valid_from AND (m.valid_to IS NULL OR o.ordered_at<m.valid_to) GROUP BY o.order_id HAVING count(*)>1;
