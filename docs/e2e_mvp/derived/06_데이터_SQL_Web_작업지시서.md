# 데이터 SQL Web 작업지시서

> 상태: 사용 중단. 2026-08-12 Docker 감사 기록으로만 보존하며 신규 데이터 작업의 지시서로 사용하지 않는다.

이 문서는 Web에서 Answervice 합성 데이터 SQL을 다시 만들 때 그대로 붙여 넣는 작업지시서다. 2026-08-12에 실행 중인 Docker 컨테이너를 읽기 전용으로 조회해 스키마, 적재량, 값 분포, Trino 연결 결과를 확인했다.

Codex에서는 데이터 행과 생성 SQL을 만들지 않는다. Web은 이 문서에 적힌 실제 구조를 기준으로 SQL 파일을 만들고, Codex는 결과를 받아 Docker에 적용·검증한다.

## 1. 이번 작업의 범위

### 목표

- 현재 업무 테이블과 컬럼을 그대로 사용한다.
- 한 호텔의 2022~2026년 운영처럼 보이는 합성 데이터를 만든다.
- PMS 1 Source, PMS+CRM 2 Source, PMS+CRM+POS 3 Source 질문을 우선 재현한다.
- 이후 Banquet과 Facility도 같은 스냅샷과 호텔 운영 흐름에 연결한다.
- 고정 seed로 언제 다시 실행해도 같은 행과 같은 결과가 나오게 한다.

### 하지 않는 것

- 실제 고객 데이터, 이름, 전화번호, 이메일 등 PII를 사용하지 않는다.
- 업무 테이블이나 컬럼을 임의로 추가·삭제·개명하지 않는다.
- 기존 Gold 합계 `475,972,400원`에 새 데이터를 억지로 맞추지 않는다.
- 단순히 CHECK와 FK만 통과하는 균등 반복 데이터를 만들지 않는다.
- Web은 Docker를 실행했다고 주장하지 않는다. Web에서 실행하지 못한 검증은 `NOT_RUN`으로 둔다.

스냅샷 메타데이터가 부족한 문제는 업무 테이블 변경과 분리한다. 필요하면 `dataset_snapshot_metadata` 같은 별도 메타 테이블과 migration을 제안하되, 기존 업무 테이블 구조는 유지한다.

## 2. Docker에서 확인한 실행 환경

| Source | Container / Engine | Database / Trino FQN | 현재 seed mount |
|---|---|---|---|
| PMS | `pms-postgres` / PostgreSQL 16.13 | `pms_db` / `pms.public.*` | `260729_01_pms_postgresql_2022_2026_v2.2.sql` |
| POS | `pos-mysql` / MySQL 8.4.6 | `pos_db` / `pos.pos_db.*` | `260729_02_pos_mysql_2022_2026_v2.2.sql` |
| CRM | `crm-mssql` / SQL Server 2022 CU17 | `crm_db` / `crm.dbo.*` | `260729_03_crm_sqlserver_2022_2026_v2.2.sql` |
| Facility | `facility-clickhouse` / ClickHouse 24.8.4.13 | `facility` / `facility.facility.*` | `260729_04_facility_clickhouse_2022_2026_v2.2.sql` |
| Banquet | `banquet-postgres` / PostgreSQL 16.13 | `banquet_db` / `banquet.public.*` | `260729_05_banquet_postgresql_2022_2026_v2.2.sql` |
| Query | `hotel-synthetic-db-trino-1` / Trino 476 | catalogs `pms`, `pos`, `crm`, `facility`, `banquet`, `serving` | DDL 폴더 read-only mount |

현재 모든 Source의 `schema_version`은 `1.0.0`, `seed_metadata`는 `20260729 / synthetic`이다. Compose는 `sql/data/*_v2.2.sql`을 실제로 mount한다. 별도 release 폴더의 v2.3 정적 검증 결과는 현재 데이터의 실행 근거가 아니다.

## 3. 실제 업무 스키마 계약

아래 구조가 Web이 따라야 할 기준이다. 타입 길이와 허용 상태값도 바꾸지 않는다.

### 3.1 PMS — PostgreSQL, Asia/Seoul

`pms_guests`

