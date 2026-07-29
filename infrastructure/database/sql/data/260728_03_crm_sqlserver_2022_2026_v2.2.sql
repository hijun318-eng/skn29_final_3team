-- CRM deterministic synthetic load v2.2
-- seed=20260729; schema_version=1.0.0; scenario_version=1.0.0
-- fixture_version=1.0.0; synthetic=true; property_id=SYNTHETIC_HOTEL_001
USE crm_db;
GO
SET XACT_ABORT ON;
SET NOCOUNT ON;
SET DATEFORMAT ymd;
SET LANGUAGE us_english;
SET LOCK_TIMEOUT 30000;
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET ARITHABORT ON;
SET NUMERIC_ROUNDABORT OFF;

BEGIN TRANSACTION;

IF EXISTS (SELECT 1 FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
   OR EXISTS (SELECT 1 FROM dbo.crm_member_grade_history WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
   OR EXISTS (SELECT 1 FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
   OR EXISTS (SELECT 1 FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
    THROW 51000, 'SCHEMA_CONTRACT_MISMATCH', 1;

DELETE FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001';
DELETE FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001';
DELETE FROM dbo.crm_member_grade_history WHERE property_id='SYNTHETIC_HOTEL_001';
DELETE FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001';

WITH digits(d) AS (
    SELECT d FROM (VALUES(0),(1),(2),(3),(4),(5),(6),(7),(8),(9)) v(d)
),
seq AS (
    SELECT TOP (80000)
           1 + a.d + 10*b.d + 100*c.d + 1000*d.d + 10000*e.d AS n
    FROM digits a CROSS JOIN digits b CROSS JOIN digits c
    CROSS JOIN digits d CROSS JOIN digits e
    ORDER BY n
),
members AS (
    SELECT n,
           CONCAT('MEM-',RIGHT(CONCAT('00000000',n),8)) member_no,
           DATEADD(day,n%730,CONVERT(datetime2(3),'2022-01-01T00:00:00',126)) joined_at,
           CASE WHEN n<=200 THEN 'SILVER'
                WHEN n<=400 THEN 'GOLD'
                WHEN n%4=0 THEN 'VIP'
                WHEN n%4=1 THEN 'GOLD'
                WHEN n%4=2 THEN 'SILVER'
                ELSE 'BASIC' END membership_grade
    FROM seq
)
INSERT INTO dbo.crm_members (
    property_id,member_no,membership_grade,points_balance,joined_at,member_status,
    data_period_status,is_forecast,is_synthetic,source_updated_at
)
SELECT 'SYNTHETIC_HOTEL_001',member_no,membership_grade,1200,joined_at,'ACTIVE',
       CASE WHEN joined_at<'2025-01-01' THEN 'REFERENCE_CALIBRATED'
            WHEN joined_at<'2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE'
            ELSE 'YTD_SYNTHETIC' END,
       0,1,CONVERT(datetime2(3),'2026-07-28T05:00:00',126)
FROM members;

WITH first_history AS (
    SELECT member_no,joined_at,
           CASE WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=200 THEN 'GOLD'
                WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=400 THEN 'SILVER'
                WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=40000 THEN 'BASIC'
                ELSE membership_grade END grade_code,
           CASE WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=40000
                THEN DATEADD(day,365,joined_at) END valid_to
    FROM dbo.crm_members
    WHERE property_id='SYNTHETIC_HOTEL_001'
),
second_history AS (
    SELECT member_no,DATEADD(day,365,joined_at) valid_from,membership_grade grade_code
    FROM dbo.crm_members
    WHERE property_id='SYNTHETIC_HOTEL_001'
      AND TRY_CONVERT(int,RIGHT(member_no,8))<=40000
),
all_history AS (
    SELECT member_no,joined_at valid_from,valid_to,grade_code,
           CASE WHEN valid_to IS NULL THEN 'JOIN' ELSE 'REVIEW' END reason
    FROM first_history
    UNION ALL
    SELECT member_no,valid_from,NULL,grade_code,
           CASE WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=200 THEN 'DOWNGRADE'
                WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=400 THEN 'UPGRADE'
                ELSE 'REVIEW' END
    FROM second_history
)
INSERT INTO dbo.crm_member_grade_history (
    property_id,grade_history_id,member_no,grade_code,valid_from,valid_to,
    change_reason_code,is_synthetic,source_updated_at
)
SELECT 'SYNTHETIC_HOTEL_001',
       CONCAT('GRD-',SUBSTRING(CONVERT(varchar(64),HASHBYTES('SHA2_256',
              CONCAT('SYNTHETIC_HOTEL_001|',member_no,'|',CONVERT(varchar(33),valid_from,126),'|',grade_code)),2),1,32)),
       member_no,grade_code,valid_from,valid_to,reason,1,
       CONVERT(datetime2(3),'2026-07-28T05:00:00',126)
FROM all_history;

WITH txns AS (
    SELECT m.member_no,m.joined_at,v.txn_seq,v.txn_type,v.points_delta
    FROM dbo.crm_members m
    CROSS JOIN (VALUES
        (1,'EARN',1000),(2,'USE',-200),(3,'EARN',500),(4,'EXPIRE',-100)
    ) v(txn_seq,txn_type,points_delta)
    WHERE m.property_id='SYNTHETIC_HOTEL_001'
)
INSERT INTO dbo.crm_point_transactions (
    property_id,point_txn_id,member_no,event_at,txn_type,points_delta,
    related_source,related_id,data_period_status,is_forecast,is_synthetic,source_updated_at
)
SELECT 'SYNTHETIC_HOTEL_001',
       CONCAT('PTX-',SUBSTRING(CONVERT(varchar(64),HASHBYTES('SHA2_256',
              CONCAT('SYNTHETIC_HOTEL_001|',member_no,'|',txn_seq)),2),1,32)),
       member_no,DATEADD(day,txn_seq*30,joined_at),txn_type,points_delta,
       CASE txn_seq WHEN 1 THEN 'PMS' WHEN 2 THEN 'POS' WHEN 3 THEN 'FACILITY' ELSE 'BANQUET' END,
       CONCAT('SYN-',RIGHT(member_no,8),'-',txn_seq),
       CASE WHEN DATEADD(day,txn_seq*30,joined_at)<'2025-01-01' THEN 'REFERENCE_CALIBRATED'
            WHEN DATEADD(day,txn_seq*30,joined_at)<'2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE'
            ELSE 'YTD_SYNTHETIC' END,
       0,1,DATEADD(hour,1,DATEADD(day,txn_seq*30,joined_at))
FROM txns;

INSERT INTO dbo.crm_customer_map (
    property_id,customer_map_id,member_no,pms_guest_id,pos_customer_ref,
    facility_user_ref,banquet_customer_id,valid_from,valid_to,mapping_status,
    mapping_confidence,is_synthetic,source_updated_at
)
SELECT 'SYNTHETIC_HOTEL_001',
       CONCAT('MAP-',SUBSTRING(CONVERT(varchar(64),HASHBYTES('SHA2_256',
              CONCAT('SYNTHETIC_HOTEL_001|',member_no,'|ACTIVE')),2),1,32)),
       member_no,
       CASE WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=68000 THEN CONCAT('GST-',RIGHT(member_no,8)) END,
       CASE WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=54400 THEN CONCAT('POSC-',RIGHT(member_no,8)) END,
       CASE WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=24000 THEN CONCAT('FACU-',RIGHT(member_no,8)) END,
       CASE WHEN TRY_CONVERT(int,RIGHT(member_no,8))<=6400 THEN CONCAT('BQC-',RIGHT(member_no,8)) END,
       joined_at,NULL,'ACTIVE',CONVERT(decimal(5,4),0.9900),1,
       CONVERT(datetime2(3),'2026-07-28T05:00:00',126)
FROM dbo.crm_members
WHERE property_id='SYNTHETIC_HOTEL_001';

COMMIT;

SELECT 'crm_members' table_name,COUNT_BIG(*) row_count,MAX(source_updated_at) watermark,
       CHECKSUM_AGG(BINARY_CHECKSUM(member_no,membership_grade,points_balance)) checksum
FROM dbo.crm_members WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'crm_member_grade_history',COUNT_BIG(*),MAX(source_updated_at),
       CHECKSUM_AGG(BINARY_CHECKSUM(grade_history_id,grade_code))
FROM dbo.crm_member_grade_history WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'crm_point_transactions',COUNT_BIG(*),MAX(source_updated_at),
       CHECKSUM_AGG(BINARY_CHECKSUM(point_txn_id,points_delta))
FROM dbo.crm_point_transactions WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'crm_customer_map',COUNT_BIG(*),MAX(source_updated_at),
       CHECKSUM_AGG(BINARY_CHECKSUM(customer_map_id,member_no))
FROM dbo.crm_customer_map WHERE property_id='SYNTHETIC_HOTEL_001';
GO
