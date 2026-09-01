# 합성 Hidden Test에서 WAPE 16.260%를 기록한 HGBR V2.2 객관적 결과지표서

| 항목 | 내용 |
|---|---|
| 문서 설명 | 객실 수요예측 HGBR V2.2의 저장 artifact를 기준으로 제출 가능한 성능·일반화·기준선 개선·재현성·운영 준비도 지표를 정리한 결과서 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-09-01 12:39 |
| 작성·수정 | Codex |
| 문서 ID | `ML-ROOM-DEMAND-V22-OBJECTIVE-METRICS-20260901` |
| 기준 모델 | `room-demand-timeseries-hgbr-v2.2.0` |
| 데이터 릴리스 | `room-demand-timeseries-d1-d10-v2.0.0` |
| 모델 상태 | `FROZEN_CANDIDATE` |
| 저장 판정 | `CONDITIONAL_PASS`, `VALIDATED_SYNTHETIC` |
| 제출 판정 | 합성 데이터 검증 결과로는 제출 가능, 실제 운영 성능 증거로는 사용 불가 |

## 1. 제출용 핵심 판정

HGBR V2.2는 합성 Validation과 독립 Hidden Test A·B에서 저장된 모든 성능 gate를 통과했다. Hidden Test A·B를 가중 통합하면 MAE 9.588실, RMSE 17.619, WAPE 16.260%이며 저장 기준선보다 WAPE가 10.752% 상대 개선됐다.

그러나 학습과 평가 데이터는 실제 PMS 관측값이 아닌 합성 데이터다. Train 성능, D+1~D+7 개별 지표, 실제 추론시간, 통계적 신뢰구간도 artifact에 저장되지 않았다. 따라서 제출 시 모델 개발·합성 검증 결과로는 사용할 수 있지만 실제 호텔 운영 정확도나 운영 승인 완료로 표현하면 안 된다.

| 판정 항목 | 결과 | 근거 |
|---|---|---|
| Validation WAPE 18% 이하 | PASS | 17.532% |
| Hidden Test A WAPE 18% 이하 | PASS | 16.212% |
| Hidden Test B WAPE 18% 이하 | PASS | 16.331% |
| 기준선 대비 WAPE 8% 이상 개선 | PASS | A 10.476%, B 11.161% |
| 고수요 객실유형 WAPE 30% 이하 | PASS | A 24.161%, B 26.028% |
| 저수요 객실유형 MAE 3실 이하 | PASS | A 2.871실, B 2.950실 |
| D+10 WAPE 20% 이하 | PASS | A 16.109%, B 16.477% |
| 절대 Bias 5% 이하 | PASS | A 0.303%, B 1.597% |
| 음수·수용량 초과 예측 | PASS | 저장 위반 0건 |
| 실제 PMS 평가 | 미완료 | 데이터가 합성임 |
| 실제 운영 승인 | 미완료 | 승인자·승인시각 없음 |

## 2. 모델과 평가 대상

| 항목 | 값 |
|---|---|
| 알고리즘 | `HistGradientBoostingRegressor` |
| 모델 유형 | 과거 일별 실적 기반 다중 Horizon HGBR |
| 최종 예측값 | 객실유형별 판매 객실 수 `rooms_sold` |
| 내부 학습 Target | 4주 동일요일 값 대비 잔차율 `residual_rate` |
| 입력 특징 | 44개 |
| 지원 범위 | D+1~D+10 |
| 제출 관심 범위 | D+1~D+7 |
| 학습 행 | 227,790행 |
| 모델 파일 크기 | 1,361,774 bytes |
| 모델 SHA-256 | `5b0a8a896bf87dd2516129d52599bf183c05dd7bc154e17b570851ca1e1564fa` |
| 합성 학습 데이터 | `true` |
| Test 학습 사용 | `false` |
| 2026년 9월 관측값 사용 | `false` |

### 선택된 HGBR 설정

| 설정 | 값 |
|---|---:|
| scope | `global` |
| loss | `squared_error` |
| target mode | `residual_rate` |
| learning rate | 0.045 |
| max iter | 360 |
| max leaf nodes | 31 |
| min samples leaf | 40 |
| L2 regularization | 2.0 |
| random state | 20260826 |
| seasonal blend weight | 1.0 |

## 3. 데이터 분할과 독립성

