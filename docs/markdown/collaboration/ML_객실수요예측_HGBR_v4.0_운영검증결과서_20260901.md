# ML 객실수요예측 HGBR v4.0 운영 검증결과서

| 항목 | 내용 |
|---|---|
| 문서 설명 | V4.0 단독 재학습과 제출용 객관적 평가지표 검증 결과 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.3 |
| 문서 기준일 | 2026-09-01 13:24 |
| 작성·수정 | Codex |
| 문서 ID | `ML-ROOM-DEMAND-V4-RESULT-20260901` |
| 기준 모델 | `room-demand-operational-hgbr-v4.0.0` |
| 예측 범위 | 객실유형별 D+1~D+7 수요예측 |
| 평가 데이터 | 2024~2026 합성 데이터 |
| 기술 평가 | `CONDITIONAL_PASS` |
| 운영 승인 | `production_approved=false` |
| 재학습 artifact SHA-256 | `7d8842fb4126253c0e1894c3907dce8ea0d602fa922df48f60b504a4e83505d9` |

## 1. 최종 판정

V4.0 고정 설정으로 Train·Validation·Test를 다시 학습·평가했다. 기준선 이름과 개선율, Train 대 Validation, D+1~D+7, 호텔·객실유형·수요구간, 잔차·극단오차, target-date moving-block bootstrap 95% 신뢰구간, 단일 요청 추론시간 P50·P95·P99, 모델 크기·hash와 실행환경을 모두 산출물에 저장했다.

합성 Test 5,355행에서 다음 결과를 기록했다.

- MAE: `0.704실`
- RMSE: `1.451실`
- WAPE: `1.237%`
- 4주 동일요일 기준선 WAPE: `5.828%`
- 기준선 대비 WAPE 감소: `78.772%`
- target-date bootstrap 상대 개선율 95% CI: `77.300%~79.908%`

그러나 운영 승인은 계속 차단한다. 실제 PMS 평가가 없고, 현재 분할 파일에는 예약·재고·행사의 관측시각과 원천 종류를 증명하는 필드가 없으며, 데이터가 합성 자료이기 때문이다. 저장소도 재학습 당시 dirty 상태여서 commit만으로 동일 소스를 완전히 복원할 수 없다.

| 판정 항목 | 결과 | 해석 |
|---|---|---|
| V4 고정 설정 재학습 | PASS | `robust_leaf31` 설정 유지 |
| 시간 분할 및 label 가용시점 purge | PASS | 다음 분할 시작 이후 확정되는 label 제거 |
| Test 독립성 | PASS | `test_seen_by_trainer=false` |
| 제출용 객관적 지표 | PASS | 상세 JSON·CSV 저장 |
| 모델 파일 무결성 | PASS | 14개 산출물 checksum 일치 |
| 실제 PMS 평가 | FAIL | 합성 데이터만 보유 |
| 실제 PIT provenance | FAIL | 시점 증명 필드 누락 |
| 학습 commit 재현성 | PARTIAL | commit 기록, working tree dirty |
| 최종 운영 승인 | **BLOCKED** | `production_approved=false` |

## 2. 재학습 범위와 모델 설정

이번 실행은 V4.0만 재학습했다. V2.2와 V3.3은 재학습하거나 버전 우열 비교에 사용하지 않았다.

| 항목 | 값 |
|---|---|
| 모델 | `HistGradientBoostingRegressor` |
| Target | `target_occupancy_rate` |
| 최종 객실 수 | 점유율 예측 × `target_sellable_rooms` |
| 특징 수 | 64개 |
| Loss | `absolute_error` |
| learning_rate | `0.04` |
| max_iter | `460` |
| max_leaf_nodes | `31` |
| min_samples_leaf | `35` |
| l2_regularization | `2.0` |
| random_state | `20260901` |
| 최종 학습 행 | 31,248 |
| 모델 크기 | 1,371,620 bytes |
| 모델 SHA-256 | `7d8842fb4126253c0e1894c3907dce8ea0d602fa922df48f60b504a4e83505d9` |

