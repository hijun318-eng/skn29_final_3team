# 멀티턴·발화 이해 BP와 벤치마크 적용

> 상태: 2026-08-15 외부 공식 문서·공개 연구를 현재 Answervice P0 계약에 번역한 참고 문서다. 제품 요구사항의 기준은 `docs/product/00_기획서.md`~`03_아키텍처.md`이며, 공개 벤치마크 점수만으로 P0를 통과시키지 않는다.

## 결론

Answervice의 발화 이해는 **정규식 대 GPT** 중 하나를 고르는 문제가 아니다. 다음 세 계층을 분리한다.

1. 결정론적 전처리는 Unicode, 공백, 날짜 표기, 승인된 exact alias처럼 의미를 바꾸지 않는 기계적 정리만 수행한다.
2. GPT/Node1은 존댓말·반말, 어순, 축약, 경미한 오탈자, 후속 지시어를 `TurnRouteCandidate`와 typed slot 후보로 변환한다. 출력은 strict JSON Schema로 제한한다.
3. 서버 resolver가 현재 사용자에게 보이는 DataHub Term·관계, Rule, Conversation focus, source Turn, Artifact schema를 대조해 하나로 확정한다. 0개·복수 후보이면 실행하지 않고 확인한다.

Structured Output은 형식을 고정할 뿐 slot 값의 의미 정확성을 보장하지 않는다. 따라서 모델은 후보 생성자이고 서버 resolver가 실행 권한자다.

## 참고한 BP와 우리 프로젝트 적용

