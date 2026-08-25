# Answervice 예약 No-show 이진 분류 ML 결과보고서 v1.3

작성일: 2026-08-04
정정일: 2026-08-10
대상: `ML-as-a-Tool` P2 예약 No-show 이진 분류 1개
데이터: 전량 합성 데이터
현재 Tool 상태: `INACTIVE`

## 1. 결론

기획서의 방향은 맞다. 기존 객실수요 회귀 모델을 바꾸지 않고, 예약 1건 단위 No-show 이진 분류 모델을 별도 폴더에 구현했다.

과거 기술검증에서는 학습, 시간 순서 평가, Feature 계약, ONNX 변환과 로컬 fixture를 재현했다. 그러나 현재 PMS export에는 `NO_SHOW`가 0건이고 결과 확정시각이 없어 과거 `SYNTHETIC_RULE_V1` 모델을 공식 후보로 승격할 수 없다. 현재 구현은 `source_snapshot_id`, 추출 시각, 기준시점 이후 `outcome_recorded_at`이 없으면 재학습을 중단하며, readiness가 모두 PASS가 아니면 `local_demo` 우회 활성화도 차단한다.

| 최종 판단 항목 | 결과 |
|---|---|
| 공식 ML 대상 | 예약 No-show 이진 분류 1개 |
| 기존 객실수요 회귀 | 참고 산출물로 유지, 공식 Tool 연결 대상에서 제외 |
| 선택 모델 | `LogisticRegression` |
| TEST PR-AUC / ROC-AUC | 0.01356 / 0.68275 |
| TEST Recall / Precision / F1 | 30.82% / 1.45% / 2.76% |
| TEST Top15 Recall / Precision / Lift | 28.93% / 1.48% / 1.93배 |
| TEST Brier Score | 0.00760 |
| ONNX Runtime 일치 | PASS, 1,000행 분류 불일치 0건 |
| 로컬 Tool 계약 테스트 | 과거 fixture 기록, 활성화 근거 아님 |
| 메인 챗·stdio MCP | 현재 범위에서 미도입 |
| Tool registry | `INACTIVE` |

## 2. 기획서 적용 범위

| 기획 단계 | 적용 결과 | 상태 |
|---|---|---|
| RDB Feature Set 조회 | PMS export 사용, PostgreSQL 조회 SQL·원천 hash 저장 | 부분 적용 |
| 입력 schema·기준 시점 검증 | `reservation_id`, 체크인 전날 18시, Feature v1.0 계약 | 완료 |
| 모델 학습 | Baseline·Logistic·HistGB·LightGBM·XGBoost·RandomForest 비교 | 완료 |
| ONNX 변환 | 선택 모델을 ONNX로 변환 | 완료 |
| ONNX Runtime 서빙 검증 | 동일 1,000행 일치와 로컬 예약 ID 호출 확인 | 완료 |
| MCP Tool 등록 | I5 이후 R1 별도 Gate 승인 시 수행 | 현재 범위 밖 |
| 대화 중 호출 | 승인 후 메인챗 계약에 연결 | 현재 범위 밖 |
| UI·감사 로그 | 응답 표시 문구·로컬 감사 fixture 확인 | 부분 적용 |

`부분 적용`은 조회 SQL은 준비했지만 실시간 RDB 대신 고정 export를 사용했다는 뜻이다. 결과를 성공으로 과장하지 않기 위해 대화 호출과 운영 UI·감사 저장소가 확인되기 전에는 활성 상태로 표시하지 않는다.

## 3. 데이터 정의와 검증

### 3.1 업무 정의

| 항목 | 적용 기준 |
|---|---|
| 한 행의 단위 | `reservation_id` 1건 |
| 타깃 | `is_no_show`: No-show 1, 정상 체크인·완료 0 |
| 제외 | 사전 취소, 결과 미확정 미래 예약 |
| 예측 기준 시점 | 체크인 예정일 전날 18:00, Asia/Seoul |
| 데이터 표시 | `is_synthetic=true`, `label_source=SYNTHETIC_RULE_V1` |
| 누수 차단 | 상태·실제 체크인·취소 결과·환불·타깃 컬럼 입력 제외 |

