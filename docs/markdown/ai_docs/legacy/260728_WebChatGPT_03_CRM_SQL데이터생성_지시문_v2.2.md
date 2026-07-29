# 웹 ChatGPT 03
## CRM·멤버십·교차 Source 고객키 SQL 데이터 적재 지시문 v2.2

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

이 ChatGPT는 **`hotel_crm` SQL Server 데이터 적재만** 담당한다.

### R2 source binding·논리 entity mapping

```text
source_id=crm
engine=SQL Server
database=hotel_crm
ingestion_role=crm_ingest
query_role=crm_query
datahub_platform_instance=hotel_crm
trino_catalog=crm
```

- 논리 `member`, `member_grade_history`, `point_transaction`은 각각 `crm_members`, `crm_member_grade_history`, `crm_point_transactions`다.
- R2 매뉴얼의 논리 `customer_identity_map`은 물리 테이블 `crm_customer_map`으로 구현한다.
- DataHub term alias와 R3 `asset_binding`에 두 이름을 함께 기록하고, 별도 중복 identity table을 만들지 않는다.
- local ID별 유효기간 중첩, 한 local ID의 복수 활성 회원, 존재하지 않는 member, 의도한 미매핑을 각각 positive/negative fixture로 검증한다.
- 현재 `crm_members.membership_grade` snapshot은 과거 거래·ML 시점 등급에 사용하지 않는다.

### 생성할 SQL 파일

```text
260728_03_crm_sqlserver_2022_2026_v2.2.sql
```

### 적재 대상 테이블

```text
crm_members
crm_member_grade_history
crm_point_transactions
crm_customer_map
```

`crm_generation_audit`는 생성하거나 사용하지 않는다.

---

## SQL Server 안전 설정

```sql
SET XACT_ABORT ON;
SET NOCOUNT ON;
SET DATEFORMAT ymd;
SET LANGUAGE us_english;
SET LOCK_TIMEOUT 30000;
```

날짜 hash 입력은 ISO 8601 style 126으로 명시 변환한다.

---

## CRM 컬럼 계약

모든 테이블에 `property_id varchar(64) NOT NULL`을 추가한다.

### `crm_members`

```text
UNIQUE(property_id, member_no)
joined_at <= source_updated_at
```

미래 가입자를 forecast 회원으로 생성하지 않는다.

`membership_grade`는 `evaluation_as_of` 시점의 현재 표시용 snapshot이다.
과거 거래의 등급 판정에는 사용하지 않는다.

### `crm_member_grade_history`

```text
property_id        varchar(64) NOT NULL
grade_history_id   varchar(36) PK
member_no          varchar(36) NOT NULL FK
grade_code         varchar(16) NOT NULL
valid_from         datetime2(3) NOT NULL
valid_to           datetime2(3) NULL
change_reason_code varchar(24) NOT NULL
is_synthetic       bit NOT NULL
source_updated_at  datetime2(3) NOT NULL
```

규칙:

```text
valid_from < valid_to 또는 valid_to IS NULL
유효기간은 [valid_from, valid_to)
회원별 기간 중첩 금지
현재 유효 등급은 회원별 최대 1건
valid_from >= joined_at
source_updated_at >= valid_from
```

### `crm_point_transactions`

```text
event_at <= source_updated_at
event_at <= generation_as_of_at
```

2026-07-29 이후 포인트 거래를 생성하지 않는다.

### `crm_customer_map`

```text
valid_from <= source_updated_at
valid_to IS NULL OR valid_to <= source_updated_at
```

ACTIVE 매핑은 동일 `property_id + member_no`에 한 시점 한 건만 허용한다.
각 PMS/POS/Facility/Banquet local ID도 동일 시점에 여러 회원으로 매핑될 수 없다.
유효기간은 `[valid_from, valid_to)`이며 `valid_from = valid_to`를 허용하지 않는다.

---

## 생성 규모

