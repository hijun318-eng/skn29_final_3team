# Docker Compose 합성 운영 DB

DataHub의 선택적 Elasticsearch 8.18 + 로컬 Ollama semantic-search 구성과 실제
검증 절차는 [`datahub/SEMANTIC_SEARCH.md`](datahub/SEMANTIC_SEARCH.md)를 따른다.
기본 OpenSearch 구성은 semantic-search 완료 증거로 취급하지 않는다.

5개 업무 사일로와 애플리케이션 관리 DB를 독립 컨테이너·볼륨·계정으로 실행한다.
초기화는 재현 가능한 DDL과 migration만 적용하고 업무 row, 특정 기간 snapshot,
질문 전용 serving view는 넣지 않는다. Trino는 5개 source catalog와 내부 `serving`
catalog를 노출하지만, 실제 relation은 `information_schema`에서 런타임에 발견한다.
`serving`은 Polaris REST catalog, PostgreSQL metastore, S3-compatible object storage에
View metadata를 영속화하므로 Trino 재시작 후 복구용 View 재생성이 필요하지 않다.

```powershell
cd infrastructure/database
$secretDirectory = Join-Path $env:LOCALAPPDATA 'Answervice\secrets'
New-Item -ItemType Directory -Force -Path $secretDirectory | Out-Null
Copy-Item .env.example .env
# Git에서 제외된 .env의 CHANGE_ME_/REQUIRED_ 값을 교체하고 TLS PKI 파일의 절대 경로를 설정한다.
powershell -NoProfile -ExecutionPolicy Bypass `
  -File security/provision-trino-password-database.ps1 `
  -PasswordDatabasePath (Join-Path $secretDirectory 'trino-password.db')
powershell -NoProfile -ExecutionPolicy Bypass `
  -File security/provision-serving-catalog-secrets.ps1 `
  -CredentialsPath (Join-Path $secretDirectory 'serving-catalog-bootstrap.json') `
  -TokenPublicKeyPath (Join-Path $secretDirectory 'serving-catalog-token-public.pem') `
  -TokenPrivateKeyPath (Join-Path $secretDirectory 'serving-catalog-token-private.pem')
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/start.ps1 -Stage Core
Push-Location ../..
docker compose --env-file infrastructure/database/.env --profile dev `
  run --rm app-migrations upgrade head
powershell -NoProfile -ExecutionPolicy Bypass `
  -File infrastructure/database/security/provision-release-principals.ps1
Pop-Location
# loopback DataHub UI/OIDC에서 서로 다른 read/publish service actor와 PAT를 발급하고,
# 최소권한 정책과 actor URN/token을 .env에 기록한다.
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/start.ps1 -Stage Catalog
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1
```

Core 기동은 object store와 Polaris를 먼저 준비하고, management API에서 Trino 전용
principal·role·grant를 멱등 구성해 exact read-back한 뒤 Trino를 만든다. bootstrap admin
credential을 Trino에 재사용하지 않는다. 저장소 로컬 `.env`와 secret은 개발 중에만
사용하며 `.env`는 반드시 `.gitignore` 대상이어야 한다. 외부 dotenv는 허용하지 않는다.

App의 사람 Role은 `analyst`, `admin` 두 개뿐이다. `provision-release-principals.ps1`은
두 bootstrap verifier를 migration이 만든 `security.accounts`에 upsert하고, 같은 username의
기존 subject를 보존하며 해당 subject의 session을 폐기한다. `.env`를 직접 바꾸는 것만으로
DB verifier가 변경되지는 않으므로 비밀번호·로그인 ID 변경 뒤 script를 명시적으로 다시
실행한다. 이 통합 bootstrap은 두 계정 verifier를 함께 갱신하고 두 계정의 기존 session을
폐기한다. admin 한 계정만 회전하는 작업은 로그인 후 관리자 API로 수행하며, 과거
별도 로컬 진입점이나 제3의 사람 계정은 제공하지 않는다.

