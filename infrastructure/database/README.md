# 합성 운영 DB 환경

이 디렉터리는 실제 고객 데이터 없이 고정 seed `20260729`와 `synthetic` 표기로 재생성 가능한 6개 DB 컨테이너를 제공한다. 컨테이너 내부 연결은 Docker 서비스명(`pms-postgres`, `pos-mysql` 등)을 사용한다.

## 실행

```powershell
Copy-Item .env.example .env
# .env의 모든 ChangeMe 값을 고유한 비밀번호로 교체
docker compose --env-file .env -f compose.yml config
docker compose --env-file .env -f compose.yml up -d
docker compose --env-file .env -f compose.yml ps
docker compose --env-file .env -f compose.yml down
```

초기화 스크립트는 새 볼륨에서만 실행된다. 동일한 합성 환경을 다시 만들려면, 컨테이너를 중지한 뒤 명시적으로 이 Compose 프로젝트의 볼륨을 삭제하고 다시 `up -d` 한다.

```powershell
docker compose --env-file .env -f compose.yml down -v
docker compose --env-file .env -f compose.yml up -d
```

`crm-mssql-init`는 SQL Server가 healthy가 된 뒤 스키마·seed·읽기 전용 계정을 한 번 만들고 종료하는 초기화 작업이다. 6개 DB 서비스의 health 상태와 별도로 `docker compose ... logs crm-mssql-init`에서 성공 여부를 확인한다.

## 서비스와 접속

모든 포트는 기본값으로 `127.0.0.1`에만 노출된다. 값은 `.env`가 아닌 `compose.yml`의 기본 포트이며, 필요하면 Compose 환경변수로만 변경한다.

| 서비스 | 엔진·고정 버전 | 호스트 포트 | CLI 예시 |
| --- | --- | ---: | --- |
| app-postgres | PostgreSQL 16.4 | 54321 | `psql -h 127.0.0.1 -p 54321 -U $env:APP_RW_USERNAME -d $env:APP_DB_NAME` |
| pms-postgres | PostgreSQL 16.4 | 54322 | `psql -h 127.0.0.1 -p 54322 -U $env:PMS_RO_USERNAME -d $env:PMS_DB_NAME` |
| banquet-postgres | PostgreSQL 16.4 | 54323 | `psql -h 127.0.0.1 -p 54323 -U $env:BANQUET_RO_USERNAME -d $env:BANQUET_DB_NAME` |
| pos-mysql | MySQL 8.4.2 | 33061 | `mysql -h 127.0.0.1 -P 33061 -u $env:POS_RO_USERNAME -p $env:POS_DB_NAME` |
| crm-mssql | SQL Server 2022 CU14 | 14331 | `sqlcmd -C -S 127.0.0.1,14331 -U $env:CRM_RO_USERNAME -P $env:CRM_RO_PASSWORD -d $env:CRM_DB_NAME` |
| facility-clickhouse | ClickHouse 24.8.4.13 | 8124 | `clickhouse-client --host 127.0.0.1 --port 8124 --user $env:FACILITY_RO_USERNAME --password $env:FACILITY_RO_PASSWORD --database $env:FACILITY_DB_NAME` |

PostgreSQL, MySQL, ClickHouse는 UTF-8/`utf8mb4`를 우선하고, 모든 컨테이너는 `Asia/Seoul`을 설정한다.

## 계정·권한

| 서비스 | 계정 환경변수 | 권한 |
| --- | --- | --- |
| app-postgres | `APP_RW_USERNAME` | application table 읽기·쓰기 |
| app-postgres | `APP_MIGRATION_USERNAME` | schema 변경 포함 migration |
| pms-postgres | `PMS_RO_USERNAME` | `SELECT`, 메타데이터 조회 |
| banquet-postgres | `BANQUET_RO_USERNAME` | `SELECT`, 메타데이터 조회 |
| pos-mysql | `POS_RO_USERNAME` | `SELECT`, `SHOW VIEW` |
| crm-mssql | `CRM_RO_USERNAME` | `db_datareader`; DML·DDL 거부 |
| facility-clickhouse | `FACILITY_RO_USERNAME` | `SELECT` |

업무 source의 읽기 전용 계정에는 `INSERT`, `UPDATE`, `DELETE`, DDL 권한을 부여하지 않는다. DataHub ingestion과 Trino는 이 읽기 전용 자격증명을 사용한다. `app-postgres`는 애플리케이션 관리 DB이므로 ingestion과 Trino catalog 대상에서 제외한다.

## DataHub·Trino 매핑

| 서비스 | DataHub platform instance | Trino catalog |
| --- | --- | --- |
| pms-postgres | pms | pms |
| banquet-postgres | banquet | banquet |
| pos-mysql | pos | pos |
| crm-mssql | crm | crm |
| facility-clickhouse | facility | facility |

각 행은 개별 DB, 계정, DataHub recipe, Trino catalog로 격리한다.

## 이미지와 라이선스

태그는 재현성을 위해 고정했다: `postgres:16.4-bookworm`, `mysql:8.4.2`, `mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04`, `clickhouse/clickhouse-server:24.8.4.13-alpine`. SQL Server 이미지에 포함된 `/opt/mssql-tools18/bin/sqlcmd`를 초기화 작업에도 재사용한다. 이미지 digest는 플랫폼/아키텍처별로 달라 배포 직전에 `docker image inspect --format '{{index .RepoDigests 0}}' <image>` 결과를 릴리스 기록에 고정한다.

SQL Server는 `ACCEPT_EULA=Y`와 `MSSQL_PID=Developer`를 사용한다. Developer edition은 개발·테스트·시연용이며 운영 상용 워크로드 라이선스가 아니다. `CRM_SA_PASSWORD`는 SQL Server 복잡성 정책을 만족해야 하며, 모든 예시 비밀번호는 반드시 교체해야 한다.
