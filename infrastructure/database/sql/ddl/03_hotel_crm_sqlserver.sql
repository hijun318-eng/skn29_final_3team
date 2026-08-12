-- source_id=crm; engine=SQL Server; database=crm_db
-- ingestion_role=crm_ingest; query_role=crm_query
-- datahub_platform_instance=crm_db; trino_catalog=crm
-- schema_version=1.0.0
IF DB_ID(N'crm_db') IS NULL CREATE DATABASE crm_db COLLATE Korean_100_CI_AS_SC_UTF8;
GO
USE crm_db;
GO
SET XACT_ABORT ON;
SET NOCOUNT ON;
SET DATEFORMAT ymd;
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET ARITHABORT ON;
SET NUMERIC_ROUNDABORT OFF;

IF DATABASE_PRINCIPAL_ID(N'crm_ingest') IS NULL CREATE ROLE crm_ingest;
IF DATABASE_PRINCIPAL_ID(N'crm_query') IS NULL CREATE ROLE crm_query;
GO

IF OBJECT_ID(N'dbo.crm_members', N'U') IS NULL
CREATE TABLE dbo.crm_members (
    property_id varchar(64) NOT NULL,
    member_no varchar(36) NOT NULL PRIMARY KEY,
    membership_grade varchar(16) NOT NULL,
    points_balance integer NOT NULL,
    joined_at datetime2(3) NOT NULL,
    member_status varchar(16) NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast bit NOT NULL,
    is_synthetic bit NOT NULL,
    source_updated_at datetime2(3) NOT NULL,
    CONSTRAINT uq_crm_member_property UNIQUE (property_id, member_no),
    CONSTRAINT ck_crm_member_grade CHECK (membership_grade IN ('BASIC','SILVER','GOLD','VIP')),
    CONSTRAINT ck_crm_member_balance CHECK (points_balance >= 0),
    CONSTRAINT ck_crm_member_status CHECK (member_status IN ('ACTIVE','INACTIVE','REVOKED')),
    CONSTRAINT ck_crm_member_time CHECK (joined_at <= source_updated_at),
    CONSTRAINT ck_crm_member_synthetic CHECK (is_synthetic = 1)
);
GO

IF OBJECT_ID(N'dbo.crm_member_grade_history', N'U') IS NULL
CREATE TABLE dbo.crm_member_grade_history (
    property_id varchar(64) NOT NULL,
    grade_history_id varchar(36) NOT NULL PRIMARY KEY,
    member_no varchar(36) NOT NULL,
    grade_code varchar(16) NOT NULL,
    valid_from datetime2(3) NOT NULL,
    valid_to datetime2(3) NULL,
    change_reason_code varchar(24) NOT NULL,
    is_synthetic bit NOT NULL,
    source_updated_at datetime2(3) NOT NULL,
    CONSTRAINT fk_crm_grade_member FOREIGN KEY (member_no) REFERENCES dbo.crm_members(member_no),
    CONSTRAINT ck_crm_grade_code CHECK (grade_code IN ('BASIC','SILVER','GOLD','VIP')),
    CONSTRAINT ck_crm_grade_period CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_crm_grade_synthetic CHECK (is_synthetic = 1)
);
GO

IF OBJECT_ID(N'dbo.crm_point_transactions', N'U') IS NULL
CREATE TABLE dbo.crm_point_transactions (
    property_id varchar(64) NOT NULL,
    point_txn_id varchar(36) NOT NULL PRIMARY KEY,
    member_no varchar(36) NOT NULL,
    event_at datetime2(3) NOT NULL,
    txn_type varchar(16) NOT NULL,
    points_delta integer NOT NULL,
    related_source varchar(16) NULL,
    related_id varchar(36) NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast bit NOT NULL,
    is_synthetic bit NOT NULL,
    source_updated_at datetime2(3) NOT NULL,
    CONSTRAINT fk_crm_point_member FOREIGN KEY (member_no) REFERENCES dbo.crm_members(member_no),
    CONSTRAINT ck_crm_point_type CHECK (txn_type IN ('EARN','USE','EXPIRE','ADJUST')),
    CONSTRAINT ck_crm_point_time CHECK (event_at <= source_updated_at),
    CONSTRAINT ck_crm_point_synthetic CHECK (is_synthetic = 1)
);
GO

