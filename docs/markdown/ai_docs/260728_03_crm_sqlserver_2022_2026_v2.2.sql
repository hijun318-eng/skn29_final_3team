-- 호텔 데이터허브 합성 Source 데이터 적재 SQL
-- seed=20260728 / schema_version=schema-v4.6-websql / scenario_version=scenario-v4.6
-- fixture_version=source-fixture-v4.6 / property_id=SYNTHETIC_HOTEL_001 / synthetic=true
-- source_id=crm / engine=SQL Server 2022 / database=hotel_crm
-- ingestion_role=crm_ingest / query_role=crm_query / trino_catalog=crm
-- 검증 상태: STATIC_REVALIDATED_PASS / DB_EXECUTION_NOT_RUN
-- DDL 생성 금지. v4.6 DDL이 먼저 적용되어 있어야 한다.

USE [hotel_crm];
GO
SET XACT_ABORT ON;
SET NOCOUNT ON;
SET DATEFORMAT ymd;
SET LANGUAGE us_english;
SET LOCK_TIMEOUT 30000;
GO

-- 전체 44개 컬럼 계약 검사.
IF EXISTS (
 SELECT 1 FROM (VALUES
 ('crm_members','property_id'),
 ('crm_members','member_no'),
 ('crm_members','membership_grade'),
 ('crm_members','points_balance'),
 ('crm_members','joined_at'),
 ('crm_members','member_status'),
 ('crm_members','data_period_status'),
 ('crm_members','is_forecast'),
 ('crm_members','is_synthetic'),
 ('crm_members','source_updated_at'),
 ('crm_member_grade_history','property_id'),
 ('crm_member_grade_history','grade_history_id'),
 ('crm_member_grade_history','member_no'),
 ('crm_member_grade_history','grade_code'),
 ('crm_member_grade_history','valid_from'),
 ('crm_member_grade_history','valid_to'),
 ('crm_member_grade_history','change_reason_code'),
 ('crm_member_grade_history','is_synthetic'),
 ('crm_member_grade_history','source_updated_at'),
 ('crm_point_transactions','property_id'),
 ('crm_point_transactions','point_txn_id'),
 ('crm_point_transactions','member_no'),
 ('crm_point_transactions','event_at'),
 ('crm_point_transactions','txn_type'),
 ('crm_point_transactions','points_delta'),
 ('crm_point_transactions','related_source'),
 ('crm_point_transactions','related_id'),
 ('crm_point_transactions','data_period_status'),
 ('crm_point_transactions','is_forecast'),
 ('crm_point_transactions','is_synthetic'),
 ('crm_point_transactions','source_updated_at'),
 ('crm_customer_map','property_id'),
 ('crm_customer_map','customer_map_id'),
 ('crm_customer_map','member_no'),
 ('crm_customer_map','pms_guest_id'),
 ('crm_customer_map','pos_customer_ref'),
 ('crm_customer_map','facility_user_ref'),
 ('crm_customer_map','banquet_customer_id'),
 ('crm_customer_map','valid_from'),
 ('crm_customer_map','valid_to'),
 ('crm_customer_map','mapping_status'),
 ('crm_customer_map','mapping_confidence'),
 ('crm_customer_map','is_synthetic'),
 ('crm_customer_map','source_updated_at')
 ) r(t,c)
 WHERE NOT EXISTS (
  SELECT 1 FROM sys.columns sc JOIN sys.tables st ON st.object_id=sc.object_id
  WHERE st.name=r.t AND sc.name=r.c AND SCHEMA_NAME(st.schema_id)='dbo'
 )
) THROW 51000,'SCHEMA_CONTRACT_MISMATCH',1;
GO

BEGIN TRANSACTION;
IF EXISTS (
 SELECT 1 FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0
 UNION ALL SELECT 1 FROM dbo.crm_member_grade_history WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0
 UNION ALL SELECT 1 FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0
 UNION ALL SELECT 1 FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0
) THROW 51001,'NON_SYNTHETIC_ROW_PRESENT',1;

DELETE FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=1;
DELETE FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=1;
DELETE FROM dbo.crm_member_grade_history WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=1;
DELETE FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=1;