## 3. 시간 분할과 누수 방지

원본 분할은 cutoff 기준이어서 Train의 target이 Validation 시작일 이후까지, Validation의 target이 Test 시작일 이후까지 이어졌다. 시점 재현 평가에서 미래 label이 되는 것을 막기 위해 cutoff 묶음 전체를 purge했다.

| Split | 원본 행 | 제거 행 | 평가 행 | Cutoff 기간 | Target 종료일 |
|---|---:|---:|---:|---|---|
| Train | 26,334 | 441 | 25,893 | 2025-01-07~2026-02-21 | 2026-02-28 |
| Validation | 5,796 | 441 | 5,355 | 2026-03-01~2026-05-24 | 2026-05-31 |
| Test | 5,355 | 0 | 5,355 | 2026-06-01~2026-08-24 | 2026-08-31 |

적용 규칙은 `이전 split의 target_date < 다음 split의 최초 cutoff_date`이다. D+1~D+7 중 일부 행만 제거하지 않고 해당 cutoff의 7개 horizon을 모두 제외했다. 모든 split은 3개 호텔, 9개 객실유형, D+1~D+7을 동일하게 포함하며 식별 행 중복은 없다.

기존 `development.csv.gz`는 Test까지 포함한 37,485행이지만 이번 재학습에서는 사용하지 않았다. 데이터 생성 코드는 이후 `Train+Validation`만 development로 만들도록 수정했다.

## 4. 기준선 정의

| 항목 | 값 |
|---|---|
| 기준선 이름 | `seasonal_same_weekday_mean_4w_clipped` |
| 정의 | 목표일과 같은 요일의 최근 4주 평균 판매 객실 수 |
| 제한 | 0 이상, 목표일 판매 가능 객실 이하 |
| 비교 단위 | 후보와 완전히 같은 평가 행 |

## 5. Train·Validation·Test 성능

Train과 Validation은 Train 전용 개발 모델로 평가했다. Test는 Train+Validation 최종 모델로 평가했다.

| Split | 모델 학습 범위 | 행 | MAE | RMSE | WAPE | R² |
|---|---|---:|---:|---:|---:|---:|
| Train | Train only | 25,893 | 0.646 | 1.191 | 1.136% | 0.999748 |
| Validation | Train only | 5,355 | 0.701 | 1.261 | 1.234% | 0.999718 |
| Test | Train+Validation | 5,355 | 0.704 | 1.451 | 1.237% | 0.999627 |

Train 대비 Validation WAPE 상대 악화는 `8.575%`다. 절대 WAPE 차이는 `0.097%p`로, 학습 성능과 검증 성능의 차이는 크지 않다. 다만 합성 데이터 특성 때문에 이것만으로 실제 일반화를 증명할 수는 없다.

## 6. Test 기준선 비교

| 비교 대상 | MAE | RMSE | WAPE |
|---|---:|---:|---:|
| V4.0 재학습 | 0.704 | 1.451 | 1.237% |
| 4주 동일요일 기준선 | 3.316 | 5.369 | 5.828% |
| 상대 감소율 | 78.772% | 72.963% | 78.772% |

기준선 비교는 같은 5,355개 Test 행에서 수행했다.

## 7. Learning Curve

고정 V4 설정을 사용하고 Train의 시간 순서상 앞부분을 25%·50%·75%·100%로 늘리면서 동일 Validation을 평가했다.

| Train 비율 | 학습 행 | 학습 Cutoff 종료 | Validation MAE | Validation RMSE | Validation WAPE |
|---:|---:|---|---:|---:|---:|
| 25% | 6,426 | 2025-04-18 | 0.818 | 1.475 | 1.439% |
| 50% | 12,915 | 2025-07-30 | 0.740 | 1.339 | 1.301% |
| 75% | 19,404 | 2025-11-10 | 0.725 | 1.300 | 1.275% |
| 100% | 25,893 | 2026-02-21 | 0.701 | 1.261 | 1.234% |

