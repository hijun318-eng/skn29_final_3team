-- 실행 금지: master 오적재 사실과 exact object 목록을 검토한 뒤 별도 승인으로만 실행한다.
USE [master];
GO
IF SCHEMA_ID(N'walkerhill_v4_3') IS NULL
  THROW 51000,'master.walkerhill_v4_3 does not exist; cleanup target changed',1;

DROP TABLE IF EXISTS [walkerhill_v4_3].[crm_voc_analysis];
DROP TABLE IF EXISTS [walkerhill_v4_3].[crm_voc_reviews];
DROP TABLE IF EXISTS [walkerhill_v4_3].[crm_customer_map];
DROP TABLE IF EXISTS [walkerhill_v4_3].[crm_point_transactions];
DROP TABLE IF EXISTS [walkerhill_v4_3].[crm_member_grade_history];
DROP TABLE IF EXISTS [walkerhill_v4_3].[crm_members];
DROP TABLE IF EXISTS [walkerhill_v4_3].[crm_membership_tiers];
DROP FUNCTION IF EXISTS [walkerhill_v4_3].[v43_journey_pos_eligible_amount];
DROP FUNCTION IF EXISTS [walkerhill_v4_3].[v43_u01];

IF EXISTS (SELECT 1 FROM sys.objects WHERE schema_id=SCHEMA_ID(N'walkerhill_v4_3'))
  THROW 51000,'unexpected objects remain in master.walkerhill_v4_3',1;
DROP SCHEMA [walkerhill_v4_3];
GO
