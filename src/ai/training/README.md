# Answervice SQL LoRA 학습 실행 가이드

이 폴더는 `Qwen/Qwen3-4B-Instruct-2507` Base를 먼저 평가하고, 필요한 경우에만 Node 2·2′용 SQL LoRA를 학습하기 위한 최소 실행 패키지다. 이전 `Qwen/Qwen3-4B` adapter는 새 checkpoint와 호환성이 검증되지 않았으므로 재사용하지 않는다.

## 1. 파일 역할

| 파일 | 역할 |
|---|---|
| `case_specs.example.jsonl` | 사람이 작성하는 정답 사례 템플릿 |
| `dataset.py` | 사례 검사 및 Qwen 대화형 학습데이터 변환 |
| `train_lora.py` | RunPod A40 단일 GPU BF16 LoRA 학습 |
| `evaluate_lora.py` | Validation·Gold·Acceptance 생성 결과의 JSON·SQL 일치율 확인 |
| `requirements.txt` | RunPod에 추가 설치할 Python 패키지 |

예제 데이터는 형식 설명용이며 `trino_status=NOT_RUN`이다. 실제 학습에는 사용할 수 없다.

## 2. 학습데이터가 만들어지는 과정

### 2.1 정답 사례 하나를 먼저 만든다

질문을 무작정 생성하지 않는다. 먼저 DB 계약으로 실행 가능한 정답 SQL을 만든다.

```text
승인된 DDL·지표·JOIN 확인
→ 서로 다른 SQL 문제 하나 설계
→ SQL에 필요한 Context Package 작성
→ 정답 SQL 작성
→ 질문을 SQL 의미에 맞게 작성
→ G1·G2를 거쳐 Trino 실행
→ 실행 결과 SHA-256 기록
```

한 줄이 학습 사례 한 건이다. 주요 필드는 다음과 같다.

| 필드 | 작성 방법 |
|---|---|
| `case_id` | 중복되지 않는 ID |
| `split` | `train`, `validation`, `gold`, `acceptance` 중 하나 |
| `node` | 정상 SQL은 `node2`, 오류 수정은 `node2_repair` |
| `domain` | `pms`, `crm`, `pms_crm`, `pos`, `facility`, `banquet` |
| `scenario_group` | 같은 SQL 구조와 질문 계열에 같은 값 사용 |
| `normalized_question` | SQL이 답해야 하는 질문 한 문장 |
| `context_package` | 이 문제에서 사용 가능한 자산·컬럼·지표·JOIN만 포함 |
| `expected_output` | 정답 SQL·근거 자산·parameter |
| `review_status` | 자동검사만 통과하면 `AUTO_PASSED`, 사람이 확인하면 `APPROVED` |
| `trino_status` | 실행 전 `NOT_RUN`, G1·G2·Trino 통과 후 `PASS` |
| `result_sha256` | 정렬·형식 고정된 Trino 결과의 SHA-256 |

복사해서 작성할 실제 구조는 `case_specs.example.jsonl`에 들어 있다.

### 2.2 2,000건은 무엇을 바꿔서 만드는가

같은 SQL을 문장만 바꿔 2,000건으로 늘리지 않는다. 다음 축을 조합해 **SQL의 의미나 구조가 달라지는 문제**를 만든다.

- 지표: 객실 매출, 점유율, ADR, 회원 수, 포인트, F&B 순매출 등
- 기간: 일, 주, 월, 전월 대비, 전년 동기 대비
- 집계: 합계, 평균, 건수, 비율, 추이
- 조건: 객실 유형, 회원 등급, 매장, 서비스 시간대
- 결과 형태: 전체 값, 그룹별 값, 상위 항목, 기간별 추이
- JOIN: 단일 소스 또는 승인된 PMS·CRM 시점 JOIN
- 오류 유형: Base 평가에서 실제 반복된 수정 가능한 오류

후보 2,000건의 업무별 목표 수는 다음과 같다.

| 업무 | 후보 수 |
|---|---:|
| PMS | 720 |
| CRM | 440 |
| PMS·CRM | 360 |
| POS | 280 |
| 시설 | 120 |
| 연회 | 80 |

각 `scenario_group`은 한 split에만 넣는다. 예를 들어 월만 Train, 같은 SQL 구조의 주간 질문을 Gold에 넣는 식으로 시험문제를 변형해 유출하면 안 된다.

### 2.3 질문은 SQL 뒤에 작성한다

정답 SQL이 확정된 후 그 SQL이 답할 수 있는 질문을 작성한다. LLM으로 질문 초안을 만들 수는 있지만 다음 값은 LLM이 결정하지 않는다.

- 정답 SQL
- 사용할 테이블과 JOIN
- 지표 계산식
- Trino 실행 성공 여부
- 결과 hash
- 최종 split

질문 초안이 SQL의 지표·기간·조건과 다르면 폐기하거나 수정한다.

### 2.4 Trino 검증 근거를 붙인다

정답 SQL은 기존 Control Plane의 G1·G2와 읽기 전용 Trino 계정을 통해 실행한다. 실행 결과는 컬럼 순서와 행 정렬을 고정한 뒤 SHA-256을 계산한다.

검증 전:

```json
"trino_status": "NOT_RUN",
"result_sha256": null
```

검증 후:

```json
"trino_status": "PASS",
"result_sha256": "실제 결과의 64자리 sha256"
```