-- 결정적 1..80000 tally. ORDER BY (SELECT NULL)을 사용하지 않는다.
WITH D(n) AS (SELECT n FROM (VALUES(0),(1),(2),(3),(4),(5),(6),(7),(8),(9))v(n)),
Nums AS (
 SELECT 1+d0.n+10*d1.n+100*d2.n+1000*d3.n+10000*d4.n n
 FROM D d0 CROSS JOIN D d1 CROSS JOIN D d2 CROSS JOIN D d3 CROSS JOIN D d4
 WHERE d0.n+10*d1.n+100*d2.n+1000*d3.n+10000*d4.n < 80000
),
Base AS (
 SELECT n,CASE WHEN n<=300 THEN DATEADD(day,n,CONVERT(datetime2(3),'2022-01-01T00:00:00.000',126)) ELSE DATEADD(day,(n*19)%1580,CONVERT(datetime2(3),'2022-01-01T00:00:00.000',126)) END joined_at,
        CASE WHEN n<=150 THEN 'SILVER' WHEN n<=300 THEN 'GOLD'
             WHEN n%100<55 THEN 'SILVER' WHEN n%100<85 THEN 'GOLD' WHEN n%100<95 THEN 'VIP' ELSE 'BASIC' END current_grade
 FROM Nums
)
INSERT dbo.crm_members(property_id,member_no,membership_grade,points_balance,joined_at,member_status,data_period_status,is_forecast,is_synthetic,source_updated_at)
SELECT 'SYNTHETIC_HOTEL_001',CONCAT('MEM-',RIGHT(CONCAT('00000000',n),8)),current_grade,1800,joined_at,
       CASE WHEN n%100<96 THEN 'ACTIVE' WHEN n%100<99 THEN 'INACTIVE' ELSE 'REVOKED' END,
       CASE WHEN joined_at<'2025-01-01' THEN 'REFERENCE_CALIBRATED' WHEN joined_at<'2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE' ELSE 'YTD_SYNTHETIC' END,
       0,1,DATEADD(hour,1+(n%72),joined_at)
FROM Base;

WITH D(n) AS (SELECT n FROM (VALUES(0),(1),(2),(3),(4),(5),(6),(7),(8),(9))v(n)),
Nums AS (
 SELECT 1+d0.n+10*d1.n+100*d2.n+1000*d3.n+10000*d4.n n
 FROM D d0 CROSS JOIN D d1 CROSS JOIN D d2 CROSS JOIN D d3 CROSS JOIN D d4
 WHERE d0.n+10*d1.n+100*d2.n+1000*d3.n+10000*d4.n < 80000
),
M AS (
 SELECT n,CONCAT('MEM-',RIGHT(CONCAT('00000000',n),8)) member_no,m.joined_at,m.membership_grade current_grade,
        CASE WHEN n<=150 THEN 'GOLD' WHEN n<=300 THEN 'SILVER' WHEN n%4=0 THEN 'BASIC' ELSE 'SILVER' END initial_grade,
        CASE WHEN n<=300 THEN CONVERT(datetime2(3),'2025-01-01T00:00:00.000',126)
             ELSE CASE WHEN DATEADD(day,30+((n*7)%300),m.joined_at)>CONVERT(datetime2(3),'2026-06-30T00:00:00.000',126) THEN CONVERT(datetime2(3),'2026-06-30T00:00:00.000',126) ELSE DATEADD(day,30+((n*7)%300),m.joined_at) END END transition_at
 FROM Nums JOIN dbo.crm_members m ON m.property_id='SYNTHETIC_HOTEL_001' AND m.member_no=CONCAT('MEM-',RIGHT(CONCAT('00000000',n),8))
), H AS (
 SELECT n,member_no,initial_grade grade_code,joined_at valid_from,transition_at valid_to,'JOIN' reason FROM M
 UNION ALL SELECT n,member_no,current_grade,transition_at,NULL,
   CASE WHEN current_grade IN('GOLD','VIP') AND initial_grade IN('BASIC','SILVER') THEN 'UPGRADE'
        WHEN current_grade IN('BASIC','SILVER') AND initial_grade IN('GOLD','VIP') THEN 'DOWNGRADE' ELSE 'REVIEW' END FROM M
)
INSERT dbo.crm_member_grade_history(property_id,grade_history_id,member_no,grade_code,valid_from,valid_to,change_reason_code,is_synthetic,source_updated_at)
SELECT 'SYNTHETIC_HOTEL_001','GRD-'+LEFT(CONVERT(varchar(64),HASHBYTES('SHA2_256',CONCAT(member_no,'|',CONVERT(varchar(33),valid_from,126),'|',grade_code)),2),32),
       member_no,grade_code,valid_from,valid_to,reason,1,DATEADD(hour,1,COALESCE(valid_to,valid_from))
