-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=PMS; script_type=FOLIO_SEED; execution_order=33
-- dependencies=32_postgresql_pms_status_stay_seed.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=501248; execution_default=NOT_RUN; destructive_operation=false
-- assumption=service/tax decomposition is synthetic accounting, not Walkerhill policy
-- next=40_postgresql_pms_constraints_indexes.sql

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM walkerhill_v4_3.pms_folio_postings) THEN
    RAISE EXCEPTION 'candidate folio table must be empty';
  END IF;
END $$;

WITH charges AS (
  SELECT s.stay_id,s.reservation_id,s.actual_checkout_at AS posted_at,'ROOM_CHARGE'::varchar AS posting_type,
         NULL::varchar AS source_system,NULL::varchar AS source_transaction_id,s.room_revenue AS total_amount
  FROM walkerhill_v4_3.pms_stays s
  UNION ALL
  SELECT s.stay_id,s.reservation_id,s.actual_checkout_at,'OTHER_ROOM_CHARGE',NULL,NULL,
         s.other_room_charges-CASE WHEN s.stay_id LIKE 'S_JOURNEY_%' THEN
           (SELECT sum(walkerhill_v4_3.v43_journey_pos_amount(substring(s.stay_id,11)::int,meal_no))
            FROM generate_series(1,3) meal_no) ELSE 0 END
  FROM walkerhill_v4_3.pms_stays s WHERE s.other_room_charges>0
  UNION ALL
  SELECT s.stay_id,s.reservation_id,
         (((s.actual_checkin_at AT TIME ZONE 'Asia/Seoul')::date
            +CASE WHEN meal_no=1 THEN 0 ELSE 1 END)::timestamp
            +CASE meal_no WHEN 1 THEN TIME '19:15' WHEN 2 THEN TIME '08:15' ELSE TIME '19:15' END) AT TIME ZONE 'Asia/Seoul',
         'POS_ROOM_CHARGE','POS',
         'O_'||lpad((((substring(s.stay_id,11)::int-1)*3)+meal_no)::text,10,'0'),
         walkerhill_v4_3.v43_journey_pos_amount(substring(s.stay_id,11)::int,meal_no)
  FROM walkerhill_v4_3.pms_stays s CROSS JOIN generate_series(1,3) meal_no
  WHERE s.stay_id LIKE 'S_JOURNEY_%'
), decomposed AS (
  SELECT c.*,round(c.total_amount/1.21,0) AS gross_amount
  FROM charges c
), final_amounts AS (
  SELECT d.*,round(d.gross_amount*0.10,0) AS service_amount,
         d.total_amount-d.gross_amount-round(d.gross_amount*0.10,0) AS tax_amount
  FROM decomposed d
)
INSERT INTO walkerhill_v4_3.pms_folio_postings
(folio_posting_id,stay_id,reservation_id,posted_at,posting_type,source_system,source_transaction_id,gross_amount,discount_amount,
 service_charge_amount,tax_amount,refund_amount,net_amount,currency_code,posting_status,is_synthetic)
SELECT 'FP_'||substr(encode(sha256(convert_to(stay_id||'|'||posting_type||'|'||coalesce(source_transaction_id,''),'UTF8')),'hex'),1,30),
       stay_id,reservation_id,posted_at,posting_type,source_system,source_transaction_id,gross_amount,0,service_amount,tax_amount,0,total_amount,
       'KRW','POSTED',true
FROM final_amounts;
