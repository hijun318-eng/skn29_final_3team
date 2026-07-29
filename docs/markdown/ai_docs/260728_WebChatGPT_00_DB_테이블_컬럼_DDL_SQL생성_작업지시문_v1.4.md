# 웹 ChatGPT DB·테이블·컬럼 DDL SQL 생성 작업지시문 v1.4

작성일: 2026-07-28
설계 기준: `260728_호텔데이터허브_데이터베이스_설계서_통합본_v4.6.md`
작업 유형: DB·schema·table·column·constraint·index·view·최소권한 role 생성
결과 형식: SQL 파일만 포함한 ZIP 1개

## 명칭 적용 원칙

- 폐기된 프로젝트 고유명 접두어를 사용하지 않는다.
- 문서 표기명은 `호텔 데이터허브`로 통일한다.
- DB와 SQL 파일은 `hotel_*` 기능 중심 이름을 사용한다.
- 특정 호텔·기업 브랜드명을 DB·schema·table·column 식별자에 넣지 않는다.
- 출력 SQL·주석·ZIP 내부에서 폐기된 고유명이 발견되면 검증 실패로 처리한다.

## 1. 실행 지시

이 문서는 설명 자료가 아니라 웹 ChatGPT가 직접 수행하는 작업지시문이다.

이 문서와 통합 설계서가 업로드되면 다음을 즉시 수행한다.

1. 사용자에게 프롬프트를 다시 복사하라고 요구하지 않는다.
2. 통합 설계서를 처음부터 끝까지 읽는다.
3. 설계서에 따라 6개 DB, 5 source의 ingestion/query role 경계와 Trino 분석 View의 DDL SQL을 생성한다.
4. 채팅 본문에 전체 SQL을 붙이지 않는다.
5. Python 또는 파일 생성 도구로 `/mnt/data`에 SQL 파일을 만든다.
6. SQL 파일만 ZIP으로 묶는다.
7. 최종 응답에는 ZIP 링크와 검증 요약만 제공한다.
8. 질문·확인 요청 없이 작업을 완료한다.

통합 설계서가 누락되면 임의 schema를 만들지 않고
`260728_호텔데이터허브_데이터베이스_설계서_통합본_v4.6.md 필요`라고 중단한다.

---

## 2. 산출물

정확히 다음 파일을 생성한다.

```text
00_hotel_datahub_app_postgresql.sql
00b_hotel_datahub_app_p2_optional_postgresql.sql
01_hotel_pms_postgresql.sql
02_hotel_pos_mysql.sql
03_hotel_crm_sqlserver.sql
04_hotel_facility_clickhouse.sql
05_hotel_banquet_postgresql.sql
06_trino_analytics_views.sql
```

위 SQL 8개를 다음 ZIP 하나로 묶는다.

```text
260728_호텔데이터허브_DB_DDL_SQL_v4.6.zip
```

ZIP 안에 다음 형식을 넣지 않는다.

```text
JSON
JSONL
CSV
Parquet
XLSX
HTML
Python script
README
```

SQL 파일의 설명은 SQL 주석으로 작성한다.

---

## 3. 생성 범위

### Application PostgreSQL

Database:

```text
hotel_datahub_app
```

Schema:

```text
connection
context
chat
query
artifact
report
governance
model
tooling
rag
ml
reference
analytics
```

기본 P0/P1 물리 테이블:

```text
19개
```

- 플랫폼 Core·실험 16개
- reference 3개

P2 선택 테이블 5개는 `00b_hotel_datahub_app_p2_optional_postgresql.sql`에만 둔다.
기본 P0/P1 DDL은 P2 extension이나 P2 테이블 없이 실행 가능해야 한다.

기본 필수 extension:

```text
pgcrypto
```

P2 선택 extension:

```text
vector
```

`vector`가 없으면 P2 선택 파일만 `P2_PREREQUISITE_MISSING`으로 중단한다.
기본 P0/P1 DDL은 실패시키지 않으며 다른 타입으로 몰래 대체하지 않는다.

### Source DB

```text
hotel_pms       PostgreSQL  4 tables
hotel_pos       MySQL       4 tables
hotel_crm       SQL Server  4 tables
hotel_facility  ClickHouse  4 tables
hotel_banquet   PostgreSQL  2 tables
```

총 source table:

```text
18개
```

