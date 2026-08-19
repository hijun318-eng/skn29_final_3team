# RunPod Serverless vLLM 배포 가이드

작성일: 2026-08-12

## 1. 목적

현재 RunPod Pod에서 검증한 Answervice Node2 LoRA 모델을 RunPod Serverless의 고정 Endpoint로 옮긴다.

목표 API는 다음과 같다.

```text
https://api.runpod.ai/v2/<ENDPOINT_ID>/openai/v1
```

Serverless worker가 교체되거나 scale-to-zero 이후 다시 생성되어도 같은 Endpoint ID를 사용하는 동안 URL은 유지된다. Endpoint 자체를 삭제하고 다시 만들면 ID와 URL도 바뀐다.

이 문서는 다음 경로를 기본으로 한다.

```text
Qwen base: Hugging Face 공개 저장소
LoRA Adapter: 사용자 Private Hugging Face 저장소
Runtime: RunPod 공식 vLLM Serverless Worker
Endpoint type: Queue
API: OpenAI-compatible
GPU: RTX 4090 우선
```

Load Balancer와 custom Docker image는 기본 경로가 실패할 때만 사용한다.

## 2. 현재 검증된 모델 계약

| 항목 | 값 |
|---|---|
| Base model | `Qwen/Qwen3.5-4B` |
| Base revision | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` |
| Adapter type | BF16 LoRA |
| LoRA rank | 16 |
| LoRA alpha | 32 |
| Runtime model ID | `answervice-sql` |
| Serving context window | `5120` tokens |
| Backend max output | `1280` tokens |
| Backend safety margin | `256` tokens |
| Adapter model SHA-256 | `90a3d896a22e9148e46c609e978a657cd638cb6ab938d00af54cefcd3715c313` |
| Pod에서 검증한 vLLM | `0.21.0+cu129` |
| Pod에서 검증한 Transformers | `5.14.1` |
| 검증 GPU | RTX 4090 |
| 입력 | `Structured Business Request + Approved Context Package` |
| 출력 | `{sql, used_assets, used_metrics}` strict JSON |

자연어 원문 question을 Qwen 입력에 직접 추가하지 않는다.

## 3. Pod 방식과 달라지는 점

Serverless worker는 임시 인스턴스이므로 Web Terminal에 접속해 ZIP을 풀고 `vllm serve`를 수동 실행하는 방식은 사용할 수 없다.

| Pod | Serverless |
|---|---|
| 터미널에서 모델 파일 준비 | Worker 시작 전에 접근 가능한 저장소가 필요 |
| `vllm serve` 직접 실행 | 공식 Worker가 환경 변수로 vLLM 실행 |
| Pod proxy URL | Endpoint ID 기반 고정 URL |
| `VLLM_API_KEY` | RunPod API Key |
| Pod가 켜진 동안 warm | Active worker가 0이면 cold start 발생 |

따라서 Adapter는 다음 중 하나로 worker가 시작될 때 접근 가능해야 한다.

1. Private Hugging Face 저장소에 업로드한다. 이 문서의 기본 경로다.
2. Adapter를 custom Docker image 안에 포함한다.
3. 공식 Worker가 해당 local path 구성을 지원하는지 별도 검증한 뒤 Network Volume을 사용한다.

현재 공식 문서는 `LORA_MODULES`의 Hugging Face 경로 사용을 명시하므로, Network Volume local LoRA 경로는 기본 절차로 간주하지 않는다.

## 4. 사전 준비

다음 항목이 필요하다.

- RunPod 계정과 RunPod API Key
- Hugging Face 계정
- Private Hugging Face model repository 1개
- 해당 저장소에 접근할 수 있는 Hugging Face read token
- 학습 결과 ZIP 또는 이미 압축 해제된 `results/adapter` 디렉터리

Secret은 명령 기록, 문서, Git, Docker image layer에 직접 넣지 않는다.

### 4.1 Adapter 필수 파일

현재 Adapter 디렉터리에는 다음 파일이 있다.

```text
adapter_config.json
adapter_model.safetensors
chat_template.jinja
README.md
tokenizer.json
tokenizer_config.json
```

최소한 `adapter_config.json`과 `adapter_model.safetensors`가 필요하다. 현재 학습·추론 계약을 그대로 보존하기 위해 위 6개 파일을 모두 Private repository에 올린다.

### 4.2 Python으로 ZIP 압축 해제

이미 압축을 해제했다면 이 단계는 생략한다. `unzip` 명령은 사용하지 않는다.

```bash
python - <<'PY'
from pathlib import Path
from zipfile import ZipFile

