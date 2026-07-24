# SensePlace 로컬 실행 가이드

## 사전 요구사항

- Python 3.11+ (3.13 권장)
- Node.js 18+ (v24 권장)
- PostgreSQL 16 (선택, 미설치 시 SQLite fallback)

## 1. 환경 설정

### Django 백엔드

```powershell
cd app\django
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

`.env` 파일 생성 (`.env.example` 참조):

```
SECRET_KEY=dev-secret-key
DEBUG=True
SENSEPLACE_LLM_PROVIDER=stub
FASTAPI_INTERNAL_URL=http://localhost:8001
# PostgreSQL 사용 시:
# DATABASE_URL=postgresql://senseplace:senseplace@localhost:5432/senseplace
```

### FastAPI 분석 서비스

```powershell
cd app\fastapi
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env` 파일 생성:

```
SENSEPLACE_LLM_PROVIDER=stub
DJANGO_API_URL=http://localhost:8000
```

### React 프론트엔드

```powershell
cd app\react
& "C:\Program Files\nodejs\npm.cmd" install
```

## 2. 데이터베이스 마이그레이션

```powershell
cd app\django
.\.venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py loaddata ..\..\data\samples\*.json  # fixture 로드 (선택)
```

## 3. 서버 실행

### 터미널 1: Django (포트 8000)

```powershell
cd app\django
.\.venv\Scripts\Activate.ps1
python manage.py runserver 0.0.0.0:8000
```

### 터미널 2: FastAPI (포트 8001)

```powershell
cd app\fastapi
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 터미널 3: React (포트 5173)

```powershell
cd app\react
& "C:\Program Files\nodejs\npm.cmd" run dev
```

## 4. 접속

- React: http://localhost:5173
- Django API: http://localhost:8000/api/v1/
- FastAPI Health: http://localhost:8001/internal/v1/health

## 5. 데모 자격

| 역할 | 아이디 | 비밀번호 |
|---|---|---|
| 운영관리자 | staff.ops | demo1234 |
| 시설관리자 | staff.fac | demo1234 |
| 외부관계자 | ext.review | demo1234 |

## 6. smoke test

```powershell
.\scripts\smoke_test.ps1
```

## Docker (선택)

PostgreSQL만 Docker로 실행:

```powershell
docker run -d --name senseplace-db -e POSTGRES_USER=senseplace -e POSTGRES_PASSWORD=senseplace -e POSTGRES_DB=senseplace -p 5432:5432 postgres:16
```

`.env`에 `DATABASE_URL=postgresql://senseplace:senseplace@localhost:5432/senseplace` 설정 후 migrate 재실행.