- `property_id varchar(64) NOT NULL`
- `guest_id varchar(36) PK`
- `guest_segment varchar(24)`: `LEISURE | BUSINESS | GROUP`
- `country_group varchar(24)`
- `crm_mapping_eligible boolean`
- `created_at timestamptz`, `source_updated_at timestamptz`, `is_synthetic boolean=true`
- Unique: `(property_id, guest_id)`

`pms_room_inventory_daily`

- Key: `inventory_id bigint PK`, Unique `(property_id, business_date, room_type_code)`
- `business_date date`
- `room_type_code`: `STANDARD | DELUXE | SUITE | RESIDENCE`
- `physical_rooms`, `out_of_order_rooms`, `house_use_rooms`, `available_room_nights` integer
- `available_room_nights = physical_rooms - out_of_order_rooms - house_use_rooms`
- `data_period_status`, `is_forecast`, `is_synthetic`, `source_updated_at`

`pms_reservations`

- Key: `reservation_id varchar(36) PK`, FK `guest_id -> pms_guests.guest_id`
- 시점: `booked_at timestamptz`, `checkin_date date`, `checkout_date date`, `cancelled_at timestamptz NULL`
- 분류: `room_type_code`, `rate_plan_code`, `market_segment`, `booking_channel`, `reservation_status`, `cancellation_reason_code`
- 상태: `reservation_status = BOOKED | CANCELLED | CHECKED_IN | CHECKED_OUT | NO_SHOW`
- 채널: `DIRECT | OTA | CORPORATE`; 시장: `LEISURE | BUSINESS | GROUP`
- 인원: `adult_count`, `child_count`
- 금액 `numeric(14,2)`: `quoted_room_rate`, `gross_room_amount`, `discount_amount`, `commission_amount`, `booked_amount`, `refund_amount`, `cancellation_fee`
- 계산식: `gross_room_amount = quoted_room_rate * 숙박일수`, `booked_amount = gross - discount`
- 취소 행: `refund_amount + cancellation_fee = booked_amount`; 비취소 행은 refund와 fee가 0
- `data_period_status`, `is_forecast`, `is_synthetic`, `source_updated_at`

`pms_stays`

- Key: `stay_id varchar(36) PK`, Unique/FK `reservation_id`, FK `guest_id`
- `room_unit_code`, `actual_checkin_at timestamptz NULL`, `actual_checkout_at timestamptz NULL`, `room_type_code`
- `occupied_room_nights`, `guest_count`, `complimentary_flag`, `house_use_flag`
- `room_revenue numeric(14,2)`, `other_room_charges numeric(14,2)`
- `stay_status = EXPECTED | IN_HOUSE | COMPLETED | CANCELLED | NO_SHOW`
- 무료·house-use 행은 `room_revenue=0`; `pms_stays`는 실제 체류이므로 `is_forecast=false`

`pms_stays_actual`은 `pms_stays` 중 forecast가 아닌 행을 보여 주는 view다.

### 3.2 POS — MySQL, 업무시간 Asia/Seoul

`pos_stores`

- Key: `store_id varchar(32) PK`, Unique `(property_id, store_id)`
- `store_name`, `store_category`, `seat_capacity`, `open_time`, `close_time`, `is_active`, `is_synthetic`, `source_updated_at datetime(3)`

`pos_service_periods`

- Key: `service_period_id bigint PK`, FK `store_id`, Unique `(property_id, store_id, business_date, service_period)`
- `business_date`, `service_period`, `seat_capacity`, `open_minutes`, `covers`
- `seat_hours_available decimal(14,2)`, `seat_hours_used decimal(14,2)`이며 used는 available 이하
- `data_period_status`, `is_forecast`, `is_synthetic`, `source_updated_at`

`pos_orders`

- Key: `order_id varchar(36) PK`, FK `store_id`
- Identity: `pos_customer_ref varchar(36) NULL`
- 시점: `ordered_at`, `check_opened_at`, `check_closed_at NULL`, `source_updated_at` 모두 `datetime(3)`
- `guest_count`, `service_period`
- `order_status = OPEN | PAID | VOID | PARTIAL_REFUND | REFUNDED`
- 금액 `decimal(14,2)`: `gross_amount`, `discount_amount`, `refund_amount`, `net_amount`, `payment_amount`
- `payment_status = PAID | PARTIAL_REFUND | REFUNDED | FAILED`, `void_flag`
- `data_period_status`, `is_forecast`, `is_synthetic`

