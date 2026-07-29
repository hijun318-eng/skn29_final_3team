# Answervice 통합 SQL 배포본 검증·역할별 매핑 작업지시문 v1.0

작성일: 2026-07-29  
작업 유형: `SQL_BUNDLE_MAPPING_ONLY`  
입력 단위: **통합 SQL ZIP 1개**  
실제 DB 실행: 기본 `false`

---

## 1. 작업 목적

Answervice 프로젝트에서 생성된 역할별·엔진별 SQL을 하나의 통합 ZIP으로 전달받아 다음 작업을 수행한다.

1. 통합 ZIP의 무결성과 manifest 확인
2. SQL 파일의 역할·도메인·DBMS·실행 성격 판정
3. 역할 소유권 위반 확인
4. 실행용 SQL과 검증·참조용 SQL 분리
5. 승인된 저장소 경로에 복사 또는 매핑 제안
6. 중복·충돌·누락 보고
7. checksum 기반 최종 mapping manifest 작성

이번 작업에서는 SQL 내용을 새로 설계하거나 실제 DB에 실행하지 않는다.

---

## 2. 단일 배포본 원칙

### 2.1 허용되는 단일 파일

팀 공유 시 다음과 같이 **ZIP 하나만 전달**한다.

```text
260729_Answervice_팀공유_SQL_결과물_v1.0.zip
```

ZIP 내부에는 역할별·엔진별 SQL이 분리되어 있어야 한다.

### 2.2 금지되는 단일 SQL

다음 DBMS의 SQL을 하나의 `.sql` 파일로 합치지 않는다.

```text
PostgreSQL
MySQL
Microsoft SQL Server
ClickHouse
Trino
```

이유:

- PostgreSQL의 `\connect`, `DO $$`, `timestamptz`
- MySQL의 `USE`, `ENGINE=InnoDB`, 백틱, `DELIMITER`
- SQL Server의 `GO`, `dbo`, `datetime2`
- ClickHouse의 `MergeTree`, `LowCardinality`, `ALTER ... DELETE`
- Trino의 cross-catalog View 문법

위 문법은 하나의 엔진에서 동시에 실행될 수 없다.

단일 공유가 필요하면 ZIP을 사용한다.  
모든 SQL을 이어 붙인 파일은 검토용 문서로만 만들 수 있으며 실행 파일로 취급하지 않는다.

---

## 3. 기준 역할

```text
R1 박준희
- 최종 통합 검증
- 공유 환경 적용 승인
- P2 승인
- 역할 충돌 최종 판정

R2 정승
- Source DB 5개
- Source DDL
- Source seed
- DataHub
- Trino catalog·View

R4 김재홍
- Application DB
- Alembic migration chain
- OpenAPI

R5 송민지
- Report migration 초안
- 최종 Alembic revision 확정 금지

ML 작업카드 담당자
- 객실수요예측 Feature Query
- 학습·평가·예측 구현
- Source DB와 Application DB 쓰기 금지
```

현재 branch, 공식 WBS, 역할소유권 문서, 승인 작업 카드를 먼저 확인한다.

승인 작업 카드가 없거나 경로 소유권이 불명확하면 저장소를 수정하지 않고 매핑 제안서만 작성한다.

---

## 4. 입력 ZIP 탐색

### 4.1 우선 탐색 순서

다음 순서로 통합 ZIP의 내용을 분석한다.

```text
1. manifest.json 또는 sql_mapping_manifest.csv
2. 역할별 폴더명
3. SQL 파일 헤더
4. 생성·참조 테이블
5. DBMS 고유 문법
6. 파일명
```

파일명만으로 역할이나 DBMS를 확정하지 않는다.

### 4.2 예상 역할 폴더

```text
R2/
R4/
R5/
R1/
ML/
00_공유/
00_역할별_ZIP/
```

폴더명이 다르더라도 manifest와 SQL 내용으로 판정한다.

### 4.3 누락 상태

```text
NOT_FOUND
NOT_SQL
EMPTY
AMBIGUOUS
CHECKSUM_MISMATCH
MANIFEST_MISMATCH
```

누락되거나 모호한 SQL을 임의로 새로 생성하지 않는다.

---

## 5. SQL 성격 분류

각 SQL은 다음 중 하나로 판정한다.

