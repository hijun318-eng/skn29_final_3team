USE [crm_db];
GO
-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=SQL Server 2022; domain=CRM_VOC; script_type=SEED; execution_order=33
-- expected_rows=161944; dependency=32_sqlserver_crm_customer_map_seed.sql; execution_default=NOT_RUN
-- privacy=no real review, reviewer identity, contact detail or external-platform text is used
-- realism_rule=event congestion changes review volume and rating; rating, text, topic and sentiment remain mutually consistent

SET NOCOUNT ON;
SET XACT_ABORT ON;
IF EXISTS(SELECT 1 FROM [walkerhill_v4_3].[crm_voc_reviews]) OR EXISTS(SELECT 1 FROM [walkerhill_v4_3].[crm_voc_analysis])
  THROW 51000,'candidate CRM VOC tables must be empty',1;
DECLARE @review_batch_start int=1;
WHILE @review_batch_start<=80000
BEGIN
DECLARE @review_batch_end int=IIF(@review_batch_start+1999>80000,80000,@review_batch_start+1999);
;WITH n AS (
  SELECT @review_batch_start i UNION ALL SELECT i+1 FROM n WHERE i<@review_batch_end
)
SELECT i,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-channel|',i)) channel_u,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-related|',i)) related_u,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-hotel|',i)) hotel_u,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-date|',i)) date_u,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-event|',i)) event_u,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-event-window|',i)) event_window_u,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-rating|',i)) rating_u,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-topic|',i)) topic_u,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-event-penalty|',i)) penalty_u,
    [walkerhill_v4_3].[v43_u01](CONCAT('voc-component|',i)) component_u
INTO #voc_base
FROM n
OPTION (MAXRECURSION 0, USE HINT('DISABLE_TSQL_SCALAR_UDF_INLINING'));

;WITH shaped AS (
  SELECT *,
    CASE WHEN channel_u<0.44 THEN 'POST_STAY_SURVEY' WHEN channel_u<0.61 THEN 'IN_STAY_QR'
         WHEN channel_u<0.78 THEN 'FNB_QR' WHEN channel_u<0.89 THEN 'FACILITY_QR'
         WHEN channel_u<0.95 THEN 'BANQUET_SURVEY' ELSE 'PUBLIC_REVIEW_SYNTHETIC' END source_channel,
    CASE WHEN channel_u<0.44 THEN 'CHECKOUT' WHEN channel_u<0.61 THEN 'ROOM'
         WHEN channel_u<0.78 THEN 'FNB' WHEN channel_u<0.89 THEN 'FACILITY'
         WHEN channel_u<0.95 THEN 'BANQUET' ELSE 'OVERALL' END touchpoint
  FROM #voc_base
), raw_source_keys AS (
  SELECT *,1+CONVERT(int,(CAST(i AS bigint)*7919)%733000) raw_pos_i_candidate,
         1+CONVERT(int,(CAST(i AS bigint)*3571)%733000) facility_i,
         1+CONVERT(int,(CAST(i AS bigint)*2377)%2919) banquet_i,
         CONVERT(int,(CAST(i AS bigint)*37)%973) pms_day,
         1+CONVERT(int,i%3) pms_hotel_idx,
         -- PMS bridge stay의 결정적 숙박일수를 동일 산식으로 재현한다.
         -- 원본: 01_postgresql_pms/31_..._seed.sql 의 least(1+mod(day_idx+hotel_idx,3), 2026-09-01 - business_date)
         CASE WHEN 1+CONVERT(int,(CONVERT(int,(CAST(i AS bigint)*37)%973)+1+CONVERT(int,i%3))%3)
                   > 974-CONVERT(int,(CAST(i AS bigint)*37)%973)
              THEN 974-CONVERT(int,(CAST(i AS bigint)*37)%973)
              ELSE 1+CONVERT(int,(CONVERT(int,(CAST(i AS bigint)*37)%973)+1+CONVERT(int,i%3))%3)
          END bridge_los
  FROM shaped
), reserved_range_safe AS (
  SELECT *,CASE WHEN raw_pos_i_candidate<=2916 THEN raw_pos_i_candidate+2916 ELSE raw_pos_i_candidate END raw_pos_i
  FROM raw_source_keys
), source_keys AS (
  SELECT *,CASE WHEN (CAST(raw_pos_i AS bigint)*19)%100=99
                THEN CASE WHEN raw_pos_i=733000 THEN raw_pos_i-1 ELSE raw_pos_i+1 END ELSE raw_pos_i END pos_i
  FROM reserved_range_safe
), mechanics AS (
  SELECT *,1+CONVERT(int,((CAST(pos_i AS bigint)-1)*7919)%12) pos_outlet_seq,
         CONVERT(int,(CAST(pos_i AS bigint)*17)%1000) pos_event_pick,
         CONVERT(int,(CAST(pos_i AS bigint)*23)%100) pos_event_window,
         CONVERT(int,(CAST(pos_i AS bigint)*37)%974) pos_date_slot,
         DATEADD(day,CONVERT(int,((CAST(facility_i AS bigint)-1)*37)%974),CONVERT(date,'2024-01-01')) facility_date,
         CONVERT(int,((CAST(banquet_i AS bigint)-2920)*7919)%13636) banquet_slot_id
  FROM source_keys
)
SELECT * INTO #voc_mechanics FROM mechanics;
DROP TABLE #voc_base;

