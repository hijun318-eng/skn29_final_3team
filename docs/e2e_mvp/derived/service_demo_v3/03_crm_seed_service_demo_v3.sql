USE crm_db;
SET ANSI_NULLS ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET QUOTED_IDENTIFIER ON;
SET NUMERIC_ROUNDABORT OFF;
SET NOCOUNT ON;
;WITH d AS (SELECT TOP (13500) ROW_NUMBER() OVER(ORDER BY (SELECT NULL)) n FROM sys.all_objects a CROSS JOIN sys.all_objects b)
INSERT INTO dbo.crm_members(property_id,member_no,membership_grade,points_balance,joined_at,member_status,data_period_status,is_forecast,is_synthetic,source_updated_at)
SELECT 'SYNTHETIC_HOTEL_001',CONCAT('CM-',RIGHT(CONCAT('00000000',n),8)),CASE WHEN n%29=0 THEN 'VIP' WHEN n%7=0 THEN 'GOLD' WHEN n%3=0 THEN 'SILVER' ELSE 'BASIC' END,100+((n*97+n*n)%120000),DATEADD(day,-(30+(n*37+n*n)%1600),CONVERT(datetime2(3),'2026-08-01')),CASE WHEN n%97=0 THEN 'INACTIVE' ELSE 'ACTIVE' END,'SYNTHETIC_ACTUAL_LIKE',0,1,CONVERT(datetime2(3),'2026-08-01') FROM d;
;WITH d AS (SELECT TOP (11475) ROW_NUMBER() OVER(ORDER BY (SELECT NULL)) n FROM sys.all_objects a CROSS JOIN sys.all_objects b)
INSERT INTO dbo.crm_customer_map(property_id,customer_map_id,member_no,pms_guest_id,pos_customer_ref,facility_user_ref,banquet_customer_id,valid_from,valid_to,mapping_status,mapping_confidence,is_synthetic,source_updated_at)
SELECT 'SYNTHETIC_HOTEL_001',CONCAT('MAP-',RIGHT(CONCAT('00000000',n),8)),CONCAT('CM-',RIGHT(CONCAT('00000000',n),8)),CONCAT('PG-',RIGHT(CONCAT('00000000',n),8)),CONCAT('PC-',RIGHT(CONCAT('00000000',n),8)),CONCAT('FU-',RIGHT(CONCAT('00000000',n),8)),CONCAT('BC-',RIGHT(CONCAT('00000000',n),8)),CONVERT(datetime2(3),'2025-01-01'),NULL,'ACTIVE',0.9900,1,CONVERT(datetime2(3),'2026-08-01') FROM d;
-- crm_member_grade_history 및 crm_point_transactions는 다음 FILE_GENERATION 단계에서 DDL 열 목록 정적 대조 후 추가한다.
;WITH d AS (SELECT TOP (13500) ROW_NUMBER() OVER(ORDER BY (SELECT NULL)) n FROM sys.all_objects a CROSS JOIN sys.all_objects b)
INSERT INTO dbo.crm_member_grade_history(property_id,grade_history_id,member_no,grade_code,valid_from,valid_to,change_reason_code,is_synthetic,source_updated_at)
SELECT 'SYNTHETIC_HOTEL_001',CONCAT('GH-',RIGHT(CONCAT('00000000',n),8)),CONCAT('CM-',RIGHT(CONCAT('00000000',n),8)),CASE WHEN n%29=0 THEN 'VIP' WHEN n%7=0 THEN 'GOLD' WHEN n%3=0 THEN 'SILVER' ELSE 'BASIC' END,CONVERT(datetime2(3),'2025-01-01'),NULL,'INITIAL_LOAD',1,CONVERT(datetime2(3),'2026-08-01') FROM d;
;WITH d AS (SELECT TOP (45000) ROW_NUMBER() OVER(ORDER BY (SELECT NULL)) n FROM sys.all_objects a CROSS JOIN sys.all_objects b)
INSERT INTO dbo.crm_point_transactions(property_id,point_txn_id,member_no,event_at,txn_type,points_delta,related_source,related_id,data_period_status,is_forecast,is_synthetic,source_updated_at)
SELECT 'SYNTHETIC_HOTEL_001',CONCAT('PT-',RIGHT(CONCAT('00000000',n),8)),CONCAT('CM-',RIGHT(CONCAT('00000000',1+((n*7919)%13500)),8)),DATEADD(minute,(n*137)%830880,CONVERT(datetime2(3),'2025-01-01')),CASE WHEN n%13=0 THEN 'EXPIRE' WHEN n%5=0 THEN 'USE' ELSE 'EARN' END,CASE WHEN n%13=0 THEN -50-(n%200) WHEN n%5=0 THEN -100-(n%500) ELSE 100+(n%1000) END,CASE WHEN n%3=0 THEN 'PMS' WHEN n%3=1 THEN 'POS' ELSE 'BANQUET' END,CONCAT('SRC-',RIGHT(CONCAT('00000000',n),8)),'SYNTHETIC_ACTUAL_LIKE',0,1,CONVERT(datetime2(3),'2026-08-01') FROM d;