```text
SOURCE_DDL
SOURCE_SEED
SOURCE_PERMISSION
TRINO_VIEW_DDL
TRINO_FEATURE_QUERY
APP_DB_DDL
APP_DB_PREFLIGHT
APP_DB_POSTFLIGHT
REPORT_REVIEW_SQL
INTEGRATION_GATE_SQL
ML_LEAKAGE_PREFLIGHT
REFERENCE_SQL
UNKNOWN
```

### 5.1 실행용 초기화 후보

다음만 Source DB 초기화 후보로 취급한다.

```text
SOURCE_DDL
SOURCE_SEED
SOURCE_PERMISSION
```

### 5.2 자동 초기화 제외

다음은 자동 init 디렉터리에 넣지 않는다.

```text
TRINO_VIEW_DDL
TRINO_FEATURE_QUERY
APP_DB_DDL
APP_DB_PREFLIGHT
APP_DB_POSTFLIGHT
REPORT_REVIEW_SQL
INTEGRATION_GATE_SQL
ML_LEAKAGE_PREFLIGHT
REFERENCE_SQL
```

각 SQL은 별도 실행 단계와 별도 승인 주체가 있으므로 Source init에 섞지 않는다.

---

## 6. R2 Source SQL 매핑

### 6.1 PMS

```text
DBMS: PostgreSQL
Compose service: pms-postgres
권장 경로:
infrastructure/database/init/pms-postgres/
```

실행 순서:

```text
01_schema.sql
02_seed.sql
03_permissions.sql
```

실제 파일이 완결형 SQL이면 분할하지 않고 원래 파일을 유지하며 manifest에 순서만 기록한다.

### 6.2 POS

```text
DBMS: MySQL
Compose service: pos-mysql
권장 경로:
infrastructure/database/init/pos-mysql/
```

### 6.3 CRM

```text
DBMS: Microsoft SQL Server
Compose service: crm-mssql
권장 경로:
infrastructure/database/init/crm-mssql/
```

다음 실제 객체를 확인한다.

```text
crm_customer_map
crm_member_grade_history
```

논리 alias인 `customer_identity_map`, `member_grade_history`만 보고 물리 테이블이 없다고 오판하지 않는다.

`crm-mssql-init`은 SQL Server가 healthy가 된 뒤 초기화를 수행하고 정상 종료하는 one-shot 컨테이너다.

```text
crm-mssql-1:
실제 SQL Server
실행 중·healthy가 정상

crm-mssql-init:
초기화 완료 후 Exited (0) 또는 비활성이 정상
별도 상시 시작 대상 아님
```

### 6.4 Facility

```text
DBMS: ClickHouse
Compose service: facility-clickhouse
권장 경로:
infrastructure/database/init/facility-clickhouse/
```

ClickHouse SQL의 논리 관계를 PostgreSQL FK로 변환하지 않는다.

### 6.5 Banquet

```text
DBMS: PostgreSQL
Compose service: banquet-postgres
권장 경로:
infrastructure/database/init/banquet-postgres/
```

PMS와 같은 PostgreSQL이라도 DB, 계정, volume, schema, seed를 공유하지 않는다.

---

## 7. Trino SQL 매핑

### 7.1 Analytics View

```text
file_type=TRINO_VIEW_DDL
owner_role=R2
```

권장 경로:

```text
infrastructure/trino/sql/views/
```

Source DB init 디렉터리에 넣지 않는다.

필수 확인:

```text
catalog:
app
pms
pos
crm
facility
banquet

view count:
8
```

### 7.2 ML Feature Query

```text
file_type=TRINO_FEATURE_QUERY
owner_role=ML 작업카드 담당자
review_role=R2
```

권장 경로:

```text
sql/ml/reference/
```

자동 실행하지 않는다.

다음 구문이 있으면 차단한다.

```text
CREATE TABLE
INSERT
UPDATE
DELETE
MERGE
DROP
ALTER
CALL
```

Feature Query는 read-only SELECT·CTE만 허용한다.

---

## 8. R4 Application DB SQL 매핑

다음 SQL은 Source DB init에 넣지 않는다.

```text
APP_DB_PREFLIGHT
APP_DB_DDL
APP_DB_POSTFLIGHT
```

권장 전달 경로:

```text
docs/db/application/
```

실제 Alembic 적용은 R4가 담당한다.

### 8.1 Preflight 필수

