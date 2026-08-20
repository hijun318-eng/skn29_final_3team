# Qwen3.5-2B 기반 Answervice Node2 학습·검증·배포 실행 가이드

> 상태: **실행 계획 / 미학습 / 미검증**<br>
> 작성 기준일: 2026-08-20<br>
> 대상: Answervice의 Node2 SQL 생성 및 1회 Repair 경로<br>
> 기본 모델 결정: `Qwen/Qwen3.5-2B` 우선<br>
> 4B 전환 조건: 이 문서의 2B 데이터·계약·검증 조건을 충족했는데도 사전 정의한 품질 Gate를 통과하지 못한 경우<br>
> 주의: 이 문서는 학습 담당자의 실행 인수인계 문서다. 문서가 존재한다는 사실은 adapter 학습, endpoint 배포 또는 제품 E2E 성공을 의미하지 않는다.
> Backend 전환 준비: `MODEL-v1.12.0`은 내부에서 SQL-only 또는 완전한 legacy lineage 응답을 허용한다. 활성 GPT provider에는 기존 다섯 필드 strict schema와 `node2.sql` prompt를 계속 보내므로 현재 GPT 동작은 유지된다.

---

## 0. 문서 목적

이 문서는 기존 adapter를 수정하거나 재사용하는 절차가 아니다. `Qwen/Qwen3.5-2B`를 Answervice의 Node2 전용 sLLM으로 처음부터 학습하여, 현재 GPT 계열 모델이 담당할 수 있는 SQL 생성 경로를 교체하기 위한 단일 실행 기준을 정의한다.

학습 담당자는 이 문서만 보고 다음을 판단하고 실행할 수 있어야 한다.

1. Node2가 서비스에서 어떤 입력을 받고 어떤 결과를 내야 하는가.
2. 학습데이터 한 건은 어떤 형태여야 하는가.
3. 실제 서비스 스키마에 과적합하지 않도록 데이터를 어떻게 구성하는가.
4. 한 번의 LoRA 학습에서 어떤 설정을 고정하는가.
5. 학습 전후 어떤 검증을 통과해야 하는가.
6. adapter를 vLLM과 Backend에 어떻게 연결하는가.
7. 어떤 실패는 데이터·Context·코드 문제이고, 어떤 실패만 모델 용량 문제인가.

### 이번 범위

- Node2의 구조화된 입력에서 Trino read-only SQL 생성
- Node2 Repair의 1회 SQL 수정
- Qwen3.5-2B Non-thinking SFT/LoRA
- 학습데이터 계약, split, 검증, release manifest
- vLLM 서빙 및 Backend 연결을 위한 준비 조건
- 실제 스키마 이름에 대한 암기 최소화

### 이번 범위가 아닌 것

- Node1의 질문 정규화·명확화 학습
- Node3의 결과 설명 학습
- 자연어 대화 전체를 입력으로 받는 범용 text-to-SQL agent
- 모델이 권한, 실행 여부, 최종 Gate를 결정하는 구조
- 모델이 DataHub/Trino를 직접 탐색하는 agent 구조
- Trino가 아닌 다른 SQL dialect 지원
- 과거 `node2-lora-adapter_v4.1.zip`의 재사용 또는 이어서 학습
- Thinking/Chain-of-Thought 학습
- 4B 모델의 선제 학습

---

## 1. 최종 기술 결정

### 1.1 Node2의 역할

Node2는 자연어 질문만 보고 데이터베이스를 추측하는 모델이 아니다. Node1과 Context Builder가 확정한 요청 및 승인된 runtime 계약을 받아, 그 계약 안에서만 Trino SQL을 만드는 **제약된 SQL 플래너**다.

```text
사용자 질문
  → Node1: 질문 정규화, intent/metric/dimension/filter 해석
  → Context Builder: 권한과 DataHub metadata를 반영한 6개 runtime 계약 구성
  → Node2 Qwen3.5-2B: parameterized Trino SQL 생성
  → SQLGlot G2 Guard: AST/정책/지표/조인/시간/파라미터 검증
  → 서버 소유 parameter 값 AST binding
  → Trino read-only 실행
  → 결과/lineage/evidence 저장
```

### 1.2 시간 제약을 반영한 설계 결정

장기적으로 typed Query Plan과 결정적 SQL compiler를 도입하는 방법도 가능하다. 하지만 현재 서비스는 이미 모델이 SQL을 반환하고 SQLGlot이 AST를 검증하는 경로를 갖고 있다. 제한된 일정 안에 compiler, 새 Plan schema, 새 validation을 동시에 추가하면 학습 외의 변경 범위가 과도해진다.

따라서 이번 release에서는 다음을 고정한다.

- 현재의 `runtime contracts → SQL → SQLGlot Guard` 구조를 유지한다.
- Node2 모델 출력은 SQL 하나로 축소한다.
- 실제 lineage는 모델이 선언하지 않고 SQLGlot AST와 입력 계약에서 서버가 계산한다.
- 동일한 adapter가 Node2와 Node2 Repair prompt를 함께 학습한다.
- 운영에서는 Thinking을 끈다.

### 1.3 목표 모델 출력

Node2:

```json
{
  "sql": "SELECT ... LIMIT 100"
}
```

Node2 Repair:

```json
{
  "corrected_sql": "SELECT ... LIMIT 100"
}
```

모델은 Markdown, 설명, reasoning, parameter 값, 실행 결과, 승인 여부를 출력하지 않는다.

---

## 2. 현재 저장소에서 확인된 Node2 구조

이 절은 목표 구조가 아니라 **현재 코드에서 확인된 사실**이다.

### 2.1 현재 요청 계약

현재 `node2_request`는 다음 9개 필드를 요구한다.

| 필드 | 책임 |
|---|---|
| `question_id` | trace 식별자. SQL 의미에는 사용하지 않는다. |
| `normalized_question` | Node1이 정규화한 질문 |
| `resolved_request` | 확정된 intent, metric, dimension, filter |
| `schema_context` | 요청에서 사용할 수 있는 승인 asset·column·grain |
| `metric_rules` | 지표 source, aggregation, result field, unit, time field, required filter |
| `join_graph` | 승인된 join edge, cardinality, temporal/preaggregation 규칙 |
| `time_rules` | timezone, calendar, half-open interval, time field normalization |
| `parameter_contract` | named placeholder와 타입·scope |
| `query_policy` | dialect, read-only, LIMIT, 허용 함수·catalog |

권위 파일:

- `src/ai/contracts/node_io.v0.1.json`
- `app/backend/app/adapters/model_schemas.py::node2_training_input`
- `app/backend/app/adapters/model_context.py::serialize_context_package`

`node2_training_input`은 모델 호출 전에 다음을 검사한다.

- 여섯 runtime contract가 모두 존재한다.
- resolved intent는 하나다.
- `resolved_request.metric_ids`와 `metric_rules`의 ID 집합이 정확히 일치한다.
- dimension은 metric rule에서 승인한 dimension만 사용한다.
- Node2 일반 생성과 Repair가 같은 계약 형태를 사용한다.

### 2.2 현재 응답 계약