archive = Path("/workspace/answervice-sllm-results.zip")
target = Path("/workspace/answervice-sllm")
target.mkdir(parents=True, exist_ok=True)

with ZipFile(archive) as bundle:
    bundle.extractall(target)

print(target.resolve())
PY
```

압축 파일 이름과 실제 Adapter 경로는 현재 파일 구조에 맞게 바꾼다.

### 4.3 Adapter hash 확인

```bash
python - <<'PY'
from hashlib import sha256
from pathlib import Path

path = Path("/workspace/answervice-sllm/results/adapter/adapter_model.safetensors")
digest = sha256(path.read_bytes()).hexdigest()
expected = "90a3d896a22e9148e46c609e978a657cd638cb6ab938d00af54cefcd3715c313"

print("file:", path)
print("sha256:", digest)
print("hash match:", digest == expected)

if digest != expected:
    raise SystemExit("Adapter hash mismatch")
PY
```

`hash match: True`가 아니면 업로드하지 않는다.

## 5. Private Hugging Face Adapter 저장소 준비

Hugging Face 웹 UI에서 새 Model repository를 만들고 Visibility를 `Private`로 설정한다.

예시 이름:

```text
<HF_ACCOUNT>/answervice-sql-lora
```

`results/adapter` 안의 파일을 저장소 root에 업로드한다. 다음처럼 한 단계 더 중첩시키지 않는다.

```text
# 올바름
repo-root/adapter_config.json
repo-root/adapter_model.safetensors

# 피해야 함
repo-root/results/adapter/adapter_config.json
```

업로드 완료 후 repository Files 화면에서 `adapter_config.json`과 `adapter_model.safetensors`가 root에 보이는지 확인한다.

외부 저장소 업로드는 모델 파일 전송이므로 사용자의 명시적 승인과 조직 정책 확인 후 수행한다.

## 6. RunPod Serverless Endpoint 생성

### 6.1 공식 vLLM Worker 선택

1. RunPod Console에서 `Serverless`로 이동한다.
2. `New Endpoint` 또는 vLLM Hub의 `Deploy`를 선택한다.
3. RunPod 공식 vLLM Worker를 선택한다.
4. Endpoint Type은 우선 `Queue`를 선택한다.
5. Endpoint 이름은 예를 들어 `answervice-sql`로 설정한다.

Queue Endpoint도 다음 OpenAI-compatible URL을 제공하므로 현재 Backend 연결에 충분하다.

```text
https://api.runpod.ai/v2/<ENDPOINT_ID>/openai/v1
```

### 6.2 GPU와 worker 설정

데모와 초기 검증에서는 다음 값으로 제한한다.

| 설정 | 권장값 | 이유 |
|---|---:|---|
| Primary GPU | RTX 4090 | Pod 검증 GPU와 동일 |
| GPUs per worker | 1 | 4B base + LoRA에 충분 |
| Active workers | 1 | cold start 제거 |
| Max workers | 1 | 비용 상한 및 단일 검증 |
| Idle timeout | 기본값 | Active worker 1에서는 실질적 scale-to-zero 없음 |
| Execution timeout | 600초 이상 | 초기 검증 여유 |
| FlashBoot | Enabled | worker 재기동 시간 단축 |

`Active workers=1`은 요청이 없어도 계속 과금된다. 비용 절감이 더 중요하면 검증 후 0으로 낮출 수 있지만, 그 경우 Backend timeout보다 cold start가 길 수 있다.

Serverless에서는 사용자가 Pod template의 CUDA 12.4를 직접 재현하는 것이 목표가 아니다. 선택한 공식 Worker image와 RunPod host driver가 호환되어야 한다. CUDA 선택 항목이 있다면 worker image가 요구하는 버전과 그보다 새로운 호환 버전을 허용한다.

### 6.3 Public 환경 변수

다음 값을 설정한다.

```dotenv
MODEL_NAME=Qwen/Qwen3.5-4B
MODEL_REVISION=851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a