현재 export 상태는 `CHECKED_OUT` 167,070건, `CANCELLED` 48,570건, `BOOKED` 4,359건, `CHECKED_IN` 1건이며 `NO_SHOW`는 0건이다. 학습 라벨은 원천 SQL의 No-show 확률 설계를 seed `20260804`와 SHA-256 기반 결정 규칙으로 복원했다.

### 3.2 시간 순서 분할

| 구분 | 기간 | 행 수 | No-show 수 | 비율 |
|---|---:|---:|---:|---:|
| TRAIN | 2022-01-01~2024-12-31 | 109,770 | 915 | 0.8336% |
| VALIDATION | 2025-01-01~2025-12-31 | 36,600 | 301 | 0.8224% |
| TEST | 2026-01-01~2026-07-28 | 20,701 | 159 | 0.7681% |
| INFERENCE | 2026-07-29 이후 | 4,359 | 미확정 | — |

무작위 분할은 사용하지 않았다. 예약 ID 중복, 타깃 누락, 피처 누락, 기간 중첩, 금지 피처 포함은 모두 0건이다.

## 4. 모델 비교

PR-AUC를 주 선택 지표로 사용하고 `Recall·Precision·Lift@Top15%`, Brier Score, 월별 안정성을 함께 확인했다. Accuracy는 클래스 불균형 때문에 주 지표에서 제외했다. 모델 선택에는 TRAIN과 VALIDATION만 사용하고 TEST는 최종 선택 모델 1개에만 사용했다.

### 4.1 고정 확률 Baseline

| 구분 | 행 수 | 발생률·PR-AUC | ROC-AUC | Brier |
|---|---:|---:|---:|---:|
| TRAIN | 109,770 | 0.00834 | 0.50000 | 0.00827 |
| VALIDATION | 36,600 | 0.00822 | 0.50000 | 0.00816 |

### 4.2 VALIDATION 모델 선택 비교

| 모델 | 최적 설정 | PR-AUC | LR 대비 | Recall@15 | Precision@15 | Lift@15 | Brier | 월별 PR 표준편차 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| LogisticRegression | 기본 | 0.014298 | 기준 | 29.90% | 1.64% | 1.99배 | 0.008131 | 0.003758 |
| LogisticRegression | `class_weight=balanced` | 0.014362 | +0.000064 | 27.57% | 1.51% | 1.84배 | 0.246276 | 0.003761 |
| HistGradientBoosting | 기본 | 0.016187 | +0.001889 | 31.23% | 1.71% | 2.08배 | 0.008130 | 0.021470 |
| LightGBM | `scale_pos_weight=10` | 0.016406 | +0.002108 | 30.23% | 1.66% | 2.02배 | 0.015394 | 0.007763 |
| XGBoost | `scale_pos_weight=1` | 0.014504 | +0.000206 | 31.56% | 1.73% | 2.10배 | 0.008150 | 0.005870 |
| RandomForest | 가중치 없음 | 0.014605 | +0.000307 | 30.56% | 1.68% | 2.04배 | 0.008137 | 0.006222 |

LightGBM과 XGBoost는 각각 7개 `scale_pos_weight` 값으로 제한 탐색했고 RandomForest는 2개 설정만 참고 비교했다. 총 16개 추가 실험이다.

### 4.3 모델 선택 결과

LightGBM의 PR-AUC가 가장 높았지만 개선폭이 최소 기준 0.005에 못 미쳤고 Brier Score가 크게 나빠졌다. `class_weight=balanced` LogisticRegression도 Brier가 0.246276으로 악화돼 제외했다. HistGradientBoosting은 월별 변동이 컸고 XGBoost·RandomForest의 개선폭은 거의 없었다. PR-AUC 개선폭, Top15 성능, Brier, 월별 안정성 게이트를 모두 통과한 후보가 없어 기본 LogisticRegression을 유지했다. 다른 후보는 TEST에서 평가하지 않았다.

