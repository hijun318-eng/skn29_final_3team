USE master;
GO
IF SUSER_ID(N'$(QueryUser)') IS NULL
    CREATE LOGIN [$(QueryUser)] WITH PASSWORD=N'$(QueryPassword)', CHECK_POLICY=ON;
ELSE
    ALTER LOGIN [$(QueryUser)] WITH PASSWORD=N'$(QueryPassword)';
GO

USE crm_db;
GO
IF USER_ID(N'$(QueryUser)') IS NULL CREATE USER [$(QueryUser)] FOR LOGIN [$(QueryUser)];
IF IS_ROLEMEMBER(N'crm_query',N'$(QueryUser)')<>1
    ALTER ROLE crm_query ADD MEMBER [$(QueryUser)];
REVOKE CONTROL ON SCHEMA::dbo FROM crm_query;
GRANT SELECT ON SCHEMA::dbo TO crm_query;
GO
