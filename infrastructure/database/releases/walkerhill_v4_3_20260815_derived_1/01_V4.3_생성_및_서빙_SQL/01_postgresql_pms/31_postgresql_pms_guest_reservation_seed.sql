-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=PMS; script_type=GUEST_RESERVATION_SEED; execution_order=31
-- dependencies=30_postgresql_pms_inventory_seed.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=402466; execution_default=NOT_RUN; destructive_operation=false
-- assumption=guest identities, LOS, lead time, rates, channels, cancellation and demand are synthetic
-- next=32_postgresql_pms_status_stay_seed.sql

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM walkerhill_v4_3.pms_guests)
     OR EXISTS (SELECT 1 FROM walkerhill_v4_3.pms_reservations) THEN
    RAISE EXCEPTION 'candidate guest and reservation tables must be empty';
  END IF;
END $$;

INSERT INTO walkerhill_v4_3.pms_guests
(guest_id,guest_segment,country_group,created_at,is_synthetic)
SELECT 'G' || lpad(n::text,9,'0'),
       CASE WHEN u_seg < 0.57 THEN 'LEISURE' WHEN u_seg < 0.82 THEN 'BUSINESS' WHEN u_seg < 0.95 THEN 'GROUP' ELSE 'VIP' END,
       CASE WHEN u_country < 0.70 THEN 'DOMESTIC' WHEN u_country < 0.84 THEN 'NORTHEAST_ASIA'
            WHEN u_country < 0.93 THEN 'SOUTHEAST_ASIA' ELSE 'OTHER_REGION' END,
       (DATE '2022-01-01' + floor(u_created*730)::int)::timestamp AT TIME ZONE 'Asia/Seoul',true
FROM generate_series(1,100000) n
CROSS JOIN LATERAL (SELECT walkerhill_v4_3.v43_u01('guest-segment|'||n) u_seg,
                           walkerhill_v4_3.v43_u01('guest-country|'||n) u_country,
                           walkerhill_v4_3.v43_u01('guest-created|'||n) u_created) u;