IF OBJECT_ID(N'dbo.crm_customer_map', N'U') IS NULL
CREATE TABLE dbo.crm_customer_map (
    property_id varchar(64) NOT NULL,
    customer_map_id varchar(36) NOT NULL PRIMARY KEY,
    member_no varchar(36) NOT NULL,
    pms_guest_id varchar(36) NULL,
    pos_customer_ref varchar(36) NULL,
    facility_user_ref varchar(36) NULL,
    banquet_customer_id varchar(36) NULL,
    valid_from datetime2(3) NOT NULL,
    valid_to datetime2(3) NULL,
    mapping_status varchar(16) NOT NULL,
    mapping_confidence decimal(5,4) NOT NULL,
    is_synthetic bit NOT NULL,
    source_updated_at datetime2(3) NOT NULL,
    CONSTRAINT fk_crm_map_member FOREIGN KEY (member_no) REFERENCES dbo.crm_members(member_no),
    CONSTRAINT ck_crm_map_period CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_crm_map_status CHECK (mapping_status IN ('ACTIVE','REVOKED')),
    CONSTRAINT ck_crm_map_confidence CHECK (mapping_confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_crm_map_time CHECK (valid_from <= source_updated_at AND (valid_to IS NULL OR valid_to <= source_updated_at)),
    CONSTRAINT ck_crm_map_synthetic CHECK (is_synthetic = 1)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'idx_crm_member_grade_status')
CREATE INDEX idx_crm_member_grade_status ON dbo.crm_members(membership_grade, member_status);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'idx_crm_grade_member_period')
CREATE INDEX idx_crm_grade_member_period ON dbo.crm_member_grade_history(member_no, valid_from, valid_to);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'idx_crm_point_member_time')
CREATE INDEX idx_crm_point_member_time ON dbo.crm_point_transactions(member_no, event_at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'uq_crm_active_member')
CREATE UNIQUE INDEX uq_crm_active_member ON dbo.crm_customer_map(property_id, member_no)
WHERE mapping_status = 'ACTIVE' AND valid_to IS NULL;
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'uq_crm_active_pms')
CREATE UNIQUE INDEX uq_crm_active_pms ON dbo.crm_customer_map(property_id, pms_guest_id)
WHERE mapping_status = 'ACTIVE' AND valid_to IS NULL AND pms_guest_id IS NOT NULL;
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'uq_crm_active_pos')
CREATE UNIQUE INDEX uq_crm_active_pos ON dbo.crm_customer_map(property_id, pos_customer_ref)
WHERE mapping_status = 'ACTIVE' AND valid_to IS NULL AND pos_customer_ref IS NOT NULL;
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'uq_crm_active_facility')
CREATE UNIQUE INDEX uq_crm_active_facility ON dbo.crm_customer_map(property_id, facility_user_ref)
WHERE mapping_status = 'ACTIVE' AND valid_to IS NULL AND facility_user_ref IS NOT NULL;
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'uq_crm_active_banquet')
CREATE UNIQUE INDEX uq_crm_active_banquet ON dbo.crm_customer_map(property_id, banquet_customer_id)
WHERE mapping_status = 'ACTIVE' AND valid_to IS NULL AND banquet_customer_id IS NOT NULL;
GO

