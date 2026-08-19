USE [crm_db];
GO
-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=SQL Server 2022; domain=CRM; script_type=SEED; execution_order=32
-- expected_rows=110000; dependency=20_sqlserver_crm_tier_member_seed.sql; execution_default=NOT_RUN
-- privacy=no name, email, phone, address or actual identifier is generated

SET NOCOUNT ON;
IF EXISTS(SELECT 1 FROM [walkerhill_v4_3].[crm_customer_map])
  THROW 51000,'candidate CRM customer map table must be empty',1;
;WITH n AS (SELECT 1 i UNION ALL SELECT i+1 FROM n WHERE i<110000)
INSERT [walkerhill_v4_3].[crm_customer_map]
 (customer_map_id,member_no,pms_guest_id,pos_customer_ref,facility_user_ref,banquet_customer_id,
  valid_from,valid_to,mapping_status,mapping_confidence,is_synthetic)
SELECT CONCAT('CM_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),i),9)),
       CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),i),9)),
       CASE WHEN i<=100000 THEN CONCAT('G',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),i),9)) END,
       CASE WHEN i<=75000 THEN CONCAT('C',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),i),9)) END,
       CONCAT('FUSR_',RIGHT(REPLICATE('0',8)+CONVERT(varchar(8),i),8)),
       CASE WHEN i<=100000 THEN CONCAT('B',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),i),9)) END,
       TODATETIMEOFFSET(CONVERT(datetime2,'2024-01-01T00:00:00'),'+09:00'),NULL,'ACTIVE',
       CONVERT(decimal(5,4),0.8500+[walkerhill_v4_3].[v43_u01](CONCAT('map-confidence|',i))*0.1499),1
FROM n OPTION (MAXRECURSION 0);
GO
