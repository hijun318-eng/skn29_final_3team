# Answervice ML 공식지표 모델비교 결과보고서

| 항목 | 내용 |
|---|---|
| 버전 | v1.2 |
| 기준일 | 2026-08-10 |
| 검증 대상 | 예약 No-show 이진분류, 객실수요 7일 회귀 |
| 데이터 | 시간 순서로 분리한 합성 PMS 데이터 |
| 선택 원칙 | TRAIN 학습 → VALIDATION 튜닝·선택 → TEST 사후 보고 |
| 지표 구현 | scikit-learn `1.7.2` |

## 1. 결론

| 모델 | 최종 판단 | 근거 |
|---|---|---|
| No-show | `LogisticRegression` 유지 | LightGBM의 Validation AP가 더 높지만 절대 개선폭 `0.002108`로 사전 기준 `0.005` 미달, Brier Score는 89.32% 악화 |
| 7일 수요 | `XGBRegressor` 유지 | Validation·TEST 모두 Seasonal Naive와 LGBM보다 MAE가 낮음 |

이번 비교에서 `pr_auc`로 저장했던 값은 실제 구현상 scikit-learn의 `average_precision_score`다. 따라서 이 보고서에서는 정확한 명칭인 **Average Precision(AP)** 으로 표기한다.

## 2. 학습 데이터 기준

두 모델은 같은 호텔 서비스 시나리오를 표현하지만 같은 학습 CSV를 공유하지 않는다. 현재 산출물만으로는 동일한 물리적 PMS snapshot에서 파생됐다는 계보가 증명되지 않은 독립 합성 데이터셋이다.

| 구분 | No-show 분류 | 7일 객실수요 회귀 |
|---|---|---|
| 한 행의 단위 | `reservation_id` 예약 1건 | `property_id + target_date + room_type_code + horizon_days` |
| Target | `is_no_show` 0·1 | `rooms_sold` 객실 수 |
| 기준 시점 | 도착 전날 18시, Asia/Seoul | 목표일에서 horizon 1~7일 전 |
| 주요 입력 | 예약 리드타임·숙박일수·인원·금액·채널·고객군 | 예약잔량·취소잔량·과거 판매·ADR·요일·계절·수요지수 |
| 학습 파일 | `reservation_no_show_train.csv` | `room_demand_train.csv` |
| 데이터 생성 seed | `20260804` 계열 산출물 | `20260803` |
| 현재 성격 | 과거 합성 규칙 기반 기술검증본 | 합성 시계열 기술검증본 |

### 2.1 No-show 데이터 분할

| Split | 기간 | 행 수 | No-show 수 | 양성률 | 사용 목적 |
|---|---|---:|---:|---:|---|
| TRAIN | 2022-01-01~2024-12-30 | 109,770 | 915 | 0.8336% | 모델 학습 |
| VALIDATION | 2025-01-02~2025-12-31 | 36,600 | 301 | 0.8224% | 튜닝·모델·threshold 선택 |
| TEST | 2026-01-02~2026-07-27 | 20,701 | 159 | 0.7681% | 선택 고정 후 사후 평가 |
| INFERENCE | 2026-07-29~2026-12-25 | 4,359 | 미확정 | 해당 없음 | 예측 입력 |

라벨 1은 `NO_SHOW`, 라벨 0은 정상 체크인·완료다. `CANCELLED` 48,570건과 결과 미확정 미래 예약은 학습에서 제외하는 것이 원칙이다. 결과 컬럼과 실제 체크인 이후 정보는 Feature에서 금지한다.

그러나 현재 CSV의 `label_source`는 `SYNTHETIC_RULE_V1`이고 원천 프로파일의 실제 `NO_SHOW` 상태는 0건이다. 즉 현재 점수는 **과거에 별도로 생성된 합성 학습용 CSV의 기술검증 결과**이며, 현재 PMS 원천으로 재학습된 결과가 아니다. 현재 builder는 `source_snapshot_id`, 추출시각, `outcome_recorded_at`, 실제 `NO_SHOW`가 없으면 재학습을 중단한다.

### 2.2 7일 수요 데이터 분할

