# Answervice Backend

`app/backend`는 FastAPI API, 분석·보고서 orchestration, 외부 adapter와 단일 Alembic chain을 소유한다. 현재 구현 기준은 repository root [`AGENTS.md`](../../AGENTS.md)와 [`docs/product/`](../../docs/product/) 계약을 따른다.

## 경계 규칙

- `api`와 `controllers`는 요청 흐름을 조정하고 비즈니스 처리는 `services`에 위임한다.
- `services`는 `ports`의 계약에만 의존하며 `adapters`의 구체 구현을 직접 가져오지 않는다.
- `adapters`만 외부 시스템 계약을 구현한다.
- PMS, POS, CRM, Facility, Banquet DB에 직접 연결하지 않고 DataHub·Trino adapter 경계를 사용한다.
- 공통 API 계약 버전은 `OPENAPI-v1.0.0`이다.

## 실행

프로젝트 의존성이 준비된 환경에서 다음 명령을 실행한다.

```powershell
Set-Location app/backend
uvicorn app.main:app --reload
```

- OpenAPI: `http://127.0.0.1:8000/openapi.json`
- Health: `GET /health`
- Readiness: `GET /readiness`
- Analysis: `POST /analysis`

운영 인증은 서버가 소유한 외부 principal store만 사용한다. 파일은 JSON 배열이며 각 항목에는 `username`, `password_salt`, `password_hash`, `password_iterations`, `subject`, `role`, `active`만 기록한다. provisioning script가 PBKDF2-SHA256 hash를 만들며 raw password는 principal 파일이나 로그에 남기지 않는다. 로그인용 raw password와 session secret이 있는 deployment environment는 저장소 밖에서 별도 보안 채널로 관리한다. 로그인 성공 시 Backend가 HMAC 서명 session을 발급해 App DB에 등록하고 `HttpOnly` cookie로 전달한다. `AUTH_PRINCIPALS_FILE`에는 container 내부 read-only 경로를 지정하며 실제 secret mount는 배포 설정에서 구성한다. principal store나 signed-session 필수값이 없으면 기동하며 합성 계정으로 대체하지 않고 fail closed한다.

권한 판정은 사용자명이 아니라 서버가 검증한 Role과 중앙 Capability 정책을 사용한다. `platform_admin`은 통제된 인수환경에서 분석·보고서·데이터 관리의 현재 애플리케이션 Capability 전체를 가지지만, DataHub publish·Trino setup·Source DB 계정 같은 service identity를 상속하지 않는다. 외부 env의 `ANALYST_LOGIN_ROLE`로 계정 Role을 회전해도 provisioning은 기존 subject를 보존하므로 저장 Analysis·Report 소유권을 끊지 않는다.

Backend는 실제 Trino·DataHub·OpenAI 호환 endpoint만 사용한다. 승인 Template은 DB에서 읽어 G1·G2·Trino·G3를 거치며, 일반 질문은 Node1·Node2·Node3 모델 계약을 실행한다. 테스트 대역을 선택하는 운영 환경 변수나 제품 fallback은 제공하지 않는다.

Backend의 DataHub 조회는 `DATAHUB_GMS_URL` HTTPS origin,
`DATAHUB_READ_API_TOKEN`, `DATAHUB_READ_ACTOR_URN`, `DATAHUB_TLS_CA_FILE`이 모두 있어야
조립된다. mutation 전용 `DATAHUB_PUBLISH_API_TOKEN`은 Backend container에 주입하지
않는다. owned `httpx` transport는 system proxy를 신뢰하지 않고 지정 CA와 Bearer만
사용하며 readiness도 공개 `/config`가 아니라 인증 actor의 bounded GraphQL 결과를
검증한다.

```powershell
$env:OPENAI_ENDPOINT = "https://api.openai.com"
$env:OPENAI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-5.4-mini"
$env:MODEL_TIMEOUT_SECONDS = "15"
```

로컬 Docker 배포에서는 위 secret을 저장소에 복사하지 않고 외부 env 파일로 주입한다.
`REPORT_ASSISTANT_MODEL_ENV_FILE`에는 `OPENAI_ENDPOINT`, `OPENAI_API_KEY`, `OPENAI_MODEL`이
들어 있는 파일의 절대 경로를 지정한다. Compose는 이 값이 없으면 backend 구성을 거부한다.

```powershell
$env:REPORT_ASSISTANT_MODEL_ENV_FILE = "C:\Users\<사용자>\외부-secret\openai.env"
docker compose --env-file <DB 환경 파일> -f compose.report-assistant-stage5.yml up -d --build
```

