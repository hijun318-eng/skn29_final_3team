# Report Assistant 실제 인프라 연결 실행 프롬프트

당신은 Answervice 저장소의 Report Assistant 실연동을 담당하는 시니어 플랫폼·풀스택
엔지니어다. 계획만 작성하지 말고, 안전하게 실행 가능한 범위를 실제로 구현·기동·검증하라.

## 작업 환경

- 저장소: `C:\Users\Playdata\Documents\파이널 프젝젝젝\report-assistant-advanced`
- 브랜치: `codex/report-assistant-advanced-20260824`
- 기준 브랜치: `origin/dev`
- 기존 dirty 변경은 Report Assistant 실구현이므로 모두 보존한다.
- 저장소 루트 `AGENTS.md`와 `docs/README.md`를 전체 읽고 준수한다.
- secret 값은 채팅, 명령 출력, argv, 로그, 문서, Git diff에 노출하지 않는다.

## 현재 검증된 상태

- Backend `http://127.0.0.1:18001/health` HTTP 200
- App PostgreSQL, migration, analysis template registry 준비 완료
- OpenAI key는 저장소 밖
  `C:\Users\Playdata\Documents\파이널 프젝젝젝\.secrets\openai.env`에 보관
- OpenAI `/v1/models` HTTP 200 및 `gpt-5.4-mini` exact 존재 확인
- Backend `/readiness`에서 `model=ready`
- 실제 `report.assistant` strict 계약 호출 1건 성공
- OpenAI key 권한은 `List models=Read`, `Model capabilities=Request`만 허용
- 현재 `/readiness`는 다음 항목 때문에 503이다.
  - `trino`
  - `datahub_transport`
  - `semantic_release`
  - `catalog_manifest`
  - `trino_schema`
  - `auth_session_store`
- 기존 Trino container는 다음 누락으로 재시작 중이다.
  - `TRINO_TLS_KEYSTORE_PASSWORD`
  - `TRINO_INTERNAL_SHARED_SECRET`
  - TLS keystore·CA 및 password DB mount
- 기존 배포 env는 현재 `.env.example`보다 다수의 보안·runtime 항목이 부족하다.
- 기존 DataHub GMS와 source DB container 및 데이터 volume은 보존해야 한다.

## 이번 목표

다음 순서로 실제 Report Assistant E2E 실행 기반을 복구한다.

```text
외부 deployment env 준비
→ 인증 principal/session 준비
→ Trino TLS·password 인증 복구
→ DataHub read actor/token·TLS 연결
→ semantic release·manifest·schema readiness
→ 최신 backend/frontend 기동
→ 실제 로그인
→ Report Assistant 요청·승인·분석·Artifact·Revision·Canvas 검증
```

## 절대 금지

- `docker compose down -v`, `reset.ps1`, volume 삭제·초기화 금지
- 기존 source/App DB 데이터 재적재·seed 실행 금지
- 기존 migration 수정 금지
- production mock, fallback Artifact, 고정 SQL, 질문별 응답 추가 금지
- 기존 container의 secret 원문을 출력하거나 다른 파일로 무단 복제하지 않기
- secret 값을 명령 인자, URL, Git 추적 파일에 넣지 않기
- DataHub token, 로그인 계정, 인증서처럼 지속 권한을 생성·회전하는 최종 동작은
  실행 직전에 대상과 영향을 설명하고 사용자 확인 받기
- `/health` 200이나 화면 렌더링만으로 live E2E 성공 판정 금지
- readiness 503을 성공으로 표현하지 않기

## 1. 시작 전 읽기 전용 확인

다음을 먼저 실행하고 결과를 요약한다.

```powershell
git status --short --branch
docker ps --all --format "{{.Names}}|{{.Status}}|{{.Ports}}"
curl.exe --silent --show-error http://127.0.0.1:18001/readiness
```

다음 파일을 읽는다.

