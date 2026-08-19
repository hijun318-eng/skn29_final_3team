-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=MySQL 8.4; target_database=walkerhill_v4_3
-- domain=POS; script_type=DDL; execution_order=10
-- dependencies=00_mysql_pos_preflight_readonly.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814; expected_rows=0
-- execution_default=NOT_RUN; destructive_operation=false
-- evidence=https://app.walkerhill.com/book/Dining
-- assumption=outlet capacity, menu, pricing, orders and payments are synthetic
-- next=20_mysql_pos_outlet_menu_seed.sql

CREATE DATABASE walkerhill_v4_3 CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE walkerhill_v4_3;
SET time_zone='+09:00';

DELIMITER //
CREATE FUNCTION v43_u01(p_key VARCHAR(512)) RETURNS DECIMAL(20,18)
DETERMINISTIC NO SQL
RETURN LEAST(CAST(0.999999999999999999 AS DECIMAL(20,18)),
  CAST(CONV(SUBSTRING(SHA2(CONCAT('20260814|',p_key),256),1,15),16,10) AS DECIMAL(38,18))
  /CAST(1152921504606846976 AS DECIMAL(38,0)))//
DELIMITER ;

CREATE TABLE pos_outlets (
  resort_id VARCHAR(32) NOT NULL COMMENT '모든 식음 업장을 묶는 합성 리조트 식별자',
  outlet_id VARCHAR(40) NOT NULL COMMENT '식음 업장의 안정적 합성 식별 코드',
  outlet_seq SMALLINT NOT NULL COMMENT '결정적 생성과 화면 정렬에 쓰는 업장 순번',
  hotel_code VARCHAR(32) NOT NULL COMMENT '업장이 귀속되는 GRAND·VISTA·DOUGLAS 합성 호텔 코드',
  public_name VARCHAR(160) NOT NULL COMMENT '워커힐 공식 다이닝 채널에서 확인한 공개 업장명',
  outlet_category VARCHAR(40) NOT NULL COMMENT 'BUFFET·KOREAN·CHINESE·ITALIAN·BAR·CAFE 등 업장 유형',
  open_time TIME NOT NULL COMMENT '시간대 주문 분포에 쓰는 합성 영업 시작 시각',
  close_time TIME NOT NULL COMMENT '시간대 주문 분포에 쓰는 합성 영업 종료 시각',
  synthetic_seat_capacity INT NOT NULL COMMENT '회전율과 주문 포화를 위한 합성 좌석 수. 공식 좌석 수가 아님',
  source_url TEXT NOT NULL COMMENT '공개 업장명 근거 URL',
  provenance_class VARCHAR(48) NOT NULL COMMENT '공개 명칭과 합성 운영 파라미터의 출처 분류',
  is_active BOOLEAN NOT NULL COMMENT '생성 기간 종료일 현재 영업 대상 여부',
  PRIMARY KEY(outlet_id),UNIQUE KEY uq_v43_outlet_seq(outlet_seq)
) ENGINE=InnoDB COMMENT='공개 식음 업장명과 합성 영업시간·좌석을 관리하는 POS 업장 마스터';
CREATE TABLE pos_menu_items (
  item_code VARCHAR(48) NOT NULL COMMENT '메뉴 품목의 안정적 합성 식별 코드',
  outlet_id VARCHAR(40) NOT NULL COMMENT '메뉴를 판매하는 합성 업장 코드',
  menu_slot SMALLINT NOT NULL COMMENT '업장 내 결정적 메뉴 생성·정렬 순번',
  item_name VARCHAR(160) NOT NULL COMMENT '실제 레시피와 무관한 합성 메뉴 표시명 또는 공개 카테고리명',
  item_category VARCHAR(40) NOT NULL COMMENT 'FOOD·BEVERAGE·ALCOHOL·DESSERT 등 메뉴 범주',
  provenance_class VARCHAR(48) NOT NULL COMMENT '공개 업장 기준과 합성 메뉴 조합의 출처 분류',
  is_active BOOLEAN NOT NULL COMMENT '생성 기간 종료일 현재 판매 여부',
  PRIMARY KEY(item_code),UNIQUE KEY uq_v43_menu_slot(outlet_id,menu_slot)
) ENGINE=InnoDB COMMENT='업장별 품목 구성과 카테고리를 제공하는 비공식 합성 메뉴 마스터';
CREATE TABLE pos_menu_price_history (
  item_code VARCHAR(48) NOT NULL COMMENT '가격 이력이 적용되는 합성 메뉴 품목 코드',
  valid_from DATE NOT NULL COMMENT '해당 합성 단가의 유효 시작일',
  valid_to DATE COMMENT '해당 합성 단가의 유효 종료일. 현재 가격은 NULL',
  unit_price_krw DECIMAL(18,2) NOT NULL COMMENT '원 단위로 반올림된 합성 메뉴 판매단가',
  price_reason VARCHAR(40) NOT NULL COMMENT 'INITIAL·ANNUAL_REPRICE·SEASONAL 등 가격 변경 사유',
  is_synthetic BOOLEAN NOT NULL COMMENT '실제 가격표가 아닌 합성 이력임을 나타내며 항상 true',
  PRIMARY KEY(item_code,valid_from)
) ENGINE=InnoDB COMMENT='기간 중 가격 변화와 주문 시점 단가 검증을 위한 합성 메뉴 가격 이력';
CREATE TABLE pos_orders (
  order_id VARCHAR(64) NOT NULL COMMENT 'POS 주문의 결정적 합성 식별자',
  outlet_id VARCHAR(40) NOT NULL COMMENT '주문이 발생한 합성 식음 업장 코드',
  business_date DATE NOT NULL COMMENT '자정 이후 영업 마감을 고려해 주문이 귀속되는 영업일',
  ordered_at DATETIME(6) NOT NULL COMMENT '한국 표준시 기준 합성 주문 발생 시각. 세션 시간대가 Asia/Seoul이어야 함',
  pos_customer_ref VARCHAR(40) COMMENT '개인정보가 아닌 CRM 교차 매핑용 합성 고객 참조값',
  linked_stay_id VARCHAR(64) COMMENT '투숙 중 식음 주문인 경우의 PMS 합성 stay_id',
  guest_count SMALLINT NOT NULL COMMENT '주문 테이블의 합성 고객 커버 수',
  service_period VARCHAR(24) NOT NULL COMMENT 'BREAKFAST·LUNCH·DINNER·LATE_NIGHT 등 서비스 시간대',
  order_status VARCHAR(24) NOT NULL COMMENT 'PAID·PARTIAL_REFUND·REFUNDED·VOID 중 주문 종료 상태',
  item_gross_amount DECIMAL(18,2) NOT NULL COMMENT '품목 할인 전 합성 금액 합계',
  discount_amount DECIMAL(18,2) NOT NULL COMMENT '주문에 적용한 합성 할인액',
  service_charge_amount DECIMAL(18,2) NOT NULL COMMENT '할인 후 공급가에 적용한 합성 봉사료',
  tax_amount DECIMAL(18,2) NOT NULL COMMENT '합성 과세 기준으로 별도 계산한 세액',
  refund_amount DECIMAL(18,2) NOT NULL COMMENT '환불 처리된 금액의 양수 표시 합계',
  void_amount DECIMAL(18,2) NOT NULL COMMENT '결제 전 취소된 금액의 양수 표시 합계',
  net_amount DECIMAL(18,2) NOT NULL COMMENT '할인·봉사료·세금·환불·취소를 반영한 최종 합성 주문액',
  payment_status VARCHAR(24) NOT NULL COMMENT 'SETTLED·REFUNDED·VOIDED 중 결제 정산 상태',
  currency_code CHAR(3) NOT NULL COMMENT '주문 통화 ISO 코드이며 현재 KRW',
  is_forecast BOOLEAN NOT NULL COMMENT '2026-08-31 종료 합성 시나리오 주문과 향후 별도 예측 행을 구분하는 플래그. false는 실제 워커힐 실적을 뜻하지 않음',
  is_synthetic BOOLEAN NOT NULL COMMENT '실제 주문이 아닌 합성 행임을 나타내며 항상 true',
  PRIMARY KEY(order_id)
) ENGINE=InnoDB COMMENT='업장·시간대·이벤트·투숙 연계를 포함하고 세금·봉사료·환불을 분리한 합성 POS 주문 헤더';
CREATE TABLE pos_order_items (
  order_item_id VARCHAR(72) NOT NULL COMMENT '주문 품목 행의 결정적 합성 식별자',
  order_id VARCHAR(64) NOT NULL COMMENT '품목이 속한 합성 POS 주문 식별자',
  item_code VARCHAR(48) NOT NULL COMMENT '판매된 합성 메뉴 품목 코드',
  quantity SMALLINT NOT NULL COMMENT '주문 품목 수량',
  unit_price DECIMAL(18,2) NOT NULL COMMENT '주문 시점 가격 이력에서 선택한 합성 단가',
  gross_amount DECIMAL(18,2) NOT NULL COMMENT 'quantity*unit_price로 계산한 할인 전 품목 금액',
  discount_amount DECIMAL(18,2) NOT NULL COMMENT '주문 할인을 품목에 배분한 합성 할인액',
  net_amount DECIMAL(18,2) NOT NULL COMMENT 'gross_amount-discount_amount인 품목 순액. 세금·봉사료 제외',
  is_synthetic BOOLEAN NOT NULL COMMENT '실제 판매 품목이 아닌 합성 행임을 나타내며 항상 true',
  PRIMARY KEY(order_item_id)
) ENGINE=InnoDB COMMENT='메뉴 가격 이력과 주문 헤더 금액을 재조정할 수 있는 합성 POS 주문 품목';
CREATE TABLE pos_payment_lines (
  payment_line_id VARCHAR(72) NOT NULL COMMENT '결제·환불 행의 결정적 합성 식별자',
  order_id VARCHAR(64) NOT NULL COMMENT '결제 또는 환불이 귀속되는 합성 주문 식별자',
  paid_at DATETIME(6) NOT NULL COMMENT '한국 표준시 기준 합성 결제·환불 처리 시각',
  transaction_type VARCHAR(24) NOT NULL COMMENT 'SALE·REFUND 중 결제 원장 거래 유형',
  tender_type VARCHAR(24) NOT NULL COMMENT 'CARD·CASH·ROOM_CHARGE·MOBILE 등 합성 결제수단',
  signed_amount DECIMAL(18,2) NOT NULL COMMENT '결제는 양수, 환불·취소는 음수인 부호 있는 거래금액',
  payment_status VARCHAR(24) NOT NULL COMMENT '결제 원장 반영이 완료된 SETTLED 처리 상태',
  is_synthetic BOOLEAN NOT NULL COMMENT '실제 결제자료가 아닌 합성 행임을 나타내며 항상 true',
  PRIMARY KEY(payment_line_id)
) ENGINE=InnoDB COMMENT='주문의 결제수단과 환불·취소를 부호 있는 금액으로 보존하는 합성 결제 원장';