;WITH dated AS (
  SELECT *,
    CASE WHEN pos_event_pick<CASE WHEN pos_outlet_seq<=6 THEN 140 WHEN pos_outlet_seq<=10 THEN 170 ELSE 70 END
      THEN CASE WHEN pos_event_window<18 THEN DATEADD(day,pos_date_slot%61,CONVERT(date,'2024-09-01'))
                WHEN pos_event_window<28 THEN DATEADD(day,pos_date_slot%31,CONVERT(date,'2024-12-01'))
                WHEN pos_event_window<39 THEN DATEADD(day,pos_date_slot%30,CONVERT(date,'2025-06-21'))
                WHEN pos_event_window<54 THEN DATEADD(day,pos_date_slot%91,CONVERT(date,'2025-09-01'))
                WHEN pos_event_window<68 THEN DATEADD(day,pos_date_slot%47,CONVERT(date,'2026-04-22'))
                WHEN pos_event_window<82 THEN DATEADD(day,pos_date_slot%113,CONVERT(date,'2026-05-11'))
                ELSE DATEADD(day,pos_date_slot%66,CONVERT(date,'2026-06-26')) END
      ELSE DATEADD(day,pos_date_slot,CONVERT(date,'2024-01-01')) END pos_business_date,
    CASE WHEN banquet_i<=2919 THEN DATEADD(day,(banquet_i-1)/3,CONVERT(date,'2024-01-02'))
         ELSE DATEADD(day,banquet_slot_id/14,CONVERT(date,'2024-01-01')) END banquet_event_date,
    CASE WHEN facility_date<CONVERT(date,'2025-06-21')
      THEN CASE 1+CONVERT(int,((CAST(facility_i AS bigint)-1)*7919)%9)
        WHEN 1 THEN 'F_RIVERPARK' WHEN 2 THEN 'F_GRAND_FIT' WHEN 3 THEN 'F_VISTA_WELL' WHEN 4 THEN 'F_DOUGLAS_LIB'
        WHEN 5 THEN 'F_SAUNA' WHEN 6 THEN 'F_TENNIS' WHEN 7 THEN 'F_KIDS' WHEN 8 THEN 'F_GARDEN' ELSE 'F_CONV' END
      ELSE CASE 1+CONVERT(int,((CAST(facility_i AS bigint)-1)*7919)%10)
        WHEN 1 THEN 'F_GOLF' WHEN 2 THEN 'F_RIVERPARK' WHEN 3 THEN 'F_GRAND_FIT' WHEN 4 THEN 'F_VISTA_WELL'
        WHEN 5 THEN 'F_DOUGLAS_LIB' WHEN 6 THEN 'F_SAUNA' WHEN 7 THEN 'F_TENNIS' WHEN 8 THEN 'F_KIDS'
        WHEN 9 THEN 'F_GARDEN' ELSE 'F_CONV' END END facility_key
  FROM #voc_mechanics
)
SELECT * INTO #voc_dated FROM dated;
DROP TABLE #voc_mechanics;

