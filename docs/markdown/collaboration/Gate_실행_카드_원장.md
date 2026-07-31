# Gate 실행 카드 원장

| 항목 | 내용 |
|---|---|
| 문서 설명 | 역할별 자율 구현 범위와 Gate 중단·통합 조건을 관리하는 실행 카드 원장 |
| 문서 분류 | 일반 문서 |
| 버전 | v2.15 |
| 문서 기준일 | 2026-07-31 11:24 |
| 작성·수정 | 박준희 / 3팀 사용자 요청·Codex 반영 |

> 쉬운 용어: Gate는 단계별 통과 검사, Wave는 함께 개발·합칠 작업 묶음, handoff는 다음 담당자에게 넘길 결과를 뜻한다.

## 사용 원칙

1. 세부 카드 `R*-**`는 WBS 추적 단위이며, 실행 승인은 역할·통합 Wave별 `EXECUTION_BUNDLE_ID` 단위로 한다.
2. 담당자는 승인된 `TASK_CARD_RANGE`를 번호 순서대로 수행하고 카드 사이에 별도 승인을 기다리지 않는다.
3. `CHECKPOINT_GATES`에서는 계약·증거를 확인한 뒤 같은 Wave의 다음 카드로 계속 진행한다. 현재 일정에서는 I0와 Wave 4의 RC1을 사용한다.
4. `TARGET_INTEGRATION_GATE` 도달, 카드 범위 완료, 허용 경로 밖 변경 필요, 계약·보안 충돌, 필수 검증 실패 시 멈춘다.
5. 목표 통합 Gate 종료 시 변경 파일, 완료 카드, 계약·fixture version, 검증 결과, change request, 남은 위험을 제출한다.
6. R1이 통합 결과와 다음 실행 묶음을 승인하기 전에는 다음 Wave 범위로 넘어가지 않는다.
7. `PLANNED` 묶음은 일정 예약이며 실행 승인이 아니다. Wave 시작 시 `BASE_SHA`와 계약 버전을 채워 `READY`로 바꾼다.
8. 아직 동결되지 않은 계약은 공란 대신 `DRAFT` 또는 `N/A — 사유`로 기록한다.
9. F-01~F-04는 I5 이후 후속 단계다. 현재 Wave 1~4와 I5 완료율에 포함하지 않으며, 새 실행 묶음이 `READY`로 발행되기 전에는 구현 완료로 표시하지 않는다.

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

## GitHub Actions·Google Docs Gate 자동화 계약

이 원장은 실행 권한과 Gate 판정 기준의 단일 기준이다. GitHub Actions와
`.github/scripts/gate_scope.py`는 이 원장을 읽어 증거를 검사할 뿐 원장 상태,
계약 version, `BASE_SHA`, `READY`, `VERIFIED_GATE`를 자동으로 변경하지 않는다.

역할 branch는 `origin/dev...개인 branch SHA`의 merge-base diff를 검사하고,
`dev`는 push 직전 SHA와 현재 SHA의 직접 diff를 검사한다. 개인 branch의
허용 범위는 최신 non-`PLANNED` 실행 묶음의 `ALLOWED_PATHS`, 해당 역할의 개인
일일보고, 정확히 일치하는 `handoffs/<EXECUTION_BUNDLE_ID>.json`이다. 제품
구현과 무관한 공용 보고 자동화·팀 요약·보고 검증 경로는 모든 역할에 허용하되
다른 역할의 개인 일일보고는 허용하지 않는다. `MERGED_DEV`·`VERIFIED_GATE`
역할은 개인 일일보고와 공용 보고 경로 외 신규 구현을 차단한다.

자동화 판정은 원장 상태와 구분해 다음처럼 사용한다.

| 자동화 판정 | 자동 검사 기준 | 후속 처리 |
|---|---|---|
| `PASS` | 허용 경로, 실행 묶음·branch·`BASE_SHA`·결과 SHA, 실제 diff, 필수 handoff 필드와 실행 검증이 일치 | R1 승인 후보로 표시 |
| `FAIL` | 허용 경로 침범, 필드 누락·형식 오류, SHA·diff 불일치, `FAIL`·`BLOCKED` 검증, `REVIEW` 상태의 handoff 누락 | 원 소유 역할에 반환하고 병합 차단 |
| `REVIEW_REQUIRED` | `NOT_RUN`, change request, 잔여 위험, 외부 download·image pull·비용·secret·데이터 전송·배포·Git 권한 요청 | Google Docs의 R1 검토 큐에 표시하며 Gate를 차단하지 않음 |
| `NOT_RUN` | 아직 handoff를 제출하지 않은 `READY`·`IN_PROGRESS` 묶음 | 작업 또는 제출 대기이며 성공으로 계산하지 않되 Gate를 차단하지 않음 |
| `N/A` | `MERGED_DEV`·`VERIFIED_GATE`로 신규 handoff가 필요하지 않음 | 추가 구현 없이 유지 |

handoff manifest는 역할이 `REVIEW`를 요청하기 전에 제출하며 다음 필드를 모두
포함한다.

```text
EXECUTION_BUNDLE_ID
ROLE
BRANCH
BASE_SHA
RESULT_SHA
COMPLETED_CARDS
CHANGED_FILES
CONTRACT_VERSIONS
TEST_RESULTS
NOT_RUN
CHANGE_REQUESTS
RESIDUAL_RISKS
EXTERNAL_APPROVAL_REQUIRED
```

`gate_scope.py`는 권한·범위·증거 일치성만 검사한다. 기획서의 대표 질문 정답,
업무 수용성, DataHub→G1→G2→Trino→G3→Artifact→Report 의미 정확성,
UI·접근성 수동 증거, 계약 Freeze와 최종 Gate는 역할별 실제 test와 R1이
별도로 판정한다. GitHub Actions Summary는 객관적 검사 결과를 제공하고,
Google Docs는 R1이 `승인`, `보완 요청`, `보류`와 다음 실행 지시를 기록하는
결정 채널로 사용한다.

GitHub Actions의 최종 `quality-gate`는 역할 범위, Python unit·contract·
integration test, frontend production build·contract, R2 DataHub service
fragment, root Compose `dev`·`full`·`split-host`, 문서 정책·WBS·보고서
검증 결과를 집계한다.
실행 대상이 아닌 역할별 job의 `skipped`는 `N/A`로 취급하지만 `failure`와
`cancelled`는 전체 자동 품질 Gate를 실패시킨다. 개인 branch의 handoff는
`FAIL`일 때만 전체 자동 품질 Gate를 실패시킨다. `NOT_RUN`과 `REVIEW_REQUIRED`는
R1 검토 큐에 표시하되 Gate를 차단하지 않는다. 미실행 검증·change request·
잔여 위험·외부 승인 요청을 정직하게 기록한 역할이 CI 실패로 불이익을 받으면
해당 항목을 비워 두는 편이 유리해져 Gate가 수집하려는 증거 자체가 사라지므로,
차단은 증거의 무결성 위반에만 적용한다. 자동 품질 Gate 통과는
기계 검증 완료를 뜻하며 R1의 제품 수용·계약 Freeze·최종 Gate 승인을
대체하지 않는다.

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
| §1·3·5·19 범위·우선순위 | R1-W1, 전 역할 | P0/P1 우선, P2·고객 360은 I5 이후 후속, 현재 완료선 비차단 |
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
| R1 | `AGENTS.md`, root Compose·env·CI, `.githooks/**`, `tests/integration/**`, `docs/Answervice_기획서.md`, 공통 계약·WBS·협업 문서 | R2~R5 서비스 내부 구현 |
| R2 | source DDL·seed, `infrastructure/database/trino/**`, DataHub 설정, `src/data/**`, `tests/data/**` | app DB, 공통 FastAPI, AI model·prompt, frontend·Report |
| R3 | `src/ai/**`, `src/modelops/**`, `evals/**`, `tests/ai/**`, model serving 설정 | DB 원천, G1·G2·G3, 공통 FastAPI, frontend |
| R4 | `app/backend/**`, `tests/backend/**`, app DB·migration | source DDL·seed, AI model·prompt, frontend, root Compose |
| R5 | `app/enterprise-react/**`, `tests/frontend/**`, Report proposal, `docs/markdown/01_요구사항정의서.md`, `docs/markdown/05_화면설계서.md` | root Compose, 공통 FastAPI entrypoint·Alembic chain, source DB·AI model |