FROM H;

WITH D(n) AS (SELECT n FROM (VALUES(0),(1),(2),(3),(4),(5),(6),(7),(8),(9))v(n)),
Nums AS (
 SELECT 1+d0.n+10*d1.n+100*d2.n+1000*d3.n+10000*d4.n n
 FROM D d0 CROSS JOIN D d1 CROSS JOIN D d2 CROSS JOIN D d3 CROSS JOIN D d4
 WHERE d0.n+10*d1.n+100*d2.n+1000*d3.n+10000*d4.n < 80000
),
Seq AS (SELECT 1 s,1000 delta,'EARN' typ UNION ALL SELECT 2,500,'EARN' UNION ALL SELECT 3,-300,'USE' UNION ALL SELECT 4,700,'EARN' UNION ALL SELECT 5,-100,'EXPIRE'),
Tx AS (
 SELECT n,s,delta,typ,CONCAT('MEM-',RIGHT(CONCAT('00000000',n),8)) member_no,DATEADD(day,s*7,m.joined_at) event_at
 FROM Nums CROSS JOIN Seq JOIN dbo.crm_members m ON m.property_id='SYNTHETIC_HOTEL_001' AND m.member_no=CONCAT('MEM-',RIGHT(CONCAT('00000000',n),8))
)
INSERT dbo.crm_point_transactions(property_id,point_txn_id,member_no,event_at,txn_type,points_delta,related_source,related_id,data_period_status,is_forecast,is_synthetic,source_updated_at)
SELECT 'SYNTHETIC_HOTEL_001','PTX-'+LEFT(CONVERT(varchar(64),HASHBYTES('SHA2_256',CONCAT(member_no,'|',CONVERT(varchar(33),event_at,126),'|',s)),2),32),member_no,event_at,typ,delta,
       CASE WHEN s=1 THEN 'PMS' WHEN s=2 THEN 'POS' WHEN s=3 THEN 'FACILITY' WHEN s=4 AND n<=6000 THEN 'BANQUET' ELSE NULL END,
       CASE WHEN s=1 THEN CONCAT('GST-',RIGHT(member_no,8)) WHEN s=2 THEN CONCAT('POSC-',RIGHT(member_no,8)) WHEN s=3 THEN CONCAT('FACU-',RIGHT(member_no,8)) WHEN s=4 AND n<=6000 THEN CONCAT('BQC-',RIGHT(member_no,8)) ELSE NULL END,
       CASE WHEN event_at<'2025-01-01' THEN 'REFERENCE_CALIBRATED' WHEN event_at<'2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE' ELSE 'YTD_SYNTHETIC' END,
       0,1,DATEADD(minute,30,event_at)
FROM Tx;

