USE [crm_db];
GO
-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=SQL Server 2022; target_database=crm_db; target_schema=walkerhill_v4_3
-- domain=CRM; script_type=DDL; execution_order=10
-- dependencies=00_sqlserver_crm_preflight_readonly.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814; expected_rows=0
-- execution_default=NOT_RUN; destructive_operation=false
-- evidence=https://www.walkerhill.com/en/membership/Rewards
-- assumption=member population, tier distribution and point behavior are synthetic
-- next=20_sqlserver_crm_tier_member_seed.sql

EXEC(N'CREATE SCHEMA [walkerhill_v4_3] AUTHORIZATION [dbo]');
GO
CREATE FUNCTION [walkerhill_v4_3].[v43_u01](@key nvarchar(512))
RETURNS decimal(19,18)
WITH SCHEMABINDING
AS
BEGIN
  DECLARE @hash varbinary(32)=HASHBYTES('SHA2_256',CONVERT(varchar(1024),CONCAT('20260814|',@key)));
  DECLARE @raw decimal(20,0)=CONVERT(decimal(20,0),CONVERT(bigint,SUBSTRING(@hash,1,7)))*16
                           +CONVERT(int,CONVERT(tinyint,SUBSTRING(@hash,8,1)))/16;
  RETURN CONVERT(decimal(19,18),@raw/CONVERT(decimal(20,0),1152921504606846976));
END;
GO
CREATE FUNCTION [walkerhill_v4_3].[v43_journey_pos_eligible_amount](@journey_seq int)
RETURNS bigint
WITH SCHEMABINDING
AS
BEGIN
  DECLARE @outlet_seq int=CASE (@journey_seq-1)%3 WHEN 0 THEN 2 WHEN 1 THEN 7 ELSE 11 END;
  DECLARE @item_code varchar(16)=CONCAT('MI_',RIGHT(CONCAT('0',@outlet_seq),2),'_01');
  DECLARE @business_date date=DATEADD(day,((@journey_seq-1)/3)*3,CONVERT(date,'2024-01-01'));
  DECLARE @base decimal(18,4)=CASE WHEN @outlet_seq IN(2,7) THEN 68000 ELSE 26000 END;
  DECLARE @price decimal(18,4)=@base*(0.88+0.12*[walkerhill_v4_3].[v43_u01](CONCAT('menu-price|',@item_code)));
  IF @business_date>=CONVERT(date,'2025-01-01')
    SET @price=@price*(1.03+0.04*[walkerhill_v4_3].[v43_u01](CONCAT('menu-reprice|',@item_code)));
  IF @business_date>=CONVERT(date,'2026-01-01')
    SET @price=@price*(1.025+0.035*[walkerhill_v4_3].[v43_u01](CONCAT('menu-reprice-2026|',@item_code)));
  RETURN CONVERT(bigint,ROUND(@price,-3));
