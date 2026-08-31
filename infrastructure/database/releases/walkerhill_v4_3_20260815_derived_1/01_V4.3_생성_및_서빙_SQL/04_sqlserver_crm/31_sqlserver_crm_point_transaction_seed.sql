USE [crm_db];
GO
-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=SQL Server 2022; domain=CRM; script_type=SEED; execution_order=31
-- expected_rows=480000; dependency=20_sqlserver_crm_tier_member_seed.sql; execution_default=NOT_RUN
-- realism_rule=event timestamps and transaction types are deterministic; balances reconcile to the signed ledger
-- exclusion_rule=POS earn never targets order ids 1..2916, which are reserved for the multi-night journey contract

SET NOCOUNT ON;
IF EXISTS(SELECT 1 FROM [walkerhill_v4_3].[crm_point_transactions])
  THROW 51000,'candidate CRM point transaction table must be empty',1;
;WITH n AS (
  SELECT 1 AS i UNION ALL SELECT i+1 FROM n WHERE i<480000
), tx AS (
  SELECT i,1+((CAST(i AS bigint)*7919)%150000) member_i,1+((i-1)/150000) txn_seq,
         [walkerhill_v4_3].[v43_u01](CONCAT('point-type|',i)) u_type,
         [walkerhill_v4_3].[v43_u01](CONCAT('point-value|',i)) u_value,
         [walkerhill_v4_3].[v43_u01](CONCAT('point-time|',i)) u_time,
         [walkerhill_v4_3].[v43_u01](CONCAT('point-source|',i)) u_source
  FROM n
), typed AS (
  SELECT *,CASE WHEN txn_seq=1 OR (txn_seq=2 AND member_i<=972) OR u_type<0.60 THEN 'EARN'
                WHEN u_type<0.90 THEN 'REDEEM' ELSE 'EXPIRE' END AS effective_type
  FROM tx
), pos_contract AS (
  SELECT *,CASE WHEN txn_seq=2 AND member_i<=972 THEN CONVERT(int,member_i*3-2) ELSE CONVERT(int,member_i) END order_i,
         1+CONVERT(int,((member_i-1)*7919)%12) outlet_seq,
         CONVERT(int,(member_i*17)%1000) event_pick,CONVERT(int,(member_i*23)%100) event_window,
         CONVERT(int,(member_i*37)%974) date_slot
  FROM typed
), dated AS (
  SELECT *,CASE WHEN txn_seq=2 AND member_i<=972
        THEN DATEADD(day,((member_i-1)/3)*3,CONVERT(date,'2024-01-01'))
        WHEN event_pick<CASE WHEN outlet_seq<=6 THEN 140 WHEN outlet_seq<=10 THEN 170 ELSE 70 END
        THEN CASE WHEN event_window<18 THEN DATEADD(day,date_slot%61,CONVERT(date,'2024-09-01'))
                  WHEN event_window<28 THEN DATEADD(day,date_slot%31,CONVERT(date,'2024-12-01'))
                  WHEN event_window<39 THEN DATEADD(day,date_slot%30,CONVERT(date,'2025-06-21'))
                  WHEN event_window<54 THEN DATEADD(day,date_slot%91,CONVERT(date,'2025-09-01'))
                  WHEN event_window<68 THEN DATEADD(day,date_slot%47,CONVERT(date,'2026-04-22'))
                  WHEN event_window<82 THEN DATEADD(day,date_slot%113,CONVERT(date,'2026-05-11'))
                  ELSE DATEADD(day,date_slot%66,CONVERT(date,'2026-06-26')) END
        ELSE DATEADD(day,date_slot,CONVERT(date,'2024-01-01')) END pos_business_date
  FROM pos_contract
), linked AS (
  SELECT *,CASE WHEN txn_seq=2 AND member_i<=972 THEN 1
                WHEN txn_seq>1 AND effective_type='EARN' AND member_i>2916 AND member_i<=75000
                          AND member_i%10<7 AND (member_i*19)%100<98 THEN 1 ELSE 0 END pos_earn
  FROM dated
)
INSERT [walkerhill_v4_3].[crm_point_transactions]
  (point_txn_id,member_no,event_at,txn_type,points_delta,related_source,related_id,is_synthetic)
SELECT CONCAT('PT_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),i),10)),
       CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),member_i),9)),
       CASE WHEN pos_earn=1 THEN TODATETIMEOFFSET(DATEADD(hour,27,CONVERT(datetime2,pos_business_date)),'+09:00')
            ELSE TODATETIMEOFFSET(DATEADD(second,
              CASE txn_seq WHEN 1 THEN 0 WHEN 2 THEN 244*86400 WHEN 3 THEN 488*86400 ELSE 731*86400 END
              +CONVERT(int,FLOOR(u_time*CASE WHEN txn_seq IN(1,2) THEN 244*86400 ELSE 243*86400 END)),
              CONVERT(datetime2,'2024-01-01T00:00:00')), '+09:00') END,
       effective_type,
        CASE WHEN txn_seq=1 THEN 10000+CONVERT(bigint,FLOOR(u_value*3001))
            WHEN txn_seq=2 AND member_i<=972 THEN [walkerhill_v4_3].[v43_journey_pos_eligible_amount](CONVERT(int,member_i))*5/100
            WHEN effective_type='EARN' THEN 100+CONVERT(bigint,FLOOR(u_value*9901))
            WHEN effective_type='REDEEM' THEN -(100+CONVERT(bigint,FLOOR(u_value*2901)))
            ELSE -(50+CONVERT(bigint,FLOOR(u_value*951))) END,
       CASE WHEN effective_type='EXPIRE' THEN 'CRM_EXPIRY' WHEN pos_earn=1 THEN 'POS_ORDER'
            WHEN member_i<=100000 THEN 'PMS_GUEST' ELSE 'CRM_CAMPAIGN' END,
       CASE WHEN effective_type='EXPIRE'
              THEN CONCAT('EXP_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),i),10))
            WHEN pos_earn=1
              THEN CONCAT('O_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),order_i),10))
            WHEN member_i<=100000
              THEN CONCAT('G',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),member_i),9))
            ELSE CONCAT('CMP_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),i),10)) END,1
FROM linked JOIN [walkerhill_v4_3].[crm_members] m
  ON m.member_no=CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),member_i),9))
OPTION (MAXRECURSION 0);

;WITH b AS (
 SELECT member_no,SUM(points_delta) AS balance
 FROM [walkerhill_v4_3].[crm_point_transactions] GROUP BY member_no
)
UPDATE m SET points_balance=COALESCE(b.balance,0)
FROM [walkerhill_v4_3].[crm_members] m LEFT JOIN b ON b.member_no=m.member_no;
GO