WITH D(n) AS (SELECT n FROM (VALUES(0),(1),(2),(3),(4),(5),(6),(7),(8),(9))v(n)),
Nums AS (
 SELECT 1+d0.n+10*d1.n+100*d2.n+1000*d3.n+10000*d4.n n
 FROM D d0 CROSS JOIN D d1 CROSS JOIN D d2 CROSS JOIN D d3 CROSS JOIN D d4
 WHERE d0.n+10*d1.n+100*d2.n+1000*d3.n+10000*d4.n < 80000
),
Versions AS (SELECT n,1 v FROM Nums UNION ALL SELECT n,2 FROM Nums WHERE n<=10000),
MapBase AS (
 SELECT n,v,CONCAT('MEM-',RIGHT(CONCAT('00000000',n),8)) member_no,m.joined_at,
        CASE WHEN n<=10000 AND v=1 THEN DATEADD(day,1,m.joined_at)
             WHEN n<=10000 AND v=2 THEN CASE WHEN DATEADD(day,180,m.joined_at)>CONVERT(datetime2(3),'2026-06-30T00:00:00.000',126) THEN CONVERT(datetime2(3),'2026-06-30T00:00:00.000',126) ELSE DATEADD(day,180,m.joined_at) END
             ELSE DATEADD(day,1,m.joined_at) END valid_from,
        CASE WHEN n<=10000 AND v=1 THEN CASE WHEN DATEADD(day,180,m.joined_at)>CONVERT(datetime2(3),'2026-06-30T00:00:00.000',126) THEN CONVERT(datetime2(3),'2026-06-30T00:00:00.000',126) ELSE DATEADD(day,180,m.joined_at) END ELSE NULL END valid_to
 FROM Versions JOIN dbo.crm_members m ON m.property_id='SYNTHETIC_HOTEL_001' AND m.member_no=CONCAT('MEM-',RIGHT(CONCAT('00000000',n),8))
)
INSERT dbo.crm_customer_map(property_id,customer_map_id,member_no,pms_guest_id,pos_customer_ref,facility_user_ref,banquet_customer_id,valid_from,valid_to,mapping_status,mapping_confidence,is_synthetic,source_updated_at)
SELECT 'SYNTHETIC_HOTEL_001','MAP-'+LEFT(CONVERT(varchar(64),HASHBYTES('SHA2_256',CONCAT(member_no,'|',CONVERT(varchar(33),valid_from,126),'|',v)),2),32),member_no,
       CASE WHEN n%100<85 THEN CONCAT('GST-',RIGHT(member_no,8)) END,
       CASE WHEN n%100>=32 THEN CONCAT('POSC-',RIGHT(member_no,8)) END,
       CASE WHEN n%100<30 THEN CONCAT('FACU-',RIGHT(member_no,8)) END,
       CASE WHEN n%100<8 THEN CONCAT('BQC-',RIGHT(member_no,8)) END,
       valid_from,valid_to,CASE WHEN valid_to IS NULL THEN 'ACTIVE' ELSE 'REVOKED' END,
       CAST(CASE WHEN valid_to IS NULL THEN .9950 ELSE .9700 END AS decimal(5,4)),1,DATEADD(hour,1,COALESCE(valid_to,valid_from))
FROM MapBase;
COMMIT;
GO

-- 모든 violation_count는 0이어야 한다.
SELECT 'member_duplicate' check_name,COUNT(*) violation_count FROM (SELECT property_id,member_no FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY property_id,member_no HAVING COUNT(*)>1)x
UNION ALL SELECT 'grade_orphan',COUNT(*) FROM dbo.crm_member_grade_history h LEFT JOIN dbo.crm_members m ON m.property_id=h.property_id AND m.member_no=h.member_no WHERE h.property_id='SYNTHETIC_HOTEL_001' AND m.member_no IS NULL
UNION ALL SELECT 'grade_invalid_period',COUNT(*) FROM dbo.crm_member_grade_history WHERE property_id='SYNTHETIC_HOTEL_001' AND valid_to IS NOT NULL AND valid_from>=valid_to
UNION ALL SELECT 'joined_after_source_update',COUNT(*) FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001' AND joined_at>source_updated_at
UNION ALL SELECT 'point_before_join',COUNT(*) FROM dbo.crm_point_transactions t JOIN dbo.crm_members m ON m.property_id=t.property_id AND m.member_no=t.member_no WHERE t.property_id='SYNTHETIC_HOTEL_001' AND t.event_at<m.joined_at
UNION ALL SELECT 'point_after_source_update',COUNT(*) FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' AND event_at>source_updated_at
UNION ALL SELECT 'future_point',COUNT(*) FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' AND event_at>='2026-07-29'
UNION ALL SELECT 'map_invalid_period',COUNT(*) FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001' AND valid_to IS NOT NULL AND valid_from>=valid_to
UNION ALL SELECT 'map_before_join',COUNT(*) FROM dbo.crm_customer_map x JOIN dbo.crm_members m ON m.property_id=x.property_id AND m.member_no=x.member_no WHERE x.property_id='SYNTHETIC_HOTEL_001' AND x.valid_from<m.joined_at
UNION ALL SELECT 'related_pair_mismatch',COUNT(*) FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' AND ((related_source IS NULL AND related_id IS NOT NULL) OR (related_source IS NOT NULL AND related_id IS NULL))
UNION ALL SELECT 'banquet_related_id_out_of_range',COUNT(*) FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' AND related_source='BANQUET' AND TRY_CONVERT(int,RIGHT(related_id,8))>6000
UNION ALL SELECT 'parent_child_property_mismatch',COUNT(*) FROM dbo.crm_point_transactions t JOIN dbo.crm_members m ON m.member_no=t.member_no WHERE t.property_id='SYNTHETIC_HOTEL_001' AND t.property_id<>m.property_id
UNION ALL SELECT 'prefix_violation',COUNT(*) FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001' AND ((pms_guest_id IS NOT NULL AND pms_guest_id NOT LIKE 'GST-%') OR (pos_customer_ref IS NOT NULL AND pos_customer_ref NOT LIKE 'POSC-%') OR (facility_user_ref IS NOT NULL AND facility_user_ref NOT LIKE 'FACU-%') OR (banquet_customer_id IS NOT NULL AND banquet_customer_id NOT LIKE 'BQC-%'))
UNION ALL SELECT 'global_member_watermark',CASE WHEN COUNT(DISTINCT source_updated_at)>1 THEN 0 ELSE 1 END FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001';