END;
GO
CREATE TABLE [walkerhill_v4_3].[crm_membership_tiers](
  tier_code varchar(24) NOT NULL,public_name nvarchar(100) NOT NULL,synthetic_rank int NOT NULL,
  source_url nvarchar(500) NOT NULL,provenance_class varchar(48) NOT NULL,is_active bit NOT NULL
);
CREATE TABLE [walkerhill_v4_3].[crm_members](
  member_no varchar(40) NOT NULL,joined_at datetimeoffset(3) NOT NULL,current_tier_code varchar(24) NOT NULL,
  member_status varchar(24) NOT NULL,points_balance bigint NOT NULL,is_synthetic bit NOT NULL
);
CREATE TABLE [walkerhill_v4_3].[crm_member_grade_history](
  grade_history_id varchar(72) NOT NULL,member_no varchar(40) NOT NULL,tier_code varchar(24) NOT NULL,
  valid_from datetimeoffset(3) NOT NULL,valid_to datetimeoffset(3),change_reason varchar(40) NOT NULL,is_synthetic bit NOT NULL
);
CREATE TABLE [walkerhill_v4_3].[crm_point_transactions](
  point_txn_id varchar(72) NOT NULL,member_no varchar(40) NOT NULL,event_at datetimeoffset(3) NOT NULL,
  txn_type varchar(24) NOT NULL,points_delta bigint NOT NULL,related_source varchar(24) NOT NULL,
  related_id varchar(72) NOT NULL,is_synthetic bit NOT NULL
);
CREATE TABLE [walkerhill_v4_3].[crm_customer_map](
  customer_map_id varchar(72) NOT NULL,member_no varchar(40) NOT NULL,pms_guest_id varchar(40),
  pos_customer_ref varchar(40),facility_user_ref varchar(40),banquet_customer_id varchar(40),
  valid_from datetimeoffset(3) NOT NULL,valid_to datetimeoffset(3),mapping_status varchar(24) NOT NULL,
  mapping_confidence decimal(5,4) NOT NULL,is_synthetic bit NOT NULL
);
CREATE TABLE [walkerhill_v4_3].[crm_voc_reviews](
  voc_review_id varchar(72) NOT NULL,submitted_at datetimeoffset(3) NOT NULL,source_business_date date NOT NULL,hotel_code varchar(32) NOT NULL,
  source_channel varchar(32) NOT NULL,touchpoint varchar(24) NOT NULL,selected_category varchar(40) NOT NULL,
  related_source varchar(24) NOT NULL,related_id varchar(72),member_no varchar(40),
  outlet_id varchar(40),facility_id varchar(40),visit_cohort varchar(16) NOT NULL,prior_visit_count smallint NOT NULL,
  rating_overall tinyint NOT NULL,rating_service tinyint NOT NULL,rating_cleanliness tinyint,
  rating_food tinyint,rating_facility tinyint,rating_value tinyint NOT NULL,
  review_title nvarchar(200) NOT NULL,review_text_original nvarchar(2000) NOT NULL,language_code char(2) NOT NULL,
  is_external bit NOT NULL,consent_for_analysis bit NOT NULL,is_synthetic bit NOT NULL
);
CREATE TABLE [walkerhill_v4_3].[crm_voc_analysis](
  voc_analysis_id varchar(72) NOT NULL,voc_review_id varchar(72) NOT NULL,analyzed_at datetimeoffset(3) NOT NULL,
  model_version varchar(40) NOT NULL,sentiment_label varchar(16) NOT NULL,sentiment_score decimal(6,5) NOT NULL,
  primary_topic varchar(40) NOT NULL,urgency_level varchar(16) NOT NULL,requires_followup bit NOT NULL,
  analysis_confidence decimal(5,4) NOT NULL,is_synthetic bit NOT NULL
);
GO

-- SQL Server 네이티브 데이터 사전: SSMS의 Properties 및 sys.extended_properties에서 조회한다.
EXEC sys.sp_addextendedproperty N'MS_Description',N'멤버십 등급의 공개 명칭과 합성 모델용 순위를 관리하는 기준 테이블.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_membership_tiers';
EXEC sys.sp_addextendedproperty N'MS_Description',N'등급을 식별하는 영문 코드. 회원·등급 이력의 논리적 참조 키.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_membership_tiers',N'COLUMN',N'tier_code';
EXEC sys.sp_addextendedproperty N'MS_Description',N'공개 웹사이트에서 확인 가능한 고객 노출용 등급명.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_membership_tiers',N'COLUMN',N'public_name';
EXEC sys.sp_addextendedproperty N'MS_Description',N'합성 데이터 생성 시 등급 간 서열을 비교하기 위한 정수 순위.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_membership_tiers',N'COLUMN',N'synthetic_rank';
EXEC sys.sp_addextendedproperty N'MS_Description',N'등급명 근거를 확인한 공개 페이지 URL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_membership_tiers',N'COLUMN',N'source_url';
EXEC sys.sp_addextendedproperty N'MS_Description',N'OFFICIAL_FACT 또는 SYNTHETIC_ASSUMPTION 등 값의 출처 분류.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_membership_tiers',N'COLUMN',N'provenance_class';
EXEC sys.sp_addextendedproperty N'MS_Description',N'생성 기준일 현재 사용 가능한 등급인지 나타내는 비트 값.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_membership_tiers',N'COLUMN',N'is_active';

