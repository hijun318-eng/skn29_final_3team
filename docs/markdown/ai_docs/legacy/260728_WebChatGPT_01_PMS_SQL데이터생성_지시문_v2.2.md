# 웹 ChatGPT 01
## PMS·객실 공급·예약·투숙 SQL 데이터 적재 지시문 v2.2

## 이 문서의 사용 방법

이 문서는 설명 자료가 아니라 **웹 ChatGPT용 직접 실행 지시문**이다.

이 문서가 업로드되거나 내용이 제공되면 다음과 같이 행동한다.

1. 사용자에게 프롬프트를 다시 복사하거나 붙여 넣으라고 요구하지 않는다.
2. 추가 문서 업로드를 요구하지 않는다.
3. 아래 명세를 읽고 즉시 맡은 영역의 SQL 생성 작업을 수행한다.
4. 긴 SQL을 채팅 본문에 전부 출력하지 않는다.
5. Python 또는 파일 생성 도구를 내부적으로 사용해 `/mnt/data`에 지정된 SQL 파일을 만든다.
6. 최종 응답에는 생성된 SQL 파일 링크와 5줄 이내의 검증 요약만 제공한다.
7. 결과 파일은 **정확히 1개의 `.sql` 파일**이어야 한다.
8. JSON, JSONL, CSV, Parquet, XLSX를 결과물로 생성하지 않는다.
9. 개별 행마다 `INSERT` 문을 반복하지 않는다. SQL 엔진의 집합 기반 생성 기능으로 데이터를 만든다.
10. 사용자에게 실행 여부를 다시 묻지 말고 작업을 완료한다.
11. DB·schema·table·column은 사전에 DDL SQL로 생성되어 있다고 가정한다.
12. 이 작업의 SQL은 `CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`, `DROP ... CASCADE`를 실행하지 않는다.
13. 명세에 필요한 컬럼이 없으면 임의 우회하지 않고 `SCHEMA_CONTRACT_MISMATCH`로 생성 작업을 중단한다.

---

## 공통 프로젝트 계약

### 목적

실제 호텔이나 실제 고객 데이터를 복제하지 않고, DataHub Core·Trino·Guarded Text-to-SQL·자동 리포팅·객실수요예측을 검증하기 위한 합성 호텔 운영 원천 데이터를 SQL로 적재한다.

### 고정값

```text
seed                  = 20260728
schema_version        = schema-v4.6-websql
scenario_version      = scenario-v4.6
data_start            = 2022-01-01
data_end              = 2026-12-31
reference_cutoff_date = 2026-06-30
simulation_as_of_date = 2026-07-28
generation_as_of_at   = 2026-07-28 05:00:00+00:00
evaluation_as_of      = 2026-07-28T00:00:00+09:00
business_timezone     = Asia/Seoul
storage_timezone      = UTC
currency              = KRW
property_id           = SYNTHETIC_HOTEL_001
property_profile      = PREMIUM_URBAN_RESORT_SYNTHETIC
synthetic_label       = SYNTHETIC_DEMO_DATA
synthetic             = true
generated_at          = 2026-07-28T05:00:00Z
fixture_version       = source-fixture-v4.6
profile               = demo
```

`reference_cutoff_date`는 공식 통계가 확보된 마지막 날짜다.
`simulation_as_of_date`는 합성 원천 데이터가 관측된 것으로 간주하는 기준일이다.
`evaluation_as_of`는 대표 질문과 point-in-time 수용시험의 기준 시각이다.
두 날짜를 같은 개념으로 취급하지 않는다.

### 기간 상태

```text
2022-01-01~2024-12-31 = REFERENCE_CALIBRATED
2025-01-01~2025-12-31 = SYNTHETIC_ACTUAL_LIKE
2026-01-01~2026-07-28 = YTD_SYNTHETIC
2026-07-29~2026-12-31 = FORECAST_SCENARIO
```

### 원천 사실·계획·전망 구분

