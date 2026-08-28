# Answervice 로컬 환경 자동 설치 — AI 실행 지시서

## 사람 사용법

이 파일만 로컬 filesystem·terminal·Docker에 접근할 수 있는 AI coding agent에 첨부하고
`이 문서대로 실제 설치를 진행해 줘`라고 요청한다. 받은 handoff bundle은 AI가 접근할 수
있는 로컬 폴더에 두되, `.env`, `private/`, DB dump를 채팅이나 외부 서비스에 첨부하지 않는다.

터미널이나 로컬 파일에 접근할 수 없는 AI는 설치를 대신 실행할 수 없다. 이 경우 아래 명령을
사용자에게 안내만 하고 완료했다고 주장하면 안 된다.

---

## AI에게 주는 최상위 명령

당신은 Answervice의 로컬 설치 담당 agent다. 이 문서를 요약하는 데서 끝내지 말고, 아래
계약대로 실제 사전점검·설치·기동·검증을 순서대로 수행하라. 사용자의 기존 source, Docker
project, volume, credential을 임의로 변경하거나 삭제하지 말라.

목표는 다음 두 수준을 구분해 달성하는 것이다.

- `Fresh`: exact Git SHA와 전달된 설정으로 새 storage를 초기화한다. 기존 runtime data와
  DataHub PAT의 동일성은 주장하지 않는다.
- `Snapshot`: exact Git SHA와 검증된 native backup을 새 storage에 복원한다. receipt가
  보장하지 않는 Kafka·검색 index·model cache는 재생성한다.

다음 우선순위를 사용하라.

1. `public/release-manifest.json`과 checksum 검증 결과
2. exact SHA의 Compose·PowerShell script·migration
3. bundle의 `public/HANDOFF.md`와 checksummed snapshot receipt
4. 이 문서

서로 충돌하거나 검증된 명령이 없으면 추측하지 말고 `SETUP_BLOCKED`로 종료하라.

## 절대 안전 규칙

- secret 값, `.env` 원문, private key, password, token, 전체 `docker inspect`, 렌더링된
  `docker compose config`를 채팅·로그·보고서에 출력하지 않는다.
- secret의 **값**을 사용자에게 채팅으로 요구하지 않는다. 필요한 경우 사용자가 설치된 env
  파일을 자신의 editor에서 직접 갱신하게 하고, AI는 key의 존재·placeholder 여부만 확인한다.
- `private/`와 snapshot을 Git에 add/commit/push하거나 외부 서비스에 upload하지 않는다.
- 제품 source를 수정하거나 자동 commit/push하지 않는다. 설치는 clean exact SHA에서 한다.
- 기존 dirty repository를 reset/clean/checkout하지 않는다. 별도의 clean clone을 사용한다.
- 기존 `answervice` 또는 다른 Compose project를 자동 중지·삭제·재사용하지 않는다.
- `docker compose down -v`, `docker system prune`, `docker volume prune`, named-volume 원본 복사,
  기존 DB/volume 위 restore를 실행하지 않는다.
- host-wide Docker·Git 설치, Docker Desktop version 변경, 관리자 권한 작업이 필요하면 먼저
  사용자의 명시적 승인을 받는다.
- 실패한 단계 뒤의 명령을 계속 실행하지 않는다. healthcheck만으로 설치 완료를 선언하지 않는다.

## 성공 조건

아래 항목을 모두 증명한 경우에만 `SETUP_COMPLETE`를 출력한다.

1. public/private checksum 검증 성공
2. repository가 manifest의 exact commit이며 clean
3. 설치된 env와 10개 host-file entry가 저장소 밖에 존재
4. 선택된 mode의 storage 초기화 또는 restore 완료
5. DB·Trino 검증 성공
6. DataHub actor/PAT와 catalog readback 성공
7. 현재 release가 요구하는 semantic/catalog activation 성공
8. Backend `/readiness`의 모든 dependency가 `ready`
9. Frontend health와 최소 login·analysis smoke 성공

일부만 성공하면 `SETUP_PARTIAL`로 보고하고 남은 단계와 blocker를 정확히 적는다.

## 1. 입력 자동 발견

먼저 현재 workspace와 이 문서가 놓인 폴더의 바로 아래에서 다음 구조를 가진 bundle을 찾는다.

```text
answervice-<sha>-<utc>-<mode>/
├─ public/
│  ├─ AI_SETUP_AGENT.md
│  ├─ HANDOFF.md
│  ├─ release-manifest.json
│  └─ checksums.sha256
└─ private/
   ├─ answervice.env.template
   ├─ secrets/
   └─ private-checksums.sha256
```

정확히 하나를 찾으면 사용하고, 없거나 여러 개면 다음 한 가지만 질문하라.

> 받은 `answervice-...` handoff bundle의 절대경로를 알려주세요.

bundle path만 받으며 secret 내용을 요구하지 않는다. `.INCOMPLETE`가 있거나 public/private 중
하나라도 없으면 중단한다. `release-manifest.json`에서 `schemaVersion`, `mode`, full
`sourceCommit`, runtime OS/architecture를 읽되 secret 파일은 열어 출력하지 않는다.

