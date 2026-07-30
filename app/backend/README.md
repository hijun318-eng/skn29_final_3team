# R4 Control Plane 골격

`app/backend`는 R4가 소유하는 FastAPI, 공통 계약, 단일 Alembic chain의 최소 골격이다.

## 경계 규칙

- `api`와 `controllers`는 요청 흐름을 조정하고 비즈니스 처리는 `services`에 위임한다.
- `services`는 `ports`의 계약에만 의존하며 `adapters`의 구체 구현을 직접 가져오지 않는다.
- `adapters`만 외부 시스템 계약을 구현한다.
- PMS, POS, CRM, Facility, Banquet DB에 직접 연결하지 않는다. 실제 데이터 플랫폼 구현은 R2가 제공한다.
- 공통 API 계약 버전은 `DRAFT-OPENAPI-v0.1`이다.

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

`APP_DATABASE_URL`을 지정한 뒤 `alembic upgrade head`를 실행하면 Alembic version table만 만든다. Compose가 관리하는 application DDL의 소유권 이전이 승인되기 전에는 domain migration을 추가하지 않는다.