현재 내부 `node2_response`는 전환 호환성을 위해 두 형태 중 정확히 하나를 허용한다.

신규 Qwen 학습·향후 서빙 목표:

```json
{
  "sql": "..."
}
```

활성 GPT provider가 현재 계속 사용하는 legacy 형태:

```json
{
  "sql": "...",
  "used_assets": ["..."],
  "used_columns": [
    {"asset_fqn": "...", "column": "..."}
  ],
  "used_joins": ["..."],
  "used_metrics": ["..."]
}
```

네 legacy lineage 필드는 모델의 자기 선언이며, SQL Guard가 실제 AST와 일치하는지 다시 검사한다. 부분 lineage는 허용하지 않는다. `sql`만 있거나 네 lineage 필드가 모두 있어야 한다.

### 2.3 현재 모델 호출 설정

`app/backend/app/adapters/model_schemas.py::qwen_payload`에서 다음을 확인할 수 있다.

- `temperature=0`
- `chat_template_kwargs.enable_thinking=false`
- `guided_json=guided_serving_schema(node)`
- Node2와 Repair의 출력 상한은 각각 1,280 tokens

이 방향은 유지한다. Qwen3.5-2B 공식 모델 카드에 따르면 모델은 Thinking과 Non-thinking을 지원하지만 2B는 Thinking loop와 종료 실패에 더 취약할 수 있다. Node2는 reasoning 문장보다 결정적 구조 출력이 중요하므로 Non-thinking만 사용한다.

공식 참고:

- <https://huggingface.co/Qwen/Qwen3.5-2B>

### 2.4 현재 SQL 검증과 Repair

`app/backend/app/services/analysis/stages/plan_stage.py`와 `app/backend/app/services/sql_guard/guard.py`의 현재 흐름은 다음과 같다.

1. 승인된 Template SQL이 있으면 모델을 호출하지 않는다.
2. Template이 없으면 Node2를 호출한다.
3. 모델 계획에 `sql`이 있는지 검사한다.
4. SQLGlot으로 단일 read-only SELECT와 LIMIT를 검사한다.
5. 실제 physical table과 승인 asset 집합을 대조한다.
6. 실제 함수와 `query_policy.allowed_functions`를 대조한다.
7. column, metric 수식, required filter, time rule을 검사한다.
8. join graph, cardinality, grain, preaggregation을 검사한다.
9. named parameter 집합을 확인하고 서버 값으로 AST binding한다.
10. 위반이면 Node2 Repair를 한 번만 호출한다.
11. 수정 SQL도 실패하면 실행하지 않고 typed error로 닫는다.

SQL Guard는 성공 시 이미 다음 권위 정보를 반환한다.

- canonical SQL
- executable SQL
- AST에서 계산된 references
- bound parameters
- AST evidence

따라서 모델의 `used_*` 자기 선언은 서비스의 권위 원본이 될 필요가 없다.

### 2.5 현재 모델·학습 release 상태

현재 저장소 기준으로 다음 차이가 존재한다.

| 항목 | 현재 상태 |
|---|---|
| Node2 schema/prompt release | 활성 계약 존재 |
| runtime Qwen profile | `Qwen/Qwen3.5-4B`를 가리킴 |
| `train_lora.py` 기본 모델 | `Qwen/Qwen3-4B-Instruct-2507` |
| 기존 train max length | 12,288 |
| 현재 Qwen runtime context | 5,120 |
| SQL LoRA release candidate | `DRAFT / NOT_READY` |
| `sql_lora_enabled_nodes` | 빈 배열 |

즉, 현재 코드는 Qwen3.5-2B adapter를 바로 학습·배포할 준비가 완료된 상태가 아니다. 아래 변경을 먼저 반영해야 train-serving skew를 피할 수 있다.

---

## 3. Backend 호환 패치와 Qwen 활성화 전에 남은 변경

### 3.1 Node2 출력 단순화

현재 네 lineage 출력은 다음 권위 원본으로 대체한다.

| 제거할 모델 출력 | 서버 권위 원본 |
|---|---|
| `used_assets` | SQLGlot AST physical tables |
| `used_columns` | SQLGlot AST column lineage |
| `used_joins` | AST join과 runtime `join_graph` 매칭 결과 |
| `used_metrics` | `resolved_request.metric_ids`와 `metric_rules` |

