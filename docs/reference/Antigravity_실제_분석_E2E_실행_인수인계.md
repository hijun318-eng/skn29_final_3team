# Antigravity 실제 분석 E2E 실행 인수인계

> 작성 기준 시각: 2026-08-17 KST
>
> 대상 저장소: `skn29_final_3team`
>
> 작업 범위: 실제 Browser → Backend → Model → DataHub/Trino → SQL → Artifact → Report 연결 검증만
>
> 현재 판정: **구현 완료나 E2E PASS가 아니라, 실행 전 인수인계 상태**

## 1. 이 문서의 목적

이 문서는 Antigravity가 Answervice의 실제 분석 흐름을 한 번 끝까지 실행하고, 각 단계가 동일한 실제 release와 식별자로 연결됐는지 증명하기 위한 실행 지침이다. 화면에 그럴듯한 숫자가 나타나는지 확인하는 smoke test가 아니다.

다음 연결을 모두 실제로 증명해야 한다.

```text
실제 Chrome 로그인
→ 실제 Frontend 요청
→ 실제 Backend 인증·권한·진행 상태
→ 실제 외부 model Node 1/2/3 호출
→ 실제 DataHub 승인 Glossary·Dataset·Schema 조회
→ 실제 SQLGlot 정책 검증·서버 값 바인딩
→ 실제 Trino read-only query
→ 실제 App PostgreSQL query/evidence/artifact 저장
→ 실제 Browser artifact 표시
→ 실제 Report draft 전송·조회
→ report_admin 승인·HTML/PDF read-back
```

한 단계라도 mock, fixture, 정적 성공 JSON, test token, in-memory repository, 고정 결과, 수기 DB 삽입으로 대체되면 이 E2E는 실패다.

## 2. 냉정한 현재 상태

### 이미 실제로 검증된 범위

- DataHub metadata-only catalog 발행과 live read-back은 완료됐다.
- 활성 catalog release는 `walkerhill-v4.3-catalog.1`이다.
- catalog SHA-256은 `d8efc5cb11f543a93ce8d3b584899a90f9548d9f9deb6b897e737a629a720ce8`이다.
- 실제 발행량은 Dataset 51개, Column 578개, 승인 Metric Term 7개, Governance Entity 8개, Aspect 458개다.
- Backend의 실제 `GovernedDataPlatformAdapter`로 DataHub와 Trino를 연결해 7개 Metric Term 해석 및 두 source health가 `HEALTHY`임을 확인했다.
- 실제 Trino의 핵심 serving dataset 기간은 현재 다음과 같다.
  - `serving.analytics_v4_3.hotel_operations_daily`: 2024-01-01 ~ 2026-08-31, 2,922행
  - `serving.analytics_v4_3.voc_daily`: 2024-01-01 ~ 2026-08-31, 15,532행
  - `serving.analytics_v4_3.banquet_daily`: 2024-01-01 ~ 2026-08-31, 2,922행
- 실제 외부 principal 파일에는 `hotel_analyst`, `report_admin` 두 역할의 active 계정이 존재한다.

이 증거는 DataHub/Trino runtime 경계만 증명한다. Browser, Backend HTTP, 실제 model, App DB artifact, Report/PDF까지 같은 요청으로 연결됐다는 뜻은 아니다.

### 아직 검증되지 않은 범위

- Answervice Backend와 Frontend는 작성 시점에 실행 중이 아니다.
  - `127.0.0.1:13000`: 닫힘
  - `127.0.0.1:28000`: 닫힘
- 실제 Browser에서 로그인한 뒤 `/analysis`가 성공한 증거가 없다.
- 실제 model Node 1, Node 2, Node 3가 같은 분석 요청에서 호출됐다는 증거가 없다.
- 실제 Trino `query_id`가 App DB의 query execution 및 artifact와 연결됐다는 Browser E2E 증거가 없다.
- 분석 artifact를 Report draft로 전송한 뒤 최종 HTML/PDF까지 확인한 실제 증거가 없다.

### 실행 전 반드시 확인할 Frontend API 경로

