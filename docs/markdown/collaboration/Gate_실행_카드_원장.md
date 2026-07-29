# Gate 실행 카드 원장

| 항목 | 내용 |
|---|---|
| 문서 설명 | 역할별 자율 구현 범위와 Gate 중단·통합 조건을 관리하는 실행 카드 원장 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.3 |
| 문서 기준일 | 2026-07-29 17:35 |
| 작성·수정 | 3팀 사용자 승인·Codex 반영 |

## 사용 원칙

1. 세부 카드 `R*-**`는 WBS 추적 단위이며, 실행 승인은 역할·통합 Wave별 `EXECUTION_BUNDLE_ID` 단위로 한다.
2. 담당자는 승인된 `TASK_CARD_RANGE`를 번호 순서대로 수행하고 카드 사이에 별도 승인을 기다리지 않는다.
3. `CHECKPOINT_GATES`에서는 계약·증거를 확인한 뒤 같은 Wave의 다음 카드로 계속 진행한다. 현재 일정에서는 I0와 Wave 4의 RC1을 사용한다.
4. `TARGET_INTEGRATION_GATE` 도달, 카드 범위 완료, 허용 경로 밖 변경 필요, 계약·보안 충돌, 필수 검증 실패 시 멈춘다.
5. 목표 통합 Gate 종료 시 변경 파일, 완료 카드, 계약·fixture version, 검증 결과, change request, 남은 위험을 제출한다.
6. R1이 통합 결과와 다음 실행 묶음을 승인하기 전에는 다음 Wave 범위로 넘어가지 않는다.
7. `PLANNED` 묶음은 일정 예약이며 실행 승인이 아니다. Wave 시작 시 `BASE_SHA`와 계약 버전을 채워 `READY`로 바꾼다.
8. 아직 동결되지 않은 계약은 공란 대신 `DRAFT` 또는 `N/A — 사유`로 기록한다.

상태는 다음과 같이 사용한다.

| 상태 | 의미 |
|---|---|
| `READY_TO_ISSUE` | 범위·완료 조건은 준비됐으며 기준 문서 반영 SHA 확인 후 발행 가능 |
| `READY` | R1이 기준 SHA와 버전을 승인해 실행 가능 |
| `IN_PROGRESS` | 역할 소유 경로에서 수행 중 |
| `REVIEW` | Gate handoff 제출 후 통합 판정 대기 |
| `BLOCKED` | 중단 조건 발생 |
| `MERGED_DEV` | 개인 branch 결과가 `dev`에 병합됨 |
| `VERIFIED_GATE` | 통합 Gate 검증 완료 |
| `PLANNED` | 미래 Gate 예약, 실행 불가 |

## 카드 상세도 기준

실행 묶음은 아래 항목을 모두 갖춰야 `READY`로 발행할 수 있다.

| 구분 | 필수 내용 | 발행 차단 조건 |
|---|---|---|
| 식별 | 역할·담당자·branch·`EXECUTION_BUNDLE_ID`·`TARGET_INTEGRATION_GATE`·`CHECKPOINT_GATES`·`TASK_CARD_RANGE` | 역할 또는 범위가 둘 이상으로 해석됨 |
| 기준선 | repository root·base branch·`BASE_SHA` | SHA가 없거나 팀원이 확인할 수 없음 |
| 입력 계약 | I0·공통·schema·model·OpenAPI·UI·Report·fixture 중 해당 version | 공란 또는 서로 다른 version 혼용 |
| 작업 순서 | 세부 카드별 입력·행동·산출물·완료 조건 | 카드 번호만 있고 결과 정의가 없음 |
| 수정 권한 | 실제 경로 기준 `ALLOWED_PATHS`·`FORBIDDEN_PATHS` | 다른 역할 파일과 경계가 겹침 |
| 검증 | 복사해 실행할 수 있는 formatter·lint·type check·unit/contract test·build 명령 | “테스트한다” 같은 서술만 있음 |
| 중단 | 목표 통합 Gate·범위·계약·보안·검증 실패 조건 | 실패 후 임의 계속 가능 |
| handoff | 받을 역할·전달 파일/계약/version·미실행 항목 | 소비자나 전달 형식이 없음 |
| 외부 권한 | 설치·download·비용·배포·데이터 전송·Git 권한 | 승인 여부가 불명확 |
| 종료 보고 | 변경 파일·완료 카드·version·검증·change request·잔여 위험 | Gate 판정 근거가 남지 않음 |

카드 길이는 고정하지 않는다. 다만 위 항목과 세부 카드별 완료 조건이 빠지면 짧은 카드로 판정하고 발행하지 않는다.

## 기획서 추적성 기준

각 실행 묶음은 역할 매뉴얼뿐 아니라 `docs/Answervice_기획서.md`의 다음 영역과 연결한다.