학습 데이터를 늘릴수록 Validation MAE·RMSE·WAPE가 모두 개선됐다. 현재 범위에서는 데이터 추가 효과가 남아 있다.

## 8. D+1~D+7 Test 성능

| Horizon | 행 | MAE | RMSE | WAPE | 기준선 대비 WAPE 감소 |
|---|---:|---:|---:|---:|---:|
| D+1 | 765 | 0.157 | 0.370 | 0.275% | 95.207% |
| D+2 | 765 | 0.313 | 0.642 | 0.551% | 90.463% |
| D+3 | 765 | 0.527 | 0.919 | 0.925% | 83.779% |
| D+4 | 765 | 0.723 | 1.206 | 1.269% | 77.670% |
| D+5 | 765 | 0.877 | 1.468 | 1.537% | 72.800% |
| D+6 | 765 | 1.035 | 1.725 | 1.819% | 68.929% |
| D+7 | 765 | 1.295 | 2.602 | 2.291% | 64.168% |

모든 horizon에서 기준선보다 낮은 WAPE를 기록했다. 예상대로 예측 거리가 멀어질수록 오차가 커지며 D+7이 가장 취약하다.

## 9. 호텔·객실유형별 Test 성능

### 9.1 호텔별

| 호텔 | 행 | MAE | RMSE | WAPE | 절대오차 P95 | 최대오차 |
|---|---:|---:|---:|---:|---:|---:|
| DOUGLAS | 1,785 | 0.212 | 0.497 | 2.479% | 1.098 | 3.384 |
| GRAND | 1,785 | 1.219 | 2.151 | 1.061% | 4.385 | 42.496 |
| VISTA | 1,785 | 0.681 | 1.202 | 1.442% | 2.642 | 18.807 |

### 9.2 객실유형별

| 호텔 | 객실유형 | 행 | MAE | RMSE | WAPE | 절대오차 P95 | 최대오차 |
|---|---|---:|---:|---:|---:|---:|---:|
| DOUGLAS | D_DELUXE | 595 | 0.560 | 0.820 | 2.513% | 1.917 | 3.384 |
| DOUGLAS | D_SUITE | 595 | 0.028 | 0.164 | 2.107% | 0.032 | 1.000 |
| DOUGLAS | D_TRAD | 595 | 0.047 | 0.209 | 2.347% | 0.047 | 1.014 |
| GRAND | G_CLUB | 595 | 0.993 | 1.487 | 1.444% | 3.188 | 7.580 |
| GRAND | G_DELUXE | 595 | 2.086 | 3.315 | 0.850% | 6.057 | 42.496 |
| GRAND | G_SUITE | 595 | 0.579 | 0.827 | 1.892% | 1.821 | 4.444 |
| VISTA | V_DELUXE | 595 | 1.312 | 1.885 | 1.190% | 3.445 | 18.807 |
| VISTA | V_SPA | 595 | 0.440 | 0.705 | 2.244% | 1.237 | 3.255 |
| VISTA | V_SUITE | 595 | 0.291 | 0.532 | 2.472% | 1.023 | 2.168 |

저수요 객실유형은 WAPE 분모가 작아 비율이 상대적으로 크게 보이므로 MAE를 함께 해석해야 한다. 최대오차는 `G_DELUXE`에 집중됐다.

## 10. 잔차와 극단오차

| 항목 | 값 |
|---|---:|
| 평균 잔차, 예측-실제 | -0.075실 |
| 잔차 표준편차 | 1.450실 |
| 잔차 왜도 | 4.245 |
| 절대오차 P50 | 0.235실 |
| 절대오차 P90 | 1.923실 |
| 절대오차 P95 | 2.796실 |
| 절대오차 P99 | 5.498실 |
| 최대 절대오차 | 42.496실 |
| 잔차 lag-1 자기상관 | 0.330 |
| 잔차 lag-7 자기상관 | 0.000069 |