활성 frontend는 `app/enterprise-react/**` 하나다. `app/react/**`는 삭제 여부를 별도 결정할 때까지 보존하되 구현 변경 경로로 허용하지 않는다.

## 전체 실행 묶음

카드 집합에 같은 세부 카드가 다시 나타나는 경우는 새 기능 재승인이 아니라 다음 Gate에서의 연결·회귀·동결 작업을 뜻한다.

| 실행 묶음 | Wave·기간 | 역할 | checkpoint → 목표 통합 Gate | `TASK_CARD_RANGE` | 통합 시 제출물 | 초기 상태 |
|---|---|---|---|---|---|---|
| R1-W1 | Wave 1·07/29~08/07 | R1 | I0 → I1 | R1-00~08 | 역할·범위·소유권·공통 계약·Compose·env·CI·I1 판정 | `BLOCKED` |
| R2-W1 | Wave 1·07/29~08/07 | R2 | I0 → I1 | R2-00~08 | registry·논리/물리 모델·seed·identity·quality·read-only | `MERGED_DEV` |
| R3-W1 | Wave 1·07/29~08/07 | R3 | I0 → I1 | R3-00~03, R3-07 | AI 범위·Node schema·fake·Node 1 baseline·Prompt Registry | `MERGED_DEV` |
| R4-W1 | Wave 1·07/29~08/07 | R4 | I0 → I1 | R4-00~05 | backend 경계·OpenAPI·auth·DB·migration·Controller skeleton | `MERGED_DEV` |
| R5-W1 | Wave 1·07/29~08/07 | R5 | I0 → I1 | R5-00~04, R5-08 | 활성 frontend·IA·typed client·mock·Chat 상태·Report 계약 | `MERGED_DEV` |
| R2-W1-F1 | Wave 1 follow-up | R2 | 없음 → I1 | R2-09의 I1 service fragment 보완 | DataHub/database fragment·health·env 요구 | `MERGED_DEV` |
| R2-W1-F2 | Wave 1 follow-up | R2 | 없음 → I1 | R2-09의 DataHub consumer fragment 보완 | immutable version·official Compose source·health·env | `MERGED_DEV` |
| R2-W1-F3 | Wave 1 follow-up | R2 | 없음 → I1 | R2-09의 대표 질문 metric·JOIN 계약 보완 | 실제 PMS 수익 인식 필드·event-time CRM JOIN·I1 data version | `READY` |
| R4-W1-F1 | Wave 1 follow-up | R4 | 없음 → I1 | R4-20의 I1 container subset | backend Dockerfile·container health·runtime 증거 | `MERGED_DEV` |
| R4-W1-F2 | Wave 1 follow-up | R4 | 없음 → I1 | R4-W1-F1 cleanup 결함 수정 | container 검증 종료 코드·잔존 container 정리 | `MERGED_DEV` |
| R4-W1-F3 | Wave 1 follow-up | R4 | 없음 → I1 | R4-01의 OpenAPI/state/error version 동결 | 최종 OpenAPI version·동일 상태/오류 contract | `READY` |
| R4-W1-F3-CLEAN | Wave 1 follow-up | R4 | 없음 → I1 | R4-W1-F3 사전 개인 branch 복구 | 허용 범위 밖 제출본 변경을 `origin/dev` 상태로 복구 | `MERGED_DEV` |
| R5-W1-F1 | Wave 1 follow-up | R5 | 없음 → I1 | R5-01~04, R5-08, R5-18의 I1 보완 | 금지 route 차단·typed contract·lockfile·clean build | `MERGED_DEV` |
| R5-W1-F2 | Wave 1 follow-up | R5 | 없음 → I1 | R5-01·08의 UI/Report version 동결 | 최종 UI·Report·fixture version·OpenAPI 정합 | `READY` |
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
| R3-W4 | Wave 4·08/24~09/02 | R3 | I4·RC1 → I5 | R3-11~15 + R3-01~10 회귀 | LoRA 1회 비교·조건부 채택·production client·전체 평가·fallback·release | `PLANNED` |
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

R2~R5의 최초 Wave 1 묶음은 `dev` commit `2c2779d23738038d5cd0560cffa70c5b509991c3`에서 시작했고 결과가 최신 `dev`에 병합됐다. R1-W1은 통합 후 `dev` commit `5df4e535eaa4abb01fe6721e3eacd13bd79d9d7a`에서 계약 입력을 재판정한다.