`pos_order_items`

- Key: `order_item_id varchar(36) PK`, FK `order_id`
- `item_code`, `item_category`, `quantity`, `unit_price`, `gross_amount`, `discount_amount`, `net_amount`
- 계산식: `net_amount = gross_amount - discount_amount`

주의: MySQL `datetime(3)`에는 timezone 정보가 없다. seed의 모든 값은 Asia/Seoul 업무시각으로 정의하고 Trino에서도 명시적으로 같은 해석을 적용한다.

### 3.3 CRM — SQL Server, 업무시간 Asia/Seoul

`crm_members`

- Key: `member_no varchar(36) PK`, Unique `(property_id, member_no)`
- `membership_grade = BASIC | SILVER | GOLD | VIP`
- `points_balance integer >= 0`, `joined_at datetime2(3)`
- `member_status = ACTIVE | INACTIVE | REVOKED`
- `data_period_status`, `is_forecast`, `is_synthetic`, `source_updated_at`

`crm_member_grade_history`

- Key: `grade_history_id varchar(36) PK`, FK `member_no`
- `grade_code = BASIC | SILVER | GOLD | VIP`
- `[valid_from, valid_to)` `datetime2(3)`, `valid_to NULL`은 현재 구간
- `change_reason_code`, `is_synthetic`, `source_updated_at`
- Trigger가 같은 회원의 기간 중첩을 차단한다.

`crm_customer_map`

- Key: `customer_map_id varchar(36) PK`, FK `member_no`
- nullable local ID: `pms_guest_id`, `pos_customer_ref`, `facility_user_ref`, `banquet_customer_id`
- `[valid_from, valid_to)`, `mapping_status = ACTIVE | REVOKED`
- `mapping_confidence decimal(5,4)`, `is_synthetic`, `source_updated_at`
- filtered unique index와 trigger가 Source ID별 active 중복 및 기간 중첩을 차단한다.

`crm_point_transactions`

- Key: `point_txn_id varchar(36) PK`, FK `member_no`
- `event_at datetime2(3)`, `txn_type = EARN | USE | EXPIRE | ADJUST`, `points_delta integer`
- `related_source NULL`, `related_id NULL`, `data_period_status`, `is_forecast`, `is_synthetic`, `source_updated_at`

주의: `datetime2(3)`에도 timezone 정보가 없다. 값은 Asia/Seoul 업무시각으로 생성하고 Trino 변환 규칙을 함께 낸다.

### 3.4 Banquet — PostgreSQL, Asia/Seoul

`banquet_bookings`

- Key: `banquet_event_id varchar(36) PK`; CRM과 연결되는 `customer_id varchar(36)`
- `inquiry_at`, `quoted_at NULL`, `confirmed_at NULL`, `cancelled_at NULL`, `event_date`
- `product_code`, `product_category = WEDDING | CONFERENCE | MEETING | CORPORATE_EVENT | SOCIAL_EVENT`
- `expected_guests`, `actual_attendees NULL`, `lead_source`, `sales_owner_team`
- `booking_status = INQUIRY | QUOTED | TENTATIVE | CONFIRMED | CANCELLED | COMPLETED`
- `contracted_amount`, `cancellation_fee`
- 객실 블록: `reserved_room_block_count`, `expected_room_nights`, `group_checkin_date NULL`, `group_checkout_date NULL`, `released_room_count`, `pickup_room_count`
- `pickup <= reserved - released`, `expected_room_nights >= pickup`

`banquet_revenue`

- Key: `revenue_id varchar(36) PK`, FK `banquet_event_id`
- `recognized_date`, `product_code`
- `product_category = VENUE | FOOD_BEVERAGE | EQUIPMENT | DECORATION | SERVICE | ACCOMMODATION_PACKAGE`
- `revenue_amount`, `reversal_amount`, `cost_amount`
- `revenue_status = EXPECTED | RECOGNIZED | REVERSED`
- reversed 행은 revenue 0, reversal 양수다.

### 3.5 Facility — ClickHouse, UTC 저장

`facility_master`