| 기획서 영역 | 실행 묶음 | 카드에 반영할 핵심 |
|---|---|---|
| §1·3·5·19 범위·우선순위 | R1-W1, 전 역할 | P0/P1 우선, P2·고객 360 별도 승인, 완료 증거 |
| §7·9 실행 아키텍처·Guarded Text-to-SQL | R3-W1~W3, R4-W1~W3 | 결정론적 Controller, Node 책임 분리, G1·G2·G3, Context·Cache 계약 |
| §8·14 DataHub·Trino·합성 데이터 | R2-W1~W4 | 5 source·4 engine, URN/FQN, read-only, seed·schema·identity·시간 무결성 |
| §10 sLLM·RunPod | R3-W1~W4, R1-W3~W4 | 동일 조건 Base/adapter 비교, Node별 model 격리, 비용·fallback |
| §11 자동 리포팅 | R5-W1~W4, R4-W4 | definition/run 분리, artifact 왕복, 수동 성공 후 schedule, partial |
| §15·16 UI·기술 구조 | R5-W1~W4 | React+TypeScript+Vite, 중립 token, 상태·근거·접근성·반응형 |
| §17 보안·감사·복구 | R4-W3~W4, R1-W4 | role policy, mask·redaction, trace, retention, SBOM/SCA, backup restore |
| §18 평가 | R1·R2·R3 전 Wave, R4·R5 회귀 | 필수 30건, gold 120건, 실행 결과·중단·출처·재현성 |
| §20·22 개발 순서·결정 | R1 전 Wave | 선행 조건, 되돌림 지점, profile·library·model 채택 기록 |

## 역할별 기본 경로

Gate 시작 시 실제 존재 경로와 소유권을 다시 확인한다. 아래 경로 밖 변경은 change request로 넘긴다.

| 역할 | 기본 `ALLOWED_PATHS` | 주요 `FORBIDDEN_PATHS` |
|---|---|---|
| R1 | `AGENTS.md`, root Compose·env·CI, `.githooks/**`, `tests/integration/**`, 공통 계약·WBS·협업 문서 | R2~R5 서비스 내부 구현 |
| R2 | source DDL·seed, `infrastructure/database/trino/**`, DataHub 설정, `src/data/**`, `tests/data/**` | app DB, 공통 FastAPI, AI model·prompt, frontend·Report |
| R3 | `src/ai/**`, `src/modelops/**`, `evals/**`, `tests/ai/**`, model serving 설정 | DB 원천, G1·G2·G3, 공통 FastAPI, frontend |
| R4 | `app/fastapi/**`, `src/backend/**`, `src/control_plane/**`, `tests/backend/**`, app DB·migration | source DDL·seed, AI model·prompt, frontend, root Compose |
| R5 | I0의 frontend 후보, I0에서 확정한 활성 frontend, `src/report/**`, `tests/frontend/**`, `tests/report/**`, Report proposal | root Compose, 공통 FastAPI entrypoint·Alembic chain, source DB·AI model |

R5는 I0에서만 `app/react/**`와 `app/enterprise-react/**`를 함께 조사할 수 있다. 구현 변경은 결정된 활성 frontend 하나에만 적용한다.

## 전체 실행 묶음

카드 집합에 같은 세부 카드가 다시 나타나는 경우는 새 기능 재승인이 아니라 다음 Gate에서의 연결·회귀·동결 작업을 뜻한다.

