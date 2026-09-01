# ML 객실수요예측 HGBR V2.2·V3.3·V4.0 통합 비교보고서

| 항목 | 내용 |
|---|---|
| 문서 설명 | 객실 수요예측 HGBR V2.2, V3.3, V4.0의 모델 구조, 데이터, 저장 성능, Runtime 반영 및 운영 준비도를 동일한 판정 기준으로 비교한 보고서 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-09-01 12:20 |
| 작성·수정 | Codex |
| 문서 ID | `ML-ROOM-DEMAND-VERSION-COMPARE-20260901` |
| 비교 모델 | `room-demand-timeseries-hgbr-v2.2.0`, `room-demand-hgbr-occupancy-v3.3.0`, `room-demand-operational-hgbr-v4.0.0` |
| 목표 범위 | 객실유형별 D+1~D+7 운영 수요예측 |
| 최종 판정 | `BLOCKED` |
| 운영 승인 | 세 버전 모두 실제 관측 데이터 기준 `production_approved=true` 증거 없음 |

## 1. 최종 결론

세 버전은 모두 HGBR 계열이지만 동일한 모델을 순차 승격한 관계가 아니다.

- V2.2는 과거 일별 실적 44개 특징으로 객실 수요를 예측하는 이전 Runtime 모델이다.
- V3.3은 V2.2와 같은 44개 입력 특징을 사용하면서 Target과 하이퍼파라미터를 바꿔 HGBR의 비열등성을 검증한 오프라인 최적화 후보다. Runtime에는 반영되지 않았다.
- V4.0은 예약잔량, pickup, 목표일 판매 가능 객실, 행사 등 point-in-time 신호 20개를 추가한 64개 특징 운영 후보다. 현재 Runtime 설정은 V4.0 artifact를 가리키지만 기본 기능은 비활성화되어 있고 운영 승인은 차단되어 있다.

저장된 합성 수치만 보면 V4.0의 오차가 가장 낮다. 그러나 V4.0의 기존 데이터에는 목표일 재고·행사의 실제 과거 snapshot 시각이 증명되지 않았고 미래 정보 위험이 있으므로, 이 수치로 세 버전의 최종 우열을 결정하면 안 된다.

현재 내릴 수 있는 판정은 다음과 같다.

| 질문 | 판정 |
|---|---|
| V2.2가 이전 Runtime 모델이었는가 | 예 |
| V3.3이 이전 운영 모델이었는가 | 아니오. 비승인 오프라인 후보다 |
| V4.0이 V3.3을 그대로 승격한 모델인가 | 아니오. 특징·Target 분모·학습 설정·운영 계약이 다르다 |
| 저장된 합성 평가에서 V4.0이 가장 낮은 오차인가 | 예 |
| 세 버전이 실제 관측 데이터와 동일 분할로 공정하게 비교됐는가 | 아니오 |
| 현재 V4.0을 운영 활성화할 수 있는가 | 아니오 |
| 최종 권장 모델 | 실제 PIT 데이터의 3자 정렬 비교와 90일 shadow를 통과한 V4.0 |

## 2. 버전 관계와 적용 상태

| 구분 | V2.2 | V3.3 | V4.0 |
|---|---|---|---|
| 모델 버전 | `room-demand-timeseries-hgbr-v2.2.0` | `room-demand-hgbr-occupancy-v3.3.0` | `room-demand-operational-hgbr-v4.0.0` |
| 역할 | 이전 Runtime 후보·비교 기준 | 오프라인 모델 최적화 후보 | point-in-time 운영 후보 |
| 모델 계열 | HGBR | HGBR | HGBR |
| Runtime 반영 | 과거 serving release | 미반영 | 현재 Compose 경로 연결 |
| 현재 기본 활성화 | 아니오 | 아니오 | 아니오 |
| 저장 승인 상태 | `CONDITIONAL_PASS`, `VALIDATED_SYNTHETIC` | 별도 승인 파일 없음 | `CONDITIONAL_PASS`, `VALIDATED_SYNTHETIC` |
| `production_approved` | `true` 증거 없음 | `false` | `false` |
| 사람의 최종 승인 | 없음 | 없음 | 없음 |

V3.3 artifact에는 `runtime_integrated=false`가 기록되어 있으며 `model.approval.json`도 없다. 현재 Runtime 구성에는 V4.0 경로가 있고 V3.3 경로는 없다. 따라서 “V3.3이 V4.0 직전 운영 버전이었다”는 설명은 사실과 다르다.

