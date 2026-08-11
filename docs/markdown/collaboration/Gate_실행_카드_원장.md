# Gate 실행 카드 원장

| 항목 | 내용 |
|---|---|
| 문서 설명 | 현재 역할별 실행 카드와 Gate 중단·통합 조건을 관리하는 활성 원장 |
| 문서 분류 | 일반 문서 |
| 버전 | v5.68 |
| 문서 기준일 | 2026-08-11 14:04 |
| 작성·수정 | 박준희 / 3팀 사용자 요청·Codex 반영 |

> 종료되거나 대체된 카드는 [2026-07-29~2026-08-04 Archive](archive/Gate_실행_카드_원장_20260729-20260804.md)와 [2026-08-05~2026-08-11 Archive](archive/Gate_실행_카드_원장_20260805-20260811.md)에서 확인한다.

## 사용 원칙

1. 자동화와 에이전트는 이 파일의 역할별 마지막 non-`PLANNED` 카드만 현재 실행 기준으로 사용한다.
2. `READY`·`IN_PROGRESS`만 구현을 계속할 수 있으며 `BLOCKED`는 차단 원인을 해소하는 새 묶음이 필요하다.
3. `MERGED_DEV`·`VERIFIED_GATE`는 개인 보고와 공용 보고 경로 외 신규 구현을 허용하지 않는다.
4. 과거 카드·상태 전이·비용·검증 이력은 archive에 보존하며 활성 원장에 복제하지 않는다.
5. 일정과 진행률의 단일 기준은 `docs/markdown/02_WBS.md`다.

## 현재 역할별 실행 상태

| 역할 | 실행 묶음 | 상태 | 개인 branch |
|---|---|---|---|
| R1 | `R1-W5-F29` | `READY` | `junhee` |
| R2 | `R2-W5-F9` | `READY` | `seung` |
| R3 | `R3-W5-F8` | `READY` | `daesung` |
| R4 | `R4-W5-F16` | `READY` | `jaehong` |
| R5 | `R5-W5-F4` | `READY` | `minji` |

## 활성 실행 카드

### R3 · R3-W5-F4

```text
STATUS=PLANNED
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F4
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=R1 Node2→G2→binder·3-source API E2E PASS
TASK_CARD_RANGE=R3-14 compiled 1,350건 typed parameter 재생성·검증
CURRENT_TASK_CARD_ID=N/A — R1-W5-F9 선행
BASE_BRANCH=dev
BASE_SHA=N/A — 통합 E2E 결과 SHA로 발행
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=N/A — build_case_specs와 generated dataset의 exact 경로·용량·제출 정책을 R1 검토 뒤 확정
FORBIDDEN_PATHS=RunPod·외부 endpoint; Gold/Acceptance 평가; backend/data/root Compose; secret
ACCEPTANCE_CRITERIA=현재 compiled 1,350건과 예시 4건의 typed parameter 0건 상태를 실제 동결 계약으로 재생성한다. period_start·period_end_exclusive·required_filter_N과 value_type을 보존하고 train/validation 누수·중복·Trino 실행 검증을 다시 확인한다. 제품 조합 E2E가 실패하면 dataset을 먼저 바꾸지 않는다.
STOP_CONDITIONS=R1 통합 E2E 미통과; generated path·제출 정책 미확정; Gold 의미 변경; RunPod·비용·secret 필요
R1_REVIEW_CONDITIONS=제품 실행 계약이 먼저 통과한 뒤 dataset 생성 path와 hash 갱신 범위를 별도 승인한다.
```

### R1 · R1-W5-F6

```text
STATUS=PLANNED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F6
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=DataHub v1.7 first-start health
TASK_CARD_RANGE=R1-02 exact runtime first-start checkpoint
CURRENT_TASK_CARD_ID=N/A — host free RAM 8GB 이상 확보 뒤 발행
BASE_BRANCH=dev
BASE_SHA=N/A — 실행 직전 최신 dev SHA로 발행
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=docs/markdown/collaboration/Gate_실행_카드_원장.md; handoffs/R1-W5-F6.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=runtime script 변경; DataHub recipe; Trino; source/app DB; 다른 Compose project/container/volume; tracked env·secret
ACCEPTANCE_CRITERIA=시작 직전 host free RAM 8GB 이상과 local secret 5개 readiness를 값 출력 없이 확인한다. exact target inventory와 unrelated project의 container ID·state·volume snapshot을 전후 비교하고 dependency healthy→system-update exit 0→GMS/management/frontend healthy 순서로만 기동한다. DataHub v1.7.0 image digest와 Trino 476·source/app DB 무변경을 확인하며 실패 시 exact DataHub 7개 service만 rollback하고 volume을 보존한다.
STOP_CONDITIONS=host free RAM 8GB 미만; 다른 project 변경 필요; secret 출력; target label 불일치; system-update/health 실패; Trino·source/app DB 변경 필요
R1_REVIEW_CONDITIONS=현재 free RAM 4.67GB이므로 READY 발행과 runtime start를 금지한다. 메모리 확보 결정 뒤 실행 전 재점검한다.
```

### R1 · R1-W5-F7

```text
STATUS=PLANNED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F7
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=R2 typed/3-source producer·R4 binder consumer·R3 Node2 consumer merged dev
TASK_CARD_RANGE=R1-08·09 Node2→G2→binder 조합 회귀·대표 3-source 제품 API E2E
CURRENT_TASK_CARD_ID=N/A — R2-W5-F4→R4-W5-F5→R3-W5-F3 선행
BASE_BRANCH=dev
BASE_SHA=N/A — 세 소비자 통합 SHA로 발행
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=tests/integration/**; handoffs/R1-W5-F7.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 제품 구현; model·RunPod; DataHub runtime PASS 위조; root env·secret; dependency
ACCEPTANCE_CRITERIA=하나의 테스트에서 Node2 출력→R4 G2 placeholder+typed parameter 검증→단일 binder를 통과한다. 이어 G120-046 질문을 Business Request→승인 PMS·CRM·POS Context→Node2 SQL→G2→실제 Trino→G3→표·차트·설명·근거까지 제품 API로 실행하고 하나의 request_id로 trace한다. 권한 없음·승인 밖 JOIN·필수 필터 누락·repair 정확히 1회·timeout/cancel·빈/대용량 결과·masking·Gold 수치 비교는 구현된 계약 범위만 실제 결과로 기록하고 미구현은 후속 카드로 남긴다.
STOP_CONDITIONS=생산자/소비자 미통합; fixture-only 성공; 제품 경로 수정 필요; DataHub runtime·RunPod·비용·secret 필요; 필수 검증 실패
R1_REVIEW_CONDITIONS=조합 회귀와 대표 3-source 실제 API E2E가 모두 PASS한 뒤에만 Analysis persistence·SQLGlot G2/G3·Report worker 단계로 진행한다.
```

