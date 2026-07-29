USE [$(CRM_DB_NAME)];
GO

MERGE crm.member_profile AS target
USING (VALUES
    (CAST(40001 AS bigint), N'member-0001', N'GOLD', CAST('2024-03-10' AS date), CAST(1 AS bit), N'Seoul'),
    (CAST(40002 AS bigint), N'member-0002', N'SILVER', CAST('2025-11-02' AS date), CAST(0 AS bit), N'Gyeonggi'),
    (CAST(40003 AS bigint), N'member-0003', N'PLATINUM', CAST('2022-06-19' AS date), CAST(1 AS bit), N'Busan')
) AS source (member_id, member_token, tier_code, join_date, consent_marketing, home_region)
ON target.member_id = source.member_id
WHEN MATCHED THEN
    UPDATE SET member_token = source.member_token,
               tier_code = source.tier_code,
               join_date = source.join_date,
               consent_marketing = source.consent_marketing,
               home_region = source.home_region
WHEN NOT MATCHED THEN
    INSERT (member_id, member_token, tier_code, join_date, consent_marketing, home_region)
    VALUES (source.member_id, source.member_token, source.tier_code, source.join_date, source.consent_marketing, source.home_region);
GO

MERGE crm.point_ledger AS target
USING (VALUES
    (CAST(41001 AS bigint), CAST(40001 AS bigint), CAST('2026-07-10T14:30:00' AS datetime2(0)), 6400, N'STAY'),
    (CAST(41002 AS bigint), CAST(40002 AS bigint), CAST('2026-07-20T18:20:00' AS datetime2(0)), 350, N'FNB'),
    (CAST(41003 AS bigint), CAST(40003 AS bigint), CAST('2026-07-25T11:00:00' AS datetime2(0)), -3000, N'REDEEM')
) AS source (ledger_id, member_id, occurred_at, point_delta, reason_code)
ON target.ledger_id = source.ledger_id
WHEN MATCHED THEN
    UPDATE SET member_id = source.member_id,
               occurred_at = source.occurred_at,
               point_delta = source.point_delta,
               reason_code = source.reason_code
WHEN NOT MATCHED THEN
    INSERT (ledger_id, member_id, occurred_at, point_delta, reason_code)
    VALUES (source.ledger_id, source.member_id, source.occurred_at, source.point_delta, source.reason_code);
GO