- `(property_id, facility_id)` 정렬키
- `facility_name`, `facility_type`, `owner_team`, `capacity`, `open_hour`, `close_hour`, `is_active`, `is_synthetic`, `source_updated_at DateTime64(3,'UTC')`

`facility_events`

- 정렬키 `(property_id, facility_id, event_at, event_id)`
- `facility_user_ref Nullable(String)`, `event_type = USAGE | INSPECTION | INCIDENT`
- `event_status`, `severity Nullable`, `duration_minutes`, `amount`, `downtime_minutes`
- `event_at`, `source_updated_at`은 UTC 저장

`facility_resource_daily`

- 정렬키 `(property_id, business_date, resource_scope)`
- `energy_kwh`, `water_m3`, `waste_kg`, `resource_cost`, `scheduled_hours`, `downtime_hours`

`hotel_staffing_daily`

- 정렬키 `(property_id, business_date, department)`
- `approved_positions`, `scheduled_hours`, `worked_hours`, `labor_cost`, `fte`, `vacancies`, `new_hires`, `separations`

ClickHouse에는 PostgreSQL식 FK가 없다. Web이 별도 validation SQL로 event의 `facility_id`, CRM map, 일자별 중복을 검사해야 한다.

## 4. 현재 적재 데이터 실측

### 4.1 행 수와 기간

| Source | 실제 행 수 | 실제 기간 |
|---|---:|---|
| PMS | guest 100,000 / reservation 220,000 / stay 167,071 / inventory 7,304 | 예약·재고 2022-01~2026-12, 실제 stay 2026-07-28까지 |
| POS | store 8 / order 320,000 / item 960,000 / service period 53,440 | 2022-01-01~2026-07-28 |
| CRM | member 80,000 / map 80,000 / grade history 120,000 / point txn 320,000 | 가입·map 2023년 말, grade 2024년 말, point 2024-04-29에 종료 |
| Banquet | booking 6,000 / revenue 10,902 | 2022-01~2026-12 |
| Facility | master 20 / event 700,000 / resource daily 6,680 / staffing daily 11,690 | 2022-01-01~2026-07-28 |

### 4.2 구조적 무결성

- PMS reservation→guest, stay→reservation orphan은 0건이고 stay의 guest 불일치도 0건이다.
- CRM grade 기간 중첩은 0건이며 회원마다 open grade 1건, open map 1건이 있다.
- Trino에서 다섯 Source catalog가 모두 조회된다.
- 현재 3-Source Gold SQL은 Trino 476에서 실제 재현됐다.

```text
SYNTHETIC_HOTEL_001 | 2026-05 | 218275200.00 | 39326900.00 | 257602100.00
SYNTHETIC_HOTEL_001 | 2026-06 | 180813600.00 | 37556700.00 | 218370300.00
합계: 475972400.00
```

이 결과는 현재 seed의 재현 증거일 뿐 새 seed가 따라야 할 목표 금액은 아니다.

### 4.3 현실성 문제

1. PMS 예약의 시장 세그먼트와 예약 채널이 각각 거의 정확히 1/3이다. 할인 적용 예약은 0건이고 NO_SHOW도 0건이다.
2. PMS 취소율은 22.08%지만 취소 사유·채널·리드타임·성수기와 연결된 분포가 아니라 반복 규칙에 가깝다.
3. PMS guest의 segment×country×CRM 대상 여부 조합도 거의 동일 건수로 반복된다.
4. POS 8개 매장은 주문이 정확히 40,000건씩이다. BREAKFAST/LUNCH/AFTERNOON/DINNER도 정확히 80,000건씩이다.
5. POS 주문은 품목이 매번 3개이고 FOOD/BEVERAGE/SERVICE가 정확히 320,000개씩, 수량 평균이 모두 1이다.
6. POS 매장명이 `Synthetic Dining 02` 같은 placeholder다. 매장 성격과 메뉴, 영업시간, service period가 충분히 연결되지 않는다.
7. CRM 80,000명의 포인트 잔액이 전부 1,200점이다. 회원은 전부 ACTIVE, map은 전부 ACTIVE, confidence는 전부 0.9900이다.
8. CRM point 거래도 Source별 정확히 80,000건이고, 2024-04-29 이후 거래가 없어 2026년 PMS/POS와 시간축이 끊긴다.
9. Banquet product category는 각각 정확히 1,200건, lead source는 각각 정확히 1,500건이다. INQUIRY/QUOTED/TENTATIVE 상태가 0건이다.
10. Facility master 이름도 placeholder이며 resource scope와 staffing department는 각 일자에 기계적으로 한 행씩 반복된다.
11. Trino 단순 active-map join 기준 연결률은 PMS guest 68,000/100,000, POS order 134,912/320,000, Banquet 6,000/6,000, Facility event 64,800/700,000이다. Banquet 100% 연결과 Source별 고정 비율은 실제 업무 선택 편향을 표현하지 못한다.
12. PMS는 `timestamptz`, POS와 CRM은 timezone 없는 타입, Facility는 UTC 타입을 쓴다. 현재는 같은 자정 경계를 Source별로 보장하는 공통 변환 계약이 부족하다.

