# Gate 실행 카드 원장

| 항목 | 내용 |
|---|---|
| 문서 설명 | 현재 역할별 실행 카드와 Gate 중단·통합 조건을 관리하는 활성 원장 |
| 문서 분류 | 일반 문서 |
| 버전 | v5.29 |
| 문서 기준일 | 2026-08-10 16:55 |
| 작성·수정 | 박준희 / 3팀 사용자 요청·Codex 반영 |

> 종료되거나 대체된 카드는 [2026-07-29~2026-08-04 Archive](archive/Gate_실행_카드_원장_20260729-20260804.md)에서 확인한다.

## 사용 원칙

1. 자동화와 에이전트는 이 파일의 역할별 마지막 non-`PLANNED` 카드만 현재 실행 기준으로 사용한다.
2. `READY`·`IN_PROGRESS`만 구현을 계속할 수 있으며 `BLOCKED`는 차단 원인을 해소하는 새 묶음이 필요하다.
3. `MERGED_DEV`·`VERIFIED_GATE`는 개인 보고와 공용 보고 경로 외 신규 구현을 허용하지 않는다.
4. 과거 카드·상태 전이·비용·검증 이력은 archive에 보존하며 활성 원장에 복제하지 않는다.
5. 일정과 진행률의 단일 기준은 `docs/markdown/02_WBS.md`다.

## 현재 역할별 실행 상태

| 역할 | 실행 묶음 | 상태 | 개인 branch |
|---|---|---|---|
| R1 | `R1-W5-F9` | `BLOCKED` | `junhee` |
| R2 | `R2-W5-F6` | `READY` | `seung` |
| R3 | `R3-W5-F6` | `READY` | `daesung` |
| R4 | `R4-W5-F9` | `READY` | `jaehong` |
| R5 | `R5-W5-F1` | `MERGED_DEV` | `minji` |

## 활성 실행 카드

### R1 · R1-W4-F5

```text
STATUS=VERIFIED_GATE
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
RESULT_SHA=f4871df852d606daf793414e9582aa48be49514e
RESULT_CI=R3 30885817084 PASS; R2 30886662028 PASS; R4 30889083425 PASS; dev 30889141133 PASS
```

