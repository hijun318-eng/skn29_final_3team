# Docker Compose 기반 합성 운영 DB 구축 수행 보고서

## 1. 작업 개요

`db_세팅.md` 지침에 따라 호텔 데이터 플랫폼 개발·시연용 합성 운영 DB 환경을 Docker Compose로 구성했다.

구성 대상은 다음과 같다.

- 애플리케이션 관리 DB 1개
- 업무 사일로 DB 5개
- DB별 독립 컨테이너, 계정, 볼륨 및 초기화 스크립트
- DataHub 및 Trino 연결을 위한 업무 DB 읽기 전용 계정

최종적으로 6개 DB 컨테이너를 실제로 실행하고 권한, 데이터 재현성, 볼륨 격리 및 데이터 영속성을 검증했다.

## 2. 기존 환경 확인

작업 전에 기존 Docker 설정과 컨테이너를 확인했다.

- 기존 프로젝트가 PostgreSQL 호스트 포트 `5432`를 사용 중인 것을 확인
- 기존 컨테이너, 네트워크 및 볼륨은 삭제하거나 변경하지 않음
- 신규 환경은 `hotel-synthetic-db`라는 별도 Compose 프로젝트로 격리
- 포트 충돌을 피하기 위해 신규 PostgreSQL은 `15432`부터 별도 포트를 사용

작업 완료 후 기존 `skn29-4th-5team` 컨테이너가 그대로 정상 실행 중인 것도 확인했다.

## 3. 생성한 파일 구조

구성 파일은 `infrastructure/database` 아래에 생성했다.

```text
infrastructure/database/
├─ compose.yml
├─ .env
├─ .env.example
├─ .gitignore
├─ README.md
├─ DB_세팅_수행_보고서.md
├─ start.ps1
├─ stop.ps1
├─ reset.ps1
├─ verify.ps1
└─ init/
   ├─ app-postgres/
   ├─ pms-postgres/
   ├─ banquet-postgres/
   ├─ pos-mysql/
   ├─ crm-mssql/
   └─ facility-clickhouse/
```

각 DB 초기화 디렉터리에서는 다음 항목을 별도 파일로 분리했다.

- 스키마 DDL
- 기준 데이터
- 고정 합성 데이터
- schema version
- 계정 및 권한

주요 파일:

- [Compose 구성](compose.yml)
- [환경변수 예시](.env.example)
- [운영 및 접속 설명서](README.md)
- [자동 검증 스크립트](verify.ps1)

## 4. DB 구성

| 서비스 | DB 엔진 | 호스트 접속 주소 | 컨테이너 접속 주소 | DB |
| --- | --- | --- | --- | --- |
| `app-postgres` | PostgreSQL | `127.0.0.1:15432` | `app-postgres:5432` | `app_db` |
| `pms-postgres` | PostgreSQL | `127.0.0.1:15433` | `pms-postgres:5432` | `pms_db` |
| `banquet-postgres` | PostgreSQL | `127.0.0.1:15434` | `banquet-postgres:5432` | `banquet_db` |
| `pos-mysql` | MySQL | `127.0.0.1:13306` | `pos-mysql:3306` | `pos_db` |
| `crm-mssql` | SQL Server | `127.0.0.1:11433` | `crm-mssql:1433` | `crm_db` |
| `facility-clickhouse` | ClickHouse HTTP | `127.0.0.1:18123` | `facility-clickhouse:8123` | `facility` |
| `facility-clickhouse` | ClickHouse Native | `127.0.0.1:19000` | `facility-clickhouse:9000` | `facility` |

모든 호스트 포트는 `127.0.0.1`에만 바인딩했다.

컨테이너 간 통신은 공통 `database-network`에서 서비스명을 DNS 주소로 사용한다.

## 5. 이미지 및 버전 고정

`latest` 태그를 사용하지 않고 이미지 태그와 manifest digest를 함께 고정했다.

| 엔진 | 고정 이미지 태그 |
| --- | --- |
| PostgreSQL | `postgres:16.13-bookworm` |
| MySQL | `mysql:8.4.6` |
| SQL Server | `mcr.microsoft.com/mssql/server:2022-CU17-ubuntu-22.04` |
| ClickHouse | `clickhouse/clickhouse-server:24.8.4.13` |

실제 검증에 사용한 컨테이너 내 클라이언트 버전은 다음과 같다.

- `psql 16.13`
- `mysql 8.4.6`
- `sqlcmd 18.4.0001.1`
- `clickhouse-client 24.8.4.13`

정확한 digest는 [README.md](README.md)의 고정 버전 항목에 기록했다.