Qwen 학습·서빙 목표 `node2_sql_only_response`:

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["sql"],
  "properties": {
    "sql": {"type": "string", "minLength": 1}
  }
}
```

이 변경은 모델의 작업량과 실패 지점을 줄인다. SQL이 맞는데 `used_columns`를 하나 누락해서 전체 요청이 실패하는 상황을 제거한다.

### 3.2 현재 반영된 호환 변경과 남은 활성화 작업

Backend에는 GPT를 중단하지 않는 호환 경계가 먼저 반영되어 있다. 학습 담당자는 SQL-only 계약과 `node2.sql_only` prompt를 사용한다. Qwen endpoint를 실제로 연결할 때만 provider route의 prompt/guided schema 선택을 활성화한다.

| 파일 | 현재 상태 또는 남은 작업 |
|---|---|
| `src/ai/contracts/node_io.v0.1.json` | 반영: SQL-only와 완전한 legacy 응답을 `oneOf`로 수용 |
| `src/ai/prompt_registry.py` | 반영: GPT용 `node2.sql` 유지, 학습용 `node2.sql_only` 추가 |
| `app/backend/app/adapters/model_adapter.py` | 반영: SQL-only이면 declared lineage 없이 plan 생성 |
| `app/backend/app/services/sql_guard/guard.py` | 기존 동작 유지: 모델 lineage가 없어도 AST references 생성 |
| `app/backend/app/adapters/model_schemas.py` | 반영: 활성 serving schema는 legacy 유지, SQL-only schema helper 추가 |
| `src/ai/training/dataset.py` | 반영: 신규 Node2 compile은 SQL-only output과 prompt를 강제 |
| `src/ai/training/verify_case_specs.py` | 반영: SQL-only이면 AST/runtime contract를 권위 lineage로 사용 |
| `src/ai/training/evaluate_lora.py` | 현재 SQL field 평가 가능. 실제 2B 실행 전 model 기본값/revision 변경 필요 |
| Qwen provider route | 남음: adapter 준비 후 `node2.sql_only`와 SQL-only guided schema 선택 |
| `src/modelops/model_runtime_manifest.v1.json` | 남음: exact Qwen3.5-2B revision, context/output capacity, model alias 추가 |

### 3.3 변경 완료 확인 조건

Full 학습과 Qwen 활성화 전에 다음이 통과해야 한다.

- `node2_request`의 9개 입력 필드는 유지된다.
- 학습 compile은 Node2의 `sql` 외 assistant 필드를 거부한다.
- Backend 내부 응답 검증은 SQL-only 또는 완전한 legacy lineage만 허용한다.
- 활성 GPT serving schema와 `node2.sql` prompt는 기존 다섯 필드 형태를 유지한다.
- `node2_repair_response`는 `corrected_sql`만 허용한다.
- 모델 응답에서 lineage가 없어도 G2가 AST references를 생성한다.
- 기존 lineage 저장·감사 기능이 AST evidence로 유지된다.
- guided JSON schema가 학습 assistant 출력과 정확히 일치한다.
- prompt version, response schema version, dataset version이 같은 release 경계에 묶인다.

기존 다섯 필드 데이터를 신규 Qwen 학습에 사용하면 안 된다. Qwen 학습 형식과 향후 Qwen 서빙 형식은 `node2.sql_only`와 `{"sql":"..."}`로 동일해야 한다. GPT legacy 형식은 전환 기간의 별도 활성 provider 계약이다.

---

## 4. 학습데이터 기본 단위

### 4.1 Full case spec

학습 원본은 단순한 `question → SQL` 쌍이 아니라 다음 증거를 포함하는 full case spec이어야 한다.

```json
{
  "case_id": "train-pms-revenue-0001",
  "split": "train",
  "node": "node2",
  "domain": "hotel_pms",
  "scenario_group": "single-asset-sum-by-day",
  "synthetic": false,
  "schema_version": "<NEW_NODE2_SCHEMA_VERSION>",
  "seed_version": "<TRINO_DATA_RELEASE>",
  "review_status": "APPROVED",
  "trino_status": "PASS",
  "result_sha256": "<NORMALIZED_RESULT_SHA256>",
  "input": {
    "question_id": "opaque-trace-id",
    "normalized_question": "승인된 기간의 일별 객실 매출을 조회",
    "resolved_request": {
      "intent": "aggregate",
      "metric_ids": ["room_revenue"],
      "dimensions": [
        {
          "asset_fqn": "serving.pms.daily_revenue",
          "column": "business_date"
        }
      ],
      "filters": []
    },
    "schema_context": {
      "version": "<CONTEXT_RELEASE>",
      "assets": [
        {
          "urn": "<DATAHUB_URN>",
          "fqn": "serving.pms.daily_revenue",
          "grain": {
            "kind": "daily",
            "keys": ["hotel_id", "business_date"]
          },
          "columns": [
            {
              "name": "business_date",
              "native_type": "date",
              "nullable": false,
              "role": "time"
            },
            {
              "name": "room_revenue",
              "native_type": "decimal(18,2)",
              "nullable": false,
              "role": "measure"
            }
          ]
        }
      ]
    },
    "metric_rules": [
      {
        "id": "room_revenue",
        "source": {
          "kind": "column",
          "field": {
            "asset_fqn": "serving.pms.daily_revenue",
            "column": "room_revenue"
          }
        },
        "aggregation": "sum",
        "result_field": "room_revenue",
        "unit": "krw",
        "time_field": {
          "asset_fqn": "serving.pms.daily_revenue",
          "column": "business_date"
        },
        "dimensions": [
          {
            "asset_fqn": "serving.pms.daily_revenue",
            "column": "business_date"
          }
        ],
        "required_filters": []
      }
    ],
    "join_graph": {"edges": []},
    "time_rules": {
      "timezone": "Asia/Seoul",
      "calendar_id": "gregorian",
      "interval": "[start,end)",
      "start_parameter": "start_date",
      "end_parameter": "end_date",
      "fields": [
        {
          "field": {
            "asset_fqn": "serving.pms.daily_revenue",
            "column": "business_date"
          },
          "native_type": "date",
          "bucket": "day",
          "timezone_mode": "preserve"
        }
      ]
    },
    "parameter_contract": {
      "style": "named",
      "parameters": [
        {"name": "start_date", "type": "date", "scope": "time"},
        {"name": "end_date", "type": "date", "scope": "time"}
      ]
    },
    "query_policy": {
      "dialect": "trino",
      "statement_type": "select",
      "read_only": true,
      "require_limit": true,
      "max_limit": 100,
      "allowed_functions": ["sum"],
      "allowed_catalogs": ["serving"]
    }
  },
  "expected_output": {
    "sql": "SELECT d.business_date, SUM(d.room_revenue) AS room_revenue FROM serving.pms.daily_revenue AS d WHERE d.business_date >= :start_date AND d.business_date < :end_date GROUP BY d.business_date ORDER BY d.business_date LIMIT 100"
  }
}
```

위 예시는 구조 설명용이다. 그대로 실제 Gold로 복사하지 말고 현재 활성 DataHub/Trino/schema/metric 계약에서 다시 작성하고 실행 검증해야 한다.

### 4.2 Compiled chat record

검증된 full spec은 다음 chat message로 compile한다.

```json
{
  "messages": [
    {
      "role": "system",
      "content": "<VERSIONED_NODE2_SYSTEM_PROMPT>"
    },
    {
      "role": "user",
      "content": "<STABLE_JSON_OF_NODE2_REQUEST>"
    },
    {
      "role": "assistant",
      "content": "{\"sql\":\"SELECT ... LIMIT 100\"}"
    }
  ]
}
```

학습 loss는 assistant message에만 적용한다. system과 user token은 `-100`으로 masking한다.

### 4.3 학습데이터에 넣지 않는 것

- 원본 사용자 대화 전체
- Node1이 해결하지 못한 모호한 요청
- 실제 사용자 parameter 값
- 고객 이름, 이메일, 전화번호 등 개인정보
- 실행 결과 row 전체
- Chain-of-Thought 또는 `<think>` 내용
- 승인되지 않은 asset을 사용한 성공 SQL
- 정규식이나 질문 키워드로 특정 정답 SQL을 재생하는 힌트
- 실제 실행하지 않은 SQL의 `trino_status=PASS`
- 과거 adapter가 생성한 SQL을 검증 없이 Gold로 승격한 데이터

실제 row data는 모델 학습 입력이 아니라 Gold SQL과 모델 SQL의 결과 일치 검증을 위한 격리된 Trino snapshot에서만 사용한다.

---

## 5. 데이터 규모와 고정 구성

시간이 제한되어 있으므로 여러 데이터 규모를 실험하지 않는다. 첫 2B release의 목표를 다음으로 고정한다.

### 5.1 Split별 목표 수

| Split | 목표 수 | 사용 목적 |
|---|---:|---|
| Train | 3,000 | LoRA 학습 |
| Validation | 300 | epoch checkpoint 선택과 오류 분석 |
| Gold | 150 | 학습·prompt 조정이 끝난 뒤 1회 모델 평가 |
| Acceptance | 100 | 실제 Backend→G2→Trino 제품 승인 |
| 합계 | 3,550 | 전체 검증 case spec |

데이터 수보다 구조적 coverage와 실행 검증이 우선이다. 구조 coverage가 부족한 상태에서 paraphrase만 늘려 3,000건을 맞추지 않는다.

### 5.2 Train 3,000건의 구성

| 구분 | 목표 수 | 설명 |
|---|---:|---|
| 실제 Node2 서비스 구조 | 1,200 | 현재 PMS/POS/CRM/연회/시설 등 승인된 runtime 계약 기반 |
| identifier/schema skin | 900 | 동일 구조를 다른 catalog/schema/table/column/metric/parameter 이름으로 변환 |
| 복합 구조 | 500 | 다중 asset, 조인, preaggregation, ratio, 비교 기간, 복합 filter |
| Node2 Repair | 400 | 실제 G2 위반 유형을 현재 계약으로 수정하는 사례 |

Node2 일반 생성 2,600건과 Repair 400건을 하나의 adapter에 섞는다. system prompt와 response schema가 노드 역할을 구분한다.

### 5.3 필수 구조 coverage

학습데이터에는 현재 계약이 지원하는 다음 구조를 모두 포함한다.

#### 집계

- 단일 measure `sum`
- `count`
- `count_distinct`
- `avg`
- `min`, `max`
- `exists`
- numerator/denominator가 명시된 `ratio`
- 다중 metric의 동일 grain projection

#### 시간

- `date`
- `timestamp`
- `timestamp with time zone`
- `[start,end)` half-open interval
- 일/주/월 등 현재 `time_rules`가 허용하는 bucket
- primary period
- comparison period
- timezone preserve/normalize 등 현재 계약이 열어 둔 mode

#### Filter와 parameter

- 현재 JSON contract가 열어 둔 모든 filter operator
- metric의 required filter
- 사용자 filter와 required filter의 동시 적용
- 같은 column에 대한 복수 조건
- string/integer/decimal/date/timestamp 등 현재 parameter type
- placeholder exact set
- SQL literal 대신 named placeholder 사용

#### Asset와 join

- 단일 asset
- 두 asset join
- 세 asset 이상 연결
- 모든 승인 cardinality 형태
- temporal join
- 서로 다른 grain에서 preaggregation이 필요한 join
- 같은 이름의 column이 여러 asset에 존재하는 경우
- join 가능한 asset과 불필요한 distractor asset이 함께 들어오는 경우

#### 정책과 보안

- LIMIT 필수
- 허용 함수만 사용
- 허용 catalog만 사용
- 질문에 미승인 table 이름이 포함된 경우에도 사용하지 않음
- metadata description에 명령형/prompt injection 문자열이 섞인 경우
- parameter 값을 질문에서 SQL literal로 복사하지 않음

#### 현재 명시적으로 지원하지 않는 조합

현재 prompt/guard가 차단하는 조합은 성공 Gold로 만들지 않는다. 예:

- `ratio`와 comparison window의 동시 사용
- `exists`와 comparison window의 동시 사용
- runtime `join_graph`에 없는 관계
- 다른 grain을 preaggregation 없이 직접 join
- 계약에 없는 function/aggregation

지원 범위를 늘리려면 먼저 계약과 Guard를 변경하고 별도의 schema version으로 학습해야 한다.

---

## 6. 스키마 변경과 다른 데이터 소스 일반화 전략

### 6.1 일반화 목표

이 프로젝트에서 말하는 스키마 일반화는 다음 의미다.

> Trino dialect와 Node2의 6개 runtime contract 형식이 유지되는 한, 학습에서 보지 못한 catalog/schema/table/column 이름이라도 현재 요청의 계약을 읽고 SQL을 구성한다.

다음을 의미하지 않는다.

- metric definition이 없어도 업무 의미를 추측한다.
- join graph가 없어도 이름이 비슷한 column을 자동 join한다.
- 다른 SQL dialect를 자동 생성한다.
- 입력 JSON contract가 바뀌어도 자동 호환한다.

### 6.2 모델이 암기해야 할 것과 runtime으로 받아야 할 것

| 모델 가중치에 학습 | runtime Context로 전달 |
|---|---|
| 입력·출력 JSON 계약 준수 | 실제 catalog/schema/table/FQN |
| metric rule을 SQL expression으로 변환하는 방법 | 현재 metric source와 aggregation |
| join graph를 따라가는 방법 | 현재 승인 join edge |
| grain/preaggregation 처리 방법 | 현재 asset grain |
| half-open time filter 구성 | 현재 time field와 parameter 이름 |
| named placeholder 사용 | 실제 typed parameter 값은 서버가 보유 |
| Trino SQL 패턴 | 허용 function/catalog/LIMIT |
| Repair 시 invalid subtree를 교체하는 방법 | 현재 G2 error code와 repair hint |

### 6.3 Identifier/schema skin

실제 서비스 case만 학습하면 모델이 `room_revenue`, `booking_date`, `pms` 같은 이름을 의미와 결합해 암기할 수 있다. 이를 막기 위해 동일한 구조에 여러 identifier skin을 적용한다.

예:

```text
원본
serving.pms.daily_revenue.room_revenue
metric_id = room_revenue
parameter = start_date/end_date

