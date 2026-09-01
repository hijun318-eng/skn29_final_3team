\set ON_ERROR_STOP on

-- 운영 PMS에서 cutoff 종료 시점에 실제로 관측한 D+1~D+7 신호만 보존한다.
-- 과거 최종 상태를 이용한 backfill은 허용하지 않으며 INSERT 이후 수정·삭제할 수 없다.
BEGIN;

CREATE SCHEMA IF NOT EXISTS ml_evaluation;

SELECT format('CREATE ROLE %I NOLOGIN', :'snapshot_writer_role')
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = :'snapshot_writer_role'
) \gexec

CREATE TABLE IF NOT EXISTS ml_evaluation.room_demand_signal_snapshot (
    property_id text NOT NULL,
    room_type_code text NOT NULL,
    cutoff_date date NOT NULL,
    target_date date NOT NULL,
    horizon_days smallint NOT NULL,
    target_sellable_rooms double precision NOT NULL,
    target_out_of_order_rooms double precision NOT NULL,
    booking_on_hand double precision NOT NULL,
    booking_on_hand_ratio double precision NOT NULL,
    booking_pickup_1d double precision NOT NULL,
    booking_pickup_7d double precision NOT NULL,
    booking_pickup_acceleration double precision NOT NULL,
    cancellations_on_hand double precision NOT NULL,
    cancellations_7d double precision NOT NULL,
    net_booking_pickup_7d double precision NOT NULL,
    banquet_room_nights_on_hand double precision NOT NULL,
    event_count double precision NOT NULL,
    event_demand_uplift double precision NOT NULL,
    reservation_as_of_at timestamptz NOT NULL,
    capacity_as_of_at timestamptz NOT NULL,
    event_as_of_at timestamptz NOT NULL,
    signal_source_kind text NOT NULL,
    signal_is_synthetic boolean NOT NULL,
    captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    source_batch_id text NOT NULL,
    source_payload_sha256 text NOT NULL,
    PRIMARY KEY (
        property_id,
        room_type_code,
        cutoff_date,
        target_date,
        horizon_days
    ),
    UNIQUE (source_batch_id, property_id, room_type_code, target_date),
    CHECK (btrim(property_id) <> ''),
    CHECK (btrim(room_type_code) <> ''),
    CHECK (target_date = cutoff_date + horizon_days),
    CHECK (horizon_days BETWEEN 1 AND 7),
    CHECK (target_sellable_rooms > 0),
    CHECK (target_out_of_order_rooms >= 0),
    CHECK (booking_on_hand >= 0),
    CHECK (booking_on_hand_ratio >= 0),
    CHECK (booking_pickup_1d >= 0),
    CHECK (booking_pickup_7d >= 0),
    CHECK (cancellations_on_hand >= 0),
    CHECK (cancellations_7d >= 0),
    CHECK (banquet_room_nights_on_hand >= 0),
    CHECK (event_count >= 0),
    CHECK (event_demand_uplift >= 0),
    CHECK (booking_on_hand <= target_sellable_rooms),
    CHECK (
        abs(
            booking_on_hand_ratio
            - booking_on_hand / target_sellable_rooms
        ) <= 0.000001
    ),
    CHECK (
        reservation_as_of_at
        <= (cutoff_date + 1)::timestamp AT TIME ZONE 'Asia/Seoul'
    ),
    CHECK (
        capacity_as_of_at
        <= (cutoff_date + 1)::timestamp AT TIME ZONE 'Asia/Seoul'
    ),
    CHECK (
        event_as_of_at
        <= (cutoff_date + 1)::timestamp AT TIME ZONE 'Asia/Seoul'
    ),
    CHECK (
        captured_at
        >= (cutoff_date + 1)::timestamp AT TIME ZONE 'Asia/Seoul'
    ),
    CHECK (
        captured_at
        <= (cutoff_date + 1)::timestamp AT TIME ZONE 'Asia/Seoul'
            + interval '6 hours'
    ),
    CHECK (captured_at >= reservation_as_of_at),
    CHECK (captured_at >= capacity_as_of_at),
    CHECK (captured_at >= event_as_of_at),
    CHECK (signal_source_kind = 'OBSERVED_PIT'),
    CHECK (NOT signal_is_synthetic),
    CHECK (source_batch_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'),
    CHECK (source_payload_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_room_demand_signal_snapshot_cutoff
ON ml_evaluation.room_demand_signal_snapshot (
    cutoff_date,
    property_id,
    room_type_code,
    horizon_days
);

CREATE OR REPLACE FUNCTION ml_evaluation.reject_signal_snapshot_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'room_demand_signal_snapshot is append-only; mutation is forbidden';
END;
$$;

CREATE OR REPLACE FUNCTION ml_evaluation.validate_live_signal_snapshot_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    database_now timestamptz := clock_timestamp();
BEGIN
    IF NEW.captured_at < database_now - interval '10 minutes'
       OR NEW.captured_at > database_now + interval '2 minutes' THEN
        RAISE EXCEPTION
            'snapshot captured_at must match the live database clock; historical backfill is forbidden';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION ml_evaluation.validate_complete_signal_snapshot_batch()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    cutoff_count integer;
    captured_count integer;
    hash_count integer;
BEGIN
    SELECT
        count(DISTINCT cutoff_date),
        count(DISTINCT captured_at),
        count(DISTINCT source_payload_sha256)
    INTO cutoff_count, captured_count, hash_count
    FROM ml_evaluation.room_demand_signal_snapshot
    WHERE source_batch_id = NEW.source_batch_id;

    IF cutoff_count <> 1 OR captured_count <> 1 OR hash_count <> 1 THEN
        RAISE EXCEPTION
            'snapshot batch must have one cutoff, capture time, and source hash';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM ml_evaluation.room_demand_signal_snapshot
        WHERE source_batch_id = NEW.source_batch_id
        GROUP BY cutoff_date, property_id, room_type_code
        HAVING count(*) <> 7
            OR count(DISTINCT horizon_days) <> 7
            OR min(horizon_days) <> 1
            OR max(horizon_days) <> 7
    ) THEN
        RAISE EXCEPTION
            'snapshot batch must contain complete D+1 through D+7 rows';
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_live_signal_snapshot_insert
ON ml_evaluation.room_demand_signal_snapshot;
CREATE TRIGGER trg_validate_live_signal_snapshot_insert
BEFORE INSERT ON ml_evaluation.room_demand_signal_snapshot
FOR EACH ROW EXECUTE FUNCTION ml_evaluation.validate_live_signal_snapshot_insert();

DROP TRIGGER IF EXISTS trg_validate_complete_signal_snapshot_batch
ON ml_evaluation.room_demand_signal_snapshot;
CREATE CONSTRAINT TRIGGER trg_validate_complete_signal_snapshot_batch
AFTER INSERT ON ml_evaluation.room_demand_signal_snapshot
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION ml_evaluation.validate_complete_signal_snapshot_batch();

DROP TRIGGER IF EXISTS trg_reject_signal_snapshot_update_delete
ON ml_evaluation.room_demand_signal_snapshot;
CREATE TRIGGER trg_reject_signal_snapshot_update_delete
BEFORE UPDATE OR DELETE ON ml_evaluation.room_demand_signal_snapshot
FOR EACH ROW EXECUTE FUNCTION ml_evaluation.reject_signal_snapshot_mutation();

DROP TRIGGER IF EXISTS trg_reject_signal_snapshot_truncate
ON ml_evaluation.room_demand_signal_snapshot;
CREATE TRIGGER trg_reject_signal_snapshot_truncate
BEFORE TRUNCATE ON ml_evaluation.room_demand_signal_snapshot
FOR EACH STATEMENT EXECUTE FUNCTION ml_evaluation.reject_signal_snapshot_mutation();

CREATE OR REPLACE VIEW
ml_evaluation.room_demand_point_in_time_signals_observed
WITH (security_barrier = true)
AS
SELECT
    property_id,
    room_type_code,
    cutoff_date,
    target_date,
    horizon_days,
    target_sellable_rooms,
    target_out_of_order_rooms,
    booking_on_hand,
    booking_on_hand_ratio,
    booking_pickup_1d,
    booking_pickup_7d,
    booking_pickup_acceleration,
    cancellations_on_hand,
    cancellations_7d,
    net_booking_pickup_7d,
    banquet_room_nights_on_hand,
    event_count,
    event_demand_uplift,
    reservation_as_of_at,
    capacity_as_of_at,
    event_as_of_at,
    signal_source_kind,
    signal_is_synthetic
FROM ml_evaluation.room_demand_signal_snapshot
WHERE signal_source_kind = 'OBSERVED_PIT'
  AND NOT signal_is_synthetic;

GRANT USAGE ON SCHEMA ml_evaluation
TO :"snapshot_writer_role", :"readonly_role";
GRANT INSERT, SELECT
ON ml_evaluation.room_demand_signal_snapshot
TO :"snapshot_writer_role";
GRANT SELECT
ON ml_evaluation.room_demand_point_in_time_signals_observed
TO :"readonly_role";
REVOKE UPDATE, DELETE, TRUNCATE
ON ml_evaluation.room_demand_signal_snapshot
FROM :"snapshot_writer_role", :"readonly_role", PUBLIC;

COMMENT ON TABLE ml_evaluation.room_demand_signal_snapshot IS
    '실제 운영 cutoff 종료 시점의 D+1~D+7 신호만 보존하는 append-only 원장. 합성 및 과거 최종값 backfill 금지';
COMMENT ON VIEW ml_evaluation.room_demand_point_in_time_signals_observed IS
    '시점과 비합성 출처가 증명된 운영 수요예측 신호만 제공하는 runtime view';

COMMIT;
