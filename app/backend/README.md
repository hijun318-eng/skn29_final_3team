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
- Fake analysis: `POST /analysis`

실제 Base serving을 사용할 때는 OpenAI 호환 endpoint의 base URL만 환경 변수로 전달한다. token은 선택 사항이며 로그나 응답에 포함하지 않는다.

```powershell
$env:MODEL_MODE = "openai"
$env:MODEL_ENDPOINT = "http://127.0.0.1:8001"
$env:MODEL_TIMEOUT_SECONDS = "15"
```

`MODEL_MODE=fake`는 R4 fake adapter, `MODEL_MODE=contract-fake`는 R3 계약 fake adapter를 그대로 사용한다. 일반 분석은 원문 질문을 `normalized_question`으로 전달하고 request ID는 추적 식별자로 분리한다. 실제 endpoint에는 node별 R3 response schema를 `guided_json`으로 전달하고 동일 schema를 다시 검증한다. timeout·HTTP 오류·잘못된 JSON·schema 불일치·fallback·circuit open은 분석 성공이나 Artifact로 저장하지 않는다.

## API 계약

FastAPI·Pydantic code가 API 계약의 단일 원본이다. 분석 응답의 `OPENAPI-v1.0.0` 호환성은 유지하고 FastAPI 문서 버전은 `OPENAPI-v1.1.0-DRAFT`로 분리한다. 문서에는 기존 `/health`, `/readiness`, `/analysis`와 Report 관리자 endpoint만 포함한다.

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

`APP_DATABASE_URL`을 지정한 뒤 `alembic upgrade head`를 실행하면 단일 migration chain이 application schema를 최신 head까지 적용한다. 현재 head는 `20260804_05`이며 기존 DB와 빈 DB upgrade를 모두 지원한다. Report endpoint는 기존 `report` schema를 변경하지 않고 `REPORT-v1.0.0` 호환 및 `REPORT-v1.1.0-DRAFT` 등록본을 `report_v1` schema에 영속화한다. 공개 요청·응답은 strict Pydantic schema와 고정 operation ID를 사용한다.

Report HTTP는 owner 범위의 definition 목록·초안 block 교체·run 목록/상세와 `POST /reports/runs/manual`만 제공한다. 수동 실행 요청은 `definition_id`, `version`, `as_of`, `idempotency_key`만 받고 command ID와 `queued` 상태는 서버가 만든다. 실행 결과 전체를 저장하는 기존 `create_run` 연결은 신뢰된 내부 호출에만 남겨 두며 HTTP route로 공개하지 않는다. 실제 command 소비, worker, schedule, Artifact 생성은 후속 계약 전까지 구현하지 않는다.

## Container 검증

repository root에서 다음 명령을 실행하면 기존 database Compose와 R4 backend service fragment를 결합해 `answervice-backend`를 기동한다. `/health`와 `/readiness`에서 application과 `app-postgres` 연결을 모두 검증하며, 성공한 container는 Docker Desktop에서 계속 확인할 수 있다.

```powershell
powershell -ExecutionPolicy Bypass -File app/backend/scripts/verify-container.ps1
```

성공 출력은 `BACKEND_CONTAINER_READY`, `BACKEND_DATABASE_READY`다. 검증 후 container까지 제거하려면 `-RemoveAfterVerification`을 추가한다.

```powershell
powershell -ExecutionPolicy Bypass -File app/backend/scripts/verify-container.ps1 -RemoveAfterVerification
```

backend는 `http://127.0.0.1:18000`에서 접근한다. root Compose 파일 자체는 R1 소유이므로 수정하지 않고 [compose.fragment.yml](compose.fragment.yml)만 결합한다.

## 조건부 backend 선행 작업

I1 전체 승인이 완료되기 전에도 R4는 producer draft와 fixture를 만들 수 있지만 `APPROVED` 또는 Gate 통과로 표시하지 않는다. R5는 고정된 draft fixture를 소비하고 변경이 필요하면 contract diff를 제출한다. UI·Report 구현과 다른 역할 소유 코드는 R4가 직접 변경하지 않는다.

Context Package의 초기 제한은 다음과 같다.

- 최대 dataset 8개
- 최대 column 60개
- 최대 `min(6,000 tokens, model context의 25%)`
- 권한 없는 asset은 package와 model 입력 전에 제외
- package는 release·policy·time·entitlement·URN/FQN·token과 결정론적 hash를 기록