skin A
quartz.semantic.fact_observations.amount
metric_id = quartz_measure
parameter = quartz_window_start/quartz_window_end

skin B
ember.analytics.event_rollup.value_decimal
metric_id = ember_value
parameter = ember_from/ember_until
```

변경 시 다음을 모두 일관되게 바꾼다.

- DataHub URN
- catalog/schema/table FQN
- column
- table alias
- metric ID와 result field
- join ID
- parameter 이름
- query policy의 allowed catalog
- SQL AST의 identifier와 placeholder

다음은 바꾸지 않는다.

- column type
- grain 구조
- join topology/cardinality
- metric aggregation 의미
- time interval 의미
- required filter 의미
- 예상 result의 논리

### 6.4 Schema skin 생성 정책

현재 `src/ai/training/README.md`는 사람이 작성·검토한 full spec만 학습 입력으로 허용하고 자동 정답 생성을 금지한다. 이 원칙은 유지한다.

시간 절약을 위해 schema skin을 도구로 만들 경우에도 다음 조건을 모두 지켜야 한다.

1. 사람이 작성하고 승인한 canonical case만 입력으로 사용한다.
2. 자연어 LLM이 SQL을 새로 작성하지 않는다.
3. SQLGlot AST transform으로 식별자만 결정적으로 변경한다.
4. 계약의 모든 참조를 같은 mapping으로 변경한다.
5. 변환 결과를 JSON Schema와 SQL AST로 재검증한다.
6. skin별 격리 schema 또는 동등한 fixture에서 Trino 실행 검증한다.
7. result hash가 기대한 변환 관계를 만족해야 한다.
8. base canonical case ID와 transformation manifest를 보존한다.
9. 자동 검증이 완전하지 않으면 `APPROVED`로 올리지 않는다.

이 조건을 구현할 시간이 없다면 schema skin을 자동 생성하지 말고 사람이 작성·검토한다. 검증되지 않은 자동 증강보다 적은 수의 정확한 case가 낫다.

### 6.5 Split 누출 방지

random row split은 금지한다. 다음 단위를 하나의 그룹으로 묶어 같은 split에 둔다.

- canonical case와 그 paraphrase
- canonical case와 identifier skin
- 동일 SQL AST structural signature
- 동일 join topology
- 동일 metric composition
- 동일 time/comparison pattern

Validation/Gold에는 최소한 다음 holdout을 둔다.

- train에 없는 FQN/column/metric/parameter family
- train에 없는 질문 paraphrase group
- 일부 train에 없는 join topology 또는 metric composition
- 긴 context p95/p99 사례

현재 `build_validation_v2`가 사용하는 identifier-free structural signature를 유지하고, 실제 split manifest를 저장한다.

---

## 7. Gold SQL 작성과 검증

### 7.1 Gold 작성 원칙

Gold SQL은 다음 순서로 만든다.

1. 활성 runtime contract에서 metric, asset, join, time, parameter, policy를 읽는다.
2. SQL 작성자가 canonical Trino SQL을 작성한다.
3. SQLGlot으로 parse하고 canonicalize한다.
4. G2와 동일한 semantic guard를 통과시킨다.
5. 고정된 Trino data release에서 실행한다.
6. 결과를 정규화한다.
7. normalized result의 SHA-256을 저장한다.
8. reviewer가 질문·계약·SQL·결과를 함께 승인한다.

### 7.2 Teacher LLM 사용 제한

외부 LLM은 다음 용도로만 사용할 수 있다.

- 질문 paraphrase 후보 작성
- 누락된 coverage 후보 목록 제안
- 사람이 작성한 SQL의 설명 초안

다음 용도로 사용하지 않는다.

- 실행 검증 없는 Gold SQL 생성
- 없는 metric/join/time rule 보충
- 승인 상태 자동 부여
- SQL 실행 결과 추측
- 실제 schema description을 모델의 상식으로 대체

### 7.3 결과 정규화

SQL exact string match는 주 평가 지표가 아니다. 동일 결과를 만드는 SQL은 여러 개일 수 있다.

결과 비교 전에 다음을 고정한다.

- column 순서
- row ordering이 의미 있는지 여부
- unordered 결과의 deterministic sort key
- decimal scale과 tolerance
- floating tolerance
- date/timestamp timezone representation
- NULL 표현
- duplicate row 의미
- empty result schema

Primary metric은 `RESULT_MATCH`다. SQL exact match와 AST shape match는 진단 지표로만 사용한다.

---

## 8. 데이터 품질 Gate

한 건이라도 다음 조건을 만족하지 않으면 학습 dataset으로 compile하지 않는다.

### 8.1 계약 검증

- full spec 필드가 정확하다.
- `node2_request` 또는 `node2_repair_request` JSON Schema를 통과한다.
- expected output이 새 response schema를 통과한다.
- unknown additional property가 없다.
- metric ID 집합이 `metric_rules`와 일치한다.
- dimension/filter field가 승인 schema에 존재한다.
- parameter placeholder 집합이 `parameter_contract`와 정확히 일치한다.

### 8.2 SQL 검증

- SQLGlot Trino parse 성공
- 단일 statement
- read-only SELECT
- LIMIT 존재 및 정책 범위 내
- physical table이 승인 asset의 부분집합
- column이 해당 asset에 존재
- function이 whitelist 안에 존재
- metric expression이 metric rule과 일치
- required filter 누락 없음
- half-open time condition 정확
- join edge와 predicate가 join graph와 일치
- grain/preaggregation 규칙 통과

### 8.3 실행 증거

- `trino_status=PASS`
- 실제 Trino query ID 또는 검증 run ID 보관
- 동일 data release와 seed version 사용
- normalized result hash 존재
- timeout/OOM/permission failure를 PASS로 기록하지 않음

### 8.4 데이터 위생

- 이메일·전화번호 등 PII 패턴 없음
- secret/token/password 없음
- 실제 parameter 값 없음
- train/validation/gold/acceptance 누출 없음
- case ID 중복 없음
- 동일 input에 서로 다른 Gold 없음
- assistant answer에 reasoning/Markdown 없음

---

## 9. Qwen3.5-2B 단일 학습 전략

여러 rank, learning rate, seed, epoch를 비교하지 않는다. 아래 설정으로 한 번 학습하고 epoch checkpoint만 Validation으로 선택한다.

### 9.1 고정 설정

| 항목 | 설정 |
|---|---|
| Base model | `Qwen/Qwen3.5-2B` |
| Revision | Hugging Face commit SHA로 고정. `main` 금지 |
| Model type | post-trained model, Base checkpoint로 교체하지 않음 |
| Thinking | `false` |
| Training | BF16 LoRA |
| Quantization | 학습 시 사용하지 않음 |
| LoRA target | `all-linear` |
| Rank | 16 |
| Alpha | 32 |
| Dropout | 0.05 |
| Bias | `none` |
| Learning rate | `1e-4` |
| Epochs | 2 |
| Per-device batch | 1 |
| Gradient accumulation | 32, 단일 GPU 기준 effective batch 32 |
| Scheduler | cosine |
| Warmup | 0.03 |
| Weight decay | 0.01 |
| Gradient clipping | 1.0 |
| Precision | BF16, TF32 허용 GPU에서 TF32 |
| Gradient checkpointing | 사용 |
| Sequence packing | 첫 release에서는 사용하지 않음 |
| Loss | assistant-only |
| Seed | release seed 하나로 고정 |
| Save/eval | epoch마다 저장·Validation |

PEFT는 아키텍처마다 projection 이름이 다른 문제를 피하기 위해 `target_modules="all-linear"`를 지원한다.

공식 참고:

- <https://github.com/huggingface/peft/blob/main/docs/source/developer_guides/lora.md>

### 9.2 왜 기존 target module 목록을 그대로 쓰지 않는가

현재 `train_lora.py`는 다음 전통적인 projection 이름을 지정한다.

```text
q_proj, k_proj, v_proj, o_proj,
gate_proj, up_proj, down_proj
```

Qwen3.5는 full attention과 linear attention이 섞인 hybrid 구조이므로 기존 목록만으로는 모델의 일부 linear projection이 빠질 수 있다. 한 번만 학습한다면 특정 이름을 추측하는 것보다 `all-linear`를 적용하고 실제 `targeted_module_names`를 manifest에 저장하는 것이 안전하다.

단, full training 전에 다음을 반드시 확인한다.

- LoRA가 `lm_head`에 의도치 않게 적용되지 않았다.
- 적용된 module 이름 목록이 비어 있지 않다.
- trainable parameter 비율이 비정상적으로 크거나 작지 않다.
- 저장한 adapter를 PEFT와 vLLM이 모두 읽을 수 있다.

### 9.3 Context 길이 통일

현재 학습 기본 길이 12,288과 Qwen runtime 5,120은 일치하지 않는다. 새 2B release에서는 다음 기준으로 통일한다.

- training `max_length=8192`
- vLLM `max_model_len=8192`
- Node2 output budget 기본 1,024
- safety margin 256
- 실제 사용 가능한 입력 budget 약 6,912 tokens

최종 output budget은 전체 Gold SQL을 tokenizer로 측정한 뒤 결정한다.

```text
output_budget >= max(gold_assistant_tokens) × 1.10
```

1,024를 초과해야 한다면 실제 max를 근거로 manifest를 변경한다. 반대로 근거 없이 1,280이나 그 이상을 유지하지 않는다.

어떤 학습 record도 조용히 truncate하지 않는다. 8,192를 넘으면 다음 순서로 해결한다.

1. Context Builder가 불필요한 distractor asset을 제거한다.
2. JSON key/description의 불필요한 중복을 제거한다.
3. required contract는 유지한다.
4. 그래도 초과하면 case를 실패 처리하고 계약 설계를 검토한다.

### 9.4 기존 학습 스크립트에서 바꿀 값

`src/ai/training/train_lora.py`의 최소 변경 기준:

```python
DEFAULT_MODEL = "Qwen/Qwen3.5-2B"