## 3. 모델 구조 비교

| 항목 | V2.2 | V3.3 | V4.0 |
|---|---:|---:|---:|
| 입력 특징 수 | 44 | 44 | 64 |
| 최대 Horizon | D+10 | D+10 | D+7 |
| 학습 Target 방식 | 4주 동일요일 기준선 대비 잔차율 | 물리 객실 대비 점유율 | 목표일 판매 가능 객실 대비 점유율 |
| 최종 수요 환산 기준 | 객실 수 기준선·물리 객실 | 물리 객실 | 목표일 판매 가능 객실 |
| Loss | `squared_error` | `squared_error` | `absolute_error` |
| learning rate | 0.045 | 0.06 | 0.04 |
| max iter | 360 | 240 | 460 |
| max leaf nodes | 31 | 31 | 31 |
| min samples leaf | 40 | 40 | 35 |
| L2 regularization | 2.0 | 0.2 | 2.0 |
| 모델 크기 | 1,361,774 bytes | 931,014 bytes | 1,753,014 bytes |

V2.2와 V3.3의 44개 입력 특징 순서와 내용은 동일하다. 두 버전의 핵심 차이는 Target 변환과 모델 설정이다.

V4.0은 기존 44개 특징을 유지하면서 다음 20개 운영 특징을 추가했다.

- 목표일 과거 실적: `target_rooms_sold_lag_7/14/21/28`
- 목표일 동일요일 평균: `target_same_weekday_mean_4w/8w/12w`
- 목표일 객실 공급: `target_sellable_rooms`, `target_out_of_order_rooms`
- 예약잔량: `booking_on_hand`, `booking_on_hand_ratio`
- 예약 증감: `booking_pickup_1d/7d`, `booking_pickup_acceleration`
- 취소: `cancellations_on_hand`, `cancellations_7d`, `net_booking_pickup_7d`
- 연회·행사: `banquet_room_nights_on_hand`, `event_count`, `event_demand_uplift`

이 추가 특징은 실제 예측시점에 알 수 있다면 유용하다. 반대로 목표일 최종값을 사용하거나 snapshot 시각이 없으면 미래 정보 누수가 된다. V4.0 운영 계약은 이를 막기 위해 예약·객실 공급·행사 각각의 `as_of_at` 시각과 `OBSERVED_PIT` source를 요구한다.

## 4. 데이터와 검증 설계 비교

### 4.1 저장 artifact의 실제 설계

| 항목 | V2.2 | V3.3 | V4.0 |
|---|---|---|---|
| 데이터 종류 | 합성 | 합성 | 합성 |
| Train | 2018-01-07~2023-12-21, 227,790행 | 2021·2022·2023 순방향 CV 후 2024 검증 구조 | 2025-01-07~2026-02-28, 26,334행 |
| Validation | 2024-01-01~2024-12-21, 32,040행 | 2024 Validation | 2026-03-01~2026-05-31, 5,796행 |
| Test | 2025 Test A, 2026 Test B 및 Hidden Test D | 합성 F/G Test A·B | 2026-06-01~2026-08-24, 5,355행 |
| 시간 순서 보존 | artifact 계약상 보존 | 연도 순방향 CV | split 순서는 보존 |
| PIT provenance | 없음 | 없음 | 계약은 있음, 기존 합성 원본 증명은 실패 |
| 실제 PMS 검증 | 없음 | 없음 | 없음 |

V3.3 문서는 2021~2023 순방향 CV와 2024 Validation을 기록하지만, V3.3 manifest에는 전체 Train 날짜와 행 수가 별도 필드로 고정되어 있지 않다. 따라서 V2.2와 동일한 2018~2023 원본 행을 사용했다고 artifact만으로 완전히 증명할 수는 없다.

### 4.2 사용자가 정한 최종 공통 기준

세 버전의 최종 비교에는 다음 기준을 적용해야 한다.

| Split | 기간 | 사용 목적 |
|---|---|---|
| Train | 2018-01-01~2023-12-21 | 후보 학습 |
| Validation | 2024-01-01~2024-12-21 | 후보 선택·예측구간 보정 |
| Test A | 2025-01-01~2025-12-21 | 독립 시험 |
| Test B | 2026-01-01~2026-08-21 | 최신 독립 시험 |

다만 2018년부터 실제 PIT snapshot이 없다면 날짜만 맞추기 위해 과거 최종값을 복원하면 안 된다. 예약·재고·행사의 실제 snapshot이 모두 존재하는 가장 이른 공통 날짜부터 세 버전을 다시 비교해야 한다.

