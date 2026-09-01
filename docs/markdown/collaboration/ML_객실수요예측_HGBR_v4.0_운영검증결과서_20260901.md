# ML 객실수요예측 HGBR v4.0 운영 검증결과서

| 항목 | 내용 |
|---|---|
| 문서 설명 | 객실 수요예측 HGBR V4.0의 저장된 합성 평가, 신규 자체평가 계약과 운영 준비도를 정리한 검증결과서 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-09-01 12:14 |
| 작성·수정 | Codex |
| 문서 ID | `ML-ROOM-DEMAND-V4-RESULT-20260901` |
| 작성일 | 2026-09-01 |
| 기준 모델 | `room-demand-operational-hgbr-v4.0.0` |
| 예측 범위 | 객실유형별 D+1~D+7 수요예측 |
| 결과 상태 | `BLOCKED` |
| 운영 승인 | `production_approved=false` |
| 저장된 후보 판정 | `CONDITIONAL_PASS`, `VALIDATED_SYNTHETIC` |
| 기준 artifact SHA-256 | `50769a9f84af069f15599dad958aace64f98fe17f3449da4c93b73a07b32d9c2` |

## 1. 최종 판정

V4.0은 합성 holdout에서 V2.2와 4주 동일요일 기준선보다 높은 성능을 기록했다. D+1~D+7, 3개 호텔, 9개 객실유형의 저장된 합성 평가 게이트도 모두 통과했다.

그러나 이 결과는 운영 승인 증거가 아니다. 저장된 데이터가 합성 자료이고 목표일 재고·행사의 실제 과거 snapshot 시각이 증명되지 않았으며, 새로 고정한 동일 비교 기간으로 V2.2와 V4.0을 재학습·평가하지 못했기 때문이다.

| 판정 항목 | 결과 | 해석 |
|---|---|---|
| Artifact 무결성 | PASS | 저장된 모델과 checksum 일치 |
| Feature provenance 계약 | PASS | 시점 증명 필드와 관측 source 종류를 계약에 포함 |
| 기본 Runtime 비활성화 | PASS | 승인 전 기본 기능 비활성 |
| 기존 합성 holdout 후보 검증 | CONDITIONAL PASS | 합성 자료 내부 비교만 통과 |
| 2018~2026 관측 정렬 데이터 | FAIL | 필요한 실제 PIT snapshot 없음 |
| 동일 행 V2.2 대 V4.0 재평가 | FAIL | 신규 동일 기간 계약으로 미실행 |
| 90일 관측 shadow 검증 | FAIL | 관측 shadow 원본과 보고서 없음 |
| 사람의 최종 승인 | FAIL | 승인자와 승인시각 없음 |
| 최종 운영 승인 | **BLOCKED** | `production_approved=false` |

## 2. 모델 정의

| 항목 | 값 |
|---|---|
| 모델 유형 | Point-in-time HGBR |
| Target | `target_occupancy_rate` |
| 분모 | `target_sellable_rooms` |
| Loss | `absolute_error` |
| learning_rate | `0.04` |
| max_iter | `460` |
| max_leaf_nodes | `31` |
| min_samples_leaf | `35` |
| l2_regularization | `2.0` |
| random_state | `20260901` |
| 최종 학습 행 | `32,130` |
| 모델 크기 | `1,753,014 bytes` |

모델은 목표일 판매 가능 객실 대비 예상 점유율을 예측한다. 최종 객실 수는 0 이상, 목표일 판매 가능 객실 이하로 제한한다.

## 3. 데이터와 평가 범위

### 3.1 저장된 기존 V4.0 데이터

| 구분 | 값 |
|---|---|
| 원천 행 | `8,766` |
| 원천 기간 | 2024-01-01~2026-08-31 |
| 호텔 | DOUGLAS, GRAND, VISTA |
| 객실유형 | 9개 |
| 합성 데이터 여부 | `true` |
| 중복 행 | 0 |
| 누락 날짜 | 0 |
| 유효하지 않은 Target | 0 |

기존 artifact의 실제 분할은 다음과 같다.

| Split | Cutoff 기간 | 행 수 |
|---|---|---:|
| Train | 2025-01-07~2026-02-28 | 26,334 |
| Validation | 2026-03-01~2026-05-31 | 5,796 |
| Test | 2026-06-01~2026-08-24 | 5,355 |

### 3.2 신규 필수 동일 비교 계약

향후 V2.2와 V4.0의 최종 비교에는 아래 계약만 허용한다.

| Split | Cutoff 기간 | 용도 |
|---|---|---|
| Train | 2018-01-01~2023-12-21 | 후보 학습 |
| Validation | 2024-01-01~2024-12-21 | 후보 선택·구간 보정 |
| Test A | 2025-01-01~2025-12-21 | 독립 시험 |
| Test B | 2026-01-01~2026-08-21 | 최신 독립 시험 |