;WITH contracted AS (
  SELECT *,
    CASE touchpoint
      WHEN 'CHECKOUT' THEN CASE pms_hotel_idx WHEN 1 THEN 'GRAND' WHEN 2 THEN 'VISTA' ELSE 'DOUGLAS' END
      WHEN 'ROOM' THEN CASE pms_hotel_idx WHEN 1 THEN 'GRAND' WHEN 2 THEN 'VISTA' ELSE 'DOUGLAS' END
      WHEN 'FNB' THEN CASE WHEN pos_outlet_seq<=6 THEN 'GRAND' WHEN pos_outlet_seq<=10 THEN 'VISTA' ELSE 'DOUGLAS' END
      -- facility_master.reporting_hotel_code와 동일한 귀속을 유지해야 하며 마스터 변경 시 이 CASE도 함께 동기화한다.
      WHEN 'FACILITY' THEN CASE WHEN facility_key IN('F_GOLF','F_VISTA_WELL','F_TENNIS') THEN 'VISTA'
                                WHEN facility_key IN('F_DOUGLAS_LIB','F_KIDS') THEN 'DOUGLAS' ELSE 'GRAND' END
      WHEN 'BANQUET' THEN CASE WHEN banquet_i<=2919 THEN CASE (banquet_i-1)%3 WHEN 0 THEN 'GRAND' WHEN 1 THEN 'VISTA' ELSE 'DOUGLAS' END
        ELSE CASE 1+banquet_slot_id%7 WHEN 1 THEN 'VISTA' WHEN 3 THEN 'DOUGLAS' WHEN 6 THEN 'VISTA' ELSE 'GRAND' END END
      ELSE CASE WHEN hotel_u<0.63 THEN 'GRAND' WHEN hotel_u<0.93 THEN 'VISTA' ELSE 'DOUGLAS' END END hotel_code,
    CASE touchpoint WHEN 'CHECKOUT' THEN DATEADD(day,pms_day+bridge_los,CONVERT(date,'2024-01-01'))
      WHEN 'ROOM' THEN DATEADD(day,pms_day+bridge_los,CONVERT(date,'2024-01-01'))
      WHEN 'FNB' THEN DATEADD(day,1,pos_business_date)
      WHEN 'FACILITY' THEN DATEADD(day,1,facility_date) WHEN 'BANQUET' THEN banquet_event_date
      ELSE DATEADD(day,CONVERT(int,FLOOR(date_u*974)),CONVERT(date,'2024-01-01')) END review_date
  FROM #voc_dated
)
SELECT * INTO #voc_contracted FROM contracted;
DROP TABLE #voc_dated;

;WITH categorized AS (
  SELECT *,
    CASE touchpoint
      WHEN 'CHECKOUT' THEN CASE WHEN topic_u<0.25 THEN 'CHECKOUT_PROCESS' WHEN topic_u<0.50 THEN 'ROOM_CLEANLINESS' WHEN topic_u<0.75 THEN 'STAFF_SERVICE' ELSE 'VALUE' END
      WHEN 'ROOM' THEN CASE WHEN topic_u<0.25 THEN 'ROOM_CLEANLINESS' WHEN topic_u<0.50 THEN 'ROOM_MAINTENANCE' WHEN topic_u<0.75 THEN 'SLEEP_QUALITY' ELSE 'STAFF_SERVICE' END
      WHEN 'FNB' THEN CASE WHEN topic_u<0.25 THEN 'BREAKFAST_QUEUE' WHEN topic_u<0.55 THEN 'DINING_QUALITY' WHEN topic_u<0.78 THEN 'STAFF_SERVICE' ELSE 'VALUE' END
      WHEN 'FACILITY' THEN CASE WHEN topic_u<0.28 THEN 'FACILITY_CROWDING' WHEN topic_u<0.53 THEN 'FACILITY_CONDITION' WHEN topic_u<0.76 THEN 'STAFF_SERVICE' ELSE 'VALUE' END
      WHEN 'BANQUET' THEN CASE WHEN topic_u<0.30 THEN 'BANQUET_SERVICE' WHEN topic_u<0.55 THEN 'DINING_QUALITY' WHEN topic_u<0.78 THEN 'FACILITY_CONDITION' ELSE 'VALUE' END
      ELSE CASE WHEN topic_u<0.35 THEN 'GENERAL_EXPERIENCE' WHEN topic_u<0.62 THEN 'STAFF_SERVICE' WHEN topic_u<0.82 THEN 'VALUE' ELSE 'LOCATION_ACCESS' END
    END selected_category,
    CASE WHEN rating_u+CASE hotel_code WHEN 'VISTA' THEN 0.025 WHEN 'DOUGLAS' THEN 0.055 ELSE 0 END<0.05 THEN 1
         WHEN rating_u+CASE hotel_code WHEN 'VISTA' THEN 0.025 WHEN 'DOUGLAS' THEN 0.055 ELSE 0 END<0.14 THEN 2
         WHEN rating_u+CASE hotel_code WHEN 'VISTA' THEN 0.025 WHEN 'DOUGLAS' THEN 0.055 ELSE 0 END<0.29 THEN 3
         WHEN rating_u+CASE hotel_code WHEN 'VISTA' THEN 0.025 WHEN 'DOUGLAS' THEN 0.055 ELSE 0 END<0.67 THEN 4 ELSE 5 END base_rating
  FROM #voc_contracted
)
SELECT * INTO #voc_categorized FROM categorized;
DROP TABLE #voc_contracted;