Node2 전용 설정 네 개를 모두 비우면 Node2·Repair도 위 primary route를 공유한다.
RunPod Qwen route를 사용할 때는 `NODE2_MODEL_PROVIDER`, `NODE2_MODEL_ENDPOINT`,
`NODE2_MODEL_API_TOKEN`, `NODE2_MODEL`을 모두 선언해야 한다. provider·model alias와
capacity는 `src/modelops/model_runtime_manifest.v1.json`, 비활성 예시는
`infrastructure/database/.env.example`을 따른다. 실제 endpoint와 token은 배포 환경에서만
주입하며 일부만 선언하면 readiness와 adapter 생성이 모두 fail-closed한다.

일반 분석은 원문 질문을 `normalized_question`으로 전달하고 request ID는 추적 식별자로 분리한다. 실제 endpoint에는 node별 response schema를 전달하고 동일 schema를 다시 검증한다. timeout·HTTP 오류·잘못된 JSON·schema 불일치·circuit open은 분석 성공이나 Artifact로 저장하지 않는다.

데이터 플랫폼은 요청마다 실제 Trino health와 DataHub dataset URN·name·승인 컬럼을 확인한다. DataHub가 반환한 원본 추가 컬럼은 Context나 응답에 노출하지 않는다. `POST /analysis`는 request, query evidence, G3 이후 Artifact를 한 흐름으로 영속화한다.

## API 계약

FastAPI·Pydantic code가 API 계약의 단일 원본이다. 분석 응답의 `OPENAPI-v1.0.0` 호환성은 유지하고 FastAPI 문서 버전은 `OPENAPI-v1.1.0-DRAFT`로 분리한다. 문서에는 기존 `/health`, `/readiness`, `/analysis`, Report 관리자 endpoint와 owner 범위의 Analysis Definition·Run 조회 및 재실행 endpoint를 포함한다.

Analysis Definition은 사용자 소유의 불변 버전이며 공개 응답에 parameter 값·SQL·결과 snapshot을 노출하지 않는다. 재실행은 저장 SQL을 사용하지 않고 현재 `AnalysisController`를 호출해 entitlement·Context·G1·G2·G3·repair·binder를 다시 검증한다. 매 실행은 새 `chat.analysis_requests` → `query.query_executions` → `artifact.analysis_artifacts` 이력을 만들고 Definition과 새 request의 연결을 함께 저장한다.

계약 파일과 상태별 fixture를 갱신하거나 drift를 확인하는 명령은 다음과 같다.

```powershell
python app/backend/scripts/export_openapi.py
python app/backend/scripts/export_openapi.py --check
```

- 고정 명세: [openapi.v0.1.json](contracts/openapi.v0.1.json)
- 상태 매핑: [state_mapping.v0.1.json](contracts/state_mapping.v0.1.json)
- 상태 fixture: `tests/backend/fixtures/api/v0.1/`
- 명세 파일과 fixture는 직접 수정하지 않고 exporter로 다시 생성한다.
- pagination·sorting·filter·idempotency는 현재 세 endpoint에 적용되지 않으며, 이를 사용하는 endpoint 구현 시 별도 version으로 추가한다.

`APP_DATABASE_URL`을 지정한 뒤 `alembic upgrade head`를 실행하면 단일 migration chain이 application schema를 최신 head까지 적용한다. root는 `20260729_01`, 현재 tracked head는 `20260826_44` 하나씩이다. Report와 Analysis endpoint는 application PostgreSQL에 정의·실행·Artifact·예약·Assistant 평가 이력을 영속화하며 공개 요청·응답은 strict Pydantic schema와 고정 operation ID를 사용한다.

`CONTEXT-REGISTRY-v1.0.0-DRAFT`는 내부 service-only 계약이다. Context record, immutable release, request package binding을 application PostgreSQL에 저장하며 checksum은 정렬된 canonical JSON을 서버에서 SHA-256으로 계산한다. 같은 idempotency key와 같은 payload는 기존 결과를 반환하고, 다른 payload·중복 version·승인되지 않은 record·배포되지 않은 release는 도메인 충돌로 차단한다. 승인·배포 이후 payload와 package는 DB trigger로 변경을 거부한다. 이 단계에는 public router, OpenAPI, live DataHub 조립, Analysis 저장 연결을 추가하지 않는다.

backend 기동 전 `alembic current` 결과가 위 지원 목록에 있는지 확인한다. 저장소에 존재하지 않는 `20260803_03`은 Alembic이 native non-zero로 거부하며 운영 판정 코드 `LEGACY_REVISION_UNSUPPORTED`로 기록한다. 이 상태를 우회하는 추정 migration, 자동 `stamp`, schema·data 변경, `drop`은 금지한다. 보존이 필요한 legacy DB는 변경하지 않고 별도 복구·변환 결정을 요청한다.