## 5. 저장된 Validation 성능

다음 표는 각 artifact에 저장된 Validation 결과다. V2.2와 V3.3은 2024 Validation으로 기록되어 있지만 동일 행 fingerprint가 함께 저장되지 않았다. V4.0은 기간과 특징 구성이 전혀 다르다. 따라서 이 표는 버전별 기존 증거를 모은 것이며 공정한 3자 순위표가 아니다.

| 버전 | 평가 구간 | 행 | MAE | RMSE | WAPE | R² | 기준선 WAPE |
|---|---|---:|---:|---:|---:|---:|---:|
| V2.2 | 2024 합성 Validation | 32,040 | 10.302실 | 18.980 | 17.532% | 0.94415 | 19.566% |
| V3.3 | 2024 합성 Validation | artifact 미기록 | 9.900실 | 18.229 | 16.841% | 0.94969 | 미기록 |
| V4.0 | 2026-03~05 합성 Validation | 5,796 | 0.707실 | 1.267 | 1.243% | 미기록 | 6.047% |

해석은 다음 범위로 제한한다.

- V2.2는 자체 2024 합성 Validation에서 기준선보다 WAPE가 10.40% 상대 개선됐다.
- V3.3 HGBR는 같은 보고 연도의 자체 Validation에서 V2.2보다 낮은 오차를 기록했지만, 동일 행 prediction과 fingerprint가 없어 직접 개선율을 확정하지 않는다.
- V3.3 Validation WAPE 1위는 XGBoost 16.795%였고 HGBR 16.841%는 비열등 기준을 통과한 종합 선정 모델이다.
- V4.0의 매우 낮은 오차는 예약잔량 등 운영 신호 효과가 포함된 결과지만, 기존 합성 신호의 시점 증명이 실패했으므로 실제 정확도로 승계할 수 없다.

## 6. 저장된 Test 성능

### 6.1 각 버전의 독립 또는 보유 Test

| 버전 | Test | 행 | MAE | RMSE | WAPE | R² | 증거 수준 |
|---|---|---:|---:|---:|---:|---:|---|
| V2.2 | Hidden Test D A | 31,950 | 9.500실 | 17.538 | 16.212% | 0.95196 | 합성 독립 시험 |
| V2.2 | Hidden Test D B | 20,970 | 9.722실 | 17.742 | 16.331% | 0.95192 | 합성 독립 시험 |
| V3.3 | F Test A | 31,950 | 9.833실 | 17.866 | 16.885% | 0.95141 | 합성 F holdout |
| V3.3 | F Test B | 20,970 | 10.190실 | 18.872 | 17.229% | 0.94745 | 합성 F holdout |
| V3.3 | G Test A | 31,950 | 9.887실 | 18.273 | 16.906% | 0.94953 | 합성 G holdout |
| V3.3 | G Test B | 20,970 | 10.003실 | 18.428 | 16.713% | 0.94934 | 합성 G holdout |
| V4.0 | 2026-06~08 Test | 5,355 | 0.694실 | 1.363 | 1.219% | 미기록 | 합성·PIT 미증명 |

V3.3의 F/G 통합 WAPE는 HGBR 16.9253%, XGBoost 16.9031%, LightGBM 16.9104%였다. HGBR는 통합 WAPE 단독 1위가 아니지만 네 구간의 RMSE와 R²가 가장 좋았고 사전 정의한 WAPE 0.20%p 비열등 기준을 통과했다.

V2.2 원래 Test WAPE 약 16%와 V4.0 저장 비교에서 산출된 V2.2 WAPE 9.879%는 서로 다른 데이터와 평가 실행의 결과다. 두 숫자는 오류가 아니라 평가 모집단이 다르기 때문에 달라진 것이며 서로 대체해서 쓰면 안 된다.

### 6.2 동일 5,355행에서 저장된 V2.2 대 V4.0 비교

V4.0 release comparison에는 2026-06-01~2026-08-24의 같은 5,355행에 대한 V2.2와 V4.0 결과가 있다.

| 모델 | MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|
| V2.2 | 5.621실 | 10.039 | 9.879% | 1.866% |
| V4.0 | 0.694실 | 1.363 | 1.219% | -0.121% |
| 4주 동일요일 기준선 | 3.316실 | 5.369 | 5.828% | 0.051% |

이 저장 비교에서 V4.0은 V2.2 대비 MAE 87.66%, RMSE 86.42%, WAPE 87.66% 감소를 기록했다. 그러나 다음 이유로 운영 우월성 증거 등급은 낮다.

