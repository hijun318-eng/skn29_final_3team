SELECT 'CRM_MEMBER_COUNT' issue,CAST(COUNT(*) AS varchar(36)) detail FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001' HAVING COUNT(*)<>13500
UNION ALL SELECT 'CRM_ORPHAN_MAP',m.customer_map_id FROM dbo.crm_customer_map m LEFT JOIN dbo.crm_members c ON m.member_no=c.member_no WHERE c.member_no IS NULL
UNION ALL SELECT 'CRM_INVALID_MAP_INTERVAL',customer_map_id FROM dbo.crm_customer_map WHERE valid_to IS NOT NULL AND valid_to<=valid_from;