| 구분 | 기간 | 행 수 | 사용 목적 |
|---|---|---:|---|
| Train | 2018-01-07~2023-12-21 | 227,790 | 모델 학습 |
| Validation | 2024-01-01~2024-12-21 | 32,040 | 후보 선택·성능 확인 |
| Hidden Test A | `HIDDEN_TEST_D` split A, 세부 날짜 미기록 | 31,950 | 독립 시험 |
| Hidden Test B | `HIDDEN_TEST_D` split B, 세부 날짜 미기록 | 20,970 | 독립 시험 |

승인 artifact에는 알려진 Test 기간이 `2025-01-01~2025-12-21`, `2026-01-01~2026-08-21`로 기록돼 있다. 독립 성능의 주 근거는 별도 release인 `HIDDEN_TEST_D-seed-20260904` 결과다.

- 시간 순서대로 Train, Validation, Test를 분리했다.
- `test_seen_by_trainer=false`로 기록돼 있다.
- 2026년 9월 관측값은 학습·평가에 사용하지 않았다.
- 데이터는 Walkerhill 구조를 모사한 합성 자료이며 실제 PMS 데이터가 아니다.

## 4. 평가 지표 정의

| 지표 | 계산식 | 해석 |
|---|---|---|
| MAE | `mean(abs(예측-실제))` | 평균적으로 몇 실 차이 나는지 나타냄 |
| RMSE | `sqrt(mean((예측-실제)^2))` | 큰 오차에 더 큰 가중치를 부여함 |
| WAPE | `sum(abs(예측-실제)) / sum(abs(실제))` | 전체 수요 대비 절대오차 비율 |
| Bias | `sum(예측-실제) / sum(abs(실제))` | 음수는 과소예측, 양수는 과대예측 |
| MASE | `모델 MAE / 기준선 MAE` | 1보다 작으면 기준선보다 우수함 |
| R² | `1 - SSE/SST` | 수요 변동 설명력을 나타내는 보조지표 |
| 기준선 개선율 | `1 - 모델 WAPE/기준선 WAPE` | 기준선 대비 WAPE 상대 감소율 |

저장 artifact에는 기준선 수치가 있지만 어떤 후보 기준선이 최종 선택됐는지 이름이 기록되지 않았다. 따라서 이 문서에서는 이를 `저장 기준선`으로 표기하며 임의로 전일값 또는 4주 동일요일 기준선이라고 단정하지 않는다.

## 5. Validation 결과

| 지표 | HGBR V2.2 | 저장 기준선 | 차이·개선 |
|---|---:|---:|---:|
| 행 수 | 32,040 | 32,040 | 동일 |
| 실제 객실 수 합계 | 1,882,749 | 1,882,749 | 동일 |
| 실제 평균 | 58.762실 | 58.762실 | 동일 |
| MAE | 10.302실 | 11.498실 | 10.398% 감소 |
| RMSE | 18.980 | 21.113 | 10.101% 감소 |
| WAPE | 17.532% | 19.566% | 10.398% 감소 |
| MASE | 0.896 | 1.000 | 기준선보다 우수 |
| R² | 0.94415 | 0.93089 | 0.01326 증가 |
| Bias | -0.535% | -0.047% | HGBR가 더 과소예측 |

Validation에서 HGBR는 MAE·RMSE·WAPE·R²가 저장 기준선보다 좋았다. Bias 절댓값은 HGBR가 더 크지만 승인 한도 5% 이내다.

### Validation 취약구간 지표

| 항목 | 결과 | 기준 | 판정 |
|---|---:|---:|---|
| 고수요 객실유형 최악 WAPE | 24.723% | 30% 이하 | PASS |
| 저수요 객실유형 최악 MAE | 2.851실 | 3실 이하 | PASS |
| D+10 WAPE | 17.595% | 20% 이하 | PASS |
| raw 음수 예측 | 0건 | 0건 | PASS |
| raw 수용량 초과 | 0건 | 0건 | PASS |
| clipping 후 범위 위반 | 0건 | 0건 | PASS |

## 6. Hidden Test A 결과

| 지표 | HGBR V2.2 | 저장 기준선 | 차이·개선 |
|---|---:|---:|---:|
| 행 수 | 31,950 | 31,950 | 동일 |
| 실제 객실 수 합계 | 1,872,175 | 1,872,175 | 동일 |
| 실제 평균 | 58.597실 | 58.597실 | 동일 |
| MAE | 9.500실 | 10.611실 | 10.476% 감소 |
| RMSE | 17.538 | 19.362 | 9.420% 감소 |
| WAPE | 16.212% | 18.109% | 10.476% 감소 |
| MASE | 0.895 | 1.000 | 기준선보다 우수 |
| R² | 0.95196 | 0.94145 | 0.01051 증가 |
| Bias | -0.303% | -0.001% | 승인 한도 이내 |