DDL 전에 다음을 비교해야 한다.

```text
schema
table
column
data type
NULL
PK
FK
UNIQUE
CHECK
index
```

기존 객체가 계약과 다르면:

```text
SCHEMA_CONTRACT_MISMATCH
```

로 중단한다.

`CREATE TABLE IF NOT EXISTS`만으로 기존 객체를 정상으로 판정하지 않는다.

### 8.2 P2

```text
INCLUDE_P2=false
```

R1 승인과 별도 작업 카드가 없으면 P2 SQL을 생성하거나 적용하지 않는다.

---

## 9. R5 Report SQL 매핑

R5 산출물은 다음으로 제한한다.

```text
REPORT_REVIEW_SQL
Report migration 초안 문서
```

자동 실행 디렉터리에 넣지 않는다.

R5는 다음을 수행하지 않는다.

```text
최종 Alembic revision ID 확정
down_revision 확정
alembic_version 변경
migration 실행
Application schema 직접 변경
```

최종 migration chain은 R4가 작성한다.

---

## 10. R1 통합 Gate SQL 매핑

다음 SQL은 read-only 통합 검증용이다.

```text
INTEGRATION_GATE_SQL
```

권장 경로:

```text
sql/validation/integration/
```

자동 초기화 시 실행하지 않는다.

R1 Gate는 다음을 확인한다.

```text
Application table count
Source table count
Trino View count
role write violation
forecast/actual 분리
schema version
seed version
watermark
checksum
```

R1은 검증을 위해 다른 담당자의 원본 SQL을 직접 수정하지 않는다.

---

## 11. ML SQL 매핑

다음 유형을 구분한다.

```text
TRINO_FEATURE_QUERY
ML_LEAKAGE_PREFLIGHT
PMS_ONLY_FALLBACK_QUERY
```

권장 경로:

```text
sql/ml/reference/
```

다음 파일·테이블은 생성하지 않는다.

```text
train.csv
validation.csv
test.csv
train.jsonl
validation.jsonl
test.jsonl
ml_train table
ml_validation table
ml_test table
Feature Store
별도 학습 DB
```

Train·Validation·Test는 Trino 조회 결과를 메모리 DataFrame에서 시간순으로 분할한다.

---

## 12. 원본 보존

다음 작업을 금지한다.

```text
원본 삭제
원본 이동
원본 덮어쓰기
DBMS 문법 자동 변환
서로 다른 엔진 SQL 병합
테이블명 변경
컬럼명 변경
타입 변경
제약조건 삭제
seed 축소
현재 시각 기반 값으로 변경
```

복사본 상단에도 주석을 추가하지 않는다.

원본 파일명, checksum, 출처, 대상 경로는 manifest에서 관리한다.

---

## 13. 중복·충돌 판정

상태는 다음 중 하나만 사용한다.

```text
NO_CONFLICT
IDENTICAL_DUPLICATE
STRUCTURE_CONFLICT
CONSTRAINT_CONFLICT
TYPE_CONFLICT
INDEX_CONFLICT
SEED_CONFLICT
ROLE_OWNERSHIP_CONFLICT
EXECUTION_ORDER_CONFLICT
MANIFEST_CONFLICT
UNRESOLVED
```

동일 테이블이 여러 SQL에 존재하면 자동 병합하지 않는다.

DDL과 seed는 중복이 아니다. 역할이 다르다.

```text
DDL:
객체 구조 생성

seed:
합성 데이터 적재
```

---

## 14. 시간 기준

다음 세 값은 같은 순간으로 취급한다.

```text
snapshot_as_of_at   = 2026-07-28T05:00:00Z
generation_as_of_at = 2026-07-28T05:00:00Z
evaluation_as_of    = 2026-07-28T14:00:00+09:00
```

다른 값이 발견되면 자동 수정하지 말고:

```text
TIME_CONTRACT_MISMATCH
```

로 기록한다.

---

## 15. 실행 승인 계약

기본값:

```text
GENERATE_FILES_ONLY=true
EXECUTE_DB=false
INCLUDE_P2=false
```

접속정보가 있다는 사실은 실행 승인으로 간주하지 않는다.

승인 주체:

