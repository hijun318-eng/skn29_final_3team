# Answervice sLLM 모델·학습·평가

| 항목 | 내용 |
|---|---|
| sLLM 역할 | `Structured Request + Approved Context → Trino SQL Draft` |
| 최우선 품질 | 실제 조회 결과가 Gold Result와 일치하는가 |
| 비교 원칙 | 같은 데이터 snapshot·Context·decoding·실행 환경에서 비교 |
| 학습 원칙 | Base benchmark와 오류 분석 뒤 반복 Model Error가 있을 때만 Adapter 학습 |

> 모델 이름이 “최신”이거나 일반 벤치마크 점수가 높다는 이유만으로 채택하지 않는다. Answervice의 Trino Text-to-SQL 과제에서 정확도·제약 준수·운영 비용을 직접 측정한다.

## 1. sLLM이 맡는 범위

```text
Structured Business Analysis Request
+ Approved Context Package
→ sLLM
→ Trino SQL Draft
```

sLLM은 다음을 하지 않는다.

- 전체 Schema 자유 탐색
- Metric·JOIN·Permission 창작
- 실제 날짜 계산
- SQL 실행과 결과 검증
- Report 문장 작성
- 전체 Workflow 계획

기존 검증 Analysis를 재사용할 수 있으면 sLLM을 호출하지 않는다.

## 2. 입출력 Contract

### 입력

1. 구조화된 Metric·Dimension·Filter·Period 요청
2. 허용된 Dataset / Table / Column
3. Asset Binding으로 확인된 Trino FQN
4. Metric / JOIN / Time / Identity Rule
5. 현재 Permission Scope
6. Trino dialect와 허용 SQL 정책
7. query/result 제한

### 출력

```json
{
  "sql": "SELECT ...",
  "used_assets": ["membership.public.members", "rooms.public.reservations"],
  "used_metrics": ["room_revenue"]
}
```

모델의 JSON 출력 기능을 신뢰 경계로 사용하지 않는다. Backend가 응답을 파싱하고 Pydantic/JSON Schema로 엄격히 검증한다. 자유 설명, Markdown code fence 또는 누락 필드가 있으면 정형 오류로 처리한다.

## 3. 후보 모델과 사전 자격 확인

2026-08-10 기준 공식 배포 페이지에서 확인한 후보 ID는 다음과 같다.

| 후보 | Model ID | 비교 시 주의 |
|---|---|---|
| Qwen3 4B Instruct | `Qwen/Qwen3-4B-Instruct-2507` | text-only, non-thinking 모델 |
| Qwen3.5 4B | `Qwen/Qwen3.5-4B` | multimodal 계열이지만 이 실험은 text-only 입력만 사용 |
| Kanana 2 3B Instruct | `kakaocorp/kanana-2-3b-instruct` | 한국어 효율과 별개로 Text-to-SQL을 동일 기준 평가; custom license 확인 |
| Gemma 4 E2B IT | `google/gemma-4-E2B-it` | multimodal·thinking 기능을 사용하지 않는 동일 SQL 생성 조건 필요 |

본 Benchmark 전에 모델마다 다음 smoke gate를 통과해야 한다.

1. Model ID와 exact revision SHA 확인
2. license와 프로젝트 사용 조건 검토
3. tokenizer/chat template 고정
4. text-only SQL 요청 10건 load·generation 성공
5. 목표 runtime에서 지원 여부 확인
6. 한 요청의 peak VRAM·startup time 기록

load나 license 조건을 통과하지 못한 모델은 정확도 표에서 억지로 비교하지 않고 `INELIGIBLE`과 사유를 기록한다.

## 4. 실험 순서

```text
Gold Dataset과 실행 환경 동결
→ 후보별 smoke gate
→ 동일 조건 Base benchmark
→ 오류 원인 분리
→ Context ablation
→ Best Base 선정
→ 반복 Model Error가 있을 때만 LoRA/QLoRA
→ Same Base vs Same Base + Adapter
→ 최종 채택·Serving 검증
```

Fine-tuning부터 시작하지 않는다. Context·Binding·Rule·Engine 오류는 모델 학습으로 고치지 않는다.

## 5. Gold Dataset 설계

### 5.1 한 Case의 필수 요소

```text
case_id
natural-language question
structured request
approved context
gold Trino SQL
expected result
comparison rule
data snapshot version
rule/binding version
difficulty / intent family / join graph
```

