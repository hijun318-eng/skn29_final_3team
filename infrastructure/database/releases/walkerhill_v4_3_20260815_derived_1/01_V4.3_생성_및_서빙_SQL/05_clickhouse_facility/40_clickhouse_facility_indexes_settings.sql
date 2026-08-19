-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=ClickHouse 24.8+; domain=FACILITY; script_type=INDEX; execution_order=40
-- dependency=20..33 seed scripts; expected_rows=0; execution_default=NOT_RUN
-- note=ClickHouse does not enforce cross-table foreign keys; 50 validation provides logical integrity gates

ALTER TABLE walkerhill_v4_3.facility_usage_events ADD INDEX ix_usage_event_code event_id TYPE set(100) GRANULARITY 4;
ALTER TABLE walkerhill_v4_3.facility_usage_events MATERIALIZE INDEX ix_usage_event_code;
ALTER TABLE walkerhill_v4_3.facility_incidents ADD INDEX ix_incident_severity severity TYPE set(10) GRANULARITY 4;
ALTER TABLE walkerhill_v4_3.facility_incidents MATERIALIZE INDEX ix_incident_severity;
-- 외부 인증 주체는 생성하지 않는다. facility_readonly GRANT는 운영 계정 프로비저닝 후 별도 적용한다.
