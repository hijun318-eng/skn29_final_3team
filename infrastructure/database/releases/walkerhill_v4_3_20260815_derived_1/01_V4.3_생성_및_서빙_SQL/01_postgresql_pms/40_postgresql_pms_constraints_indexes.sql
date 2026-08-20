-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=PMS; script_type=CONSTRAINTS_INDEXES; execution_order=40
-- dependencies=33_postgresql_pms_folio_seed.sql; expected_rows=0
-- execution_default=NOT_RUN; destructive_operation=false
-- next=50_postgresql_pms_validation.sql

ALTER TABLE walkerhill_v4_3.hotel_entities ADD CONSTRAINT pk_v43_hotel_entities PRIMARY KEY(hotel_code);
ALTER TABLE walkerhill_v4_3.hotel_entities ADD CONSTRAINT fk_v43_hotel_parent FOREIGN KEY(parent_hotel_code) REFERENCES walkerhill_v4_3.hotel_entities(hotel_code);
ALTER TABLE walkerhill_v4_3.hotel_entities ADD CONSTRAINT ck_v43_hotel_capacity CHECK(synthetic_room_capacity>=0);
ALTER TABLE walkerhill_v4_3.calendar_daily ADD CONSTRAINT pk_v43_calendar PRIMARY KEY(business_date);
ALTER TABLE walkerhill_v4_3.calendar_daily ADD CONSTRAINT ck_v43_rate_day_type CHECK(room_rate_day_type IN ('SUN_THU','FRIDAY','SATURDAY'));
ALTER TABLE walkerhill_v4_3.evidence_registry ADD CONSTRAINT pk_v43_evidence PRIMARY KEY(evidence_id);
ALTER TABLE walkerhill_v4_3.event_master ADD CONSTRAINT pk_v43_event PRIMARY KEY(event_id);
ALTER TABLE walkerhill_v4_3.event_master ADD CONSTRAINT fk_v43_event_evidence FOREIGN KEY(evidence_id) REFERENCES walkerhill_v4_3.evidence_registry(evidence_id);
ALTER TABLE walkerhill_v4_3.event_master ADD CONSTRAINT ck_v43_event_dates CHECK(start_date<=end_date);
ALTER TABLE walkerhill_v4_3.hotel_event_effect ADD CONSTRAINT pk_v43_event_effect PRIMARY KEY(event_id,hotel_code,domain,metric_name);
ALTER TABLE walkerhill_v4_3.hotel_event_effect ADD CONSTRAINT fk_v43_effect_event FOREIGN KEY(event_id) REFERENCES walkerhill_v4_3.event_master(event_id);
ALTER TABLE walkerhill_v4_3.hotel_event_effect ADD CONSTRAINT fk_v43_effect_hotel FOREIGN KEY(hotel_code) REFERENCES walkerhill_v4_3.hotel_entities(hotel_code);
ALTER TABLE walkerhill_v4_3.hotel_event_effect ADD CONSTRAINT fk_v43_effect_evidence FOREIGN KEY(evidence_id) REFERENCES walkerhill_v4_3.evidence_registry(evidence_id);
ALTER TABLE walkerhill_v4_3.hotel_event_effect ADD CONSTRAINT ck_v43_effect_range CHECK(0<=uplift_min AND uplift_min<=uplift_mode AND uplift_mode<=uplift_max);