1. 관측 거래·이벤트의 발생 시각은 `generation_as_of_at` 이후일 수 없다.
2. 미래 영업일자 행은 기준일 현재 이미 알려진 예약·계획·일정만 허용한다.
3. 미래의 주문·포인트 거래·시설 이용·장애·실제 투숙을 원천 사실처럼 생성하지 않는다.
4. 미래 예측량은 Source 거래 테이블이 아니라 ML·Analytics Scenario에서 생성한다.
5. `source_updated_at`은 행이 원천에서 마지막으로 알려진 시각이며, 관측 이벤트 시각보다 빠를 수 없다.
6. `source_updated_at`을 모든 행에 `generation_as_of_at`으로 일괄 고정하지 않는다.
7. point-in-time 검증은 `source_updated_at <= evaluation_as_of`인 행만 사용한다.
8. 실제·YTD와 forecast는 검증 결과에서 반드시 별도 행으로 출력한다.
9. 실제 질의용 View는 `is_forecast=false`만 사용한다.

### 공통 식별자 계약

```text
PMS guest_id               = GST-00000001 형식
CRM member_no              = MEM-00000001 형식
POS pos_customer_ref       = POSC-00000001 형식
Facility facility_user_ref = FACU-00000001 형식
Banquet customer_id        = BQC-00000001 형식
```

숫자 부분이 같으면 승인된 CRM 매핑을 통해 같은 합성 인물로 연결할 수 있다.
다른 Source 테이블을 물리 FK로 참조하지 않는다.

### 개인정보 금지

다음 값을 생성하지 않는다.

- 실제 사람 이름·전화번호·이메일·주소
- 카드번호·주민등록번호·여권번호
- 실제 호텔 고객번호와 혼동 가능한 값
- DB 비밀번호·토큰·키
- 특정 호텔·기업의 실제 시설명·회사명

---

## 2022~2026 레퍼런스 계약

### 2022~2024 시장 기준점

| 연도 | OCC | ADR(KRW) | RevPAR(KRW) |
|---:|---:|---:|---:|
| 2022 | 0.5879 | 138874 | 81642 |
| 2023 | 0.6603 | 148547 | 98079 |
| 2024 | 0.6790 | 169171 | 114918 |

위 값은 합성 호텔의 실제 실적이 아니라 시장 추세 보정용 기준점이다.

### 2025·2026 적용 원칙

- 2025년은 `SYNTHETIC_ACTUAL_LIKE`다.
- 2026년 1월 1일부터 7월 28일까지는 `YTD_SYNTHETIC`이다.
- 2026년 7월 29일 이후는 `FORECAST_SCENARIO`다.
- 공식 관광 수치를 호텔 거래 수·매출에 1:1로 복사하지 않는다.
- 외부 관광 수요는 약한 macro factor로만 사용한다.
- 2026년 1~6월 외래객 증가율의 영향은 최대 30%만 반영한다.
- 2026년 하반기 보수적 시나리오 계수는 `1.053`이며 시나리오 전용 분석에만 사용한다.

SQL 생성 시 웹 검색 결과로 아래 값을 교체하지 않는다. 다음 월별 합성 계절 가중치를 평균 1로 정규화해 고정 사용한다.

```text
01=0.86, 02=0.90, 03=1.02, 04=1.07,
05=1.10, 06=1.05, 07=1.08, 08=1.12,
09=1.02, 10=1.10, 11=0.99, 12=1.06
```

SQL 헤더에는 적용한 기준값·가중치·가정·출처를 기록한다.

---

## 공통 SQL 산출 원칙

생성 SQL은 다음 구조를 가진다.

```text
1. 파일 헤더·버전·가정·레퍼런스 주석
2. DB·schema·필수 컬럼 사전검증
3. 안전한 session 설정
4. 기존 합성 데이터 정리
5. 집합 기반 합성 데이터 INSERT 또는 UPSERT
6. 인덱스·제약조건 생성 없음
7. 실효성 있는 검증 SELECT
8. actual/YTD/forecast 분리 요약 SELECT
```

필수 조건:

- SQL은 데이터 적재 전용이다.
- DDL은 별도 `호텔 데이터허브 DB DDL SQL`에서만 수행한다.
- `DROP`, `CASCADE`, 무제한 timeout을 사용하지 않는다.
- 동일 seed와 동일 자연키로 재실행하면 동일 결과가 생성되어야 한다.
- hash 입력의 date/time은 명시적 ISO 형식 문자열로 변환한다.
- 전역 row number를 pseudo-random key로 사용하지 않는다.
- 각 Source의 ID는 변하지 않는 자연키 조합으로 생성한다.
- 모든 Source 테이블에 `property_id`를 저장한다.
- 독립 event/date grain을 가진 fact table에는 `data_period_status`, `is_forecast`, `is_synthetic`, `source_updated_at`을 둔다.
- `pos_order_items` 같은 자식 detail은 부모 fact의 기간 상태를 상속하며 단독 기간 판정에 사용하지 않는다.
- 취소·환불·환입은 상태와 별도 금액 컬럼으로 표현한다.
- KPI 비율은 원천 테이블에 저장하지 않는다.
- 검증 실패를 숨기는 사후 `UPDATE` 보정문을 넣지 않는다.
- 실패 불가능한 회귀 가드는 품질 통과 근거와 분리해 표시한다.
- 실제 DB 실행을 하지 못하면 `STATIC_PASS`와 `DB_EXECUTION_NOT_RUN`을 분리해 기록한다.

