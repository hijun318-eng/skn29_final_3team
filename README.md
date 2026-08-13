# Answervice

Answervice는 자연어 질문을 승인된 DataHub Context와 read-only Trino SQL로 분석하고, 결과와 근거를 저장된 Analysis·Report로 연결하는 서비스다.

현재 제품 범위와 계약은 [`docs/e2e_mvp/README.md`](docs/e2e_mvp/README.md)에서 시작한다. 과거 역할별 handoff와 AI 작업 문서는 제품 실행 기준이 아니다.

## 로컬 환경 재현

필수 도구는 Git, Docker Desktop, PowerShell이다. 모델 호출을 위해 OpenAI-compatible API key도 필요하다.

```powershell
git clone https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team
git switch daesung

Copy-Item infrastructure/database/.env.example infrastructure/database/.env
```

팀에서 전달받은 `infrastructure/database/.env`를 사용하거나, 직접 만들 때는 모든 `CHANGE_ME_` 값을 교체하고 `OPENAI_API_KEY`를 설정한다. 기본 모델은 Node 1·2·Repair·3 모두 `gpt-5.4-mini`이며, endpoint나 모델을 바꾸려는 경우에만 `OPENAI_ENDPOINT`, `OPENAI_MODEL`, `NODE2_MODEL`을 수정한다.

다음 script는 `.env`의 두 로그인 계정을 PBKDF2-SHA256으로 해시해 `hotel_analyst`·`report_admin` principal 파일을 생성한다. 비밀번호와 principal 파일은 Git에서 제외된다.

```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/database/security/provision-release-principals.ps1
docker compose --env-file infrastructure/database/.env --profile full up -d --build
docker compose --env-file infrastructure/database/.env --profile full ps
```

첫 기동은 DataHub와 Source DB 초기화 때문에 시간이 걸릴 수 있다. 준비 상태는 다음처럼 확인한다.

```powershell
Invoke-RestMethod http://127.0.0.1:28000/readiness | ConvertTo-Json -Depth 5
```

- Frontend: `http://127.0.0.1:13000`
- Backend: `http://127.0.0.1:28000`
- Trino: `http://127.0.0.1:18080`
- DataHub: `http://127.0.0.1:19002`

동일한 schema와 합성 snapshot은 추적된 Compose·migration·`docs/e2e_mvp/derived/service_demo_v3/` seed 파일로 생성한다. Docker volume이나 로컬 `.env`를 복사할 필요는 없다.

## 실행 파일 구조

- `compose.yml`: 전체 서비스 진입점
- `infrastructure/database/compose.yml`: App DB, 5개 Source DB, Trino
- `infrastructure/database/datahub/compose.consumer.yml`: DataHub
- `app/backend/compose.fragment.yml`, `app/frontend/compose.fragment.yml`: Backend·Frontend
- `infrastructure/database/sql/ddl/`, `infrastructure/database/sql/app/`: 런타임 DDL·기준 데이터
- `docs/e2e_mvp/derived/service_demo_v3/01_*`~`05_*`: 현재 Source DB seed
- `app/backend/migrations/versions/`: App DB 증분 migration

`infrastructure/database/releases/`와 `infrastructure/database/sql/data/`는 과거 배포·seed 근거이며 현재 루트 Compose가 마운트하지 않는다.

## Git에 포함하지 않는 값

다음 값은 저장소에 commit하지 않는다.

- `infrastructure/database/.env`
- `infrastructure/database/security/answervice_auth_principals.local.json`
- `OPENAI_API_KEY`와 사설 OpenAI-compatible endpoint 인증정보
- 개인별 DB 비밀번호와 Analyst·Report Admin 로그인 비밀번호

팀원이 같은 외부 모델 endpoint를 사용해야 한다면 `.env` 또는 `OPENAI_API_KEY`와, 기본값이 아닌 경우 `OPENAI_ENDPOINT`를 별도 보안 채널로 전달한다. principal 파일은 provisioning script로 각자 생성할 수 있다.

## 검증

```powershell
python -m pytest tests/backend tests/ai tests/data tests/integration -q
Set-Location app/frontend
npm ci
npm run test:contracts
npm run build
```