각 source에는 실제 credential이 아닌 다음 권한 role을 분리해 생성한다.

| source | ingestion role | query role |
|---|---|---|
| PMS | `pms_ingest` | `pms_query` |
| POS | `pos_ingest` | `pos_query` |
| CRM | `crm_ingest` | `crm_query` |
| Facility | `facility_ingest` | `facility_query` |
| Banquet | `banquet_ingest` | `banquet_query` |

- 실제 login, password, token, connection URL은 생성하거나 출력하지 않는다.
- ingestion role은 합성 적재에 필요한 최소 DML만, query role은 승인 schema/view의 `SELECT`만 허용한다.
- PostgreSQL은 `NOLOGIN` group role, MySQL은 `CREATE ROLE`, SQL Server는 database role, ClickHouse는 role을 사용한다. 실제 사용자를 생성하거나 role에 사용자를 연결하지 않는다.
- 각 SQL 끝에 query role의 INSERT·UPDATE·DELETE·DDL 차단을 확인하는 negative test를 제공한다.

### Trino

5개 source catalog와 app catalog를 사용해 분석 View 8개를 생성한다.

```text
app
pms
pos
crm
facility
banquet
```

5개 업무 source catalog는 `pms`, `pos`, `crm`, `facility`, `banquet`다.
`app`은 내부 reference·analytics 저장용 catalog이며 업무 source 5개에 포함하지 않는다.

DataHub recipe와 runtime credential은 이 ZIP의 산출물이 아니다. 다만 각 source SQL 헤더와 구조 검증 결과에 다음 binding 값을 주석으로 고정한다.

```text
source_id
engine
database/schema
ingestion_role
query_role
datahub_platform_instance
trino_catalog
schema_version=schema-v4.6-websql
```

R2는 이 값을 사용해 5개 recipe와 DataHub URN↔Trino FQN `asset_binding`을 만들고, R5는 별도 secret과 `access-policy.yaml`을 연결한다.

---

## 4. SQL 공통 구조

각 SQL 파일은 다음 순서로 작성한다.

```text
1. 버전·엔진·실행 도구·선행조건 주석
2. Database 생성
3. Database 전환
4. Schema 생성
5. Table 생성
6. PK·FK·UNIQUE·CHECK
7. Index
8. Table·Column comment
9. 구조 검증 query
10. 권한·read-only negative query
11. 생성 객체 요약 query
```

대량 합성 운영 데이터는 삽입하지 않는다.

DDL은 빈 DB 또는 동일 v4.6 계약의 빈 schema 초기화를 기준으로 한다.
동명 객체가 존재하지만 컬럼·타입·제약이 다르면 `IF NOT EXISTS`로 숨기지 않고
`SCHEMA_CONTRACT_MISMATCH`를 발생시켜 중단한다.
v4.4 운영 DB를 v4.6로 바꾸는 migration은 이 ZIP의 범위가 아니다.

허용:

```text
DDL
COMMENT
정적 CHECK
구조 검증 SELECT
필요한 최소 extension
```

금지:

```text
수십만 행의 INSERT
실제 개인정보
password/token/key
DataHub 내부 schema 복제
교차 source physical FK
실제 login/password/token/connection URL
성공하지 않은 작업을 성공으로 출력
```

---

## 5. 엔진별 요구사항

### PostgreSQL 파일

- PostgreSQL 15 이상
- `psql` 실행 가능 형식
- `CREATE DATABASE`와 `\connect` 경계를 명확히 작성
- `CREATE SCHEMA IF NOT EXISTS`
- `CREATE TABLE IF NOT EXISTS`
- UUID 기본값은 `gen_random_uuid()`
- 금액은 `numeric(14,2)`
- 시각은 `timestamptz`
- FK index 생성
- CHECK와 UNIQUE 구현
- `COMMENT ON TABLE`, `COMMENT ON COLUMN`
- P2 선택 파일의 `rag_chunks.embedding`은 `vector(1024)`

### MySQL 파일

- MySQL 8.0 이상
- `CREATE DATABASE IF NOT EXISTS`
- `utf8mb4`
- InnoDB
- CHECK constraint 사용
- datetime은 `datetime(3)`
- FK·index·unique 구현
- `COMMENT` 포함

### SQL Server 파일