| 취약구간 항목 | 결과 | 기준 | 판정 |
|---|---:|---:|---|
| 고수요 객실유형 최악 WAPE | 24.161% | 30% 이하 | PASS |
| 저수요 객실유형 최악 MAE | 2.871실 | 3실 이하 | PASS |
| D+10 WAPE | 16.109% | 20% 이하 | PASS |

## 7. Hidden Test B 결과

| 지표 | HGBR V2.2 | 저장 기준선 | 차이·개선 |
|---|---:|---:|---:|
| 행 수 | 20,970 | 20,970 | 동일 |
| 실제 객실 수 합계 | 1,248,389 | 1,248,389 | 동일 |
| 실제 평균 | 59.532실 | 59.532실 | 동일 |
| MAE | 9.722실 | 10.944실 | 11.161% 감소 |
| RMSE | 17.742 | 19.991 | 11.250% 감소 |
| WAPE | 16.331% | 18.383% | 11.161% 감소 |
| MASE | 0.888 | 1.000 | 기준선보다 우수 |
| R² | 0.95192 | 0.93895 | 0.01296 증가 |
| Bias | -1.597% | -0.310% | 승인 한도 이내 |

| 취약구간 항목 | 결과 | 기준 | 판정 |
|---|---:|---:|---|
| 고수요 객실유형 최악 WAPE | 26.028% | 30% 이하 | PASS |
| 저수요 객실유형 최악 MAE | 2.950실 | 3실 이하 | PASS, 한도와 0.050실 차이 |
| D+10 WAPE | 16.477% | 20% 이하 | PASS |

저수요 객실유형 최악 MAE는 3실 gate에 근접했다. 합성 Test에서는 통과했지만 실제 데이터 재평가에서 우선 확인해야 하는 위험 지표다.

## 8. Hidden Test A·B 가중 통합 지표

다음 수치는 저장된 Test A·B의 행 수, 실제 합계, 절대오차합과 제곱오차합을 이용해 이 문서에서 가중 집계한 값이다. artifact에 별도 통합 레코드로 저장된 값은 아니다.

| 지표 | HGBR V2.2 | 저장 기준선 | 차이·개선 |
|---|---:|---:|---:|
| 총 행 수 | 52,920 | 52,920 | 동일 |
| 실제 객실 수 합계 | 3,120,564 | 3,120,564 | 동일 |
| MAE | 9.588실 | 10.743실 | 10.752% 감소 |
| RMSE | 17.619 | 19.614 | 10.169% 감소 |
| WAPE | 16.260% | 18.218% | 10.752% 감소 |
| Bias | -0.821% | -0.125% | HGBR의 과소예측이 더 큼 |

R²는 분할별 실제 평균과 전체 제곱합 원본이 없으면 정확히 통합할 수 있으므로 합성하지 않았다.

## 9. Rolling-origin 일반화 결과

| 항목 | 결과 |
|---|---:|
| fold 수 | 3 |
| 평균 WAPE | 16.783% |
| WAPE 표준편차 | 0.351%p |
| 최악 fold WAPE | 17.190% |
| WAPE 변동계수 | 2.090% |
| 평균 기준선 개선율 | 9.585% |
| 모든 fold 기준선 개선 | `true` |

세 fold에서 모두 기준선을 개선했고 WAPE 변동계수도 낮았다. 이는 합성 시계열 안에서 성능이 한 구간에만 집중되지 않았다는 증거다. 실제 PMS 환경의 일반화를 증명하지는 않는다.

### 알려진 Test 재현 결과

다음 값은 학습 당시 알려진 Test A·B를 다시 평가한 재현 증거다. 독립 성능 주장은 Hidden Test D를 우선하며, 이 결과는 재현성 보조자료로만 사용한다.

| 구간 | 행 | MAE | RMSE | WAPE | R² | 기준선 WAPE 개선 |
|---|---:|---:|---:|---:|---:|---:|
| Known Test A | 31,950 | 9.833실 | 18.046 | 16.729% | 0.94992 | 10.906% |
| Known Test B | 20,970 | 9.791실 | 17.790 | 16.652% | 0.95092 | 10.558% |

