# sLLM RunPod 연결 가이드

## 1. 제공된 결과물

```text
ZIP: answervice-sllm-results (3).zip
ZIP SHA-256: 22510f0de36d0121c350c4cd5ba3705a4db95dea27ce78baf70434ff1e24f29e
Experiment: ANSWERVICE-SLLM-RUNPOD-v4.1
Base: Qwen/Qwen3.5-4B
Revision: 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a
License: apache-2.0
Adapter: BF16 LoRA, rank 16
Adapter model file SHA-256: 90a3d896a22e9148e46c609e978a657cd638cb6ab938d00af54cefcd3715c313
```

ZIP 안에는 base weight가 아니라 PEFT Adapter, tokenizer, chat template, 학습·평가 결과가 있다. serving할 때 exact base revision과 Adapter를 함께 로드해야 한다.

## 2. 현재 평가 해석

sealed Test 50건에서 Adapter는 다음 정적·모델 단계 지표를 기록했다.

| 지표 | Adapter |
|---|---:|
| valid JSON | 1.00 |
| schema pass | 1.00 |
| SQL parse | 1.00 |
| G2 acceptance | 1.00 |
| context violation | 0.00 |
| semantic SQL match | 1.00 |
| sort request match | 1.00 |
| p50 generation latency | 약 10.6초 |
| p95 generation latency | 약 54.6초 |
| 실제 Trino Result Accuracy | `PENDING_LOCAL_TRINO` |

이 결과는 Adapter 연결 가치가 있다는 근거지만 제품 채택 완료 근거는 아니다. 특히 latency는 A40에서 `transformers.generate()`로 측정한 비최적화 결과이며, 실제 Trino 결과 비교가 아직 끝나지 않았다.

## 3. 검증된 RunPod 호환 환경

2026-08-12 RTX 4090 RunPod에서 다음 조합으로 vLLM의 CUDA 초기화와
Qwen3.5 base weight 로딩까지 확인했다.

| 항목 | 확인된 값 |
|---|---|
| GPU | NVIDIA GeForce RTX 4090 |
| `nvidia-smi` CUDA 표시 | 12.4 |
| Python | 3.11.10 |
| vLLM | `0.21.0+cu129` |
| Transformers | `5.14.1` |
| Base model | `Qwen/Qwen3.5-4B` |
| Base revision | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` |
| LoRA module name | `answervice-sql` |
| LoRA rank | 16 |
| Serving context window | `5120` tokens |
| Backend max output | `1280` tokens |
| Backend safety margin | `256` tokens |

여기서 `nvidia-smi`의 `CUDA Version: 12.4`는 호스트 드라이버가 표시하는
지원 버전이다. `cu129`는 설치한 wheel의 빌드 변형 이름이다. 두 문자열이
같아야 한다고 가정하지 않는다. 이 문서의 조합은 버전 문자열만 보고 정한
것이 아니라 실제 vLLM 엔진 초기화와 8.68 GiB base weight 로딩으로 확인했다.

### 3.1 사용하지 않는 조합

다음 조합은 이 환경에서 실패했으므로 다시 사용하지 않는다.

- `vllm==0.8.5.post1` + `transformers==5.15.0`: `Qwen2Tokenizer has no attribute all_special_tokens_extended`
- 당시 nightly vLLM wheel: vLLM 확장 모듈이 `libcudart.so.13`을 요구하여 import 실패
- 단순 `pip check`: Python package dependency만 검사하므로 CUDA shared library 호환성의 통과 근거가 아니다.

## 4. 설치

기존 실패 환경을 덮어쓰지 않고 새 virtual environment를 만든다.

```bash
python3 -m venv /workspace/venvs/answervice-vllm
source /workspace/venvs/answervice-vllm/bin/activate

python -m pip install -U pip uv
```

RunPod의 `/workspace`는 FUSE network volume이다. uv의 기본 hardlink 설치는
실제 여유 공간이 있어도 `Disk quota exceeded`로 실패할 수 있으므로
`--link-mode copy --no-cache`를 반드시 사용한다.

```bash
uv pip install \
  vllm==0.21.0 \
  transformers==5.14.1 \
  --torch-backend=cu129 \
  --extra-index-url https://wheels.vllm.ai/0.21.0/cu129 \
  --extra-index-url https://download.pytorch.org/whl/cu129 \
  --index-strategy unsafe-best-match \
  --link-mode copy \
  --no-cache