| 실행 묶음 | Wave·기간 | 역할 | checkpoint → 목표 통합 Gate | `TASK_CARD_RANGE` | 통합 시 제출물 | 초기 상태 |
|---|---|---|---|---|---|---|
| R1-W1 | Wave 1·07/29~08/07 | R1 | I0 → I1 | R1-00~08 | 역할·범위·소유권·공통 계약·Compose·env·CI·I1 판정 | `READY` |
| R2-W1 | Wave 1·07/29~08/07 | R2 | I0 → I1 | R2-00~08 | registry·논리/물리 모델·seed·identity·quality·read-only | `READY` |
| R3-W1 | Wave 1·07/29~08/07 | R3 | I0 → I1 | R3-00~03, R3-07 | AI 범위·Node schema·fake·Node 1 baseline·Prompt Registry | `READY` |
| R4-W1 | Wave 1·07/29~08/07 | R4 | I0 → I1 | R4-00~05 | backend 경계·OpenAPI·auth·DB·migration·Controller skeleton | `READY` |
| R5-W1 | Wave 1·07/29~08/07 | R5 | I0 → I1 | R5-00~04, R5-08 | 활성 frontend·IA·typed client·mock·Chat 상태·Report 계약 | `READY` |
| R1-W2 | Wave 2·08/10~08/14 | R1 | 없음 → I2 | R1-07, R1-09 | 수용 subset·통합 profile·deterministic trace 판정 | `PLANNED` |
| R2-W2 | Wave 2·08/10~08/14 | R2 | 없음 → I2 | R2-09~16 | PMS/CRM catalog·JOIN·adapter·정답 hash | `PLANNED` |
| R3-W2 | Wave 2·08/10~08/14 | R3 | 없음 → I2 | R3-02, R3-06, R3-08 | deterministic fake·설명 schema·평가 runner | `PLANNED` |
| R4-W2 | Wave 2·08/10~08/14 | R4 | 없음 → I2 | R4-04~13, R4-15 | Template→Context→G1→G2→Trino→G3→Artifact trace | `PLANNED` |
| R5-W2 | Wave 2·08/10~08/14 | R5 | 없음 → I2 | R5-03~07 | Chat·상태·Evidence·표·차트·Artifact bridge | `PLANNED` |
| R1-W3 | Wave 3·08/17~08/21 | R1 | 없음 → I3 | R1-07, R1-10 | gold 관리·일반 질문·보안 기준선 판정 | `PLANNED` |
| R2-W3 | Wave 3·08/17~08/21 | R2 | 없음 → I3 | R2-09~18 | 5 source·recipe·catalog·JOIN·watermark·fixture | `PLANNED` |
| R3-W3 | Wave 3·08/17~08/21 | R3 | 없음 → I3 | R3-03~10, R3-12~14 | Node 1·2·2′·3·Base 비교·serving·trace | `PLANNED` |
| R4-W3 | Wave 3·08/17~08/21 | R4 | 없음 → I3 | R4-08~15, R4-18 | model client·repair 1회·Cache·Audit·권한 | `PLANNED` |
| R5-W3 | Wave 3·08/17~08/21 | R5 | 없음 → I3 | R5-04~10, R5-14 | 오류 상태·Report proposal·Catalog mock | `PLANNED` |
| R1-W4 | Wave 4·08/24~09/02 | R1 | I4·RC1 → I5 | R1-11~13 | Report 통합·보안·장애·복구·성능·release manifest | `PLANNED` |
| R2-W4 | Wave 4·08/24~09/02 | R2 | I4·RC1 → I5 | R2-17~19 + R2-03~16 회귀 | 5번째 source·빈 환경 재생성·schema/seed/watermark/hash 동결 | `PLANNED` |
| R3-W4 | Wave 4·08/24~09/02 | R3 | I4·RC1 → I5 | R3-11~15 + R3-01~10 회귀 | 조건부 LoRA·production client·전체 평가·fallback·release | `PLANNED` |
| R4-W4 | Wave 4·08/24~09/02 | R4 | I4·RC1 → I5 | R4-16~21 + R4-01~15 회귀 | Report·worker·권한·복구·backend 전체 회귀·동결 | `PLANNED` |
| R5-W4 | Wave 4·08/24~09/02 | R5 | I4·RC1 → I5 | R5-08~19 + R5-02~07 회귀 | Report·E2E·접근성·발표 route·fallback·frontend 동결 | `PLANNED` |

## Gate 공통 완료 조건

| Gate | `ACCEPTANCE_CRITERIA` |
|---|---|
| I0 | 역할·branch·P0/P1/P2·backend·frontend·단일 파일 소유권이 결정되고 충돌 원장이 남는다. |
| I1 | contract/schema/seed/model/UI/Report version이 기록되고 R4·R5가 fake adapter로 소비할 수 있으며 역할별 검증 명령이 고정된다. |
| I2 | 대표 질문이 Context→G1→G2→Trino→G3→Artifact→화면으로 재현되고 성공·재질문·차단·source 실패 trace가 남는다. |
| I3 | 5 catalog 단독·승인 JOIN·Node 통합·보안 기준선이 통과하고 비승인 SQL·Context 밖 참조·무제한 repair가 차단된다. |
| I4 | Chat→Artifact→Report→manual/schedule→history가 연결되고 partial·retry·중복 방지·승인 version immutable이 검증된다. |
| I5 | 빈 환경 재현·필수 30건·보안·장애·복구·성능·E2E·발표 fallback을 판정하고 release SHA와 모든 version을 동결한다. |

## Wave 1 발행 카드

아래 묶음은 기준 문서와 최신 원격 변경을 통합한 `dev` commit `72292d9`를 `BASE_SHA`로 사용한다. 담당자는 개인 branch에 이 기준을 반영한 뒤 기존 구현을 보존하면서 첫 미완료 카드부터 수행한다.

### R1-W1