LoraConfig(
    task_type="CAUSAL_LM",
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    target_modules="all-linear",
)
```

CLI 기본값:

```text
max_length=8192
epochs=2
learning_rate=1e-4
gradient_accumulation=32
lora_rank=16
lora_alpha=32
```

현재 스크립트는 실제로 base model을 4-bit로 load하지 않으므로 BF16 LoRA다. docstring이나 설명에 `QLoRA`라고 적혀 있어도 quantization 설정이 없다면 QLoRA라고 보고하지 않는다.

### 9.5 Dependency 고정

Qwen3.5를 지원하는 다음 dependency를 smoke에서 확인한 뒤 정확한 버전과 image digest를 manifest에 기록한다.

- Python
- CUDA
- PyTorch
- Transformers
- PEFT
- Accelerate
- SQLGlot
- vLLM
- tokenizer files hash

`latest`라는 문자열만 기록하지 않는다. Qwen3.5 공식 모델 카드가 최신 구현을 요구하더라도, 성공한 실행의 정확한 package version과 container digest를 release 근거로 고정한다.

---

## 10. 전체 학습 실행 절차

아래 경로는 RunPod/Linux 예시다. 실제 경로는 workspace mount에 맞게 변경하되 dataset과 output을 Git 저장소 내부에 넣지 않는다.

### 10.1 환경 변수 예시

```bash
export REPO_ROOT=/workspace/skn29_final_3team
export REVIEWED_DATA=/workspace/model-data/reviewed/full_specs.qwen35-2b.v1.jsonl
export SELECTED_DATA=/workspace/model-data/selected/train_validation.qwen35-2b.v1.jsonl
export COMPILED_DATA=/workspace/model-data/compiled/node2.qwen35-2b.v1.jsonl
export ADAPTER_DIR=/workspace/model-artifacts/node2-qwen35-2b-lora-r16-v1
export MODEL_REVISION=<PINNED_QWEN35_2B_COMMIT_SHA>
```

### 10.2 계약·데이터 검증

```bash
cd "$REPO_ROOT"