CREATE OR ALTER TRIGGER dbo.trg_crm_grade_history_no_overlap
ON dbo.crm_member_grade_history
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted i
        JOIN dbo.crm_member_grade_history h
          ON h.property_id = i.property_id
         AND h.member_no = i.member_no
         AND h.grade_history_id <> i.grade_history_id
         AND i.valid_from < COALESCE(h.valid_to, CONVERT(datetime2(3), '9999-12-31T23:59:59.999'))
         AND h.valid_from < COALESCE(i.valid_to, CONVERT(datetime2(3), '9999-12-31T23:59:59.999'))
    )
        THROW 51001, 'CRM_GRADE_PERIOD_OVERLAP', 1;
END;
GO

CREATE OR ALTER TRIGGER dbo.trg_crm_customer_map_no_overlap
ON dbo.crm_customer_map
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    -- Active open-ended identifiers are already protected by the five filtered
    -- unique indexes. Avoid comparing a large all-active batch with itself.
    IF NOT EXISTS (
        SELECT 1
        FROM dbo.crm_customer_map
        WHERE mapping_status <> 'ACTIVE' OR valid_to IS NOT NULL
    )
        RETURN;

    IF EXISTS (
        SELECT 1
        FROM inserted i
        JOIN dbo.crm_customer_map m
          ON m.property_id = i.property_id
         AND m.customer_map_id <> i.customer_map_id
         AND (
              m.member_no = i.member_no
              OR (i.pms_guest_id IS NOT NULL AND m.pms_guest_id = i.pms_guest_id)
              OR (i.pos_customer_ref IS NOT NULL AND m.pos_customer_ref = i.pos_customer_ref)
              OR (i.facility_user_ref IS NOT NULL AND m.facility_user_ref = i.facility_user_ref)
              OR (i.banquet_customer_id IS NOT NULL AND m.banquet_customer_id = i.banquet_customer_id)
         )
         -- Both open ACTIVE rows are already protected by the five filtered
         -- unique indexes above. Keep the trigger for every historical or
         -- revoked interval so this fast path cannot weaken overlap checks.
         AND NOT (
             i.mapping_status = 'ACTIVE' AND i.valid_to IS NULL
             AND m.mapping_status = 'ACTIVE' AND m.valid_to IS NULL
         )
         AND i.valid_from < COALESCE(m.valid_to, CONVERT(datetime2(3), '9999-12-31T23:59:59.999'))
         AND m.valid_from < COALESCE(i.valid_to, CONVERT(datetime2(3), '9999-12-31T23:59:59.999'))
    )
        THROW 51002, 'CRM_IDENTITY_PERIOD_OVERLAP', 1;
END;
GO

CREATE OR ALTER VIEW dbo.customer_identity_map
AS
SELECT
    property_id, customer_map_id, member_no, pms_guest_id, pos_customer_ref,
    facility_user_ref, banquet_customer_id, valid_from, valid_to, mapping_status,
    mapping_confidence, is_synthetic, source_updated_at
FROM dbo.crm_customer_map;
GO

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = N'schema_version' AND schema_id = SCHEMA_ID(N'dbo'))
CREATE TABLE dbo.schema_version (version nvarchar(32) NOT NULL PRIMARY KEY);
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = N'seed_metadata' AND schema_id = SCHEMA_ID(N'dbo'))
CREATE TABLE dbo.seed_metadata (seed int NOT NULL PRIMARY KEY, data_class nvarchar(16) NOT NULL);
IF NOT EXISTS (SELECT 1 FROM dbo.schema_version WHERE version = N'1.0.0') INSERT INTO dbo.schema_version(version) VALUES (N'1.0.0');
IF NOT EXISTS (SELECT 1 FROM dbo.seed_metadata WHERE seed = 20260729) INSERT INTO dbo.seed_metadata(seed, data_class) VALUES (20260729, N'synthetic');
GO

GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::dbo TO crm_ingest;
GRANT SELECT ON SCHEMA::dbo TO crm_query;
DENY INSERT, UPDATE, DELETE, ALTER ON SCHEMA::dbo TO crm_query;
GO

SELECT COUNT(*) AS crm_table_count
FROM sys.tables
WHERE schema_id = SCHEMA_ID(N'dbo');
GO
