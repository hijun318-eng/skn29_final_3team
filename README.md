# Answervice

> 흩어진 호텔 데이터를 대화로 분석하고 보고서까지 만드는 서비스

[서비스 상세 문서](docs/e2e_mvp/README.md) · [실행 방법](docs/e2e_mvp/LOCAL_SETUP.md)

> **현재 상태:** 기본 runtime은 고정 demo snapshot을 적재하지 않는다. Source DB와 App DB는
> schema만 초기화하고, DataHub와 Trino에서 실제로 발견된 dataset·column·Glossary Term이
> 완전한 경우에만 분석 readiness가 열린다. 따라서 승인된 운영 데이터가 아직 발행되지 않은
> clean volume은 의도적으로 `NOT_READY`다.

현재 제품 범위와 계약은 [`docs/README.md`](docs/README.md)에서 시작한다. 4개 기준 문서는 [`docs/product/`](docs/product/)에 있다. 과거 역할별 handoff, screenshot, fake adapter 테스트는 제품 완료 근거가 아니다.

## 서비스 소개

호텔에서는 객실, 고객, 식음료, 시설, 연회 데이터를 서로 다른 시스템에서 관리합니다. 필요한 자료를 여러 부서에서 모으고 하나의 표로 만드는 데 시간이 오래 걸리고, 같은 매출도 계산 기준에 따라 결과가 달라질 수 있습니다.

Answervice는 사용자가 일상적인 말로 질문하면 관련 데이터를 찾아 분석하고, 결과를 표와 차트로 보여주는 서비스입니다. 분석에 사용한 기간과 데이터 출처를 함께 제공하며, 필요한 결과는 보고서에 바로 활용할 수 있습니다.

예를 들어 다음과 같이 질문할 수 있습니다.

> 2026년 5월과 6월 GOLD 고객의 객실과 식음료 매출을 비교해 줘.

## 주요 기능

| 기능 | 설명 |
|---|---|
| 대화형 데이터 분석 | 복잡한 조회 방법을 몰라도 한국어로 질문할 수 있습니다. |
| 여러 데이터 통합 | 객실, 고객, 식음료, 시설, 연회 데이터를 한 번에 살펴볼 수 있습니다. |
| 기준 확인 | 질문의 기간이나 매출 기준이 분명하지 않으면 사용자에게 다시 확인합니다. |
| 결과와 출처 제공 | 표, 차트, 설명과 함께 사용한 데이터와 기간을 보여줍니다. |
| 보고서 만들기 | 분석 결과를 불러와 보고서를 만들고 다시 실행할 수 있습니다. |
| 사용자별 권한 | 분석 담당자와 보고서 관리자가 필요한 기능만 사용할 수 있습니다. |

## 이용 흐름

```text
질문하기 → 데이터 분석 → 결과 확인 → 보고서 생성
```

1. 사용자가 호텔 운영에 관한 질문을 입력합니다.
2. 기간이나 계산 기준이 모호하면 Answervice가 선택지를 보여줍니다.
3. 여러 시스템의 데이터를 읽기 전용으로 조회합니다.
4. 결과를 표와 차트로 확인하고 데이터 출처도 함께 살펴봅니다.
5. 필요한 분석 결과를 보고서에 추가합니다.

## 서비스 화면

| 분석 화면 | 보고서 화면 |
|---|---|
| `이미지 등록 예정` | `이미지 등록 예정` |

## 서비스 구성

| 영역 | 역할 | 사용 기술 |
|---|---|---|
| 사용자 화면 | 질문, 분석 결과, 차트와 보고서를 보여줍니다. | React |
| 서비스 서버 | 로그인, 권한, 분석과 보고서 기능을 처리합니다. | FastAPI |
| 데이터 연결 | 여러 데이터 저장소를 연결하고 필요한 정보를 찾습니다. | DataHub, Trino |
| AI 분석 | 질문을 이해하고 분석에 필요한 작업을 만듭니다. | LLM |
| 데이터 저장 | 분석 결과, 보고서와 작업 기록을 보관합니다. | Database |
| 실행 환경 | 전체 서비스를 같은 방식으로 실행합니다. | Docker Compose |

## 로컬 운영 경로 재현

아래 절차는 schema-only database stack과 동적 metadata discovery 경로를 재현한다.
질문·지표 전용 seed나 고정 serving SQL을 설치하는 절차가 아니다.

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
설정한다. 운영 기본값은 저장소 내부 `.env`를 묵시적으로 읽지 않는다. 로컬 개발에서는
gitignored `.env`를 `-AllowRepositoryLocalDevelopment`와 함께 명시할 수 있다. Trino server keystore와
CA PEM은 운영 PKI에서 발급해 저장소 밖 절대 경로로 설정하며 인증서 SAN에는 `trino`와
`127.0.0.1`을 포함한다. Node2 전용 변수 네 개가 모두 비면 Node 1·2·Repair·3과
Report Assistant가 primary `gpt-5.4-mini` route를 공유한다. Node2를 별도 endpoint로
분리할 때는 `NODE2_MODEL_PROVIDER`, `NODE2_MODEL_ENDPOINT`, `NODE2_MODEL_API_TOKEN`,
`NODE2_MODEL`을 모두 설정하며 일부 설정은 fail-closed한다.

다음 script는 deployment environment의 두 로그인 계정을 PBKDF2-SHA256으로
해시하고 Trino의 세 역할을 별도 PBKDF2 verifier로 만든다. 인증
principal은 운영에서는 저장소 밖의 명시적 경로에 생성한다. 로컬 개발 경로를 쓰는 경우
명시적 switch와 `.gitignore` 검증을 통과해야 하며 정적 principal JSON으로 fallback하지 않는다.