python -m src.ai.training.dataset validate "$REVIEWED_DATA"

python -m src.ai.training.build_case_specs \
  "$REVIEWED_DATA" \
  "$SELECTED_DATA" \
  --split train \
  --split validation \
  --review-status APPROVED

python -m src.ai.training.dataset build \
  "$SELECTED_DATA" \
  "$COMPILED_DATA"
```

### 10.3 Validation ID/OOD manifest

```bash
python -m src.ai.training.build_validation_v2 \
  "$REVIEWED_DATA" \
  /workspace/model-data/selected/validation.qwen35-2b.v1.jsonl \
  /workspace/model-data/selected/validation.qwen35-2b.v1.manifest.json \
  --limit-per-slice 100
```

manifest에서 다음을 확인한다.

- train/validation 구조 signature 누출 없음
- ID와 OOD case가 모두 존재
- unseen identifier family 존재
- repair case 존재
- long-context slice 존재

### 10.4 Full training 전 smoke

Full training과 같은 container/GPU/model revision/dataset으로 다음만 실행한다.

1. model/tokenizer load
2. compiled record 2건 tokenize
3. 8,192 초과 시 즉시 실패
4. LoRA injection 후 `targeted_module_names` 기록
5. 한 batch forward/backward
6. adapter 임시 저장·재로드
7. vLLM adapter load 및 guided JSON 한 건 생성

smoke는 hyperparameter 실험이 아니다. 모듈 불일치, OOM, tokenizer/chat-template 불일치, adapter 서빙 불가를 full training 전에 차단하는 검증이다.

### 10.5 Full training

계약 변경이 반영된 `train_lora.py` 기준:

```bash
python -m src.ai.training.train_lora \
  --data "$COMPILED_DATA" \
  --output-dir "$ADAPTER_DIR" \
  --model Qwen/Qwen3.5-2B \
  --revision "$MODEL_REVISION" \
  --max-length 8192 \
  --epochs 2 \
  --learning-rate 1e-4 \
  --gradient-accumulation 32 \
  --lora-rank 16 \
  --lora-alpha 32
