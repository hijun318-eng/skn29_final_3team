# Answervice ML 기획 정합성 최종 검증보고서

| 항목 | 내용 |
|---|---|
| 문서 버전 | v1.1 |
| 기준일 | 2026-08-10 |
| 작업 위치 | 저장소 루트의 `src/ml` |
| 기획 기준 | `docs/Answervice_기획서.md` §13 |
| 공식 ML 후보 | 예약 No-show 이진분류 1개 |
| 참고 분석 | 객실수요 7일 예측 회귀 |
| 종합 판정 | **분석 산출물 정합성 PASS / 공식 ML 활성화 BLOCKED** |

## 1. 결론

기획서의 최소·안전 방안을 채택했다. 공식 P2 ML-as-a-Tool 후보는 `predict-reservation-no-show` 1개로 제한하고, 객실수요 7일 예측은 오프라인 기술검증 산출물로 분리했다.

현재 No-show 원천은 유효하지 않다. 기존 PMS export에는 `NO_SHOW`가 0건이며 후보 원천에는 예측 기준시점 이후 결과가 확정됐음을 증명하는 `outcome_recorded_at`이 없다. 따라서 기존 ONNX와 성능은 과거 기술 fixture로만 보존하며 학습·MCP·운영 활성화를 차단한다.

| 대상 | 현재 지위 | 허용 범위 |
|---|---|---|
| No-show 이진분류 | P2 미래 후보, `INACTIVE` | 계약·코드·과거 산출물 검토 |
| 객실수요 7일 예측 | 오프라인 참고 분석 | 회귀 성능·28행 예측 재현 |
| MCP server | 미도입 | I5 이후 R1 별도 승인 전 등록 금지 |

## 2. 기획서 요구사항 반영 결과

| 기획서 요구사항 | 반영 결과 | 판정 |
|---|---|---|
| No-show 대표 모델 1개 | 공식 후보를 No-show 1개로 제한 | 반영 |
| 여러 모델 동시 Tool 구현 방지 | 객실수요 모델을 registry·router에서 제외 | 반영 |
| Feature 기준시점 | 체크인 전날 18시로 고정 | 반영 |
| 미래정보 누수 방지 | `outcome_recorded_at > feature_as_of` 필수 | 반영 |
| Feature Set 계보 | snapshot ID·추출 시각·원천 SHA-256 필수 | 반영 |
| ONNX·Runtime 일치 | 과거 fixture PASS, 유효 원천 재학습 후 재검증 필요 | 부분 |
| Tool 입력·출력 계약 | entity key·schema·기준시점·버전·실행 ID 정의 | 반영 |
| UI 예측 구분 | 응답 계약만 존재, 실제 화면 미구현 | 미완료 |
| 감사 로그 | schema fixture만 존재, 영구 저장 미연결 | 미완료 |
| 실제 RDB Feature | 과거 로컬 Trino 기록, 운영 adapter 미연결 | 미완료 |
| 운영 MCP E2E | 현재 P0/P1 범위 밖 | 대기 |

## 3. 수정한 맹점

### 3.1 No-show에 stay 행을 강제하던 잘못된 조건

PMS 설계상 `CANCELLED`, `NO_SHOW` 예약은 stay를 만들지 않을 수 있다. 따라서 `pms_stays`에 `NO_SHOW` 행이 없다는 사실만으로 원천을 실패 처리하던 기준을 제거했다.

대신 다음 조건으로 라벨을 검증한다.

```text
reservation_status = NO_SHOW
AND outcome_recorded_at > prediction_cutoff_at
AND source_snapshot_id IS NOT NULL
AND source_extracted_at IS NOT NULL
```

`outcome_recorded_at`은 라벨 확정 검증에만 사용하고 모델 Feature에는 포함하지 않는다.

### 3.2 합성 규칙으로 양성 라벨을 복원하던 문제

현재 학습 코드는 `SYNTHETIC_RULE_V1`을 새로 생성하지 않는다. 원천 `NO_SHOW`가 0건이면 즉시 실패한다. 저장된 기존 모델은 비교 실험 이력일 뿐 재사용 가능한 공식 모델이 아니다.

### 3.3 승인 전 local demo 우회

과거에는 `local_demo`가 registry의 비활성 상태를 메모리에서 `APPROVED`로 바꿀 수 있었다. 현재는 readiness의 모든 Gate가 `PASS`가 아니면 No-show local demo를 거부한다. 객실수요 모델은 참고 분석이므로 local demo 자체를 거부한다.

### 3.4 분석 모델과 운영 Tool 혼동

| 구분 | No-show | 객실수요 7일 예측 |
|---|---|---|
| 공식 P2 후보 | 예 | 아니오 |
| 메인챗 ML routing | 승인 전 차단 | 제외 |
| MCP template | 미등록 | 미등록 |
| 저장 모델 | 과거 ONNX fixture | Joblib 참고 모델 |
| 재학습 조건 | 승인 snapshot과 결과시점 필수 | 기존 합성 CSV 계약 |

## 4. 모델 분석 결과

