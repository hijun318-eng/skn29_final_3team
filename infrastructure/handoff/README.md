# Answervice 팀 환경 통일 및 전달 가이드

이 디렉터리는 최종 커밋을 팀원이 같은 코드·설정으로 실행하도록 전달 묶음을 만드는
절차를 정의한다. 제품 계약의 권위 원본은 현재 Git commit과 Compose·startup script이며,
이 문서와 충돌하면 코드가 우선이다.

## 1. 지원하는 동일성 수준

| 모드 | 보장 대상 | 포함하지 않는 것 |
| --- | --- | --- |
| `Fresh` | 같은 Git SHA, deployment env, secret 파일, Compose 구성 | 현재 DB row, DataHub·Polaris 상태, object store 객체 |
| `Snapshot` | `Fresh` 항목과 검증된 native backup 입력 | Kafka transport 상태, 재생성 가능한 검색 index·Ollama cache |

`Fresh`는 같은 코드와 빈 초기 환경을 만드는 모드다. 새 DataHub DB에서는 기존 PAT가
유효하다고 간주하지 않으며 Core 기동 뒤 read/publish service actor와 PAT를 새로 발급한다.

`Snapshot`은 현재 데이터까지 맞추는 모드다. 여러 엔진 사이의 동일 시점은 각 엔진의
dump 기능만으로 자동 보장되지 않으므로 writer를 멈춘 하나의 quiescence 구간에서 만들어진
`snapshot-receipt.json`만 입력으로 허용한다.

## 2. 현재 확인된 실행 경계

- 기본 startup은 lexical DataHub 경로다. `start.ps1`은 semantic overlay를 자동으로
  결합하지 않는다.
- `start.ps1 -Stage Core`와 `-Stage Catalog`는 인프라 경로다. Backend·Frontend까지
  포함하는 검증된 단일 turnkey wrapper는 아직 없다.
- `stop.ps1`은 database Compose만 대상으로 하며 전체 서비스 종료 명령이 아니다.
- root Compose와 database Compose는 App DB port override가 다르다. 서로 다른 Compose
  조합을 같은 project에 반복 적용한 상태를 전달 기준으로 삼지 않는다.
- 2026-08-17 Docker 정상화 작업안은 폐기되어 저장소에서 제거했으며 현재 팀 설치
  명령의 권위 원본이 아니다.
- `docs/e2e_mvp/LOCAL_SETUP.md`의 repo-local env와 과거 port 절차는 현재 startup 계약으로
  사용하지 않는다.

따라서 최종 전달 직전에는 `answervice` project만 전달 대상으로 확정하고 acceptance용
`answervice-phase2b-datahub` project와 과거 컨테이너를 snapshot에 섞지 않는다.

## 3. 전달물

소스는 압축 복사하지 않고 push된 exact Git SHA로 전달한다. 별도 전달 묶음에는 다음만
넣는다.

1. `public/AI_SETUP_AGENT.md`
2. `public/HANDOFF.md`
3. `public/release-manifest.json`
4. `public/checksums.sha256`
5. `private/answervice.env.template`
6. `private/secrets/`의 10개 host-file entry
7. `Snapshot`이면 `private/state/`의 native backup과 receipt
8. `private/private-checksums.sha256`

현재 10개 host-file key 중 Trino CA와 DataHub CA가 같은 파일을 참조하므로 unique source는
9개다. 묶음에서는 수신자 경로 재작성을 단순하게 하기 위해 두 CA entry를 별도 이름으로
복사한다.

```text
TRINO_PASSWORD_DB_HOST_FILE
TRINO_TLS_KEYSTORE_HOST_FILE
TRINO_TLS_CA_HOST_FILE
DATAHUB_TLS_KEYSTORE_HOST_FILE
DATAHUB_TLS_TRUSTSTORE_HOST_FILE
DATAHUB_TLS_CA_HOST_FILE
AUTH_PRINCIPALS_HOST_FILE
SERVING_CATALOG_BOOTSTRAP_CREDENTIALS_HOST_FILE
SERVING_CATALOG_TOKEN_PUBLIC_KEY_HOST_FILE
SERVING_CATALOG_TOKEN_PRIVATE_KEY_HOST_FILE
```

`private/`에는 API key, password, principal hash, private key, 업무 데이터가 포함될 수 있다.
Git, 메신저 공개 채널, 일반 이메일에 올리지 않고 승인된 암호화 채널로 전달한다. 전달이
끝나면 sender·receiver의 임시 bundle을 삭제하고 공유 credential의 회전 여부를 결정한다.

팀원은 `public/AI_SETUP_AGENT.md` 한 파일만 로컬 terminal과 filesystem에 접근 가능한 AI
coding agent에 첨부해 설치를 맡길 수 있다. 이 파일은 public 문서이지만 AI가 접근할 실제
bundle은 로컬에 있어야 한다. `.env`, `private/`, dump를 채팅에 첨부하지 않는다.

