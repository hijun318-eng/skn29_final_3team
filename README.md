# Answervice

Answervice는 자연어 질문을 승인된 DataHub Context와 read-only Trino SQL로 분석하고, 결과와 근거를 저장된 Analysis·Report로 연결하는 서비스다.

> **현재 상태:** 기본 runtime은 고정 demo snapshot을 적재하지 않는다. Source DB와 App DB는
> schema만 초기화하고, DataHub와 Trino에서 실제로 발견된 dataset·column·Glossary Term이
> 완전한 경우에만 분석 readiness가 열린다. 따라서 승인된 운영 데이터가 아직 발행되지 않은
> clean volume은 의도적으로 `NOT_READY`다.

현재 제품 범위와 계약은 [`docs/README.md`](docs/README.md)에서 시작한다. 4개 기준 문서는 [`docs/product/`](docs/product/)에 있다. 과거 역할별 handoff, screenshot, fake adapter 테스트는 제품 완료 근거가 아니다.

## 로컬 운영 경로 재현

아래 절차는 schema-only database stack과 동적 metadata discovery 경로를 재현한다.
질문·지표 전용 seed나 고정 serving SQL을 설치하는 절차가 아니다.

필수 도구는 Git, Docker Desktop, PowerShell이다. 모델 호출을 위해 OpenAI-compatible API key도 필요하다.

```powershell
git clone https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team

$deploymentDirectory = Join-Path $env:LOCALAPPDATA 'Answervice\deployment'
$secretDirectory = Join-Path $env:LOCALAPPDATA 'Answervice\secrets'
New-Item -ItemType Directory -Force -Path $deploymentDirectory,$secretDirectory | Out-Null
$deploymentEnv = Join-Path $deploymentDirectory 'answervice.env'
Copy-Item infrastructure/database/.env.example $deploymentEnv
```

외부 `$deploymentEnv`의 모든 `CHANGE_ME_`·`REQUIRED_` 값을 교체하고 `OPENAI_API_KEY`를
설정한다. 저장소 내부 `.env`는 만들거나 묵시적으로 읽지 않는다. Trino server keystore와
CA PEM은 운영 PKI에서 발급해 저장소 밖 절대 경로로 설정하며 인증서 SAN에는 `trino`와
`127.0.0.1`을 포함한다. Node2 전용 변수 네 개가 모두 비면 Node 1·2·Repair·3과
Report Assistant가 primary `gpt-5.4-mini` route를 공유한다. Node2를 별도 endpoint로
분리할 때는 `NODE2_MODEL_PROVIDER`, `NODE2_MODEL_ENDPOINT`, `NODE2_MODEL_API_TOKEN`,
`NODE2_MODEL`을 모두 설정하며 일부 설정은 fail-closed한다.

다음 script는 외부 deployment environment의 두 로그인 계정을 PBKDF2-SHA256으로
해시하고 Trino의 세 역할을 별도 PBKDF2 verifier로 만든다. 인증
principal은 저장소 밖의 명시적 경로에만 생성되며, 그 절대 경로가 외부 env에 기록된다.
저장소 안의 정적 principal JSON으로 fallback하지 않는다.

```powershell
powershell -ExecutionPolicy Bypass `
  -File infrastructure/database/security/provision-release-principals.ps1 `
  -EnvPath $deploymentEnv `
  -PrincipalPath (Join-Path $secretDirectory 'principals.json')
powershell -ExecutionPolicy Bypass `
  -File infrastructure/database/security/provision-trino-password-database.ps1 `
  -EnvPath $deploymentEnv `
  -PasswordDatabasePath (Join-Path $secretDirectory 'trino-password.db')
powershell -NoProfile -ExecutionPolicy Bypass `
  -File infrastructure/database/scripts/start.ps1 `
  -EnvFilePath $deploymentEnv -Stage Core
# loopback DataHub UI/OIDC에서 read 전용과 publish 전용 service actor·PAT를 각각
# 발급하고 최소권한 정책을 연결한 뒤, 외부 $deploymentEnv에 네 값을 기록한다.
powershell -NoProfile -ExecutionPolicy Bypass `
  -File infrastructure/database/scripts/start.ps1 `
  -EnvFilePath $deploymentEnv -Stage Catalog
```

