-- ============================================================================
-- Answervice 팀공유 SQL 산출물
-- ownership_contract=team-ownership-v2.1
-- schema_version=schema-v4.6-websql
-- snapshot_as_of_at=2026-07-28T05:00:00Z
-- generation_as_of_at=2026-07-28T05:00:00Z
-- evaluation_as_of=2026-07-28T14:00:00+09:00
-- GENERATE_FILES=true / RUN_STATIC_VALIDATION=true / EXECUTE_DB=false
-- 접속정보·healthy 컨테이너는 실행 승인으로 간주하지 않는다.
-- 실제 실행 전 해당 owner의 approval_id가 필요하다.
-- ============================================================================
-- owner=R2_정승
-- work_card=R2-DB
-- output=260729_03_hotel_crm_sqlserver_ddl.sql

-- ============================================================================
-- 260729_03_hotel_crm_sqlserver_ddl.sql
-- Answervice CRM schema contract v4.6
-- SQL Server 2022 / sqlcmd 또는 SSMS
-- source_id=crm
-- engine=SQL Server
-- database/schema=hotel_crm/dbo
-- ingestion_role=crm_ingest
-- query_role=crm_query
-- datahub_platform_instance=hotel_crm
-- trino_catalog=crm
-- schema_version=schema-v4.6-websql
-- ============================================================================
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET DATEFORMAT ymd;
SET LANGUAGE us_english;
SET LOCK_TIMEOUT 30000;
GO

IF DB_ID(N'hotel_crm') IS NULL
  EXEC(N'CREATE DATABASE hotel_crm');
GO
USE hotel_crm;
GO

CREATE OR ALTER PROCEDURE dbo.answervice_assert_table_contract_v46
  @table_name sysname,
  @expected nvarchar(max)
AS
BEGIN
  SET NOCOUNT ON;
  IF OBJECT_ID(QUOTENAME(N'dbo') + N'.' + QUOTENAME(@table_name), N'U') IS NULL RETURN;

  DECLARE @actual nvarchar(max);
  SELECT @actual = STRING_AGG(
    CONCAT(
      c.name, N':',
      LOWER(CASE
        WHEN t.name IN (N'varchar',N'char') THEN CONCAT(t.name,N'(',c.max_length,N')')
        WHEN t.name IN (N'nvarchar',N'nchar') THEN CONCAT(t.name,N'(',c.max_length/2,N')')
        WHEN t.name IN (N'decimal',N'numeric') THEN CONCAT(t.name,N'(',c.precision,N',',c.scale,N')')
        WHEN t.name IN (N'datetime2',N'time') THEN CONCAT(t.name,N'(',c.scale,N')')
        ELSE t.name END),
      N':', c.is_nullable
    ), N'|'
  ) WITHIN GROUP (ORDER BY c.column_id)
  FROM sys.columns c
  JOIN sys.types t ON t.user_type_id=c.user_type_id
  WHERE c.object_id=OBJECT_ID(QUOTENAME(N'dbo') + N'.' + QUOTENAME(@table_name));

  IF BINARY_CHECKSUM(@actual) <> BINARY_CHECKSUM(@expected) OR @actual <> @expected
    THROW 51000, 'SCHEMA_CONTRACT_MISMATCH: existing SQL Server table columns differ', 1;
END;
GO

EXEC dbo.answervice_assert_table_contract_v46 @table_name=N'crm_members', @expected=N'property_id:varchar(64):0|member_no:varchar(36):0|membership_grade:varchar(16):0|points_balance:integer:0|joined_at:datetime2(3):0|member_status:varchar(16):0|data_period_status:varchar(32):0|is_forecast:bit:0|is_synthetic:bit:0|source_updated_at:datetime2(3):0';
GO

