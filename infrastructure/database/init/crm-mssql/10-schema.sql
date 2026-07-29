USE [master];
GO

IF DB_ID(N'$(CRM_DB_NAME)') IS NULL
BEGIN
    EXEC(N'CREATE DATABASE [$(CRM_DB_NAME)] COLLATE Korean_100_CI_AS_SC_UTF8');
END;
GO

USE [$(CRM_DB_NAME)];
GO

IF SCHEMA_ID(N'crm') IS NULL
    EXEC(N'CREATE SCHEMA crm AUTHORIZATION dbo');
GO

IF OBJECT_ID(N'crm.member_tier', N'U') IS NULL
BEGIN
    CREATE TABLE crm.member_tier (
        tier_code nvarchar(20) NOT NULL PRIMARY KEY,
        tier_name nvarchar(80) NOT NULL,
        minimum_points int NOT NULL,
        CONSTRAINT chk_member_tier_points CHECK (minimum_points >= 0)
    );
END;
GO

IF OBJECT_ID(N'crm.member_profile', N'U') IS NULL
BEGIN
    CREATE TABLE crm.member_profile (
        member_id bigint NOT NULL PRIMARY KEY,
        member_token nvarchar(80) NOT NULL UNIQUE,
        tier_code nvarchar(20) NOT NULL,
        join_date date NOT NULL,
        consent_marketing bit NOT NULL,
        home_region nvarchar(50) NOT NULL,
        CONSTRAINT fk_member_profile_tier
            FOREIGN KEY (tier_code) REFERENCES crm.member_tier(tier_code)
    );
END;
GO

IF OBJECT_ID(N'crm.point_ledger', N'U') IS NULL
BEGIN
    CREATE TABLE crm.point_ledger (
        ledger_id bigint NOT NULL PRIMARY KEY,
        member_id bigint NOT NULL,
        occurred_at datetime2(0) NOT NULL,
        point_delta int NOT NULL,
        reason_code nvarchar(30) NOT NULL,
        CONSTRAINT fk_point_ledger_member
            FOREIGN KEY (member_id) REFERENCES crm.member_profile(member_id)
    );
END;
GO

IF OBJECT_ID(N'crm.schema_version', N'U') IS NULL
BEGIN
    CREATE TABLE crm.schema_version (
        version nvarchar(30) NOT NULL PRIMARY KEY,
        seed bigint NOT NULL,
        applied_at datetimeoffset(0) NOT NULL
    );
END;
GO