- SQL Server 2022
- `IF DB_ID(...) IS NULL CREATE DATABASE`
- `GO` batch 구분
- `dbo` schema 사용
- `datetime2(3)`
- CHECK·FK·filtered unique index 사용
- ACTIVE customer map의 기간 중복 방지 구조와 검증 query 제공
- `crm_member_grade_history`의 `[valid_from, valid_to)`와 회원별 기간 중복 방지 구조·검증 query 제공
- PMS/POS/Facility/Banquet local ID별 활성 mapping 중복 검증 query 제공

### ClickHouse 파일

- ClickHouse 24 이상
- `CREATE DATABASE IF NOT EXISTS`
- MergeTree 계열
- 설계서의 `ORDER BY` 준수
- 강제 FK가 없으므로 논리 관계 검증 SELECT 제공
- `DateTime64(3,'UTC')`
- LowCardinality·Nullable 조합은 설계서와 일치

### Trino 파일

- Trino SQL
- setup용 관리자 세션에서만 View DDL 실행
- runtime 일반 사용자 계정은 read-only
- cross-catalog JOIN은 설계서의 logical relationship만 사용
- `NULLIF`로 분모 0 처리
- `data_period_status`와 `is_forecast`를 결과에 보존
- 2026년 YTD와 forecast를 무표시로 합치지 않음

---


## Source 스키마 v4.6 필수 변경

다음 변경을 DDL SQL에 반드시 반영한다.

### 공통

- 18개 Source 테이블 모두 `property_id` 추가
- Source별 `generation_audit` 테이블 생성 금지
- Source 데이터 SQL은 DDL을 수행하지 않으므로 모든 컬럼·CHECK·FK·UNIQUE를 여기서 생성
- PostgreSQL DDL에서 `DROP ... CASCADE` 사용 금지
- 실제 질의용 View는 `is_forecast=false`를 기본 조건으로 사용

### PMS

```text
pms_guests.crm_mapping_eligible
pms_reservations.gross_room_amount
pms_reservations.refund_amount
pms_reservations.cancellation_fee
pms_stays.room_unit_code
```

필수 CHECK:

```text
gross_room_amount = quoted_room_rate * (checkout_date - checkin_date)
booked_amount = gross_room_amount - discount_amount
refund_amount >= 0
cancellation_fee >= 0
CANCELLED이면 refund_amount + cancellation_fee = booked_amount
비취소이면 refund_amount = 0 AND cancellation_fee = 0
booked_at <= source_updated_at
```

`pms_stays_actual` View를 생성한다.

```sql
SELECT *
FROM pms_stays
WHERE is_forecast = false
  AND data_period_status <> 'FORECAST_SCENARIO';
```

추가 필수 CHECK·검증:

```text
pms_stays.guest_id = pms_reservations.guest_id
COMPLETED의 occupied_room_nights = actual_checkout_at::date - actual_checkin_at::date
동일 room_unit_code의 실제 투숙기간 중첩 0
complimentary_flag 또는 house_use_flag이면 room_revenue = 0
```

### CRM

`crm_member_grade_history` 9개 컬럼을 통합 설계서와 동일하게 생성한다.

필수 제약·검증:

```text
valid_from < valid_to 또는 valid_to IS NULL
회원별 등급 유효기간 중첩 0
현재 유효 등급은 회원별 최대 1건
crm_members.membership_grade = evaluation_as_of 시점의 유효 grade_code
customer map의 valid_from < valid_to 또는 valid_to IS NULL
각 local ID가 동일 시점에 여러 member_no로 매핑되는 건수 0
```

### Banquet

```text
banquet_bookings.cancellation_fee
banquet_bookings.reserved_room_block_count
banquet_bookings.expected_room_nights
banquet_bookings.group_checkin_date
banquet_bookings.group_checkout_date
banquet_bookings.released_room_count
banquet_bookings.pickup_room_count
banquet_revenue.reversal_amount
```

`REVERSED`는 `revenue_amount=0`, `reversal_amount>0`로 제약한다.


## 6. 필수 제약조건

### 기간

```text
2022-01-01~2024-12-31 = REFERENCE_CALIBRATED
2025-01-01~2025-12-31 = SYNTHETIC_ACTUAL_LIKE
2026-01-01~2026-07-28 = YTD_SYNTHETIC
2026-07-29~2026-12-31 = FORECAST_SCENARIO
```

