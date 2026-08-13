# R4 Control Plane 골격

`app/backend`는 R4가 소유하는 FastAPI, 공통 계약, 단일 Alembic chain의 최소 골격이다.

## 경계 규칙

- `api`와 `controllers`는 요청 흐름을 조정하고 비즈니스 처리는 `services`에 위임한다.
- `services`는 `ports`의 계약에만 의존하며 `adapters`의 구체 구현을 직접 가져오지 않는다.
- `adapters`만 외부 시스템 계약을 구현한다.
- PMS, POS, CRM, Facility, Banquet DB에 직접 연결하지 않는다. 실제 데이터 플랫폼 구현은 R2가 제공한다.
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

운영 인증은 기본값 `AUTH_MODE=release`에서 서버가 소유한 principal JSON 파일을 사용한다. 파일은 JSON 배열이며 각 항목에는 `token_sha256`, `subject`, `role`, `not_before`, `expires_at`만 기록한다. raw Bearer token은 파일·환경 변수·로그에 기록하지 않는다. `AUTH_PRINCIPALS_FILE`에는 container 내부 read-only 경로를 지정하며 실제 secret mount는 R1 배포 카드에서 구성한다. `AUTH_MODE=test`는 고정 합성 principal을 사용하는 test 전용 모드이고 운영 fallback으로 사용하지 않는다.

Backend는 실제 Trino·DataHub·OpenAI 호환 endpoint만 사용한다. 승인 Template은 DB에서 읽어 G1·G2·Trino·G3를 거치며, 일반 질문은 Node1·Node2·Node3 모델 계약을 실행한다. 테스트 대역을 선택하는 운영 환경 변수나 제품 fallback은 제공하지 않는다.

```powershell
$env:OPENAI_ENDPOINT = "https://api.openai.com"
$env:OPENAI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-5.4-mini"
$env:NODE2_MODEL_PROVIDER = "openai"
$env:NODE2_MODEL = "gpt-5.4-mini"
$env:MODEL_TIMEOUT_SECONDS = "15"
```

일반 분석은 원문 질문을 `normalized_question`으로 전달하고 request ID는 추적 식별자로 분리한다. 실제 endpoint에는 node별 response schema를 전달하고 동일 schema를 다시 검증한다. timeout·HTTP 오류·잘못된 JSON·schema 불일치·circuit open은 분석 성공이나 Artifact로 저장하지 않는다.

데이터 플랫폼은 요청마다 실제 Trino health와 DataHub dataset URN·name·승인 컬럼을 확인한다. DataHub가 반환한 원본 추가 컬럼은 Context나 응답에 노출하지 않는다. `POST /analysis`는 request, query evidence, G3 이후 Artifact를 한 흐름으로 영속화한다.

## API 계약

FastAPI·Pydantic code가 API 계약의 단일 원본이다. 분석 응답의 `OPENAPI-v1.0.0` 호환성은 유지하고 FastAPI 문서 버전은 `OPENAPI-v1.1.0-DRAFT`로 분리한다. 문서에는 기존 `/health`, `/readiness`, `/analysis`, Report 관리자 endpoint와 owner 범위의 Analysis Definition·Run 조회 및 재실행 endpoint를 포함한다.

Analysis Definition은 사용자 소유의 불변 버전이며 공개 응답에 질문 원문·parameter 값·SQL·결과 snapshot을 노출하지 않는다. 재실행은 저장 SQL을 사용하지 않고 현재 `AnalysisController`를 호출해 entitlement·Context·G1·G2·G3·repair·binder를 다시 검증한다. 실행 이력은 기존 `chat.analysis_requests` → `query.query_executions` → `artifact.analysis_artifacts`를 재사용하고 Definition과 request의 연결만 저장한다.

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

`APP_DATABASE_URL`을 지정한 뒤 `alembic upgrade head`를 실행하면 단일 migration chain이 application schema를 최신 head까지 적용한다. root는 `20260729_01`, 현재 head는 `20260813_14` 하나씩이다. Report와 Analysis endpoint는 application PostgreSQL에 정의·실행·Artifact·예약 이력을 영속화하며 공개 요청·응답은 strict Pydantic schema와 고정 operation ID를 사용한다.

`CONTEXT-REGISTRY-v1.0.0-DRAFT`는 내부 service-only 계약이다. Context record, immutable release, request package binding을 application PostgreSQL에 저장하며 checksum은 정렬된 canonical JSON을 서버에서 SHA-256으로 계산한다. 같은 idempotency key와 같은 payload는 기존 결과를 반환하고, 다른 payload·중복 version·승인되지 않은 record·배포되지 않은 release는 도메인 충돌로 차단한다. 승인·배포 이후 payload와 package는 DB trigger로 변경을 거부한다. 이 단계에는 public router, OpenAPI, live DataHub 조립, Analysis 저장 연결을 추가하지 않는다.

backend 기동 전 `alembic current` 결과가 위 지원 목록에 있는지 확인한다. 저장소에 존재하지 않는 `20260803_03`은 Alembic이 native non-zero로 거부하며 운영 판정 코드 `LEGACY_REVISION_UNSUPPORTED`로 기록한다. 이 상태를 우회하는 추정 migration, 자동 `stamp`, schema·data 변경, `drop`은 금지한다. 보존이 필요한 legacy DB는 변경하지 않고 별도 복구·변환 결정을 요청한다.

Report HTTP는 분석가 소유 초안 작성·조회와 `report_admin`의 전체 정의 승인·수동 실행·예약 실행을 제공한다. 실행 결과 전체를 직접 주입하는 경로는 공개하지 않으며 서버가 승인된 Analysis Artifact를 다시 검증해 block run을 생성한다.

브라우저 CORS는 설정된 exact origin과 credentials·필수 header를 유지하며, 기존 `GET`·`POST`·`OPTIONS`와 draft block 교체용 `PUT` preflight만 허용한다. origin·method·header wildcard는 사용하지 않는다.

## Container 검증

repository root에서 다음 명령을 실행하면 기존 database Compose와 R4 backend service fragment를 결합해 `answervice-backend`를 기동한다. `/health`와 `/readiness`에서 application과 `app-postgres` 연결을 모두 검증하며, 성공한 container는 Docker Desktop에서 계속 확인할 수 있다.

```powershell
powershell -ExecutionPolicy Bypass -File app/backend/scripts/verify-container.ps1
```

성공 출력은 `BACKEND_CONTAINER_READY`, `BACKEND_DATABASE_READY`다. 검증 후 container까지 제거하려면 `-RemoveAfterVerification`을 추가한다.

```powershell
powershell -ExecutionPolicy Bypass -File app/backend/scripts/verify-container.ps1 -RemoveAfterVerification
```

backend는 root Compose 기준 `http://127.0.0.1:28000`에서 접근한다.

## 조건부 backend 선행 작업

I1 전체 승인이 완료되기 전에도 R4는 producer draft와 fixture를 만들 수 있지만 `APPROVED` 또는 Gate 통과로 표시하지 않는다. R5는 고정된 draft fixture를 소비하고 변경이 필요하면 contract diff를 제출한다. UI·Report 구현과 다른 역할 소유 코드는 R4가 직접 변경하지 않는다.

Context Package의 초기 제한은 다음과 같다.

- 최대 dataset 8개
- 최대 column 60개
- 최대 `min(6,000 tokens, model context의 25%)`
- 권한 없는 asset은 package와 model 입력 전에 제외
- package는 release·policy·time·entitlement·URN/FQN·token과 결정론적 hash를 기록