따라서 현재 데이터는 테스트 fixture로는 쓸 수 있지만, “실제 호텔처럼 보이는 분석용 합성 데이터”로 승인하지 않는다.

## 5. 새 데이터의 현실성 계약

아래 비율은 외부 산업 통계라고 주장하는 값이 아니다. Answervice 데모에서 비현실적인 균등 반복을 피하기 위한 프로젝트 시나리오 범위다. Web은 최종 선택값과 선택 근거를 manifest에 기록한다.

### 5.1 공통 시간축

- 한 호텔 `SYNTHETIC_HOTEL_001`을 기준으로 한다.
- 실제형 기간은 2022-01-01~2026-07-28, 스냅샷은 `2026-07-29T00:00:00+09:00`으로 고정한다.
- 2026-07-29 이후 2026-12-31은 forecast로 분리한다.
- Golden 기간은 Asia/Seoul `[2026-05-01T00:00:00, 2026-07-01T00:00:00)`다.
- 주말, 월별 계절성, 공휴일·행사 효과를 deterministic calendar table 또는 고정 lookup으로 반영한다.
- POS/CRM의 timezone 없는 timestamp는 Asia/Seoul local time, Facility는 UTC로 저장한다. 변환식과 boundary test를 함께 낸다.

### 5.2 PMS

- 객실 공급은 room type별로 고정하되 out-of-order와 house-use는 날짜별 소폭 변동한다.
- 예약량은 가용 객실과 연결하고, 과거 완료 stay가 물리적 객실 공급을 장기간 초과하지 않게 한다.
- room type별 기본 요금 차등, 주말·성수기 가산, 채널·rate plan 할인, OTA commission을 반영한다.
- `discount_amount=0`인 예약과 할인 예약을 모두 만들고, CORPORATE·DIRECT·OTA의 할인과 수수료 정책을 다르게 한다.
- 완료, 취소, no-show, 당일 check-in, 장기 숙박, 무료/house-use, 객실 타입 변경 사례를 포함한다.
- 프로젝트 목표 범위 예시: 취소 12~25%, no-show 1~3%, 무료/house-use stay 합계 0.5~2%, 1~3박 중심의 오른쪽 꼬리 분포.
- LEISURE는 주말·휴가철, BUSINESS는 평일·짧은 리드타임, GROUP은 Banquet room block과 더 자주 연결한다.
- adult/child, room type, 숙박일수, 객실료가 서로 모순되지 않게 한다.

### 5.3 POS

- 기존 8개 store ID는 유지해도 되지만, 이름은 PII 없는 현실적인 합성 outlet 이름으로 바꾼다.
- BREAKFAST 매장은 아침 시간, BAR는 저녁, CAFE는 낮, DINING은 점심·저녁 주문이 많아야 한다.
- 주문 수는 호텔 투숙·Banquet·요일·계절성과 연결하되 외부 고객 주문도 포함한다.
- 모든 주문을 정확히 같은 item 수로 만들지 않는다. 1~6개 중심, 수량 1~4 중심의 가변 분포를 만든다.
- FOOD/BEVERAGE/SERVICE item은 매장과 시간대에 맞는 `item_code`, 가격대, 할인정책을 갖는다.
- PAID, PARTIAL_REFUND, REFUNDED, VOID, OPEN을 모두 만들고 order/payment/void/net/refund 관계를 validation한다.
- member 식별 주문과 anonymous 주문을 모두 둔다. `pos_customer_ref` 존재 여부와 CRM 실제 map 여부는 별개로 검증한다.
- `pos_orders` 합계와 `pos_order_items` 합계가 주문 상태별 정의에 맞는지 검증한다.