### 4.1 No-show 이진분류

다음 수치는 `SYNTHETIC_RULE_V1` 과거 라벨에 대한 기술검증 결과다. 운영 성능으로 인용하지 않는다.

| 지표 | TEST 결과 |
|---|---:|
| 행 수 | 20,701 |
| PR-AUC | 0.01356 |
| ROC-AUC | 0.68275 |
| Precision | 1.45% |
| Recall | 30.82% |
| F1 | 2.76% |
| Top15 Lift | 1.93배 |

모델은 자동 취소·보증금 부과·고객 제재에 사용할 수 없다. 유효 원천 재학습 후에도 상위 위험 예약의 연락 우선순위 보조까지만 검토한다.

### 4.2 객실수요 7일 예측

| 구분 | 행 수 | MAE | RMSE | WAPE | R² |
|---|---:|---:|---:|---:|---:|
| TRAIN | 30,492 | 0.4591실 | 0.7670실 | 1.0495% | 0.999483 |
| VALIDATION | 10,220 | 0.9141실 | 1.4813실 | 1.9646% | 0.998261 |
| TEST | 5,852 | 0.7994실 | 1.3084실 | 1.7416% | 0.998588 |

회귀 결과는 단일 호텔 합성 seed의 기술검증이다. 공식 No-show Tool의 성능이나 운영 준비도를 보강하는 증거로 사용하지 않는다.

## 5. 활성화 Gate

| 순서 | Gate | 현재 상태 | 완료 기준 |
|---:|---|---|---|
| 1 | I5 완료·R1 P2 승인 | 대기 | F-03 실행 묶음과 역할별 허용 경로 승인 |
| 2 | PMS 원천 라벨 | BLOCKED | `NO_SHOW`와 기준시점 이후 `outcome_recorded_at` 확보 |
| 3 | 원천 계보 | BLOCKED | snapshot ID·추출 시각·원천 파일 SHA-256 기록 |
| 4 | 유효 원천 재학습 | Not Run | 동일 시간 분할로 후보 비교·TEST 1회 평가 |
| 5 | ONNX 재생성·일치 | Not Run | 동일 fixture 허용오차 내 일치 |
| 6 | Feature adapter | 미구현 | 승인된 Trino/RDB 기준시점 조회 |
| 7 | UI 표시 | 미구현 | 모델 예측·합성 여부·기준시점 표시 |
| 8 | 감사 영구 저장 | 미구현 | 실행 ID·모델·Feature version 저장 |
| 9 | hard timeout·fallback | 미검증 | 실제 배포 경계에서 2초 중단과 안전 실패 |
| 10 | 운영 E2E | 현재 범위 밖 | 인증·RDB·UI·감사를 포함한 대화 호출 PASS |

모든 Gate가 PASS가 아니면 Tool registry는 비활성 상태를 유지한다.

## 6. 재학습 입력 계약

필수 환경값은 다음과 같다.

```powershell
$env:ANSWERVICE_ML_SOURCE_DIR='D:\approved\pms_snapshot\full'
$env:ANSWERVICE_ML_SOURCE_SNAPSHOT_ID='pms-snapshot-v1'
$env:ANSWERVICE_ML_SOURCE_EXTRACTED_AT='2026-08-10T00:00:00Z'
```

필수 예약 컬럼에는 기존 Feature 원천과 함께 `reservation_status`, `outcome_recorded_at`, `is_forecast`, `is_synthetic`가 포함돼야 한다. `outcome_recorded_at`, 실제 상태, 실제 체크인·체크아웃 정보는 Feature로 사용하지 않는다.

## 7. 재검증 결과

| 검증 | 결과 |
|---|---:|
| No-show 원천·서비스·Gate 단위 테스트 | 15/15 PASS |
| 객실수요 참고 모델 단위 테스트 | 8/8 PASS |
| 메인챗 ML routing 계약 테스트 | 4/4 PASS |
| No-show 과거 산출물 정합성 | PASS, 공식 활성화는 BLOCKED |
| 공통 로컬 검증 항목 | 13/13 PASS |
| MCP server template | 빈 registry PASS |
| `git diff --check` | PASS |

첫 실행에서는 저장소 루트에서 패키지 테스트를 호출해 import 경로 오류가 발생했다. 패키지별 실행 경로로 바로잡아 위 결과를 확인했으며, 모델 또는 코드 결함으로 계산하지 않았다.

## 8. 최종 판정

> 현재 ML 산출물은 기획서에 맞게 “No-show 단일 공식 후보 + 객실수요 오프라인 참고 분석”으로 정리됐다. No-show의 유효 원천과 P2 승인이 없으므로 운영 등록은 차단한다. 현재 PASS는 분석 산출물과 차단 정책의 정합성을 뜻하며 서비스 활성화 완료를 뜻하지 않는다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.1 | 2026-08-10 | No-show 단일 후보 확정, 객실수요 참고 분석 분리, 결과시점·snapshot 계보·승인 전 우회 차단 반영 |
| v1.0 | 2026-08-04 | 두 모델 로컬 기술검증 기록 |