1. 데이터가 합성이다.
2. V4.0의 예약·재고·행사 신호에 실제 과거 snapshot 시각이 없다.
3. 목표일 최종 재고·행사를 사용했을 가능성을 배제할 수 없다.
4. V2.2와 V4.0을 사용자 지정 2018~2026 공통 분할로 다시 학습한 결과가 아니다.
5. V3.3은 이 동일 행 비교에서 제외됐다.

## 7. 비교 가능성 등급

| 등급 | 정의 |
|---|---|
| A | 실제 관측 PIT 데이터, 동일 행·Target·기간·학습 예산, 누수 검증 완료 |
| B | 동일 행 비교지만 합성 또는 PIT provenance 미증명 |
| C | 동일 기간으로 기록됐지만 행 identity나 prediction이 미고정 |
| D | 기간·행·특징·평가 설계 중 하나 이상이 다름 |

| 비교 | 현재 등급 | 이유 |
|---|---|---|
| V2.2 대 V3.3 2024 Validation | C | 같은 보고 기간이나 동일 행 fingerprint와 paired prediction 없음 |
| V2.2 대 V4.0 저장 Test | B | 같은 5,355행이나 합성·PIT provenance 미증명 |
| V3.3 대 V4.0 | D | 공통 행 평가 없음 |
| V2.2 대 V3.3 대 V4.0 최종 비교 | 미달 | A등급 3자 비교가 존재하지 않음 |

## 8. D+1~D+7 평가 범위

V2.2와 V3.3은 D+10까지 지원하지만 V4.0은 D+7까지만 지원한다. 세 버전의 공정 비교 범위는 공통 구간인 D+1~D+7로 제한해야 한다.

V4.0의 기존 합성 Test 결과는 다음과 같다.

| Horizon | 행 | MAE | RMSE | WAPE |
|---|---:|---:|---:|---:|
| D+1 | 765 | 0.160실 | 0.412 | 0.281% |
| D+2 | 765 | 0.309실 | 0.644 | 0.543% |
| D+3 | 765 | 0.507실 | 0.890 | 0.889% |
| D+4 | 765 | 0.720실 | 1.184 | 1.264% |
| D+5 | 765 | 0.875실 | 1.452 | 1.533% |
| D+6 | 765 | 1.019실 | 1.707 | 1.790% |
| D+7 | 765 | 1.266실 | 2.282 | 2.240% |

예측 거리가 멀어질수록 오차가 증가하는 형태는 자연스럽다. 다만 D+1 예약잔량이 최종 판매량과 지나치게 가까운 합성 특성이 확인됐으므로 D+1 저오차를 운영 성능으로 해석하지 않는다.

현재 artifact에는 세 버전의 동일 D+1~D+7 행별 비교표가 없다.

## 9. 일반화·통계·운영 평가 비교

| 평가 항목 | V2.2 | V3.3 | V4.0 |
|---|---|---|---|
| 시간 기반 Validation | 있음 | 있음 | 있음 |
| Rolling-origin | 3 fold | 2021~2023 CV | 6 fold |
| Baseline 비교 | 있음 | 경쟁 모델 중심 | 있음 |
| Paired bootstrap | 없음 | 경쟁 모델 대비 2,000회 | 구현됨, 관측 재실행 대기 |
| D+1~D+7 개별 평가 | 일부 artifact 계약 | 현재 통합 문서에 상세 없음 | 저장 결과 있음 |
| 호텔별 평가 | 있음 | F/G 통합 중심 | 저장 결과 있음 |
| 객실유형별 gate | 있음 | F/G 통합 중심 | 저장 결과 있음 |
| 80%·95% 예측구간 | 없음 | 없음 | 합성 결과 있음 |
| 추론시간 P50·P95·P99 | 없음 | 없음 | 구현됨, 90일 shadow 대기 |
| Artifact checksum | 있음 | 있음 | 있음 |
| 실제 PIT provenance | 없음 | 없음 | 계약 있음, 데이터 증거 없음 |

V3.3의 저장 학습시간은 HGBR 7.42초, LightGBM 10.81초, XGBoost 85.87초다. 이는 V3.3 최적화 환경에서의 재학습 시간이며 V2.2·V4.0과 같은 장비·같은 행 수로 측정한 추론시간 비교가 아니다.

## 10. Runtime·운영 준비도 비교

