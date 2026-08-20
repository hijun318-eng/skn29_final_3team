-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=banquet_db; target_schema=walkerhill_v4_3
-- domain=BANQUET; script_type=CONSTRAINTS_INDEXES; execution_order=40
-- dependencies=32_postgresql_banquet_revenue_block_seed.sql; expected_rows=0
-- execution_default=NOT_RUN; destructive_operation=false
-- next=50_postgresql_banquet_validation.sql

ALTER TABLE walkerhill_v4_3.banquet_venues ADD CONSTRAINT pk_v43_venues PRIMARY KEY(venue_id);
ALTER TABLE walkerhill_v4_3.banquet_venues ADD CONSTRAINT ck_v43_venue_capacity CHECK(synthetic_capacity>0);
ALTER TABLE walkerhill_v4_3.banquet_bookings ADD CONSTRAINT pk_v43_bookings PRIMARY KEY(banquet_event_id);
ALTER TABLE walkerhill_v4_3.banquet_bookings ADD CONSTRAINT uq_v43_booking_venue_slot UNIQUE(venue_id,event_date,event_slot);
ALTER TABLE walkerhill_v4_3.banquet_bookings ADD CONSTRAINT fk_v43_booking_venue FOREIGN KEY(venue_id) REFERENCES walkerhill_v4_3.banquet_venues(venue_id);
ALTER TABLE walkerhill_v4_3.banquet_bookings ADD CONSTRAINT ck_v43_booking_dates CHECK(extract(epoch FROM inquiry_at)<extract(epoch FROM starts_at) AND inquiry_at<=quoted_at AND quoted_at<=confirmed_at AND (cancelled_at IS NULL OR confirmed_at<=cancelled_at) AND starts_at<ends_at);
ALTER TABLE walkerhill_v4_3.banquet_bookings ADD CONSTRAINT ck_v43_booking_values CHECK(expected_guests>0 AND (actual_attendees IS NULL OR actual_attendees>=0) AND quoted_amount>=contracted_amount AND contracted_amount>=0 AND deposit_amount>=0 AND balance_amount>=0 AND cancellation_fee_amount>=0 AND ((booking_status='COMPLETED' AND deposit_amount+balance_amount=contracted_amount AND cancellation_fee_amount=0) OR (booking_status='CANCELLED' AND balance_amount=0 AND cancellation_fee_amount<=deposit_amount)));
ALTER TABLE walkerhill_v4_3.banquet_status_history ADD CONSTRAINT pk_v43_banquet_history PRIMARY KEY(status_history_id);
ALTER TABLE walkerhill_v4_3.banquet_status_history ADD CONSTRAINT fk_v43_banquet_history_event FOREIGN KEY(banquet_event_id) REFERENCES walkerhill_v4_3.banquet_bookings(banquet_event_id);
ALTER TABLE walkerhill_v4_3.banquet_revenue_lines ADD CONSTRAINT pk_v43_banquet_revenue PRIMARY KEY(revenue_line_id);
ALTER TABLE walkerhill_v4_3.banquet_revenue_lines ADD CONSTRAINT fk_v43_revenue_event FOREIGN KEY(banquet_event_id) REFERENCES walkerhill_v4_3.banquet_bookings(banquet_event_id);
ALTER TABLE walkerhill_v4_3.banquet_revenue_lines ADD CONSTRAINT ck_v43_revenue_equation CHECK(recognized_amount=gross_amount-discount_amount-reversal_amount AND cost_amount>=0);
ALTER TABLE walkerhill_v4_3.banquet_room_blocks ADD CONSTRAINT pk_v43_room_blocks PRIMARY KEY(room_block_id);
ALTER TABLE walkerhill_v4_3.banquet_room_blocks ADD CONSTRAINT fk_v43_block_event FOREIGN KEY(banquet_event_id) REFERENCES walkerhill_v4_3.banquet_bookings(banquet_event_id);
ALTER TABLE walkerhill_v4_3.banquet_room_blocks ADD CONSTRAINT ck_v43_block_values CHECK(checkin_date<checkout_date AND reserved_room_nights>=0 AND pickup_room_nights BETWEEN 0 AND reserved_room_nights);
CREATE INDEX ix_v43_banquet_event_date ON walkerhill_v4_3.banquet_bookings(event_date,venue_id,booking_status);
CREATE INDEX ix_v43_banquet_history_time ON walkerhill_v4_3.banquet_status_history(banquet_event_id,status_at);
CREATE INDEX ix_v43_banquet_revenue_date ON walkerhill_v4_3.banquet_revenue_lines(recognized_date,banquet_event_id);

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='banquet_readonly') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA walkerhill_v4_3 TO banquet_readonly';
    EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA walkerhill_v4_3 TO banquet_readonly';
  END IF;
END $$;