### 5.4 CRM과 Identity

- 회원 등급은 균등 25%를 피한다. 예시 범위: BASIC 45~60%, SILVER 25~35%, GOLD 10~18%, VIP 2~7%.
- ACTIVE 외 INACTIVE와 REVOKED를 포함하되, 해당 상태의 map·point 사용이 시간상 모순되지 않게 한다.
- 회원별 point 거래 수와 잔액을 가변화하고 `points_balance`는 스냅샷까지 transaction 누계와 조정 규칙으로 재현 가능해야 한다.
- PMS/POS/Banquet/Facility 관련 거래는 실제 존재하는 Source ID를 사용한다. 일부 거래는 관련 Source가 없는 수동 ADJUST로 둔다.
- grade 승급·강등과 map 변경을 `[valid_from, valid_to)`로 만든다. exact boundary 전후 행을 반드시 포함한다.
- 문자열 유사도 join을 금지한다. 연결은 `crm_customer_map`의 승인된 local ID로만 한다.
- Source별 map coverage는 똑같은 비율을 쓰지 않는다. 선택 편향을 설명하고, 미가입·미식별·철회·과거 map 사례를 둔다.
- `mapping_confidence`를 모두 같은 값으로 두지 않는다. 다만 confidence를 join 조건으로 쓸지는 별도 identity rule로 명시한다.

### 5.5 Banquet

- inquiry→quote→tentative→confirmed→completed/cancelled 흐름이 timestamp와 status에 맞아야 한다.
- 아직 진행 중인 INQUIRY/QUOTED/TENTATIVE와 forecast CONFIRMED를 포함한다.
- WEDDING은 주말·성수기, CORPORATE/MEETING은 평일 비중을 높이는 식으로 달력과 연결한다.
- expected guests, 실제 참석자, 계약금액, venue/F&B revenue, room block pickup을 행사 유형과 연결한다.
- completed 행사만 recognized revenue를 갖고, 취소·reversal 규칙을 명확히 한다.
- PMS GROUP reservation과 room block을 전부 강제 연결하지 말고, 연결된 사례와 독립 사례를 함께 둔다.

### 5.6 Facility

- 시설 20개를 단순 번호 이름이 아닌 SPA/POOL/FITNESS/ACTIVITY/BACK_OF_HOUSE 성격이 드러나는 합성 이름으로 만든다.
- USAGE는 영업시간과 수용인원, 호텔 occupancy, 계절성과 연결한다.
- INSPECTION은 정기 주기, INCIDENT는 드문 사건으로 만들고 severity·downtime·status를 사건 흐름과 맞춘다.
- usage에 무조건 같은 amount를 넣지 않는다. 무료시설, 유료 프로그램, 회원 할인 등 설명 가능한 차이를 둔다.
- resource와 staffing은 occupancy·Banquet·Facility 활동량과 방향성이 맞아야 한다. 매일 동일 패턴을 반복하지 않는다.
- UTC event 시각을 Asia/Seoul business date로 변환하는 test를 포함한다.

## 6. 반드시 포함할 경계 사례

Web은 bulk 데이터와 별도로 ID가 명확한 작은 Golden pocket을 만든다. 이 pocket도 실제 schema에 들어가며, aggregate 포함·제외 이유를 표로 설명한다.

| 영역 | 필수 사례 |
|---|---|
| 기간 | 시작시각 정확히 포함, 종료시각 정확히 제외, UTC↔KST 자정 전후 |
| PMS | CHECKED_OUT/COMPLETED, CANCELLED+fee/refund, NO_SHOW, 무료, house-use, stay 없는 미래 BOOKED |
| POS | PAID, PARTIAL_REFUND, REFUNDED, VOID, OPEN, anonymous, map 없는 ref, item 합계 검증 |
| CRM map | valid_from 직전/정확히/직후, valid_to 직전/정확히, REVOKED, local ID NULL |
| CRM grade | GOLD 승급 직전/정확히, GOLD 종료 정확히, 등급 변경 후 거래 |
| Join | 한 회원 여러 거래, 한 주문 여러 item, 사전 집계 없는 JOIN 증폭 실패 사례 |
| Banquet | funnel 중간 상태, 취소, 완료+recognized, reversal, room block 일부 pickup |
| Facility | 영업시간 경계, inspection, open incident, closed incident, downtime 포함 |