모든 모델은 같은 호텔·객실유형·cutoff·target·horizon 행으로 재학습하고 평가해야 한다. 각 cutoff와 객실유형에는 D+1~D+7이 모두 있어야 하며 split 간 행 중복과 시리즈 구성이 달라지는 경우 평가를 중단한다.

현재 보유 자료에는 2018~2023 실제 예약·재고·행사 snapshot이 없으므로 이 계약의 재실행 결과는 아직 없다.

## 4. 평가 지표 계약

### 4.1 핵심 지표

| 지표 | 정의 | 사용 목적 |
|---|---|---|
| MAE | `평균 abs(예측-실제)` | 평균적으로 몇 실 틀리는지 설명 |
| RMSE | `sqrt(평균((예측-실제)^2))` | 큰 오차 위험 확인 |
| WAPE | `합계 abs(예측-실제) / 합계 abs(실제)` | 전체 수요 대비 오차율 확인 |

실제 합계가 0인 집단의 WAPE는 0으로 꾸미지 않고 정의되지 않은 값으로 처리한다.

### 4.2 보조·진단 지표

- R², MASE, sMAPE
- 객실 수 편향과 정규화 편향
- 절대오차 P50·P75·P90·P95·P99·최댓값
- ±1실·±3실·±5실 적중률
- 과소·과대·정확 예측 비율
- 잔차 표준편차·왜도·lag 1/7 자기상관
- 실제 수요와 절대오차의 상관관계

### 4.3 기준선과 통계 검증

- 4주 동일요일 평균 기준선과 동일 행 비교
- V2.2와 V4.0의 동일 행 비교
- MAE·RMSE·WAPE 절대 감소량과 상대 개선율
- cutoff 날짜 기준 7일 paired moving-block bootstrap
- 95% 신뢰구간과 cutoff별 승·무·패 비율

### 4.4 예측구간과 운영 지표

- 80%·95% 구간의 실제 포함률
- 평균·중앙 구간 폭과 객실 정원 대비 정규화 폭
- Winkler interval score
- 실제 요청 단위 추론시간 P50·P95·P99·최댓값

기술 guardrail은 고수요 객실유형 WAPE 30% 이하, 저수요 객실유형 MAE 3실 이하, 80% 구간 포함률 70% 이상, 95% 구간 포함률 90% 이상, shadow 추론시간 P95 100ms 이하로 기록한다. 실제 운영 SLO가 확정되면 이 값은 승인된 정책으로 교체해야 한다.

## 5. 저장된 합성 Validation 결과

| 모델 | 행 | MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|---:|
| V4.0 | 5,796 | **0.707실** | **1.267** | **1.243%** | -0.126% |
| 4주 동일요일 기준선 | 5,796 | 3.439실 | 5.203 | 6.047% | 0.066% |

저장된 Validation에서 V4.0 WAPE는 기준선 대비 약 79.45% 감소했다. 이 수치는 합성 Validation 내부 결과이며 실제 호텔 정확도로 해석할 수 없다.

현재 저장된 artifact 평가에는 신규 공통 계약의 R²·MASE·오차 분위수·잔차 자기상관·통계 신뢰구간이 포함되지 않았다. 해당 지표 계산 코드는 구현됐지만 관측 정렬 데이터로 artifact를 다시 생성해야 숫자를 확정할 수 있다.

## 6. 저장된 합성 Test 결과

Test 기간은 2026-06-01~2026-08-24이며 총 5,355행이다.

| 비교 대상 | MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|
| V4.0 | **0.694실** | **1.363** | **1.219%** | -0.121% |
| V2.2 | 5.621실 | 10.039 | 9.879% | 1.866% |
| 4주 동일요일 기준선 | 3.316실 | 5.369 | 5.828% | 0.051% |

합성 Test에서 관측된 개선율은 다음과 같다.

| 비교 | MAE 감소 | RMSE 감소 | WAPE 감소 |
|---|---:|---:|---:|
| V4.0 대 V2.2 | 87.66% | 86.42% | 87.66% |
| V4.0 대 기준선 | 79.08% | 74.61% | 79.08% |

이 비교는 같은 5,355개 Test 행을 사용했지만, 두 모델을 신규 2018~2026 공통 분할로 다시 학습한 결과는 아니다. 따라서 모델 버전 간 최종 우열 근거로 사용하지 않는다.

## 7. D+1~D+7 합성 Test 결과

| Horizon | 행 | MAE | RMSE | WAPE |
|---|---:|---:|---:|---:|
| D+1 | 765 | 0.160실 | 0.412 | 0.281% |
| D+2 | 765 | 0.309실 | 0.644 | 0.543% |
| D+3 | 765 | 0.507실 | 0.890 | 0.889% |
| D+4 | 765 | 0.720실 | 1.184 | 1.264% |
| D+5 | 765 | 0.875실 | 1.452 | 1.533% |
| D+6 | 765 | 1.019실 | 1.707 | 1.790% |
| D+7 | 765 | 1.266실 | 2.282 | 2.240% |