## 4. 발신자 절차

### 4.1 최종 release 고정

아래 조건을 먼저 만족해야 collector가 실행된다.

1. 작업 완료 후 commit과 push를 마친다.
2. `git fetch` 뒤 working tree가 clean인지 확인한다.
3. 현재 HEAD, upstream tracking SHA, remote branch SHA가 모두 같아야 한다.
4. 최종 앱 이미지를 다시 build하고 현재 source와 같은 release인지 확인한다.
5. `docker compose --env-file <env> --profile full config --quiet`가 성공해야 한다.

Backend Python dependency와 Frontend base image가 모두 immutable하게 고정된 상태는 아니다.
완전히 같은 image byte가 필요하면 최종 Backend·Migration·Frontend image를 별도 registry의
immutable digest로 게시하거나 `docker image save` artifact를 snapshot receipt에 추가한다.
`docker image save`는 DB와 Docker volume을 포함하지 않는다.

### 4.2 읽기 전용 사전점검

운영 기본값은 저장소 밖 env와 secret이다. 현재처럼 gitignored repo-local 개발 secret을
수집해야 할 때만 `-AllowRepositoryLocalDevelopment`를 명시한다.

```powershell
$repo = 'C:\path\to\skn29_final_3team'
$envFile = 'C:\private\answervice.env'

powershell -NoProfile -ExecutionPolicy Bypass `
  -File "$repo\infrastructure\handoff\New-HandoffBundle.ps1" `
  -Mode Fresh -EnvFilePath $envFile -PreflightOnly
```

사전점검은 파일을 만들거나 Docker 상태를 바꾸지 않는다. 현재 저장소가 dirty하면 의도적으로
실패하며 변경 파일명이나 secret 값은 출력하지 않는다.

### 4.3 Fresh 묶음 생성

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File "$repo\infrastructure\handoff\New-HandoffBundle.ps1" `
  -Mode Fresh `
  -EnvFilePath $envFile `
  -OutputRoot 'D:\answervice-handoff' `
  -AcknowledgePlaintextSecrets
```

output은 저장소 밖에만 생성되며 기존 디렉터리를 덮어쓰지 않는다.

### 4.4 Snapshot 입력 계약

현재 저장소에는 검증 완료된 backup/restore wrapper가 없다. 최종 작업 완료 시 다음 native
artifact를 writer가 멈춘 같은 구간에서 생성하고 clean restore rehearsal을 통과시킨 뒤
`snapshot-receipt.json`을 확정한다.

| 경로 예시 | 대상 | 권장 형식 |
| --- | --- | --- |
| `databases/postgres/app_db.pg16.dump` | App PostgreSQL | `pg_dump -Fc` |
| `databases/postgres/pms_db.pg16.dump` | PMS PostgreSQL | `pg_dump -Fc` |
| `databases/postgres/banquet_db.pg16.dump` | Banquet PostgreSQL | `pg_dump -Fc` |
| `databases/postgres/serving_catalog.pg16.dump` | Polaris PostgreSQL | `pg_dump -Fc` |
| `databases/mysql/pos.mysql8.4.sql.zst` | POS MySQL 전체 업무 DB | logical dump |
| `databases/mysql/datahub.mysql8.2.sql.zst` | DataHub MySQL·PAT·policy | logical dump |
| `databases/mssql/crm_db.sqlserver2022.bak` | CRM SQL Server | native `.bak` |
| `databases/clickhouse/facility-clickhouse24.8.zip` | ClickHouse `facility`·`walkerhill_v4_3` | native backup |
| `object-store/answervice-serving/` | Serving object store | S3 API export + inventory |

Kafka는 새 cluster에서 재생성하고, OpenSearch·Elasticsearch index는 DataHub 원본 상태에서
재구축하는 것이 기본 계약이다. usage/profile 같은 time-series 상태까지 동일해야 하면 해당
검색엔진의 native snapshot을 별도 artifact로 추가한다. Ollama volume은 전달하지 않고 model
이름과 full digest를 receipt에 기록해 다시 pull한다.

엔진별 실제 dump·restore 명령을 확정할 때는
[DataHub Backup & Restore](https://docs.datahub.com/docs/how/backup-datahub),
[DataHub RestoreIndices](https://docs.datahub.com/docs/how/restore-indices),
[ClickHouse Backup/Restore](https://clickhouse.com/docs/concepts/features/backup-restore/overview)의
공식 절차와 현재 고정 image version을 함께 확인한다.

Snapshot 전에는 적어도 Backend/report scheduler, DataHub GMS·Actions·ingestion,
semantic publisher, Polaris/object writer를 멈추고 진행 중 migration·DDL이 없는지 확인한다.
`docker compose down -v`, `docker system prune`, `docker volume prune`는 사용하지 않는다.

receipt는 아래 최소 형식을 따른다. collector는 receipt의 Git SHA, `quiesced=true`, artifact
상대경로와 실제 파일 존재만 검증한다. native backup 자체의 유효성은 각 엔진 검증과 clean
restore rehearsal receipt로 입증해야 한다.

```json
{
  "schemaVersion": 1,
  "sourceCommit": "REPLACE_WITH_FULL_GIT_SHA",
  "createdAtUtc": "2026-08-23T00:00:00Z",
  "composeProject": "answervice",
  "quiescenceId": "REPLACE_WITH_SINGLE_FREEZE_ID",
  "quiesced": true,
  "nativeVerificationPassed": true,
  "cleanRestoreRehearsalPassed": true,
  "artifacts": [
    {
      "kind": "postgresql",
      "service": "app-postgres",
      "relativePath": "databases/postgres/app_db.pg16.dump"
    }
  ],
  "rebuildRequired": [
    "kafka-broker",
    "opensearch-or-semantic-elasticsearch",
    "ollama-model-cache"
  ]
}
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File "$repo\infrastructure\handoff\New-HandoffBundle.ps1" `
  -Mode Snapshot `
  -EnvFilePath $envFile `
  -SnapshotInputRoot 'D:\answervice-private\snapshot-staging' `
  -OutputRoot 'D:\answervice-handoff' `
  -AcknowledgePlaintextSecrets
```