EXEC sys.sp_addextendedproperty N'MS_Description',N'개인 식별정보 없이 멤버십 상태와 현재 포인트 잔액을 재현한 합성 회원 마스터.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_members';
EXEC sys.sp_addextendedproperty N'MS_Description',N'실제 회원번호와 무관한 결정적 합성 회원 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_members',N'COLUMN',N'member_no';
EXEC sys.sp_addextendedproperty N'MS_Description',N'한국 표준시 오프셋을 포함한 합성 가입 시각.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_members',N'COLUMN',N'joined_at';
EXEC sys.sp_addextendedproperty N'MS_Description',N'2026-08-31 종료 시점의 현재 멤버십 등급 코드.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_members',N'COLUMN',N'current_tier_code';
EXEC sys.sp_addextendedproperty N'MS_Description',N'ACTIVE·DORMANT·WITHDRAWN 중 합성 회원 생애주기 상태.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_members',N'COLUMN',N'member_status';
EXEC sys.sp_addextendedproperty N'MS_Description',N'시간순 포인트 원장을 합산한 종료 잔액. 생성 규칙상 중간·최종 잔액 모두 0 이상.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_members',N'COLUMN',N'points_balance';
EXEC sys.sp_addextendedproperty N'MS_Description',N'실제 고객 자료가 아닌 합성 레코드임을 나타내며 항상 1.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_members',N'COLUMN',N'is_synthetic';

EXEC sys.sp_addextendedproperty N'MS_Description',N'회원 가입과 승급에 따른 유효기간형 등급 변화를 보존하는 이력 테이블.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_member_grade_history';
EXEC sys.sp_addextendedproperty N'MS_Description',N'등급 이력 행의 결정적 합성 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_member_grade_history',N'COLUMN',N'grade_history_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'등급 변화를 겪은 합성 회원 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_member_grade_history',N'COLUMN',N'member_no';
EXEC sys.sp_addextendedproperty N'MS_Description',N'해당 유효기간에 적용되는 멤버십 등급 코드.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_member_grade_history',N'COLUMN',N'tier_code';
EXEC sys.sp_addextendedproperty N'MS_Description',N'등급 적용이 시작된 한국 표준시 시각.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_member_grade_history',N'COLUMN',N'valid_from';
EXEC sys.sp_addextendedproperty N'MS_Description',N'등급 적용 종료 시각. 현재 유효한 최종 이력은 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_member_grade_history',N'COLUMN',N'valid_to';
EXEC sys.sp_addextendedproperty N'MS_Description',N'JOIN 또는 ANNUAL_SPEND 등 합성 등급 변경 사유.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_member_grade_history',N'COLUMN',N'change_reason';
EXEC sys.sp_addextendedproperty N'MS_Description',N'실제 고객 이력이 아닌 합성 행임을 나타내며 항상 1.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_member_grade_history',N'COLUMN',N'is_synthetic';

EXEC sys.sp_addextendedproperty N'MS_Description',N'적립·사용·만료를 부호 있는 증감값으로 기록한 멤버십 포인트 원장.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_point_transactions';
EXEC sys.sp_addextendedproperty N'MS_Description',N'포인트 원장 행의 결정적 합성 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_point_transactions',N'COLUMN',N'point_txn_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'포인트 변동 대상 합성 회원 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_point_transactions',N'COLUMN',N'member_no';
EXEC sys.sp_addextendedproperty N'MS_Description',N'포인트가 적립·사용·만료된 한국 표준시 시각.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_point_transactions',N'COLUMN',N'event_at';
EXEC sys.sp_addextendedproperty N'MS_Description',N'EARN·REDEEM·EXPIRE 중 원장 거래 유형.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_point_transactions',N'COLUMN',N'txn_type';
EXEC sys.sp_addextendedproperty N'MS_Description',N'적립은 양수, 사용·만료는 음수로 기록한 포인트 변동량.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_point_transactions',N'COLUMN',N'points_delta';
EXEC sys.sp_addextendedproperty N'MS_Description',N'PMS_GUEST·POS_ORDER·CRM_EXPIRY·CRM_CAMPAIGN 중 포인트 근거 객체 유형.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_point_transactions',N'COLUMN',N'related_source';
EXEC sys.sp_addextendedproperty N'MS_Description',N'PMS guest_id·POS order_id 또는 자체 만료 이벤트의 결정적 합성 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_point_transactions',N'COLUMN',N'related_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'실제 포인트 거래가 아닌 합성 행임을 나타내며 항상 1.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_point_transactions',N'COLUMN',N'is_synthetic';