;WITH rated AS (
  SELECT *,
    CASE WHEN penalty_u<0.38
                   AND (review_date BETWEEN '2024-09-01' AND '2024-10-31'
                     OR review_date BETWEEN '2024-12-01' AND '2024-12-31'
                     OR review_date BETWEEN '2025-06-21' AND '2025-07-20'
                     OR review_date BETWEEN '2025-09-01' AND '2025-11-30'
                     OR review_date BETWEEN '2026-04-22' AND '2026-06-07'
                     OR review_date BETWEEN '2026-05-11' AND '2026-08-31'
                     OR review_date BETWEEN '2026-06-26' AND '2026-08-30')
                   AND selected_category IN('CHECKOUT_PROCESS','BREAKFAST_QUEUE','FACILITY_CROWDING','STAFF_SERVICE')
                   AND base_rating>1 THEN base_rating-1 ELSE base_rating END rating_overall
  FROM #voc_categorized
)
SELECT *,
  CASE WHEN touchpoint IN('CHECKOUT','ROOM') THEN 'PMS_STAY' WHEN touchpoint='FNB' THEN 'POS_ORDER'
       WHEN touchpoint='FACILITY' THEN 'FACILITY_USAGE' WHEN touchpoint='BANQUET' THEN 'BANQUET_BOOKING' ELSE 'NONE' END related_source,
  CASE WHEN component_u<0.25 THEN -1 WHEN component_u>0.82 THEN 1 ELSE 0 END component_delta
INTO #review_rows
FROM rated
OPTION (MAXRECURSION 0, USE HINT('DISABLE_TSQL_SCALAR_UDF_INLINING'));
DROP TABLE #voc_categorized;

INSERT [walkerhill_v4_3].[crm_voc_reviews]
 (voc_review_id,submitted_at,source_business_date,hotel_code,source_channel,touchpoint,selected_category,related_source,related_id,member_no,
  outlet_id,facility_id,visit_cohort,prior_visit_count,
  rating_overall,rating_service,rating_cleanliness,rating_food,rating_facility,rating_value,
  review_title,review_text_original,language_code,is_external,consent_for_analysis,is_synthetic)
