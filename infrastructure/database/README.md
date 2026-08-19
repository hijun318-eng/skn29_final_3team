# Docker Compose 합성 운영 DB

DataHub의 선택적 Elasticsearch 8.18 + 로컬 Ollama semantic-search 구성과 실제
검증 절차는 [`datahub/SEMANTIC_SEARCH.md`](datahub/SEMANTIC_SEARCH.md)를 따른다.
기본 OpenSearch 구성은 semantic-search 완료 증거로 취급하지 않는다.

5개 업무 사일로와 애플리케이션 관리 DB를 독립 컨테이너·볼륨·계정으로 실행한다.
초기화는 재현 가능한 DDL과 migration만 적용하고 업무 row, 특정 기간 snapshot,
질문 전용 serving view는 넣지 않는다. Trino는 5개 source catalog와 내부 `serving`
catalog를 노출하지만, 실제 relation은 `information_schema`에서 런타임에 발견한다.

```powershell
cd infrastructure/database
$deploymentDirectory = Join-Path $env:LOCALAPPDATA 'Answervice\deployment'
$secretDirectory = Join-Path $env:LOCALAPPDATA 'Answervice\secrets'
New-Item -ItemType Directory -Force -Path $deploymentDirectory,$secretDirectory | Out-Null
$deploymentEnv = Join-Path $deploymentDirectory 'answervice.env'
Copy-Item .env.example $deploymentEnv
# $deploymentEnv의 CHANGE_ME_/REQUIRED_ 값을 교체하고 TLS PKI 파일의 절대 경로를 설정한다.
powershell -NoProfile -ExecutionPolicy Bypass `
  -File security/provision-release-principals.ps1 `
  -EnvPath $deploymentEnv `
  -PrincipalPath (Join-Path $secretDirectory 'principals.json')
powershell -NoProfile -ExecutionPolicy Bypass `
  -File security/provision-trino-password-database.ps1 `
  -EnvPath $deploymentEnv `
  -PasswordDatabasePath (Join-Path $secretDirectory 'trino-password.db')
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/start.ps1 -EnvFilePath $deploymentEnv -Stage Core
# loopback DataHub UI/OIDC에서 서로 다른 read/publish service actor와 PAT를 발급하고,
# 최소권한 정책과 actor URN/token을 외부 $deploymentEnv에 기록한다.
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/start.ps1 -EnvFilePath $deploymentEnv -Stage Catalog
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1 -EnvFilePath $deploymentEnv
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1 -EnvFilePath $deploymentEnv
```

## D0/D1 release 검증과 Trino View 복구

현재 source row를 다시 생성하지 않는 읽기 전용 D0 검증과 memory connector의 D1 View
복구는 release id와 외부 deployment env를 명시해 실행한다. verifier는 release manifest
전체 checksum을 먼저 확인하며 evidence 경로에는 SQL 원문이나 credential 대신 file/query
hash와 실행시간만 기록한다.

```powershell
$releaseId = 'walkerhill-v4.3-sql-20260815-derived.1'
$evidence = Join-Path $PWD 'output\d0-d1\<base-sha>'

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/verify-release-sources.ps1 `
  -EnvFilePath $deploymentEnv -ReleaseId $releaseId -EvidenceDirectory $evidence

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/recreate-serving-views.ps1 `
  -EnvFilePath $deploymentEnv -ReleaseId $releaseId -IncludeValidation

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/verify-release-trino.ps1 `
  -EnvFilePath $deploymentEnv -ReleaseId $releaseId -EvidenceDirectory $evidence