## 5. Top15 업무량 정책과 TEST

고정 F1 임계값 대신 체크인 예정 예약의 예측점수 상위 15%를 연락 우선 대상으로 정했다. 이 방식은 매일 처리량을 고정하고 모델의 상대 순위 능력을 사용한다. 저장된 임계값 `0.015165`는 VALIDATION 상위 15%의 참고 경계이며, 실제 배치 판정은 순위로 수행한다.

| 구분 | 전체 행 | 상위 15% | 탐지 No-show | Recall@15 | Precision@15 | Lift@15 |
|---|---:|---:|---:|---:|---:|---:|
| VALIDATION | 36,600 | 5,490 | 90 | 29.90% | 1.64% | 1.99배 |
| TEST | 20,701 | 3,106 | 46 | 28.93% | 1.48% | 1.93배 |

TEST 상위 15%에서는 무작위 선택보다 No-show 밀도가 1.93배 높았다. 하지만 연락 100건 중 실제 No-show는 약 1.5건이므로 자동 제재나 확정 판단에는 사용하지 않고 연락 순서를 정하는 보조 기능으로 제한한다. VALIDATION 임계값을 TEST에 그대로 적용하면 분포 변화로 16.36%가 선택되므로 운영에서는 고정 순위 정책을 사용해야 한다.

## 6. 확률·편향·합성 패턴 점검

| 점검 | 결과 | 판단 |
|---|---|---|
| 전체 평균 예측확률 | VALIDATION 0.8238%, TEST 0.8328% | 실제 0.8224%, 0.7681%와 전체 수준은 유사 |
| TEST Brier Score | 0.00760 | 고정 확률 Baseline 수준보다 소폭 개선 |
| ECE 10분위 | VALIDATION 0.00150, TEST 0.00179 | 가중치 없는 Logistic 확률을 유지 |
| 사후 Calibration | 미적용 | 독립 TEST를 보정 학습에 재사용하지 않음 |
| 모델 복잡도 효과 | LightGBM 최대 PR 개선 +0.00211 | 최소 교체 기준 미달 |
| 채널별 경고 | OTA만 경고 발생 | 채널 의존이 지나침 |
| 채널·고객군 조합 | 가능한 9개 중 3개만 존재 | 합성 생성 규칙의 구조적 결합 경고 |
| 실제 PMS No-show 라벨 | 0건 | 실제 라벨로 재검증 필요 |

이 모델은 확률의 전체 평균은 비교적 맞지만 개별 예약 구분력은 낮다. 특히 TEST 경고가 OTA에 집중되고 `booking_channel`과 `market_segment`가 1:1로 묶여 있어 실제 데이터 일반화를 증명하지 못한다.

## 7. ONNX와 Tool 계약

| 항목 | 결과 |
|---|---|
| ONNX 모델 | `reservation_no_show_model.onnx` 생성 |
| 비교 표본 | TEST 앞 1,000행 |
| 최대 확률 차이 | 0.000000000000000165 |
| 임계값 기준 분류 불일치 | 0건 |
| 결과 | PASS |
| 동일 seed 전체 재실행 | 후보 실험·선택표·평가·Top15·예측·ONNX 6개 SHA-256 일치 |

### 7.1 로컬 Tool 실행 검증

| 검증 | 결과 |
|---|---|
| 동일 예약·기준 시점 2회 호출 | 확률 `0.0066517027` 동일 |
| 실행 ID | 호출마다 고유 `mlrun-*` 발급 |
| 정상 응답 | `SUCCESS`, `LOW`, 합성 예측 표시 |
| 업무량 정책 | `TOP_15_PERCENT_DAILY_COHORT`, rank 2,545/4,359 |
| 없는 예약 | `FEATURE_NOT_FOUND` |
| Feature 버전 불일치 | `SCHEMA_MISMATCH` |
| 입력·기준 시점·재현 테스트 | 단위 테스트 7건 PASS |
| 로컬 감사 fixture | 4행 JSONL 생성 |

