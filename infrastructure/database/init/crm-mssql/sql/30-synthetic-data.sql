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
    SELECT 1
    FROM dbo.crm_point_transactions
    WHERE point_txn_id = 'CRM-POINT-0001'
)
BEGIN
    INSERT INTO dbo.crm_point_transactions (
        property_id,
        point_txn_id,
        member_no,
        event_at,
        txn_type,
        points_delta,
        related_source,
        related_id,
        data_period_status,
        is_forecast,
        is_synthetic,
        source_updated_at
    )
    VALUES (
        'SYNTHETIC_HOTEL_001',
        'CRM-POINT-0001',
        'CRM-MEMBER-0001',
        '2026-07-20T12:00:00',
        'EARN',
        12000,
        'PMS',
        'PMS-STAY-0001',
        'YTD_SYNTHETIC',
        0,
        1,
        '2026-07-28T04:30:00'
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM dbo.crm_customer_map
    WHERE customer_map_id = 'CRM-MAP-0001'
)
BEGIN
    INSERT INTO dbo.crm_customer_map (
        property_id,
        customer_map_id,
        member_no,
        pms_guest_id,
        pos_customer_ref,
        facility_user_ref,
        banquet_customer_id,
        valid_from,
        valid_to,
        mapping_status,
        mapping_confidence,
        is_synthetic,
        source_updated_at
    )
    VALUES (
        'SYNTHETIC_HOTEL_001',
        'CRM-MAP-0001',
        'CRM-MEMBER-0001',
        'PMS-GUEST-0001',
        'POS-CUSTOMER-0001',
        'FACILITY-USER-0001',
        'BANQUET-CUSTOMER-0001',
        '2025-01-15T09:00:00',
        NULL,
        'ACTIVE',
        1.0000,
        1,
        '2026-07-28T04:30:00'
    );
END;

COMMIT TRANSACTION;
GO