ENABLE_LORA=true
MAX_LORAS=1
MAX_LORA_RANK=16
LORA_MODULES=[{"name":"answervice-sql","path":"<HF_ACCOUNT>/answervice-sql-lora"}]

DTYPE=bfloat16
MAX_MODEL_LEN=5120
MAX_NUM_SEQS=1
GPU_MEMORY_UTILIZATION=0.85
ENFORCE_EAGER=true
LANGUAGE_MODEL_ONLY=true

RAW_OPENAI_OUTPUT=1
```

`LANGUAGE_MODEL_ONLY`가 배포한 공식 Worker/vLLM 버전에서 인식되는지는 worker startup log에서 확인한다. 인식되지 않거나 Qwen3.5 text-only 로딩이 실패하면 공식 Worker 버전을 억지로 수정하지 말고 11장의 fallback으로 이동한다.

`OPENAI_SERVED_MODEL_NAME_OVERRIDE`는 우선 설정하지 않는다. 요청의 `model`은 LoRA module name인 `answervice-sql`이어야 한다. 배포 후 `/models`에 이 ID가 노출되지 않을 때만 worker의 LoRA 등록 로그와 공식 Worker 버전을 먼저 확인한다.

### 6.4 Secret 환경 변수

RunPod의 Secret 환경 변수 영역에 다음 값을 설정한다.

```dotenv
HF_TOKEN=<Private Adapter repository를 읽을 수 있는 token>
```

RunPod API Key는 worker가 Hugging Face를 읽기 위한 환경 변수가 아니다. 호출 클라이언트의 `Authorization` header에 사용한다.

## 7. Worker 시작 로그 Gate

Endpoint를 생성한 뒤 worker log에서 다음을 확인한다.

| 확인 항목 | 통과 조건 |
|---|---|
| Base model | `Qwen/Qwen3.5-4B` |
| Revision | 지정 commit hash 사용 |
| Architecture | Qwen3.5 language model 로딩 성공 |
| Adapter | `answervice-sql` LoRA 등록 성공 |
| LoRA rank | 16 허용 |
| GPU | CUDA device 인식 |
| Startup | worker ready/healthy |
| 반복 재시작 | 없음 |

다음 오류가 있으면 API 검증으로 넘어가지 않는다.

- `ImportError` 또는 CUDA shared library 오류
- Qwen3.5 architecture 미지원
- `adapter_config.json` 또는 Adapter repository 접근 실패
- LoRA target module 불일치
- OOM
- worker가 ready가 되기 전 반복 종료

## 8. 고정 Endpoint 직접 검증

새 터미널에서 Secret을 shell history에 직접 남기지 않는 방법으로 환경 변수를 준비한다.

```bash
export RUNPOD_ENDPOINT_ID="<ENDPOINT_ID>"
export RUNPOD_API_KEY="<RUNPOD_API_KEY>"
export RUNPOD_OPENAI_BASE="https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/openai/v1"
```

### 8.1 Model 목록

```bash
curl -sS "${RUNPOD_OPENAI_BASE}/models" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}"
```

응답 `data` 안에 다음 model ID가 있어야 한다.

```text
answervice-sql
```

Base model만 보이고 `answervice-sql`이 없으면 Backend를 연결하지 않는다.

### 8.2 OpenAI-compatible completion

Node2의 실제 제품 입력은 Backend serializer가 만든 sealed structured input이어야 한다. 수동 검증에서도 자연어 질문만 단독으로 보내서 성공 판정을 내리지 않는다.

```bash
curl -sS "${RUNPOD_OPENAI_BASE}/chat/completions" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @node2-sealed-smoke.json
```

`node2-sealed-smoke.json`은 Secret을 포함하지 않아야 하며 현재 Backend의 Node2 직렬화와 동일한 다음 구조를 포함해야 한다.

```text
Structured Business Request
+ Approved Context Package
→ {sql, used_assets, used_metrics}
```

통과 조건:

- HTTP 200
- `choices[0].message.content` 존재
- content가 strict JSON으로 parse됨
- `sql`, `used_assets`, `used_metrics`만 계약대로 존재
- 승인 Context 밖 asset/metric이 없음
- `model` 요청값이 `answervice-sql`

## 9. Answervice Backend 연결

현재 Backend는 `NODE2_MODEL_ENDPOINT` 뒤에 `/v1/models`와 `/v1/chat/completions`를 붙인다. 따라서 Serverless 공식 base URL 전체를 넣으면 안 된다.

repository root `README.md` 절차로 만든 외부 deployment environment에 다음처럼 설정한다.

```dotenv
NODE2_MODEL_PROVIDER=qwen
NODE2_MODEL_ENDPOINT=https://api.runpod.ai/v2/<ENDPOINT_ID>/openai
NODE2_MODEL_API_TOKEN=<RUNPOD_API_KEY>
NODE2_MODEL=answervice-sql
MODEL_TIMEOUT_SECONDS=600
```

중요:

```text
# 현재 코드에 맞는 값
.../<ENDPOINT_ID>/openai