기간성 fact에는 다음 컬럼이 존재해야 한다.

```text
data_period_status
is_forecast
is_synthetic
source_updated_at
```

### source 내부

- 예약·투숙·주문·포인트·연회 관계는 물리 FK
- ClickHouse 시설 관계는 논리 검증
- 음수 금액·수량 방지 CHECK
- 날짜 역전 방지 CHECK
- 상태 코드 CHECK
- inventory·service period 중복 방지 UNIQUE

### source 간

다음 관계에 물리 FK를 생성하지 않는다.

```text
CRM ↔ PMS
CRM ↔ POS
CRM ↔ Facility
CRM ↔ Banquet
```

관계는 `crm_customer_map`과 Trino JOIN_POLICY를 통해서만 사용한다.

---

## 7. Trino 분석 View

다음 View를 생성한다.

```text
analytics.hotel_daily_metrics
analytics.hotel_monthly_metrics
analytics.hotel_yearly_metrics
analytics.fnb_daypart_metrics
analytics.facility_daily_metrics
analytics.banquet_monthly_metrics
analytics.workforce_monthly_metrics
analytics.resource_monthly_metrics
```

공식:

```text
OCC = rooms_sold / available_room_nights
ADR = room_revenue / rooms_sold
RevPAR = room_revenue / available_room_nights
TRevPAR = total_operating_revenue / available_room_nights
RevPOR = total_operating_revenue / rooms_sold
RevPASH = fnb_net_revenue / seat_hours_available
HPOR = worked_hours / rooms_sold
Labor CPOR = labor_cost / rooms_sold
```

분모가 0이면 `NULL`을 반환한다.

각 View는 통합 설계서 v4.6의 grain·사전 집계·숙박일별 매출 배부·`business_unit_code`·point-in-time 계약을 그대로 구현한다.
원시 fact끼리 날짜만으로 직접 JOIN하지 않는다.
`analytics.hotel_monthly_metrics`는 source별 월 집계를 `UNION ALL`한 뒤 최종 집계한다.
View 결과에는 source별 watermark와 `data_period_status`, `is_forecast`를 보존한다.

---

## 8. 자체 검증

생성 후 SQL 텍스트를 정적으로 검증한다.

필수 검증:

```text
SQL 파일 8개 존재
ZIP 내부 비SQL 파일 0
Application 기본 table 19개
Application P2 선택 table 5개
Application 전체 table 24개
Source table 18개
Trino View 8개
PK 누락 0
명세상 FK 누락 0
source 간 물리 FK 0
상태 CHECK 누락 0
금액 음수 방지 누락 0
2026 forecast 표현 컬럼 누락 0
CRM 등급 이력 기간 중첩 검증 누락 0
CRM local ID 활성 중복 검증 누락 0
Trino View grain·사전 집계 조건 누락 0
P0 DDL의 vector extension 의존 0
password/token/private key 원문 0
source별 ingestion/query role 10개 구분
query role write 성공 0
source_id·platform instance·Trino catalog binding 주석 누락 0
논리 entity→물리 table mapping 불일치 0
폐기된 프로젝트 고유명 문자열 0
```

가능한 경우 parser 또는 정규식으로 객체 수를 검증한다.

DB 서버가 연결되지 않은 환경에서는:

```text
SQL 생성·정적 검증 = PASS/PARTIAL/FAILED
실제 DB 실행 = NOT_RUN
```

실행하지 않은 DB를 성공으로 기록하지 않는다.

---

## 9. 최종 응답

```text
[260728_호텔데이터허브_DB_DDL_SQL_v4.6.zip 다운로드 링크]

- SQL 파일: 8개
- Application 테이블: 24개
- Source 테이블: 18개
- Trino View: 8개
- Source 권한 role: 10개
- 정적 검증:
- 실제 DB 실행: NOT_RUN 또는 실제 결과
```

지금 즉시 작업을 시작한다.


## 10. 객체 수 기준

| 구분 | 개수 | 기준 |
| --- | --- | --- |
| Application 물리 테이블 | 24 | Core/실험/P2/reference |
| Source 물리 테이블 | 18 | 5개 업무 source |
| 전체 물리 테이블 | 42 | Application+Source |
| Trino 분석 View | 8 | cross-source read model |
| 전체 명세 컬럼 | 571 | 통합 설계서 기준 |