## 10. 승인 gate 전체 결과

Hidden Test A와 B는 다음 hard check를 모두 통과했다.

| Gate | Test A | Test B |
|---|---|---|
| WAPE 18% 이하 | PASS | PASS |
| 기준선 개선율 8% 이상 | PASS | PASS |
| 고수요 객실유형 WAPE 30% 이하 | PASS | PASS |
| 저수요 객실유형 MAE 3실 이하 | PASS | PASS |
| D+10 WAPE 20% 이하 | PASS | PASS |
| 절대 Bias 5% 이하 | PASS | PASS |
| clipping 후 음수 0건 | PASS | PASS |
| clipping 후 수용량 초과 0건 | PASS | PASS |

Test B의 Test A 대비 WAPE 상대 변화는 약 0.739% 증가로 기록돼 있다. 승인 artifact는 이를 허용 범위로 판정했다.

## 11. 재현성과 무결성

| 항목 | 값 | 판정 |
|---|---|---|
| 모델 SHA-256 | `5b0a8a896bf87dd2516129d52599bf183c05dd7bc154e17b570851ca1e1564fa` | 일치 |
| 모델 manifest SHA-256 | `07766acc7d4cf2857b19a3dc6309ff2ba6fc01f080784328d689659fb230f321` | 동결 manifest와 일치 |
| 데이터 split SHA-256 | Train·Validation·Test A/B·Inference 기록 | 있음 |
| 승인 checksum manifest | `APPROVAL_SHA256SUMS.txt` | 있음 |
| 모델 checksum manifest | `SHA256SUMS.txt` | 있음 |
| random state | 20260826 | 기록됨 |
| 코드 revision | `NOT_COLLECTED` | 보완 필요 |
| 학습 환경 버전 | V2.2 manifest에 상세 미기록 | 보완 필요 |

모델 파일과 저장 checksum은 현재 바이트와 일치한다. 그러나 학습 당시 commit과 Python·scikit-learn 세부 버전이 V2.2 manifest에 완전하게 기록되지 않아 다른 환경에서 동일 모델을 처음부터 재학습하는 재현성은 불완전하다.

## 12. 제출 필수지표 충족도

| 제출 평가 항목 | V2.2 저장 결과 | 판정 |
|---|---|---|
| Train·Validation·Test 시간 분리 | 기간과 hash 기록 | 충족 |
| 시계열 순서 보존 | 시간 분할과 rolling-origin 기록 | 충족 |
| MAE | Validation·Test A/B 기록 | 충족 |
| RMSE | Validation·Test A/B 기록 | 충족 |
| WAPE | Validation·Test A/B 기록 | 충족 |
| R² | Validation·Test A/B 기록 | 충족 |
| 기준선 비교 | 저장 기준선 수치와 개선율 기록 | 부분 충족, 기준선 이름 미기록 |
| Train 대 Validation 비교 | Train 성능 미기록 | 미충족 |
| D+1~D+7 개별 성능 | 개별 수치 미기록 | 미충족 |
| 객실유형별 상세표 | 최악 지표만 저장 | 부분 충족 |
| 잔차·극단오차 분석 | 상세 분위수·잔차표 미기록 | 미충족 |
| 통계적 신뢰구간 | bootstrap 결과 미기록 | 미충족 |
| 추론시간 | P50·P95·P99 미기록 | 미충족 |
| 모델 크기·hash | 기록 | 충족 |
| 실제 PMS 평가 | 없음 | 미충족 |

## 13. 운영 준비도 판정

| 항목 | 저장 상태 | 해석 |
|---|---|---|
| 모델 승인 결정 | `CONDITIONAL_PASS` | 합성 검증 조건부 통과 |
| 승인 상태 | `VALIDATED_SYNTHETIC` | 실제 데이터 승인 아님 |
| 저장 E2E 상태 | `PASS` | 저장된 계약·합성 실행 결과 |
| Runtime feature parity | 승인 파일에는 `PASS` | 별도 Runtime 계약에는 `IMPLEMENTATION_REQUIRED`가 남음 |
| 실제 관측 데이터 | 없음 | 운영 정확도 미증명 |
| 승인자 | `null` | 사람 승인 없음 |
| 승인시각 | `null` | 사람 승인 없음 |
| 최종 운영 승인 | 없음 | 운영 활성화 근거로 사용 불가 |