PostgreSQL 조회 기준은 `sql/reservation_no_show_feature_set_v1.sql`로 고정했다. 로컬 실행기는 예약 ID로 Feature snapshot을 조회하고 ONNX Runtime을 호출한다.

### 7.2 메인 챗·MCP 연결 상태

아래 PASS는 2026-08-04 과거 로컬 fixture 기록이다. 현재 P0/P1 범위에는 MCP server가 도입되지 않았고, 유효한 No-show 원천 모델도 없으므로 현재 활성화 증거로 사용하지 않는다.

| 검증 | 결과 |
|---|---|
| 메인 챗 No-show 예측 질문 | `ML_ONLY` |
| No-show 처리 규정 질문 | `RAG_ONLY` |
| No-show 예측과 절차 질문 | `ML_AND_RAG` |
| 운영 등록 | `enabled=false`, `NOT_APPROVED`, Tool 목록 미노출 |
| 로컬 합성 demo | 현재 readiness FAIL로 우회 활성화 차단 |
| stdio MCP handshake | 과거 fixture 기록, 현재 범위에서는 Not Run |
| 응답 evidence | `MODEL_PREDICTION`, `PREDICTION_NOT_OBSERVED` |
| hard timeout fixture | 2초 계약·강제 timeout 처리 PASS |
| ML+RAG 결합 | 모델 예측과 문서 근거를 별도 evidence로 유지 |

로컬 실행용 실제 MCP 설정은 `artifacts/mcp_server_config.local.json`에 생성된다. 이 파일은 현재 PC 경로를 포함하므로 Git에서는 제외하며, 이식용 템플릿은 `config/mcp_server_config.template.json`으로 관리한다.

입력 계약은 `reservation_id`, `feature_as_of`, `feature_set_version`, `input_schema_version`을 요구한다. 출력에는 No-show 확률, Top15 위험등급·순위, 오류 상태, 합성 여부, 모델·Feature 버전, 기준 시점, 실행 ID를 포함한다. 화면에는 반드시 `모델 예측`과 `합성 데이터 기반 예측`을 표시한다.

## 8. 사용 제한사항과 활성화 게이트

현재 결과는 학습·ONNX·계약 검증에 사용할 수 있다. 다음 게이트 전에는 운영 Tool로 활성화하지 않는다.

| 게이트 | 현재 상태 | 완료 기준 |
|---|---|---|
| Feature 기준 시점·누수 | PASS | 현재 유지 |
| PMS 원천 No-show 라벨 | FAIL | 확정 `NO_SHOW`와 기준시점 이후 `outcome_recorded_at`이 포함된 예약 원천 재생성 |
| 원천 계보 | FAIL | `source_snapshot_id`·추출 시각·원천 파일 SHA-256 기록 |
| ONNX Runtime 일치 | 과거 fixture | 유효 원천 재학습 후 새 ONNX로 재검증 |
| 로컬 Tool fixture | 과거 fixture | 유효 원천 모델 생성 후 재실행 |
| 메인 챗 Router | 계약만 준비 | I5와 R1 P2 승인 후 연결 |
| MCP JSON-RPC·stdio | 현재 범위 밖 | R1 P2 승인 후 도입·검증 |
| hard timeout | 과거 handler fixture | 실제 배포 경계에서 재검증 |
| 실시간 RDB Feature 조회 | 로컬 PASS | Trino `pms.public` 1행 계약 조회 성공, production 서비스 adapter 연결 필요 |
| 운영 UI 예측 구분 | 미검증 | 실제 화면에 모델 예측·합성 여부·기준 시점 표시 |
| 운영 감사 로그 | 미검증 | 서비스 저장소에 실행 메타데이터 영구 저장 |
| 운영 MCP end-to-end | 현재 범위 밖 | I5와 R1 P2 승인 후 인증·RDB·UI 포함 대화 호출 성공 |
| 운영 hard timeout | 미검증 | 실제 API/MCP 배포 경계에서 2초 중단 확인 |
| Top15 업무량 정책 | 로컬 적용 | 일별 연락 가능 비율을 담당자가 최종 승인 |

