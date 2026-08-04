# Gate 실행 카드 원장

| 항목 | 내용 |
|---|---|
| 문서 설명 | 역할별 자율 구현 범위와 Gate 중단·통합 조건을 관리하는 실행 카드 원장 |
| 문서 분류 | 일반 문서 |
| 버전 | v3.13 |
| 문서 기준일 | 2026-08-04 16:45 |
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
| `REVIEW_REQUIRED` | 제출된 handoff에 `NOT_RUN`, change request, 잔여 위험, 외부 download·image pull·비용·secret·데이터 전송·배포·Git 권한 요청이 존재 | R1 검토 큐에 표시하고 해소·예외 승인 전 terminal 제출 수용을 차단 |
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
`cancelled`는 전체 자동 품질 Gate를 실패시킨다. 개인 branch에서 handoff가
제출된 뒤 `FAIL` 또는 `REVIEW_REQUIRED`이면 terminal 제출 수용을 차단한다.
아직 handoff를 제출하지 않은 `READY`·`IN_PROGRESS`의 `NOT_RUN`은 정상 작업
상태이므로 자동 실패로 만들지 않는다. 미실행 검증·change request·잔여 위험·
외부 승인 요청은 manifest에서 삭제하지 않고 R1이 보완 완료 또는 명시적 예외를
판정한 뒤 상태를 갱신한다. 자동 품질 Gate 통과는
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
| R1-W1 | Wave 1·07/29~08/07 | R1 | I0 → I1 | R1-00~08 | 역할·범위·소유권·공통 계약·Compose·env·CI·I1 판정 | `VERIFIED_GATE` |
| R2-W1 | Wave 1·07/29~08/07 | R2 | I0 → I1 | R2-00~08 | registry·논리/물리 모델·seed·identity·quality·read-only | `MERGED_DEV` |
| R3-W1 | Wave 1·07/29~08/07 | R3 | I0 → I1 | R3-00~03, R3-07 | AI 범위·Node schema·fake·Node 1 baseline·Prompt Registry | `MERGED_DEV` |
| R3-W1-CLEAN | Wave 1 follow-up | R3 | 없음 → I1 | R3 문서 제출 재판정 | 사용자 override에 따라 R3 최신 기획 문서를 우선 통합하고 복구 작업 종료 | `MERGED_DEV` |
| R4-W1 | Wave 1·07/29~08/07 | R4 | I0 → I1 | R4-00~05 | backend 경계·OpenAPI·auth·DB·migration·Controller skeleton | `MERGED_DEV` |
| R5-W1 | Wave 1·07/29~08/07 | R5 | I0 → I1 | R5-00~04, R5-08 | 활성 frontend·IA·typed client·mock·Chat 상태·Report 계약 | `MERGED_DEV` |
| R2-W1-F1 | Wave 1 follow-up | R2 | 없음 → I1 | R2-09의 I1 service fragment 보완 | DataHub/database fragment·health·env 요구 | `MERGED_DEV` |
| R2-W1-F2 | Wave 1 follow-up | R2 | 없음 → I1 | R2-09의 DataHub consumer fragment 보완 | immutable version·official Compose source·health·env | `MERGED_DEV` |
| R2-W1-F3 | Wave 1 follow-up | R2 | 없음 → I1 | R2-09의 대표 질문 metric·JOIN 계약 보완 | 실제 PMS 수익 인식 필드·event-time CRM JOIN·I1 data version | `MERGED_DEV` |
| R4-W1-F1 | Wave 1 follow-up | R4 | 없음 → I1 | R4-20의 I1 container subset | backend Dockerfile·container health·runtime 증거 | `MERGED_DEV` |
| R4-W1-F2 | Wave 1 follow-up | R4 | 없음 → I1 | R4-W1-F1 cleanup 결함 수정 | container 검증 종료 코드·잔존 container 정리 | `MERGED_DEV` |
| R4-W1-F3 | Wave 1 follow-up | R4 | 없음 → I1 | R4-01의 OpenAPI/state/error version 동결 | 최종 OpenAPI version·동일 상태/오류 contract | `MERGED_DEV` |
| R4-W1-F3-CLEAN | Wave 1 follow-up | R4 | 없음 → I1 | R4-W1-F3 사전 개인 branch 복구 | 허용 범위 밖 제출본 변경을 `origin/dev` 상태로 복구 | `MERGED_DEV` |
| R5-W1-F1 | Wave 1 follow-up | R5 | 없음 → I1 | R5-01~04, R5-08, R5-18의 I1 보완 | 금지 route 차단·typed contract·lockfile·clean build | `MERGED_DEV` |
| R5-W1-F2 | Wave 1 follow-up | R5 | 없음 → I1 | R5-01·08의 UI/Report version 동결 | 최종 UI·Report·fixture version·OpenAPI 정합 | `MERGED_DEV` |
| R2-W1-F4 | Wave 1 finalization | R2 | 없음 → I1 | R2-00·09의 data contract 최종 승격 | `I1-v1.0.0` 실제 contract version·회귀 | `MERGED_DEV` |
| R3-W1-F1 | Wave 1 finalization | R3 | 없음 → I1 | R3-00·01·02·07의 model/prompt/fixture 최종 승격 | 최종 model I/O·prompt·fixture version·회귀 | `MERGED_DEV` |
| R4-W1-F4 | Wave 1 finalization | R4 | 없음 → I1 | R4-01의 OpenAPI 문서 정합 | README의 `OPENAPI-v1.0.0` 정합·회귀 | `MERGED_DEV` |
| R1-W2 | Wave 2·08/10~08/14 | R1 | 없음 → I2 | R1-07, R1-09 | 수용 subset·통합 profile·deterministic trace 판정 | `VERIFIED_GATE` |
| R2-W2 | Wave 2·08/10~08/14 | R2 | 없음 → I2 | R2-09~16 | PMS/CRM catalog·JOIN·adapter·정답 hash | `MERGED_DEV` |
| R3-W2 | Wave 2·08/10~08/14 | R3 | 없음 → I2 | R3-02, R3-06, R3-08 | deterministic fake·설명 schema·평가 runner | `MERGED_DEV` |
| R4-W2 | Wave 2·08/10~08/14 | R4 | 없음 → I2 | R4-04~13, R4-15 | Template→Context→G1→G2→Trino→G3→Artifact trace | `MERGED_DEV` |
| R4-W2-F2 | Wave 2 follow-up | R4 | 없음 → I2 | R4-04·07·11·20 보완 | DB Template·실제 Trino·migration·CORS runtime 연결 | `MERGED_DEV` |
| R4-W2-F3 | Wave 2 follow-up | R4 | 없음 → I2 | R4-20 container startup 보완 | immutable migration을 보존한 blank DB image startup | `MERGED_DEV` |
| R5-W2 | Wave 2·08/10~08/14 | R5 | 없음 → I2 | R5-03~07 | Chat·상태·Evidence·표·차트·Artifact bridge | `MERGED_DEV` |
| R5-W2-F1 | Wave 2 follow-up | R5 | 없음 → I2 | R5-04 source 실패 표시 보완 | API `retryable` 표시·R4 timeout fixture 소비 | `MERGED_DEV` |
| R5-W2-F2 | Wave 2 follow-up | R5 | 없음 → I2 | R5-01·03~07 실제 API 보완 | production HTTP client·실제 backend 화면 trace | `MERGED_DEV` |
| R1-W3 | Wave 3·08/17~08/21 | R1 | 없음 → I3 | R1-07, R1-10 | gold 관리·일반 질문·보안 기준선 판정 | `VERIFIED_GATE` |
| R2-W3 | Wave 3·08/17~08/21 | R2 | 없음 → I3 | R2-09~18 | 5 source·recipe·catalog·JOIN·watermark·fixture | `MERGED_DEV` |
| R2-W3-F1 | Wave 3 follow-up | R2 | 없음 → I3 | R2-18 평가 fixture 보강 | required30 결과 hash 연결·gold120 완성 | `MERGED_DEV` |
| R2-W3-F2 | Wave 3 review follow-up | R2 | 없음 → I3 | R2-18 평가 승인 상태 동기화 | R1·R2·R3 reviewer와 APPROVED 상태 반영 | `MERGED_DEV` |
| R3-W3 | Wave 3·08/17~08/21 | R3 | 없음 → I3 | R3-03~10, R3-12~14 | Node 1·2·2′·3·Base 비교·serving·trace | `MERGED_DEV` |
| R3-W3-F1C | Wave 3 compatibility follow-up | R3 | 없음 → I3 | R3-10 평가 manifest 소비 호환 | partial/full gold count consumer 검증 | `MERGED_DEV` |
| R3-W3-F2 | Wave 3 training package follow-up | R3 | 없음 → I3 | R3-10 학습 데이터 재생성·검증 도구 반입 | 제공된 training package 정적·재현성 검증 | `MERGED_DEV` |
| R3-W3-F3 | Wave 3 held-out follow-up | R3 | 없음 → I3 | R3-10 Gold·Acceptance 실행 입력 완성 | 원장 Gold 120건·Acceptance 30건 명시 선택·승인·로컬 Trino 검증 | `MERGED_DEV` |
| R3-W3-F10 | Wave 3 reference follow-up | R3 | 없음 → I3 | R3-07 Node 2·2′ reference 정합 | SQL FROM/JOIN과 references 정확 일치·불일치 1회 repair | `MERGED_DEV` |
| R3-W3-F11 | Wave 3 semantic SQL follow-up | R3 | 없음 → I3 | R3-07 승인 JOIN·기간·집계 의미 보완 | 승인 5-table JOIN·절대 기간·월 집계 PROMPT-v1.0.6 | `MERGED_DEV` |
| R4-W3 | Wave 3·08/17~08/21 | R4 | 없음 → I3 | R4-08~15, R4-18 | model client·repair 1회·Cache·Audit·권한 | `MERGED_DEV` |
| R4-W3-F4 | Wave 3 serving contract follow-up | R4 | 없음 → I3 | R4-08 실제 Base 응답 안정화 | SQL-only guided output·결정론적 metadata·전월 대비 기간 안전 검증 | `MERGED_DEV` |
| R5-W3 | Wave 3·08/17~08/21 | R5 | 없음 → I3 | R5-04~10, R5-14 | 오류 상태·Report proposal·Catalog mock | `MERGED_DEV` |
| R5-W3-F1C | Wave 3 compatibility follow-up | R5 | 없음 → I3 | R5-14 Catalog 계약 버전 호환 | frontend I3 data contract 상수 동기화 | `MERGED_DEV` |
| R1-W4 | Wave 4·08/24~09/02 | R1 | I4·RC1 → I5 | R1-11~13 | Report 통합·보안·장애·복구·성능·release manifest | `PLANNED` |
| R1-W4-F2 | Wave 4 model 전환 승인 | R1 | Gate 0 → I4 | R1-11 model checkpoint·비용 판정 | Instruct-2507 checkpoint·평가·비용·중단 조건 승인 | `IN_PROGRESS` |
| R1-W4-F3 | Wave 4 Base smoke 재작업 승인 | R1 | Gate 0 → I4 | R1-11 model 실패 분류·재평가 판정 | 첫 균형 표본의 Trino 타입 오류로 재평가 중단 | `BLOCKED` |
| R1-W4-F4 | Wave 4 Base SQL 타입 재검증 승인 | R1 | Gate 0 → I4 | R1-11 model 타입·범위 규칙 판정 | 일반 타입·synthetic 범위 규칙과 남은 비용 승인 | `IN_PROGRESS` |
| R2-W4 | Wave 4·08/24~09/02 | R2 | I4·RC1 → I5 | R2-17~19 + R2-03~16 회귀 | 5번째 source·빈 환경 재생성·schema/seed/watermark/hash 동결 | `PLANNED` |
| R2-W4-F1 | Wave 4 serving metadata follow-up | R2 | 없음 → I4 | R2-09~11 `serving.analytics` 정합 | live DataHub View URN·column·lineage·read-only 계약 | `BLOCKED` |
| R2-W4-F1A | Wave 4 serving metadata 권한 보완 | R2 | 없음 → I4 | R2-09~11 `serving.analytics` 정합 | View 소유자 위임 조회 권한과 metadata 계약 동시 검증 | `MERGED_DEV` |
| R2-W4-F2 | Wave 4 혼합 Context 계약 | R2 | Gate 0 → I4 | R2-10~14 승인 raw asset·JOIN 정합 | View 우선·CRM 단독·PMS–CRM JOIN의 명시적 live DataHub 계약 | `MERGED_DEV` |
| R2-W4-F2A | Wave 4 raw URN 교정 | R2 | Gate 0 → I4 | R2-10 DataHub URN exact-match | platform instance·database를 포함한 실제 raw URN 7개 교정 | `MERGED_DEV` |
| R2-W4-F3 | Wave 4 metric registry 생산 | R2 | Gate 0 → I4 | R2-10~14 metric semantic contract | 승인 asset별 metric·필수 필터를 versioned Context 계약으로 제공 | `MERGED_DEV` |
| R4-W4-F1A | Wave 4 serving Context 소비 보완 | R4 | Gate 0 → I4 | R4-06~11 `LIVE_DATAHUB` Context·G2 정합 | 승인 View를 질문별 60-column 상한으로 선별하고 권한·G2를 fail-closed 검증 | `MERGED_DEV` |
| R4-W4-F2 | Wave 4 혼합 Context 소비 | R4 | Gate 0 → I4 | R4-06~11 View·제한 raw Context·G2 정합 | 축약 raw URN이 live DataHub와 불일치해 생산자 교정 대기 | `BLOCKED` |
| R4-W4-F2A | Wave 4 혼합 Context 재검증 | R4 | Gate 0 → I4 | R4-06~11 live raw Context 재검증 | R2 URN 교정 통합 후 실제 CRM·PMS–CRM Context·G2 재검증 | `MERGED_DEV` |
| R3-W4 | Wave 4·08/24~09/02 | R3 | I4·RC1 → I5 | R3-11~15 + R3-01~10 회귀 | LoRA 1회 비교·조건부 채택·production client·전체 평가·fallback·release | `PLANNED` |
| R3-W4-F1 | Wave 4 model checkpoint 전환 | R3 | Gate 0 → I4 | R3-10~14 Instruct-2507 Base smoke·Validation | checkpoint 고정 완료, Validation v2 Context 계약 대기 | `BLOCKED` |
| R3-W4-F2 | Wave 4 Validation v2·Base 평가 | R3 | Gate 0 → I4 | R3-10~14 ID/OOD·Instruct-2507 Base | Validation-ID 75·OOD 75 잠금 완료, Base smoke 4/20로 중단 | `BLOCKED` |
| R3-W4-F3 | Wave 4 Base smoke 재작업 | R3 | Gate 0 → I4 | R3-10~14 prompt·평가 harness·Instruct-2507 Base | 첫 균형 표본의 `timestamp(3) <= varchar(7)` 오류로 중단 | `BLOCKED` |
| R3-W4-F4 | Wave 4 Base SQL 타입 재검증 | R3 | Gate 0 → I4 | R3-10~14 prompt 일반화·Instruct-2507 Base | 같은 균형 20건의 타입·범위·결과 동등성 재검증 | `READY` |
| R3-W4-F5 | Wave 4 metric filter 계약 보완 | R3 | Gate 0 → I4 | R3-01·07·09~14 metric filter 계약 | 구조화 필터 schema·prompt·Validation Context 보존 | `MERGED_DEV` |
| R4-W4 | Wave 4·08/24~09/02 | R4 | I4·RC1 → I5 | R4-16~21 + R4-01~15 회귀 | Report·worker·권한·복구·backend 전체 회귀·동결 | `PLANNED` |
| R4-W4-F3 | Wave 4 Report production 등록 | R4 | 없음 → I4 | R4-16 Report 공통 등록 | FastAPI·Alembic·권한·승인본 불변성·중복 실행 차단 | `MERGED_DEV` |
| R4-W4-F4 | Wave 4 metric registry 소비 | R4 | Gate 0 → I4 | R4-06~11 metric semantic Context·G2 | R2 registry를 권한별 Context·model payload·G2에 보존 | `READY` |
| R5-W4 | Wave 4·08/24~09/02 | R5 | I4·RC1 → I5 | R5-08~19 + R5-02~07 회귀 | Report·E2E·접근성·발표 route·fallback·frontend 동결 | `PLANNED` |
| R5-W4-F1 | Wave 4 12-column Report editor | R5 | 없음 → I4 | R5-11 Report editor | draft layout·keyboard 대안·승인본 불변성 | `MERGED_DEV` |

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
STATUS=VERIFIED_GATE
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=I0
TASK_CARD_RANGE=R1-00~08
CURRENT_TASK_CARD_ID=R1-08
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=04e5e6dfb1ab66d41d8235275bfe5a30290c7181
REMOTE_DEV_SHA=04e5e6dfb1ab66d41d8235275bfe5a30290c7181
REMOTE_CI_EVIDENCE=GitHub Actions run 30604495881 PASS
REMOTE_SYNC_STATE=VERIFIED
I0_DECISION_VERSION=I0-v1.0.0
CONTRACT_VERSION=I1-v1.0.0
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.0
MODEL_FIXTURE_VERSION=MODEL-FIXTURE-v1.0.0
BLOCKER=없음
R1_APPROVED_INPUTS=R2 data contract I1-v1.0.0·schema 1.0.0·seed 20260729·scenario 1.0.0; R3 MODEL-v1.0.0·PROMPT-v1.0.0·MODEL-FIXTURE-v1.0.0; R4 OPENAPI-v1.0.0; R5 UI-v1.0.0·REPORT-v1.0.0·UI-FIXTURE-v1.0.0
R3_SERVICE_FRAGMENT=N/A — R3-W3에서 model serving Dockerfile 또는 실행 manifest 제출
R1_REWORK_AUTHORIZATION=R2-W1-F4·R3-W1-F1·R4-W1-F4·R5-W1-F2는 MERGED_DEV·WAIT; R1-W2·R2-W2·R3-W2·R4-W2·R5-W2 READY
R3_USER_OVERRIDE=사용자가 origin/daesung 733307c의 최신 기획 문서를 충돌 시 R3 우선으로 dev 병합하도록 지시; 역할 scope failure는 명시적 override로 수용하고 요약본·공식 03 DOCX를 a0ac7ed로 통합
INDEPENDENT_PROGRESS=R1-04~06 root DataHub 통합 profile·env·재현 가능한 service fragment 검증과 Python·frontend·Compose·문서 품질 Gate 완료, R1-07 필수 30·gold 120 평가 원장 schema 준비
I1_GATE_EVIDENCE=data 8건·AI 15건·integration 16건·frontend build/contract·root dev/full/split-host Compose·service fragment PASS; dev CI run 30604495881 PASS
NEXT_WAVE_AUTHORIZATION=Wave 2 전 역할 READY; BASE_SHA=04e5e6dfb1ab66d41d8235275bfe5a30290c7181; TARGET_INTEGRATION_GATE=I2
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