## 2. host 사전점검

Windows PowerShell에서 다음을 읽기 전용으로 확인한다.

```powershell
git --version
docker version
docker compose version
python --version
python -c "import httpx"
```

- Docker daemon이 실행 중이어야 한다.
- server OS는 `linux`, architecture는 manifest와 같아야 한다.
- Docker·Compose version이 manifest와 다르면 차이를 기록한다. 자동 downgrade/upgrade하지
  말고, Compose config가 실패하거나 major compatibility가 확인되지 않으면 중단한다.
- Docker가 없거나 daemon을 시작할 수 없으면 설치·시작 승인을 요청하고 대기한다.
- `start.ps1 -Stage Core`는 host Python의 `httpx`를 사용한다. import가 실패하면 repository
  안이나 global Python을 임의 변경하지 않는다. 저장소 밖 release 전용 virtual environment와
  exact dependency 설치를 제안하고, package download 승인을 받은 뒤 그 environment를 활성화한
  process에서만 계속한다.
- Git/Docker 명령 실패를 성공으로 무시하지 않는다.

기존 project 충돌을 확인하되 컨테이너 environment를 출력하지 않는다. manifest의 Compose
project 이름을 label filter로 조회해 기존 컨테이너가 있으면 이름과 상태만 보고하고 중단한다.
acceptance용 `answervice-phase2b-datahub`를 전달 대상에 섞지 않는다.

## 3. exact source 준비

repository URL은 다음과 같다.

```text
https://github.com/hijun318-eng/skn29_final_3team.git
```

사용자가 별도 위치를 지정하지 않으면 사용자 profile 아래 `source` 폴더에 clone한다. 같은 이름의
폴더가 dirty이거나 다른 commit이면 건드리지 말고 SHA suffix가 붙은 새 clean 폴더를 사용한다.

```powershell
git clone --no-checkout https://github.com/hijun318-eng/skn29_final_3team.git <clean-repo-path>
git -C <clean-repo-path> fetch origin
git -C <clean-repo-path> checkout --detach <manifest-sourceCommit>
git -C <clean-repo-path> rev-parse HEAD
git -C <clean-repo-path> rev-parse <manifest-upstream>
git -C <clean-repo-path> status --porcelain=v1 --untracked-files=all
```

HEAD와 manifest upstream의 remote-tracking SHA가 모두 manifest SHA와 같고 status 출력이 비어
있어야 한다. exact SHA에 `infrastructure/handoff/Install-HandoffConfig.ps1`가 없으면 bundle과
source가 불일치하므로 중단한다.

## 4. private 설정 설치

release별로 격리된 저장소 밖 경로를 사용한다. 예시는 다음과 같다.