Gold SQL만 있고 Expected Result가 없으면 SQL 문장 유사도에 과도하게 의존하게 된다. 가능한 모든 positive case에 재현 가능한 Gold Result를 함께 둔다.

### 5.2 난이도

| Level | 범위 | 예 |
|---|---|---|
| L1 | Single Source 기본 | filter, aggregation, group, period |
| L2 | Single Source 복합 | CTE, subquery, 필요한 window function |
| L3 | 2 Source | 승인 JOIN, identity mapping |
| L4 | 3 Source | 객실·멤버십·F&B 교차 분석 |
| L5 | Temporal | 등급 이력, event-time, `as_of` |

권한 없음, Metric 없음, 승인 JOIN 없음은 sLLM에게 SQL을 강제로 만들게 하지 않는다. G1/G2 negative corpus로 분리한다.

### 5.3 Split과 누수 방지

단순 random row split을 피하고 다음 단위를 묶어서 분리한다.

- intent family
- join graph
- metric/query template
- temporal pattern
- 원문의 paraphrase 묶음

같은 SQL template의 표현만 바꾼 질문이 train과 test에 동시에 들어가면 성능이 과대평가된다. Gold Test는 최종 평가 전까지 학습·prompt 조정에 사용하지 않는다.

초기 수량은 고정 정답이 아니다. Coverage matrix를 먼저 채우고 learning curve를 보며 늘린다. 원문의 `Train 600~1,000 / Validation 80~120 / Test 약 120`은 자원 계획 범위일 뿐 충분성 기준으로 사용하지 않는다.

## 6. 공정한 Base Benchmark

모든 후보에 다음을 동일하게 적용한다.

- 같은 data snapshot과 Gold Test
- 같은 Structured Request와 Approved Context
- 같은 context serialization 순서
- 같은 최대 input/output 길이
- 가능한 경우 greedy 또는 `temperature=0` 단일 생성
- 같은 timeout과 retry 0회
- reasoning/thinking 비활성 또는 최종 SQL만 비교하도록 명시
- 같은 G2, Trino, Result comparator

모델별 chat template 차이는 그대로 사용하되 prompt 내용과 제공 정보는 동일하게 유지한다. 한 모델만 위한 수작업 schema 힌트는 공정 비교에서 제외하고 별도 최적화 실험으로 기록한다.

## 7. 평가 파이프라인

```text
Model response
→ Output Schema parse
→ SQL parse
→ G2 policy
→ Trino execution
→ Result normalization
→ Gold Result comparison
→ Error attribution
```

단계별 결과를 따로 저장해야 “실행 실패”와 “실행됐지만 결과가 틀림”을 구분할 수 있다.

## 8. 핵심 지표

### 8.1 Execution Result Accuracy — 최우선

생성 SQL의 결과를 Gold Result와 비교한다. 다음 비교 규칙을 case별로 명시한다.

- row order가 의미 없으면 정렬 후 비교
- column name/type 정규화 규칙
- money/정수는 정확 비교
- 부동소수 비율은 사전 정의한 tolerance 적용
- null과 빈 문자열 구분
- duplicate row 보존 여부

SQL 문자열이 달라도 같은 업무 결과를 만들면 성공할 수 있다.

### 8.2 단계별 지표

| 지표 | 의미 |
|---|---|
| Contract Parse Success | 모델 출력이 지정 Schema로 파싱되는 비율 |
| SQL Parse Success | Trino dialect SQL로 파싱되는 비율 |
| G2 Acceptance | 정상 후보 SQL이 정책을 통과하는 비율 |
| Query Success | Trino 실행이 성공하는 비율 |
| Result Accuracy | 실행 결과가 Gold와 일치하는 비율 |
| Context Violation | Approved Context 밖 자산을 사용한 비율 |
| Component Accuracy | table/column/JOIN/Metric/Time/filter 정확도 |

### 8.3 운영 지표

- cold start / warm average / p95 latency
- peak VRAM
- tokens per second와 throughput
- timeout / OOM / server error
- 장시간 반복 요청 안정성

SQL Exact Match는 디버깅용 보조 지표다.

## 9. 오류 원인 분리

| 오류 유형 | 판단 근거 | 우선 수정 |
|---|---|---|
| Data Error | Gold Result 또는 seed가 잘못됨 | dataset/seed |
| Context Error | 필요한 자산이 입력에 없음 | Context Builder |
| Binding Error | URN과 FQN 불일치 | Asset Binding |
| Rule Error | Metric/JOIN 계약 자체가 잘못됨 | Business Rule |
| Time Error | `as_of`/기간 계산 오류 | deterministic time logic |
| Policy Error | 정상 Gold SQL을 G2가 차단 | G2 policy |
| Engine Error | connector/type/runtime 실패 | Trino query layer |
| Model Error | 충분하고 올바른 Context에서도 SQL이 반복 오류 | prompt 또는 sLLM |

