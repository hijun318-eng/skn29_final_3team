USE [crm_db];
GO
-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=SQL Server 2022; database=crm_db; schema=walkerhill_v4_3
-- domain=CRM; script_type=SEED; execution_order=20; expected_rows=150003
-- dependency=10_sqlserver_crm_ddl.sql; period=2024-01-01..2026-08-31; base_seed=20260814
-- runtime_estimate=1-3 minutes; execution_default=NOT_RUN; rerunnable=false
-- official_anchor=public tier names only; all member counts and behavior are synthetic assumptions

SET NOCOUNT ON;
IF EXISTS(SELECT 1 FROM [walkerhill_v4_3].[crm_membership_tiers]) OR EXISTS(SELECT 1 FROM [walkerhill_v4_3].[crm_members])
  THROW 51000,'candidate CRM tier and member tables must be empty',1;
INSERT [walkerhill_v4_3].[crm_membership_tiers]
  (tier_code,public_name,synthetic_rank,source_url,provenance_class,is_active)
VALUES
 ('CLASSIC',N'Classic',1,N'https://www.walkerhill.com/en/membership/Rewards','OFFICIAL_NAME_SYNTHETIC_RULE',1),
 ('PLUS',N'Plus',2,N'https://www.walkerhill.com/en/membership/Rewards','OFFICIAL_NAME_SYNTHETIC_RULE',1),
 ('PREMIER',N'Premier',3,N'https://www.walkerhill.com/en/membership/Rewards','OFFICIAL_NAME_SYNTHETIC_RULE',1);

;WITH n AS (
  SELECT 1 AS i UNION ALL SELECT i+1 FROM n WHERE i<150000
), ranked AS (
  SELECT i,ROW_NUMBER() OVER(ORDER BY [walkerhill_v4_3].[v43_u01](CONCAT('tier-rank|',i)),i) AS tier_rank
  FROM n
)
INSERT [walkerhill_v4_3].[crm_members]
  (member_no,joined_at,current_tier_code,member_status,points_balance,is_synthetic)
SELECT CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),i),9)),
       TODATETIMEOFFSET(DATEADD(second,CONVERT(int,FLOOR([walkerhill_v4_3].[v43_u01](CONCAT('join|',i))*94607999)),CONVERT(datetime2,'2021-01-01T00:00:00')), '+09:00'),
       CASE WHEN tier_rank<=108000 THEN 'CLASSIC' WHEN tier_rank<=142500 THEN 'PLUS' ELSE 'PREMIER' END,
       CASE WHEN [walkerhill_v4_3].[v43_u01](CONCAT('status|',i))<0.93 THEN 'ACTIVE'
            WHEN [walkerhill_v4_3].[v43_u01](CONCAT('status|',i))<0.985 THEN 'DORMANT' ELSE 'WITHDRAWN' END,
       0,1
FROM ranked OPTION (MAXRECURSION 0);
GO