### R1-W1

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=I0
TASK_CARD_RANGE=R1-00~08
CURRENT_TASK_CARD_ID=R1-03
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=e5eea6057468a7d3ababb3a4cc432924fc4cc207
REMOTE_DEV_SHA=4f0826321790c939ce785a08a39dfae549ee51e1
REMOTE_CI_EVIDENCE=GitHub Actions run 30598777511 PASS
REMOTE_SYNC_STATE=VERIFIED
I0_DECISION_VERSION=DRAFT-I0-v0.2
CONTRACT_VERSION=DRAFT-I1-v0.1
MODEL_CONTRACT_VERSION=DRAFT-MODEL-v0.1
PROMPT_VERSION=DRAFT-PROMPT-v0.1
MODEL_FIXTURE_VERSION=DRAFT-MODEL-FIXTURE-v0.1
BLOCKER=R2-W1-F3 handoff manifest 재제출과 dev 통합, R4 OpenAPI·R5 UI/Report 최종 version 미동결
R1_APPROVED_INPUTS=R2 schema 1.0.0·seed 20260729·scenario 1.0.0; R3 model I/O DRAFT-MODEL-v0.1·prompt DRAFT-PROMPT-v0.1·fixture DRAFT-MODEL-FIXTURE-v0.1
R3_SERVICE_FRAGMENT=N/A — R3-W3에서 model serving Dockerfile 또는 실행 manifest 제출
R1_REWORK_AUTHORIZATION=R2-W1-F3은 제품 결과 SHA 뒤 handoff manifest-only commit·seung push만 REWORK, R4-W1-F3·R5-W1-F2는 ACTION, 전 역할 Wave 2는 I1 VERIFIED_GATE 전 불허
INDEPENDENT_PROGRESS=R1-04~06 root DataHub 통합 profile·env·재현 가능한 service fragment 검증과 Python·frontend·Compose·문서 품질 Gate, R1-07 필수 30·gold 120 평가 원장 schema
ROLE_GATE_POLICY=개인 branch는 origin/dev 대비 고유 변경을 최신 비-PLANNED 실행 묶음의 ALLOWED_PATHS로 검사; 공용 보고 자동화·팀 요약·검증은 비제품 경로로 허용하고 다른 역할 개인 보고는 차단; MERGED_DEV·VERIFIED_GATE는 개인 보고·공용 보고 외 변경 차단; dev는 role scope 강제 없이 통합 검사
ROLE_GATE_PERMISSION=GitHub Actions contents: read만 사용, 자동 상태 변경·commit·push·merge 금지
HANDOFF_MANIFEST_POLICY=역할별 handoffs/<EXECUTION_BUNDLE_ID>.json을 REVIEW 요청 전 제출; RESULT_SHA는 제품 결과 HEAD 또는 최신 dev를 제외한 역할 고유 diff에서 그 뒤 변경이 해당 manifest 하나뿐인 조상 SHA를 허용하고 실제 diff·완료 카드·계약 version·검증·Not Run·change request·잔여 위험·외부 승인 요청을 기록
AUTOMATED_DECISION_BOUNDARY=경로·SHA·diff·manifest·검증 상태는 자동 판정; 기획 의미·업무 수용·계약 Freeze·Gate 승인·예외 승인은 R1 수동 판정
GOOGLE_DOCS_DECISION_CHANNEL=GitHub Actions Summary의 PASS·FAIL·REVIEW_REQUIRED·NOT_RUN을 근거로 R1이 승인·보완 요청·보류와 다음 실행 지시를 기록
ALLOWED_PATHS=AGENTS.md; compose*.yml; .env.example; .github/**; .githooks/**; tests/integration/**; docs/Answervice_기획서.md; docs/markdown/02_WBS.md; docs/markdown/collaboration/**; docs/markdown/ai_docs/5인_병렬구현_*
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현
ACCEPTANCE_CRITERIA=I0 역할·범위·소유권·full/dev/split-host 결정과 I1 공통 계약·Compose skeleton·env·CI·fake 소비 가능 판정, 필수 30·gold 120 원장 schema/reviewer/split 계획
TEST_COMMANDS=python -m unittest tests.integration.test_gate_scope -v; powershell -ExecutionPolicy Bypass -File infrastructure/database/scripts/verify-service-fragment.ps1 -EnvFilePath .env.example; docker compose -f compose.yml --env-file .env.example --profile dev config --quiet; docker compose -f compose.yml --env-file .env.example --profile full config --quiet; docker compose -f compose.yml --env-file .env.example --profile split-host config --quiet; python -m compileall -q .github/scripts app/backend src tests; python -m pytest -p no:cacheprovider tests; python .github/scripts/gate_scope.py --dashboard --next-gate I2; python .agents/skills/manage-project-documents/scripts/check_document_policy.py docs/markdown/02_WBS.md docs/markdown/collaboration/Gate_실행_카드_원장.md docs/markdown/collaboration/I0_결정_및_I1_공통_계약_원장.md docs/markdown/collaboration/I1_평가_원장.md; python .agents/skills/update-project-wbs/scripts/validate_wbs.py docs/markdown/02_WBS.md; python .agents/skills/update-project-reports/scripts/validate_reports.py docs/markdown/daily_reports/junhee/일일보고.md --date 20260731; git diff --check
STOP_CONDITIONS=I1 종료 조건 도달; 역할 밖 구현 필요; 미해결 계약 충돌; 통합 검증 실패
EXTERNAL_ACTION_PERMISSION=설치·비용·배포·데이터 전송·stage·commit·push·merge 불가
```

### R2-W1

```text
STATUS=MERGED_DEV
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
BASE_SHA=2c2779d23738038d5cd0560cffa70c5b509991c3
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
STATUS=MERGED_DEV
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
BASE_SHA=2c2779d23738038d5cd0560cffa70c5b509991c3
I0_DECISION_VERSION=DRAFT-I0-v0.1
CONTRACT_VERSION=DRAFT-I1-v0.1
MODEL_CONTRACT_VERSION=DRAFT-MODEL-v0.1
PROMPT_VERSION=DRAFT-PROMPT-v0.1
FIXTURE_VERSION=DRAFT-MODEL-FIXTURE-v0.1
SERVICE_FRAGMENT=N/A — R3-W3에서 model serving Dockerfile 또는 실행 manifest 제출
ALLOWED_PATHS=src/ai/**; src/modelops/**; evals/**; tests/ai/**
FORBIDDEN_PATHS=DB 원천·G1/G2/G3·공통 FastAPI·frontend·root Compose
ACCEPTANCE_CRITERIA=P0/P2 혼입 없는 AI 범위, versioned Node I/O schema, deterministic fake adapter, Node 1 baseline, Prompt Registry, Node 1·3 SQL LoRA 적용 0건
TEST_COMMANDS=python -m compileall src/ai src/modelops evals; python -m unittest discover -s tests/ai -p "test_*.py"; git diff --check
STOP_CONDITIONS=I1 종료 조건 도달; Gate 판정 로직 필요; 외부 모델·GPU·비용 필요; schema·fake contract 검증 실패
EXTERNAL_ACTION_PERMISSION=download·RunPod·비용·배포·stage·commit·push·merge 불가
```

### R4-W1

```text
STATUS=MERGED_DEV
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
BASE_SHA=2c2779d23738038d5cd0560cffa70c5b509991c3
I0_DECISION_VERSION=DRAFT-I0-v0.1
CONTRACT_VERSION=DRAFT-OPENAPI-v0.1
DB_REVISION_HEAD=DRAFT — I1에서 확정
ADAPTER_VERSION=DRAFT-R2-R3-v0.1
FIXTURE_VERSION=DRAFT-BACKEND-FIXTURE-v0.1
ALLOWED_PATHS=app/fastapi/**; src/backend/**; src/control_plane/**; tests/backend/**; infrastructure/database/sql/ddl/00_answervice_app_postgresql.sql; infrastructure/database/security/provision-app-postgres.sh
FORBIDDEN_PATHS=source DDL/seed·AI model/prompt·frontend·root Compose
ACCEPTANCE_CRITERIA=순환 의존 없는 backend 경계, versioned OpenAPI·상태·오류, auth context, app DB migration, Router·Controller skeleton
TEST_COMMANDS=python -m compileall app/backend; python -m unittest discover -s tests/backend -p "test_*.py"; git diff --check
STOP_CONDITIONS=I1 종료 조건 도달; source/AI/frontend/root 변경 필요; 자유 ReAct 요구; OpenAPI·migration·상태 전이 검증 실패
EXTERNAL_ACTION_PERMISSION=설치·외부 배포·secret·stage·commit·push·merge 불가
```

### R5-W1

```text
STATUS=MERGED_DEV
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
BASE_SHA=2c2779d23738038d5cd0560cffa70c5b509991c3
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

## Wave 1 follow-up 발행 카드

follow-up 묶음은 I1 blocker 보완만 허가한다. 대표 질문과 metric은 승인값이 없으므로 작성하지 않으며, R1-W1은 `BLOCKED`, R2-W2를 포함한 Wave 2 묶음은 `PLANNED`를 유지한다.

### R2-W1-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W1-F1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-09의 I1 service fragment 보완
CURRENT_TASK_CARD_ID=R2-09
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=858b0be4968ace64c8a9bcef2448616ce0daf2b7
CONTRACT_VERSION=DRAFT-I1-v0.1
SCHEMA_VERSION=1.0.0
SEED_VERSION=20260729
SCENARIO_VERSION=1.0.0
REPRESENTATIVE_QUESTION=N/A — 승인값 미확정, I1 승인 전 작성 금지
METRIC_CONTRACT=N/A — 승인값 미확정, I1 승인 전 작성 금지
ALLOWED_PATHS=infrastructure/database/**
FORBIDDEN_PATHS=root Compose·.env.example·CI·app/**·src/ai/**·src/backend/**·src/control_plane/**·frontend·Report·docs/markdown/collaboration/**·docs/markdown/02_WBS.md
ACCEPTANCE_CRITERIA=DataHub와 database 서비스별 service name·image/build·port·env key·health·dependency·profile 요구를 R1이 소비 가능한 fragment로 제출, schema 1.0.0·seed 20260729·scenario 1.0.0 유지, root Compose 변경 0건, secret 값 기록 0건
TEST_COMMANDS=docker compose -f infrastructure/database/compose.yml config; powershell -ExecutionPolicy Bypass -File infrastructure/database/scripts/verify.ps1; python -m unittest discover -s tests/data -p "test_*.py"; git diff --check
STOP_CONDITIONS=I1 fragment 제출 완료; infrastructure/database/** 밖 변경 필요; schema·seed·read-only 계약 drift; 전체 DB verify 실패
SUBMISSION_PERMISSION_STATUS=APPROVED
SUBMISSION_PERMISSION_BASIS=READY 카드 commit 9925a88이 origin/dev 4527375에 이미 포함됨
SUBMISSION_PATHS=infrastructure/database/r1-service-fragment.v1.json; infrastructure/database/scripts/verify-service-fragment.ps1; infrastructure/database/scripts/verify.ps1
EXPECTED_COMMIT_MESSAGE=feat(data): I1 서비스 fragment와 검증 추가
HANDOFF_SHA=055b26578cbd17da0d0d4f116fb1b27af59e817e
R1_REVIEW_EVIDENCE=허용 경로 밖 변경 0건; R2_SERVICE_FRAGMENT_VERIFIED; tests/data 7건 통과; docker compose config 통과; schema 1.0.0·seed 20260729·scenario 1.0.0과 full/split-host·DataHub dev 제외 요구 확인
R1_INTEGRATION_EVIDENCE=origin/seung 055b265를 dev 0b0e410에 병합; R2_SERVICE_FRAGMENT_VERIFIED 재실행; 전체 tests 26건 통과
R1_NOT_RUN=전체 live DB verify는 생산자 DATABASE_CONTRACT_VERIFIED 증거를 유지하며 DataHub 포함 full·split-host runtime은 consumer fragment 미제출로 미실행
EXTERNAL_ACTION_PERMISSION=R2-W1-F1 추가 작업 없음, R2-W2 READY 발행 전 구현 금지
```

### R4-W1-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W1-F1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-20의 I1 container subset
CURRENT_TASK_CARD_ID=R4-20
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=858b0be4968ace64c8a9bcef2448616ce0daf2b7
CONTRACT_VERSION=DRAFT-I1-v0.1
OPENAPI_VERSION=DRAFT-OPENAPI-v0.1
EXPECTED_DB_REVISION_HEAD=20260730_02 — R4 보고값, branch 제출 후 검증
HANDOFF_SHA=af6cc10878493454cf1c7bc2cda5bf96454b54f0
R1_REVIEW_EVIDENCE=origin/dev 대비 net diff가 app/backend/**·tests/backend/**·개인 일일보고로 정리됨; compileall 통과; local dependency 미설치로 backend test 10건 통과 후 2건 Blocked; container image build·/health·/readiness·app-postgres 연결이 BACKEND_CONTAINER_READY·BACKEND_DATABASE_READY로 통과
R1_REVIEW_NOTE=verify-container.ps1 -RemoveAfterVerification가 Docker의 정상 stop stderr를 terminating error로 처리해 rm 단계가 실행되지 않으므로 cleanup 종료 코드·잔존 container 검증 보완 필요
R1_NOT_RUN=DataHub 포함 full·split-host runtime은 R2 consumer fragment 미제출로 미실행
R1_INTEGRATION_EVIDENCE=origin/jaehong 61852de를 dev에 병합; backend image에서 tests/backend 17건 통과; BACKEND_CONTAINER_READY·BACKEND_DATABASE_READY·BACKEND_CONTAINER_REMOVED 확인
REPRESENTATIVE_QUESTION=N/A — 승인값 미확정, I1 승인 전 작성 금지
METRIC_CONTRACT=N/A — 승인값 미확정, I1 승인 전 작성 금지
ALLOWED_PATHS=app/backend/**; tests/backend/**
FORBIDDEN_PATHS=root Compose·.env.example·CI·infrastructure/database/**·src/data/**·src/ai/**·frontend·Report·docs/markdown/collaboration/**·docs/markdown/02_WBS.md·tests/integration/**
ACCEPTANCE_CRITERIA=backend Dockerfile과 재현 가능한 container 검증 절차 제출, container에서 /health·/readiness 확인, Alembic head 20260730_02 확인, BACKEND_CONTAINER_READY 증거, 신규 production dependency 0건, R1·R2·R3·R5 소유 경로 변경 0건
TEST_COMMANDS=python -m compileall app/backend/app; python -m unittest discover -s tests/backend -p "test_*.py"; powershell -ExecutionPolicy Bypass -File app/backend/scripts/verify-container.ps1; git diff --check
STOP_CONDITIONS=I1 container 증거 제출 완료; 허용 경로 밖 변경 필요; migration 다중 head; health·readiness·container 기동 실패; cross-role 변경 잔존
EXTERNAL_ACTION_PERMISSION=app/backend/scripts/verify-container.ps1의 cleanup 결함 수정·검증, 해당 파일과 개인 일일보고의 commit·jaehong push 허용; merge·신규 dependency·외부 배포·secret·비용·데이터 전송은 불가
```

### R4-W1-F2

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W1-F2
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-W1-F1의 container cleanup 결함 수정
CURRENT_TASK_CARD_ID=R4-20
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=85c2ff0a2c23a156fc28c8d2a112792d47d42da5
CONTRACT_VERSION=DRAFT-I1-v0.1
ALLOWED_PATHS=app/backend/scripts/verify-container.ps1; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=root Compose·.env.example·CI·infrastructure/database/**·src/data/**·src/ai/**·frontend·Report·docs/markdown/collaboration/**·docs/markdown/02_WBS.md·tests/integration/**
ACCEPTANCE_CRITERIA=-RemoveAfterVerification 성공 시 docker stop의 stderr가 terminating error가 되지 않고 검증 container가 제거되며 기존 /health·/readiness·app-postgres 연결 검증 유지
TEST_COMMANDS=python -m compileall app/backend/app; python -m pytest tests/backend -q; powershell -ExecutionPolicy Bypass -File app/backend/scripts/verify-container.ps1 -RemoveAfterVerification; docker ps -a --filter name=answervice-backend --format "{{.Names}}"; git diff --check
STOP_CONDITIONS=허용 경로 밖 변경 필요; 기존 container 검증 실패; cleanup 후 container 잔존
EXTERNAL_ACTION_PERMISSION=허용 경로만 commit·jaehong push 후 SHA와 검증 결과 보고; merge·신규 dependency·외부 배포·secret·비용·데이터 전송 불가
HANDOFF_SHA=61852dee54fe1a31d81b28dfe3067cccdf39b7cf
R1_INTEGRATION_EVIDENCE=cleanup 종료 코드와 잔존 container 검증을 dev에 병합하고 BACKEND_CONTAINER_REMOVED 확인
```

### R5-W1-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W1-F1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R5-01~04, R5-08, R5-18의 I1 보완
CURRENT_TASK_CARD_ID=R5-01
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=85c2ff0a2c23a156fc28c8d2a112792d47d42da5
CONTRACT_VERSION=DRAFT-I1-v0.1
UI_CONTRACT_VERSION=DRAFT-UI-v0.1
REPORT_CONTRACT_VERSION=DRAFT-REPORT-v0.1
HANDOFF_SHA=ba5617bb6c861fd1da4d7dbd7bbaf8fe60f3f42a
R1_REVIEW_EVIDENCE=origin/dev 대비 고유 변경이 app/enterprise-react/**·tests/frontend/** 20개로 한정; npm ci·production build·contract test·Compose config 통과; Docker image build·기동·healthy·/health 통과; /customers·/catalog/tools 비활성; OPENAPI_VERSION DRAFT-OPENAPI-v0.1 정합
R1_REVIEW_FINDINGS=필수 보완 해소, 추가 구현 금지; dev 병합과 combined profile 소비자 검증 대기
REPRESENTATIVE_QUESTION=N/A — 승인값 미확정, I1 승인 전 작성 금지
METRIC_CONTRACT=N/A — 승인값 미확정, I1 승인 전 작성 금지
ALLOWED_PATHS=app/enterprise-react/**; src/report/**; tests/frontend/**; tests/report/**
FORBIDDEN_PATHS=app/react/**·root Compose·.env.example·CI·공통 FastAPI entrypoint·Alembic chain·source DB·AI model·docs/markdown/collaboration/**·docs/markdown/02_WBS.md
ACCEPTANCE_CRITERIA=/customers와 /catalog/tools route·메뉴 비활성, typed client·mock·UI/Report contract와 고정 lockfile 제출, npm ci 기반 clean production build 통과, frontend Dockerfile·health fragment 제출, 양쪽 frontend 동시 변경 0건
TEST_COMMANDS=npm --prefix app/enterprise-react ci; npm --prefix app/enterprise-react run build; docker build -f app/enterprise-react/Dockerfile app/enterprise-react; git diff --check
STOP_CONDITIONS=I1 frontend 증거 제출 완료; 활성 frontend 밖 변경 필요; 금지 route 노출; lockfile drift; clean production build·container build 실패
EXTERNAL_ACTION_PERMISSION=추가 구현·commit·push 금지, R1의 dev 병합·combined profile 소비자 검증 판정 대기
R1_INTEGRATION_EVIDENCE=origin/minji ca8beae를 dev에 병합; npm ci·production build·frontend contract·Compose config 통과
```

### R2-W1-F2

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W1-F2
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-09의 DataHub consumer fragment 보완
CURRENT_TASK_CARD_ID=R2-09
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=2c7b72dbfb8b097982acde1d35c26e00112d15b5
CONTRACT_VERSION=DRAFT-I1-v0.1
SCHEMA_VERSION=1.0.0
SEED_VERSION=20260729
SCENARIO_VERSION=1.0.0
REPRESENTATIVE_QUESTION=N/A — 승인값 미확정, I1 승인 전 작성 금지
METRIC_CONTRACT=N/A — 승인값 미확정, I1 승인 전 작성 금지
ALLOWED_PATHS=infrastructure/database/**
FORBIDDEN_PATHS=root Compose·.env.example·CI·app/**·src/ai/**·src/backend/**·src/control_plane/**·frontend·Report·docs/markdown/collaboration/**·docs/markdown/02_WBS.md
ACCEPTANCE_CRITERIA=R1 root full·split-host profile이 직접 소비할 DataHub Compose fragment 제출, DATAHUB_VERSION을 immutable v* release 또는 sha-* tag로 고정하고 공식 source URL·revision 기록, GMS 8080 /health와 management 4319 /actuator/health·필수 env·dependency 검증, dev profile 제외 유지, root Compose 변경 0건, secret 값 기록 0건
TEST_COMMANDS=powershell -ExecutionPolicy Bypass -File infrastructure/database/scripts/verify-service-fragment.ps1; docker compose -f <DataHub consumer fragment> config --quiet; python -m unittest discover -s tests/data -p "test_*.py"; git diff --check
STOP_CONDITIONS=DataHub consumer fragment 제출 완료; infrastructure/database/** 밖 변경 필요; immutable version 또는 공식 source provenance 확정 불가; Compose config·health 계약 검증 실패; 실제 secret 필요
R1_REVIEW_EVIDENCE=origin/seung 731399d의 고유 변경이 consumer fragment·service manifest·검증 스크립트 3개로 한정되고 Actions role-scope·Python contracts 통과; 공식 DataHub source revision 059a36c와 blob 028473e 존재 확인; R1 local에서 R2_SERVICE_FRAGMENT_VERIFIED와 root dev·full·split-host Compose config 통과
R1_INTEGRATION_EVIDENCE=origin/seung 731399d를 dev에 fast-forward 통합하고 root Compose include·profile 소유 위치·DataHub env·seung Compose CI를 R1 범위에서 보완
EXTERNAL_ACTION_PERMISSION=추가 R2 구현 없음; image pull·실제 container runtime·비용·배포·secret 등록은 별도 승인 전 불가
```

## I1 계약 동결 follow-up

아래 세 묶음은 새 기능이 아니라 병합된 Wave 1 계약의 잘못된 PMS 필드와
`DRAFT` version을 고치는 최소 보완이다. 각 역할은 자기 묶음만 수행하며
Wave 2 구현은 시작하지 않는다.

### R2-W1-F3

```text
STATUS=READY
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W1-F3
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-09의 대표 질문 metric·JOIN 계약 보완
CURRENT_TASK_CARD_ID=R2-09
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=e2ecee3afbc7fa9d0e05d3973e607bed6b1d62cb
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W1-F3@e2ecee3
SUBMISSION_PERMISSION_STATUS=APPROVED
SUBMISSION_STATE=PRODUCT_RESULT_READY; HANDOFF_MANIFEST_REWORK
CONTRACT_VERSION=DRAFT-I1-v0.1 → I1-v1.0.0 후보
SCHEMA_VERSION=1.0.0
SEED_VERSION=20260729
SCENARIO_VERSION=1.0.0
REPRESENTATIVE_QUESTION=지난달 GOLD 회원의 인식 객실 매출은 전월 대비 얼마나 변했어?
METRIC_CONTRACT=recognized_room_revenue; KRW; SUM; month; membership_grade(event-time); completed·paid·non-forecast stays
ALLOWED_PATHS=src/data/r2_w1_contract.v1.json; src/data/source_registry.v1.json; tests/data/**
FORBIDDEN_PATHS=source DDL·seed·root Compose·.env.example·CI·app/**·src/ai/**·frontend·Report·docs/markdown/collaboration/**·docs/markdown/02_WBS.md
ACCEPTANCE_CRITERIA=pms.public.pms_stays.room_revenue를 수익 인식 필드로 사용하고 실제 스키마에 존재하는 PMS reservation·guest와 CRM customer map·grade history를 잇는 stable JOIN ID·cardinality·event-time predicate·time field를 registry에 기록, DDL·seed·row count·checksum 변경 0건, data contract와 registry version을 I1-v1.0.0 후보로 일치
TEST_COMMANDS=python -m unittest discover -s tests/data -p "test_*.py" -v; python -m json.tool src/data/r2_w1_contract.v1.json > NUL; python -m json.tool src/data/source_registry.v1.json > NUL; git diff --check
STOP_CONDITIONS=실제 컬럼으로 승인 JOIN을 표현할 수 없음; DDL·seed 변경 필요; 기존 schema·seed·scenario 또는 checksum 변경; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R1에 metric ID·time field·JOIN ID·cardinality·temporal predicate·변경된 contract version과 검증 결과 전달
R1_REVIEW_EVIDENCE=origin/seung 23059a6의 고유 변경은 승인된 data contract·registry·test 3개이고 CI run 30597402020의 제품·범위·Compose·문서 검사는 PASS; handoff self-reference만 R1 validator e5eea60에서 수정
R1_REWORK_AUTHORIZATION=origin/dev e5eea60을 반영하고 RESULT_SHA=23059a62957b2baec7ba1e7113d08bc63f621364인 handoffs/R2-W1-F3.json 하나만 commit·seung push
EXTERNAL_ACTION_PERMISSION=기존 제품 3개 파일의 추가 변경 없이 handoffs/R2-W1-F3.json manifest-only commit·seung push 승인; dependency 설치·download·image pull·비용·배포·secret·데이터 전송·dev merge 불가
```

### R4-W1-F3

```text
STATUS=READY
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W1-F3
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-01의 OpenAPI·state·error version 동결
CURRENT_TASK_CARD_ID=R4-01
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=e5eea6057468a7d3ababb3a4cc432924fc4cc207
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W1-F3@e5eea60
SUBMISSION_PERMISSION_STATUS=APPROVED
ACTIVATION_EVIDENCE=origin/jaehong 14bedf8의 tree가 origin/dev e4c4651과 동일해 고유 diff 0건; R4-W1-F3-CLEAN 수용
OPENAPI_VERSION=DRAFT-OPENAPI-v0.1 → OPENAPI-v1.0.0 후보
ALLOWED_PATHS=app/backend/app/contracts.py; app/backend/contracts/**; tests/backend/**
FORBIDDEN_PATHS=root Compose·.env.example·CI·source DDL·seed·src/data/**·src/ai/**·frontend·Report·docs/markdown/collaboration/**·docs/markdown/02_WBS.md
ACCEPTANCE_CRITERIA=producer constant·committed OpenAPI·state mapping·source registry·API fixture·backend test의 version을 OPENAPI-v1.0.0 후보로 일치, 기존 endpoint·schema·상태·오류·migration·runtime 동작 변경 0건
TEST_COMMANDS=python -m compileall -q app/backend tests/backend; python -m pytest -p no:cacheprovider tests/backend; python app/backend/scripts/export_openapi.py --check; git diff --check
STOP_CONDITIONS=version 치환 외 API·상태·오류·migration 동작 변경 필요; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R1과 R5에 최종 OpenAPI 후보 version·변경 파일·회귀 결과 전달
EXTERNAL_ACTION_PERMISSION=origin/dev e5eea60 반영 후 이 묶음의 허용 경로에 한해 commit·jaehong push 승인; dependency 설치·외부 배포·secret·dev merge 불가
```

### R5-W1-F2

```text
STATUS=READY
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W1-F2
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R5-01·08의 UI·Report·fixture version 동결
CURRENT_TASK_CARD_ID=R5-01
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=e2ecee3afbc7fa9d0e05d3973e607bed6b1d62cb
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R5-W1-F2@e2ecee3
SUBMISSION_PERMISSION_STATUS=APPROVED
OPENAPI_VERSION=OPENAPI-v1.0.0 후보
UI_VERSION=DRAFT-UI-v0.1 → UI-v1.0.0 후보
REPORT_VERSION=DRAFT-REPORT-v0.1 → REPORT-v1.0.0 후보
UI_FIXTURE_VERSION=DRAFT-UI-FIXTURE-v0.1 → UI-FIXTURE-v1.0.0 후보
ALLOWED_PATHS=app/enterprise-react/src/contracts/**; app/enterprise-react/src/data/analysisFixtures.ts; tests/frontend/**
FORBIDDEN_PATHS=root Compose·.env.example·CI·app/backend/**·source DDL·seed·src/data/**·src/ai/**·docs/markdown/collaboration/**·docs/markdown/02_WBS.md
ACCEPTANCE_CRITERIA=UI·Report·fixture version을 각 v1.0.0 후보로 고정하고 R4 OPENAPI-v1.0.0 후보와 typed client·fixture·contract test를 일치, route·화면·Report 동작·dependency 변경 0건
TEST_COMMANDS=npm --prefix app/enterprise-react run build; node --test tests/frontend/contracts.test.mjs; git diff --check
STOP_CONDITIONS=version 치환 외 UI·Report 동작 또는 dependency 변경 필요; R4 최종 OpenAPI 후보와 불일치; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R1에 UI·Report·fixture·OpenAPI 후보 version과 build·contract 결과 전달
EXTERNAL_ACTION_PERMISSION=이 묶음의 허용 경로에 한해 commit·minji push 승인; dependency 설치·download·비용·배포·secret·데이터 전송·dev merge 불가
```

### R4-W1-F3-CLEAN

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W1-F3-CLEAN
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-W1-F3 사전 개인 branch 복구
CURRENT_TASK_CARD_ID=R4-W1-F3-CLEAN
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=e2ecee3afbc7fa9d0e05d3973e607bed6b1d62cb
SOURCE_HEAD=9a5d3bd96a2798450a069e5743b4655aa179eee0
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W1-F3-CLEAN@e2ecee3
SUBMISSION_PERMISSION_STATUS=APPROVED
ALLOWED_PATHS=docs/deliverables/04_수집데이터보고서_29기_3팀.docx; docs/deliverables/05_데이터베이스저장소설계서_29기_3팀.xlsx; docs/deliverables/05_[[]별첨]데이터테이블명세서.xlsx; docs/deliverables/05_데이터베이스저장소설계서_29기_3팀.docx; docs/deliverables/06_데이터전처리결과서_29기_3팀.docx
FORBIDDEN_PATHS=위 파일을 origin/dev 상태로 복구하는 작업 외 전체 경로, backend contract 포함 신규 구현
ACCEPTANCE_CRITERIA=지정 5개 경로가 origin/dev와 byte·존재 상태까지 동일, origin/jaehong 고유 diff 0건, 최신 origin/dev 병합, 다른 경로 변경 0건
TEST_COMMANDS=git diff --exit-code origin/dev -- docs/deliverables/04_수집데이터보고서_29기_3팀.docx docs/deliverables/05_데이터베이스저장소설계서_29기_3팀.xlsx ":(literal)docs/deliverables/05_[별첨]데이터테이블명세서.xlsx" docs/deliverables/05_데이터베이스저장소설계서_29기_3팀.docx docs/deliverables/06_데이터전처리결과서_29기_3팀.docx; git diff --name-only origin/dev...HEAD; git diff --check
STOP_CONDITIONS=지정 경로 외 변경 필요; 제출본 내용을 새로 편집해야 함; origin/dev와 동일 상태를 만들 수 없음; 검증 실패
HANDOFF=R1에 복구 commit SHA·origin/dev 병합 SHA·고유 diff 0건·검증 결과 전달, R4-W1-F3 READY 재발행 전 backend 구현 금지
R1_REVIEW_EVIDENCE=origin/jaehong 14bedf8 확인; git diff dev origin/jaehong과 git diff --name-status dev origin/jaehong 모두 0건
R1_INTEGRATION_EVIDENCE=N/A — 결과 tree가 dev와 이미 동일해 별도 merge 대상 없음
EXTERNAL_ACTION_PERMISSION=추가 cleanup·제출본 편집·force push·rebase·reset·dev merge 불가
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
- 완료 조건: SQL Plan Cache와 Result Cache를 분리하고 key에 context/policy/권한 범위(entitlement)/as_of/watermark/mask가 반영되며, Template·Plan·Result Cache도 G1·G2·G3와 권한 확인을 우회하지 않고, 최대 LLM 4회·동시 2건·초과 대기/429와 request→context→query/cache→artifact trace가 재현됨
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

- `CARD_PLAN`: R3-11 LoRA 1회 비교·조건부 채택 → R3-12~14 serving/client/trace → R3-15 release 후보 → R3-01~10 전체 회귀
- 완료 조건: 외부 실행 조건 충족 시 1회 비교, 미충족 시 `Blocked`·`Not Run` 사유, 제품 채택·미채택 결정, Base/채택 model·prompt·adapter·fallback 전체 평가와 release manifest 동결
- 검증: 전체 AI test·필수 평가·restart/fallback·manifest hash
- handoff: R4에 동결 endpoint/client, R1에 model/prompt/adapter version·비용·rollback 전달
- 중단: 비용 미승인은 비교를 `Blocked`·`Not Run`으로 기록하고 Base release는 계속함; fallback 실패, release hash drift, 승인 없는 제품 채택은 중단

### R4-W4

- `CARD_PLAN`: R4-16 Report 등록 → R4-17 worker/schedule → R4-18~20 권한·복구·health → R4-21 release → R4-01~15 회귀
- 완료 조건: Report 수동/예약 동일 경로, 수동 반복 성공 후 schedule 활성화, 영속 job·같은 요청 한 번만 처리(idempotency)·retry·실패 격리·일부 실패(partial), versioned role mapping·mask·민감정보 가림(redaction), migration 단일 head, RPO 24h·RTO 4h restore 증거와 API/policy/worker 동결
- 검증: backend 전체 회귀, migration 빈/기존 DB upgrade, worker retry·duplicate, 암호화 backup·분리 key·restore, health smoke
- handoff: R5에 동결 Report/worker API, R1에 backend release manifest·복구 증거 전달
- 중단: migration 다중 head, 중복 Artifact, 권한 우회, backup/restore 실패, release 회귀 실패

### R5-W4

- `CARD_PLAN`: R5-08~15 Report·Catalog·Audit → R5-16 접근성·반응형 → R5-17 실제 API → R5-18 build/E2E → R5-19 발표 route/fallback → R5-02~07 회귀
- 완료 조건: editor·run·history·partial과 수동 반복 성공 후 schedule 활성화, production API parity, keyboard/focus/role UI, production build·E2E·발표 fallback 동결
- 검증: 활성 frontend production build, 실제 API E2E, 접근성·반응형 수동 증거, mock/fallback 회귀
- handoff: R1에 build artifact·E2E·발표 route, R4에 최종 response drift·결함 전달
- 중단: 실제 API parity 실패, 접근성 Critical/High, production build 실패, 동결 후 신규 기능 요구

## I5 이후 후속 단계 예약

아래 항목은 기획에서 빠진 것이 아니라 현재 일정 뒤에 남겨 둔 작업이다. 아직 실행 Wave와 날짜를 정하지 않으며, 현재 상태는 `PLANNED`다. R1이 I5 이후 새 `BASE_SHA`, 담당 경로, 계약·비용·보안 기준을 채워 별도 실행 묶음을 `READY`로 발행해야 시작할 수 있다.

| 후속 ID | 항목 | 주 책임 | 현재 I5 영향 |
|---|---|---|---|
| F-01 | MCP Tool Registry·호출 통제 | R4 | 없음 |
| F-02 | 사내 운영 문서 RAG | R3 | 없음 |
| F-03 | ML-as-a-Tool | R3 | 없음 |
| F-04 | 고객 360 | R5 | 없음 |

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
HANDOFF_MANIFEST=handoffs/<EXECUTION_BUNDLE_ID>.json
HANDOFF_REQUIRED_FIELDS=실행 묶음·역할·branch·BASE_SHA·RESULT_SHA·완료 카드·실제 변경 파일·계약 version·검증·Not Run·change request·잔여 위험·외부 승인 요청
ACCEPTANCE_CRITERIA=<목표 통합 Gate 공통 조건 + 역할별 제출물>
TEST_COMMANDS=<formatter·lint·type check·unit/contract test·build 중 적용 명령>
STOP_CONDITIONS=<목표 통합 Gate 도달·범위 완료·역할 밖 변경·계약 충돌·필수 검증 실패>
EXTERNAL_ACTION_PERMISSION=<설치·비용·배포·데이터 전송·Git 권한>
AUTO_FAIL_CONDITIONS=<경로 침범·SHA/diff 불일치·manifest 누락/오류·필수 검증 실패>
R1_REVIEW_CONDITIONS=<Not Run·change request·잔여 위험·외부 승인·기획/계약 수동 수용 판단>
```

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v2.15 | 2026-07-31 11:24 | R1 경로 정합성 제안의 1·2·3·4·6·7번을 승인해 R4 기본 경로를 실제 `app/backend/**`로 교정하고 활성 frontend를 `app/enterprise-react/**`로 단일화했으며 R1 기획서·R5 요구사항·화면설계서 소유권을 지정했다. `app/react/**` 삭제는 별도 결정으로 보류했다. R4 follow-up 집계 상태를 현재 카드와 맞추고 `origin/dev` `4f08263`·CI run `30598777511` PASS를 반영했다. |
| v2.14 | 2026-07-31 11:20 | 기획 검토 결과를 반영해 자동 Gate의 차단 범위를 조정했다. `R2-W1-F3`·`R4-W1-F3-CLEAN`·`R5-W1-F2`를 `READY`로 발행하면서 manifest 미제출 상태의 `NOT_RUN`이 4개 개인 branch를 동시에 차단하는 현상을 확인해, handoff는 `FAIL`일 때만 자동 품질 Gate를 차단하도록 고쳤다. `NOT_RUN`과 `REVIEW_REQUIRED`는 R1 검토 큐에만 표시한다. R1-W1 `ALLOWED_PATHS`에 `docs/Answervice_기획서.md`를 추가해 소유자 공백을 해소했다. `RESULT_SHA` 닭-달걀은 v2.12~v2.13의 `result_sha_matches_checked_head`와 manifest-only 후속 commit 허용 계약을 그대로 유지한다. 나머지 경로 정합성 3건과 역할별 test 분기·`dev` 병합 경로는 `R1_Gate_원장_경로_정합성_패치_제안서.md`로 분리해 R1 승인 대기 중이다. |
| v2.13 | 2026-07-31 11:05 | `origin/dev` `e5eea60`과 CI run `30598022457` PASS를 확인하고 handoff manifest-only 후속 commit을 허용하도록 R1 validator 계약을 수정했다. R2 제품 결과 `23059a6`은 manifest 재제출만 REWORK로 허가했으며, `origin/jaehong` `14bedf8`의 dev 대비 고유 diff 0건을 수용해 R4-W1-F3을 READY/ACTION으로 재발행했다. |
| v2.12 | 2026-07-31 10:25 | 최신 `origin/dev` `e2ecee3`과 CI run `30596060168` PASS를 기준으로 R2-W1-F3·R5-W1-F2의 commit·개인 branch push를 ACTION 승인했다. 허용 범위 밖 제출본 변경이 남은 R4는 R4-W1-F3을 차단하고 원상복구 전용 R4-W1-F3-CLEAN만 REWORK 승인했으며 R3·Wave 2는 WAIT를 유지했다. |
| v2.11 | 2026-07-31 10:12 | `origin/dev` `68fc068`과 GitHub Actions run `30528089815` PASS를 확인해 원격 동기화 차단을 해제했다. 실제 schema에 없는 PMS 수익 필드와 PMS↔CRM event-time 승인 JOIN 미등록, OpenAPI·UI·Report 초안 version을 I1 차단 원인으로 확정하고 R2-W1-F3·R4-W1-F3·R5-W1-F2를 동결 전용 READY로 발행 |
| v2.10 | 2026-07-30 17:09 | R2 DataHub consumer `731399d`를 dev에 통합하고 공식 source provenance·service fragment·root dev/full/split-host Compose 정적 소비를 검증해 R2-W1-F2를 MERGED_DEV로 전환했다. Git 한글 경로 raw 처리, 공용 보고 자동화 비제품 예외, seung Compose 검증, handoff 최종 차단을 CI에 반영했으며 실제 DataHub container 기동과 common I1 version·대표 질문·metric 동결은 남겼다. |
| v2.9 | 2026-07-30 16:26 | GitHub Actions는 원장의 권한·SHA·diff·handoff 증거와 Python·frontend·Compose·문서/WBS 품질을 읽기 전용으로 집계하고 Google Docs는 R1 최종 결정 채널로 사용하는 자동화 계약, PASS·FAIL·REVIEW_REQUIRED·NOT_RUN·N/A 기준, handoff 필수 필드와 자동/수동 판정 경계를 추가 |
| v2.8 | 2026-07-30 15:47 | R4 cleanup·R5 frontend handoff의 dev 통합과 root dev/full/split-host Compose 정적 소비를 확인해 R4·R5 follow-up을 MERGED_DEV로 전환하고, full profile에 남은 DataHub consumer fragment·immutable version·공식 source 보완을 R2-W1-F2 READY로 발행 |
| v2.7 | 2026-07-30 14:57 | 기존 읽기 전용 CI에 실행 카드 기반 역할 경로 검사와 R5 clean build job을 추가하고 terminal 역할의 신규 구현 차단·개인 일일보고 허용·자동 Git 작업 금지 정책을 기록 |
| v2.6 | 2026-07-30 14:52 | R2~R5 원격 작업을 재확인해 R4 cleanup 전용 R4-W1-F2를 READY로 발행하고, R5 clean handoff `ba5617b`의 npm ci·build·contract·container health를 독립 검증해 추가 구현을 중단시킴 |
| v2.5 | 2026-07-30 14:39 | R2 handoff `055b265`를 dev에 통합하고 service fragment 정적 소비 검증과 전체 테스트를 통과해 R2-W1-F1을 MERGED_DEV로 전환했으며 combined root Compose 검증은 R4·R5 fragment 도착까지 보류 |
| v2.4 | 2026-07-30 14:16 | R2 handoff `055b265`를 fragment·data test·Compose config로 검토해 REVIEW로 전환하고, R4 clean handoff `af6cc10`의 container readiness 통과와 cleanup 결함을 기록해 정확한 보완 commit·push만 허가 |
| v2.3 | 2026-07-30 14:01 | R5 handoff `140563f`의 typed contract·금지 route를 검토해 REVIEW로 전환하고 branch 오염·lockfile·clean build·frontend fragment·OpenAPI version 보완 전 I1 차단을 유지 |
| v2.2 | 2026-07-30 13:39 | READY 카드 `9925a88`의 dev 포함을 확인하고 R2-W1-F1의 지정 3개 파일에 한해 commit·seung push를 허가했으며 원격 제출 전 상태는 READY로 유지 |
| v2.1 | 2026-07-30 12:56 | `origin/jaehong`의 R4-W1-F1 handoff를 container·OpenAPI·role test로 독립 검토해 REVIEW로 전환하고 dev 통합·combined database readiness 재검증 전 I1 차단을 유지 |
| v2.0 | 2026-07-30 12:36 | R2-W1-F1·R4-W1-F1·R5-W1-F1 follow-up을 READY로 발행하고 역할별 허용 경로·검증·중단·외부 권한을 고정했으며 대표 질문·metric은 승인 전 N/A로 유지 |
| v1.9 | 2026-07-30 12:32 | R3 Dockerfile·실행 manifest를 I1 비필수로 판정하고 R3-W3 제출로 이관해 R1-W1의 R3 service fragment blocker를 해제 |
| v1.8 | 2026-07-30 12:03 | R2·R3 I1 입력을 승인하고 R4·R5 기존 Wave 1 재작업만 허가했으며 I1 Freeze·Wave 2는 보류 |
| v1.7 | 2026-07-30 11:53 | R1-W1 기준을 최신 `dev` SHA로 갱신하고 R1-03 차단 중 독립 진행한 Python 통합 CI와 필수 30·gold 120 평가 원장 schema를 기록 |
| v1.6 | 2026-07-30 11:35 | R1-W1 기준을 최신 통합 `dev` SHA로 갱신하고 R2~R5를 `MERGED_DEV`로 정합화했으며 R2·R3·R4 계약 도착과 R5 UI·Report·route 및 역할별 service fragment 차단 근거를 반영 |
| v1.5 | 2026-07-30 10:25 | R1~R5 Wave 1의 `BASE_SHA`를 현재 `dev` 기준 SHA `2c2779d23738038d5cd0560cffa70c5b509991c3`으로 교정하고, 활성 frontend 결정 후 R1-00~02 완료·R1-03 계약 입력 대기를 기록 |
| v1.4 | 2026-07-30 09:32 | Wave 1 기준 SHA를 현재 `dev`로 교정하고 LoRA 비교·worker·backup 절차와 I5 이후 F-01~F-04 비차단 후속 단계를 동기화 |
| v1.3 | 2026-07-29 17:35 | 최신 `dev` 통합 SHA `72292d9`를 기준으로 R1~R5 Wave 1 실행 묶음을 `READY`로 발행 |
| v1.2 | 2026-07-29 17:27 | 기획서 §1·3·5·7~11·14~20·22 추적성 대조와 기술·평가·보안·복구 수용 조건 보강 |
| v1.1 | 2026-07-29 17:24 | 병합 충돌과 자율 진행량을 균형화한 4개 Wave 및 Wave 2~4 역할별 상세 계획 카드 보강 |
| v1.0 | 2026-07-29 17:11 | I0~I5 역할별 실행 묶음 원장과 Wave 1 발행 준비 카드 5개 작성 |