IF OBJECT_ID(N'dbo.crm_members',N'U') IS NULL
BEGIN
  CREATE TABLE [dbo].[crm_members] (
    [property_id] varchar(64) NOT NULL,
    [member_no] varchar(36) NOT NULL,
    [membership_grade] varchar(16) NOT NULL,
    [points_balance] integer NOT NULL,
    [joined_at] datetime2(3) NOT NULL,
    [member_status] varchar(16) NOT NULL,
    [data_period_status] varchar(32) NOT NULL,
    [is_forecast] bit NOT NULL,
    [is_synthetic] bit NOT NULL,
    [source_updated_at] datetime2(3) NOT NULL,
    CONSTRAINT [pk_crm_members] PRIMARY KEY ([member_no]),
    CONSTRAINT [uq_crm_members_property_id_member_no] UNIQUE ([property_id], [member_no]),
    CONSTRAINT [ck_crm_members_1] CHECK ([membership_grade] IN ('BASIC','SILVER','GOLD','VIP')),
    CONSTRAINT [ck_crm_members_2] CHECK ([points_balance] >= 0),
    CONSTRAINT [ck_crm_members_3] CHECK ([member_status] IN ('ACTIVE','INACTIVE','REVOKED')),
    CONSTRAINT [ck_crm_members_4] CHECK ([joined_at] <= [source_updated_at]),
    CONSTRAINT [ck_crm_members_5] CHECK ([is_synthetic]=1),
    CONSTRAINT [ck_crm_members_6] CHECK ([data_period_status] IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    CONSTRAINT [ck_crm_members_7] CHECK (([is_forecast]=CASE WHEN [data_period_status]='FORECAST_SCENARIO' THEN 1 ELSE 0 END)),
    CONSTRAINT [ck_crm_members_8] CHECK ((([joined_at] >= CONVERT(datetime2(3),'2022-01-01T00:00:00.000',126) AND [joined_at] < CONVERT(datetime2(3),'2025-01-01T00:00:00.000',126) AND [data_period_status]='REFERENCE_CALIBRATED') OR ([joined_at] >= CONVERT(datetime2(3),'2025-01-01T00:00:00.000',126) AND [joined_at] < CONVERT(datetime2(3),'2026-01-01T00:00:00.000',126) AND [data_period_status]='SYNTHETIC_ACTUAL_LIKE') OR ([joined_at] >= CONVERT(datetime2(3),'2026-01-01T00:00:00.000',126) AND [joined_at] < CONVERT(datetime2(3),'2026-07-29T00:00:00.000',126) AND [data_period_status]='YTD_SYNTHETIC') OR ([joined_at] >= CONVERT(datetime2(3),'2026-07-29T00:00:00.000',126) AND [joined_at] < CONVERT(datetime2(3),'2027-01-01T00:00:00.000',126) AND [data_period_status]='FORECAST_SCENARIO')))
  );
END;
GO

IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND ep.minor_id=0 AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'합성 멤버십 회원 1건',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'property_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'property_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'member_no' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'회원 번호. MEM-8자리 합성 키 [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'member_no';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'membership_grade' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'멤버십 등급. BASIC/SILVER/GOLD/VIP [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'membership_grade';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'points_balance' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'포인트 잔액. 0 이상 [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'points_balance';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'joined_at' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'가입 시각.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'joined_at';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'member_status' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'상태. ACTIVE/INACTIVE/REVOKED [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'member_status';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'data_period_status' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'기간 상태. 가입 시점 상태 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'data_period_status';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'is_forecast' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'전망 여부. 2026-07 이후 true [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'is_forecast';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'is_synthetic' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'합성 여부. 항상 1 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'is_synthetic';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_members') AND c.name=N'source_updated_at' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'원천 수정시각. watermark [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_members',
    @level2type=N'COLUMN', @level2name=N'source_updated_at';
GO

EXEC dbo.answervice_assert_table_contract_v46 @table_name=N'crm_member_grade_history', @expected=N'property_id:varchar(64):0|grade_history_id:varchar(36):0|member_no:varchar(36):0|grade_code:varchar(16):0|valid_from:datetime2(3):0|valid_to:datetime2(3):1|change_reason_code:varchar(24):0|is_synthetic:bit:0|source_updated_at:datetime2(3):0';
GO

IF OBJECT_ID(N'dbo.crm_member_grade_history',N'U') IS NULL
BEGIN
  CREATE TABLE [dbo].[crm_member_grade_history] (
    [property_id] varchar(64) NOT NULL,
    [grade_history_id] varchar(36) NOT NULL,
    [member_no] varchar(36) NOT NULL,
    [grade_code] varchar(16) NOT NULL,
    [valid_from] datetime2(3) NOT NULL,
    [valid_to] datetime2(3),
    [change_reason_code] varchar(24) NOT NULL,
    [is_synthetic] bit NOT NULL,
    [source_updated_at] datetime2(3) NOT NULL,
    CONSTRAINT [pk_crm_member_grade_history] PRIMARY KEY ([grade_history_id]),
    CONSTRAINT [uq_crm_member_grade_history_property_id_grade__0772b390] UNIQUE ([property_id], [grade_history_id]),
    CONSTRAINT [ck_crm_member_grade_history_1] CHECK ([grade_code] IN ('BASIC','SILVER','GOLD','VIP')),
    CONSTRAINT [ck_crm_member_grade_history_2] CHECK ([change_reason_code] IN ('JOIN','UPGRADE','DOWNGRADE','REVIEW')),
    CONSTRAINT [ck_crm_member_grade_history_3] CHECK (([valid_to] IS NULL OR [valid_from] < [valid_to])),
    CONSTRAINT [ck_crm_member_grade_history_4] CHECK ([source_updated_at] >= [valid_from]),
    CONSTRAINT [ck_crm_member_grade_history_5] CHECK (([valid_to] IS NULL OR [source_updated_at] >= [valid_to])),
    CONSTRAINT [ck_crm_member_grade_history_6] CHECK ([is_synthetic]=1),
    CONSTRAINT [fk_crm_member_grade_history_member] FOREIGN KEY ([property_id],[member_no]) REFERENCES [dbo].[crm_members]([property_id],[member_no])
  );
END;
GO

IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND ep.minor_id=0 AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'회원별 멤버십 등급 유효기간 1건',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND c.name=N'property_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history',
    @level2type=N'COLUMN', @level2name=N'property_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND c.name=N'grade_history_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'등급 이력 ID. 안정 관계 PK [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history',
    @level2type=N'COLUMN', @level2name=N'grade_history_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND c.name=N'member_no' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'회원 번호.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history',
    @level2type=N'COLUMN', @level2name=N'member_no';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND c.name=N'grade_code' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'멤버십 등급. BASIC/SILVER/GOLD/VIP [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history',
    @level2type=N'COLUMN', @level2name=N'grade_code';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND c.name=N'valid_from' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'유효 시작. inclusive [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history',
    @level2type=N'COLUMN', @level2name=N'valid_from';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND c.name=N'valid_to' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'유효 종료. exclusive, NULL은 현재 유효 [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history',
    @level2type=N'COLUMN', @level2name=N'valid_to';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND c.name=N'change_reason_code' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'변경 사유 코드. JOIN/UPGRADE/DOWNGRADE/REVIEW [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history',
    @level2type=N'COLUMN', @level2name=N'change_reason_code';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND c.name=N'is_synthetic' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'합성 여부. 항상 1 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history',
    @level2type=N'COLUMN', @level2name=N'is_synthetic';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND c.name=N'source_updated_at' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'원천 수정시각. watermark [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_member_grade_history',
    @level2type=N'COLUMN', @level2name=N'source_updated_at';
GO

EXEC dbo.answervice_assert_table_contract_v46 @table_name=N'crm_point_transactions', @expected=N'property_id:varchar(64):0|point_txn_id:varchar(36):0|member_no:varchar(36):0|event_at:datetime2(3):0|txn_type:varchar(16):0|points_delta:integer:0|related_source:varchar(16):1|related_id:varchar(36):1|data_period_status:varchar(32):0|is_forecast:bit:0|is_synthetic:bit:0|source_updated_at:datetime2(3):0';
GO

IF OBJECT_ID(N'dbo.crm_point_transactions',N'U') IS NULL
BEGIN
  CREATE TABLE [dbo].[crm_point_transactions] (
    [property_id] varchar(64) NOT NULL,
    [point_txn_id] varchar(36) NOT NULL,
    [member_no] varchar(36) NOT NULL,
    [event_at] datetime2(3) NOT NULL,
    [txn_type] varchar(16) NOT NULL,
    [points_delta] integer NOT NULL,
    [related_source] varchar(16),
    [related_id] varchar(36),
    [data_period_status] varchar(32) NOT NULL,
    [is_forecast] bit NOT NULL,
    [is_synthetic] bit NOT NULL,
    [source_updated_at] datetime2(3) NOT NULL,
    CONSTRAINT [pk_crm_point_transactions] PRIMARY KEY ([point_txn_id]),
    CONSTRAINT [uq_crm_point_transactions_property_id_point_txn_id] UNIQUE ([property_id], [point_txn_id]),
    CONSTRAINT [ck_crm_point_transactions_1] CHECK ([txn_type] IN ('EARN','USE','EXPIRE','ADJUST')),
    CONSTRAINT [ck_crm_point_transactions_2] CHECK (([related_source] IS NULL OR [related_source] IN ('PMS','POS','FACILITY','BANQUET'))),
    CONSTRAINT [ck_crm_point_transactions_3] CHECK ((([txn_type]='EARN' AND [points_delta]>0) OR ([txn_type] IN ('USE','EXPIRE') AND [points_delta]<0) OR ([txn_type]='ADJUST' AND [points_delta]<>0))),
    CONSTRAINT [ck_crm_point_transactions_4] CHECK ([event_at] <= [source_updated_at]),
    CONSTRAINT [ck_crm_point_transactions_5] CHECK ([is_synthetic]=1),
    CONSTRAINT [ck_crm_point_transactions_6] CHECK ([data_period_status] IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    CONSTRAINT [ck_crm_point_transactions_7] CHECK (([is_forecast]=CASE WHEN [data_period_status]='FORECAST_SCENARIO' THEN 1 ELSE 0 END)),
    CONSTRAINT [ck_crm_point_transactions_8] CHECK ((([event_at] >= CONVERT(datetime2(3),'2022-01-01T00:00:00.000',126) AND [event_at] < CONVERT(datetime2(3),'2025-01-01T00:00:00.000',126) AND [data_period_status]='REFERENCE_CALIBRATED') OR ([event_at] >= CONVERT(datetime2(3),'2025-01-01T00:00:00.000',126) AND [event_at] < CONVERT(datetime2(3),'2026-01-01T00:00:00.000',126) AND [data_period_status]='SYNTHETIC_ACTUAL_LIKE') OR ([event_at] >= CONVERT(datetime2(3),'2026-01-01T00:00:00.000',126) AND [event_at] < CONVERT(datetime2(3),'2026-07-29T00:00:00.000',126) AND [data_period_status]='YTD_SYNTHETIC') OR ([event_at] >= CONVERT(datetime2(3),'2026-07-29T00:00:00.000',126) AND [event_at] < CONVERT(datetime2(3),'2027-01-01T00:00:00.000',126) AND [data_period_status]='FORECAST_SCENARIO'))),
    CONSTRAINT [fk_crm_point_transactions_member] FOREIGN KEY ([property_id],[member_no]) REFERENCES [dbo].[crm_members]([property_id],[member_no])
  );
END;
GO

IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND ep.minor_id=0 AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'합성 포인트 거래 1건',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'property_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'property_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'point_txn_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'포인트 거래 ID. PK [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'point_txn_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'member_no' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'회원 번호.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'member_no';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'event_at' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'거래 시각.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'event_at';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'txn_type' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'거래 유형. EARN/USE/EXPIRE/ADJUST [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'txn_type';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'points_delta' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'포인트 증감.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'points_delta';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'related_source' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'연관 소스. PMS/POS/FACILITY/BANQUET [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'related_source';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'related_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'연관 거래 ID.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'related_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'data_period_status' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'기간 상태. 4개 고정 상태 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'data_period_status';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'is_forecast' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'전망 여부. 2026-07 이후 true [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'is_forecast';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'is_synthetic' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'합성 여부. 항상 1 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'is_synthetic';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_point_transactions') AND c.name=N'source_updated_at' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'원천 수정시각. watermark [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_point_transactions',
    @level2type=N'COLUMN', @level2name=N'source_updated_at';
GO

EXEC dbo.answervice_assert_table_contract_v46 @table_name=N'crm_customer_map', @expected=N'property_id:varchar(64):0|customer_map_id:varchar(36):0|member_no:varchar(36):0|pms_guest_id:varchar(36):1|pos_customer_ref:varchar(36):1|facility_user_ref:varchar(36):1|banquet_customer_id:varchar(36):1|valid_from:datetime2(3):0|valid_to:datetime2(3):1|mapping_status:varchar(16):0|mapping_confidence:decimal(5,4):0|is_synthetic:bit:0|source_updated_at:datetime2(3):0';
GO

IF OBJECT_ID(N'dbo.crm_customer_map',N'U') IS NULL
BEGIN
  CREATE TABLE [dbo].[crm_customer_map] (
    [property_id] varchar(64) NOT NULL,
    [customer_map_id] varchar(36) NOT NULL,
    [member_no] varchar(36) NOT NULL,
    [pms_guest_id] varchar(36),
    [pos_customer_ref] varchar(36),
    [facility_user_ref] varchar(36),
    [banquet_customer_id] varchar(36),
    [valid_from] datetime2(3) NOT NULL,
    [valid_to] datetime2(3),
    [mapping_status] varchar(16) NOT NULL,
    [mapping_confidence] decimal(5,4) NOT NULL,
    [is_synthetic] bit NOT NULL,
    [source_updated_at] datetime2(3) NOT NULL,
    CONSTRAINT [pk_crm_customer_map] PRIMARY KEY ([customer_map_id]),
    CONSTRAINT [uq_crm_customer_map_property_id_customer_map_id] UNIQUE ([property_id], [customer_map_id]),
    CONSTRAINT [ck_crm_customer_map_1] CHECK ([mapping_status] IN ('ACTIVE','REVOKED')),
    CONSTRAINT [ck_crm_customer_map_2] CHECK ([mapping_confidence] BETWEEN 0 AND 1),
    CONSTRAINT [ck_crm_customer_map_3] CHECK (([valid_to] IS NULL OR [valid_from] < [valid_to])),
    CONSTRAINT [ck_crm_customer_map_4] CHECK ([valid_from] <= [source_updated_at]),
    CONSTRAINT [ck_crm_customer_map_5] CHECK (([valid_to] IS NULL OR [valid_to] <= [source_updated_at])),
    CONSTRAINT [ck_crm_customer_map_6] CHECK (([pms_guest_id] IS NOT NULL OR [pos_customer_ref] IS NOT NULL OR [facility_user_ref] IS NOT NULL OR [banquet_customer_id] IS NOT NULL)),
    CONSTRAINT [ck_crm_customer_map_7] CHECK ([is_synthetic]=1),
    CONSTRAINT [fk_crm_customer_map_member] FOREIGN KEY ([property_id],[member_no]) REFERENCES [dbo].[crm_members]([property_id],[member_no])
  );
END;
GO

IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND ep.minor_id=0 AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'CRM 회원과 소스별 합성 고객키의 유효기간 매핑 1건',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'property_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'property_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'customer_map_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'고객 매핑 ID. 관계 자산 PK [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'customer_map_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'member_no' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'CRM 회원 번호.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'member_no';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'pms_guest_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'PMS 고객 ID.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'pms_guest_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'pos_customer_ref' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'POS 고객 참조.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'pos_customer_ref';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'facility_user_ref' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'시설 고객 참조.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'facility_user_ref';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'banquet_customer_id' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'연회 고객 ID.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'banquet_customer_id';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'valid_from' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'유효 시작.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'valid_from';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'valid_to' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'유효 종료.  [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'valid_to';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'mapping_status' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'상태. ACTIVE/REVOKED [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'mapping_status';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'mapping_confidence' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'매핑 신뢰도. 0~1 [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'mapping_confidence';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'is_synthetic' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'합성 여부. 항상 1 [classification=POLICY]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'is_synthetic';
IF NOT EXISTS (
  SELECT 1 FROM sys.extended_properties ep
  JOIN sys.columns c ON c.object_id=ep.major_id AND c.column_id=ep.minor_id
  WHERE ep.major_id=OBJECT_ID(N'dbo.crm_customer_map') AND c.name=N'source_updated_at' AND ep.name=N'MS_Description'
)
  EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'원천 수정시각. watermark [classification=SYNTHETIC]',
    @level0type=N'SCHEMA', @level0name=N'dbo',
    @level1type=N'TABLE', @level1name=N'crm_customer_map',
    @level2type=N'COLUMN', @level2name=N'source_updated_at';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND name=N'ux_crm_grade_current_member')
  CREATE UNIQUE INDEX [ux_crm_grade_current_member] ON [dbo].[crm_member_grade_history]([property_id],[member_no]) WHERE [valid_to] IS NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.crm_customer_map') AND name=N'ux_crm_map_current_member')
  CREATE UNIQUE INDEX [ux_crm_map_current_member] ON [dbo].[crm_customer_map]([property_id],[member_no]) WHERE [mapping_status]='ACTIVE' AND [valid_to] IS NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.crm_customer_map') AND name=N'ux_crm_map_current_pms')
  CREATE UNIQUE INDEX [ux_crm_map_current_pms] ON [dbo].[crm_customer_map]([property_id],[pms_guest_id]) WHERE [mapping_status]='ACTIVE' AND [valid_to] IS NULL AND [pms_guest_id] IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.crm_customer_map') AND name=N'ux_crm_map_current_pos')
  CREATE UNIQUE INDEX [ux_crm_map_current_pos] ON [dbo].[crm_customer_map]([property_id],[pos_customer_ref]) WHERE [mapping_status]='ACTIVE' AND [valid_to] IS NULL AND [pos_customer_ref] IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.crm_customer_map') AND name=N'ux_crm_map_current_facility')
  CREATE UNIQUE INDEX [ux_crm_map_current_facility] ON [dbo].[crm_customer_map]([property_id],[facility_user_ref]) WHERE [mapping_status]='ACTIVE' AND [valid_to] IS NULL AND [facility_user_ref] IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.crm_customer_map') AND name=N'ux_crm_map_current_banquet')
  CREATE UNIQUE INDEX [ux_crm_map_current_banquet] ON [dbo].[crm_customer_map]([property_id],[banquet_customer_id]) WHERE [mapping_status]='ACTIVE' AND [valid_to] IS NULL AND [banquet_customer_id] IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.crm_members') AND name=N'ix_crm_members_grade_status')
  CREATE INDEX [ix_crm_members_grade_status] ON [dbo].[crm_members]([membership_grade],[member_status]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.crm_member_grade_history') AND name=N'ix_crm_grade_member_period')
  CREATE INDEX [ix_crm_grade_member_period] ON [dbo].[crm_member_grade_history]([member_no],[valid_from],[valid_to]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.crm_point_transactions') AND name=N'ix_crm_points_member_event')
  CREATE INDEX [ix_crm_points_member_event] ON [dbo].[crm_point_transactions]([member_no],[event_at]);
GO

CREATE OR ALTER TRIGGER dbo.trg_crm_grade_no_overlap
ON dbo.crm_member_grade_history
AFTER INSERT, UPDATE
AS
BEGIN
  SET NOCOUNT ON;
  IF EXISTS (
    SELECT 1
    FROM inserted i
    JOIN dbo.crm_member_grade_history e
      ON e.property_id=i.property_id
     AND e.member_no=i.member_no
     AND e.grade_history_id<>i.grade_history_id
     AND i.valid_from < ISNULL(e.valid_to, CONVERT(datetime2(3),'9999-12-31T23:59:59.999',126))
     AND e.valid_from < ISNULL(i.valid_to, CONVERT(datetime2(3),'9999-12-31T23:59:59.999',126))
  )
    THROW 51001, 'CRM_GRADE_PERIOD_OVERLAP', 1;
END;
GO

CREATE OR ALTER TRIGGER dbo.trg_crm_map_no_overlap
ON dbo.crm_customer_map
AFTER INSERT, UPDATE
AS
BEGIN
  SET NOCOUNT ON;
  IF EXISTS (
    SELECT 1
    FROM inserted i
    JOIN dbo.crm_customer_map e
      ON e.property_id=i.property_id
     AND e.customer_map_id<>i.customer_map_id
     AND i.mapping_status='ACTIVE' AND e.mapping_status='ACTIVE'
     AND i.valid_from < ISNULL(e.valid_to, CONVERT(datetime2(3),'9999-12-31T23:59:59.999',126))
     AND e.valid_from < ISNULL(i.valid_to, CONVERT(datetime2(3),'9999-12-31T23:59:59.999',126))
     AND (
          i.member_no=e.member_no
       OR (i.pms_guest_id IS NOT NULL AND i.pms_guest_id=e.pms_guest_id)
       OR (i.pos_customer_ref IS NOT NULL AND i.pos_customer_ref=e.pos_customer_ref)
       OR (i.facility_user_ref IS NOT NULL AND i.facility_user_ref=e.facility_user_ref)
       OR (i.banquet_customer_id IS NOT NULL AND i.banquet_customer_id=e.banquet_customer_id)
     )
  )
    THROW 51002, 'CRM_CUSTOMER_MAP_PERIOD_OVERLAP', 1;
END;
GO

IF DATABASE_PRINCIPAL_ID(N'crm_ingest') IS NULL CREATE ROLE [crm_ingest];
IF DATABASE_PRINCIPAL_ID(N'crm_query') IS NULL CREATE ROLE [crm_query];
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::dbo TO [crm_ingest];
GRANT SELECT ON SCHEMA::dbo TO [crm_query];
DENY INSERT, UPDATE, DELETE, ALTER, CONTROL ON SCHEMA::dbo TO [crm_query];
GO

-- Read-only negative tests: crm_query role만 할당된 별도 시험 사용자로 실행한다.
-- INSERT/UPDATE/DELETE dbo.crm_members 및 ALTER TABLE 시 권한 거부가 나와야 한다.
-- 실제 사용자는 이 파일에서 생성하지 않는다.

SELECT COUNT(*) AS source_table_count,
       CASE WHEN COUNT(*)=4 THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM sys.tables
WHERE schema_id=SCHEMA_ID(N'dbo')
  AND name IN (N'crm_members',N'crm_member_grade_history',N'crm_point_transactions',N'crm_customer_map');

SELECT COUNT(*) AS source_column_count,
       CASE WHEN COUNT(*)=44 THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM sys.columns
WHERE object_id IN (
  OBJECT_ID(N'dbo.crm_members'),OBJECT_ID(N'dbo.crm_member_grade_history'),
  OBJECT_ID(N'dbo.crm_point_transactions'),OBJECT_ID(N'dbo.crm_customer_map')
);

-- 회원별 등급 유효기간 중첩 검증
SELECT a.property_id,a.member_no,a.grade_history_id,b.grade_history_id
FROM dbo.crm_member_grade_history a
JOIN dbo.crm_member_grade_history b
  ON a.property_id=b.property_id AND a.member_no=b.member_no
 AND a.grade_history_id<b.grade_history_id
 AND a.valid_from<ISNULL(b.valid_to,CONVERT(datetime2(3),'9999-12-31T23:59:59.999',126))
 AND b.valid_from<ISNULL(a.valid_to,CONVERT(datetime2(3),'9999-12-31T23:59:59.999',126));

-- evaluation_as_of=2026-07-28T14:00:00+09:00, UTC 저장값 2026-07-28T05:00:00
SELECT m.property_id,m.member_no,m.membership_grade,h.grade_code
FROM dbo.crm_members m
LEFT JOIN dbo.crm_member_grade_history h
  ON h.property_id=m.property_id AND h.member_no=m.member_no
 AND h.valid_from<=CONVERT(datetime2(3),'2026-07-28T05:00:00.000',126)
 AND (h.valid_to IS NULL OR CONVERT(datetime2(3),'2026-07-28T05:00:00.000',126)<h.valid_to)
WHERE h.grade_code IS NULL OR m.membership_grade<>h.grade_code;

-- local ID별 활성 기간 중복 검증
SELECT a.property_id,a.customer_map_id,b.customer_map_id
FROM dbo.crm_customer_map a
JOIN dbo.crm_customer_map b
  ON a.property_id=b.property_id AND a.customer_map_id<b.customer_map_id
 AND a.mapping_status='ACTIVE' AND b.mapping_status='ACTIVE'
 AND a.valid_from<ISNULL(b.valid_to,CONVERT(datetime2(3),'9999-12-31T23:59:59.999',126))
 AND b.valid_from<ISNULL(a.valid_to,CONVERT(datetime2(3),'9999-12-31T23:59:59.999',126))
 AND (
      (a.pms_guest_id IS NOT NULL AND a.pms_guest_id=b.pms_guest_id)
   OR (a.pos_customer_ref IS NOT NULL AND a.pos_customer_ref=b.pos_customer_ref)
   OR (a.facility_user_ref IS NOT NULL AND a.facility_user_ref=b.facility_user_ref)
   OR (a.banquet_customer_id IS NOT NULL AND a.banquet_customer_id=b.banquet_customer_id)
 );

SELECT 'crm' AS source_id, 'SQL Server' AS engine, 'hotel_crm/dbo' AS database_schema,
       'crm_ingest' AS ingestion_role, 'crm_query' AS query_role,
       'hotel_crm' AS datahub_platform_instance, 'crm' AS trino_catalog,
       'schema-v4.6-websql' AS schema_version;
GO