### R1 · R1-W4-F6

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F6
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=agent automation efficiency
TASK_CARD_RANGE=R1-06 CI·병합·보고 자동화 정합성 보완
CURRENT_TASK_CARD_ID=R1-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=5b368a5b17fa91028e128f79ac03f19e0742a074
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W4-F6@5b368a5
ALLOWED_PATHS=AGENTS.md; .agents/skills/merge-branch-to-dev/**; .github/scripts/gate_scope.py; .github/workflows/ci.yml; tests/integration/test_gate_scope.py; tests/integration/test_merge_preflight.py; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/collaboration/README.md; docs/markdown/daily_reports/README.md; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 제품 경로; backend·frontend·data·AI 제품 코드; root Compose·env; dependency; secret
ACCEPTANCE_CRITERIA=개인 branch를 dev에 병합하기 전에 해당 source SHA의 CI 성공을 확인하고, 작업 시작 전에 예상 변경 경로가 활성 실행 카드 범위인지 검사한다. 문서 CI는 고정 목록이 아니라 실제 변경 문서를 검사한다. 여러 branch를 한 요청에서 통합할 때 handoff를 push 전 검증하고 팀 보고는 마지막 source 뒤 한 번만 commit한다. 기존 역할 소유권·Gate·secret·외부 비용 경계를 유지한다.
ACCEPTANCE_IDS=AC1_SOURCE_CI;AC2_PLANNED_PATHS;AC3_CHANGED_DOCS;AC4_BATCH_REPORT;AC5_EXISTING_BOUNDARIES
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/integration -q; python -m compileall -q .github/scripts .agents/skills/merge-branch-to-dev/scripts tests/integration; CI YAML parse; document/report validation; python .github/scripts/gate_scope.py --branch junhee --check-planned-path .github/workflows/ci.yml; git diff --check
TEST_COMMAND_IDS=T1_INTEGRATION;T2_COMPILE;T3_YAML;T4_DOCS;T5_PLANNED_SCOPE;T6_DIFF
STOP_CONDITIONS=CI 실패 source 병합 허용; terminal 카드로 제품 변경 허용; 변경 문서 검사 누락; 역할·보안 경계 축소; R2~R5 제품 경로 변경; 새 dependency·외부 비용·secret 필요; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local 자동화·문서·test 변경만 승인하며 commit·push·dev 병합은 별도 사용자 요청 전 금지한다.
RESULT_SHA=8037c5dafe6b85706737e7ae2aab5f2d02d817e8
RESULT_CI=branch 31060559706 PASS; dev 31060722209 PASS; sync 31060779744 PASS
```

### R1 · R1-W4-F7

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F7
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=agent parallel bootstrap and integration
TASK_CARD_RANGE=R1-06 작업 위치·상태·공통 지침·다중 branch 통합 자동화 보완
CURRENT_TASK_CARD_ID=R1-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=23214ac3eaf2e4b8dacf85a0df9bf34f7310a973
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W4-F7@23214ac
ALLOWED_PATHS=AGENTS.md; .github/scripts/gate_scope.py; .agents/skills/merge-branch-to-dev/**; tests/integration/test_gate_scope.py; tests/integration/test_merge_preflight.py; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/collaboration/README.md; docs/markdown/collaboration/AI_개발_환경_설정.md; docs/markdown/ai_docs/5인_병렬구현_*_매뉴얼_최종안.md; docs/markdown/ai_docs/legacy/260805_코딩에이전트_작업프로세스_개선기록_v1.0.md; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 제품 경로; backend·frontend·data·AI 제품 코드; root Compose·env·CI; dependency; secret
ACCEPTANCE_CRITERIA=역할 작업 시작 전에 현재 branch·dirty 상태·실행 가능 카드와 읽을 기준 문서를 한 명령으로 확인한다. 병합 완료 카드가 실행 가능 상태로 남지 않도록 결과 기록 절차를 고정한다. 역할 매뉴얼의 중복·노후 CI 설명을 공통 협업 규칙으로 대체한다. 여러 source의 worktree·remote SHA·CI를 dev에서 한 번에 점검한다. 기존 Gate·소유권·source CI·dev 회귀 경계를 유지한다.
ACCEPTANCE_IDS=AC1_BOOTSTRAP;AC2_TERMINAL_STATE;AC3_CANONICAL_GUIDANCE;AC4_BATCH_PREFLIGHT;AC5_EXISTING_BOUNDARIES
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/integration -q; python -m compileall -q .github/scripts .agents/skills/merge-branch-to-dev/scripts tests/integration; document/report validation; python .github/scripts/gate_scope.py --branch junhee --bootstrap; python .github/scripts/gate_scope.py --branch junhee --check-planned-path .github/scripts/gate_scope.py; git diff --check
TEST_COMMAND_IDS=T1_INTEGRATION;T2_COMPILE;T3_DOCS;T4_BOOTSTRAP;T5_PLANNED_SCOPE;T6_DIFF
STOP_CONDITIONS=다른 역할 제품 경로 변경; terminal·BLOCKED 카드 구현 허용; dirty·branch 불일치 무시; source CI·dev 회귀 생략; 자동 merge·push 확대; 새 dependency·외부 비용·secret 필요; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local 자동화·문서·test 변경만 승인하며 commit·push·dev 병합은 별도 사용자 요청 전 금지한다.
RESULT_SHA=19a05c3ae356d2af5b5919b770fd6741f060d807
RESULT_CI=branch 31062826908 PASS
```

### R1 · R1-W4-F8

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F8
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=terminal card regression
TASK_CARD_RANGE=R1-06 병합 종료 상태 이후 Gate test 회귀 보정
CURRENT_TASK_CARD_ID=R1-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=18910ba41cc3647371fdb9013c1156541bb8c937
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W4-F8@18910ba
ALLOWED_PATHS=tests/integration/test_gate_scope.py; docs/markdown/collaboration/Gate_실행_카드_원장.md
FORBIDDEN_PATHS=제품 코드; 다른 역할 경로; workflow; dependency; secret
ACCEPTANCE_CRITERIA=Gate test가 활성 카드에만 의존하지 않고 MERGED_DEV 전환 뒤에도 planned path의 구현 허용·차단 조건을 독립적으로 검증한다. 전체 dev Python test 회귀를 복구하며 제품 동작과 기존 안전 경계는 변경하지 않는다.
ACCEPTANCE_IDS=AC1_STATE_INDEPENDENT_TEST;AC2_DEV_FULL_REGRESSION;AC3_NO_PRODUCT_CHANGE
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/integration -q; python -m pytest -p no:cacheprovider tests -q; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_INTEGRATION;T2_FULL;T3_SCOPE;T4_DIFF
STOP_CONDITIONS=제품 코드·workflow 변경; Gate 안전 경계 축소; 다른 역할 경로 변경; 새 dependency; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local test·Gate 원장 변경과 승인된 commit·push·dev 병합만 허용한다.
RESULT_SHA=2fa04df4af552544e442cd137c2c84cd1bb06b3d
RESULT_CI=branch 31063368217 PASS
```

### R1 · R1-W4-F9

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F9
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=agent merge automation hardening
TASK_CARD_RANGE=R1-06 Gate test·parser·병합 세션 정합성 개선
CURRENT_TASK_CARD_ID=R1-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=65679f69e0253611e3e572b1bbe08229d3e66d77
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W4-F9@65679f6
ALLOWED_PATHS=.github/scripts/gate_scope.py; .agents/skills/merge-branch-to-dev/**; tests/integration/test_gate_scope.py; tests/integration/test_merge_preflight.py; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/collaboration/README.md; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=제품 코드; 다른 역할 경로; workflow; dependency; secret
ACCEPTANCE_CRITERIA=역할별 최신 카드 번호 변경이 test fixture를 깨뜨리지 않는다. 병합 사전검사는 gate_scope의 원장 parser와 terminal status를 재사용한다. source·dev·final 단계가 하나의 ignored JSON session에서 base SHA·source SHA·CI 결과를 재사용하고 결과 기록 값을 제공한다. 기존 승인·충돌 중단·수동 merge·push 경계는 유지한다.
ACCEPTANCE_IDS=AC1_NO_LIVE_CARD_IDS;AC2_SINGLE_LEDGER_PARSER;AC3_SESSION_REUSE;AC4_EXISTING_GIT_BOUNDARIES
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/integration -q; python -m compileall -q .github/scripts .agents/skills/merge-branch-to-dev/scripts tests/integration; document/report validation; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_INTEGRATION;T2_COMPILE;T3_DOCS;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=자동 merge·push·conflict 해결 추가; 제품 코드·workflow 변경; Gate 안전 경계 축소; 새 dependency; 다른 역할 경로 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local 자동화·문서·test 변경만 허용하며 commit·push·dev 병합은 별도 사용자 요청 전 금지한다.
RESULT_SHA=f8e8d1900b1ae5a4f3b003bb62d6a8a0016a09a5
RESULT_CI=branch 31065077010 PASS
```

### R1 · R1-W4-F10

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W4-F10
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=owner-scoped REWORK card regression
TASK_CARD_RANGE=R1-06 실행 카드 전환 회귀 검증 보정
CURRENT_TASK_CARD_ID=R1-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=6c05c6057d0518d3edab412bb1af860da0d6ce69
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W4-F10@6c05c60
ALLOWED_PATHS=tests/integration/test_gate_scope.py; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=제품 코드; R2~R5 소유 경로; workflow·root Compose·env; dependency; secret
ACCEPTANCE_CRITERIA=dashboard의 BLOCKED→owner-scoped REWORK 동작을 현재 활성 카드 번호에 의존하지 않는 독립 fixture로 검증한다. R5-W4-F5 READY 발행 뒤 실제 dashboard가 새 카드를 선택하고 기존 terminal·BLOCKED 구현 차단과 handoff 검증 경계를 유지한다.
ACCEPTANCE_IDS=AC1_NO_LIVE_CARD_ID;AC2_REWORK_SELECTION;AC3_EXISTING_GATE_BOUNDARIES
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/integration/test_gate_scope.py -q; python -m pytest -p no:cacheprovider tests/integration -q; python -m compileall -q .github/scripts tests/integration; document validation; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_TARGET;T2_INTEGRATION;T3_COMPILE;T4_DOCS;T5_SCOPE;T6_DIFF
STOP_CONDITIONS=제품 코드·workflow 변경; 특정 live bundle ID 재고정; Gate 안전 경계 축소; 다른 역할 경로 변경; 새 dependency; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local Gate test·원장·보고와 승인된 commit·push·dev 병합만 허용한다.
RESULT_SHA=187cac11fcdf8b3bbb60517dd248ed6cf66a7495
RESULT_CI=branch 31345351140 PASS
```

### R2 · R2-W4-F4

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W4-F4
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=single-asset metric registry coverage
TASK_CARD_RANGE=R2-10~14 product metric registry safe subset
CURRENT_TASK_CARD_ID=R2-10
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=c97c468b769bf9870cf39048e4916acfd410c156
START_POINT=origin/seung e9a57ed41b83fdbdf90b1e467a12856581033705에 origin/dev c97c468b769bf9870cf39048e4916acfd410c156을 병합해 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W4-F4@c97c468
CONTRACT_VERSION=I4-CONTEXT-v2.2.0-DRAFT; I4-CONTEXT-v2.1.0-compatible
ALLOWED_PATHS=src/data/analytics_context_contract.i4.v2.json; tests/data/test_analytics_context_contract.py; handoffs/R2-W4-F4.json; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/ai/**; frontend/**; infrastructure/database/**; root Compose·env·CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R2-W4-F4.json
ACCEPTANCE_CRITERIA=registry version을 올리고 기존 recognized_room_revenue·expired_points를 변경하지 않은 채, 기존 metric이 없는 서로 다른 승인 분석 View에 fnb_net_revenue·facility_revenue·actual_attendees를 각각 1개 추가한다. 각 metric은 실제 View field·time_field와 aggregation=sum을 사용하고 ACTUAL·false structured required_filters를 포함한다. 모든 field·time·filter field는 해당 승인 View column이어야 하며 asset_fqn당 metric은 정확히 1개를 유지한다. 기존 raw asset·JOIN·selection policy와 R4 consumer 회귀를 보존하고 전체 23개 coverage를 주장하지 않는다.
ACCEPTANCE_IDS=AC1_VERSION_BUMP;AC2_THREE_METRICS;AC3_EXACT_COLUMNS;AC4_TYPED_FILTERS;AC5_ONE_PER_ASSET;AC6_EXISTING_COMPAT;AC7_R4_CONSUMER;AC8_LOCAL_ONLY
TEST_COMMANDS=python -m json.tool src/data/analytics_context_contract.i4.v2.json; python -m pytest -p no:cacheprovider tests/data/test_analytics_context_contract.py -q; python -m pytest -p no:cacheprovider tests/data -q; python -m pytest -p no:cacheprovider tests/backend/test_i2_data_platform.py tests/backend/test_context_builder.py tests/backend/test_production_model.py -q; python -m pytest -p no:cacheprovider tests -q; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_JSON;T2_TARGET;T3_DATA;T4_CONSUMER;T5_FULL;T6_SCOPE;T7_DIFF
STOP_CONDITIONS=같은 FQN에 두 번째 metric 필요; weighted ratio·denominator·count와 SUM 정규화·expression field·multi-asset·empty required_filters·gt numeric filter 필요; R3·R4 경로 변경 필요; 승인 View column으로 정확히 표현 불가; 외부 서비스·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local contract·test·허용 경로 commit·seung push만 승인한다.
AUTO_FAIL_CONDITIONS=전체 23개 무단 확대; 기존 2개 변경; asset당 복수 metric; column 불일치; empty filter; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=3개 metric의 실제 View column·ACTUAL/false·asset당 1개, 기존 registry와 R4 consumer 회귀, branch CI를 제출한다. 통과해도 150건 product-context 평가와 cloud 실행은 금지한다.
RESULT_SHA=507e2c6243e1e5a1a7875e9da7335ff1158cf494
RESULT_CI=branch 30891985728 PASS; dev 30892043700 PASS
```

### R3 · R3-W4-F7

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W4-F7
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=exact-one metric selection contract
TASK_CARD_RANGE=R3-01·03 Node1 approved metric selection
CURRENT_TASK_CARD_ID=R3-01
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=b99d1fb8c59fe0c7a44a783325ef8959848fc01e
START_POINT=origin/daesung 2cc8a6bf21aeb333198936c54f9784a999a2677a에 origin/dev b99d1fb8c59fe0c7a44a783325ef8959848fc01e를 병합해 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R3-W4-F7@b99d1fb
CONTRACT_VERSION=MODEL-v1.1.0-DRAFT; MODEL-v1.0.0-compatible; METRIC-GLOSSARY-v1.0.0-DRAFT
ALLOWED_PATHS=src/ai/node1.py; src/ai/contracts/node_io.v0.1.json; src/ai/contracts/metric_glossary.i5.v1.json; tests/ai/test_node1.py; tests/ai/test_contracts.py; handoffs/R3-W4-F7.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; training dataset·prompt·modelops; Docker·Trino·endpoint·RunPod; dependency; secret
HANDOFF_MANIFEST=handoffs/R3-W4-F7.json
ACCEPTANCE_CRITERIA=Node1 response에 required nullable selected_metric_id를 additive로 추가하고, 입력 business_terms에서 질문과 일치한 승인 metric 후보가 정확히 1개일 때만 그 ID를 선택한다. 0개는 metric_missing, 2개 이상은 metric_ambiguous이며 둘 다 selected_metric_id=null이고 clarification을 제공한다. metric_candidates는 진단·호환용으로 유지하고 dimension 다중 일치는 metric ambiguity와 분리한다. 사전순 첫 항목 선택이나 새 ID 생성은 금지한다. versioned glossary는 현재 제품 registry 5개 ID(recognized_room_revenue·expired_points·fnb_net_revenue·facility_revenue·actual_attendees)의 한국어·영문 alias만 제공하며 asset·entitlement·Gate 정보를 포함하지 않는다.
ACCEPTANCE_IDS=AC1_SELECTED_FIELD;AC2_EXACT_ONE;AC3_MISSING;AC4_AMBIGUOUS;AC5_NO_ARBITRARY_PICK;AC6_COMPAT_CANDIDATES;AC7_DIMENSION_SEPARATE;AC8_VERSIONED_GLOSSARY;AC9_LOCAL_ONLY
TEST_COMMANDS=python -m json.tool src/ai/contracts/metric_glossary.i5.v1.json; python -m pytest -p no:cacheprovider tests/ai/test_node1.py tests/ai/test_contracts.py -q; python -m pytest -p no:cacheprovider tests/ai -q; python -m compileall -q src/ai; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_GLOSSARY;T2_TARGET;T3_AI;T4_COMPILE;T5_SCOPE;T6_DIFF
STOP_CONDITIONS=entitlement·Gate 판정을 Node1에 추가; R4 backend 변경 필요; 승인 ID 밖 자유 생성; glossary alias 충돌을 임의 우선순위로 해결; 기존 Node1 payload 비호환; 외부 model·RunPod·비용 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local schema·glossary·Node1·test·허용 경로 commit·daesung push만 승인한다.
AUTO_FAIL_CONDITIONS=복수 후보 임의 선택; 미등록 ID 생성; 권한 정보 포함; 기존 candidate 제거; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=5개 glossary ID·alias와 exact-one/missing/ambiguous/dimension 회귀, AI 전체 회귀, branch CI를 제출한다. 통과 뒤 R4가 entitlement와 교집합해 제품 Context에 선택 ID 1개만 전달하도록 별도 발행한다.
RESULT_SHA=dcc8ada48738636ded8c40de069a4ef49b604396
RESULT_CI=branch 30893491712 PASS; dev 30893564400 PASS
```

### R4 · R4-W4-F8

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W4-F8
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=selected metric entitlement consumption
TASK_CARD_RANGE=R4-06·08 Node1 selected metric Context 소비
CURRENT_TASK_CARD_ID=R4-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=2efa20cf48676e6e718e92637f702ba7fa3452d7
START_POINT=origin/jaehong 2efa20cf48676e6e718e92637f702ba7fa3452d7에서 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W4-F8@2efa20c
CONTRACT_VERSION=MODEL-v1.0.0-compatible; MODEL-v1.1.0-DRAFT selected_metric_id; METRIC-GLOSSARY-v1.0.0-DRAFT; I4-CONTEXT-v2.2.0-DRAFT
ALLOWED_PATHS=app/backend/app/services/analysis_service.py; app/backend/app/services/context_builder.py; app/backend/app/services/pipeline_support.py; app/backend/app/adapters/i2_data_platform.py; tests/backend/test_analysis_pipeline.py; tests/backend/test_context_builder.py; tests/backend/test_i2_data_platform.py; tests/backend/test_production_model.py; tests/backend/test_execution_control.py; handoffs/R4-W4-F8.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/ai/**; src/data/**; Report·OpenAPI·DB·migration; frontend; root Compose·env·CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R4-W4-F8.json
ACCEPTANCE_CRITERIA=asset search와 entitlement로 만든 candidate Context의 metric ID와 R3 versioned glossary의 교집합만 Node1 business_terms에 전달하고 R3 normalize_question을 재사용한다. selected_metric_id가 정확히 1개이며 entitled registry와 선택 asset에 존재할 때만 final Context를 만들고, final Context·package hash·model payload·plan/result cache key에는 그 metric 1개만 보존한다. Node2 reference와 Node3 metric은 같은 selected ID를 사용한다. metric missing·ambiguous·미승인·중복은 SQL/model/query 전에 fail-closed 재질문 또는 계약 오류로 종료한다. R4에 alias·우선순위를 hardcode하지 않고 entitlement 전 metric을 노출하지 않는다. 기존 template·legacy single metric과 model call budget을 회귀 유지한다.
ACCEPTANCE_IDS=AC1_ENTITLED_TERMS;AC2_NODE1_REUSE;AC3_EXACT_ONE;AC4_FINAL_CONTEXT;AC5_HASH_CACHE;AC6_NODE2_NODE3_MATCH;AC7_FAIL_CLOSED;AC8_NO_HARDCODE;AC9_LEGACY_COMPAT;AC10_BUDGET
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend/test_i2_data_platform.py tests/backend/test_context_builder.py tests/backend/test_production_model.py tests/backend/test_analysis_pipeline.py tests/backend/test_execution_control.py -q; python -m pytest -p no:cacheprovider tests/backend -q; python -m compileall -q app/backend/app; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_TARGET;T2_BACKEND;T3_COMPILE;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=R3 schema·glossary 또는 R2 registry 변경 필요; R4 alias·metric 우선순위 hardcode; entitlement 전 노출; 복수 metric을 Node2에 전달; 기존 template 계약 비호환; Report·frontend 변경 필요; 허용 경로 밖 변경; 외부 model·비용·secret 필요; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=없음. local backend·test·허용 경로 commit·jaehong push만 승인한다.
AUTO_FAIL_CONDITIONS=임의 metric 선택; 권한 밖 metric; final Context 복수 metric; selected ID hash/cache 누락; SQL 전 fail-closed 누락; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=missing·ambiguous·unauthorized·exact-one과 Context/hash/cache/Node2/Node3 동일 ID, backend 전체 회귀와 branch CI를 제출한다. 통과 뒤 같은 asset의 두 번째 metric 등록을 재판정한다.
RESULT_SHA=23efdb83810496e73d5d5defbb7aa00a3e2c882e
RESULT_CI=branch 30895702408 PASS; dev 30895792161 PASS
```

### R5 · R5-W4-F4

```text
STATUS=BLOCKED
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W4-F4
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=OPENAPI-v1.1 actual Report consumer
TASK_CARD_RANGE=R5-12·17 actual Report definition·manual command·Run History integration
CURRENT_TASK_CARD_ID=R5-17
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=2b7d2dba46e57be6ad7a5e131d7c7b525ee43a76
START_POINT=origin/minji a7c4128b3282f94bf4da876436f2a21ed6f15b7c에 origin/dev 2b7d2dba46e57be6ad7a5e131d7c7b525ee43a76을 병합해 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R5-W4-F4R1@2b7d2db
CONTRACT_VERSION=OPENAPI-v1.1.0-DRAFT additive; OPENAPI-v1.0.0 request context; REPORT-v1.0.0 wire compatible; REPORT-v1.1.0-DRAFT behavior
ALLOWED_PATHS=app/enterprise-react/src/api/reportClient.ts; app/enterprise-react/src/contracts/report.ts; app/enterprise-react/src/pages/ReportsPage.jsx; app/enterprise-react/src/styles.css; tests/frontend/contracts.test.mjs; handoffs/R5-W4-F4.json; docs/markdown/daily_reports/minji/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/report/**; migration·DB·worker·schedule; 다른 page·route; root Compose·env·CI; dependency; secret; share·export
HANDOFF_MANIFEST=handoffs/R5-W4-F4.json
ACCEPTANCE_CRITERIA=HTTP Report client를 기본으로 하고 fixture는 VITE_REPORT_MODE=fixture에서만 선택하며 API 오류 시 자동 fallback하지 않는다. 공개 9개 operation과 strict snake_case request·response를 typed contract로 소비하고 Bearer·X-User-Id·report_admin·X-As-Of·X-Trace-Id·Asia/Seoul·OPENAPI-v1.0.0 header를 보존한다. definition create/list/get, draft block replace, 명시적 approve, approved version의 next draft를 서버 응답으로만 갱신한다. API mode는 UUID와 table·chart·text block만 전송한다. manual request는 definition_id·version·as_of·idempotency_key만 보내고 queued command를 run으로 만들지 않는다. Run History/detail은 GET 실제 상태만 표시한다. definition A→B 전환의 늦은 A 응답이 B state를 덮어쓰지 않도록 request sequence 또는 취소 경계를 두고, 동시 mutation 동안 pending을 먼저 끝난 요청이 해제하지 않도록 요청 수명별 busy 상태를 유지한다. 재시도 성공 시 이전 error를 지운다. loading·401/403·error·empty·queued receipt를 text·icon·aria-live로 구분한다. fixture badge·6상태·12-column·keyboard·focus·반응형을 유지하고 API mode에서 서버에 없는 성공·수치·작성자·기간·worker 진행을 표시하지 않는다. contract test는 X-As-Of·X-User-Id·body 요청 Content-Type을 검증한다.
ACCEPTANCE_IDS=AC1_HTTP_DEFAULT;AC2_EXPLICIT_FIXTURE;AC3_TYPED_CONTRACT;AC4_ADMIN_CONTEXT;AC5_DEFINITION_FLOW;AC6_DRAFT_REPLACE;AC7_MANUAL_BOUNDARY;AC8_REAL_HISTORY;AC9_ASYNC_STATES;AC10_NO_FAKE_SUCCESS;AC11_FIXTURE_COMPAT
TEST_COMMANDS=python app/backend/scripts/export_openapi.py --check; python -m pytest -p no:cacheprovider tests/backend/test_openapi_contract.py tests/backend/test_report_registration.py -q; node tests/frontend/contracts.test.mjs; npm --prefix app/enterprise-react run build; browser fixture mode badge·6상태·keyboard·1440·1024·768·360 확인; browser API mode local backend definition create→PUT replace→approve→next draft·manual queued receipt·real history empty/detail·401·403·409·422·503 확인; python .github/scripts/gate_scope.py --branch minji --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_OPENAPI;T2_BACKEND_CONSUMER;T3_FRONTEND_CONTRACT;T4_BUILD;T5_FIXTURE_BROWSER;T6_API_BROWSER;T7_SCOPE;T8_DIFF
STOP_CONDITIONS=PUT preflight 실패; local Report runtime·migration 부재로 API browser 검증 불가; request·response version drift; fixture 자동 fallback 또는 fake success; worker·schedule·public result ingestion 필요; unsupported block에 backend 변경 필요; production secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local frontend·stub test·기존 local synthetic Report API/DB 검증·허용 경로 commit·minji push만 승인한다. 외부 배포·비용·secret·Docker resource 변경은 금지한다.
AUTO_FAIL_CONDITIONS=HTTP 비기본; 자동 fixture fallback; client 결과/status 생성; queued를 run으로 표시; server에 없는 success; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=typed client·전체 필수 headers·definition/draft/manual/history·fixture 경계·stale response 차단·동시 pending·오류 복구, build·contract·두 browser mode·branch CI를 제출한다. worker 없는 queued 이후 상태는 미구현으로 명시한다. 현재 origin/minji a7c4128의 Python·frontend·문서 job은 PASS지만 browser T5·T6 BLOCKED로 role-scope·quality-gate가 FAIL이며, UI 경쟁 상태 P1이 확인되어 dev 병합을 차단한다.
```

### R5 · R5-W4-F5

```text
STATUS=MERGED_DEV
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W4-F5
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=OPENAPI-v1.1 actual Report consumer scope recovery and browser evidence
TASK_CARD_RANGE=R5-12·17 actual Report definition·manual command·Run History 재검증
CURRENT_TASK_CARD_ID=R5-17
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=6c05c6057d0518d3edab412bb1af860da0d6ce69
START_POINT=origin/minji a864d79b95c976680f8427c7140abf7201979c35에 origin/dev 6c05c6057d0518d3edab412bb1af860da0d6ce69을 병합해 시작한다. history rewrite·force push·기존 미커밋 변경 폐기를 금지한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R5-W4-F5@6c05c60
CONTRACT_VERSION=OPENAPI-v1.1.0-DRAFT additive; OPENAPI-v1.0.0 request context; REPORT-v1.0.0 wire compatible; REPORT-v1.1.0-DRAFT behavior
IMPLEMENTATION_PATHS=app/enterprise-react/src/api/reportClient.ts; app/enterprise-react/src/contracts/report.ts; app/enterprise-react/src/pages/ReportsPage.jsx; app/enterprise-react/src/styles.css; tests/frontend/contracts.test.mjs; docs/markdown/daily_reports/minji/일일보고.md
CLEANUP_ONLY_PATHS=app/enterprise-react/src/App.jsx; app/enterprise-react/src/api/analysisClient.ts; app/enterprise-react/src/components/analysis/AnalysisStatePanel.tsx; app/enterprise-react/src/components/layout/AppHeader.jsx; app/enterprise-react/src/components/layout/AppSidebar.jsx; app/enterprise-react/src/data/analysisFixtures.ts; app/enterprise-react/src/pages/AgentPage.jsx; app/enterprise-react/src/pages/CatalogPage.jsx; app/enterprise-react/src/pages/ConnectionsPage.jsx; app/enterprise-react/vite.config.js; docs/markdown/daily_reports/team_summaries/4주차/20260804.md; handoffs/R5-W4-F4.json
ALLOWED_PATHS=app/enterprise-react/src/App.jsx; app/enterprise-react/src/api/analysisClient.ts; app/enterprise-react/src/api/reportClient.ts; app/enterprise-react/src/components/analysis/AnalysisStatePanel.tsx; app/enterprise-react/src/components/layout/AppHeader.jsx; app/enterprise-react/src/components/layout/AppSidebar.jsx; app/enterprise-react/src/contracts/report.ts; app/enterprise-react/src/data/analysisFixtures.ts; app/enterprise-react/src/pages/AgentPage.jsx; app/enterprise-react/src/pages/CatalogPage.jsx; app/enterprise-react/src/pages/ConnectionsPage.jsx; app/enterprise-react/src/pages/ReportsPage.jsx; app/enterprise-react/src/styles.css; app/enterprise-react/vite.config.js; tests/frontend/contracts.test.mjs; handoffs/R5-W4-F4.json; handoffs/R5-W4-F5.json; docs/markdown/daily_reports/minji/일일보고.md; docs/markdown/daily_reports/team_summaries/4주차/20260804.md
FORBIDDEN_PATHS=app/backend/**; src/report/**; migration·DB·worker·schedule; 위 CLEANUP_ONLY_PATHS의 신규 기능 변경; 다른 frontend path·route; root Compose·env·CI; dependency; secret; share·export
HANDOFF_MANIFEST=handoffs/R5-W4-F5.json
ACCEPTANCE_CRITERIA=origin/dev 대비 범위 초과 변경은 CLEANUP_ONLY_PATHS에서 origin/dev 내용으로만 복구하고 Report 구현은 IMPLEMENTATION_PATHS에만 남긴다. HTTP Report client를 기본으로 하고 fixture는 VITE_REPORT_MODE=fixture에서만 선택하며 API 오류 시 자동 fallback하지 않는다. 공개 9개 operation과 strict snake_case request·response, 필수 인증·사용자·권한·시각·trace header를 보존한다. definition create/list/get, draft replace, approve, next draft, manual queued receipt, 실제 Run History를 서버 응답으로만 처리한다. 늦은 definition 응답·동시 mutation busy·재시도 error clear를 검증한다. API mode에서 서버에 없는 success·수치·작성자·기간·worker 진행을 만들지 않는다. fixture와 local API browser 검증을 실제 실행하고 BLOCKED·Not Run을 PASS로 기록하지 않는다. 새 handoff는 BASE_SHA·DIRECTIVE_TOKEN·CHANGED_FILES·RESULT_SHA와 실제 test 결과가 일치해야 한다.
ACCEPTANCE_IDS=AC1_SCOPE_RECOVERY;AC2_HTTP_DEFAULT;AC3_EXPLICIT_FIXTURE;AC4_TYPED_CONTRACT;AC5_ADMIN_CONTEXT;AC6_DEFINITION_FLOW;AC7_MANUAL_BOUNDARY;AC8_REAL_HISTORY;AC9_ASYNC_STATES;AC10_NO_FAKE_SUCCESS;AC11_BROWSER_EVIDENCE;AC12_HANDOFF_EXACT
TEST_COMMANDS=python app/backend/scripts/export_openapi.py --check; python -m pytest -p no:cacheprovider tests/backend/test_openapi_contract.py tests/backend/test_report_registration.py -q; node tests/frontend/contracts.test.mjs; npm --prefix app/enterprise-react run build; browser fixture mode badge·6상태·keyboard·1440·1024·768·360 확인; browser API mode local backend definition create→PUT replace→approve→next draft·manual queued receipt·real history empty/detail·401·403·409·422·503 확인; python .github/scripts/gate_scope.py --branch minji --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_OPENAPI;T2_BACKEND_CONSUMER;T3_FRONTEND_CONTRACT;T4_BUILD;T5_FIXTURE_BROWSER;T6_API_BROWSER;T7_SCOPE;T8_DIFF
STOP_CONDITIONS=기존 미커밋 변경 폐기·history rewrite·force push 필요; CLEANUP_ONLY_PATHS에 신규 기능을 남겨야 함; browser 또는 local Report API 검증 BLOCKED; request·response version drift; fixture 자동 fallback 또는 fake success; worker·schedule·public result ingestion 필요; production secret·외부 비용 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local frontend·기존 local synthetic Report API/DB·browser 검증·허용 경로 commit·minji push만 승인한다. 외부 배포·비용·secret·Docker resource 변경·force push는 금지한다.
AUTO_FAIL_CONDITIONS=범위 초과 기능 잔존; HTTP 비기본; 자동 fixture fallback; client 결과/status 생성; queued를 run으로 표시; server에 없는 success; browser BLOCKED; handoff 불일치; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=origin/dev 대비 변경 경로와 cleanup-only 복구, typed client·필수 headers·definition/draft/manual/history·fixture 경계·경쟁 상태, build·contract·두 browser mode·branch CI와 정확한 R5-W4-F5 handoff를 제출한다. 모두 PASS일 때만 dev 병합을 검토한다.
RESULT_SHA=b58d3c00fc0fd9936ad3a5a0f86911074b631892
RESULT_CI=branch 31347368113 PASS
```

### R2 · R2-W5-F1

```text
STATUS=BLOCKED
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F1
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=representative three-source gold query
TASK_CARD_RANGE=R2-15 대표 3-source 정답 조회
CURRENT_TASK_CARD_ID=R2-15
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=ccbb94cfdb20caf975975a68f6beeb5f37f7eff0
START_POINT=origin/seung ccbb94cfdb20caf975975a68f6beeb5f37f7eff0에서 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R2-W5-F1@ccbb94c
CONTRACT_VERSION=I3-DATA-v1.1.0-DRAFT; schema 1.0.0; seed 20260729; scenario 1.0.0
ALLOWED_PATHS=infrastructure/database/sql/queries/i5_gold_three_source_operating_revenue.sql; src/data/i3_contract.v1.json; tests/data/test_i3_contract.py; handoffs/R2-W5-F1.json; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/ai/**; frontend/**; DataHub recipe·source DDL·seed·root Compose·env·CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R2-W5-F1.json
ACCEPTANCE_CRITERIA=기존 승인 schema·synthetic seed만 사용해 서로 다른 3개 source의 운영 매출을 월 단위 KRW로 결합하는 read-only Trino 정답 SQL 1개를 추가한다. 각 source는 자기 CTE에서 승인 상태·취소/void·forecast 제외·Asia/Seoul 기간 경계를 적용하고, source 간 raw row JOIN 대신 집계 결과를 month로 결합한다. contract에는 SQL path·입력 source·기간·정렬된 결과 hash·row count·합계를 기록하고 test가 파일 hash와 결정론적 fixture를 검증한다. 기존 2-source gold와 watermark·평가 manifest는 변경하지 않는다.
ACCEPTANCE_IDS=AC1_THREE_SOURCES;AC2_READ_ONLY;AC3_SOURCE_FILTERS;AC4_AGGREGATE_JOIN;AC5_DETERMINISTIC_HASH;AC6_EXISTING_COMPAT
TEST_COMMANDS=python -m json.tool src/data/i3_contract.v1.json; python -m pytest -p no:cacheprovider tests/data/test_i3_contract.py -q; python -m pytest -p no:cacheprovider tests/data -q; local synthetic Trino에서 SQL 실행 후 row count·합계·hash 확인; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_JSON;T2_TARGET;T3_DATA;T4_LOCAL_TRINO;T5_SCOPE;T6_DIFF
STOP_CONDITIONS=승인되지 않은 source·column·JOIN 필요; 3-source 결과를 raw row 수준으로 결합; 기존 seed·DDL·recipe 변경 필요; local Trino 또는 source가 불건전; 외부 서비스·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=기존 local synthetic DB·Trino read-only 조회와 허용 경로 commit·seung push만 승인한다. volume reset·외부 전송·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=source 3개 미만; forecast·취소·void 포함; 비결정 기간; hash 불일치; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=SQL의 3-source·filter·집계 후 결합, 실제 local Trino 결과와 contract hash, data 전체 회귀와 branch CI를 제출한다.
BLOCKED_REASON=사용자가 DataHub v1.7.0 최신화를 우선 요청했고, 기존 허용 범위로는 공식 v1.7.0 consumer pin·호환 증거를 변경할 수 없다. 기존 3-source Gold 요구도 지점별·고정 직전 달·GOLD 회원 객실/F&B 매출 grain으로 보완이 필요하므로 현재 token을 폐기하고 DataHub 업그레이드 완료 뒤 owner-scoped REWORK로 재발행한다.
```

### R1 · R1-W5-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F1
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=R2~R4 owner-scoped work issuance
TASK_CARD_RANGE=R1-03 역할별 실행 묶음 발행·승인
CURRENT_TASK_CARD_ID=R1-03
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=ccbb94cfdb20caf975975a68f6beeb5f37f7eff0
START_POINT=origin/junhee ccbb94cfdb20caf975975a68f6beeb5f37f7eff0에서 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W5-F1@ccbb94c
ALLOWED_PATHS=docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/ai_docs/Answervice_기획서_기반_현재_구현_진행현황_20260810.md; handoffs/R1-W5-F1.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 제품 경로; root Compose·env·CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R1-W5-F1.json
ACCEPTANCE_CRITERIA=R2~R4의 terminal 카드·remote branch·WBS 진행 항목을 대조해 각 역할에 owner-scoped 실행 묶음 하나씩 발행한다. R2는 local synthetic 3-source 정답 조회, R3는 고유 commit 보존·off-scope 복구 후 required filter SQL, R4는 legacy migration 호환을 독립 카드로 승인한다. 각 카드에 최신 dev BASE_SHA·허용 경로·검증·중단·외부 권한 경계를 기록하고 planned path 검사를 통과한다. 같은 시점에 작성된 기획서 기반 구현 현황 스냅샷은 ai_docs 참고자료로 보존하되 WBS·Gate 판정을 덮어쓰지 않는다. 외부 model·RunPod·비용·secret을 승인하지 않는다.
ACCEPTANCE_IDS=AC1_ROLE_STATE;AC2_R2_CARD;AC3_R3_RECOVERY;AC4_R4_COMPAT;AC5_SCOPE_CHECK;AC6_NO_EXTERNAL_COST;AC7_STATUS_SNAPSHOT
TEST_COMMANDS=document validation; python .github/scripts/gate_scope.py --dashboard --next-gate I5; 역할별 planned path scope 검사; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_DOCS;T2_DASHBOARD;T3_PLANNED_SCOPE;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=역할 소유권 혼합; R3 고유 commit 폐기·history rewrite; 외부 서비스·비용·secret 승인; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=Gate 원장·handoff·R1 보고와 승인된 commit·junhee push·dev 병합만 허용한다. 외부 비용·secret·제품 코드 변경은 금지한다.
AUTO_FAIL_CONDITIONS=base SHA 누락; 역할별 복수 활성 카드; planned path 실패; 외부 비용 승인; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R2~R4 dashboard READY, 각 카드 planned path PASS, R1 branch CI와 정확한 handoff를 제출한다.
RESULT_SHA=4dd1ba5e1ba8a21ae7e7054d42f1639d100c521b
RESULT_CI=branch 31347640928 PASS
```

### R3 · R3-W5-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F1
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=branch scope recovery and required-filter SQL generation
TASK_CARD_RANGE=R3-04·05 Node 2 Context 제한 SQL·1회 수정
CURRENT_TASK_CARD_ID=R3-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=ccbb94cfdb20caf975975a68f6beeb5f37f7eff0
START_POINT=origin/daesung e3324660425bebb6b2cbe5f8e614bae8bbf1f547에 origin/dev ccbb94cfdb20caf975975a68f6beeb5f37f7eff0을 병합해 시작한다. history rewrite·force push·고유 commit 폐기를 금지한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R3-W5-F1@ccbb94c
CONTRACT_VERSION=MODEL-v1.1.0-DRAFT; I4-CONTEXT-v2.2.0-DRAFT
IMPLEMENTATION_PATHS=src/ai/node2.py; tests/ai/test_node2.py; tests/ai/test_contracts.py; handoffs/R3-W5-F1.json; docs/markdown/daily_reports/daesung/일일보고.md
CLEANUP_ONLY_PATHS=.gitignore; docs/Answervice_기획서.md; docs/markdown/Answervice_sLLM_RunPod_재구축.md; infrastructure/database/datahub/compose.consumer.yml; infrastructure/database/datahub/recipes/banquet.i3.yml; infrastructure/database/datahub/recipes/crm.i2.yml; infrastructure/database/datahub/recipes/facility.i3.yml; infrastructure/database/datahub/recipes/pms.i2.yml; infrastructure/database/datahub/recipes/pos.i3.yml; src/ai/training/README.md; src/ai/training/build_case_specs.py; src/ai/training/build_smoke_manifest.py; src/ai/training/build_validation_v2.py; src/ai/training/case_specs.example.jsonl; src/ai/training/dataset.py; src/ai/training/evaluate_endpoint.py; src/ai/training/evaluate_lora.py; src/ai/training/generate_scenarios.py; src/ai/training/requirements.txt; src/ai/training/train_lora.py; src/ai/training/verify_case_specs.py; tests/ai/test_training_dataset.py; tests/ai/test_training_scenarios.py; tests/ai/test_training_verification.py; tests/ai/test_validation_v2.py
ALLOWED_PATHS=.gitignore; docs/Answervice_기획서.md; docs/markdown/Answervice_sLLM_RunPod_재구축.md; infrastructure/database/datahub/compose.consumer.yml; infrastructure/database/datahub/recipes/banquet.i3.yml; infrastructure/database/datahub/recipes/crm.i2.yml; infrastructure/database/datahub/recipes/facility.i3.yml; infrastructure/database/datahub/recipes/pms.i2.yml; infrastructure/database/datahub/recipes/pos.i3.yml; src/ai/node2.py; src/ai/training/README.md; src/ai/training/build_case_specs.py; src/ai/training/build_smoke_manifest.py; src/ai/training/build_validation_v2.py; src/ai/training/case_specs.example.jsonl; src/ai/training/dataset.py; src/ai/training/evaluate_endpoint.py; src/ai/training/evaluate_lora.py; src/ai/training/generate_scenarios.py; src/ai/training/requirements.txt; src/ai/training/train_lora.py; src/ai/training/verify_case_specs.py; tests/ai/test_node2.py; tests/ai/test_contracts.py; tests/ai/test_training_dataset.py; tests/ai/test_training_scenarios.py; tests/ai/test_training_verification.py; tests/ai/test_validation_v2.py; handoffs/R3-W5-F1.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; 위 CLEANUP_ONLY_PATHS의 신규 내용 유지; model endpoint·RunPod·dataset 생성·평가 실행; root Compose·env·CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R3-W5-F1.json
ACCEPTANCE_CRITERIA=origin/daesung의 고유 commit은 보존하되 CLEANUP_ONLY_PATHS 결과를 origin/dev 내용으로만 복구한다. Node2는 Context의 선택 metric에 포함된 typed required_filters를 column·operator·value allowlist로 검증해 parameterized WHERE에 모두 포함하며, context 밖 field·raw SQL·지원하지 않는 operator·중복 filter는 fail-closed한다. 날짜 parameter와 required filter parameter 이름·순서는 결정론적으로 고정하고 response reference에는 실제 참조 column을 포함한다. Node2-prime은 Controller가 허용한 normalized error code에서만 같은 Context·filter 계약으로 정확히 1회 수정한다. case ID·정답 SQL·특정 metric ID hardcode를 금지하고 기존 no-filter payload 호환을 유지한다.
ACCEPTANCE_IDS=AC1_SCOPE_RECOVERY;AC2_TYPED_FILTERS;AC3_PARAMETERIZED;AC4_FAIL_CLOSED;AC5_DETERMINISTIC;AC6_REFERENCES;AC7_ONE_REPAIR;AC8_NO_CASE_HARDCODE;AC9_COMPAT
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/ai/test_node2.py tests/ai/test_contracts.py -q; python -m pytest -p no:cacheprovider tests/ai -q; python -m compileall -q src/ai; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_TARGET;T2_AI;T3_COMPILE;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=고유 commit 폐기·history rewrite·force push 필요; CLEANUP_ONLY_PATHS에 신규 내용을 유지해야 함; Context schema 변경·R2/R4 경로 변경 필요; raw SQL filter 또는 arbitrary identifier 허용; 외부 model·RunPod·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local Node2·test·범위 복구와 허용 경로 commit·daesung push만 승인한다. model download·RunPod·외부 endpoint·비용·secret·force push는 금지한다.
AUTO_FAIL_CONDITIONS=off-scope 잔존; filter 누락·문자열 삽입; context 밖 column; repair 2회 이상; case hardcode; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=origin/dev 대비 cleanup-only 복구, typed required filter의 SQL·parameter·reference와 거부 case, AI 전체 회귀, 정확한 handoff와 branch CI를 제출한다.
RESULT_SHA=93505e81637a291f8e4792a53285a815d463384a
RESULT_CI=branch 31349329692 PASS
```

### R3 · R3-W5-F2

```text
STATUS=BLOCKED
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F2
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=parameterized model evaluation and full dev CI recovery
TASK_CARD_RANGE=R3-14 endpoint evaluator·AI G2 regression contract alignment
CURRENT_TASK_CARD_ID=R3-14
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=308660c
START_POINT=origin/daesung을 최신 dev 308660c로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R3-W5-F2@308660c
CONTRACT_VERSION=MODEL-v1.1.0-DRAFT; G2 parameterized required-filter contract
ALLOWED_PATHS=src/ai/training/evaluate_endpoint.py; src/ai/training/verify_case_specs.py; tests/ai/test_training_verification.py; tests/ai/test_validation_v2.py; tests/ai/test_eval_runner.py; handoffs/R3-W5-F2.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; compiled/train/validation/Gold dataset; model·prompt registry; RunPod·endpoint 실행; root Compose/env/CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R3-W5-F2.json
ACCEPTANCE_CRITERIA=R4 G2의 MODEL literal filter 금지 경계를 되돌리지 않고 endpoint evaluator와 AI 회귀를 Node2의 parameterized required-filter 계약에 맞춘다. generated/expected plan은 Context가 승인한 placeholder와 결정론적 parameter만 사용하며 arbitrary parameter·literal 우회·OR·값 변조는 G2에서 차단한다. Trino 평가가 실행될 경우 승인된 parameter를 안전하게 binding한 SQL만 전달하고 generated·expected 동일 경계를 적용한다. 기존 compiled dataset이 parameterized contract와 불일치하면 데이터를 무단 재작성하지 않고 change request로 반환한다.
ACCEPTANCE_IDS=AC1_NO_LITERAL_BYPASS;AC2_PARAMETERIZED_EVALUATOR;AC3_CONTEXT_PARAMETERS;AC4_SAFE_TRINO_BINDING;AC5_AI_REGRESSION;AC6_DATASET_BOUNDARY
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/ai/test_training_verification.py tests/ai/test_validation_v2.py tests/ai/test_eval_runner.py -q; python -m pytest -p no:cacheprovider tests/ai -q; python -m compileall -q src/ai; python .github/scripts/gate_scope.py --branch daesung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_TARGET;T2_AI;T3_COMPILE;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=backend G2 완화 필요; compiled dataset 재생성·RunPod·model endpoint 필요; arbitrary literal/parameter 허용; R4/R2 파일 변경 필요; dependency·secret·비용 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local evaluator·AI test·handoff·R3 보고와 승인된 commit·daesung push만 허용한다. model/RunPod/Trino container 실행·데이터 재생성·외부 비용·secret은 금지한다.
AUTO_FAIL_CONDITIONS=MODEL literal filter 재허용; Context 밖 parameter; unsafe string 치환; dataset 무단 변경; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=dev CI 31352194575의 3개 METRIC_FILTER_MISSING 실패를 parameterized evaluator·test로 해소하고 AI 전체·branch CI와 정확한 handoff를 제출한다.
BLOCKED_REASON=기존 evaluator 범위만으로는 string·boolean·number·date typed contract, period_end_exclusive, R4 단일 binder를 확정할 수 없다. R2 생산자와 R4 소비자 계약이 선행되어야 하므로 token을 폐기하고 로컬 부분 변경은 stash로 보존한다.
```

### R3 · R3-W5-F3

```text
STATUS=MERGED_DEV
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F3
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=R2 typed registry와 R4 Context·G2·binder 통합
TASK_CARD_RANGE=R3-04·05·14 Node2 typed parameter 출력·endpoint evaluator 정합화
CURRENT_TASK_CARD_ID=R3-04
BASE_BRANCH=dev
BASE_SHA=83c5d94b762938c4ecab1d1297d54bedbfa1e8da
START_POINT=origin/daesung을 최신 dev 83c5d94로 fast-forward한 뒤 시작한다. 로컬 stash는 자동 적용하지 않고 현재 계약과 path를 대조한 뒤 필요한 변경만 수동 반영한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R3-W5-F3@83c5d94
ALLOWED_PATHS=src/ai/contracts/node_io.v0.1.json; src/ai/node2.py; src/ai/training/evaluate_endpoint.py; src/ai/training/verify_case_specs.py; tests/ai/test_contracts.py; tests/ai/test_node2.py; tests/ai/test_training_verification.py; tests/ai/test_validation_v2.py; tests/ai/test_eval_runner.py; handoffs/R3-W5-F3.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; compiled/train/validation/Gold dataset; RunPod·외부 endpoint; root Compose/env/CI; dependency; secret
ACCEPTANCE_CRITERIA=Node2는 R2/R4가 동결한 string·boolean·number·date parameter contract와 period_start·period_end_exclusive·required_filter_N 이름을 그대로 출력한다. generated/expected plan은 Context의 placeholder·type·value와 일치해야 하며 literal·OR·unknown placeholder·값 변조를 허용하지 않는다. R3 내부에 별도 실행 binder를 복제하지 않고 R4 공개 binder 계약을 소비하며 dataset 불일치는 별도 재생성 카드로 반환한다.
STOP_CONDITIONS=R2/R4 계약 미통합; backend 완화·별도 binder·dataset 재생성 필요; model·RunPod·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
R1_REVIEW_CONDITIONS=R2 생산자→R4 소비자 통합 뒤 최신 BASE_SHA·token으로 READY 전환하며 Node2→G2→binder 조합 회귀는 별도 R1 통합 카드에서 검증한다.
RESULT_SHA=c2b44b2c1b2200a4b05b489ea9339bf463f3df11
RESULT_CI=branch 31355000164 PASS
```

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

### R4 · R4-W5-F1

```text
STATUS=BLOCKED
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F1
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=legacy application DB migration compatibility
TASK_CARD_RANGE=R4-03 application DB Alembic REWORK
CURRENT_TASK_CARD_ID=R4-03
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=ccbb94cfdb20caf975975a68f6beeb5f37f7eff0
START_POINT=origin/jaehong 23efdb83810496e73d5d5defbb7aa00a3e2c882e에 origin/dev ccbb94cfdb20caf975975a68f6beeb5f37f7eff0을 병합해 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F1@ccbb94c
CONTRACT_VERSION=OPENAPI-v1.1.0-DRAFT; REPORT-v1.1.0-DRAFT; Alembic current head 20260804_05
ALLOWED_PATHS=app/backend/migrations/versions/20260810_06_legacy_20260803_03_compatibility.py; app/backend/migrations/versions/20260810_07_merge_legacy_compatibility.py; app/backend/README.md; tests/backend/test_report_migration.py; tests/backend/test_migration_compatibility.py; handoffs/R4-W5-F1.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=기존 migration 파일 수정; application table·Report contract·router·frontend; src/ai/**; src/data/**; root Compose·env·CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R4-W5-F1.json
ACCEPTANCE_CRITERIA=현행 저장소의 migration graph에 없는 legacy revision 20260803_03이 기록된 보존 DB를 stamp·drop·데이터 삭제 없이 current head까지 올릴 수 있는 additive compatibility branch와 merge revision을 제공한다. 빈 DB→head와 legacy 20260803_03→head 두 경로가 모두 단일 head에서 끝나며 동일 schema·grant·Report registration 결과를 갖는다. legacy revision이 실제 기대 schema와 다르면 임의 추정하지 않고 fail-closed precondition으로 중단한다. downgrade는 데이터 손실 없이 migration metadata만 안전하게 되돌릴 수 있는 범위만 제공하고 기존 migration 파일은 수정하지 않는다.
ACCEPTANCE_IDS=AC1_LEGACY_REVISION;AC2_NO_STAMP_DROP;AC3_EMPTY_UPGRADE;AC4_LEGACY_UPGRADE;AC5_SINGLE_HEAD;AC6_SCHEMA_EQUIVALENCE;AC7_FAIL_CLOSED;AC8_EXISTING_IMMUTABLE
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend/test_report_migration.py tests/backend/test_migration_compatibility.py -q; python -m pytest -p no:cacheprovider tests/backend -q; alembic heads 단일 head 확인; 격리 empty DB와 legacy revision fixture에서 alembic upgrade head; python -m compileall -q app/backend; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_TARGET;T2_BACKEND;T3_HEAD;T4_UPGRADE_PATHS;T5_COMPILE;T6_SCOPE;T7_DIFF
STOP_CONDITIONS=legacy schema를 확인할 수 없음; stamp·drop·기존 migration 수정·운영 데이터 삭제 필요; head가 둘 이상 남음; Report schema 비호환; 외부 DB·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=격리 local synthetic PostgreSQL fixture 생성·삭제와 허용 경로 commit·jaehong push만 승인한다. 기존 app_db·volume 변경, 외부 DB, 비용, secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=stamp·drop 사용; 기존 migration 수정; multi-head; empty 또는 legacy upgrade 실패; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=migration graph·두 upgrade path·schema 동등성·backend 전체 회귀·정확한 handoff와 branch CI를 제출한다.
BLOCKED_REASON=저장소와 승인된 fixture에 legacy revision 20260803_03의 실제 schema snapshot이 없어 fail-closed precondition을 증명할 수 없다. 기존 app DB·volume·stamp·drop을 사용하지 않고는 진행할 수 없으므로 이 token을 폐기하고 DataHub Context consumer REWORK를 우선 발행한다.
```

### R1 · R1-W5-F2

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F2
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=team AI tool version consistency
TASK_CARD_RANGE=R1-06 AI 개발 환경 정책 정합성 보완·동시 생성된 LLM 사용 현황 참고자료 보존
CURRENT_TASK_CARD_ID=R1-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=cf178b411d62f91b882e98d6e856bddbfa6208ad
START_POINT=origin/junhee cf178b411d62f91b882e98d6e856bddbfa6208ad에서 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W5-F2@cf178b4
ALLOWED_PATHS=AGENTS.md; docs/markdown/collaboration/AI_개발_환경_설정.md; docs/markdown/collaboration/Gate_실행_카드_원장.md; docs/markdown/ai_docs/legacy/LLM_사용_현황.md; handoffs/R1-W5-F2.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 제품 경로; 과거 일일보고; plugin source·설치 상태; root Compose·env·CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R1-W5-F2.json
ACCEPTANCE_CRITERIA=실제 사용 가능한 Ponytail Skill v4.9.0을 팀 단일 기준으로 확정하고 AGENTS.md와 AI 개발 환경 설정의 설치·최종 확인 문구를 v4.9.0 full mode로 일치시킨다. 과거 일일보고의 v4.8.4 기록은 당시 이력으로 유지한다. 현재 R2-W5-F1의 제품 허용 경로와 겹치지 않으므로 기존 token을 재발행하지 않고 최신 dev 동기화 뒤 bootstrap이 READY를 반환함을 확인한다. 같은 시각 생성된 LLM 사용 현황은 현재 코드·설정 근거를 다시 확인한 ai_docs legacy 참고 스냅샷으로만 보존하며 공식 WBS·Gate·제품 계약을 대체하지 않는다.
ACCEPTANCE_IDS=AC1_CANONICAL_VERSION;AC2_AGENTS_MATCH;AC3_SETUP_MATCH;AC4_HISTORY_PRESERVED;AC5_R2_TOKEN_CONTINUES;AC6_BOOTSTRAP;AC7_LLM_SNAPSHOT_BOUNDARY
TEST_COMMANDS=현재 Ponytail Skill 경로 v4.9.0 확인; current-policy에서 v4.8.4 부재·v4.9.0 일치 검사; LLM 스냅샷의 코드·설정 근거와 secret 부재 확인; document validation; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; python .github/scripts/gate_scope.py --dashboard --next-gate I5에서 R2-W5-F1 READY 확인; git diff --check
TEST_COMMAND_IDS=T1_INSTALLED;T2_VERSION_TEXT;T3_LLM_SNAPSHOT;T4_DOCS;T5_SCOPE;T6_R2_READY;T7_DIFF
STOP_CONDITIONS=설치되지 않은 version으로 변경; 과거 보고 이력 수정; R2 제품 경로·token 변경; plugin 설치·dependency·외부 비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=정책 문서·Gate 원장·handoff·R1 보고와 승인된 commit·push·dev 병합·seung fast-forward 동기화만 허용한다. plugin 설치·외부 비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=AGENTS와 설치 가이드 version 불일치; full 외 mode; 과거 이력 변경; R2 bootstrap 차단 지속; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=v4.9.0 단일 기준, LLM 스냅샷의 참고자료 경계, 문서·scope 검사, R2-W5-F1 READY와 branch CI를 제출한다. dev 통합 뒤 seung fast-forward·bootstrap READY는 통합 후 검증한다.
RESULT_SHA=0bd2aae2ca4687dc197f5a9f3e70c591fd24c2b1
RESULT_CI=branch 31348559427 PASS
```

### R1 · R1-W5-F3

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F3
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=R5 mockup rework authorization
TASK_CARD_RANGE=R1-06 R5 목업 기반 frontend 재작업 범위 승인
CURRENT_TASK_CARD_ID=R1-06
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=594c34da9ef14ec7db5a483446409dea69aee673
START_POINT=origin/junhee 594c34da9ef14ec7db5a483446409dea69aee673에서 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R1-W5-F3@594c34d
ALLOWED_PATHS=docs/markdown/collaboration/Gate_실행_카드_원장.md; handoffs/R1-W5-F3.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 제품 경로; backend·data·AI 제품 코드; root Compose·env·CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R1-W5-F3.json
ACCEPTANCE_CRITERIA=사용자가 제공한 목업과 현재 frontend를 대조한 읽기 전용 분석을 근거로 R5 owner-scoped 재작업 묶음을 발행한다. 기존 Analysis·Report API·route·권한·fixture 경계를 유지하고 목업의 가짜 저장·자동 채움·PDF·공유·AI 도우미는 편입하지 않는다. 실제 설치된 Ponytail v4.9.0 full mode와 1440·1024·768·360 반응형·keyboard·focus·dark/light 검증을 고정한다. R2~R4 제품 경로와 직접 충돌하지 않음을 기록한다.
ACCEPTANCE_IDS=AC1_OWNER_SCOPE;AC2_EXISTING_CONTRACTS;AC3_NO_MOCK_FEATURES;AC4_PONYTAIL_4_9;AC5_BROWSER_A11Y;AC6_PARALLEL_SAFE
TEST_COMMANDS=python .github/scripts/gate_scope.py --branch junhee --check-planned-path docs/markdown/collaboration/Gate_실행_카드_원장.md; python .github/scripts/gate_scope.py --dashboard --next-gate I5; document/report validation; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_PLANNED;T2_DASHBOARD;T3_DOCS;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=R5 소유권 밖 제품 변경; route·API·schema·fixture 의미 변경; 목업의 합성 성공값·가짜 기능 편입; dependency·외부 font/network·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=Gate 원장·handoff·R1 보고와 승인된 commit·push·dev 병합·minji fast-forward 동기화만 허용한다. 제품 코드 변경·dependency·외부 비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=R5 카드 미발행; 기존 API·route·fixture 경계 축소; Ponytail v4.9.0 full 외 mode; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R5-W5-F1의 owner path·기존 계약 보존·금지 목업 기능·browser 검증·R2~R4 병렬 안전 경계를 제출한다.
RESULT_SHA=daba10d5353c50c5313b5ecc970991d0524707ca
RESULT_CI=branch 31348830005 PASS
```

### R1 · R1-W5-F4

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F4
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=DataHub v1.7.0 pinned integration contract
TASK_CARD_RANGE=R1-02 root env·service manifest·통합 verifier의 DataHub v1.7.0 정합성
CURRENT_TASK_CARD_ID=R1-02
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=264391f1d4bdafaf6cd9529571c55dfbe71bd57a
START_POINT=origin/junhee 264391f1d4bdafaf6cd9529571c55dfbe71bd57a에서 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R1-W5-F4@264391f
CONTRACT_VERSION=R1-SERVICE-v1.1.0-DRAFT; DataHub v1.7.0; Trino 476 유지
ALLOWED_PATHS=.env.example; infrastructure/database/r1-service-fragment.v1.json; infrastructure/database/scripts/verify-service-fragment.ps1; tests/integration/test_gate_scope.py; docs/markdown/collaboration/Gate_실행_카드_원장.md; handoffs/R1-W5-F4.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=infrastructure/database/datahub/**; R2~R5 제품 경로; Trino image/version; DB DDL·seed·volume; dependency; secret
HANDOFF_MANIFEST=handoffs/R1-W5-F4.json
ACCEPTANCE_CRITERIA=공식 stable DataHub v1.7.0 release를 root DATAHUB_VERSION·service manifest·통합 verifier의 단일 pin으로 반영하고 R2 consumer compose가 동일 버전을 선언하도록 검증한다. 기존 v1.6.0에서 v1.7.0으로만 한 단계 이동하며 Trino 476과 schema·seed·recipe·volume은 변경하지 않는다. 공식 tag·release URL과 image tag를 고정하고 latest·가변 tag를 사용하지 않는다. compose config와 service fragment 검증은 image pull·container 재생성 없이 수행한다. v1.7.0 breaking change인 secret·authentication·classifier 관련 설정은 저장소 현재 설정과 대조해 별도 런타임 위험으로 기록하며 secret 값을 출력하지 않는다. Gate unit test는 실제 원장의 현재 R2 상태에 종속되지 않는 고정 bundle fixture로 executable·terminal 분기를 각각 검증한다.
ACCEPTANCE_IDS=AC1_OFFICIAL_STABLE;AC2_SINGLE_PIN;AC3_TRINO_FREEZE;AC4_NO_RUNTIME_MUTATION;AC5_BREAKING_CHANGE_AUDIT;AC6_R2_CONSUMER_CONTRACT
TEST_COMMANDS=python -m json.tool infrastructure/database/r1-service-fragment.v1.json; powershell -NoProfile -ExecutionPolicy Bypass -File infrastructure/database/scripts/verify-service-fragment.ps1; docker compose -f infrastructure/database/compose.yml -f infrastructure/database/datahub/compose.consumer.yml config; 공식 DataHub v1.7.0 tag·release·image tag 대조; python -m pytest -p no:cacheprovider tests/integration/test_gate_scope.py -q; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_JSON;T2_FRAGMENT;T3_COMPOSE_CONFIG;T4_OFFICIAL_PROVENANCE;T5_SCOPE;T6_DIFF
STOP_CONDITIONS=공식 v1.7.0 tag·image 부재; v1.6.0 우회 upgrade 필요; Trino·DDL·seed·recipe·volume 변경 필요; image pull·container 재생성·secret 변경 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=공식 release/tag 읽기, 허용 경로 수정·검증·commit·junhee push·dev 병합만 승인한다. image pull·DataHub container/volume 변경·외부 데이터 전송·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=latest tag; R1·R2 version 불일치; Trino version 변경; runtime resource 변경; secret 출력; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=공식 v1.7.0 provenance, root env·manifest·verifier와 R2 consumer pin 일치, compose config·branch CI·rollback 경계를 제출한다.
RESULT_SHA=3a3fd7ce95f3411850c8f9300b5471f71bfb17f4
RESULT_CI=dev 31350486043 PASS
```

### R2 · R2-W5-F2

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F2
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=DataHub v1.7.0 consumer configuration compatibility
TASK_CARD_RANGE=R2-11·19 DataHub consumer pin·recipe config compatibility evidence
CURRENT_TASK_CARD_ID=R2-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=264391f1d4bdafaf6cd9529571c55dfbe71bd57a
START_POINT=origin/seung을 최신 origin/dev 264391f1d4bdafaf6cd9529571c55dfbe71bd57a로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R2-W5-F2@264391f
CONTRACT_VERSION=I5-DATAHUB-v1.1.0-DRAFT; DataHub v1.7.0; Trino 476 유지
ALLOWED_PATHS=infrastructure/database/datahub/compose.consumer.yml; src/data/serving_analytics_contract.i4.v1.json; tests/data/test_serving_analytics_contract.py; handoffs/R2-W5-F2.json; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=.env.example; infrastructure/database/compose.yml; infrastructure/database/r1-service-fragment.v1.json; infrastructure/database/scripts/verify-service-fragment.ps1; recipe·DDL·seed·volume; Trino image/version; app/backend/**; dependency; secret
HANDOFF_MANIFEST=handoffs/R2-W5-F2.json
ACCEPTANCE_CRITERIA=공식 DataHub v1.7.0 tag의 quickstart compose provenance를 확인해 consumer source revision·compose blob·release URL과 upgrade·GMS·Actions·Frontend image를 정확한 v1.7.0 tag로 갱신한다. 공식 quickstart와 맞춰 Kafka image를 8.2.2로 고정하고 GMS의 local object-storage URI를 명시하되 현재 5-source와 serving recipe 내용, DataHub service names·network·health·local port, Trino 476은 유지한다. 기존 serving analytics contract에 from/to version, 공식 tag·source revision·compose blob, image digest, config-only 검증 결과, v1.7.0 breaking change 점검과 rollback v1.6.0 경계를 최소 추가한다. 실제 ingestion/search·lineage 기존 PASS는 v1.6.0 실행 증거로 보존하고 v1.7.0 runtime PASS로 바꾸지 않으며 Asset Binding·3-source hash는 후속 런타임 카드로 분리한다. image pull·container·volume 변경 없이 docker compose config와 결정론적 contract test만 수행한다.
ACCEPTANCE_IDS=AC1_OFFICIAL_PROVENANCE;AC2_PINNED_IMAGES;AC3_RECIPE_STABILITY;AC4_TRINO_FREEZE;AC5_VERSIONED_EVIDENCE;AC6_NO_FAKE_RUNTIME_PASS;AC7_ROLLBACK_BOUNDARY
TEST_COMMANDS=python -m json.tool src/data/serving_analytics_contract.i4.v1.json; python -m pytest -p no:cacheprovider tests/data/test_serving_analytics_contract.py -q; python -m pytest -p no:cacheprovider tests/data -q; docker compose -f infrastructure/database/compose.yml -f infrastructure/database/datahub/compose.consumer.yml config; 공식 v1.7.0 source revision·compose blob·image tag·digest와 Kafka 8.2.2 대조; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_JSON;T2_TARGET;T3_DATA;T4_COMPOSE_CONFIG;T5_OFFICIAL_PROVENANCE;T6_SCOPE;T7_DIFF
STOP_CONDITIONS=공식 source/image tag 불일치; recipe·DDL·seed·Trino 변경 필요; image pull·container·volume 재생성 필요; secret·외부 데이터·비용 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=공식 release/tag/원본 읽기, config-only compose 검증, 허용 경로 commit·seung push만 승인한다. image pull·container/volume 변경·실제 ingestion·외부 전송·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=latest tag; provenance 불일치; recipe/Trino drift; runtime PASS 위조; resource 변경; secret 출력; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=공식 v1.7.0 provenance와 pinned image, 기존 recipe/Trino 불변, versioned evidence·compose config·data 회귀·branch CI를 제출한다. 통합 후 Asset Binding health→live ingestion/search·Trino 3-source hash→지점별 직전 달 GOLD 객실/F&B Gold REWORK 순으로 별도 카드 발행한다.
RESULT_SHA=0342939d82ab4e2411c7d6386f5836c92154248f
RESULT_CI=branch 31350128426 python·document·scope PASS, compose expected producer-consumer mismatch; dev 31350486043 PASS
```

### R1 · R1-W5-F5

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F5
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=DataHub v1.7.0 repository runtime preflight and safe lifecycle
TASK_CARD_RANGE=R1-02 DataHub exact target inventory·secret readiness·기동/rollback 자동화
CURRENT_TASK_CARD_ID=R1-02
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=af8b11db15734bf6f047bdd709a890a3ff18a19a
START_POINT=origin/junhee를 최신 dev af8b11db15734bf6f047bdd709a890a3ff18a19a로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R1-W5-F5@af8b11d
CONTRACT_VERSION=R1-SERVICE-v1.1.0-RUNTIME-DRAFT; DataHub v1.7.0; Trino 476 frozen
ALLOWED_PATHS=infrastructure/database/scripts/upgrade-datahub-runtime.ps1; infrastructure/database/scripts/rollback-datahub-runtime.ps1; tests/integration/test_datahub_runtime_upgrade_scripts.py; docs/markdown/collaboration/Gate_실행_카드_원장.md; handoffs/R1-W5-F5.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=infrastructure/database/datahub/recipes/**; src/data/**; app/backend/**; Trino image/version; source DB·app DB container/volume; 다른 Compose project/container/volume; tracked env·secret
HANDOFF_MANIFEST=handoffs/R1-W5-F5.json
ACCEPTANCE_CRITERIA=Compose config와 label에서 project=hotel-synthetic-db의 DataHub 7개 service와 전용 volume 3개를 exact name으로 식별하고 prefix/glob·project down·down -v·prune를 사용하지 않는다. 현재 대상 DataHub runtime/volume 0개는 BACKUP_NOT_APPLICABLE_NEW_RUNTIME으로 기록하며 가짜 backup PASS를 만들지 않는다. local env의 필수 secret 5개는 값 출력 없이 존재·최소 길이만 확인하고 필요 시 암호학적 난수로 로컬 파일에만 생성한다. pinned image digest·port·RAM·다른 project snapshot을 preflight하고, RAM 부족 또는 다른 project 변경 없이는 안전하지 않으면 실제 start를 BLOCKED로 남긴다. 안전 조건 충족 시 dependency healthy→system-update exit 0→GMS/management/frontend health 순서만 허용하며 실패 시 이번 실행에서 생성한 exact DataHub service만 제거하고 volume은 기본 보존한다.
ACCEPTANCE_IDS=AC1_EXACT_TARGET;AC2_NEW_RUNTIME_BOUNDARY;AC3_SECRET_REDACTION;AC4_RESOURCE_PREFLIGHT;AC5_ORDERED_START;AC6_EXACT_ROLLBACK;AC7_OTHER_PROJECT_INVARIANCE;AC8_TRINO_FREEZE
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/integration/test_datahub_runtime_upgrade_scripts.py -q; powershell script syntax/help dry-run; docker compose config --quiet; exact label inventory; secret leak scan; python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_UNIT;T2_SCRIPT_DRY_RUN;T3_COMPOSE;T4_INVENTORY;T5_SECRET_SCAN;T6_SCOPE;T7_DIFF
STOP_CONDITIONS=host free RAM 8GB 미만; 필수 secret 생성/검증 실패; target project/label 불일치; 다른 project 변경 필요; 기존 target volume backup 검증 실패; system-update nonzero; health 실패; Trino/source DB 변경 필요; 허용 경로 밖 변경
EXTERNAL_ACTION_PERMISSION=사용자가 pinned DataHub v1.7.0 최초 기동을 승인했다. exact target DataHub image 확인·service 생성/정지/재생성·새 전용 volume 생성과 local secret 생성만 허용한다. 다른 project·기존 source/app DB·Trino·외부 전송·비용·secret 출력은 금지한다.
AUTO_FAIL_CONDITIONS=glob/project-wide down; 다른 project drift; secret 출력; runtime 조건 미충족인데 PASS; Trino drift; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=현재는 unrelated data-hub-test를 유지하면 RAM 부족이므로 offline script·secret readiness까지 진행하고 runtime start는 BLOCKED 근거를 제출한다. 메모리 확보 후에만 실제 health checkpoint를 발행한다.
RESULT_SHA=3a5f1af4c6c6c12281885586cd6c36e3a5c860b4
RESULT_CI=branch 31351161858 PASS; runtime start NOT_RUN(BLOCKED_INSUFFICIENT_MEMORY)
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

### R1 · R1-W5-F8

```text
STATUS=MERGED_DEV
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F8
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=CI supply-chain pinning and bounded execution
TASK_CARD_RANGE=R1-04 CI action SHA pin·job timeout
CURRENT_TASK_CARD_ID=R1-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=b2df6bf1ac3b05078599a0663bf9affcae1551cf
START_POINT=origin/junhee을 최신 dev b2df6bf로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R1-W5-F8@b2df6bf
CONTRACT_VERSION=CI-SUPPLY-v1.0.0-DRAFT
ALLOWED_PATHS=.github/workflows/ci.yml; tests/integration/test_ci_workflow.py; handoffs/R1-W5-F8.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 제품 경로; workflow trigger·permissions·branch scope·test target 의미 변경; dependency; secret
HANDOFF_MANIFEST=handoffs/R1-W5-F8.json
ACCEPTANCE_CRITERIA=actions/checkout v4.4.0=11d5960a326750d5838078e36cf38b85af677262, actions/setup-python v6.3.0=ece7cb06caefa5fff74198d8649806c4678c61a1, actions/setup-node v4.4.0=49933ea5288caeca8642d1e84afbd3f7d6820020의 공식 tag commit SHA로 모든 uses를 고정하고 exact version comment를 유지한다. 모든 6개 job에 timeout-minutes를 설정하며 기존 최소 permissions·concurrency·branch별 test routing·quality gate 의미를 바꾸지 않는다. 회귀 test는 mutable actions/* tag와 timeout 누락을 차단한다. 현재 dev의 알려진 R3 METRIC_FILTER_MISSING 실패는 이 카드 범위 밖 baseline으로 기록하고 R1 제품 코드로 우회하지 않는다.
ACCEPTANCE_IDS=AC1_ACTION_SHA_PIN;AC2_VERSION_COMMENT;AC3_ALL_JOB_TIMEOUT;AC4_EXISTING_SEMANTICS;AC5_REGRESSION;AC6_BASELINE_BOUNDARY
TEST_COMMANDS=git ls-remote official action tags; python -m pytest -p no:cacheprovider tests/integration/test_ci_workflow.py tests/integration/test_gate_scope.py -q; python -m pytest -p no:cacheprovider tests/integration -q; workflow syntax review; gate_scope merge-base; git diff --check; junhee branch CI
TEST_COMMAND_IDS=T1_UPSTREAM;T2_TARGET;T3_INTEGRATION;T4_WORKFLOW;T5_SCOPE;T6_DIFF;T7_BRANCH_CI
STOP_CONDITIONS=공식 tag SHA 불일치; workflow 기능·permission·trigger 변경 필요; dependency·secret·외부 write 필요; 허용 경로 밖 변경; R1 integration 검증 실패
EXTERNAL_ACTION_PERMISSION=공식 GitHub action tag의 read-only 확인과 허용 경로 commit·junhee push만 승인한다. 외부 workflow 수동 실행·secret 변경·비용은 금지한다.
AUTO_FAIL_CONDITIONS=mutable actions tag 잔존; job timeout 누락; 기존 branch/test routing 변경; R3 baseline을 R1에서 우회; scope 위반; R1 필수 검증 FAIL
R1_REVIEW_CONDITIONS=immutable SHA·version comment·6 job timeout과 integration 회귀, 정확한 handoff·branch CI를 제출한다. dev 전체 green 판정은 R2→R4→R3 계약 통합 뒤 별도로 수행한다.
RESULT_SHA=aed36f38198019b7553631deeb2110cf99d13fd4
RESULT_CI=branch 31353517478 PASS
```

### R1 · R1-W5-F9

```text
STATUS=BLOCKED
ROLE_ID=R1
ASSIGNEE=박준희
PERSONAL_BRANCH=junhee
EXECUTION_BUNDLE_ID=R1-W5-F9
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=typed Node2→G2→binder and representative 3-source product API
TASK_CARD_RANGE=R1-08·09 typed 조합 회귀·G120-046 제품 API E2E
CURRENT_TASK_CARD_ID=R1-08
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=107e7cfbe7e13c0b8751ca91cc3a686d5bd59cf1
START_POINT=origin/junhee을 최신 dev 107e7cf로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R1-W5-F9@107e7cf
CONTRACT_VERSION=I4-CONTEXT-v2.3.0-DRAFT; I5-3SOURCE-CONTEXT-v1.0.0-DRAFT; MODEL typed extension
ALLOWED_PATHS=tests/integration/test_typed_three_source_e2e.py; handoffs/R1-W5-F9.json; docs/markdown/daily_reports/junhee/일일보고.md
FORBIDDEN_PATHS=R2~R5 product code·fixture·dataset; DataHub runtime; RunPod·model endpoint; root Compose/env/CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R1-W5-F9.json
ACCEPTANCE_CRITERIA=하나의 integration test에서 R2의 approved G120-046 Context를 입력해 R3 Node2 typed plan→R4 G2 exact parameter map→단일 I2 binder를 통과한다. 같은 질문을 실제 제품 Analysis API 경로로 실행해 Business Request·승인 PMS/CRM/POS Context·Node2 SQL·G2·local Trino 476·G3·표/차트/설명/근거와 request_id trace를 확인하고 Gold 2행·총액 475972400.00·canonical hash를 비교한다. fixture 존재만으로 성공 처리하지 않고 권한 없음·승인 밖 JOIN·필수 filter 누락·repair 1회 경계를 함께 검증한다.
ACCEPTANCE_IDS=AC1_COMBINED_PATH;AC2_ACTUAL_API;AC3_THREE_SOURCE_TRINO;AC4_G3_ARTIFACT;AC5_SINGLE_REQUEST_TRACE;AC6_GOLD_MATCH;AC7_NEGATIVE_AUTH_JOIN_FILTER;AC8_REPAIR_ONCE
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/integration/test_typed_three_source_e2e.py -q; python -m pytest -p no:cacheprovider tests -q; actual local API+Trino trace; gate_scope merge-base; git diff --check; junhee branch CI
TEST_COMMAND_IDS=T1_TARGET;T2_ALL;T3_RUNTIME;T4_SCOPE;T5_DIFF;T6_BRANCH_CI
STOP_CONDITIONS=제품 code 변경 필요; DataHub runtime 필요; actual Trino/API unavailable; Gold mismatch; request_id trace 단절; 권한/JOIN/filter negative 실패; RunPod·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local synthetic app DB·backend·Trino 476의 조회 전용 E2E용 임시 process 생성·정리와 허용 경로 commit·junhee push만 승인한다. DDL·seed·volume reset·다른 Docker project·DataHub lifecycle·외부 비용·secret 변경은 금지한다.
R1_REVIEW_CONDITIONS=조합 회귀와 실제 제품 API E2E가 모두 PASS한 뒤에만 compiled dataset 재생성과 Analysis persistence·SQLGlot G2/G3·Report worker 단계로 진행한다.
BLOCKED_REASON=Trino Gold 자체는 2행·475972400.00·canonical hash가 일치했지만 제품 경로는 live Asset Binding BLOCKED/NOT_RUN, Node2의 단일 asset/PMS-CRM plan, METRIC_FILTER_MISSING repair 미지원, G2의 safe CTE 차단, chart 미조립 때문에 성공 trace를 만들지 못했다. fake/fixture-only 성공을 금지하고 R3·R4 owner REWORK 뒤 새 token으로 재발행한다.
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

### R3 · R3-W5-F5

```text
STATUS=BLOCKED
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F5
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=G120-046 multi-source Node2 plan and one repair
TASK_CARD_RANGE=R3-04·05 derived metric·approved 3-source JOIN typed SQL
CURRENT_TASK_CARD_ID=R3-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=32e7a4de6e4a3a817a5a2b9dd9b9f9014db4e7c4
START_POINT=origin/daesung을 최신 dev 32e7a4d로 fast-forward한 뒤 시작한다. stash@{0}은 계속 보존하고 적용하지 않는다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R3-W5-F5@32e7a4d
ALLOWED_PATHS=src/ai/node2.py; tests/ai/test_node2.py; tests/ai/test_training_verification.py; handoffs/R3-W5-F5.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=src/data/**; app/backend/**; prompt/model serving; dataset·RunPod·외부 endpoint; dependency; secret
HANDOFF_MANIFEST=handoffs/R3-W5-F5.json
ACCEPTANCE_CRITERIA=Node2는 특정 case ID나 정답 SQL을 hardcode하지 않고 Context의 derived metric·6 asset·approved join=pms_crm_pos_gold_revenue_month_v1·typed binding을 사용해 PMS·CRM·POS source별 선집계 CTE와 property_id+month grain의 parameterized SELECT를 생성한다. period_end_exclusive와 모든 required_filter를 보존하고 G2가 승인한 join/column만 참조한다. METRIC_FILTER_MISSING을 같은 Context에서 정확히 1회 repair 가능한 normalized code로 처리하며 임의 JOIN·literal·raw-row 증폭은 차단한다.
TEST_COMMANDS=target Node2/G2 composition tests; AI 전체; compileall; gate_scope; git diff --check; daesung branch CI
STOP_CONDITIONS=R2/R4 product file 변경 필요; case/Gold SQL hardcode; raw-row join; dataset·RunPod·비용·secret 필요; scope/필수 검증 실패
R1_REVIEW_CONDITIONS=multi-source plan의 SQL 구조·typed parameters·approved join·repair 1회와 AI 전체·source CI를 제출한다.
BLOCKED_REASON=R3 제품 commit 626164b의 단위 회귀는 통과했으나 R4-W5-F6 Context가 5-edge topology를 전달하지 않아 실제 조합이 ContractError로 중단되고, 보정 뒤에도 G2가 두 번째 POS CTE filter를 검사하지 못해 METRIC_FILTER_MISSING이 발생한다. R4 owner REWORK 통합 뒤 최신 dev에서 조합을 재검증하기 전 handoff·push·병합을 금지한다.
```

### R3 · R3-W5-F6

```text
STATUS=READY
ROLE_ID=R3
ASSIGNEE=윤대성
PERSONAL_BRANCH=daesung
EXECUTION_BUNDLE_ID=R3-W5-F6
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=actual Node2→R4 multi-CTE G2→single binder composition
TASK_CARD_RANGE=R3-04·05 G120-046 조합 회귀·handoff 교정
CURRENT_TASK_CARD_ID=R3-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=dcbc6165f30b2899630cd2db01a44d90b72f3623
START_POINT=보존한 R3 제품 commit 626164b를 최신 dev dcbc616 위에 안전하게 재적용하고 stash@{0}은 계속 건드리지 않는다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R3-W5-F6@dcbc616
ALLOWED_PATHS=src/ai/node2.py; tests/ai/test_node2.py; tests/ai/test_training_verification.py; handoffs/R3-W5-F5.json; handoffs/R3-W5-F6.json; docs/markdown/daily_reports/daesung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/data/**; dataset·prompt/model serving; RunPod·외부 endpoint; dependency; secret
HANDOFF_MANIFEST=handoffs/R3-W5-F6.json
ACCEPTANCE_CRITERIA=최신 dev의 R4-W5-F7 Context가 전달하는 6 asset·5-edge topology와 R2 typed binding을 R3 Node2가 소비해 두 source preaggregate CTE SQL을 생성하고, 실제 R4 PipelineSupport G2와 I2DataPlatformAdapter single binder를 순서대로 통과한다. POS CTE filter 하나를 제거하면 METRIC_FILTER_MISSING, 승인 밖 JOIN·literal·OR·unknown/duplicate/value mutation은 fail-closed이며 METRIC_FILTER_MISSING repair는 정확히 1회만 허용한다. F5 handoff의 BLOCKED를 조합 결과로 대체하되 compiled dataset·RunPod는 계속 변경하지 않는다.
ACCEPTANCE_IDS=AC1_LATEST_DEV_CONTEXT;AC2_ACTUAL_NODE2_G2_BINDER;AC3_MULTI_CTE_NEGATIVE;AC4_ONE_REPAIR;AC5_HANDOFF_SUPERSEDE;AC6_NO_DATASET_RUNPOD
TEST_COMMANDS=actual R3 Node2→R4 G2→I2 binder composition target; Node2 target; AI 전체; compileall; gate_scope merge-base; git diff --check; daesung branch CI
TEST_COMMAND_IDS=T1_COMPOSITION;T2_NODE2;T3_AI;T4_COMPILE;T5_SCOPE;T6_DIFF;T7_BRANCH_CI
STOP_CONDITIONS=backend/data 변경 필요; actual composition 실패; case/Gold SQL hardcode; raw-row join; second repair; dataset·RunPod·비용·secret; scope/필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local deterministic 조합 test와 허용 경로 commit·daesung push만 허용한다. Docker/DataHub/Trino lifecycle·외부 비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=probe SQL만 검증; 실제 Node2 plan 미검증; multi-CTE filter 누락 허용; second repair; stash 변경; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R3 source CI PASS 뒤 dev에 통합하고 새 R1 actual API E2E 카드로 local Trino Gold·G3 table/chart/evidence/artifact/request trace를 검증한다.
```

### R2 · R2-W5-F3

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F3
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=DataHub v1.7 ingestion/search/schema/lineage evidence
TASK_CARD_RANGE=R2-11·19 runtime validator·Asset Binding health evidence
CURRENT_TASK_CARD_ID=R2-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=af8b11db15734bf6f047bdd709a890a3ff18a19a
START_POINT=origin/seung을 최신 dev af8b11db15734bf6f047bdd709a890a3ff18a19a로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R2-W5-F3@af8b11d
CONTRACT_VERSION=I5-DATAHUB-v1.1.0-RUNTIME-DRAFT; ASSET-BINDING-v1.0.0-DRAFT
ALLOWED_PATHS=infrastructure/database/datahub/scripts/run-runtime-validation.ps1; src/data/datahub_runtime_evidence.i5.v1.json; src/data/asset_binding_health.i5.v1.json; src/data/serving_analytics_contract.i4.v1.json; tests/data/test_datahub_runtime_evidence.py; tests/data/test_asset_binding_health.py; tests/data/test_serving_analytics_contract.py; handoffs/R2-W5-F3.json; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=root Compose/env/lifecycle scripts; recipe 내용; DDL·seed; Trino image/version; app/backend/**; src/ai/**; container/volume lifecycle; secret
HANDOFF_MANIFEST=handoffs/R2-W5-F3.json
ACCEPTANCE_CRITERIA=R1_RUNTIME_HEALTHY checkpoint 전에는 redacting validator와 versioned evidence schema·offline tests만 구현하고 실제 ingestion을 실행하지 않는다. runtime 가능 시 5-source recipe 뒤 serving.i4를 실행해 exit 0을 확인하고 GMS에서 승인된 serving.analytics 8개 View의 exact URN·FQN·column·dataset/fine-grained lineage를 조회한다. Asset Binding은 binding_id·urn·fqn·status·version·verified_at과 provenance를 포함하고 유일성·UTC timestamp·DataHub exact search·Trino metadata 존재를 검증한다. v1.6 live PASS는 보존하고 v1.7 결과는 실제 trace가 있을 때만 PASS로 전환하며 raw secret·token·resolved recipe를 기록하지 않는다.
ACCEPTANCE_IDS=AC1_OFFLINE_VALIDATOR;AC2_R1_HEALTH_GATE;AC3_FIVE_SOURCE_INGESTION;AC4_VIEW_SEARCH_SCHEMA;AC5_LINEAGE;AC6_ASSET_BINDING_HEALTH;AC7_NO_FAKE_PASS;AC8_SECRET_REDACTION
TEST_COMMANDS=python -m json.tool evidence JSON; python -m pytest -p no:cacheprovider tests/data/test_datahub_runtime_evidence.py tests/data/test_asset_binding_health.py tests/data/test_serving_analytics_contract.py -q; python -m pytest -p no:cacheprovider tests/data -q; PowerShell validator dry-run; secret leak scan; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_JSON;T2_TARGET;T3_DATA;T4_DRY_RUN;T5_SECRET_SCAN;T6_SCOPE;T7_DIFF
STOP_CONDITIONS=R1 runtime health 없음; recipe 변경 필요; 승인 밖 URN/FQN; DataHub/Trino 결과 불일치; container/volume lifecycle 필요; secret·외부 데이터·비용 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=offline validator·contract·test 구현과 R1 health 뒤 local synthetic ingestion/search/read-only Trino metadata 조회만 허용한다. runtime lifecycle·다른 project·외부 전송·비용·secret 출력은 금지한다.
AUTO_FAIL_CONDITIONS=R1 checkpoint 전 ingestion; v1.7 fake PASS; binding 불일치; lineage 없음; secret 노출; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=현재 RAM blocker 동안 offline validator·Asset Binding schema/test를 완료하고 runtime evidence는 BLOCKED로 제출한다. R1 health 뒤 실제 trace만 후속 증거 commit으로 허용한다.
RESULT_SHA=49a34ccba8cd4d05a71a9d6564c150f44d1aaee8
RESULT_CI=branch 31351264193 PASS; runtime evidence BLOCKED/NOT_RUN
```

### R2 · R2-W5-F4

```text
STATUS=MERGED_DEV
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F4
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=typed metric registry and approved PMS·CRM·POS Context producer
TASK_CARD_RANGE=R2-15 typed required-filter 계약·대표 3-source Context fixture·deterministic Gold SQL
CURRENT_TASK_CARD_ID=R2-15
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=cea8ad9b456950bffd649b9a0fb8d9b135ee58ad
START_POINT=origin/seung을 최신 dev cea8ad9로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R2-W5-F4@cea8ad9
CONTRACT_VERSION=I4-CONTEXT-v2.3.0-DRAFT; I5-3SOURCE-CONTEXT-v1.0.0-DRAFT
ALLOWED_PATHS=src/data/analytics_context_contract.i4.v2.json; tests/data/test_analytics_context_contract.py; infrastructure/database/sql/queries/i5_gold_pms_crm_pos_context.sql; src/data/pms_crm_pos_context.i5.v1.json; tests/data/test_pms_crm_pos_context.py; handoffs/R2-W5-F4.json; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=app/backend/**; src/ai/**; frontend/**; DataHub recipe·runtime evidence; DDL·seed·Compose·env·CI; Trino image/version; secret
HANDOFF_MANIFEST=handoffs/R2-W5-F4.json
ACCEPTANCE_CRITERIA=required_filter를 field·operator·value_type·value로 정의하고 value_type은 string·boolean·number·date만 허용한다. date는 ISO YYYY-MM-DD, number는 bool을 제외한 유한 수이며 parameter 이름은 period_start·period_end_exclusive·required_filter_N 순서로 고정한다. 승인된 G120-046 질문과 join=pms_crm_pos_gold_revenue_month_v1을 재사용해 PMS·CRM·POS asset·column·filter·property_id+month grain을 명시한 versioned Context fixture를 만든다. SYNTHETIC_HOTEL_001과 2026-05~06을 고정하고 source별 선집계 뒤 결합한 single read-only Trino SQL의 row count·합계·canonical hash·SQL hash를 실제 실행으로 기록한다. 기존 I3 fixture·평가 manifest·DataHub runtime 상태는 변경하지 않는다.
ACCEPTANCE_IDS=AC1_TYPED_FILTER;AC2_PARAMETER_NAMES;AC3_APPROVED_SCENARIO;AC4_THREE_SOURCE_CONTEXT;AC5_PREAGG_JOIN;AC6_TRINO_HASH;AC7_EXISTING_IMMUTABLE;AC8_NO_FAKE_RUNTIME
TEST_COMMANDS=python -m json.tool src/data/analytics_context_contract.i4.v2.json; python -m json.tool src/data/pms_crm_pos_context.i5.v1.json; python -m pytest -p no:cacheprovider tests/data/test_analytics_context_contract.py tests/data/test_pms_crm_pos_context.py -q; python -m pytest -p no:cacheprovider tests/data -q; local Trino read-only SQL 실행과 hash 검증; python .github/scripts/gate_scope.py --branch seung --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_JSON;T2_TARGET;T3_DATA;T4_TRINO;T5_SCOPE;T6_DIFF
STOP_CONDITIONS=승인 질문·JOIN·source 의미 변경 필요; R4/R3 경로 변경 필요; raw-row source 결합·증폭; DDL·seed·recipe 변경; PMS·CRM·POS·Trino unhealthy; 기존 결과와 설명 없는 불일치; DataHub runtime PASS 필요; 비용·secret·외부 전송; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local synthetic PMS·CRM·POS와 Trino 476의 read-only 조회, 허용 경로 commit·seung push만 승인한다. DataHub lifecycle·DDL·seed·외부 서비스·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=type 미검증; period_end 사용; dynamic date; raw-row join; 승인 밖 asset/column; hash 위조; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=typed registry와 대표 3-source producer를 같은 R2 카드 안에서 순서대로 완료하고 실제 Trino 결과·target/data 회귀·handoff·branch CI를 제출한다.
RESULT_SHA=1eec81b7f46545e7d1e6d448cc8b1a567435ce7d
RESULT_CI=branch 31353517252 PASS
```

### R2 · R2-W5-F6

```text
STATUS=READY
ROLE_ID=R2
ASSIGNEE=정승
PERSONAL_BRANCH=seung
EXECUTION_BUNDLE_ID=R2-W5-F6
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=versioned Semantic Catalog producer and isolated runtime evidence
TASK_CARD_RANGE=R2-11·19 serving View description catalog·DataHub publish/verify·CRM seed protection
CURRENT_TASK_CARD_ID=R2-11
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=593b68a46c7800c1993be0656bea0c9bf58b57d6
START_POINT=origin/seung을 최신 dev 593b68a로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R2-W5-F6@593b68a
CONTRACT_VERSION=I5-SEMANTIC-CATALOG-v1.0.0-DRAFT; I5-DATAHUB-v1.1.0-RUNTIME-DRAFT
ALLOWED_PATHS=infrastructure/database/sql/ddl/03_hotel_crm_sqlserver.sql; infrastructure/database/datahub/compose.consumer.yml; infrastructure/database/trino/etc/access-control-rules.json; src/data/serving_semantic_catalog.i4.v1.json; infrastructure/database/datahub/publish_semantic_catalog.py; infrastructure/database/datahub/verify_semantic_catalog.py; src/data/serving_analytics_contract.i4.v1.json; tests/data/test_serving_semantic_catalog.py; handoffs/R2-W5-F6.json; docs/markdown/daily_reports/seung/일일보고.md
FORBIDDEN_PATHS=infrastructure/database/compose.yml; seed/data SQL; backend·AI·frontend; root env/CI; DataHub volume reset; 다른 Docker project; secret
HANDOFF_MANIFEST=handoffs/R2-W5-F6.json
ACCEPTANCE_CRITERIA=현재 동결된 serving analytics 8 View·116 field occurrence·70 unique field의 FQN·column 목록을 재사용해 description만 versioned enrichment한 단일 Semantic Catalog를 만든다. publisher는 재실행 가능하고 verifier는 ingestion 뒤 Dataset description 8/8·Column description 116/116 및 catalog version/hash를 exact 검증한다. Kafka healthcheck는 현재 image에 실제 존재하는 kafka-topics 명령을 사용하고 datahub_ingestion 계정에는 system.metadata.catalogs·table_comments SELECT만 최소 허용한다. CRM의 기존 active-only filtered unique index 5개와 grade/customer_map history overlap trigger는 보존하며 trigger 내부 fast path가 filtered unique 보호 범위에만 적용됨을 duplicate·adjacent·overlap 회귀와 fresh synthetic 80000 seed 증거로 확인한다. 격리 문서의 과거 183 passed 수치를 현재 PASS로 복사하지 않고 이번 실행 증거만 기록한다.
ACCEPTANCE_IDS=AC1_CATALOG_CARDINALITY;AC2_DESCRIPTION_VERSION_HASH;AC3_IDEMPOTENT_PUBLISH;AC4_EXACT_VERIFY;AC5_KAFKA_HEALTH;AC6_MINIMUM_METADATA_GRANT;AC7_CRM_PROTECTION;AC8_CURRENT_EVIDENCE_ONLY
TEST_COMMANDS=python -m json.tool src/data/serving_semantic_catalog.i4.v1.json; python -m pytest -p no:cacheprovider tests/data/test_serving_semantic_catalog.py -q; python -m pytest -p no:cacheprovider tests/data -q; docker compose config; fresh isolated synthetic CRM duplicate·adjacent·overlap·80000 seed 검증; isolated DataHub ingestion→publisher 2회→verifier 8/116; gate_scope merge-base; git diff --check; seung branch CI
TEST_COMMAND_IDS=T1_JSON;T2_TARGET;T3_DATA;T4_COMPOSE;T5_CRM;T6_DATAHUB;T7_SCOPE;T8_DIFF;T9_BRANCH_CI
STOP_CONDITIONS=기존 index·trigger 의미 약화; seed 파일 변경 필요; 8/116/70 불일치; publisher 비멱등; ingestion warning/health 실패; broad system grant; root compose 복사; 다른 project·volume reset·secret·비용; scope/필수 검증 실패
EXTERNAL_ACTION_PERMISSION=정확히 격리된 synthetic CRM 무볼륨 container의 단계별 DDL→fresh 80000 seed→trigger 검증을 최대 20분까지 background·short poll로 실행하고 exact container만 정리할 수 있다. 격리 DataHub 신규 기동은 host free RAM 8GB 이상일 때만 허용한다. 기존 hotel-synthetic-db·data-hub-test·다른 project/volume, root env, 외부 전송·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=과거 격리 수치를 현재 PASS로 승격; catalog cardinality/hash 불일치; broad grant; 기존 history 보호 약화; 다른 project drift; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=Option 1 요청은 부분 수용한다. 이 R2 생산자를 먼저 dev에 통합·동결한 뒤 R4 Dataset/Column description Context 소비자와 R3 training catalog 소비자를 별도 owner 카드로 발행하고, 마지막에 R1 fresh integration을 수행한다.
```

### R4 · R4-W5-F2

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F2
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=approved analytics View Context consumer
TASK_CARD_RANGE=R4-04·05 DataHub Context adapter·entitlement·G2 contract
CURRENT_TASK_CARD_ID=R4-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=af8b11db15734bf6f047bdd709a890a3ff18a19a
START_POINT=origin/jaehong을 최신 dev af8b11db15734bf6f047bdd709a890a3ff18a19a로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F2@af8b11d
CONTRACT_VERSION=I4-CONTEXT-v2.2.0-DRAFT; ASSET-BINDING-v1.0.0-DRAFT; OPENAPI-v1.1.0-DRAFT
ALLOWED_PATHS=app/backend/app/adapters/i2_data_platform.py; app/backend/app/services/context_builder.py; app/backend/app/services/execution_control.py; app/backend/app/services/pipeline_support.py; tests/backend/test_i2_data_platform.py; tests/backend/test_context_builder.py; tests/backend/test_execution_control.py; tests/backend/test_analysis_pipeline.py; handoffs/R4-W5-F2.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/data/**; src/ai/**; route/OpenAPI schema; migration; frontend; root Compose/env; dependency; secret
HANDOFF_MANIFEST=handoffs/R4-W5-F2.json
ACCEPTANCE_CRITERIA=live DataHub health가 없을 때는 승인된 versioned analytics Context binding만 소비하고 PMS·CRM 원천 5개 고정 반환을 실제 제품 성공처럼 표시하지 않는다. entitlement 후 허용된 serving.analytics View URN/FQN만 Context Package에 포함하며 권한 없는 View·binding status 비정상·version 불일치는 제외한다. G2는 Context 내부 FQN과 parameterized required filter만 허용하고 외부 FQN·raw identifier를 차단한다. R2 runtime evidence가 아직 없으면 live mode는 fail-closed하고 versioned mode contract test만 PASS로 기록한다.
ACCEPTANCE_IDS=AC1_VERSIONED_BINDING;AC2_NO_HARDCODE_SUCCESS;AC3_ENTITLEMENT;AC4_VIEW_CONTEXT;AC5_G2_ALLOW;AC6_G2_BLOCK;AC7_LIVE_FAIL_CLOSED;AC8_EXISTING_COMPAT
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend/test_i2_data_platform.py tests/backend/test_context_builder.py tests/backend/test_execution_control.py -q; python -m pytest -p no:cacheprovider tests/backend -q; python -m compileall -q app/backend; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_TARGET;T2_BACKEND;T3_COMPILE;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=R2 contract/schema 변경 필요; live 결과 위조; entitlement 근거 없음; route/OpenAPI/migration 변경 필요; arbitrary FQN 허용; 외부 서비스·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local versioned Context adapter·backend tests와 허용 경로 commit·jaehong push만 승인한다. DataHub lifecycle·외부 endpoint·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=hardcoded source만 성공 반환; 권한 없는 View 포함; 외부 FQN 허용; live fake PASS; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=versioned binding 기반 analytics View Context와 entitlement·G2 allow/block·live fail-closed·backend 회귀·정확한 handoff와 branch CI를 제출한다.
RESULT_SHA=65ef3d0b5d6419f654a5f1f167d7bfd45c9a4fa1
RESULT_CI=branch 31351378232 PASS
```

### R4 · R4-W5-F3

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F3
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=R2 Asset Binding producer-consumer status consistency
TASK_CARD_RANGE=R4-04 Asset Binding health 소비자 fail-closed REWORK
CURRENT_TASK_CARD_ID=R4-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=459fa3c
START_POINT=origin/jaehong을 최신 dev 459fa3c로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F3@459fa3c
CONTRACT_VERSION=I4-CONTEXT-v2.2.0-DRAFT; ASSET-BINDING-v1.0.0-DRAFT
ALLOWED_PATHS=app/backend/app/adapters/i2_data_platform.py; tests/backend/test_i2_data_platform.py; tests/backend/test_context_builder.py; handoffs/R4-W5-F3.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/data/**; migration·entrypoint·OpenAPI·route; frontend; root Compose/env; dependency; secret
HANDOFF_MANIFEST=handoffs/R4-W5-F3.json
ACCEPTANCE_CRITERIA=R2의 src/data/asset_binding_health.i5.v1.json을 읽기 전용 생산자 계약으로 소비해 binding_id·URN·FQN·version·status를 Context 후보와 교차 검증한다. PENDING_RUNTIME_VERIFICATION·verified_at null·provenance NOT_RUN인 binding을 VERIFIED로 재작성하거나 Context 성공에 포함하지 않으며, 현재 runtime BLOCKED에서는 versioned/live 모두 fail-closed한다. URN/FQN/version 불일치·누락·중복은 차단하고 실제 R2 runtime evidence가 PASS로 전환된 경우에만 기존 entitlement·G2 경계를 유지한 채 승인 binding을 노출한다.
ACCEPTANCE_IDS=AC1_R2_CONTRACT_CONSUME;AC2_NO_PENDING_AS_VERIFIED;AC3_VERSION_MATCH;AC4_FAIL_CLOSED;AC5_ENTITLEMENT_G2_REGRESSION
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend/test_i2_data_platform.py tests/backend/test_context_builder.py -q; python -m pytest -p no:cacheprovider tests/backend -q; python -m compileall -q app/backend; python .github/scripts/gate_scope.py --branch jaehong --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_TARGET;T2_BACKEND;T3_COMPILE;T4_SCOPE;T5_DIFF
STOP_CONDITIONS=R2 contract 변경 필요; PENDING을 성공으로 노출; runtime PASS 위조; migration·OpenAPI·route 변경 필요; 외부 서비스·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local contract consumer·backend test·handoff·R4 보고와 승인된 commit·jaehong push만 허용한다. DataHub lifecycle·외부 endpoint·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=PENDING binding을 VERIFIED로 표시; R2 contract 불일치 무시; entitlement/G2 회귀; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R2 binding 상태를 그대로 존중하는 fail-closed consumer와 target/backend 회귀·정확한 handoff·branch CI를 제출한다.
RESULT_SHA=0f881a7d8f7b034000dc2d2617bade4fa290c7d8
RESULT_CI=branch 31352114861 PASS
```

### R4 · R4-W5-F4

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F4
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=official Alembic support boundary and unknown revision fail-closed evidence
TASK_CARD_RANGE=R4-03 공식 Alembic 지원 경로·unknown revision 검증
CURRENT_TASK_CARD_ID=R4-03
BASE_BRANCH=dev
BASE_SHA=b8331bc
START_POINT=origin/jaehong을 최신 dev b8331bc로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F4@b8331bc
ALLOWED_PATHS=app/backend/README.md; tests/backend/test_migration_compatibility.py; handoffs/R4-W5-F4.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=기존 migration·entrypoint·env·schema·data; stamp·drop; 외부 DB·secret
ACCEPTANCE_CRITERIA=현행 migration graph의 single root·single head와 공식 known revision 목록을 검증하고 격리 empty DB 및 20260731_03에서 stamp 없이 head upgrade가 성공해야 한다. 존재하지 않는 20260803_03은 native Alembic non-zero로 backend 기동 전에 차단되고 운영 판정 LEGACY_REVISION_UNSUPPORTED로 기록한다. README는 지원 범위를 공식 migration revision으로 한정하며 추정 migration·자동 stamp·drop·기존 schema/data 변경을 금지한다.
TEST_COMMANDS=migration compatibility target test; backend 전체 test; alembic heads; 격리 empty/known/unknown revision 검증; compileall; gate_scope; git diff --check
STOP_CONDITIONS=R4-W5-F3 미통합; 실제 legacy DB 보존 필요; migration·entrypoint·schema·data 변경 필요; stamp/drop; multi-head; 외부 DB·비용·secret·scope 밖 변경
R1_REVIEW_CONDITIONS=Google Docs의 R4→R1 재발행 요청을 부분 수용했다. 기존 F2 번호는 Context/G2에 사용됐으므로 F4로 재번호화했고, 제품 변경 없이 native Alembic 지원·차단 경계의 결정론적 증거만 제출한다.
RESULT_SHA=3977f3554de8f3ef82334c976a3bfb360fbc37b0
RESULT_CI=branch 31352566492 PASS
```

### R4 · R4-W5-F5

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F5
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=R2-W5-F4 typed registry·3-source Context producer merged dev
TASK_CARD_RANGE=R4-04·05 typed Context·G2 parameter map·single Trino binder
CURRENT_TASK_CARD_ID=R4-04
BASE_BRANCH=dev
BASE_SHA=b35f2d86d2089f461aff6de316d062ce1cc40bfd
START_POINT=origin/jaehong을 최신 dev b35f2d8로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F5@b35f2d8
ALLOWED_PATHS=app/backend/app/adapters/contract_model.py; app/backend/app/adapters/i2_data_platform.py; app/backend/app/services/context_builder.py; app/backend/app/services/pipeline_support.py; tests/backend/test_context_builder.py; tests/backend/test_i2_data_platform.py; tests/backend/test_production_model.py; tests/backend/test_analysis_pipeline.py; handoffs/R4-W5-F5.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/data/**; src/ai/**; migration·OpenAPI·route; frontend; root Compose/env/CI; dependency; secret
ACCEPTANCE_CRITERIA=R2의 string·boolean·number·date required_filter와 period_start·period_end_exclusive를 Context model이 손실 없이 보존한다. G2는 SQL placeholder와 parameter map을 Context의 name·type·value와 함께 검증하고 누락·unknown·중복·literal·OR·값 변조를 fail-closed한다. 단일 Trino binder는 string escaping, boolean, bool 제외 finite number, ISO date만 안전하게 bind하고 실행 직전까지 parameterized SQL을 유지한다. 승인된 PMS·CRM·POS Context의 FQN·column·JOIN만 허용하며 기존 entitlement·1회 repair 경계를 유지한다.
ACCEPTANCE_IDS=AC1_TYPED_CONTEXT;AC2_PERIOD_EXCLUSIVE;AC3_G2_PAIR_VALIDATION;AC4_SINGLE_BINDER;AC5_TYPE_ALLOWLIST;AC6_THREE_SOURCE_POLICY;AC7_FAIL_CLOSED;AC8_REGRESSION
TEST_COMMANDS=target backend typed Context/G2/binder tests; backend 전체 test; compileall; gate_scope merge-base; git diff --check
STOP_CONDITIONS=R2 producer 미통합; AST dependency·migration·OpenAPI 변경 필요; R3/data 경로 변경; arbitrary literal/type coercion 필요; 외부 서비스·비용·secret 필요; 허용 경로 밖 변경; 필수 검증 실패
R1_REVIEW_CONDITIONS=R2 producer 통합 뒤 최신 BASE_SHA·token으로 READY 전환하며 SQLGlot AST와 G3·Analysis persistence는 후속 카드로 분리한다.
RESULT_SHA=2a2ed9feb97723a7ac495fe87b2c59d142cacc13
RESULT_CI=branch 31354450601 PASS
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

### R4 · R4-W5-F6

```text
STATUS=BLOCKED
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F6
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=versioned 3-source product Context·safe CTE·chart trace
TASK_CARD_RANGE=R4-04·05·06·09 G120-046 Context/G2/G3 response REWORK
CURRENT_TASK_CARD_ID=R4-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=32e7a4de6e4a3a817a5a2b9dd9b9f9014db4e7c4
START_POINT=origin/jaehong을 최신 dev 32e7a4d로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F6@32e7a4d
ALLOWED_PATHS=app/backend/app/adapters/contract_model.py; app/backend/app/adapters/i2_data_platform.py; app/backend/app/services/pipeline_support.py; app/backend/app/services/analysis_service.py; app/backend/app/contracts.py; tests/backend/test_i2_data_platform.py; tests/backend/test_analysis_pipeline.py; tests/backend/test_control_plane_contract.py; handoffs/R4-W5-F6.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/data/**; src/ai/**; migration·OpenAPI route; frontend; root Compose/env/CI; SQLGlot dependency; secret
HANDOFF_MANIFEST=handoffs/R4-W5-F6.json
ACCEPTANCE_CRITERIA=대표 E2E의 versioned-trino mode에서 R2가 실제 Trino 검증한 I5-3SOURCE-CONTEXT-v1.0.0-DRAFT를 승인 binding으로 소비하되 live mode의 PENDING Binding은 계속 fail-closed한다. hardcoded PMS-CRM join을 제거하고 Context의 3-source join·typed binding을 전달한다. G2는 single read-only SELECT를 끝으로 하는 safe WITH CTE만 구조적으로 허용하며 DML·multi-statement·승인 밖 FQN/column/JOIN·literal filter는 차단한다. Analysis success는 G3 뒤 table·chart·explanation·evidence·artifact와 같은 request_id/trace를 조립하고 실패 상태를 성공처럼 채우지 않는다.
TEST_COMMANDS=target backend Context/G2/G3/API tests; backend 전체; compileall; gate_scope; git diff --check; jaehong branch CI
STOP_CONDITIONS=R2/AI/frontend/migration/OpenAPI route 변경 필요; general SQL parser/SQLGlot dependency 필요; live PENDING을 승인; fake chart/trace; 외부 서비스·비용·secret; scope/필수 검증 실패
R1_REVIEW_CONDITIONS=versioned/live 경계, safe CTE negative, 3-source Context mapping, G3 이후 chart/evidence/request trace와 backend 전체·source CI를 제출한다.
RESULT_SHA=dcd4d8378ea50cf1a3aeb4dca4cb0b89fb07e20f
RESULT_CI=31356025262 FAILURE — handoff REVIEW_REQUIRED로 후속 jobs skipped
BLOCKED_REASON=실제 R3-W5-F5 plan 조합에서 Context topology가 1-edge로 축약되어 ContractError가 발생하고, 5-edge 보정 뒤에도 required-filter 검사가 첫 CTE WHERE만 읽어 POS CTE filter를 누락한다. 단일 WHERE probe test로는 이 결함을 검출하지 못했으므로 병합을 보류한다.
```

### R4 · R4-W5-F7

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F7
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=actual R3 multi-CTE topology and required-filter composition
TASK_CARD_RANGE=R4-04·05 G120-046 Context topology·multi-CTE G2 REWORK
CURRENT_TASK_CARD_ID=R4-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=593b68a46c7800c1993be0656bea0c9bf58b57d6
START_POINT=origin/jaehong의 R4-W5-F6 결과를 보존하고 최신 dev 593b68a와 충돌 여부를 확인한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F7@593b68a
ALLOWED_PATHS=app/backend/app/adapters/contract_model.py; app/backend/app/adapters/i2_data_platform.py; app/backend/app/contracts.py; app/backend/app/services/analysis_service.py; app/backend/app/services/pipeline_support.py; tests/backend/test_analysis_pipeline.py; tests/backend/test_i2_data_platform.py; tests/backend/test_control_plane_contract.py; handoffs/R4-W5-F6.json; handoffs/R4-W5-F7.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/data/**; src/ai/**; Context schema·migration·OpenAPI route; frontend; root Compose/env/CI; dependency·SQLGlot; secret
HANDOFF_MANIFEST=handoffs/R4-W5-F7.json
ACCEPTANCE_CRITERIA=승인된 pms_crm_pos_gold_revenue_month_v1에 한해 R3와 합의한 6 asset·5-edge topology와 preaggregate_then_one_to_one_month cardinality를 model Context에 전달한다. G2 required-filter 검사는 각 CTE의 alias·WHERE 범위를 독립적으로 확인해 PMS·CRM·POS typed placeholder 11개를 exact parameter map과 대조하며, POS filter 하나만 제거해도 METRIC_FILTER_MISSING이어야 한다. 다른 CTE의 같은 field·literal·OR·unknown/duplicate placeholder·value mutation으로 우회할 수 없다. 실제 R3-W5-F5 Node2 plan shape를 test fixture로 직접 조합해 Context→Node2 output→G2→single binder를 통과시키고 second repair는 계속 차단한다.
ACCEPTANCE_IDS=AC1_FIVE_EDGE_TOPOLOGY;AC2_MULTI_CTE_FILTER_SCOPE;AC3_EXACT_TYPED_MAP;AC4_BYPASS_NEGATIVE;AC5_ACTUAL_R3_PLAN;AC6_SINGLE_BINDER;AC7_ONE_REPAIR
TEST_COMMANDS=target backend Context/G2 composition tests; backend 전체; compileall; gate_scope merge-base; git diff --check; jaehong branch CI
TEST_COMMAND_IDS=T1_TARGET;T2_BACKEND;T3_COMPILE;T4_SCOPE;T5_DIFF;T6_BRANCH_CI
STOP_CONDITIONS=R2/R3 product 변경 필요; general SQL parser/dependency 필요; approved join 밖 topology 합성; literal/OR 우회; local probe만 통과하고 actual R3 shape 실패; scope/필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local deterministic test와 허용 경로 commit·jaehong push만 허용한다. DataHub/Trino lifecycle·외부 서비스·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=1-edge topology 잔존; 첫 WHERE만 검사; POS filter 누락 허용; actual R3 plan 미검증; second repair; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=F6를 결함 상태로 선통합하지 않는다. F7은 origin/dev 대비 F6+F7 누적 diff와 두 handoff를 한 번에 제출하고 source CI PASS 뒤 dev에 통합한다. 이후 R3-W5-F5를 최신 dev에 동기화해 combined test·source CI를 다시 통과시킨다. 그 전 R1-W5-F9 actual API E2E를 재발행하지 않는다.
RESULT_SHA=44941147c1795fdfcdf9035293de336f02e63339
RESULT_CI=branch 31357307192 PASS; product 31357211797 PASS; 104 passed·10 skipped
```

### R4 · R4-W5-F8

```text
STATUS=MERGED_DEV
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F8
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=Context period binding preservation and R3 composition
TASK_CARD_RANGE=R4-04·05 period_start·period_end_exclusive Context REWORK
CURRENT_TASK_CARD_ID=R4-04
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=ff294bb56293f19e50d12cdf0412ab6d283ac77e
START_POINT=origin/jaehong을 최신 dev ff294bb로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R4-W5-F8@ff294bb
ALLOWED_PATHS=app/backend/app/adapters/contract_model.py; tests/backend/test_i2_data_platform.py; tests/backend/test_analysis_pipeline.py; handoffs/R4-W5-F8.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=src/data/**; src/ai/**; pipeline policy·binder 의미 변경; migration·OpenAPI·frontend; root Compose/env/CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R4-W5-F8.json
ACCEPTANCE_CRITERIA=ContractModelAdapter가 approved Context Package의 parameter_bindings에서 period_start와 period_end_exclusive를 이름·type=date·ISO value 그대로 읽어 execution_time에 전달하며 RequestContext.as_of로 덮어쓰지 않는다. 누락·중복·type 불일치·invalid date·start>=end는 model 호출 전에 fail-closed한다. 실제 R3-W5-F5 Node2 shape로 2026-05-01/2026-07-01과 required_filter 9개를 생성해 R4 G2 exact map과 single binder를 통과시키고, 임의 기간 mutation은 PARAMETERS_INVALID로 차단한다. 기존 5-edge·multi-CTE·repair 1회 경계를 유지한다.
ACCEPTANCE_IDS=AC1_PERIOD_BINDING_SOURCE;AC2_NO_AS_OF_OVERRIDE;AC3_DATE_FAIL_CLOSED;AC4_ACTUAL_R3_PERIOD;AC5_G2_BINDER;AC6_MUTATION_NEGATIVE;AC7_EXISTING_BOUNDARIES
TEST_COMMANDS=target backend ContractModel/Context/G2 composition; backend 전체; R3 consumer composition test read-only; compileall; gate_scope merge-base; git diff --check; jaehong branch CI
TEST_COMMAND_IDS=T1_TARGET;T2_BACKEND;T3_R3_CONSUMER;T4_COMPILE;T5_SCOPE;T6_DIFF;T7_BRANCH_CI
STOP_CONDITIONS=R2/R3 product 변경 필요; period를 question/Gold/as_of에서 추정; invalid range 허용; binder/policy 완화; dependency·external service·secret; scope/필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local deterministic test와 허용 경로 commit·jaehong push만 허용한다. Docker/DataHub/Trino lifecycle·외부 비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=as_of override 잔존; package binding 무시; invalid date/range 통과; R3 plan hardcode; 기존 negative/repair 회귀; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R4 source CI PASS 뒤 dev에 통합하고 R3-W5-F6를 최신 dev에 재동기화해 actual Node2→G2→binder와 dev 전체 CI를 복구한다.
RESULT_SHA=5720a01bb514eb401584d40e60ab970b10fc3146
RESULT_CI=branch 31357958938 PASS; product 31357850201 PASS; 110 passed·10 skipped
```

### R4 · R4-W5-F9

```text
STATUS=READY
ROLE_ID=R4
ASSIGNEE=김재홍
PERSONAL_BRANCH=jaehong
EXECUTION_BUNDLE_ID=R4-W5-F9
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=Analysis Definition·Run·Result persistence contract freeze
TASK_CARD_RANGE=R4-05·13·16 Analysis 저장·조회·현재 계약 재실행
CURRENT_TASK_CARD_ID=R4-05
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=b825e6da8c7f80f372dcf6bf436b540deff749d2
START_POINT=origin/jaehong을 최신 dev b825e6d로 fast-forward한 뒤 시작한다.
DIRECTIVE=ACTION
DIRECTIVE_TOKEN=R4-W5-F9@b825e6d
CONTRACT_VERSION=ANALYSIS-PERSISTENCE-v1.0.0-DRAFT; existing request→query→artifact reuse
ALLOWED_PATHS=app/backend/app/analysis_contracts.py; app/backend/app/adapters/analysis_repository.py; app/backend/app/services/analysis_service.py; app/backend/app/controllers/analysis_controller.py; app/backend/app/api/router.py; app/backend/app/main.py; app/backend/migrations/versions/20260810_06_analysis_persistence.py; app/backend/contracts/openapi.v0.1.json; app/backend/README.md; tests/backend/test_analysis_persistence.py; tests/backend/test_analysis_pipeline.py; tests/backend/test_openapi_contract.py; tests/backend/test_migration_compatibility.py; tests/backend/test_report_registration.py; handoffs/R4-W5-F9.json; docs/markdown/daily_reports/jaehong/일일보고.md
FORBIDDEN_PATHS=기존 migration·context.analysis_templates 의미 변경; R2/R3/frontend; Report worker/schedule; SQLGlot/G3 정책 확장; root Compose/env/CI; dependency; secret
HANDOFF_MANIFEST=handoffs/R4-W5-F9.json
ACCEPTANCE_CRITERIA=context.analysis_templates는 system routing template로 유지하고 user-owned versioned Analysis Definition만 additive migration으로 추가한다. Run/Result 본체는 기존 chat.analysis_requests→query.query_executions→artifact.analysis_artifacts를 재사용하고 Definition↔request 연결만 최소 저장하며 result blob을 복제하지 않는다. R1은 /analysis/definitions create·list·get, /analysis/definitions/{id}/runs replay, /analysis/runs list·detail route를 명시 승인한다. client는 owner/status/request_id/query_id/artifact_id/result를 제출할 수 없고, replay는 승인 Definition의 redacted question·typed parameters·as_of로 기존 AnalysisController 한 경로를 호출해 현재 entitlement·Context·G1/G2/G3·repair·binder를 다시 검증한다. terminal success·partial·failure와 idempotency를 저장하되 G3 전 Artifact 성공을 만들지 않고 과거 run은 불변이다. owner/role scope, 401·403·404·409·422·503, raw SQL·unbound parameter·result snapshot·secret 비노출, 기존 POST /analysis와 Report v1.1 9-operation 호환을 검증한다.
ACCEPTANCE_IDS=AC1_SYSTEM_TEMPLATE_IMMUTABLE;AC2_EXISTING_RUN_RESULT_REUSE;AC3_APPROVED_ROUTES;AC4_SERVER_OWNED_IDS_STATUS;AC5_CURRENT_GATE_REPLAY;AC6_TERMINAL_IMMUTABLE;AC7_AUTH_REDACTION;AC8_EXISTING_API_COMPAT
TEST_COMMANDS=python -m pytest -p no:cacheprovider tests/backend/test_analysis_persistence.py tests/backend/test_analysis_pipeline.py tests/backend/test_openapi_contract.py tests/backend/test_report_registration.py -q; python -m pytest -p no:cacheprovider tests/backend -q; python app/backend/scripts/export_openapi.py --check; alembic heads; isolated empty→head and 20260804_05→head; python -m compileall -q app/backend; gate_scope merge-base; git diff --check; jaehong branch CI
TEST_COMMAND_IDS=T1_TARGET;T2_BACKEND;T3_OPENAPI;T4_HEADS;T5_MIGRATION;T6_COMPILE;T7_SCOPE;T8_DIFF;T9_BRANCH_CI
STOP_CONDITIONS=기존 request/query/artifact 의미 변경 또는 raw result 복제 필요; client-owned status/id; G1/G2/G3 우회; system template user mutation; Report worker/schedule·SQLGlot/G3 정책·R2/R3/frontend 변경; dependency·외부 DB·secret; scope/필수 검증 실패
EXTERNAL_ACTION_PERMISSION=local deterministic test와 전용 ephemeral PostgreSQL migration 검증, 허용 경로 commit·jaehong push만 허용한다. 기존 app DB·volume·외부 서비스·비용·secret 변경은 금지한다.
AUTO_FAIL_CONDITIONS=새 result blob/table 중복; 과거 SQL 무검증 재실행; client-owned id/status; G3 전 Artifact success; owner bypass; raw SQL/result 노출; 기존 API 파손; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=R3-W5-F6와 경로 충돌 없이 병렬 수행한다. Analysis persistence source CI와 dev 통합 뒤 Report v1.2 worker·partial contract를 별도 카드로 발행한다.
```

### R5 · R5-W5-F1

```text
STATUS=MERGED_DEV
ROLE_ID=R5
ASSIGNEE=송민지
PERSONAL_BRANCH=minji
EXECUTION_BUNDLE_ID=R5-W5-F1
TARGET_INTEGRATION_GATE=I5
CHECKPOINT_GATES=mockup-aligned frontend browser regression
TASK_CARD_RANGE=R5-01·03·11·12·16·17 목업 기반 shell·Chat·Report 표현 정렬 및 회귀 검증
CURRENT_TASK_CARD_ID=R5-01
REPOSITORY_ROOT=C:\Users\Playdata\Documents\skn29_final_3team
BASE_BRANCH=dev
BASE_SHA=594c34da9ef14ec7db5a483446409dea69aee673
START_POINT=origin/minji를 최신 origin/dev 594c34da9ef14ec7db5a483446409dea69aee673로 fast-forward한 뒤 시작한다.
DIRECTIVE=REWORK
DIRECTIVE_TOKEN=R5-W5-F1@594c34d
ALLOWED_PATHS=app/enterprise-react/src/App.jsx; app/enterprise-react/src/components/layout/AppHeader.jsx; app/enterprise-react/src/components/layout/AppSidebar.jsx; app/enterprise-react/src/pages/AgentPage.jsx; app/enterprise-react/src/pages/ReportsPage.jsx; app/enterprise-react/src/styles.css; tests/frontend/contracts.test.mjs; handoffs/R5-W5-F1.json; docs/markdown/daily_reports/minji/일일보고.md
FORBIDDEN_PATHS=app/enterprise-react/src/api/**; app/enterprise-react/src/contracts/**; app/enterprise-react/src/data/**; app/enterprise-react/src/routing.js; package*.json; backend·data·AI; root Compose·env·CI; secret
HANDOFF_MANIFEST=handoffs/R5-W5-F1.json
ACCEPTANCE_CRITERIA=목업의 compact sidebar·52px topbar·고밀도 neutral dark/light token·질문 중심 thread/composer·근거 panel·Report 시각 계층을 기존 React 구조에 최소 이식한다. /agent·/reports·/catalog·/catalog/connections와 P2·customer360 차단, Analysis·Report HTTP client 기본·명시적 fixture mode·오류 자동 fallback 금지, 기존 artifact/query/trace/as_of/source·definition/version/run/block ID·승인본 immutable·queued receipt와 run 구분을 유지한다. 목업의 auto-fill·print/PDF/export/share·AI 보고서 도우미·localStorage 가짜 저장·실행은 구현하지 않는다. 1440·1024·768·360과 200% zoom에서 sidebar·panel 접근, single-column 읽기 순서, keyboard·focus·aria-expanded·aria-current·aria-live·텍스트+아이콘 상태를 확인한다. 외부 font·network·dependency를 추가하지 않는다.
ACCEPTANCE_IDS=AC1_MOCKUP_VISUAL_HIERARCHY;AC2_ROUTE_FREEZE;AC3_API_FIXTURE_BOUNDARY;AC4_ID_STATE_PRESERVATION;AC5_NO_MOCK_FEATURE_IMPORT;AC6_RESPONSIVE_A11Y;AC7_NO_DEPENDENCY
TEST_COMMANDS=python app/backend/scripts/export_openapi.py --check; python -m pytest -p no:cacheprovider tests/backend/test_openapi_contract.py tests/backend/test_report_registration.py -q; node tests/frontend/contracts.test.mjs; npm --prefix app/enterprise-react run build; browser fixture mode /agent·/reports 1440·1024·768·360·200% zoom·keyboard·focus·drawer·panel; browser API mode definition list/get→draft replace→approve→next draft→manual queued receipt→real history 및 401·403·409·422·503 회귀; python .github/scripts/gate_scope.py --branch minji --base origin/dev --head HEAD --mode merge-base; git diff --check
TEST_COMMAND_IDS=T1_OPENAPI;T2_BACKEND_CONTRACT;T3_FRONTEND_CONTRACT;T4_BUILD;T5_FIXTURE_BROWSER;T6_API_BROWSER;T7_SCOPE;T8_DIFF
STOP_CONDITIONS=route·API·schema·data fixture·backend 변경 필요; 목업 합성값·fake success·자동 fallback 필요; P2 export·share·customer360·자유 AI 도우미 편입 필요; package·dependency·외부 font/network·secret 필요; 승인본 직접 수정 또는 queued를 run으로 표시; 360px·200% zoom·keyboard·API browser 회귀 실패; 허용 경로 밖 변경; 필수 검증 실패
EXTERNAL_ACTION_PERMISSION=허용 frontend·test·handoff·R5 보고와 local fixture/API browser 검증용 임시 process·격리 DB 생성·정리, 승인된 commit·minji push만 허용한다. package 설치·외부 비용·secret·실데이터·운영 서비스 변경은 금지한다.
AUTO_FAIL_CONDITIONS=route·API·fixture 의미 변경; mockup fake 기능 이식; 승인본 수정; queued receipt를 run으로 표시; 360px·200% zoom·keyboard·API 회귀 실패; scope 위반; 필수 검증 FAIL
R1_REVIEW_CONDITIONS=변경 전후 1440·1024·768·360 screenshot, dark/light·keyboard·focus·200% zoom, fixture/API browser trace, frontend·backend contract·build, 정확한 handoff와 branch CI를 제출한다.
RESULT_SHA=25bfe2abf50fbfae669bb1a3d6e1959f17ed04e2
RESULT_CI=branch 31350163587 PASS
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

## 현재 통합 확인 사항

| ID | 상태 | 확인 결과 | 다음 결정 |
|---|---|---|---|
| E2E-DATA-01 | RESOLVED | versioned-trino 시연 Context와 Template을 YTD_SYNTHETIC으로 한정하고 일별 객실 매출을 집계했다. 브라우저에서 Frontend→Backend→G2→Trino→G3→Artifact가 READY로 완료됐으며 61행, 2,505,043,200 KRW, 기간 2026-05-01~2026-07-01, query 20260805_101833_00023_i4vd9를 확인했다. | 운영 real 모드와 학습 계약의 ACTUAL은 유지한다. 이후 R2가 합성 상태 명칭을 변경하면 versioned-trino 계약과 함께 갱신한다. |
| I5-PRIORITY-01 | IN_PROGRESS | R3와 R4의 required filter 계약은 string·boolean 중심이며 `period_end`/`period_end_exclusive`와 실행 binder가 불일치한다. 승인 3-source 질문 G120-046과 Gold hash는 있으나 제품 소비용 PMS·CRM·POS Context fixture가 없다. | R2 typed registry+3-source producer → R4 Context/G2/binder → R3 Node2/evaluator → R1 조합 회귀+실제 API E2E 순으로 통합한다. 이 경로 통과 전 RunPod와 Node2 기능 확장을 보류한다. |
| I5-BACKLOG-02 | PLANNED | Analysis는 기존 template/request/query/artifact 테이블이 있으나 persistence·조회·재실행 API가 없고, G2는 regex 기반, G3는 증폭·불변식·redaction이 부족하다. Report는 worker·schedule이 없고 실패 block 필드가 실행 전 실패를 표현하기 어렵다. | 기존 테이블 재사용 계약 결정 → Analysis persistence → SQLGlot G2 → R2 실행 증적/R4 G3 → Report v1.2 worker → R5 partial UI → schedule → Golden 보안·성능 검증 순으로 owner-scoped 카드 발행한다. |

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
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