예측 거리가 멀어질수록 오차가 증가하는 정상적인 형태다. 다만 D+1 booking-on-hand가 최종 판매량과 지나치게 가까운 합성 특성이 확인됐으므로 낮은 D+1 오차는 운영 성능으로 승계하지 않는다.

## 8. 호텔·객실유형 합성 Test 결과

### 8.1 호텔별

| 호텔 | 행 | MAE | RMSE | WAPE |
|---|---:|---:|---:|---:|
| DOUGLAS | 1,785 | 0.210실 | 0.506 | 2.465% |
| GRAND | 1,785 | 1.200실 | 1.984 | 1.044% |
| VISTA | 1,785 | 0.670실 | 1.176 | 1.420% |

### 8.2 객실유형별 요약

- 저장된 9개 객실유형 모두 합성 holdout 승인 기준을 통과했다.
- 고수요 객실유형 최대 WAPE는 `2.555%`였다.
- 저수요 객실유형 최대 MAE는 `0.045실`이었다.
- 가장 큰 객실유형 MAE는 GRAND G_DELUXE의 `2.046실`이었다.

위 승인 범위는 `VALIDATED_SYNTHETIC`이며 실제 운영 quality scope가 아니다.

## 9. 예측구간과 시계열 안정성

| 항목 | 저장된 결과 | 판정 |
|---|---:|---|
| 80% 예측구간 포함률 | 80.95% | 합성 기준 PASS |
| 95% 예측구간 포함률 | 94.42% | 합성 기준 PASS |
| Rolling-origin fold | 6개 | 실행됨 |
| Rolling-origin 평균 WAPE | 1.216% | 합성 결과 |
| 모든 fold 기준선 개선 | true | 합성 기준 PASS |
| 완전 평탄한 D+1~D+7 window | 0% | PASS |

관측 Test A·Test B의 신규 80%·95% 구간 보정 결과와 실제 운영 latency 결과는 없다.

## 10. 데이터 누수와 provenance 판정

### 구현된 차단 계약

- `reservation_as_of_at`, `capacity_as_of_at`, `event_as_of_at` 필수
- 모든 as-of 시각은 cutoff 종료시각 이하여야 함
- `signal_source_kind=OBSERVED_PIT`만 운영 승인 가능
- 합성 여부와 source 종류가 다르면 즉시 실패
- 목표일 최종값 복원과 검증되지 않은 final-state 자료 금지
- snapshot 저장 후 수정·삭제 금지
- 모델·feature contract·shadow 원본 SHA-256 결합

### 현재 실제 상태

기존 합성 신호에는 시점 증명 필드가 없고 목표일 최종 재고·행사를 사용한 흔적이 있다. 실제 기존 CSV로 데이터 빌드를 재실행하면 필수 provenance 열 누락으로 정상 차단된다.

따라서 저장된 낮은 오차가 미래정보 없이 얻어진 결과라고 증명할 수 없다.

## 11. 자체평가 구현 상태

| 평가 항목 | 구현 | 현재 관측 결과 |
|---|---|---|
| Train/Validation/Test 시간 분리 | 완료 | 데이터 없음 |
| D+1~D+7 완전성 | 완료 | 데이터 없음 |
| MAE·RMSE·WAPE | 완료 | 기존 합성 수치만 있음 |
| R²·MASE·sMAPE | 완료 | 재실행 대기 |
| Baseline 동일 행 비교 | 완료 | 재실행 대기 |
| 7일 paired bootstrap | 완료 | 재실행 대기 |
| Horizon·호텔·객실유형 분석 | 완료 | 기존 합성 수치만 있음 |
| 수요구간·월·주말 분석 | 완료 | 재실행 대기 |
| 잔차·극단오차 분석 | 완료 | 재실행 대기 |
| 80%·95% 구간 보정 | 완료 | 관측 재실행 대기 |
| 실제 추론시간 P50·P95·P99 | 완료 | 90일 shadow 대기 |
| Artifact·원본 재현성 | 완료 | 관측 증거 대기 |

Train 전용 모델은 2018~2023 Train과 2024 Validation 평가에만 사용한다. Train+Validation 재학습 모델은 2025 Test A와 2026 Test B에만 사용해 2024 Validation 누수를 차단한다.

## 12. 운영 준비도

2026-09-01 재감사 결과는 다음과 같다.

| Check | 결과 |
|---|---|
| artifact_integrity | PASS |
| feature_provenance_contract | PASS |
| runtime_default_disabled | PASS |
| observed_aligned_dataset | FAIL |
| aligned_v22_v40_benchmark | FAIL |
| observed_90_day_shadow | FAIL |
| human_approval_recorded | FAIL |