```text
crm_members             80,000건
crm_member_grade_history 100,000~180,000건
crm_point_transactions  270,000~650,000건
crm_customer_map        80,000~95,000건
```

---

## CRM 생성 논리

### 시간 논리

- 회원은 첫 거래·첫 매핑 이전에 가입한다.
- 포인트 거래는 가입 이후에만 발생한다.
- 고객 매핑 유효 시작은 회원 가입 이후다.
- 미래 회원·미래 포인트 거래를 Source 사실로 생성하지 않는다.
- mapping history는 `valid_from`, `valid_to`, `mapping_status`로 표현한다.
- 회원 등급 변경 이력은 가입 시 최초 등급부터 생성하며 UPGRADE·DOWNGRADE 반례를 모두 포함한다.
- 거래 당시 GOLD/현재 SILVER와 거래 당시 SILVER/현재 GOLD 회원을 각각 100명 이상 생성한다.
- `valid_to`와 거래 시각이 같은 경계 fixture를 생성한다.

### 포인트 잔액

최종 합계뿐 아니라 거래 시점별 running balance가 음수가 되지 않아야 한다.

```text
running_points_balance >= 0
points_balance = 최종 running balance
```

`USE`, `EXPIRE`는 음수 `points_delta`를 사용하되 허용 잔액을 넘지 않는다.

### 안정 ID

```text
point_txn_id:
property_id + member_no + event_date + txn_sequence_for_member_day

customer_map_id:
property_id + member_no + valid_from + mapping_version

grade_history_id:
property_id + member_no + valid_from + grade_code
```

전역 transaction row number를 hash key로 사용하지 않는다.

### 교차 Source 매핑

동일 숫자부 계약을 유지하되 모든 회원을 모든 Source에 연결하지 않는다.

```text
PMS 85%
POS 68%
Facility 30%
Banquet 8%
```

매핑되는 Source ref는 해당 Source의 생성 범위와 충돌하지 않도록 1~80,000 안에서 만든다.
동일 local ID 숫자부를 두 회원에게 재사용하지 않는다.

---

## SQL Server 구현 요구

- SQL Server 2022
- digit cross join 또는 tally CTE
- `HASHBYTES` 중심 deterministic 생성
- `CHECKSUM`은 분산 보조용으로만 사용
- `RAND()` 사용 금지
- `ABS(-2147483648)` 회피
- 자식→부모 순서 DELETE
- DDL·index 생성·DROP 금지
- transaction 사용
- 적재 순서는 `crm_members` → `crm_member_grade_history` → `crm_point_transactions` → `crm_customer_map`

---

## 필수 검증 쿼리

```text
member 중복 0
grade history orphan 0
grade valid_from >= valid_to 건수 0
회원별 grade 기간 중첩 0
현재 유효 grade 중복 0
crm_members.membership_grade와 evaluation_as_of 유효 grade 불일치 0
거래 당시 GOLD/현재 SILVER fixture 100명 이상
거래 당시 SILVER/현재 GOLD fixture 100명 이상
joined_at > source_updated_at 0
가입일 이전 포인트 거래 0
event_at > source_updated_at 0
2026-07-29 이후 포인트 거래 0
running balance 음수 0
거래 합계와 member balance 불일치 0
ACTIVE map 중복 0
valid_to <= valid_from 0
valid_from < joined_at 0
local ID별 활성·기간 중첩 mapping 0
mapping valid_to 경계에서 양쪽 이력 동시 JOIN 0
map source ID prefix 위반 0
참여하지 않는 source ref 생성 0
부모·자식 property_id 불일치 0
2026-07-29 이후 is_forecast=0 fact 0
실제 개인정보 패턴 0
```

요약은 연도·기간상태별 가입·거래를 분리하고 forecast 거래 0건을 확인한다.
등급 이력·mapping에 대해 row count, 유효기간 경계, watermark, checksum을 별도 출력한다.

---

## 완료 행동

T-SQL 파일 하나를 생성하고 링크와 검증 요약만 제공한다.
