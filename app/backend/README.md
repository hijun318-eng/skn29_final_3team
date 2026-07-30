# R4 Fake Control Plane 골격

`app/backend`는 R4가 소유하는 FastAPI·공통 계약·단일 Alembic chain의 최소 골격이다. PMS·POS·CRM·Facility·Banquet에 직접 접속하는 repository는 두지 않는다. R2가 `DataPlatformAdapter`의 실제 구현을 제공하고, 이 앱은 해당 Port만 소비한다.

## 실행

```powershell
cd app/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:APP_DB_HOST = '127.0.0.1'
$env:APP_DB_PORT = '15432'
uvicorn app.main:app --reload
```

- OpenAPI: `http://127.0.0.1:8000/openapi.json`
- Health: `GET /health`
- Readiness: `GET /readiness`
- Fake analysis: `POST /analysis`

`APP_DATABASE_URL`을 지정한 뒤 `alembic upgrade head`를 실행하면 빈 DB에서 Alembic version table만 생성한다. 기존 Compose application DDL을 중복 생성하지 않으며, 테이블 소유권 이전 승인 전까지 domain migration은 추가하지 않는다.
