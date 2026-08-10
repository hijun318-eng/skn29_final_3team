# Answervice sLLM RunPod 재구축

| 항목 | 내용 |
|---|---|
| 문서 설명 | 합성 Text-to-SQL 데이터, 공통 평가, QLoRA와 RunPod 실행의 단일 기준 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.2 |
| 문서 기준일 | 2026-08-05 00:00 |
| 작성·수정 | 윤대성 |

## 확인된 사실

- 데이터 원천은 5개 합성 source와 `serving.analytics` View이며 Trino는 조회 전용이다.
- GPU 모델 다운로드, 실제 Trino 실행, 네 모델 평가와 QLoRA 학습은 로컬에서 실행하지 않았다.
- 모델 revision은 Hugging Face API로 확인한 2026-08-05 기준 commit이다.

## 이번 결정

- 비교 대상은 Qwen3-4B-Instruct-2507, Qwen3.5-9B, Gemma 4 12B IT, Kanana 2 3B Instruct의 zero-shot과 Qwen3.5-9B BF16 LoRA다.
- 새 데이터는 결정론적 Python으로 600/150/120/30 train/validation/gold/acceptance split을 생성한다. scenario family는 split을 넘지 않는다.
- 생성과 평가는 `do_sample=False`와 고정 `max_new_tokens`를 사용한다. 학습에는 temperature를 적용하지 않는다.
- 기본 학습은 BF16 LoRA다. RunPod smoke에서 실제 named module을 확인하고 vision/audio 모듈을 제외한 뒤 시작한다. OOM 조정 후에도 불가할 때만 NF4 QLoRA로 전환하며 전환 근거를 manifest에 기록한다.
- Qwen3.5 고정 tokenizer로 모든 split의 input·answer·전체 token을 측정해 max sequence length를 결정한다. audit PASS와 초과 사례 0건 전에는 학습을 차단한다.

## RunPod 실행 순서

1. `python run_pipeline.py preflight`로 30GB 이상 여유 공간, CUDA/BF16, 모델 revision을 확인한다.
2. `python run_pipeline.py all`로 데이터 생성·검증, 동일 Validation 평가, QLoRA smoke와 결과 패키징을 실행한다.
3. 데이터 누수, SQL 정책, text-only template, 4-bit/BF16, LoRA target 중 하나라도 실패하면 학습을 중단한다.

## 가정 및 추가 확인

- 권장 환경은 동일 SKU의 48GB BF16 GPU와 150GB 이상 Persistent Volume이다.
- 각 모델 라이선스 수용, 모델 download 접근 권한, Trino endpoint, 실제 결과 fixture는 RunPod 실행 직전에 다시 확인한다.
- 실제 측정 전 성능, 비용, latency, VRAM 수치는 확정하지 않는다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.2 | 2026-08-05 00:00 | Qwen3.5 tokenizer audit과 길이 초과 학습 차단, 출력 상한 도달 기록을 추가 |
| v1.1 | 2026-08-05 00:00 | 기본 학습을 BF16 LoRA로 전환하고 OOM 근거 기반 QLoRA fallback만 허용 |
| v1.0 | 2026-08-05 00:00 | 기존 sLLM 산출물을 정리하고 재현 가능한 RunPod 재구축 기준을 새로 작성 |
