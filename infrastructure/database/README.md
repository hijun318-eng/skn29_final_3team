# Docker Compose 합성 운영 DB

5개 업무 사일로와 애플리케이션 관리 DB를 독립 컨테이너·볼륨·계정으로 실행한다. 실제 고객 데이터는 사용하지 않으며 모든 seed는 `20260729`, schema version은 `1.0.0`이다. Trino는 5개 source catalog와 내부 `serving` catalog를 사용한다.

```powershell
cd infrastructure/database
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 최초 실행 전 .env의 모든 CHANGE_ME_ 값을 로컬 전용 비밀번호로 교체
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1
```

`scripts/reset.ps1 -Force`는 현재 로컬 Docker DB 볼륨을 삭제하고 다시 생성한다. 보존할 데이터가 없는 synthetic 개발 환경인지 확인한 뒤에만 실행한다.

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

Trino는 다섯 개의 `answervice_*` profile principal과 `hotel_synthetic_setup`, `datahub_ingestion`만 query resource group에 배정하며, 그 밖의 principal은 catalog·table·query 모두 default-deny한다. Profile은 source registry에 등록된 업무 테이블과 허용된 serving view만 조회할 수 있고, 모든 분석 조회에는 synthetic 사업장 `SYNTHETIC_HOTEL_001` row filter를 Trino가 강제한다. profile별 동시 실행은 2건, queue는 4건이고 전체 애플리케이션 동시 실행은 4건으로 제한한다. 실행 시간은 2분, queue·planning을 포함한 전체 run time은 3분을 넘길 수 없다.

승인된 raw·serving Context에는 email, 전화번호, 이름, 주민·여권·결제카드 번호 같은 직접식별 컬럼이 없다. `guest_id`, `member_no` 등은 합성 내부 join 식별자로서 승인된 분석 계약에만 사용한다. 따라서 현재는 의미를 훼손하는 임의 column mask를 추가하지 않고, 직접식별 컬럼이 계약에 들어오면 Trino 조회 경계의 명시적 mask와 role별 누출 테스트를 먼저 추가한다.

실행 원본은 `sql/ddl`, `sql/data`, `sql/app`, `security`에만 둔다.

PowerShell 실행 파일은 `scripts`에 모아 관리한다.

```text
infrastructure/database/
└─ scripts/
   ├─ start.ps1
   ├─ stop.ps1
   ├─ reset.ps1
   ├─ verify.ps1
   ├─ retention-app-postgres.ps1
   ├─ backup-app-postgres.ps1
   ├─ run-app-postgres-maintenance.ps1
   ├─ install-app-postgres-maintenance-task.ps1
   └─ verify-app-postgres-restore.ps1
```

## 애플리케이션 DB 보존·백업·복구

보존 정책은 기본적으로 후보만 집계한다. `-Apply -Approval APPLY_RETENTION`을 함께 전달하면 일반 artifact payload는 30일, 승인 보고서 snapshot payload는 90일 뒤 비우고 trace 식별자는 유지한다. audit metadata는 180일 뒤 append-only archive로 옮긴다. 참조 중인 report definition, Analysis Definition, Context release/package와 실행 연결은 삭제하지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/retention-app-postgres.ps1
```

백업은 custom-format `pg_dump`를 외부 key file로 AES-256 암호화하고 SHA-256·RPO manifest를 남긴다. key file과 백업 출력 디렉터리는 Git 밖의 접근 제한 경로를 사용한다. 복구 검증은 기본적으로 `pg_restore --list`만 수행하며, 실제 복구는 운영 `app_db`가 아닌 격리 DB와 `-Approval RESTORE_TO_ISOLATED_DB`가 모두 지정된 경우에만 허용한다. 정확한 인자는 각 스크립트 상단의 parameter 선언을 확인한다.

일일 자동 작업은 암호화 백업이 성공한 뒤 retention을 dry-run으로만 수행한다. 스케줄러는 `-Apply`를 전달할 수 없으며 실제 정리는 사람이 후보를 검토하고 명시적으로 승인한 경우에만 수동 실행한다. 아래 예시는 매일 오전 2시에 Windows 작업을 등록하며, evidence 경로를 `RECOVERY_EVIDENCE_HOST_DIR`와 같게 지정하면 운영 감사 화면에 상태가 반영된다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-app-postgres-maintenance-task.ps1 `
  -BackupDirectory D:\answervice-backups `
  -EncryptionKeyFile C:\secure\answervice-backup.key `
  -EvidenceDirectory C:\answervice\recovery-evidence `
  -At 02:00
```

이미지는 태그와 manifest digest를 함께 고정했다.

| 엔진 | 이미지 |
| --- | --- |
| PostgreSQL | `postgres:16.13-bookworm@sha256:472efd9a66f2b2f1a5aeb18b28de74332e6ef88c2b93a1a5d812fb6db67a5f60` |
| MySQL | `mysql:8.4.6@sha256:869218921e61d6c3c89820955d63cca42971f0e3e6c1e2792247bbd944ebc6e9` |
| SQL Server | `mcr.microsoft.com/mssql/server:2022-CU17-ubuntu-22.04@sha256:d252932ef839c24c61c1139cc98f69c85ca774fa7c6bfaaa0015b7eb02b9dc87` |
| ClickHouse | `clickhouse/clickhouse-server:24.8.4.13@sha256:b2c51583a6df9c19d613b579a03f237b92e0dfc63433b3fdb567ce223e0fb0f7` |

SQL Server는 `ACCEPT_EULA=Y`, `MSSQL_PID=Developer`로 개발·테스트·시연에만 사용한다. 상용 운영에는 적절한 라이선스와 edition이 필요하다. SQL Server 비밀번호는 복잡성 정책을 만족해야 한다.