Report HTTP는 분석가 소유 초안 작성·조회와 `report_admin`의 전체 정의 승인·수동 실행·예약 실행을 제공한다. 수동·예약 실행은 같은 `ReportExecutionService`를 사용하며, Block에 고정된 Analysis Definition/version을 현재 권한·정책과 공통 `as_of`로 재실행한다. 각 Block Run은 새 request/query/artifact 또는 typed failure를 기록하고 일부 Block만 성공하면 Report Run을 `partial`로 보존한다. 기존 Artifact checksum만 읽어 새 실행처럼 성공 처리하는 경로는 없다.

브라우저 CORS는 설정된 exact origin과 credentials·필수 header를 유지하며, 기존 `GET`·`POST`·`OPTIONS`와 draft block 교체용 `PUT` preflight만 허용한다. origin·method·header wildcard는 사용하지 않는다.

## Container 검증

repository root에서 다음 명령을 실행하면 기존 database Compose와 backend service fragment를 결합해 `answervice-backend`를 기동한다. `/health`와 `/readiness`에서 application과 `app-postgres` 연결을 모두 검증하며, 성공한 container는 Docker Desktop에서 계속 확인할 수 있다.

```powershell
powershell -ExecutionPolicy Bypass -File app/backend/scripts/verify-container.ps1 `
  -EnvFilePath C:\absolute\external\answervice.env
```

성공 출력은 `BACKEND_CONTAINER_READY`, `BACKEND_DATABASE_READY`, `BACKEND_IMAGE_PROVENANCE_READY`, `BACKEND_METRIC_RETRIEVAL_READY`다. provenance 신호는 실행 image의 Git revision·dirty 상태·source fingerprint label이 현재 source tree와 일치한다는 뜻이며, 마지막 신호는 image에 봉인된 Phase 2A v2 retrieval Gate가 현재 live dependency의 active-release Search coverage·실패율·품질·권한·p95 threshold를 모두 통과해 `PROMOTE`를 기록했다는 뜻이다. 검증 후 container까지 제거하려면 `-RemoveAfterVerification`을 추가한다.

Search process 전환의 rollback을 리허설할 때는 새 gitignored JSON 경로와 사전 복구시간 상한을 지정한다. 검증기는 실제 Backend를 `datahub_lexical → lexical → datahub_lexical`로 재생성하고 각 단계의 전체 readiness, image provenance, 동일 release/Gold identity와 Phase 2A v2 `PROMOTE`를 하나의 append-only receipt로 기록한다. 이 receipt의 범위는 `P0-DATAHUB-SEARCH_PROCESS_MODE_ONLY`이며 DB·데이터 release rollback 증거를 대신하지 않는다.

```powershell
powershell -ExecutionPolicy Bypass -File app/backend/scripts/verify-container.ps1 `
  -EnvFilePath C:\absolute\external\answervice.env `
  -SearchRollbackReceiptPath .tmp\search-rollback-receipt.json `
  -MaxSearchTransitionSeconds 180
```

```powershell
powershell -ExecutionPolicy Bypass -File app/backend/scripts/verify-container.ps1 `
  -EnvFilePath C:\absolute\external\answervice.env -RemoveAfterVerification
```

backend는 root Compose 기준 `http://127.0.0.1:28000`에서 접근한다.

로컬 개발에서만 repository 내부의 gitignored env를 사용해야 하면 `-AllowRepositoryLocalDevelopment`를 명시한다. 이 switch 없이 repository 내부 env를 전달하면 검증기는 거부하며, 운영 기본값은 계속 repository 외부 env다.

검증기를 우회해 backend image를 직접 build해야 하는 배포 도구는 먼저 `source-provenance.ps1`을 dot-source하고 `Set-AnswerviceSourceProvenanceEnvironment`를 호출해야 한다. 세 build argument가 없거나 형식이 잘못되면 Dockerfile은 label 없는 image 생성을 거부한다.

## Backend 계약 변경

Backend API를 바꾸면 OpenAPI, Frontend 타입·client, 상태 fixture와 같은 Slice의 실제 HTTP 검증을 함께 갱신한다. producer draft나 fake fixture만으로 `APPROVED` 또는 제품 Gate 통과로 표시하지 않는다.

Context Package의 초기 제한은 다음과 같다.

- 최대 dataset 8개
- 최대 column 60개
- 최대 `min(6,000 tokens, model context의 25%)`
- 권한 없는 asset은 package와 model 입력 전에 제외
- package는 release·policy·time·entitlement·URN/FQN·token과 결정론적 hash를 기록