```text
STATUS=READY
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=I0
TASK_CARD_RANGE=R1-00~08
CURRENT_TASK_CARD_ID=R1-00
REPOSITORY_ROOT=C:\Users\Playdata\Desktop\SKN_FINAL\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=72292d9
I0_DECISION_VERSION=DRAFT-I0-v0.1
CONTRACT_VERSION=DRAFT-I1-v0.1
ALLOWED_PATHS=AGENTS.md; compose*.yml; .env.example; .github/**; .githooks/**; tests/integration/**; docs/markdown/02_WBS.md; docs/markdown/collaboration/**; docs/markdown/ai_docs/5인_병렬구현_*
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현
ACCEPTANCE_CRITERIA=I0 역할·범위·소유권·full/dev/split-host 결정과 I1 공통 계약·Compose skeleton·env·CI·fake 소비 가능 판정, 필수 30·gold 120 원장 schema/reviewer/split 계획
TEST_COMMANDS=python .agents/skills/manage-project-documents/scripts/check_document_policy.py docs/markdown/02_WBS.md; python .agents/skills/update-project-wbs/scripts/validate_wbs.py docs/markdown/02_WBS.md; git diff --check
STOP_CONDITIONS=I1 종료 조건 도달; 역할 밖 구현 필요; 미해결 계약 충돌; 통합 검증 실패
EXTERNAL_ACTION_PERMISSION=설치·비용·배포·데이터 전송·stage·commit·push·merge 불가
```

### R2-W1

```text
STATUS=READY
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=I0
TASK_CARD_RANGE=R2-00~08
CURRENT_TASK_CARD_ID=R2-00
REPOSITORY_ROOT=C:\Users\Playdata\Desktop\SKN_FINAL\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=72292d9
I0_DECISION_VERSION=DRAFT-I0-v0.1
CONTRACT_VERSION=DRAFT-I1-v0.1
SCHEMA_VERSION=DRAFT-SCHEMA-v0.1
SEED_VERSION=DRAFT-SEED-v0.1
ALLOWED_PATHS=infrastructure/database/sql/ddl/01_hotel_pms_postgresql.sql; infrastructure/database/sql/ddl/02_hotel_pos_mysql.sql; infrastructure/database/sql/ddl/03_hotel_crm_sqlserver.sql; infrastructure/database/sql/ddl/04_hotel_facility_clickhouse.sql; infrastructure/database/sql/ddl/05_hotel_banquet_postgresql.sql; infrastructure/database/sql/ddl/06_trino_analytics_views.sql; infrastructure/database/sql/data/**; infrastructure/database/trino/**; src/data/**; tests/data/**
FORBIDDEN_PATHS=app DB·공통 FastAPI·AI model/prompt·frontend·Report·root Compose
ACCEPTANCE_CRITERIA=5 source·4 engine registry, 논리/물리 모델·grain, PMS/CRM DDL·deterministic seed·identity·event-time 등급·quality·read-only 증거, 직접식별 값 형식 사용 0건
TEST_COMMANDS=docker compose -f infrastructure/database/compose.yml config; powershell -ExecutionPolicy Bypass -File infrastructure/database/scripts/verify.ps1; git diff --check
STOP_CONDITIONS=I1 종료 조건 도달; source 소유권 충돌; app DB 또는 다른 역할 경로 변경 필요; DDL·seed·read-only 검증 실패
EXTERNAL_ACTION_PERMISSION=설치·외부 DB·비용·stage·commit·push·merge 불가
```

### R3-W1

```text
STATUS=READY
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=I0
TASK_CARD_RANGE=R3-00~03, R3-07
CURRENT_TASK_CARD_ID=R3-00
REPOSITORY_ROOT=C:\Users\Playdata\Desktop\SKN_FINAL\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=72292d9
I0_DECISION_VERSION=DRAFT-I0-v0.1
CONTRACT_VERSION=DRAFT-I1-v0.1
MODEL_CONTRACT_VERSION=DRAFT-MODEL-v0.1
PROMPT_VERSION=DRAFT-PROMPT-v0.1
FIXTURE_VERSION=DRAFT-MODEL-FIXTURE-v0.1
ALLOWED_PATHS=src/ai/**; src/modelops/**; evals/**; tests/ai/**
FORBIDDEN_PATHS=DB 원천·G1/G2/G3·공통 FastAPI·frontend·root Compose
ACCEPTANCE_CRITERIA=P0/P2 혼입 없는 AI 범위, versioned Node I/O schema, deterministic fake adapter, Node 1 baseline, Prompt Registry, Node 1·3 SQL LoRA 적용 0건
TEST_COMMANDS=python -m compileall src/ai src/modelops evals; python -m unittest discover -s tests/ai -p "test_*.py"; git diff --check
STOP_CONDITIONS=I1 종료 조건 도달; Gate 판정 로직 필요; 외부 모델·GPU·비용 필요; schema·fake contract 검증 실패
EXTERNAL_ACTION_PERMISSION=download·RunPod·비용·배포·stage·commit·push·merge 불가
```