| 항목 | V2.2 | V3.3 | V4.0 |
|---|---|---|---|
| 배포용 모델 파일 | 있음 | 후보 파일 있음 | 있음 |
| 승인 파일 | 있음 | 없음 | 있음 |
| Runtime feature parity 기록 | `PASS` | 변환 전 | `PASS` |
| 현재 Compose 참조 | 아니오 | 아니오 | 예 |
| 기본 기능 활성화 | 아니오 | 아니오 | 아니오 |
| 관측 90일 shadow | 없음 | 없음 | 없음 |
| 운영 승인자·시각 | 없음 | 없음 | 없음 |
| 현재 운영 사용 가능 | 아니오 | 아니오 | 아니오 |

V2.2의 `runtime_feature_contract.json`에는 `status=IMPLEMENTATION_REQUIRED`가 남아 있는데 승인 파일에는 `runtime_feature_parity=PASS`가 기록되어 있다. 이는 저장 증거 간 상태 표현이 완전히 일치하지 않는 부분이므로 V2.2를 다시 운영 후보로 사용할 경우 재검증해야 한다.

V4.0 현재 readiness 결과는 다음 네 항목을 차단 사유로 기록한다.

- 실제 관측 정렬 데이터 없음
- 관측 데이터 기반 정렬 benchmark 없음
- 90일 관측 shadow 없음
- 사람의 최종 승인 없음

## 11. 현재 구현 공백

현재 `operational_aligned_benchmark.py`는 V2.2와 V4.0을 같은 행으로 재학습·비교하고, 과거 특징과 운영 특징의 동일 예산 ablation을 수행하도록 구현되어 있다.

그러나 V3.3 고정 설정은 이 정렬 benchmark에 포함되어 있지 않다. 따라서 현재 코드만 실행해도 V2.2·V3.3·V4.0 3자 최종 비교표가 자동 생성되지는 않는다.

3자 비교를 완성하려면 다음 두 비교를 모두 수행해야 한다.

### 11.1 Release 고정 설정 비교

- V2.2: 잔차율, squared loss, 360회 설정
- V3.3: 점유율, squared loss, 240회 설정
- V4.0: PIT 점유율, absolute loss, 460회 설정
- 동일 D+1~D+7 행과 동일 Train·Validation·Test split 사용

이 비교는 각 버전 전체 설계의 결과 차이를 측정한다.

### 11.2 동일 예산 ablation 비교

- 동일 Target 사용
- 동일 후보 수와 하이퍼파라미터 탐색 예산 사용
- 동일 Train·Validation·Test 행 사용
- 과거 44개 특징과 PIT 64개 특징을 비교

이 비교는 모델 설정 차이와 운영 특징 추가 효과를 분리한다.

## 12. 최종 운영 승인 기준

세 버전의 최종 선택은 다음 조건을 모두 통과해야 한다.

1. 실제 예약·재고·행사의 point-in-time snapshot을 확보한다.
2. 모든 snapshot의 `as_of_at`이 해당 cutoff 종료시각 이하인지 검증한다.
3. 세 모델을 동일 D+1~D+7 행, 같은 Train·Validation·Test 기간으로 재학습한다.
4. MAE, RMSE, WAPE와 R²·MASE를 동일 계산식으로 산출한다.
5. 전체·Horizon·호텔·객실유형별로 기준선보다 개선됐는지 확인한다.
6. cutoff 날짜 기준 paired moving-block bootstrap 95% 신뢰구간을 확인한다.
7. 고수요 WAPE, 저수요 MAE, 편향, 극단오차와 예측구간 포함률을 검증한다.
8. 최소 90일 관측 shadow에서 정확도와 추론시간 P50·P95·P99를 측정한다.
9. 모델·데이터·feature contract·평가 원본의 SHA-256을 결합한다.
10. 영업 기준 검토 후 승인자와 승인시각을 기록한다.

기술적으로 V4.0이 위 조건을 통과하면 가장 추천할 수 있다. 예약잔량과 판매 가능 객실을 반영하므로 호텔 운영 상황을 가장 잘 표현할 가능성이 높기 때문이다. 단, 실제 PIT 검증에서 통과하지 못하면 V2.2 또는 V3.3을 자동 승격하지 않고 같은 기준으로 다시 선택해야 한다.

## 13. 사용 가능한 문장과 금지 문장

### 사용 가능한 문장

> V2.2는 이전 Runtime 모델, V3.3은 Runtime에 반영되지 않은 최적화 후보, V4.0은 point-in-time 운영 후보입니다. 저장된 합성 평가에서는 V4.0 오차가 가장 낮지만 실제 PIT 데이터의 3자 정렬 비교가 없어 현재 운영 승인은 차단되어 있습니다.