| Split | 기간 | 행 수 | 구조 | 사용 목적 |
|---|---|---:|---|---|
| TRAIN | 2022-01-01~2024-12-31 | 30,688 | 4객실유형×1~7 horizon | 모델 학습 |
| VALIDATION | 2025-01-01~2025-12-31 | 10,220 | 동일 grain | 튜닝·모델 선택 |
| TEST | 2026-01-01~2026-07-28 | 5,852 | 동일 grain | 선택 고정 후 평가 |
| FORECAST | 2026-07-29~2026-12-31 | 4,368 | label 비공개 | 예측 Feature |
| Hidden QA | 2026-07-29~2026-12-31 | 624 | 별도 파일 | 합성 미래 정답 QA 전용 |

seed, schema version, scenario version, fixture version, 행 수, 기간과 SHA-256 checksum을 manifest에 기록한다. TRAIN·VALIDATION·TEST의 `rooms_sold`는 null·음수·소수·객실용량 초과를 허용하지 않으며, FORECAST의 label은 비워 둔다.

### 2.3 데이터 계보 판정

| 항목 | No-show | 7일 수요 | 판정 |
|---|---|---|---|
| 학습 CSV SHA-256 | split별 `dataset_manifest.csv`에 존재 | `input_file_hashes.csv`에 존재 | 개별 파일 무결성 확인 가능 |
| 생성 seed | `20260804` | `20260803` | 서로 다름 |
| 생성·추출 시각 | 현재 학습 manifest에 없음 | `2026-08-03 03:00:00+00` | 공통 추출 시각 증명 불가 |
| `source_snapshot_id` | 현재 학습 manifest에 없음 | 없음 | 공통 원천 snapshot 증명 불가 |
| 원천 파일 hash | 과거 외부 경로 기록만 존재 | 학습 CSV hash만 존재 | 동일 PMS 원천 여부 증명 불가 |

따라서 두 모델을 “동일 학습 데이터에 Target만 두 개 적용한 것”으로 설명하면 안 된다. 현재 정확한 표현은 **서로 다른 생성 규칙·seed·grain을 사용한 두 개의 합성 학습 데이터셋**이다. 공통 `source_snapshot_id`, 원천 추출시각과 원천 SHA-256이 두 Feature Set에 함께 기록되기 전에는 공통 원천 계보 Gate를 완료로 판정하지 않는다.

## 3. 맹점과 해석 제한

| 우선순위 | 맹점 | 영향 | 현재 판정 |
|---:|---|---|---|
| P0 | No-show 실제 PMS 원천에 `NO_SHOW`가 0건 | 현재 분류 성능이 원천 라벨 재학습 결과가 아님 | 공식 활성화 차단 |
| P0 | No-show CSV가 `SYNTHETIC_RULE_V1` 라벨 | 생성 규칙을 모델이 학습했을 가능성 | 기술검증 수치로만 사용 |
| P1 | No-show 채널×고객군 조합이 3/9만 존재 | 구조적 결합으로 특정 조합 과대학습 가능 | DQ-10 WARN |
| P1 | TEST의 고정 threshold 경고가 OTA·BUSINESS에만 발생 | CORPORATE·DIRECT·GROUP·LEISURE Recall이 0으로 운영 편향 위험 | 자동 조치 금지 |
| P1 | 두 데이터셋 모두 단일 합성 seed 중심 | 생성 패턴 의존성·분산 미측정 | 복수 seed 필요 |
| P1 | 한 합성 호텔·4개 객실유형 | 다른 호텔·객실구성 일반화 근거 없음 | 외부 적용 금지 |
| P1 | 수요 FORECAST 전체의 최대 Feature null 비율 92.95% | 먼 미래 cutoff를 임의 호출하면 결측 위험 | 현재 기준일의 완전한 28행만 허용 |
| P1 | 수요 전처리기가 숫자 결측을 median으로 대체 | 예약잔량 같은 핵심 Feature 결측도 조용히 대체될 수 있음 | 운영 편입 전 fail-closed 검증 필요 |
| P1 | 수요의 미학습 범주값을 one-hot zero로 처리 | 범주 drift가 응답 경고에 나타나지 않음 | 운영 편입 전 범주 경고 필요 |
| P1 | Hidden QA도 같은 합성 생성 체계 | 독립 외부 검증셋이 아님 | QA 보조 근거만 인정 |
| P2 | No-show 양성률 약 0.8% | Accuracy·ROC-AUC만 보면 성능 과대평가 가능 | AP·Brier·혼동행렬 우선 |
| P2 | XGB·LGB TEST 사후 비교 | 반복 사용 시 TEST가 Validation처럼 오염될 위험 | 현 결과 이후 재튜닝 금지 |
| P2 | 수요 TRAIN 대비 VALIDATION 오차 증가 | 합성 기간 패턴 또는 과적합 가능 | rolling·실데이터 검증 필요 |