최대오차 행은 `GRAND/G_DELUXE`, cutoff `2026-08-24`, target `2026-08-31`, D+7이다. 실제 114실을 156.496실로 예측해 42.496실 과대예측했다. 평균 지표는 좋지만 이 단일 극단오차 때문에 실제 운영 전 예외 원인 분석과 observed shadow 검증이 필수다.

전체 Test 잔차 5,355행과 상위 10개 극단오차는 평가 artifact에 저장했다.

## 11. 통계적 신뢰구간

target_date 기준 7일 moving-block bootstrap을 1,000회 수행했다.

| 항목 | 점 추정 | 95% 신뢰구간 |
|---|---:|---:|
| WAPE 절대 개선 | 4.591%p | 4.227~4.762%p |
| WAPE 상대 개선 | 78.772% | 77.300~79.908% |
| MAE 개선 | 2.612실 | 2.404~2.707실 |

평가 대상 target-date는 91일이며, 날짜별 후보 승률은 100%였다. 이 신뢰구간도 합성 데이터 내부의 불확실성만 설명한다.

## 12. 예측구간

| 구간 | 명목 포함률 | 실제 포함률 | 절대 보정오차 | 평균 폭 |
|---|---:|---:|---:|---:|
| 80% | 80.0% | 80.635% | 0.635%p | 2.270실 |
| 95% | 95.0% | 94.024% | 0.976%p | 4.450실 |

95% 구간은 명목값보다 0.976%p 낮지만 현재 기술 최소기준 90%는 충족한다.

## 13. 단일 요청 추론시간

| 항목 | 값 |
|---|---:|
| 측정 요청 | 500회 |
| Warm-up | 10회 |
| 평균 | 5.492ms |
| P50 | 5.123ms |
| P95 | 7.263ms |
| P99 | 13.337ms |
| 최대 | 17.038ms |

측정 방식은 `in_process_single_row_request`다. 특징 전처리와 모델 예측은 포함하지만 네트워크, API 인증, 직렬화는 제외한다. 따라서 서비스 전체 응답시간 SLO 증거는 아니다.

## 14. 제출 체크리스트

| 평가 항목 | 상태 | 증거 |
|---|---|---|
| 기준선 이름·수치·개선율 | PASS | JSON 전체·그룹 지표 |
| Train 대 Validation | PASS | Train 전용 모델로 동일 계산 |
| D+1~D+7 개별 성능 | PASS | `test_by_horizon.csv` |
| 호텔·객실유형 상세표 | PASS | property·room_type CSV |
| 수요구간 상세표 | PASS | `test_by_demand_band.csv` |
| 잔차·P90·P95·P99·최대오차 | PASS | JSON·`test_residuals.csv.gz` |
| target-date bootstrap 95% CI | PASS | 1,000회·7일 block |
| 요청 단위 P50·P95·P99 | PASS | 단일 행 500회 |
| Learning Curve | PASS | 25%·50%·75%·100% |
| 모델 크기·hash | PASS | manifest·checksum |
| Python·라이브러리 버전 | PASS | manifest |
| 학습 commit 고정 | PARTIAL | commit 기록, dirty tree |
| 실제 PMS 평가 | FAIL | 미제공 |
| 실제 PIT 시점 증명 | FAIL | 필수 필드 누락 |

## 15. 재현환경

| 항목 | 값 |
|---|---|
| Git commit | `51c7b62dcbeedf4f1454e0f193d8f940bb710156` |
| Git dirty | `true` |
| Python | 3.13.15 |
| joblib | 1.5.3 |
| numpy | 2.5.2 |
| pandas | 2.3.3 |
| scikit-learn | 1.9.0 |
| scipy | 1.18.1 |

commit은 기록됐지만 미커밋 변경이 있으므로 완전한 재현 기준점은 아니다. 제출 직전 변경사항을 commit하고 같은 입력 hash로 한 번 더 재학습해야 한다.

## 16. 검증 결과

### 16.1 V4 모델·데이터 검증

