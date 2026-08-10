# Answervice LLM 사용 현황

| 항목 | 내용 |
|---|---|
| 문서 성격 | AI 참고·구현 현황 스냅샷 |
| 기준일 | 2026-08-10 |
| 확인 기준 | 현재 `junhee` branch의 코드·설정·ModelOps manifest |
| 주의사항 | 이 문서는 공식 산출물이나 최신 계약의 단일 기준이 아니다. 실제 구현은 코드와 테스트, 일정·상태는 WBS와 Gate 원장을 우선한다. |

## 서론

Answervice는 하나의 LLM이 권한 확인부터 SQL 실행과 답변 생성까지 모두 처리하는 구조가 아니다. FastAPI Controller가 결정론적으로 전체 흐름을 통제하고, LLM은 질문 해석·SQL 생성·결과 설명처럼 제한된 역할의 Node로 사용한다.

현재 로컬 기본 환경에서는 실제 외부 LLM을 호출하지 않는다.

- Docker Compose 기본값: `MODEL_MODE=contract-fake`
- FastAPI 직접 실행 시 기본값: `MODEL_MODE=fake`
- 현재 `.env`: `MODEL_MODE`, `MODEL_ENDPOINT`, `MODEL_API_TOKEN` 미설정
- 결과: 기본 기동에서는 RunPod나 OpenAI API 호출 비용이 발생하지 않는다.

## 본론

### 1. 모델 호출 위치와 실행 모드

모델 선택은 `app/backend/app/api/router.py`의 `_model()`에서 수행한다.

| `MODEL_MODE` | Adapter | 동작 |
|---|---|---|
| `fake` | R4 `FakeModelAdapter` | 고정된 합성 SQL·설명 반환 |
| `contract-fake` | R3 계약 기반 `ContractModelAdapter` | Node 입출력 schema와 prompt metadata를 따르는 결정론적 fake 사용 |
| `openai` | `ContractModelAdapter.from_openai()` | OpenAI-compatible endpoint의 `/v1/chat/completions` 호출 |

여기서 `openai`는 OpenAI GPT 모델을 뜻하지 않고 OpenAI-compatible API 규격을 뜻한다. 실제 요청 payload의 모델명은 현재 다음 값으로 고정되어 있다.

```text
Qwen/Qwen3-4B
```

외부 모델 사용 시 환경 변수는 다음과 같다.

| 환경 변수 | 용도 |
|---|---|
| `MODEL_MODE=openai` | 실제 OpenAI-compatible transport 선택 |
| `MODEL_ENDPOINT` | vLLM 등 서빙 endpoint의 base URL |
| `MODEL_API_TOKEN` | endpoint 인증 token, 선택 사항 |
| `MODEL_TIMEOUT_SECONDS` | 모델 요청 제한 시간, 기본 15초 |

실제 요청 주소는 다음 형식이다.

```text
{MODEL_ENDPOINT}/v1/chat/completions
```

### 2. 모델별 현재 상태

| 구분 | 모델 | 현재 상태 |
|---|---|---|
| 제품 runtime transport | `Qwen/Qwen3-4B` | 실제 endpoint 요청 코드에 연결된 모델명 |
| 과거 RunPod serving 검증 | `Qwen/Qwen3-4B` Base | A40·vLLM 검증 완료 후 Pod 삭제 |
| 차기 평가 후보 | `Qwen/Qwen3-4B-Instruct-2507` | 평가 재작업 상태, 제품 runtime 미연결 |
| SQL LoRA | Instruct-2507 기반 후보 | 제품 미채택·비활성 |
| GPT API | OpenAI GPT 계열 | 현재 모델 호출 구현·설정 없음 |

RunPod 검증 manifest에는 vLLM `0.10.2`, A40, 동시 실행 2건, dynamic adapter loading 비활성, `Qwen/Qwen3-4B` Base 사용 기록이 있다. 검증 Pod는 삭제되어 현재 상시 endpoint로 동작하지 않는다.

