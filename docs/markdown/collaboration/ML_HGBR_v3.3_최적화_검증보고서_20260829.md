# ML HGBR v3.3 최적화 검증보고서

- 작성일: 2026-08-29
- 후보 버전: `room-demand-hgbr-occupancy-v3.3.0`
- 최종 모델 계열: `HGBR`
- 선정 유형: WAPE 비열등성 기반 종합 운영 최적
- 운영 승인: `false`

## 1. 최종 판정

HGBR는 WAPE 단독 1위는 아니다. F/G 통합 WAPE 1위는 XGBoost다.

그러나 HGBR는 실행 전에 정한 `경쟁 모델 대비 WAPE 0.20%p 이내` 조건을 통과했고, F/G 네 구간 모두 RMSE와 R2가 1위였으며 Bias 절댓값과 재학습 시간에서도 가장 유리했다. 따라서 심사에서는 HGBR를 `정확도 단일지표 1위`가 아니라 `정확도 비열등성과 운영 품질을 함께 만족한 종합 최적 모델`로 선정하는 것이 타당하다.

| 판정 항목 | 결과 |
|---|---|
| HGBR 시계열 CV 후보 선택 | PASS |
| 2024 Validation 비열등성 | PASS |
| F/G XGBoost 대비 비열등성 | PASS |
| F/G LightGBM 대비 비열등성 | PASS |
| F/G RMSE 4개 구간 1위 | PASS |
| F/G R2 4개 구간 1위 | PASS |
| HGBR WAPE 통계적 단독 우승 | FAIL |
| HGBR 종합 운영 모델 선정 | PASS |
| 실제 PMS 검증 | PENDING |
| Runtime 연동 | PENDING |

## 2. 검증 설계

### 후보 선택 구간

- 2021년 순방향 검증
- 2022년 순방향 검증
- 2023년 순방향 검증

각 연도 검증 시점보다 과거인 데이터만 학습에 사용했다.

### HGBR 후보 14개

- 객실 수 직접 예측
- 4주 동일요일 기준선 대비 객실 수 잔차
- 객실 정원 대비 잔차율
- 객실 정원 대비 점유율
- `squared_error`
- `absolute_error`
- `poisson`
- 31-leaf 기본 구조
- 63-leaf 확장 구조

### 봉인 확인 구간

- 2024 Validation
- 합성 독립 홀드아웃 F Test A/B
- 합성 독립 홀드아웃 G Test A/B

2024와 F/G는 HGBR 후보 선택에 사용하지 않았다.

## 3. 선택된 HGBR 구조

| 항목 | 값 |
|---|---|
| Target | `target_rooms_sold / physical_rooms` |
| Target 의미 | 객실 유형별 점유율 |
| Loss | `squared_error` |
| max_iter | 240 |
| learning_rate | 0.06 |
| max_leaf_nodes | 31 |
| min_samples_leaf | 40 |
| l2_regularization | 0.2 |

예측 시 HGBR가 점유율을 출력하고 이를 실제 객실 정원과 곱한다. 최종 객실 수는 0 이상, 객실 정원 이하로 제한한다.

점유율 Target이 선택된 이유는 규모가 다른 객실 유형을 동일한 비율 단위로 학습하여 대형 객실군이 학습을 과도하게 지배하는 문제를 줄였기 때문이다.

## 4. HGBR 시계열 CV 결과

| 순위 | HGBR 구조 | 평균 WAPE | 최악 연도 WAPE | 표준편차 |
|---:|---|---:|---:|---:|
| 1 | 점유율·squared·31 leaf | 17.008% | 17.351% | 0.265%p |
| 2 | 점유율·squared·63 leaf | 17.045% | 17.399% | 0.275%p |
| 3 | 직접 객실 수·absolute·31 leaf | 17.077% | 17.476% | 0.299%p |
| 4 | 잔차율·squared·31 leaf | 17.078% | 17.480% | 0.314%p |
| 5 | 잔차율·squared·63 leaf | 17.097% | 17.520% | 0.327%p |

단순한 31-leaf 점유율 HGBR가 가장 낮은 평균 WAPE를 기록했다. 더 복잡한 63-leaf 구조는 개선되지 않았다.

## 5. 2024 Validation 비교

| 모델 | WAPE | MAE | RMSE | R2 | Bias |
|---|---:|---:|---:|---:|---:|
| XGBoost | 16.795% | 9.872실 | 18.300 | 0.94930 | -1.848% |
| LightGBM | 16.823% | 9.889실 | 18.333 | 0.94912 | -2.062% |
| HGBR | 16.841% | 9.900실 | **18.229** | **0.94969** | **-0.449%** |

HGBR는 WAPE에서 XGBoost보다 `0.047%p`, LightGBM보다 `0.018%p` 낮은 순위다. 하지만 RMSE, R2, Bias는 가장 좋다.

## 6. F/G 독립 합성 확인

### WAPE

| 구간 | XGBoost | LightGBM | HGBR | WAPE 1위 |
|---|---:|---:|---:|---|
| F Test A | **16.861%** | 16.892% | 16.885% | XGBoost |
| F Test B | 17.234% | 17.286% | **17.229%** | HGBR |
| G Test A | 16.792% | **16.755%** | 16.906% | LightGBM |
| G Test B | 16.805% | 16.798% | **16.713%** | HGBR |

HGBR는 4개 구간 중 2개 구간에서 WAPE 1위다.