EXEC sys.sp_addextendedproperty N'MS_Description',N'서로 다른 운영 시스템의 비식별 합성 고객 키를 회원 키에 연결하는 교차 도메인 매핑.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map';
EXEC sys.sp_addextendedproperty N'MS_Description',N'고객 매핑 행의 결정적 합성 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'customer_map_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'매핑 기준이 되는 CRM 합성 회원 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'member_no';
EXEC sys.sp_addextendedproperty N'MS_Description',N'PMS의 합성 투숙객 식별자. 미연결 회원은 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'pms_guest_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'POS 주문의 비식별 합성 고객 참조값. 미연결 회원은 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'pos_customer_ref';
EXEC sys.sp_addextendedproperty N'MS_Description',N'시설 이용 이벤트의 비식별 합성 사용자 참조값. 미연결 회원은 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'facility_user_ref';
EXEC sys.sp_addextendedproperty N'MS_Description',N'연회 예약의 합성 고객 식별자. 미연결 회원은 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'banquet_customer_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'교차 시스템 매핑이 유효해진 한국 표준시 시각.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'valid_from';
EXEC sys.sp_addextendedproperty N'MS_Description',N'매핑 유효 종료 시각. 현재 매핑은 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'valid_to';
EXEC sys.sp_addextendedproperty N'MS_Description',N'ACTIVE 또는 EXPIRED인 합성 매핑 상태.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'mapping_status';
EXEC sys.sp_addextendedproperty N'MS_Description',N'0~1 범위의 합성 키 연결 신뢰도. 실제 매칭 정확도를 뜻하지 않음.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'mapping_confidence';
EXEC sys.sp_addextendedproperty N'MS_Description',N'실제 개인 식별 연결이 아닌 합성 매핑임을 나타내며 항상 1.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_customer_map',N'COLUMN',N'is_synthetic';

EXEC sys.sp_addextendedproperty N'MS_Description',N'내부 설문·QR과 외부 리뷰 형식의 평점·원문을 개인정보 없이 재현한 합성 VOC 원본 테이블.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews';
EXEC sys.sp_addextendedproperty N'MS_Description',N'VOC 리뷰 행의 결정적 합성 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'voc_review_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'한국 표준시 오프셋을 포함한 리뷰 제출 시각.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'submitted_at';
EXEC sys.sp_addextendedproperty N'MS_Description',N'리뷰가 평가하는 PMS·POS·시설·연회 이용의 원 영업일. 제출일과 분리해 운영 지표에 귀속.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'source_business_date';
EXEC sys.sp_addextendedproperty N'MS_Description',N'GRAND·VISTA·DOUGLAS 중 리뷰 분석 대상 합성 호텔 코드. Trino에서 PMS 호텔 마스터와 논리 검증.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'hotel_code';
EXEC sys.sp_addextendedproperty N'MS_Description',N'POST_STAY_SURVEY·IN_STAY_QR·FNB_QR·FACILITY_QR·BANQUET_SURVEY·PUBLIC_REVIEW_SYNTHETIC 중 수집 채널.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'source_channel';
EXEC sys.sp_addextendedproperty N'MS_Description',N'CHECKOUT·ROOM·FNB·FACILITY·BANQUET·OVERALL 중 고객 여정 접점.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'touchpoint';
EXEC sys.sp_addextendedproperty N'MS_Description',N'고객이 선택한 합성 의견 범주. NLP 분석의 primary_topic과 구분되는 원본 응답 필드.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'selected_category';
EXEC sys.sp_addextendedproperty N'MS_Description',N'PMS_STAY·POS_ORDER·FACILITY_USAGE·BANQUET_BOOKING·NONE 중 관련 운영 객체 유형.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'related_source';
EXEC sys.sp_addextendedproperty N'MS_Description',N'관련 원천의 합성 stay_id·order_id·usage_event_id·banquet_event_id. 외부 합성 리뷰는 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'related_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'동의 기반 고객 여정 연결을 재현한 합성 회원 식별자. 비회원·외부 리뷰는 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'member_no';
EXEC sys.sp_addextendedproperty N'MS_Description',N'FNB 접점의 POS 업장 식별자. 다른 접점은 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'outlet_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'시설 접점의 합성 시설 식별자. 다른 접점은 NULL.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'facility_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'원천 키에서 재생성한 NEW·RETURNING 합성 방문 코호트.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'visit_cohort';
EXEC sys.sp_addextendedproperty N'MS_Description',N'이번 이용 전의 합성 방문 횟수. NEW는 0, RETURNING은 1 이상.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'prior_visit_count';
EXEC sys.sp_addextendedproperty N'MS_Description',N'1점 매우 불만족부터 5점 매우 만족까지의 합성 종합 평점.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'rating_overall';
EXEC sys.sp_addextendedproperty N'MS_Description',N'1~5 범위의 직원 응대·서비스 합성 평점.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'rating_service';
EXEC sys.sp_addextendedproperty N'MS_Description',N'객실 접점 리뷰에만 기록하는 1~5 범위의 합성 청결 평점.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'rating_cleanliness';
EXEC sys.sp_addextendedproperty N'MS_Description',N'식음·연회 접점 리뷰에만 기록하는 1~5 범위의 합성 음식 평점.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'rating_food';
EXEC sys.sp_addextendedproperty N'MS_Description',N'시설 접점 리뷰에만 기록하는 1~5 범위의 합성 시설 평점.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'rating_facility';
EXEC sys.sp_addextendedproperty N'MS_Description',N'1~5 범위의 가격 대비 가치 합성 평점.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'rating_value';
EXEC sys.sp_addextendedproperty N'MS_Description',N'선택 범주와 평점 방향을 반영해 조합한 합성 리뷰 제목.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'review_title';
EXEC sys.sp_addextendedproperty N'MS_Description',N'실제 고객·외부 플랫폼 문장을 복제하지 않은 조합형 합성 리뷰 원문.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'review_text_original';
EXEC sys.sp_addextendedproperty N'MS_Description',N'원문 ISO 639-1 언어 코드. 현재 합성 버전은 ko.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'language_code';
EXEC sys.sp_addextendedproperty N'MS_Description',N'외부 리뷰 형식이면 1. 실제 외부 사이트에서 수집했다는 뜻은 아님.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'is_external';
EXEC sys.sp_addextendedproperty N'MS_Description',N'분석 이용 동의가 있는 합성 응답인지 나타내며 현재 항상 1.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'consent_for_analysis';
EXEC sys.sp_addextendedproperty N'MS_Description',N'실제 VOC가 아닌 합성 행임을 나타내며 항상 1.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_reviews',N'COLUMN',N'is_synthetic';