학습 스크립트는 Train·Validation에 `NOT_RUN`이 하나라도 있으면 중단한다. 이 폴더에서 SQL을 직접 실행하지 않는 이유는 프로젝트의 G1·G2를 우회하지 않기 위해서다.

## 3. 학습용 JSONL 만들기

프로젝트 루트에서 실행한다.

```bash
python -m src.ai.training.dataset build \
  /workspace/data/sllm/case_specs.v1.jsonl \
  /workspace/data/sllm/dataset.v1.jsonl
```

이 명령은 다음을 자동검사한다.

- 필수 필드와 Node 입출력 형식
- Context Package 계약
- 중복 `case_id`
- `scenario_group`의 split 누수
- 쓰기 SQL, 다중 SQL, `SELECT *`
- Context에 없는 reference·컬럼·지표·JOIN
- 이메일·휴대전화 형식
- Trino 상태와 결과 hash 형식

변환 결과는 다음 세 메시지로 만들어진다.

```text
system: Node 2 또는 Node 2′의 고정 지시문
user: 정규화 질문 + Context Package
assistant: 정답 SQL + references + parameters
```

이미 변환한 파일은 다음 명령으로 다시 확인한다.

```bash
python -m src.ai.training.dataset validate /workspace/data/sllm/dataset.v1.jsonl
```

## 4. RunPod 준비

RunPod에서 A40 48GB와 PyTorch가 포함된 image를 선택하고 repository를 `/workspace` 아래에 준비한다.

```bash
cd /workspace/skn29_final_3team
python -m venv /workspace/venvs/answervice-sllm
source /workspace/venvs/answervice-sllm/bin/activate
python -m pip install --upgrade pip
python -m pip install -r src/ai/training/requirements.txt
python -c "import torch; print(torch.__version__, torch.cuda.get_device_name(), torch.cuda.is_bf16_supported())"
```

`requirements.txt`에는 RunPod image에 이미 있는 PyTorch를 넣지 않았다. Qwen3는 Transformers 4.51 이상이 필요하며, 이 패키지는 호환 범위를 고정하기 위해 Transformers 4.x 최종 안정판을 사용한다.

## 5. Smoke test

실제 데이터 중 소량을 사용해 2 step만 실행한다.

```bash
python -m src.ai.training.train_lora \
  --data /workspace/data/sllm/dataset.v1.jsonl \
  --output-dir /workspace/models/answervice-sql-lora-smoke \
  --max-steps 2
```

확인할 결과:

- CUDA·BF16 인식
- 데이터 token 길이 12,288 이하
- forward·backward 성공
- checkpoint와 adapter 저장
- `training_manifest.json` 생성

## 6. 본 학습

Smoke test가 통과하면 `--max-steps` 없이 실행한다.

```bash
python -m src.ai.training.train_lora \
  --data /workspace/data/sllm/dataset.v1.jsonl \
  --output-dir /workspace/models/answervice-sql-lora-v1
```

기본 설정:

| 항목 | 값 |
|---|---:|
| Base model | `Qwen/Qwen3-4B-Instruct-2507` |
| 정밀도 | BF16 |
| Thinking | 사용하지 않음 |
| 최대 길이 | 12,288 tokens |
| Epoch | 2 |
| LoRA rank / alpha | 16 / 32 |
| GPU batch | 1 |
| Gradient accumulation | 8 |
| Learning rate | `2e-4` |

이 값은 첫 실행값이다. Base 평가와 smoke test 결과 없이 여러 조합을 동시에 탐색하지 않는다.

중단된 checkpoint에서 이어서 실행하려면 다음 옵션을 추가한다.

```bash
--resume-from-checkpoint /workspace/models/answervice-sql-lora-v1/checkpoint-번호
```

## 7. Base와 LoRA 평가

먼저 같은 Validation 데이터에서 새 Base를 실행한다. LoRA는 Base가 승인 기준에 미달하고 별도 승인을 받은 경우에만 비교한다.

Base:

```bash
python -m src.ai.training.evaluate_lora \
  --data /workspace/data/sllm/dataset.v1.jsonl \
  --split validation \
  --output /workspace/evals/base.validation.jsonl
```

LoRA:

```bash
python -m src.ai.training.evaluate_lora \
  --data /workspace/data/sllm/dataset.v1.jsonl \
  --split gold \
  --adapter /workspace/models/answervice-sql-lora-v1 \
  --output /workspace/evals/lora.gold.jsonl
```

이 평가 스크립트는 JSON 형식과 정답 SQL의 문자열 일치 여부를 빠르게 확인한다. 의미가 같지만 표현이 다른 SQL까지 최종 정답으로 판정하려면 생성 SQL도 G2와 Trino에서 실행하고 `result_sha256`을 비교해야 한다.

## 8. 아직 연결해야 하는 계약

현재 동결된 `node2_request`에는 `question_id`와 `context_package`만 있고 `normalized_question`이 없다. 학습데이터는 실제 SQL 생성에 필요한 `normalized_question + context_package`를 입력으로 사용한다.

공식 serving을 연결하기 전에 R3·R4가 다음 중 하나로 runtime 계약을 동결해야 한다.

1. `node2_request`에 `normalized_question`을 추가한다.
2. `question_id`로 서버 상태에서 정규화 질문을 조회해 모델 입력에 합친다.

이 계약이 정해지기 전에도 데이터 제작과 LoRA 학습은 가능하지만, 학습한 adapter를 현재 backend에 바로 연결할 수는 없다.