`Core` 단계는 clean volume에서 schema와 source read-only 계정, Trino, 인증된 DataHub
GMS/UI까지만 준비한다. `Catalog` 단계는 서로 다른 service actor·PAT를 실제 GMS에서
확인한 뒤 runtime recipe, dataset `semanticContent`, embedding을 순서대로 갱신한다.
업무 row나 특정 질문용 serving view는 생성하지 않으며, 발견·권한·semantic 계약 중
하나라도 불완전하면 성공 marker와 Backend readiness가 fail-closed된다.

`full` 운영 경로는 위 semantic overlay를 항상 함께 사용한다. Overlay 없는 기동은
OpenSearch 기반 rollback 경로이며 동적 schema linking 완료 근거로 사용할 수 없다.
첫 semantic index 전환과 검증 순서는
[`infrastructure/database/datahub/SEMANTIC_SEARCH.md`](infrastructure/database/datahub/SEMANTIC_SEARCH.md)를 따른다.

첫 기동은 DataHub와 Source DB 초기화 때문에 시간이 걸릴 수 있다. 준비 상태는 다음처럼 확인한다.

```powershell
Invoke-RestMethod http://127.0.0.1:28000/readiness | ConvertTo-Json -Depth 5
```

- Frontend: `http://127.0.0.1:13000`
- Backend: `http://127.0.0.1:28000`
- Trino: `https://127.0.0.1:18443` (외부 CA 검증과 Basic authentication 필수)
- DataHub UI: `http://127.0.0.1:19002` (loopback 전용)
- DataHub GMS API: `https://127.0.0.1:18081` (외부 CA 검증과 Bearer authentication 필수)

Docker volume이나 외부 deployment env, principal·Trino secret을 다른 환경에 복사해 배포
근거로 삼지 않는다. release evidence는 live discovery 결과와 승인된 bundle에서 다시
생성한다.

## 실행 파일 구조

- `compose.yml`: 전체 서비스 진입점
- `infrastructure/database/compose.yml`: App DB, 5개 Source DB, Trino
- `infrastructure/database/datahub/compose.consumer.yml`: DataHub
- `app/backend/compose.fragment.yml`, `app/frontend/compose.fragment.yml`: Backend·Frontend
- `infrastructure/database/sql/ddl/`, `infrastructure/database/sql/app/`: schema-only 런타임 DDL
- `infrastructure/database/datahub/recipes/*.runtime.yml`: runtime metadata discovery 설정
- `docs/product/`: 현재 제품·PRD·사용자 흐름·아키텍처 기준
- `docs/reference/Walkerhill_V4.1_SQL_검토.md`: 현재 실행 경로가 아닌 과거 후보의 NO-GO 감사 기록
- `app/backend/migrations/versions/`: App DB 증분 migration

`infrastructure/database/releases/`와 `infrastructure/database/sql/data/`는 재현성과
감사를 위한 불변 과거 배포·seed 아카이브다. 현재 Compose, bootstrap, CI가 이를
실행하거나 운영 fallback으로 참조하지 않는다.

## Git에 포함하지 않는 값

다음 값은 저장소에 commit하지 않는다.

- 저장소 밖 deployment env와 `TRINO_*_HOST_FILE`이 가리키는 PKI/password 파일
- `AUTH_PRINCIPALS_HOST_FILE`이 가리키는 저장소 외부 principal secret
- `OPENAI_API_KEY`와 사설 OpenAI-compatible endpoint 인증정보
- 개인별 DB 비밀번호와 Analyst·Report Admin 로그인 비밀번호

팀원이 같은 외부 모델 endpoint를 사용해야 한다면 외부 deployment env 또는 `OPENAI_API_KEY`와,
기본값이 아닌 경우 `OPENAI_ENDPOINT`를 별도 보안 채널로 전달한다. principal secret은
각 환경에서 provisioning script로 새로 생성하며 Git이나 release archive에 포함하지 않는다.

## 검증

```powershell
python -m pytest -p no:cacheprovider tests/backend tests/ai tests/data tests/integration -q
Set-Location app/frontend
npm ci
npm run test:contracts
npm run build
```