- 현재 root Compose의 `compose.app-postgres.override.yml`은 Backend를 host `127.0.0.1:28000`에 연다.
- 저장소 내부 `infrastructure/database/.env`와 외부 `%LOCALAPPDATA%\Answervice\deployment\answervice.env`의 `VITE_BACKEND_BASE_URL`은 현재 `/api`다.
- 이 값은 오류가 아니다. 컨테이너 Frontend의 `app/frontend/nginx.conf`가 브라우저의 `/api/` 요청을 내부 `http://backend:8000/`으로 proxy하므로, root Compose로 Frontend `127.0.0.1:13000`을 사용할 때는 `/api`가 same-origin 정식 경로다.
- `http://127.0.0.1:28000` 같은 absolute URL은 Nginx를 우회해 Backend를 직접 호출하거나 별도 개발 서버를 사용할 때만 명시적으로 검토한다. Container E2E를 위해 `/api`를 무조건 absolute URL로 바꾸지 않는다.
- Antigravity는 build 전 `app/frontend/nginx.conf`, render된 Compose, 실제 접근 방식을 함께 대조한다. 저장소 내부 `.env`의 secret 값을 출력·복사·commit하지 않으며 운영 정본은 repository 밖 absolute deployment env와 secret 파일이다.

## 3. 이번 작업에서 제외할 것

다음은 이 인수인계의 범위가 아니다.

- semantic search, embedding, vector index, Ollama 도입 또는 검증
- DataHub catalog 재발행이나 Glossary 재설계
- V4.3 데이터 재적재·재생성
- 다른 Docker Compose project 정리
- Docker volume 삭제, `docker compose down -v`, `docker system prune`, VHDX 조작
- model 재학습, LoRA, RunPod 신규 배포
- schedule, 자동 report run, 장기 conversation/multi-turn 완성
- 전체 제품 완료 선언

`DATAHUB_SEARCH_MODE=lexical` 상태로 진행한다. semantic dependency가 없다는 이유로 이 E2E를 막거나 Ollama를 임의 기동하지 않는다.

## 4. 권위 있는 구현 경계

Antigravity는 과거 screenshot·derived prompt·발표자료보다 아래 현재 코드를 우선한다.

- 저장소 원칙: `AGENTS.md`
- 현행 제품 흐름: `docs/product/02_유저플로우.md`
- Frontend 분석 요청: `app/frontend/src/api/analysisClient.ts`
- Frontend 실제 화면 흐름: `app/frontend/src/pages/AgentPage.jsx`
- Backend 인증·분석 endpoint: `app/backend/app/api/router.py`
- Backend runtime wiring: `app/backend/app/api/analysis_router_runtime.py`
- 분석 stage: `app/backend/app/services/analysis_*_stage.py`
- DataHub runtime adapter: `app/backend/app/adapters/governed_data_platform.py`
- Trino transport: `app/backend/app/adapters/trino_async.py`
- SQL 정책: `app/backend/app/services/pipeline_sql_*.py`, `src/ai/sql_policy.py`, `src/ai/sql_binding.py`
- 분석 영속화: `app/backend/app/adapters/analysis_*_repository.py`
- Report artifact 전송: `app/backend/app/api/report_router.py`, `app/backend/app/adapters/report_artifact_repository.py`
- Frontend Report 흐름: `app/frontend/src/features/reports/useReportsPageController.jsx`
- 공개 API snapshot: `app/backend/contracts/openapi.v0.1.json`
- model route: `src/modelops/model_runtime_manifest.v1.json`

문서와 코드가 충돌하면 먼저 현재 코드와 실제 runtime을 비교한다. 차이가 확인되면 요청 하나만 통과시키는 우회 코드를 추가하지 말고 일반 계약의 결함으로 수정한다.

## 5. 절대 금지 사항

### 데이터와 결과

- 질문 문구를 보고 특정 metric, table, date, SQL로 분기하지 않는다.
- 테스트 통과를 위해 특정 질문의 결과값을 production 코드·JSON·prompt·migration에 넣지 않는다.
- DataHub 장애나 누락 필드를 로컬 JSON으로 보충하지 않는다.
- Trino 실행 실패를 이전 artifact, cached fixture, 빈 성공 결과로 바꾸지 않는다.
- 결과가 예상과 다르다는 이유로 source row나 serving table을 수정하지 않는다.

### 인증과 권한

- test token, `AUTH_MODE=test`, 고정 cookie, 임의 `X-Role`로 로그인 단계를 우회하지 않는다.
- analyst artifact를 DB에서 report draft에 수기로 연결하지 않는다.
- `report_admin` 승인을 analyst 역할이나 Frontend UI 숨김만으로 대신하지 않는다.

