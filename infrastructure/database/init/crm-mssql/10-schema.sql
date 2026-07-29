IF DB_ID('$(CRM_DB_NAME)') IS NULL EXEC('CREATE DATABASE [$(CRM_DB_NAME)]');
GO
USE [$(CRM_DB_NAME)];
GO
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'schema_version') CREATE TABLE dbo.schema_version (version nvarchar(64) NOT NULL PRIMARY KEY, applied_at datetime2 NOT NULL DEFAULT sysdatetime());
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'seed_metadata') CREATE TABLE dbo.seed_metadata (seed_name nvarchar(64) NOT NULL PRIMARY KEY, seed_value int NOT NULL, data_classification nvarchar(32) NOT NULL);
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'crm_members') CREATE TABLE dbo.crm_members (member_id nvarchar(32) NOT NULL PRIMARY KEY, member_name nvarchar(128) NOT NULL, created_at datetime2 NOT NULL DEFAULT sysdatetime());
IF NOT EXISTS (SELECT 1 FROM dbo.schema_version WHERE version = 'crm-mssql/v1') INSERT INTO dbo.schema_version(version) VALUES ('crm-mssql/v1');
IF NOT EXISTS (SELECT 1 FROM dbo.seed_metadata WHERE seed_name = 'synthetic-demo') INSERT INTO dbo.seed_metadata VALUES ('synthetic-demo', 20260729, 'synthetic');
IF NOT EXISTS (SELECT 1 FROM dbo.crm_members WHERE member_id = 'CRM-0001') INSERT INTO dbo.crm_members(member_id, member_name) VALUES ('CRM-0001', 'Synthetic Member');
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = '$(CRM_RO_USERNAME)') EXEC('CREATE LOGIN [$(CRM_RO_USERNAME)] WITH PASSWORD = ''$(CRM_RO_PASSWORD)''');
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$(CRM_RO_USERNAME)') EXEC('CREATE USER [$(CRM_RO_USERNAME)] FOR LOGIN [$(CRM_RO_USERNAME)]');
ALTER ROLE db_datareader ADD MEMBER [$(CRM_RO_USERNAME)];
REVOKE CONTROL TO [$(CRM_RO_USERNAME)];
DENY INSERT, UPDATE, DELETE, ALTER, CREATE TABLE, CREATE VIEW, CREATE PROCEDURE TO [$(CRM_RO_USERNAME)];
