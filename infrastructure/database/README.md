# 합성 운영 DB 로컬 환경

호텔 데이터허브 개발·시연용으로 5개 업무 source와 애플리케이션 관리 DB를 서로 다른 컨테이너, 데이터베이스, 계정, 볼륨으로 실행한다. 초기 데이터는 모두 `synthetic`이며 실제 고객·호텔 운영 데이터를 포함하지 않는다.

이 디렉터리는 DB bootstrap과 연결 템플릿만 제공한다. DataHub와 Trino 서버 자체는 이 Compose에 포함하지 않으며, 대규모 2022~2026 합성 데이터 생성기와 Trino 분석 View도 별도 작업 범위다. 현재 fixture는 엔진·스키마·권한·재현성을 검증할 수 있는 작은 대표 데이터셋이다.

## 빠른 시작

```powershell
Set-Location infrastructure/database
Copy-Item .env.example .env
```

`.env`의 모든 `ChangeMe` 값을 로컬 전용 강한 비밀번호로 바꾼 뒤 실행한다.

```powershell
docker compose config
docker compose up -d
docker compose ps
python scripts/verify.py --env-file .env
```

중지는 데이터 유지 여부에 따라 구분한다.

```powershell
# 컨테이너만 중지하며 named volume 데이터는 유지
docker compose stop

# 컨테이너와 network를 제거하지만 named volume은 유지
docker compose down

# 이 Compose 프로젝트의 6개 DB volume까지 삭제하고 동일 seed로 재생성
python scripts/verify.py --env-file .env --recreate
```

`--recreate`는 이 프로젝트의 named volume을 삭제한다. 필요한 로컬 데이터가 있으면 먼저 백업한다.

## 서비스와 접속

| 서비스 | Engine / Database | Host endpoint | Docker network endpoint |
|---|---|---|---|
| `app-postgres` | PostgreSQL / `hotel_datahub_app` | `127.0.0.1:15430` | `app-postgres:5432` |
| `pms-postgres` | PostgreSQL / `hotel_pms` | `127.0.0.1:15432` | `pms-postgres:5432` |
| `banquet-postgres` | PostgreSQL / `hotel_banquet` | `127.0.0.1:15433` | `banquet-postgres:5432` |
| `pos-mysql` | MySQL / `hotel_pos` | `127.0.0.1:13306` | `pos-mysql:3306` |
| `crm-mssql` | SQL Server / `hotel_crm` | `127.0.0.1:11433` | `crm-mssql:1433` |
| `facility-clickhouse` | ClickHouse / `hotel_facility` | `127.0.0.1:18123`, `127.0.0.1:19000` | `facility-clickhouse:8123`, `facility-clickhouse:9000` |

호스트 포트는 `.env`에서 변경할 수 있지만 항상 `127.0.0.1`에만 bind된다. 컨테이너끼리는 공통 `database-network`에서 위 서비스명을 사용한다.

SQL Server에는 공식 init hook이 없어 `crm-mssql-init` one-shot 서비스가 schema와 계정을 만든다. 정상 초기화 뒤 이 서비스가 `Exited (0)`인 것은 정상이며 실행 중인 DB 컨테이너 수에는 포함하지 않는다.

### 컨테이너 안에서 CLI 접속

```powershell
docker compose exec app-postgres psql -U app_admin -d hotel_datahub_app
docker compose exec pms-postgres psql -U pms_admin -d hotel_pms
docker compose exec banquet-postgres psql -U banquet_admin -d hotel_banquet
docker compose exec pos-mysql mysql -uroot -p hotel_pos
docker compose exec crm-mssql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -d hotel_crm
docker compose exec facility-clickhouse clickhouse-client --user facility_admin --database hotel_facility --password
```

비밀번호는 명령행에 직접 쓰지 말고 prompt 또는 컨테이너 환경변수를 사용한다.

## 고정 버전과 image digest

| Engine | Image | Multi-platform manifest digest | 선택 근거 |
|---|---|---|---|
| PostgreSQL | `postgres:16.14-bookworm` | `sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55` | PostgreSQL 15+ 계약과 호환되는 16 계열 고정 patch, Debian bookworm |
| MySQL | `mysql:8.4.11-oraclelinux9` | `sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb` | 8.4 LTS 고정 patch |
| SQL Server | `2022-CU26-ubuntu-22.04` | `sha256:ba4c8329f48fb8f02e1416be6a930ebfd71268caee78aa985f3af4315e457c89` | 설계 계약의 SQL Server 2022와 일치하는 고정 CU |
| ClickHouse | `26.3.17.56` | `sha256:422be85ae7344058369cdd366ac0efea9daa8428b55c9cf50258e83a7d12fcb3` | 26.3 LTS의 고정 patch |

Trino와 DataHub는 이 Compose에 설치하지 않는다. `integrations/trino/`는 Trino 483의 catalog property 형식, `integrations/datahub/`는 DataHub 1.6.0 source recipe 형식을 기준으로 작성했다. 실제 JDBC/Python driver 버전은 배포하는 Trino/DataHub distribution이 결정하므로, 해당 runtime 버전과 함께 별도로 고정해야 한다.

## 계정과 최소 권한

| DB | 관리자/애플리케이션 계정 | DataHub 계정 | Trino 계정 | 내부 role |
|---|---|---|---|---|
| app | `app_admin`, `app_migration`, `app_runtime` | 제외 | 제외 | migration은 schema 소유, runtime은 DML |
| PMS | `pms_admin` | `pms_datahub` | `pms_trino` | `pms_ingest`(NOLOGIN DML), `pms_query`(SELECT) |
| Banquet | `banquet_admin` | `banquet_datahub` | `banquet_trino` | `banquet_ingest`(NOLOGIN DML), `banquet_query`(SELECT) |
| POS | `root` | `pos_datahub` | `pos_trino` | `pos_ingest`(DML), `pos_query`(SELECT) |
| CRM | `sa` | `crm_datahub` | `crm_trino` | `crm_ingest`(DML), `crm_query`(SELECT·metadata) |
| Facility | `facility_admin` | `facility_datahub` | `facility_trino` | `facility_ingest`(DML), `facility_query`(SELECT) |