한 Case가 여러 원인을 가질 때 첫 실패 단계와 root cause를 함께 기록한다.

## 10. Metadata·Rule 효과 비교

같은 모델과 decoding으로 Context만 바꾼다.

```text
A. Schema only
B. Schema + Structural Metadata
C. Schema + Metadata + Business Rule
```

Result Accuracy, Context 크기, JOIN Accuracy와 latency를 함께 본다. 정보가 많다고 항상 좋은 것은 아니므로 Context precision과 token 수를 기록한다.

## 11. Fine-tuning 결정과 학습

다음 조건을 모두 만족할 때 Adapter 학습을 검토한다.

1. Context·Binding·Rule·Gold Result가 검증됐다.
2. G2·Trino·result comparator 문제가 아니다.
3. 같은 Model Error 유형이 여러 case에서 반복된다.
4. prompt와 serialization 조정만으로 충분히 개선되지 않는다.
5. GPU·일정·Serving 제약 안에서 재현 가능하다.

학습 원칙:

- LoRA를 우선하고 메모리 제약이 크면 QLoRA를 검토한다.
- Gold Test를 학습·early stopping·prompt 선택에 사용하지 않는다.
- adapter, base revision, dataset version, seed와 hyperparameter를 기록한다.
- 비교는 `같은 Base`와 `같은 Base + Adapter`로 한다.
- 한 번의 점수 상승보다 오류 유형별 개선과 회귀를 함께 본다.

## 12. G2 Retry 평가

첫 G2 실패 후 다음과 같은 최소 정형 오류만 전달한다.

```json
{
  "error_code": "UNAPPROVED_JOIN",
  "detail": {"left_asset_id": "...", "right_asset_id": "..."},
  "retry_count": 1
}
```

Secret, 민감 값, 전체 Schema를 재전송하지 않는다. 수정은 최대 1회이며, retry 전후 Result Accuracy와 추가 latency를 따로 기록한다.

## 13. Serving 선택

Serving stack은 모델을 고른 뒤 결정한다.

후보:

- vLLM
- SGLang
- Transformers 기반 단순 endpoint

선정 기준:

- exact model revision과 adapter 지원
- structured output 처리 안정성
- peak VRAM과 p95 latency
- healthcheck·timeout·cancellation
- 재현 가능한 container image

모델 weight는 Backend image와 분리한다. 개발 중 `latest`만 사용하지 않고 image digest 또는 exact tag를 Release Manifest에 남긴다.

## 14. 실험 기록과 채택 Gate

최소 기록:

- `experiment_id`, date, commit SHA
- model ID / revision SHA / license 검토 상태
- tokenizer / chat template / reasoning mode
- prompt / output schema / context schema Version
- binding / rule / data snapshot Version
- decoding parameter / seed / max tokens
- GPU / runtime / container
- 단계별 지표와 error breakdown
- average / p95 latency / peak VRAM

최종 표:

| 항목 | Qwen3 4B | Qwen3.5 4B | Kanana 2 3B | Gemma 4 E2B |
|---|---:|---:|---:|---:|
| Eligibility | 미검증 | 미검증 | 미검증 | 미검증 |
| Result Accuracy | 미측정 | 미측정 | 미측정 | 미측정 |
| Query Success | 미측정 | 미측정 | 미측정 | 미측정 |
| Context Violation | 미측정 | 미측정 | 미측정 | 미측정 |
| p95 Latency | 미측정 | 미측정 | 미측정 | 미측정 |
| Peak VRAM | 미측정 | 미측정 | 미측정 | 미측정 |

채택은 Result Accuracy, 제약 준수, 운영 자원, license와 Serving 안정성을 종합해 결정한다. 측정 전 숫자를 만들지 않는다.

## 15. 모델 ID 확인 링크

- [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
- [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)
- [kanana-2-3b-instruct](https://huggingface.co/kakaocorp/kanana-2-3b-instruct)
- [gemma-4-E2B-it](https://huggingface.co/google/gemma-4-E2B-it)

다음 문서: [03. 구현·운영·검증](03_Answervice_구현_운영_검증.md)