### RMSE와 R2

| 구간 | HGBR RMSE | HGBR R2 | 판정 |
|---|---:|---:|---|
| F Test A | 17.866 | 0.95141 | 두 지표 모두 1위 |
| F Test B | 18.872 | 0.94745 | 두 지표 모두 1위 |
| G Test A | 18.273 | 0.94953 | 두 지표 모두 1위 |
| G Test B | 18.428 | 0.94934 | 두 지표 모두 1위 |

HGBR는 F/G 네 구간 모두 RMSE가 가장 낮고 R2가 가장 높다.

### 통합 WAPE

| 순위 | 모델 | F/G 통합 WAPE |
|---:|---|---:|
| 1 | XGBoost | 16.9031% |
| 2 | LightGBM | 16.9104% |
| 3 | HGBR | 16.9253% |

통합 WAPE 차이는 다음과 같다.

- HGBR와 XGBoost 차이: `0.0223%p`
- HGBR와 LightGBM 차이: `0.0149%p`

## 7. 부트스트랩 검증

release, split, target date별 7일 paired moving-block bootstrap을 2,000회 수행했다.

| 비교 | HGBR-경쟁모델 WAPE 차이 95% 신뢰구간 | 상한 | 0.20%p 기준 |
|---|---|---:|---|
| HGBR vs XGBoost | -0.0353%p ~ 0.0790%p | 0.0790%p | PASS |
| HGBR vs LightGBM | -0.0433%p ~ 0.0765%p | 0.0765%p | PASS |

두 신뢰구간 모두 0을 포함한다. 따라서 어느 모델이 통계적으로 더 정확하다고 단정할 수 없다. 반면 신뢰구간 상한은 비열등 기준 `0.20%p`보다 충분히 작다.

## 8. 운영 효율

683,370건 최종 학습 시간은 다음과 같다.

| 모델 | 학습 시간 |
|---|---:|
| HGBR | **7.42초** |
| LightGBM | 10.81초 |
| XGBoost | 85.87초 |

HGBR는 XGBoost보다 약 11.6배, LightGBM보다 약 1.5배 빠르다.

최종 후보 모델 크기는 `931,014 bytes`이며 SHA-256은 다음과 같다.

```text
96b8527372c47341f1432b3b8288b770fabd90ae5bf0a55649bcd7eab2ba3f8c
```

## 9. 심사 대응 선정 논리

실행 전에 다음 규칙을 고정했다.

1. 과거 연도 시계열 CV로 HGBR 구조를 선택한다.
2. XGBoost와 LightGBM의 설정은 이전 비교에서 고정한다.
3. 2024와 F/G 결과로 하이퍼파라미터를 변경하지 않는다.
4. HGBR WAPE 열세의 95% 신뢰구간 상한이 두 경쟁 모델 모두에 대해 `0.20%p` 이하면 HGBR를 운영 모델로 선정한다.
5. 기준을 넘으면 F/G 통합 WAPE 1위 모델을 선정한다.

HGBR는 4번 조건을 통과했으므로 운영 모델로 선정됐다.

발표 권장 문장:

> 순수 통합 WAPE는 XGBoost가 0.022%p 앞섰지만 그 차이는 통계적으로 유의하지 않았습니다. HGBR는 모든 독립 구간에서 RMSE와 R2가 가장 좋았고 Bias와 재학습 시간에서도 우수했습니다. 사전에 정한 WAPE 0.20%p 비열등 기준을 통과해 HGBR를 종합 최적 운영 모델로 선정했습니다.

사용하면 안 되는 문장:

- HGBR가 F/G 통합 WAPE 1위였다.
- HGBR가 XGBoost보다 통계적으로 더 정확했다.
- 실제 PMS 데이터에서 HGBR가 1위로 검증됐다.

## 10. 남은 제한사항

- F/G는 실제 PMS가 아니라 동일 생성기 계열의 합성 홀드아웃이다.
- `0.20%p` 허용 기준의 실제 영업 손실 비용 환산은 아직 없다.
- 저장된 후보는 Runtime 전용 기존 Artifact 계약으로 변환하지 않았다.
- 학습 환경은 `requirements.hgbr-v3.3.txt`로 분리 고정했으며 현재 서비스 Runtime 의존성과 동일하다고 가정하지 않는다.
- Trino Feature 생성과 PostgreSQL provenance 저장 E2E는 아직 수행하지 않았다.
- `production_approved`는 `false`다.

## 11. 증거 파일

- `src/ml/artifacts/room-demand-hgbr-optimization-v3.3.0/hgbr_cv_results.csv`
- `src/ml/artifacts/room-demand-hgbr-optimization-v3.3.0/selection.json`
- `src/ml/artifacts/room-demand-hgbr-optimization-v3.3.0/hgbr_candidate.joblib`
- `src/ml/artifacts/room-demand-hgbr-optimization-v3.3.0/model_manifest.json`
- `src/ml/artifacts/room-demand-hgbr-optimization-v3.3.0/release_checksums.json`

## 12. 최종 결론

- WAPE 단독 관측 1위: `XGBoost`
- WAPE 통계적 단독 우승: `없음`
- F/G RMSE·R2 일관성 1위: `HGBR`
- Bias·재학습 효율 우수: `HGBR`
- 사전 정의 비열등성 통과: `HGBR`
- 종합 최적 운영 모델: `HGBR`
- 실제 운영 승인: `PENDING`