WITH RECURSIVE schedule(room_id,hotel_code,room_type_code,stay_seq,checkin_date,los) AS (
  SELECT r.room_id,r.hotel_code,r.room_type_code,1,
         DATE '2024-01-01' + floor(walkerhill_v4_3.v43_u01('initial|'||r.room_id)*3)::int,
         1 + floor(walkerhill_v4_3.v43_u01('los|'||r.room_id||'|1')*3)::int
  FROM walkerhill_v4_3.pms_rooms r
  WHERE r.room_id NOT IN (
    'GRAND-G_DELUXE-0355','GRAND-G_DELUXE-0356','GRAND-G_DELUXE-0357','GRAND-G_DELUXE-0358','GRAND-G_DELUXE-0359','GRAND-G_DELUXE-0360',
    'VISTA-V_DELUXE-0185','VISTA-V_DELUXE-0186','VISTA-V_DELUXE-0187','VISTA-V_DELUXE-0188','VISTA-V_DELUXE-0189','VISTA-V_DELUXE-0190',
    'DOUGLAS-D_DELUXE-0040','DOUGLAS-D_DELUXE-0041','DOUGLAS-D_DELUXE-0042','DOUGLAS-D_DELUXE-0043','DOUGLAS-D_DELUXE-0044','DOUGLAS-D_DELUXE-0045')
  UNION ALL
  SELECT s.room_id,s.hotel_code,s.room_type_code,s.stay_seq+1,n.next_checkin,
         1 + floor(walkerhill_v4_3.v43_u01('los|'||s.room_id||'|'||(s.stay_seq+1))*3)::int
  FROM schedule s
  CROSS JOIN LATERAL (
    SELECT s.checkin_date+s.los+
      floor(walkerhill_v4_3.v43_u01('gap|'||s.room_id||'|'||(s.stay_seq+1))*
        greatest(1,CASE s.hotel_code WHEN 'GRAND' THEN 3 WHEN 'VISTA' THEN 4 ELSE 5 END
          -CASE WHEN extract(isodow FROM s.checkin_date+s.los) IN (5,6) THEN 1 ELSE 0 END))::int AS next_checkin
  ) n
  WHERE n.next_checkin < DATE '2026-09-01'
), eligible AS (
  SELECT s.*,rt.synthetic_base_rate_krw
  FROM schedule s
  JOIN walkerhill_v4_3.pms_room_types rt USING(hotel_code,room_type_code)
  WHERE s.checkin_date+s.los <= DATE '2026-09-01'
    AND NOT EXISTS (
      SELECT 1 FROM walkerhill_v4_3.pms_room_out_of_order_periods o
      WHERE o.room_id=s.room_id
        AND tstzrange(o.started_at,o.ended_at,'[)') &&
            tstzrange((s.checkin_date::timestamp+TIME '15:00') AT TIME ZONE 'Asia/Seoul',
                      ((s.checkin_date+s.los)::timestamp+TIME '12:00') AT TIME ZONE 'Asia/Seoul','[)')
    )
    AND NOT EXISTS (
      SELECT 1
      FROM generate_series(s.checkin_date,s.checkin_date+s.los-1,INTERVAL '1 day') hd
      WHERE s.room_id=(SELECT min(r2.room_id) FROM walkerhill_v4_3.pms_rooms r2
                       WHERE r2.hotel_code=s.hotel_code AND r2.room_type_code=s.room_type_code)
        AND walkerhill_v4_3.v43_u01('house-use|'||s.hotel_code||'|'||s.room_type_code||'|'||to_char(hd::date,'YYYY-MM-DD'))<0.012
    )
), rate_inputs AS (
  SELECT e.*,
         1+floor(walkerhill_v4_3.v43_u01('lead|'||room_id||'|'||stay_seq)*90)::int AS lead_days,
         floor(walkerhill_v4_3.v43_u01('discount|'||room_id||'|'||stay_seq)*4)::int*0.05 AS discount_rate,
         0.92+0.18*walkerhill_v4_3.v43_u01('rate|'||room_id||'|'||to_char(checkin_date,'YYYY-MM-DD')) AS rate_noise
  FROM eligible e
), priced AS (
  SELECT p.*,round(a.gross_total/p.los,-3) AS quoted_rate,a.discount_total,a.booked_total
  FROM rate_inputs p
  CROSS JOIN LATERAL (
    SELECT sum(n.gross_rate) gross_total,
           sum(n.gross_rate-round(n.gross_rate*(1-p.discount_rate),0)) discount_total,
           sum(round(n.gross_rate*(1-p.discount_rate),0)) booked_total
    FROM (
      SELECT round((p.synthetic_base_rate_krw
        * CASE c.season_code WHEN 'SUMMER' THEN 1.12 WHEN 'AUTUMN' THEN 1.10 WHEN 'WINTER' THEN 1.05 ELSE 1.00 END
        * CASE c.room_rate_day_type WHEN 'FRIDAY' THEN 1.10 WHEN 'SATURDAY' THEN 1.28 ELSE 1.00 END
        * CASE WHEN c.is_holiday THEN 1.18 ELSE 1.00 END
        * (1+coalesce(ev.uplift_mode,0))*p.rate_noise)/1000,-0)*1000 AS gross_rate
      FROM generate_series(p.checkin_date,p.checkin_date+p.los-1,INTERVAL '1 day') d
      JOIN walkerhill_v4_3.calendar_daily c ON c.business_date=d::date
      LEFT JOIN LATERAL (
        SELECT he.uplift_mode
        FROM walkerhill_v4_3.event_master em JOIN walkerhill_v4_3.hotel_event_effect he USING(event_id)
        WHERE he.hotel_code=p.hotel_code AND he.domain='ROOMS' AND he.metric_name='ADR'
          AND d::date BETWEEN em.start_date-he.lead_days AND em.end_date+he.lag_days
        ORDER BY he.uplift_mode DESC,em.event_id LIMIT 1
      ) ev ON true
    ) n
  ) a
)
INSERT INTO walkerhill_v4_3.pms_reservations
(reservation_id,guest_id,hotel_code,room_type_code,assigned_room_id,booked_at,checkin_date,checkout_date,
 booking_channel,market_segment,reservation_status,cancelled_at,cancellation_reason_code,banquet_event_id,
 quoted_room_rate,discount_amount,booked_amount,currency_code,is_forecast,is_synthetic)
