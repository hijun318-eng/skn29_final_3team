# 기능별 품질 평가와 버전 비교 가이드

## 1. 목적

기능, prompt, model, data pipeline이 바뀔 때 같은 test set으로 재평가해 성능 변화와 회귀를 확인한다. 단순히 “개선됨”이라고 표현하지 않고 version별 근거를 남긴다.

## 2. 저장 구조

```text
evals/
├─ registry.json
├─ testsets/<feature-id>/<testset-version>.jsonl
├─ baselines/<feature-id>/<baseline-version>.json
├─ reports/<feature-id>/<comparison-version>.md
├─ templates/
└─ runs/                     일회성 raw output, Git ignore
```

작고 비식별화된 test set, 승인 baseline, 요약 report는 Git으로 관리한다. 대용량 trace, model response 원본, cache는 `evals/runs/`에 두고 commit하지 않는다.

## 3. Feature 등록

`evals/registry.json`의 각 feature는 다음 정보를 가진다.

- `feature_id`: 안정적인 kebab-case 식별자
- `owner`: GitHub username 또는 team
- `testset_version`
- `baseline_version`
- `metrics`: metric 이름 목록
- `status`: `planned`, `active`, `deprecated`
- `latest_report`: 최신 비교 보고서 경로

아직 기능이 없으므로 registry는 빈 배열로 시작한다. 실제 기능이 생길 때만 entry를 추가한다.

## 4. Test set 원칙

- 정상, 경계, 오류, 회귀 사례를 포함한다.
- 합성 데이터는 생성 scenario와 seed를 기록한다.
- 실제 개인정보나 고객 review 원문을 commit하지 않는다.
- 기대값이 주관적이면 평가 rubric과 허용 기준을 함께 기록한다.
- test set 변경은 기능 개선 commit과 분리한다.
- test set version이 다르면 성능 수치를 직접 비교하지 않는다.

## 5. 평가 절차

1. feature와 평가 목적을 정의한다.
2. 고정 test set과 metric을 확정한다.
3. 현재 version을 실행해 baseline을 저장한다.
4. 기능 변경 후 동일 환경과 test set으로 재실행한다.
5. 절대값, 기존 대비 변화, 실패 사례를 비교한다.
6. threshold 통과 여부와 알려진 제한을 report에 기록한다.
7. 사람이 결과를 검토한 뒤 baseline 승격 여부를 결정한다.

## 6. 보고서 필수 항목

- 비교 대상 version
- code commit 또는 tag
- data/test set version
- prompt/model/config version
- 실행 일시와 환경
- metric별 before/after
- 개선 사례와 회귀 사례
- 실패 원인 가설
- release gate 결과
- 검토자

`evals/templates/QUALITY_REPORT_TEMPLATE.md`를 복사해 사용한다.

## 7. 프로젝트 기능별 후보 지표

아래는 기능이 확정된 뒤 선택할 후보이며 현재 확정 metric이 아니다.

| 기능 | 후보 지표 |
|---|---|
| VOC 감성·주제·긴급도 분류 | macro F1, class별 recall, abstain rate |
| 유사 사례 검색 | Recall@k, Precision@k, MRR, reviewer relevance |
| 이상징후 탐지 | precision, recall, false alarm rate, detection delay |
| 원인 후보 분석 | evidence coverage, unsupported claim rate, reviewer score |
| 리포트 생성 | factual consistency, required-section coverage, citation coverage |

metric 이름만 보고 품질을 판단하지 않는다. 비즈니스 위험이 큰 class에는 별도 threshold와 human review를 둔다.

## 8. Release gate

다음 중 하나라도 해당하면 `dev -> main` PR에 비교 보고서를 첨부한다.

- 사용자에게 보이는 분석 결과 변경
- prompt 또는 model 변경
- preprocessing 또는 schema 변경
- retrieval index 또는 embedding 변경
- metric, threshold, test set 변경

비교가 불가능하면 이유와 재현 가능한 다음 절차를 PR에 명시하고 자동으로 성능 향상이라고 판단하지 않는다.