```powershell
$deploymentRoot = Join-Path $env:LOCALAPPDATA `
  ('Answervice\releases\' + '<manifest-sourceCommit>'.Substring(0, 12))

powershell -NoProfile -ExecutionPolicy Bypass `
  -File <clean-repo-path>\infrastructure\handoff\Install-HandoffConfig.ps1 `
  -BundleDirectory <absolute-bundle-path> `
  -RepositoryPath <clean-repo-path> `
  -DeploymentRoot $deploymentRoot
```

installer가 public/private checksum, exact clean SHA, 10개 secret entry를 검증하게 한다. 출력의
`ENV_FILE|...` 뒤 절대경로만 이후 `$envFile`로 사용한다. `STATE_INPUT|...`는 Snapshot 입력이며
내용을 공개 출력하지 않는다.

대상 env나 secret이 이미 있으면 installer는 덮어쓰지 않는다. 이를 삭제하거나 우회하지 말고
`SETUP_BLOCKED`로 보고한다.

## 5. Compose 계약 점검

Compose는 설치된 env를 명시하고 implicit `.env`를 끈 상태에서 실행한다. 렌더링된 설정은
출력하지 않고 `--quiet`만 사용한다.

```powershell
$env:COMPOSE_DISABLE_ENV_FILE = '1'
docker compose `
  --env-file $envFile `
  -f <clean-repo-path>\compose.yml `
  --profile full `
  config --quiet
```

process environment에 env 파일과 같은 key가 다른 값으로 이미 정의되어 있으면 key 이름만
보고하고 clean child process에서 다시 실행한다. 값을 출력하거나 ambient override를 그대로
사용하지 않는다.

## 6. mode별 storage 준비

### Fresh

Core를 exact source의 공식 script로 시작한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File <clean-repo-path>\infrastructure\database\scripts\start.ps1 `
  -EnvFilePath $envFile `
  -Stage Core
```

`DATABASE_CORE_READY|next=PROVISION_DATAHUB_SERVICE_TOKENS`가 있어야 다음 단계로 간다.
Fresh의 bundle에 들어 있던 DataHub PAT는 새 DataHub DB에서 유효하다고 간주하지 않는다.
Core 전 두 token의 값을 출력하지 않은 hash로만 기억하고, 사용자에게 loopback DataHub UI에서
서로 다른 read/publish service actor와 최소권한 PAT를 발급해 설치된 env의 다음 key를 직접
교체하도록 안내한다.

```text
DATAHUB_READ_ACTOR_URN
DATAHUB_READ_API_TOKEN
DATAHUB_PUBLISH_ACTOR_URN
DATAHUB_PUBLISH_API_TOKEN
```

AI가 token을 채팅으로 받지 않는다. 네 값이 placeholder가 아니고 두 token hash가 기존 token과
달라졌으며 read와 publish identity/token이 서로 다름을 값 비출력 방식으로 확인한 뒤에만
Catalog를 실행한다. actor URN은 동일한 service 이름으로 재생성될 수 있으므로 과거 URN과의
차이 자체를 요구하지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File <clean-repo-path>\infrastructure\database\scripts\start.ps1 `
  -EnvFilePath $envFile `
  -Stage Catalog
```

### Snapshot

`private/state/snapshot-receipt.json`의 다음 항목이 모두 충족되어야 한다.

- `sourceCommit`이 manifest SHA와 같음
- `composeProject`가 `answervice`
- `quiesced`, `nativeVerificationPassed`, `cleanRestoreRehearsalPassed`가 모두 `true`
- 모든 artifact가 state 폴더 안에 존재하고 private checksum에 포함됨

restore는 bundle의 checksummed `public/HANDOFF.md` 또는 state 안의 checksummed restore plan에
exact 명령과 새 volume 대상이 기록된 경우에만 수행한다. 일반적인 Docker volume 복사나 AI가
추론한 임의 명령으로 대체하지 않는다. 복원 명령이 없으면
`SETUP_BLOCKED|SNAPSHOT_RESTORE_PLAN_MISSING`으로 종료한다.

restore 후 Kafka·검색 index·model cache처럼 receipt의 `rebuildRequired`에 기록된 항목을 현재
release의 공식 script로 재생성한다. 기존 volume에는 복원하지 않는다.

## 7. infrastructure 검증

Catalog 또는 Snapshot restore가 끝난 뒤 다음 검증을 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File <clean-repo-path>\infrastructure\database\scripts\verify.ps1 `
  -EnvFilePath $envFile
```

이 검증은 DB health, source read-only 거절, 인증된 Trino catalog query를 확인한다. DataHub와
semantic release 완료를 대신하지 않는다. `start.ps1 -Stage Catalog`가
`catalog_ready=false|next=SEMANTIC_CHECK`를 출력했다면 exact release의 승인된 semantic check,
publish, readback receipt가 필요하다. bundle에 검증된 명령이 없으면 추론해서 실행하지 말고
`SETUP_PARTIAL|SEMANTIC_ACTIVATION_REQUIRED`로 보고한다.

Catalog ingestion 성공만으로 read PAT의 실제 actor identity가 검증됐다고 주장하지 않는다.
exact release에 checksummed DataHub token identity readback 절차가 있어야 해당 항목을 완료한다.

## 8. Backend·Frontend

현재 source에는 database startup과 root Compose 사이에 App PostgreSQL container/port override가
있을 수 있다. 따라서 `docker compose --profile full up`이나 `stop.ps1`을 전체 app의 검증된
turnkey 명령으로 간주하지 않는다.

Backend·Frontend는 bundle의 checksummed `HANDOFF.md`에 **같은 SHA의 clean rehearsal에서
성공한 exact application startup 명령**이 기록된 경우에만 실행한다. 없다면 기존 DB container를
재구성하거나 `--no-deps` workaround를 발명하지 말고
`SETUP_PARTIAL|APPLICATION_START_COMMAND_MISSING`으로 종료한다.

application을 시작한 경우 다음을 모두 검증한다.

- Backend `/health`
- Backend `/readiness`와 `app_postgres`, `migration`, `analysis_template_registry`, `trino`,
  `datahub`, `model` dependency가 모두 `ready`
- Frontend `/health`
- 실제 login 후 최소 analysis smoke

기본 loopback 후보는 Frontend `http://127.0.0.1:13000`, Backend
`http://127.0.0.1:28000`이지만 실제 port는 exact Compose와 release handoff에서 다시 읽는다.

## 9. 최종 보고 형식

secret 값과 전체 env를 제외하고 다음 형식으로 짧게 보고한다.

```text
STATUS: SETUP_COMPLETE | SETUP_PARTIAL | SETUP_BLOCKED
MODE: Fresh | Snapshot
SOURCE_COMMIT: <full sha>
REPOSITORY_CLEAN: true | false
CHECKSUMS: public=pass|fail, private=pass|fail
RUNTIME: docker=<version>, compose=<version>, os/arch=<value>
COMPLETED: <실제로 성공한 단계>
PENDING: <남은 단계>
BLOCKER: <없음 또는 정확한 원인>
USER_ACTION: <필요한 최소 행동 또는 없음>
```

일부 단계가 실패했는데 `SETUP_COMPLETE`, `READY`, `동일 환경 완료`라고 표현하지 않는다.