SELECT 'R_'||substr(encode(sha256(convert_to(room_id||'|'||to_char(checkin_date,'YYYY-MM-DD'),'UTF8')),'hex'),1,30),
       'G'||lpad((1+floor(walkerhill_v4_3.v43_u01('guest|'||room_id||'|'||stay_seq)*100000))::int::text,9,'0'),
       hotel_code,room_type_code,room_id,
       ((checkin_date-lead_days)::timestamp + TIME '10:00') AT TIME ZONE 'Asia/Seoul',
       checkin_date,checkin_date+los,
       CASE floor(walkerhill_v4_3.v43_u01('channel|'||room_id||'|'||stay_seq)*5)::int
         WHEN 0 THEN 'DIRECT_WEB' WHEN 1 THEN 'MOBILE' WHEN 2 THEN 'OTA' WHEN 3 THEN 'CORPORATE' ELSE 'CALL_CENTER' END,
       CASE WHEN hotel_code='DOUGLAS' THEN 'LEISURE_ADULT' WHEN walkerhill_v4_3.v43_u01('segment|'||room_id||'|'||stay_seq)<0.18 THEN 'CORPORATE' ELSE 'LEISURE' END,
       'CHECKED_OUT',NULL,NULL,NULL,quoted_rate,discount_total,booked_total,'KRW',false,true
FROM priced;

-- 회귀용 bridge는 유지하되 3개 객실을 순환하며 1~3박 pickup 분포를 갖는다.
WITH hotels(hotel_code,hotel_idx,room_type_code,room_prefix,first_room) AS (
  VALUES ('GRAND',1,'G_DELUXE','GRAND-G_DELUXE-',358),
         ('VISTA',2,'V_DELUXE','VISTA-V_DELUXE-',188),
         ('DOUGLAS',3,'D_DELUXE','DOUGLAS-D_DELUXE-',43)
), bridge_base AS (
  SELECT c.business_date,h.*,(c.business_date-DATE '2024-01-01')::int day_idx,
         least(1+mod((c.business_date-DATE '2024-01-01')::int+h.hotel_idx,3),(DATE '2026-09-01'-c.business_date)::int) AS los,
         rt.synthetic_base_rate_krw,
         floor(walkerhill_v4_3.v43_u01('bridge-discount|'||h.hotel_code||'|'||to_char(c.business_date,'YYYY-MM-DD'))*2)::int*0.05 discount_rate,
         0.96+0.08*walkerhill_v4_3.v43_u01('bridge-rate|'||h.hotel_code||'|'||to_char(c.business_date,'YYYY-MM-DD')) rate_noise
  FROM walkerhill_v4_3.calendar_daily c CROSS JOIN hotels h
  JOIN walkerhill_v4_3.pms_room_types rt USING(hotel_code,room_type_code)
), bridge AS (
  SELECT b.*,b.room_prefix||lpad((b.first_room+mod(b.day_idx,3))::text,4,'0') AS room_id FROM bridge_base b
), rated AS (
  SELECT b.*,a.gross_total,a.discount_total,a.booked_total
  FROM bridge b
  CROSS JOIN LATERAL (
    SELECT sum(n.gross_rate) gross_total,
           sum(n.gross_rate-round(n.gross_rate*(1-b.discount_rate),0)) discount_total,
           sum(round(n.gross_rate*(1-b.discount_rate),0)) booked_total
    FROM (
      SELECT round((b.synthetic_base_rate_krw
        *CASE c.season_code WHEN 'SUMMER' THEN 1.12 WHEN 'AUTUMN' THEN 1.10 WHEN 'WINTER' THEN 1.05 ELSE 1.00 END
        *CASE c.room_rate_day_type WHEN 'FRIDAY' THEN 1.10 WHEN 'SATURDAY' THEN 1.28 ELSE 1.00 END
        *CASE WHEN c.is_holiday THEN 1.18 ELSE 1.00 END
        *(1+coalesce(ev.uplift_mode,0))*b.rate_noise)/1000,0)*1000 gross_rate
      FROM generate_series(b.business_date,b.business_date+b.los-1,INTERVAL '1 day') d
      JOIN walkerhill_v4_3.calendar_daily c ON c.business_date=d::date
      LEFT JOIN LATERAL (
        SELECT he.uplift_mode FROM walkerhill_v4_3.event_master em JOIN walkerhill_v4_3.hotel_event_effect he USING(event_id)
        WHERE he.hotel_code=b.hotel_code AND he.domain='ROOMS' AND he.metric_name='ADR'
          AND d::date BETWEEN em.start_date-he.lead_days AND em.end_date+he.lag_days
        ORDER BY he.uplift_mode DESC,em.event_id LIMIT 1
      ) ev ON true
    ) n
  ) a
)
INSERT INTO walkerhill_v4_3.pms_reservations
(reservation_id,guest_id,hotel_code,room_type_code,assigned_room_id,booked_at,checkin_date,checkout_date,
 booking_channel,market_segment,reservation_status,cancelled_at,cancellation_reason_code,banquet_event_id,
 quoted_room_rate,discount_amount,booked_amount,currency_code,is_forecast,is_synthetic)