### Docker와 secret

- `answervice` 외 다른 Compose project를 건드리지 않는다.
- 현재 source/App DB, DataHub, Trino volume을 삭제·초기화·재생성하지 않는다.
- secret 원문을 명령행 인수, log, screenshot, Markdown에 기록하지 않는다.
- 저장소 내부 `.env`를 새로운 운영 정본으로 만들지 않는다.

### 검증 명칭

- MockTransport, unit fixture, 직접 함수 호출은 E2E 증거가 아니다.
- `/health` 또는 `/readiness`만 통과해도 E2E PASS가 아니다.
- Backend API 직접 호출만으로 Browser E2E PASS라 부르지 않는다.
- Browser 화면만 보고 App DB·Trino 연결 확인을 생략하지 않는다.

## 6. 실행 전 스냅샷과 안전 Gate

### 6.1 작업트리 보존

현재 worktree는 대규모 dirty 상태다. 다른 변경을 되돌리거나 정리하지 않는다.

```powershell
Set-Location C:\Users\Playdata\Desktop\SKN_FINAL\skn29_final_3team
git status --short --branch
```

E2E 중 코드 변경이 필요해도 관련 파일만 최소 수정한다. `git reset --hard`, `git checkout --`, 광범위 formatter를 금지한다.

### 6.2 Docker 범위 확인

```powershell
docker ps --filter label=com.docker.compose.project=answervice `
  --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker volume ls --filter label=com.docker.compose.project=answervice
```

실행 전 container ID, volume 이름, 상태를 외부 evidence 디렉터리에 저장한다. 볼륨 내용이나 container를 변경하지 않는 read-only inventory만 허용한다.

### 6.3 외부 deployment env 확인

정본 후보 경로는 다음과 같다.

```powershell
$deploymentEnv = Join-Path $env:LOCALAPPDATA 'Answervice\deployment\answervice.env'
```

다음은 값 자체를 출력하지 말고 존재·비어 있지 않음·파일 존재만 검사한다.

- `AUTH_PRINCIPALS_HOST_FILE`, `AUTH_SESSION_SECRET`
- `APP_DB_USER`, `APP_DB_PASSWORD`
- `APP_MIGRATION_USER`, `APP_MIGRATION_PASSWORD`
- `TRINO_RUNTIME_USER`, `TRINO_RUNTIME_PASSWORD`, `TRINO_TLS_CA_HOST_FILE`
- `DATAHUB_READ_API_TOKEN`, `DATAHUB_READ_ACTOR_URN`, `DATAHUB_TLS_CA_HOST_FILE`
- `OPENAI_ENDPOINT`, `OPENAI_API_KEY`, `OPENAI_MODEL`
- `ANALYST_LOGIN_ID`, `ANALYST_LOGIN_PASSWORD`
- `REPORT_ADMIN_LOGIN_ID`, `REPORT_ADMIN_LOGIN_PASSWORD`
- `VITE_BACKEND_BASE_URL`

Node 2 전용 네 변수 `NODE2_MODEL_PROVIDER`, `NODE2_MODEL_ENDPOINT`, `NODE2_MODEL_API_TOKEN`, `NODE2_MODEL`은 모두 비어 있거나 모두 채워져야 한다. 현재는 모두 비어 있으며, 이는 primary OpenAI route를 Node 2까지 공유하는 의도된 구성이다. 일부만 채우지 않는다.

### 6.4 Compose render 검증

먼저 실제 merge 결과를 확인한다.

```powershell
docker compose --env-file $deploymentEnv --profile dev config --quiet
docker compose --env-file $deploymentEnv --profile dev config --format json > $env:TEMP\answervice-compose.json
```

검사 항목:

- project name이 `answervice`인지
- `app-postgres`, `app-migrations`, `backend`, `frontend`만 dev profile 대상인지
- Backend host port와 `VITE_BACKEND_BASE_URL`이 정확히 일치하는지
- Frontend가 Backend host origin을 build arg로 받는지
- Backend가 기존 `answervice-network`, `answervice_datahub-network`에 연결되는지
- DataHub, Trino, source DB container를 recreate하도록 변동하지 않는지
- secret mount가 실제 absolute file이고 repository 내부가 아닌지

Compose가 기존 source DB, DataHub, Trino를 recreate하려 하면 중단한다. 원인을 확인하기 전 `--force-recreate`를 사용하지 않는다.

## 7. App stack만 안전하게 기동

기존 infra와 volume을 유지한 채 app service만 올린다. 먼저 image를 build하고, 의존성 자동 재생성을 피하기 위해 대상 service를 좁힌다.

```powershell
docker compose --env-file $deploymentEnv --profile dev build app-migrations backend frontend
docker compose --env-file $deploymentEnv --profile dev up --no-deps app-migrations
docker compose --env-file $deploymentEnv --profile dev ps -a app-migrations
```

`app-migrations`가 exit 0인지 확인한 뒤에만 다음으로 진행한다.

```powershell
docker compose --env-file $deploymentEnv --profile dev up -d --no-deps backend
docker compose --env-file $deploymentEnv --profile dev up -d --no-deps frontend
```

주의:

- migration failure를 `SKIP_MIGRATIONS`, DB 수기 수정, 이전 image로 우회하지 않는다.
- Frontend는 build-time `VITE_BACKEND_BASE_URL`을 사용하므로 env만 고친 뒤 기존 image를 재사용하면 안 된다.
- app service 기동 중 infra container가 변경됐는지 전후 container ID를 비교한다.

## 8. Readiness는 시작 조건일 뿐 완료 조건이 아니다

실제 render된 host URL을 사용한다. 현재 root override 기준 예시는 다음과 같다.

```powershell
$backend = 'http://127.0.0.1:28000'
Invoke-RestMethod "$backend/health"
Invoke-RestMethod "$backend/readiness"
```

`/readiness`에서 최소 다음 실제 경계가 모두 ready여야 한다.

- App PostgreSQL connection/migration head
- 실제 principal store parsing 및 현재 유효 principal 존재
- DataHub 인증 GraphQL capability
- Trino runtime principal의 terminal `SELECT 1`
- 활성 model route의 `/v1/models` exact model ID

`/v1/info` 200, DataHub `/config` 200, principal 파일 크기만으로 ready라고 판단하지 않는다. 하나라도 not ready면 Browser 분석을 시작하지 않고 dependency별 원인을 해결한다.

## 9. 실제 Browser 정상 흐름

### 9.1 브라우저 사용 원칙

- 실제 Chrome의 새 탭 또는 격리된 profile을 사용한다.
- Frontend `http://127.0.0.1:13000`에서 시작한다.
- DevTools Network와 Backend log를 동시에 관찰한다.
- API를 먼저 직접 호출해 cookie를 만들고 Browser에 주입하지 않는다.
- 로그인 비밀번호와 cookie 원문을 screenshot에 포함하지 않는다.

