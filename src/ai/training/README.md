# Answervice SQL 학습 데이터 운영

학습 입력은 사람이 작성하고 검토한 full case spec만 사용한다. 도구는 질문, 메트릭, 자산 식별자, 날짜, SQL 정답을 만들거나 보충하지 않는다. 각 spec은 선택 전에 `dataset.load_specs` 계약 검증을 통과해야 한다.

## Full spec 선택

`build_case_specs`는 검증된 JSONL을 메타데이터로만 필터링하고 원본 record를 변경하지 않은 채 출력한다.

```bash
python -m src.ai.training.build_case_specs \
  /workspace/data/reviewed/full_specs.jsonl \
  /workspace/data/selected/train_validation.jsonl \
  --split train \
  --split validation \
  --review-status APPROVED
```

지원 필터는 `case_id`, `split`, `node`, `review_status`와 deterministic `limit`이다. 제품 도메인이나 특정 지표를 quota로 사용하지 않는다. 불완전 scenario ledger를 받던 기존 `build_case` 경로는 명시적으로 거절하며, `generate_scenarios.py`는 제거됐다.

## Validation ID/OOD 선택

`build_validation_v2`는 train signature를 기준으로 validation record를 ID/OOD로 나눈다. 출력 record는 입력과 동일하며 gold/acceptance record는 선택하지 않는다.

```bash
python -m src.ai.training.build_validation_v2 \
  /workspace/data/reviewed/full_specs.jsonl \
  /workspace/data/selected/validation.jsonl \
  /workspace/data/selected/validation.manifest.json \
  --limit-per-slice 100
```

Signature에는 다음 구조만 포함한다.

- asset grain과 typed column shape
- join 종류, cardinality, temporal/preaggregation 규칙, identifier-free topology
- column-source metric aggregation과 filter/time-field shape
- time interval과 field type/bucket/timezone mode

질문, FQN, URN, 도메인 이름, 실제 날짜, SQL 문자열은 signature에 포함하지 않는다.

## Smoke target 선택

`build_smoke_manifest`는 validation manifest에서 관측된 node/slice/structural-signature strata를 deterministic round-robin으로 선택한다. 과거 제품 도메인별 quota나 이전 평가 결과를 성공 근거로 사용하지 않는다.

```bash
python -m src.ai.training.build_smoke_manifest \
  /workspace/data/selected/validation.manifest.json \
  /workspace/data/selected/smoke.manifest.json \
  --target-size 20
```

## Dataset 검증과 빌드

선택된 full specs는 기존 dataset 도구로 다시 검증하고 학습 메시지로 변환한다.

```bash
python -m src.ai.training.dataset validate /workspace/data/selected/train_validation.jsonl
python -m src.ai.training.dataset build \
  /workspace/data/selected/train_validation.jsonl \
  /workspace/data/compiled/dataset.jsonl
```

`NOT_RUN`은 실행 검증 증거가 아니다. 실행 결과를 주장하려면 별도 검증 경로의 실제 Trino 결과와 hash가 필요하다.
