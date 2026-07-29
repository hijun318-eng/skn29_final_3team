# 웹 ChatGPT 04
## 시설 운영·인력·에너지·자원 SQL 데이터 적재 지시문 v2.2

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

이 ChatGPT는 **`hotel_facility` ClickHouse 데이터 적재만** 담당한다.

### R2 source binding·논리 entity mapping

```text
source_id=facility
engine=ClickHouse
database=hotel_facility
ingestion_role=facility_ingest
query_role=facility_query
datahub_platform_instance=hotel_facility
trino_catalog=facility
```

- 논리 `facility`는 `facility_master`다.
- 논리 `usage`, `inspection`, `incident`는 `facility_events.event_type`으로 구분한다.
- 인력과 자원 일별 fact는 각각 `hotel_staffing_daily`, `facility_resource_daily`다.
- `facility_user_ref`는 CRM identity mapping 유효기간을 통과할 때만 교차 source 분석에 사용한다.
- ClickHouse 물리 FK가 없으므로 orphan·event type·시간·범위 실패 fixture와 검증 SELECT를 반드시 제공한다.

### 생성할 SQL 파일

```text
260728_04_facility_clickhouse_2022_2026_v2.2.sql
```

### 적재 대상 테이블

```text
facility_master
facility_events
hotel_staffing_daily
facility_resource_daily
```

`facility_generation_audit`는 생성하거나 사용하지 않는다.

---

## ClickHouse 안전 설정

```sql
SET session_timezone = 'UTC';
SET max_execution_time = 1800;
```

실행 전 대상 `property_id` 범위에 `is_synthetic=0` 행이 있는지 `throwIf`로 검사한다.
기본 재실행은 자식 성격 테이블부터 `ALTER TABLE ... DELETE WHERE property_id='SYNTHETIC_HOTEL_001'`를 수행하고 `mutations_sync=2`로 완료를 기다린다.
`TRUNCATE`와 `DROP TABLE`은 사용하지 않는다.

---

## Facility 컬럼 계약

모든 테이블에 `property_id String`을 추가한다.

### `facility_master`

```text
ORDER BY (property_id, facility_id)
```

### `facility_events`

- 관측 `USAGE`, `INCIDENT`, 완료된 `INSPECTION`은 `event_at <= generation_as_of_at`
- 미래 이벤트는 `INSPECTION + SCHEDULED`만 허용
- 미래 `USAGE`, `INCIDENT` 생성 금지
- `source_updated_at >= least(event_at, generation_as_of_at)`의 의미를 유지
- `source_updated_at`을 모든 행에 전역 생성시각 하나로 고정하지 않는다.
- 고객 ref가 있는 행은 `USAGE`만 허용

### `hotel_staffing_daily`

- `business_date <= simulation_as_of_date`
- 미래의 실제 `worked_hours`, `labor_cost`, 채용·퇴사를 생성하지 않는다.
- 계획 인력 forecast는 별도 Scenario에서 생성한다.
- 최대 grain은 `property_id + business_date + department` 한 건이다.

### `facility_resource_daily`

- `business_date <= simulation_as_of_date`
- 미래의 실제 energy·water·waste·cost를 생성하지 않는다.
- 최대 grain은 `property_id + business_date + resource_scope` 한 건이다.

---

## 생성 규모

```text
facility_master          20건
facility_events          650,000~1,400,000건
hotel_staffing_daily     11,000~11,690건
facility_resource_daily  6,500~10,000건
```

`hotel_staffing_daily`는 1,670일 × 7개 부서의 최대 11,690건이라는 grain 상한을 넘지 않는다.

---

## Facility 생성 논리

### 이벤트 상태

```text
USAGE:
event_at <= as_of, COMPLETED/FAILED

INSPECTION:
과거 COMPLETED/FAILED
미래 SCHEDULED 가능

INCIDENT:
event_at <= as_of, OPEN/CLOSED
```

미래 `OPEN INCIDENT`, 미래 실제 이용 매출, 미래 downtime을 만들지 않는다.

### 인력

- 실제 `worked_hours`와 `labor_cost`는 관측일까지만 생성
- vacancies <= approved_positions
- 부서 수요와 약한 상관만 허용
- 완전 선형 관계 금지

### 자원

- 실제 사용량은 관측일까지만 생성
- 계절·시설 가동·날씨 시나리오와 약한 상관
- 음수 금지
- 미래 forecast consumption은 ML Scenario에서 생성

### 안정 ID

```text
event_id:
property_id + facility_id + event_at + event_type + event_sequence_at_timestamp

staffing_id:
property_id + business_date + department

resource_id:
property_id + business_date + resource_scope
```

전역 번호가 변해 다른 날짜의 ID가 이동하면 안 된다.

---

## ClickHouse 구현 요구

- ClickHouse 24 이상
- `numbers()`·`arrayJoin`
- `cityHash64` 입력은 ISO 날짜·명명된 자연키
- `rand()` 사용 금지
- `INSERT SELECT`
- DDL·DROP 금지
- 실제 DB 실행이 없으면 정적 검증과 미실행을 구분
- property 범위 DELETE mutation 완료를 확인한 뒤 INSERT

---

## 필수 검증 쿼리

```text
facility orphan 0
부모·자식 property_id 불일치 0
duration/amount/downtime 음수 0
미래 USAGE 0
미래 INCIDENT 0
미래 이벤트 중 INSPECTION+SCHEDULED 외 0
event_at <= as_of인데 source_updated_at < event_at 0
staffing business_date > as_of 0
resource business_date > as_of 0
staffing grain 중복 0
resource grain 중복 0
downtime_hours > scheduled_hours 0
vacancies > approved_positions 0
worked_hours·labor_cost 음수 0
energy·water·waste·cost 음수 0
BACK_OF_HOUSE 고객 이용 0
실제 개인정보 패턴 0
대상 property 외 row count 변경 0
DELETE mutation 미완료 0
table별 row count·watermark·checksum 출력
```

forecast Source actual 행은 0건이어야 한다.

---

## 완료 행동

ClickHouse SQL 파일 하나를 생성하고 링크와 검증 요약만 제공한다.