ALTER TABLE walkerhill_v4_3.pms_room_types ADD CONSTRAINT pk_v43_room_types PRIMARY KEY(hotel_code,room_type_code);
ALTER TABLE walkerhill_v4_3.pms_room_types ADD CONSTRAINT fk_v43_room_type_hotel FOREIGN KEY(hotel_code) REFERENCES walkerhill_v4_3.hotel_entities(hotel_code);
ALTER TABLE walkerhill_v4_3.pms_room_types ADD CONSTRAINT ck_v43_room_type_values CHECK(synthetic_room_count>0 AND synthetic_max_occupancy>0 AND synthetic_base_rate_krw>0);
ALTER TABLE walkerhill_v4_3.pms_rooms ADD CONSTRAINT pk_v43_rooms PRIMARY KEY(room_id);
ALTER TABLE walkerhill_v4_3.pms_rooms ADD CONSTRAINT uq_v43_room_tuple UNIQUE(room_id,hotel_code,room_type_code);
ALTER TABLE walkerhill_v4_3.pms_rooms ADD CONSTRAINT fk_v43_room_type FOREIGN KEY(hotel_code,room_type_code) REFERENCES walkerhill_v4_3.pms_room_types(hotel_code,room_type_code);
ALTER TABLE walkerhill_v4_3.pms_guests ADD CONSTRAINT pk_v43_guests PRIMARY KEY(guest_id);
ALTER TABLE walkerhill_v4_3.pms_room_out_of_order_periods ADD CONSTRAINT pk_v43_ooo PRIMARY KEY(out_of_order_id);
ALTER TABLE walkerhill_v4_3.pms_room_out_of_order_periods ADD CONSTRAINT fk_v43_ooo_room FOREIGN KEY(room_id) REFERENCES walkerhill_v4_3.pms_rooms(room_id);
ALTER TABLE walkerhill_v4_3.pms_room_out_of_order_periods ADD CONSTRAINT ck_v43_ooo_dates CHECK(started_at<ended_at);
ALTER TABLE walkerhill_v4_3.pms_room_inventory_daily ADD CONSTRAINT pk_v43_inventory PRIMARY KEY(hotel_code,business_date,room_type_code);
ALTER TABLE walkerhill_v4_3.pms_room_inventory_daily ADD CONSTRAINT fk_v43_inventory_type FOREIGN KEY(hotel_code,room_type_code) REFERENCES walkerhill_v4_3.pms_room_types(hotel_code,room_type_code);
ALTER TABLE walkerhill_v4_3.pms_room_inventory_daily ADD CONSTRAINT fk_v43_inventory_date FOREIGN KEY(business_date) REFERENCES walkerhill_v4_3.calendar_daily(business_date);
ALTER TABLE walkerhill_v4_3.pms_room_inventory_daily ADD CONSTRAINT ck_v43_inventory_capacity CHECK(physical_rooms>=0 AND out_of_order_rooms>=0 AND house_use_rooms>=0 AND out_of_order_rooms+house_use_rooms<=physical_rooms AND available_room_nights>=0 AND available_room_nights=physical_rooms-out_of_order_rooms-house_use_rooms);

