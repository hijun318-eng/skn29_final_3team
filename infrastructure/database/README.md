# Docker Compose 합성 운영 DB

5개 업무 사일로와 애플리케이션 관리 DB를 독립 컨테이너·볼륨·계정으로 실행한다. 실제 고객 데이터는 사용하지 않으며 모든 seed는 `20260729`, schema version은 `1.0.0`이다.

```powershell
cd infrastructure/database
Copy-Item .env.example .env
# .env의 CHANGE_ME 비밀번호를 교체
.\start.ps1
.\verify.ps1
.\stop.ps1
.\reset.ps1 -Force
```

| 서비스 | 엔진 | localhost 포트 | DataHub instance | Trino catalog |
| --- | --- | ---: | --- | --- |
| app-postgres | PostgreSQL 16.13 | 15432 | 제외 | 제외 |
| pms-postgres | PostgreSQL 16.13 | 15433 | pms | pms |
| banquet-postgres | PostgreSQL 16.13 | 15434 | banquet | banquet |
| pos-mysql | MySQL 8.4.6 | 13306 | pos | pos |
| crm-mssql | SQL Server 2022 CU17 | 11433 | crm | crm |
| facility-clickhouse | ClickHouse 24.8.4.13 | 18123 / 19000 | facility | facility |

컨테이너 간 접속은 `app-postgres`, `pms-postgres` 등 서비스명과 내부 포트를 사용한다. 모든 외부 포트는 `127.0.0.1`에만 바인딩한다.

업무 DB는 `*_READONLY_USER` 계정으로 DataHub와 Trino에 연결한다. 이 계정은 `SELECT` 및 시스템 메타데이터 조회만 허용하며 DML·DDL은 거부한다. `app-postgres`의 `APP_DB_USER`는 앱 읽기·쓰기, `APP_MIGRATION_USER`는 migration 전용이다.

이미지는 `postgres:16.13-bookworm`, `mysql:8.4.6`, `mcr.microsoft.com/mssql/server:2022-CU17-ubuntu-22.04`, `clickhouse/clickhouse-server:24.8.4.13`으로 고정했다. 배포 시 `docker image inspect --format '{{index .RepoDigests 0}}' <image>`로 실제 digest를 릴리스 기록에 남긴다.

SQL Server는 `ACCEPT_EULA=Y`, `MSSQL_PID=Developer`로 개발·테스트·시연에만 사용한다. 상용 운영에는 적절한 라이선스와 edition이 필요하다. SQL Server 비밀번호는 복잡성 정책을 만족해야 한다.