### R4-W1

```text
STATUS=READY
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=I0
TASK_CARD_RANGE=R4-00~05
CURRENT_TASK_CARD_ID=R4-00
REPOSITORY_ROOT=C:\Users\Playdata\Desktop\SKN_FINAL\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=72292d9
I0_DECISION_VERSION=DRAFT-I0-v0.1
CONTRACT_VERSION=DRAFT-OPENAPI-v0.1
DB_REVISION_HEAD=DRAFT — I1에서 확정
ADAPTER_VERSION=DRAFT-R2-R3-v0.1
FIXTURE_VERSION=DRAFT-BACKEND-FIXTURE-v0.1
ALLOWED_PATHS=app/fastapi/**; src/backend/**; src/control_plane/**; tests/backend/**; infrastructure/database/sql/ddl/00_answervice_app_postgresql.sql; infrastructure/database/security/provision-app-postgres.sh
FORBIDDEN_PATHS=source DDL/seed·AI model/prompt·frontend·root Compose
ACCEPTANCE_CRITERIA=순환 의존 없는 backend 경계, versioned OpenAPI·상태·오류, auth context, app DB migration, Router·Controller skeleton
TEST_COMMANDS=python -m compileall app/fastapi src/backend src/control_plane; python -m unittest discover -s tests/backend -p "test_*.py"; git diff --check
STOP_CONDITIONS=I1 종료 조건 도달; source/AI/frontend/root 변경 필요; 자유 ReAct 요구; OpenAPI·migration·상태 전이 검증 실패
EXTERNAL_ACTION_PERMISSION=설치·외부 배포·secret·stage·commit·push·merge 불가
```

### R5-W1

```text
STATUS=READY
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=I0
TASK_CARD_RANGE=R5-00~04, R5-08
CURRENT_TASK_CARD_ID=R5-00
REPOSITORY_ROOT=C:\Users\Playdata\Desktop\SKN_FINAL\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=72292d9
I0_DECISION_VERSION=DRAFT-I0-v0.1
UI_CONTRACT_VERSION=DRAFT-UI-v0.1
OPENAPI_VERSION=DRAFT — R4-W1 입력
REPORT_CONTRACT_VERSION=DRAFT-REPORT-v0.1
FIXTURE_VERSION=DRAFT-UI-FIXTURE-v0.1
ALLOWED_PATHS=app/react/**; app/enterprise-react/**; src/report/**; tests/frontend/**; tests/report/**
FORBIDDEN_PATHS=root Compose·공통 FastAPI entrypoint/Alembic chain·worker runtime·source DB·AI model
ACCEPTANCE_CRITERIA=활성 frontend 하나, React+TypeScript+Vite 정합 또는 전환안, 중립 design token, IA·routing·상태 목록, typed client·mock, Chat 상태 UI, Report domain 계약, P2·Customer360 route 비활성, 이중 app 동시 변경 0건
TEST_COMMANDS=git diff --check; 활성 frontend의 package manifest가 있으면 해당 build 실행, 없으면 Blocked와 필요 계약 기록
STOP_CONDITIONS=I1 종료 조건 도달; 활성 frontend 결정 불가; 양쪽 app 동시 구현 필요; backend 공통 변경 필요; build·contract 검증 실패
EXTERNAL_ACTION_PERMISSION=dependency 설치·외부 배포·secret·stage·commit·push·merge 불가
```

## Wave 2 상세 계획 카드

Wave 2는 I1에서 동결한 계약과 fake를 기준으로 대표 질문의 deterministic 전체 왕복을 완성한다. 각 카드는 Wave 1 통합 완료 `dev` SHA와 승인 version을 입력한 뒤 `READY`로 바꾼다.

### R1-W2

- `CARD_PLAN`: R1-07 필수 평가 subset·gold 원장 확인 → R1-09 통합 profile과 deterministic trace 판정
- 입력: I1 승인 contract·schema·model·OpenAPI·UI·Report·fixture version
- 수정 범위: R1 기본 경로와 `tests/integration/**`
- 완료 조건: 대표 질문의 Context→G1→G2→Trino→G3→Artifact→화면 trace와 성공·재질문·차단·source 실패 판정
- 검증: `python -m unittest discover -s tests/integration -p "test_*.py"`, WBS·문서 정책 검사, `git diff --check`
- handoff: 역할별 실패를 원 소유자에게 반환하고 I2 병합 순서·회귀 결과를 전원에게 전달
- 중단: 필수 producer contract 미도착, trace ID 단절, 소비자 contract test 실패

### R2-W2

