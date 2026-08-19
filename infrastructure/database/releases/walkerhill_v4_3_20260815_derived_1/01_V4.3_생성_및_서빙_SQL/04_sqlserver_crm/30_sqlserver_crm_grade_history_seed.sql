USE [crm_db];
GO
-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=SQL Server 2022; domain=CRM; script_type=SEED; execution_order=30
-- expected_rows=192000; dependency=20_sqlserver_crm_tier_member_seed.sql; execution_default=NOT_RUN
-- realism_rule=all members receive a join history; 42,000 deterministic members receive one synthetic upgrade

SET NOCOUNT ON;
IF EXISTS(SELECT 1 FROM [walkerhill_v4_3].[crm_member_grade_history])
  THROW 51000,'candidate CRM grade history table must be empty',1;
INSERT [walkerhill_v4_3].[crm_member_grade_history]
  (grade_history_id,member_no,tier_code,valid_from,valid_to,change_reason,is_synthetic)
SELECT CONCAT('GH_JOIN_',member_no),member_no,'CLASSIC',joined_at,
       CASE WHEN current_tier_code='CLASSIC' THEN NULL
            ELSE DATEADD(day,180+CONVERT(int,FLOOR([walkerhill_v4_3].[v43_u01](CONCAT('upgrade-day|',member_no))*360)),joined_at) END,
       'JOIN',1
FROM [walkerhill_v4_3].[crm_members];

;WITH upgrade_members AS (
  SELECT TOP (42000) member_no,joined_at,current_tier_code,
         DATEADD(day,180+CONVERT(int,FLOOR([walkerhill_v4_3].[v43_u01](CONCAT('upgrade-day|',member_no))*360)),joined_at) AS upgraded_at
  FROM [walkerhill_v4_3].[crm_members]
  WHERE current_tier_code<>'CLASSIC'
  ORDER BY [walkerhill_v4_3].[v43_u01](CONCAT('upgrade-pick|',member_no)),member_no
)
INSERT [walkerhill_v4_3].[crm_member_grade_history]
  (grade_history_id,member_no,tier_code,valid_from,valid_to,change_reason,is_synthetic)
SELECT CONCAT('GH_UP_',member_no),member_no,current_tier_code,upgraded_at,NULL,'ANNUAL_SPEND',1
FROM upgrade_members;
GO
