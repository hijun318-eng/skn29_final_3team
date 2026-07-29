SET XACT_ABORT ON;
SET NOCOUNT ON;
SET DATEFORMAT ymd;
SET LANGUAGE us_english;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF DB_ID(N'$(CRM_DATABASE)') IS NULL
BEGIN
    EXEC(N'CREATE DATABASE [$(CRM_DATABASE)] COLLATE Korean_100_CI_AS_SC_UTF8');
END;
GO

USE [$(CRM_DATABASE)];
GO

IF OBJECT_ID(N'dbo.crm_members', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.crm_members (
        property_id varchar(64) NOT NULL,
        member_no varchar(36) NOT NULL,
        membership_grade varchar(16) NOT NULL,
        points_balance int NOT NULL,
        joined_at datetime2(3) NOT NULL,
        member_status varchar(16) NOT NULL,
        data_period_status varchar(32) NOT NULL,
        is_forecast bit NOT NULL,
        is_synthetic bit NOT NULL,
        source_updated_at datetime2(3) NOT NULL,
        CONSTRAINT pk_crm_members PRIMARY KEY (member_no),
        CONSTRAINT uq_crm_members_property UNIQUE (property_id, member_no),
        CONSTRAINT ck_crm_members_grade CHECK (
            membership_grade IN ('BASIC', 'SILVER', 'GOLD', 'VIP')
        ),
        CONSTRAINT ck_crm_members_points CHECK (points_balance >= 0),
        CONSTRAINT ck_crm_members_status CHECK (
            member_status IN ('ACTIVE', 'INACTIVE', 'REVOKED')
        ),
        CONSTRAINT ck_crm_members_period CHECK (
            data_period_status IN (
                'REFERENCE_CALIBRATED', 'SYNTHETIC_ACTUAL_LIKE',
                'YTD_SYNTHETIC', 'FORECAST_SCENARIO'
            )
        ),
        CONSTRAINT ck_crm_members_forecast CHECK (
            is_forecast = CASE
                WHEN data_period_status = 'FORECAST_SCENARIO' THEN 1
                ELSE 0
            END
        ),
        CONSTRAINT ck_crm_members_synthetic CHECK (is_synthetic = 1)
    );
END;
GO

IF OBJECT_ID(N'dbo.crm_member_grade_history', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.crm_member_grade_history (
        property_id varchar(64) NOT NULL,
        grade_history_id varchar(36) NOT NULL,
        member_no varchar(36) NOT NULL,
        grade_code varchar(16) NOT NULL,
        valid_from datetime2(3) NOT NULL,
        valid_to datetime2(3) NULL,
        change_reason_code varchar(24) NOT NULL,
        is_synthetic bit NOT NULL,
        source_updated_at datetime2(3) NOT NULL,
        CONSTRAINT pk_crm_member_grade_history PRIMARY KEY (grade_history_id),
        CONSTRAINT fk_crm_grade_member FOREIGN KEY (member_no)
            REFERENCES dbo.crm_members(member_no),
        CONSTRAINT ck_crm_grade_code CHECK (
            grade_code IN ('BASIC', 'SILVER', 'GOLD', 'VIP')
        ),
        CONSTRAINT ck_crm_grade_reason CHECK (
            change_reason_code IN ('JOIN', 'UPGRADE', 'DOWNGRADE', 'REVIEW')
        ),
        CONSTRAINT ck_crm_grade_period CHECK (
            valid_to IS NULL OR valid_from < valid_to
        ),
        CONSTRAINT ck_crm_grade_synthetic CHECK (is_synthetic = 1)
    );
END;
GO

IF OBJECT_ID(N'dbo.crm_point_transactions', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.crm_point_transactions (
        property_id varchar(64) NOT NULL,
        point_txn_id varchar(36) NOT NULL,
        member_no varchar(36) NOT NULL,
        event_at datetime2(3) NOT NULL,
        txn_type varchar(16) NOT NULL,
        points_delta int NOT NULL,
        related_source varchar(16) NULL,
        related_id varchar(36) NULL,
        data_period_status varchar(32) NOT NULL,
        is_forecast bit NOT NULL,
        is_synthetic bit NOT NULL,
        source_updated_at datetime2(3) NOT NULL,
        CONSTRAINT pk_crm_point_transactions PRIMARY KEY (point_txn_id),
        CONSTRAINT fk_crm_points_member FOREIGN KEY (member_no)
            REFERENCES dbo.crm_members(member_no),
        CONSTRAINT ck_crm_points_type CHECK (
            txn_type IN ('EARN', 'USE', 'EXPIRE', 'ADJUST')
        ),
        CONSTRAINT ck_crm_points_source CHECK (
            related_source IS NULL
            OR related_source IN ('PMS', 'POS', 'FACILITY', 'BANQUET')
        ),
        CONSTRAINT ck_crm_points_synthetic CHECK (is_synthetic = 1)
    );
END;
GO

IF OBJECT_ID(N'dbo.crm_customer_map', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.crm_customer_map (
        property_id varchar(64) NOT NULL,
        customer_map_id varchar(36) NOT NULL,
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
        CONSTRAINT pk_crm_customer_map PRIMARY KEY (customer_map_id),
        CONSTRAINT fk_crm_map_member FOREIGN KEY (member_no)
            REFERENCES dbo.crm_members(member_no),
        CONSTRAINT ck_crm_map_period CHECK (
            valid_to IS NULL OR valid_from < valid_to
        ),
        CONSTRAINT ck_crm_map_status CHECK (
            mapping_status IN ('ACTIVE', 'REVOKED')
        ),
        CONSTRAINT ck_crm_map_confidence CHECK (
            mapping_confidence >= 0 AND mapping_confidence <= 1
        ),
        CONSTRAINT ck_crm_map_synthetic CHECK (is_synthetic = 1)
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'ix_crm_members_grade_status'
      AND object_id = OBJECT_ID(N'dbo.crm_members')
)
    CREATE INDEX ix_crm_members_grade_status
        ON dbo.crm_members(membership_grade, member_status);
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'ix_crm_grade_member_period'
      AND object_id = OBJECT_ID(N'dbo.crm_member_grade_history')
)
    CREATE INDEX ix_crm_grade_member_period
        ON dbo.crm_member_grade_history(member_no, valid_from, valid_to);
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'ix_crm_points_member_event'
      AND object_id = OBJECT_ID(N'dbo.crm_point_transactions')
)
    CREATE INDEX ix_crm_points_member_event
        ON dbo.crm_point_transactions(member_no, event_at);
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'ux_crm_active_pms_map'
      AND object_id = OBJECT_ID(N'dbo.crm_customer_map')
)
    CREATE UNIQUE INDEX ux_crm_active_pms_map
        ON dbo.crm_customer_map(property_id, pms_guest_id)
        WHERE mapping_status = 'ACTIVE' AND pms_guest_id IS NOT NULL;
GO

IF EXISTS (
    SELECT required.name
    FROM (VALUES
        (N'crm_members'),
        (N'crm_member_grade_history'),
        (N'crm_point_transactions'),
        (N'crm_customer_map')
    ) AS required(name)
    WHERE OBJECT_ID(N'dbo.' + required.name, N'U') IS NULL
)
    THROW 50002, 'SCHEMA_CONTRACT_MISMATCH', 1;
GO