Golden pocket의 행을 의도적으로 중복 삽입하지 않는다. 중복과 overlap 차단은 별도 실패 SQL로 검증하고 transaction rollback으로 끝낸다.

## 7. 결정론과 출력 크기

- 무작위 함수의 실행시각·세션 상태에 기대면 안 된다.
- 대량 행을 전부 손으로 literal 나열하지 않는다. 각 DB dialect에 맞는 set-based 생성 방식을 사용한다.
- PostgreSQL `generate_series`, MySQL recursive CTE 또는 고정 sequence staging, SQL Server tally CTE, ClickHouse `numbers`를 사용할 수 있다.
- 변동값은 `seed + stable business key`를 입력으로 하는 명시적 hash/modulo 규칙으로 만든다. 같은 engine/version에서 재실행 시 동일해야 한다.
- 단순 `row_number % N` 순환만으로 category를 균등 배분하지 않는다. 월·요일·Source 관계를 조건에 포함한다.
- reset 범위를 `property_id='SYNTHETIC_HOTEL_001'`와 현재 snapshot ID로 제한한다.
- PostgreSQL/SQL Server는 transaction과 오류 중단, MySQL은 FK 순서와 transaction 가능 범위, ClickHouse는 delete 완료 확인 순서를 명시한다.
- 재실행 전후 row count와 canonical result hash가 같아야 한다.

## 8. 메타데이터와 canonical 파일

다섯 Source에 같은 값을 기록한다.

- `data_snapshot_id = ANS-SYN-20260729-V3`
- `snapshot_as_of_at = 2026-07-29T00:00:00+09:00`
- `schema_version = 1.0.0`
- `seed_version = 3.0.0`
- `scenario_version = HOTEL-OPS-2026.1`
- `fixture_version = 3.0.0`
- `timezone_policy = SOURCE_LOCAL_KST__FACILITY_UTC`
- `deterministic_seed`와 `property_id`

기존 `seed_metadata(seed, data_class)`만으로는 부족하다. 별도 metadata DDL을 만들고, business seed와 Gold manifest에 같은 ID와 파일 SHA-256을 남긴다.

Web 산출 파일은 다음처럼 분리한다.

1. `00_dataset_snapshot_metadata_<dialect>_v3.0.sql`
2. `01_pms_postgresql_seed_v3.0.sql`
3. `02_pos_mysql_seed_v3.0.sql`
4. `03_crm_sqlserver_seed_v3.0.sql`
5. `04_facility_clickhouse_seed_v3.0.sql`
6. `05_banquet_postgresql_seed_v3.0.sql`
7. `10_validate_pms_v3.0.sql`부터 Source별 validation SQL
8. `20_gold_pms_1source_v3.0.sql`
9. `21_gold_pms_crm_2source_v3.0.sql`
10. `22_gold_pms_crm_pos_3source_v3.0.sql`
11. `manifest.v3.0.json`
12. `boundary_matrix.v3.0.md`
13. `compose_mount_change.v3.0.md`

DDL과 seed를 한 파일에 섞지 않는다. 업무 DDL은 현재 v1.0.0을 유지하고 metadata migration만 별도로 낸다.

## 9. 검증 계약

### Source별

- table/column/type/PK/FK/CHECK가 3장의 계약과 같은지 확인한다.
- row count, PK duplicate, FK orphan, 허용 상태값, NULL, 시간 역전, 금액 계산식을 검사한다.
- 연도·월·요일·상태·채널·등급·매장·상품 분포를 출력한다.
- min/max/평균만 보지 말고 p50/p90 또는 구간별 분포를 낸다.
- 물리적 한도와 업무 관계를 검사한다: 객실 공급, 좌석, 영업시간, point balance, room block, downtime.

### Source 간

