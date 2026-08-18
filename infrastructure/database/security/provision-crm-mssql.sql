-- 책임: 외부에서 검증된 SQL Server login 이름과 secret으로 CRM query principal을
-- 최소 read 권한으로 조정한다. sqlcmd 변수 누락이나 DDL 오류는 batch를 실패시킨다.
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