기존 principal JSON을 사용하던 환경의 첫 이관은 검증된 절대 경로를
`-LegacyPrincipalPath`로 명시한다. 두 bootstrap username이 모두 있어야 하며 그 subject를
신규 DB INSERT 후보로 사용한다. 이미 같은 username의 DB 계정이 있으면 DB subject를
변경하지 않는다. 로그인·Analysis/Report 소유권을 확인한 뒤 JSON mount와 파일을 운영
경로에서 제거하고 이후 회전에는 이 인자를 사용하지 않는다.

로컬의 구 관리자 key를 전환할 때는 migration 뒤 `-LegacyPrincipalPath`와
`-AdminUsername admin -PromptAdminPassword`를 함께 사용한다. secure prompt 입력은 argv와
log에 남지 않고, 성공 시 폐기된 Role 선택·관리자 dotenv key도 `.env`에서 제거된다.

### 운영 중 release의 maintenance 전환 순서

구 Backend가 실행되는 동안 새 migration을 적용하면 폐기된 Role로 session을 다시 쓰려는
요청이 DB 제약에 막혀 로그인 503을 만들 수 있다. 따라서 트래픽 차단과 구 Backend·Frontend
중지를 먼저 완료하고 old/new Backend가 동시에 실행되지 않게 한다. App PostgreSQL과
DataHub를 유지한 maintenance 상태에서 아래 순서를 고정한다.

1. `app-migrations upgrade head`
2. one-time `-LegacyPrincipalPath`를 포함한 두 DB 계정 provision과 subject 보존 확인
3. DataHub 새 Role 정책의 read-only check, checksum 고정 publish, 전체 live read-back
4. 새 Backend·Frontend 시작, readiness와 analyst/admin 로그인·권한·기존 소유권 검증
5. 검증 성공 뒤에만 트래픽 재개

migration과 provision 사이에는 인증 트래픽을 받지 않는다. DB 또는 DataHub 검증이
실패하면 새 Backend를 시작하지 않고 maintenance를 유지하며 검증된 predecessor/DB 복구
절차를 따른다. 영구적인 legacy Role alias나 구 Backend 재기동으로 중간 상태를 운영하지
않는다.

## DataHub entitlement Role 전환

live DataHub의 Dataset·Metric entitlement도 App Role과 같은 `analyst`, `admin` 집합을
사용해야 한다. 과거 Role 문자열을 runtime alias로 허용하거나 로컬 JSON으로 덮어쓰지
않는다. 승인된 live release를 `datahub/migrate_semantic_policy.py`로 읽어
`--role analyst --role admin`인 다음 version 정책을 만들고,
[`datahub/SEMANTIC_AUTHORING.md`](datahub/SEMANTIC_AUTHORING.md)의 read-only `--check` →
predecessor/target checksum을 명시한 `--publish` → 전체 live read-back 순서로 전환한다.
`PUBLISHED_AND_VERIFIED` 뒤 Backend를 재시작하고 두 Role의 실제 분석 경로를 확인하기
전에는 새 entitlement release를 활성 상태로 선언하지 않는다.

## D0/D1 release 검증과 영속 serving 발행

현재 source row를 다시 생성하지 않는 읽기 전용 D0 검증과 영속 catalog의 D1 View
발행·검증은 release id와 저장소 `.env`를 사용해 실행한다. verifier는 release manifest
전체 checksum을 먼저 확인하며 evidence 경로에는 SQL 원문이나 credential 대신 file/query
hash와 실행시간만 기록한다.

```powershell
$releaseId = 'walkerhill-v4.3-sql-20260815-derived.1'
$evidence = Join-Path $PWD 'output\d0-d1\<base-sha>'

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/verify-release-sources.ps1 `
  -ReleaseId $releaseId -EvidenceDirectory $evidence

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/recreate-serving-views.ps1 `
  -ReleaseId $releaseId -IncludeValidation

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/verify-release-trino.ps1 `
  -ReleaseId $releaseId -EvidenceDirectory $evidence