- `CARD_PLAN`: R2-09~10 PMS/CRM recipe·URN/FQN·lineage → R2-11 DataHub adapter → R2-12~15 Trino catalog·type·승인 JOIN·정답 hash → R2-16 query adapter
- 입력: I1 schema·seed·metric·time·권한 계약과 대표 질문
- 수정 범위: R2 기본 경로
- 완료 조건: PMS/CRM 원천 결과와 Trino hash 일치, 비승인 JOIN·증폭·null·timeout·cancel·partial fixture 구분
- 검증: `docker compose -f infrastructure/database/compose.yml config`, `powershell -ExecutionPolicy Bypass -File infrastructure/database/scripts/verify.ps1`, `python -m unittest discover -s tests/data -p "test_*.py"`, `git diff --check`
- handoff: R4에 typed adapter·URN/FQN·정답 hash, R5에 source/metric/filter fixture, R1에 재현 명령 전달
- 중단: source credential 필요, 원천/Trino hash 불일치, 승인되지 않은 cross-role schema 변경

### R3-W2

- `CARD_PLAN`: R3-02 deterministic fake 회귀 → R3-06 G3 pass shaped result만 받는 Node 3 → R3-08 평가 runner
- 입력: I1 model I/O·R4 shaped result·R2 gold fixture
- 수정 범위: R3 기본 경로
- 완료 조건: 동일 입력의 fake 출력·평가 결과가 재현되고 G3 실패 입력과 schema 초과·누락 field가 거부됨
- 검증: `python -m compileall src/ai src/modelops evals`, `python -m unittest discover -s tests/ai -p "test_*.py"`, `git diff --check`
- handoff: R4에 model contract·fake endpoint, R1에 평가 subset 결과와 실패 case 전달
- 중단: Node가 권한·Gate·SQL 결과를 재판정해야 함, gold fixture drift, schema 검증 실패

### R4-W2

- `CARD_PLAN`: R4-04~05 Router·Controller → R4-06~07 Context·G1 → R4-08~10 model·G2·repair 1회 → R4-11~13 query·G3·Artifact → R4-15 trace
- 입력: I1 OpenAPI/state/error, R2 adapter, R3 fake, R5 상태 fixture
- 수정 범위: R4 기본 경로
- 완료 조건: 대표 질문과 재질문·차단·timeout·partial이 고정 상태 전이로 재현되고 Context Package가 최대 8 dataset·60 column·6k token/25% 상한을 지키며 Gate 우회·repair 2회·G3 실패 Artifact가 차단됨
- 검증: `python -m compileall app/fastapi src/backend src/control_plane`, `python -m unittest discover -s tests/backend -p "test_*.py"`, `git diff --check`
- handoff: R5에 OpenAPI example·상태 fixture·Artifact contract, R1에 request→artifact trace 전달
- 중단: R2/R3 contract 불일치, migration 다중 head, 불법 상태 전이 또는 contract test 실패

### R5-W2

- `CARD_PLAN`: R5-03 Chat shell → R5-04 전체 상태 UI → R5-05 Evidence → R5-06 표·차트 → R5-07 Artifact bridge
- 입력: I1 UI/OpenAPI/Report 계약과 R2/R4 fixture
- 수정 범위: I0에서 확정한 활성 frontend 하나와 R5 기본 Report 경로
- 완료 조건: request/run/artifact ID가 유지되고 metric·단위·기간·as_of·filter·source 및 loading·blocked·partial·failed 상태가 표시됨
- 검증: `npm --prefix <ACTIVE_FRONTEND_PATH> run build`, `git diff --check`
- handoff: R1에 성공·재질문·차단·partial 화면 증거, R4에 response drift와 필요한 contract diff 전달
- 중단: 활성 frontend 밖 수정 필요, API 결과 재계산·권한 재판정 필요, build 또는 mock/contract 검증 실패

## Wave 3 상세 계획 카드

Wave 3는 I2에서 검증한 전체 왕복을 5 source와 실제 general LLM 경로로 확장한다. I2 병합 완료 SHA를 기준으로 역할별 기능을 적당한 크기로 나눠 I3에서 통합한다.

### R1-W3

- `CARD_PLAN`: R1-07 gold·필수 30건 관리 → R1-10 General LLM·Analytics Agent 기준선·보안 통합
- 입력: I2 통합 trace, R2 5-source fixture, R3 model 비교, R4 권한·Cache, R5 오류 상태
- 완료 조건: 일반 질문 subset, repair 최대 1회, 비승인 SQL 차단, schema-only/DataHub metadata/승인 Context 3조건 비교와 Base 비교·보안 기준선 판정
- 검증: 역할별 producer/consumer contract test와 `tests/integration/**` 회귀, 문서 정책 검사
- handoff: I3 판정·미실행 model 후보·보안 결함을 소유 역할에 전달
- 중단: 필수 30건 expected 결과 미확정, 보안 High 결함, 통합 회귀 실패

