SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE [$(CRM_DATABASE)];
GO

CREATE OR ALTER VIEW dbo.environment_manifest
AS
SELECT
    CAST('crm' AS varchar(32)) AS source_id,
    CAST('sqlserver' AS varchar(32)) AS engine,
    CAST('$(CRM_DATABASE)' AS varchar(128)) AS database_name,
    CAST('$(DATABASE_SCHEMA_VERSION)' AS nvarchar(128)) AS schema_version,
    CAST('$(SCENARIO_VERSION)' AS nvarchar(128)) AS scenario_version,
    CAST('$(FIXTURE_VERSION)' AS nvarchar(128)) AS fixture_version,
    CAST($(SYNTHETIC_DATA_SEED) AS bigint) AS synthetic_seed,
    CAST('$(GENERATED_AT)' AS datetime2(3)) AS generated_at,
    CAST(1 AS bit) AS is_synthetic;
GO