SELECT CONCAT('VR_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),i),10)),
  TODATETIMEOFFSET(DATEADD(minute,CONVERT(int,FLOOR([walkerhill_v4_3].[v43_u01](CONCAT('voc-time|',i))*50)),
    DATEADD(hour,CASE touchpoint WHEN 'CHECKOUT' THEN 13 WHEN 'ROOM' THEN 13 WHEN 'FNB' THEN 12
                                WHEN 'FACILITY' THEN 12 WHEN 'BANQUET' THEN 23 ELSE 12 END,CONVERT(datetime2,review_date))),'+09:00'),
  CASE related_source WHEN 'PMS_STAY' THEN DATEADD(day,-1,review_date) WHEN 'POS_ORDER' THEN pos_business_date
       WHEN 'FACILITY_USAGE' THEN facility_date WHEN 'BANQUET_BOOKING' THEN banquet_event_date ELSE review_date END,
  hotel_code,source_channel,touchpoint,selected_category,related_source,
  CASE related_source
    WHEN 'PMS_STAY' THEN CONCAT('S_BRIDGE_',hotel_code,'_',CONVERT(char(8),DATEADD(day,pms_day,CONVERT(date,'2024-01-01')),112))
    WHEN 'POS_ORDER' THEN CONCAT('O_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),pos_i),10))
    WHEN 'FACILITY_USAGE' THEN CONCAT('FUEV_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),facility_i),10))
    WHEN 'BANQUET_BOOKING' THEN CONCAT('BE_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),banquet_i),10)) END,
  CASE related_source
    WHEN 'PMS_STAY' THEN CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),1+(pms_day*3+pms_hotel_idx*7919)%90000),9))
    WHEN 'POS_ORDER' THEN CASE WHEN pos_i%10<7 THEN CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),1+(pos_i-1)%75000),9)) END
    WHEN 'FACILITY_USAGE' THEN CASE WHEN (facility_i-1)%100<68 THEN CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),1+((CAST(facility_i AS bigint)-1)*3571)%110000),9)) END
    WHEN 'BANQUET_BOOKING' THEN CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),1+(CAST(banquet_i AS bigint)*3571)%100000),9)) END,
  CASE WHEN touchpoint='FNB' THEN CASE pos_outlet_seq WHEN 1 THEN 'OUTLET_BUFFET' WHEN 2 THEN 'OUTLET_PIZZA' WHEN 3 THEN 'OUTLET_MYUNGWOL'
    WHEN 4 THEN 'OUTLET_GEUMRYONG' WHEN 5 THEN 'OUTLET_PAVILION' WHEN 6 THEN 'OUTLET_GRAND_ROOM' WHEN 7 THEN 'OUTLET_MOEGI'
    WHEN 8 THEN 'OUTLET_DELVINO' WHEN 9 THEN 'OUTLET_REBAR' WHEN 10 THEN 'OUTLET_VISTA_ROOM' WHEN 11 THEN 'OUTLET_DOUGLAS' ELSE 'OUTLET_DOUGLAS_ROOM' END END,
  CASE WHEN touchpoint='FACILITY' THEN facility_key END,
  CASE WHEN i%5=0 THEN 'NEW' ELSE 'RETURNING' END,CASE WHEN i%5=0 THEN 0 ELSE 1+i%7 END,
  rating_overall,
  CONVERT(tinyint,GREATEST(1,LEAST(5,rating_overall+component_delta))),
  CASE WHEN touchpoint IN('CHECKOUT','ROOM') THEN CONVERT(tinyint,GREATEST(1,LEAST(5,rating_overall+CASE WHEN component_u<0.35 THEN -1 WHEN component_u>0.88 THEN 1 ELSE 0 END))) END,
  CASE WHEN touchpoint IN('FNB','BANQUET') THEN CONVERT(tinyint,GREATEST(1,LEAST(5,rating_overall+CASE WHEN component_u<0.30 THEN -1 WHEN component_u>0.86 THEN 1 ELSE 0 END))) END,
  CASE WHEN touchpoint='FACILITY' THEN CONVERT(tinyint,GREATEST(1,LEAST(5,rating_overall+CASE WHEN component_u<0.30 THEN -1 WHEN component_u>0.86 THEN 1 ELSE 0 END))) END,
  CONVERT(tinyint,GREATEST(1,LEAST(5,rating_overall+CASE WHEN component_u<0.42 THEN -1 WHEN component_u>0.90 THEN 1 ELSE 0 END))),
  CONCAT(CASE selected_category
    WHEN 'CHECKOUT_PROCESS' THEN N'체크아웃 절차' WHEN 'ROOM_CLEANLINESS' THEN N'객실 청결' WHEN 'ROOM_MAINTENANCE' THEN N'객실 정비'
    WHEN 'SLEEP_QUALITY' THEN N'수면 환경' WHEN 'BREAKFAST_QUEUE' THEN N'조식 대기' WHEN 'DINING_QUALITY' THEN N'식음 품질'
    WHEN 'FACILITY_CROWDING' THEN N'시설 혼잡' WHEN 'FACILITY_CONDITION' THEN N'시설 상태' WHEN 'BANQUET_SERVICE' THEN N'연회 서비스'
    WHEN 'STAFF_SERVICE' THEN N'직원 응대' WHEN 'LOCATION_ACCESS' THEN N'접근 안내' WHEN 'VALUE' THEN N'가격 대비 가치' ELSE N'전반적 경험' END,
    CASE WHEN rating_overall<=2 THEN N' 개선 요청' WHEN rating_overall=3 THEN N' 이용 의견' ELSE N' 만족 후기' END),
  CONCAT(
    CASE i%6 WHEN 0 THEN N'이번 방문에서 ' WHEN 1 THEN N'가족과 이용하면서 ' WHEN 2 THEN N'주말 일정 중 ' WHEN 3 THEN N'행사 기간에 방문해 ' WHEN 4 THEN N'저녁 시간대에 ' ELSE N'이용을 마치고 ' END,
    CASE selected_category
      WHEN 'CHECKOUT_PROCESS' THEN CASE WHEN rating_overall<=2 THEN CONCAT(N'체크아웃 처리에 약 ',10+CONVERT(int,FLOOR(component_u*36)),N'분이 걸려 안내 보완이 필요했습니다.') WHEN rating_overall=3 THEN N'체크아웃 안내는 이해하기 쉬웠지만 대기 동선은 조금 혼잡했습니다.' ELSE N'체크아웃 절차가 빠르고 안내도 분명해 편안했습니다.' END
      WHEN 'ROOM_CLEANLINESS' THEN CASE WHEN rating_overall<=2 THEN N'욕실과 침구의 세부 청결 상태가 기대에 미치지 못했습니다.' WHEN rating_overall=3 THEN N'전반적으로 정돈되어 있었지만 일부 구역은 추가 점검이 필요해 보였습니다.' ELSE N'객실과 욕실이 깔끔하게 정돈되어 안심하고 머물렀습니다.' END
      WHEN 'ROOM_MAINTENANCE' THEN CASE WHEN rating_overall<=2 THEN N'객실 설비의 작동 상태를 다시 확인해 주셨으면 합니다.' WHEN rating_overall=3 THEN N'설비 이용은 가능했지만 사용 설명과 사전 점검이 더 있으면 좋겠습니다.' ELSE N'객실 설비가 안정적으로 작동하고 관리 상태도 좋았습니다.' END
      WHEN 'SLEEP_QUALITY' THEN CASE WHEN rating_overall<=2 THEN N'복도 소음과 실내 온도 때문에 편하게 쉬기 어려웠습니다.' WHEN rating_overall=3 THEN N'침구는 편안했지만 늦은 시간 소음이 조금 느껴졌습니다.' ELSE N'침구와 실내 환경이 편안해 숙면할 수 있었습니다.' END
      WHEN 'BREAKFAST_QUEUE' THEN CASE WHEN rating_overall<=2 THEN CONCAT(N'조식 입장까지 약 ',8+CONVERT(int,FLOOR(component_u*33)),N'분을 기다려 혼잡 안내가 필요했습니다.') WHEN rating_overall=3 THEN N'음식 구성은 무난했지만 입장 대기와 좌석 안내가 아쉬웠습니다.' ELSE N'조식 입장과 좌석 안내가 원활했고 음식도 만족스러웠습니다.' END
      WHEN 'DINING_QUALITY' THEN CASE WHEN rating_overall<=2 THEN N'음식 온도와 제공 속도가 기대보다 아쉬워 개선이 필요했습니다.' WHEN rating_overall=3 THEN N'메뉴 구성은 좋았지만 제공 속도와 온도는 조금 아쉬웠습니다.' ELSE N'메뉴 구성과 음식 상태가 좋고 서비스 흐름도 만족스러웠습니다.' END
      WHEN 'FACILITY_CROWDING' THEN CASE WHEN rating_overall<=2 THEN N'이용 인원이 한꺼번에 몰려 대기와 동선 관리가 필요했습니다.' WHEN rating_overall=3 THEN N'시설은 좋았지만 특정 시간대의 혼잡도가 다소 높았습니다.' ELSE N'시설 이용 인원이 적절히 분산되어 여유롭게 즐겼습니다.' END
      WHEN 'FACILITY_CONDITION' THEN CASE WHEN rating_overall<=2 THEN N'공용 시설의 청결과 비품 상태를 더 자주 확인해 주셨으면 합니다.' WHEN rating_overall=3 THEN N'시설 이용에는 문제가 없었지만 일부 비품은 보완이 필요했습니다.' ELSE N'공용 시설과 비품이 잘 관리되어 편리하게 이용했습니다.' END
      WHEN 'BANQUET_SERVICE' THEN CASE WHEN rating_overall<=2 THEN N'행사 진행 안내와 현장 대응 속도가 기대에 미치지 못했습니다.' WHEN rating_overall=3 THEN N'행사는 무난했지만 진행 순서 안내가 조금 더 명확하면 좋겠습니다.' ELSE N'행사 준비와 현장 대응이 매끄러워 일정이 원활했습니다.' END
      WHEN 'STAFF_SERVICE' THEN CASE WHEN rating_overall<=2 THEN N'문의에 대한 설명과 후속 응답이 충분하지 않아 아쉬웠습니다.' WHEN rating_overall=3 THEN N'직원 응대는 친절했지만 바쁜 시간에는 답변이 다소 늦었습니다.' ELSE N'직원이 친절하고 요청에도 빠르게 대응해 주어 만족했습니다.' END
      WHEN 'LOCATION_ACCESS' THEN CASE WHEN rating_overall<=2 THEN N'주차와 이동 동선 안내를 찾기 어려워 불편했습니다.' WHEN rating_overall=3 THEN N'접근은 가능했지만 셔틀과 주차 안내가 더 눈에 띄면 좋겠습니다.' ELSE N'셔틀과 이동 동선 안내가 명확해 편하게 도착했습니다.' END
      WHEN 'VALUE' THEN CASE WHEN rating_overall<=2 THEN N'지불한 금액에 비해 포함 혜택과 설명이 부족하게 느껴졌습니다.' WHEN rating_overall=3 THEN N'전반적인 구성은 무난했지만 가격 대비 혜택은 조금 더 필요해 보입니다.' ELSE N'가격에 맞는 서비스와 혜택을 제공받아 만족했습니다.' END
      ELSE CASE WHEN rating_overall<=2 THEN N'전체 이용 흐름에서 여러 차례 불편을 느껴 점검이 필요했습니다.' WHEN rating_overall=3 THEN N'전반적으로 무난했지만 세부 안내가 보완되면 더 좋겠습니다.' ELSE N'도착부터 마무리까지 전반적인 경험이 편안하고 만족스러웠습니다.' END
    END,
    CASE i%5 WHEN 0 THEN N' 다음 방문 전 개선 여부를 확인하고 싶습니다.' WHEN 1 THEN N' 동행인과도 같은 내용을 이야기했습니다.' WHEN 2 THEN N' 현장 안내에 반영되면 좋겠습니다.' WHEN 3 THEN N' 전반적인 운영 흐름과 함께 살펴봐 주세요.' ELSE N'' END,
    N' 실제 고객과 무관한 합성 설문 ',CONVERT(nvarchar(10),i),N'번입니다.'),
  'ko',CASE WHEN source_channel='PUBLIC_REVIEW_SYNTHETIC' THEN 1 ELSE 0 END,1,1
