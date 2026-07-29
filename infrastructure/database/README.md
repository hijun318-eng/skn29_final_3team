# Docker Compose 합성 운영 DB

5개 업무 사일로와 애플리케이션 관리 DB를 독립 컨테이너·볼륨·계정으로 실행한다. 실제 고객 데이터는 사용하지 않으며 모든 seed는 `20260729`, schema version은 `1.0.0`이다. Trino는 5개 source catalog와 내부 `serving` catalog를 사용한다.

```powershell
cd infrastructure/database
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 최초 실행 전 .env의 모든 CHANGE_ME_ 값을 로컬 전용 비밀번호로 교체
powershell -NoProfile -ExecutionPolicy Bypass -File start.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File stop.ps1
```

`reset.ps1 -Force`는 현재 로컬 Docker DB 볼륨을 삭제하고 다시 생성한다. 보존할 데이터가 없는 synthetic 개발 환경인지 확인한 뒤에만 실행한다.

최초 실행 시 POS synthetic seed 약 128만 행을 생성하므로 환경에 따라 최대 30분 정도 걸릴 수 있다. `DATABASE_STACK_READY`가 출력될 때까지 초기화 프로세스를 중단하지 않는다.

| 서비스 | 엔진 | localhost 포트 | DataHub instance | Trino catalog |
| --- | --- | ---: | --- | --- |
| app-postgres | PostgreSQL 16.13 | 15432 | 제외 | 제외 |
| pms-postgres | PostgreSQL 16.13 | 15433 | pms | pms |
| banquet-postgres | PostgreSQL 16.13 | 15434 | banquet | banquet |
| pos-mysql | MySQL 8.4.6 | 13306 | pos | pos |
| crm-mssql | SQL Server 2022 CU17 | 11433 | crm | crm |
| facility-clickhouse | ClickHouse 24.8.4.13 | 18123 / 19000 | facility | facility |
| trino | Trino 476 | 18080 | 제외 | `serving`(내부) + source 5개 |

컨테이너 간 접속은 `app-postgres`, `pms-postgres` 등 서비스명과 내부 포트를 사용한다. 모든 외부 포트는 `127.0.0.1`에만 바인딩한다.

업무 DB는 `*_READONLY_USER` 계정으로 DataHub와 Trino에 연결한다. 이 계정은 `SELECT` 및 시스템 메타데이터 조회만 허용하며 DML·DDL은 거부한다. `app-postgres`의 `APP_DB_USER`는 앱 읽기·쓰기, `APP_MIGRATION_USER`는 migration 전용이다.

실행 원본은 `sql/ddl`, `sql/data`, `sql/app`, `security`에만 둔다. `releases/`는 배포 아카이브이며 Compose 초기화 경로에서 사용하지 않는다.

이미지는 태그와 manifest digest를 함께 고정했다.

| 엔진 | 이미지 |
| --- | --- |
| PostgreSQL | `postgres:16.13-bookworm@sha256:472efd9a66f2b2f1a5aeb18b28de74332e6ef88c2b93a1a5d812fb6db67a5f60` |
| MySQL | `mysql:8.4.6@sha256:869218921e61d6c3c89820955d63cca42971f0e3e6c1e2792247bbd944ebc6e9` |
| SQL Server | `mcr.microsoft.com/mssql/server:2022-CU17-ubuntu-22.04@sha256:d252932ef839c24c61c1139cc98f69c85ca774fa7c6bfaaa0015b7eb02b9dc87` |
| ClickHouse | `clickhouse/clickhouse-server:24.8.4.13@sha256:b2c51583a6df9c19d613b579a03f237b92e0dfc63433b3fdb567ce223e0fb0f7` |

SQL Server는 `ACCEPT_EULA=Y`, `MSSQL_PID=Developer`로 개발·테스트·시연에만 사용한다. 상용 운영에는 적절한 라이선스와 edition이 필요하다. SQL Server 비밀번호는 복잡성 정책을 만족해야 한다.
