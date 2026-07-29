# 웹 ChatGPT 05
## 연회 예약·행사·매출 SQL 데이터 적재 지시문 v2.2

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

이 ChatGPT는 **`hotel_banquet` PostgreSQL 데이터 적재만** 담당한다.

### R2 source binding·논리 entity mapping

```text
source_id=banquet
engine=PostgreSQL
database=hotel_banquet
ingestion_role=banquet_ingest
query_role=banquet_query
datahub_platform_instance=hotel_banquet
trino_catalog=banquet
```

- 논리 `banquet_booking`과 `banquet_revenue`는 각각 `banquet_bookings`, `banquet_revenue`다.
- 논리 `banquet_product`는 현재 `product_code`·`product_category`를 두 fact에 보존하는 방식으로 구현한다.
- 상품 master가 승인되기 전에는 별도 `banquet_product` 테이블을 임의 추가하지 않는다.
- `banquet_customer_id`는 event time에 유효한 CRM identity mapping만 사용한다.
- 확정·취소·매출 인식·환입과 객실 블록은 `as_of` 이전에 알려진 상태만 수용 fixture와 ML Feature에 제공한다.

### 생성할 SQL 파일

```text
260728_05_banquet_postgresql_2022_2026_v2.2.sql
```

### 적재 대상 테이블

```text
banquet_bookings
banquet_revenue
```

`banquet_generation_audit`는 생성하거나 사용하지 않는다.

---

## PostgreSQL 안전 설정

```sql
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '15s';
SET LOCAL idle_in_transaction_session_timeout = '5min';
```

---

## Banquet 컬럼 계약

### `banquet_bookings`

```text
property_id                 varchar(64) NOT NULL
banquet_event_id            varchar(36) PK
customer_id                 varchar(36) NOT NULL
inquiry_at                  timestamptz NOT NULL
quoted_at                   timestamptz NULL
confirmed_at                timestamptz NULL
cancelled_at                timestamptz NULL
event_date                  date NOT NULL
product_code                varchar(32) NOT NULL
product_category            varchar(32) NOT NULL
expected_guests             integer NOT NULL
actual_attendees            integer NULL
lead_source                 varchar(24) NOT NULL
sales_owner_team            varchar(32) NOT NULL
booking_status              varchar(20) NOT NULL
contracted_amount           numeric(14,2) NOT NULL
cancellation_fee            numeric(14,2) NOT NULL
reserved_room_block_count   integer NOT NULL
expected_room_nights        integer NOT NULL
group_checkin_date          date NULL
group_checkout_date         date NULL
released_room_count         integer NOT NULL
pickup_room_count           integer NOT NULL
data_period_status          varchar(32) NOT NULL
is_forecast                 boolean NOT NULL
is_synthetic                boolean NOT NULL
source_updated_at           timestamptz NOT NULL
```

### `banquet_revenue`

```text
property_id          varchar(64) NOT NULL
revenue_id           varchar(36) PK
banquet_event_id     varchar(36) NOT NULL FK
recognized_date      date NOT NULL
product_code         varchar(32) NOT NULL
product_category     varchar(32) NOT NULL
revenue_amount       numeric(14,2) NOT NULL
reversal_amount      numeric(14,2) NOT NULL
cost_amount          numeric(14,2) NOT NULL
revenue_status       varchar(16) NOT NULL
data_period_status   varchar(32) NOT NULL
is_forecast          boolean NOT NULL
is_synthetic         boolean NOT NULL
source_updated_at    timestamptz NOT NULL
```

금액 정의:

```text
RECOGNIZED: revenue_amount > 0, reversal_amount = 0
REVERSED: revenue_amount = 0, reversal_amount > 0
EXPECTED: revenue_amount > 0, reversal_amount = 0, 실제 매출 집계 제외
net_recognized_revenue = recognized revenue - reversal_amount
```

취소 예약은 `cancellation_fee`를 별도 저장하며 계약금액을 실제 매출로 집계하지 않는다.

```text
0 <= cancellation_fee <= contracted_amount
COMPLETED 행사만 RECOGNIZED 허용
REVERSED reversal_amount는 이전 RECOGNIZED 누적액을 초과하지 않음
```

---

## 생성 규모

```text
banquet_bookings 4,000~8,000건
banquet_revenue  8,000~18,000건
```

---

## Banquet 생성 논리

### 시간 논리

```text
inquiry_at <= quoted_at <= confirmed_at
inquiry_at <= source_updated_at
quoted_at <= source_updated_at
confirmed_at <= source_updated_at
cancelled_at <= source_updated_at
```

- 미래 event_date는 현재 기준일 이전에 문의·견적·확정된 on-the-books 행사만 허용한다.
- 미래 COMPLETED 행사, 미래 actual_attendees, 미래 RECOGNIZED 매출은 금지한다.
- 미래 확정 행사는 `EXPECTED` revenue만 가능하고 `is_forecast=true`다.
- 과거 완료 행사는 `RECOGNIZED` 가능하다.
- 취소 환입은 `REVERSED`와 `reversal_amount`로 표현한다.
- `source_updated_at`을 모든 행에 전역 생성시각 하나로 고정하지 않는다.
- point-in-time 검증은 `source_updated_at <= evaluation_as_of` 조건을 적용한다.

### 객실 블록

```text
0 <= released_room_count <= reserved_room_block_count
0 <= pickup_room_count <= reserved_room_block_count - released_room_count
expected_room_nights >= pickup_room_count
group_checkin_date < group_checkout_date
```

객실 블록은 연회와 객실수요 ML의 보조 Feature로 사용 가능하도록 생성한다.

### 안정 ID

```text
banquet_event_id:
property_id + event_date + product_category + event_sequence_for_day_category

revenue_id:
property_id + banquet_event_id + product_code + revenue_sequence
```

전역 row number를 hash key로 사용하지 않는다.

---

## PostgreSQL 구현 요구

- PostgreSQL 15 이상
- ISO DateStyle
- hash 입력 날짜 명시 변환
- `random()` 금지
- 자식→부모 순서 합성 행 DELETE
- DDL·index·ANALYZE·DROP 금지
- 하나의 transaction

---

## 필수 검증 쿼리

```text
inquiry_at > source_updated_at 0
quoted_at > source_updated_at 0
confirmed_at > source_updated_at 0
cancelled_at > source_updated_at 0
미래 event의 COMPLETED 0
미래 event의 actual_attendees 존재 0
미래 event의 RECOGNIZED revenue 0
미완료 행사 RECOGNIZED 매출 0
REVERSED인데 revenue_amount > 0 건수 0
REVERSED인데 reversal_amount <= 0 건수 0
취소 행사 cancellation_fee 범위 위반 0
미완료 행사 cancellation_fee 외 실제 매출 집계 0
누적 reversal_amount > 이전 RECOGNIZED 누적액 건수 0
revenue/cost/reversal 음수 0
orphan revenue 0
부모·자식 property_id 불일치 0
객실 블록 수량 제약 위반 0
group_checkout_date <= group_checkin_date 0
실제 인식매출과 EXPECTED 매출 분리 출력
2026-07-29 이후 known future row의 is_forecast=false 0
실제 개인정보 패턴 0
table별 row count·watermark·checksum 출력
```

요약 SELECT는 actual/YTD/forecast와 RECOGNIZED/EXPECTED/REVERSED를 별도 행으로 출력한다.

---

## 완료 행동

PostgreSQL SQL 파일 하나를 생성하고 링크와 검증 요약만 제공한다.