## 4. 예외처리 규칙

### 4.1 학습 데이터

| 예외 | 처리 규칙 |
|---|---|
| 필수 CSV·필수 컬럼 누락 | 학습 시작 전 실패 |
| Split 기간 중첩 | 학습 중단 |
| key 중복 | 학습 중단 |
| No-show target 누락·0/1 이외 | 학습 중단 |
| 실제 라벨 결과시점이 cutoff 이전 또는 불명확 | 해당 행 제외, 원천 전체가 불충분하면 재학습 중단 |
| No-show 원천 `NO_SHOW=0` | 공식 재학습 중단 |
| 취소·미확정 예약 | No-show 학습에서 제외 |
| 수요 label 음수·소수·용량 초과 | 학습 중단 |
| FORECAST label 노출 | 미래정보 누수로 간주하고 중단 |
| manifest 행 수·기간·version 불일치 | 학습 중단 |
| 단일 Feature 전체 null·무한대 | 학습 중단 |

### 4.2 모델 선택과 평가

| 예외 | 처리 규칙 |
|---|---|
| 튜닝 결과가 기준모델보다 최소 개선폭 미달 | 기준모델 유지 |
| AP 개선, Brier 악화 | 확률 출력 모델로 교체하지 않음 |
| Validation으로 threshold 선택 후 TEST 재조정 | 금지 |
| TEST 결과를 보고 파라미터 변경 | 새 holdout을 만들기 전 금지 |
| 양성 0건인 평가 구간 | AP·Recall 해석 불가로 명시, 성공 판정 금지 |

### 4.3 추론 runtime

| 예외 | 외부 상태·처리 |
|---|---|
| Feature·input schema version 불일치 | `SCHEMA_MISMATCH`, 모델 호출 금지 |
| No-show timezone 없는 기준시점 | `INVALID_INPUT` |
| 예약 Feature 0건 | `FEATURE_NOT_FOUND` |
| 예약 Feature 또는 ranking 중복 | `INVALID_INPUT`, 첫 행 임의 선택 금지 |
| No-show 모델 Feature 컬럼 누락·null | `INVALID_INPUT`, ONNX 호출 금지 |
| No-show ONNX SHA-256 불일치 | 서비스 시작 중단 |
| 수요 model SHA-256 불일치 | `joblib.load()` 전에 서비스 시작 중단 |
| 수요 입력이 1~7일×4객실유형 28행이 아님 | `INVALID_INPUT` |
| 수요 key 중복·예측구간 margin 누락 | 예측 실패 |
| 수요 필수 컬럼 자체 누락 | 현재 `MODEL_ERROR`; 운영 편입 전 `INVALID_INPUT`으로 명시화 필요 |
| 수요 필수 예약잔량 값 null | 현재 median 대체 가능; 운영 편입 전 예측 중단 규칙 필요 |
| 수요 학습범위 밖 Feature | 예측은 반환하되 `input_range_warning=true`와 Feature명을 표시 |
| 수요 예측이 음수·객실용량 초과 | 0~`available_room_nights` 범위로 반올림·clip |
| 학습에 없던 범주값 | 현재 One-hot unknown으로 조용히 처리; 운영 편입 전 drift 경고 필요 |
| 예상하지 못한 내부 오류 | 고정된 `MODEL_ERROR`; 내부 예외문자열 외부 노출 금지 |
| timeout | 오류 반환, 관측 사실로 대체 금지; process hard cancellation은 아직 미완료 |