| 외부 근거 | 확인한 핵심 | Answervice에 적용하는 방식 |
|---|---|---|
| [Google Dialogflow CX Parameters](https://docs.cloud.google.com/dialogflow/cx/docs/concept/parameter) | 원문과 별도로 original/resolved parameter를 구조화하고 session parameter로 Turn 사이 상태를 전달한다. | raw transcript 기억 대신 `resolved_request`, slot별 source/provenance, `INHERIT/SET/REMOVE` patch를 저장한다. 정책 필터는 session slot으로 상속하지 않는다. |
| [OpenAI Structured Outputs](https://openai.com/index/introducing-structured-outputs-in-the-api/) | JSON Schema 준수는 높일 수 있지만 값 자체의 논리·의미 오류는 남는다. | Node1 후보 schema는 strict하게 봉인하되 DataHub·Rule·권한·기간·Artifact validator를 생략하지 않는다. |
| [KLUE: Korean Language Understanding Evaluation](https://arxiv.org/abs/2105.09680) | 한국어 NLU에 Dialogue State Tracking이 포함되며, 대화 상태를 slot-value 집합으로 평가한다. counterfactual goal과 unseen KB에서 성능 저하도 별도 본다. | `metric/period/dimension/filter/grain/action`의 Turn별 joint-state exact match를 측정하고, 보지 않은 승인 별칭·기간 조합·지시어를 held-out에 둔다. KLUE 공개 점수 자체는 제품 Gate가 아니다. |
| [CheckList: Behavioral Testing of NLP](https://aclanthology.org/2020.acl-main.442/) | 평균 정확도만 보지 않고 Minimum Functionality, Invariance, Directional Expectation으로 언어 행동을 분해해 검사한다. | canonical 발화, 같은 의미 변형, 의미를 바꾸는 critical-token contrast를 별도 test family로 봉인한다. |
| [BFCL V3 Multi-Turn](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html) | missing parameter/function, irrelevance, long context를 나누고 매 Turn의 backend state와 최소 실행 경로를 함께 평가한다. | Turn DB state와 `Run/query/View/block` 경로를 동시에 채점한다. 올바른 답처럼 보이더라도 불필요 query나 잘못된 source Turn이면 실패다. |
| [OpenAI Evaluation Best Practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) | 범용 leaderboard보다 실제 사용 분포의 task-specific eval, typical/edge/adversarial case, 지속적 회귀, 사람 라벨과 자동 채점의 합의가 중요하다. | 호텔 도메인 전용 sealed manifest를 만들고 production feedback은 검토·PII 제거 후 다음 버전에만 추가한다. 특정 Evals 제품에는 의존하지 않는다. |

## 행동 테스트 매트릭스

### 1. MFT — 최소 기능

각 P0 지원 intent가 가장 명확한 문장에서 정확히 동작해야 한다.

- `2025년 8월 객실 매출을 보여줘.` → `ANALYSIS`, 승인 Metric, 절대 기간, 새 Run·query 1건
- `그 전 달은?` → `SOURCE_PERIOD`, 앞선 eligible Analysis Turn을 명시 참조
- `그래프로 띄워줘.` → `PRESENTATION`, 같은 Artifact, 새 ViewSpec, query 0건
- `표로도 띄워줘.` → 기존 View 유지+table 추가, query 0건
- 필수 slot이 없으면 `NEEDS_CLARIFICATION`, Run·query 0건

### 2. INV — 의미 불변 변형

다음 변형은 같은 `turn_kind`와 `resolved_request_hash`로 수렴하거나, 원문도 모호했다면 같은 확인 질문으로 수렴해야 한다.

- 존댓말/반말: `보여주세요` / `보여줘`
- 조사·띄어쓰기: `지난 달` / `지난달`
- 어순: `2025년 8월 객실 매출` / `객실 매출, 2025년 8월`
- 승인 별칭·한영 혼용: DataHub가 같은 Term으로 승인한 표현만
- 경미한 한 글자 오탈자: 하나의 승인 후보로만 안전하게 수렴할 때
- 지시어: eligible focus가 하나일 때의 `그거`, `그 전 달`, `다른 그래프`

### 3. DIR — 의미 방향 변화

다음 token이 바뀌면 동일 hash로 수렴해서는 안 된다. 새 slot 값으로 확정되거나 확인해야 한다.

- 숫자·날짜·단위
- 부정: `포함` / `제외`, `아닌`
- 비교 방향: `증가` / `감소`, `A 대비 B` / `B 대비 A`
- 경계: `이상` / `초과`, `이하` / `미만`
- 호텔·회원 등급·사용자 filter
- 표현 대체/추가: `표로` / `표로도`

### 4. NEG — 실행하면 안 되는 입력

- 지원하지 않는 예측·처방·예약 변경·쓰기 의도
- 권한 없는 Metric·Term·Asset 탐색
- prompt injection과 정책 무시 지시
- anchor 후보가 둘 이상인 `그거`, `다른 그래프`
- 데이터 범위 밖 WALL_CLOCK 요청
- 긴 대화 안에 섞인 무관한 숫자·날짜·과거 실패 Turn

이 집합의 `unsafe_silent_execution_rate`는 반드시 0이어야 한다.

## 멀티턴 채점 방식

문장 유사도 하나로 채점하지 않는다. 매 Turn마다 두 종류를 함께 확인한다.

### 상태 기반 채점

- Conversation owner, release, head, focus가 예상과 일치하는가
- resolved slot과 provenance가 예상과 일치하는가
- 실패·명확화 Turn이 기존 focus를 오염시키지 않았는가
- Presentation ViewSpec과 Report Draft block/revision이 예상 상태인가
- 권한 회수·stale head에서 mutation이 0건인가

### 경로 기반 채점

- 예상한 `turn_kind`, `reason_code`, source Turn을 사용했는가
- Analysis가 필요한 Turn만 model·Trino를 호출했는가
- `Run/query/View/block` 수가 사전 등록 oracle과 일치하는가
- 같은 Artifact 표현 전환에서 query가 0건인가
- 새 분석과 Report child Run에 현재 permission snapshot과 query 근거가 있는가

최종 문장이 그럴듯해도 상태 또는 경로가 틀리면 실패다.

## 권장 지표

| 지표 | 용도 |
|---|---|
| `turn_route_exact_match` | ANALYSIS/PRESENTATION/REPORT_ACTION 및 차단 결과 정확도 |
| `joint_slot_exact_match` | Metric·기간·dimension·user filter·grain·action 전체 일치 |
| `resolved_request_hash_match` | 같은 의미 변형의 수렴 여부 |
| `critical_token_preservation` | 숫자·부정·방향·경계·대상 보존 |
| `clarification_precision/recall` | 불필요한 확인과 위험한 자동 추측을 함께 측정 |
| `source_turn_exact_match` | 지시어·상대기간·비교의 anchor 정확도 |
| `unsafe_silent_execution_rate` | 잘못 이해한 요청을 확인 없이 실행한 비율 |
| `unnecessary_model_call/query_rate` | Presentation·Report action의 불필요 비용·위험 |
| `backend_state_match_per_turn` | DB의 Turn/head/focus/View/Draft 상태 정확도 |
| `dialogue_success_rate` | 모든 Turn의 상태·경로를 통과한 대화 비율 |

P0의 봉인된 critical·negative·Golden 집합은 전건 통과와 `unsafe_silent_execution_rate=0`을 요구한다. 일반 equivalence held-out 목표치는 표본 구성과 두 명 이상의 도메인 검토자 합의를 먼저 확보한 뒤 사전 등록한다. 평균 정확도가 높아도 특정 critical slice 실패를 상쇄하지 못한다.

## 데이터셋과 회귀 운영

1. 각 case에 `case_id`, capability, test type, source, redacted utterance, prior state, expected route/slots/clarification/state/action count를 저장한다.
2. `train/prompt-example/calibration/held-out/release` split과 checksum을 분리한다. held-out을 prompt 예시에 재사용하지 않는다.
3. synthetic 변형은 초안 생성에만 쓰고 호텔 도메인 담당자가 의미 동일·차이를 검수한다.
4. production 발화는 동의·보존 정책과 PII 제거를 통과한 경우에만 다음 manifest 후보가 된다.
5. prompt, model, alias, Glossary, Rule, resolver가 바뀔 때 전체 critical set과 영향 slice를 다시 실행한다.
6. 자동 exact/state/action grader를 우선하고 자연어 설명 품질만 blind human review 또는 사람과 합의된 grader로 보조한다.
7. 모델 비교는 같은 sealed manifest, temperature/seed 정책, 반복 횟수, latency, 비용, 실패율로 수행한다. 공개 leaderboard 순위만으로 선택하지 않는다.

## 도입하지 않는 것

- Dialogflow, BFCL 또는 특정 eval SaaS를 runtime dependency로 추가하지 않는다.
- 전체 transcript를 모델 memory로 주입하지 않는다.
- public KLUE/BFCL 점수를 Answervice 정확도라고 발표하지 않는다.
- 발화 이해를 이유로 범용 multi-agent framework를 먼저 도입하지 않는다.
- LLM-as-a-judge 한 개의 점수로 Metric·기간·권한·query 정확성을 판정하지 않는다.

핵심은 외부 제품을 복제하는 것이 아니라, 검증된 아이디어를 **구조화 상태, 제한된 모델 권한, per-Turn 상태+경로 oracle, 한국어 행동 회귀 세트**로 번역하는 것이다.