## 6. 공통 운영 설정

모든 DB에 다음 설정을 적용했다.

- 독립 영구 Docker Volume
- Docker healthcheck
- 공통 Docker Network
- `Asia/Seoul` 시간대
- UTF-8 우선 문자 인코딩
- localhost 전용 호스트 포트
- 컨테이너 재시작 정책
- 서비스명 기반 컨테이너 간 연결

PostgreSQL은 UTF-8, 데이터 checksum 및 SCRAM-SHA-256 호스트 인증으로 초기화했다.

MySQL은 `utf8mb4`와 `utf8mb4_0900_ai_ci`를 적용했다.

SQL Server DB는 `Korean_100_CI_AS_SC_UTF8` collation으로 생성했다.

ClickHouse는 서버 시간대를 `Asia/Seoul`로 지정하는 별도 설정 파일을 적용했다.

## 7. 계정과 권한

### 7.1 app-postgres

`app-postgres`에는 다음 계정을 구성했다.

| 계정 환경변수 | 용도 |
| --- | --- |
| `APP_ADMIN_USER` | DB 초기화 및 운영 관리자 |
| `APP_MIGRATION_USER` | `app` 스키마 소유 및 DDL |
| `APP_DB_USER` | 애플리케이션 SELECT/INSERT/UPDATE/DELETE |

애플리케이션 계정에는 스키마 변경 권한을 부여하지 않았다.

`app-postgres`는 DataHub ingestion과 Trino catalog 대상에서 제외한다.

### 7.2 업무 DB 읽기 전용 계정

업무 DB 5개에는 각각 별도 읽기 전용 계정을 생성했다.

| 서비스 | 읽기 전용 계정 환경변수 |
| --- | --- |
| `pms-postgres` | `PMS_READONLY_USER` |
| `banquet-postgres` | `BANQUET_READONLY_USER` |
| `pos-mysql` | `POS_READONLY_USER` |
| `crm-mssql` | `CRM_READONLY_USER` |
| `facility-clickhouse` | `FACILITY_READONLY_USER` |

공통 권한 정책:

- 업무 테이블 `SELECT` 허용
- 시스템 메타데이터 조회 허용
- `INSERT`, `UPDATE`, `DELETE` 금지
- DDL 권한 금지
- 관리자 계정을 DataHub recipe나 Trino catalog에 사용하지 않음

DB별 추가 보호:

- PostgreSQL: 기본 읽기 전용 트랜잭션 설정
- MySQL: `SELECT`, `SHOW VIEW`만 부여
- SQL Server: 쓰기와 `ALTER` 권한을 명시적으로 `DENY`
- ClickHouse: `readonly=1` 적용

## 8. 환경변수와 비밀번호 관리

계정명과 비밀번호는 `.env`를 통해 컨테이너에 주입한다.

- `.env.example`: 팀원이 복사해서 사용하는 예시 파일
- `.env`: 현재 컴퓨터에서 즉시 실행하기 위한 로컬 설정
- `.gitignore`: `.env`가 Git에 포함되지 않도록 설정

팀원은 다음 방식으로 자신의 `.env`를 생성해야 한다.

```powershell
Copy-Item .env.example .env
```

그다음 `.env`의 모든 `CHANGE_ME_...` 비밀번호를 변경한다.

실제 `.env` 파일이나 비밀번호를 Git, 메신저 또는 문서에 공유하면 안 된다.

## 9. 합성 데이터 재현성

모든 DB에 다음 공통 값을 기록했다.

```text
schema version: 1.0.0
seed: 20260729
```

합성 데이터는 난수나 현재 시각에 의존하지 않는다.

- 고정 기본키 사용
- 고정 날짜와 시간 사용
- 고정 기준 데이터 사용
- DB별 schema version 테이블 사용

따라서 Docker Volume을 삭제한 뒤 다시 초기화해도 같은 스키마와 같은 합성 데이터가 생성된다.

## 10. DataHub 및 Trino 매핑

| 서비스 | DataHub platform instance | Trino catalog |
| --- | --- | --- |
| `pms-postgres` | `pms` | `pms` |
| `banquet-postgres` | `banquet` | `banquet` |
| `pos-mysql` | `pos` | `pos` |
| `crm-mssql` | `crm` | `crm` |
| `facility-clickhouse` | `facility` | `facility` |

각 소스는 다음 항목을 독립적으로 사용해야 한다.

- 별도 DB
- 별도 읽기 전용 계정
- 별도 DataHub recipe
- 별도 Trino catalog