ALTER TABLE walkerhill_v4_3.pms_reservations ADD CONSTRAINT pk_v43_reservations PRIMARY KEY(reservation_id);
ALTER TABLE walkerhill_v4_3.pms_reservations ADD CONSTRAINT fk_v43_res_guest FOREIGN KEY(guest_id) REFERENCES walkerhill_v4_3.pms_guests(guest_id);
ALTER TABLE walkerhill_v4_3.pms_reservations ADD CONSTRAINT fk_v43_res_room_type FOREIGN KEY(hotel_code,room_type_code) REFERENCES walkerhill_v4_3.pms_room_types(hotel_code,room_type_code);
ALTER TABLE walkerhill_v4_3.pms_reservations ADD CONSTRAINT fk_v43_res_room_tuple FOREIGN KEY(assigned_room_id,hotel_code,room_type_code) REFERENCES walkerhill_v4_3.pms_rooms(room_id,hotel_code,room_type_code);
-- booked_at와 로컬 checkin_date의 시간대 비교는 50번 validator에서 수행한다.
-- CHECK에는 세션 TimeZone에 따라 값이 달라질 수 있는 timestamptz/date 변환을 넣지 않는다.
ALTER TABLE walkerhill_v4_3.pms_reservations ADD CONSTRAINT ck_v43_res_dates CHECK(checkin_date<checkout_date);
ALTER TABLE walkerhill_v4_3.pms_reservations ADD CONSTRAINT ck_v43_res_money CHECK(quoted_room_rate>=0 AND discount_amount>=0 AND booked_amount>=0);
ALTER TABLE walkerhill_v4_3.pms_reservation_status_history ADD CONSTRAINT pk_v43_res_history PRIMARY KEY(status_history_id);
ALTER TABLE walkerhill_v4_3.pms_reservation_status_history ADD CONSTRAINT fk_v43_history_res FOREIGN KEY(reservation_id) REFERENCES walkerhill_v4_3.pms_reservations(reservation_id);
ALTER TABLE walkerhill_v4_3.pms_stays ADD CONSTRAINT pk_v43_stays PRIMARY KEY(stay_id);
ALTER TABLE walkerhill_v4_3.pms_stays ADD CONSTRAINT uq_v43_stay_reservation UNIQUE(reservation_id);
ALTER TABLE walkerhill_v4_3.pms_stays ADD CONSTRAINT uq_v43_stay_res_tuple UNIQUE(stay_id,reservation_id);
ALTER TABLE walkerhill_v4_3.pms_stays ADD CONSTRAINT fk_v43_stay_res FOREIGN KEY(reservation_id) REFERENCES walkerhill_v4_3.pms_reservations(reservation_id);
ALTER TABLE walkerhill_v4_3.pms_stays ADD CONSTRAINT fk_v43_stay_guest FOREIGN KEY(guest_id) REFERENCES walkerhill_v4_3.pms_guests(guest_id);
ALTER TABLE walkerhill_v4_3.pms_stays ADD CONSTRAINT fk_v43_stay_room_tuple FOREIGN KEY(room_id,hotel_code,room_type_code) REFERENCES walkerhill_v4_3.pms_rooms(room_id,hotel_code,room_type_code);
ALTER TABLE walkerhill_v4_3.pms_stays ADD CONSTRAINT ck_v43_stay_values CHECK(actual_checkin_at<actual_checkout_at AND occupied_room_nights>0 AND guest_count>0 AND room_revenue>=0 AND other_room_charges>=0);
ALTER TABLE walkerhill_v4_3.pms_stay_nights ADD CONSTRAINT pk_v43_stay_nights PRIMARY KEY(stay_id,business_date);
ALTER TABLE walkerhill_v4_3.pms_stay_nights ADD CONSTRAINT fk_v43_stay_night_tuple FOREIGN KEY(stay_id,reservation_id) REFERENCES walkerhill_v4_3.pms_stays(stay_id,reservation_id);
ALTER TABLE walkerhill_v4_3.pms_stay_nights ADD CONSTRAINT fk_v43_stay_night_date FOREIGN KEY(business_date) REFERENCES walkerhill_v4_3.calendar_daily(business_date);
ALTER TABLE walkerhill_v4_3.pms_stay_nights ADD CONSTRAINT fk_v43_stay_night_event FOREIGN KEY(event_id) REFERENCES walkerhill_v4_3.event_master(event_id);
ALTER TABLE walkerhill_v4_3.pms_stay_nights ADD CONSTRAINT ck_v43_stay_night_values CHECK(room_rate_day_type IN ('SUN_THU','FRIDAY','SATURDAY') AND gross_room_rate>=0 AND discount_amount>=0 AND net_room_revenue=gross_room_rate-discount_amount);
ALTER TABLE walkerhill_v4_3.pms_folio_postings ADD CONSTRAINT pk_v43_folio PRIMARY KEY(folio_posting_id);
ALTER TABLE walkerhill_v4_3.pms_folio_postings ADD CONSTRAINT fk_v43_folio_stay_tuple FOREIGN KEY(stay_id,reservation_id) REFERENCES walkerhill_v4_3.pms_stays(stay_id,reservation_id);
ALTER TABLE walkerhill_v4_3.pms_folio_postings ADD CONSTRAINT ck_v43_folio_equation CHECK(net_amount=gross_amount-discount_amount+service_charge_amount+tax_amount-refund_amount);
ALTER TABLE walkerhill_v4_3.pms_folio_postings ADD CONSTRAINT ck_v43_folio_source_pair CHECK((source_system IS NULL)=(source_transaction_id IS NULL));

CREATE INDEX ix_v43_reservation_dates ON walkerhill_v4_3.pms_reservations(hotel_code,checkin_date,checkout_date);
CREATE INDEX ix_v43_reservation_guest ON walkerhill_v4_3.pms_reservations(guest_id,booked_at);
CREATE INDEX ix_v43_stay_dates ON walkerhill_v4_3.pms_stays(hotel_code,actual_checkin_at,actual_checkout_at);
CREATE INDEX ix_v43_stay_night_date ON walkerhill_v4_3.pms_stay_nights(business_date,stay_id);
CREATE INDEX ix_v43_history_res_time ON walkerhill_v4_3.pms_reservation_status_history(reservation_id,status_at);
CREATE INDEX ix_v43_folio_stay ON walkerhill_v4_3.pms_folio_postings(stay_id,posted_at);
CREATE UNIQUE INDEX uq_v43_folio_source_transaction ON walkerhill_v4_3.pms_folio_postings(source_system,source_transaction_id) WHERE source_transaction_id IS NOT NULL;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='pms_readonly') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA walkerhill_v4_3 TO pms_readonly';
    EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA walkerhill_v4_3 TO pms_readonly';
  END IF;
END $$;