## 5. 공인 지표 기준

아래 지표는 프로젝트가 새로 만든 공식이 아니라 scikit-learn이 제공하는 표준 평가 함수다. 전체 분류·회귀 지표 정의는 [scikit-learn Model evaluation](https://scikit-learn.org/stable/modules/model_evaluation.html)을 기준으로 한다.

| 문제 | 지표 | 구현 | 방향 | 사용 목적 |
|---|---|---|---|---|
| 이진분류 | Average Precision | `average_precision_score` | 높을수록 좋음 | 희소한 No-show 양성의 Precision-Recall 품질 |
| 이진분류 | ROC-AUC | `roc_auc_score` | 높을수록 좋음 | 전체 순위 분리력 보조 확인 |
| 이진분류 | Precision·Recall·F1 | `precision_score`, `recall_score`, `f1_score` | 높을수록 좋음 | Validation에서 정한 threshold의 판정 성능 |
| 이진분류 | Brier Score | `brier_score_loss` | 낮을수록 좋음 | 확률과 실제 0·1 결과의 제곱오차 |
| 이진분류 | Confusion Matrix | `confusion_matrix` | TN·FP·FN·TP 확인 | 오류 종류와 업무 영향 확인 |
| 회귀 | MAE | `mean_absolute_error` | 낮을수록 좋음 | 평균 객실 오차, 단위는 객실 수 |
| 회귀 | RMSE | `sqrt(mean_squared_error)` | 낮을수록 좋음 | 큰 오차에 더 민감한 객실 오차 |
| 회귀 | R² | `r2_score` | 1에 가까울수록 좋음 | 데이터 분산 설명력 |

AP, Brier, MAE, RMSE의 상세 정의는 각각 [Average Precision](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html), [Brier Score](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html), [MAE](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.mean_absolute_error.html), [RMSE](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.root_mean_squared_error.html) 공식 문서를 따른다.

`Recall@Top15%`, `Precision@Top15%`, `Lift@Top15%`, WAPE는 운영 해석을 위한 보조지표다. 모델의 공식 성능지표와 섞어 주 지표로 사용하지 않는다.

## 6. No-show 베이스라인 비교

### 6.1 TRAIN

| 모델 | 행 수 | AP | ROC-AUC | Precision | Recall | F1 | Brier |
|---|---:|---:|---:|---:|---:|---:|---:|
| Prior Probability | 109,770 | 0.008336 | 0.500000 | 0.008336 | 1.0000 | 0.016533 | 0.008266 |
| LogisticRegression | 109,770 | 0.014759 | 0.676530 | 0.016284 | 0.3399 | 0.031078 | 0.008238 |
| LogisticRegression Balanced | 109,770 | 0.014731 | 0.676921 | 0.016910 | 0.1443 | 0.030272 | 0.227759 |
| HistGradientBoosting | 109,770 | 0.027040 | 0.733047 | 0.023726 | 0.3792 | 0.044659 | 0.008218 |

TRAIN은 학습 적합도와 과적합 징후 확인용이며 모델 선정에는 사용하지 않는다. HistGradientBoosting AP가 TRAIN `0.027040`에서 VALIDATION `0.016187`로 하락하므로 복잡한 모델의 과적합 위험을 함께 본다.

### 6.2 VALIDATION

VALIDATION 36,600건, 양성 301건, 발생률 `0.8224%` 기준이다.

| 모델 | 역할 | AP | ROC-AUC | Precision | Recall | F1 | Brier |
|---|---|---:|---:|---:|---:|---:|---:|
| Prior Probability | 확률 기준선 | 0.008224 | 0.500000 | 0.008224 | 1.0000 | 0.016314 | 0.008156 |
| LogisticRegression | 선형 기준모델 | 0.014298 | 0.666458 | 0.016393 | 0.2990 | 0.031083 | 0.008131 |
| LogisticRegression Balanced | 불균형 가중 기준 | 0.014362 | 0.665960 | 0.015116 | 0.2757 | 0.028660 | 0.246276 |
| HistGradientBoosting | 비선형 후보 | 0.016187 | 0.668645 | 0.017100 | 0.3123 | 0.032425 | 0.008130 |

LogisticRegression AP는 단순 발생률 기준선보다 `73.86%` 높다. Balanced 모델은 AP가 거의 같지만 Brier Score가 크게 악화되어 확률 출력용으로 부적절하다.

## 7. No-show 튜닝 모델 비교

튜닝은 VALIDATION에서만 수행했다. 총 16개 설정은 LightGBM 7개, XGBoost 7개, RandomForest 2개다. 아래 표는 각 계열의 AP 1위 설정이다.

| 모델 계열 | 최적 설정 | Validation AP | ROC-AUC | Brier | Recall@15% | Precision@15% | Lift@15% |
|---|---|---:|---:|---:|---:|---:|---:|
| LightGBM | `scale_pos_weight=10` | 0.016406 | 0.649407 | 0.015394 | 0.3023 | 0.016576 | 2.0155 |
| RandomForest | `class_weight=None` | 0.014605 | 0.660073 | 0.008137 | 0.3056 | 0.016758 | 2.0377 |
| XGBoost | `scale_pos_weight=1` | 0.014629 | 0.649420 | 0.008151 | 0.3056 | 0.016758 | 2.0377 |

LightGBM은 LogisticRegression보다 AP가 `14.74%` 높지만 절대 차이는 `0.002108`이다. 사전에 정한 최소 개선폭 `0.005`를 넘지 못했고 Brier Score는 LogisticRegression보다 `89.32%` 높아 확률 신뢰성이 나빠졌다. LightGBM 공식 문서도 불균형 가중치가 개별 클래스 확률 품질을 떨어뜨릴 수 있어 보정을 검토하라고 안내한다. 따라서 복잡한 모델로 교체하지 않은 결정이 타당하다. [LightGBM 공식 문서](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMClassifier.html)

XGBoost의 `scale_pos_weight`는 불균형 클래스의 가중 균형을 위한 공식 파라미터다. 이번 데이터에서는 가중치를 높인 설정보다 기본값 1이 가장 높아, 무조건 `음성/양성 비율`을 적용하면 좋아진다는 근거가 없었다. [XGBoost 공식 파라미터](https://xgboost.readthedocs.io/en/stable/parameter.html)

## 8. No-show 최종 TEST

TEST 20,701건, 양성 159건, 발생률 `0.7681%`다. TEST는 LogisticRegression 선택을 고정한 뒤 평가했다.

| AP | ROC-AUC | Precision | Recall | F1 | Brier | AP/발생률 | 고정 threshold 경고율 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.013561 | 0.682746 | 0.014467 | 0.308176 | 0.027637 | 0.007600 | 1.766배 | 16.36% |

| 실제\예측 | 정상 | No-show |
|---|---:|---:|
| 정상 | TN 17,204 | FP 3,338 |
| No-show | FN 110 | TP 49 |

위 혼동행렬은 Validation에서 정한 고정 threshold `0.015165`를 TEST에 그대로 적용한 결과다. 일별 업무량을 정확히 15%로 제한하는 별도 ranking 정책은 다음과 같다.

| 정책 | 선택 행 수 | Recall@15% | Precision@15% | Lift@15% | TEST score cutoff |
|---|---:|---:|---:|---:|---:|
| TEST 상위 15% | 3,106 | 0.289308 | 0.014810 | 1.9282배 | 0.015392 |

고정 threshold와 Top15는 같은 지표가 아니다. 운영에서는 일별 처리량을 고정하는 Top15를 사용하되, 실제 일일 최대 연락 건수 승인이 추가로 필요하다.

TEST subgroup에서는 OTA·BUSINESS에만 경고가 발생했고 해당 그룹 Recall은 각각 `0.50`이었다. CORPORATE·DIRECT·GROUP·LEISURE의 Recall은 모두 `0`이었다. 이는 고객 특성에 따른 실제 일반화 근거가 아니라 합성 채널×고객군 결합의 영향일 가능성이 높으므로 고객 불이익·자동 취소·보증금 부과에 사용하면 안 된다.

확률 보정 보조검사에서 ECE는 VALIDATION `0.001501`, TEST `0.001785`였고 추가 calibration은 적용하지 않았다. 다만 ECE 역시 같은 합성 데이터 기준이므로 실제 확률 신뢰성을 보증하지 않는다.

판정은 명확하다. 무작위보다 순위 효율은 높지만 자동 취소·제재용 성능은 아니다. 상위 위험 예약의 연락 순서를 정하는 보조 모델까지만 허용한다.

## 9. 7일 객실수요 베이스라인·튜닝 비교

Seasonal Naive는 같은 객실유형의 7일 전 실적을 사용하는 시계열 기준선이다. XGB와 LGBM은 동일 TRAIN·VALIDATION과 early stopping 조건으로 비교했다.

### 9.1 TRAIN

Seasonal Naive가 계산 가능한 공통 구간 30,492행 기준이다. 원본 TRAIN 30,688행과 평가 행 수가 다른 이유는 7일 전 실적이 없는 최초 구간 196행을 동일 비교에서 제외했기 때문이다.

| 모델 | 행 수 | MAE | RMSE | R² | WAPE 보조 |
|---|---:|---:|---:|---:|---:|
| Seasonal Naive | 30,492 | 4.6178실 | 7.4897실 | 0.950736 | 10.5557% |
| XGBRegressor | 30,492 | 0.4591실 | 0.7670실 | 0.999483 | 1.0495% |
| LGBMRegressor | 30,492 | 0.5026실 | 0.8150실 | 0.999417 | 1.1488% |

XGB의 TRAIN MAE `0.4591실`이 VALIDATION `0.9141실`보다 크게 낮아 일반화 간격이 존재한다. 다만 Validation·TEST가 모두 Seasonal Naive보다 낮고 rolling 검증에서도 유지되는지 함께 판단한다.

### 9.2 Validation

| 모델 | 역할 | 행 수 | MAE | RMSE | R² | WAPE 보조 |
|---|---|---:|---:|---:|---:|---:|
| Seasonal Naive | 시계열 기준선 | 10,220 | 4.7452실 | 7.6190실 | 0.954006 | 10.1987% |
| XGBRegressor | 튜닝 후보·선정 | 10,220 | 0.9141실 | 1.4813실 | 0.998261 | 1.9646% |
| LGBMRegressor | 튜닝 후보 | 10,220 | 0.9253실 | 1.4847실 | 0.998253 | 1.9888% |

XGB의 MAE는 Seasonal Naive보다 `80.74%` 낮다. XGB와 LGBM의 차이는 작지만 세 공식 지표 모두 XGB가 근소하게 우수해 XGB를 선택했다.

### 9.3 Test 사후 확인

| 모델 | 역할 | 행 수 | MAE | RMSE | R² | WAPE 보조 |
|---|---|---:|---:|---:|---:|---:|
| Seasonal Naive | 시계열 기준선 | 5,852 | 4.6172실 | 7.3371실 | 0.955596 | 10.0594% |
| XGBRegressor | 선정 모델 | 5,852 | 0.7994실 | 1.3084실 | 0.998588 | 1.7416% |
| LGBMRegressor | 선정 후 사후 감사 | 5,852 | 0.8038실 | 1.3172실 | 0.998569 | 1.7513% |

XGB TEST MAE는 Seasonal Naive보다 `82.69%` 낮다. LGBM과의 MAE 차이는 `0.0044실`뿐이므로 두 부스팅 모델이 실질적으로 비슷하다는 해석도 함께 유지한다.

### 9.4 시간·그룹·불확실성 보조검증

| 검증 | 결과 | 해석 |
|---|---|---|
| 2025 계절별 rolling WAPE | 1.73%~2.03% | 네 계절 모두 Seasonal Naive 8.09%~12.31%보다 낮음 |
| TEST horizon별 clipped MAE | 1일 0.6435실 → 7일 0.9605실 | 먼 horizon에서 오차 증가 |
| TEST 객실유형별 clipped MAE | RESIDENCE 0.2098실, STANDARD 1.6042실 | 객실 수 규모가 달라 절대 MAE 직접 비교 주의 |
| 95% 예측구간 | 포함률 98.67%, 평균 폭 4.79실 | 합성 TEST에서 보수적 구간 |
| 학습범위 이탈 | `inbound_travel_index` WARN | 현재 28행 응답에 경고 표시 |

예측구간은 Validation residual로 만든 경험적 구간이며 실제 운영의 통계적 95% 보장을 의미하지 않는다.

## 10. 객관성 한계

- 지표 공식과 구현은 공인 라이브러리를 사용했지만 평가 데이터는 자체 합성 데이터다.
- 따라서 이 수치는 외부 호텔이나 실제 운영 성능을 보증하지 않는다.
- No-show 라벨 `SYNTHETIC_RULE_V1`과 단일 seed 의존성이 남아 있다.
- 튜닝 비교는 제한된 탐색이며 대규모 AutoML 최적화 결과가 아니다.
- TEST 비교 결과는 이후 재튜닝 근거로 사용하지 않는다.
- 실제 비식별 PMS 데이터와 독립된 외부 평가셋이 확보되어야 운영 성능으로 승격할 수 있다.

### 10.1 아직 측정되지 않은 항목

| 항목 | 상태 | 완료 기준 |
|---|---|---|
| No-show AP·Recall 신뢰구간 | 미측정 | 시간 단위 block bootstrap 등으로 불확실성 범위 산출 |
| 복수 합성 seed 분산 | 미측정 | 최소 5개 seed에서 모델 순위·지표 변동 확인 |
| 공통 원천 계보 | 미완료 | 두 Feature Set에 동일 `source_snapshot_id`·추출시각·원천 SHA-256 기록 |
| 실제 비식별 데이터 외부검증 | Blocked | 별도 승인 데이터에서 동일 시간 분할 평가 |
| 일일 연락 비용·최대 건수 | 승인 대기 | Top 비율과 일일 최대 건수를 함께 확정 |
| 운영 drift 기준선 | 미측정 | 입력 분포·양성률·성능 저하 경보 기준 확정 |
| 수요 핵심 Feature 결측 fail-closed | 미구현 | 예약잔량 null이면 `INVALID_INPUT` 반환 |
| 수요 범주 drift 경고 | 미구현 | 미학습 범주값을 응답·감사 로그에 기록 |
| 운영 latency·동시성 | 미측정 | 배포 경계에서 p50·p95·p99와 2초 hard timeout 측정 |
| 7일 수요 ONNX parity | 미구현 | P2 후보 편입 시 ONNX 변환·runtime 일치 검증 |
| UI·영구 감사·인증 포함 E2E | 미검증 | 실제 서비스 경계에서 통합 검증 |

이 표의 항목은 실패를 숨긴 “향후 과제”가 아니라 현재 결과의 사용 범위를 제한하는 미완료 Gate다.

## 11. 생성 산출물

| 산출물 | 내용 |
|---|---|
| `reservation_no_show/artifacts/official_model_comparison.csv` | No-show 기준·후보·선정 모델의 공식 지표 |
| `reservation_no_show/artifacts/official_tuning_comparison.csv` | 16개 튜닝 설정 전체 비교 |
| `room_demand_forecast/artifacts/official_model_comparison.csv` | Seasonal Naive·XGB·LGB의 split 비교 |
| `artifacts/official_metric_manifest.json` | 지표 정책, 파일 행 수, SHA-256 |

## 변경 내역

| 버전 | 일자 | 내용 |
|---|---|---|
| v1.2 | 2026-08-10 | TRAIN 비교, 독립 합성 데이터 계보, threshold·Top15 구분, subgroup 편향, rolling·horizon·예측구간 및 미측정 Gate 추가 |
| v1.1 | 2026-08-10 | 모델별 학습 데이터 분리, 라벨·분할 기준, 맹점과 학습·선택·runtime 예외처리 추가 |
| v1.0 | 2026-08-10 | 공인 지표 기준, 베이스라인·튜닝·TEST 비교와 객관성 한계 최초 작성 |