| 검증 | 결과 |
|---|---|
| ML 전체 테스트 | PASS, 47개 |
| 모델 재로딩·Test 재추론 | PASS |
| 저장 예측 대 재추론 최대 차이 | PASS, `5.68e-14실` |
| Test 지표 독립 재계산 | PASS, MAE·RMSE·WAPE·R² 완전 일치 |
| 산출물 checksum | PASS, 14/14 일치 |
| 입력 Train·Validation·Test hash | PASS, 3/3 일치 |
| split·purge 계약과 manifest | PASS |
| 분할 간 cutoff 중복 | PASS, 0건 |
| Train target 대 Validation cutoff | PASS, 이전 시점에서 종료 |
| Validation target 대 Test cutoff | PASS, 이전 시점에서 종료 |
| 식별 grain 중복 | PASS, 전 split 0건 |
| 64개 특징 결측 | PASS, 전 split 0건 |
| 수치 특징 NaN·무한대 | PASS, 전 split 0건 |
| D+1~D+7 행 균형 | PASS, Validation·Test 각 horizon 765행 |
| 예측 NaN·무한대·음수 | PASS, 0건 |
| 판매 가능 객실 초과 예측 | PASS, 0건 |
| PIT 시점 증명 필드 | FAIL, 필수 5개 모두 없음 |
| 실제 PMS 평가 | FAIL, 합성 데이터만 존재 |

재계산 Test 결과는 MAE `0.7039747375`, RMSE `1.4514984806`, WAPE `0.0123728501`, R² `0.9996267171`이며 저장 JSON과 수치 차이가 없다.

### 16.2 저장소 전체 Gate

| 검증 | 결과 |
|---|---|
| OpenAPI snapshot | PASS, `OPENAPI_CONTRACT_VERIFIED` |
| 아키텍처 invariant | PASS, source 520개 |
| repository integrity | PASS, 파일 1,378개 |
| code documentation | PASS, source 604개·실행 설정 81개 |
| Python compileall | PASS |
| Trino access-control JSON | PASS |
| Frontend test | PASS, 43개 |
| Frontend production build | PASS, 2,698 modules |
| Compose profile config | PASS, CI 정의 11/11 조합 |
| `git diff --check` | PASS, 기존 inventory CRLF 경고 1건 |
| 전체 Python suite | **FAIL**, 2,239 passed·2 failed·74 skipped·subtest 548 passed |

전체 Python suite의 실패 2건은 이번 V4 변경 파일이 아니다.

1. `tests/ai/test_node2_serverless_worker.py::test_local_image_receipt_is_source_bound_and_not_a_gpu_pass`: 기존 Node2 local image receipt와 현재 `handler.py`, `preflight_node2_vllm.py`, `verify_node2_serverless_image_static.py`의 SHA-256이 불일치한다. CI에서도 이 검사는 별도 `continue-on-error` 후보 증거로 분리되어 있다.
2. `tests/backend/test_report_document.py::ReportDocumentTest::test_actual_weasyprint_candidate_and_final_source_have_page_parity`: 로컬 Windows에 `libgobject-2.0-0`이 없어 WeasyPrint가 로드되지 않았다. Python package는 설치됐지만 네이티브 runtime이 없는 환경 실패다.

따라서 V4 전용 검증은 통과했지만 저장소 전체 Gate는 엄격하게 `FAIL`로 기록한다. FastAPI `on_event` deprecation warning 2건은 기존 경고이며 이번 V4 평가 결과에는 영향을 주지 않는다. skip 74건은 PASS 수에 포함하지 않았다.

### 16.3 jaehong 브랜치 적용 전 검증

재학습·평가 변경을 `origin/jaehong` 기반 전용 브랜치 `codex/jaehong-ml-v4`에 적용한 뒤 같은 저장소 Gate를 다시 실행했다. V4 ML 경로는 통과했지만 jaehong 원본에 존재하던 RAG·Backend·release archive 문제가 확인됐다.

