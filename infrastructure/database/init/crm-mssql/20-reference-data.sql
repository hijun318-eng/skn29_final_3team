USE [$(CRM_DB_NAME)];
GO

MERGE crm.member_tier AS target
USING (VALUES
    (N'SILVER', N'Silver', 0),
    (N'GOLD', N'Gold', 10000),
    (N'PLATINUM', N'Platinum', 30000)
) AS source (tier_code, tier_name, minimum_points)
ON target.tier_code = source.tier_code
WHEN MATCHED THEN
    UPDATE SET tier_name = source.tier_name,
               minimum_points = source.minimum_points
WHEN NOT MATCHED THEN
    INSERT (tier_code, tier_name, minimum_points)
    VALUES (source.tier_code, source.tier_name, source.minimum_points);
GO