```

`df -h /workspace`는 RunPod 공유 storage 전체 용량을 표시할 수 있으므로
개별 Volume Disk quota 판단에 사용하지 않는다. 실제 할당량은 RunPod UI의
Volume Disk와 `du -sh /workspace`를 함께 확인한다.

### 4.1 설치 검증

```bash
python - <<'PY'
import torch
import transformers
import vllm

print("vLLM:", vllm.__version__)
print("Transformers:", transformers.__version__)
print("PyTorch:", torch.__version__)
print("Built CUDA:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())
print("GPU:", torch.cuda.get_device_name(0))

x = torch.tensor([1.0], device="cuda")
print("CUDA tensor:", x)
print("Environment: PASS")
PY

uv pip check
```

`vllm import`, CUDA tensor 생성, GPU 이름 확인이 모두 성공해야 다음 단계로
진행한다. `uv pip check`만 성공한 상태는 충분하지 않다.

## 5. vLLM 실행

### 5.1 API key 생성과 보관

vLLM API key는 외부에서 발급받는 값이 아니라 endpoint 인증용으로 직접
생성하는 random secret이다.

```bash
export VLLM_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

python -c 'import os, pathlib; p=pathlib.Path("/workspace/.vllm_api_key"); p.write_text(os.environ["VLLM_API_KEY"]); p.chmod(0o600)'
```

Secret 값은 채팅, 문서, commit, 공유 로그에 포함하지 않는다. vLLM startup
로그의 `non-default args`에 key가 나타날 수 있으므로 해당 줄을 공유하면
key를 즉시 교체한다.

### 5.2 백그라운드 실행

Qwen3.5는 multimodal 구조지만 이 Adapter와 제품 입력은 text-only다.
`--language-model-only`로 vision tower를 제외해야 불필요한 GPU memory 사용과
visual LoRA 경고를 줄일 수 있다.

```bash
source /workspace/venvs/answervice-vllm/bin/activate

export HF_HOME=/workspace/.cache/huggingface
export VLLM_API_KEY="$(cat /workspace/.vllm_api_key)"

nohup vllm serve Qwen/Qwen3.5-4B \
  --revision 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a \
  --language-model-only \
  --enable-lora \
  --lora-modules answervice-sql=/workspace/answervice-sllm/results/adapter \
  --max-lora-rank 16 \
  --dtype bfloat16 \
  --max-model-len 5120 \
  --max-num-seqs 1 \
  --gpu-memory-utilization 0.85 \
  --enforce-eager \
  --api-key "$VLLM_API_KEY" \
  --host 0.0.0.0 \
  --port 8000 \
  > /workspace/vllm-server.log 2>&1 &

echo $! > /workspace/vllm-server.pid
```

`nohup`으로 실행하므로 Web Terminal을 닫아도 server process가 유지된다.

```bash
tail -f /workspace/vllm-server.log
```

`Application startup complete`가 나온 뒤에만 endpoint가 기동됐다고 판정한다.

## 6. Endpoint 검증

새 Web Terminal에서는 먼저 같은 virtual environment와 key를 불러온다.

```bash
source /workspace/venvs/answervice-vllm/bin/activate
export VLLM_API_KEY="$(cat /workspace/.vllm_api_key)"
```

LoRA model 등록을 확인한다.

```bash
curl -sS http://127.0.0.1:8000/v1/models \
  -H "Authorization: Bearer $VLLM_API_KEY"
```

응답의 `data`에 `"id":"answervice-sql"`이 있어야 한다. RunPod UI의
`Connect -> HTTP Services -> Port 8000` URL에서도 같은 요청이 성공해야 외부
endpoint 검증을 통과한 것으로 기록한다.

## 7. 확인된 로그와 남은 검증

현재 보존된 실행 로그로 확인된 사실은 다음과 같다.

| 항목 | 상태 | 근거 |
|---|---|---|
| vLLM import와 API process 시작 | Pass | `vLLM version 0.21.0` |
| exact base revision | Pass | engine config의 revision 일치 |
| Qwen3.5 architecture 인식 | Pass | `Resolved architecture: Qwen3_5ForConditionalGeneration` |
| CUDA model weight 로딩 | Pass | 8.68 GiB load 완료 |
| LoRA module argument 등록 | Pass | `answervice-sql=/workspace/answervice-sllm/results/adapter` |
| text-only 재기동 | Pass | `--language-model-only` 적용 server 기동 |
| `Application startup complete` | Pass | 외부 HTTP endpoint 응답 확인 |
| `/v1/models`의 `answervice-sql` | Pass | RunPod proxy에서 인증된 model 목록 확인 |
| `/v1/chat/completions` 실제 생성 | Pass | sealed test 입력으로 strict JSON 세 필드 확인 |

Backend의 Slice B routing을 적용한 뒤에도 다음 실제 호출을 확인했다.

| Node | Endpoint | 상태 |
|---|---|---|
| Node1 | OpenAI `gpt-5.4-mini` | strict schema 응답 Pass |
| Node2 | RunPod `answervice-sql` | 학습 직렬화 및 runtime contract 변환 Pass |
| Node3 | OpenAI `gpt-5.4-mini` | strict schema 응답 Pass |

Docker backend readiness에서도 OpenAI와 RunPod의 인증된 `/v1/models` probe가
모두 성공하여 `model: ready`를 확인했다.

visual module의 `no matching PunicaWrapper` 경고는 기존 실행이 multimodal
기본값으로 vision tower까지 로드하면서 발생했다. text-only Adapter가 실패했다는
뜻으로 확정하지 않으며, `--language-model-only` 재기동 결과로 최종 판단한다.

## 8. Backend 환경 변수

### 8.1 제품 Contract

`GET /v1/models` 응답에 base와 `answervice-sql`이 보여야 한다. chat completion request의 `model`은 `answervice-sql`을 사용한다.

smoke payload는 학습 Contract와 같아야 한다.

```text
Structured Business Request
+ Approved Context Package
→ {sql, used_assets, used_metrics}
```

자연어 question을 Qwen 입력에 추가하지 않는다. `temperature=0`, thinking off, retry 0으로 시작한다.

확인 항목:

- strict JSON parse
- `sql`, `used_assets`, `used_metrics`
- Approved Context 밖 자산 0건
- G2 통과
- 실제 Trino 실행
- Gold Result 비교
- timeout, 4xx, 5xx, malformed JSON이 성공으로 저장되지 않음

코드가 Node별 routing을 지원하도록 구현된 뒤 사용자가 repository root
`README.md` 절차로 만든 외부 deployment environment에 다음 값을 넣는다.

```dotenv
OPENAI_ENDPOINT=https://api.openai.com
OPENAI_API_KEY=<사용자가 보관한 OpenAI API key>
OPENAI_MODEL=<승인한 GPT model>

NODE2_MODEL_PROVIDER=qwen
NODE2_MODEL_ENDPOINT=<RunPod OpenAI-compatible base URL>
NODE2_MODEL_API_TOKEN=<RunPod endpoint token>
NODE2_MODEL=answervice-sql
MODEL_TIMEOUT_SECONDS=<실측 후 결정>
```

현재 검증 대상인 GPU Pod의 HTTP Service URL은 RunPod UI의
`Connect -> HTTP Services -> Port 8000`에서 복사한다. 일반적인 형태는 다음과
같다.

```text
https://<POD_ID>-8000.proxy.runpod.net
```

Backend가 `/v1/chat/completions`를 붙이므로 `NODE2_MODEL_ENDPOINT`에는 `/v1`을
붙이지 않는다. Serverless 전환은 Pod HTTP E2E가 통과한 뒤 별도로 검증한다.
`MODEL_MODE`는 runtime 계약에 없는 값이므로 설정하지 않는다. Node2 전용 route는
provider·endpoint·token·model 네 값을 모두 선언해야 하며 일부만 있으면 readiness와
모델 adapter 생성이 함께 실패한다.

## 9. 사용자에게 필요한 작업

- RunPod에서 ZIP 업로드
- base model 다운로드에 필요한 Hugging Face 접근 확인
- GPU Pod 선택과 비용 승인
- endpoint URL 확인과 인증 token 생성
- repository 밖 deployment environment에 OpenAI·RunPod Secret 입력

Secret 값은 채팅에 보내지 않는다. 준비 완료 여부와 endpoint가 `/v1/models`에 응답하는지만 알려주면 된다.

## 10. 채택 Gate

다음을 모두 통과하기 전 Adapter를 제품 기본값으로 바꾸지 않는다.

- ZIP과 Adapter hash 일치
- exact base revision
- 학습과 runtime serialization 일치
- 실제 Trino Result Accuracy 측정
- Golden Path HTTP E2E 성공
- G2 실패·endpoint 실패가 fail-closed
- p95 latency와 timeout 실측
- GPT Node1·Node3와 sLLM Node2 trace 구분