### 공통 재실행 정책

- 전용 합성 DB에서만 실행한다.
- 대상 `property_id`의 합성 행만 자식→부모 순서로 삭제한 뒤 재생성한다.
- `is_synthetic=false` 행이 한 건이라도 존재하면 실행을 중단한다.
- `generation_audit` Source 테이블을 만들지 않는다.
- 실행 이력은 Application DB의 `connection.ingestion_runs`와 `governance.audit_events`가 담당한다.
- 검증 SELECT는 `seed`, `schema_version`, `scenario_version`, table별 row count, `max(source_updated_at)`, 안정 정렬 핵심 checksum을 출력한다.
- 실제 실행 후 위 증거를 Application audit에 기록하며, SQL 파일 생성만 한 경우 `DB_EXECUTION_NOT_RUN`으로 남긴다.

### 병렬구현 연계 증거

- SQL 헤더와 검증 SELECT에 `source_id`, engine, schema/scenario/fixture version, seed, `generated_at`, `synthetic=true`를 출력한다.
- 실제 실행 결과에는 table별 row count, source watermark, 안정 정렬 checksum, 실행 상태를 포함한다.
- DataHub URN과 Trino FQN은 SQL에서 임의 생성하지 않고 R2의 승인 `asset_binding`에 연결할 물리 database/schema/table 이름을 출력한다.
- query account의 INSERT·UPDATE·DELETE·DDL 차단 검증은 R5가 독립 실행할 수 있는 SELECT 중심 evidence와 예상 오류 범위를 제공한다.
- 실제 고객과 혼동 가능한 direct identifier fixture를 만들지 않는다. PII·secret 원문은 query result, log, trace, artifact, report, export에 남기지 않는다.


## 담당 영역

이 ChatGPT는 **`hotel_pms` PostgreSQL 데이터 적재만** 담당한다.

### R2 source binding·논리 entity mapping

```text
source_id=pms
engine=PostgreSQL
database=hotel_pms
ingestion_role=pms_ingest
query_role=pms_query
datahub_platform_instance=hotel_pms
trino_catalog=pms
```

- 논리 `guest`, `reservation`, `stay`는 각각 `pms_guests`, `pms_reservations`, `pms_stays`다.
- 논리 `room`은 `pms_room_inventory_daily.room_type_code`의 일별 공급 grain과 `pms_stays.room_unit_code`로 구현한다.
- 논리 `room_revenue` fact는 `pms_stays.room_revenue`이며 Trino View에서 완료 투숙을 숙박일별로 배부한다.
- 별도 `room`·`room_revenue` 테이블을 임의 추가하지 않는다. 요구가 바뀌면 schema version을 올린 R2 proposal로 처리한다.
- 대표 수용 질문은 PMS↔CRM 승인 JOIN, event-time mapping/grade, `business_unit_code='ROOMS'`, `as_of` 미만 기간을 함께 검증한다.

### 생성할 SQL 파일

```text
260728_01_pms_postgresql_2022_2026_v2.2.sql
```

### 적재 대상 테이블

```text
pms_guests
pms_room_inventory_daily
pms_reservations
pms_stays
```

`pms_generation_audit`는 생성하거나 사용하지 않는다.

### 생성 금지

```text
CREATE TABLE
ALTER TABLE
DROP TABLE
DROP ... CASCADE
pos_*
crm_*
facility_*
banquet_*
analytics_*
report_*
```

---

## PostgreSQL 안전 설정

SQL 시작부에 다음을 포함한다.

```sql
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '15s';
SET LOCAL idle_in_transaction_session_timeout = '5min';
```

모든 hash 입력의 날짜는 `to_char(date_value, 'YYYY-MM-DD')`로 변환한다.