EXEC sys.sp_addextendedproperty N'MS_Description',N'VOC 원문을 변경하지 않고 규칙 기반 감성·주제·긴급도를 별도로 저장한 합성 분석 결과.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis';
EXEC sys.sp_addextendedproperty N'MS_Description',N'VOC 분석 결과의 결정적 합성 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'voc_analysis_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'분석 대상 crm_voc_reviews의 리뷰 식별자.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'voc_review_id';
EXEC sys.sp_addextendedproperty N'MS_Description',N'리뷰 제출 후 결정적 지연을 더한 한국 표준시 분석 완료 시각.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'analyzed_at';
EXEC sys.sp_addextendedproperty N'MS_Description',N'분석 규칙 또는 모델 버전. 현재 RULE_SENTIMENT_V1.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'model_version';
EXEC sys.sp_addextendedproperty N'MS_Description',N'평점과 리뷰 방향으로 생성한 POSITIVE·NEUTRAL·NEGATIVE 감성 라벨.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'sentiment_label';
EXEC sys.sp_addextendedproperty N'MS_Description',N'-1 부정부터 +1 긍정 범위의 합성 감성 점수.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'sentiment_score';
EXEC sys.sp_addextendedproperty N'MS_Description',N'분석기가 분류한 주요 운영 주제 코드. 원본 선택 범주와 독립 보존.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'primary_topic';
EXEC sys.sp_addextendedproperty N'MS_Description',N'LOW·MEDIUM·HIGH 중 운영 확인 긴급도.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'urgency_level';
EXEC sys.sp_addextendedproperty N'MS_Description',N'1~2점 또는 안전·정비 관련 저평점으로 후속 확인이 필요하면 1.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'requires_followup';
EXEC sys.sp_addextendedproperty N'MS_Description',N'0~1 범위의 합성 분류 신뢰도. 실제 ML 성능 지표가 아님.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'analysis_confidence';
EXEC sys.sp_addextendedproperty N'MS_Description',N'실제 모델 추론이 아닌 합성 분석 행임을 나타내며 항상 1.',N'SCHEMA',N'walkerhill_v4_3',N'TABLE',N'crm_voc_analysis',N'COLUMN',N'is_synthetic';
GO