## 11. 실행 방법

### 11.1 시작

```powershell
cd "프로젝트경로\infrastructure\database"
.\start.ps1
```

직접 Docker Compose 명령을 사용할 수도 있다.

```powershell
docker compose config --quiet
docker compose up -d --wait --wait-timeout 420
docker compose ps
```

### 11.2 검증

```powershell
.\verify.ps1
```

### 11.3 데이터 보존 상태로 중지

```powershell
.\stop.ps1
```

또는:

```powershell
docker compose down
```

### 11.4 전체 초기화

```powershell
.\reset.ps1
```

비대화형 실행:

```powershell
.\reset.ps1 -Force
```

이 명령은 `hotel-synthetic-db` 프로젝트가 소유한 DB 볼륨만 삭제한다.

## 12. 검증 결과

[verify.ps1](verify.ps1)을 사용해 다음 내용을 실제로 검증했다.

- `docker compose config` 성공
- 6개 DB 컨테이너 모두 `healthy`
- 모든 DB의 schema version `1.0.0` 확인
- 모든 DB의 seed `20260729` 확인
- 업무 읽기 전용 계정의 데이터 SELECT 성공
- PostgreSQL `information_schema` 조회 성공
- MySQL `information_schema` 조회 성공
- SQL Server `sys.tables` 조회 성공
- ClickHouse `system.tables` 조회 성공
- PMS 계정의 INSERT 실패
- 연회 계정의 DELETE 실패
- POS 계정의 UPDATE 실패
- CRM 계정의 DELETE 실패
- 시설 계정의 DDL 실패
- `app-postgres` 애플리케이션 계정 읽기·쓰기 성공
- PMS와 연회 PostgreSQL의 DB, 계정 및 볼륨 격리
- PMS 계정으로 연회 DB 교차 로그인 실패
- 컨테이너 재시작 후 데이터 유지
- 전체 볼륨 삭제 후 동일 seed 환경 재생성
- 기존 Docker 프로젝트가 변경되지 않았음을 확인

최종 검증 결과:

```text
All verification checks passed.
```

## 13. 작업 중 발견하고 보정한 내용

### 13.1 기존 PostgreSQL 포트 충돌

기존 프로젝트가 `5432`를 사용 중이어서 신규 PostgreSQL 호스트 포트를 `15432`, `15433`, `15434`로 변경했다.

### 13.2 MySQL 읽기 전용 계정 초기화

MySQL 초기화 스크립트에서 필요한 `POS_DB_NAME` 환경변수 전달을 보완했다.

볼륨을 삭제한 뒤 다시 초기화하여 읽기 전용 계정 생성과 권한을 재검증했다.

### 13.3 SQL Server 권한 계층

초기 설정에서 스키마의 `CONTROL`을 거부하면 하위 `SELECT` 권한도 함께 거부되는 것을 확인했다.

`CONTROL` 거부는 제거하고 쓰기 및 `ALTER` 권한만 명시적으로 거부하도록 수정했다.

### 13.4 Windows PowerShell 호환성

Windows PowerShell 5.1 환경에서 UTF-8 BOM과 CRLF 처리로 검증 스크립트가 영향을 받는 문제를 확인했다.

다음 방식으로 보정했다.

- PowerShell 실행 메시지를 ASCII로 작성
- 컨테이너 명령을 인자 대신 표준 입력으로 전달
- Windows CR 문자가 셸의 마지막 인자에 포함되지 않도록 처리
- Docker의 정상 stderr 진행 메시지를 실패로 오인하지 않도록 처리

## 14. SQL Server 사용 주의사항

`.env`의 다음 설정은 SQL Server EULA 동의를 의미한다.

```text
MSSQL_ACCEPT_EULA=Y
```

기본 edition은 다음과 같다.

```text
MSSQL_PID=Developer
```

Developer Edition은 개발, 테스트 및 시연 같은 비운영 용도로만 사용해야 한다. 운영 환경에는 적절한 SQL Server 라이선스와 edition 설정이 필요하다.

SQL Server 비밀번호는 최소 8자 이상이며 대문자, 소문자, 숫자, 기호 중 세 종류 이상을 포함해야 한다.

## 15. 최종 상태

다음 6개 DB가 현재 모두 실행 중이며 `healthy` 상태다.

```text
app-postgres
pms-postgres
banquet-postgres
pos-mysql
crm-mssql
facility-clickhouse
```

기존 Docker 프로젝트는 변경하지 않았으며 신규 환경은 독립된 Compose 프로젝트, 네트워크 및 볼륨으로 운영된다.