### R3-W1-CLEAN

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W1-CLEAN
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3 개인 branch 허용 범위 복구
CURRENT_TASK_CARD_ID=R3-W1-CLEAN
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=aa605543a0395db4042b779e05a277932568449f
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R3-W1-CLEAN@aa60554
SUBMISSION_PERMISSION_STATUS=CLOSED_BY_USER_OVERRIDE
ALLOWED_PATHS=docs/Answervice_기획서_요약본.md; docs/deliverables/03_프로젝트기획서_29기_3팀.docx
FORBIDDEN_PATHS=위 2개 외 전체 경로
ACCEPTANCE_CRITERIA=사용자 지시에 따라 R3 최신 요약본과 공식 03 DOCX를 충돌 시 R3 우선으로 dev 통합
TEST_COMMANDS=문서 정책 검사; DOCX ZIP·python-docx 구조 검사; git diff --check; GitHub Actions
STOP_CONDITIONS=추가 작업 없음
HANDOFF=완료 — origin/daesung 733307c의 두 고유 문서를 a0ac7ed로 dev 통합
USER_OVERRIDE=R3 최신 문서를 dev에 병합하고 내용 충돌 시 R3 작성물을 우선하라는 2026-07-31 사용자 지시
VALIDATION_EVIDENCE=document-quality PASS; python-contracts PASS; DOCX ZIP 정상·142 paragraphs·24 tables·3 sections; LibreOffice 부재로 PNG render Not Run
INTEGRATION_SHA=a0ac7ed644e15028dc0417c9b477cee679727b5c
EXTERNAL_ACTION_PERMISSION=추가 문서·기능·Wave 2 변경·commit·push 불가; 다음 R1 READY 대기
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
STATUS=MERGED_DEV
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
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R2-W1-F3@e2ecee3
SUBMISSION_PERMISSION_STATUS=APPROVED
SUBMISSION_STATE=ACCEPTED_AND_MERGED_DEV
CONTRACT_VERSION=DRAFT-I1-v0.1; DATA_CANDIDATE_VERSION=I1-v1.0.0
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
R1_REVIEW_EVIDENCE=고유 변경 4개가 허용 경로와 manifest에 일치하고 role Gate·handoff PASS, data 8건·소비자 계약·JSON·diff와 CI run 30599951597 PASS
HANDOFF_SHA=b8ec6b9692f8fbe2172775876ac9a3b8d50c1313
INTEGRATION_SHA=47c1f9489c8b38c35c4c3766e5cbac86fbac0079
EXTERNAL_ACTION_PERMISSION=추가 제품 변경·commit·push·Wave 2 착수 불가; R1의 다음 실행 묶음 발행 대기
```

### R4-W1-F3

```text
STATUS=MERGED_DEV
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
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R4-W1-F3@e5eea60
SUBMISSION_PERMISSION_STATUS=APPROVED
SUBMISSION_STATE=ACCEPTED_AND_MERGED_DEV
PRODUCT_RESULT_SHA=c83809af317948095bfdc8a9a417de1bbc517160
PRODUCT_CI_EVIDENCE=GitHub Actions run 30599636125 PASS; backend 55건 PASS; OpenAPI export·diff 검사 PASS
ACTIVATION_EVIDENCE=origin/jaehong 14bedf8의 tree가 origin/dev e4c4651과 동일해 고유 diff 0건; R4-W1-F3-CLEAN 수용
OPENAPI_VERSION=OPENAPI-v1.0.0
HANDOFF_SHA=9da78aae7ea73e4cc82955c90fec108ba6a758b9
INTEGRATION_SHA=9da78aae7ea73e4cc82955c90fec108ba6a758b9
ALLOWED_PATHS=app/backend/app/contracts.py; app/backend/contracts/**; tests/backend/**
FORBIDDEN_PATHS=root Compose·.env.example·CI·source DDL·seed·src/data/**·src/ai/**·frontend·Report·docs/markdown/collaboration/**·docs/markdown/02_WBS.md
ACCEPTANCE_CRITERIA=producer constant·committed OpenAPI·state mapping·source registry·API fixture·backend test의 version을 OPENAPI-v1.0.0으로 일치, 기존 endpoint·schema·상태·오류·migration·runtime 동작 변경 0건
TEST_COMMANDS=python -m compileall -q app/backend tests/backend; python -m pytest -p no:cacheprovider tests/backend; python app/backend/scripts/export_openapi.py --check; git diff --check
STOP_CONDITIONS=version 치환 외 API·상태·오류·migration 동작 변경 필요; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=완료 — R1과 R5에 최종 OpenAPI version·변경 파일·회귀 결과 전달
EXTERNAL_ACTION_PERMISSION=추가 제품 변경·commit·push·Wave 2 착수 불가; R1의 다음 실행 묶음 발행 대기
```

### R5-W1-F2

```text
STATUS=MERGED_DEV
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
BASE_SHA=b81f8e15ec3bb7c54ac7f921bb5a62a1efc83e63
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R5-W1-F2@b81f8e1
SUBMISSION_PERMISSION_STATUS=ACCEPTED_AND_MERGED_DEV
OPENAPI_VERSION=OPENAPI-v1.0.0
UI_VERSION=UI-v1.0.0
REPORT_VERSION=REPORT-v1.0.0
UI_FIXTURE_VERSION=UI-FIXTURE-v1.0.0
ALLOWED_PATHS=app/enterprise-react/src/contracts/**; app/enterprise-react/src/data/analysisFixtures.ts; tests/frontend/**
FORBIDDEN_PATHS=root Compose·.env.example·CI·app/backend/**·source DDL·seed·src/data/**·src/ai/**·docs/markdown/collaboration/**·docs/markdown/02_WBS.md
ACCEPTANCE_CRITERIA=UI·Report·fixture version을 각 v1.0.0으로 고정하고 R4 OPENAPI-v1.0.0과 typed client·fixture·contract test를 일치, route·화면·Report 동작·dependency 변경 0건
TEST_COMMANDS=npm --prefix app/enterprise-react run build; node --test tests/frontend/contracts.test.mjs; git diff --check
STOP_CONDITIONS=version 치환 외 UI·Report 동작 또는 dependency 변경 필요; R4 최종 OpenAPI와 불일치; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=완료 — R1에 UI·Report·fixture·OpenAPI 최종 version과 build·contract 결과 전달
R1_REVIEW_EVIDENCE=제품 c600f65·handoff 3f143af의 허용 경로 6개, npm ci·production build·frontend contract·report·role gate·diff PASS, branch CI run 30602136889 PASS
R1_INTEGRATION_EVIDENCE=origin/minji 3f143af를 5a52c8f로 dev에 통합; dev CI run 30602295894 PASS
EXTERNAL_ACTION_PERMISSION=추가 제품 변경·commit·push·Wave 2 착수 불가; R1의 다음 실행 묶음 발행 대기
```

## I1 최종 version 승격 follow-up

### R2-W1-F4

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W1-F4
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-00·09의 data contract actual version 승격
CURRENT_TASK_CARD_ID=R2-00
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=f3038c9b44f06db75597933057a72e42502a00c8
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R2-W1-F4@f3038c9
SUBMISSION_PERMISSION_STATUS=ACCEPTED_AND_MERGED_DEV
CONTRACT_VERSION=I1-v1.0.0
ALLOWED_PATHS=src/data/r2_w1_contract.v1.json; src/data/source_registry.v1.json; tests/data/test_source_registry.py
FORBIDDEN_PATHS=DDL·seed·manifest·row count·checksum·metric·JOIN·adapter 동작·R1/R3/R4/R5 소유 경로
ACCEPTANCE_CRITERIA=두 JSON의 contract_version을 I1-v1.0.0으로 일치, candidate 값·schema·seed·scenario·metric·JOIN·data state 변경 0건, data·integration 소비자 회귀 통과
TEST_COMMANDS=python -m unittest discover -s tests/data -p "test_*.py"; python -m unittest tests.integration.test_wave1_contracts -v; git diff --check
STOP_CONDITIONS=version 치환 외 data 계약 변경 필요; DDL·seed·checksum drift; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=완료 — R1에 최종 data contract version·변경 파일·회귀 결과 전달
PRODUCT_RESULT_SHA=7051f91fc6a142b46ce74b2de48f45203f38a607
HANDOFF_SHA=510981bc798d8615ba8f839c218c61177f0a3fad
R1_REVIEW_EVIDENCE=data 8건·integration 1건·role gate·보고·diff와 branch CI run 30603374739 PASS
R1_INTEGRATION_EVIDENCE=origin/seung 510981b를 7e5e16c로 dev에 통합; dev CI run 30603556566 PASS
EXTERNAL_ACTION_PERMISSION=추가 제품 변경·commit·push·Wave 2 착수 불가; R1의 다음 실행 묶음 발행 대기
```

### R3-W1-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W1-F1
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-00·01·02·07의 model I/O·prompt·fixture version 승격
CURRENT_TASK_CARD_ID=R3-00
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=5a52c8f957614c2ea28cf8cfde84e15f35126d0d
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R3-W1-F1@5a52c8f
SUBMISSION_PERMISSION_STATUS=ACCEPTED_AND_MERGED_DEV
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.0
MODEL_FIXTURE_VERSION=MODEL-FIXTURE-v1.0.0
DEFERRED_BASE_MODEL_VERSION=DRAFT-BASE-v0.1·DRAFT-FAKE-BASE-v0.1 유지 — 실제 Base model 선택은 R3-W3
ALLOWED_PATHS=src/ai/contracts/node_io.v0.1.json; src/ai/fake_model.py; src/ai/prompt_registry.py; src/modelops/model_decision.v0.1.json; tests/ai/**
FORBIDDEN_PATHS=model·prompt 내용·schema 구조·Node 동작·serving·dependency·R1/R2/R4/R5 소유 경로
ACCEPTANCE_CRITERIA=model I/O·decision은 MODEL-v1.0.0, prompt는 PROMPT-v1.0.0, fake fixture는 MODEL-FIXTURE-v1.0.0으로 일치, Base model version과 prompt hash·Node 출력·경계 동작 변경 0건
TEST_COMMANDS=python -m compileall -q src/ai src/modelops tests/ai; python -m unittest discover -s tests/ai -p "test_*.py"; python -m unittest tests.integration.test_wave1_contracts -v; git diff --check
STOP_CONDITIONS=version 치환 외 schema·prompt·Node 동작 변경 필요; Base model 선택 필요; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=완료 — R1에 최종 model I/O·prompt·fixture version과 회귀 결과 전달
PRODUCT_RESULT_SHA=4c8eedf5ff54d40432c6fa129eaedc9473f164bf
HANDOFF_SHA=cb10eca702fe3d59c747435bc4a39fcc35e40f18
R1_REVIEW_EVIDENCE=AI 15건·integration 1건·Gate 13건·role gate·보고·diff와 branch CI run 30604028295 PASS
R1_INTEGRATION_EVIDENCE=origin/daesung cb10eca를 14259c8로 dev에 통합; dev CI run 30604145173 PASS
EXTERNAL_ACTION_PERMISSION=R3-W2 READY 범위 외 추가 제품 변경 금지
```

### R4-W1-F4

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W1-F4
TARGET_INTEGRATION_GATE=I1
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-01의 README OpenAPI version 정합
CURRENT_TASK_CARD_ID=R4-01
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=5a52c8f957614c2ea28cf8cfde84e15f35126d0d
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R4-W1-F4@5a52c8f
SUBMISSION_PERMISSION_STATUS=ACCEPTED_AND_MERGED_DEV
OPENAPI_VERSION=OPENAPI-v1.0.0
ALLOWED_PATHS=app/backend/README.md
FORBIDDEN_PATHS=API·state·error·migration·runtime·fixture·dependency·R1/R2/R3/R5 소유 경로
ACCEPTANCE_CRITERIA=README의 DRAFT-OPENAPI-v0.1 두 표기를 OPENAPI-v1.0.0으로 교체, 다른 문구·제품 동작 변경 0건, backend·integration 회귀 통과
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend; python app/backend/scripts/export_openapi.py --check; python -m unittest tests.integration.test_wave1_contracts -v; git diff --check
STOP_CONDITIONS=version 문구 치환 외 변경 필요; 제품 계약 drift; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=완료 — R1에 README 정합 diff와 backend·integration 회귀 결과 전달
PRODUCT_RESULT_SHA=2fa5b49f897c70df2ea255e227af2d01c1383baa
HANDOFF_SHA=825a0c2cf6dd63f887265fafd34e3f7e569bdc11
R1_REVIEW_EVIDENCE=README 두 표기 정합, integration 1건·Gate 13건·role gate·보고·diff와 branch CI run 30604368794 전체 PASS
R1_INTEGRATION_EVIDENCE=origin/jaehong 825a0c2를 04e5e6d로 dev에 통합; dev CI run 30604495881 PASS
EXTERNAL_ACTION_PERMISSION=R4-W2 READY 범위 외 추가 제품 변경 금지
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

```text
STATUS=VERIFIED_GATE
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W2
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R1-07·09
CURRENT_TASK_CARD_ID=R1-09
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=04e5e6dfb1ab66d41d8235275bfe5a30290c7181
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W2@04e5e6d
CONTRACT_VERSION=I1-v1.0.0
REMOTE_DEV_SHA=56cbf08f70b984ca34c74361062a3c90883c209c
REMOTE_CI_EVIDENCE=GitHub Actions run 30784368551 PASS
REMOTE_SYNC_STATE=VERIFIED
BLOCKER=없음
R1_PROGRESS=R4 실제 DB Template·역할 정책·blank/existing DB migration·Trino runtime과 R5 production HTTP client를 순차 통합하고, 성공·재질문·차단·source 실패를 실제 browser에서 독립 확인해 I2 네 필수 runtime을 모두 승인; 필수 30건·Gold 120건 전체 세트는 R1-07 후속 범위로 0/30·0/120 유지
I2_GATE_EVIDENCE=R2 GOLD hash e6c2d1e…08fd; R3 deterministic runner; R4 Template→G1→G2→실제 Trino→G3→Artifact·role 403·source failure; R5 production browser 성공·재질문·차단·source 실패와 retryable 표시; integration 22건 PASS; R5 branch CI 30782796303·dev CI 30784368551 PASS
NEXT_WAVE_AUTHORIZATION=N/A — R1 I2 판정 commit을 dev에 통합한 SHA에서 Wave 3 역할별 묶음을 별도 READY 발행
ALLOWED_PATHS=.github/**; compose*.yml; .env.example; .dockerignore; config/access-policy.yaml; tests/integration/**; docs/Answervice_기획서.md; docs/deliverables/02_WBS_29기_3팀.xlsx; docs/markdown/02_WBS.md; docs/markdown/collaboration/**
R1_SCOPE_AUTHORIZATION=사용자 요청에 따라 기획서 v1.2와 동기화한 공식 WBS XLSX 단일 경로의 작성·덮어쓰기·commit·junhee push를 승인; 다른 deliverable 경로는 승인하지 않음
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현
ACCEPTANCE_CRITERIA=필수 평가 subset·gold 원장을 확인하고 대표 질문의 Context→G1→G2→Trino→G3→Artifact→화면 trace에서 성공·재질문·차단·source 실패를 판정, 역할별 실패는 원 소유자에게 반환
ACCEPTANCE_IDS=AC1_TEMPLATE_RUNTIME;AC2_TRINO_RUNTIME;AC3_BROWSER_RUNTIME;AC4_FAILURE_RUNTIME
TEST_COMMANDS=python -m unittest discover -s tests/integration -p "test_*.py"; python .github/scripts/gate_scope.py --dashboard --next-gate I3; python .agents/skills/manage-project-documents/scripts/check_document_policy.py docs/markdown/02_WBS.md docs/markdown/collaboration/Gate_실행_카드_원장.md; git diff --check
TEST_COMMAND_IDS=T1_INTEGRATION;T2_DASHBOARD;T3_DOCUMENT_POLICY;T4_DIFF_CHECK
STOP_CONDITIONS=필수 producer contract 미도착; trace ID 단절; 소비자 contract test 실패; R2~R5 소유 경로 변경 필요
HANDOFF=역할별 실패를 원 소유자에게 반환하고 I2 병합 순서·통합 회귀 결과를 전 역할에 전달
EXTERNAL_ACTION_PERMISSION=R1 허용 경로의 commit·junhee push와 검증만 승인; dependency 설치·비용·배포·secret·데이터 전송·dev merge는 별도 통합 판정
```

### R2-W2

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W2
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-09~16
CURRENT_TASK_CARD_ID=R2-16
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=04e5e6dfb1ab66d41d8235275bfe5a30290c7181
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R2-W2@04e5e6d
RESULT_SHA=75f148b3d9cf8ac7c7bd2ba34cb46248e3927ee8
HANDOFF_SHA=de0a26f7c3315a9d690068baa79f2aae920a1c72
MERGED_DEV_SHA=5afb90bf994c6e0f76f1546a9ea90ccd8c2ea258
CI_EVIDENCE=branch run 30605617536 PASS; dev run 30605760842 PASS
CONTRACT_VERSION=I1-v1.0.0
ALLOWED_PATHS=infrastructure/database/**; src/data/**; tests/data/**
FORBIDDEN_PATHS=app/backend/**; src/ai/**; src/modelops/**; frontend·Report; root Compose·.env.example·CI; R1/R3/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=PMS/CRM recipe·URN/FQN·lineage와 typed DataHub adapter, Trino catalog·type·승인 JOIN·대표 질문 정답 hash·query lifecycle을 제공하고 PMS/CRM 원천 결과와 Trino hash 일치, 비승인 JOIN·증폭·null·timeout·cancel·partial fixture를 구분
TEST_COMMANDS=docker compose -f infrastructure/database/compose.yml config; powershell -ExecutionPolicy Bypass -File infrastructure/database/scripts/verify.ps1; python -m unittest discover -s tests/data -p "test_*.py"; git diff --check
STOP_CONDITIONS=source credential 필요; 원천/Trino hash 불일치; 승인되지 않은 cross-role schema 변경; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R4에 typed adapter·URN/FQN·정답 hash, R5에 source·metric·filter fixture, R1에 재현 명령과 manifest 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R2 개인 일일보고·handoff manifest의 commit·seung push 승인; dependency 설치·외부 데이터 전송·비용·배포·secret·dev merge 불가
```

### R3-W2

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W2
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-02·06·08
CURRENT_TASK_CARD_ID=R3-08
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=04e5e6dfb1ab66d41d8235275bfe5a30290c7181
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R3-W2@04e5e6d
RESULT_SHA=345a788ebfb095786b70034476e304b549e2e54e
HANDOFF_SHA=f4f25631fa7cce7af7640ba30d216fd481786929
MERGED_DEV_SHA=f2817a0b7c041ba296184334350341c7a00c381f
CI_EVIDENCE=branch run 30605387557 PASS; dev run 30605486384 PASS
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.0
MODEL_FIXTURE_VERSION=MODEL-FIXTURE-v1.0.0
ALLOWED_PATHS=src/ai/**; src/modelops/**; evals/**; tests/ai/**
FORBIDDEN_PATHS=source DDL·seed·src/data/**; app/backend/**·G1·G2·G3; frontend·Report; root Compose·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=deterministic fake 회귀, G3 pass shaped result만 받는 Node 3, 평가 runner를 제공하고 동일 입력 출력·평가를 재현하며 G3 실패와 schema 초과·누락 field를 거부; Node는 권한·SQL 실행·Gate 결과를 재판정하지 않음
TEST_COMMANDS=python -m compileall -q src/ai src/modelops evals tests/ai; python -m unittest discover -s tests/ai -p "test_*.py"; git diff --check
STOP_CONDITIONS=Node가 권한·Gate·SQL 결과를 재판정해야 함; gold fixture drift; schema 검증 실패; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R4에 model contract·fake endpoint, R1에 평가 subset 결과·실패 case와 manifest 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R3 개인 일일보고·handoff manifest의 commit·daesung push 승인; dependency 설치·외부 model 호출·비용·배포·secret·데이터 전송·dev merge 불가
```

### R4-W2

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W2
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-04~13·15
CURRENT_TASK_CARD_ID=R4-15
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=04e5e6dfb1ab66d41d8235275bfe5a30290c7181
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R4-W2@04e5e6d
OPENAPI_VERSION=OPENAPI-v1.0.0
ALLOWED_PATHS=app/backend/**; tests/backend/**
FORBIDDEN_PATHS=source DDL·seed·src/data/**; src/ai/**·src/modelops/**; frontend·Report; root Compose·.env.example·CI; R1/R2/R3/R5 소유 문서
ACCEPTANCE_CRITERIA=Router→Controller→Context→G1→model→G2→repair 최대 1회→query→G3→Artifact와 trace를 고정 상태 전이로 재현, Context Package 최대 8 dataset·60 column·6k token/25% 상한, Gate 우회·repair 2회·G3 실패 Artifact 차단
TEST_COMMANDS=python -m compileall -q app/backend tests/backend; python -m pytest -p no:cacheprovider tests/backend; python app/backend/scripts/export_openapi.py --check; git diff --check
STOP_CONDITIONS=R2/R3 contract 불일치; migration 다중 head; 불법 상태 전이; 허용 경로 밖 변경 필요; 필수 contract test 실패
HANDOFF=R5에 OpenAPI example·상태 fixture·Artifact contract, R1에 request→artifact trace와 manifest 전달
R1_REVIEW_EVIDENCE=origin/jaehong b671ca5와 handoff 2924d0b의 허용 경로·11개 완료 카드·OPENAPI-v1.0.0·Context/Policy version·branch CI run 30606533152 PASS·Not Run/잔여 위험/외부 승인 0건 확인
R1_INTEGRATION_EVIDENCE=e34442d로 제품을 dev에 병합하고 pipeline 8건·integration 16건을 독립 실행했으며 보고 통합 1789ba2와 dev CI run 30606915908 PASS 확인
EXTERNAL_ACTION_PERMISSION=허용 경로와 R4 개인 일일보고·handoff manifest의 commit·jaehong push 승인; dependency 설치·비용·배포·secret·데이터 전송·dev merge 불가
```

### R4-W2-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W2-F1
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-04~13·15 보강
CURRENT_TASK_CARD_ID=R4-W2-F1
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=6a82fff05ab489d9e18ab946551f0dfe098c0845
SOURCE_CANDIDATE_SHA=caaa94a7d81390c9b674d713b8b56b873eb9a2ec
SOURCE_HEAD=08c8db23fe680e8d59919f1db67f1f1a67ff42ad
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R4-W2-F1@6a82fff
OPENAPI_VERSION=OPENAPI-v1.0.0
ALLOWED_PATHS=app/backend/app/adapters/fake_data_platform.py; app/backend/app/adapters/fake_model.py; app/backend/app/services/analysis_responses.py; app/backend/app/services/analysis_service.py; app/backend/app/services/pipeline_support.py; tests/backend/test_analysis_pipeline.py
FORBIDDEN_PATHS=그 밖의 app/backend/**; source DDL·seed·src/data/**; src/ai/**·src/modelops/**; frontend·Report; root Compose·.env.example·CI; R1/R2/R3/R5 소유 문서
ACCEPTANCE_CRITERIA=전달한 기존 후보를 최신 dev에 적용해 고정 상태 전이·OPENAPI-v1.0.0·Gate 우회 금지·repair 최대 1회·G3 실패 Artifact 차단을 보존하고 변경 목적과 전후 동작을 handoff에 명시
TEST_COMMANDS=python -m compileall -q app/backend tests/backend; python -m pytest -p no:cacheprovider tests/backend; python app/backend/scripts/export_openapi.py --check; python -m unittest discover -s tests/integration -p "test_*.py"; git diff --check
STOP_CONDITIONS=후보 SHA를 복구할 수 없음; 허용 6개 제품·테스트 경로 밖 변경 필요; OpenAPI drift; 불법 상태 전이; 필수 검증 실패
HANDOFF=R1에 최신 dev 기준 RESULT_SHA·실제 diff·변경 목적·전후 동작·검증 결과·Not Run·잔여 위험을 manifest로 제출
R1_REVIEW_NOTE=Google Docs HANDOFF의 후보 caaa94a는 현재 R1 저장소와 origin/jaehong에서 조회되지 않아 제품 수용이 아니라 제한된 개인 branch 제출·검토 권한만 발행
R1_REVIEW_EVIDENCE=origin/jaehong 08c8db2·handoff R4-W2-F1의 최신 dev 기준 8개 고유 경로, 변경 목적·전후 동작, Not Run·잔여 위험·외부 승인 0건, branch CI run 30609007535 전체 PASS, role gate·handoff PASS 확인
R1_INTEGRATION_EVIDENCE=f8e4740으로 제품·R4 보고·handoff를 dev에 병합하고 pipeline 15건·integration 16건·compileall·보고 validator를 독립 실행했으며 팀 보고 4db0503과 dev CI run 30609351155 전체 PASS 확인
EXTERNAL_ACTION_PERMISSION=허용 6개 경로와 R4 개인 일일보고·handoff manifest의 commit·jaehong push 승인; dependency 설치·비용·배포·secret·데이터 전송·dev merge 불가
```

### R4-W2-F2

`origin/jaehong` 제품 `4bec9d7`·handoff `b812122`을 독립 검토한 결과 기존 migration upgrade, Template 역할 권한, Trino PARTIAL 오류 처리와 실제 HTTP 재현 증거가 수용 기준을 충족하지 못해 아래 최소 재작업만 승인한다.

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W2-F2
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-04·07·11·20 runtime 보완
CURRENT_TASK_CARD_ID=R4-W2-F2
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=e023b0640020248ec35c998b9de637a67012cdaa
SOURCE_HEAD=80c30ec1abd15078f035392ae7b5bb27123b6b5c
PRODUCT_RESULT_SHA=3fb5e142604cc18d45c35885beb7d0587c3ab213
HANDOFF_SHA=80c30ec1abd15078f035392ae7b5bb27123b6b5c
MERGED_DEV_SHA=b1e33c6a5cc483172c3b46922318e99cffe906f6
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R4-W2-F2-REWORK@e023b06
OPENAPI_VERSION=OPENAPI-v1.0.0
ACCESS_POLICY_VERSION=ACCESS-POLICY-v1.0.0
ALLOWED_PATHS=app/backend/**; tests/backend/**
FORBIDDEN_PATHS=source DDL·seed·src/data/**; src/ai/**·src/modelops/**; frontend·Report; root Compose·.env.example·CI; R1/R2/R3/R5 소유 문서
ACCEPTANCE_CRITERIA=기존 `20260730_02`를 dev와 byte-for-byte 동일하게 복구하고 새 후속 revision에서 기존 02 DB와 빈 DB 모두에 컬럼 backfill·NOT NULL·승인 Template seed·최소 runtime grant를 적용하며, `config/access-policy.yaml`의 `ACCESS-POLICY-v1.0.0`에 따라 `hotel_analyst`만 Template·자산을 통과시키고 다른 유효 role은 서버에서 403으로 거부한다. R2 AdapterError의 실제 구조로 FINISHED+warnings를 PARTIAL 응답에 보존하고, real mode HTTP template 요청이 G1→G2→Trino→G3→query_id·Artifact까지 이어져야 한다. exact CORS와 기존 R2 TrinoAdapter 재사용은 유지한다.
ACCEPTANCE_IDS=AC1_IMMUTABLE_MIGRATION;AC2_EXISTING_DB_UPGRADE;AC3_TEMPLATE_ROLE_POLICY;AC4_TRINO_PARTIAL;AC5_REAL_HTTP_TEMPLATE_TRACE;AC6_EXACT_CORS
TEST_COMMANDS=python -m compileall -q app/backend tests/backend; python -m pytest -p no:cacheprovider tests/backend; python app/backend/scripts/export_openapi.py --check; python -m unittest discover -s tests/integration -p "test_*.py"; 빈 DB와 기존 `20260730_02` DB 각각 `alembic upgrade head`; real mode HTTP Template positive·report_admin/data_admin negative·FINISHED+warnings PARTIAL; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_COMPILE;T2_BACKEND;T3_OPENAPI;T4_INTEGRATION;T5_MIGRATION_PATHS;T6_REAL_HTTP_ROLE_PARTIAL;T7_ROLE_GATE;T8_DIFF_CHECK
STOP_CONDITIONS=기존 revision 수정; R2 adapter 수정 필요; migration 다중 head; role·entitlement·G1·G2·G3 우회; immutable trace에 UPDATE·DELETE 권한 필요; wildcard CORS 필요; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R1에 기존 02 파일 hash 일치, 빈·기존 DB upgrade, hotel_analyst 승인과 report_admin/data_admin 거부, 실제 Trino PARTIAL, real HTTP query_id·Artifact trace, CORS 허용·거부 결과를 ID별 manifest로 제출
R1_REVIEW_EVIDENCE=origin/jaehong 제품 4bec9d7·handoff b812122·branch CI run 30619550796 PASS를 검토했으나 기존 02 revision 수정과 grant-only 03으로 기존 DB upgrade가 누락되고, role/entitlement 없는 Template·자산 조회, AdapterError.payload 오참조, fake mode 중심 HTTP 증거를 확인해 병합 거부
R1_INTEGRATION_EVIDENCE=최종 80c30ec의 기존 02 blob 불변, 새 03의 빈·기존 DB upgrade와 SELECT·INSERT 최소 grant, hotel_analyst 허용·report_admin/data_admin 403, 실제 Trino PARTIAL·query_id·Artifact, exact CORS, role Gate와 branch CI run 30779910256 PASS를 확인해 b1e33c6으로 dev 통합
EXTERNAL_ACTION_PERMISSION=N/A — R4-W2-F2 완료; 다음 Wave 승인 전 WAIT
```

### R4-W2-F3

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W2-F3
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-20 container startup 보완
CURRENT_TASK_CARD_ID=R4-W2-F3
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=cee1ca2e272f182159be7aff5ee9874ff0c6c85b
SOURCE_HEAD=51947de078da381de3158238588be15969b7bfbb
PRODUCT_RESULT_SHA=3f8a2cfc8fdcd229af8f8e07d6b47deaf58bc3d5
HANDOFF_SHA=51947de078da381de3158238588be15969b7bfbb
MERGED_DEV_SHA=158a493349cf7fc7f20e5faec529852b61ec3562
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R4-W2-F3@cee1ca2
OPENAPI_VERSION=OPENAPI-v1.0.0
ALLOWED_PATHS=app/backend/Dockerfile; tests/backend/test_control_plane_contract.py
FORBIDDEN_PATHS=app/backend/migrations/**; 그 밖의 app/backend/**·tests/backend/**; source DDL·seed·src/data/**; frontend·Report; root Compose·.env.example·CI; R1/R2/R3/R5 소유 문서
ACCEPTANCE_CRITERIA=기존 migration 파일을 byte-for-byte 보존한 채 Docker image 안에 repository layout을 유지해 normal entrypoint의 `alembic upgrade head`가 빈 DB에서 20260730_02의 DDL과 20260731_03의 Template SQL·접근 정책을 모두 찾고 backend가 healthy·ready가 된다. 기존 DB upgrade와 real Trino 경로는 회귀하지 않으며 검증용 임시 DB·container를 삭제한다.
ACCEPTANCE_IDS=AC1_IMMUTABLE_MIGRATIONS;AC2_BLANK_DB_IMAGE_STARTUP;AC3_READY_DEPENDENCIES;AC4_EXISTING_DB_REGRESSION;AC5_CLEANUP
TEST_COMMANDS=기존 migration Git blob hash dev 일치; docker build -f app/backend/Dockerfile; 임시 blank DB에 built image normal entrypoint 기동; /health·/readiness의 migration·approved_templates·trino 상태 확인; python -m unittest discover -s tests/backend; python -m unittest discover -s tests/integration; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_MIGRATION_HASH;T2_IMAGE_BUILD;T3_BLANK_ENTRYPOINT;T4_READINESS;T5_BACKEND;T6_INTEGRATION;T7_ROLE_GATE;T8_DIFF_CHECK
STOP_CONDITIONS=기존 migration 수정; backend runtime code 변경 필요; dependency 추가; root Compose 변경; 다른 Docker project·volume 변경; 허용 경로 밖 변경 필요; blank DB normal entrypoint 또는 readiness 실패
HANDOFF=R1에 before/after image startup 결과, migration head, readiness dependency 값, 기존 migration hash, 임시 DB·container 삭제와 ID별 manifest를 제출
R1_REVIEW_EVIDENCE=R5-W2-F2 실제 browser 준비 중 accepted image의 normal entrypoint가 빈 DB에서 20260730_02의 repository-relative DDL 경로를 찾지 못해 종료됨을 재현했다. bind mount·migration bypass는 production 수용 근거로 인정하지 않는다.
R1_INTEGRATION_EVIDENCE=제품 3f8a2cf·handoff 51947de의 migration 무변경, built image blank DB normal entrypoint head 20260731_03, health·전체 readiness·existing DB·실제 Trino·cleanup, role Gate와 branch CI run 30781472877 PASS를 확인해 158a493으로 dev 통합
EXTERNAL_ACTION_PERMISSION=N/A — R4-W2-F3 완료; 다음 Wave 승인 전 WAIT
```

### R5-W2

```text
STATUS=MERGED_DEV
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W2
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R5-03~07
CURRENT_TASK_CARD_ID=R5-07
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=6b37f5750e492be76d73c1034977fa0815f58773
SOURCE_HEAD=d1f6a74d1b316efe17f8b76a2aaa6e37548cc682
PRODUCT_RESULT_SHA=58aa7069eeba3feaeecbfcaa76ebe4dea4031d6e
HANDOFF_SHA=d1f6a74d1b316efe17f8b76a2aaa6e37548cc682
MERGED_DEV_SHA=555ea14bd7b0b933129392ef9ca381fa0a5a6a0d
REPORT_SHA=79ba385e5fc031d96b7e0c983844f66ad431d643
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R5-W2@6b37f57
OPENAPI_VERSION=OPENAPI-v1.0.0
UI_VERSION=UI-v1.0.0
REPORT_VERSION=REPORT-v1.0.0
UI_FIXTURE_VERSION=UI-FIXTURE-v1.0.0
ALLOWED_PATHS=app/enterprise-react/**; tests/frontend/**
FORBIDDEN_PATHS=app/react/**; app/backend/**; source DDL·seed·src/data/**; src/ai/**·src/modelops/**; root Compose·.env.example·CI; R1/R2/R3/R4 소유 문서
ACCEPTANCE_CRITERIA=Chat shell·전체 상태 UI·Evidence·표·차트·Artifact bridge에서 request/run/artifact ID, metric·단위·기간·as_of·filter·source와 loading·blocked·partial·failed 상태를 API 결과 재계산 없이 표시
TEST_COMMANDS=npm --prefix app/enterprise-react run build; node --test tests/frontend/contracts.test.mjs; git diff --check
STOP_CONDITIONS=활성 frontend 밖 수정 필요; API 결과·권한·Gate 재계산 필요; 허용 경로 밖 변경 필요; build 또는 mock/contract 검증 실패
HANDOFF=R1에 성공·재질문·차단·partial·source 실패 화면 증거, R4에 response drift·필요 contract diff와 manifest 전달
R1_REVIEW_EVIDENCE=제품 58aa706·handoff d1f6a74의 허용 경로·R4 g1_clarification fixture 계약·production build·frontend contract·role gate·branch CI run 30609754303 PASS와 browser의 추가 정보 필요/재질문·요청 차단·정상·partial·source 실패·Artifact bridge·console error 0건을 확인
R1_INTEGRATION_EVIDENCE=제품·R5 보고·handoff를 555ea14로 dev에 병합하고 팀 보고 79ba385, data·AI·backend·integration 51건·frontend build/contract·compileall과 dev CI run 30610065590 전체 PASS 확인
EXTERNAL_ACTION_PERMISSION=허용 경로와 R5 개인 일일보고·handoff manifest의 commit·minji push 승인; dependency 설치·비용·배포·secret·데이터 전송·dev merge 불가
```

### R5-W2-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W2-F1
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R5-04 source 실패 표시 보완
CURRENT_TASK_CARD_ID=R5-W2-F1
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=79ba385e5fc031d96b7e0c983844f66ad431d643
SOURCE_HEAD=dce723bd845e8de91a99365e08f7df862071ec5c
PRODUCT_RESULT_SHA=f356f1a28739ed1264e5a72282811256346d41e2
HANDOFF_SHA=dce723bd845e8de91a99365e08f7df862071ec5c
MERGED_DEV_SHA=6bd191c9519986e506cad2a17f11ebd92bf14533
REPORT_SHA=5652e4e7aaf70a009610f03507c0d5c9eb2eba85
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R5-W2-F1@79ba385
OPENAPI_VERSION=OPENAPI-v1.0.0
UI_VERSION=UI-v1.0.0
ALLOWED_PATHS=app/enterprise-react/src/components/analysis/AnalysisStatePanel.tsx; app/enterprise-react/src/data/analysisFixtures.ts; app/enterprise-react/src/styles.css; tests/frontend/contracts.test.mjs
FORBIDDEN_PATHS=그 밖의 app/enterprise-react/**; app/react/**; app/backend/**; source DDL·seed·src/data/**; src/ai/**·src/modelops/**; root Compose·.env.example·CI; R1/R2/R3/R4 소유 문서
ACCEPTANCE_CRITERIA=QUERY_SOURCE_FAILED 화면이 API error.message와 retryable을 재계산 없이 보존해 각각 `다시 시도 가능` 또는 `다시 시도 불가`로 표시하고 Artifact를 만들지 않으며, R4 timeout fixture 기반 contract test와 source 실패·partial browser 증거를 제출하고 기존 성공·재질문·차단·Artifact bridge를 보존
TEST_COMMANDS=npm --prefix app/enterprise-react run build; node --test tests/frontend/contracts.test.mjs; python .github/scripts/gate_scope.py --branch minji --base origin/dev --head HEAD --mode merge-base; git diff --check
STOP_CONDITIONS=API contract 변경 필요; 활성 frontend 밖 수정 필요; retryable·권한·Gate를 frontend가 재계산해야 함; 허용 경로 밖 변경 필요; build 또는 contract 검증 실패
HANDOFF=R1에 실제 R4 timeout fixture 기반 retryable contract 결과, source 실패·partial browser 문구와 console error, 기존 상태 회귀 결과를 manifest로 제출
R1_REVIEW_EVIDENCE=제품 f356f1a·handoff dce723b의 허용 경로, API retryable 표시·Artifact 미생성·partial 보존 browser 증거, build·frontend contract·integration 17건·role gate와 branch CI run 30612008099 전체 PASS 확인
R1_INTEGRATION_EVIDENCE=제품·R5 보고·handoff를 6bd191c로 dev에 병합하고 팀 보고 5652e4e와 dev CI run 30614284494 전체 PASS 확인
EXTERNAL_ACTION_PERMISSION=허용 4개 경로와 R5 개인 일일보고·handoff manifest의 commit·minji push 승인; dependency 설치·비용·배포·secret·데이터 전송·dev merge 불가
```

### R5-W2-F2

`R5-W2-F1`과 `R4-W2-F2`의 `MERGED_DEV`를 확인해 실제 backend 화면 연결 범위를 승인했다.

```text
STATUS=MERGED_DEV
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W2-F2
TARGET_INTEGRATION_GATE=I2
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R5-01·03~07 실제 API 보완
CURRENT_TASK_CARD_ID=R5-W2-F2
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
ORIGINAL_BASE_SHA=b1e33c6a5cc483172c3b46922318e99cffe906f6
BASE_SHA=158a493349cf7fc7f20e5faec529852b61ec3562
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R5-W2-F2-RESUME@158a493
BLOCKER_RESOLVED_BY=R4-W2-F3 MERGED_DEV 158a493
OPENAPI_VERSION=OPENAPI-v1.0.0
UI_VERSION=UI-v1.0.0
PRODUCT_RESULT_SHA=dae606f7915c5d0cb9641dc4565bf74bf822c4f8
FINAL_BRANCH_SHA=ab1d7252bbe4a07084915f9d4e20a723b39c0239
BRANCH_CI_EVIDENCE=GitHub Actions run 30782796303 PASS
DEV_INTEGRATION_EVIDENCE=dev 56cbf08f70b984ca34c74361062a3c90883c209c·GitHub Actions run 30784368551 PASS
ALLOWED_PATHS=app/enterprise-react/**; tests/frontend/**
FORBIDDEN_PATHS=app/react/**; app/backend/**; source DDL·seed·src/data/**; src/ai/**·src/modelops/**; root Compose·.env.example·CI; R1/R2/R3/R4 소유 문서
ACCEPTANCE_CRITERIA=production 화면은 환경변수의 backend base URL을 사용하는 실제 HTTP client로 /analysis를 호출하고 mock은 test·발표 fallback에서만 사용하며, Template 성공·재질문·차단·source 실패 응답의 request_id·trace_id·query_id·artifact_id·retryable을 재계산 없이 화면에 표시
ACCEPTANCE_IDS=AC1_REAL_HTTP_CLIENT;AC2_NO_PRODUCTION_MOCK;AC3_TEMPLATE_BROWSER_TRACE;AC4_FAILURE_BROWSER_TRACE
TEST_COMMANDS=npm --prefix app/enterprise-react run build; node --test tests/frontend/contracts.test.mjs; python .github/scripts/gate_scope.py --branch minji --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_BUILD;T2_FRONTEND_CONTRACT;T3_ROLE_GATE;T4_DIFF_CHECK
STOP_CONDITIONS=OpenAPI drift; frontend가 권한·Gate·retryable을 재계산해야 함; backend 수정 필요; 양쪽 frontend 수정 필요; 허용 경로 밖 변경 필요; build·contract 실패
HANDOFF=R1에 실제 backend를 사용한 Template·실패 browser trace, network request/response, console error 0건과 ID별 manifest를 제출
EXTERNAL_ACTION_PERMISSION=보존된 4개 frontend/test 변경과 허용 경로 내 후속, R5 개인 일일보고·handoff manifest의 commit·minji push 승인; dependency 설치·비용·배포·secret·데이터 전송·dev merge 불가
```

## Wave 3 상세 계획 카드

Wave 3는 I2에서 검증한 전체 왕복을 5 source와 실제 general LLM 경로로 확장한다. I2 병합 완료 SHA를 기준으로 역할별 기능을 적당한 크기로 나눠 I3에서 통합한다.

### R1-W3

```text
STATUS=VERIFIED_GATE
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W3
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R1-07·10
CURRENT_TASK_CARD_ID=R1-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=744592ab129ed44c0cfcf5cf860b8945b011a324
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W3@744592a
I2_GATE_VERSION=I2-v1.0.0
CONTRACT_VERSION=I1-v1.0.0
BASE_DEV_CI_EVIDENCE=GitHub Actions run 30785580556 PASS
R1_START_EVIDENCE=origin/dev 1c57797789b040932fc6a02c3f45294d99bc0347·GitHub Actions run 30786041244 PASS; integration 23건·Gate dashboard·문서 정책 PASS; required30 0/30·gold120 0/120으로 생산자 handoff 대기
R1_PROGRESS_EVIDENCE=required30 30/30·gold120 120/120·평가 150건 reviewer/status 승인 완료; R2-W3-F2·R3-W3-F2·R4-W3·R5-W3-F1C MERGED_DEV; dev·junhee 3a7ceec·CI 30800298617/30800328577 PASS; integration 23건·Context/G1/G2/cache/concurrency 보안 회귀 29건 PASS
R1_LOCAL_MODEL_EVIDENCE=CUDA GPU 없음; 로컬 Hugging Face cache에 Qwen3-4B 없음; 실제 Base model·RunPod/LoRA·serving은 model download·비용 미승인으로 NOT_RUN
R1_FINAL_EVIDENCE=Base·LoRA 비교와 Base serving 실측을 완료했고, dev `baeda49`·CI `30870270154` PASS 기준의 실제 synthetic read-only trace `r1-w3-f7-product-trace-retry7`에서 2026-06·07 두 행과 ROUTER→CONTROLLER→CONTEXT→G1→MODEL→G2→QUERY→G3→ARTIFACT 전 단계 PASS를 확인했다.
ALLOWED_PATHS=AGENTS.md; .github/**; compose*.yml; .env.example; .dockerignore; config/access-policy.yaml; tests/integration/**; docs/Answervice_기획서.md; docs/markdown/02_WBS.md; docs/markdown/collaboration/**
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현
ACCEPTANCE_CRITERIA=필수 30건 expected 결과와 reviewer를 확인하고 일반 질문 subset에서 schema-only·DataHub metadata·승인 Context 세 조건 및 Base model을 동일 질문·데이터·권한으로 비교하며 repair 최대 1회, 비승인 SQL·Context 밖 참조·G3 실패 설명을 차단하고 I3 통합 trace를 판정
ACCEPTANCE_IDS=AC1_REQUIRED30_EXPECTED;AC2_GENERAL_LLM_BASELINE;AC3_SECURITY_BASELINE;AC4_I3_INTEGRATED_TRACE
TEST_COMMANDS=python -m unittest discover -s tests/integration -p "test_*.py"; python .github/scripts/gate_scope.py --dashboard --next-gate I4; python .agents/skills/manage-project-documents/scripts/check_document_policy.py docs/markdown/02_WBS.md docs/markdown/collaboration/Gate_실행_카드_원장.md docs/markdown/collaboration/I1_평가_원장.md; git diff --check
TEST_COMMAND_IDS=T1_INTEGRATION;T2_DASHBOARD;T3_DOCUMENT_POLICY;T4_DIFF_CHECK
STOP_CONDITIONS=필수 30건 expected 결과 미확정; 보안 High 결함; 역할별 필수 handoff 미도착; 통합 회귀 실패; R2~R5 소유 경로 변경 필요
HANDOFF=I3 판정·미실행 model 후보·보안 결함·다음 Wave 시작 조건을 전 역할에 전달
EXTERNAL_ACTION_PERMISSION=R1 허용 경로와 개인 일일보고의 commit·junhee push 승인; dependency 설치·model download·비용·배포·secret·외부 데이터 전송·dev merge 불가
```

### R2-W3

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W3
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-09~18
CURRENT_TASK_CARD_ID=R2-18
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=744592ab129ed44c0cfcf5cf860b8945b011a324
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R2-W3@744592a
RESULT_SHA=33e17dfc326c130edb9f0257070b0c575dcca52d
HANDOFF_SHA=7a509d5e72f1e0f79a1349c414005e6c1b999ffa
MERGED_DEV_SHA=8bfcd8ca62455a4c234fe565eee9b18776379cd8
CI_EVIDENCE=branch run 30787914002 PASS; dev run 30788112084 PASS
CONTRACT_VERSION=I1-v1.0.0
DATA_CONTRACT_VERSION=I3-DATA-v1.0.0
BASE_DEV_CI_EVIDENCE=GitHub Actions run 30785580556 PASS
ALLOWED_PATHS=infrastructure/database/**; src/data/**; tests/data/**
FORBIDDEN_PATHS=app/backend/**; src/ai/**; src/modelops/**; frontend·Report; root Compose·.env.example·CI; R1/R3/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=5 source catalog 단독 조회와 승인된 2·3-source JOIN을 type·cardinality·event-time·watermark 계약으로 재현하고 원천·Trino 결과 hash, 실패 case와 필수 30·Gold용 fixture manifest를 제공
ACCEPTANCE_IDS=AC1_FIVE_CATALOGS;AC2_APPROVED_JOINS;AC3_WATERMARK_HASH;AC4_EVAL_FIXTURE
TEST_COMMANDS=docker compose -f infrastructure/database/compose.yml config; powershell -ExecutionPolicy Bypass -File infrastructure/database/scripts/verify.ps1; python -m unittest discover -s tests/data -p "test_*.py"; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_COMPOSE;T2_DATABASE_VERIFY;T3_DATA_TESTS;T4_ROLE_GATE;T5_DIFF_CHECK
STOP_CONDITIONS=5번째 source 외부 권한 필요; JOIN 증폭·type 손실·watermark drift; 원천/Trino hash 불일치; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R3/R4/R5에 5-source fixture·watermark·실패 case를, R1에 Gold manifest와 ID별 증거를 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R2 개인 일일보고·handoff manifest의 commit·seung push 승인; dependency 설치·외부 image pull·비용·배포·secret·외부 데이터 전송·dev merge 불가
```

### R2-W3-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W3-F1
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-18 required30 결과 계약 강화·gold120 완성
CURRENT_TASK_CARD_ID=R2-18
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=e780b75798188331964e55c2437965b78b290211
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W3-F1@e780b75
CONTRACT_VERSION=I1-v1.0.0
DATA_CONTRACT_VERSION=I3-DATA-v1.1.0-DRAFT
EVALUATION_MANIFEST_VERSION=EVAL-DATA-I3-v1.1.0-DRAFT
BASE_DEV_CI_EVIDENCE=GitHub Actions run 30791740474 PASS
R1_REVIEW_EVIDENCE=required30 30건과 gold 후보 5건의 수량·범주·split은 유효하지만 성공 case의 expected_query_result가 실제 SQL·result hash가 아닌 참조 문자열이고, 모든 35건이 REVIEW·R1/R3 PENDING이며 R3 runner는 inventory만 소비함
GOLD_CATEGORY_PLAN=단일 source 25; 승인 2-source JOIN 20; 승인 3-source JOIN 20; 모호·근거 부족 20; 권한·금지 20; source 실패·timeout·partial 15 = 120
ALLOWED_PATHS=infrastructure/database/sql/queries/**; infrastructure/database/scripts/**; src/data/**; tests/data/**
FORBIDDEN_PATHS=app/backend/**; src/ai/**; src/modelops/**; evals/**; frontend·Report; root Compose·.env.example·CI; R1/R3/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=required30 30건과 gold120 120건을 중복 없이 제공하고 성공 case의 expected_query_result를 i3_contract의 catalog check 또는 승인 JOIN gold fixture ID·SQL·sha256으로 해석·검증하며 evidence 파일 존재, data/schema/seed/scenario/policy version, category 수량, paraphrase_group split 누수 0건을 자동 검사한다. R1·R3 승인 전 case status는 REVIEW를 유지하고 단순 문장 복제로 수량을 채우지 않는다.
ACCEPTANCE_IDS=AC1_REQUIRED30_RESULT_HASH;AC2_GOLD120_COMPLETE;AC3_CATEGORY_AND_SPLIT;AC4_EVIDENCE_AND_VERSION
TEST_COMMANDS=python -m json.tool src/data/evaluation_fixture_manifest.i3.v1.json; python -m unittest discover -s tests/data -p "test_*.py"; python -m unittest tests.ai.test_wave3 -v; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_JSON;T2_DATA_TESTS;T3_AI_CONSUMER;T4_ROLE_GATE;T5_DIFF_CHECK
STOP_CONDITIONS=실제 고객·외부 데이터 필요; 승인되지 않은 JOIN·새 원천·schema 변경 필요; expected result hash 불일치; category·split·evidence 검증 실패; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R3에 EVAL-DATA-I3-v1.1.0 manifest와 case→SQL/result hash 해석 계약을, R1에 required30·gold120 범주별 수량·검증·미실행 항목을 전달
IMPLEMENTATION_SHA=46bcb74faa3338f9917e586bd7a6fe38cbe45e5e
SOURCE_CI_EVIDENCE=GitHub Actions run 30793635759 PASS
DEV_MERGE_SHA=078651fb3b5c4df62c34ddd193d1dc718522ddfe
EXTERNAL_ACTION_PERMISSION=허용 경로와 R2 개인 일일보고·handoff manifest의 commit·seung push 승인; dependency 설치·외부 image pull·비용·배포·secret·외부 데이터 전송·dev merge 불가
```

### R3-W3-F1C

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F1C
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-10 R2 평가 manifest partial/full count 소비 호환
CURRENT_TASK_CARD_ID=R3-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=c8a943be94827778fad48a626b0810adce86972b
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F1C@c8a943b
CONTRACT_VERSION=I1-v1.0.0
INPUT_EVALUATION_MANIFEST_VERSION=EVAL-DATA-I3-v1.0.0→v1.1.0-DRAFT
BASE_DEV_CI_EVIDENCE=GitHub Actions run 30792024162 PASS
CHANGE_REQUEST_EVIDENCE=tests/ai/test_wave3.py가 gold120=5·REVIEW=35를 하드코딩해 R2-W3-F1 승인 결과 gold120=120·전체 150 case를 소비하면 필연적으로 실패함. R2는 tests/ai/** 금지이므로 R3 소유 경로에서 선행 호환 보완 필요
ALLOWED_PATHS=evals/**; tests/ai/**
FORBIDDEN_PATHS=source DDL·seed·src/data/**; app/backend/**·G1·G2·G3; frontend·Report; root Compose·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=R2 manifest의 declared required30·gold partial count와 실제 case 수를 비교하고 required30=30·gold target=120·gold partial 0~120 경계를 유지한다. 테스트는 현재 partial 5건과 full 120건을 모두 검증하며 특정 REVIEW 총수 35를 하드코딩하지 않는다. model runtime·Node 동작·평가 성공 판정은 변경하지 않는다.
ACCEPTANCE_IDS=AC1_DECLARED_COUNT;AC2_PARTIAL_AND_FULL_GOLD;AC3_REQUIRED30_AND_TARGET;AC4_NO_RUNTIME_CHANGE
TEST_COMMANDS=python -m compileall -q evals tests/ai; python -m unittest discover -s tests/ai -p "test_*.py"; python -m unittest tests.data.test_i3_contract -v; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_COMPILE;T2_AI_TESTS;T3_DATA_CONSUMER;T4_ROLE_GATE;T5_DIFF_CHECK
STOP_CONDITIONS=R2 manifest schema 변경 필요; required30=30·gold target=120 경계 완화 필요; runtime·Node 동작 변경 필요; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R2에 partial/full count를 모두 소비하는 검증 기준을, R1에 변경 전후 테스트와 runtime 무변경 증거를 전달
IMPLEMENTATION_SHA=5ad22eeb366c5bda56ece201574d94255bfe1c0a
SOURCE_CI_EVIDENCE=GitHub Actions run 30793002152 PASS
DEV_MERGE_SHA=1ac9c5de4a6dd620bea00d5b787c16b9b0d7053e
EXTERNAL_ACTION_PERMISSION=허용 경로와 R3 개인 일일보고·handoff manifest의 commit·daesung push 승인; dependency 설치·model download·RunPod·비용·배포·secret·외부 데이터 전송·dev merge 불가
```
### R3-W3

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-03~10·12~14
CURRENT_TASK_CARD_ID=R3-14
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=b06a0da59df2a2b3481aaae0ef7845207cedbd09
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R3-W3@b06a0da
RESULT_SHA=5b13828725cca58c0640484e9cc5b2185d9a2758
HANDOFF_SHA=0ca009658bc6d12b10012a64aedd9217a8317c74
MERGED_DEV_SHA=41f5788176f507f9b07c7bb3643234f9ffceaa23
CI_EVIDENCE=branch run 30789043209 PASS; dev run 30789184985 PASS
DEFERRED_GATE_EVIDENCE=실제 Base model·RunPod/vLLM·GPU·비용·cold/warm/restart와 Gold120 나머지 115건은 I3 통과 증거로 계산하지 않음
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.0
MODEL_FIXTURE_VERSION=MODEL-FIXTURE-v1.0.0
BASE_DEV_CI_EVIDENCE=GitHub Actions run 30787154375 PASS
R1_REISSUE_EVIDENCE=기존 BASE_SHA 744592a와 신규 실행 시점 origin/dev 1c57797 불일치로 자동 중단됨; R1 착수 통합 후 origin/dev b06a0da·CI 30787154375 PASS 기준으로 재발행; origin/daesung 1e07ca8의 개인 일일보고 commit은 보존하고 dev를 no-rebase merge
ALLOWED_PATHS=src/ai/**; src/modelops/**; evals/**; tests/ai/**
FORBIDDEN_PATHS=source DDL·seed·src/data/**; app/backend/**·G1·G2·G3; frontend·Report; root Compose·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=Node 1·2·2′·3이 승인 Context 밖 참조 없이 typed schema를 지키고 repair 최대 1회, 동일 질문·데이터·권한 조건의 Base 비교, production client timeout·fallback·circuit·trace와 평가 결과를 재현하며 Node가 권한·SQL 실행·Gate·정답을 재판정하지 않음
ACCEPTANCE_IDS=AC1_NODE_CHAIN;AC2_REPAIR_LIMIT;AC3_BASE_COMPARISON;AC4_SERVING_CLIENT_TRACE
TEST_COMMANDS=python -m compileall -q src/ai src/modelops evals tests/ai; python -m unittest discover -s tests/ai -p "test_*.py"; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_COMPILE;T2_AI_TESTS;T3_ROLE_GATE;T4_DIFF_CHECK
STOP_CONDITIONS=model download·RunPod·비용·secret 필요; 학습 누수; Context 밖 참조; schema·timeout·fallback 검증 실패; 허용 경로 밖 변경 필요
HANDOFF=R4에 production client·fallback·timeout 계약을, R1에 정확도·p50/p95·자원·비용·미실행 결과와 ID별 증거를 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R3 개인 일일보고·handoff manifest의 commit·daesung push 승인; dependency 설치·model download·RunPod·비용·배포·secret·외부 데이터 전송·dev merge 불가
```

### R4-W3

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W3
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-08~15·18
CURRENT_TASK_CARD_ID=R4-08
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=41f5788176f507f9b07c7bb3643234f9ffceaa23
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W3@41f5788
OPENAPI_VERSION=OPENAPI-v1.0.0
BASE_DEV_CI_EVIDENCE=GitHub Actions run 30789184985 PASS
R1_REISSUE_EVIDENCE=R2 5원천 계약과 R3 production model client·timeout·fallback·circuit·trace 계약이 dev 41f5788에 통합되고 CI PASS를 확인해 R4-W3를 재발행
R1_REVIEW_EVIDENCE=제품 3c2ee47·최종 70d9e56의 model call budget·권한별 Cache·동시 2건·HTTP 429·Audit trace, role gate와 branch CI 30789842373 PASS를 확인
MERGED_DEV_SHA=c89a1a03d462e04dcd86dd33766936033063313d
DEV_CI_EVIDENCE=GitHub Actions run 30790048113 PASS
ALLOWED_PATHS=app/backend/**; tests/backend/**
FORBIDDEN_PATHS=source DDL·seed·src/data/**; src/ai/**·src/modelops/**; frontend·Report; root Compose·.env.example·CI; R1/R2/R3/R5 소유 문서
ACCEPTANCE_CRITERIA=실제 model client·repair 최대 1회·Trino·G3·Artifact를 고정 상태 전이로 유지하고 SQL Plan Cache와 Result Cache를 분리하며 key에 context·policy·entitlement·as_of·watermark·mask를 포함한다. Template·Cache도 G1·G2·G3·권한을 우회하지 않고 최대 LLM 4회·동시 2건·초과 대기/429와 request→context→query/cache→artifact trace를 재현
ACCEPTANCE_IDS=AC1_MODEL_CLIENT;AC2_CACHE_ISOLATION;AC3_CONCURRENCY_LIMIT;AC4_AUTH_MASK_AUDIT
TEST_COMMANDS=python -m compileall -q app/backend tests/backend; python -m pytest -p no:cacheprovider tests/backend; python app/backend/scripts/export_openapi.py --check; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_COMPILE;T2_BACKEND_TESTS;T3_OPENAPI;T4_ROLE_GATE;T5_DIFF_CHECK
STOP_CONDITIONS=Gate 우회; PII·secret 노출; repair 2회; Cache 권한 공유; migration 다중 head; backend 회귀 실패; 허용 경로 밖 변경 필요
HANDOFF=R5에 실제 OpenAPI·status·trace fixture를, R1에 Cache·권한·Audit 보안 증거와 ID별 manifest를 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R4 개인 일일보고·handoff manifest의 commit·jaehong push 승인; dependency 설치·비용·배포·secret·외부 데이터 전송·dev merge 불가
```

### R5-W3

```text
STATUS=MERGED_DEV
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W3
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R5-04~10·14
CURRENT_TASK_CARD_ID=R5-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=8bfcd8ca62455a4c234fe565eee9b18776379cd8
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R5-W3@8bfcd8c
OPENAPI_VERSION=OPENAPI-v1.0.0
UI_VERSION=UI-v1.0.0
REPORT_VERSION=REPORT-v1.0.0
BASE_DEV_CI_EVIDENCE=GitHub Actions run 30788112084 PASS
R1_REISSUE_EVIDENCE=R2-W3 5원천 계약이 dev 8bfcd8c에 통합되고 CI PASS를 확인해 R5가 R4 완료를 기다리지 않고 기존 OpenAPI example·mock과 R2 fixture로 병렬 착수하도록 재발행
R1_REVIEW_EVIDENCE=제품 e6e527a·최종 1c33f1c의 전체 오류 UI·Artifact→Report·immutable Report proposal·5원천 Catalog, role gate와 branch CI 30790336427 PASS를 확인
MERGED_DEV_SHA=4106b6d247b3f8cae7528a9915fb06b9dbcbae7f
DEV_CI_EVIDENCE=GitHub Actions run 30790451402 PASS
FOLLOW_UP=R4-16 실제 FastAPI·Alembic 등록과 R5-16 browser 접근성은 Wave 4 범위로 유지
ALLOWED_PATHS=app/enterprise-react/**; src/report/**; tests/frontend/**; tests/report/**
FORBIDDEN_PATHS=app/react/**; app/backend/**·공통 FastAPI·Alembic chain; source DDL·seed·src/data/**; src/ai/**·src/modelops/**; root Compose·.env.example·CI; R1/R2/R3/R4 소유 문서
ACCEPTANCE_CRITERIA=전체 오류 상태를 API 값 그대로 표시하고 immutable Report definition/version/run/block domain, R4가 등록 가능한 독립 router·migration proposal과 contract test, 5-source Catalog·Connection mock을 활성 frontend 하나에서 제공
ACCEPTANCE_IDS=AC1_ERROR_STATES;AC2_REPORT_VERSION;AC3_ROUTER_MIGRATION_PROPOSAL;AC4_FIVE_SOURCE_CATALOG
TEST_COMMANDS=npm --prefix app/enterprise-react run build; node --test tests/frontend/contracts.test.mjs; python -m unittest discover -s tests/report -p "test_*.py"; python .github/scripts/gate_scope.py --branch minji --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_BUILD;T2_FRONTEND_CONTRACT;T3_REPORT_TESTS;T4_ROLE_GATE;T5_DIFF_CHECK
STOP_CONDITIONS=공통 FastAPI·Alembic 직접 수정 필요; 양쪽 frontend 수정; Report version 덮어쓰기; API 상태 재계산; build·contract 실패; 허용 경로 밖 변경 필요
HANDOFF=R4에 router·migration proposal과 contract test를, R1에 전체 오류 UI·Catalog 증거와 ID별 manifest를 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R5 개인 일일보고·handoff manifest의 commit·minji push 승인; dependency 설치·비용·배포·secret·외부 데이터 전송·dev merge 불가
```

### R5-W3-F1C

```text
STATUS=MERGED_DEV
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W3-F1C
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R5-14 Catalog 계약 버전 호환
CURRENT_TASK_CARD_ID=R5-14
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=3d6bed7f29aec0c9610c4bfa054d3d57ef9b522e
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R5-W3-F1C@3d6bed7
DATA_CONTRACT_VERSION=I3-DATA-v1.1.0-DRAFT
BASE_DEV_CI_EVIDENCE=GitHub Actions run 30794421419 FAIL — frontend I3 data contract 상수 불일치가 동일하게 재현됐으며 본 카드의 교정 대상
CHANGE_REQUEST_EVIDENCE=dev CI run 30793737827에서 tests/frontend/contracts.test.mjs:188이 frontend 상수 I3-DATA-v1.0.0과 실제 src/data/i3_contract.v1.json의 I3-DATA-v1.1.0-DRAFT 불일치로 실패함
ALLOWED_PATHS=app/enterprise-react/src/data/catalogFixtures.ts; tests/frontend/contracts.test.mjs
FORBIDDEN_PATHS=src/data/**; app/backend/**; src/ai/**; src/modelops/**; src/report/**; root Compose·.env.example·CI; R1/R2/R3/R4 소유 문서
ACCEPTANCE_CRITERIA=frontend의 I3 data contract 상수를 실제 계약 버전 I3-DATA-v1.1.0-DRAFT와 일치시키고 Catalog 내용·UI 동작·R2 계약 파일은 변경하지 않으며 frontend contract test와 build를 통과
ACCEPTANCE_IDS=AC1_CONTRACT_VERSION_SYNC;AC2_FRONTEND_CONTRACT;AC3_BUILD_REGRESSION
TEST_COMMANDS=node --test tests/frontend/contracts.test.mjs; npm --prefix app/enterprise-react run build; python .github/scripts/gate_scope.py --branch minji --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_FRONTEND_CONTRACT;T2_BUILD;T3_ROLE_GATE;T4_DIFF_CHECK
STOP_CONDITIONS=버전 상수 외 제품 동작 변경 필요; R2 계약 파일 수정 필요; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R1에 변경 파일·frontend contract·build·role gate 결과를 전달
IMPLEMENTATION_SHA=aeb8bfa892d7f136646f89ba354e043a12373049
SOURCE_CI_EVIDENCE=GitHub Actions run 30796547226 PASS — frontend production build·contract, Python, 문서, 역할 범위, quality gate 통과
DEV_MERGE_SHA=4825c0c4157a168ea6f5add214cb936235605063
EXTERNAL_ACTION_PERMISSION=허용 경로와 R5 개인 일일보고·handoff manifest의 commit·minji push 승인; dependency 설치·비용·배포·secret·외부 데이터 전송·dev merge 불가
```

### R2-W3-F2

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W3-F2
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-18 평가 승인 상태 동기화
CURRENT_TASK_CARD_ID=R2-18
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=98b84364a16828cd1543397a5ee6662735d879b3
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W3-F2@98b8436
DATA_CONTRACT_VERSION=I3-DATA-v1.1.0-DRAFT
EVALUATION_MANIFEST_VERSION=EVAL-DATA-I3-v1.1.0-DRAFT
R1_R3_REVIEW_EVIDENCE=required30 30건·gold120 120건 전수 질문 검토; 중복 0·split 누수 0·필수 필드 누락 0; data 21건·AI 32건·integration 23건 PASS
ALLOWED_PATHS=src/data/evaluation_fixture_manifest.i3.v1.json; tests/data/test_i3_contract.py
FORBIDDEN_PATHS=질문·정답 SQL·result hash·category·split·evidence 내용; infrastructure/database/**; app/backend/**; src/ai/**; evals/**; frontend·Report; root Compose·CI; R1/R3/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=150건의 질문·정답·근거·version·분할을 변경하지 않고 reviewers를 R1:REVIEWED|R2:REVIEWED|R3:REVIEWED, status를 APPROVED로 동기화하며 data·AI consumer 회귀와 역할 범위를 통과
ACCEPTANCE_IDS=AC1_REVIEWER_SYNC;AC2_APPROVED_STATUS;AC3_CONTENT_IMMUTABLE;AC4_CONSUMER_REGRESSION
TEST_COMMANDS=python -m json.tool src/data/evaluation_fixture_manifest.i3.v1.json; python -m unittest discover -s tests/data -p "test_*.py"; python -m unittest discover -s tests/ai -p "test_*.py"; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_JSON;T2_DATA_TESTS;T3_AI_TESTS;T4_ROLE_GATE;T5_DIFF_CHECK
STOP_CONDITIONS=질문·정답·근거·version·분할 변경 필요; 일부 case 승인 불가; 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R1에 reviewer/status 변경 수량, content 무변경 diff, data·AI·role gate 결과를 전달
IMPLEMENTATION_SHA=c9c7dc7920bf51ab4f4c4ec13050b130435dccc7
HANDOFF_SHA=b798ee508d685609be444583d1d52a2782a72f1f
SOURCE_CI_EVIDENCE=GitHub Actions run 30798132320 PASS — role scope·Python·Compose·문서·quality gate 통과
CONTENT_IMMUTABILITY_EVIDENCE=reviewers·status 제외 SHA-256 8ffe1cdbdbdc460b2b5440e56fec31741c295195989ec904b320d4074d8e9a00 변경 전후 일치
DEV_MERGE_SHA=81934046243b84890e0988f8f1faf701959676b1
DEV_CI_EVIDENCE=GitHub Actions run 30798345089 PASS — 전체 Python·frontend·Compose·문서·role scope·quality gate 통과
EXTERNAL_ACTION_PERMISSION=허용 경로와 R2 개인 일일보고·handoff manifest의 commit·seung push 승인; dependency 설치·외부 image pull·model download·비용·배포·secret·외부 데이터 전송·dev merge 불가
```

### R3-W3-F2

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F2
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-10 학습 데이터 재생성·검증 도구 반입
CURRENT_TASK_CARD_ID=R3-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=65254239ee803369c846031d5cf45ee81aad7760
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F2@6525423
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.0
TRAINING_PACKAGE_SOURCE_SHA256=694ddcf4fe2f5d912383f9d871f33e153fd44ed751c4cdc111e72a72311f7c5d
ALLOWED_PATHS=src/ai/training/**; tests/ai/test_training_dataset.py; tests/ai/test_training_scenarios.py; tests/ai/test_training_verification.py
FORBIDDEN_PATHS=__pycache__/**; *.pyc; 제공된 학습 JSONL 원본; app/backend/**; src/data/**; infrastructure/database/**; frontend·Report; root Compose·env·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=training.zip의 source·README·example·requirements 10개 파일을 src/ai/training에 반입하되 compiled cache를 제외하고, 동작을 고정하는 training 전용 AI test 3개와 Python 7개 AST parse·Qwen 1,350건 validate·검증 원본 재빌드 SHA-256 일치·기존 AI 회귀를 통과
ACCEPTANCE_IDS=AC1_PACKAGE_CONTENTS;AC2_NO_COMPILED_CACHE;AC3_DATASET_VALIDATE;AC4_REPRODUCIBLE_BUILD;AC5_AI_REGRESSION
TEST_COMMANDS=python AST parse src/ai/training/*.py; python -m src.ai.training.dataset validate <Qwen JSONL>; python -m src.ai.training.dataset build <TrinoPASS JSONL> <temp output> 후 SHA-256 비교; python -m src.ai.training.train_lora --help; python -m src.ai.training.evaluate_lora --help; python -m unittest discover -s tests/ai -p "test_*.py"; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_AST;T2_DATASET_VALIDATE;T3_REBUILD_HASH;T4_TRAIN_HELP;T5_EVAL_HELP;T6_AI_TESTS;T7_ROLE_GATE;T8_DIFF_CHECK
STOP_CONDITIONS=압축 경로 탈출·secret·compiled cache 발견; 제공 JSONL 반입 필요; 재빌드 hash 불일치; 허용 경로 밖 변경; dependency 설치·model download·RunPod·비용·배포·외부 데이터 전송 필요; 필수 검증 실패
HANDOFF=R1에 반입 파일 목록, archive hash, dataset validate·재빌드 hash·AI 회귀·role gate 결과와 RunPod 미실행을 전달
IMPLEMENTATION_SHA=b78437e9845b896c38202060ddab99f99c93c41f
REPORT_SHA=45cf61c67208bf24c50f3370b46d985fc5349588
HANDOFF_SHA=fdb598849eeedf67923609e27f7009e78c498677
SOURCE_CI_EVIDENCE=GitHub Actions run 30799546249 PASS — Python·문서·role scope·quality gate 통과
DEV_MERGE_SHA=9b1fe34ff6dbfe7bc423e5879d4855b00879cfa9
DEV_CI_EVIDENCE=GitHub Actions run 30799712073 PASS — 전체 Python·frontend·Compose·문서·role scope·quality gate 통과
EXTERNAL_ACTION_PERMISSION=허용 경로와 R3 개인 일일보고·handoff manifest의 commit·daesung push 승인; dependency 설치·model download·RunPod resource·비용·배포·secret 사용·외부 데이터 전송·dev merge 불가
```

### R3-W3-F3

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F3
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-10 Gold·Acceptance 실행 입력 완성
CURRENT_TASK_CARD_ID=R3-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=a7c7aae196e960f1487c074877dd9a3996e3bbec
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F3@a7c7aae
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.0
SCENARIO_LEDGER_SHA256=33d706e962970f07d227afd4c1b4a39115db7136bc709197aa34d4f88f6a93c6
GAP_EVIDENCE=2,000건 원장에는 gold 120건·acceptance 30건이 있으나 build_case_specs.py는 train·validation만 선택하고 Qwen compiled 1,350건에도 held-out split이 없어 evaluate_lora.py의 gold·acceptance 실행 입력이 없음
ALLOWED_PATHS=src/ai/training/build_case_specs.py; tests/ai/test_training_scenarios.py; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=제공 JSONL 원본; src/data/**; app/backend/**; infrastructure/database/**; frontend·Report; root Compose·env·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=기존 train 1,200건·validation 150건 생성 기본값을 보존하면서 명시적 held-out 옵션에서만 gold 120건·acceptance 30건을 선택하고 APPROVED로 표시한다. 150건의 case_id·scenario_group 중복과 train·validation 누수를 0건으로 확인하고 Python AST·AI 회귀를 통과한 뒤 제공 원장을 읽기 전용으로 사용해 임시 case spec을 생성한다. 로컬 G2·Trino 검증과 compiled 변환은 실제 150건 전수 PASS일 때만 성공으로 보고한다.
ACCEPTANCE_IDS=AC1_DEFAULT_SPLITS_PRESERVED;AC2_EXPLICIT_HELD_OUT_150;AC3_APPROVAL_BOUNDARY;AC4_NO_SPLIT_LEAKAGE;AC5_LOCAL_TRINO_PASS;AC6_COMPILED_VALIDATE
TEST_COMMANDS=python -m unittest tests.ai.test_training_scenarios -v; python -m unittest discover -s tests/ai -p "test_*.py"; python -m src.ai.training.build_case_specs <scenario-ledger> <temp-held-out-specs> --held-out; python -m src.ai.training.verify_case_specs <temp-held-out-specs> <temp-held-out-verified>; python -m src.ai.training.dataset build <temp-held-out-verified> <temp-held-out-compiled>; python -m src.ai.training.dataset validate <temp-held-out-compiled>; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_SCENARIO_TEST;T2_AI_REGRESSION;T3_HELD_OUT_BUILD;T4_LOCAL_TRINO;T5_COMPILED_BUILD;T6_COMPILED_VALIDATE;T7_ROLE_GATE;T8_DIFF_CHECK
STOP_CONDITIONS=held-out 자동 승인 없이 생성 필요; 150건 수량·split·중복 불일치; G2·Trino 실패; 제공 원본 수정 필요; 허용 경로 밖 변경; dependency 설치·model download·RunPod·비용·secret·외부 데이터 전송 필요; 필수 검증 실패
HANDOFF=R1에 기본 동작 보존, held-out 120/30 수량·승인 경계·누수 검사, 로컬 Trino 150건 전수 결과, compiled validate와 role gate 결과를 전달
IMPLEMENTATION_SHA=b781cfbc7a556498300784cb27ca10da6afaa5d5
HANDOFF_SHA=c480c7de04f8eceb108c9f662da5babdff822574
SOURCE_CI_EVIDENCE=GitHub Actions run 30802900472 PASS — role scope·Python·문서·quality gate 통과
DEV_MERGE_SHA=aede5a5caba70a6b6ee64e0f8c85edb7e1c16a4b
DEV_CI_EVIDENCE=GitHub Actions run 30803015630 PASS — 전체 Python·frontend·Compose·문서·role scope·quality gate 통과
EXTERNAL_ACTION_PERMISSION=제공된 2,000건 원장의 로컬 읽기와 임시 생성물, 이미 실행 중인 합성 DB·Trino의 setup 계정 검증, 허용 경로와 R3 개인 일일보고의 commit·daesung push 승인; dependency 설치·model download·RunPod resource·비용·배포·secret 사용·외부 데이터 전송·dev merge 불가
```

### R3-W3-F4

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F4
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-11 time-boxed Qwen3-4B LoRA 1회 비교와 채택 판단 증거
CURRENT_TASK_CARD_ID=R3-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=852e8c879b04ea3a41ad73e299d78a6173252e42
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F4@852e8c8
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.0
EVALUATION_MANIFEST_VERSION=EVAL-DATA-I3-v1.1.0-DRAFT
USER_APPROVAL_EVIDENCE=사용자가 RunPod A40 실행과 최대 비용 USD 15, 학습 외 남은 작업의 계속 진행, 완료 후 commit·push·dev 통합을 승인함
ALLOWED_PATHS=src/ai/training/evaluate_lora.py; tests/ai/test_eval_runner.py; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=.env; API key; 학습·평가 JSONL 원본; model binary·adapter·checkpoint·평가 생성물; app/backend/**; src/data/**; infrastructure/database/**; frontend·Report; root Compose·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=Qwen3-4B Base와 같은 checkpoint·held-out 입력·decoding 조건에서 BF16 LoRA 학습을 1회만 수행한다. Gold 120건·Acceptance 30건의 JSON 구조·SQL 정확 일치와 로컬 G2·실제 Trino 결과 일치를 확인하고, Gold의 p50·p95 응답시간과 최대 VRAM을 기록한다. adapter·manifest·로그·평가 결과를 저장소 밖에 hash와 함께 회수하고 task Pod를 삭제하며 총 RunPod 비용을 USD 15 이하로 제한한다. 정확도·안전·지연시간·메모리·재현성 조건을 모두 확인하기 전에는 제품 기본값을 LoRA로 전환하지 않는다.
ACCEPTANCE_IDS=AC1_SINGLE_LORA_RUN;AC2_SAME_CONDITION_BASELINE;AC3_HELD_OUT_150_EVALUATED;AC4_G2_TRINO_150;AC5_LATENCY_VRAM_EVIDENCE;AC6_ARTIFACT_HASH_ROLLBACK;AC7_POD_DELETED;AC8_COST_WITHIN_LIMIT;AC9_NO_DEFAULT_SWITCH
TEST_COMMANDS=python -m unittest tests.ai.test_eval_runner -v; python -m compileall -q src/ai/training/evaluate_lora.py; python .agents/skills/update-project-reports/scripts/validate_reports.py --date 20260804 docs/markdown/daily_reports/daesung/일일보고.md; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_EVAL_UNIT;T2_COMPILE;T3_REPORT;T4_ROLE_GATE;T5_DIFF_CHECK
STOP_CONDITIONS=누적 RunPod 비용 USD 15 초과 예상; secret 출력·commit 필요; 다른 Pod·volume 변경 필요; 학습·평가 데이터 누수; G2·Trino 안전 검증 실패; 결과 artifact 회수·hash 확인 실패; task Pod 삭제 실패; 허용 경로 밖 변경; 필수 검증 실패; p95 SLO 미확정 상태의 제품 기본값 전환 요구
HANDOFF=R1에 Base·LoRA 정확도, Trino 결과 일치율, p50·p95, 최대 VRAM, 학습 manifest·adapter hash, 실제 비용, Pod 삭제, rollback과 제품 기본값 보류 근거를 전달
R1_REVIEW_RESULT=코드·평가 증거의 dev 통합은 승인한다. serving 미실행과 p95 증가 위험은 후속 카드로 유지하며 LoRA 제품 기본값 전환은 승인하지 않고 Base를 유지한다.
IMPLEMENTATION_SHA=b5afd4551f2d433f0e8da85d7bc050967d0ce808
HANDOFF_SHA=bda5687c4aec07cdd924900a3440cdd64faa28af
SOURCE_CI_EVIDENCE=GitHub Actions run 30833685964 FAIL은 handoff의 REVIEW_REQUIRED 때문이었고 R1 분리 판정·terminal 동기화 뒤 corrective run 30834157984 PASS — role scope·Python·문서·quality gate 통과
DEV_MERGE_SHA=34facd695faf28f96036207823f03520e44069ae
DEV_CI_EVIDENCE=GitHub Actions run 30834138561 PASS — 전체 Python·frontend·Compose·문서·role scope·quality gate 통과
EXTERNAL_ACTION_PERMISSION=사용자 승인 한도 USD 15 안에서 task 전용 RunPod A40 Pod 생성·dependency 설치·Qwen3-4B 다운로드·합성 학습/평가 데이터 전송·BF16 LoRA 1회 학습·평가·결과 회수·정확한 task Pod 삭제와 허용 경로 commit·daesung push 승인; 다른 Pod·volume 변경, secret 출력·commit, 제품 기본값 전환, 외부 배포는 불가
```

### R3-W3-F5

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F5
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-12~14 Qwen3-4B Base vLLM endpoint 실측과 model client 운영 trace
CURRENT_TASK_CARD_ID=R3-12
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=8a0e9c4382db2ccf7dca85accb5cc2b34385d9dc
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F5@8a0e9c4
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.0
MODEL_ID=Qwen/Qwen3-4B
MODEL_REVISION=1cfa9a7208912126459214e8b04321603b3df60c
PRODUCT_DEFAULT=Base
LORA_PRODUCT_ADOPTION=NOT_APPROVED
USER_APPROVAL_EVIDENCE=사용자가 RunPod A40 실행과 모든 비용 합계 최대 USD 15, 학습 외 남은 작업의 계속 진행, 완료 후 commit·push·dev 통합을 승인함
PREVIOUS_RUNPOD_COST_USD=0.9522728326846845
CUMULATIVE_RUNPOD_COST_LIMIT_USD=15
ALLOWED_PATHS=src/ai/training/benchmark_serving.py; src/modelops/serving_manifest.v0.1.json; evals/base_comparison.v0.1.json; tests/ai/test_serving_benchmark.py; tests/ai/test_wave3.py; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=.env; API key; model binary·adapter·checkpoint·평가 생성물; app/backend/**; src/data/**; infrastructure/database/**; frontend·Report; root Compose·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=고정 image·runtime·Qwen3-4B revision으로 OpenAI-compatible `/v1/models`와 `/v1/chat/completions` endpoint를 기동하고 readiness를 확인한다. 첫 요청 cold latency, 반복 warm p50·p95, 최대 VRAM, 최대 동시 2건, 동일 revision 재시작 후 readiness를 기록한다. 기존 `ProductionModelClient`로 정상·timeout·fallback·circuit trace를 재현하고 secret을 제거한 manifest와 artifact hash를 남긴다. 실행 전 누적 비용을 확인하고 총 RunPod 비용을 USD 15 이하로 제한하며 결과 회수 뒤 정확한 task Pod만 삭제한다. 이 카드는 R3 endpoint 증거만 승인하며 FastAPI 제품 연결·I3 전체 통과·LoRA 제품 채택을 주장하지 않는다.
ACCEPTANCE_IDS=AC1_FIXED_RUNTIME_REVISION;AC2_OPENAI_ENDPOINT_READY;AC3_COLD_WARM_LATENCY;AC4_PEAK_VRAM_CONCURRENCY2;AC5_RESTART_READINESS;AC6_CLIENT_FAILURE_TRACE;AC7_REDACTED_MANIFEST_HASH;AC8_POD_DELETED;AC9_CUMULATIVE_COST_LIMIT;AC10_BASE_DEFAULT_PRESERVED
TEST_COMMANDS=python -m unittest tests.ai.test_serving_benchmark -v; python -m unittest tests.ai.test_wave3 -v; python -m compileall -q src/ai/training/benchmark_serving.py; python .agents/skills/update-project-reports/scripts/validate_reports.py --date 20260804 docs/markdown/daily_reports/daesung/일일보고.md; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_SERVING_UNIT;T2_MODEL_CLIENT;T3_COMPILE;T4_REPORT;T5_ROLE_GATE;T6_DIFF_CHECK
STOP_CONDITIONS=누적 비용 USD 15 초과 예상; secret 출력·commit 필요; 다른 Pod·volume 변경 필요; 고정 model revision 또는 endpoint readiness 불가; 결과 artifact 회수·hash 확인 실패; task Pod 삭제 실패; 허용 경로 밖 변경; 필수 검증 실패; FastAPI 제품 연결 또는 LoRA 제품 기본값 전환 필요
HANDOFF=R1에 image·runtime·model revision, endpoint schema·readiness, cold·warm p50/p95·peak VRAM·동시 2건, restart, ProductionModelClient 정상·timeout·fallback·circuit trace, artifact hash·실측 누적 비용·Pod 삭제와 R4 제품 연결에 필요한 최소 endpoint 계약을 전달
R1_REVIEW_RESULT=Python·문서 CI와 로컬 AI 45건, 고정 revision endpoint·restart·동시 2건·peak VRAM·artifact hash·Pod 404·활성 0개를 확인해 통합을 승인한다. role-scope CI 실패는 청구 확정 지연·R4 change request·잔여 위험을 수동 검토하라는 REVIEW_REQUIRED에 한정되며 구현 실패가 아니다. 비용은 실행시간 추정 신규 USD 0.062802·예상 누적 USD 1.015075로 한도 이내다. FastAPI 제품 연결과 I3 전체 통과는 후속으로 유지한다.
IMPLEMENTATION_SHA=8125885d4614f440f4f5cdad3c39ab4f2ca026d5
HANDOFF_SHA=5e2fa990ad72e0605e0cf141b0b75e86e41ecd6d
SOURCE_CI_EVIDENCE=GitHub Actions run 30837382461 FAIL은 role-scope REVIEW_REQUIRED 때문이며 Python 전체·문서 품질은 PASS — R1이 Not Run·change request·잔여 위험·외부 승인 항목을 분리 검토해 수용
DEV_MERGE_SHA=5e2fa990ad72e0605e0cf141b0b75e86e41ecd6d
DEV_CI_EVIDENCE=최종 R1 terminal 동기화 뒤 dev push CI 재검증 예정
EXTERNAL_ACTION_PERMISSION=기존 누적 비용을 포함한 사용자 승인 한도 USD 15 안에서 task 전용 RunPod A40 Pod 생성·고정 serving image pull·Qwen3-4B 다운로드·합성 평가 요청 전송·Base vLLM 실측·결과 회수·정확한 task Pod 삭제와 허용 경로 commit·daesung push 승인; 다른 Pod·volume 변경, secret 출력·commit, LoRA 재학습·제품 기본값 전환, FastAPI 수정, 외부 공개 배포는 불가
```

### R4-W3-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W3-F1
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-08 실제 Base endpoint transport와 Control Plane 안전 실패 연결
CURRENT_TASK_CARD_ID=R4-08
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=382b7f527191df4690f8d9e6e4c4cac73c120a0c
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W3-F1@382b7f5
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
SERVING_MANIFEST_VERSION=SERVING-v0.2
OPENAPI_VERSION=0.1.0
ALLOWED_PATHS=app/backend/app/adapters/contract_model.py; app/backend/app/api/router.py; app/backend/README.md; tests/backend/test_production_model.py; tests/backend/test_analysis_pipeline.py; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/ai/**; src/modelops/**; evals/**; .env; API key; root Compose·CI; infrastructure/database/**; frontend·Report; R1/R2/R3/R5 소유 문서
ACCEPTANCE_CRITERIA=`MODEL_MODE=openai`에서만 `MODEL_ENDPOINT`와 선택적 `MODEL_API_TOKEN`을 읽어 SERVING-v0.2의 `/v1/chat/completions`를 호출하고 기존 fake·contract mode 동작을 보존한다. R3 prompt·payload를 JSON으로 전달하며 temperature 0, `enable_thinking=false`, 최대 출력 제한을 고정한다. 응답 JSON은 기존 `ProductionModelClient`와 R3 schema를 통과한 뒤에만 R4 plan으로 변환한다. timeout·HTTP 오류·잘못된 JSON·schema 불일치·circuit open·fallback은 fake 성공으로 숨기지 않고 기존 Control Plane `MODEL_RESPONSE_INVALID` 안전 실패로 반환한다. Authorization header와 오류 본문은 log·trace·응답에 남기지 않는다. R4 unit·analysis regression·OpenAPI 회귀를 통과하되 실제 RunPod 재기동과 I3 전체 통과는 주장하지 않는다.
ACCEPTANCE_IDS=AC1_EXPLICIT_OPENAI_MODE;AC2_SERVING_V02_REQUEST;AC3_SCHEMA_BEFORE_PLAN;AC4_FAILURE_IS_SAFE;AC5_SECRET_REDACTED;AC6_FAKE_CONTRACT_COMPAT;AC7_NO_GATE_DELEGATION;AC8_BACKEND_REGRESSION
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend/test_production_model.py tests/backend/test_analysis_pipeline.py tests/backend/test_openapi_contract.py; python -m compileall -q app/backend/app/adapters/contract_model.py app/backend/app/api/router.py; python .agents/skills/update-project-reports/scripts/validate_reports.py --date 20260804 docs/markdown/daily_reports/jaehong/일일보고.md; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check origin/dev..HEAD
TEST_COMMAND_IDS=T1_PRODUCTION_MODEL;T2_ANALYSIS_REGRESSION;T3_OPENAPI;T4_COMPILE;T5_REPORT;T6_ROLE_GATE;T7_DIFF_CHECK
STOP_CONDITIONS=R3 schema·prompt·ProductionModelClient 수정 필요; endpoint가 권한·G1/G2/G3·SQL 실행을 판정해야 함; fake fallback을 제품 성공으로 반환해야 함; secret 출력·commit 필요; 허용 경로 밖 변경; dependency 설치·RunPod·비용·외부 데이터 전송 필요; 필수 검증 실패
HANDOFF=R1에 MODEL_MODE별 선택, 실제 HTTP request·response schema, retry·timeout·fallback·circuit의 안전 실패, secret 비기록, backend 회귀와 R1 live endpoint trace에 필요한 실행 env를 전달
EXTERNAL_ACTION_PERMISSION=SERVING-v0.2와 R3 runtime의 로컬 읽기, 허용 경로와 R4 개인 일일보고의 commit·jaehong push 승인; dependency 설치·RunPod resource·비용·secret 사용·외부 호출·dev merge 불가
RESULT_SHA=ba78870b73a79fcf868d428a4811d5f152043e95
SOURCE_SYNC_SHA=5068ac160add72ec5658bf74fcc1fddbac175d78
SOURCE_CI_EVIDENCE=GitHub Actions run 30838961585 PASS; Python 150 passed·7 environment skipped, OpenAPI 4 passed, role scope·document quality·quality gate PASS
DEV_MERGE_SHA=39b8c886da5f368e7a68a7940f6f690385160cc8
R1_REVIEW=실제 endpoint request의 temperature 0·max_tokens 1500·enable_thinking false, R3 schema 선검증, timeout·invalid JSON·fallback·circuit open의 query·Artifact 없는 안전 실패와 secret 비기록을 code·test·CI로 수용. Handoff manifest NOT_RUN은 카드가 handoffs 경로를 허용하지 않은 발행 누락으로 R4 일일보고·commit·CI 직접 검수로 대체
CONTRACT_NOTE=카드의 MODEL_RESPONSE_INVALID 표기는 동결 OPENAPI-v1.0.0에 존재하지 않아 기존 model_error의 INTERNAL_ERROR를 유지했다. 신규 오류 code를 추정 추가하지 않고 같은 안전 실패 의미를 보존
```

### R1-W3-F1

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W3-F1
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R1-10 실제 Base endpoint와 FastAPI 제품 전체 trace 판정
CURRENT_TASK_CARD_ID=R1-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=7a52059f3bee2ad653daaa3099cc139c161ae567
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W3-F1@7a52059
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
SERVING_MANIFEST_VERSION=SERVING-v0.2
OPENAPI_VERSION=OPENAPI-v1.0.0
ALLOWED_PATHS=tests/integration/**; .github/**; compose*.yml; docs/markdown/02_WBS.md; docs/markdown/collaboration/**; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현; .env; API key; actual customer data; model binary·RunPod artifact commit; frontend·Report 변경; 다른 Docker project·container·volume
ACCEPTANCE_CRITERIA=dev CI `30839298442` PASS 기준으로 task 전용 RunPod A40에서 고정 Qwen/Qwen3-4B revision의 vLLM endpoint를 localhost 전용 tunnel로 기동하고, task 전용 FastAPI runtime을 `DATA_PLATFORM_MODE=fake`, `MODEL_MODE=openai`로 연결해 합성 일반 질문 `/analysis`를 실제 HTTP로 호출한다. 성공이면 MODEL→G2→QUERY→G3→ARTIFACT trace와 model version·evidence를 확인하고, 실패면 MODEL 단계 INTERNAL_ERROR·query/Artifact 없음·secret 비기록을 확인해 원인을 판정한다. 정상·timeout·invalid JSON·fallback·circuit 회귀와 endpoint 요청 옵션을 함께 검수한다. 결과·hash·비용·cleanup을 기록하고 정확한 task Pod와 task backend container만 삭제한다. 실제 성공 trace가 없으면 I3 VERIFIED_GATE로 전환하지 않는다.
ACCEPTANCE_IDS=AC1_FIXED_BASE_ENDPOINT;AC2_PRODUCT_HTTP_TRACE;AC3_SAFE_FAILURE;AC4_SECRET_REDACTED;AC5_COST_LIMIT;AC6_EXACT_CLEANUP;AC7_I3_EVIDENCE_DECISION
TEST_COMMANDS=task backend health·readiness; synthetic POST /analysis with fixed auth/context headers; python -m pytest -p no:cacheprovider tests/backend/test_production_model.py tests/backend/test_analysis_pipeline.py tests/backend/test_openapi_contract.py; python -m unittest discover -s tests/integration -p "test_*.py"; docker inspect task container; RunPod GET exact Pod 404 and active Pods 0; document·WBS·report validation; git diff --check
TEST_COMMAND_IDS=T1_BACKEND_READY;T2_LIVE_ANALYSIS;T3_BACKEND_REGRESSION;T4_INTEGRATION;T5_CONTAINER_SCOPE;T6_POD_CLEANUP;T7_DOCUMENTS;T8_DIFF_CHECK
STOP_CONDITIONS=누적 비용 USD 15 도달 예상; task 외 Pod·container·volume 변경 필요; public model endpoint 노출 필요; secret 출력·commit 필요; 실제 고객 데이터 전송 필요; R2~R5 소유 code 변경 필요; 필수 안전 실패 위반
HANDOFF=실제 product HTTP trace·model 응답 판정·latency·artifact/evidence·회귀·artifact hash·비용·task resource cleanup과 I3 승인 또는 후속 병목을 전 역할에 전달
EXTERNAL_ACTION_PERMISSION=사용자가 승인한 누적 USD 15 한도 안에서 task 전용 RunPod A40 Pod 생성·고정 serving image와 Qwen3-4B 다운로드·합성 요청 전송·localhost SSH tunnel·task backend container build/run·결과 회수·정확한 task Pod와 task container 삭제, R1 허용 경로 commit·junhee/dev push 승인. 다른 Pod·Docker project·container·volume 변경, public endpoint·secret 출력/commit, 실제 고객 데이터, LoRA 재학습·제품 기본값 전환은 불가
COST_BASELINE_USD=이전 실측·추정 누적 1.015075; 최종 provider billing 지연 시 예상값과 확정 여부를 분리 기록
RESULT_EVIDENCE=제품 기본 timeout 15초는 15,593.1ms에 MODEL INTERNAL_ERROR·query/Artifact 없음으로 안전 실패. 60초에서도 16,054.139ms로 동일해 timeout이 아님을 확인. Base 원응답 2건은 762/767자·SHA-256 0618feb1da5b.../f12f0d00ec2b...이며 JSON line1 col1 실패, JSON object mode는 `query` key만 생성해 node2 필수 field가 누락됐다. 실제 R3 node2 schema의 guided_json은 1,680자·SHA-256 0a938bc0eaf5...·schema PASS였으나 fake Context가 pms_guests.guest_id만 승인하고 metric은 pms_stays.room_revenue를 요구해 MODEL PASS 뒤 G2 RESOURCE_POLICY_MISSING, 1회 repair 뒤 SQL_POLICY_BLOCKED로 종료
COST_AND_CLEANUP=task Pod fohruepmj5cjnt A40 USD0.44/h, 로컬 추적 875.833초로 신규 예상 USD0.107045·예상 누적 USD1.122120. provider billing row는 삭제 직후 pending. exact Pod GET 404·active Pods 0, task backend container·image·SSH tunnel·known_hosts task endpoint 제거 완료. 기존 Docker project·container·volume 변경 없음
BLOCKER=R4 transport가 R3 response schema를 structured output으로 전달해야 하며 실제 제품 성공 trace는 fake data Context가 아니라 승인된 I2 synthetic Context와 read-only Trino로 재검증해야 한다. R4 code와 R2 data source를 R1이 대신 수정하지 않고 후속 카드로 분리
```

### R4-W3-F2

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W3-F2
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-08 R3 response schema 기반 structured output transport 보완
CURRENT_TASK_CARD_ID=R4-08
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=95c0eff4cbac8fa550d0e98112b4a271141c2069
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W3-F2@95c0eff
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
SERVING_MANIFEST_VERSION=SERVING-v0.2
OPENAPI_VERSION=OPENAPI-v1.0.0
ALLOWED_PATHS=app/backend/app/adapters/contract_model.py; app/backend/README.md; tests/backend/test_production_model.py; tests/backend/test_analysis_pipeline.py; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/ai/**; src/modelops/**; evals/**; app/backend/app/adapters/fake_data_platform.py; .env; API key; root Compose·CI; infrastructure/database/**; frontend·Report; R1/R2/R3/R5 소유 문서
ACCEPTANCE_CRITERIA=각 node의 실제 R3 `<node>_response` JSON schema를 contract bundle에서 읽어 `$defs`와 함께 vLLM `guided_json`에 전달한다. node별 field를 R4에 복제·하드코딩하지 않고 기존 temperature 0·max_tokens 1500·enable_thinking false·prompt·payload·token 처리와 `ProductionModelClient` 선검증·fallback 차단을 보존한다. node2·node2_repair·node3 모두 올바른 response schema를 선택하고 schema 파일 누락·unknown node·HTTP·invalid JSON·schema 오류는 안전 실패한다. fake·contract-fake mode와 OpenAPI는 변경하지 않는다. 실제 RunPod·I2 Trino 재실행이나 I3 통과는 주장하지 않는다.
ACCEPTANCE_IDS=AC1_SCHEMA_FROM_CONTRACT;AC2_ALL_NODE_GUIDANCE;AC3_NO_SCHEMA_DUPLICATION;AC4_EXISTING_OPTIONS;AC5_SAFE_FAILURE;AC6_MODE_COMPAT;AC7_BACKEND_REGRESSION
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend/test_production_model.py tests/backend/test_analysis_pipeline.py tests/backend/test_openapi_contract.py; python -m compileall -q app/backend/app/adapters/contract_model.py; python .agents/skills/update-project-reports/scripts/validate_reports.py --date 20260804 docs/markdown/daily_reports/jaehong/일일보고.md; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check origin/dev..HEAD
TEST_COMMAND_IDS=T1_PRODUCTION_MODEL;T2_ANALYSIS_REGRESSION;T3_OPENAPI;T4_COMPILE;T5_REPORT;T6_ROLE_GATE;T7_DIFF_CHECK
STOP_CONDITIONS=R3 schema file 수정·별도 dependency 필요; response field를 R4에 하드코딩해야 함; guided output이 R3 validate_payload를 우회함; secret·오류 본문 출력 필요; 허용 경로 밖 변경; RunPod·비용·외부 호출 필요; 필수 검증 실패
HANDOFF=R1에 node별 guided schema source·request option·R3 validation 순서·fallback 차단·backend/OpenAPI 회귀와 다음 실제 I2 synthetic product trace 조건을 전달
EXTERNAL_ACTION_PERMISSION=R3 contract와 vLLM 0.10.2 공식 기능의 로컬 읽기, 허용 경로와 R4 개인 일일보고의 commit·jaehong push 승인; dependency 설치·RunPod·비용·secret 사용·외부 호출·dev merge 불가
RESULT_SHA=b873ef3ce18807eb98fb859649c63439ed4f6e82
SOURCE_CI_EVIDENCE=GitHub Actions run 30841201329 PASS; 전체 Python·OpenAPI·document quality·role scope·quality gate PASS
DEV_MERGE_SHA=6ebee36a4de12bb147e4843ac370080a100dc486
R1_REVIEW=node별 실제 R3 response schema를 contract bundle에서 읽어 cached guided_json으로 전달하고, schema field를 R4에 복제하지 않은 상태에서 기존 고정 생성 옵션·ProductionModelClient 검증·fallback 차단·fake mode·OpenAPI 보존을 code·22건 local test·전체 CI로 수용
```

### R1-W3-F2

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W3-F2
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R1-10 guided Base endpoint와 실제 I2 synthetic Context·Trino 제품 trace
CURRENT_TASK_CARD_ID=R1-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=6ebee36a4de12bb147e4843ac370080a100dc486
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W3-F2@6ebee36
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
SERVING_MANIFEST_VERSION=SERVING-v0.2
OPENAPI_VERSION=OPENAPI-v1.0.0
DATA_CONTRACT_VERSION=DATA-v1.0.0
ALLOWED_PATHS=tests/integration/**; .github/**; compose*.yml; docs/markdown/02_WBS.md; docs/markdown/collaboration/**; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현; .env; API key; actual customer data; model binary·RunPod artifact commit; frontend·Report 변경; 다른 Docker project·container·volume의 생성·수정·삭제·재시작
ACCEPTANCE_CRITERIA=dev `6ebee36`의 R3 schema guided transport를 task 전용 RunPod A40 고정 Qwen3-4B endpoint와 task backend container에 연결한다. backend는 `DATA_PLATFORM_MODE=i2`, `TRINO_URL=http://host.docker.internal:18080`, read-only `TRINO_USER=answervice`로 이미 검증된 hotel-synthetic-db Trino를 조회만 하며 해당 project·container·volume·설정을 변경하지 않는다. 합성 일반 질문 `/analysis`가 MODEL→G2→QUERY→G3→ARTIFACT까지 성공하면 model·source·query·artifact evidence와 latency를 확인하고, 실패하면 마지막 stage·오류·query/Artifact 부재와 guided schema·G2·Trino 원인을 분리한다. 정상·timeout·invalid JSON·fallback·circuit·OpenAPI·integration 회귀를 함께 검수한다. 결과·hash·비용·cleanup을 기록하고 task Pod·backend container·image·tunnel만 제거한다. 성공 trace와 필수 회귀·보안 확인 전 I3를 승인하지 않는다.
ACCEPTANCE_IDS=AC1_GUIDED_BASE_ENDPOINT;AC2_I2_SYNTHETIC_CONTEXT;AC3_READ_ONLY_TRINO;AC4_PRODUCT_SUCCESS_OR_EXACT_BLOCKER;AC5_SECRET_REDACTED;AC6_REGRESSION;AC7_COST_LIMIT;AC8_EXACT_CLEANUP;AC9_I3_DECISION
TEST_COMMANDS=task backend health; I2 data source health; synthetic POST /analysis fixed headers; response trace·artifact·evidence inspection; python -m pytest -p no:cacheprovider tests/backend/test_production_model.py tests/backend/test_analysis_pipeline.py tests/backend/test_openapi_contract.py; python -m unittest discover -s tests/integration -p "test_*.py"; exact task container/image/tunnel cleanup; RunPod exact Pod GET 404 and active Pods 0; verify existing Docker container IDs·status unchanged; document·WBS·report validation; git diff --check
TEST_COMMAND_IDS=T1_BACKEND_HEALTH;T2_I2_HEALTH;T3_LIVE_ANALYSIS;T4_EVIDENCE;T5_BACKEND_REGRESSION;T6_INTEGRATION;T7_TASK_CLEANUP;T8_POD_CLEANUP;T9_DOCKER_SCOPE;T10_DOCUMENTS
STOP_CONDITIONS=누적 비용 USD 15 도달 예상; hotel-synthetic-db 또는 다른 project의 write·restart·configuration change 필요; public model endpoint 필요; secret 출력·commit 필요; 실제 고객 데이터 전송 필요; R2~R5 code 변경 필요; 필수 안전 경계 위반
HANDOFF=guided product HTTP trace·model/G2/query/G3/artifact evidence·latency·read-only Trino·회귀·비용·task cleanup과 I3 승인 또는 정확한 후속 병목을 전 역할에 전달
EXTERNAL_ACTION_PERMISSION=사용자가 승인한 누적 USD 15 한도 안에서 task 전용 RunPod A40 Pod 생성·고정 serving image와 Qwen3-4B 다운로드·합성 요청 전송·localhost SSH tunnel·task backend container build/run·결과 회수·정확한 task Pod·container·image·tunnel 삭제와 기존 hotel-synthetic-db Trino의 read-only synthetic 조회, R1 허용 경로 commit·junhee/dev push 승인. 다른 Pod·Docker project·container·volume 변경, public endpoint·secret 출력/commit, 실제 고객 데이터, LoRA 재학습·제품 기본값 전환은 불가
COST_BASELINE_USD=이전 실측·추정 누적 1.122120; 최종 provider billing 지연 시 예상값과 확정 여부를 분리 기록
LIVE_TRACE_EVIDENCE=task Secure A40 `wzr7b1kcjpttug`·고정 Qwen3-4B revision·vLLM 0.10.2와 task backend `63b5ad6`을 localhost tunnel로 연결했다. backend health=healthy, readiness의 Trino=ready이며 앱 DB는 의도적으로 미설정했다. 실제 I2 Context의 synthetic `/analysis`는 HTTP 200·30,696.5ms·BLOCKED로 MODEL guided schema까지 PASS했지만 G2 `RESOURCE_POLICY_MISSING`, repair 1회 뒤 `SQL_POLICY_BLOCKED`로 종료됐고 QUERY·G3·ARTIFACT는 실행되지 않았다.
ROOT_CAUSE=node2 SQL은 허용된 `pms.public.pms_stays`·`crm.dbo.crm_member_grade_history`만 정확히 참조했지만 필수 `LIMIT`가 없었다. node2와 repair SQL은 모두 708자·SHA-256 `4d579699523988ecf363def46678587c3f090aea71dfa55f98493e7967fa4619`로 동일해 `RESOURCE_POLICY_MISSING` repair가 실제로 수정되지 않았다. R3 `PROMPT-v1.0.0` 문구가 Control Plane의 `LIMIT <= 1000` resource policy와 오류별 repair 행동을 명시하지 않은 prompt 계약 병목이다.
REGRESSION_EVIDENCE=production model·analysis pipeline 22건 PASS, integration 23건 PASS. OpenAPI local 재실행은 host Python에 FastAPI가 없어 collection BLOCKED였고 동일 R4 source CI run `30841201329`의 OpenAPI 4건 PASS를 기존 근거로 유지한다.
RESOURCE_CLEANUP=task backend container·image·localhost tunnel·known_hosts 항목 제거, Pod exact GET 404·active Pods 0 확인. hotel-synthetic-db Trino ID `bafdc16362af...`·running·restart count 0 유지, 다른 Docker resource는 변경하지 않았다.
COST_RESULT=Pod 실행 상한 544.915초·USD 0.066601 추정, 예상 누적 USD 1.188721로 승인 한도 USD 15 이내. provider billing 확정 지연 가능성이 있어 상한 추정값으로 기록한다.
BLOCKER=R3 node2·node2_repair prompt가 G2 resource policy의 `LIMIT <= 1000`과 `RESOURCE_POLICY_MISSING`의 결정론적 수정 행동을 명시하고 Base endpoint에서 서로 다른 repaired SQL·G2 PASS를 증명하기 전 실제 QUERY·G3·ARTIFACT trace와 I3 승인이 불가하다.
```

### R3-W3-F6

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F6
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-15 node2 resource limit·단일 repair prompt 계약 보완
CURRENT_TASK_CARD_ID=R3-15
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=63b5ad6c4366dafc86738f1ae4592590ee373f7c
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F6@63b5ad6
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.1
MODEL_ID=Qwen/Qwen3-4B
MODEL_REVISION=1cfa9a7208912126459214e8b04321603b3df60c
ALLOWED_PATHS=src/ai/prompt_registry.py; tests/ai/test_prompt_registry.py; tests/ai/test_node2.py; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; infrastructure/database/**; .env; API key; model binary·adapter·checkpoint·평가 생성물; frontend·Report; root Compose·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=node2 prompt가 승인 Context의 단일 read-only Trino SELECT와 `LIMIT 1..1000`을 명시하고, node2_repair prompt가 정규화 오류 코드에 해당하는 항목만 한 번 수정하되 `RESOURCE_POLICY_MISSING`이면 기존 의미·허용 reference·parameter를 유지하며 `LIMIT 1000`을 추가하도록 명시한다. 두 prompt의 version을 `PROMPT-v1.0.1`로 올리고 hash metadata가 실제 문구를 반영한다. R3 schema·fake generation·다른 node prompt·model default는 변경하지 않는다. unit test는 resource limit·오류별 단일 repair 문구와 기존 node2 계약 회귀를 고정한다. 실제 Base endpoint·제품 trace는 R1 후속 카드에서 검증한다.
ACCEPTANCE_IDS=AC1_NODE2_LIMIT_POLICY;AC2_RESOURCE_REPAIR_ACTION;AC3_PROMPT_VERSION_HASH;AC4_SINGLE_REPAIR;AC5_SCHEMA_UNCHANGED;AC6_REGRESSION
TEST_COMMANDS=python -m unittest tests.ai.test_prompt_registry tests.ai.test_node2 tests.ai.test_contracts tests.ai.test_fake_model -v; python -m compileall -q src/ai/prompt_registry.py; python .agents/skills/update-project-reports/scripts/validate_reports.py --date 20260804 docs/markdown/daily_reports/daesung/일일보고.md; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_PROMPT_UNIT;T2_COMPILE;T3_REPORT;T4_ROLE_GATE;T5_DIFF_CHECK
STOP_CONDITIONS=R3 schema·backend G2 code·training dataset 수정 필요; prompt만으로 limit·repair 행동을 명시할 수 없음; model default·LoRA·RunPod 변경 필요; secret 출력·commit 필요; 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R1에 node2·repair prompt version/hash·resource limit 문구·오류별 단일 repair 계약·unit regression과 후속 실제 Base I2 product trace 조건을 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R3 개인 일일보고의 commit·daesung push 승인; dependency 설치·RunPod·비용·secret 사용·외부 model 호출·dev merge 불가
RESULT_SHA=f717058abbf3d0830ff94a3a4e1772f780d58a43
SOURCE_CI_EVIDENCE=GitHub Actions run 30842808365 PASS; Python 전체·document quality·role scope·quality gate PASS
DEV_MERGE_SHA=a57b2731fc43226ccd899af0d942acc2ee22968b
R1_REVIEW=node2·node2_repair만 `PROMPT-v1.0.1`로 올려 LIMIT 1~1000과 RESOURCE_POLICY_MISSING의 단일 추가·교체 행동을 명시하고, schema·backend·dataset·다른 node를 보존한 최소 변경과 15건 local·전체 CI를 수용
```

### R1-W3-F3

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W3-F3
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R1-10 prompt v1.0.1 Base·I2 synthetic 제품 전체 trace 재검증
CURRENT_TASK_CARD_ID=R1-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=a57b2731fc43226ccd899af0d942acc2ee22968b
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W3-F3@a57b273
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.1
SERVING_MANIFEST_VERSION=SERVING-v0.2
OPENAPI_VERSION=OPENAPI-v1.0.0
DATA_CONTRACT_VERSION=DATA-v1.0.0
ALLOWED_PATHS=tests/integration/**; .github/**; compose*.yml; docs/markdown/02_WBS.md; docs/markdown/collaboration/**; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현; .env; API key; actual customer data; model binary·RunPod artifact commit; frontend·Report 변경; 다른 Docker project·container·volume의 생성·수정·삭제·재시작
ACCEPTANCE_CRITERIA=dev `a57b273`의 PROMPT-v1.0.1과 R3 schema guided transport를 task 전용 RunPod A40 고정 Qwen3-4B endpoint·task backend에 연결한다. 기존 hotel-synthetic-db Trino는 `DATA_PLATFORM_MODE=i2`·read-only `TRINO_USER=answervice`로 조회만 하고 project·container·volume을 변경하지 않는다. 동일 synthetic `/analysis`에서 node2 SQL의 LIMIT 1~1000, G2 PASS, 실제 read-only QUERY, G3, ARTIFACT와 model/source/query/evidence/latency를 확인한다. 실패 시 마지막 stage·오류·SQL hash·query/Artifact 부재와 정확한 소유 병목을 기록한다. 회귀·비용·task cleanup을 확인하고 성공 trace와 필수 보안 경계가 모두 충족될 때만 I3 판정을 진행한다.
ACCEPTANCE_IDS=AC1_PROMPT_V101_ENDPOINT;AC2_LIMIT_POLICY;AC3_G2_PASS;AC4_READ_ONLY_QUERY;AC5_G3_ARTIFACT;AC6_EVIDENCE;AC7_REGRESSION;AC8_COST_LIMIT;AC9_EXACT_CLEANUP;AC10_I3_DECISION
TEST_COMMANDS=task backend health; I2 source health; synthetic POST /analysis fixed headers; LIMIT·trace·artifact·evidence inspection; production model·analysis·OpenAPI regression; integration regression; exact task container/image/tunnel cleanup; RunPod exact Pod GET 404 and active Pods 0; existing Docker IDs·status unchanged; document·WBS·report validation; git diff --check
TEST_COMMAND_IDS=T1_BACKEND_HEALTH;T2_I2_HEALTH;T3_LIVE_ANALYSIS;T4_LIMIT_TRACE;T5_EVIDENCE;T6_BACKEND_REGRESSION;T7_INTEGRATION;T8_TASK_CLEANUP;T9_POD_CLEANUP;T10_DOCKER_SCOPE;T11_DOCUMENTS
STOP_CONDITIONS=누적 비용 USD 15 도달 예상; 다른 Docker project write·restart·configuration change 필요; public model endpoint 필요; secret 출력·commit 필요; 실제 고객 데이터 전송 필요; R2~R5 code 추가 변경 필요; 필수 안전 경계 위반
HANDOFF=PROMPT-v1.0.1 실제 node2·repair·G2·query·G3·artifact trace와 model/source/evidence·latency·비용·cleanup, I3 승인 또는 정확한 후속 병목을 전 역할에 전달
EXTERNAL_ACTION_PERMISSION=사용자가 승인한 누적 USD 15 한도 안에서 task 전용 RunPod A40 Pod 생성·고정 serving image와 Qwen3-4B 다운로드·합성 요청 전송·localhost SSH tunnel·task backend build/run·결과 회수·정확한 task Pod·container·image·tunnel 삭제와 기존 hotel-synthetic-db Trino의 read-only synthetic 조회, R1 허용 경로 commit·junhee/dev push 승인. 다른 Pod·Docker project·container·volume 변경, public endpoint·secret 출력/commit, 실제 고객 데이터, LoRA 재학습·제품 기본값 전환은 불가
COST_BASELINE_USD=이전 실측·추정 누적 상한 1.188721; 최종 provider billing 지연 시 예상값과 확정 여부를 분리 기록
LIVE_TRACE_EVIDENCE=task Secure A40 `0bkuseap7qtuyn`·고정 Qwen3-4B revision·vLLM 0.10.2와 task backend `91610c2`을 localhost tunnel로 연결했다. backend health=healthy, Trino=ready, app DB는 의도적으로 미설정했다. 동일 synthetic `/analysis`는 HTTP 200·57,108.0ms·FAILED/INTERNAL_ERROR로 MODEL에서 안전 종료했고 QUERY·G2·G3·ARTIFACT는 실행되지 않았다.
ROOT_CAUSE=PROMPT-v1.0.1은 SQL에 LIMIT 1건을 생성했지만 한 node2 completion이 SQL 문자열 안에 881줄의 불필요한 개행을 만들었다. raw endpoint는 prompt 639·completion 1,500 token, content 2,854자, `finish_reason=length`였고 JSON은 line 881에서 종료되어 references·parameters·model field가 생성되지 않았다. content SHA-256은 `cb1a50b955b7293dd67dfc1edc4474b46621daec4bc12a08850eedcd75a9f430`이며 원문은 출력·저장하지 않았다.
REGRESSION_EVIDENCE=production model·analysis pipeline 22건 PASS, integration 24건 PASS. OpenAPI local은 host FastAPI 부재로 이전과 같이 BLOCKED이며 R4 source CI run `30841201329`의 OpenAPI PASS를 유지한다.
RESOURCE_CLEANUP=task backend container·image·localhost tunnel·known_hosts 제거, Pod exact GET 404·active Pods 0 확인. hotel-synthetic-db Trino ID `bafdc16362af...`·running·restart count 0 유지, 다른 Docker resource는 변경하지 않았다.
COST_RESULT=Pod 실행 상한 541.834초·USD 0.066224 추정, 예상 누적 상한 USD 1.254945로 승인 한도 USD 15 이내다.
BLOCKER=R3 node2 prompt가 SQL을 한 줄·불필요한 공백과 개행 없이 간결하게 생성하도록 제한하고 동일 raw endpoint에서 `finish_reason=stop`·완전한 schema·LIMIT을 확인하기 전 제품 G2·QUERY·G3·ARTIFACT와 I3 승인이 불가하다.
```

### R3-W3-F7

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F7
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-15 node2 단일 행 SQL 출력 prompt 보완
CURRENT_TASK_CARD_ID=R3-15
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=91610c2e7fa43374532c7557a26cf9a2186834c7
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F7@91610c2
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.2
MODEL_ID=Qwen/Qwen3-4B
MODEL_REVISION=1cfa9a7208912126459214e8b04321603b3df60c
ALLOWED_PATHS=src/ai/prompt_registry.py; tests/ai/test_prompt_registry.py; tests/ai/test_node2.py; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; infrastructure/database/**; .env; API key; model binary·adapter·checkpoint·평가 생성물; training dataset; frontend·Report; root Compose·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=node2 prompt에 SQL 문자열은 한 줄로 작성하고 불필요한 공백·개행을 넣지 않으며 기존 단일 read-only SELECT·LIMIT 1~1000을 유지하도록 명시한다. node2 prompt만 `PROMPT-v1.0.2`로 올리고 repair는 `PROMPT-v1.0.1`, 다른 node·schema·backend·dataset·max_tokens는 변경하지 않는다. unit test는 한 줄·간결 출력 문구와 node별 version mapping을 고정한다. 실제 Base `finish_reason=stop`·제품 trace는 R1 후속에서 검증한다.
ACCEPTANCE_IDS=AC1_SINGLE_LINE_SQL;AC2_NO_REDUNDANT_WHITESPACE;AC3_LIMIT_PRESERVED;AC4_VERSION_MAPPING;AC5_SCOPE_PRESERVED;AC6_REGRESSION
TEST_COMMANDS=python -m unittest tests.ai.test_prompt_registry tests.ai.test_node2 tests.ai.test_contracts tests.ai.test_fake_model -v; python -m compileall -q src/ai/prompt_registry.py; python .agents/skills/update-project-reports/scripts/validate_reports.py --date 20260804 docs/markdown/daily_reports/daesung/일일보고.md; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_PROMPT_UNIT;T2_COMPILE;T3_REPORT;T4_ROLE_GATE;T5_DIFF_CHECK
STOP_CONDITIONS=max_tokens·guided schema·backend transport·dataset 수정 필요; prompt만으로 compact SQL을 명시할 수 없음; RunPod·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R1에 node2 prompt v1.0.2 hash·한 줄 compact SQL·LIMIT 보존·version mapping·unit regression과 후속 raw finish reason·제품 trace 조건을 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R3 개인 일일보고의 commit·daesung push 승인; dependency 설치·RunPod·비용·secret 사용·외부 model 호출·dev merge 불가
RESULT_SHA=863cb373289af1d0ea917f175797094417dbf93a
SOURCE_CI_EVIDENCE=GitHub Actions run 30843971371 PASS; Python 전체·document quality·role scope·quality gate PASS
DEV_MERGE_SHA=80b91b068d83b8bc171542e912c0508ebd41a7b0
R1_REVIEW=node2 prompt 한 문장과 version mapping만 바꿔 한 줄·불필요한 공백/개행 금지를 명시하고 기존 LIMIT·repair·schema·backend·dataset·max_tokens를 보존한 최소 변경과 15건 local·전체 CI를 수용
```

### R1-W3-F4

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W3-F4
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R1-10 PROMPT-v1.0.2 Base·I2 synthetic 최종 제품 trace
CURRENT_TASK_CARD_ID=R1-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=80b91b068d83b8bc171542e912c0508ebd41a7b0
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W3-F4@80b91b0
MODEL_CONTRACT_VERSION=MODEL-v1.0.0
PROMPT_VERSION=PROMPT-v1.0.2
OPENAPI_VERSION=OPENAPI-v1.0.0
DATA_CONTRACT_VERSION=DATA-v1.0.0
ALLOWED_PATHS=tests/integration/**; .github/**; compose*.yml; docs/markdown/02_WBS.md; docs/markdown/collaboration/**; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현; .env; API key; actual customer data; model binary·RunPod artifact commit; frontend·Report 변경; 다른 Docker project·container·volume의 생성·수정·삭제·재시작
ACCEPTANCE_CRITERIA=dev `80b91b0`의 PROMPT-v1.0.2·guided schema를 task A40 고정 Qwen3-4B와 task backend에 localhost로 연결한다. raw node2가 `finish_reason=stop`, 완전한 schema, 한 줄 SQL, LIMIT 1~1000을 반환하는지 먼저 확인한 뒤 동일 I2 synthetic `/analysis`의 MODEL→G2→read-only QUERY→G3→ARTIFACT와 evidence를 확인한다. 실패하면 exact stage·hash·query/Artifact 부재를 기록한다. 비용·회귀·정확한 cleanup을 확인하고 성공 trace와 필수 경계가 모두 충족될 때만 I3를 판정한다.
ACCEPTANCE_IDS=AC1_RAW_STOP;AC2_SINGLE_LINE_LIMIT;AC3_SCHEMA;AC4_G2_QUERY;AC5_G3_ARTIFACT;AC6_EVIDENCE;AC7_REGRESSION;AC8_COST;AC9_CLEANUP;AC10_I3_DECISION
TEST_COMMANDS=task backend·I2 health; raw node2 metadata diagnostic; synthetic POST /analysis; trace·artifact·evidence inspection; backend·integration regression; exact task resource cleanup; Pod 404·active 0; existing Docker unchanged; docs/WBS/report validation; git diff --check
TEST_COMMAND_IDS=T1_HEALTH;T2_RAW_NODE2;T3_LIVE_ANALYSIS;T4_EVIDENCE;T5_REGRESSION;T6_TASK_CLEANUP;T7_POD_CLEANUP;T8_DOCKER_SCOPE;T9_DOCUMENTS
STOP_CONDITIONS=누적 비용 USD 15 도달 예상; 다른 Docker project 변경 필요; public endpoint·secret 출력/commit·실제 고객 데이터 필요; R2~R5 code 추가 변경 필요; 필수 안전 경계 위반
HANDOFF=PROMPT-v1.0.2 raw finish/schema/single-line/LIMIT와 제품 G2/query/G3/artifact·evidence·latency·비용·cleanup, I3 승인 또는 exact blocker 전달
EXTERNAL_ACTION_PERMISSION=사용자 승인 누적 USD 15 안의 task 전용 A40·고정 model 다운로드·합성 localhost 요청·task backend·정확한 task cleanup과 기존 synthetic Trino read-only 조회, R1 허용 경로 commit·junhee/dev push 승인. 다른 Pod·Docker project·volume 변경, public endpoint·secret 출력/commit·실제 고객 데이터·LoRA 변경 불가
COST_BASELINE_USD=이전 실측·추정 누적 상한 1.254945
LIVE_TRACE_EVIDENCE=raw node2는 고정 합성 UUID에서 `finish_reason=stop`, schema PASS, SQL 1줄·644자·LIMIT 500·completion 971 token을 확인했다. 그러나 실제 제품의 무작위 request UUID 두 건은 각각 약 54.6초 뒤 MODEL/INTERNAL_ERROR로 종료됐고 QUERY·G2·G3·ARTIFACT가 없었다. task backend circuit 초기화 뒤에도 동일했다.
ROOT_CAUSE=동일 실패 request UUID를 새 `ContractModelAdapter`로 직접 호출하면 schema·plan이 정상인 반면 제품 singleton의 두 transport attempt는 해당 UUID에서 연속 invalid 응답을 받아 circuit을 열었다. 현재 동결 node2 request는 실제 질문 없이 `question_id + context_package`만 전달해 Base가 분석 의미 대신 무작위 UUID에 반응한다. R3 training README도 `normalized_question` 누락을 실제 SQL 생성 계약 차이로 명시하고 있다.
RESOURCE_CLEANUP=task backend container·image·localhost tunnel·known_hosts 제거, Pod exact GET 404·active Pods 0 확인. hotel-synthetic-db Trino ID `bafdc16362af...`·running·restart count 0 유지, 다른 Docker resource는 변경하지 않았다.
COST_RESULT=Pod 실행 상한 744.369초·USD 0.090978 추정, 예상 누적 상한 USD 1.345923로 승인 한도 USD 15 이내다.
BLOCKER=R3 node2 request가 실제 normalized question을 호환 수용하고 prompt가 question_id의 의미를 무시하도록 명시한 뒤 R4 제품 adapter가 실제 질문을 전달하기 전 Base 제품 trace와 I3 승인이 불가하다.
```

### R3-W3-F8

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F8
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-15 node2 normalized question 호환 계약
CURRENT_TASK_CARD_ID=R3-15
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=b182fafe4ed123919f3d0e21329cbabc99fe0110
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F8@b182faf
MODEL_CONTRACT_VERSION=MODEL-v1.0.0-compatible
PROMPT_VERSION=PROMPT-v1.0.3
ALLOWED_PATHS=src/ai/contracts/node_io.v0.1.json; src/ai/prompt_registry.py; tests/ai/test_contracts.py; tests/ai/test_prompt_registry.py; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; infrastructure/database/**; .env; API key; model binary·adapter·checkpoint·평가 생성물; training dataset; frontend·Report; root Compose·CI; R1/R2/R4/R5 소유 문서
ACCEPTANCE_CRITERIA=node2_request에 기존 소비자를 깨지 않는 optional non-empty `normalized_question` property를 추가한다. node2 prompt는 SQL 의미를 normalized_question에서만 가져오고 question_id는 추적 식별자일 뿐 분석 의미로 사용하지 않도록 명시하며 기존 한 줄 read-only SELECT·LIMIT 규칙을 유지한다. node2 prompt만 PROMPT-v1.0.3으로 올린다. 기존 payload와 새 payload 모두 schema PASS, empty question은 거부한다. backend·training dataset·다른 node contract는 변경하지 않는다.
ACCEPTANCE_IDS=AC1_OPTIONAL_QUESTION;AC2_NON_EMPTY;AC3_ID_IGNORED;AC4_LEGACY_COMPAT;AC5_PROMPT_VERSION;AC6_REGRESSION
TEST_COMMANDS=python -m unittest tests.ai.test_prompt_registry tests.ai.test_contracts tests.ai.test_node2 tests.ai.test_fake_model -v; python -m compileall -q src/ai; report validation; role gate; git diff --check
TEST_COMMAND_IDS=T1_AI_CONTRACT;T2_COMPILE;T3_REPORT;T4_ROLE_GATE;T5_DIFF
STOP_CONDITIONS=required field로 즉시 전환해야 함; backend·dataset·다른 node 수정 필요; RunPod·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R1·R4에 optional normalized_question schema·legacy compatibility·prompt version/hash·question_id 비의미 규칙·test를 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R3 개인 일일보고 commit·daesung push 승인; dependency·RunPod·비용·secret·외부 model·dev merge 불가
RESULT_SHA=01dd9130e60c371ad5898cb8e1ddcb0c44a3de78
SOURCE_CI_EVIDENCE=GitHub Actions run 30845353451 PASS; Python 전체·document quality·role scope·quality gate PASS
DEV_MERGE_SHA=cc200ee391075e022ef21c94fa49307bae08d54a
R1_REVIEW=node2 request에 optional non-empty normalized_question만 추가하고 prompt가 질문만 SQL 의미로 사용하도록 명시해 legacy payload·다른 node·backend·dataset을 보존한 호환 변경과 16건 local·전체 CI를 수용
```

### R4-W3-F3

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W3-F3
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-08 제품 질문의 node2 normalized_question 전달
CURRENT_TASK_CARD_ID=R4-08
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=cc200ee391075e022ef21c94fa49307bae08d54a
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W3-F3@cc200ee
MODEL_CONTRACT_VERSION=MODEL-v1.0.0-compatible
PROMPT_VERSION=PROMPT-v1.0.3
OPENAPI_VERSION=OPENAPI-v1.0.0
ALLOWED_PATHS=app/backend/app/services/analysis_service.py; app/backend/app/adapters/contract_model.py; tests/backend/test_production_model.py; tests/backend/test_analysis_pipeline.py; app/backend/README.md; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/ai/**; src/data/**; infrastructure/database/**; .env; API key; frontend·Report; root Compose·CI; R1/R2/R3/R5 소유 문서
ACCEPTANCE_CRITERIA=AnalysisService의 일반 질문 node2 payload에 원문 `payload.question`을 추가하고 ContractModelAdapter가 이를 R3 node2_request의 `normalized_question`으로 전달한다. question_id·Context·guided schema·fixed generation options·repair·fallback 차단·OpenAPI를 보존한다. 빈 질문은 기존 AnalysisRequest 경계가 거부한다. unit test는 실제 질문이 transport payload까지 동일하게 도달하고 request_id와 분리됨을 확인하며 fake·failure·analysis 회귀를 통과한다.
ACCEPTANCE_IDS=AC1_SERVICE_QUESTION;AC2_ADAPTER_NORMALIZED;AC3_ID_SEPARATION;AC4_BOUNDARY;AC5_TRANSPORT_PRESERVED;AC6_REGRESSION
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend/test_production_model.py tests/backend/test_analysis_pipeline.py tests/backend/test_openapi_contract.py; python -m compileall -q app/backend; report validation; role gate; git diff --check
TEST_COMMAND_IDS=T1_BACKEND;T2_COMPILE;T3_REPORT;T4_ROLE_GATE;T5_DIFF
STOP_CONDITIONS=R3 schema·prompt 추가 변경 필요; normalized question 변형·요약 필요; OpenAPI·DB·data 변경 필요; dependency·RunPod·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R1에 service→adapter→R3 request 실제 질문 전달·ID 분리·guided transport·회귀와 후속 Base 제품 trace 조건을 전달
EXTERNAL_ACTION_PERMISSION=허용 경로와 R4 개인 일일보고 commit·jaehong push 승인; dependency·RunPod·비용·secret·외부 model·dev merge 불가
RESULT_SHA=f8140d0a8ca6fc4b11fc532eda6ce279b95502c6
SOURCE_CI_EVIDENCE=GitHub Actions run 30845776821 PASS; Python 전체·OpenAPI·document quality·role scope·quality gate PASS
DEV_MERGE_SHA=dcb00c362995e4593e70783c23f3c9e03825b2fd
R1_REVIEW=제품 원문 question을 AnalysisService node2 payload와 ContractModelAdapter normalized_question에 그대로 전달하고 request ID·Context·guided schema·generation option·fallback 경계를 보존한 2줄 production 변경과 23건 local·전체 CI를 수용
```

### R1-W3-F5

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W3-F5
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R1-10 실제 질문 Base·I2 synthetic 제품 전체 trace
CURRENT_TASK_CARD_ID=R1-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=dcb00c362995e4593e70783c23f3c9e03825b2fd
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W3-F5@dcb00c3
MODEL_CONTRACT_VERSION=MODEL-v1.0.0-compatible
PROMPT_VERSION=PROMPT-v1.0.3
OPENAPI_VERSION=OPENAPI-v1.0.0
DATA_CONTRACT_VERSION=DATA-v1.0.0
ALLOWED_PATHS=tests/integration/**; .github/**; compose*.yml; docs/markdown/02_WBS.md; docs/markdown/collaboration/**; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현; .env; API key; actual customer data; model binary·RunPod artifact commit; frontend·Report 변경; 다른 Docker project·container·volume 변경
ACCEPTANCE_CRITERIA=dev `dcb00c3`을 task A40 고정 Qwen3-4B·task backend·기존 synthetic Trino read-only에 localhost로 연결한다. raw node2 request에 실제 normalized question과 별도 question_id가 포함되고 finish/schema/한 줄/LIMIT을 통과하는지 확인한 뒤 동일 `/analysis`의 MODEL→G2→QUERY→G3→ARTIFACT와 evidence를 판정한다. 실패 시 exact blocker를 기록한다. 비용·회귀·task cleanup을 확인하고 성공 trace 전 I3를 승인하지 않는다.
ACCEPTANCE_IDS=AC1_QUESTION_INPUT;AC2_RAW_SCHEMA;AC3_G2_QUERY;AC4_G3_ARTIFACT;AC5_EVIDENCE;AC6_REGRESSION;AC7_COST;AC8_CLEANUP;AC9_I3
TEST_COMMANDS=task health; raw node2 metadata; synthetic POST /analysis; trace/artifact/evidence; regressions; exact cleanup; Pod 404·active 0; Docker scope; docs validation
TEST_COMMAND_IDS=T1_HEALTH;T2_RAW;T3_PRODUCT;T4_EVIDENCE;T5_REGRESSION;T6_CLEANUP;T7_SCOPE;T8_DOCS
STOP_CONDITIONS=USD15 예상 도달; 다른 Docker 변경·public endpoint·secret·실제 고객 데이터·R2~R5 추가 code 필요; 안전 경계 위반
HANDOFF=실제 질문 raw·제품 trace·evidence·비용·cleanup과 I3 판정 또는 exact blocker 전달
EXTERNAL_ACTION_PERMISSION=누적 USD15 안 task A40·고정 model·합성 localhost 요청·task backend·정확한 cleanup과 기존 synthetic Trino read-only 조회, R1 commit·junhee/dev push 승인. 다른 resource·public endpoint·secret·실제 고객 데이터·LoRA 변경 불가
COST_BASELINE_USD=이전 실측·추정 누적 상한 1.345923
RESULT=raw node2는 실제 질문·별도 question_id·guided schema·한 줄 SQL·LIMIT을 통과했고 제품 `/analysis`도 MODEL·G2를 통과했으나 QUERY_SOURCE_FAILED로 종료되어 G3·Artifact·evidence가 생성되지 않았다.
ROOT_CAUSE=Base가 SQL placeholder와 무관한 `normalized_question`·`question_id`를 response parameters로 반환했고 R4 날짜 바인더가 non-ISO 값을 안전하게 거부했다. 진단 SQL hash는 `63d6325bcbad42da9c3904591150bc1a27077f130f4125183f39f9f66b9be04a`, G2는 PASS였다.
EVIDENCE=제품 request `a3924833-0718-4e78-b819-4e80b015e974`는 HTTP 200·FAILED·repair 0·ROUTER~G2 PASS·QUERY FAILED였다. task Pod `zql141iuw1xdda`는 582.566초 뒤 404, 활성 Pod 0, 비용 상한 USD 0.071203·누적 상한 USD 1.417126이며 task container·image·tunnel 0과 기존 Trino ID·running·restart 0을 확인했다.
BLOCKER=R3 node2 prompt가 response parameters를 SQL placeholder와 1:1로 제한하고 request metadata를 parameter로 반환하지 않게 한 뒤 실제 제품 trace를 다시 확인하기 전 I3 승인 불가
```

### R3-W3-F9

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F9
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-07 node2 SQL parameter 의미 고정
CURRENT_TASK_CARD_ID=R3-07
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team\.wt\r3_w3
BASE_BRANCH=dev
BASE_SHA=908d0b31d0f00034697f59c0497b9d7bd8ee7039
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F9@908d0b3
MODEL_CONTRACT_VERSION=MODEL-v1.0.0-compatible
PROMPT_VERSION=PROMPT-v1.0.4
ALLOWED_PATHS=src/ai/prompt_registry.py; tests/ai/test_prompt_registry.py; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=node schema·training dataset·backend·data adapter·frontend·root Compose·.env·model binary
ACCEPTANCE_CRITERIA=node2 prompt의 parameters는 SQL에 실제로 사용한 `:name` placeholder만 포함하고 이름이 placeholder와 1:1로 일치해야 하며, `question_id`·`normalized_question` 등 request metadata를 포함하지 않는다. placeholder가 없으면 빈 배열을 반환한다. 기존 actual-question·한 줄 read-only SELECT·LIMIT 규칙과 다른 prompt·schema·dataset은 보존하고 node2 prompt만 PROMPT-v1.0.4로 올린다.
ACCEPTANCE_IDS=AC1_PARAMETER_PLACEHOLDER;AC2_METADATA_EXCLUSION;AC3_EMPTY_PARAMETERS;AC4_PROMPT_REGRESSION;AC5_SCOPE
TEST_COMMANDS=python -m unittest tests.ai.test_prompt_registry; python -m unittest discover -s tests/ai -p test_*.py; git diff --check
TEST_COMMAND_IDS=T1_PROMPT;T2_AI;T3_DIFF
STOP_CONDITIONS=schema·dataset·backend 변경 필요; 날짜 값 생성 규칙 확장 필요; 기존 actual-question·LIMIT 규칙 회귀; test 실패
HANDOFF=R1에 prompt version/hash·parameter 의미·metadata 제외·회귀 결과 전달
EXTERNAL_ACTION_PERMISSION=없음 — local code·test·commit·daesung push만 승인
RESULT=PROMPT-v1.0.4에서 parameters를 SQL의 실제 `:name` placeholder와 1:1로 제한하고 placeholder가 없으면 빈 배열, request metadata는 제외하도록 명시했다.
EVIDENCE=daesung `d70821a`, harness sync `ea22ea7`, CI `30847080427` PASS, dev merge `15480fd`, AI local 47건·gate scope 19건 PASS
R1_REVIEW=prompt 2문장과 assertion만 추가해 schema·dataset·backend를 보존한 최소 변경이며 전체 CI를 통과해 수용
```

### R1-W3-F6

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W3-F6
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R1-10 parameter 보완 후 Base·I2 제품 전체 trace
CURRENT_TASK_CARD_ID=R1-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=15480fd20e3c2e55812d8c9e37f7a1159ea52630
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W3-F6@15480fd
MODEL_CONTRACT_VERSION=MODEL-v1.0.0-compatible
PROMPT_VERSION=PROMPT-v1.0.4
OPENAPI_VERSION=OPENAPI-v1.0.0
DATA_CONTRACT_VERSION=DATA-v1.0.0
ALLOWED_PATHS=tests/integration/**; .github/**; compose*.yml; docs/markdown/02_WBS.md; docs/markdown/collaboration/**; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현; .env; API key; actual customer data; model binary·RunPod artifact commit; frontend·Report 변경; 다른 Docker project·container·volume 변경
ACCEPTANCE_CRITERIA=dev `15480fd`을 task A40 고정 Qwen3-4B·task backend·기존 synthetic Trino read-only에 localhost로 연결한다. raw node2의 parameters가 SQL placeholder와 일치하고 request metadata를 포함하지 않는지 확인한 뒤 동일 `/analysis`의 MODEL→G2→QUERY→G3→ARTIFACT와 evidence를 판정한다. 실패 시 exact blocker를 기록한다. 비용·회귀·task cleanup을 확인하고 성공 trace 전 I3를 승인하지 않는다.
ACCEPTANCE_IDS=AC1_PARAMETER_OUTPUT;AC2_RAW_SCHEMA;AC3_G2_QUERY;AC4_G3_ARTIFACT;AC5_EVIDENCE;AC6_REGRESSION;AC7_COST;AC8_CLEANUP;AC9_I3
TEST_COMMANDS=task health; raw node2 metadata; synthetic POST /analysis; trace/artifact/evidence; regressions; exact cleanup; Pod 404·active 0; Docker scope; docs validation
TEST_COMMAND_IDS=T1_HEALTH;T2_RAW;T3_PRODUCT;T4_EVIDENCE;T5_REGRESSION;T6_CLEANUP;T7_SCOPE;T8_DOCS
STOP_CONDITIONS=USD15 예상 도달; 다른 Docker 변경·public endpoint·secret·실제 고객 데이터·R2~R5 추가 code 필요; 안전 경계 위반
HANDOFF=parameter raw·제품 trace·evidence·비용·cleanup과 I3 판정 또는 exact blocker 전달
EXTERNAL_ACTION_PERMISSION=누적 USD15 안 task A40·고정 model·합성 localhost 요청·task backend·정확한 cleanup과 기존 synthetic Trino read-only 조회, R1 commit·junhee/dev push 승인. 다른 resource·public endpoint·secret·실제 고객 데이터·LoRA 변경 불가
COST_BASELINE_USD=이전 실측·추정 누적 상한 1.417126
RESULT=정상 uptime의 Secure A40에서 고정 Qwen3-4B endpoint와 task backend를 기동해 실제 synthetic `/analysis`를 호출했다. HTTP 200이었지만 ROUTER→CONTROLLER→CONTEXT→G1→MODEL 뒤 첫 G2가 `SQL_REFERENCE_MISMATCH`, 허용된 1회 repair 뒤 두 번째 G2가 `SQL_POLICY_BLOCKED`로 차단돼 QUERY·G3·ARTIFACT는 생성되지 않았다.
EVIDENCE=제품 응답 SHA-256 `5adeeaaa7f1a1bce2c725ee3f4c4c7738130caf8e9ff0505fd48a7ac1ce90758`, 두 번째 task Pod 상한 USD 0.166222, task Pod GET 404·활성 Pod 0, task backend·task PostgreSQL·image·tunnel 0을 확인했다. 기존 `hotel-synthetic-db-trino-1`과 `app-postgres`는 ID·restart count가 동일하고 healthy이며 secret은 응답·로그에 남기지 않았다. 첫 SSH 진단 Pod의 별도 청구 확정은 billing 반영 전이라 Not Run으로 유지한다.
BLOCKER=Base node2가 반환한 SQL의 FROM/JOIN table 집합과 references의 `trino_fqn` 집합이 일치하지 않았고, `SQL_REFERENCE_MISMATCH` 1회 repair도 G2 정책을 통과하지 못했다. 두 집합의 정확 일치와 해당 오류의 단일 수정 행동을 prompt에 고정한 뒤 실제 제품 trace 재검증 전 I3 승인 불가
RESUME_EVIDENCE=사용자 목표 재개 후 공식 PyTorch template Secure A40 `6xiz3gs3a68032`을 다시 할당했으나 474.937초 동안 실제 uptime이 계속 0이어서 SSH·모델·제품 요청을 실행하지 않았다. Pod GET 404·활성 0, 신규 비용 상한 USD 0.058048·누적 상한 USD 1.617033, 기존 Trino 동일 ID·running·restart 0과 임시 CLI config 0 bytes를 확인했다.
RESUME_DECISION=동일 외부 provisioning blocker가 재현되어 I3와 R1-W3-F6 BLOCKED를 유지한다. R2~R5에 추가 구현 지시는 없으며 정상 uptime이 확인되는 task A40에서 동일 승인 조건으로 재검증한다.
FOLLOWUP_DECISION=R3-W3-F10의 PROMPT-v1.0.5/PROMPT-v1.0.2가 SQL-reference 정확 일치와 단일 repair 행동을 dev `b316336`·CI `30866726434` PASS로 통합해 code blocker는 해제했다. 실제 성공 trace는 R1-W3-F7에서 재판정한다.
```

### R3-W3-F10

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F10
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-07 Node 2·2′ SQL-reference 정합 보완
CURRENT_TASK_CARD_ID=R3-07
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=7a514905b6608a8a7399cb5b5c5cc63f37e632f1
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F10@7a51490
MODEL_CONTRACT_VERSION=MODEL-v1.0.0-compatible
PROMPT_VERSION=PROMPT-v1.0.5/PROMPT-v1.0.2
ALLOWED_PATHS=src/ai/prompt_registry.py; tests/ai/test_prompt_registry.py; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=node schema·training dataset·backend·G2 policy·data adapter·frontend·root Compose·.env·model binary
ACCEPTANCE_CRITERIA=node2 prompt는 SQL의 FROM/JOIN에 실제 사용한 승인 Context asset의 `trino_fqn` 집합과 response references의 `trino_fqn` 집합을 양방향 정확 일치시키고, 사용하지 않은 asset을 references에 넣거나 사용한 table을 누락하지 않는다. node2_repair prompt는 `SQL_REFERENCE_MISMATCH`일 때 rejected SQL의 질문 의미·승인 Context·parameter를 보존하면서 corrected SQL과 references의 같은 집합을 한 번만 맞춘다. 기존 actual-question·한 줄 read-only SELECT·LIMIT 1~1000·placeholder 1:1·RESOURCE_POLICY_MISSING 행동과 schema·dataset은 보존한다.
ACCEPTANCE_IDS=AC1_NODE2_REFERENCE_EXACT;AC2_REPAIR_REFERENCE_EXACT;AC3_CONTEXT_ONLY;AC4_EXISTING_POLICY;AC5_PROMPT_REGRESSION;AC6_SCOPE
TEST_COMMANDS=python -m unittest tests.ai.test_prompt_registry; python -m unittest discover -s tests/ai -p "test_*.py"; git diff --check
TEST_COMMAND_IDS=T1_PROMPT;T2_AI;T3_DIFF
STOP_CONDITIONS=schema·training dataset·backend·G2 변경 필요; reference 정확 일치가 prompt만으로 표현 불가; 기존 LIMIT·parameter·actual-question 규칙 회귀; test 실패
HANDOFF=R1에 node2·repair prompt version/hash·SQL-reference 정확 일치 문구·기존 정책 회귀 결과 전달
EXTERNAL_ACTION_PERMISSION=없음 — local prompt·test·commit·daesung push만 승인
RESULT=node2는 SQL FROM·JOIN과 references의 승인 `trino_fqn` 집합을 양방향 정확 일치시키고, node2_repair는 `SQL_REFERENCE_MISMATCH`에서 질문 의미·승인 Context·parameter를 보존해 한 번만 맞추도록 prompt를 보완했다. node2는 PROMPT-v1.0.5, repair는 PROMPT-v1.0.2로 올렸다.
EVIDENCE=daesung `9d1b937`, dev `b316336`, CI `30866726434` PASS, prompt 3건·AI 47건·Gate scope 19건·보고 검증 PASS
R1_REVIEW=schema·training dataset·backend·G2를 바꾸지 않고 prompt 두 문장과 문자열 회귀만 추가한 최소 변경으로 허용 경로와 기존 LIMIT·parameter·actual-question 규칙을 보존해 수용한다.
```

### R1-W3-F7

```text
STATUS=VERIFIED_GATE
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W3-F7
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R1-10 SQL-reference 보완 후 Base·I2 제품 전체 trace
CURRENT_TASK_CARD_ID=R1-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=b316336cb2b145f14737e77b4e3119c6fe8de80e
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W3-F7@b316336
MODEL_CONTRACT_VERSION=MODEL-v1.0.0-compatible
PROMPT_VERSION=PROMPT-v1.0.6/PROMPT-v1.0.2
OPENAPI_VERSION=OPENAPI-v1.0.0
DATA_CONTRACT_VERSION=DATA-v1.0.0
ALLOWED_PATHS=tests/integration/**; .github/**; compose*.yml; docs/markdown/02_WBS.md; docs/markdown/collaboration/**; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 서비스 내부 구현; .env; API key; actual customer data; model binary·RunPod artifact commit; frontend·Report 변경; 다른 Docker project·container·volume 변경
ACCEPTANCE_CRITERIA=dev `b316336`·CI `30866726434` PASS의 PROMPT-v1.0.5/PROMPT-v1.0.2를 task A40 고정 Qwen3-4B·task backend·기존 synthetic Trino read-only에 localhost로 연결한다. raw node2의 SQL FROM/JOIN과 references `trino_fqn` 집합·parameters/placeholder를 확인하고 동일 synthetic `/analysis`의 MODEL→G2→QUERY→G3→ARTIFACT와 evidence를 판정한다. 실패 시 첫·repair plan의 exact G2 code와 query/Artifact 부재를 기록한다. 회귀·비용·secret 비기록·task cleanup을 확인하고 성공 trace와 필수 보안 경계가 모두 충족될 때만 I3를 승인한다.
ACCEPTANCE_IDS=AC1_REFERENCE_OUTPUT;AC2_PARAMETER_OUTPUT;AC3_RAW_SCHEMA;AC4_G2_QUERY;AC5_G3_ARTIFACT;AC6_EVIDENCE;AC7_REGRESSION;AC8_SECRET_REDACTED;AC9_COST;AC10_CLEANUP;AC11_I3
TEST_COMMANDS=task health; raw node2 reference/parameter; synthetic POST /analysis; trace/artifact/evidence; backend·integration regressions; exact cleanup; Pod 404·active 0; Docker scope; docs validation
TEST_COMMAND_IDS=T1_HEALTH;T2_RAW;T3_PRODUCT;T4_EVIDENCE;T5_REGRESSION;T6_SECRET;T7_CLEANUP;T8_SCOPE;T9_DOCS
STOP_CONDITIONS=USD15 예상 도달; 다른 Docker 변경·public endpoint·secret·실제 고객 데이터·R2~R5 추가 code 필요; 안전 경계 위반
HANDOFF=reference/parameter raw·제품 trace·evidence·비용·cleanup과 I3 판정 또는 exact blocker 전달
EXTERNAL_ACTION_PERMISSION=누적 USD15 안 task A40·고정 model·합성 localhost 요청·task backend·task 임시 PostgreSQL·정확한 cleanup과 기존 synthetic Trino read-only 조회, R1 commit·junhee/dev push 승인. 다른 resource·public endpoint·secret·실제 고객 데이터·LoRA 변경 불가
COST_BASELINE_USD=확인된 이전 상한 USD 1.783255 + 첫 SSH 진단 Pod 청구 확정 대기, 총 USD 15 미만 유지
RESULT=trace `r1-w3-f7-product-trace-retry7`에서 2026-06 `843295200.00`, 2026-07 `843453600.00` 두 행을 반환했고 ROUTER→CONTROLLER→CONTEXT→G1→MODEL→G2→QUERY→G3→ARTIFACT가 모두 PASSED했다. repair_count=0, Trino query `20260804_013401_00004_7nsas`, artifact `5df73606-2419-51dc-94f4-0de6880745aa`를 확인했다.
EVIDENCE=R3 dev merge `5ce29ff`·R4 dev merge `0007932`·보고 통합 dev `baeda49`, dev CI `30870270154` PASS, AI 52건·backend 25건·integration 24건 PASS, 신규 Pod 비용 상한 USD 0.307711, Pod 404·active 0·secret log 0건·기존 Trino·app DB 무변경
I3_DECISION=5 catalog·승인 5-table JOIN·Node 연결·G1/G2/G3·read-only query·Artifact·보안 회귀와 전월 대비 2개월 의미 결과를 모두 확인해 I3를 VERIFIED_GATE로 승인한다.
```

### R3-W3-F11

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W3-F11
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R3-07 승인 JOIN·기간·집계 의미 보완
CURRENT_TASK_CARD_ID=R3-07
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=11ff44e1d9a16fa73874d625cc4d0ecef1eeaf3f
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W3-F11@11ff44e
MODEL_CONTRACT_VERSION=MODEL-v1.0.0-compatible
PROMPT_VERSION=PROMPT-v1.0.6/PROMPT-v1.0.2
ALLOWED_PATHS=src/ai/prompt_registry.py; tests/ai/test_prompt_registry.py; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; frontend/**; root Compose·env·CI; schema·training data·model binary
ACCEPTANCE_CRITERIA=node2가 승인 PMS→CRM 5-table event-time JOIN을 metadata 식별자와 SQL table로 혼동하지 않고, Context asset 컬럼·metric 집계만 사용한다. 전월 대비 질문은 Context 절대 시각으로 직전 완료 2개월을 반개구간 조회해 월 2행을 반환하도록 PROMPT-v1.0.6에 명시한다. repair·schema·training data·generation option은 변경하지 않는다.
ACCEPTANCE_IDS=AC1_APPROVED_JOIN;AC2_APPROVED_COLUMNS;AC3_METRIC_AGGREGATION;AC4_ABSOLUTE_WINDOW;AC5_PROMPT_VERSION;AC6_REGRESSION
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/ai; python -m compileall -q src/ai/prompt_registry.py; git diff --check
TEST_COMMAND_IDS=T1_AI;T2_COMPILE;T3_DIFF
STOP_CONDITIONS=R3 경로 밖 변경 필요; schema·training data·model option 변경 필요; unit test 실패
HANDOFF=PROMPT-v1.0.6 문구·version·AI regression과 R4 소비자 재검증 조건 전달
EXTERNAL_ACTION_PERMISSION=없음. download·RunPod·비용·secret·배포·데이터 전송 불가
RESULT=PROMPT-v1.0.6에 승인 PMS→CRM 5-table event-time JOIN, 승인 컬럼·metric 집계, timestamp-safe 직전 완료 2개월 반개구간을 고정했다.
EVIDENCE=daesung code `015b3de`·handoff `9ee776b`, AI 47건 PASS, branch CI `30870043448` PASS, dev merge `5ce29ff`
```

### R4-W3-F4

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W3-F4
TARGET_INTEGRATION_GATE=I3
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R4-08 실제 Base 응답 안정화
CURRENT_TASK_CARD_ID=R4-08
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=11ff44e1d9a16fa73874d625cc4d0ecef1eeaf3f
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W3-F4@11ff44e
MODEL_CONTRACT_VERSION=MODEL-v1.0.0-compatible
OPENAPI_VERSION=OPENAPI-v1.0.0
ALLOWED_PATHS=app/backend/app/adapters/contract_model.py; tests/backend/test_production_model.py; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/ai/**; src/data/**; frontend/**; migration·OpenAPI·Controller·G1/G2/G3 상태 전이; root Compose·env·CI
ACCEPTANCE_CRITERIA=실제 Base에는 node2 SQL 또는 repair SQL만 guided 생성시키고, references·prompt/model trace는 승인 Context와 registry에서 결정론적으로 복원한 뒤 기존 MODEL-v1.0.0 response schema 검증을 그대로 통과시킨다. SQL에 없는 잉여 parameter는 실행 계획에서 제외한다. 전월 대비 질문은 승인된 2개월 절대 기간·GROUP BY·ORDER BY가 없으면 모델 실패로 처리한다. G2·query·G3·OpenAPI·schema는 변경하지 않는다.
ACCEPTANCE_IDS=AC1_SQL_ONLY_GUIDE;AC2_DETERMINISTIC_METADATA;AC3_FULL_SCHEMA;AC4_PARAMETER_FILTER;AC5_MOM_FAIL_CLOSED;AC6_REGRESSION
TEST_COMMANDS=python -m unittest tests.backend.test_production_model tests.backend.test_analysis_pipeline; python -m compileall -q app/backend/app/adapters/contract_model.py; git diff --check
TEST_COMMAND_IDS=T1_BACKEND;T2_COMPILE;T3_DIFF
STOP_CONDITIONS=R4 경로 밖 변경 필요; OpenAPI·schema·Gate 상태 전이 변경 필요; full schema 또는 안전 실패 회귀
HANDOFF=SQL-only guided request·결정론적 full response·parameter/기간 fail-closed 회귀와 R1 제품 재검증 조건 전달
EXTERNAL_ACTION_PERMISSION=없음. download·RunPod·비용·secret·배포·데이터 전송 불가
RESULT=실제 serving에서 node2·repair는 SQL만 guided 생성하고 references·model trace는 승인 Context와 prompt registry로 복원하며, SQL placeholder가 아닌 parameter를 제거하고 2개월 질의를 fail-closed로 검증했다.
EVIDENCE=jaehong code `fbac0b8`·handoff `7f05d9a`, backend 25건 PASS, branch CI `30870043591` PASS, dev merge `0007932`
```

## Wave 4 상세 계획 카드

Wave 4는 I4 Reporting 통합부터 RC1·리허설·I5 동결까지 포함한다. I4에서 기능 통합을 마친 뒤 신규 기능을 금지하고 Critical·High 결함과 release 회귀만 수행한다.

### R1-W4-F1A

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F1A
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Gate 0 DataHub runtime
TASK_CARD_RANGE=R1-11 DataHub health 통합 계약 교정
CURRENT_TASK_CARD_ID=R1-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=d2c6fdc132b53c56c6d5e4d9ad714b22dd1cc538
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W4-F1A@d2c6fdc
ALLOWED_PATHS=infrastructure/database/r1-service-fragment.v1.json; infrastructure/database/scripts/verify-service-fragment.ps1; tests/integration/test_gate_scope.py; docs/markdown/02_WBS.md; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=infrastructure/database/datahub/**; src/data/**; app/backend/**; src/ai/**; frontend/**; .env; secret; 다른 Docker project·container·volume 변경
ACCEPTANCE_CRITERIA=DataHub v1.6.0 공식 quickstart와 실제 task 환경에서 200을 반환한 GMS `/health`를 유일한 필수 health endpoint로 고정한다. 존재하지 않는 management `/actuator/health` 요구를 service fragment와 검증기에서 함께 제거하고 `R2_SERVICE_FRAGMENT_VERIFIED`를 확인한다. 이 교정을 dev에 통합한 뒤 R2-W4-F1A가 최신 dev를 받아 branch CI 전체 PASS를 확인하기 전에는 R2 결과를 병합하지 않는다.
ACCEPTANCE_IDS=AC1_OFFICIAL_HEALTH;AC2_FRAGMENT_SYNC;AC3_LOCAL_VERIFY;AC4_DEV_INTEGRATION;AC5_R2_CI
TEST_COMMANDS=powershell -ExecutionPolicy Bypass -File infrastructure/database/scripts/verify-service-fragment.ps1 -EnvFilePath .env.example; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; document/WBS/report validation; git diff --check
TEST_COMMAND_IDS=T1_FRAGMENT;T2_SCOPE;T3_DOCS;T4_DIFF
STOP_CONDITIONS=공식 v1.6 health 계약과 불일치; R1 허용 경로 밖 변경 필요; R2 제품 경로 변경 필요; 필수 검증 실패
HANDOFF=dev health 계약 commit·CI와 R2 최신 dev 재검증 조건 전달
EXTERNAL_ACTION_PERMISSION=사용자의 작업 계속·commit·push·dev 통합 승인에 따라 위 허용 경로의 local 검증·commit·junhee push·dev 병합을 승인한다. 비용·외부 배포·secret·다른 Docker 변경은 불가하다.
RESULT=task DataHub v1.6.0에서 GMS `/health` 200과 management `/actuator/health` 404를 확인해 service fragment와 검증기의 잘못된 management 필수 조건을 제거했다. R2 결과를 최신 dev에서 재검증해 branch와 dev CI를 모두 통과했다.
EVIDENCE=junhee `cdf6a24`; health 교정 dev `7ba5d40`; junhee CI `30875926545` PASS; R2 branch CI `30876089391` PASS; 최종 dev `7ca7755`; dev CI `30876201074` PASS
```

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

### R2-W4-F1

```text
STATUS=BLOCKED
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W4-F1
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-09~11 serving.analytics DataHub·lineage·adapter 계약 정합
CURRENT_TASK_CARD_ID=R2-09
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=90669192e5940f8f66b132e585937a24076fb6b6
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W4-F1@9066919
I0_DECISION_VERSION=I0-v1.0.0
CONTRACT_VERSION=I4-DATA-v1.0.0-DRAFT
SCHEMA_VERSION=1.0.0
SEED_VERSION=20260729
ALLOWED_PATHS=infrastructure/database/datahub/**; src/data/**; tests/data/**; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/ai/**; app/enterprise-react/**; root Compose·env·CI; 기존 source DDL·seed 변경
HANDOFF_MANIFEST=handoffs/R2-W4-F1.json
ACCEPTANCE_CRITERIA=제품 Context 공급 방식은 `LIVE_DATAHUB`로 고정한다. 학습 JSONL이 사용하는 `serving.analytics` 8개 View를 Trino DataHub recipe의 명시적 allowlist로 고정하고 각 View의 Trino URN·FQN·column·synthetic·schema/seed version·원천 lineage를 versioned contract로 제공한다. versioned contract는 대체 Context 공급원이 아니라 live 수집 결과의 검증·fail-closed 기준으로만 사용한다. 학습 Context의 View·column 집합이 계약의 부분집합이며 미등록 View·column은 검증에서 차단된다. DataHub에서 8개 View URN·column·lineage를 조회한 trace와 application read-only 계정의 SELECT 허용·DDL·DML 거부 trace를 제출하되 backend·학습데이터를 변경하지 않는다.
ACCEPTANCE_IDS=AC1_RECIPE;AC2_VIEW_ALLOWLIST;AC3_COLUMNS;AC4_LINEAGE;AC5_SYNTHETIC_VERSION;AC6_TRAINING_SUBSET;AC7_DATAHUB_TRACE;AC8_READ_ONLY_TRACE;AC9_CONSUMER_HANDOFF
TEST_COMMANDS=python -m unittest discover -s tests/data -p "test_*.py"; python -m compileall -q src/data; docker compose -f compose.yml --env-file .env.example --profile full config --quiet; git diff --check
TEST_COMMAND_IDS=T1_DATA;T2_COMPILE;T3_COMPOSE_CONFIG;T4_DIFF
STOP_CONDITIONS=View 실제 column과 학습 Context 불일치; DataHub Trino source가 memory catalog View를 수집하지 못함; backend·AI·root 경로 변경 필요; 실제 고객 데이터·secret 필요; 필수 검증 또는 live trace 실패
HANDOFF=R4에 `LIVE_DATAHUB` View URN/FQN/column·lineage·어댑터 오류 계약, R1에 recipe 재현·DataHub 조회·read-only 실행 trace 전달
EXTERNAL_ACTION_PERMISSION=로컬 정적 검증·현재 실행 중인 기존 DataHub·Trino container에 대한 read-only 조회·기존 설치 dependency 사용·R2 허용 경로 commit·seung push. dependency 설치·image pull·container 신규 생성·volume 삭제·외부 데이터 전송·비용·secret·dev 병합 불가
AUTO_FAIL_CONDITIONS=허용 경로 침범; 학습 Context 자산·컬럼 누락; lineage·version·synthetic 필드 누락; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R2 환경에서 기존 container가 실행 중이지 않아 live trace를 만들 수 없을 때만 Not Run으로 전달하고, R1이 dev 통합 전에 기존 통합 환경에서 같은 trace를 실행한다. 실제 DataHub 조회·read-only trace가 없으면 Gate 0은 PASS로 전환하지 않는다.
```

차단 근거: `datahub_ingestion`의 원천 테이블 SELECT는 성공했지만 `serving.analytics` View SELECT가 `View owner does not have sufficient privileges`로 실패했다. Trino file access control에서 View 소유자 `hotel_synthetic_setup`에 원천 `SELECT`만 있고 `GRANT_SELECT`가 없어 다른 조회 전용 사용자의 View 실행이 차단됐다. 기존 허용 경로 밖의 Trino access rule 한 파일이 필요하므로 아래 보완 묶음으로 대체한다.

### R2-W4-F1A

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W4-F1A
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=없음
TASK_CARD_RANGE=R2-09~11 serving.analytics DataHub·lineage·adapter·read-only 권한 계약 정합
CURRENT_TASK_CARD_ID=R2-09
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=90669192e5940f8f66b132e585937a24076fb6b6
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W4-F1A@9066919
I0_DECISION_VERSION=I0-v1.0.0
CONTRACT_VERSION=I4-DATA-v1.0.0-DRAFT
SCHEMA_VERSION=1.0.0
SEED_VERSION=20260729
ALLOWED_PATHS=infrastructure/database/datahub/**; infrastructure/database/trino/etc/access-control-rules.json; src/data/**; tests/data/**; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/ai/**; app/enterprise-react/**; root Compose·env·CI; 기존 source DDL·seed 변경
HANDOFF_MANIFEST=handoffs/R2-W4-F1A.json
ACCEPTANCE_CRITERIA=R2-W4-F1의 전체 조건을 유지한다. 추가로 View 소유자 `hotel_synthetic_setup`에만 serving·원천 table의 `GRANT_SELECT`를 부여해 다른 조회 전용 사용자가 `serving.analytics` View를 실행할 수 있게 하되, 일반 사용자와 `datahub_ingestion`의 권한은 SELECT 전용으로 유지한다. 학습 JSONL이 사용하는 8개 View를 명시적 allowlist로 수집하고 URN·FQN·column·synthetic·schema/seed version·원천 lineage를 versioned validation contract로 제공한다. application read-only SELECT 성공과 DDL·DML 거부, DataHub 8개 View 조회 trace를 제출한다.
ACCEPTANCE_IDS=AC1_OWNER_GRANT_SELECT;AC2_RUNTIME_READ_ONLY;AC3_RECIPE;AC4_VIEW_ALLOWLIST;AC5_COLUMNS;AC6_LINEAGE;AC7_SYNTHETIC_VERSION;AC8_TRAINING_SUBSET;AC9_DATAHUB_TRACE;AC10_READ_ONLY_TRACE;AC11_CONSUMER_HANDOFF
TEST_COMMANDS=python -m unittest discover -s tests/data -p "test_*.py"; python -m compileall -q src/data; docker compose -f compose.yml --env-file .env.example --profile full config --quiet; git diff --check
TEST_COMMAND_IDS=T1_DATA;T2_COMPILE;T3_COMPOSE_CONFIG;T4_DIFF
STOP_CONDITIONS=일반 사용자 또는 `datahub_ingestion`에 `GRANT_SELECT`·write 권한이 생김; View 실제 column과 학습 Context 불일치; DataHub Trino source가 memory catalog View를 수집하지 못함; backend·AI·root 경로 변경 필요; 실제 고객 데이터·secret 필요; 필수 검증 또는 live trace 실패
HANDOFF=R4에 `LIVE_DATAHUB` View URN/FQN/column·lineage·어댑터 오류 계약, R1에 View 권한·recipe 재현·DataHub 조회·read-only 실행 trace 전달
EXTERNAL_ACTION_PERMISSION=로컬 정적 검증·현재 실행 중인 기존 Trino container에 대한 access rule 재적용을 위한 해당 container 재시작·기존 DataHub container의 read-only 조회·기존 설치 dependency 사용·R2 허용 경로 commit·seung push. dependency 설치·image pull·container 신규 생성·volume 삭제·외부 데이터 전송·비용·secret·dev 병합 불가
AUTO_FAIL_CONDITIONS=허용 경로 침범; 일반 사용자 권한 상승; 학습 Context 자산·컬럼 누락; lineage·version·synthetic 필드 누락; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=현재 DataHub container가 실행 중이지 않거나 승인 버전 image가 없어 live DataHub trace를 만들 수 없을 때만 Not Run으로 전달하고, R1이 dev 통합 전에 승인된 통합 환경에서 같은 trace를 실행한다. 실제 DataHub 조회 trace가 없으면 Gate 0은 PASS로 전환하지 않는다.
RESULT=task 전용 DataHub v1.6.0에 recipe를 실제 실행해 93 records를 적재했고, 계약과 live 결과가 8개 View·116개 column·17개 upstream edge·90개 column lineage에서 일치했다. View 소유자만 `GRANT_SELECT`를 갖고 application·ingestion 사용자는 read-only를 유지했으며 task 전용 자원은 제거했다.
EVIDENCE=seung `fefec52`; data test 27건 PASS; canonical SHA-256 `b4e6774e2cd5c5655487d44b0d288d1216cb746fe8afab0388d09f9120388b02`; branch CI `30876089391` PASS; dev `7ca7755`; dev CI `30876201074` PASS
```

### R4-W4-F1A

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W4-F1A
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Gate 0 Context consumer
TASK_CARD_RANGE=R4-06~11 LIVE_DATAHUB Context·G2 정합
CURRENT_TASK_CARD_ID=R4-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=7ca7755378c51501c824c6d2fe35afc7ba76fbbd
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W4-F1A@7ca7755
I0_DECISION_VERSION=I0-v1.0.0
CONTRACT_VERSION=I4-DATA-v1.0.0-DRAFT; OPENAPI-v1.0.0
ALLOWED_PATHS=app/backend/app/adapters/i2_data_platform.py; app/backend/app/api/router.py; app/backend/compose.fragment.yml; tests/backend/test_i2_data_platform.py; tests/backend/test_context_builder.py; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=infrastructure/database/**; src/data/**; src/ai/**; src/modelops/**; app/enterprise-react/**; root Compose·env·CI; migration·OpenAPI·secret
HANDOFF_MANIFEST=handoffs/R4-W4-F1A.json
ACCEPTANCE_CRITERIA=제품 Context 공급은 `LIVE_DATAHUB`로 고정하고 `src/data/serving_analytics_contract.i4.v1.json`은 live 결과 검증·fail-closed 기준으로만 읽는다. backend는 DataHub에서 계약에 등록된 `serving.analytics` View의 URN·FQN·column을 조회하고, 질문과 entitlement에 맞는 후보만 Context Package에 포함한다. 기획서의 최대 8 dataset·60 column 상한은 유지하며 권한 없는 View, 계약 밖 URN/FQN/column, DataHub 조회 실패는 Context에 포함하지 않거나 안전 실패한다. Node 2의 Context 내부 `serving.analytics.*` FQN은 G2가 허용하고 외부 FQN은 차단하는 contract test를 추가한다. 기존 raw 5개 asset을 real mode의 성공 fallback으로 사용하지 않는다.
ACCEPTANCE_IDS=AC1_LIVE_DATAHUB;AC2_CONTRACT_VALIDATION;AC3_ENTITLEMENT_FILTER;AC4_CONTEXT_LIMIT;AC5_SERVING_FQN_G2_ALLOW;AC6_EXTERNAL_FQN_G2_BLOCK;AC7_FAIL_CLOSED;AC8_REGRESSION
TEST_COMMANDS=python -m pytest tests/backend/test_i2_data_platform.py tests/backend/test_context_builder.py -q; python -m compileall -q app/backend/app; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_BACKEND;T2_COMPILE;T3_SCOPE;T4_DIFF
STOP_CONDITIONS=60-column 상한을 지키지 못함; DataHub live 결과를 versioned contract로 대체함; entitlement 이전에 자산 노출; R4 허용 경로 밖 변경 필요; 필수 검증 실패
HANDOFF=R3에 실제 제품 Context의 승인 View URN/FQN/column과 Node 2 입력 계약, R1에 live DataHub 오류·권한·G2 contract trace 전달
EXTERNAL_ACTION_PERMISSION=사용자의 작업 계속·commit·push·dev 통합 승인에 따라 위 허용 경로의 local 검증·commit·jaehong push·dev 병합을 승인한다. dependency 설치·비용·RunPod·외부 데이터 전송·secret·다른 Docker project 변경은 불가하다.
AUTO_FAIL_CONDITIONS=허용 경로 침범; raw asset 성공 fallback; 계약 밖 View·column 포함; 권한 우회; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=live DataHub container가 없으면 HTTP는 mock contract test로 검증하고 실제 통합 trace는 Not Run으로 명시한다. R4 결과가 dev에 통합되고 실제 제품 Context·Node 2·G2 trace가 확인되기 전에는 Gate 0을 PASS로 전환하거나 새 모델 평가를 시작하지 않는다.
RESULT=DataHub v1.6.0 GraphQL exact URN 조회로 질문에 맞는 hotel_daily_metrics 1개·15개 column을 제품 Context에 포함했다. hotel_analyst 외 역할은 live 조회 전에 제외하고, 계약 불일치·DataHub 실패를 안전 실패로 처리했으며 Context 내부 FQN만 G2가 허용했다.
EVIDENCE=jaehong code `f1211e3`·handoff `e6b5e8b`; targeted 17건 PASS; branch CI `30876986451` PASS; dev `db6d42f`; dev CI `30877055428` PASS; task DataHub 93 records·G2 내부 허용/외부 차단·task 자원 제거
```

### R2-W4-F2

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W4-F2
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=혼합 Context 생산자 계약
TASK_CARD_RANGE=R2-10~14 승인 raw asset·JOIN 정합
CURRENT_TASK_CARD_ID=R2-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=46c0c750c464bcbed0a711d1f2c207c5bfcc9d5b
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W4-F2@46c0c75
CONTRACT_VERSION=I4-CONTEXT-v2.0.0-DRAFT
ALLOWED_PATHS=src/data/**; tests/data/**; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/ai/**; infrastructure/database DDL·seed·recipe 변경; frontend/**; root Compose·env·CI; secret
HANDOFF_MANIFEST=handoffs/R2-W4-F2.json
ACCEPTANCE_CRITERIA=`serving.analytics` 8개 View를 우선 유지하고 View에 없는 CRM 단독 질의의 `crm_members`, `crm_member_grade_history`, `crm_point_transactions` 및 승인 JOIN `pms_stay_to_crm_membership_grade_event_time_v1`에 필요한 PMS·CRM raw 5개 asset만 versioned 계약에 명시한다. 기존 source registry와 DataHub recipe를 재사용해 각 URN·FQN·허용 column·용도·JOIN ID를 고정하고, 계약 밖 raw asset·column·JOIN을 거부하는 data test를 추가한다. 신규 View·DDL·seed·recipe는 만들지 않는다.
ACCEPTANCE_IDS=AC1_VIEW_PRIORITY;AC2_RAW_ALLOWLIST;AC3_JOIN_ID;AC4_URN_FQN_COLUMNS;AC5_DENY_OUTSIDE
TEST_COMMANDS=python -m pytest tests/data -q; python -m compileall -q src/data; git diff --check
TEST_COMMAND_IDS=T1_DATA;T2_COMPILE;T3_DIFF
STOP_CONDITIONS=기존 metadata로 정확한 URN·column을 고정할 수 없음; 승인 JOIN 밖 raw 사용 필요; 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R4에 I4-CONTEXT-v2 계약과 질문별 허용 asset 용도 전달
EXTERNAL_ACTION_PERMISSION=사용자의 모든 역할 잔여 작업·commit·push·dev 통합 승인에 따라 허용 경로 commit·seung push를 승인한다. cloud 비용·DB 변경·신규 dependency 설치는 불가하다.
AUTO_FAIL_CONDITIONS=raw 전체 schema 노출; 임의 cross-catalog JOIN; recipe·DDL 변경; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R2 제품·handoff·branch CI 수용 뒤 R4-W4-F2를 READY로 발행한다.
```

### R4-W4-F2

```text
STATUS=BLOCKED
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W4-F2
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=혼합 Context 소비자 계약
TASK_CARD_RANGE=R4-06~11 View·제한 raw Context·G2 정합
CURRENT_TASK_CARD_ID=R4-06
BASE_BRANCH=dev
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_SHA=115232ec0f7282500315cad15530caa980cc7131
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W4-F2@115232e
CONTRACT_VERSION=I4-CONTEXT-v2.0.0
ALLOWED_PATHS=app/backend/**; tests/backend/**; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/data/**; src/ai/**; infrastructure/database/**; frontend/**; root Compose·env·CI; secret
HANDOFF_MANIFEST=handoffs/R4-W4-F2.json
ACCEPTANCE_CRITERIA=R2의 I4-CONTEXT-v2 계약을 live DataHub에서 exact-match 검증하고 질문별 View 우선, CRM 단독 raw, 승인 PMS–CRM JOIN만 Context에 포함한다. 최대 8 dataset·60 column, entitlement, G2 fail-closed는 유지한다.
ACCEPTANCE_IDS=AC1_CONTRACT_LOAD;AC2_VIEW_DEFAULT;AC3_CRM_RAW;AC4_APPROVED_JOIN;AC5_LIVE_EXACT;AC6_ENTITLEMENT;AC7_G2_DENY
TEST_COMMANDS=python -m pytest tests/backend -q; python -m compileall -q app/backend; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_BACKEND;T2_COMPILE;T3_SCOPE;T4_DIFF
STOP_CONDITIONS=계약 밖 raw fallback 필요; live DataHub exact-match 실패; 8 dataset·60 column 상한 초과; 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R3에 질문 유형별 실제 Context와 G2 허용·차단 trace 전달
EXTERNAL_ACTION_PERMISSION=사용자의 모든 역할 잔여 작업·commit·push·dev 통합 승인에 따라 허용 경로 commit·jaehong push를 승인한다. cloud 비용·DB 변경·신규 dependency 설치는 불가하다.
AUTO_FAIL_CONDITIONS=질문과 무관한 raw asset 노출; 계약 밖 URN/FQN/column 허용; 권한 우회; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=제품·handoff·branch CI 수용 뒤 dev 병합하고 Validation v2·R3 Base 평가를 재발행한다.
```

차단 근거: 실제 DataHub v1.6 raw dataset URN은 `crm.crm_db.dbo.*`, `pms.pms_db.public.*`처럼 platform instance와 database를 포함하지만 R2 계약은 축약 URN을 사용했다. R4 exact-match가 이를 거부했으므로 아래 생산자 교정부터 수행한다.

### R2-W4-F2A

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W4-F2A
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=raw URN exact-match
TASK_CARD_RANGE=R2-10 DataHub URN 교정
CURRENT_TASK_CARD_ID=R2-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=2f573d91b0a2ddc4dc60db690bf43b46cbe07fef
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R2-W4-F2A@2f573d9
CONTRACT_VERSION=I4-CONTEXT-v2.0.1-DRAFT
ALLOWED_PATHS=src/data/analytics_context_contract.i4.v2.json; tests/data/test_analytics_context_contract.py; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=그 외 전체 경로; secret
HANDOFF_MANIFEST=handoffs/R2-W4-F2A.json
ACCEPTANCE_CRITERIA=raw 7개 DataHub URN만 실제 v1.6 수집 결과의 platform instance·database 포함 값으로 교정한다. Trino FQN·column·용도·JOIN·View 계약은 변경하지 않고 test가 축약 URN 회귀를 차단한다.
ACCEPTANCE_IDS=AC1_LIVE_URN;AC2_FQN_STABLE;AC3_COLUMNS_STABLE;AC4_REGRESSION
TEST_COMMANDS=python -m pytest tests/data -q; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_DATA;T2_SCOPE;T3_DIFF
STOP_CONDITIONS=실제 URN 불명확; FQN·column·JOIN 변경 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=허용 경로 commit·seung push·task DataHub read-only 재검증을 승인한다. 다른 Docker 프로젝트·DB·cloud 비용 변경은 불가하다.
AUTO_FAIL_CONDITIONS=축약 URN 잔존; FQN·column·JOIN 변경; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R2 통합 뒤 R4-W4-F2A를 READY로 발행한다.
```

### R4-W4-F2A

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W4-F2A
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=live raw Context 재검증
TASK_CARD_RANGE=R4-06~11 raw metadata exact-match·G2
CURRENT_TASK_CARD_ID=R4-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=40776daa7f9e5745bbdc4102bb2d625b013dd5d0
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W4-F2A@40776da
CONTRACT_VERSION=I4-CONTEXT-v2.0.1
ALLOWED_PATHS=app/backend/**; tests/backend/**; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=그 외 전체 경로; secret
HANDOFF_MANIFEST=handoffs/R4-W4-F2A.json
ACCEPTANCE_CRITERIA=View는 기존 URN·schema name·전체 column exact-match를 유지한다. raw는 교정된 URN을 exact-match하고 원본 database 기반 schema name을 확인하며, 계약 허용 column이 live schema의 부분집합일 때만 Context에 노출한다. live의 추가 column은 노출하지 않는다. 실제 CRM 단독·PMS–CRM 5개 asset·승인 JOIN ID·G2 허용/차단을 task DataHub에서 확인한다.
ACCEPTANCE_IDS=AC1_VIEW_EXACT;AC2_RAW_URN;AC3_RAW_NAME;AC4_COLUMN_SUBSET;AC5_NO_EXTRA_EXPOSURE;AC6_LIVE_CRM_JOIN;AC7_G2
TEST_COMMANDS=python -m pytest tests/backend -q; python -m compileall -q app/backend; live DataHub adapter trace; git diff --check
TEST_COMMAND_IDS=T1_BACKEND;T2_COMPILE;T3_LIVE;T4_DIFF
STOP_CONDITIONS=raw URN 불일치; 허용 column 누락; live 추가 column 노출; 승인 JOIN 우회; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=허용 경로 commit·jaehong push·task DataHub read-only 조회와 정확한 task 자원 cleanup을 승인한다. 다른 Docker·DB·cloud 비용 변경은 불가하다.
AUTO_FAIL_CONDITIONS=View 검증 완화; raw 전체 schema 노출; 권한·G2 우회; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=제품·branch CI·live trace 수용 뒤 dev 통합하고 R3 Validation v2를 재발행한다.
```

### R3-W4-F1

```text
STATUS=BLOCKED
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W4-F1
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Gate 0 PASS·Base smoke
TASK_CARD_RANGE=R3-10~14 Qwen3-4B-Instruct-2507 Base 전환·Validation
CURRENT_TASK_CARD_ID=R3-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=db6d42fb7237580cc9e411e411794df4c92e7ed9
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W4-F1@db6d42f
I0_DECISION_VERSION=I0-v1.0.0
CONTRACT_VERSION=MODEL-v1.0.0-compatible; PROMPT-v1.0.6/PROMPT-v1.0.2; I4-DATA-v1.0.0-DRAFT
MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
MODEL_REVISION=cdbee75f17c01a7cc42f958dc650907174af0554
ALLOWED_PATHS=src/ai/training/**; src/modelops/**; evals/**; tests/ai/**; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; infrastructure/database/**; frontend/**; root Compose·env·CI; 기존 Qwen3-4B 실험 증거 덮어쓰기; secret
HANDOFF_MANIFEST=handoffs/R3-W4-F1.json
ACCEPTANCE_CRITERIA=제품 후보를 공식 `Qwen/Qwen3-4B-Instruct-2507` non-thinking checkpoint와 고정 revision으로 전환하고 이전 adapter를 재사용하지 않는다. checkpoint·runner 기본값·비용 manifest까지만 선행하며, 기존 Validation 150건은 제품 Context 밖 raw FQN과 의미 구조 누수가 있어 실행하지 않는다. R2·R4 혼합 Context 계약 통합과 Validation-ID 75·OOD 75 재생성·검증 전 RunPod 실행을 차단한다.
ACCEPTANCE_IDS=AC1_OFFICIAL_MODEL;AC2_PINNED_REVISION;AC3_NO_OLD_ADAPTER;AC4_BASE_SMOKE;AC5_CONTEXT_REFERENCE;AC6_VALIDATION_150;AC7_LATENCY_VRAM;AC8_COST_CLEANUP;AC9_LORA_DECISION
TEST_COMMANDS=python -m pytest tests/ai -q; python -m compileall -q src/ai src/modelops; model endpoint smoke·Validation runner; git diff --check
TEST_COMMAND_IDS=T1_AI;T2_COMPILE;T3_MODEL_EVAL;T4_DIFF
STOP_CONDITIONS=혼합 Context 계약 미통합; Validation-ID/OOD 미확정; smoke schema·Context·G2 실패; revision 불일치; 이전 adapter 로드; 누적 RunPod 비용 USD 15 초과 예상; 신규 비용 USD 0.50 도달; 실제 고객 데이터·secret 로그; 허용 경로 밖 변경 필요
HANDOFF=R4에 새 model ID·revision·endpoint schema·latency, R1에 Validation·비용·cleanup·LoRA 필요성 판정 전달
EXTERNAL_ACTION_PERMISSION=사용자가 지정한 model로 작업 계속을 승인했다. 기존 RunPod API key를 로그에 출력하지 않고 task 전용 Pod 1개·model download·최대 신규 USD 0.50·누적 USD 15 이내 Base smoke와 Validation 150건, task 자원 삭제, 허용 경로 commit·daesung push를 승인한다. LoRA 학습·Blind Gold·다른 cloud resource·외부 데이터 전송·dev 병합은 별도 R1 판정 전 불가하다.
AUTO_FAIL_CONDITIONS=다른 checkpoint·main revision·old adapter 사용; Validation split 변경·누수; 비용 상한 초과; task Pod 미삭제; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=Base Validation 결과가 기존 제품 Gate에 미달하면 LoRA 또는 다른 model을 자동 실행하지 않고 정확도·속도·비용 근거와 함께 재승인을 요청한다.
```

### R3-W4-F2

```text
STATUS=BLOCKED
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W4-F2
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Validation v2 lock·Base smoke
TASK_CARD_RANGE=R3-10~14 Validation-ID/OOD·Instruct-2507 Base
CURRENT_TASK_CARD_ID=R3-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=23d27ac0434265ca5679a1ce1929bb462a113e85
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W4-F2@23d27ac
MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
MODEL_REVISION=cdbee75f17c01a7cc42f958dc650907174af0554
CONTRACT_VERSION=I4-CONTEXT-v2.0.1; MODEL-CANDIDATE-v0.1
ALLOWED_PATHS=src/ai/training/**; src/modelops/**; evals/**; tests/ai/**; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; infrastructure/database/**; frontend/**; root Compose·env·CI; secret; 기존 Gold·Acceptance·실험 증거 덮어쓰기
HANDOFF_MANIFEST=handoffs/R3-W4-F2.json
ACCEPTANCE_CRITERIA=2,000건 원장의 train 1,200건을 기준으로 `domain, metric, aggregation, dimension, filter, output, period, node` semantic signature를 고정한다. 기존 Gold 120·Acceptance 30을 제외한 validation·reserve에서 Train signature와 겹치는 ID 75, 겹치지 않는 OOD 75를 도메인 quota로 결정론적 선별하고 manifest SHA-256을 잠근다. 새 150건의 Context FQN은 I4-CONTEXT-v2.0.1 내부만 허용하고 중복·누수·G2·Trino 검증을 통과해야 한다. 이후 Instruct-2507 Base 20건 smoke 성공 시에만 동일 endpoint로 150건을 평가한다. LoRA·Blind Gold는 실행하지 않는다.
ACCEPTANCE_IDS=AC1_SIGNATURE;AC2_ID75;AC3_OOD75;AC4_NO_GOLD;AC5_CONTEXT;AC6_G2_TRINO;AC7_HASH_LOCK;AC8_BASE_SMOKE;AC9_VALIDATION150;AC10_COST_CLEANUP
TEST_COMMANDS=python -m pytest tests/ai -q; python -m compileall -q src/ai src/modelops; Validation v2 build·audit·Trino; Instruct-2507 endpoint smoke·evaluation; git diff --check
TEST_COMMAND_IDS=T1_AI;T2_COMPILE;T3_VALIDATION;T4_MODEL;T5_DIFF
STOP_CONDITIONS=ID/OOD 수량 부족; Gold·Acceptance 포함; Context 밖 FQN; G2·Trino 실패; revision 불일치; 이전 adapter 로드; 신규 USD 0.50 또는 누적 USD 15 도달; secret 로그; task Pod 미삭제; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=task RunPod Pod 1개·model download·최대 신규 USD 0.50·누적 USD 15 이내 Base smoke와 Validation 150, task 자원 삭제, 허용 경로 commit·daesung push를 승인한다. LoRA·Blind Gold·다른 cloud resource는 불가하다.
AUTO_FAIL_CONDITIONS=기존 Validation 재사용; signature·split 변경 후 hash 미갱신; old adapter·다른 model; 비용 상한 초과; 필수 검증 FAIL
RESULT=Validation-ID 75·OOD 75 Context·G2·Trino 검증은 PASS했다. Instruct-2507 Base smoke 20건은 JSON 12, G2 4, 합성 Trino 4, 정답 SQL 4건만 PASS했고 MODEL_SCHEMA_INVALID 8·RESOURCE_POLICY_MISSING 8로 분류했다. 150건 전체 평가·LoRA·Blind Gold는 Not Run, task Pod는 삭제 확인, 신규 비용은 USD 0.132 추정, R3 commit 847ebc6·branch CI 30880359294는 PASS했다.
R1_REVIEW_CONDITIONS=Base 결과가 Gate에 미달해 STOP했다. prompt/schema 보정 후 Base 재평가, 조건부 LoRA 또는 다른 model 중 다음 경로와 추가 비용을 R1이 새 실행 묶음으로 승인해야 한다.
```

### R1-W4-F2

```text
STATUS=IN_PROGRESS
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F2
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Gate 0 PASS
TASK_CARD_RANGE=R1-11 model checkpoint·평가 비용 판정
CURRENT_TASK_CARD_ID=R1-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=db6d42fb7237580cc9e411e411794df4c92e7ed9
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W4-F2@db6d42f
ALLOWED_PATHS=docs/markdown/02_WBS.md; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/daily_reports/junhee/일일보고.md; tests/integration/test_gate_scope.py
FORBIDDEN_PATHS=R2~R5 제품 경로; root Compose·env·CI; secret
ACCEPTANCE_CRITERIA=R4 Gate 0 소비자 결과를 dev·CI로 확정하고 사용자가 지정한 Qwen3-4B-Instruct-2507의 공식 checkpoint·revision·Base 우선 평가·비용·cleanup·중단 조건을 R3 실행 묶음에 고정한다. 이전 Qwen3-4B 실험 증거는 덮어쓰지 않는다.
ACCEPTANCE_IDS=AC1_GATE0;AC2_MODEL_ID;AC3_REVISION;AC4_BASE_FIRST;AC5_COST;AC6_R3_BUNDLE
TEST_COMMANDS=python -m unittest tests.integration.test_gate_scope; document/WBS/report validation; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_GATE;T2_DOCS;T3_SCOPE;T4_DIFF
STOP_CONDITIONS=공식 model 정보 불일치; 비용 상한 누락; R1 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R3에 model ID·revision·Base smoke·Validation·비용 상한 전달
EXTERNAL_ACTION_PERMISSION=사용자의 작업 계속·commit·push·dev 통합 승인에 따라 허용 경로 commit·junhee push·dev 병합을 승인한다. 실제 RunPod 비용은 R3-W4-F1 조건만 허용한다.
AUTO_FAIL_CONDITIONS=허용 경로 침범; model·revision·비용 조건 누락; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R3 Base 결과가 Gate 미달이면 LoRA 또는 다른 model을 자동 승인하지 않는다.
```

### R1-W4-F3

```text
STATUS=IN_PROGRESS
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F3
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Base smoke 재작업 승인
TASK_CARD_RANGE=R1-11 model 실패 분류·재평가 판정
CURRENT_TASK_CARD_ID=R1-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=d7d7acc886d3c3d3765311c4ef20e8fab28488d5
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W4-F3@d7d7acc
ALLOWED_PATHS=docs/markdown/02_WBS.md; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/daily_reports/junhee/일일보고.md; tests/integration/test_gate_scope.py
FORBIDDEN_PATHS=R2~R5 제품 경로; root Compose·env·CI; secret
ACCEPTANCE_CRITERIA=R3-W4-F2의 20건을 domain·node별로 재분류하고 편향된 선두 20건 선택, JSON 미완성, 1000행 초과를 서로 다른 원인으로 기록한다. G2의 1000행 상한을 낮추거나 우회하지 않고 6개 도메인·두 node의 결정론적 smoke, 합성 Trino 결과 동등성, 동일 model·revision, 잔여 비용·cleanup 조건을 R3 재작업 묶음에 고정한다.
ACCEPTANCE_IDS=AC1_FAILURE_CLASS;AC2_STRATIFIED_SMOKE;AC3_G2_UNCHANGED;AC4_RESULT_EQUIVALENCE;AC5_MODEL_REVISION;AC6_COST_CLEANUP;AC7_R3_REWORK
TEST_COMMANDS=python -m unittest tests.integration.test_gate_scope; document/WBS/report validation; python .github/scripts/gate_scope.py --dashboard --next-gate I4; git diff --check
TEST_COMMAND_IDS=T1_GATE;T2_DOCS;T3_DASHBOARD;T4_DIFF
STOP_CONDITIONS=G2 완화; checkpoint·revision 변경; 비용 상한 누락; R1 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R3에 편향 제거·SQL-only JSON·1000행 상한·결과 동등성·비용 잔액 전달
EXTERNAL_ACTION_PERMISSION=사용자의 지속 작업·승인·commit·push·dev 통합 요청과 기존 누적 USD 15 상한 안에서 R3 smoke 재평가만 신규 USD 0.35까지 승인한다.
AUTO_FAIL_CONDITIONS=G2 우회; 20건 hardcode; 다른 model·revision; LoRA·150건·Blind Gold 실행; task Pod 미삭제; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R3 smoke가 전부 통과해야 150건 전체 평가를 별도 발행한다. 미달이면 비용·오류를 기록하고 다시 STOP한다.
```

### R3-W4-F3

```text
STATUS=BLOCKED
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W4-F3
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Base smoke 재작업
TASK_CARD_RANGE=R3-10~14 prompt·평가 harness·Instruct-2507 Base
CURRENT_TASK_CARD_ID=R3-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=d7d7acc886d3c3d3765311c4ef20e8fab28488d5
START_POINT=origin/daesung 847ebc6ee54d644b0434d95e5b4248539f9485cb; origin/dev를 merge해 최신 계약을 반영한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R3-W4-F3@d7d7acc
MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
MODEL_REVISION=cdbee75f17c01a7cc42f958dc650907174af0554
CONTRACT_VERSION=I4-CONTEXT-v2.0.1; MODEL-CANDIDATE-v0.1
ALLOWED_PATHS=src/ai/**; src/modelops/**; evals/**; tests/ai/**; handoffs/R3-W4-F3.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; infrastructure/database/**; frontend/**; root Compose·env·CI; secret; G2 상한 완화; 기존 Gold·Acceptance·실험 증거 덮어쓰기
HANDOFF_MANIFEST=handoffs/R3-W4-F3.json
ACCEPTANCE_CRITERIA=기존 20건 실패를 `MODEL_SCHEMA_INVALID` 8건·`RESOURCE_POLICY_MISSING` 8건·PASS 4건과 domain·node 편향으로 재현한다. case ID나 정답 SQL을 prompt·후처리에 hardcode하지 않고 SQL-only guided JSON과 512 token 상한을 제품 transport와 동일하게 유지한다. Validation v2에서 pms·crm·pms_crm·pos·facility·banquet 6개 domain과 node2·node2_repair를 모두 포함하는 결정론적 smoke 20건을 선별하고 case manifest SHA-256을 고정한다. prompt는 1~1000 정수 LIMIT과 승인 Context·metric·filter·기간 규칙을 분명히 하며 G2를 변경하지 않는다. 동일 checkpoint·revision의 새 endpoint에서 valid JSON 20/20, G2 20/20, 합성 Trino 20/20을 충족하고, 정답 SQL과 문자열이 달라도 양쪽 Trino 결과를 정규화해 result match를 기록한다. 통과해도 150건·LoRA·Blind Gold는 실행하지 않고 endpoint를 삭제한 뒤 R1 판정을 요청한다.
ACCEPTANCE_IDS=AC1_REPRODUCE;AC2_NO_HARDCODE;AC3_STRATIFIED20;AC4_PROMPT_POLICY;AC5_JSON20;AC6_G2_20;AC7_TRINO20;AC8_RESULT_MATCH;AC9_MODEL_REVISION;AC10_COST_CLEANUP
TEST_COMMANDS=python -m pytest tests/ai -q; python -m compileall -q src/ai src/modelops; smoke manifest 재생성 동일 SHA; 기존 실패 20건 offline 분류; Instruct-2507 endpoint smoke 20; git diff --check
TEST_COMMAND_IDS=T1_AI;T2_COMPILE;T3_MANIFEST;T4_REPRO;T5_MODEL;T6_DIFF
STOP_CONDITIONS=6개 domain 또는 두 node 누락; case·정답 hardcode; G2 1000행 상한 완화; valid JSON·G2·Trino 중 1건이라도 실패; revision 불일치; 이전 adapter 로드; 신규 USD 0.35 또는 누적 USD 15 도달; secret 로그; task Pod 미삭제; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=task RunPod Pod 1개·고정 model download·smoke 20건만 신규 USD 0.35·누적 USD 15 이내에서 승인한다. prompt·평가 harness·manifest 수정, 허용 경로 commit·daesung push와 task 자원 삭제를 승인한다. 150건 전체 평가·LoRA·Blind Gold·다른 model·다른 cloud resource·dev 병합은 불가하다.
AUTO_FAIL_CONDITIONS=선두 20건 재사용; hardcode; G2 우회; 다른 model·revision; 비용 상한 초과; 150건·LoRA·Blind Gold 실행; task Pod 미삭제; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=branch CI와 smoke 20건의 JSON·G2·Trino·result match·비용·cleanup 증거를 제출한다. 전부 통과해도 R1의 별도 150건 발행 전에는 대기한다.
```

### R1-W4-F4

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F4
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Base SQL 타입 재검증 승인
TASK_CARD_RANGE=R1-11 model 타입·범위 규칙 판정
CURRENT_TASK_CARD_ID=R1-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=c67612f93e50b8db8acea1b556b7627c86bd05e4
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R1-W4-F4@c67612f
ALLOWED_PATHS=docs/markdown/02_WBS.md; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/daily_reports/junhee/일일보고.md; tests/integration/test_gate_scope.py
FORBIDDEN_PATHS=R2~R5 제품 경로; root Compose·env·CI; secret
ACCEPTANCE_CRITERIA=R3-W4-F3의 균형 표본 첫 건이 JSON·G2를 통과했으나 `timestamp(3) <= varchar(7)`로 Trino 실패했고 정답 SQL은 같은 Trino에서 결과 hash까지 일치했음을 기록한다. case별 정답을 넣지 않고 Context column type에 맞는 날짜 literal과 project-wide synthetic 범위만 prompt 일반 규칙으로 제한한다. F3의 USD 0.0423을 포함한 합계 USD 0.35 안에서 같은 manifest 20건을 한 번만 재검증하고 G2·model·revision·512 token·fail-fast·cleanup 조건을 유지한다.
ACCEPTANCE_IDS=AC1_F3_EVIDENCE;AC2_GENERAL_RULE;AC3_SAME_MANIFEST;AC4_G2_UNCHANGED;AC5_COST_REMAINDER;AC6_R3_REWORK
TEST_COMMANDS=document/WBS/report validation; python .github/scripts/gate_scope.py --dashboard --next-gate I4; git diff --check
TEST_COMMAND_IDS=T1_DOCS;T2_DASHBOARD;T3_DIFF
STOP_CONDITIONS=case별 SQL hardcode; G2 완화; 다른 model·revision; F3 증거 덮어쓰기; 합계 비용 상한 누락; R1 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R3에 동일 manifest·일반 날짜 타입·synthetic 범위·남은 비용 USD 0.3077 전달
EXTERNAL_ACTION_PERMISSION=기존 R3-W4-F3 승인 USD 0.35 중 사용한 USD 0.0423을 제외하고, 같은 smoke 목적의 task Pod 1개와 최대 신규 USD 0.30을 승인한다. F3+F4 합계는 USD 0.35를 넘지 않는다.
AUTO_FAIL_CONDITIONS=case별 hardcode; G2 우회; 다른 model·revision; 합계 USD 0.35 초과; 150건·LoRA·Blind Gold 실행; task Pod 미삭제; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R3 smoke 20건이 전부 통과해야 150건 전체 평가를 별도 발행한다. 미달이면 비용·오류를 기록하고 다시 STOP한다.
RESULT=R3-W4-F4는 첫 3건의 JSON·G2·합성 Trino·result match를 통과했으나 4번째 validation-0228에서 result match가 실패했다. F4 약 USD 0.0402·F3+F4 약 USD 0.0825, Pod 삭제·active 0, branch CI 30884334429 FAIL을 확인해 추가 cloud 실행을 금지하고 모델 전략 재판정으로 전환한다.
```

### R3-W4-F4

```text
STATUS=BLOCKED
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W4-F4
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Base SQL 타입 재검증
TASK_CARD_RANGE=R3-10~14 prompt 일반화·Instruct-2507 Base
CURRENT_TASK_CARD_ID=R3-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=c67612f93e50b8db8acea1b556b7627c86bd05e4
START_POINT=origin/daesung 9b53d43cf76ae2c59e9ca10ccbff4b690b8101df; 승인 문서가 통합된 origin/dev를 merge한 뒤 시작한다.
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=R3-W4-F4@c67612f
MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
MODEL_REVISION=cdbee75f17c01a7cc42f958dc650907174af0554
CONTRACT_VERSION=I4-CONTEXT-v2.0.1; MODEL-CANDIDATE-v0.1; PROMPT-v1.0.8
ALLOWED_PATHS=src/ai/**; src/modelops/**; evals/**; tests/ai/**; handoffs/R3-W4-F3.json; handoffs/R3-W4-F4.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; infrastructure/database/**; frontend/**; root Compose·env·CI; secret; G2 상한 완화; F3 실패 증거·기존 Gold·Acceptance·실험 증거 덮어쓰기
HANDOFF_MANIFEST=handoffs/R3-W4-F4.json
ACCEPTANCE_CRITERIA=R3-W4-F3의 동일 manifest SHA와 6개 domain·node2/node2_repair·ID/OOD 균형을 보존한다. 첫 실패 SQL과 정답 SQL을 local synthetic Trino에서 다시 재현하고, case ID·정답 SQL을 prompt·후처리에 hardcode하지 않은 채 날짜·timestamp column type에 맞는 DATE 또는 TIMESTAMP literal과 project-wide `SYNTHETIC_HOTEL_001`·ACTUAL·non-forecast 범위를 일반 prompt 규칙으로 고정한다. SQL-only guided JSON·512 token·G2 1000행 상한·동일 checkpoint/revision을 유지한다. 새 endpoint에서 같은 20건의 valid JSON·G2·합성 Trino·정답 결과 동등성을 모두 20/20으로 확인하며 첫 실패에서 즉시 중단한다. 성공해도 150건·LoRA·Blind Gold는 실행하지 않고 endpoint를 삭제한 뒤 R1 판정을 요청한다.
ACCEPTANCE_IDS=AC1_SAME_MANIFEST;AC2_REPRODUCE;AC3_NO_CASE_HARDCODE;AC4_TYPE_SCOPE_RULE;AC5_JSON20;AC6_G2_20;AC7_TRINO20;AC8_RESULT_MATCH20;AC9_MODEL_REVISION;AC10_COST_CLEANUP
TEST_COMMANDS=python -m pytest tests/ai -q; python -m compileall -q src/ai src/modelops; smoke manifest 재생성 동일 SHA; F3 generated·expected SQL local Trino 재현; Instruct-2507 endpoint smoke 20; git diff --check
TEST_COMMAND_IDS=T1_AI;T2_COMPILE;T3_MANIFEST;T4_REPRO;T5_MODEL;T6_DIFF
STOP_CONDITIONS=manifest 변경; 6개 domain 또는 두 node 누락; case·정답 SQL hardcode; G2 1000행 상한 완화; valid JSON·G2·Trino·result match 중 1건이라도 실패; revision 불일치; 이전 adapter 로드; F4 신규 USD 0.30 또는 F3+F4 합계 USD 0.35 도달; secret 로그; task Pod 미삭제; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=task RunPod Pod 1개·고정 model download·같은 smoke 20건만 신규 USD 0.30, F3+F4 합계 USD 0.35와 전체 누적 USD 15 이내에서 승인한다. 허용 경로 commit·daesung push와 task 자원 삭제를 승인한다. 150건 전체 평가·LoRA·Blind Gold·다른 model·다른 cloud resource·dev 병합은 불가하다.
RESULT=daesung 8c76f1e. 같은 manifest 첫 3건은 전 기준 PASS, 4번째 validation-0228은 JSON·G2·Trino PASS 뒤 result hash 불일치로 중단했다. 생성 SQL이 CRM 소멸 포인트의 property·txn_type·is_forecast·음수 합산 조건을 누락하고 기간을 확장했다. F4 약 USD 0.0402·F3+F4 약 USD 0.0825, Pod 삭제·active 0, CI 30884334429은 handoff FAIL을 정확히 반영해 의도대로 실패했다.
AUTO_FAIL_CONDITIONS=manifest 변경; case별 hardcode; G2 우회; 다른 model·revision; 비용 상한 초과; 150건·LoRA·Blind Gold 실행; task Pod 미삭제; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=branch CI와 smoke 20건의 JSON·G2·Trino·result match·비용·cleanup 증거를 제출한다. 전부 통과해도 R1의 별도 150건 발행 전에는 대기한다.
```

### R1-W4-F5

```text
STATUS=IN_PROGRESS
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F5
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=metric semantic contract
TASK_CARD_RANGE=R1-11 Context metric 필터 계약 판정
CURRENT_TASK_CARD_ID=R1-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=bc08100d5d38a729b4b37e715afa4f5f9674b200
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W4-F5@bc08100
ALLOWED_PATHS=docs/markdown/02_WBS.md; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/daily_reports/junhee/일일보고.md; tests/integration/test_gate_scope.py
FORBIDDEN_PATHS=R2~R5 제품 경로; root Compose·env·CI; secret
ACCEPTANCE_CRITERIA=F4 CRM 결과 불일치에서 지표 field·aggregation만으로는 txn_type 등 필수 의미 필터를 복원할 수 없는 계약 누락을 기록한다. R3가 metric required_filters를 구조화해 schema·prompt·Validation 생성기에 보존하는 local-only 작업을 발행하고, cloud 재실행과 R4 소비자 변경은 별도 판정으로 남긴다.
ACCEPTANCE_IDS=AC1_ROOT_CAUSE;AC2_STRUCTURED_FILTER;AC3_LOCAL_ONLY;AC4_R3_ISSUE
TEST_COMMANDS=document/WBS/report validation; python -m unittest tests.integration.test_gate_scope; python .github/scripts/gate_scope.py --dashboard --next-gate I4; git diff --check
TEST_COMMAND_IDS=T1_DOCS;T2_GATE;T3_DASHBOARD;T4_DIFF
STOP_CONDITIONS=case ID·정답 SQL hardcode; raw SQL filter 문자열을 model trust boundary에 그대로 허용; R4 경로 변경; 외부 비용·model 실행; R1 허용 경로 밖 변경; 필수 검증 실패
HANDOFF=R3에 구조화 metric filter schema·일반 prompt 소비·validation-0228 회귀를 local-only로 전달
EXTERNAL_ACTION_PERMISSION=없음. RunPod·model download·endpoint·외부 비용·150건·LoRA·Blind Gold를 금지한다.
```

### R3-W4-F5

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W4-F5
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=metric semantic contract
TASK_CARD_RANGE=R3-01·07·09~14 metric filter 계약 보완
CURRENT_TASK_CARD_ID=R3-01
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=bc08100d5d38a729b4b37e715afa4f5f9674b200
START_POINT=origin/daesung 8c76f1eb1ccc2510fd6bec74b3eec5f65b3e3e48; origin/dev를 merge해 최신 승인 문서를 반영한 뒤 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W4-F5@bc08100
CONTRACT_VERSION=MODEL-CANDIDATE-v0.1; PROMPT-v1.0.9-DRAFT; NODE-IO-v0.1-compatible
ALLOWED_PATHS=src/ai/**; src/modelops/**; evals/**; tests/ai/**; handoffs/R3-W4-F3.json; handoffs/R3-W4-F4.json; handoffs/R3-W4-F5.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; infrastructure/database/**; frontend/**; root Compose·env·CI; eval 결과·Gold·Acceptance 덮어쓰기; secret
HANDOFF_MANIFEST=handoffs/R3-W4-F5.json
ACCEPTANCE_CRITERIA=context metric에 optional required_filters를 field·operator·value 구조로 추가하고 허용 operator·value type을 schema로 제한한다. build_case_specs가 Source의 필수 predicate를 case나 정답 SQL hardcode 없이 이 구조로 보존하며 prompt는 이 필터를 정확히 적용하도록 일반 규칙을 추가한다. validation-0228의 txn_type=EXPIRE·is_forecast=false와 기존 분석 View의 ACTUAL·non-forecast가 생성 Context에 포함됨을 test로 확인한다. 기존 required field와 payload는 호환 유지하고 raw SQL predicate를 새 trust-boundary 입력으로 허용하지 않는다.
ACCEPTANCE_IDS=AC1_OPTIONAL_SCHEMA;AC2_OPERATOR_VALUE;AC3_SOURCE_FILTERS;AC4_PROMPT_RULE;AC5_CRM_REGRESSION;AC6_VIEW_REGRESSION;AC7_COMPATIBILITY;AC8_LOCAL_ONLY
TEST_COMMANDS=python -m pytest tests/ai -q; python -m compileall -q src/ai; validation-0228 local context build 확인; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_AI;T2_COMPILE;T3_CONTEXT;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=case ID·정답 SQL hardcode; unrestricted SQL filter string 추가; 기존 payload 비호환; 허용 경로 밖 변경; RunPod·model download·endpoint·외부 비용; 150건·LoRA·Blind Gold; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local code·test·허용 경로 commit·daesung push만 승인한다.
AUTO_FAIL_CONDITIONS=unrestricted predicate; hardcode; 외부 실행·비용; 기존 schema 비호환; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=구조화 필터 schema·생성 Context·prompt·AI test·branch CI를 제출한다. 통과해도 R4 소비자나 cloud smoke는 별도 발행 전까지 대기한다.
RESULT_SHA=96d3d803ffdb0f9d886982888d3f5c5ccb792c3e
RESULT_CI=branch 30885817084 PASS; dev 30885892814 PASS; junhee 30885949124 PASS
```

### R2-W4-F3

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W4-F3
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=metric semantic contract
TASK_CARD_RANGE=R2-10~14 metric registry 생산
CURRENT_TASK_CARD_ID=R2-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=96d3d803ffdb0f9d886982888d3f5c5ccb792c3e
START_POINT=origin/seung에서 origin/dev 96d3d803ffdb0f9d886982888d3f5c5ccb792c3e를 merge한 뒤 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W4-F3@96d3d80
CONTRACT_VERSION=I4-CONTEXT-v2.1.0-DRAFT; PROMPT-v1.0.9-compatible
ALLOWED_PATHS=src/data/analytics_context_contract.i4.v2.json; tests/data/test_analytics_context_contract.py; handoffs/R2-W4-F3.json; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/ai/**; frontend/**; infrastructure/database/**; root Compose·env·CI; secret
HANDOFF_MANIFEST=handoffs/R2-W4-F3.json
ACCEPTANCE_CRITERIA=versioned Context 계약에 metric registry를 추가해 metric id·asset FQN·field·aggregation·time field와 optional required_filters(field·operator·string 또는 boolean value)를 제공한다. 각 metric field와 filter field가 해당 asset의 승인 column에 포함되는지 검증한다. expired_points에는 txn_type=EXPIRE와 is_forecast=false를, 분석 View metric에는 실제 View column에 맞는 ACTUAL·non-forecast 필터를 보존한다. 기존 raw asset·JOIN·selection policy는 호환 유지하며 case ID·정답 SQL·자유 SQL predicate는 넣지 않는다.
ACCEPTANCE_IDS=AC1_VERSIONED_REGISTRY;AC2_ASSET_COLUMN;AC3_STRUCTURED_FILTER;AC4_CRM_FILTER;AC5_VIEW_FILTER;AC6_COMPATIBILITY;AC7_LOCAL_ONLY
TEST_COMMANDS=python -m pytest tests/data/test_analytics_context_contract.py -q; python -m json.tool src/data/analytics_context_contract.i4.v2.json; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_DATA;T2_JSON;T3_SCOPE;T4_DIFF
STOP_CONDITIONS=case ID·정답 SQL hardcode; unrestricted SQL predicate; 승인 asset 밖 metric; 기존 계약 비호환; R4·R3 경로 변경; 외부 서비스·비용·secret 필요; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local contract·test·허용 경로 commit·seung push만 승인한다.
AUTO_FAIL_CONDITIONS=filter field가 asset column 밖; unrestricted predicate; 기존 계약 비호환; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=metric registry·column 정합·CRM/View 필터·data test·branch CI를 제출한다. 통과해도 R4 소비자와 cloud smoke는 별도 발행 전까지 대기한다.
RESULT_SHA=e9a57ed41b83fdbdf90b1e467a12856581033705
RESULT_CI=branch 30886662028 PASS; dev 30886729486 PASS
```

### R4-W4-F3

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W4-F3
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=Report production registration
TASK_CARD_RANGE=R4-16 Report 공통 등록
CURRENT_TASK_CARD_ID=R4-16
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=f82df8d3fb1709347af80d45c07152e32f22b1ce
START_POINT=origin/jaehong 75807e51a8ffcb73336e657600059f41ca0ded39; origin/dev를 merge한 뒤 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W4-F3@f82df8d
CONTRACT_VERSION=REPORT-v1.0.0-compatible; OPENAPI-v1.0.0; migration head new
ALLOWED_PATHS=app/backend/app/**; app/backend/migrations/versions/**; app/backend/README.md; tests/backend/**; tests/report/**; handoffs/R4-W4-F3.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/report/**; src/data/**; src/ai/**; frontend/**; root Compose·env·CI; 기존 migration 수정; secret
HANDOFF_MANIFEST=handoffs/R4-W4-F3.json
ACCEPTANCE_CRITERIA=기존 src/report proposal 계약을 FastAPI Control Plane에 등록하고 인증·권한을 적용한다. Report definition·version·block·run·block_run을 기존 Alembic head 뒤의 새 revision 하나로 영속화한다. 승인 version은 불변이고 승인 definition만 run 가능하며 duplicate run_id를 차단한다. 기존 migration과 R5 proposal은 수정하지 않고 worker·schedule runtime은 구현하지 않는다. README migration head를 실제 값으로 갱신한다.
ACCEPTANCE_IDS=AC1_ROUTER;AC2_AUTH;AC3_NEW_MIGRATION;AC4_IMMUTABLE_APPROVED;AC5_APPROVED_RUN_ONLY;AC6_DUPLICATE_RUN;AC7_EXISTING_MIGRATION;AC8_NO_WORKER
TEST_COMMANDS=python -m pytest tests/backend tests/report -q; 빈 DB와 기존 DB alembic upgrade head; python -m compileall -q app/backend/app; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_BACKEND_REPORT;T2_MIGRATION;T3_COMPILE;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=기존 migration 수정; worker·schedule 구현 필요; R5 proposal 변경 필요; 허용 경로 밖 변경; 외부 서비스·비용·secret 필요; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local code·test·허용 경로 commit·jaehong push만 승인한다.
AUTO_FAIL_CONDITIONS=인증 우회; 승인본 수정; 미승인 run; duplicate run 허용; migration chain 분기; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=새 migration·router·권한·불변성·중복 차단·branch CI를 제출한다. worker와 실제 schedule은 별도 발행 전 대기한다.
RESULT_SHA=89d656f05783dc2394bdc816257de622e6ce20de
RESULT_CI=branch 30887466759 PASS; dev 30887524951 PASS
```

### R4-W4-F4

```text
STATUS=READY
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W4-F4
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=metric semantic Context·G2
TASK_CARD_RANGE=R4-06~11 metric registry 소비
CURRENT_TASK_CARD_ID=R4-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=89d656f05783dc2394bdc816257de622e6ce20de
START_POINT=origin/jaehong 89d656f05783dc2394bdc816257de622e6ce20de에서 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W4-F4@89d656f
CONTRACT_VERSION=I4-CONTEXT-v2.1.0-DRAFT; I4-METRIC-v1.0.0-DRAFT; PROMPT-v1.0.9-compatible
ALLOWED_PATHS=app/backend/app/adapters/i2_data_platform.py; app/backend/app/adapters/contract_model.py; app/backend/app/services/context_builder.py; app/backend/app/services/pipeline_support.py; tests/backend/test_i2_data_platform.py; tests/backend/test_context_builder.py; tests/backend/test_production_model.py; handoffs/R4-W4-F4.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/data/**; src/ai/**; frontend/**; migrations/**; Report router·repository; root Compose·env·CI; secret
HANDOFF_MANIFEST=handoffs/R4-W4-F4.json
ACCEPTANCE_CRITERIA=R2 metric registry를 adapter에서 읽고 질문별로 선택된 승인 asset의 metric만 Context Package에 포함한다. metric id·asset FQN·field·aggregation·time field·required_filters를 entitlement 이후에도 보존하고 package hash와 model payload에 포함한다. registry가 없거나 선택 asset에 metric이 0개 또는 동일 id가 여러 개면 fail-closed한다. hardcoded recognized_room_revenue metric을 제거한다. G2는 SQL이 Context metric의 required_filters를 충족하는지 일반 규칙으로 확인해 누락·변조를 차단하며 CRM expired_points와 View ACTUAL/non-forecast 회귀를 검증한다. 기존 asset·JOIN·60-column·권한 계약과 1회 repair 상한은 유지한다.
ACCEPTANCE_IDS=AC1_REGISTRY_LOAD;AC2_ENTITLED_METRICS;AC3_CONTEXT_HASH;AC4_MODEL_PAYLOAD;AC5_NO_HARDCODE;AC6_FAIL_CLOSED;AC7_G2_FILTER;AC8_CRM_VIEW_REGRESSION;AC9_COMPATIBILITY
TEST_COMMANDS=python -m pytest tests/backend/test_i2_data_platform.py tests/backend/test_context_builder.py tests/backend/test_production_model.py -q; python -m pytest tests/backend -q; python -m compileall -q app/backend/app; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_TARGET;T2_BACKEND;T3_COMPILE;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=metric case ID·정답 SQL hardcode; raw SQL predicate를 Context 입력으로 허용; entitlement 전 metric 노출; metric 0/중복을 묵인; R2·R3·frontend·migration·Report 경로 변경; 외부 서비스·비용·secret 필요; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local backend code·test·허용 경로 commit·jaehong push만 승인한다.
AUTO_FAIL_CONDITIONS=hardcoded single metric; required filter 누락 허용; 권한 밖 metric; package hash 미포함; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=두 대표 metric의 Context·model payload·G2 차단, fail-closed, backend 회귀와 branch CI를 제출한다. 통과해도 cloud smoke는 별도 비용 승인 전까지 대기한다.
```

### R5-W4-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W4-F1
TARGET_INTEGRATION_GATE=I4
CHECKPOINT_GATES=12-column Report editor
TASK_CARD_RANGE=R5-11 Report editor
CURRENT_TASK_CARD_ID=R5-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=f82df8d3fb1709347af80d45c07152e32f22b1ce
START_POINT=origin/minji f8e9eb5c261a452e01a347039605d416b6fb4cc4; origin/dev를 merge한 뒤 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R5-W4-F1@f82df8d
CONTRACT_VERSION=REPORT-v1.0.0-compatible; SCR-RPT-003; RPE-01~08
ALLOWED_PATHS=app/enterprise-react/src/contracts/report.ts; app/enterprise-react/src/pages/ReportsPage.jsx; app/enterprise-react/src/styles.css; tests/frontend/contracts.test.mjs; handoffs/R5-W4-F1.json; docs/markdown/daily_reports/minji/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/report/**; src/data/**; src/ai/**; root Compose·env·CI; 다른 화면·route; secret
HANDOFF_MANIFEST=handoffs/R5-W4-F1.json
ACCEPTANCE_CRITERIA=SCR-RPT-003에서 block의 x·y·w·h를 사용하는 실제 12-column draft layout을 직렬화한다. add·move·resize·delete에는 keyboard 대안을 제공하고 draft만 변경할 수 있으며 승인본을 자동 덮어쓰지 않는다. Chat Artifact ID를 보존하고 local fixture임을 명시한다. manual run·history·schedule·실제 API 성공은 구현하거나 주장하지 않는다.
ACCEPTANCE_IDS=AC1_12_COLUMN;AC2_SERIALIZE;AC3_ADD_MOVE_RESIZE_DELETE;AC4_KEYBOARD;AC5_DRAFT_ONLY;AC6_ARTIFACT_ID;AC7_FIXTURE_LABEL;AC8_SCOPE
TEST_COMMANDS=cd app/enterprise-react && npm run build; node tests/frontend/contracts.test.mjs; 1440·1024·768·360px keyboard·focus 수동 확인; python .github/scripts/gate_scope.py --branch minji --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_BUILD;T2_CONTRACT;T3_VISUAL_KEYBOARD;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=새 dependency 필요; backend·route 변경 필요; 승인본 mutation; keyboard 대안 누락; manual run·history·schedule·API 구현 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local code·test·허용 경로 commit·minji push만 승인한다.
AUTO_FAIL_CONDITIONS=승인본 덮어쓰기; local fixture를 실제 API로 표시; 접근성 회귀; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=12-column state·keyboard·draft 불변성·Artifact ID·build·contract·branch CI를 제출한다. 실제 run/history/schedule/API는 R4 등록 뒤 별도 발행 전 대기한다.
RESULT_SHA=5768aa3b29b06a383a81c33012828181b95b6a4d
RESULT_CI=branch 30887190599 PASS; dev 30887264040 PASS
```

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
HANDOFF_REQUIRED_FIELDS=실행 묶음·역할·branch·BASE_SHA·RESULT_SHA·완료 카드·실제 변경 파일·계약 version·수용 결과 ID/증거·검증 결과 ID/증거·Not Run·change request·잔여 위험·외부 승인 요청
ACCEPTANCE_CRITERIA=<목표 통합 Gate 공통 조건 + 역할별 제출물>
ACCEPTANCE_IDS=<AC1;AC2;... 고유 ID>
TEST_COMMANDS=<formatter·lint·type check·unit/contract test·build 중 적용 명령>
TEST_COMMAND_IDS=<T1;T2;... TEST_COMMANDS 순서와 일치하는 고유 ID>
STOP_CONDITIONS=<목표 통합 Gate 도달·범위 완료·역할 밖 변경·계약 충돌·필수 검증 실패>
EXTERNAL_ACTION_PERMISSION=<설치·비용·배포·데이터 전송·Git 권한>
AUTO_FAIL_CONDITIONS=<경로 침범·SHA/diff 불일치·manifest 누락/오류·필수 검증 실패>
R1_REVIEW_CONDITIONS=<Not Run·change request·잔여 위험·외부 승인·기획/계약 수동 수용 판단>
```

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v3.13 | 2026-08-04 16:45 | R2 metric registry, R4 Report production 등록, R5 12-column editor의 제품·handoff·branch/dev CI를 확인해 MERGED_DEV로 전환했다. R2 registry를 권한별 Context·model payload·G2에 보존하고 hardcoded metric을 제거하는 R4-W4-F4를 local-only로 발행했다. |
| v3.12 | 2026-08-04 16:20 | R3-W4-F5의 구조화 metric 필터 계약과 branch·dev·junhee CI 통과를 확인해 MERGED_DEV로 전환했다. 제품 Context가 같은 의미 계약을 소비할 수 있도록 R2-W4-F3 metric registry 생산자를 local-only로 발행하고 R4 소비·cloud 재평가는 후속 판정으로 유지했다. |
| v3.11 | 2026-08-04 15:50 | R3 F5의 누적 F3/F4 증거가 role scope에 걸리는 오탐을 이전 승인 경로와의 합집합으로 교정했다. I4의 독립 local-only 작업으로 R4-W4-F3 Report production 등록과 R5-W4-F1 12-column editor를 발행하고 worker·schedule·실제 API·외부 비용은 제외했다. |
| v3.10 | 2026-08-04 15:40 | F4 CRM 실패가 모델에 전달되지 않은 metric 필수 필터 계약에서 시작됐음을 확인했다. field·operator·value 구조를 schema·prompt·Validation 생성기에 보존하는 비용 없는 R1-W4-F5·R3-W4-F5를 발행하고 R4 소비·cloud 재평가는 별도 판정으로 남겼다. |
| v3.09 | 2026-08-04 15:34 | R3-W4-F4는 같은 균형 manifest의 첫 3건을 전 기준 통과했으나 4번째 CRM 소멸 포인트에서 필수 범위·지표 조건을 누락해 result hash가 달랐다. fail-fast·USD 0.0402·F3+F4 USD 0.0825·Pod 삭제·active 0·CI `30884334429`의 의도된 FAIL을 확인해 R1·R3 F4를 BLOCKED·WAIT로 전환하고 추가 cloud 실행을 금지했다. |
| v3.08 | 2026-08-04 15:01 | 균형 smoke 첫 건은 JSON·G2를 통과했지만 생성 SQL의 `timestamp(3) <= varchar(7)` 타입 오류로 Trino에서 중단했고 정답 SQL은 결과 hash까지 일치했다. USD 0.0423·Pod 삭제·active 0과 의도된 CI 실패를 기록하고, 일반 날짜 타입·synthetic 범위 규칙만 보완해 같은 manifest를 F3+F4 합계 USD 0.35 안에서 한 번 재검증하는 R1-W4-F4·R3-W4-F4를 발행했다. |
| v3.07 | 2026-08-04 14:30 | R3-W4-F2 실패를 편향된 선두 20건·JSON 미완성 8건·1000행 초과 8건·repair PASS 4건으로 분리했다. G2를 유지하면서 6개 domain·두 node·Trino 결과 동등성을 smoke 20건과 신규 USD 0.35 안에서 재검증하는 R1-W4-F3·R3-W4-F3를 발행했다. |
| v3.06 | 2026-08-04 14:20 | Instruct-2507 Base smoke 20건이 JSON 12건·G2/Trino/정답 SQL 각 4건에 그쳐 R3-W4-F2를 BLOCKED로 전환했다. R3 branch CI `30880359294`는 PASS했지만 150건 전체 평가·LoRA·Blind Gold는 실행하지 않았고 task Pod 삭제와 신규 비용 USD 0.132 추정을 기록했다. |
| v3.05 | 2026-08-04 14:35 | R4가 actual DataHub에서 PMS–CRM 5개·허용 26개 column만 Context에 포함하고 승인 JOIN은 G2 PASS, JOIN ID 누락은 `UNAPPROVED_JOIN`으로 차단했다. branch CI `30878778928`·dev `23d27ac`과 task 자원 0을 확인해 R4-W4-F2A를 MERGED_DEV로 전환하고, Gold·Acceptance를 제외한 Validation-ID 75·OOD 75 생성 후 Instruct-2507 Base를 최대 신규 USD 0.50 안에서 평가하는 R3-W4-F2를 READY 발행했다. |
| v3.04 | 2026-08-04 14:20 | R2 raw URN 교정 `b1349bc`·data test 30건·branch CI `30878553003`·dev `40776da`를 수용했다. View exact-match는 유지하고 raw는 exact URN·원본 database schema name·허용 column 부분집합만 노출해 실제 CRM·PMS–CRM Context와 G2를 재검증하는 R4-W4-F2A를 READY 발행했다. |
| v3.03 | 2026-08-04 14:10 | 실제 DataHub raw URN이 platform instance·database를 포함해 R2 축약 계약과 불일치함을 R4 exact-match가 차단했다. R4-W4-F2를 BLOCKED로 전환하고 raw 7개 URN만 교정하는 R2-W4-F2A를 READY, 실제 재검증 R4-W4-F2A를 PLANNED로 발행했다. |
| v3.02 | 2026-08-04 13:55 | R2의 `I4-CONTEXT-v2.0.0`이 View 기본·CRM raw 3개·승인 PMS–CRM JOIN 5개를 명시하고 data test 30건·branch CI `30877829305`·dev `115232e`로 통합됐다. 같은 계약을 live DataHub exact-match·entitlement·G2로 소비하는 R4-W4-F2를 READY 발행했다. |
| v3.01 | 2026-08-04 13:45 | 기존 Validation 150건이 제품 View 계약 밖 raw FQN 7개를 포함하고 v2의 ID/OOD 분리·누수 차단 기준을 충족하지 못해 RunPod 실행을 중단했다. View 우선과 CRM 단독·승인 PMS–CRM JOIN만 명시하는 R2-W4-F2를 READY, 후속 R4-W4-F2를 PLANNED로 발행하고 R3-W4-F1을 Context 계약 대기로 전환했다. |
| v3.00 | 2026-08-04 13:40 | R1 health 묶음을 닫은 뒤 발생한 새 checkpoint 승인 문서의 역할 경로 오판을 분리했다. R1-W4-F2에 Gate 0 수용·model/revision·Base 우선·비용 상한과 R3 발행 문서·테스트 경로만 허용해 제품 범위를 넓히지 않고 CI 선택 기준을 교정했다. |
| v2.99 | 2026-08-04 13:40 | R4의 live DataHub Context·entitlement·60-column·G2 정합을 실제 v1.6 trace와 dev `db6d42f`·CI `30877055428` PASS로 확정해 Gate 0을 해제했다. 사용자가 지정한 `Qwen/Qwen3-4B-Instruct-2507`의 공식 non-thinking 특성과 revision을 고정하고, 이전 adapter 없이 Base smoke 성공 후 Validation 150건만 최대 신규 USD 0.50 안에서 실행하는 R3-W4-F1을 READY 발행했다. |
| v2.98 | 2026-08-04 13:20 | R1 health 교정과 R2 DataHub 생산자 결과를 최종 dev `7ca7755`·CI `30876201074` PASS로 확정했다. R2의 8개 View·116개 column 계약을 live DataHub 검증 기준으로 소비하되 질문별 최대 60개 column과 entitlement를 유지하고 raw 5개 asset fallback을 금지하는 R4-W4-F1A를 READY 발행했다. |
| v2.97 | 2026-08-04 12:51 | R1-W4-F1A branch CI에서 최신 R1 bundle을 과거 `R1-W3-F7`로 고정한 통합 테스트 한 건만 실패해, 현재 bundle ID·상태 기대값 교정을 허용 경로와 검증에 추가했다. Compose·문서·role scope는 PASS를 유지했다. |
| v2.96 | 2026-08-04 12:48 | R2 DataHub 실수집은 8개 URN·116개 column·17개 upstream edge·90개 column lineage로 PASS했으나, 실제 GMS에 없는 management actuator를 service fragment가 필수 health로 요구해 CI가 실패했다. R2 범위 위반을 되돌리고 공식 v1.6 `/health` 계약만 R1 경로에서 교정한 뒤 dev 통합·R2 재검증하는 R1-W4-F1A를 발행했다. |
| v2.95 | 2026-08-04 11:42 | R2-W4-F1 사전 조회에서 원천 SELECT는 성공했지만 View 소유자의 `GRANT_SELECT` 부재로 `serving.analytics` 조회가 실패했다. 기존 카드의 경로 제한을 지키기 위해 F1을 BLOCKED로 전환하고, 소유자에게만 위임 조회 권한을 추가하되 일반 사용자는 SELECT 전용으로 유지하는 R2-W4-F1A를 같은 기준 SHA에서 READY 발행했다. |
| v2.94 | 2026-08-04 11:20 | sLLM 학습데이터는 `serving.analytics` View를 사용하지만 DataHub에는 5개 원천 recipe만 있고 backend 제품 Context는 PMS·CRM 5개 원천 asset을 고정 반환하는 불일치를 확인했다. I3 Base 제품 통과는 유지하되 LoRA 제품 채택은 정합 전까지 보류했다. 제품 Context는 `LIVE_DATAHUB`로 확정하고 실제 조회·read-only trace를 요구하는 R2-W4-F1을 먼저 READY 발행했으며, R4 follow-up은 R2 dev 통합 뒤 발행한다. |
| v2.93 | 2026-08-04 11:20 | R3-W3-F11·R4-W3-F4를 dev에 통합하고 최종 CI `30870270154` PASS를 확인했다. 고정 Qwen3-4B Base·synthetic Trino read-only 제품 trace가 2026-06·07 두 행, repair 0회, ROUTER부터 ARTIFACT까지 모두 PASS했고 Pod 404·active 0·secret 로그 0건·기존 Docker 무변경을 확인해 R1-W3·R1-W3-F7을 VERIFIED_GATE로 승인했다. Dashboard가 과거 BLOCKED 카드를 현재 카드로 오인하던 선택 로직도 마지막 발행 묶음 기준으로 교정했다. |
| v2.92 | 2026-08-04 10:41 | R1-W3-F7 실제 trace에서 G2 reference 보완 뒤 잉여 non-date parameter, 승인 JOIN 단축·타입 오류, verbose guided 응답 불안정과 전월 대비 기간 누락을 순서대로 확인했다. 안전 경계를 유지하는 R3-W3-F11 PROMPT-v1.0.6과 R4-W3-F4 SQL-only guided·결정론적 metadata·2개월 fail-closed를 READY 발행하며, 두 변경 통합 뒤 동일 trace를 최종 판정한다. |
| v2.91 | 2026-08-04 09:49 | R3-W3-F10의 SQL FROM/JOIN·references 정확 일치 PROMPT-v1.0.5와 mismatch 단일 repair PROMPT-v1.0.2를 AI 47건·Gate 19건·CI `30866726434` PASS로 dev에 통합했다. 같은 Base·synthetic Trino read-only 제품 trace를 재판정하는 R1-W3-F7을 발행하며 성공 전 I3를 유지한다. |
| v2.90 | 2026-08-04 09:37 | 정상 Secure A40 제품 trace가 MODEL 뒤 SQL-reference 불일치와 1회 repair 후 G2 정책 차단으로 종료된 사실, QUERY·Artifact 부재·cleanup·기존 Docker 무변경을 기록했다. R3-W3-F10으로 node2·repair의 SQL FROM/JOIN과 references 정확 일치 행동만 READY 발행하며 실제 성공 trace 전 I3를 유지한다. |
| v2.89 | 2026-08-04 08:12 | 목표 재개 후 공식 PyTorch template Secure A40을 재시도했으나 474.937초 동안 uptime 0이 반복돼 실제 제품 trace는 Not Run이었다. Pod 404·활성 0·신규 비용 상한 USD 0.058048·누적 USD 1.617033, 기존 Trino 무변경과 임시 key 저장 제거를 확인하고 R1-W3-F6·I3 차단을 유지했다. |
| v2.88 | 2026-08-04 05:09 | R1-W3-F6의 세 task Secure A40이 모두 desired RUNNING과 달리 container uptime 0에 머물러 PROMPT-v1.0.4 제품 trace를 실행하지 못했다. 세 Pod 404·활성 0·신규 비용 상한 USD 0.141859·누적 USD 1.558985, 기존 Trino 무변경과 임시 key 저장 제거를 확인하고 외부 provisioning blocker로 I3를 유지했다. |
| v2.87 | 2026-08-04 04:47 | R3-W3-F9의 SQL placeholder와 parameters 1:1·request metadata 제외 PROMPT-v1.0.4와 CI `30847080427` PASS를 검수해 dev에 통합했다. R1-W3-F6는 같은 Base·I2 read-only 제품 trace를 한 번 재검증하고 성공 전 I3 승인·다른 resource 변경을 금지했다. |
| v2.86 | 2026-08-04 04:39 | R1-W3-F5에서 actual question·MODEL·G2는 통과했으나 Base가 request metadata를 SQL parameter로 반환해 안전한 날짜 바인더가 거부한 QUERY blocker를 확정했다. 비용·task cleanup·기존 Trino 무변경을 확인하고 R3-W3-F9로 SQL placeholder와 parameters의 1:1 의미만 PROMPT-v1.0.4에 고정했다. |
| v2.85 | 2026-08-04 04:27 | R4-W3-F3의 제품 원문 question→normalized_question 전달과 CI `30845776821` PASS를 검수해 dev에 통합했다. R1-W3-F5는 actual question raw 입력과 동일 Base·I2 read-only 제품 trace를 판정하고 성공 전 I3 승인·다른 resource 변경을 금지했다. |
| v2.84 | 2026-08-04 04:21 | R3-W3-F8의 optional normalized_question·ID 비의미 prompt와 CI `30845353451` PASS를 검수해 dev에 통합했다. R4-W3-F3는 제품 원문 질문을 service→adapter→R3 request로 그대로 전달하는 최소 변경만 READY 발행하며 schema·prompt·OpenAPI·generation option 변경을 금지했다. |
| v2.83 | 2026-08-04 04:17 | R1-W3-F4 raw 고정 UUID는 schema·한 줄·LIMIT을 통과했지만 실제 제품의 무작위 request UUID에서는 MODEL invalid·circuit 안전 실패가 반복됐다. node2 계약에 실제 질문이 없어 Base가 UUID에 반응하는 근본 병목과 QUERY·Artifact 부재, cleanup·active Pods 0·예상 신규 상한 USD0.090978을 기록했다. R3-W3-F8로 optional normalized_question·ID 비의미 prompt만 호환 추가하고 실제 제품 재검증 전 I3를 차단한다. |
| v2.82 | 2026-08-04 04:03 | R3-W3-F7의 node2 한 줄 compact SQL PROMPT-v1.0.2와 CI `30843971371` PASS를 검수해 dev에 통합했다. 후속 R1-W3-F4는 raw finish/schema/LIMIT을 먼저 확인하고 동일 read-only 제품 trace의 G2·QUERY·G3·ARTIFACT를 판정하며, 다른 resource 변경과 성공 trace 없는 I3 승인을 금지했다. |
| v2.81 | 2026-08-04 03:59 | R1-W3-F3 실제 Base trace에서 LIMIT은 생성됐지만 SQL 문자열의 881줄 불필요한 개행 때문에 completion 1,500 token에 도달해 JSON이 미완성으로 MODEL 안전 실패했다. QUERY·Artifact 부재와 cleanup·active Pods 0·예상 신규 상한 USD0.066224를 확인했다. node2 prompt에 한 줄 compact SQL만 추가하는 R3-W3-F7을 READY 발행했으며 실제 재검증 전 I3는 차단한다. |
| v2.80 | 2026-08-04 03:48 | R3-W3-F6의 PROMPT-v1.0.1 resource limit·단일 repair 문구와 CI `30842808365` PASS를 검수해 dev에 통합했다. 후속 R1-W3-F3는 task A40·backend와 기존 synthetic Trino의 read-only 조회만 사용해 동일 제품 trace의 LIMIT·G2·QUERY·G3·ARTIFACT를 재판정하고, 다른 Docker resource 변경과 성공 trace 없는 I3 승인을 금지했다. |
| v2.79 | 2026-08-04 03:42 | R1-W3-F2 실제 I2 product trace는 guided MODEL까지 통과했지만 node2가 `LIMIT` 없는 SQL을 생성하고 repair도 동일 SQL을 반환해 G2에서 안전 차단됐다. QUERY·Artifact 부재와 task resource cleanup·active Pods 0·예상 신규 상한 USD0.066601를 확인했다. `LIMIT <= 1000`과 `RESOURCE_POLICY_MISSING` 단일 수정 행동만 prompt에 명시하는 R3-W3-F6를 READY 발행했으며 실제 Base 재검증 전 I3는 차단한다. |
| v2.78 | 2026-08-04 03:27 | R4-W3-F2의 node별 R3 response schema guided transport와 전체 CI `30841201329` PASS를 검수해 dev에 통합했다. 후속 R1-W3-F2는 task A40·backend와 기존 hotel-synthetic-db Trino의 read-only synthetic 조회만 허용해 실제 MODEL→G2→QUERY→G3→ARTIFACT trace를 판정하고, 다른 Docker resource 변경과 I3 조기 승인을 금지했다. |
| v2.77 | 2026-08-04 03:21 | R1-W3-F1 live product trace는 Base가 plain 응답·JSON object mode에서 R3 schema를 지키지 못해 MODEL 안전 실패했고, 실제 R3 schema의 guided_json은 schema PASS였지만 fake Context의 asset·metric 불일치로 G2 repair 뒤 차단됐다. task Pod·container·image·tunnel을 정확히 제거하고 예상 신규 USD0.107045를 기록했다. schema-guided transport만 보완하는 R4-W3-F2를 READY 발행했으며 실제 I2 synthetic trace 전 I3는 차단한다. |
| v2.76 | 2026-08-04 03:01 | R4 endpoint 연결과 dev CI `30839298442` PASS 뒤 남은 실제 제품 trace를 위해 R1-W3-F1을 READY 발행했다. 누적 USD 15 안에서 task 전용 A40 Base endpoint와 task backend만 사용하고 synthetic `/analysis`의 성공 또는 MODEL 안전 실패를 판정하며, 실제 성공 trace 없이는 I3를 승인하지 않도록 고정했다. |
| v2.75 | 2026-08-04 02:58 | R4-W3-F1의 OpenAI 호환 Base endpoint transport, 고정 생성 옵션, R3 schema 선검증과 timeout·invalid JSON·fallback·circuit open 안전 실패를 검수해 dev에 통합했다. Source CI `30838961585`는 Python 150건·OpenAPI 4건과 역할·문서·quality gate를 통과했다. 동결 OpenAPI에 없는 `MODEL_RESPONSE_INVALID` 대신 기존 `INTERNAL_ERROR`를 유지했으며 실제 RunPod 제품 전체 trace 전 I3는 진행 상태다. |
| v2.74 | 2026-08-04 02:43 | R3 Base serving과 최종 dev CI `30837830356` PASS를 기준으로 R4-W3-F1을 READY 발행했다. 기존 ContractModelAdapter·ProductionModelClient를 재사용해 명시적 openai mode만 실제 endpoint를 호출하고, timeout·schema·circuit·fallback을 fake 성공이 아닌 Control Plane 안전 실패로 처리하도록 범위를 제한했다. RunPod 재기동·비용·secret·I3 통과는 승인하지 않았다. |
| v2.73 | 2026-08-04 02:37 | R3-W3-F5의 고정 Qwen3-4B Base vLLM endpoint, initial readiness 101.623초, warm p95 725.808ms, peak 39,280 MiB, 동시 2건, 동일 revision 재시작과 ProductionModelClient 실패 trace를 검수해 dev에 통합했다. Branch CI의 REVIEW_REQUIRED는 청구 확정 지연·R4 change request·잔여 위험을 R1이 수동 수용했으며, 예상 신규 비용 USD 0.062802·누적 USD 1.015075·Pod 404·활성 0개를 확인했다. FastAPI 제품 연결과 I3 통과는 후속이다. |
| v2.72 | 2026-08-04 02:11 | Base·LoRA 비교 뒤 남은 실제 serving 병목을 해소하기 위해 R3-W3-F5를 READY로 발행했다. Qwen3-4B Base 고정 revision의 vLLM endpoint·cold/warm·VRAM·동시 2건·재시작·ProductionModelClient 실패 trace를 요구하고, 이전 비용 USD 0.9523을 포함한 누적 USD 15 한도와 task Pod 삭제를 고정했다. FastAPI 제품 연결·I3 통과·LoRA 채택은 승인하지 않았다. |
| v2.71 | 2026-08-04 01:53 | R1 terminal 판정을 동기화한 daesung corrective CI `30834157984`와 최종 dev CI `30834138561`, junhee CI `30834174015`가 모두 PASS해 R3-W3-F4의 최종 CI 근거를 확정했다. 최초 REVIEW_REQUIRED와 Base 유지 결정은 v2.70 이력에 보존한다. |
| v2.70 | 2026-08-04 01:49 | R3-W3-F4의 Qwen3-4B LoRA 1회 학습·Base 비교, held-out 150건 G2·Trino 검증, 지연시간·VRAM·artifact hash·실측 비용 USD 0.9523·task Pod 삭제를 검토해 dev `34facd6`에 통합했다. Branch CI `30833685964`의 REVIEW_REQUIRED는 serving 미실행·p95 증가·제품 채택 승인 요구에 따른 것으로, R1은 증거 통합만 승인하고 LoRA 제품 기본값 전환은 불승인해 Base를 유지한다. |
| v2.69 | 2026-08-04 01:39 | 사용자 승인 한도 USD 15 안에서 Qwen3-4B Base·LoRA 1회 비교, held-out 150건 G2·Trino 검증, Gold 지연시간·VRAM 기록, artifact 회수·task Pod 삭제와 제품 기본값 보류를 수행한 R3-W3-F4를 REVIEW로 기록했다. |
| v2.68 | 2026-08-03 18:49 | R3-W3-F3의 기본 Train·Validation 보존, held-out Gold 120건·Acceptance 30건 명시 승인, split 누수 0건, 로컬 G2·Trino 150건 전수 PASS와 compiled validate를 확인했다. branch CI `30802900472`와 dev CI `30803015630` PASS 뒤 `aede5a5`에 통합했으며 실제 model download·RunPod·Base/LoRA 실행은 계속 미승인이다. |
| v2.67 | 2026-08-03 18:36 | 실제 Qwen compiled 1,350건에 Gold·Acceptance split이 없고 생성기도 Train·Validation만 선택해 Base·LoRA 평가 입력을 만들 수 없는 누락을 확인했다. 기존 기본 동작을 보존하면서 제공 원장의 Gold 120건·Acceptance 30건을 명시적으로 승인·생성하고 로컬 G2·Trino로 전수 검증하는 R3-W3-F3를 READY 발행했으며 외부 model·RunPod 승인은 계속 제외했다. |
| v2.66 | 2026-08-03 18:20 | R1-W3의 required30·gold120 승인과 전 역할 Wave 3 dev 통합, dev·junhee 동일 SHA·CI PASS, 통합 23건과 Context·G1/G2·cache 격리·동시 실행 제한 보안 회귀 29건을 확인해 현재 카드를 R1-10으로 전환했다. 로컬 CUDA와 Qwen3-4B cache가 없고 model download·RunPod 비용이 미승인이라 실제 Base model 비교는 NOT_RUN으로 유지하며 I3·Wave 4는 승인하지 않았다. |
| v2.61 | 2026-08-03 17:28 | 평가 150건의 전수 질문·범주·기대 결과와 자동 검증을 대조해 R1 업무 검토와 R3 계약 소비 검토를 승인했다. 질문·정답·근거는 보존하고 reviewer/status만 동기화하는 R2-W3-F2를 dev `98b8436` 기준으로 발행했으며 model download·비용 권한은 승인하지 않았다. |
| v2.60 | 2026-08-03 17:21 | 구현·handoff·branch CI·dev 병합이 완료된 R2-W3-F1과 R3-W3-F1C의 요약·상세 상태를 `MERGED_DEV`로 정합화하고 실제 구현·CI·병합 SHA를 기록했다. I3 통합 판정과 외부 model 권한은 변경하지 않았다. |
| v2.59 | 2026-08-03 17:15 | R5-W3-F1C에서 Catalog 계약 상수 한 곳을 `I3-DATA-v1.1.0-DRAFT`로 맞추고 minji CI `30796547226`의 production build·frontend contract·Python·문서·역할 범위 통과를 확인한 뒤 dev `4825c0c`에 통합했다. 제품 동작·R2 계약·외부 권한은 변경하지 않았다. |
| v2.58 | 2026-08-03 17:05 | `origin/dev`가 minji 기획서 재구성 병합 `3d6bed7`로 전진했고 CI `30794421419`에서 같은 frontend I3 계약 상수 불일치가 재현됐다. R5-W3-F1C를 `R5-W3-F1C@3d6bed7`로 재발행하며 허용 경로·수용 조건·외부 권한은 변경하지 않았다. |
| v2.57 | 2026-08-03 16:57 | R2-W3-F1 통합 뒤 dev CI `30793737827`에서 R5 Catalog fixture의 I3 data contract 상수만 이전 버전으로 남은 소비자 호환 실패를 확인했다. dev `078651f` 기준 R5-W3-F1C를 READY 발행해 상수 동기화와 frontend contract·build 회귀만 승인하며 R2 계약과 UI 동작은 변경하지 않는다. |
| v2.56 | 2026-08-03 16:04 | R2-W3-F1 구현 중 R3 소비자 테스트가 gold partial 5건·REVIEW 35건을 하드코딩해 full 120건 manifest를 차단하는 change request를 확인했다. dev `c8a943b`·CI `30792024162` 기준으로 R3-W3-F1C를 READY 발행해 partial/full count 호환만 선행 보완하며 runtime·Node 변경과 외부 권한은 승인하지 않았다. |
| v2.55 | 2026-08-03 15:56 | dev `e780b75`·CI `30791740474` PASS를 기준으로 R2-W3-F1을 READY 발행했다. required30 성공 case의 SQL·result hash 연결과 gold120 120건 완성을 우선하며, R3 후속은 이 manifest가 dev에 통합된 뒤 재발행한다. 외부 데이터·image pull·model download·비용·secret은 승인하지 않았다. |
| v2.54 | 2026-08-03 15:50 | Wave 3 요약표와 상세 카드의 상태를 R2~R5 `MERGED_DEV`로 정합화하고, R1 기본 소유 파일인 `AGENTS.md`를 R1-W3 허용 경로에 반영했다. CI run `30791392982`는 Python·Compose·문서 검증 PASS였으나 이 상세 경로 누락으로 role-scope만 실패해 후속 CI 재검증 대상으로 기록했다. |
| v2.53 | 2026-08-03 15:42 | R4 제품 `3c2ee47`·최종 `70d9e56`과 R5 제품 `e6e527a`·최종 `1c33f1c`의 role gate·branch CI를 확인해 순서대로 dev `c89a1a0`·`4106b6d`에 통합하고 dev CI `30790048113`·`30790451402` PASS를 확인했다. R4-W3·R5-W3는 `MERGED_DEV`로 전환했으며 Report 공통 등록·browser 접근성과 외부 Base model·Gold 잔여 근거가 남아 I3는 진행 상태를 유지한다. |
| v2.52 | 2026-08-03 15:10 | R3-W3 제품 `5b13828`·최종 `0ca0096`의 Context 제한 Node2·1회 repair·R2 평가 manifest 소비·timeout/fallback/circuit/trace와 branch CI `30789043209` PASS를 확인해 dev `41f5788`에 통합하고 dev CI `30789184985` PASS를 확인했다. 외부 Base model·RunPod/GPU/비용과 Gold120 나머지는 I3 미완료 증거로 유지하고, R4-W3를 최신 R3 model client 소비 기준 `R4-W3@41f5788`로 재발행했다. |
| v2.51 | 2026-08-03 14:47 | R2-W3의 5원천 catalog·2/3원천 JOIN·필수 30건 fixture를 dev `8bfcd8c`에 통합하고 CI run `30788112084` PASS를 확인했다. R5 부재가 I3 병목이 되지 않도록 R5-W3를 최신 R2 계약 기준 `R5-W3@8bfcd8c`로 재발행했으며, 기존 OpenAPI example·mock을 사용해 R4 완료 전 병렬 착수하도록 승인했다. |
| v2.50 | 2026-08-03 14:26 | R3 신규 실행이 카드 `BASE_SHA=744592a`와 당시 최신 dev 불일치로 자동 차단된 것을 확인했다. R1 착수 커밋을 dev `b06a0da`에 통합하고 CI run `30787154375` PASS를 확인해 R3-W3만 `R3-W3@b06a0da`로 재발행했으며, 원격 R3 일일보고 commit 보존과 no-rebase dev merge를 요구했다. |
| v2.49 | 2026-08-03 14:18 | 최신 dev `1c57797`·CI run `30786041244` PASS와 통합 23건·Gate dashboard·문서 정책 검증을 확인하고 R1-W3를 `IN_PROGRESS`로 전환했다. R2~R5 지시를 Google Docs 섹션 9에 역할별로 발행했으며 required30 0/30·gold120 0/120과 외부 model·비용·secret 미승인 상태를 유지했다. |
| v2.48 | 2026-08-03 13:54 | I2 통합 dev 744592a와 CI run 30785580556 PASS를 기준으로 R1~R5 Wave 3 묶음을 READY 발행했다. 역할별 허용 경로·수용/검증 ID·중단 조건·개인 branch commit·push 권한을 고정하고 model download·RunPod·비용·secret·외부 배포·데이터 전송은 승인하지 않았다. |
| v2.47 | 2026-08-03 13:30 | R5-W2-F2 제품 `dae606f`·최종 `ab1d725`의 production HTTP client, 실제 browser 성공·재질문·차단·source 실패 trace, build·contract·branch CI `30782796303` PASS를 확인해 dev `56cbf08`에 통합하고 dev CI `30784368551` PASS를 확인했다. R1 통합 22건과 DB·Trino·화면 네 runtime 근거를 전수 대조해 R5-W2-F2를 MERGED_DEV, R1-W2를 I2 VERIFIED_GATE로 전환했으며 필수 30·Gold 120 전체 세트는 0/30·0/120 진행 상태로 유지했다. |
| v2.46 | 2026-08-03 12:28 | R4-W2-F3 제품 `3f8a2cf`·handoff `51947de`의 immutable migration, built image blank/existing DB normal entrypoint, readiness·실제 Trino·cleanup과 branch CI `30781472877`를 확인해 dev `158a493`에 통합했다. R5의 보존된 frontend diff를 최신 dev에 동기화해 browser trace를 재개하는 `R5-W2-F2-RESUME@158a493`을 발행했다. |
| v2.45 | 2026-08-03 12:06 | R5 실제 browser 준비 중 accepted backend image가 빈 DB에서 immutable `20260730_02`의 repository-relative DDL 경로를 찾지 못해 normal entrypoint가 종료되는 production blocker를 확인했다. R5-W2-F2를 일시 BLOCKED·WAIT로 전환하고 기존 migration을 보존한 Dockerfile layout과 blank DB startup만 보완하는 `R4-W2-F3@cee1ca2`를 발행했다. |
| v2.44 | 2026-08-03 11:44 | R4-W2-F2 최종 `80c30ec`의 migration 불변성·역할 정책·실제 Trino PARTIAL·query_id·Artifact·exact CORS와 branch CI `30779910256`를 확인해 dev `b1e33c6`에 통합했다. 실제 production 화면 연결을 위한 `R5-W2-F2@b1e33c6`과 minji commit·push 권한을 발행했다. |
| v2.43 | 2026-08-03 10:50 | R1 정책 commit의 role Gate에서 새 `.dockerignore`와 `config/access-policy.yaml`이 기존 R1-W2 허용 목록에 누락된 것을 확인했다. R1 소유 root build-context·공통 접근 정책 경로만 허용 목록에 추가하고 다른 service·deliverable 범위는 확장하지 않았다. |
| v2.42 | 2026-08-03 10:41 | `origin/jaehong` 제품 `4bec9d7`·handoff `b812122`의 CI는 통과했으나 기존 `20260730_02` 수정으로 기존 DB upgrade가 누락되고, Template role·entitlement 미검사, PARTIAL 오류 경로의 `AdapterError.payload` 오참조, real mode HTTP 증거 부재를 확인해 병합을 거부했다. `ACCESS-POLICY-v1.0.0`과 새 migration·실제 HTTP 회귀를 요구하는 `R4-W2-F2-REWORK@e023b06` 및 개인 branch commit·push 권한만 발행했다. |
| v2.41 | 2026-07-31 17:28 | R5-W2-F1을 dev에 통합하고 R1 증거 Gate 보강 CI PASS를 확인한 뒤 실제 DB Template·Trino·migration·CORS runtime 연결을 위한 `R4-W2-F2@0e756e7`을 READY로 발행했다. |
| v2.40 | 2026-07-31 17:11 | 독립 코드 리뷰에서 확인한 증거 우회를 차단하기 위해 ID 없는 추가 결과와 자동 생성 placeholder 증거를 거부하고, 제출된 `REVIEW_REQUIRED`의 차단 정책을 CI Summary·최종 quality 판정과 회귀 test에 동기화했다. |
| v2.39 | 2026-07-31 17:03 | handoff의 빈 `NOT_RUN`을 강제로 채우지 않고 새 실행 묶음의 `ACCEPTANCE_IDS`·`TEST_COMMAND_IDS`를 제출 증거와 전수 대조하도록 R1 Gate를 보강했다. 정적 runtime 검토에서 빈 Template registry·fake data adapter·frontend mock client를 확인해 I2 통합 판정을 재개방하고, R4 실제 Template·Trino·migration·정확한 CORS 연결과 후속 R5 실제 HTTP 연결을 순차 `PLANNED`로 등록했다. |
| v2.38 | 2026-07-31 17:01 | 독립 검증 권고를 반영해 역할 diff가 삭제 파일도 검사하도록 `ACMRD`로 확장하고, 작업 중 manifest 미제출 `NOT_RUN`은 허용하되 제출된 handoff의 `REVIEW_REQUIRED`는 보완·예외 승인 전 terminal 수용을 차단하도록 자동 Gate 정책과 통합 test를 동기화했다. |
| v2.37 | 2026-07-31 15:38 | R5-W2 제품 `58aa706`·handoff `d1f6a74`의 재질문 구분, R4 fixture 계약, build·role gate·branch CI와 독립 browser 증거를 확인해 제품 `555ea14`·팀 보고 `79ba385`로 dev에 통합하고 dev CI run `30610065590` PASS를 확인했다. I2 subset의 성공·재질문·차단은 승인했으나 source 실패 화면이 API `retryable`을 표시하지 않아 I2를 3/4로 유지하고, 기준 `79ba385`의 최소 `R5-W2-F1` REWORK와 minji commit·push 권한을 발행했다. |
| v2.36 | 2026-07-31 15:21 | R4-W2-F1 제품 `0549dbb`·terminal/handoff `08c8db2`의 최신 dev 기준 8개 고유 경로, model 계약 오류·timeout, query timeout·cancel, G2 hard LIMIT, G3 결과 범위·정상/의심 0건 검증과 branch CI run `30609007535` PASS를 확인했다. `f8e4740`으로 dev에 병합하고 pipeline 15건·integration 16건·compileall·보고 validator, 팀 보고 `4db0503`, dev CI run `30609351155` 전체 PASS를 확인해 R4-W2-F1을 MERGED_DEV·WAIT로 전환했다. |
| v2.35 | 2026-07-31 15:05 | Google Docs의 R4 보강 HANDOFF를 읽었으나 후보 `caaa94a`는 현재 R1 저장소와 origin/jaehong에서 조회되지 않았다. 제품 수용 없이 전달된 6개 제품·테스트 경로에 한정해 최신 dev `6a82fff` 기준의 `R4-W2-F1@6a82fff` REWORK와 개인 branch 제출 권한을 발행했으며 실제 diff·목적·전후 동작·필수 검증을 다시 handoff하도록 했다. |
| v2.34 | 2026-07-31 14:55 | R5-W2 제품 `9a4d4e9`·handoff `b7f26f9`와 branch CI run `30607885337`, production build·frontend contract·integration 16건·role gate를 확인했다. 실제 R4 `CONTEXT_INCOMPLETE` 응답이 별도 재질문 화면 없이 일반 ERROR·“요청 차단”으로 표시되고 browser 증거에도 재질문 상태가 빠져 dev 병합을 보류했으며, 기준 `6b37f57`·token `R5-W2@6b37f57`로 해당 상태·fixture·증거만 보완하는 REWORK를 발행했다. |
| v2.33 | 2026-07-31 14:47 | 팀 저장소 dev `bb13121`의 CI run `30607588406` 전체 PASS를 확인하고 R1 평가 원장을 v0.6으로 정합화했다. R5-W2 HANDOFF가 source 실패 화면 증거를 누락하지 않도록 제출 기준을 명확히 했으며, R2·R3·R4는 MERGED_DEV·WAIT, R5만 READY·ACTION을 유지한다. |
| v2.32 | 2026-07-31 14:34 | R4-W2를 MERGED_DEV로 전환한 뒤 junhee CI run `30607094428`에서 실행 묶음 선택 회귀 테스트가 과거 `READY` 상태를 고정 기대해 1건 실패한 것을 확인했다. 현재 원장 상태를 기대하도록 R1 소유 통합 테스트 한 줄을 교정했으며 제품·계약·다른 역할 경로는 변경하지 않았다. |
| v2.31 | 2026-07-31 14:30 | R4-W2 제품 `cd9e9c6`·handoff `2924d0b`의 Context→G1→model→G2→repair 1회→query→G3→Artifact 고정 흐름, 11개 완료 카드, branch CI run `30606533152` PASS를 확인해 `e34442d`로 dev에 통합했다. pipeline 8건·integration 16건과 dev CI run `30606915908` PASS를 확인하고 R4-W2를 MERGED_DEV·WAIT로 전환했으며 R1 평가 원장에 네 결과 trace 근거를 연결했다. |
| v2.30 | 2026-07-31 14:20 | 사용자 요청으로 기획서 v1.2와 동기화한 공식 `02_WBS_29기_3팀.xlsx`가 R1-W2 허용 범위에서 누락돼 junhee CI run `30606452633`의 role-scope만 실패한 것을 확인했다. 문서·Python·Compose 검증은 PASS였으므로 해당 XLSX 단일 경로의 작성·덮어쓰기·commit·junhee push를 승인하고 다른 deliverable은 계속 금지했다. |
| v2.29 | 2026-07-31 14:05 | R2-W2 제품 `75f148b`·handoff `de0a26f`의 `I2-v1.0.0`, GOLD hash `e6c2d1e…08fd`, 승인 JOIN, typed DataHub/Trino adapter, data 14건·통합 16건·role scope와 branch CI run `30605617536` PASS를 확인해 `5afb90b`으로 dev에 통합하고 dev CI run `30605760842` PASS를 확인했다. R2-W2를 MERGED_DEV·WAIT로 전환하고 R1 평가 원장에 정답 hash·source 근거를 연결했다. |
| v2.28 | 2026-07-31 13:58 | R3-W2 제품 `345a788`·handoff `f4f2563`의 허용 경로, G3 pass 전용 Node 3, deterministic 평가 runner, AI 20건·통합 14건·role scope와 branch CI run `30605387557` PASS를 확인해 `f2817a0`으로 dev에 통합하고 dev CI run `30605486384` PASS를 확인했다. R3-W2를 MERGED_DEV·WAIT로 전환하고 R1 평가 원장에 runner 도착 근거를 연결했다. |
| v2.27 | 2026-07-31 13:49 | R1-W2를 IN_PROGRESS로 전환하고 평가 원장 v0.2에 I2 성공·재질문·차단·source 실패 수용 슬롯과 역할별 필수 trace 근거를 고정했다. R2~R5 Wave 2 제품·handoff가 아직 없어 실제 fixture·runner·통합 trace는 생성하지 않고 producer 입력 대기를 기록했다. |
| v2.26 | 2026-07-31 13:36 | R3 제품 `4c8eedf`·handoff `cb10eca`와 R4 제품 `2fa5b49`·handoff `825a0c2`를 각각 `14259c8`·`04e5e6d`로 dev에 통합하고 branch/dev CI PASS를 확인했다. data·model·prompt·fixture·OpenAPI·UI·Report 계약을 최종 version으로 단일 고정하고 로컬 data 8건·AI 15건·integration 16건·frontend·Compose와 dev CI run `30604495881` PASS를 근거로 R1-W1을 I1 `VERIFIED_GATE`로 승인했으며, 기준 `04e5e6d`의 R1~R5 Wave 2 실행 묶음을 READY로 발행했다. |
| v2.25 | 2026-07-31 13:14 | R2 제품 `7051f91`·handoff `510981b`의 data actual version·허용 범위·회귀·branch CI run `30603374739` PASS를 확인해 `7e5e16c`로 dev에 통합하고 dev CI run `30603556566` PASS를 확인했다. R2-W1-F4를 MERGED_DEV·WAIT로 전환하고 R1-W1 blocker를 R3·R4 최종 승격으로 축소했으며 Wave 2는 계속 보류했다. |
| v2.24 | 2026-07-31 13:01 | R2-W1-F4의 data 8건 PASS 후 R1 통합 테스트가 과거 DRAFT data version을 단일 기대해 중단된 것을 확인했다. R2 변경은 commit·push 없이 보관하고 R1 전환 테스트와 최신 R4 bundle 기대를 보완해 통합 14건 및 dev CI run `30603031072` PASS를 확인했으며, R2-W1-F4를 새 기준 `f3038c9`·token으로 재발행했다. |
| v2.23 | 2026-07-31 12:46 | R5 제품 `c600f65`·handoff `3f143af`의 scope·version·build·contract·role gate와 branch CI run `30602136889` PASS를 확인해 `5a52c8f`로 dev에 통합하고 dev CI run `30602295894` PASS를 확인했다. I1 최종 동결을 위해 R2 data actual version, R3 model/prompt/fixture version, R4 README OpenAPI 정합만 수행하는 `R2-W1-F4`·`R3-W1-F1`·`R4-W1-F4`를 READY로 발행했으며 Wave 2는 계속 보류했다. |
| v2.22 | 2026-07-31 12:25 | 최신 `origin/dev` `b81f8e1`과 GitHub Actions run `30601436187` PASS를 확인해 유일한 실행 가능 follow-up인 `R5-W1-F2`의 기준 SHA와 token을 갱신하고 commit·minji push 승인을 유지했다. R2·R3·R4는 `MERGED_DEV/WAIT`, Wave 2는 I1 `VERIFIED_GATE` 전 `PLANNED`를 유지한다. |
| v2.21 | 2026-07-31 12:21 | 사용자가 R3 최신 문서를 dev에 병합하고 충돌 시 R3 작성물을 우선하도록 지시해 기존 cleanup 방침을 종료했다. origin/daesung `733307c`의 요약본과 공식 03 DOCX를 `a0ac7ed`로 dev에 통합하고 문서 정책·DOCX ZIP/구조·diff를 통과했으며, R3 CI의 문서 품질·Python job PASS와 역할 scope failure의 사용자 override를 기록했다. |
| v2.20 | 2026-07-31 12:14 | R3가 기존 복구 지시를 읽은 뒤 제출한 `733307c`에서 요약본 추가와 공식 `03_프로젝트기획서` DOCX 수정이 고유 diff로 남고 CI run `30600969172`가 실패한 것을 확인했다. `R3-W1-CLEAN`의 허용 경로를 현재 두 고유 diff로 교정하고 두 파일을 `origin/dev` 상태로 복구하는 commit·push만 재허가했다. |
| v2.19 | 2026-07-31 12:01 | R3 `d044fb7`의 terminal 허용 범위 밖 기획 요약·DOCX 추가와 CI failure를 확인해 dev 병합을 거부하고, 두 파일만 `origin/dev` 상태로 복구하는 `R3-W1-CLEAN`을 READY·REWORK로 발행했다. 기능·Wave 2·다른 경로 변경은 계속 금지했다. |
| v2.18 | 2026-07-31 11:55 | R2 제품 `23059a6`·handoff `b8ec6b9`의 scope·manifest·data 8건·소비자 계약·CI run `30599951597` PASS를 확인해 `47c1f94`로 dev에 통합하고 R2-W1-F3을 MERGED_DEV·WAIT로 전환했다. R1-W1 blocker는 R5 하나로 축소했으며, R3 `d044fb7`은 terminal 허용 범위 밖 문서 추가와 CI failure로 병합하지 않았다. |
| v2.17 | 2026-07-31 11:44 | R4 제품 `c83809a`와 handoff `9da78aa`의 허용 경로·manifest·backend 55건·GitHub Actions run `30599636125` PASS를 확인해 dev에 통합하고 R4-W1-F3을 MERGED_DEV·WAIT로 전환했으며 OpenAPI를 `OPENAPI-v1.0.0`으로 동결하고 R1-W1 blocker를 R2·R5로 축소했다. |
| v2.16 | 2026-07-31 11:30 | R4 제품 결과 `c83809a`의 역할 범위와 51개 회귀 통과를 수용하고, 실패 1건이 R1 통합 계약의 DRAFT 고정 기대임을 확인해 `OPENAPI-v1.0.0` 전환 계약을 반영했다. 제품 결과는 유지하고 최신 dev 반영 뒤 `handoffs/R4-W1-F3.json`만 추가하는 REWORK로 전환했으며 `origin/dev` `bb5f89d`·CI run `30599059380` PASS를 기록했다. |
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
