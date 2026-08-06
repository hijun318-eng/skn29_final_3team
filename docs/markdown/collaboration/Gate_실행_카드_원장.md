# Gate 실행 카드 원장

| 항목 | 내용 |
|---|---|
| 문서 설명 | 현재 역할별 실행 카드와 Gate 중단·통합 조건을 관리하는 활성 원장 |
| 문서 분류 | 일반 문서 |
| 버전 | v4.3 |
| 문서 기준일 | 2026-08-06 10:09 |
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
| R1 | `R1-W4-F7` | `IN_PROGRESS` | `junhee` |
| R2 | `R2-W4-F4` | `MERGED_DEV` | `seung` |
| R3 | `R3-W4-F7` | `MERGED_DEV` | `daesung` |
| R4 | `R4-W4-F8` | `MERGED_DEV` | `jaehong` |
| R5 | `R5-W4-F4` | `BLOCKED` | `minji` |

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
STATUS=IN_PROGRESS
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

## 현재 통합 확인 사항

| ID | 상태 | 확인 결과 | 다음 결정 |
|---|---|---|---|
| E2E-DATA-01 | RESOLVED | versioned-trino 시연 Context와 Template을 YTD_SYNTHETIC으로 한정하고 일별 객실 매출을 집계했다. 브라우저에서 Frontend→Backend→G2→Trino→G3→Artifact가 READY로 완료됐으며 61행, 2,505,043,200 KRW, 기간 2026-05-01~2026-07-01, query 20260805_101833_00023_i4vd9를 확인했다. | 운영 real 모드와 학습 계약의 ACTUAL은 유지한다. 이후 R2가 합성 상태 명칭을 변경하면 versioned-trino 계약과 함께 갱신한다. |

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v4.2 | 2026-08-06 09:30 | source CI 확인·작업 전 경로 검사·변경 문서 CI·보고 일괄 통합을 위한 R1 유지보수 카드 발행·착수 |
| v4.1 | 2026-08-05 20:14 | versioned-trino 합성 기간 상태·일별 집계·KPI·Evidence 기간을 일치시키고 실브라우저 E2E 병목 해소 |
| v4.0 | 2026-08-05 19:44 | 역할별 최신 실행 카드만 활성 원장에 유지하고 기존 전체 이력을 archive로 분리 |