---

## PMS 컬럼 계약

### `pms_guests`

```text
property_id           varchar(64) NOT NULL
guest_id              varchar(36) PK
guest_segment         varchar(24) NOT NULL
country_group         varchar(24) NOT NULL
crm_mapping_eligible  boolean NOT NULL
created_at            timestamptz NOT NULL
source_updated_at     timestamptz NOT NULL
is_synthetic          boolean NOT NULL
```

시간 규칙:

```text
created_at <= 최초 예약 booked_at
created_at <= source_updated_at
```

고객 번호가 낮을수록 대체로 오래된 고객이 되도록 생성한다.
예약과 무관한 무작위 고객 배정은 금지한다.

### `pms_room_inventory_daily`

```text
property_id           varchar(64) NOT NULL
inventory_id          bigint PK
business_date         date NOT NULL
room_type_code        varchar(32) NOT NULL
physical_rooms        integer NOT NULL
out_of_order_rooms    integer NOT NULL
house_use_rooms       integer NOT NULL
available_room_nights integer NOT NULL
data_period_status    varchar(32) NOT NULL
is_forecast           boolean NOT NULL
is_synthetic          boolean NOT NULL
source_updated_at     timestamptz NOT NULL
UNIQUE(property_id, business_date, room_type_code)
```

객실 공급은 2026-12-31까지 생성할 수 있다. 미래 날짜는 계획 공급이며 `is_forecast=true`다.

### `pms_reservations`

```text
property_id               varchar(64) NOT NULL
reservation_id            varchar(36) PK
guest_id                  varchar(36) NOT NULL FK
booked_at                 timestamptz NOT NULL
checkin_date              date NOT NULL
checkout_date             date NOT NULL
room_type_code            varchar(32) NOT NULL
rate_plan_code            varchar(32) NOT NULL
market_segment            varchar(24) NOT NULL
booking_channel           varchar(24) NOT NULL
reservation_status        varchar(20) NOT NULL
cancelled_at              timestamptz NULL
cancellation_reason_code  varchar(32) NULL
adult_count               integer NOT NULL
child_count               integer NOT NULL
quoted_room_rate          numeric(14,2) NOT NULL
gross_room_amount         numeric(14,2) NOT NULL
discount_amount           numeric(14,2) NOT NULL
commission_amount         numeric(14,2) NOT NULL
booked_amount             numeric(14,2) NOT NULL
refund_amount             numeric(14,2) NOT NULL
cancellation_fee          numeric(14,2) NOT NULL
data_period_status        varchar(32) NOT NULL
is_forecast               boolean NOT NULL
is_synthetic              boolean NOT NULL
source_updated_at         timestamptz NOT NULL
```

금액 정의:

```text
stay_nights        = checkout_date - checkin_date
gross_room_amount  = quoted_room_rate × stay_nights
booked_amount      = gross_room_amount - discount_amount
```

취소 예약:

```text
0 <= cancellation_fee <= booked_amount
refund_amount = booked_amount - cancellation_fee
commission_amount <= booked_amount
```

비취소 예약:

```text
refund_amount = 0
cancellation_fee = 0
```

예약의 `booked_amount`는 예약 당시 계약가이며 매출이 아니다.
객실 매출은 완료된 `pms_stays.room_revenue`에서만 집계한다.

### `pms_stays`

```text
property_id            varchar(64) NOT NULL
stay_id                varchar(36) PK
reservation_id         varchar(36) NOT NULL FK
guest_id               varchar(36) NOT NULL FK
room_unit_code         varchar(32) NOT NULL
actual_checkin_at      timestamptz NULL
actual_checkout_at     timestamptz NULL
room_type_code         varchar(32) NOT NULL
occupied_room_nights   integer NOT NULL
guest_count            integer NOT NULL
complimentary_flag     boolean NOT NULL
house_use_flag         boolean NOT NULL
room_revenue           numeric(14,2) NOT NULL
other_room_charges     numeric(14,2) NOT NULL
stay_status            varchar(20) NOT NULL
data_period_status     varchar(32) NOT NULL
is_forecast            boolean NOT NULL
is_synthetic           boolean NOT NULL
source_updated_at      timestamptz NOT NULL
```

`room_unit_code`는 다음 자연키로 안정적으로 만든다.

```text
property_id + room_type_code + unit_sequence
```