`Qwen/Qwen3-4B-Instruct-2507`은 학습·평가 후보이며 현재 제품 runtime의 hard-coded model 값과 아직 일치하지 않는다. 현재 ModelOps 결정상 SQL LoRA가 활성화된 Node도 없다.

### 3. Node별 LLM 용도

#### 3.1 Node 1 — 질문 정규화

설계상 역할은 다음과 같다.

- intent 후보 추출
- metric·dimension 후보 추출
- 절대 기간 후보 추출
- 질문이 모호할 때 최소 재질문 생성

현재 backend 실제 요청 경로에서는 Node 1을 외부 LLM으로 호출하지 않는다. Router와 metric 선택 로직이 결정론적으로 처리하며, `src/ai/node1.py`도 deterministic baseline이다.

따라서 “설계상 Node 1 LLM”과 “현재 runtime 구현”을 구분해야 한다.

#### 3.2 Node 2 — Text-to-SQL

Node 2는 다음 정보를 입력받는다.

- 정규화된 질문
- 승인된 asset URN과 Trino FQN
- 사용할 수 있는 column
- metric의 field·aggregation·time field
- 필수 filter
- 승인된 JOIN
- 기준 시각과 timezone

Node 2의 출력은 Trino용 read-only `SELECT` SQL 후보이다. 이 SQL은 모델 응답만으로 실행되지 않고 G2 검사를 통과해야 한다.

G2 주요 검사 범위:

- 승인되지 않은 table·column 사용
- JOIN 계약 위반
- `SELECT` 이외 문장
- `LIMIT` 정책
- 기간·필터 계약
- Trino 문법과 실행 정책

#### 3.3 Node 2′ — SQL 한 번 수정

G2가 수정 가능한 오류를 반환한 경우 Controller가 한 번만 호출한다.

수정 범위 예시:

- `LIMIT` 누락 또는 1000 초과
- 승인되지 않은 table 참조
- 정규화된 SQL 정책 오류

Node 2′는 자유로운 반복 실행이나 ReAct loop를 수행하지 않는다. 두 번째 수정 호출은 허용하지 않는다.

#### 3.4 Node 3 — 검증 결과 설명

Node 3는 Trino 실행 결과가 G3를 통과한 뒤에만 호출한다.

입력:

- G3를 통과한 shaped result
- metric
- 기간·필터·단위
- source URN
- sampling·masking·partial 여부
- query 실행 식별자

출력:

- 사용자에게 표시할 근거 기반 요약 설명

Node 3는 SQL을 생성하거나 결과 수치를 재계산하지 않으며, 인과관계를 임의로 단정하지 않는다. Node 2의 추론 과정도 전달받지 않는다.

### 4. Prompt Registry

프롬프트는 `src/ai/prompt_registry.py`에서 version과 SHA-256 hash를 포함해 관리한다.

| Prompt ID | 버전 | 핵심 지시 |
|---|---|---|
| `node1.normalize` | `PROMPT-v1.0.0` | intent·metric·dimension·기간과 최소 재질문만 추출 |
| `node2.sql` | `PROMPT-v1.0.9-DRAFT` | 승인 Context 안에서 Trino SQL 한 줄만 생성 |
| `node2.repair` | `PROMPT-v1.0.3` | 거절 SQL에서 허용된 오류만 한 번 수정 |
| `node3.explain` | `PROMPT-v1.0.0` | 검증된 결과의 조건·기간·단위·출처·한계만 설명 |

#### 4.1 Node 1 prompt 핵심

```text
질문에서 intent, metric, dimension, 절대 기간 후보와 최소 재질문만 추출한다.
자산·권한·Gate·SQL을 결정하지 않는다.
```

#### 4.2 Node 2 prompt 핵심

- 설명이나 Markdown 없이 `{"sql":"한 줄 SQL"}` JSON만 반환
- 승인 Context Package의 asset·column·metric·JOIN만 사용
- 세미콜론 없는 단일 read-only Trino `SELECT`
- `LIMIT`은 1~1000이며 누락 금지
- `CURRENT_DATE`, `CURRENT_TIMESTAMP`, `now()` 사용 금지
- Context의 절대 실행 시각 사용
- `property_id`, `data_period_status`, `is_forecast` 등 필수 filter 적용
- metric의 `field`, `aggregation`, `time_field`, `required_filters` 준수
- 승인되지 않은 table·column·JOIN 단축 경로 생성 금지
- SQL 실행과 정책 통과 여부를 모델이 판정하지 않음