### 9.2 analyst 로그인

외부 deployment env의 `ANALYST_LOGIN_ID`와 `ANALYST_LOGIN_PASSWORD`를 화면에 입력한다. 자격 증명을 log나 문서에 복사하지 않는다.

완료 증거:

- Browser에서 `POST /auth/login` 성공
- `HttpOnly`, `SameSite=Strict`, 배포 정책에 맞는 `Secure` cookie
- 이어지는 `GET /auth/session`이 `hotel_analyst`
- Frontend의 권한 메뉴가 서버 응답과 일치
- 새로고침 뒤 session 복원

### 9.3 사전 봉인할 정상 질문

현재 live 승인 Glossary에 존재하고 실제 기간 범위 안인 다음 질문을 acceptance scenario로 사용한다.

> 2026년 7월 호텔별 합성 통합 운영매출을 보여주고, 사용한 지표와 데이터 근거를 설명해줘.

이 질문은 **테스트 입력**일 뿐 production 분기나 정답 SQL의 근거가 아니다. 실행 전 question text와 timestamp의 hash를 evidence manifest에 기록해 결과를 본 뒤 질문을 바꾸는 행위를 막는다.

이 질문을 선택한 이유:

- 승인 Term `합성 통합 운영매출`이 현재 live Glossary에 존재한다.
- metric ID는 `total_operating_revenue_krw`, 단위는 KRW, aggregation/reduction은 sum이다.
- 승인 source는 `serving.analytics_v4_3.hotel_operations_daily`다.
- 승인 dimension은 `hotel_code`, time field는 `business_date`다.
- 2026년 7월은 실제 dataset 기간 안이다.
- alias exact match가 가능해 불필요한 모호성을 줄이지만 SQL과 결과를 미리 고정하지는 않는다.