최종 상태는 `BLOCKED`, `production_approved=false`다.

## 13. 코드·테스트 검증

동일 작업트리에서 확인한 결과다.

| 검사 | 결과 |
|---|---|
| ML 테스트 | 43 passed |
| ML·Backend 테스트 | 1,377 passed, 71 skipped, 1 deselected |
| 전체 회귀검사 | 2,230 passed, 73 skipped, 2 deselected |
| Frontend 테스트 | 43 passed |
| Frontend production build | PASS |
| Compose CI 조합 | 11개 PASS |
| Python compileall | PASS |
| 코드 문서 검사 | PASS |
| 아키텍처 규칙 | PASS |
| 저장소 무결성 | 1,371 files PASS |
| git diff 검사 | PASS |

전체 회귀검사의 제외 항목은 실제 WeasyPrint 렌더 환경 검사 1개와 현재 소스 hash가 과거 Node2 이미지 영수증과 다른 검사 1개다. Node2 영수증은 해당 이미지를 다시 빌드하기 전까지 PASS로 갱신하지 않는다.

## 14. 남은 필수 조치

1. 2018~2026 실제 예약·재고·행사의 point-in-time snapshot을 확보한다.
2. 자료가 2018년부터 없다면 실제 snapshot이 모두 존재하는 가장 이른 공통 기간을 확정한다.
3. 같은 행과 같은 후보 예산으로 V2.2와 V4.0을 재학습한다.
4. Validation으로 후보 선택과 예측구간을 보정하고 Test A·B는 최종 1회만 평가한다.
5. 신규 자체평가 보고서의 모든 기술 게이트를 통과한다.
6. 최소 90일 관측 shadow에서 정확도·구간·지연시간·artifact 결합을 검증한다.
7. 영업 손실 기준과 기술 guardrail을 대조하고 사람의 최종 승인을 기록한다.

## 15. 사용 가능한 문장과 금지 문장

### 사용 가능한 문장

> V4.0은 합성 holdout에서 V2.2와 4주 동일요일 기준선보다 낮은 오차를 기록했지만, 실제 point-in-time 데이터와 신규 동일 기간 비교가 없어 현재 운영 승인은 차단되어 있습니다.

### 사용하면 안 되는 문장

- V4.0은 실제 호텔에서 WAPE 1.219%를 달성했다.
- V4.0은 V2.2보다 운영에서 87.66% 정확하다.
- 9개 객실유형 모두 운영 승인됐다.
- 2018~2026 실제 데이터로 검증됐다.
- 목표일 미래정보가 없다고 최종 증명됐다.

## 16. 증거 파일

- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/model.joblib`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/model_manifest.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/model.approval.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/feature_contract.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/checksums.sha256.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/evaluation/release_comparison.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/evaluation/recent_rolling_validation.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/evaluation/test_by_horizon.csv`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/evaluation/test_by_property.csv`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/evaluation/test_by_room_type.csv`
- `data/processed/ml_operational_v4/dataset/dataset_manifest.json`
- `data/processed/ml_operational_v4/production_readiness.json`
- `src/ml/room_demand_timeseries/operational_metrics.py`
- `src/ml/room_demand_timeseries/operational_self_evaluation.py`
- `src/ml/room_demand_timeseries/operational_shadow_validation.py`
- `src/ml/room_demand_timeseries/operational_readiness.py`

## 17. 문서 제약사항

저장소에 필수 문서 정책 파일 `docs/문서관리규칙.md`와 `docs/markdown/document_specs/산출물작성규격.md`가 없다. 따라서 이 문서는 기존 ML 검증보고서 구조와 실제 V4.0 artifact 계약을 기준으로 작성했다. 문서 정책 파일이 복구되면 문서 ID·metadata·변경이력 형식을 다시 확인해야 한다.

## 변경 내역

| 버전 | 일자 | 변경 내용 |
|---|---|---|
| 1.0 | 2026-09-01 | V4.0 합성 평가 결과, 신규 자체평가 계약, 운영 차단 사유와 검증 증거 최초 정리 |

## 18. 결론

- 합성 후보 성능: `CONDITIONAL_PASS`
- 신규 자체평가 구현: 완료
- 실제 정렬 데이터 재평가: 미완료
- 90일 관측 shadow: 미완료
- 실제 운영 승인: `BLOCKED`
- 최종 `production_approved`: `false`

V4.0은 운영 후보 코드와 검증 체계는 준비됐지만 운영 정확도 증거는 아직 준비되지 않았다. 실제 point-in-time 자료로 동일 기준 재학습·평가와 90일 shadow 검증을 마치기 전에는 기능을 활성화하지 않는다.