### R2-W3

- `CARD_PLAN`: R2-09~17을 5 source·watermark까지 확장 → R2-18 평가 fixture 고정
- 입력: I2 승인 schema·adapter·정답 hash와 5-source 범위
- 완료 조건: 5 catalog 단독 조회, 승인된 2·3-source JOIN, type·cardinality·watermark·gold fixture 재현
- 검증: database compose config·verify, `tests/data/**` unit/contract test, 원천/Trino hash 비교
- handoff: R3/R4/R5에 5-source fixture·watermark·실패 case, R1에 gold manifest 전달
- 중단: 5번째 source 외부 권한 필요, JOIN 증폭·type 손실·watermark drift, hash 불일치

### R3-W3

- `CARD_PLAN`: R3-03~06 Node 1·2·2′·3 → R3-07~10 prompt·평가·Base 비교·학습 데이터 검수 → R3-12~14 serving·production client·trace
- 입력: I2 model schema·gold fixture·R4 호출/timeout/error 계약
- 완료 조건: Context 밖 참조 0건, repair 1회, 동일 조건 Base 비교, serving timeout·fallback·trace 재현
- 검증: compileall, `tests/ai/**`, 필수 평가 subset, serving manifest dry-run
- handoff: R4에 production client·fallback 계약, R1에 정확도·p50/p95·자원·비용·미실행 결과 전달
- 중단: model download·RunPod·비용 미승인, 학습 누수, schema/timeout/fallback 검증 실패

### R4-W3

- `CARD_PLAN`: R4-08~13 실제 model·G2·repair·Trino·G3·Artifact → R4-14 Cache → R4-15 Audit → R4-18 권한·mask·redaction
- 입력: I2 backend trace, R2 5-source adapter, R3 production client
- 완료 조건: SQL Plan Cache와 Result Cache를 분리하고 key에 context/policy/entitlement/as_of/watermark/mask가 반영되며 Hit도 G2·G3를 우회하지 않고, 최대 LLM 4회·동시 2건·초과 대기/429와 request→context→query→artifact trace가 재현됨
- 검증: compileall, `tests/backend/**` 전체 회귀, invalid schema·timeout·권한·Cache negative test
- handoff: R5에 실제 OpenAPI/status/trace fixture, R1에 보안·Audit 증거 전달
- 중단: Gate 우회, PII·secret 노출, repair 2회, Cache 권한 공유, backend 회귀 실패

### R5-W3

- `CARD_PLAN`: R5-04 상태 UI 회귀 → R5-08~10 Report domain·router·migration proposal → R5-14 Catalog·Connection
- 입력: I2 활성 frontend·Artifact contract, R2 catalog fixture, R4 실제 OpenAPI
- 완료 조건: 전체 오류 상태, immutable Report version, R4가 등록 가능한 router/migration proposal, 5-source Catalog mock
- 검증: 활성 frontend build, mock/real response parity 검사, Report contract test, `git diff --check`
- handoff: R4에 router·migration proposal과 contract test, R1에 UI 상태·Catalog 증거 전달
- 중단: 공통 FastAPI/Alembic 직접 수정 필요, 양쪽 frontend 수정, Report version 덮어쓰기, build 실패

## Wave 4 상세 계획 카드

Wave 4는 I4 Reporting 통합부터 RC1·리허설·I5 동결까지 포함한다. I4에서 기능 통합을 마친 뒤 신규 기능을 금지하고 Critical·High 결함과 release 회귀만 수행한다.

### R1-W4

- `CARD_PLAN`: R1-11 Report 통합 → R1-12 보안·장애·복구·성능 → R1-13 RC1·RC2·Release
- 완료 조건: Chat→Report→manual/schedule→history, 필수 30건, 복구·성능, 승인 SHA·runbook·version 동결
- 검증: 전체 integration test, Compose profile smoke, 필수 30건, SBOM·SCA·container image scan, 문서·WBS·release manifest 검사
- handoff: 최종 판정·승인 SHA·잔여 위험·발표 runbook을 전원에게 전달
- 중단: Critical/High 결함, 복구 불가, 미승인 외부 서비스, release version 불일치

### R2-W4

- `CARD_PLAN`: R2-17 watermark 회귀 → R2-18 gold fixture → R2-19 5번째 source 온보딩 → R2-03~16 빈 환경 회귀
- 완료 조건: recipe→URN→FQN→query→source trace, 빈 환경 DDL·seed·ingestion·catalog·hash 재현, schema/seed/watermark 동결
- 검증: database reset/start/verify/stop runbook, 원천/Trino hash, 장애·partial fixture
- handoff: R4/R5에 동결 fixture·watermark·부분 실패, R1에 checksum·재현 로그 전달
- 중단: 데이터 재생성 불일치, read-only 위반, source trace 단절, 동결 후 schema 변경 필요

