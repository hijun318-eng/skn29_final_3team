# Backend Control Plane

`app/backend`는 FastAPI API, 공통 계약, 단일 Alembic chain과 Report worker를 제공한다.

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

승인된 P0 Template만 실행할 때는 `MODEL_MODE=template-only`를 사용한다. 이 모드는 승인 SQL을 G1·G2로 검사하고 실제 Trino 결과를 G3 통과 후 표·차트·Artifact로 저장한다. 일반 자연어 SQL 생성은 지원하지 않고 실패 차단한다.

일반 질문까지 실행하려면 OpenAI 호환 endpoint의 base URL을 환경 변수로 전달한다. token은 선택 사항이며 로그나 응답에 포함하지 않는다.

```powershell
$env:MODEL_MODE = "openai"
$env:MODEL_ENDPOINT = "http://127.0.0.1:8001"
$env:MODEL_TIMEOUT_SECONDS = "15"
```

일반 분석은 `MODEL_MODE=openai`에서 원문 질문을 `normalized_question`으로 전달하고 request ID는 추적 식별자로 분리한다. 실제 endpoint에는 node별 R3 response schema를 `guided_json`으로 전달하고 동일 schema를 다시 검증한다. timeout·HTTP 오류·잘못된 JSON·schema 불일치·circuit open은 분석 성공이나 Artifact로 저장하지 않는다.

`DATA_PLATFORM_MODE=real`은 요청마다 실제 Trino health와 DataHub dataset URN·name·승인 컬럼을 확인한다. DataHub가 반환한 원본 추가 컬럼은 Context나 응답에 노출하지 않는다. `POST /analysis`는 application DB가 설정된 경우 request, query evidence, G3 이후 Artifact를 한 흐름으로 영속화한다.

`DATA_PLATFORM_MODE=versioned-trino`는 DataHub 없이 승인된 versioned Context와 실제 Trino를 연결한다. `real`은 live DataHub metadata exact-match와 승인 raw join 계약을 요구한다.

### DataHub 접근 profile 운영