`*_ingest` role은 초기화 관리자와 분리된 향후 loader 경계이며 현재 실제 login에 연결하지 않는다. DataHub와 Trino login은 source별 `*_query` role만 받아 `SELECT`와 필요한 최소 metadata 조회만 가능하다. `INSERT`, `UPDATE`, `DELETE`, DDL은 DB 권한으로 차단하며 `scripts/verify.py`가 두 login 모두의 허용·거부 경로를 검사한다.

`app_runtime`은 Application schema의 읽기·쓰기만 가능하고 `app_migration`이 schema 변경을 소유한다. `app-postgres`는 기본 DataHub recipe와 Trino catalog 대상에서 제외한다.

## DataHub·Trino source 매핑

| 서비스 | DataHub platform instance | DataHub recipe | Trino catalog |
|---|---|---|---|
| `pms-postgres` | `pms` | `integrations/datahub/pms.yml` | `integrations/trino/pms.properties` |
| `banquet-postgres` | `banquet` | `integrations/datahub/banquet.yml` | `integrations/trino/banquet.properties` |
| `pos-mysql` | `pos` | `integrations/datahub/pos.yml` | `integrations/trino/pos.properties` |
| `crm-mssql` | `crm` | `integrations/datahub/crm.yml` | `integrations/trino/crm.properties` |
| `facility-clickhouse` | `facility` | `integrations/datahub/facility.yml` | `integrations/trino/facility.properties` |

각 recipe/catalog는 서로 다른 DB와 read-only credential을 사용한다. DataHub recipe를 실행할 때는 `DATAHUB_GMS_URL`, `DATAHUB_TOKEN`과 source별 `*_DATAHUB_PASSWORD`를 실행 환경에 주입한다. Trino는 catalog 파일을 `etc/catalog/`로 복사하고 source별 `*_TRINO_PASSWORD`를 Trino 프로세스 환경변수로 주입한다.

고급 query lineage·usage 수집은 기본적으로 꺼져 있다. 이를 켜면 PostgreSQL `pg_read_all_stats`, SQL Server Query Store/추가 server 권한, ClickHouse `system.query_log` 등 권한 범위가 커지므로 별도 보안 검토 후 opt-in한다.

## 초기화와 재현성

각 엔진의 `init/<service>/`는 다음 책임을 순서대로 분리한다. PostgreSQL과 MySQL은 `01`~`05`, SQL Server는 `10`~`99` 번호를 사용하며, ClickHouse 계정 생성은 `00-init.sh`에서 처리한다.

```text
init/<service>/
├─ 00-init.sh
└─ sql/
   ├─ <order>-schema.sql
   ├─ <order>-reference.sql
   ├─ <order>-synthetic.sql
   ├─ <order>-accounts.sql
   └─ <order>-environment-manifest.sql
```

고정 계약은 `.env`로 주입된다.

```text
schema_version   = schema-v4.6-websql
seed             = 20260728
scenario_version = scenario-v4.6
fixture_version  = source-fixture-v4.6
property_id      = SYNTHETIC_HOTEL_001
generated_at     = 2026-07-28T05:00:00Z
synthetic        = true
```

마지막 SQL이 각 DB의 `environment_manifest` view를 만든 뒤에만 healthcheck가 성공한다. PostgreSQL, MySQL, ClickHouse 공식 init hook은 빈 volume에서만 실행된다. SQL Server one-shot initializer는 idempotent하게 실행된다. schema 변경은 기존 volume에 init 파일을 다시 실행하는 방식이 아니라 migration으로 처리하거나, 개발 fixture라면 `down --volumes` 후 동일 seed로 재생성한다.

## 검증

```powershell
# config, health, read-only SELECT/쓰기 차단, app DML, source 격리 확인
python scripts/verify.py --env-file .env

# 컨테이너 재시작 전후 fingerprint와 데이터 유지 확인
python scripts/verify.py --env-file .env --restart

# volume 삭제 전후 seed/schema/row-count fingerprint 재현 확인
python scripts/verify.py --env-file .env --recreate
```

검증기는 프로젝트 밖 컨테이너나 volume을 다루지 않는다. `--recreate`는 Compose가 정의한 `hotel-datahub-databases` 프로젝트에만 `down --volumes`를 실행한다.

## 보안·라이선스 주의

- `.env`는 Git ignore 대상이다. `.env.example`에는 실제 비밀번호를 넣지 않는다.
- SQL Server `ACCEPT_EULA=Y`는 Microsoft SQL Server EULA 동의를 뜻한다. `MSSQL_PID=Developer`는 개발·테스트용이며 운영 사용 조건은 Microsoft 라이선스를 별도로 확인한다.
- SQL Server account initializer는 안전한 SQLCMD 치환을 위해 서비스 비밀번호를 영문 대소문자, 숫자와 `_!@#%^+=.,:-` 조합 12~128자로 제한한다.
- 모든 host port는 loopback 전용이다. 외부 노출이 필요하면 TLS, 방화벽, secret manager, backup, 자원 제한과 라이선스를 별도 설계한다.
- 초기 fixture ID와 데이터는 합성값이다. 실제 고객 이름, 연락처, 주소, 카드, 계정 정보는 넣지 않는다.