### 9.4 정상 분석 실행

1. 질문을 UI에서 한 번 제출한다.
2. 제출 직전 Browser가 생성한 `X-Trace-Id`를 기록한다.
3. 진행 polling이 `/analysis/progress/{trace_id}`로 이어지는지 확인한다.
4. 화면 진행 단계가 최종 응답보다 먼저 성공으로 고정되지 않는지 확인한다.
5. 최종 응답의 `request_id`, `trace_id`, `artifact_id`, `query_id`를 기록한다.

성공 판정에는 다음이 모두 필요하다.

- HTTP 200이며 분석 status가 `SUCCEEDED` 또는 근거가 완전한 `PARTIAL`
- route가 실제 LLM 일반 분석 경로이며 template/fake route가 아님
- model trace에 Node 1, Node 2, Node 3의 실제 model version, prompt ID/version이 존재
- evidence의 catalog/context release가 실제 active release와 일치
- source URN과 Trino FQN이 live DataHub/Trino 자산과 일치
- APP-G1, APP-G2, APP-G3가 모두 통과
- repair가 있었다면 최대 1회이고 원 SQL과 수정 사유가 trace로 구분됨
- `query_id`, `artifact_id`, `context_hash`가 비어 있지 않음
- table row와 chart가 같은 server artifact에서 파생됨
- Browser가 로컬 계산값이나 fixture를 결과로 합성하지 않음

### 9.5 독립 결과 검산

화면 숫자를 정답으로 사용하지 않는다. 별도 read-only verifier가 live DataHub의 승인 metric rule과 time/dimension 계약을 다시 읽고, 그 계약으로 독립적인 parameterized Trino query를 구성해 `[2026-07-01, 2026-08-01)` 결과를 계산한다.

검산 규칙:

- production 분석이 생성한 SQL 문자열을 그대로 재사용하지 않는다.
- 정답 숫자를 JSON이나 Python 상수로 저장하지 않는다.
- 독립 verifier도 runtime principal과 승인된 asset/column만 사용한다.
- 호텔별 key set, 각 value, 합계, null 처리, row count를 비교한다.
- 통화 표시 단위 변환은 raw KRW 검산 후 별도로 확인한다.
- 불일치하면 UI rounding 문제인지, model SQL 문제인지, policy/binding 문제인지, source drift인지 분리한다.

## 10. App DB 영속화 교차검증

Browser 응답 ID를 기준으로 read-only 조회한다. 내부 SQL 원문, secret, 질문 원문을 evidence에 복사하지 않는다.

같은 `request_id`로 다음 관계가 정확히 1개씩 연결되어야 한다.

```text
chat.analysis_requests
  → analysis_v1.analysis_run_links
  → query.query_executions
  → artifact.analysis_artifacts
  → governance.audit_events
```

검사 항목:

- `chat.analysis_requests.status`가 terminal 상태인지
- DB의 `trace_id`가 Browser `X-Trace-Id`와 같은지
- `query.query_executions.generation_mode = 'LLM'`인지
- AST/join/permission validation이 통과인지
- DB `trino_query_id`가 Browser evidence의 `query_id`와 같은지
- source URN 목록이 Browser evidence 및 DataHub read-back과 같은지
- `artifact.analysis_artifacts.artifact_id`가 Browser `artifact_id`와 같은지
- artifact status가 `APPROVED`인지
- snapshot/chart/evidence checksum을 다시 계산했을 때 저장 checksum과 같은지
- audit event가 같은 request/query/artifact를 참조하는지
- 성공 경로에서 중복 request, query execution, artifact가 생기지 않았는지

DB 행을 직접 수정해 연결을 맞추지 않는다. 연결이 틀리면 E2E 실패로 기록하고 repository transaction 결함을 수정한 뒤 새 요청으로 재실행한다.

## 11. 실제 Report 연결

### 11.1 analyst의 draft 생성

분석 결과 화면에서 `보고서 초안 만들기`를 사용한다. Frontend는 실제 `POST /reports/drafts/from-analysis-artifact`를 호출해야 한다.

확인 항목:

- 요청 body의 `artifact_id`가 방금 생성된 실제 artifact와 같음
- 서버가 현재 owner의 `SUCCEEDED/PARTIAL` 승인 artifact만 허용
- 응답 definition/version이 실제 DB에 저장됨
- report block이 같은 artifact와 Trino query ID를 참조
- `/reports` 이동 후 server에서 artifact를 다시 읽어 화면을 hydrate함
- sessionStorage나 분석 화면의 복사본을 server artifact처럼 사용하지 않음
- 새로고침 후 같은 definition/version/block/artifact가 복원됨

### 11.2 analyst 권한의 부정 검증

`hotel_analyst`로는 report draft 생성·편집은 가능하지만 승인 endpoint는 403이어야 한다. UI 버튼이 숨겨졌다는 사실만으로 권한 검증을 끝내지 말고 실제 API 거부를 확인한다.

### 11.3 report_admin 승인과 최종 asset

1. analyst session을 logout한다.
2. 외부 env의 `REPORT_ADMIN_LOGIN_ID`, `REPORT_ADMIN_LOGIN_PASSWORD`로 UI 로그인한다.
3. 방금 생성된 report definition/version을 목록에서 연다.
4. 저장된 HTML 초안의 artifact 표·차트·근거가 분석 artifact와 일치하는지 확인한다.
5. `확정하고 PDF 생성`을 실행한다.
6. `GET .../document`, `document.html`, `document.pdf`를 Browser UI를 통해 연다.

완료 조건:

- status가 `draft → approved`로 1회 전이
- approved version은 수정 불가
- final document의 artifact version/checksum이 원 분석 artifact와 연결
- HTML과 PDF의 orientation, currency unit, 표 row sampling 계약이 일치
- PDF가 실제 `%PDF` 파일이고 크기가 0보다 큼
- 저장된 PDF checksum을 다운로드 파일에서 다시 계산해 일치
- 새로고침 후 final document metadata와 asset이 다시 열림
- analyst가 다른 사용자의 artifact/report를 추측한 ID로 읽을 수 없음

## 12. 최소 실패 흐름

정상 흐름 하나만 통과하면 fallback이나 권한 우회를 놓칠 수 있다. 다음 실패 흐름도 실제 Browser/API 경계에서 확인한다.

### 인증 없음

- 새 격리 session에서 `/analysis` 호출은 401이어야 한다.
- request/query/artifact 행이 생기면 안 된다.

### 모호한 질문

질문 예시는 다음과 같이 metric을 특정하지 않는 입력을 사용한다.

> 2026년 7월 호텔별 수치를 보여줘.

기대 결과:

- 임의 metric을 선택해 실행하지 않음
- `BLOCKED + NEEDS_CLARIFICATION` 또는 계약상 동등한 typed clarification
- Trino query와 artifact가 없음
- 승인 Glossary에 실제 존재하는 후보만 노출

### 권한 경계

- analyst의 report approve는 403
- 다른 owner의 artifact ID 직접 조회는 존재 여부를 드러내지 않는 404/거부
- 실패를 Frontend가 이전 성공 artifact로 덮지 않음

실패 시나리오를 통과시키려고 production에 질문별 분기나 mock response를 추가하지 않는다.

## 13. E2E 증거 묶음

원본 증거는 repository 밖에 저장한다.

```powershell
$runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$evidenceRoot = Join-Path $env:LOCALAPPDATA "Answervice\evidence\actual-analysis-e2e\$runStamp"
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
```

필수 산출물:

- `manifest.json`: 시작/종료 시각, branch, dirty 여부, image digest, container ID, release/checksum, Browser/API/DB ID
- `preflight.md`: env 값이 아닌 존재성, Compose render, readiness 결과
- `browser-network.har`: secret/cookie/password를 제거한 Network 기록
- `screenshots/`: 로그인 후 역할, 분석 진행, 결과, 근거, report draft, final document
- `backend.log`: 해당 trace/request 구간만 redaction 후 저장
- `datahub-readback.json`: 사용 metric term, dataset/schema/native governance의 live read-back
- `trino-evidence.json`: query ID, terminal state, source FQN, row count, 검산 checksum
- `app-db-evidence.json`: request/query/artifact/report/document 관계와 checksum
- `failure-cases.md`: unauthenticated, ambiguity, role boundary 결과
- `result.md`: PASS/FAIL과 남은 위험

