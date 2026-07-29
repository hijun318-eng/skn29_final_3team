# 합성 운영 DB 환경

호텔 데이터 플랫폼의 애플리케이션 관리 DB 1개와 업무 사일로 DB 5개를 Docker Compose로 실행한다. 모든 호스트 포트는 `127.0.0.1`에만 바인딩하며, 컨테이너 간에는 공통 `database-network`에서 아래 서비스명을 DNS 이름으로 사용한다.

`app-postgres`는 애플리케이션 전용이며 DataHub ingestion 및 Trino catalog 대상에서 제외한다.

## 빠른 시작

요구 사항은 Docker Desktop과 Docker Compose v2 이상이다. SQL Server를 포함하므로 Docker Desktop에 최소 6 GB, 권장 8 GB 이상의 메모리를 할당한다.

```powershell
cd infrastructure/database
.\start.ps1
.\verify.ps1
```

직접 실행하려면 다음 명령을 사용한다.

```powershell
docker compose config --quiet
docker compose up -d --wait --wait-timeout 420
docker compose ps
```

중지하되 데이터를 보존하려면:

```powershell
.\stop.ps1
# 또는
docker compose down
```

`.env`는 로컬 실행용으로 생성되어 있고 `.gitignore`에서 제외한다. 다른 환경에서는 `.env.example`을 `.env`로 복사한 뒤 모든 `CHANGE_ME_...` 값을 바꾼다. 계정명과 DB명은 영문·숫자·밑줄만, 비밀번호는 영문 대·소문자·숫자·`!_.+=-`만 사용하는 것을 권장한다.

## 서비스와 포트

기존 로컬 PostgreSQL이 `5432`를 사용하고 있어 충돌하지 않는 호스트 포트를 기본값으로 지정했다.

| 서비스 | DB 엔진 | 컨테이너 접속 주소 | 호스트 접속 주소 | DB |
| --- | --- | --- | --- | --- |
| `app-postgres` | PostgreSQL | `app-postgres:5432` | `127.0.0.1:15432` | `app_db` |
| `pms-postgres` | PostgreSQL | `pms-postgres:5432` | `127.0.0.1:15433` | `pms_db` |
| `banquet-postgres` | PostgreSQL | `banquet-postgres:5432` | `127.0.0.1:15434` | `banquet_db` |
| `pos-mysql` | MySQL | `pos-mysql:3306` | `127.0.0.1:13306` | `pos_db` |
| `crm-mssql` | SQL Server | `crm-mssql:1433` | `127.0.0.1:11433` | `crm_db` |
| `facility-clickhouse` | ClickHouse native | `facility-clickhouse:9000` | `127.0.0.1:19000` | `facility` |
| `facility-clickhouse` | ClickHouse HTTP | `facility-clickhouse:8123` | `127.0.0.1:18123` | `facility` |

호스트 포트와 DB명은 `.env`에서 바꿀 수 있다. 컨테이너 간 설정(DataHub, Trino 등)에는 호스트 포트가 아니라 반드시 서비스명과 컨테이너 포트를 사용한다.

## 계정과 권한

비밀번호는 문서에 기록하지 않고 `.env`에서만 관리한다.

| 서비스 | 계정 환경변수 | 권한 |
| --- | --- | --- |
| `app-postgres` | `APP_ADMIN_USER` | 초기화·운영 관리자(superuser) |
| `app-postgres` | `APP_MIGRATION_USER` | `app` 스키마 소유 및 DDL |
| `app-postgres` | `APP_DB_USER` | `app` 스키마 SELECT/INSERT/UPDATE/DELETE, 시퀀스 사용 |
| `pms-postgres` | `PMS_READONLY_USER` | `pms` 스키마 SELECT, 메타데이터 조회; 쓰기·DDL 없음 |
| `banquet-postgres` | `BANQUET_READONLY_USER` | `banquet` 스키마 SELECT, 메타데이터 조회; 쓰기·DDL 없음 |
| `pos-mysql` | `POS_READONLY_USER` | `pos_db` SELECT/SHOW VIEW; 쓰기·DDL 없음 |
| `crm-mssql` | `CRM_READONLY_USER` | `crm` 스키마 SELECT와 DB 메타데이터 VIEW DEFINITION; 쓰기·DDL 명시적 DENY |
| `facility-clickhouse` | `FACILITY_READONLY_USER` | `facility.*` SELECT와 필요한 `system` 메타데이터 SELECT; `readonly=1` |

업무 계정은 DataHub 메타데이터 수집 및 Trino 조회 전용이다. 관리자 계정을 recipe나 catalog에 넣지 않는다.

## DataHub·Trino 소스 매핑

각 소스는 별도 DB, 계정, DataHub recipe, Trino catalog로 격리한다.

| 서비스 | DataHub platform instance | Trino catalog |
| --- | --- | --- |
| `pms-postgres` | `pms` | `pms` |
| `banquet-postgres` | `banquet` | `banquet` |
| `pos-mysql` | `pos` | `pos` |
| `crm-mssql` | `crm` | `crm` |
| `facility-clickhouse` | `facility` | `facility` |

`app-postgres`는 위 매핑에서 의도적으로 제외한다.

## CLI 접속

컨테이너 내 클라이언트를 사용하면 호스트에 별도 드라이버를 설치하지 않아도 된다.

