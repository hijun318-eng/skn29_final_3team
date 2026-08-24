# Answervice 로컬 실행 가이드

이 문서는 Answervice 전체 E2E 환경을 로컬에서 준비하고 실행·검증·종료하는 절차를 설명한다. 프로젝트 소개와 기능은 repository root `README.md`를 먼저 확인한다.

## 1. 사전 준비

- Git
- Docker Desktop과 Docker Compose
- PowerShell
- 실제 모델 검증용 OpenAI-compatible API key

Backend 단독 테스트를 실행하려면 Python 3.12와 `app/backend/requirements.txt`의 dependency가 필요하다. Frontend build에는 Node.js와 npm이 필요하다.

전체 Compose는 DataHub와 여러 Source DB를 함께 실행하므로 Docker Desktop에 충분한 CPU·memory·disk를 할당한다. 필요한 정확한 자원은 실행 환경에 따라 달라지므로 임의의 최소값을 보장하지 않는다.

## 2. 저장소 받기

```powershell
git clone --branch dev --single-branch https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team
```

기존 clone을 사용한다면 현재 branch와 변경 상태를 먼저 확인한다.

```powershell
git branch --show-current
git status --short
```

## 3. 환경 변수 준비

예시 파일을 로컬 `.env`로 복사한다.

```powershell
Copy-Item infrastructure/database/.env.example infrastructure/database/.env
```

`infrastructure/database/.env`에서 다음을 확인한다.

- 모든 `CHANGE_ME_` 비밀번호 교체
- `OPENAI_API_KEY` 설정
- 기본값이 아닌 provider를 사용할 때만 `OPENAI_ENDPOINT`, `OPENAI_MODEL`, `NODE2_MODEL` 변경

기본 model 설정은 Node 1·2·Repair·3의 `gpt-5.4-mini`다. `.env`, API key와 비밀번호를 commit하지 않는다.

## 4. 로그인 principal 생성

다음 script는 `.env`의 로그인 정보를 PBKDF2-SHA256으로 처리해 로컬 principal 파일을 생성한다.

```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/database/security/provision-release-principals.ps1
```

생성 파일 `infrastructure/database/security/answervice_auth_principals.local.json`과 비밀번호는 Git에서 제외된다.

기본 역할은 다음과 같다.

- `analyst`: 분석과 본인 Report 사용
- `report_admin`: Report 관리 사용

로그인 ID와 비밀번호는 `.env`에서 확인하며 문서나 로그에 복사하지 않는다.

## 5. 전체 서비스 실행

repository root에서 실행한다.

```powershell
docker compose --env-file infrastructure/database/.env --profile full up -d --build
docker compose --env-file infrastructure/database/.env --profile full ps
```

첫 기동은 DataHub와 Source DB 초기화 때문에 시간이 걸릴 수 있다. 초기화 중인 서비스를 실패로 단정하지 말고 container 상태와 log를 함께 확인한다.

## 6. 준비 상태 확인

```powershell
Invoke-RestMethod http://127.0.0.1:28000/readiness | ConvertTo-Json -Depth 5
```

주요 주소는 다음과 같다.

| 서비스 | 주소 |
|---|---|
| Frontend | `http://127.0.0.1:13000` |
| Backend | `http://127.0.0.1:28000` |
| Backend readiness | `http://127.0.0.1:28000/readiness` |
| Trino | `http://127.0.0.1:18080` |
| DataHub | `http://127.0.0.1:19002` |

프런트엔드만 빠르게 수정할 때는 Backend Compose가 `127.0.0.1:28000`에서 실행 중인 상태로 다음 명령을 사용한다.

```powershell
Set-Location app/frontend
npm.cmd run dev:compose
```

이 모드는 `http://127.0.0.1:5173`의 `/api` 요청을 Backend로 proxy하므로 브라우저 코드에 Backend 주소를 넣지 않는다. 정식 `13000` 컨테이너도 `/api`를 Nginx가 내부 `backend:8000`으로 전달한다. 5173은 소스 변경이 즉시 반영되지만 13000은 `docker compose ... up -d --build frontend`로 image를 다시 만들어야 반영된다.

Backend가 `healthy`여도 dependency별 readiness가 `ready`인지 확인한다. 실제 E2E 성공은 화면 접속만으로 판정하지 않는다.

## 7. 데이터 재현 기준

동일한 schema와 합성 snapshot은 다음 추적 파일로 생성한다.

- root `compose.yml`과 포함된 service fragment
- `infrastructure/database/sql/ddl/`
- `infrastructure/database/sql/app/`
- `app/backend/migrations/versions/`
- `docs/e2e_mvp/derived/service_demo_v3/`

Docker volume이나 다른 팀원의 `.env`를 복사해 재현 근거로 사용하지 않는다. `infrastructure/database/releases/`와 `infrastructure/database/sql/data/`는 과거 archive이며 현재 root Compose 초기화 기준이 아니다.

## 8. 검증

Backend·AI·Data·통합 테스트:

```powershell
python -m pytest tests/backend tests/ai tests/data tests/integration -q
```

Report 테스트:

```powershell
python -m pytest tests/report tests/backend/test_report_registration.py tests/backend/test_report_scheduler.py -q
```

Frontend contract와 production build:

```powershell
Set-Location app/frontend
npm ci
npm run test:contracts
npm run build
Set-Location ../..
```

OpenAPI drift 확인:

```powershell
python app/backend/scripts/export_openapi.py --check
```

테스트를 실행하지 않았으면 `Pass`로 기록하지 않는다. Python version이나 dependency가 맞지 않아 실행할 수 없으면 `Blocked`와 원인을 남긴다.

## 9. 문제 확인

Container 상태:

```powershell
docker compose --env-file infrastructure/database/.env --profile full ps
```

특정 서비스 log:

```powershell
docker compose --env-file infrastructure/database/.env --profile full logs --tail 200 <service-name>
```

확인 순서는 다음과 같다.

1. `.env` 필수 값과 비밀번호가 남아 있는지 확인
2. Backend `/readiness`에서 준비되지 않은 dependency 확인
3. 해당 container의 health와 log 확인
4. migration head와 Application PostgreSQL 연결 확인
5. DataHub dataset과 Trino catalog 준비 상태 확인
6. 외부 model endpoint와 key 확인

오류를 fake·fixture·이전 Artifact로 대체해 성공 처리하지 않는다.

## 10. 종료와 초기화

서비스 종료:

```powershell
docker compose --env-file infrastructure/database/.env --profile full down
```

Volume 삭제가 필요한 초기화는 합성 개발 데이터만 존재하고 보존할 결과가 없음을 확인한 뒤 `infrastructure/database/scripts/reset.ps1 -Force`를 사용한다. 이 작업은 로컬 DB volume을 삭제하므로 일반 종료 명령처럼 사용하지 않는다.

## 11. Git에 포함하지 않는 값

- `infrastructure/database/.env`
- `infrastructure/database/security/answervice_auth_principals.local.json`
- `OPENAI_API_KEY`
- 사설 OpenAI-compatible endpoint 인증정보
- 개인별 DB·로그인 비밀번호

팀원이 같은 endpoint를 사용해야 하면 Git이 아닌 승인된 보안 채널로 전달한다.