```

### 10.6 학습 완료 산출물

adapter 디렉터리에 최소한 다음이 있어야 한다.

- `adapter_config.json`
- adapter weights (`safetensors`)
- tokenizer/config files 또는 정확한 tokenizer source reference
- `training_manifest.json`
- dataset SHA-256
- base model requested/resolved revision
- prompt/schema hash
- train/validation case 수
- seed
- max length
- LoRA target module 실제 목록
- LoRA rank/alpha/dropout
- dependency version
- training metrics
- epoch checkpoint 식별자

대용량 base model weight는 adapter 산출물에 복제하지 않는다.

---

## 11. 학습 중 확인 사항

여러 설정을 비교하지 않더라도 다음은 모니터링한다.

- train loss가 NaN/Inf가 아닌가.
- validation loss가 비정상적으로 상승하지 않는가.
- 모든 batch에서 assistant trainable token이 존재하는가.
- OOM/restart/resume이 발생했는가.
- 입력 truncation이 발생하지 않았는가.
- epoch별 checkpoint가 정상 저장되는가.
- adapter reload가 가능한가.

Validation loss만으로 제품 checkpoint를 선택하지 않는다. 두 epoch checkpoint를 동일 Validation set에서 생성시켜 다음 순서로 선택한다.

1. response schema valid rate
2. G2 pass rate
3. RESULT_MATCH
4. context violation 수
5. latency/output token
6. 동률일 때 validation loss

이는 별도 hyperparameter 실험이 아니라 한 번의 training run에서 생성된 checkpoint 선택이다.

---

## 12. 평가 설계

### 12.1 Oracle-Context Node2 평가

Node2 모델 자체를 평가하기 위해 정답 `resolved_request`와 정답 6개 runtime contract를 제공한다.

이 평가는 다음을 분리한다.

- Node1 오류
- Context Builder 검색/권한 오류
- Node2 SQL 생성 오류

Oracle-Context가 실패하면 Node2 또는 학습데이터 문제다. Oracle-Context는 성공하지만 제품 E2E가 실패하면 Node1/Context/Backend 문제일 수 있다.

### 12.2 End-to-End Acceptance 평가

실제 제품 경로로 실행한다.

```text
질문
→ Node1
→ Context Builder/DataHub
→ Node2 Qwen3.5-2B
→ G2 SQLGlot
→ parameter binding
→ Trino
→ 결과 정규화
→ Gold result 비교
```

### 12.3 필수 지표

| 지표 | 설명 | 중요도 |
|---|---|---|
| Response schema valid | guided JSON을 포함한 최종 JSON 계약 통과 | 필수 |
| SQL parse valid | SQLGlot Trino parse | 필수 |
| G2 pass | 정책·asset·column·metric·join·time·parameter 전체 통과 | 필수 |
| RESULT_MATCH | Gold와 정규화된 실행 결과 일치 | Primary |
| Context violation | 승인되지 않은 identifier/function/parameter 사용 | 안전성 |
| Repair recovery | 최초 실패 후 1회 Repair 성공 | 보조 |
| SQL exact match | 문자열/AST 차이 진단 | 진단 전용 |
| p50/p95 latency | warm endpoint 응답 시간 | 운영 |
| output tokens | 비정상 장문/loop 감지 | 운영 |
| OOM/timeout | 안정성 | 운영 |

### 12.4 2B 승인 Gate

#### Hard Gate

- 승인되지 않은 SQL이 실행된 건수: **0**
- read-only 이외 statement 실행: **0**
- parameter literal 유출: **0**
- guided JSON parse: **100%**
- P0 Acceptance 100건 RESULT_MATCH: **100%**
- G2 negative/security case의 실행 차단: **100%**
- Thinking loop/무한 출력: **0**

#### Quality Gate

- Validation 전체 RESULT_MATCH: **95% 이상**
- unseen identifier/schema slice RESULT_MATCH: **90% 이상**
- 복합 join/time/ratio slice: **사전에 정의한 case별 P0 기준 충족**
- Repair 대상 중 수정 가능한 case의 recovery: **90% 이상**

#### Operations Gate

- 제품이 정한 warm p95 latency 이내
- 동시 요청 2개에서 OOM/timeout 없음
- adapter reload 후 결과 재현
- exact model/prompt/schema/data/policy release 추적 가능

수치가 프로젝트 최종 SLA와 다르면 학습 전에 변경하고 manifest에 기록한다. 결과를 본 뒤 기준을 낮추지 않는다.

---

## 13. 오류 분류와 수정 책임

평가 실패를 모두 모델 오류로 분류하지 않는다.

| 실패 유형 | 예 | 수정 책임 |
|---|---|---|
| Node1 Error | 잘못된 metric/기간/필터 해석 | Node1/질문 해석 |
| Context Error | 필요한 asset/metric/join 누락 | Context Builder/DataHub |
| Contract Error | metric rule 자체가 틀림 | Governance/계약 |
| Gold Data Error | Gold SQL/result hash 오류 | Dataset |
| Model Syntax Error | JSON/SQL parse 실패 | Node2 학습/prompt |
| Model Semantic Error | 잘못된 metric expression/join/time | Node2 데이터/모델 |
| Guard Error | 올바른 SQL을 잘못 차단 또는 위험 SQL 허용 | SQL Guard |
| Binding Error | placeholder/type 불일치 | parameter contract/Backend |
| Runtime Error | Trino permission/timeout/catalog drift | Data platform/운영 |
| Capacity Error | 정확한 context를 줘도 복합 구조가 반복 실패 | 2B 모델 용량 후보 |

4B 승격은 마지막 `Capacity Error`가 반복되고 나머지 오류가 제거된 경우에만 검토한다.

---

## 14. vLLM 서빙

### 14.1 원칙

- 정확한 base revision과 container digest를 고정한다.
- Node2는 text-only이므로 language-model-only 경로를 사용한다.
- LoRA adapter는 서버 시작 시 preload한다.
- runtime dynamic LoRA loading은 사용하지 않는다.
- `max_lora_rank=16`으로 실제 adapter rank와 맞춘다.
- `max_model_len=8192`로 학습과 맞춘다.
- Non-thinking만 사용한다.
- MTP/speculative decoding은 첫 release에서 끈다.
- model alias는 제품 route와 분리된 versioned 이름을 사용한다.

vLLM LoRA 공식 참고:

- <https://docs.vllm.ai/en/stable/features/lora/>

### 14.2 예시 명령

실제 설치된 vLLM version에서 option 이름을 `vllm serve --help`로 확인한 뒤 사용한다.

```bash
vllm serve Qwen/Qwen3.5-2B \
  --revision "$MODEL_REVISION" \
  --served-model-name answervice-node2-qwen35-2b-v1 \
  --language-model-only \
  --enable-lora \
  --lora-modules node2="$ADAPTER_DIR" \
  --max-lora-rank 16 \
  --max-model-len 8192 \
  --dtype bfloat16 \
  --generation-config vllm