- `AGENTS.md`
- `docs/README.md`
- `infrastructure/database/README.md`
- `docs/e2e_mvp/LOCAL_SETUP.md`
- `infrastructure/database/.env.example`
- `infrastructure/database/scripts/start.ps1`
- `infrastructure/database/scripts/deployment-environment.ps1`
- `infrastructure/database/security/provision-release-principals.ps1`
- `infrastructure/database/security/provision-trino-password-database.ps1`
- `infrastructure/database/security/provision-serving-catalog-secrets.ps1`
- `app/backend/compose.fragment.yml`
- `compose.yml`
- `docs/Report_Assistant_V2_구현_진행_20260824.md`

## 2. 외부 deployment 환경 준비

권위 파일은 저장소 내부 `.env`가 아니라 다음 외부 경로를 사용한다.

```text
C:\Users\Playdata\AppData\Local\Answervice\deployment\answervice.env
C:\Users\Playdata\AppData\Local\Answervice\secrets\
```

규칙:

1. 현재 `infrastructure/database/.env.example`을 기준으로 새 외부 env를 준비한다.
2. 기존 정상 source DB와 App DB credential은 값을 출력하지 않고 보존·이관한다.
3. OpenAI 값은 기존 외부 `openai.env`에서 주입하되 원문을 출력하지 않는다.
4. `CHANGE_ME_`, `REQUIRED_`, 빈 필수값을 이름만 검사하고 값은 출력하지 않는다.
5. 모든 host secret path는 저장소 밖 절대 경로이며 실제 regular file인지 확인한다.
6. 누락값을 임의의 약한 고정 문자열로 채우지 않는다.

외부 env·secret 파일 생성 또는 credential 회전이 필요하면 사용자에게 영향 범위를 설명한 뒤
확인받고, repository가 제공하는 provisioning script를 우선 사용한다.

## 3. 인증 principal 준비

`provision-release-principals.ps1`을 사용한다.

- analyst와 report_admin 계정을 준비한다.
- 비밀번호는 secure prompt로만 입력한다.
- raw password를 출력하거나 문서에 기록하지 않는다.
- 생성 principal JSON에는 PBKDF2 verifier만 존재하는지 구조만 검증한다.
- `AUTH_PRINCIPALS_HOST_FILE`, `AUTH_SESSION_SECRET`, TTL이 외부 env에 존재하는지만 확인한다.
- analyst가 `RUN_ANALYSIS`, report_admin이 보고서 관리 권한을 갖는 기존 role 계약을 유지한다.

## 4. Trino 복구

1. 기존 volume과 source DB를 유지한다.
2. 외부 secret 경로에 다음이 준비됐는지 확인한다.
   - Trino CA PEM
   - Trino server PKCS#12 keystore
   - Trino password DB
3. 승인된 기존 PKI가 없으면 ad-hoc 인증서를 조용히 만들지 말고, 필요한 SAN
   (`trino`, host 검증 주소), 파일 형식, 회전 영향을 사용자에게 설명하고 생성 직전 확인받는다.
4. `provision-trino-password-database.ps1`을 사용해 admin/runtime/DataHub identity를 분리한다.
5. `TRINO_TLS_KEYSTORE_PASSWORD`, `TRINO_INTERNAL_SHARED_SECRET`은 강한 난수로 외부 env에만 저장한다.
6. Trino만 안전하게 재생성하고 `healthy`까지 기다린다.
7. `/v1/info`만으로 판정하지 말고 runtime principal로 TLS·Basic auth를 사용한 terminal
   `SELECT 1`을 실행한다.
8. DDL/DML 거부와 승인 catalog read-only 조회를 확인한다.

## 5. DataHub 연결

1. 기존 GMS가 healthy인지 확인한다.
2. Backend용 read actor와 publish/authoring actor를 분리한다.
3. Backend에는 read token과 read actor만 전달한다.
4. token 생성 또는 권한 변경의 마지막 버튼을 누르기 직전에 사용자 확인을 받는다.
5. `DATAHUB_GMS_URL`, read token, actor URN, CA path를 외부 env에 저장하되 값을 출력하지 않는다.
6. 공개 health endpoint가 아니라 인증 actor의 bounded GraphQL/readback으로 readiness를 검증한다.
7. semantic release, catalog manifest, Trino schema checksum이 모두 같은 release인지 확인한다.
8. 불일치나 누락은 mock·이전 snapshot으로 보충하지 않고 fail closed한다.