## 9. 다음 실행 순서

| 우선순위 | 작업 | 완료 기준 |
|---:|---|---|
| 1 | PMS 합성 원천 재생성 | 예약에 `NO_SHOW` 상태와 기준시점 이후 `outcome_recorded_at`이 존재. PMS 정책상 No-show의 stay 행은 필수 아님 |
| 2 | 실제 원천 라벨 재학습 | `SYNTHETIC_RULE_V1` 파생 라벨 제거, 동일 시간 분할 재평가 |
| 3 | 합성 결합 완화 | 채널·고객군 9개 조합의 현실적 분포와 복수 seed 검증 |
| 4 | Top15 업무량 승인 | 일별 연락 가능 건수와 상위 비율을 함께 결정 |
| 5 | I5·R1 P2 Gate 승인 | F-03 실행 묶음과 역할별 허용 경로 승인 |
| 6 | 서비스 UI·감사·MCP 연결 | 승인 후 동일 fixture, ONNX, hard timeout, fallback, 대화 호출 모두 PASS |

## 10. 재현 산출물

| 산출물 | 위치 |
|---|---|
| Feature 계약 | `artifacts/feature_contract.json` |
| Tool 계약 | `artifacts/tool_contract.json` |
| RDB Feature 조회 SQL | `sql/reservation_no_show_feature_set_v1.sql` |
| Trino Feature 조회 SQL·증적 | `sql/reservation_no_show_feature_set_trino_v1.sql`, `artifacts/rdb_feature_query_fixture.json` |
| Top15 운영 정책 | `config/top15_policy.json` |
| 모델 평가 | `artifacts/model_metrics.csv` |
| 부스팅 16개 실험 | `artifacts/boosting_trial_metrics.csv` |
| 모델 선택 비교 | `artifacts/model_selection_comparison.csv` |
| TEST Top15 지표 | `artifacts/test_top15_metrics.json` |
| Calibration 요약 | `artifacts/calibration_summary.json` |
| 월별 Calibration | `artifacts/monthly_calibration.csv` |
| 데이터 품질 | `artifacts/data_quality_checks.csv` |
| 데이터·원천 hash | `artifacts/dataset_manifest.csv`, `artifacts/source_file_hashes.csv` |
| ONNX 일치 | `artifacts/onnx_parity.json` |
| 로컬 Tool 실행 결과 | `artifacts/tool_fixture_results.json` |
| 로컬 감사 fixture | `artifacts/tool_audit_fixture.jsonl` |
| 로컬 Tool 검증 | `artifacts/local_tool_verification.json` |
| 메인 챗·MCP fixture | `artifacts/main_chat_mcp_fixture.json` |
| 운영 비활성 등록 | `config/mcp_registration.json` |
| MCP server 템플릿 | `config/mcp_server_config.template.json` |
| 활성화 게이트 | `artifacts/readiness_gate.json` |
| 예측 결과 | `artifacts/inference_predictions.csv` |

최종적으로, 이번 산출물은 과거 합성 라벨 기반 알고리즘 비교와 ONNX 기술 fixture다. LightGBM·XGBoost 비교 후 LogisticRegression 선택은 유지됐지만 공식 운영 성능은 아니다. 유효 원천 재학습과 I5·R1 P2 승인 전에는 메인챗·MCP에 등록하지 않으며, 객실수요 모델은 별도 오프라인 참고 분석으로 유지한다.