```powershell
powershell -ExecutionPolicy Bypass `
  -File infrastructure/database/security/provision-release-principals.ps1 `
  -EnvPath $deploymentEnv `
  -PrincipalPath (Join-Path $secretDirectory 'principals.json')
powershell -ExecutionPolicy Bypass `
  -File infrastructure/database/security/provision-trino-password-database.ps1 `
  -EnvPath $deploymentEnv `
  -PasswordDatabasePath (Join-Path $secretDirectory 'trino-password.db')
powershell -ExecutionPolicy Bypass `
  -File infrastructure/database/security/provision-serving-catalog-secrets.ps1 `
  -EnvPath $deploymentEnv `
  -CredentialsPath (Join-Path $secretDirectory 'serving-catalog-bootstrap.json') `
  -TokenPublicKeyPath (Join-Path $secretDirectory 'serving-catalog-token-public.pem') `
  -TokenPrivateKeyPath (Join-Path $secretDirectory 'serving-catalog-token-private.pem')
powershell -NoProfile -ExecutionPolicy Bypass `
  -File infrastructure/database/scripts/start.ps1 `
  -EnvFilePath $deploymentEnv -Stage Core
# loopback DataHub UI/OIDC에서 read 전용과 publish 전용 service actor·PAT를 각각
# 발급하고 최소권한 정책을 연결한 뒤, 외부 $deploymentEnv에 네 값을 기록한다.
powershell -NoProfile -ExecutionPolicy Bypass `
  -File infrastructure/database/scripts/start.ps1 `
  -EnvFilePath $deploymentEnv -Stage Catalog
```

`Core` 단계는 clean volume에서 schema와 source read-only 계정, 영속 serving catalog,
Trino, 인증된 DataHub
GMS/UI까지만 준비한다. `Catalog` 단계는 서로 다른 service actor·PAT를 실제 GMS에서
확인한 뒤 runtime recipe, dataset `semanticContent`, embedding을 순서대로 갱신한다.
업무 row나 특정 질문용 serving view는 생성하지 않으며, 발견·권한·semantic 계약 중
하나라도 불완전하면 성공 marker와 Backend readiness가 fail-closed된다.

`full` 운영 경로는 위 semantic overlay를 항상 함께 사용한다. Overlay 없는 기동은
OpenSearch 기반 rollback 경로이며 동적 schema linking 완료 근거로 사용할 수 없다.
첫 semantic index 전환과 검증 순서는
[`infrastructure/database/datahub/SEMANTIC_SEARCH.md`](infrastructure/database/datahub/SEMANTIC_SEARCH.md)를 따른다.

첫 기동은 DataHub와 Source DB 초기화 때문에 시간이 걸릴 수 있다. 준비 상태는 다음처럼 확인한다.

- Frontend: `http://127.0.0.1:13000`
- Backend: `http://127.0.0.1:28000`
- Trino: `https://127.0.0.1:18443` (외부 CA 검증과 Basic authentication 필수)
- DataHub UI: `http://127.0.0.1:19002` (loopback 전용)
- DataHub GMS API: `https://127.0.0.1:18081` (외부 CA 검증과 Bearer authentication 필수)

Docker volume이나 외부 deployment env, principal·Trino secret을 다른 환경에 복사해 배포
근거로 삼지 않는다. release evidence는 live discovery 결과와 승인된 bundle에서 다시
생성한다.

## 데이터 보호

- 실제 고객 데이터 대신 프로젝트용 합성 데이터를 사용합니다.
- 원본 데이터는 읽기 전용으로 조회합니다.
- 사용자 역할에 따라 화면과 기능 접근을 제한합니다.
- 비밀번호와 API key 같은 비밀정보는 저장소에 올리지 않습니다.

## 팀 구성

| 팀원 | GitHub | 담당 영역 |
|---|---|---|
| 박준희 | [hijun318-eng](https://github.com/hijun318-eng) | 프로젝트 통합, 실행 환경, 품질 관리 |
| 정승 | [jseung89](https://github.com/jseung89) | 데이터 통합 관리, 데이터 연결, 합성 데이터 관리 |
| 윤대성 | [YoonDaeSung-01](https://github.com/YoonDaeSung-01) | AI 분석 과정, 질문 처리, 모델 평가 |
| 김재홍 | [kkix1025](https://github.com/kkix1025) | Backend, 로그인과 권한, 데이터 저장 |
| 송민지 | [nowis1350](https://github.com/nowis1350) | 사용자 화면, 분석 결과, 보고서 기능 |

## 저장소 안내

- `compose.yml`: 전체 서비스 진입점
- `infrastructure/database/compose.yml`: App DB, 5개 Source DB, Trino
- `infrastructure/database/datahub/compose.consumer.yml`: DataHub
- `app/backend/compose.fragment.yml`, `app/frontend/compose.fragment.yml`: Backend·Frontend
- `infrastructure/database/sql/ddl/`, `infrastructure/database/sql/app/`: schema-only 런타임 DDL
- `infrastructure/database/datahub/recipes/*.runtime.yml`: runtime metadata discovery 설정
- `docs/product/`: 현재 제품·PRD·사용자 흐름·아키텍처 기준
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

## 더 알아보기

- [E2E 문서 안내](docs/e2e_mvp/README.md): 서비스 범위와 상세 설계
- [사용자 흐름](docs/e2e_mvp/derived/02_Golden_Path_유저플로우.md): 질문부터 결과와 보고서까지의 흐름
- [로컬 실행 가이드](docs/e2e_mvp/LOCAL_SETUP.md): 설치, 실행과 종료 방법