## 6. 통합 기동

Superseded stage5 showcase를 확장하지 말고 현재 root `compose.yml`과 기존 backend/frontend
fragment를 사용한다. 외부 env 경로를 명시하고 volume 삭제 없이 필요한 서비스만 기동한다.

기동 전 Compose merge 결과를 secret 없이 확인한다.

```powershell
docker compose --env-file <외부 answervice.env> --profile full config --services
```

그다음 repository의 `infrastructure/database/scripts/start.ps1` 단계 계약을 따른다.

- Core
- DataHub service token provisioning 확인
- Catalog
- Backend/Frontend

실패 시 무작정 전체 재시작하지 말고 최초 `not_ready` dependency의 로그와 설정부터 수정한다.

## 7. 필수 검증

### Dependency readiness

- app_postgres: ready
- migration: ready
- analysis_template_registry: ready
- trino: ready
- datahub_transport: ready
- semantic_release: ready
- catalog_manifest: ready
- trino_schema: ready
- model: ready
- auth_session_store: ready
- report_scheduler: ready 또는 의도된 not_required

### 실제 Report Assistant E2E

실제 로그인 후 기존 승인 Artifact가 연결된 보고서에서 한 요청만 실행한다.

```text
사용자 지시
→ GPT strict change proposal
→ 사용자 승인 전 Trino 호출 0회
→ 승인 뒤 AnalysisController 1회
→ DataHub 승인 metadata 사용
→ SQL Guard 통과
→ Trino query 성공
→ owner/request/query/checksum 결속 APPROVED Artifact
→ CAS 새 Report Revision
→ completed session
→ Canvas 갱신
→ 새로고침 뒤 동일 Revision 복구
```

다음을 같은 request ID로 증빙한다.

- Assistant session ID와 data request ID
- 모델/prompt release 식별자
- Trino query ID
- Artifact ID와 64자리 checksum 형식
- Report definition version/revision

SQL 원문, credential, raw model metadata는 출력하지 않는다.

### 회귀 검증

환경에서 실행 가능한 범위로 다음을 수행한다.

```powershell
python app/backend/scripts/export_openapi.py --check
python scripts/check_code_documentation.py
python scripts/lint_architectural_invariants.py
python scripts/audit_repository_integrity.py
python -m compileall -q app/backend src infrastructure/database/datahub scripts evals tests
git diff --check

Set-Location app/frontend
npm.cmd run test
npm.cmd run build
```

Python dependency가 없어 일부 suite를 실행하지 못하면 임의 설치하거나 PASS로 보고하지 말고,
동일 backend image에서 실행 가능한 테스트와 미실행 항목을 분리한다.

## 8. 중단 조건

다음 중 하나면 더 큰 변경으로 우회하지 말고 멈춰 사용자에게 정확히 보고한다.

- 기존 DB credential을 안전하게 이관할 수 없음
- volume 재생성 또는 데이터 초기화가 필요함
- 승인된 TLS PKI 생성·회전이 필요함
- DataHub service actor/token 생성 권한이 없음
- semantic release 또는 manifest가 현재 Trino schema와 불일치
- 로그인 비밀번호 secure input이 필요함
- 실제 데이터가 개인정보 또는 외부 전송 제한 대상임

## 완료 보고 형식

1. 실제로 연결된 dependency
2. 생성·회전한 credential 종류와 저장 위치(값 제외)
3. 보존한 container와 volume
4. readiness exact 결과
5. 실행한 unit/integration/browser 검증과 개수
6. 미실행 항목과 blocker
7. live E2E 여부
8. 남은 crash-recovery 위험

`model=ready`만으로 Report Agent 전체가 완성됐다고 말하지 않는다. DataHub·Trino·App DB·인증·
Browser가 같은 request ID로 연결됐을 때만 실제 Report Assistant E2E 완료로 판정한다.