FROM #review_rows OPTION (USE HINT('DISABLE_TSQL_SCALAR_UDF_INLINING'));
DROP TABLE #review_rows;
SET @review_batch_start=@review_batch_end+1;
END;

;WITH n AS (
  SELECT 1 i UNION ALL SELECT i+1 FROM n WHERE i<972
), journey AS (
  SELECT i,1+(i-1)/3 property_seq,1+(i-1)%3 hotel_idx,
         DATEADD(day,((i-1)/3)*3,CONVERT(date,'2024-01-01')) checkin_date,
         [walkerhill_v4_3].[v43_u01](CONCAT('journey-voc-rating|',i)) rating_u
  FROM n
), shaped AS (
  SELECT *,2+(property_seq+hotel_idx)%2 los,
         CASE hotel_idx WHEN 1 THEN 'GRAND' WHEN 2 THEN 'VISTA' ELSE 'DOUGLAS' END hotel_code,
         CONVERT(tinyint,CASE WHEN rating_u<0.04 THEN 1 WHEN rating_u<0.12 THEN 2 WHEN rating_u<0.30 THEN 3 WHEN rating_u<0.72 THEN 4 ELSE 5 END) rating
  FROM journey
)
INSERT [walkerhill_v4_3].[crm_voc_reviews]
 (voc_review_id,submitted_at,source_business_date,hotel_code,source_channel,touchpoint,selected_category,related_source,related_id,member_no,
  outlet_id,facility_id,visit_cohort,prior_visit_count,rating_overall,rating_service,rating_cleanliness,rating_food,rating_facility,rating_value,
  review_title,review_text_original,language_code,is_external,consent_for_analysis,is_synthetic)
