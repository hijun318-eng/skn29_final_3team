USE [$(CRM_DB_NAME)];
GO

MERGE crm.schema_version AS target
USING (VALUES
    (N'1.0.0', CAST(20260729 AS bigint), CAST('2026-07-29T00:00:00+09:00' AS datetimeoffset(0)))
) AS source (version, seed, applied_at)
ON target.version = source.version
WHEN MATCHED THEN
    UPDATE SET seed = source.seed,
               applied_at = source.applied_at
WHEN NOT MATCHED THEN
    INSERT (version, seed, applied_at)
    VALUES (source.version, source.seed, source.applied_at);
GO