### R3-W4

- `CARD_PLAN`: R3-11 조건부 LoRA → R3-12~14 serving/client/trace → R3-15 release 후보 → R3-01~10 전체 회귀
- 완료 조건: 채택 Gate 또는 미채택 근거, Base/채택 model·prompt·adapter·fallback 전체 평가와 release manifest 동결
- 검증: 전체 AI test·필수 평가·restart/fallback·manifest hash
- handoff: R4에 동결 endpoint/client, R1에 model/prompt/adapter version·비용·rollback 전달
- 중단: 비용 미승인, Base 대비 채택 근거 부족, fallback 실패, release hash drift

### R4-W4

- `CARD_PLAN`: R4-16 Report 등록 → R4-17 worker/schedule → R4-18~20 권한·복구·health → R4-21 release → R4-01~15 회귀
- 완료 조건: Report 수동/예약 동일 경로, 수동 반복 성공 후 schedule 활성화, idempotency·dead-letter·partial, versioned role mapping·mask·redaction, migration 단일 head, RPO 24h·RTO 4h restore 증거와 API/policy/worker 동결
- 검증: backend 전체 회귀, migration 빈/기존 DB upgrade, worker retry·duplicate, backup/restore, health smoke
- handoff: R5에 동결 Report/worker API, R1에 backend release manifest·복구 증거 전달
- 중단: migration 다중 head, 중복 Artifact, 권한 우회, backup/restore 실패, release 회귀 실패

### R5-W4

- `CARD_PLAN`: R5-08~15 Report·Catalog·Audit → R5-16 접근성·반응형 → R5-17 실제 API → R5-18 build/E2E → R5-19 발표 route/fallback → R5-02~07 회귀
- 완료 조건: editor·run·history·partial과 수동 반복 성공 후 schedule 활성화, production API parity, keyboard/focus/role UI, production build·E2E·발표 fallback 동결
- 검증: 활성 frontend production build, 실제 API E2E, 접근성·반응형 수동 증거, mock/fallback 회귀
- handoff: R1에 build artifact·E2E·발표 route, R4에 최종 response drift·결함 전달
- 중단: 실제 API parity 실패, 접근성 Critical/High, production build 실패, 동결 후 신규 기능 요구

## 미래 Wave 발행 템플릿

R1은 위 전체 실행 묶음 표의 해당 행을 아래 형식으로 구체화한 뒤 `PLANNED`를 `READY`로 변경한다.

```text
STATUS=READY
ROLE_ID=<R1~R5>
ASSIGNEE=<담당자>
PERSONAL_BRANCH=<개인 branch>
EXECUTION_BUNDLE_ID=<역할-Wave>
TARGET_INTEGRATION_GATE=<I2~I5>
CHECKPOINT_GATES=<없음 또는 Wave 안 확인 Gate>
TASK_CARD_RANGE=<원장 범위>
CURRENT_TASK_CARD_ID=<범위의 첫 미완료 카드>
REPOSITORY_ROOT=<절대 경로>
BASE_BRANCH=dev
BASE_SHA=<직전 Wave 통합 완료 dev SHA>
I0_DECISION_VERSION=<승인 버전>
CONTRACT_VERSION=<현재 Gate 승인 또는 DRAFT 버전>
ALLOWED_PATHS=<역할 소유 경로 중 이번 Gate 범위>
FORBIDDEN_PATHS=<다른 역할 소유 경로>
ACCEPTANCE_CRITERIA=<목표 통합 Gate 공통 조건 + 역할별 제출물>
TEST_COMMANDS=<formatter·lint·type check·unit/contract test·build 중 적용 명령>
STOP_CONDITIONS=<목표 통합 Gate 도달·범위 완료·역할 밖 변경·계약 충돌·필수 검증 실패>
EXTERNAL_ACTION_PERMISSION=<설치·비용·배포·데이터 전송·Git 권한>
```

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.3 | 2026-07-29 17:35 | 최신 `dev` 통합 SHA `72292d9`를 기준으로 R1~R5 Wave 1 실행 묶음을 `READY`로 발행 |
| v1.2 | 2026-07-29 17:27 | 기획서 §1·3·5·7~11·14~20·22 추적성 대조와 기술·평가·보안·복구 수용 조건 보강 |
| v1.1 | 2026-07-29 17:24 | 병합 충돌과 자율 진행량을 균형화한 4개 Wave 및 Wave 2~4 역할별 상세 계획 카드 보강 |
| v1.0 | 2026-07-29 17:11 | I0~I5 역할별 실행 묶음 원장과 Wave 1 발행 준비 카드 5개 작성 |