### 사용하면 안 되는 문장

- V3.3은 V4.0 직전 운영 모델이었다.
- V4.0은 실제 호텔에서 WAPE 1.219%를 달성했다.
- V4.0은 실제 운영에서 V2.2보다 87.66% 정확하다.
- 세 버전은 2018~2026 실제 데이터로 공정하게 비교됐다.
- V4.0의 예약·재고·행사 특징에는 미래정보가 없다고 최종 증명됐다.
- 현재 세 모델 중 어느 하나가 운영 승인됐다.

## 14. 증거 파일

### V2.2

- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/model_manifest.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/model.approval.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/feature_contract.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/runtime_feature_contract.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/independent_test_report.json`
- `src/ml/artifacts/room-demand-timeseries-hgbr-v2.2.0/hidden_test_d_approval.json`

### V3.3

- `src/ml/artifacts/room-demand-hgbr-optimization-v3.3.0/model_manifest.json`
- `src/ml/artifacts/room-demand-hgbr-optimization-v3.3.0/selection.json`
- `src/ml/artifacts/room-demand-hgbr-optimization-v3.3.0/feature_contract.json`
- `src/ml/artifacts/room-demand-hgbr-optimization-v3.3.0/release_checksums.json`
- `docs/markdown/collaboration/ML_HGBR_v3.3_최적화_검증보고서_20260829.md`

### V4.0

- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/model_manifest.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/model.approval.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/feature_contract.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/evaluation/release_comparison.json`
- `src/ml/artifacts/room-demand-operational-hgbr-v4.0.0/evaluation/test_by_horizon.csv`
- `data/processed/ml_operational_v4/production_readiness.json`
- `src/ml/room_demand_timeseries/operational_aligned_benchmark.py`
- `docs/markdown/collaboration/ML_객실수요예측_HGBR_v4.0_운영검증결과서_20260901.md`

## 15. 문서 및 증거 재검증

2026-09-01 동일 작업트리에서 다음 검사를 수행했다.

| 검사 | 결과 |
|---|---|
| V2.2 checksum·HGBR Runtime artifact | PASS |
| V3.3 release checksum·Runtime 미반영 계약 | PASS |
| V4.0 artifact·holdout 승인 범위 | PASS |
| PIT provenance·동일 행 benchmark·운영 차단 gate | PASS |
| 관련 Pytest | 18 passed |
| 문서 metadata 정책 검사 | PASS |
| Markdown 공백·diff 검사 | PASS |

Pytest에는 FastAPI `on_event`와 joblib/NumPy 관련 deprecation warning이 있었지만 실패는 없었다. 이 검사는 코드·artifact 계약의 회귀 상태를 확인한 것이며 실제 호텔 정확도나 운영 승인을 증명하지 않는다.

## 16. 문서 제약사항

저장소에 문서 관리 스킬이 요구하는 `docs/문서관리규칙.md`와 `docs/markdown/document_specs/산출물작성규격.md`가 없다. 따라서 이 문서는 기존 V4.0 검증결과서의 metadata와 협업 보고서 구조를 적용했다. 정책 파일이 복구되면 문서 ID, 분류, 변경 이력 및 저장 위치를 다시 확인해야 한다.

또한 artifact와 Markdown에 저장된 결과만 비교했다. 실제 관측 PIT 원본이 없으므로 운영 데이터와 완전히 동기화됐다고 선언하지 않는다.

## 변경 내역

| 버전 | 일자 | 변경 내용 |
|---|---|---|
| 1.0 | 2026-09-01 | V2.2·V3.3·V4.0 구조, 저장 성능, 비교 가능성, Runtime 상태 및 최종 3자 평가 기준 최초 정리 |

## 17. 최종 판정

- V2.2: 이전 Runtime 기준 모델, 합성 조건부 검증, 실제 운영 승인 없음
- V3.3: HGBR 최적화 비승인 후보, Runtime 미반영
- V4.0: 가장 발전된 PIT 운영 후보, 현재 Runtime 경로 연결, 기본 비활성화
- 저장 합성 성능상 우세: V4.0
- 실제 공정한 3자 우승 모델: 아직 없음
- 운영 권장 상태: `BLOCKED`
- 다음 필수 작업: 실제 PIT 데이터의 V2.2·V3.3·V4.0 동일 D+1~D+7 재학습·평가 및 90일 shadow