### R1 · R1-W5-F24

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F24
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=agent workflow throughput without weakening role ownership or final quality gate
TASK_CARD_RANGE=R1-02·04·10 coding-agent CI·Gate·handoff·worktree preflight automation simplification
CURRENT_TASK_CARD_ID=R1-04-AGENT-AUTOMATION-EFFICIENCY
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=6dfcb494d13b21cf0b3c51e67daaf1e785b28e79
START_POINT=clean junhee가 origin/dev 6dfcb49와 일치하는 상태에서 시작한다. exact path ownership·final quality gate·secret/runtime fail-closed는 유지하고, scope metadata 실패 때문에 제품 검증이 사라지거나 동일 증거를 반복 제출하는 자동화 비용만 제거한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R1-W5-F24@6dfcb49
CONTRACT_VERSION=AGENT-WORKFLOW-v2.0.0-DRAFT; HANDOFF-v1.1.0-DRAFT; GATE-SCOPE-v1.1.0-DRAFT
ALLOWED_PATHS=.github/workflows/ci.yml; .github/scripts/gate_scope.py; .github/scripts/agent_workflow.py; tests/integration/test_ci_workflow.py; tests/integration/test_gate_scope.py; tests/integration/test_agent_workflow.py; docs/markdown/collaboration/README.md; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/collaboration/archive/Gate_실행_카드_원장_20260805-20260811.md; handoffs/R1-W5-F24.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=AGENTS.md; app/**; infrastructure/**; src/**; tests/integration의 승인 3파일 외 tests/**; R2~R5 파일·보고·handoff; root Compose/env; dependency·secret
HANDOFF_MANIFEST=handoffs/R1-W5-F24.json
RESULT_SHA=7b1a7f7be58685dbd78652ce607eaaa83560e91d
RESULT_CI=branch 31453748585 PASS
ACCEPTANCE_CRITERIA=role-scope가 실패해도 변경 그룹 output을 보존하고 적용 가능한 Python·document·frontend·Compose 검증은 독립 실행해 제품 신호를 수집하되 final quality-gate는 scope·제품·handoff 실패를 계속 차단한다. handoff는 branch CI만 CI_PENDING으로 정직하게 제출할 수 있고 이 상태는 현재 push의 CI 실행을 허용하되 R1 terminal 통합 승인으로 오인되지 않는다. 카드의 INHERITED_BLOB_PATHS와 INHERITED_BLOB_SHA256이 함께 있으면 blob이 exact 불변인 경로만 누적 diff에서 current editable change와 분리하며 drift·missing checkpoint는 fail-closed한다. bundle preflight는 branch·clean·base overlap·전체 allowed path를 한 명령으로 보고하고 clean ancestor일 때만 명시적 ff-only dev sync를 제공한다. 활성 Gate 원장은 현재 실행·PLANNED queue만 유지하고 종료 이력은 신규 archive로 이동하되 current_bundle·dashboard·historical base 조회 의미를 보존한다. Google Docs·보고는 Git Gate 정본을 복제하는 상태 저장소가 아니라 요청·결과 전달로만 취급한다고 collaboration README에 명시한다. force/reset/rebase/stash·자동 conflict 해결·권한 확대는 추가하지 않는다.
ACCEPTANCE_IDS=AC1_TEST_SIGNAL_ON_SCOPE_FAILURE;AC2_FINAL_GATE_FAIL_CLOSED;AC3_PENDING_CI_HANDOFF;AC4_INHERITED_HASH;AC5_ONE_COMMAND_PREFLIGHT;AC6_SAFE_FF_ONLY;AC7_ACTIVE_LEDGER_COMPACT;AC8_SINGLE_GIT_CANONICAL;AC9_REGRESSION
TEST_COMMANDS=workflow YAML parse와 integration workflow tests; gate_scope inherited unchanged/drift/missing checkpoint·PENDING_CI 제한·legacy handoff·SAFE_STALE·current dashboard tests; agent_workflow clean/dirty/ancestor/diverged/tool-missing/dry-run/ff-only tests; 전체 tests/integration; python -m compileall -q .github/scripts tests/integration; document policy; gate_scope bootstrap·11 planned paths·merge-base; git diff --check; junhee source CI
TEST_COMMAND_IDS=T1_WORKFLOW;T2_GATE_TARGET;T3_AGENT_WORKFLOW;T4_INTEGRATION;T5_COMPILE;T6_DOCS;T7_SCOPE;T8_DIFF;T9_BRANCH_CI
STOP_CONDITIONS=제품 test를 scope PASS로 위조; quality gate 완화; inherited blob drift 수용; PENDING_CI를 일반 미검증에 허용; dirty/diverged branch 자동 변경; reset·rebase·stash·force·conflict 자동 해결; Git 외 상태를 canonical로 승격; parser가 historical card를 잃음; dependency·secret·외부 비용; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=read-only fetch와 clean ancestor branch의 명시적 ff-only sync, 허용 경로 commit·junhee push·branch CI만 승인한다. 자동 push·merge conflict 해결·workflow dispatch·secret 변경·외부 배포는 금지한다.
AUTO_FAIL_CONDITIONS=scope 실패인데 final gate PASS; 제품 job skip 회귀; inherited checkpoint drift 은폐; handoff 미검증 PASS; dirty/history 손실; archive 뒤 active bundle·historical base 조회 실패; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=scope 실패 fixture에서도 제품 jobs가 실행되고 final gate는 실패하는 CI 계약, terminal handoff 호환성, inherited blob 불변 검증, Windows/Linux preflight 회귀, compact ledger dashboard를 모두 확인한 뒤 dev 통합한다.
```

### R1 · R1-W5-F25

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F25
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=archived I4 VERIFIED_GATE → active I5 issue readiness
TASK_CARD_RANGE=R1-04 coding-agent compact Gate archive readiness regression
CURRENT_TASK_CARD_ID=R1-04-AGENT-AUTOMATION-ARCHIVE-READINESS
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=473d014f0d9c394faf62d958200ae4e9e4755200
START_POINT=R1-W5-F24 MERGED_DEV와 junhee/dev CI PASS를 기준으로 한다. 사용자 승인으로 commit된 legacy 자동화 개선 기록 2d923e2는 누적 read-only evidence로 보존하고 F25에서 추가 수정하지 않는다. 구현은 Git-write 가능한 별도 clean junhee clone에서 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R1-W5-F25@473d014
CONTRACT_VERSION=GATE-SCOPE-v1.1.1-DRAFT
ALLOWED_PATHS=.github/scripts/gate_scope.py; tests/integration/test_gate_scope.py; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/ai_docs/legacy/260805_코딩에이전트_작업프로세스_개선기록_v1.0.md; handoffs/R1-W5-F25.json; docs/markdown/daily_reports/junhee/일일보고.md
READ_ONLY_EVIDENCE_PATHS=docs/markdown/ai_docs/legacy/260805_코딩에이전트_작업프로세스_개선기록_v1.0.md@2d923e29698181f3f3fed5b62fca3bdee5abe099 — 사용자 승인 기록이며 F25 추가 수정 금지
FORBIDDEN_PATHS=docs/markdown/collaboration/archive/** 수정; ALLOWED의 exact legacy 파일 외 docs/markdown/ai_docs/legacy/**; .github/workflows/**; .github/scripts/agent_workflow.py; 승인 test 외 tests/**; app/**; infrastructure/**; src/**; R2~R5 경로; root Compose/env; dependency·secret
HANDOFF_MANIFEST=handoffs/R1-W5-F25.json
ACCEPTANCE_CRITERIA=active 원장만 current bundle·현재 blocker·PLANNED candidate·token의 정본으로 유지하고 archive는 직전 Gate VERIFIED_GATE 존재 판정에만 사용한다. archive의 R1-W4-F5 TARGET_INTEGRATION_GATE=I4·STATUS=VERIFIED_GATE를 근거로 `--dashboard --next-gate auto`가 Previous gate I4와 READY_TO_ISSUE를 출력한다. archive의 과거 PLANNED·READY·BLOCKED·MERGED_DEV는 현재 상태로 승격하지 않는다. archive missing·parse failure·I4 VERIFIED_GATE 부재는 BLOCKED와 명시적 진단을 반환한다. 기존 current_bundle·historical base·role scope·inherited blob·CI_PENDING 의미를 유지한다. Google Docs는 요청함이며 READY 정본이 아니다.
ACCEPTANCE_IDS=AC1_ARCHIVED_VERIFIED_GATE;AC2_ACTIVE_STATE_CANONICAL;AC3_ARCHIVE_FAIL_CLOSED;AC4_CURRENT_I5_READINESS;AC5_GATE_REGRESSION;AC6_USER_DIRTY_PRESERVED;AC7_GOOGLE_DOCS_INBOX_ONLY
TEST_COMMANDS=archive VERIFIED_GATE positive와 missing·malformed·no-verified negative unittest; current dashboard/current_bundle/historical base 회귀; 전체 test_gate_scope; 실제 `--dashboard --next-gate auto`; compileall; handoff json.tool; document policy; clean preflight·5 planned paths·merge-base; 원본 legacy dirty pre/post binary diff SHA-256; git diff --check; junhee source CI
TEST_COMMAND_IDS=T1_ARCHIVE_VERIFIED;T2_ARCHIVE_MISSING;T3_CURRENT_DASHBOARD;T4_GATE_REGRESSION;T5_DASHBOARD_CLI;T6_COMPILE;T7_HANDOFF_JSON;T8_DOCUMENT_POLICY;T9_SCOPE;T10_USER_DIRTY_HASH;T11_DIFF;T12_BRANCH_CI
DEPENDENCIES=R1-W5-F24 MERGED_DEV@473d014; read-only archive에 R1-W4-F5 I4 VERIFIED_GATE 존재; R2~R5 제품 카드와 무관
STOP_CONDITIONS=legacy dirty diff 변화; archive 수정·현재 실행 정본 승격; archive 과거 카드를 현재 blocker/candidate/current bundle로 사용; archive missing·손상인데 READY; current_bundle·role scope·historical base·handoff 회귀; 허용 경로 밖 변경; reset·rebase·stash·force·자동 conflict 해결; dependency·secret·외부 비용; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=origin read-only fetch, Git-write 가능한 exact 별도 clean clone, 허용 경로 commit·junhee push·branch CI만 승인한다. 원본 dirty worktree의 stage/commit/stash/reset/checkout, archive 수정, dev merge, ACL·sandbox·network 변경은 금지한다.
AUTO_FAIL_CONDITIONS=archive 때문에 active current card/blocker/candidate가 변함; archive 없음·손상인데 READY; dashboard가 I4 미검증으로 오판; 원본 dirty diff 변화; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=synthetic·실제 compact 원장에서 archive I4 VERIFIED_GATE만 인식하고 active 상태가 불변이며 원본 legacy diff hash가 일치하고 source CI PASS인 경우에만 dev 통합한다.
SUPERSEDED_BY=R1-W5-F27
BLOCK_REASON=F25 source SHA 12a46f1·CI 31455099641은 PASS했으나 별도 승인된 WBS·Gate 문서 commit 5c54b3e와 history-preserving merge 뒤 누적 branch diff가 F25 handoff 범위를 벗어났다. 이력을 되돌리지 않고 F27에서 reconciliation evidence로 종결한다.
```

### R1 · R1-W5-F27

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F27
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=R1-W5-F25 source PASS + WBS·Gate 문서 이력 reconciliation
TASK_CARD_RANGE=R1-04 junhee history-preserving reconciliation evidence correction
CURRENT_TASK_CARD_ID=R1-04-AGENT-AUTOMATION-RECONCILIATION
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=473d014f0d9c394faf62d958200ae4e9e4755200
START_POINT=F25 terminal source SHA 12a46f1·CI 31455099641 PASS와 별도 승인 문서 SHA 5c54b3e를 merge commit 7b8dc74에서 모두 보존했다. CI 31455371749는 WBS가 F25 범위 밖이고 F25 handoff가 누적 diff와 달라 FAIL했다. 기존 commit·blob을 수정하지 않고 새 evidence만 작성한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R1-W5-F27@473d014
CONTRACT_VERSION=GATE-SCOPE-v1.1.1-DRAFT
ALLOWED_PATHS=.github/scripts/gate_scope.py; docs/markdown/02_WBS.md; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/ai_docs/legacy/260805_코딩에이전트_작업프로세스_개선기록_v1.0.md; docs/markdown/daily_reports/junhee/일일보고.md; handoffs/R1-W5-F25.json; handoffs/R1-W5-F27.json; tests/integration/test_gate_scope.py
READ_ONLY_EVIDENCE_PATHS=.github/scripts/gate_scope.py@12a46f1; docs/markdown/02_WBS.md@5c54b3e; docs/markdown/ai_docs/legacy/260805_코딩에이전트_작업프로세스_개선기록_v1.0.md@2d923e2; handoffs/R1-W5-F25.json@12a46f1; tests/integration/test_gate_scope.py@12a46f1
MUTABLE_PATHS=docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/daily_reports/junhee/일일보고.md; handoffs/R1-W5-F27.json
FORBIDDEN_PATHS=READ_ONLY_EVIDENCE_PATHS 내용 변경; docs/markdown/collaboration/archive/**; R2~R5 제품·보고·handoff; app/**; infrastructure/**; src/**; root Compose/env; dependency·secret
HANDOFF_MANIFEST=handoffs/R1-W5-F27.json
RESULT_SHA=c8bd13dc4be378fdf37d316b4a7cc9be0b6fe74c
RESULT_CI=branch 31455756824 PASS
ACCEPTANCE_CRITERIA=F25 source PASS와 WBS·Gate 문서 commit을 모두 ancestry로 보존하고 누적 7경로를 정확히 handoff한다. F25 handoff의 역사적 CI PASS를 변경하지 않는다. F27은 제품·WBS·자동화 코드를 재수정하지 않고 reconciliation 사실과 실제 corrective CI만 기록한다. archive I4→I5 READY_TO_ISSUE, active current bundle, inherited checkpoint, CI_PENDING 회귀가 유지되어야 한다.
ACCEPTANCE_IDS=AC1_F25_HISTORY;AC2_WBS_HISTORY;AC3_EXACT_CUMULATIVE_DIFF;AC4_READ_ONLY_BLOBS;AC5_GATE_REGRESSION;AC6_CORRECTIVE_CI
TEST_COMMANDS=git ancestry 12a46f1·5c54b3e·7b8dc74; read-only evidence blob diff 0; python -m unittest tests.integration.test_gate_scope -v; python .github/scripts/gate_scope.py --dashboard --next-gate auto; python -m json.tool handoffs/R1-W5-F25.json handoffs/R1-W5-F27.json; document policy; report validation; gate_scope preflight·8 planned paths·merge-base; git diff --check; junhee corrective source CI
TEST_COMMAND_IDS=T1_ANCESTRY;T2_BLOB_INVARIANTS;T3_GATE_TESTS;T4_DASHBOARD;T5_HANDOFF_JSON;T6_DOCUMENT_POLICY;T7_REPORT;T8_SCOPE;T9_DIFF;T10_BRANCH_CI
STOP_CONDITIONS=기존 commit/history/blob 수정; WBS·F25 handoff·자동화 code 재작성; reset·rebase·force·stash; 누적 diff 누락; 허용 8경로 밖 변경; source CI 실패를 PASS로 기록; dependency·secret·외부 비용; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=현재 clean junhee에서 mutable 3경로 commit·junhee push·branch CI만 허용한다. dev merge·workflow dispatch·기존 history rewrite는 금지한다.
AUTO_FAIL_CONDITIONS=12a46f1·5c54b3e ancestry 손실; read-only blob drift; handoff changed files 불일치; dashboard 회귀; scope·필수 검증 FAIL
R1_REVIEW_CONDITIONS=corrective source CI가 실제 PASS하고 F27 handoff가 origin/dev...HEAD의 자기 manifest 제외 exact 7경로를 기록한 뒤에만 dev 통합한다.
```

### R1 · R1-W5-F28

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F28
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=역할별 active READY 단일화·source evidence 판정·후속 카드 발행
TASK_CARD_RANGE=R1-04 Gate 실행 큐 조정과 owner 카드 통합 판정
CURRENT_TASK_CARD_ID=R1-04-I5-ACTIVE-QUEUE
BASE_BRANCH=dev
BASE_SHA=2d805bf9cc52828b567e17e182fd88a8895a0b57
START_POINT=R1-W5-F27은 dev 2d805bf에 통합되었고 dev CI 31456640689가 PASS했다. 현재 R2-W5-F9·R3-W5-F8·R4-W5-F16·R5-W5-F4가 역할별 active READY 하나씩이며, R4-W5-F16 발행 commit 1024202의 CI 31458984632는 제품·문서 실패가 아니라 terminal R1 카드가 Gate 원장 1경로를 허용하지 않아 role-scope만 FAIL했다. 이 카드로 원장 발행·source evidence 판정·terminal 전이만 수행한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W5-F28@2d805bf
CONTRACT_VERSION=GATE-SCOPE-v1.1.1
ALLOWED_PATHS=docs/markdown/collaboration/Gate_실행_카드_원장.md; handoffs/R1-W5-F28.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=.github/**; docs/markdown/collaboration/archive/**; docs/markdown/02_WBS.md; app/**; infrastructure/**; src/**; tests/**; R2~R5 보고·handoff·제품 경로; root Compose·env; dependency·secret
HANDOFF_MANIFEST=handoffs/R1-W5-F28.json
ACCEPTANCE_CRITERIA=역할별 active READY는 하나만 유지하고 현재 R2 F9·R3 F8·R4 F16·R5 F4의 token·BASE_SHA·허용 경로를 변경 없이 정본으로 제공한다. 각 source branch의 terminal CI·handoff·scope가 실제 PASS한 경우에만 MERGED_DEV 또는 후속 READY를 원장에 기록한다. CI 실패·NOT_RUN·BLOCKED를 PASS로 승격하지 않고 생산자→소비자 순서를 유지한다. Google Docs는 작업 인계함으로만 사용하고 Git 원장 READY token을 대신하지 않는다. R4-W5-F16 발행 commit의 CI 31458984632 role-scope 실패는 역사적 사실로 보존하고 이 카드 발행 뒤 재실행되는 junhee CI의 실제 결과로만 현재 원장 발행을 판정한다.
ACCEPTANCE_IDS=AC1_ONE_ACTIVE_PER_ROLE;AC2_CANONICAL_TOKENS;AC3_EVIDENCE_ONLY_TRANSITION;AC4_PRODUCER_FIRST;AC5_FAILED_CI_PRESERVED;AC6_GOOGLE_DOCS_INBOX_ONLY
TEST_COMMANDS=python -m unittest tests.integration.test_gate_scope -q; python .github/scripts/gate_scope.py --dashboard --next-gate auto; python .agents/skills/manage-project-documents/scripts/check_document_policy.py docs/markdown/collaboration/Gate_실행_카드_원장.md; gate_scope preflight·3 planned paths·merge-base; git diff --check; junhee source CI
TEST_COMMAND_IDS=T1_GATE_REGRESSION;T2_DASHBOARD;T3_DOCUMENT_POLICY;T4_SCOPE;T5_DIFF;T6_BRANCH_CI
STOP_CONDITIONS=역할별 active 카드 중복; source CI·handoff 미통과 상태의 MERGED_DEV 전환; 생산자 미통합 상태의 소비자 후속 발행; owner 제품 파일 변경 필요; archive·WBS·workflow·Gate script 변경; 허용 경로 밖 변경; reset·rebase·force·stash; dependency·secret·외부 비용; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=origin read-only fetch·CI 조회, 허용 3경로 commit·junhee push·branch CI만 허용한다. dev merge·다른 역할 branch push·workflow dispatch·제품 구현·환경 변경은 금지한다.
AUTO_FAIL_CONDITIONS=active READY 중복; 실패 evidence의 PASS 승격; token·BASE_SHA drift; scope·필수 검증 FAIL
R1_REVIEW_CONDITIONS=원장 발행 CI가 PASS하고 현재 dashboard가 R1 F28·R2 F9·R3 F8·R4 F16·R5 F4를 각각 하나의 active READY로 표시한 뒤 역할별 작업을 계속한다.
SUPERSEDED_BY=R1-W5-F29
BLOCKED_REASON=원장 발행 CI 31459104984 PASS로 큐 정합성은 확인했으며, 사용자 요청에 따라 stale branch self-sync·Gate-only 발행·remote source merge preflight 병목을 owner-scoped 후속 카드로 교정한다.
```

### R1 · R1-W5-F29

```text
STATUS=READY
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F29
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=stale branch self-sync·Gate-only issuance·remote source merge preflight
TASK_CARD_RANGE=R1-04 coding-agent automation bottleneck correction
CURRENT_TASK_CARD_ID=R1-04-AUTOMATION-BOTTLENECKS
BASE_BRANCH=dev
BASE_SHA=2d805bf9cc52828b567e17e182fd88a8895a0b57
START_POINT=R1-W5-F28 원장 발행 CI 31459104984가 PASS했고 junhee는 clean하다. 현재 agent_workflow는 stale local ledger의 terminal status를 full preflight에서 먼저 거부해 --ff-only-dev가 실행되지 않으며, Gate planned-path의 junhee ledger-only 예외가 실제 role-scope에는 없어 CI 31458984632가 불필요하게 실패했다. merge preflight는 origin source SHA·terminal CI가 고정돼도 등록된 clean local source worktree를 강제해 반복 임시 clone을 유발한다. 기존 parser·Git·gh만 재사용해 세 병목을 최소 교정한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R1-W5-F29@2d805bf
CONTRACT_VERSION=AGENT-WORKFLOW-v1.1.0-DRAFT; GATE-SCOPE-v1.1.2-DRAFT; MERGE-PREFLIGHT-v1.1.0-DRAFT
ALLOWED_PATHS=.github/scripts/agent_workflow.py; .github/scripts/gate_scope.py; .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py; tests/integration/test_agent_workflow.py; tests/integration/test_gate_scope.py; tests/integration/test_merge_preflight.py; AGENTS.md; docs/markdown/collaboration/README.md; docs/markdown/collaboration/Gate_실행_카드_원장.md; handoffs/R1-W5-F29.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=.github/workflows/**; .github/scripts/agent_workflow.py·gate_scope.py 외 scripts/**; .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py 외 skills/**; docs/markdown/collaboration/archive/**; docs/markdown/02_WBS.md; app/**; infrastructure/**; src/**; R2~R5 보고·handoff·제품 경로; dependency·secret
HANDOFF_MANIFEST=handoffs/R1-W5-F29.json
ACCEPTANCE_CRITERIA=--ff-only-dev는 current branch·clean·origin/dev ancestor 조건만 먼저 검사하고 stale local ledger의 terminal status와 contract 오류 때문에 안전한 fast-forward를 막지 않는다. fast-forward 뒤 최신 원장으로 full preflight를 정확히 한 번 다시 실행하며 dirty·diverged·branch mismatch는 변경 없이 차단한다. junhee의 exact Gate 원장 단일 변경은 ledger health가 PASS할 때만 실제 role-scope에서도 허용하고 다른 path·role·원장 불일치는 계속 차단한다. dev 병합 batch preflight는 origin/<source> SHA와 그 SHA의 terminal source CI가 PASS하면 등록 local source worktree 없이 remote-only evidence를 허용하되, local source ref/worktree가 존재하면 불일치·dirty를 계속 fail-closed한다. 최종 source branch sync는 별도 optional 단계로 유지한다. AGENTS와 협업 README는 역할 작업 시작을 agent_workflow 단일 명령으로 통일하고 개별 bootstrap·planned-path 명령은 진단 fallback으로만 남긴다. 새 dependency·daemon·state service를 추가하지 않는다.
ACCEPTANCE_IDS=AC1_STALE_FF_FIRST;AC2_POST_FF_FULL_PREFLIGHT;AC3_DIRTY_DIVERGED_FAIL_CLOSED;AC4_LEDGER_ONLY_SCOPE;AC5_LEDGER_HEALTH;AC6_REMOTE_SOURCE_EVIDENCE;AC7_LOCAL_EVIDENCE_FAIL_CLOSED;AC8_SINGLE_START_INSTRUCTION;AC9_NO_NEW_TOOLING
TEST_COMMANDS=python -m unittest tests.integration.test_agent_workflow tests.integration.test_gate_scope tests.integration.test_merge_preflight -v; python -m unittest discover -s tests/integration -p 'test_*.py'; stale terminal ledger→ff-only→READY preflight synthetic; dirty/diverged negative; junhee ledger-only role-scope healthy/unhealthy; remote-only source SHA+CI PASS·missing/failure/local dirty negatives; python -m compileall -q .github/scripts/agent_workflow.py .github/scripts/gate_scope.py .agents/skills/merge-branch-to-dev/scripts/check_merge_preflight.py tests/integration; document policy AGENTS.md·README·Gate 원장; gate_scope preflight·11 planned paths·merge-base; git diff --check; junhee source CI
TEST_COMMAND_IDS=T1_AUTOMATION_TARGET;T2_INTEGRATION_FULL;T3_STALE_FF;T4_SYNC_NEGATIVE;T5_LEDGER_ONLY;T6_REMOTE_SOURCE;T7_COMPILE;T8_DOCUMENT_POLICY;T9_SCOPE;T10_DIFF;T11_BRANCH_CI
STOP_CONDITIONS=fast-forward 전에 dirty·diverged branch mutation; ledger health 실패를 허용; junhee 외 role 또는 Gate 원장 외 path 예외; source CI가 SHA와 불일치·missing·failure인데 remote-only 허용; 존재하는 local source의 drift·dirty 무시; 자동 fetch·push·reset·rebase·stash·conflict resolution 추가; workflow·dependency·제품 경로 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=origin read-only fetch·CI 조회, 허용 경로 commit·junhee push·branch CI만 허용한다. 테스트용 임시 Git directory는 test cleanup 범위에서만 허용한다. dev merge·다른 역할 branch push·workflow dispatch·ACL·환경 변경은 금지한다.
AUTO_FAIL_CONDITIONS=stale ledger가 안전한 ff-only를 계속 차단; Gate-only 범위가 exact 원장 1경로보다 넓음; remote-only가 failed/mismatched CI를 허용; local dirty evidence 무시; 지침에 서로 다른 필수 시작 절차 잔존; scope·필수 검증 FAIL
R1_REVIEW_CONDITIONS=세 회귀가 실제·synthetic test에서 fail-closed 경계를 유지하고 협업 지침이 단일 시작 명령으로 정렬되며 source CI가 PASS한 뒤 dev 통합한다.
```

### R2 · R2-W5-F5

```text
STATUS=PLANNED
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F5
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=DataHub v1.7 runtime health and exact Binding evidence
TASK_CARD_RANGE=R2-11·19 live Binding PASS evidence
CURRENT_TASK_CARD_ID=N/A — R1-W5-F6 RAM 8GB 조건 선행
BASE_BRANCH=dev
BASE_SHA=N/A — runtime 실행 직전 최신 dev SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=N/A — 기존 R2 runtime evidence 카드의 후속 evidence-only 범위로 재발행
FORBIDDEN_PATHS=다른 Docker project; volume reset; DDL·seed; backend/AI/frontend; secret
ACCEPTANCE_CRITERIA=DataHub v1.7을 안전 기동한 뒤 exact URN/FQN/column/lineage와 Binding verified_at·hash를 실제 PASS로 갱신한다. 대표 E2E의 interim versioned binding과 live DataHub 결과가 같은 asset identity인지 비교한다.
STOP_CONDITIONS=host free RAM 8GB 미만; 다른 project 변경 필요; runtime health/system-update 실패; secret 출력; scope 밖 변경
R1_REVIEW_CONDITIONS=현재 live 모드는 계속 fail-closed이며 R3/R4 제품 보완과 병렬로 실제 runtime을 시작하지 않는다.
```

### R3 · R3-W5-F8

```text
STATUS=READY
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F8
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=Node3 schema hardening; captured Base·LoRA comparability; split integrity; release-readiness DRAFT
TASK_CARD_RANGE=R3-06·09·10·14 Node3 metric selection 계약과 ModelOps 검증 증거 정합화
CURRENT_TASK_CARD_ID=R3-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=ef2c37186947b7b907278485b59f0d2854dcbc4f
START_POINT=clean daesung을 최신 dev Gate v5.47로 ff-only 동기화하고 repository-global stash는 적용·삭제하지 않는다. 번호 순서대로 Node3 schema hardening을 먼저 끝낸 뒤 captured evidence·split·release-readiness 검증으로 진행한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R3-W5-F8@ef2c371
CONTRACT_VERSION=MODEL-v1.1.0-NODE3-DRAFT; MODELOPS-I5-READINESS-v1.0.0-DRAFT
ALLOWED_PATHS=src/ai/contracts/node_io.v0.1.json; src/ai/node3.py; src/ai/fake_model.py; tests/ai/test_node3.py; tests/ai/test_fake_model.py; tests/ai/test_contracts.py; evals/base_comparison.v0.1.json; evals/split_manifest.v0.1.json; evals/validation_v2.manifest.json; src/ai/training/benchmark_serving.py; src/ai/training/dataset.py; src/ai/training/evaluate_endpoint.py; src/ai/training/evaluate_lora.py; src/ai/training/verify_case_specs.py; src/modelops/model_decision.v0.1.json; src/modelops/model_candidate.instruct2507.v0.1.json; src/modelops/serving_manifest.v0.1.json; src/modelops/runtime.py; src/modelops/release_candidate.i5.v1.json; tests/ai/test_model_decision.py; tests/ai/test_serving_benchmark.py; tests/ai/test_training_dataset.py; tests/ai/test_training_verification.py; tests/ai/test_validation_v2.py; tests/ai/test_eval_runner.py; tests/ai/test_wave3.py; handoffs/R3-W5-F8.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; Node2·prompt serving; compiled 1,350 dataset·Gold·acceptance 내용 재생성; root Compose·CI; dependency; RunPod·외부 endpoint·model download; secret
HANDOFF_MANIFEST=handoffs/R3-W5-F8.json
ACCEPTANCE_CRITERIA=Node3 multi-source request는 selected_metric_id·source별 context_metric_ids를 schema에서 명시하고 selected derived metric 하나와 entitlement를 exact 검증하며 missing·multi·different·outside-entitlement·source-count mismatch를 fail-closed한다. 6-asset G120-046 backend-shaped fixture는 통과하고 source·masking·sampling·partial·result reference를 보존하며 question·row·첫 metric에서 추정하지 않는다. 이어서 Base·LoRA·serving 비교는 immutable captured evidence의 model/prompt/case-set/decoding/runtime·artifact hash가 같은 경우만 comparable로 판정하고 accuracy·p50·p95·VRAM·nullable cost를 observed 값으로만 기록한다. train·validation·gold·acceptance의 case ID·paraphrase group·join graph 누수를 검증하며 기존 typed 결손은 NOT_READY로 기록하고 자동 재생성하지 않는다. release candidate manifest는 DRAFT/NOT_READY이고 제품 기본값 Base·SQL LoRA disabled를 유지한다.
ACCEPTANCE_IDS=AC1_NODE3_SCHEMA;AC2_ENTITLEMENT_FAIL_CLOSED;AC3_BACKEND_SHAPED_FIXTURE;AC4_CAPTURED_COMPARABILITY;AC5_SPLIT_INTEGRITY;AC6_TRACE_REPRO;AC7_RELEASE_NOT_READY;AC8_OWNER_BOUNDARY
TEST_COMMANDS=관련 JSON json.tool; python -m pytest -p no:cacheprovider tests/ai/test_node3.py tests/ai/test_fake_model.py tests/ai/test_contracts.py -q; python -m pytest -p no:cacheprovider tests/ai/test_model_decision.py tests/ai/test_serving_benchmark.py tests/ai/test_training_dataset.py tests/ai/test_training_verification.py tests/ai/test_validation_v2.py tests/ai/test_eval_runner.py tests/ai/test_wave3.py -q; python -m pytest -p no:cacheprovider tests/ai -q; python -m compileall -q src/ai src/modelops evals; deterministic manifest/hash 검증; gate_scope bootstrap·planned-path·merge-base; git diff --check; daesung source CI
TEST_COMMAND_IDS=T1_JSON;T2_NODE3;T3_MODELOPS;T4_AI;T5_COMPILE;T6_HASH;T7_SCOPE;T8_DIFF;T9_BRANCH_CI
STOP_CONDITIONS=latest dev ff-only 불가·dirty·stash touch 필요; backend/data 변경 필요; compiled dataset·Gold 의미 변경·자동 재생성 필요; captured hash 불일치나 누수를 숨겨야 진행 가능; Base→LoRA 기본 전환·release freeze 주장; RunPod·외부 endpoint·model download·비용·secret; dependency·scope·필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local captured artifact read-only 검증과 허용 경로 commit·daesung push·branch CI만 승인한다. 외부 endpoint·RunPod·model download·비용·secret·배포는 금지한다.
AUTO_FAIL_CONDITIONS=metric 임의 선택; incomparable 결과 비교; 누수 은폐; 과거 evidence를 live PASS로 승격; LoRA 기본 전환; stash 변경; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=Node3 schema producer와 ModelOps DRAFT evidence를 각각 확인한다. actual API PASS는 R4-W5-F11 consumer와 R1 runtime E2E가 통합된 뒤에만 판정한다.
```

### R2 · R2-W5-F8

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F8
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=F6 inherited checkpoint scope correction and F7 terminal CI
TASK_CARD_RANGE=R2-W5-F6·F7 inherited 제품 증거 인정과 terminalization only
CURRENT_TASK_CARD_ID=R2-W5-F7-SCOPE-CORRECTION
REPOSITORY_ROOT=C:\Users\Playdata\Downloads\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=616f16e6c6620b0e3e4058c586c440d6767662ab
START_POINT=origin/seung f7f8514b5c203949622c8e31946ec5f298190cb7과 CI 31448012065의 role-scope-only failure를 고정한다. 제품 8경로는 F6 source CI가 통과했고 7c4164b와 f7f8514 blob이 8/8 동일한 inherited checkpoint로 인정한다. 최신 origin/dev를 non-ff merge한 뒤 F7·F8 handoff evidence만 교정한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R2-W5-F8@616f16e
CONTRACT_VERSION=I5-SEMANTIC-CATALOG-v1.0.0-DRAFT; R2-INHERITED-CHECKPOINT-v1.0.0
INHERITED_CHECKPOINT_PATHS=infrastructure/database/datahub/compose.consumer.yml; infrastructure/database/datahub/publish_semantic_catalog.py; infrastructure/database/datahub/verify_semantic_catalog.py; infrastructure/database/sql/ddl/03_hotel_crm_sqlserver.sql; infrastructure/database/trino/etc/access-control-rules.json; src/data/serving_analytics_contract.i4.v1.json; src/data/serving_semantic_catalog.i4.v1.json; tests/data/test_serving_semantic_catalog.py
OTHER_READ_ONLY_EVIDENCE_PATHS=docs/markdown/daily_reports/seung/일일보고.md; handoffs/R2-W5-F6.json
MUTABLE_PATHS=handoffs/R2-W5-F7.json; handoffs/R2-W5-F8.json
ALLOWED_PATHS=infrastructure/database/datahub/compose.consumer.yml; infrastructure/database/datahub/publish_semantic_catalog.py; infrastructure/database/datahub/verify_semantic_catalog.py; infrastructure/database/sql/ddl/03_hotel_crm_sqlserver.sql; infrastructure/database/trino/etc/access-control-rules.json; src/data/serving_analytics_contract.i4.v1.json; src/data/serving_semantic_catalog.i4.v1.json; tests/data/test_serving_semantic_catalog.py; docs/markdown/daily_reports/seung/일일보고.md; handoffs/R2-W5-F6.json; handoffs/R2-W5-F7.json; handoffs/R2-W5-F8.json
FORBIDDEN_PATHS=INHERITED_CHECKPOINT_PATHS와 OTHER_READ_ONLY_EVIDENCE_PATHS 내용 수정; app/**; src/ai/**; root Compose·env·CI; 다른 tests; dependency; Docker lifecycle; stash·Git object; secret
HANDOFF_MANIFEST=handoffs/R2-W5-F8.json
RESULT_SHA=ceb9ab3bf9d9746a4905c9a265eb03034ab0ed9e
RESULT_CI=branch 31452376643 PASS
ACCEPTANCE_CRITERIA=origin/seung f7f8514의 inherited 제품 8경로 blob hash와 일일보고·F6 handoff가 작업 전후 exact 일치한다. 최신 dev ancestry를 병합하고 F7 handoff의 CHANGED_FILES를 자기 manifest 제외 실제 10경로로 교정하며 T11에 CI 31448012065 scope FAIL을 사실대로 기록하고 F8 supersede를 명시한다. F8 handoff는 inherited 8경로·read-only 2경로·mutable 2경로·local target/data/integration PASS를 구분하며 terminal CI를 push 전에 PASS로 주장하지 않는다. 제품 재구현·stash 적용·history rewrite 없이 최종 seung를 한 번만 push하고 clean·local/origin 0/0을 확인한다.
ACCEPTANCE_IDS=AC1_INHERITED_HASH;AC2_LATEST_DEV_ANCESTRY;AC3_REPORT_HANDOFF_PRESERVED;AC4_SCOPE_CAUSE_RECORDED;AC5_LOCAL_TESTS;AC6_SINGLE_CORRECTIVE_PUSH;AC7_TERMINAL_CI
TEST_COMMANDS=12개 planned-path; inherited 8경로 pre/post git hash-object exact 비교; clean bootstrap; F6/F7/F8 json.tool; python -m pytest -p no:cacheprovider tests/data/test_serving_semantic_catalog.py -q; python -m pytest -p no:cacheprovider tests/data -q; python -m pytest -p no:cacheprovider tests/integration -q; docker compose -f infrastructure/database/datahub/compose.consumer.yml config; gate_scope merge-base; git diff --check; f7f8514·616f16e ancestry; clean·ahead/behind 0/0; seung terminal CI
TEST_COMMAND_IDS=T1_PLANNED;T2_INHERITED_HASH;T3_BOOTSTRAP;T4_JSON;T5_TARGET;T6_DATA;T7_INTEGRATION;T8_COMPOSE;T9_SCOPE;T10_DIFF;T11_ANCESTRY;T12_BRANCH_CI
STOP_CONDITIONS=origin/seung f7f8514 drift; inherited 8경로 hash 또는 read-only evidence 변경; 허용 경로 밖 conflict/변경; 제품 재구현 필요; reset·rebase·force push·stash apply/drop/clear·중간 push 필요; Docker lifecycle·외부 전송·비용·secret; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=최신 origin/dev non-ff merge, F7·F8 handoff 교정, 검증 뒤 seung corrective push 1회와 source CI만 승인한다. inherited 제품·read-only evidence·stash·Docker·외부 서비스·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=inherited product 또는 read-only evidence drift; scope 원인을 제품 실패로 왜곡; history 손실; 중간 push; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=F8 terminal CI PASS와 inherited hash 불변·최신 dev ancestry·clean 0/0을 확인하면 F6/F7/F8을 한 묶음으로 dev 통합한다.
```

### R4 · R4-W5-F10

```text
STATUS=PLANNED
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F10
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=Metadata·Context Registry scope decision
TASK_CARD_RANGE=R4-06·07·15·18 Context Registry runtime proposal decomposition
CURRENT_TASK_CARD_ID=N/A — R4-W5-F3·F4와 R2 runtime producer 선행
BASE_BRANCH=dev
BASE_SHA=N/A — 선행 계약 통합 SHA로 발행
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=N/A — migration revision·OpenAPI·R2 producer 계약 확정 뒤 owner path로 분리 발행
FORBIDDEN_PATHS=D:\bootcamp 미추적 사용자 변경 자동 채택·덮어쓰기·삭제; 기존 migration; infrastructure 원본 DDL; src/data/**; src/ai/**; frontend; root Compose/env/CI; dependency; secret
ACCEPTANCE_CRITERIA=제안된 live DataHub∩PUBLISHED release∩ACTIVE binding∩entitlement 교집합과 Context Package 불변 저장은 제품 계약 결정 뒤 최소 카드로 분리한다. 현재 R2 runtime NOT_RUN, unknown revision F4 미검증, migration revision·OpenAPI 계약 미확정 상태에서는 schema·trigger·repository·service·error contract를 한 번에 구현하지 않는다. D:\bootcamp의 dirty·untracked 파일은 사용자 작업으로 보존하고 이 저장소 산출물로 간주하지 않는다.
STOP_CONDITIONS=R4-W5-F3·F4 미통합; R2 live runtime/metadata producer 미검증; migration revision·OpenAPI 계약 미확정; 외부 작업공간 사용자 변경 필요; cross-owner 파일 변경; 실제 DB·secret·dependency 필요
R1_REVIEW_CONDITIONS=Google Docs의 대규모 R4-W5-F3 요청은 번호 충돌과 미충족 선행조건 때문에 제안 그대로 반려한다. F3 binding 정합성→F4 native Alembic 경계→R2 live producer 판정 후 Context Registry를 migration·repository/API 소비자로 나눈 별도 카드만 검토한다.
```

### R4 · R4-W5-F12

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F12
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=Context Registry service-only contract and actual Node3 metric-selection consumer
TASK_CARD_RANGE=R4-W5-F10A·F10B Context Registry additive schema·checksum repository; R4-13 multi-source Node3 consumer REWORK
CURRENT_TASK_CARD_ID=R4-W5-F10A
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=9cdb906a67ee37b1e5cb5bcb34a4f898d300a93e
START_POINT=origin/jaehong 417a6faa5b2077c38d373620d314d9c84dc6187d의 제품 SHA f481f9123a683da7f61258f286dd2658828b00bc와 실패 CI 31451536556을 history 그대로 보존한다. 실패는 제품 test가 아니라 기존 F12 밖 F10C·F10D 경로와 handoff REVIEW 때문에 role-scope에서 발생했다. 최신 origin/dev 9cdb906을 non-ff merge한 뒤 이 재발행 범위로 scope와 제품 회귀를 함께 교정한다. reset·rebase·force push·stash 적용/삭제는 금지한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F12@9cdb906
CONTRACT_VERSION=CONTEXT-REGISTRY-v1.0.0-DRAFT; internal service plus existing /analysis path integration
ALLOWED_PATHS=app/backend/README.md; app/backend/app/adapters/analysis_repository.py; app/backend/app/adapters/context_registry_repository.py; app/backend/app/adapters/contract_model.py; app/backend/app/adapters/i2_data_platform.py; app/backend/app/api/router.py; app/backend/app/context_registry_contracts.py; app/backend/app/services/analysis_responses.py; app/backend/app/services/analysis_service.py; app/backend/app/services/context_registry_service.py; app/backend/app/services/readiness.py; app/backend/compose.fragment.yml; app/backend/migrations/versions/20260811_07_context_registry.py; tests/backend/test_analysis_persistence.py; tests/backend/test_analysis_pipeline.py; tests/backend/test_context_registry.py; tests/backend/test_http_runtime.py; tests/backend/test_i2_data_platform.py; tests/backend/test_migration_compatibility.py; tests/backend/test_production_model.py; tests/backend/test_readiness.py; handoffs/R4-W5-F12.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=app/backend/app/main.py; app/backend/contracts/openapi.v0.1.json; 기존 migration; infrastructure/**; src/data/**; src/ai/**; frontend; root Compose·env·CI; Report worker·schedule·Audit; dependency·secret
HANDOFF_MANIFEST=handoffs/R4-W5-F12.json
RESULT_SHA=d4a75d4de58e5d97c28b7622394caf7eaba62e27
RESULT_CI=branch 31453405302 PASS
ACCEPTANCE_CRITERIA=20260811_07은 20260810_06의 additive child이고 single head를 유지한다. Context checksum·idempotency·release 불변 계약과 승인 metric_selection fail-closed를 보존한다. F10C는 existing /analysis 경로 안에서 DataHub health·PUBLISHED/ACTIVE·승인 URN/FQN/column·entitlement를 모두 확인한 뒤만 live Context를 조립하며 versioned 또는 missing 상태를 live PASS로 승격하지 않는다. F10D는 기존 request/query/artifact repository를 재사용해 G3 뒤 결과만 영속화하고 public OpenAPI operation을 추가하지 않는다. G120-046 exact question과 2026-05-01~2026-07-01 bindings는 실제 Trino에서 2행·475972400.00·hash de17b5a22c6718c6e77e37936421c94618945dd31b0c7207f40e51d51b667716을 반환하고 같은 request_id/trace에 table·chart·explanation·artifact를 연결한다. 399088800 결과는 다른 exact question·Context·SQL/result hash가 입증되지 않으면 Gold PASS로 기록하지 않는다. Report manual command queued는 허용하되 worker/run 생성 성공은 주장하지 않는다. F12 handoff는 CI 31451536556 실패를 PASS로 쓰지 않고 이번 corrective CI로 supersede한다.
ACCEPTANCE_IDS=AC1_ADDITIVE_HEAD;AC2_REGISTRY_INVARIANTS;AC3_LIVE_CONTEXT_FAIL_CLOSED;AC4_EXISTING_ANALYSIS_PATH;AC5_G3_BEFORE_PERSIST;AC6_NODE3_SELECTION;AC7_G120_GOLD_EXACT;AC8_TABLE_CHART_EVIDENCE;AC9_HISTORICAL_CI_ACCURACY;AC10_REPORT_QUEUED_ONLY
TEST_COMMANDS=context registry·analysis persistence·pipeline·HTTP·I2 adapter·readiness target tests; migration graph single head; isolated empty→head·20260810_06→head; idempotency·immutability·PUBLISHED/ACTIVE/entitlement·URN/FQN/column mismatch negative; unauthorized join·missing filter·repair exactly once·timeout/cancel·empty·masking negative; actual G120-046 HTTP→Trino→G3→artifact Gold row/total/hash exact; Report queued-only contract; backend 전체 Python 3.12 test container; python app/backend/scripts/export_openapi.py --check; python -m compileall -q app/backend; gate_scope bootstrap·전체 planned-path·merge-base; git diff --check; jaehong corrective source CI
TEST_COMMAND_IDS=T1_TARGET;T2_HEAD;T3_MIGRATION;T4_NEGATIVE;T5_NODE3_COMPOSITION;T6_BACKEND;T7_OPENAPI_UNCHANGED;T8_COMPILE;T9_SCOPE;T10_DIFF;T11_BRANCH_CI
STOP_CONDITIONS=기존 migration·OpenAPI operation 변경 필요; DataHub PUBLISHED/ACTIVE/entitlement를 확인할 수 없음; canonical Gold 불일치; 399088800을 G120-046으로 재명명; Report worker 성공 위조; frontend·R2/R3/R5/root 변경; dependency·secret·다른 project/volume 변경; scope·필수 검증 실패
EXTERNAL_ACTION_PERMISSION=현재 answervice 전용 backend·app-postgres와 기존 healthy Trino/DataHub에 대한 read-only health/query 검증, 전용 ephemeral PostgreSQL migration, Python 3.12 일회성 test container, 허용 경로 corrective commit·jaehong push·source CI를 승인한다. seed·volume·다른 project/container·firewall·secret·외부 전송·비용 변경은 금지한다.
AUTO_FAIL_CONDITIONS=기존 migration 수정; duplicate head; checksum client 신뢰; released payload mutation; unverified live PASS; Gold row/total/hash 불일치; 실패 CI를 PASS 기록; Report worker fake success; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=corrective source CI가 전체 제품 job까지 PASS하고 F12 handoff가 실제 diff·실패/성공 CI를 정확히 기록해야 한다. R1은 canonical G120-046 HTTP table·chart·explanation·artifact와 DataHub/Trino provenance를 재검증한 뒤에만 dev 통합한다.
```

### R4 · R4-W5-F16

```text
STATUS=READY
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F16
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=AUTH-TRUST-v1.0.0-DRAFT server-owned principal and HTTP security scheme
TASK_CARD_RANGE=R4-16 Analysis·Report 공통 authentication·authorization trust boundary REWORK
CURRENT_TASK_CARD_ID=R4-16-AUTH-TRUST
BASE_BRANCH=dev
BASE_SHA=2d805bf9cc52828b567e17e182fd88a8895a0b57
START_POINT=R4-W5-F12가 dev에 통합되고 dev CI 31456536103 및 Gate 발행 CI 31456640689가 PASS했다. clean jaehong이 origin/dev 2d805bf와 일치하는 상태에서 preflight와 전체 planned-path 검사를 통과한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F16@2d805bf
CONTRACT_VERSION=AUTH-TRUST-v1.0.0-DRAFT; existing OPENAPI-v1.0.0
ALLOWED_PATHS=app/backend/app/auth.py; app/backend/app/context.py; app/backend/app/main.py; app/backend/compose.fragment.yml; app/backend/contracts/openapi.v0.1.json; app/backend/README.md; tests/backend/test_auth_context.py; tests/backend/test_http_runtime.py; tests/backend/test_openapi_contract.py; handoffs/R4-W5-F16.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=compose.yml; .env; .env.example; app/backend/requirements.txt; app/backend/Dockerfile; migrations/**; infrastructure/**; src/data/**; src/ai/**; frontend; Report worker·Audit·SQLGlot; dependency; real secret·token
HANDOFF_MANIFEST=handoffs/R4-W5-F16.json
ACCEPTANCE_CRITERIA=release auth mode는 server-owned principal file을 사용한다. AUTH_PRINCIPALS_FILE은 raw Bearer token이 아니라 token SHA-256 digest, subject UUID, Role, not_before, expires_at만 가진다. Authorization Bearer를 서버가 digest와 constant-time 비교해 principal로 해석하며 X-User-Id·X-Role은 신뢰하지 않고 값이 있으면 server principal과 불일치를 403으로 차단한다. test mode는 명시적 AUTH_MODE=test에서 synthetic principal만 허용하고 release·default에서 자동 fallback하지 않는다. missing·empty·unknown·expired·not-yet-valid token, duplicate digest, invalid UUID/role, unreadable·malformed mapping은 각각 401/403/503으로 fail-closed한다. as_of·timezone·trace_id·contract version은 기존 검증을 유지한다. Analysis와 Report가 같은 RequestContext dependency를 사용하며 raw token·digest·principal file·stack trace를 log·response·artifact·audit에 노출하지 않는다. OpenAPI는 HTTP Bearer security scheme와 server-owned identity를 표현하고 X-User-Id·X-Role을 필수 identity 입력으로 광고하지 않는다. OIDC/JWT·외부 IdP는 별도 R1 결정 전 구현하지 않는다.
ACCEPTANCE_IDS=AC1_SERVER_OWNED_PRINCIPAL;AC2_NO_CLIENT_ROLE_TRUST;AC3_TIME_BOUNDS;AC4_FAIL_CLOSED_MAPPING;AC5_EXPLICIT_TEST_MODE;AC6_SHARED_CONTEXT;AC7_NO_SECRET_EXPOSURE;AC8_OPENAPI_SECURITY;AC9_COMPATIBILITY
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend/test_auth_context.py tests/backend/test_http_runtime.py tests/backend/test_openapi_contract.py -q; token missing·unknown·expired·future·duplicate·invalid role·malformed file·X header mismatch negative; Analysis·Report positive/403/503 and request_id·trace_id preservation; python -m pytest -p no:cacheprovider tests/backend -q in approved Python 3.12 test container; python app/backend/scripts/export_openapi.py --check; python -m compileall -q app/backend; gate_scope preflight·전체 planned paths·merge-base; git diff --check; jaehong source CI
TEST_COMMAND_IDS=T1_AUTH_TARGET;T2_NEGATIVE_MATRIX;T3_ANALYSIS_REPORT;T4_BACKEND;T5_OPENAPI;T6_COMPILE;T7_SCOPE;T8_DIFF;T9_BRANCH_CI
STOP_CONDITIONS=실제 token·secret을 tracked file/env/log에 기록; client header role 신뢰 유지; release에서 test fallback; custom JWT/OIDC 또는 dependency 추가 필요; root Compose·env·migration·R2/R3/R5 변경 필요; raw token·digest 노출; 기존 G1·G2·G3·Context 의미 변경; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=ephemeral synthetic principal file을 test container에 read-only mount하는 검증, 허용 경로 commit·jaehong push·source CI만 허용한다. 실제 credential·외부 IdP·network call·root secret mount·배포는 금지한다.
AUTO_FAIL_CONDITIONS=임의 Bearer 문자열 수용; X-Role·X-User-Id 자칭 성공; expired/unknown token 성공; malformed mapping fail-open; release test fallback; secret 노출; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=source CI와 Python 3.12 backend 전체 회귀에서 Analysis·Report가 동일 server principal을 사용하고 client-owned identity가 차단되며 OpenAPI가 실제 security contract와 일치할 때만 dev 통합한다. root secret mount·OIDC/JWT 채택은 별도 R1 카드로 남긴다.
```

### R5 · R5-W5-F2

```text
STATUS=PLANNED
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W5-F2
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=OPENAPI-AUDIT-v1.0.0-DRAFT producer merged dev and screen approval
TASK_CARD_RANGE=R5-15 SCR-AUD-001·SCR-AUD-002 Operations·Audit read-only trace UI
CURRENT_TASK_CARD_ID=N/A — R4 audit producer와 R1 route 승인 뒤 발행
BASE_BRANCH=dev
BASE_SHA=N/A — audit producer 통합 SHA로 발행
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=app/enterprise-react/src/App.jsx; app/enterprise-react/src/components/layout/AppSidebar.jsx; app/enterprise-react/src/pages/AuditPage.jsx; app/enterprise-react/src/api/auditClient.ts; app/enterprise-react/src/contracts/audit.ts; app/enterprise-react/src/routing.js; app/enterprise-react/src/styles.css; tests/frontend/contracts.test.mjs; handoffs/R5-W5-F2.json; docs/markdown/daily_reports/minji/일일보고.md
FORBIDDEN_PATHS=backend/OpenAPI producer; schedule/worker; root Compose/env/CI; package/dependency; P2 Tool/customer360; role mutation; raw secret·SQL·parameter·result; 승인되지 않은 route/screen
ACCEPTANCE_CRITERIA=R1이 SCR-AUD-001/002와 /operations/audit·/operations/audit/:requestId를 명시 승인하고 R4 read-only list/detail OpenAPI가 dev에 통합된 뒤에만 구현한다. production은 typed HTTP client를 기본으로 하고 fixture는 명시 mode만 허용하며 오류 fallback·가짜 trace를 금지한다. 서버의 masked user·request_id·기간·상태와 context release→model/policy→query_id→artifact/report 연결을 재계산 없이 표시하고 401·403·404·422·503 및 empty/loading/partial/error를 구분한다. raw SQL·parameter·result·secret·stack trace를 노출하지 않고 keyboard·focus·aria·360~1440px·200% zoom을 검증한다.
STOP_CONDITIONS=R4 audit OpenAPI 미통합; R1 화면/route 미승인; backend/schema 변경 필요; role mutation·민감 정보 필요; fake success/fallback 필요; package/dependency·외부 network 필요; scope/필수 검증 실패
R1_REVIEW_CONDITIONS=현재 R5 READY 카드는 없고 schedule UI는 R4 worker/schedule producer가 없어 발행하지 않는다. Audit producer 통합 뒤에만 최신 BASE_SHA와 token으로 READY 전환한다.
```

### R5 · R5-W5-F4

```text
STATUS=READY
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W5-F4
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=frontend build-time backend base wiring and explicit LAN opt-in
TASK_CARD_RANGE=R5-01 Agent·Report 공통 backend base build wiring 및 fail-closed 회귀
CURRENT_TASK_CARD_ID=R5-01
REPOSITORY_ROOT=C:\Users\nowis\Desktop\SKN\Final_project
BASE_BRANCH=dev
BASE_SHA=15270f9
START_POINT=external clone의 clean minji ece70e3026c20669adb620d8f964424fb94054cf와 local-only commits 1fd9701·96f0b74·ece70e3을 history 그대로 보존한다. fetch 뒤 latest origin/dev 15270f9를 non-ff merge한다. 관측 base f5387b7 이후 latest dev까지 아래 inherited frontend 15경로 overlap은 0이므로 conflict가 없을 때만 진행하고, conflict·추가 dirty·ref drift가 있으면 중단한다. reset·rebase·force push·stash 적용/삭제는 금지한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R5-W5-F4@15270f9
CONTRACT_VERSION=FRONTEND-BACKEND-BASE-v1.0.0-DRAFT; existing Analysis·Report HTTP clients
ALLOWED_PATHS=app/enterprise-react/Dockerfile; app/enterprise-react/compose.fragment.yml; app/enterprise-react/src/App.jsx; app/enterprise-react/src/api/analysisClient.ts; app/enterprise-react/src/api/reportClient.ts; app/enterprise-react/src/components/analysis/AnalysisStatePanel.tsx; app/enterprise-react/src/components/layout/AppHeader.jsx; app/enterprise-react/src/components/layout/AppSidebar.jsx; app/enterprise-react/src/data/analysisFixtures.ts; app/enterprise-react/src/pages/AgentPage.jsx; app/enterprise-react/src/pages/CatalogPage.jsx; app/enterprise-react/src/pages/ConnectionsPage.jsx; app/enterprise-react/src/pages/ReportsPage.jsx; app/enterprise-react/src/styles.css; app/enterprise-react/vite.config.js; tests/frontend/contracts.test.mjs; handoffs/R5-W5-F4.json; docs/markdown/daily_reports/minji/일일보고.md
INHERITED_LOCAL_HISTORY_PATHS=app/enterprise-react/compose.fragment.yml; app/enterprise-react/src/App.jsx; app/enterprise-react/src/api/analysisClient.ts; app/enterprise-react/src/api/reportClient.ts; app/enterprise-react/src/components/analysis/AnalysisStatePanel.tsx; app/enterprise-react/src/components/layout/AppHeader.jsx; app/enterprise-react/src/components/layout/AppSidebar.jsx; app/enterprise-react/src/data/analysisFixtures.ts; app/enterprise-react/src/pages/AgentPage.jsx; app/enterprise-react/src/pages/CatalogPage.jsx; app/enterprise-react/src/pages/ConnectionsPage.jsx; app/enterprise-react/src/pages/ReportsPage.jsx; app/enterprise-react/src/styles.css; app/enterprise-react/vite.config.js; tests/frontend/contracts.test.mjs
MUTABLE_PATHS=app/enterprise-react/Dockerfile; app/enterprise-react/compose.fragment.yml; tests/frontend/contracts.test.mjs; handoffs/R5-W5-F4.json; docs/markdown/daily_reports/minji/일일보고.md
FORBIDDEN_PATHS=compose.yml; .env; .env.example; app/backend/**; app/enterprise-react/src/contracts/**; package*.json; root CI; firewall; 다른 project/container/volume; dependency; secret
HANDOFF_MANIFEST=handoffs/R5-W5-F4.json
ACCEPTANCE_CRITERIA=Dockerfile build stage는 ARG VITE_BACKEND_BASE_URL=http://127.0.0.1:18000과 동일 ENV를 npm run build 전에 선언하고 compose build.args는 ${VITE_BACKEND_BASE_URL:-http://127.0.0.1:18000}만 전달한다. 기본 build는 loopback을 유지하고 LAN은 FRONTEND_BIND_ADDRESS=0.0.0.0과 VITE_BACKEND_BASE_URL=http://<명시적-LAN-IP>:18000을 함께 제공할 때만 사용한다. 0.0.0.0을 browser backend URL로 사용하거나 LAN IP를 자동 추론하지 않는다. Agent·Report는 기존 동일 base와 fallback을 유지하고 backend 실패를 mock·fixture·synthetic success로 자동 전환하지 않는다. token·secret·backend/OpenAPI/CORS/route/package를 변경하지 않는다.
ACCEPTANCE_IDS=AC1_BUILD_ARG_ENV;AC2_DEFAULT_LOOPBACK;AC3_EXPLICIT_LAN_OPT_IN;AC4_AGENT_REPORT_SAME_BASE;AC5_FAIL_CLOSED;AC6_NO_SECRET_OR_OWNER_BYPASS
TEST_COMMANDS=repository path·branch·HEAD·clean·local-only 3 commit inventory; fetch 후 f5387b7→latest dev의 inherited 15경로 overlap 0 재확인; origin/dev non-ff merge와 1fd9701·96f0b74·ece70e3 ancestry 보존; default와 explicit LAN compose config에서 build arg·host_ip 확인; node tests/frontend/contracts.test.mjs; npm --prefix app/enterprise-react run build; explicit LAN backend base 별도 build; Dockerfile ARG/ENV 순서·두 client 동일 env/default·자동 fallback 부재 contract test; gate_scope bootstrap·전체 planned-path·merge-base; git diff --check; minji corrective source CI. handoff는 merge commit을 RESULT_SHA로 기록하고 T8_BRANCH_CI=CI_PENDING으로 제출하며, 이전 CI 31454965937 FAILURE와 원인을 RESULT_CI·REQUESTED_DECISION에 보존한다. 카드 필수 검증이 아닌 Docker image build는 NOT_RUN·RESIDUAL_RISKS에서 제거하되 실행했다고 주장하지 않고 NOT_RUN=[]·RESIDUAL_RISKS=[]로 정합화한다.
TEST_COMMAND_IDS=T1_DEFAULT_CONFIG;T2_LAN_CONFIG;T3_FRONTEND_CONTRACT;T4_DEFAULT_BUILD;T5_LAN_BUILD;T6_SCOPE;T7_DIFF;T8_BRANCH_CI
STOP_CONDITIONS=exact external repo·HEAD·clean snapshot 불일치; local-only commit 유실; latest dev overlap 또는 merge conflict; inherited 15경로를 reconciliation 외 새 기능으로 확대; backend endpoint·CORS·OpenAPI/schema 변경 필요; 기본값을 loopback 밖으로 변경; LAN IP 자동 탐지·0.0.0.0 backend URL·wildcard CORS; backend 실패를 mock/fixture/synthetic success로 대체; secret/token build arg; root Compose/env/backend/package/dependency 변경; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=origin/minji 46e278b의 source CI 31454965937이 제품 scope가 아니라 handoff T8 NOT_RUN·NOT_RUN/RESIDUAL_RISKS 때문에 REVIEW_REQUIRED로 실패했으므로, exact clean external clone에서 fetch 후 latest origin/dev 473d014를 history-preserving non-ff merge하고 handoff만 교정한 뒤 minji corrective push 1회를 추가 승인한다. 중간 push·reset·rebase·force push·stash 조작·다른 project/container/volume·firewall·backend lifecycle·외부 배포·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=Agent·Report base 불일치; 명시 opt-in 없는 LAN 공개; production 자동 fixture/mock fallback; secret 노출; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=local-only 3 commits와 latest dev ancestry, inherited 15경로 overlap 0, F4 build wiring, source CI와 handoff를 확인한다. corrective push CI PASS를 R1이 원격 run으로 확인한 뒤에만 dev 통합하며 CI_PENDING은 terminal PASS가 아니다. backend runtime 실패는 R5가 우회하지 않고 R4 corrective 결과와 결합해 후속 판정한다.
```

### R1 · R1-W5-F23

```text
STATUS=PLANNED
ROLE_ID=R1
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F23
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R1-08 LAN Agent·Report actual browser smoke와 request trace
BASE_SHA=N/A — R5-W5-F4 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=tests/integration/**; handoffs/R1-W5-F23.json; docs/markdown/daily_reports/junhee/일일보고.md
ACCEPTANCE_CRITERIA=명시적 LAN frontend/backend URL에서 Agent·Report network request, exact CORS, fail-closed 오류와 request_id를 검증하며 3-source 성공은 실제 API가 성공할 때만 기록한다.
TEST_COMMANDS=default/LAN compose config; actual browser/network trace; allowed/denied preflight; integration 전체; scope; diff; CI
STOP_CONDITIONS=R5-W5-F4 미통합; firewall·secret·다른 project 변경; fixture success; 제품 변경 필요
```

### R2 · R2-W5-F9

```text
STATUS=READY
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F9
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=DataHub v1.7 isolated runtime·Semantic Catalog live publish/verify·Asset Binding evidence
TASK_CARD_RANGE=R2-09·10·11·19 DataHub 5-source ingestion·Semantic Catalog publish/verify·Binding live evidence
CURRENT_TASK_CARD_ID=R2-09
BASE_BRANCH=dev
BASE_SHA=26bc8feb0e954062c95f188b722b2b0dfb13d4ec
START_POINT=R2-W5-F8과 R4-W5-F12가 dev 26bc8fe에 통합되고 dev CI 31456536103이 PASS했다. clean seung이 origin/dev와 일치하는 상태에서 preflight·전체 planned-path 검사를 통과한 뒤 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W5-F9@26bc8fe
ALLOWED_PATHS=src/data/datahub_runtime_evidence.i5.v1.json; src/data/asset_binding_health.i5.v1.json; infrastructure/database/datahub/scripts/run-runtime-validation.ps1; infrastructure/database/datahub/publish_semantic_catalog.py; infrastructure/database/datahub/verify_semantic_catalog.py; tests/data/**; handoffs/R2-W5-F9.json; docs/markdown/daily_reports/seung/일일보고.md
READ_ONLY_INPUTS=infrastructure/database/datahub/compose.consumer.yml; infrastructure/database/datahub/recipes/**; src/data/serving_semantic_catalog.i4.v1.json; src/data/serving_analytics_contract.i4.v1.json; infrastructure/database/sql/ddl/**; infrastructure/database/sql/seed/**
ACCEPTANCE_CRITERIA=pinned DataHub v1.7에서 승인된 isolated project만 사용해 5 recipe ingestion 상태를 관측한다. Dataset 8/8, Column 116/116, unique field 70과 exact catalog version/hash를 검증하고 publisher를 2회 실행해 동일 결과와 schema 재수집 뒤 description 보존을 확인한다. live URN/FQN/column/lineage·binding status·verified_at·hash는 현재 실행값으로만 기록하며 과거 PASS를 복사하지 않는다. CRM fresh synthetic 80000 회귀는 exact 승인 runtime에서만 실행하고 미완료는 NOT_RUN/BLOCKED로 분리한다. secret·resolved recipe·raw customer data는 기록하지 않고 다른 project/container/volume을 변경하지 않는다.
TEST_COMMANDS=python -m json.tool src/data/datahub_runtime_evidence.i5.v1.json src/data/asset_binding_health.i5.v1.json handoffs/R2-W5-F9.json; python -m pytest -p no:cacheprovider tests/data/test_datahub_runtime_evidence.py tests/data/test_asset_binding_health.py tests/data/test_serving_semantic_catalog.py -q; python -m pytest -p no:cacheprovider tests/data -q; docker compose -f infrastructure/database/datahub/compose.consumer.yml config --quiet; pwsh -File infrastructure/database/datahub/scripts/run-runtime-validation.ps1; publisher 2회와 verifier; gate_scope preflight·전체 planned paths·merge-base; git diff --check; seung source CI
STOP_CONDITIONS=clean preflight 실패; free RAM·port·image·project identity·secret readiness 실패; 기존 project/container/volume 변경 필요; 8/116/70·version/hash 불일치; publisher 비멱등; DDL·seed·recipe·compose 수정 필요; broad grant·실데이터·비용; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=승인된 exact isolated DataHub runtime의 기동·수집·publisher 2회·verifier와 종료, 허용 경로 commit·seung push·source CI만 허용한다. 다른 project/container/volume·DDL·seed·recipe·secret·방화벽 변경은 금지한다.
R1_REVIEW_CONDITIONS=runtime PASS와 NOT_RUN/BLOCKED를 분리하고 observed timestamp·hash·run evidence가 일치할 때만 dev 통합한다.
```

### R2 · R2-W5-F10

```text
STATUS=PLANNED
ROLE_ID=R2
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F10
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R2-10·11·19 live Semantic Catalog release freeze
BASE_SHA=N/A — R2-W5-F9 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=src/data/serving_semantic_catalog.i4.v1.json; src/data/serving_analytics_contract.i4.v1.json; src/data/asset_binding_health.i5.v1.json; src/data/datahub_runtime_evidence.i5.v1.json; tests/data/**; handoffs/R2-W5-F10.json; docs/markdown/daily_reports/seung/일일보고.md
ACCEPTANCE_CRITERIA=F9 live hash를 immutable 후보로 연결하고 PUBLISHED·VERIFIED binding만 소비자에게 노출하며 미검증 항목은 fail-closed한다.
TEST_COMMANDS=JSON/hash; tests/data 전체; producer-consumer fixtures; scope; diff; CI
STOP_CONDITIONS=F9 NOT_RUN; runtime PASS 위조; R3/R4 파일 변경; hash 비결정성
```

### R2 · R2-W5-F11

```text
STATUS=PLANNED
ROLE_ID=R2
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F11
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R2-10·11 DataHub Domain·Glossary 검색 원장과 typed structured-search producer
BASE_SHA=N/A — R2-W5-F10 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
CONTRACT_VERSION=DATAHUB-SEARCH-v1.0.0-DRAFT
ALLOWED_PATHS=src/data/datahub_search_contract.i5.v1.json; src/data/serving_semantic_catalog.i4.v1.json; src/data/i2_adapters.py; infrastructure/database/datahub/publish_semantic_catalog.py; infrastructure/database/datahub/verify_semantic_catalog.py; tests/data/test_datahub_search_contract.py; tests/data/test_i2_adapters.py; tests/data/test_serving_semantic_catalog.py; handoffs/R2-W5-F11.json; docs/markdown/daily_reports/seung/일일보고.md
ACCEPTANCE_CRITERIA=main keyword와 Domain·Glossary 후보를 서로 다른 입력으로 받는 typed search request를 동결한다. Domain·Glossary는 raw keyword 문자열을 그대로 filter에 복사하지 않고 승인된 logical ID·alias를 canonical DataHub URN으로 exact 해석한다. 후보가 없거나 ambiguous하면 해당 structured filter를 생략하거나 fail-closed하고 임의 URN을 생성하지 않는다. Dataset·Column·description·owner·Domain·Glossary·tag·lineage 반환 필드와 PUBLISHED·ACTIVE 상태, result limit, canonical hash를 고정한다.
TEST_COMMANDS=JSON schema·canonical hash; alias→Domain/Glossary URN positive·unknown·ambiguous·injection·duplicate tests; typed adapter tests; tests/data 전체; publisher/verifier 회귀; compileall; scope; diff; seung source CI
STOP_CONDITIONS=R2-W5-F10 미통합; live 미검증 상태를 VERIFIED로 승격; raw keyword를 Domain·Glossary filter에 무조건 복사; R3/R4 파일 변경; DataHub secret·실데이터·외부 비용; dependency·scope·필수 검증 실패
R1_REVIEW_CONDITIONS=logical ID·alias·canonical URN과 반환 schema/hash가 결정론적이며 R3/R4가 fixture로 독립 소비할 수 있을 때 READY 전환한다.
```

### R3 · R3-W5-F9

```text
STATUS=PLANNED
ROLE_ID=R3
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F9
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R3-10 versioned Semantic Catalog training consumer
BASE_SHA=N/A — R2·R3 W5-F8 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=src/ai/contracts/**; src/ai/training/semantic_catalog.py; src/ai/training/dataset.py; src/ai/training/verify_case_specs.py; tests/ai/**; handoffs/R3-W5-F9.json; docs/markdown/daily_reports/daesung/일일보고.md
ACCEPTANCE_CRITERIA=8/116/70과 version/hash를 fail-closed 검증하고 description을 실행 instruction으로 취급하지 않으며 compiled dataset은 변경하지 않는다.
TEST_COMMANDS=JSON; semantic tamper/injection tests; tests/ai 전체; compileall; deterministic hash; scope; diff; CI
STOP_CONDITIONS=producer 미통합; dataset 재생성; prompt/model 변경; external endpoint·secret·dependency
```

### R3 · R3-W5-F10

```text
STATUS=PLANNED
ROLE_ID=R3
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F10
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R3-10·14 compiled 1,350 typed parameter v2 재생성
BASE_SHA=N/A — actual Analysis API E2E 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=src/ai/training/**; evals/**; tests/ai/**; handoffs/R3-W5-F10.json; docs/markdown/daily_reports/daesung/일일보고.md
ACCEPTANCE_CRITERIA=period_end_exclusive·typed required filters를 1,350건에 결정론적으로 재생성하고 split/paraphrase/join graph 누수 0과 Gold 불변을 보장한다.
TEST_COMMANDS=two-run byte/hash equality; manifest/leakage tests; tests/ai 전체; compileall; scope; diff; CI
STOP_CONDITIONS=actual API E2E 미통과; Gold 의미 변경; RunPod·model·secret·비용; generated path 미승인
```

### R3 · R3-W5-F11

```text
STATUS=PLANNED
ROLE_ID=R3
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F11
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R3-15 model·prompt·adapter release candidate freeze
BASE_SHA=N/A — R3-W5-F10 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=src/modelops/**; src/ai/prompt_registry.py; tests/ai/**; handoffs/R3-W5-F11.json; docs/markdown/daily_reports/daesung/일일보고.md
ACCEPTANCE_CRITERIA=model/image/runtime/prompt/dataset/adapter hash와 rollback target을 고정하고 Base 기본·LoRA disabled를 별도 승인 전 유지한다.
TEST_COMMANDS=JSON/hash graph; artifact existence; model/prompt tests; tests/ai 전체; compileall; scope; diff; CI
STOP_CONDITIONS=stale evidence; 무승인 Base→LoRA; RunPod 비용·secret; artifact/hash 누락
```

### R3 · R3-W5-F12

```text
STATUS=PLANNED
ROLE_ID=R3
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F12
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R3-03 Node1 DataHub 검색 입력 후보 계약
BASE_SHA=N/A — R3-W5-F8·R2-W5-F11 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
CONTRACT_VERSION=NODE-IO-v0.2.0-DRAFT; DATAHUB-SEARCH-v1.0.0-DRAFT
ALLOWED_PATHS=src/ai/contracts/node_io.v0.1.json; src/ai/node1.py; src/ai/fake_model.py; src/ai/prompt_registry.py; tests/ai/test_node1.py; tests/ai/test_fake_model.py; tests/ai/test_contracts.py; tests/ai/test_prompt_registry.py; handoffs/R3-W5-F12.json; docs/markdown/daily_reports/daesung/일일보고.md
ACCEPTANCE_CRITERIA=Node1은 자연어 질문에서 main search_keywords, domain_candidates, glossary_term_candidates를 별도 typed 배열로 생성하고 후보별 confidence·근거·ambiguity를 보존한다. 동일 raw keyword를 세 배열에 기계적으로 복제하지 않는다. Domain·Glossary 후보는 R2 승인 registry의 logical ID·alias만 사용하고 DataHub URN·asset·권한을 확정하지 않는다. 후보가 없으면 빈 배열을 반환하며 질문·첫 단어·LLM 추측으로 filter를 강제하지 않는다. 기존 intent·metric·time·single-source 호환과 deterministic fake를 유지한다.
TEST_COMMANDS=Node1 schema positive; 일반 keyword-only; Domain-only; Glossary-only; multi-domain; ambiguous alias; unknown term; prompt injection; duplicate 후보; 기존 Node1/fake/prompt/contract tests; tests/ai 전체; compileall; scope; diff; daesung source CI
STOP_CONDITIONS=R2 search contract 미통합; Node1이 URN·asset·권한 확정; 동일 keyword 무조건 복제; backend/data 변경; model download·RunPod·endpoint·secret·비용; dependency·scope·필수 검증 실패
R1_REVIEW_CONDITIONS=R2 logical registry fixture와 exact 호환되고 Node1 출력만으로 검색 결과·권한 성공을 주장하지 않을 때 READY 전환한다.
```

### R4 · R4-W5-F13

```text
STATUS=PLANNED
ROLE_ID=R4
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F13
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R4-17·18 Report worker·block별 Analysis 재실행
BASE_SHA=N/A — R4-W5-F12·R5-W5-F6 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=app/backend/app/report_*.py; app/backend/app/controllers/analysis_controller.py; app/backend/compose.fragment.yml; app/backend/migrations/**; app/backend/contracts/openapi.v0.1.json; tests/backend/**; handoffs/R4-W5-F13.json; docs/markdown/daily_reports/jaehong/일일보고.md
ACCEPTANCE_CRITERIA=approved Definition command를 atomic claim하고 block마다 현재 권한·Context·G1/G2/G3 경로로 재실행해 success·partial·failed·cancelled를 구분한다.
TEST_COMMANDS=claim concurrency; partial/all-fail/auth/filter/repair/timeout/masking; migration; backend 전체; OpenAPI; compose; scope; CI
STOP_CONDITIONS=F12·R5 proposal 미통합; Gate 우회; raw SQL/result 복제; schedule·root compose·secret
```

### R4 · R4-W5-F14

```text
STATUS=PLANNED
ROLE_ID=R4
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F14
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R4-15 append-only Audit repository와 read-only API
BASE_SHA=N/A — R4-W5-F13 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=app/backend/app/audit_*.py; app/backend/app/main.py; app/backend/app/services/analysis_service.py; app/backend/app/services/report_worker.py; app/backend/migrations/**; app/backend/contracts/openapi.v0.1.json; tests/backend/**; handoffs/R4-W5-F14.json; docs/markdown/daily_reports/jaehong/일일보고.md
ACCEPTANCE_CRITERIA=request_id 기반 append-only trace와 owner-scoped list/detail을 제공하고 raw SQL·parameter·result·secret·stack trace를 redaction한다.
TEST_COMMANDS=analysis/report trace; authz; redaction; immutable append; pagination; migration; backend 전체; OpenAPI; scope; CI
STOP_CONDITIONS=role mutation; raw data 노출; worker 미통합인데 report trace PASS 주장; frontend·R2/R3 변경
```

### R4 · R4-W5-F15

```text
STATUS=PLANNED
ROLE_ID=R4
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F15
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R4-06 Node1 검색 입력→DataHub Search SDK→Context resolver
BASE_SHA=N/A — R2-W5-F11·R3-W5-F12·R4-W5-F12 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
CONTRACT_VERSION=DATAHUB-SEARCH-v1.0.0-DRAFT; CONTEXT-PACKAGE-vNEXT-DRAFT
ALLOWED_PATHS=app/backend/app/adapters/i2_data_platform.py; app/backend/app/services/analysis_service.py; app/backend/app/services/pipeline_support.py; app/backend/app/context_registry_contracts.py; app/backend/app/services/context_registry_service.py; tests/backend/test_i2_data_platform.py; tests/backend/test_analysis_pipeline.py; tests/backend/test_context_registry.py; handoffs/R4-W5-F15.json; docs/markdown/daily_reports/jaehong/일일보고.md
ACCEPTANCE_CRITERIA=Analysis 경로는 Node1의 main search_keywords를 DataHub main search에 사용하고 domain_candidates·glossary_term_candidates는 R2 registry를 통해 canonical URN structured filter로 별도 적용한다. 동일 keyword를 Domain·Glossary filter에 자동 복사하지 않는다. request role·approved domain prefilter를 먼저 적용하고 Dataset·Column·description·owner·Glossary·Domain 후보를 받은 뒤 PUBLISHED∩ACTIVE∩asset binding∩entitlement를 모두 만족한 자산만 Context에 포함한다. 점수·tie-break·최대 Dataset 8개·Column 60개를 결정론적으로 제한하고 unknown·ambiguous·zero-result·timeout·GraphQL 오류는 fail-closed한다. versioned/fake와 기존 G1·G2·G3·binder 경로를 우회하지 않는다.
TEST_COMMANDS=main keyword only; Domain/Glossary exact filter; no-candidate filter omission; raw keyword reuse negative; unknown/ambiguous alias; unauthorized domain; unpublished/inactive/unbound asset; duplicate/tie/ranking/result cap; zero/timeout/GraphQL error; analysis pipeline·Context Registry·backend 전체; compileall; scope; diff; jaehong source CI
STOP_CONDITIONS=R2/R3 producer 미통합; DataHub query schema 추정; wildcard Domain·Glossary filter; 권한·binding 우회; GraphQL 실패 fixture fallback; R2/R3/frontend/root Compose·dependency·secret 변경; scope·필수 검증 실패
R1_REVIEW_CONDITIONS=Node1→typed DataHub request→structured search→entitled Context trace가 하나의 request_id로 재현되고 negative case가 fail-closed할 때 READY 전환한다. R4-W5-F13·F14와 파일이 겹치므로 같은 branch에서 동시에 실행하지 않는다.
```

### R1 · R1-W5-F26

```text
STATUS=PLANNED
ROLE_ID=R1
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F26
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R1-08 DataHub 자연어 structured search 통합 검증
BASE_SHA=N/A — R2-W5-F11·R3-W5-F12·R4-W5-F15 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=tests/integration/test_datahub_semantic_search_e2e.py; handoffs/R1-W5-F26.json; docs/markdown/daily_reports/junhee/일일보고.md
ACCEPTANCE_CRITERIA=자연어 질문→Node1의 분리된 keyword·Domain·Glossary 후보→DataHub main/structured search→role·binding·entitlement→Context Package를 실제 제품 경로로 검증한다. 일반 검색, Domain만 지정, Glossary만 지정, 복합 질문, 모호어, 미등록어, 권한 없는 Domain, 빈 결과, result cap을 포함하고 동일 request_id trace를 확인한다. main keyword를 Domain·Glossary에 무조건 재사용하지 않는다는 계약을 Gold negative case로 고정한다.
TEST_COMMANDS=target integration test; R2 search contract·R3 Node1·R4 adapter/pipeline targets; tests/data·tests/ai·tests/backend·tests/integration; actual DataHub runtime은 자원/health PASS일 때만; scope; diff; junhee source CI; dev CI
STOP_CONDITIONS=producer 카드 미통합; 실제 DataHub health·binding 미검증인데 live PASS 주장; direct fixture/URN/SQL 주입; 권한·Gate 우회; 외부 비용·secret·다른 project 변경; scope·필수 검증 실패
R1_REVIEW_CONDITIONS=versioned 경로는 결정론적 PASS, live 경로는 observed evidence가 있을 때만 PASS로 분리 판정한다.
```

### R5 · R5-W5-F5

```text
STATUS=PLANNED
ROLE_ID=R5
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W5-F5
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R5-01 LAN actual browser·CORS·fail-closed smoke
BASE_SHA=N/A — R5-W5-F4 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=handoffs/R5-W5-F5.json; docs/markdown/daily_reports/minji/일일보고.md
ACCEPTANCE_CRITERIA=명시적 LAN frontend/backend 주소에서 Agent·Report network request와 allowed/denied CORS, 4xx/503 fail-closed UI를 실제 browser로 검증한다.
TEST_COMMANDS=resolved compose; service health; browser screenshot/network; OPTIONS allow/deny; frontend contracts/build; scope; CI
STOP_CONDITIONS=F4 미통합; 제품 수정 필요; wildcard CORS; firewall·다른 project·secret; fake success
```

### R5 · R5-W5-F6

```text
STATUS=PLANNED
ROLE_ID=R5
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W5-F6
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R5-14 Report Worker v1.2 domain/router/migration proposal
BASE_SHA=N/A — R5-W5-F5 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=src/report/**; tests/report/**; handoffs/R5-W5-F6.json; docs/markdown/daily_reports/minji/일일보고.md
ACCEPTANCE_CRITERIA=immutable Analysis Definition version·공통 report_as_of·queued→claimed→terminal·block partial·idempotency를 proposal로 동결하고 schedule은 제외한다.
TEST_COMMANDS=report domain/router/migration proposal tests; duplicate claim; partial/all-fail; backend/OpenAPI unchanged; scope; CI
STOP_CONDITIONS=app/backend 직접 수정; 과거 SQL 신뢰; fake status; schedule·P2·dependency·secret
```

### R5 · R5-W5-F7

```text
STATUS=PLANNED
ROLE_ID=R5
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W5-F7
TARGET_INTEGRATION_GATE=I5
TASK_CARD_RANGE=R5-14 actual Report worker run·partial·error UI
BASE_SHA=N/A — R4-W5-F13 dev 통합 SHA
DIRECTIVE=WAIT
DIRECTIVE_TOKEN=N/A
ALLOWED_PATHS=app/enterprise-react/src/api/reportClient.ts; app/enterprise-react/src/contracts/report.ts; app/enterprise-react/src/pages/ReportsPage.jsx; app/enterprise-react/src/styles.css; tests/frontend/contracts.test.mjs; handoffs/R5-W5-F7.json; docs/markdown/daily_reports/minji/일일보고.md
ACCEPTANCE_CRITERIA=server의 queued/running/success/partial/failed/cancelled와 block evidence를 그대로 표시하고 polling race·과거 결과 최신 위장을 차단한다.
TEST_COMMANDS=frontend contracts/build; HTTP state matrix; actual worker browser flow; responsive/a11y; scope; CI
STOP_CONDITIONS=R4 worker 미통합; API 추정; optimistic fake run; localStorage result; schedule·dependency
```


## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v5.68 | 2026-08-11 14:04 | stale branch self-sync·Gate-only 원장 발행·remote source preflight의 세 자동화 병목과 중복 시작 지침을 최소 교정하는 R1-W5-F29 READY 발행 |
| v5.67 | 2026-08-11 13:42 | terminal R1 카드 때문에 Gate-only 발행 CI가 scope FAIL하는 순환을 해소하고 역할별 active READY·source evidence 전이만 담당하는 R1-W5-F28 READY 발행 |
| v5.66 | 2026-08-11 13:16 | R4-W5-F12 통합 뒤 client-owned X-User-Id·X-Role 신뢰를 제거하고 server-owned opaque principal mapping으로 Analysis·Report 공통 인증 경계를 동결하는 R4-W5-F16 READY 발행 |
| v5.65 | 2026-08-11 13:02 | R2-W5-F8·R4-W5-F12 dev 통합과 CI 31456536103 PASS 뒤 isolated DataHub v1.7 live evidence를 수집하는 R2-W5-F9 READY 발행 |
| v5.64 | 2026-08-11 12:55 | R2-W5-F8 Semantic Catalog checkpoint와 R4-W5-F12 Context Registry·실제 Gold 조합의 source CI·handoff를 확인해 MERGED_DEV로 전환 |
| v5.63 | 2026-08-11 12:43 | R1-W5-F27의 history-preserving reconciliation과 corrective source CI를 확인해 MERGED_DEV로 전환 |
| v5.61 | 2026-08-11 12:30 | 기획서의 Node1 keyword 후보→DataHub main search·Domain/Glossary structured filter→권한 Context 흐름을 R2 F11·R3 F12·R4 F15·R1 F26 후속 카드로 명시하고 raw keyword의 필터 무조건 재사용을 금지 |
| v5.60 | 2026-08-11 12:15 | 사용자 승인으로 commit된 legacy 자동화 개선 기록을 F25 누적 read-only evidence로 분리해 role-scope 교정 |
| v5.59 | 2026-08-11 12:11 | compact archive의 I4 VERIFIED_GATE를 dashboard가 인식하지 못하는 회귀를 교정하는 R1-W5-F25 READY 발행 |
| v5.58 | 2026-08-11 11:58 | R1-W5-F24 자동화 개선을 source CI 31453748585 PASS 근거로 dev에 통합하고 MERGED_DEV로 종료 |
| v5.57 | 2026-08-11 11:55 | 역할별 최신 실행 카드와 PLANNED 큐만 활성 원장에 남기고 이전 49개 카드를 날짜 archive로 이동해 hot-file 크기를 축소 |
| v5.56 | 2026-08-11 11:45 | scope metadata 실패에도 제품 검증 신호를 수집하고 pending-CI handoff·inherited checkpoint hash·단일 preflight/sync·활성 원장 경량화를 구현하는 R1-W5-F24 READY 발행 |
| v5.55 | 2026-08-11 11:28 | 외부 R5 clone의 local-only 3 commits를 삭제 없이 보존하고 latest dev를 non-ff merge한 뒤 기존 F4 wiring을 완주하는 owner-scoped reconciliation REWORK 재발행 |
| v5.54 | 2026-08-11 11:22 | R4-W5-F12의 실제 제품 SHA f481f91과 scope-only 실패 CI 31451536556을 보존하면서 F10C·F10D owner 경로를 정식화하고 canonical G120-046 Gold 수치·hash 교정을 필수로 하는 corrective REWORK 재발행 |
| v5.53 | 2026-08-11 10:50 | actual G120-046 HTTP가 live Trino Gold PASS와 달리 Node3 MODEL 단계에서 실패한 근거로, 미착수 R4-W5-F12를 Context Registry와 multi-source metric_selection consumer를 함께 완주하는 owner-scoped REWORK로 재발행 |
| v5.52 | 2026-08-11 10:35 | R1-W5-F22의 격리 runtime·migration·Template·readiness를 MERGED_DEV로 전환하고, 각 역할의 후속 작업 11개를 단일 활성 카드 원칙을 지키는 PLANNED 큐로 등록 |
| v5.51 | 2026-08-11 10:20 | 실제 호스트의 15432·18000 점유와 Windows 55432 제외 범위를 반영해 R1-W5-F22가 내부 DNS/target을 보존한 채 answervice 전용 host 25432·28000만 override하도록 runtime identity 계약 교정 |
| v5.50 | 2026-08-11 10:10 | R1-W5-F21 checkout Node 24 immutable pin과 source CI를 dev에 통합하고, R4-W5-F11 readiness 계약 위에서 app-postgres identity 충돌을 root override로 해소해 actual readiness를 검증하는 R1-W5-F22 READY 발행 |
| v5.49 | 2026-08-11 10:10 | R2-W5-F7 CI scope 충돌을 inherited evidence로 분리해 R2-W5-F8을 발행하고, R4 Context Registry 요청 중 live 의존이 없는 F10A additive migration·F10B checksum repository를 R4-W5-F12 service-only READY로 병렬 발행 |
| v5.48 | 2026-08-11 10:10 | R4-W5-F11의 readiness·Node3 payload·LAN API 경계와 source CI를 확인해 dev에 통합하고 MERGED_DEV 전환 |
| v5.47 | 2026-08-11 09:55 | R1-W5-F20 이력 조정을 dev에 통합하고 R1 CI Node 24 공급망 pin, R3 Node3·ModelOps DRAFT 검증을 READY 발행; R4·R5는 Gate-only dev 선행을 ff-only 동기화해 기존 token으로 즉시 착수하도록 명시 |
| v5.46 | 2026-08-11 09:44 | 작업자 Downloads 저장소의 seung 7c4164b·dirty 일일보고 1개 snapshot을 조건부 정본으로 받아 제품·stash 불변과 F6/F7 handoff만 허용하도록 R2-W5-F7 token 재발행 |
| v5.45 | 2026-08-11 09:38 | 갈라진 junhee·dev 이력과 기존 R1 증거를 삭제 없이 보존하고 최신 Gate로 동기화하는 R1-W5-F20 reconciliation REWORK 발행 |
| v5.44 | 2026-08-11 09:29 | 선행 producer 완성을 기다리지 않고 R4 backend 시연 연결 해소와 R5 공통 backend base wiring을 DRAFT 계약으로 병렬 착수하도록 READY 발행 |
| v5.43 | 2026-08-11 09:27 | R4-W5-F9의 Analysis 저장·조회·재실행 API와 terminal CI를 확인해 dev에 통합하고 MERGED_DEV로 종료 |
| v5.42 | 2026-08-11 09:20 | R2-W5-F6의 원격 CI 통과 checkpoint와 로컬 일일보고·제품 변경을 모두 보존하는 R2-W5-F7 reconciliation 전용 REWORK 발행 |
| v5.41 | 2026-08-10 19:30 | R1-W5-F13을 기존 hotel-synthetic-db app-postgres 고정 이름 충돌 근거로 BLOCKED 처리하고 다른 project 불변·신규 빈 answervice resource 보존·owner별 후속 경계를 기록 |
| v5.40 | 2026-08-10 19:20 | 시연 준비를 위해 exact answervice app-postgres/backend만 기동하고 migration head·approved Template·readiness를 검증하는 R1-W5-F13 발행 |
| v5.39 | 2026-08-10 19:10 | R5-W5-F3의 기본 loopback·명시적 LAN 공개, exact frontend runtime·source CI를 확인해 dev에 통합하고 MERGED_DEV로 종료 |
| v5.38 | 2026-08-10 19:00 | frontend 기본 loopback을 유지하고 FRONTEND_BIND_ADDRESS=0.0.0.0 명시 시에만 same-LAN 13000 공개를 허용하는 R5-W5-F3 발행 |
| v5.37 | 2026-08-10 18:50 | R1-W5-F12의 live profile guard source·terminal CI와 CRM product-only dev CI를 확인해 MERGED_DEV로 종료 |
| v5.36 | 2026-08-10 18:40 | R1-W5-F12 source scope가 기존 F9/F10 handoff를 history rewrite 없이 보존하도록 두 파일을 read-only cumulative evidence로만 허용하고 CRM product integration 범위는 유지 |
| v5.35 | 2026-08-10 18:30 | R1-W5-F11을 source CI의 live Trino endpoint 부재 근거로 BLOCKED 처리하고, 명시적 live profile guard와 CRM product-only 통합을 수행하는 R1-W5-F12를 발행 |
| v5.34 | 2026-08-10 18:15 | R1-W5-F10을 근거대로 BLOCKED로 정정하고 CRM health product-only R1-W5-F11, R2 offline 9-path checkpoint, R3 Node3 derived metric producer, R4 F9 handoff-only 권한을 발행 |
| v5.33 | 2026-08-10 17:50 | R4-W5-F9 test container가 제품 entrypoint를 실행하지 않도록 docker run에 `--entrypoint sh`를 명시해 Python 3.12 pytest 검증 명령을 실행 가능하게 교정 |
| v5.32 | 2026-08-10 17:45 | R4-W5-F9의 전체 backend가 pytest 수집을 요구함을 재현해 제품 dependency는 동결하고 Python 3.12 test container 안에서만 pytest 8.3.5를 일회성 설치하도록 검증 권한을 교정 |
| v5.31 | 2026-08-10 17:35 | R3-W5-F6의 source CI·handoff와 dev 조합 회귀를 확인해 MERGED_DEV로 전환하고, R4-W5-F9의 Python 3.12 컨테이너 검증을 이미지에 없는 pytest 대신 승인 원문의 stdlib unittest 명령으로 교정 |
| v5.24 | 2026-08-10 14:00 | 대표 3-source Trino Gold는 일치했지만 제품 E2E가 Binding·Node2 multi-source plan·repair·safe CTE·chart에서 차단됨을 기록; interim은 검증된 versioned binding, live는 fail-closed로 결정하고 R3-W5-F5·R4-W5-F6을 병렬 READY 발행 |
| v5.23 | 2026-08-10 13:45 | R3 Node2·evaluator typed parameter 결과와 source CI를 MERGED_DEV로 전환하고, 실제 G120-046 제품 API E2E를 R1-W5-F9으로 READY 발행; compiled 1,350건 재생성은 E2E 통과 뒤 R3-W5-F4로 분리 |
| v5.22 | 2026-08-10 13:30 | R4 typed Context·G2·단일 Trino binder의 source CI·handoff를 확인해 MERGED_DEV로 전환하고, R3 Node2·evaluator가 같은 value_type·period_end_exclusive 계약을 소비하도록 R3-W5-F3을 READY 발행 |
| v5.21 | 2026-08-10 13:15 | R1 CI 공급망 보강과 R2 typed filter·PMS/CRM/POS Context의 source CI·handoff를 확인해 MERGED_DEV로 전환하고 R4 Context·G2·단일 binder 소비자 카드를 READY 발행; 5주차 팀 요약·주간보고를 개인 보고와 동기화 |
| v5.20 | 2026-08-10 13:00 | 다른 역할과 독립적인 R1 CI 공급망 작업을 확인해 GitHub Actions immutable SHA pin과 모든 job timeout을 검증하는 R1-W5-F8을 병렬 발행; R5는 Audit·Schedule·Report worker·Catalog live 생산자 부재로 신규 구현 없이 대기 |
| v5.19 | 2026-08-10 12:55 | R4 Alembic 검증을 MERGED_DEV로 전환하고, typed required-filter·대표 PMS/CRM/POS Context를 R2 생산자부터 R4·R3 소비자와 R1 실제 API E2E 순으로 재편; Analysis·SQLGlot G2/G3·Report worker·schedule은 선행 E2E 뒤 단계화 |
| v5.18 | 2026-08-10 12:47 | dev CI 31352194575에서 R4 G2 parameter 경계와 R3 literal evaluator/test 불일치로 3건 실패한 원인을 확인하고, backend 경계를 완화하지 않는 R3-W5-F2 REWORK를 병렬 발행 |
| v5.17 | 2026-08-10 12:40 | R4 Asset Binding consumer가 PENDING/NOT_RUN을 성공으로 오표시하지 않는 결과와 CI를 MERGED_DEV로 전환하고, 이전 R4 legacy migration 요청을 제품 migration 변경 없는 R4-W5-F4 검증 카드로 READY 발행 |
| v5.16 | 2026-08-10 12:31 | R4 Metadata·Context Registry 대규모 요청은 번호 충돌·R2 runtime NOT_RUN·migration/OpenAPI 미확정·외부 dirty 작업공간 때문에 제안 그대로 반려하고 F5 PLANNED로 분해 순서를 기록; R1 first-start와 R5 Audit UI도 선행조건부 PLANNED로 등록 |
| v5.15 | 2026-08-10 12:18 | R1 DataHub 안전 기동 도구와 R2 offline runtime·binding, R4 Context/G2 결과·CI를 MERGED_DEV로 전환; R2 PENDING binding의 R4 VERIFIED 오표시를 막는 F3 REWORK를 우선 발행하고 R4의 legacy migration 요청은 F4 PLANNED로 부분 수용 |
| v5.14 | 2026-08-10 11:52 | R3 required-filter 결과와 source CI를 확인해 MERGED_DEV 전환; legacy schema 근거 없는 R4 migration 카드를 차단하고 R1 DataHub runtime preflight·R2 offline runtime/binding validator·R4 versioned Context consumer 카드를 병렬 발행 |
| v5.13 | 2026-08-10 11:43 | R2 DataHub v1.7.0 config producer와 R1 root verifier의 결합 CI, R5 목업 기반 frontend source CI·handoff를 확인해 R1·R2·R5 카드를 MERGED_DEV로 전환 |
| v5.12 | 2026-08-10 11:23 | 공식 DataHub v1.7.0 최신화를 R1 root 계약과 R2 consumer config 카드로 분리 발행하고 Trino 476·runtime resource를 동결; 기존 R2 Gold 카드는 보완된 후속 REWORK를 위해 차단 |
| v5.11 | 2026-08-10 11:06 | R5-W5-F1 발행 범위와 R1 handoff·source CI를 확인해 R1-W5-F3를 MERGED_DEV 전환 |
| v5.10 | 2026-08-10 11:03 | 사용자 목업을 기존 API·route·fixture 계약 안에서 최소 이식하는 R5-W5-F1과 발행 검증 R1-W5-F3를 READY 발행 |
| v5.9 | 2026-08-10 11:00 | R1-W5-F2의 Ponytail v4.9.0 정합성·LLM 참고 스냅샷·handoff와 source CI를 확인해 MERGED_DEV 전환 |
| v5.8 | 2026-08-10 10:56 | 동시 생성된 LLM 사용 현황을 현재 코드·설정 근거의 legacy 참고 스냅샷으로 보존하도록 R1-W5-F2 범위 보완 |
| v5.7 | 2026-08-10 10:52 | Ponytail 실제 설치본 v4.9.0과 팀 정책을 일치시키는 R1-W5-F2 발행 |
| v5.6 | 2026-08-10 10:45 | R1-W5-F1·R5-W4-F5 source CI와 handoff를 확인하고 dev 통합 결과를 기록해 MERGED_DEV 전환 |
| v5.5 | 2026-08-10 10:40 | 같은 시점의 기획서 기반 구현 현황 스냅샷을 R1 참고 근거로 보존하도록 허용 경로 추가 |
| v5.4 | 2026-08-10 10:34 | R2~R4 카드 발행 행위를 추적하는 R1-W5-F1 실행 묶음 추가 |
| v5.3 | 2026-08-10 10:29 | R2 3-source 정답 조회, R3 범위 복구·required filter SQL, R4 legacy migration 호환 복구 카드를 발행 |
| v5.2 | 2026-08-10 09:48 | R1-W4-F10 source CI와 handoff를 확인하고 dev 통합 결과를 기록해 MERGED_DEV 전환 |
| v5.1 | 2026-08-10 09:44 | R1-W4-F10의 카드 번호 독립 회귀 검증과 전달 증거를 완료해 REVIEW 전환 |
| v5.0 | 2026-08-10 09:40 | R5 범위 초과 변경과 browser 검증 차단을 해소하는 R5-W4-F5 REWORK 및 카드 전환 회귀를 보정하는 R1-W4-F10 발행 |
| v4.9 | 2026-08-06 11:16 | R1-W4-F9 source CI와 handoff를 확인하고 dev 통합 결과를 기록해 MERGED_DEV 전환 |
| v4.8 | 2026-08-06 11:01 | R1 카드 fixture·공용 parser·병합 session 구현과 local 통합 회귀 완료 후 REVIEW 전환 |
| v4.7 | 2026-08-06 10:59 | 역할 카드 fixture·공용 Gate parser·병합 session 정합성 개선을 위한 R1 카드 발행·착수 |
| v4.2 | 2026-08-06 09:30 | source CI 확인·작업 전 경로 검사·변경 문서 CI·보고 일괄 통합을 위한 R1 유지보수 카드 발행·착수 |
| v4.1 | 2026-08-05 20:14 | versioned-trino 합성 기간 상태·일별 집계·KPI·Evidence 기간을 일치시키고 실브라우저 E2E 병목 해소 |
| v4.0 | 2026-08-05 19:44 | 역할별 최신 실행 카드만 활성 원장에 유지하고 기존 전체 이력을 archive로 분리 |