## 5. 수신자 절차

### 5.1 코드와 private 설정 설치

```powershell
git clone https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team
git checkout <release-manifest.json의 sourceCommit>

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\infrastructure\handoff\Install-HandoffConfig.ps1 `
  -BundleDirectory 'D:\received\answervice-<sha>-<time>-fresh' `
  -RepositoryPath (Get-Location).Path
```

installer는 checksum과 exact Git SHA를 확인하고 기본적으로
`%LOCALAPPDATA%\Answervice\deployment\answervice.env` 및
`%LOCALAPPDATA%\Answervice\secrets`에 private 파일을 설치한다. 기존 파일을 덮어쓰지 않고
Docker나 DB를 시작하지 않는다.

### 5.2 Fresh 기동

1. 설치된 env 경로를 사용해 `start.ps1 -Stage Core`를 실행한다.
2. 새 DataHub에서 서로 다른 read/publish service actor와 PAT를 발급하고 env의 네 값을
   갱신한다.
3. `start.ps1 -Stage Catalog`를 실행한다.
4. App migration, Backend, Frontend는 최종 release에서 검증한 exact Compose 명령으로
   기동한다.
5. `verify.ps1`은 DB·Trino 계약만 검증한다. 전체 완료 판정에는 DataHub actor/PAT와 catalog
   readback, Backend `/readiness`, Frontend smoke를 추가한다.

현재 코드에는 앱까지 포함한 단일 검증 wrapper가 없으므로 이 문서에서 임의의 한 줄
turnkey 명령을 성공 경로로 선언하지 않는다. 최종 전달 시 실제 clean restore rehearsal에서
사용한 명령과 receipt를 bundle의 `HANDOFF.md`에 추가한다.

### 5.3 Snapshot 복원

1. 빈 storage service를 exact image version으로 준비한다.
2. source/App DB와 serving object store를 native 도구로 복원한다.
3. Polaris DB와 object store의 일치 여부와 principal을 read back한다.
4. DataHub MySQL을 복원하고 기존 signing·encryption env와 함께 기동한다.
5. Kafka와 검색 backend를 새로 만들고 DataHub index를 재생성한다.
6. 필요 시 Ollama model을 full digest로 확인한 뒤 semantic publication을 다시 수행한다.
7. App migration과 권한 provisioning 후 Trino, Backend, Frontend를 순서대로 검증한다.

restore는 기존 volume에 덮어쓰지 않는다. 새 Compose project 또는 비어 있음이 확인된 volume에
복원하고, 실패하면 기존 환경을 변경하지 않은 채 중단한다.

## 6. 완료 판정

다음 항목을 서로 구분해 기록한다.

- Git SHA와 app image identity
- public/private checksum 일치
- DB native verification과 schema/table·bounded row count
- object inventory count와 byte total
- Polaris catalog/principal readback
- DataHub read/publish actor·PAT와 catalog readback
- 인증된 Trino query
- Backend `/readiness`
- Frontend login·analysis smoke

하나라도 실패하면 `동일 환경 완료`로 기록하지 않는다. healthcheck만으로 데이터·metadata·model
준비 완료를 주장하지 않는다.