OOO 비율이 바뀌어도 기존 객실 코드가 밀리지 않아야 한다.

투숙·매출 규칙:

```text
reservation.guest_id = stay.guest_id
COMPLETED occupied_room_nights = actual_checkout_at::date - actual_checkin_at::date
COMPLETED 비무료·비내부사용 room_revenue = reservation.booked_amount
complimentary_flag=true 또는 house_use_flag=true이면 room_revenue=0
IN_HOUSE room_revenue=0, 최종 매출은 COMPLETED 전환 후 인식
동일 room_unit_code의 [actual_checkin_at, actual_checkout_at) 기간 중첩 금지
```

일별 KPI View에서는 완료 stay를 숙박일별로 펼치고
`daily_room_revenue = room_revenue / occupied_room_nights`로 배부한다.
나눗셈 잔액은 마지막 숙박일에 더해 일별 합계와 stay 합계가 정확히 일치해야 한다.

---

## 생성 규모

```text
pms_guests               100,000건
pms_room_inventory_daily 7,304건
pms_reservations         170,000~240,000건
pms_stays                120,000~180,000건
```

행 수 밴드는 품질보다 우선하지 않는다.

---

## PMS 생성 논리

### 1. 객실 공급

```text
STANDARD 150
DELUXE    90
SUITE     40
RESIDENCE 20
```

```text
available_room_nights
= physical_rooms - out_of_order_rooms - house_use_rooms
```

### 2. OCC 생성

고정 `LEAST(..., 0.82)`로 계절 신호를 잘라내지 않는다.

권장 방식:

```text
base_logit = ln(base_occ / (1 - base_occ))
adjusted_logit = base_logit + ln(season_factor × weekend_factor × demand_factor × room_type_factor)
target_occ = 1 / (1 + exp(-adjusted_logit))
```

최종 안전 상한 0.92는 오류 방지용으로만 사용하며 정상 구간에서 반복적으로 닿아서는 안 된다.

연도별 OCC 목표는 시장 anchor에 다음 property factor를 적용한다.

```text
2022 1.03
2023 1.04
2024 1.05
2025 2024 합성 OCC 대비 1.035
2026 YTD 2025 동일월 대비 감쇠 수요 반영
```

### 3. ADR 생성

합성 호텔의 연도별 목표 ADR을 먼저 고정하고 객실 유형·계절·채널 효과를 평균 보정한다.

```text
property_adr_premium = 1.08
2022 target ADR = 138874 × 1.08
2023 target ADR = 148547 × 1.08
2024 target ADR = 169171 × 1.08
2025 target ADR = 2024 target × 1.07
2026 target ADR = 2025 target × 1.05
```

`1.08`, `1.07`, `1.05`는 합성 시나리오 가정이며 공식 수치가 아니다.
SQL 헤더와 결과 요약에 명명 상수로 기록한다.
연도별 실제 생성 ADR은 목표 대비 ±5% 이내여야 한다.

### 4. LOS

점유 run length에서 LOS를 역산하지 않는다.

예약별 LOS를 먼저 생성하고 재고에 배치한다.

권장 전체 분포:

```text
1박 48%
2박 30%
3박 13%
4박 5%
5~7박 4%
```

세그먼트별 가중치를 다르게 하되 전체 ALOS는 1.8~2.2박 범위다.

### 5. 예약 상태와 시점

```text
booked_at < checkin_date < checkout_date
booked_at <= source_updated_at
guest.created_at <= booked_at
cancelled_at <= source_updated_at
cancelled_at < checkin_date
```

- 2026-07-28 이후 체크인 예약은 `booked_at <= generation_as_of_at`인 on-the-books만 생성한다.
- 아직 발생하지 않은 미래 예약을 가상 거래로 생성하지 않는다.
- `CHECKED_IN`은 `checkin_date <= simulation_as_of_date < checkout_date`인 일부 행에 생성한다.
- `CHECKED_OUT`만 `COMPLETED` stay를 가진다.
- `CHECKED_IN`은 `IN_HOUSE` stay를 가진다.
- `CANCELLED`, `NO_SHOW`, 미래 `BOOKED`는 stay를 만들지 않는다.
- `pms_stays`에는 forecast 실제 투숙·forecast 객실매출을 생성하지 않는다.
- 모든 `checkout_date`와 `actual_checkout_at`은 `data_end`를 초과하지 않는다.
- 모든 행의 `source_updated_at`을 전역 생성시각 하나로 고정하지 않는다.
- point-in-time 검증은 `source_updated_at <= evaluation_as_of` 조건을 별도로 적용한다.