- Source local ID의 존재율, active/event-time-valid map 연결률, 미연결 사유를 분리한다.
- `valid_from <= event_time AND (valid_to IS NULL OR event_time < valid_to)`만 허용한다.
- 한 행이 여러 map/grade에 붙어 증폭되는지 검사한다.
- PMS occupancy와 POS/Banquet/Facility 지표의 월별 방향성을 출력하되 완벽한 상관관계를 만들지 않는다.

### Golden

- 1 Source, 승인 2 Source, 승인 3 Source 각각 canonical 정렬 규칙을 고정한다.
- row count, 행 내용, 합계, SHA-256을 manifest에 기록한다.
- 새 데이터에서 산출한 Expected Result를 사용한다. 기존 `475972400.00`에 맞추지 않는다.
- Source DB load와 Trino query를 실제 실행한 뒤에만 runtime `PASS`다.
- Web에서 실행하지 않았다면 `static_validation`과 `runtime_validation`을 분리하고 runtime은 `NOT_RUN`으로 둔다.

## 10. Web에 붙여 넣을 프롬프트

아래 코드 블록과 이 문서 전체를 함께 Web에 입력한다.

```text
첨부한 「데이터 SQL Web 작업지시서」를 유일한 요구사항으로 사용해 Answervice의 합성 호텔 데이터 SQL v3.0을 작성해줘.

가장 중요한 조건은 다음과 같다.

1. 문서 3장에 적힌 현재 Docker 업무 스키마의 테이블·컬럼·타입·키·상태값을 그대로 사용한다. 새 업무 테이블이나 업무 컬럼을 임의로 만들지 않는다.
2. schema를 통과하는 것만 목표로 하지 말고, 문서 5장의 호텔 운영 관계와 6장의 boundary 사례가 데이터 값에 실제로 드러나게 한다.
3. PMS/POS/CRM을 먼저 완성해 1 Source, 2 Source, 3 Source Gold를 만들고, 같은 snapshot으로 Banquet/Facility를 완성한다.
4. 균등 modulo 반복, 전부 같은 잔액·confidence·item 수, placeholder 이름을 금지한다.
5. nondeterministic random/current timestamp/UUID에 의존하지 않는다. stable key와 seed를 사용한 set-based deterministic generator로 작성한다.
6. 기존 Gold 합계에 맞추지 말고 새 seed로 Expected Result와 hash를 다시 산출한다.
7. SQL dialect는 PostgreSQL 16, MySQL 8.4, SQL Server 2022, ClickHouse 24.8, Trino 476에 정확히 맞춘다.
8. 실제 실행하지 않은 검증은 PASS라고 쓰지 말고 NOT_RUN으로 둔다.

먼저 다음 네 표를 출력해줘.

- 현재 schema를 Source별로 어떻게 해석했는지
- 기존 데이터의 현실성 문제를 새 생성 규칙으로 어떻게 바꿀지
- Source 간 ID와 시간 연결 규칙
- boundary 사례와 aggregate 포함/제외 영향

그 다음 문서 8장에 정의된 파일 13종을 각각 완전한 파일 단위로 작성해줘. 긴 SQL은 생략, 축약, 의사코드로 대체하지 말고 다운로드 가능한 파일로 나눠줘. 각 파일 첫 부분에 dialect, database, snapshot ID, seed version, 재실행 방법을 주석으로 넣어줘.

마지막에는 적용 순서, 예상 row count, 정적 검증 결과, 아직 실제 Docker/Trino에서 실행하지 못한 항목을 분리해서 적어줘.
```

## 11. Web 결과를 Codex로 가져올 때

다음 항목을 함께 전달한다.

- Web이 만든 13종 파일 원본
- Web이 선택한 최종 비율과 그 이유
- 예상 row count와 Expected Result
- Web이 실제 실행한 것과 실행하지 않은 것
- schema 변경 제안이 있다면 업무 DDL인지 metadata migration인지 구분한 목록

Codex는 적용 전에 현재 Docker schema와 diff, SQL dialect, Secret 포함 여부, idempotency, Compose mount 경로를 확인한다. 그 다음 별도 Docker volume 또는 백업 가능한 환경에서 load하고 Source별 query→1 Source→2 Source→3 Source 순서로 검증한다.
