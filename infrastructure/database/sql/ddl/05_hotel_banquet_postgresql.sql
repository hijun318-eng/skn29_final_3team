-- 책임: banquet source의 빈 PostgreSQL schema와 관계 제약을 생성한다. 실제 업무
-- 데이터가 없더라도 임의 seed를 만들지 않고 catalog를 빈 상태로 노출한다.
-- source_id=banquet; engine=PostgreSQL; database=banquet_db
-- ingestion_role=banquet_ingest; query_role=banquet_readonly
-- datahub_platform_instance=banquet_db; trino_catalog=banquet
-- schema_version=1.0.0
\set ON_ERROR_STOP on
SET timezone = 'Asia/Seoul';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'banquet_ingest') THEN
        CREATE ROLE banquet_ingest NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'banquet_readonly') THEN
        CREATE ROLE banquet_readonly NOLOGIN;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS banquet_bookings (
    property_id varchar(64) NOT NULL,
    banquet_event_id varchar(36) PRIMARY KEY,
    customer_id varchar(36) NOT NULL,
    inquiry_at timestamptz NOT NULL,
    quoted_at timestamptz,
    confirmed_at timestamptz,
    cancelled_at timestamptz,
    event_date date NOT NULL,
    product_code varchar(32) NOT NULL,
    product_category varchar(32) NOT NULL CHECK (product_category IN ('WEDDING','CONFERENCE','MEETING','CORPORATE_EVENT','SOCIAL_EVENT')),
    expected_guests integer NOT NULL CHECK (expected_guests >= 0),
    actual_attendees integer CHECK (actual_attendees >= 0),
    lead_source varchar(24) NOT NULL,
    sales_owner_team varchar(32) NOT NULL,
    booking_status varchar(20) NOT NULL CHECK (booking_status IN ('INQUIRY','QUOTED','TENTATIVE','CONFIRMED','CANCELLED','COMPLETED')),
    contracted_amount numeric(14,2) NOT NULL CHECK (contracted_amount >= 0),
    cancellation_fee numeric(14,2) NOT NULL CHECK (cancellation_fee BETWEEN 0 AND contracted_amount),
    reserved_room_block_count integer NOT NULL CHECK (reserved_room_block_count >= 0),
    expected_room_nights integer NOT NULL CHECK (expected_room_nights >= 0),
    group_checkin_date date,
    group_checkout_date date,
    released_room_count integer NOT NULL CHECK (released_room_count >= 0),
    pickup_room_count integer NOT NULL CHECK (pickup_room_count >= 0),
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at timestamptz NOT NULL,
    CHECK (inquiry_at <= source_updated_at),
    CHECK (quoted_at IS NULL OR (quoted_at >= inquiry_at AND quoted_at <= source_updated_at)),
    CHECK (confirmed_at IS NULL OR (confirmed_at >= quoted_at AND confirmed_at <= source_updated_at)),
    CHECK (cancelled_at IS NULL OR (cancelled_at >= inquiry_at AND cancelled_at <= source_updated_at)),
    CHECK (group_checkout_date IS NULL OR group_checkin_date IS NULL OR group_checkout_date > group_checkin_date),
    CHECK (released_room_count <= reserved_room_block_count),
    CHECK (pickup_room_count <= reserved_room_block_count - released_room_count),
    CHECK (expected_room_nights >= pickup_room_count)
);

CREATE TABLE IF NOT EXISTS banquet_revenue (
    property_id varchar(64) NOT NULL,
    revenue_id varchar(36) PRIMARY KEY,
    banquet_event_id varchar(36) NOT NULL REFERENCES banquet_bookings(banquet_event_id),
    recognized_date date NOT NULL,
    product_code varchar(32) NOT NULL,
    product_category varchar(32) NOT NULL CHECK (product_category IN ('VENUE','FOOD_BEVERAGE','EQUIPMENT','DECORATION','SERVICE','ACCOMMODATION_PACKAGE')),
    revenue_amount numeric(14,2) NOT NULL CHECK (revenue_amount >= 0),
    reversal_amount numeric(14,2) NOT NULL CHECK (reversal_amount >= 0),
    cost_amount numeric(14,2) NOT NULL CHECK (cost_amount >= 0),
    revenue_status varchar(16) NOT NULL CHECK (revenue_status IN ('EXPECTED','RECOGNIZED','REVERSED')),
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at timestamptz NOT NULL,
    CHECK (
        (revenue_status IN ('EXPECTED','RECOGNIZED') AND revenue_amount > 0 AND reversal_amount = 0)
        OR
        (revenue_status = 'REVERSED' AND revenue_amount = 0 AND reversal_amount > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_banquet_booking_date_status ON banquet_bookings(event_date, booking_status);
CREATE INDEX IF NOT EXISTS idx_banquet_booking_customer_date ON banquet_bookings(customer_id, event_date);
CREATE INDEX IF NOT EXISTS idx_banquet_revenue_event_date ON banquet_revenue(banquet_event_id, recognized_date);

CREATE TABLE IF NOT EXISTS schema_version (version varchar(32) PRIMARY KEY);
-- This value versions schema shape only; release provenance is supplied by the
-- ingestion control plane after source data has actually been loaded.
INSERT INTO schema_version(version) VALUES ('1.0.0') ON CONFLICT (version) DO NOTHING;

GRANT SELECT, INSERT, UPDATE, DELETE ON banquet_bookings, banquet_revenue TO banquet_ingest;
GRANT SELECT ON banquet_bookings, banquet_revenue TO banquet_readonly;
GRANT SELECT ON schema_version TO banquet_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM banquet_readonly;
REVOKE CREATE ON SCHEMA public FROM banquet_readonly;

COMMENT ON TABLE banquet_bookings IS 'Banquet inquiry, booking, event, and room block';
COMMENT ON TABLE banquet_revenue IS 'Expected, recognized, and reversed banquet revenue';
COMMENT ON COLUMN banquet_bookings.customer_id IS 'Banquet system local customer reference';
COMMENT ON COLUMN banquet_revenue.reversal_amount IS 'Separate reversal amount; never negative revenue';

SELECT count(*) AS banquet_table_count
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