SELECT 'R_BRIDGE_'||hotel_code||'_'||to_char(business_date,'YYYYMMDD'),
       'G'||lpad((1+mod(day_idx*3+hotel_idx*7919,90000))::text,9,'0'),hotel_code,room_type_code,room_id,
       ((business_date-30)::timestamp+TIME '10:00') AT TIME ZONE 'Asia/Seoul',business_date,business_date+los,
       'DIRECT_WEB','GROUP_MEMBER','CHECKED_OUT',NULL,NULL,
       CASE WHEN business_date<=DATE '2026-08-30' THEN 'BE_'||lpad((day_idx*3+hotel_idx)::text,10,'0') END,
       round(gross_total/los,-3),discount_total,booked_total,
       'KRW',false,true
FROM rated;

-- 다박 투숙 중 POS 객실청구·folio·포인트·VOC를 연결할 실제형 합성 고객 여정 972건.
WITH hotels(hotel_idx,hotel_code,room_type_code,room_prefix,first_room) AS (
  VALUES (1,'GRAND','G_DELUXE','GRAND-G_DELUXE-',355),
         (2,'VISTA','V_DELUXE','VISTA-V_DELUXE-',185),
         (3,'DOUGLAS','D_DELUXE','DOUGLAS-D_DELUXE-',40)
), journey_plan AS (
  SELECT j,h.*,
         1+(j-1)/3 AS property_seq,
         DATE '2024-01-01'+((j-1)/3)*3 AS checkin_date
  FROM generate_series(1,972) j
  JOIN hotels h ON h.hotel_idx=1+mod(j-1,3)
), journey AS (
  SELECT p.*,
         2+mod(p.property_seq+p.hotel_idx,2) AS los,
         p.room_prefix||lpad((p.first_room+mod(p.property_seq-1,3))::text,4,'0') AS room_id,
         21+mod(p.j*13,60) AS lead_days,
         mod(p.j,3)*0.05 AS discount_rate,
         rt.synthetic_base_rate_krw
  FROM journey_plan p JOIN walkerhill_v4_3.pms_room_types rt USING(hotel_code,room_type_code)
), priced AS (
  SELECT j.*,a.gross_total,a.discount_total,a.booked_total
  FROM journey j
  CROSS JOIN LATERAL (
    SELECT sum(n.gross_rate) gross_total,
           sum(n.gross_rate-round(n.gross_rate*(1-j.discount_rate),0)) discount_total,
           sum(round(n.gross_rate*(1-j.discount_rate),0)) booked_total
    FROM (
      SELECT round((j.synthetic_base_rate_krw
        *CASE c.season_code WHEN 'SUMMER' THEN 1.12 WHEN 'AUTUMN' THEN 1.10 WHEN 'WINTER' THEN 1.05 ELSE 1.00 END
        *CASE c.room_rate_day_type WHEN 'FRIDAY' THEN 1.10 WHEN 'SATURDAY' THEN 1.28 ELSE 1.00 END
        *CASE WHEN c.is_holiday THEN 1.18 ELSE 1.00 END
        *(1+coalesce(ev.uplift_mode,0))
        *(0.92+0.18*walkerhill_v4_3.v43_u01('rate|'||j.room_id||'|'||to_char(j.checkin_date,'YYYY-MM-DD'))))/1000,0)*1000 AS gross_rate
      FROM generate_series(j.checkin_date,j.checkin_date+j.los-1,INTERVAL '1 day') d
      JOIN walkerhill_v4_3.calendar_daily c ON c.business_date=d::date
      LEFT JOIN LATERAL (
        SELECT he.uplift_mode
        FROM walkerhill_v4_3.event_master em JOIN walkerhill_v4_3.hotel_event_effect he USING(event_id)
        WHERE he.hotel_code=j.hotel_code AND he.domain='ROOMS' AND he.metric_name='ADR'
          AND d::date BETWEEN em.start_date-he.lead_days AND em.end_date+he.lag_days
        ORDER BY he.uplift_mode DESC,em.event_id LIMIT 1
      ) ev ON true
    ) n
  ) a
)
INSERT INTO walkerhill_v4_3.pms_reservations
(reservation_id,guest_id,hotel_code,room_type_code,assigned_room_id,booked_at,checkin_date,checkout_date,
 booking_channel,market_segment,reservation_status,cancelled_at,cancellation_reason_code,banquet_event_id,
 quoted_room_rate,discount_amount,booked_amount,currency_code,is_forecast,is_synthetic)