HAR, log, JSON에 다음을 넣지 않는다.

- Authorization header
- cookie 원문
- password/API token/session secret
- 전체 `.env`
- model prompt 원문 전체
- 필요 없는 source row나 개인정보

Repository에는 redacted 최종 요약과 필요한 screenshot만 별도 검토 후 추가한다. 외부 evidence 폴더가 존재한다는 이유만으로 Git에 넣지 않는다.

## 14. PASS/FAIL 판정표

| Gate | PASS 조건 | 즉시 FAIL 조건 |
|---|---|---|
| 환경 | 기존 volume 보존, app만 기동 | infra recreate, volume 삭제 |
| 인증 | 실제 login/session/logout | test token, cookie 주입 |
| Model | Node 1/2/3 실제 route와 version trace | fixture/template/fake 결과 |
| DataHub | active release의 승인 term/asset/schema read-back | 로컬 JSON fallback |
| SQL 정책 | 동일 AST 검증·binding, read-only 1 statement | 문자열 치환·고정 SQL 우회 |
| Trino | 실제 query ID와 terminal result | cached fixture 또는 query 없음 |
| 결과 | 독립 검산과 key/value/checksum 일치 | 화면만 확인 |
| 영속화 | request→query→artifact→audit exact 연결 | DB 수기 보정, 중복/고아 row |
| Report | 실제 artifact→draft→approved HTML/PDF | UI local copy, owner 우회 |
| 실패 경계 | 401/clarification/403에서 query·artifact 없음 | 이전 성공 결과로 대체 |

모든 Gate가 PASS일 때만 `ACTUAL_ANALYSIS_E2E_VERIFIED`라고 기록한다. `PARTIAL`, skip, 미실행 dependency가 하나라도 있으면 전체 E2E는 PASS가 아니다.

## 15. 실패 시 진단 순서

증상을 보고 여러 계층을 동시에 바꾸지 않는다.

1. Frontend build-time Backend origin과 CORS/cookie
2. Backend `/readiness` dependency별 실제 probe
3. principal store와 App DB session
4. model route config와 `/v1/models` exact ID
5. DataHub active release, Term, Dataset, native governance, checksum
6. Context package completeness와 entitlement
7. Node 2 provider response schema
8. SQLGlot AST policy와 named binding
9. Trino TLS/Basic/ACL/query terminal state
10. G3 result/evidence validation
11. App DB transaction과 artifact checksum
12. Report owner scope, draft block, document renderer

실패 원인을 확인하기 전에 catalog 재발행, 데이터 재적재, 모델 변경, prompt 변경을 하지 않는다. 가장 먼저 실패한 경계 하나만 재현하고 고친다.

## 16. Antigravity 최종 보고 형식

최종 보고는 아래 순서를 지킨다.

1. `PASS`, `FAIL`, `BLOCKED` 중 하나
2. 실제 실행한 범위
3. Browser request ID / trace ID / query ID / artifact ID / report definition/version
4. 사용한 catalog/model/prompt/policy/schema version과 checksum
5. 독립 결과 검산 요약
6. App DB lineage와 checksum 검증 결과
7. Report HTML/PDF read-back 결과
8. 실패 경계 결과
9. 변경한 파일과 변경 이유
10. 실행하지 않은 항목과 남은 위험

“대체로 정상”, “보이는상 문제없음”, “unit test가 통과했으므로 E2E 완료” 같은 표현을 쓰지 않는다.

## 17. 종료 조건

이번 인수인계의 완료는 문서를 읽는 것으로 끝나지 않는다. Antigravity가 다음을 모두 충족해야 한다.

- 기존 실제 데이터와 Docker volume을 보존했다.
- app stack만 실제 구성으로 기동했다.
- 정상 Browser 분석 1건이 실제 model/DataHub/Trino/App DB를 통과했다.
- 결과를 독립 검산했다.
- 실제 artifact를 Report draft와 final HTML/PDF에 연결했다.
- 인증·모호성·역할 실패 경계를 확인했다.
- secret 없는 재현 가능한 evidence를 남겼다.
- mock, 하드코딩, 질문 전용 JSON/SQL, test auth를 production에 추가하지 않았다.

위 조건 중 하나라도 확인하지 못하면 미확인 사실을 숨기지 말고 `BLOCKED` 또는 `FAIL`로 종료한다.