```text
Source DB·seed·DataHub·Trino 로컬 적용:
R2 명시 승인

Application DB·Alembic 로컬 적용:
R4 명시 승인

공유 환경 적용:
R1 명시 승인

P2:
R1 승인 + 별도 작업 카드

삭제·재생성·volume 초기화·권한 변경:
별도 명시 승인
```

승인 문구가 없으면 실행하지 않는다.

---

## 16. 생성 산출물

승인된 R2 경로 또는 작업 산출물 경로에 다음을 생성한다.

```text
sql-mapping/
├─ SQL_BUNDLE_MAPPING_REPORT.md
├─ sql_bundle_mapping_manifest.csv
├─ checksum_manifest.sha256
└─ change_requests/
   ├─ R1_CHANGE_REQUEST.md
   ├─ R4_CHANGE_REQUEST.md
   └─ ML_CHANGE_REQUEST.md
```

### 16.1 manifest 컬럼

```text
bundle_name
sql_id
source_file
source_checksum
file_type
domain
detected_dbms
owner_role
review_role
target_service
recommended_target_path
execution_stage
mapping_action
duplicate_status
conflict_status
schema_version
seed_version
time_contract_status
notes
```

### 16.2 mapping_action

```text
COPY_TO_SOURCE_INIT
COPY_TO_TRINO_VIEW_PATH
COPY_TO_ML_REFERENCE
HANDOFF_TO_R4
HANDOFF_TO_R5
KEEP_AS_INTEGRATION_GATE
KEEP_AS_REFERENCE
EXCLUDE_FROM_AUTO_INIT
MISSING
BLOCKED_BY_OWNERSHIP
BLOCKED_BY_APPROVAL
```

---

## 17. 검증 범위

수행:

```text
ZIP 무결성
manifest 존재 여부
파일 존재 여부
확장자
SHA-256
DBMS 문법 판정
생성 테이블·View 추출
DDL·seed 구분
역할 소유권 확인
실행 순서 확인
경로 존재 여부
P2 포함 여부
시간 기준 일치
금지 DML·DDL 탐지
```

수행하지 않음:

```text
docker compose 실행
컨테이너 시작
DB 생성
SQL 실행
데이터 적재
권한 negative test
row count 실측
DataHub ingestion
Trino Query
Alembic migration
모델 학습
```

수행하지 않은 검증은 `NOT_RUN`으로 기록한다.

---

## 18. 완료 조건

```text
[ ] 통합 ZIP 하나를 입력으로 사용했다.
[ ] ZIP을 단일 SQL로 오인하지 않았다.
[ ] manifest와 실제 파일을 대조했다.
[ ] R2 Source DDL과 seed를 구분했다.
[ ] 5개 Source의 DBMS를 확인했다.
[ ] Trino View를 Source init에서 제외했다.
[ ] ML Feature Query를 Source init에서 제외했다.
[ ] Application DB SQL을 R4 전달로 분류했다.
[ ] Report SQL을 자동 실행에서 제외했다.
[ ] R1 Gate SQL을 read-only 검증으로 분류했다.
[ ] P2 SQL 기본 제외를 확인했다.
[ ] 시간 기준을 검증했다.
[ ] 원본을 수정하지 않았다.
[ ] SQL을 실제 실행하지 않았다.
[ ] manifest와 보고서를 작성했다.
```

---

## 19. 최종 보고 형식

```text
작업 유형:
SQL_BUNDLE_MAPPING_ONLY

통합 ZIP:
branch:
TASK_CARD_ID:
OWNERSHIP_CONTRACT_VERSION:
SCHEMA_VERSION:
SEED_VERSION:

ZIP 무결성:
manifest 검증:

R2 Source 매핑:
- PMS DDL:
- PMS seed:
- POS DDL:
- POS seed:
- CRM DDL:
- CRM seed:
- Facility DDL:
- Facility seed:
- Banquet DDL:
- Banquet seed:
- Trino View:

R4 전달:
R5 전달:
R1 Gate:
ML 참조 SQL:

자동 초기화 포함:
자동 초기화 제외:

중복:
충돌:
역할 소유권 위반:
DBMS 문법 불일치:
시간 기준 불일치:
P2 포함 여부:

생성·복사 파일:
작성한 manifest:
작성한 change request:

실행한 검증:
NOT_RUN:
남은 위험:
```

실행하지 않은 SQL, 데이터 적재, 권한, Trino, Alembic, ML 결과를 성공으로 기록하지 않는다.
