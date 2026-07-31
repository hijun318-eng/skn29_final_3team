-- CRM DB (SQL Server) — 회원, 등급, 포인트, 고객 매핑
-- SQL Server는 docker-entrypoint-initdb.d 미지원.
-- 사용: docker exec answervice-crm /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P Answervice123! -i /init/crm-init.sql -C
-- 또는: docker exec answervice-crm /opt/mssql-tools/bin/sqlcmd -S localhost -U sa -P Answervice123! -i /init/crm-init.sql

CREATE DATABASE crm;
GO
USE crm;
GO

CREATE TABLE crm_members (
    member_no VARCHAR(36) PRIMARY KEY,
    property_id VARCHAR(64) DEFAULT 'SYNTHETIC_HOTEL_001',
    membership_grade VARCHAR(16) DEFAULT 'BASIC',
    points_balance INTEGER DEFAULT 0,
    member_status VARCHAR(16) DEFAULT 'ACTIVE',
    is_synthetic BIT DEFAULT 1
);

CREATE TABLE crm_member_grade_history (
    grade_history_id VARCHAR(36) PRIMARY KEY,
    member_no VARCHAR(36) NOT NULL,
    grade_code VARCHAR(16) DEFAULT 'BASIC',
    valid_from DATE NOT NULL,
    valid_to DATE,
    change_reason_code VARCHAR(24) DEFAULT 'JOIN',
    is_synthetic BIT DEFAULT 1
);

CREATE TABLE crm_customer_map (
    map_id VARCHAR(36) PRIMARY KEY,
    member_no VARCHAR(36) NOT NULL,
    pms_guest_id VARCHAR(36) NOT NULL,
    pos_customer_ref VARCHAR(36) DEFAULT '',
    is_synthetic BIT DEFAULT 1
);

INSERT INTO crm_members VALUES
('MEM-00000001','SYNTHETIC_HOTEL_001','GOLD',35000,'ACTIVE',1),
('MEM-00000002','SYNTHETIC_HOTEL_001','SILVER',12000,'ACTIVE',1),
('MEM-00000003','SYNTHETIC_HOTEL_001','VIP',80000,'ACTIVE',1),
('MEM-00000004','SYNTHETIC_HOTEL_001','GOLD',42000,'ACTIVE',1),
('MEM-00000005','SYNTHETIC_HOTEL_001','BASIC',3000,'ACTIVE',1),
('MEM-00000006','SYNTHETIC_HOTEL_001','SILVER',18000,'ACTIVE',1);

INSERT INTO crm_member_grade_history VALUES
('GH-001','MEM-00000001','BASIC','2025-03-15','2025-09-15','JOIN',1),
('GH-002','MEM-00000001','GOLD','2025-09-15',NULL,'UPGRADE',1),
('GH-003','MEM-00000002','BASIC','2025-06-20','2026-01-20','JOIN',1),
('GH-004','MEM-00000002','SILVER','2026-01-20',NULL,'UPGRADE',1),
('GH-005','MEM-00000003','BASIC','2024-12-01','2025-06-01','JOIN',1),
('GH-006','MEM-00000003','VIP','2025-06-01',NULL,'UPGRADE',1),
('GH-007','MEM-00000004','BASIC','2025-04-10','2025-10-10','JOIN',1),
('GH-008','MEM-00000004','GOLD','2025-10-10',NULL,'UPGRADE',1),
('GH-009','MEM-00000005','BASIC','2026-05-01',NULL,'JOIN',1),
('GH-010','MEM-00000006','BASIC','2025-08-15','2026-02-15','JOIN',1),
('GH-011','MEM-00000006','SILVER','2026-02-15',NULL,'UPGRADE',1);

INSERT INTO crm_customer_map VALUES
('MAP-001','MEM-00000001','GUEST-0001','POS-0001',1),
('MAP-002','MEM-00000002','GUEST-0002','POS-0002',1),
('MAP-003','MEM-00000003','GUEST-0003','POS-0003',1),
('MAP-004','MEM-00000004','GUEST-0004','POS-0004',1),
('MAP-005','MEM-00000005','GUEST-0005','POS-0005',1),
('MAP-006','MEM-00000006','GUEST-0006','POS-0006',1);
GO