#### 4.3 Node 2′ prompt 핵심

```text
{"corrected_sql":"한 줄 SQL"}만 반환한다.
동일 Context에서 rejected_sql의 정규화 오류 코드에 해당하는 항목만 한 번 수정한다.
```

#### 4.4 Node 3 prompt 핵심

```text
G3 pass shaped result의 조건·기간·단위·출처·제한만 설명한다.
수치를 재계산하거나 원인을 단정하지 않는다.
```

### 5. 실제 모델 요청 구조

외부 endpoint를 사용할 때 요청 구조는 다음과 같다.

```json
{
  "model": "Qwen/Qwen3-4B",
  "messages": [
    {
      "role": "system",
      "content": "Prompt Registry에 등록된 Node별 프롬프트"
    },
    {
      "role": "user",
      "content": "질문과 Context Package를 포함한 JSON"
    }
  ],
  "temperature": 0,
  "max_tokens": 1500,
  "chat_template_kwargs": {
    "enable_thinking": false
  },
  "guided_json": {
    "type": "object"
  }
}
```

주요 특징:

- non-thinking 모드
- `temperature=0`
- Node별 JSON Schema로 출력 형식 제한
- model output을 다시 JSON·schema 검증
- timeout, HTTP 오류, 잘못된 JSON, schema 불일치, circuit open을 정상 결과로 저장하지 않음
- production fallback 결과를 제품 성공이나 Artifact로 승격하지 않음

### 6. 전체 처리 흐름

```text
사용자 질문
  → Router·metric 선택 및 Context Package 구성
  → G1 권한·Context 검사
  → Template 또는 SQL Plan Cache 확인
  → 필요할 때 Node 2 SQL 생성
  → G2 SQL 정책·참조·문법 검사
  → 수정 가능한 오류면 Node 2′ 한 번 호출
  → Trino read-only 실행
  → Result Shaper
  → G3 결과 충분성·근거 검사
  → Node 3 근거 기반 설명
  → Artifact 저장 및 frontend 응답
```

LLM은 다음 항목을 담당하지 않는다.

- 사용자 인증과 권한 판정
- DataHub asset 승인
- G1·G2·G3 통과 판정
- SQL 직접 실행
- 결과 수치 재계산
- Report 승인과 배포

## 결론

현재 Answervice의 기본 로컬 실행은 fake 모델을 사용하며 외부 LLM 비용이 발생하지 않는다. 실제 모델 모드를 활성화하면 OpenAI-compatible RunPod vLLM endpoint의 `Qwen/Qwen3-4B`를 Node 2 SQL 생성, Node 2′ 1회 수정, Node 3 결과 설명에 사용하도록 구현되어 있다.

현재 구현 상태에서 유의할 점은 다음과 같다.

1. Node 1은 설계상 LLM 역할이지만 실제 backend에서는 결정론적으로 처리한다.
2. `Qwen/Qwen3-4B-Instruct-2507`은 차기 후보이며 runtime 모델명에 아직 반영되지 않았다.
3. SQL LoRA는 제품에 채택되거나 활성화되지 않았다.
4. OpenAI GPT API를 직접 사용하는 구현은 없다.
5. 활성 RunPod endpoint가 없으므로 현재 상시 외부 모델 호출도 없다.

## 확인한 주요 파일

- `app/backend/app/api/router.py`
- `app/backend/app/adapters/contract_model.py`
- `app/backend/app/services/analysis_service.py`
- `src/ai/node1.py`
- `src/ai/node2.py`
- `src/ai/node3.py`
- `src/ai/prompt_registry.py`
- `src/modelops/serving_manifest.v0.1.json`
- `src/modelops/model_candidate.instruct2507.v0.1.json`
- `src/modelops/model_decision.v0.1.json`