```

`recreate-serving-views.ps1`은 파일명 목록을 복제하지 않는다. manifest와 SQL metadata/AST에서
실행 순서와 정확한 View identity를 구하고 live read-back을 exact 비교하므로 Trino 재시작
후에도 같은 명령을 사용한다. 최초 publish 전 collision 검사를 포함한 preflight는 이미
schema가 존재할 수 있는 멱등 recovery와 다른 계약이므로 자동 재실행하지 않는다.

`verify-release-sources.ps1`의 파일별 시간은 현재 데이터에 대한 validation 실행시간이지
최초 적재시간이 아니다. 불변 archive의 `run-v43.ps1`은 과거 container 이름과 무인증
Trino 경로를 전제로 하므로 현재 runtime 재적재에 사용하지 않는다. 파일별 실제 적재시간을
새로 만들려면 운영 볼륨을 건드리지 않는 빈 disposable 환경에서 release 전체를 replay하고
그 receipt를 별도로 고정해야 한다.

배포 환경 파일, Trino password database, Trino/DataHub PKCS#12 server keystore,
DataHub Java truststore, CA PEM과 Backend principal store는 모두 repository 밖 절대
경로에 둔다. Trino 인증서는 container DNS `trino`, DataHub 인증서는 `datahub-gms`,
host 접속 주소를 각각 SAN으로 포함해야 한다. script는 저장소 로컬 `.env`를 묵시적으로
읽거나 만들지 않으며 secret을 생성하지 않는다. `-EnvFilePath`를 생략하면 현재 process
environment만 사용한다.

`scripts/reset.ps1 -Force`는 Compose project label로 확인한 현재 로컬 DB 볼륨만
삭제하고 schema부터 다시 생성한다. 보존할 데이터가 없는 개발 환경인지 확인한 뒤에만
실행한다.

`DATABASE_STACK_READY`는 DB·Trino·DataHub 프로세스와 read-only 계정이 준비됐다는
뜻이다. 분석 데이터 readiness를 뜻하지 않는다. 승인된 source relation을 준비한 뒤
`datahub/ingest_runtime_catalog.ps1 -Apply`를 실행하고 `scripts/verify.ps1`의 live
discovery 검증을 통과해야 한다.

| 서비스 | 엔진 | localhost 포트 | DataHub instance | Trino catalog |
| --- | --- | ---: | --- | --- |
| app-postgres | PostgreSQL 16.13 | 15432 | 제외 | 제외 |
| pms-postgres | PostgreSQL 16.13 | 15433 | pms | pms |
| banquet-postgres | PostgreSQL 16.13 | 15434 | banquet | banquet |
| pos-mysql | MySQL 8.4.6 | 13306 | pos | pos |
| crm-mssql | SQL Server 2022 CU17 | 11433 | crm | crm |
| facility-clickhouse | ClickHouse 24.8.4.13 | 18123 / 19000 | facility | facility |
| trino | Trino 476 | 18443 (HTTPS) | 제외 | `serving`(내부) + source 5개 |

컨테이너 간 접속은 `app-postgres`, `pms-postgres` 등 서비스명과 내부 포트를 사용한다.
모든 외부 포트는 `127.0.0.1`에만 바인딩한다. Trino의 8080 listener는 shared-secret으로
인증되는 coordinator 내부 discovery 전용이며 host에는 publish하지 않는다. client query는
CA 검증·Basic authentication을 거친 8443/18443 HTTPS 경로만 허용한다.
DataHub GMS도 8443/18081 HTTPS와 Bearer authentication만 허용하며 UI 9002/19002는
loopback에만 publish한다. `/health` 같은 DataHub 공식 인증 예외는 readiness에만 쓰고,
catalog read는 `DATAHUB_READ_API_TOKEN`, ingestion·authoring·semantic mutation은 별도
`DATAHUB_PUBLISH_API_TOKEN`을 전송한다. 두 PAT의 actor도 달라야 하며 Backend에는
publish credential을 주입하지 않는다.

업무 DB는 `*_READONLY_USER` 계정으로 DataHub와 Trino에 연결한다. 이 계정은 `SELECT` 및 시스템 메타데이터 조회만 허용하며 DML·DDL은 거부한다. `app-postgres`의 `APP_DB_USER`는 앱 읽기·쓰기, `APP_MIGRATION_USER`는 migration 전용이다.

실행 원본은 `sql/ddl`, `sql/app`, App DB migration, DataHub runtime recipe다.
`security` script는 외부 principal secret을 생성하지만 저장소 안에 인증 JSON을 만들지
않는다. `sql/data/`와 `releases/`는 checksum과 과거 재현성을 위한 불변 아카이브이며,
Compose 초기화·bootstrap·검증 경로에서 참조하지 않는다.

PowerShell 실행 파일은 `scripts`에 모아 관리한다.

```text
infrastructure/database/
└─ scripts/
   ├─ start.ps1
   ├─ stop.ps1
   ├─ reset.ps1
   └─ verify.ps1
```

이미지는 태그와 manifest digest를 함께 고정했다.

| 엔진 | 이미지 |
| --- | --- |
| PostgreSQL | `postgres:16.13-bookworm@sha256:472efd9a66f2b2f1a5aeb18b28de74332e6ef88c2b93a1a5d812fb6db67a5f60` |
| MySQL | `mysql:8.4.6@sha256:869218921e61d6c3c89820955d63cca42971f0e3e6c1e2792247bbd944ebc6e9` |
| SQL Server | `mcr.microsoft.com/mssql/server:2022-CU17-ubuntu-22.04@sha256:d252932ef839c24c61c1139cc98f69c85ca774fa7c6bfaaa0015b7eb02b9dc87` |
| ClickHouse | `clickhouse/clickhouse-server:24.8.4.13@sha256:b2c51583a6df9c19d613b579a03f237b92e0dfc63433b3fdb567ce223e0fb0f7` |

SQL Server는 `ACCEPT_EULA=Y`, `MSSQL_PID=Developer`로 개발·테스트·시연에만 사용한다. 상용 운영에는 적절한 라이선스와 edition이 필요하다. SQL Server 비밀번호는 복잡성 정책을 만족해야 한다.