SELECT 'grade_period_overlap' check_name,COUNT(*) violation_count
FROM dbo.crm_member_grade_history a JOIN dbo.crm_member_grade_history b ON a.property_id=b.property_id AND a.member_no=b.member_no AND a.grade_history_id<b.grade_history_id AND a.valid_from<COALESCE(b.valid_to,'9999-12-31') AND b.valid_from<COALESCE(a.valid_to,'9999-12-31')
WHERE a.property_id='SYNTHETIC_HOTEL_001';

SELECT 'current_grade_duplicate' check_name,COUNT(*) violation_count FROM (SELECT member_no FROM dbo.crm_member_grade_history WHERE property_id='SYNTHETIC_HOTEL_001' AND valid_from<'2026-07-27T15:00:00' AND (valid_to IS NULL OR '2026-07-27T15:00:00'<valid_to) GROUP BY member_no HAVING COUNT(*)>1)x;
SELECT 'current_grade_snapshot_mismatch' check_name,COUNT(*) violation_count FROM dbo.crm_members m JOIN dbo.crm_member_grade_history h ON h.property_id=m.property_id AND h.member_no=m.member_no AND h.valid_from<'2026-07-27T15:00:00' AND (h.valid_to IS NULL OR '2026-07-27T15:00:00'<h.valid_to) WHERE m.property_id='SYNTHETIC_HOTEL_001' AND m.membership_grade<>h.grade_code;

-- [valid_from, valid_to) 경계에서 정확히 한 이력만 유효해야 한다.
WITH boundaries AS (
 SELECT property_id,member_no,valid_to boundary_at FROM dbo.crm_member_grade_history
 WHERE property_id='SYNTHETIC_HOTEL_001' AND valid_to IS NOT NULL
), active_count AS (
 SELECT b.member_no,b.boundary_at,COUNT(h.grade_history_id) active_rows
 FROM boundaries b JOIN dbo.crm_member_grade_history h ON h.property_id=b.property_id AND h.member_no=b.member_no
  AND h.valid_from<=b.boundary_at AND (h.valid_to IS NULL OR b.boundary_at<h.valid_to)
 GROUP BY b.member_no,b.boundary_at
)
SELECT 'grade_boundary_half_open_violation' check_name,COUNT(*) violation_count FROM active_count WHERE active_rows<>1;

