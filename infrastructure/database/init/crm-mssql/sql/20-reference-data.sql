SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

USE [$(CRM_DATABASE)];
GO
SET XACT_ABORT ON;
SET NOCOUNT ON;
GO

BEGIN TRANSACTION;

IF NOT EXISTS (
    SELECT 1 FROM dbo.crm_members WHERE member_no = 'CRM-MEMBER-0001'
)
BEGIN
    INSERT INTO dbo.crm_members (
        property_id,
        member_no,
        membership_grade,
        points_balance,
        joined_at,
        member_status,
        data_period_status,
        is_forecast,
        is_synthetic,
        source_updated_at
    )
    VALUES (
        'SYNTHETIC_HOTEL_001',
        'CRM-MEMBER-0001',
        'GOLD',
        12000,
        '2025-01-15T09:00:00',
        'ACTIVE',
        'SYNTHETIC_ACTUAL_LIKE',
        0,
        1,
        '2026-07-28T04:20:00'
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM dbo.crm_member_grade_history
    WHERE grade_history_id = 'CRM-GRADE-0001'
)
BEGIN
    INSERT INTO dbo.crm_member_grade_history (
        property_id,
        grade_history_id,
        member_no,
        grade_code,
        valid_from,
        valid_to,
        change_reason_code,
        is_synthetic,
        source_updated_at
    )
    VALUES (
        'SYNTHETIC_HOTEL_001',
        'CRM-GRADE-0001',
        'CRM-MEMBER-0001',
        'GOLD',
        '2025-01-15T09:00:00',
        NULL,
        'JOIN',
        1,
        '2026-07-28T04:20:00'
    );
END;

COMMIT TRANSACTION;
GO