SELECT 'R_JOURNEY_'||lpad(j::text,10,'0'),'G'||lpad(j::text,9,'0'),hotel_code,room_type_code,room_id,
       ((checkin_date-lead_days)::timestamp+TIME '10:00') AT TIME ZONE 'Asia/Seoul',checkin_date,checkin_date+los,
       CASE mod(j,3) WHEN 0 THEN 'DIRECT_WEB' WHEN 1 THEN 'MOBILE' ELSE 'CALL_CENTER' END,
       CASE mod(j,4) WHEN 0 THEN 'BUSINESS' WHEN 1 THEN 'LEISURE' WHEN 2 THEN 'FAMILY' ELSE 'VIP' END,
       'CHECKED_OUT',NULL,NULL,NULL,round(gross_total/los,-3),discount_total,booked_total,'KRW',false,true
FROM priced;

WITH types AS (
  SELECT rt.*,sum(synthetic_room_count) OVER(ORDER BY hotel_code,room_type_code) cumulative_rooms
  FROM walkerhill_v4_3.pms_room_types rt
), cancellation_inputs AS (
  SELECT n,1+floor(walkerhill_v4_3.v43_u01('cancel-los|'||n)*3)::int AS los,
         15+floor(walkerhill_v4_3.v43_u01('cancel-lead|'||n)*75)::int AS lead_days,
         1+floor(walkerhill_v4_3.v43_u01('cancel-type|'||n)*801)::int AS room_slot
  FROM generate_series(1,53300) n
), cancellations AS (
  SELECT c.*,DATE '2024-01-01'
         +floor(walkerhill_v4_3.v43_u01('cancel-date|'||c.n)*(975-c.los))::int AS checkin_date
  FROM cancellation_inputs c
)
INSERT INTO walkerhill_v4_3.pms_reservations
(reservation_id,guest_id,hotel_code,room_type_code,assigned_room_id,booked_at,checkin_date,checkout_date,
 booking_channel,market_segment,reservation_status,cancelled_at,cancellation_reason_code,banquet_event_id,
 quoted_room_rate,discount_amount,booked_amount,currency_code,is_forecast,is_synthetic)
SELECT 'RC_'||lpad(c.n::text,10,'0'),
       'G'||lpad((1+floor(walkerhill_v4_3.v43_u01('cancel-guest|'||c.n)*100000))::int::text,9,'0'),
       t.hotel_code,t.room_type_code,NULL,
       ((c.checkin_date-c.lead_days)::timestamp+TIME '09:00') AT TIME ZONE 'Asia/Seoul',c.checkin_date,c.checkin_date+c.los,
       CASE WHEN walkerhill_v4_3.v43_u01('cancel-channel|'||c.n)<0.55 THEN 'OTA' ELSE 'DIRECT_WEB' END,
       'LEISURE','CANCELLED',
       ((c.checkin_date-greatest(1,c.lead_days/3))::timestamp+TIME '14:00') AT TIME ZONE 'Asia/Seoul',
       CASE WHEN walkerhill_v4_3.v43_u01('cancel-reason|'||c.n)<0.55 THEN 'PLAN_CHANGED' ELSE 'PRICE_SENSITIVITY' END,
       NULL,t.synthetic_base_rate_krw,0,t.synthetic_base_rate_krw*c.los,'KRW',false,true
FROM cancellations c JOIN types t
  ON c.room_slot<=t.cumulative_rooms AND c.room_slot>t.cumulative_rooms-t.synthetic_room_count;