WITH rb AS (SELECT member_no,event_at,SUM(points_delta) OVER(PARTITION BY member_no ORDER BY event_at,point_txn_id ROWS UNBOUNDED PRECEDING) bal FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001')
SELECT 'negative_running_balance' check_name,COUNT(*) violation_count FROM rb WHERE bal<0;
SELECT 'member_balance_mismatch' check_name,COUNT(*) violation_count FROM dbo.crm_members m JOIN (SELECT member_no,SUM(points_delta) bal FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY member_no)t ON t.member_no=m.member_no WHERE m.property_id='SYNTHETIC_HOTEL_001' AND m.points_balance<>t.bal;

SELECT 'active_map_duplicate' check_name,COUNT(*) violation_count FROM (SELECT member_no FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001' AND mapping_status='ACTIVE' GROUP BY member_no HAVING COUNT(*)>1)x;
SELECT 'local_id_period_overlap' check_name,SUM(v) violation_count FROM (
 SELECT COUNT(*) v FROM dbo.crm_customer_map a JOIN dbo.crm_customer_map b ON a.customer_map_id<b.customer_map_id AND a.property_id=b.property_id AND a.pms_guest_id=b.pms_guest_id AND a.pms_guest_id IS NOT NULL AND a.valid_from<COALESCE(b.valid_to,'9999-12-31') AND b.valid_from<COALESCE(a.valid_to,'9999-12-31') WHERE a.property_id='SYNTHETIC_HOTEL_001'
 UNION ALL SELECT COUNT(*) FROM dbo.crm_customer_map a JOIN dbo.crm_customer_map b ON a.customer_map_id<b.customer_map_id AND a.property_id=b.property_id AND a.pos_customer_ref=b.pos_customer_ref AND a.pos_customer_ref IS NOT NULL AND a.valid_from<COALESCE(b.valid_to,'9999-12-31') AND b.valid_from<COALESCE(a.valid_to,'9999-12-31') WHERE a.property_id='SYNTHETIC_HOTEL_001'
 UNION ALL SELECT COUNT(*) FROM dbo.crm_customer_map a JOIN dbo.crm_customer_map b ON a.customer_map_id<b.customer_map_id AND a.property_id=b.property_id AND a.facility_user_ref=b.facility_user_ref AND a.facility_user_ref IS NOT NULL AND a.valid_from<COALESCE(b.valid_to,'9999-12-31') AND b.valid_from<COALESCE(a.valid_to,'9999-12-31') WHERE a.property_id='SYNTHETIC_HOTEL_001'
 UNION ALL SELECT COUNT(*) FROM dbo.crm_customer_map a JOIN dbo.crm_customer_map b ON a.customer_map_id<b.customer_map_id AND a.property_id=b.property_id AND a.banquet_customer_id=b.banquet_customer_id AND a.banquet_customer_id IS NOT NULL AND a.valid_from<COALESCE(b.valid_to,'9999-12-31') AND b.valid_from<COALESCE(a.valid_to,'9999-12-31') WHERE a.property_id='SYNTHETIC_HOTEL_001'
)x;

SELECT 'grade_transition_fixture_below_100' check_name,
       CASE WHEN SUM(CASE WHEN h.grade_code='GOLD' AND m.membership_grade='SILVER' THEN 1 ELSE 0 END)>=100
                  AND SUM(CASE WHEN h.grade_code='SILVER' AND m.membership_grade='GOLD' THEN 1 ELSE 0 END)>=100 THEN 0 ELSE 1 END violation_count
FROM dbo.crm_members m JOIN dbo.crm_member_grade_history h ON h.property_id=m.property_id AND h.member_no=m.member_no AND h.valid_to IS NOT NULL
WHERE m.property_id='SYNTHETIC_HOTEL_001';

SELECT YEAR(joined_at) yr,data_period_status,is_forecast,COUNT(*) joined_members FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY YEAR(joined_at),data_period_status,is_forecast ORDER BY yr;
SELECT YEAR(event_at) yr,data_period_status,is_forecast,COUNT(*) transactions,SUM(points_delta) net_points FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY YEAR(event_at),data_period_status,is_forecast ORDER BY yr;

SELECT 'crm_members' table_name,COUNT(*) row_count,MAX(source_updated_at) watermark,CONVERT(varchar(64),HASHBYTES('SHA2_256',CONCAT(COUNT(*),'|',MIN(member_no),'|',MAX(member_no),'|',CHECKSUM_AGG(BINARY_CHECKSUM(member_no,membership_grade,points_balance)))),2) checksum FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'crm_member_grade_history',COUNT(*),MAX(source_updated_at),CONVERT(varchar(64),HASHBYTES('SHA2_256',CONCAT(COUNT(*),'|',MIN(grade_history_id),'|',MAX(grade_history_id),'|',CHECKSUM_AGG(BINARY_CHECKSUM(grade_history_id,grade_code,valid_from)))),2) FROM dbo.crm_member_grade_history WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'crm_point_transactions',COUNT(*),MAX(source_updated_at),CONVERT(varchar(64),HASHBYTES('SHA2_256',CONCAT(COUNT(*),'|',MIN(point_txn_id),'|',MAX(point_txn_id),'|',CHECKSUM_AGG(BINARY_CHECKSUM(point_txn_id,points_delta,event_at)))),2) FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'crm_customer_map',COUNT(*),MAX(source_updated_at),CONVERT(varchar(64),HASHBYTES('SHA2_256',CONCAT(COUNT(*),'|',MIN(customer_map_id),'|',MAX(customer_map_id),'|',CHECKSUM_AGG(BINARY_CHECKSUM(customer_map_id,member_no,valid_from)))),2) FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001';
GO
SELECT 20260728 seed,'schema-v4.6-websql' schema_version,'scenario-v4.6' scenario_version,'source-fixture-v4.6' fixture_version,'DB_EXECUTION_RESULT_ABOVE' execution_status;
GO