# 현재 코드에서 /v1이 중복되므로 사용하지 않음
.../<ENDPOINT_ID>/openai/v1
```

OpenAI Node1/Node3 설정은 기존 값을 유지한다.

```dotenv
OPENAI_ENDPOINT=<기존 값>
OPENAI_API_KEY=<기존 secret>
OPENAI_MODEL=<기존 승인 모델>
```

외부 deployment environment 원문 또는 Secret 값을 출력하지 않는다.
`MODEL_MODE`는 Backend가 읽지 않으므로 설정하지 않는다. 위 네 Node2 값은 하나의
versioned route 계약이며 일부만 선언하거나 `NODE2_MODEL_PROVIDER=openai`로 두면
Qwen capacity profile과 일치하지 않아 Backend가 fail-closed한다.

### 9.1 Backend 재기동

repository root에서 실행한다.

```powershell
$deploymentEnv = Join-Path $env:LOCALAPPDATA 'Answervice\deployment\answervice.env'
if (-not (Test-Path -LiteralPath $deploymentEnv -PathType Leaf)) { throw '외부 deployment environment가 필요합니다.' }
docker compose --env-file $deploymentEnv --profile full up -d --force-recreate backend
docker ps --filter "name=answervice-backend"
```

여기서 Compose profile 이름은 `full`이지만 DataHub 배포 형태는 DataHub Core(GMS와 의존성)다. DataHub UI/Actions full product를 뜻하지 않는다.

Backend readiness에서 model probe가 ready인지 확인한다. Secret header나 전체 환경 변수는 로그에 출력하지 않는다.

## 10. 실제 Docker HTTP E2E

브라우저에서 다음 주소를 연다.

```text
http://127.0.0.1:13000/agent
```

대표 질문을 실행한다.

```text
2026년 6월 객실 매출을 일별로 분석해줘.
```

통과 조건:

- Frontend request가 강제 `template_id` 없이 전송됨
- Bearer 인증 통과
- Node1은 OpenAI 호출
- Node2 trace/model이 `answervice-sql`
- Node2 endpoint가 Serverless Endpoint ID를 사용
- G2 통과
- Trino 실제 query ID 존재
- Node3은 OpenAI 호출
- 상태 `SUCCEEDED`
- 표 30행 및 차트 표시
- Serverless worker log에 `/chat/completions` 성공 기록

현재 synthetic baseline과 비교할 때 대표 결과는 30행, 합계 `1,218,835,200 KRW`다. 이 숫자는 stay-day 배분 기준 baseline이며 checkout 인식 매출 의미와는 별도 미결정 사항이다.

## 11. 공식 Worker 호환성 실패 시 fallback

현재 Pod에서 검증된 조합은 `vLLM 0.21.0+cu129`와 `Transformers 5.14.1`이다. RunPod 공식 Worker의 현재 버전은 배포 시점에 다를 수 있으므로 Qwen3.5 또는 Adapter가 실패할 수 있다.

다음 오류에서는 임의 `pip install`로 실행 중 worker를 고치지 않는다.

- vLLM/Transformers API 불일치
- Qwen3.5 architecture 미지원
- CUDA binary/runtime 불일치
- `LANGUAGE_MODEL_ONLY` 또는 LoRA target module 미지원

이 경우 다음 버전을 고정한 custom Docker image를 만든다.

```text
Python 3.11
vLLM 0.21.0+cu129
Transformers 5.14.1
Torch/CUDA: vLLM 0.21.0 cu129 wheel 의존성
Base revision: 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a
Adapter: image 안에 포함하거나 startup 시 Private HF에서 다운로드
```

custom image에는 다음이 필요하다.

- Serverless handler 또는 RunPod 공식 worker-vLLM 기반 image
- health/ready 처리
- OpenAI-compatible `/v1/models`, `/v1/chat/completions`
- Secret을 image layer에 넣지 않는 다운로드 방식
- `linux/amd64` image build
- immutable version 또는 digest 사용

custom image build, registry push, Serverless Endpoint 교체는 별도 작업으로 진행한다. 공식 Worker가 성공하면 만들지 않는다.

## 12. 운영 설정 전환

### 데모 안정성 우선

```text
Active workers = 1
Max workers = 1
MODEL_TIMEOUT_SECONDS = 600
```

### 비용 절감 우선

```text
Active workers = 0
Max workers = 1
FlashBoot = Enabled
```

Active worker를 0으로 바꾸기 전 cold start를 실제 측정한다. 측정한 최대 cold start보다 Backend timeout이 짧으면 첫 요청이 실패한다.

GPU 재고 문제가 있으면 RTX 4090을 primary로 두고 공식 Worker와 호환되는 24GB 이상 GPU를 secondary로 추가할 수 있다. GPU별 latency와 LoRA 결과 일치 여부를 다시 검증한다.

## 13. 롤백

Serverless가 E2E를 통과하기 전 기존 Pod Endpoint 설정을 삭제하지 않는다.

실패 시 외부 deployment environment의 다음 네 값만 기존 Pod 값으로 되돌리고 Backend를 재기동한다.

```dotenv
NODE2_MODEL_PROVIDER=qwen
NODE2_MODEL_ENDPOINT=<기존 Pod base URL>
NODE2_MODEL_API_TOKEN=<기존 Pod token>
NODE2_MODEL=answervice-sql
```

Serverless Endpoint 삭제는 외부 상태 변경이며 비용과 복구 가능성을 확인한 뒤 사용자가 명시적으로 요청할 때만 수행한다.

## 14. 완료 체크리스트

- [ ] Adapter hash 일치
- [ ] Private Hugging Face repository 생성 및 파일 업로드
- [ ] HF read token을 RunPod Secret으로 설정
- [ ] Serverless Endpoint ID 발급
- [ ] RTX 4090 worker ready
- [ ] exact base revision 확인
- [ ] `answervice-sql` LoRA 등록 확인
- [ ] 고정 URL `/openai/v1/models` HTTP 200
- [ ] `/models`에 `answervice-sql` 존재
- [ ] sealed Node2 completion strict JSON 성공
- [ ] Backend readiness `model: ready`
- [ ] 실제 Docker HTTP Golden Path `SUCCEEDED`
- [ ] Trino query ID 및 30행 결과 확인
- [ ] worker log에서 실제 completion 확인
- [ ] cold start 또는 Active worker 비용 정책 결정
- [ ] 실패 항목과 rollback 여부 기록

## 15. 공식 참고 문서

- [RunPod Serverless vLLM 시작](https://docs.runpod.io/serverless/vllm/get-started)
- [OpenAI API compatibility](https://docs.runpod.io/serverless/vllm/openai-compatibility)
- [vLLM 환경 변수와 LoRA 설정](https://docs.runpod.io/serverless/vllm/environment-variables)
- [Serverless Endpoint 설정](https://docs.runpod.io/serverless/endpoints/endpoint-configurations)
- [RunPod 공식 worker-vllm](https://github.com/runpod-workers/worker-vllm)
- [Load Balancing vLLM Endpoint](https://docs.runpod.io/serverless/load-balancing/vllm-worker)