승인 파일의 Runtime parity `PASS`와 `runtime_feature_contract.json`의 `IMPLEMENTATION_REQUIRED`가 일치하지 않는다. 제출 시 모델 학습 결과와 실제 서비스 적용 완료를 구분해야 한다.

## 14. 제출 가능한 문장과 금지 문장

### 제출 가능한 문장

> HGBR V2.2는 2018~2023 합성 학습 데이터와 2024 합성 Validation을 사용해 개발했으며, 별도 합성 Hidden Test A·B 52,920행에서 가중 통합 MAE 9.588실, RMSE 17.619, WAPE 16.260%를 기록했습니다. 저장 기준선 대비 WAPE는 10.752% 감소했으며 두 Test split의 사전 정의 gate를 모두 통과했습니다.

> 본 결과는 실제 PMS가 아닌 합성 데이터 검증 결과이며 실제 호텔 운영 정확도나 운영 승인을 의미하지 않습니다.

### 사용하면 안 되는 문장

- 실제 호텔에서 WAPE 16.260%를 달성했다.
- V2.2는 운영 승인을 완료했다.
- D+1~D+7 모든 Horizon에서 기준선보다 우수했다.
- Train과 Test 성능 차이가 작아 과적합이 없다고 증명됐다.
- 실제 요청 추론시간이 운영 기준을 통과했다.
- XGBoost·LightGBM보다 V2.2가 우수하다고 이 artifact가 증명했다.

## 15. 제출 전 보완 우선순위

1. 동일 Test 행에 대한 D+1~D+7 MAE·RMSE·WAPE를 저장한다.
2. Train 성능과 Learning Curve를 추가해 과적합을 확인한다.
3. 객실유형·호텔·수요구간별 상세 오차표와 P90·P95 극단오차를 추가한다.
4. target-date 기준 moving-block bootstrap 95% 신뢰구간을 추가한다.
5. 실제 요청 단위 추론시간 P50·P95·P99를 측정한다.
6. 실제 PMS 관측 데이터로 동일 분할 재학습·평가한다.
7. 학습 commit과 Python·라이브러리 버전을 고정한다.

## 16. 증거 파일

- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/model.joblib`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/model_manifest.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/model.approval.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/independent_test_report.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/hidden_test_d_approval.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/feature_contract.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/runtime_feature_contract.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/freeze_manifest.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/SHA256SUMS.txt`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/APPROVAL_SHA256SUMS.txt`

## 17. 문서 제약사항

저장소에 문서 관리 절차가 요구하는 `docs/문서관리규칙.md`와 `docs/markdown/document_specs/산출물작성규격.md`가 없다. 따라서 기존 ML 협업 검증보고서의 metadata와 구조를 적용했다. 정책 파일이 복구되면 문서 ID·분류·제출물 매핑·변경이력 형식을 다시 확인해야 한다.

Hidden Test A·B 통합 지표를 제외한 모든 수치는 저장 artifact에서 직접 전사했다. 통합 지표는 분할별 저장 합계로 가중 계산했으며 R²처럼 원본 분산이 필요한 지표는 임의로 합성하지 않았다.

## 변경 내역

| 버전 | 일자 | 변경 내용 |
|---|---|---|
| 1.0 | 2026-09-01 | HGBR V2.2 저장 artifact 기반 제출용 객관적 성능·일반화·재현성·운영 준비도 지표 최초 정리 |

## 18. 최종 결론

- 합성 Validation: WAPE 17.532%, MAE 10.302실, RMSE 18.980
- 합성 Hidden Test A: WAPE 16.212%, MAE 9.500실, RMSE 17.538
- 합성 Hidden Test B: WAPE 16.331%, MAE 9.722실, RMSE 17.742
- Hidden Test A·B 가중 통합: WAPE 16.260%, MAE 9.588실, RMSE 17.619
- 저장 기준선 대비 통합 WAPE 개선: 10.752%
- 저장 성능 gate: 모두 PASS
- 데이터 성격: 합성
- 저장 승인: `CONDITIONAL_PASS`
- 실제 운영 승인: 없음

HGBR V2.2는 합성 데이터 기준으로 일관된 성능과 기준선 개선을 보였지만, 실제 PMS 정확도와 D+1~D+7 개별 운영 품질은 아직 증명되지 않았다.