SELECT CONCAT('VR_JOURNEY_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),i),10)),
       TODATETIMEOFFSET(DATEADD(minute,15+(i%75),DATEADD(hour,13,CONVERT(datetime2,DATEADD(day,los,checkin_date)))),'+09:00'),
       DATEADD(day,los,checkin_date),hotel_code,'POST_STAY_SURVEY','CHECKOUT',
       CASE i%4 WHEN 0 THEN 'ROOM_CLEANLINESS' WHEN 1 THEN 'STAFF_SERVICE' WHEN 2 THEN 'DINING_QUALITY' ELSE 'VALUE' END,
       'PMS_STAY',CONCAT('S_JOURNEY_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),i),10)),
       CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),i),9)),NULL,NULL,
       CASE WHEN i%5=0 THEN 'NEW' ELSE 'RETURNING' END,CASE WHEN i%5=0 THEN 0 ELSE 1+i%7 END,
       rating,rating,rating,NULL,NULL,rating,
       CONCAT(N'다박 투숙 여정 ',CASE WHEN rating<=2 THEN N'개선 요청' WHEN rating=3 THEN N'이용 의견' ELSE N'만족 후기' END),
       CONCAT(N'합성 고객이 ',CONVERT(nvarchar(10),los),N'박 동안 머물며 체크인 당일과 다음 날 식음 서비스를 객실로 청구한 뒤 남긴 비식별 후기입니다. ',
              CASE WHEN rating<=2 THEN N'청구 내역과 응대 흐름을 더 명확히 안내해 주셨으면 합니다.'
                   WHEN rating=3 THEN N'전반적으로 무난했지만 이용 내역 설명이 조금 더 구체적이면 좋겠습니다.'
                   ELSE N'투숙 중 식음 이용과 체크아웃 정산이 자연스럽게 이어져 만족했습니다.' END,
              N' 실제 고객과 무관한 합성 여정 ',CONVERT(nvarchar(10),i),N'번입니다.'),
       'ko',0,1,1