```powershell
# PostgreSQL 관리자 예시
docker compose exec app-postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

# MySQL 관리자
docker compose exec pos-mysql sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'

# SQL Server 관리자
docker compose exec crm-mssql sh -lc 'SQLCMD=/opt/mssql-tools18/bin/sqlcmd; [ -x "$SQLCMD" ] || SQLCMD=/opt/mssql-tools/bin/sqlcmd; "$SQLCMD" -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -d "$CRM_DB_NAME"'

# ClickHouse 관리자
docker compose exec facility-clickhouse sh -lc 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB"'
```

호스트 GUI/CLI에서는 위 포트 표와 `.env`의 계정을 사용한다. TLS 인증서가 없는 로컬 SQL Server 개발 컨테이너이므로 `sqlcmd` 예시는 인증서를 신뢰하는 `-C` 옵션을 사용한다.

## 고정 버전

2026-07-29에 `linux/amd64` Docker Desktop에서 태그 존재와 manifest digest를 확인했다. Compose는 태그와 digest를 함께 고정하므로 레지스트리의 태그 이동에도 동일 이미지를 사용한다.

| 엔진 | 이미지 태그 | manifest digest |
| --- | --- | --- |
| PostgreSQL | `postgres:16.13-bookworm` | `sha256:472efd9a66f2b2f1a5aeb18b28de74332e6ef88c2b93a1a5d812fb6db67a5f60` |
| MySQL | `mysql:8.4.6` | `sha256:869218921e61d6c3c89820955d63cca42971f0e3e6c1e2792247bbd944ebc6e9` |
| SQL Server | `mcr.microsoft.com/mssql/server:2022-CU17-ubuntu-22.04` | `sha256:d252932ef839c24c61c1139cc98f69c85ca774fa7c6bfaaa0015b7eb02b9dc87` |
| ClickHouse | `clickhouse/clickhouse-server:24.8.4.13` | `sha256:70629c6127ee7531e0d0b68ccdb0577775bbf1e27723f929e96cb26f7fbee3c2` |

PostgreSQL 16과 MySQL 8.4 LTS는 장기 유지 계열을 선택했다. SQL Server 2022는 누적 업데이트(CU) 태그, ClickHouse는 정확한 patch 태그를 사용한다. 초기 검증에는 이미지에 포함된 `psql 16.13`, `mysql 8.4.6`, `sqlcmd 18.4.0001.1`, `clickhouse-client 24.8.4.13`을 사용했다. DataHub와 Trino를 추가할 때는 해당 릴리스가 번들한 커넥터/드라이버를 우선 사용하고, 외부 드라이버를 별도로 넣는 경우 그 버전도 recipe/catalog와 함께 고정한다.

공식 이미지 동작은 [PostgreSQL Docker Official Image](https://hub.docker.com/_/postgres), [MySQL Docker Official Image](https://hub.docker.com/_/mysql), [SQL Server Linux 컨테이너 문서](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-docker-container-deployment), [ClickHouse Docker 설치 문서](https://clickhouse.com/docs/install/docker)를 기준으로 했다.

## 초기화와 재현성

각 DB 초기화 디렉터리는 실행 순서가 보이는 번호 접두사를 사용한다.

```text
infrastructure/database/
├─ compose.yml
├─ .env.example
├─ README.md
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

각 DB에서 스키마 DDL, 기준 데이터, 합성 데이터, schema version, 권한을 별도 파일로 유지한다. 모든 합성 데이터는 난수나 현재 시간에 의존하지 않으며 schema version `1.0.0`, seed `20260729`를 사용한다.

전체 볼륨을 삭제하고 동일 데이터로 재생성하려면:

```powershell
.\reset.ps1
```

비대화형 실행은 `.\reset.ps1 -Force`를 사용한다. 이 명령은 Compose 프로젝트 `hotel-synthetic-db`가 소유한 7개 볼륨만 제거한다. 기존의 다른 Docker 프로젝트, 컨테이너, 네트워크, 볼륨은 삭제하지 않는다.

초기화 스크립트나 초기 계정 비밀번호를 변경한 경우 기존 볼륨에는 자동 반영되지 않는다. 개발 데이터를 백업한 후 reset하거나, 운영 절차에 맞는 migration을 작성한다.

## 검증

```powershell
.\verify.ps1
```

다음을 자동 검증한다.

- `docker compose config`
- 6개 DB의 `healthy` 상태
- 업무 DB 읽기 전용 계정의 SELECT 성공과 INSERT/UPDATE/DELETE/DDL 실패
- `app-postgres` 애플리케이션 계정의 읽기·쓰기
- PMS와 연회 PostgreSQL의 별도 컨테이너·DB·계정·볼륨
- `app-postgres` 재시작 후 검증 행 유지

볼륨 삭제 후 재생성은 `reset.ps1 -Force` 후 `verify.ps1`을 다시 실행해 확인한다.

## SQL Server EULA와 라이선스

`.env`의 `MSSQL_ACCEPT_EULA=Y`는 Microsoft SQL Server EULA에 동의한다는 의미다. 동의할 권한이 없다면 컨테이너를 시작하지 않는다.

기본값 `MSSQL_PID=Developer`는 개발·테스트·시연 등 비운영 용도에만 허용되는 무료 Developer Edition이다. 운영 사용에는 적절한 유료 라이선스와 edition 설정이 필요하다. 자세한 조건은 [Microsoft SQL Server 컨테이너 배포 및 라이선스 안내](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-docker-container-deployment)에서 확인한다.

SQL Server 비밀번호는 기본 정책상 8자 이상이며 대문자, 소문자, 숫자, 기호 네 범주 중 세 범주 이상을 포함해야 한다. 이 구성의 로컬 `.env` 값은 정책을 만족하지만, 공유 환경에서는 반드시 별도 비밀 관리 시스템의 값으로 교체한다.
