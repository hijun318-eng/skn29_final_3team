IF DB_ID('$(DB)') IS NULL EXEC('CREATE DATABASE [$(DB)] COLLATE Korean_100_CI_AS_SC_UTF8');
GO
USE [$(DB)];
GO
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'schema_version') CREATE TABLE dbo.schema_version (version nvarchar(16) PRIMARY KEY);
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'seed_metadata') CREATE TABLE dbo.seed_metadata (seed int PRIMARY KEY, classification nvarchar(32) NOT NULL);
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'crm_members') CREATE TABLE dbo.crm_members (member_id nvarchar(32) PRIMARY KEY, member_name nvarchar(128) NOT NULL);
IF NOT EXISTS (SELECT 1 FROM dbo.schema_version WHERE version = '1.0.0') INSERT INTO dbo.schema_version VALUES ('1.0.0');
IF NOT EXISTS (SELECT 1 FROM dbo.seed_metadata WHERE seed = 20260729) INSERT INTO dbo.seed_metadata VALUES (20260729, 'synthetic');
IF NOT EXISTS (SELECT 1 FROM dbo.crm_members WHERE member_id = 'CRM-0001') INSERT INTO dbo.crm_members VALUES ('CRM-0001', 'Synthetic Member');
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = '$(RO)') EXEC('CREATE LOGIN [$(RO)] WITH PASSWORD = ''$(ROPASSWORD)''');
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$(RO)') EXEC('CREATE USER [$(RO)] FOR LOGIN [$(RO)]');
IF NOT EXISTS (SELECT 1 FROM sys.database_role_members rm JOIN sys.database_principals r ON rm.role_principal_id = r.principal_id JOIN sys.database_principals m ON rm.member_principal_id = m.principal_id WHERE r.name = 'db_datareader' AND m.name = '$(RO)') ALTER ROLE db_datareader ADD MEMBER [$(RO)];
DENY INSERT, UPDATE, DELETE, ALTER, CREATE TABLE, CREATE VIEW, CREATE PROCEDURE TO [$(RO)];