self-hosted DataHub OSS v1.7에서 `VIEW_AUTHORIZATION_ENABLED=true`는 entity page 조회를 제한하지만, 검색 시점의 권한 pushdown은 Cloud 전용이다. 따라서 backend는 검색 결과마다 허용 Domain과 Tag를 확인하고 승인된 dataset URN·schema·FQN과 exact-match한 뒤 Context에 포함해야 한다. Domain/Tag가 없거나 허용 URN을 확정할 수 없는 결과도 거부한다. 자세한 제품 경계는 DataHub 공식 [Search Access Controls](https://docs.datahub.com/docs/features/feature-guides/search-access-controls)와 [Policies Guide](https://docs.datahub.com/docs/authorization/policies)를 따른다.

profile 계약의 단일 원본은 [server-access-profiles.v1.json](../../config/server-access-profiles.v1.json)이다.

| profile | 독립 DB grant (파생 Domain) | DataHub token 환경 변수 | Trino principal |
| --- | --- | --- | --- |
| `pms_only` | `pms` (`rooms`) | `DATAHUB_PMS_ONLY_TOKEN` | `answervice_pms_only` |
| `crm_only` | `crm` (`membership`) | `DATAHUB_CRM_ONLY_TOKEN` | `answervice_crm_only` |
| `pms_crm` | `pms`, `crm` (`rooms`, `membership`) | `DATAHUB_PMS_CRM_TOKEN` | `answervice_pms_crm` |
| `integrated_revenue` | `pms`, `crm`, `pos` (`rooms`, `membership`, `food_and_beverage`) | `DATAHUB_INTEGRATED_REVENUE_TOKEN` | `answervice_integrated_revenue` |
| `integrated_operations` | `pms`, `crm`, `pos`, `facility`, `banquet` (전체 5개 Domain) | `DATAHUB_INTEGRATED_OPERATIONS_TOKEN` | `answervice_integrated_operations` |

각 preset의 `database_grants` 합집합이 서버 권한의 진실 원천이며 `database_domains`로 허용 Domain을 파생한다. Join은 필요한 DB grant가 모두 있고 해당 DB의 허용 URN이 Context에 포함된 경우에만 허용한다. 각 token은 profile별 최소 권한 PAT로 발급해 배포 secret에서 해당 환경 변수로 주입한다. raw token은 저장소·설정 예시·로그·응답에 기록하지 않는다. 브라우저는 선택한 `X-Access-Profile`만 보내며 profile token, 허용 Domain, role, DataHub token 또는 Trino 자격증명을 보내거나 보관하지 않는다.

운영 bootstrap과 검증 순서는 다음과 같다.

1. profile별 Domain·Tag·승인 URN과 Trino principal을 검토하고 versioned profile 계약을 승인한다.
2. DataHub actor와 Domain 정책을 생성하고 dataset에 Domain·Tag를 부여한 뒤 `VIEW_AUTHORIZATION_ENABLED=true`를 적용한다.
3. profile별 PAT를 별도로 발급해 secret manager 또는 read-only secret mount에 저장하고, 배포 시 계약의 환경 변수로만 주입한다.
4. [Trino 접근 제어](../../infrastructure/database/trino/etc/access-control-rules.json)에 principal별 최소 `SELECT` 범위와 명시적 deny가 있는지 확인하고 backend를 재기동한다.
5. 각 profile의 허용 dataset 검색·조회와 Trino 질의가 성공하고, 다른 Domain·Tag·URN 및 catalog 접근은 실패하는지 확인한다. 브라우저 개발자 도구에서 profile token·정책·DataHub/Trino 자격증명이 노출되지 않는지도 확인한다.
6. token 누락·만료, 알 수 없는 profile, 정책 로드 실패, metadata 불일치, DataHub/Trino 오류를 각각 유도해 요청이 성공 결과·cache·Artifact 없이 차단되는지 확인한다. 감사 로그에는 profile·정책 버전·principal 식별자만 남고 raw token은 없어야 한다.

위 검증 중 하나라도 실패하면 다른 profile, 공용 DataHub token, 더 넓은 Trino principal 또는 `versioned-trino`로 fallback하지 않는다. 정책과 자격증명이 정상화될 때까지 fail-closed 상태를 유지한다.

```powershell
$env:DATA_PLATFORM_MODE = "versioned-trino"
$env:MODEL_MODE = "template-only"
$env:TRINO_URL = "http://127.0.0.1:18080"
$env:TRINO_USER = "app_user"
uvicorn app.main:app --host 127.0.0.1 --port 18000
```

## API 계약

FastAPI·Pydantic code가 API 계약의 단일 원본이다. 분석 응답의 `OPENAPI-v1.0.0` 호환성은 유지하고 FastAPI 문서 버전은 `OPENAPI-v1.1.0-DRAFT`로 분리한다. 문서에는 기존 `/health`, `/readiness`, `/analysis`, Report 관리자 endpoint와 owner 범위의 Analysis Definition·Run 조회 및 재실행 endpoint를 포함한다.

Analysis Definition은 사용자 소유의 불변 버전이며 공개 응답에 질문 원문·parameter 값·SQL·결과 snapshot을 노출하지 않는다. 재실행은 저장 SQL을 사용하지 않고 현재 `AnalysisController`를 호출해 entitlement·Context·G1·G2·G3·repair·binder를 다시 검증한다. 실행 이력은 기존 `chat.analysis_requests` → `query.query_executions` → `artifact.analysis_artifacts`를 재사용하고 Definition과 request의 연결만 저장한다.

계약 파일을 갱신하거나 drift를 확인하는 명령은 다음과 같다.

```powershell
python app/backend/scripts/export_openapi.py
python app/backend/scripts/export_openapi.py --check
```

- 고정 명세: [openapi.v0.1.json](contracts/openapi.v0.1.json)
- 상태 매핑: [state_mapping.v0.1.json](contracts/state_mapping.v0.1.json)
- 명세 파일은 직접 수정하지 않고 exporter로 다시 생성한다.

`APP_DATABASE_URL`을 지정한 뒤 `alembic upgrade head`를 실행하면 단일 migration chain이 application schema를 최신 head까지 적용한다. 공식 지원 revision은 `20260729_01`, `20260730_02`, `20260731_03`, `20260804_04`, `20260804_05`, `20260810_06`, `20260811_07`, `20260812_08`, `20260812_09`이며 root는 `20260729_01`, head는 `20260812_09` 하나씩이다. 빈 DB와 이 목록에 있는 revision만 upgrade 대상으로 지원한다. Report endpoint는 기존 `report` schema를 변경하지 않고 `REPORT-v1.0.0` 호환 및 `REPORT-v1.1.0-DRAFT` 등록본을 `report_v1` schema에 영속화한다. 공개 요청·응답은 strict Pydantic schema와 고정 operation ID를 사용한다.

`CONTEXT-REGISTRY-v1.0.0-DRAFT`는 내부 service-only 계약이다. Context record, immutable release, request package binding을 application PostgreSQL에 저장하며 checksum은 정렬된 canonical JSON을 서버에서 SHA-256으로 계산한다. 같은 idempotency key와 같은 payload는 기존 결과를 반환하고, 다른 payload·중복 version·승인되지 않은 record·배포되지 않은 release는 도메인 충돌로 차단한다. 승인·배포 이후 payload와 package는 DB trigger로 변경을 거부한다. 이 단계에는 public router, OpenAPI, live DataHub 조립, Analysis 저장 연결을 추가하지 않는다.

Report HTTP는 owner 범위의 definition 목록·초안 block 교체·run 목록/상세, `POST /reports/runs/manual`, 일·주·월 schedule 저장·조회를 제공한다. 수동 실행 요청은 `definition_id`, `version`, `as_of`, `idempotency_key`만 받고 command ID와 `queued` 상태는 서버가 만든다. schedule은 승인된 definition version만 활성화할 수 있고 due 시각별 idempotency key로 한 번만 queue한 뒤 다음 실행 시각을 전진시킨다. 실행 결과 전체를 저장하는 기존 `create_run` 연결은 신뢰된 내부 호출에만 남겨 두며 HTTP route로 공개하지 않는다. `report-worker`는 예약 command를 소비하고 현재 분석 파이프라인으로 block을 재실행해 Artifact와 run 결과를 저장한다.

브라우저 CORS는 설정된 exact origin과 credentials·필수 header를 유지하며, 기존 `GET`·`POST`·`OPTIONS`와 draft block 교체용 `PUT` preflight만 허용한다. origin·method·header wildcard는 사용하지 않는다.

## Container 실행

repository root에서 `.env.example`을 `.env`로 복사해 필수 값을 설정한 뒤 dev profile을 실행한다.

```powershell
docker compose --profile dev up -d app-postgres app-postgres-provision backend report-worker
```

backend는 `http://127.0.0.1:18000`에서 접근한다. 서비스 정의는 root Compose가 [compose.fragment.yml](compose.fragment.yml)을 결합한다.

## 관측성

backend는 HTTP request와 분석의 Context 검색·조립, model, Trino, Artifact 단계를
OpenTelemetry span·metric·상관 로그로 기록한다. 모든 단계에는 기존 `request_id`와
`trace_id`만 상관 속성으로 사용하며 질문, token, SQL, parameter, 조회 결과는 기록하지
않는다. `OTEL_EXPORTER_OTLP_ENDPOINT`가 비어 있으면 SDK exporter를 만들지 않는 안전한
no-op이고, collector를 사용할 때만 OTLP/HTTP base URL(예: `http://otel-collector:4318`)을
배포 환경에 설정한다.

## 조건부 backend 선행 작업

I1 전체 승인이 완료되기 전에도 R4는 producer draft를 만들 수 있지만 `APPROVED` 또는 Gate 통과로 표시하지 않는다. 변경이 필요하면 contract diff를 제출한다. UI·Report 구현과 다른 역할 소유 코드는 R4가 직접 변경하지 않는다.

Context Package의 초기 제한은 다음과 같다.

- 최대 dataset 8개
- 최대 column 60개
- 최대 `min(6,000 tokens, model context의 25%)`
- 권한 없는 asset은 package와 model 입력 전에 제외
- package는 release·policy·time·entitlement·URN/FQN·token과 결정론적 hash를 기록