| 검증 | 결과 |
|---|---|
| V4 ML 테스트 | PASS, 39개 |
| Frontend 테스트 | PASS, 26개 |
| Frontend production build | PASS, 2,689 modules |
| Compose profile config | PASS, 11/11 조합 |
| OpenAPI snapshot | PASS |
| 아키텍처 invariant | PASS, source 353개 |
| Python compileall | PASS |
| `git diff --check` | PASS |
| 전체 suite 수집 | FAIL, `torch` 미설치로 RAG test collection 중단 |
| CI core 분리 suite | FAIL, 1,260 passed·22 failed·39 skipped·subtest 258 passed |
| code documentation | FAIL, 기존 RAG·Frontend 문서화 위반 29건 |
| repository integrity | FAIL, 기존 RAG 결과 JSON의 Unicode 대체문자 1건 |

core 실패는 HTTP runtime timeout, metric governance, runtime generality, release archive checksum 계열이다. 이번 V4 ML 파일의 테스트 실패는 없다. 따라서 jaehong feature 브랜치 push는 변경 보존 목적으로 수행할 수 있지만, dev 병합·운영 배포 승인의 근거로 사용할 수 없다.

## 17. 운영 차단 사유와 다음 조치

1. 실제 PMS PIT snapshot으로 동일 파이프라인을 재학습·평가한다.
2. `reservation_as_of_at`, `capacity_as_of_at`, `event_as_of_at`, `signal_source_kind`, `signal_is_synthetic`를 원천부터 보존한다.
3. `G_DELUXE` D+7 최대오차 42.496실의 원인을 실제 데이터에서 확인한다.
4. 최소 90일 observed shadow에서 동일 지표와 서비스 전체 latency를 측정한다.
5. working tree를 commit한 뒤 입력 hash를 유지해 최종 제출 artifact를 다시 생성한다.
6. 사람 승인자와 승인시각을 기록한 뒤에만 runtime을 활성화한다.

## 18. 증거 파일

- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/model_manifest.json`
- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/model.joblib`
- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/checksums.sha256.json`
- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/evaluation/submission_evaluation.json`
- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/evaluation/learning_curve.csv`
- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/evaluation/test_by_horizon.csv`
- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/evaluation/test_by_property.csv`
- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/evaluation/test_by_room_type.csv`
- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/evaluation/test_by_demand_band.csv`
- `data/processed/ml_operational_v4/retrained_submission_v4_20260901/evaluation/test_residuals.csv.gz`

## 19. 문서 제약사항

저장소에 필수 `docs/문서관리규칙.md`와 `docs/markdown/document_specs/산출물작성규격.md`가 없다. 외부 문서 정책 검사기의 기본 검사는 통과했지만 저장소 고유 규칙은 완전히 적용할 수 없다. 수치와 artifact의 동기화는 직접 대조했다.

## 변경 내역

| 버전 | 일자 | 내용 |
|---|---|---|
| 1.0 | 2026-09-01 | 기존 합성 평가와 운영 차단 사유 최초 정리 |
| 1.1 | 2026-09-01 | V4 단독 purged 재학습, 제출 지표·상세표·bootstrap·latency·재현정보 반영 |
| 1.2 | 2026-09-01 | 모델 독립 재추론·데이터 품질 검사와 저장소 전체 Gate 결과 반영 |
| 1.3 | 2026-09-01 | origin/jaehong 기반 적용 후 V4·Frontend·Compose 통과와 기존 저장소 실패 기록 |

## 20. 결론

V4.0은 합성 데이터 기준 제출용 기술 평가지표를 대부분 갖췄고, Test WAPE 1.237%와 기준선 대비 78.772% 개선을 기록했다. V4 모델·데이터 검증은 통과했지만 jaehong 적용 브랜치의 저장소 전체 Gate에는 기존 RAG·Backend·release archive 실패가 남았다. 또한 실제 PMS 평가와 PIT provenance가 없으며 D+7 극단오차가 존재한다. 따라서 현재 결과는 `합성 데이터 V4 기술 검증 완료`와 `jaehong feature 브랜치 push 완료`로만 표현할 수 있고, `저장소 전체 검증 PASS`, `dev 병합 승인`, `운영 승인 완료` 또는 `실제 호텔 정확도 입증`으로 표현해서는 안 된다.
