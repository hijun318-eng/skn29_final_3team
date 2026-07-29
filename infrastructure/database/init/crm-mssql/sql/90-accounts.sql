SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE [master];
GO
SET XACT_ABORT ON;
SET NOCOUNT ON;
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'crm_datahub')
    CREATE LOGIN [crm_datahub]
        WITH PASSWORD = N'$(CRM_DATAHUB_PASSWORD)',
        CHECK_POLICY = ON,
        CHECK_EXPIRATION = OFF,
        DEFAULT_DATABASE = [$(CRM_DATABASE)];
ELSE
    ALTER LOGIN [crm_datahub]
        WITH PASSWORD = N'$(CRM_DATAHUB_PASSWORD)';
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'crm_trino')
    CREATE LOGIN [crm_trino]
        WITH PASSWORD = N'$(CRM_TRINO_PASSWORD)',
        CHECK_POLICY = ON,
        CHECK_EXPIRATION = OFF,
        DEFAULT_DATABASE = [$(CRM_DATABASE)];
ELSE
    ALTER LOGIN [crm_trino]
        WITH PASSWORD = N'$(CRM_TRINO_PASSWORD)';
GO

USE [$(CRM_DATABASE)];
GO

IF DATABASE_PRINCIPAL_ID(N'crm_ingest') IS NULL
    CREATE ROLE [crm_ingest] AUTHORIZATION [dbo];
IF DATABASE_PRINCIPAL_ID(N'crm_query') IS NULL
    CREATE ROLE [crm_query] AUTHORIZATION [dbo];
GO

GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::dbo TO [crm_ingest];
GRANT SELECT ON SCHEMA::dbo TO [crm_query];
GRANT VIEW DEFINITION TO [crm_query];
DENY INSERT, UPDATE, DELETE ON SCHEMA::dbo TO [crm_query];
REVOKE CONTROL ON SCHEMA::dbo FROM [crm_query];
DENY ALTER ON SCHEMA::dbo TO [crm_query];
DENY CREATE TABLE, CREATE VIEW, CREATE PROCEDURE, CREATE FUNCTION
    TO [crm_query];
GO

IF DATABASE_PRINCIPAL_ID(N'crm_datahub') IS NULL
    CREATE USER [crm_datahub] FOR LOGIN [crm_datahub];
IF DATABASE_PRINCIPAL_ID(N'crm_trino') IS NULL
    CREATE USER [crm_trino] FOR LOGIN [crm_trino];
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.database_role_members drm
    JOIN sys.database_principals role_principal
      ON role_principal.principal_id = drm.role_principal_id
    JOIN sys.database_principals member_principal
      ON member_principal.principal_id = drm.member_principal_id
    WHERE role_principal.name = N'crm_query'
      AND member_principal.name = N'crm_datahub'
)
    ALTER ROLE [crm_query] ADD MEMBER [crm_datahub];

IF NOT EXISTS (
    SELECT 1
    FROM sys.database_role_members drm
    JOIN sys.database_principals role_principal
      ON role_principal.principal_id = drm.role_principal_id
    JOIN sys.database_principals member_principal
      ON member_principal.principal_id = drm.member_principal_id
    WHERE role_principal.name = N'crm_query'
      AND member_principal.name = N'crm_trino'
)
    ALTER ROLE [crm_query] ADD MEMBER [crm_trino];
GO

GRANT CONNECT TO [crm_datahub];
GRANT CONNECT TO [crm_trino];
GO