### 6. 고객·세그먼트

- `guest_id`는 `GST-`와 8자리 sequence다.
- 1~80,000 중 실제 연결 대상으로 삼을 고객만 `crm_mapping_eligible=true`다.
- `market_segment`는 예약 단위로 생성한다.
- 고객 주 성향을 80% 반영하고 20%는 다른 세그먼트가 되게 한다.
- `market_segment = guest_segment` 완전 고정은 금지한다.

### 7. 취소·노쇼

취소·노쇼는 날짜 균등분포로 별도 생성하지 않는다.

다음 조건부 확률로 기존 예약에서 파생한다.

```text
lead_time
booking_channel
rate_plan_code
market_segment
stay_month
```

장기 리드타임·OTA·할인요금은 취소율이 다소 높되 완전 결정 관계는 금지한다.

### 8. 안정 ID

다음 자연키를 hash 입력으로 사용한다.

```text
reservation_id:
property_id + guest_id + checkin_date + room_type_code + booking_sequence_for_guest_day

stay_id:
property_id + reservation_id

가격·채널 noise:
property_id + reservation_id + 명명된 feature key
```

전역 `stay_no`나 row_number 변화가 전체 난수를 재추첨하게 만들면 안 된다.

---

## PostgreSQL 구현 요구

- PostgreSQL 15 이상
- `generate_series`, CTE, window function 사용
- `random()` 사용 금지
- 전체 적재를 하나의 transaction으로 묶음
- 대상 합성 행을 FK 자식→부모 순서로 삭제
- DDL·index 생성·ANALYZE는 수행하지 않음
- `pms_stays_actual`이 DDL로 존재하는지 확인
- SQL 실행만으로 4개 테이블의 합성 데이터가 적재되어야 함

---

## 필수 검증 쿼리

### 실효 품질 검증

```text
inventory 중복 0
available_room_nights 공식 불일치 0
판매 객실박 > 가용 객실박 0
checkout_date <= checkin_date 0
booked_at >= checkin_date 0
booked_at > source_updated_at 0
guest.created_at > reservation.booked_at 0
CANCELLED 예약의 stay 0
NO_SHOW 예약의 room_revenue > 0 건수 0
미래 BOOKED 예약의 stay 0
room_revenue < 0 건수 0
gross_room_amount 공식 불일치 0
booked_amount 공식 불일치 0
CANCELLED의 refund_amount+cancellation_fee 불일치 0
비취소 예약의 refund_amount 또는 cancellation_fee > 0 건수 0
2026-07-29 이후 is_forecast=false 건수 0
pms_stays에서 is_forecast=true 건수 0
checkout_date > data_end 건수 0
CHECKED_IN 상태 1건 이상
stay와 reservation guest_id 불일치 0
COMPLETED occupied_room_nights와 실제 투숙기간 불일치 0
동일 room_unit_code 실제 투숙기간 중첩 0
complimentary/house-use인데 room_revenue > 0 건수 0
COMPLETED 비무료·비내부사용 stay와 booked_amount 불일치 0
숙박일별 배부 매출 합계와 stay room_revenue 불일치 0
market_segment와 guest_segment가 100% 동일한지 여부 false
5박 이상 예약 1% 이상
실제 개인정보 패턴 0
```

### KPI 검증

연도·기간상태·`is_forecast`별로 별도 출력한다.

```text
OCC
ADR
RevPAR
ALOS
취소율
노쇼율
CHECKED_IN 수
on-the-books 미래 예약 수
```

2026년을 실적+전망 한 행으로 합치지 않는다.

### 회귀 가드

다음 검증은 실패 불가능할 수 있으므로 `REGRESSION_GUARD`라고 주석 처리하고 품질 통과 건수에서 제외한다.

```text
CANCELLED 예약의 stay 0
NO_SHOW 예약의 room_revenue > 0
개인정보 패턴 0
```

---

## 완료 행동

지금 즉시 지정 SQL 파일을 생성한다.

최종 응답:

```text
[SQL 파일 링크]

- 적재 테이블: 4개
- 생성 기간:
- actual/YTD/forecast 분리:
- 정적 검증:
- 실제 DB 실행:
- row count·watermark·checksum:
```
