# Answervice FastAPI Backend

`app/backend`는 인증, Analysis, Report, Context, 안전 경계와 영속성을 제공하는 현재 FastAPI 실행 서비스다. 과거 R4 단독 소유·I1 Gate 방식은 사용하지 않는다.

## 실행 구조

- `app/api/`: HTTP router와 인증·권한 경계
- `app/controllers/`: Analysis 실행 흐름 조정
- `app/services/`: Context, G1·G2·G3, 실행 상태, Report scheduler
- `app/ports/`: 외부 연동 계약
- `app/adapters/`: Trino, DataHub, model, PostgreSQL 구현
- `migrations/versions/`: 단일 Alembic migration chain
- `contracts/openapi.v0.1.json`: exporter로 관리하는 고정 OpenAPI snapshot

Source DB를 직접 조회하지 않는다. 승인된 Context와 G1을 거쳐 SQL을 결정하고, G2를 통과한 read-only SQL만 Trino에서 실행한다. 결과는 G3 통과 후에만 Query·Artifact·Report 근거로 저장한다.

## 인증과 권한

브라우저 인증은 서버 세션과 `HttpOnly`, `SameSite=Strict` cookie를 사용한다. 세션 원문은 저장하지 않고 SHA-256 digest, subject, role, 유효기간과 폐기 상태를 Application PostgreSQL에 저장한다.

- `hotel_analyst`: Analysis와 본인 Report 사용
- `report_admin`: Report 관리 기능 사용
- 권한 밖 endpoint: `403`
- 만료·폐기된 세션: `401`

비밀번호, session 원문, API key를 환경 출력·로그·Git에 남기지 않는다.

## 주요 API

- `GET /health`, `GET /readiness`
- `POST /auth/login`, `GET /auth/session`, `POST /auth/logout`
- `POST /analysis`
- `GET /analysis/progress/{trace_id}`
- `POST /analysis/progress/{trace_id}/cancel`
- Analysis Definition·Run·Artifact 조회와 재실행
- Report 초안·정의·실행·예약·관리 API

정확한 endpoint와 schema는 FastAPI code 및 `contracts/openapi.v0.1.json`을 기준으로 한다.

## 환경 변수

전체 예시는 `infrastructure/database/.env.example`에 있다.

```powershell
$env:OPENAI_ENDPOINT = "https://api.openai.com"
$env:OPENAI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-5.4-mini"
$env:NODE2_MODEL_PROVIDER = "openai"
$env:NODE2_MODEL = "gpt-5.4-mini"
$env:MODEL_TIMEOUT_SECONDS = "60"
```

실제 endpoint가 준비되지 않으면 제품 실행을 fake 성공으로 바꾸지 않는다.

## 실행

전체 E2E 환경은 repository root에서 실행한다.

```powershell
Copy-Item infrastructure/database/.env.example infrastructure/database/.env
powershell -ExecutionPolicy Bypass -File infrastructure/database/security/provision-release-principals.ps1
docker compose --env-file infrastructure/database/.env --profile full up -d --build
Invoke-RestMethod http://127.0.0.1:28000/readiness | ConvertTo-Json -Depth 5
```

Backend만 개발 실행할 때는 의존 서비스와 환경 변수를 먼저 준비한다.

```powershell
Set-Location app/backend
uvicorn app.main:app --reload
```

- 로컬 단독 기본 주소: `http://127.0.0.1:8000`
- root Compose 주소: `http://127.0.0.1:28000`

## Migration과 계약 검증

현재 저장소의 Alembic head는 `20260813_18`이다. 실제 적용 상태는 DB에서 `alembic current`로 확인하며, 문서의 번호만 보고 적용 완료로 판단하지 않는다.

```powershell
python app/backend/scripts/export_openapi.py --check
python -m pytest tests/backend tests/report -q
```

OpenAPI snapshot과 fixture는 직접 편집하지 않고 exporter와 테스트를 사용한다.