FROM shaped OPTION (MAXRECURSION 0, USE HINT('DISABLE_TSQL_SCALAR_UDF_INLINING'));

DECLARE @analysis_batch_start int=1;
WHILE @analysis_batch_start<=81000
BEGIN
DECLARE @analysis_batch_end int=IIF(@analysis_batch_start+1999>81000,81000,@analysis_batch_start+1999);
;WITH review_batch AS (
  SELECT *
  FROM [walkerhill_v4_3].[crm_voc_reviews]
  WHERE (@analysis_batch_start<=80000 AND voc_review_id BETWEEN
           CONCAT('VR_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),@analysis_batch_start),10)) AND
           CONCAT('VR_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),IIF(@analysis_batch_end>80000,80000,@analysis_batch_end)),10)))
     OR (@analysis_batch_start>80000 AND voc_review_id LIKE 'VR_JOURNEY[_]%')
)
INSERT [walkerhill_v4_3].[crm_voc_analysis]
 (voc_analysis_id,voc_review_id,analyzed_at,model_version,sentiment_label,sentiment_score,
  primary_topic,urgency_level,requires_followup,analysis_confidence,is_synthetic)
SELECT CONCAT('VA_',LEFT(CONVERT(varchar(64),HASHBYTES('SHA2_256',CONVERT(varchar(100),voc_review_id)),2),32)),voc_review_id,
       DATEADD(minute,3+CONVERT(int,FLOOR([walkerhill_v4_3].[v43_u01](CONCAT('voc-latency|',voc_review_id))*58)),submitted_at),
       'RULE_SENTIMENT_V1',CASE WHEN rating_overall<=2 THEN 'NEGATIVE' WHEN rating_overall=3 THEN 'NEUTRAL' ELSE 'POSITIVE' END,
       CONVERT(decimal(6,5),CASE rating_overall WHEN 1 THEN -0.85 WHEN 2 THEN -0.60 WHEN 3 THEN 0.00 WHEN 4 THEN 0.50 ELSE 0.85 END
         +([walkerhill_v4_3].[v43_u01](CONCAT('voc-sentiment|',voc_review_id))-0.5)*0.18),
       selected_category,
       CASE WHEN rating_overall=1 OR (rating_overall<=2 AND selected_category IN('ROOM_MAINTENANCE','FACILITY_CONDITION')) THEN 'HIGH'
            WHEN rating_overall<=3 THEN 'MEDIUM' ELSE 'LOW' END,
       CASE WHEN rating_overall<=2 THEN 1 ELSE 0 END,
       CONVERT(decimal(5,4),0.7800+[walkerhill_v4_3].[v43_u01](CONCAT('voc-confidence|',voc_review_id))*0.2199),1
FROM review_batch OPTION (USE HINT('DISABLE_TSQL_SCALAR_UDF_INLINING'));
SET @analysis_batch_start=@analysis_batch_end+1;
END;
GO