```

GPU memory utilization, tensor parallel, concurrency 값은 실제 GPU와 배포 방식의 smoke 결과로 manifest에 고정한다. 근거 없이 다른 환경의 값을 복사하지 않는다.

### 14.3 Backend 요청 설정

Node2 일반 생성:

```json
{
  "model": "answervice-node2-qwen35-2b-v1",
  "temperature": 0,
  "max_tokens": 1024,
  "chat_template_kwargs": {
    "enable_thinking": false
  },
  "guided_json": {
    "type": "object",
    "additionalProperties": false,
    "required": ["sql"],
    "properties": {
      "sql": {"type": "string", "minLength": 1}
    }
  }
}
```

Repair는 같은 adapter를 사용하되 Repair prompt와 `corrected_sql` guided schema를 사용한다.

---

## 15. Release manifest

다음 항목이 하나라도 없으면 제품 release로 승격하지 않는다.

### Model

- base model ID
- requested revision
- resolved revision
- tokenizer hash/chat template hash
- language-model-only 여부
- Thinking false

### Adapter

- adapter artifact SHA-256
- PEFT config
- actual target module list
- rank/alpha/dropout
- trainable parameter count

### Dataset

- full spec SHA-256
- compiled dataset SHA-256
- train/validation/gold/acceptance count
- split manifest SHA-256
- scenario/structural coverage
- Trino data release/seed version

### Contract

- Node2 request schema version/hash
- Node2 response schema version/hash
- Node2 prompt version/hash
- Repair prompt version/hash
- SQL policy version/hash
- Context release/schema version

### Runtime

- Python/PyTorch/Transformers/PEFT/vLLM/SQLGlot versions
- container image digest
- max model length
- max output tokens
- GPU type
- concurrency
- endpoint model alias

### Evaluation

- checkpoint ID
- Validation/Gold/Acceptance case set hash
- RESULT_MATCH
- G2 pass/block 결과
- latency/OOM/timeout 결과
- failure taxonomy
- 승인/차단 결정

---

## 16. 배포와 Rollback

### 16.1 배포 순서

1. Offline Oracle-Context 평가
2. Offline End-to-End 평가
3. staging endpoint 배포
4. shadow mode: 사용자 결과에는 반영하지 않고 GPT/Base 경로와 비교
5. 내부 사용자 canary
6. 일부 Node2 traffic 전환
7. 전체 전환

### 16.2 Rollback 조건

다음 중 하나라도 발생하면 이전 승인 route로 즉시 복귀한다.

- context violation
- G2가 위험 SQL을 허용
- P0 RESULT_MATCH 회귀
- 반복적인 JSON/SQL parse failure
- p95 timeout 또는 OOM
- adapter/base revision 불일치
- schema/prompt/policy hash 불일치
- Trino/data release drift

2B와 4B를 요청별로 조용히 자동 fallback시키지 않는다. 모델별 오류율과 비용을 분리할 수 없기 때문이다. 4B는 별도 release 결정으로 관리한다.

---

## 17. 4B 진행 조건

다음 조건을 모두 만족한 뒤에도 2B가 실패할 때만 4B를 진행한다.

- Gold SQL과 result hash가 정확하다.
- Node1의 resolved request가 정확하다.
- Context Builder가 필요한 contract를 모두 제공한다.
- schema context가 8,192 안에 들어오도록 적절히 축소됐다.
- Node2 response schema와 guided JSON이 일치한다.
- LoRA가 Qwen3.5 hybrid linear module에 실제 적용됐다.
- Validation의 identifier/schema holdout이 올바르게 구성됐다.
- G2/parameter binding/Trino runtime 오류가 아니다.
- 2B 실패가 복합 join, temporal comparison, preaggregation 등 의미 조합에 반복적으로 집중된다.

4B로 변경하면 기존 2B adapter를 그대로 사용할 수 없다. 동일한 검증 dataset과 계약을 사용하더라도 4B base에 대해 adapter를 다시 학습하고 별도 release manifest를 만들어야 한다.

---

## 18. 담당자별 인수인계 체크리스트

### Backend/계약 담당

- [ ] Node2 response를 `sql` 하나로 변경
- [ ] AST-derived lineage 저장 확인
- [ ] prompt/schema version과 hash 갱신
- [ ] Node2/Repair guided JSON 갱신
- [ ] 2B runtime capacity profile 추가
- [ ] 관련 unit/contract test 통과

### Governance/Data 담당

- [ ] 활성 metric/asset/join/time/parameter/query policy 확정
- [ ] 학습용 고정 Trino data release 준비
- [ ] canonical case의 업무 의미 승인
- [ ] schema drift/checksum 확인
- [ ] Gold result hash 생성

### Dataset 담당

- [ ] 3,550 full spec 구성
- [ ] schema skin 변환/검증 manifest 생성
- [ ] PII/secret 검사
- [ ] structural split과 누출 검사
- [ ] 모든 train/validation record Trino PASS
- [ ] Gold/Acceptance를 학습과 prompt 수정에서 격리

### 학습 담당

- [ ] Qwen3.5-2B exact revision 고정
- [ ] dependency/container digest 고정
- [ ] `all-linear` target 실제 목록 확인
- [ ] 1-batch smoke와 adapter reload 확인
- [ ] BF16 LoRA r16 단일 학습
- [ ] epoch별 Validation 실행
- [ ] artifact/data/config hash 저장

### 평가/운영 담당

- [ ] Oracle-Context 평가
- [ ] Gold 평가
- [ ] End-to-End Acceptance 100건
- [ ] latency/concurrency/OOM/timeout 검증
- [ ] shadow/canary/rollback 준비
- [ ] release manifest와 증거 보존

---

## 19. 학습 시작 전 최종 Go/No-Go

다음 질문에 모두 `예`라고 답할 수 있을 때만 full training을 시작한다.

1. Qwen route가 사용할 Node2 출력이 `{"sql":"..."}`로 확정됐고, GPT legacy route와 분리됐는가?
2. 학습 prompt와 운영 prompt의 version/hash가 같은가?
3. train/validation 모든 SQL이 실제 Trino에서 PASS했는가?
4. Gold/Acceptance가 학습에 노출되지 않았는가?
5. schema skin이 identifier 암기를 검증할 수 있게 split됐는가?
6. 모든 sample이 8,192 tokens 안에 있고 truncation이 없는가?
7. Qwen3.5-2B exact revision과 dependency가 고정됐는가?
8. LoRA `all-linear` 실제 target 목록을 확인했는가?
9. adapter를 vLLM에서 reload하는 smoke가 성공했는가?
10. 실패 시 4B가 아니라 먼저 오류 분류를 수행하기로 합의했는가?

하나라도 아니면 full training을 시작하지 않는다. 한 번만 학습할 수 있기 때문에 사전 계약 불일치를 학습으로 보정할 수 없다.

---

## 20. Definition of Done

다음이 모두 충족돼야 “Qwen3.5-2B Node2 학습 및 서비스 적용 준비 완료”라고 보고한다.

- 새 Node2 request/response/prompt 계약이 Backend와 학습데이터에서 동일하다.
- 3,000 train 및 300 validation record가 전부 계약·SQLGlot·Trino 검증을 통과했다.
- adapter가 exact Qwen3.5-2B revision에서 재현 가능하게 로드된다.
- Non-thinking guided JSON으로 Node2와 Repair가 모두 동작한다.
- Validation, Gold, Acceptance Gate를 통과했다.
- 승인되지 않은 SQL 실행은 0건이다.
- unseen schema/identifier slice가 기준을 통과했다.
- AST-derived lineage가 결과 artifact에 보존된다.
- vLLM endpoint와 Backend route가 같은 model alias/release를 사용한다.
- rollback 대상이 존재하고 전환 절차가 검증됐다.
- 모델·adapter·dataset·prompt·schema·policy·runtime·evaluation hash가 release manifest에 연결됐다.

---

## 21. 저장소 참고 파일

| 목적 | 경로 |
|---|---|
| Node 입출력 계약 | `src/ai/contracts/node_io.v0.1.json` |
| Model release 계약 | `src/ai/contracts/model_release.v1.json` |
| Node2/Repair prompt | `src/ai/prompt_registry.py` |
| 학습/서빙 표준 입력과 guided schema | `app/backend/app/adapters/model_schemas.py` |
| runtime Context 직렬화 | `app/backend/app/adapters/model_context.py` |
| model 응답→plan 변환 | `app/backend/app/adapters/model_adapter.py` |
| Node2/G2/Repair orchestration | `app/backend/app/services/analysis/stages/plan_stage.py` |
| SQLGlot G2 guard | `app/backend/app/services/sql_guard/guard.py` |
| runtime capacity/route | `src/modelops/model_runtime_manifest.v1.json` |
| LoRA release candidate 상태 | `src/modelops/release_candidate.v1.json` |
| 학습데이터 검증·compile | `src/ai/training/dataset.py` |
| case 검증 | `src/ai/training/verify_case_specs.py` |
| LoRA 학습 | `src/ai/training/train_lora.py` |
| LoRA 평가 | `src/ai/training/evaluate_lora.py` |
| endpoint 평가 | `src/ai/training/evaluate_endpoint.py` |
| 학습 운영 설명 | `src/ai/training/README.md` |

---

## 22. 외부 공식 참고자료

- Qwen3.5-2B 모델 카드: <https://huggingface.co/Qwen/Qwen3.5-2B>
- Hugging Face PEFT LoRA 가이드: <https://github.com/huggingface/peft/blob/main/docs/source/developer_guides/lora.md>
- vLLM LoRA 서빙 가이드: <https://docs.vllm.ai/en/stable/features/lora/>
- PICARD constrained SQL decoding 연구: <https://arxiv.org/abs/2109.05093>
- BIRD text-to-SQL benchmark: <https://arxiv.org/abs/2305.03111>
- Spider 2.0 enterprise text-to-SQL benchmark: <https://arxiv.org/abs/2411.07763>

외부 자료는 설계 참고다. Answervice의 실제 승인 기준은 현재 저장소의 versioned 계약, 활성 DataHub/Trino release, 실행 결과와 이 문서의 release Gate다.
