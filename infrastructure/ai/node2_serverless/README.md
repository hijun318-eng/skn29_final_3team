# Node2 Qwen3.5-2B RunPod Serverless worker

이 경로는 A40 Pod에서 검증한 `vLLM 0.21.0+cu129` 실행 계약을 RunPod
Serverless custom image로 옮긴다. 기존 4B 모델이나 runtime을 참조하지 않는다.
모델은 비공개 Hugging Face repository에 저장하고 RunPod Model Cache가
worker 시작 전에 제공한다.

핵심 제약은 다음과 같다.

- corrected Full3000 checkpoint는 image에 bake하지 않는다.
- `MODEL_NAME`은 비공개 Hugging Face repo ID, `MODEL_REVISION`은 40자리 commit
  SHA로 고정한다. `main` 같은 이동 가능한 revision은 거부한다.
- worker 내부 runtime download는 금지하고 RunPod가 미리 준비한 cached snapshot만
  사용한다.
- 시작 preflight가 cached checkpoint의 12개 파일 hash와 632/96/536 merge 계약을
  다시 검증한다.
- 모델 alias는 `node2-qwen35-2b-full3000-20260825` 하나만 허용한다.
- `POST /v1/chat/completions`, `GET /v1/models`, `GET /health`만 proxy한다.
- `guided_json`과 다른 model alias 요청은 worker에서 거부한다.
- 동시성은 worker와 vLLM 모두 1로 고정한다.
- registry digest를 `NODE2_VLLM_IMAGE_DIGEST`로 주입하지 않으면 시작하지 않는다.

Hugging Face 업로드 원본은 먼저 로컬에서 검증한다.

```powershell
.\scripts\publish_node2_hf_model.ps1 `
  -RepoId "<hf-account>/node2-qwen35-2b-full3000"
```

외부 업로드 승인을 받은 후 `hf auth login`을 사용자가 직접 수행하고 `-Upload`를
추가한다. 토큰은 command argument, 저장소, log에 기록하지 않는다. 스크립트는
repository가 private인지 확인하고 최종 commit SHA를 출력한다.

로컬 build는 repository root에서 아래처럼 실행한다. 기본 동작은 registry에
push하지 않고 local Docker에 load한다.

```powershell
.\scripts\build_node2_serverless_image.ps1 `
  -ImageRef "docker.io/<account>/node2-qwen35-2b:20260826-canary"
```

`-Push`는 외부 registry 변경이므로 registry와 repository가 승인된 뒤에만
사용한다. Endpoint 생성은 이 build script의 범위가 아니다.

Endpoint에는 다음 값을 secret 또는 environment variable로 설정한다.

```text
MODEL_NAME=<hf-account>/node2-qwen35-2b-full3000
MODEL_REVISION=<40-character-Hugging-Face-commit-SHA>
NODE2_VLLM_IMAGE_DIGEST=sha256:<pushed-worker-image-digest>
```

비공개 모델 접근용 Hugging Face token은 해당 model repository에 대한 read-only
fine-grained token만 사용한다.