```

`recreate-serving-views.ps1`은 파일명 목록을 복제하지 않는다. manifest와 SQL metadata/AST에서
실행 순서와 정확한 View identity를 구하고 live read-back을 exact 비교한다. 재시작에는
재발행이 필요 없으며, 새 release 발행이나 명시적 repair에 같은 멱등 명령을 사용한다.
최초 publish 전 collision 검사를 포함한 preflight는 이미 schema가 존재할 수 있는 멱등
발행과 다른 계약이므로 자동 재실행하지 않는다.
발행은 원본 release를 수정하거나 문자열 치환하지 않는다. SQLGlot AST로 namespace를
검증하고, Iceberg가 표현하지 못하는 원천 타입만 `trino/etc/iceberg-view-coercions.json`의
versioned 계약에 따라 무손실 widening한다. 계약 열이 SQL output과 정확히 하나로 일치하지
않으면 발행을 중단한다.

`verify-release-sources.ps1`의 파일별 시간은 현재 데이터에 대한 validation 실행시간이지
최초 적재시간이 아니다. 불변 archive의 `run-v43.ps1`은 과거 container 이름과 무인증
Trino 경로를 전제로 하므로 현재 runtime 재적재에 사용하지 않는다. 파일별 실제 적재시간을
새로 만들려면 운영 볼륨을 건드리지 않는 빈 disposable 환경에서 release 전체를 replay하고
그 receipt를 별도로 고정해야 한다.

dotenv는 Git에서 제외된 `infrastructure/database/.env` 하나만 사용한다. Trino password
database, Trino/DataHub PKCS#12 server keystore, DataHub Java truststore와 CA PEM은
repository 밖 절대 경로에 둔다. 사람 계정의 권위 원본은 App PostgreSQL이며 별도
principal JSON을 mount하지 않는다. Trino
인증서는 container DNS `trino`, DataHub 인증서는 `datahub-gms`, host 접속 주소를 각각
SAN으로 포함해야 한다. deployment script는 고정된 저장소 `.env`가 없거나 Git ignore
대상이 아니면 중단하며 외부 dotenv나 현재 process environment로 fallback하지 않는다.

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
| serving-catalog-postgres | PostgreSQL 16.13 | 미공개 | 제외 | Polaris metadata store |
| serving-object-store | RustFS 1.0.0-beta.8 | 미공개 | 제외 | Iceberg metadata object store |
| serving-catalog | Apache Polaris 1.7.0 | 18181 (loopback) | 제외 | `serving` REST catalog |
| trino | Trino 483 | 18443 (HTTPS) | 제외 | `serving` + source 5개 |

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
`security` script는 기계 계정 secret과 App DB bootstrap verifier를 분리하며 저장소 안에
사람 인증 JSON을 만들지 않는다. `sql/data/`와 `releases/`는 checksum과 과거 재현성을 위한 불변 아카이브이며,
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
| Trino | `trinodb/trino:483@sha256:db58cc93e593a2706553745f276bb119c9810e69918be56ecde088ba7ccb0534` |
| Apache Polaris | `apache/polaris:1.7.0@sha256:3495f67f38cca33892a045f7dd3f46eb52387f0fd52d4145538a772fd8aedad7` |
| Polaris admin tool | `apache/polaris-admin-tool:1.7.0@sha256:3d8a24cea57aef3b71a0d7b09e5d2278d01e7e1b30071bf6648f2a6953322cca` |
| RustFS | `rustfs/rustfs:1.0.0-beta.8@sha256:fa19210ac4697c79d7ccca1ec9b0eb91aebacc6691991ffb14014bb3c67e6cc3` |

SQL Server는 `ACCEPT_EULA=Y`, `MSSQL_PID=Developer`로 개발·테스트·시연에만 사용한다. 상용 운영에는 적절한 라이선스와 edition이 필요하다. SQL Server 비밀번호는 복잡성 정책을 만족해야 한다.
