# Answervice 객실수요 7일 예측 ML

이 폴더는 `synthetic` 객실수요 CSV를 이용한 오프라인 회귀 기술검증 산출물입니다. 기획서의 공식 P2 대표 모델과 Tool registry 후보는 No-show 이진분류 1개이며, 이 모델은 메인챗·MCP 호출 대상이 아닙니다.

```text
CSV 계약검사
→ Seasonal Naive 기준선
→ XGBRegressor·LGBMRegressor 학습
→ VALIDATION 모델 선정
→ 선정 모델만 TEST 1회 평가
→ 2026-07-28 기준 FORECAST 생성
```

## 데이터 기준

- Label: `rooms_sold`
- Grain: `property_id + target_date + room_type_code + horizon_days`
- Feature: 26개
- Seed: `20260803`
- 분할: 날짜 순서 기반 TRAIN·VALIDATION·TEST·FORECAST
- `room_demand_hidden_label_qa.csv`: 계약 존재 여부만 확인하고 학습·선정·평가에는 사용하지 않음

기본 입력 경로는 다음 상대 위치입니다.

```text
../../data/raw/room_demand
```

## 실행

Python 3.10 이상 환경에 `requirements.txt` 의존성이 있어야 합니다.

두 ML 패키지를 함께 검증할 때는 상위 `src/ml/requirements.txt`와 `src/ml/.venv`를 사용합니다.

```powershell
cd src/ml/room_demand_forecast
python train.py --validate-only
python train.py
python audit_risks.py
python run_main_chat_fixture.py
python -m unittest discover -s tests -v
```

`--validate-only` 결과는 `artifacts/data_contract_summary.json`에 저장되며 학습 완료 증거인 `run_summary.json`을 덮어쓰지 않습니다.

다른 위치에서 실행할 때는 경로를 명시합니다.

```powershell
python train.py `
  --data-dir ..\..\data\raw\room_demand `
  --output-dir .\artifacts `
  --as-of-date 2026-07-28
```

## 주요 산출물

- `data_quality_checks.csv`, `data_profile.json`
- `validation_metrics.csv`, `validation_group_metrics.csv`
- `model_selection.json`
- `test_metrics.csv`, `test_group_metrics.csv`, `test_predictions.csv`
- `feature_importance.csv`
- `forecast_predictions.csv`
- `room_demand_feature_contract.json`
- `room_demand_model_metadata.json`
- `room_demand_model.joblib`
- `prediction_interval_metrics.json`, `prediction_interval_margins.csv`
- `feature_ablation_metrics.csv`, `feature_range_audit.csv`
- `hidden_qa_audit.json`, `risk_register.csv`, `risk_audit_summary.json`

`VALIDATION`에서 가장 좋은 ML 후보가 Seasonal Naive보다 나쁘면 `REVIEW_REQUIRED`로 기록하고 TEST 평가를 실행하지 않습니다.

## 운영 범위

- 현재 저장 모델은 검증된 `joblib` XGBRegressor이며 분석 결과와 28행 예측을 재현하는 용도로만 사용한다.
- 메인챗 라우터, MCP server template, production registry에는 등록하지 않는다.
- 향후 별도 P2 Gate에서 시설 수요예측이 승인될 때만 ONNX·Feature Set·UI·감사·timeout 계약을 새로 검증한다.

## 2026-08-03 로컬 검증 결과

검증 환경은 Python 3.10.20, pandas 2.3.3, scikit-learn 1.7.2, XGBoost 3.2.0, LightGBM 4.6.0입니다.

| 항목 | 결과 |
|---|---:|
| CSV·Manifest 계약검사 | 56/56 PASS |
| 선정 모델 | XGBRegressor |
| VALIDATION Seasonal Naive clipped WAPE | 10.20% |
| VALIDATION XGBRegressor clipped WAPE | 1.96% |
| VALIDATION 상대 개선율 | 80.74% |
| TEST XGBRegressor clipped MAE | 0.80실 |
| TEST XGBRegressor clipped WAPE | 1.74% |
| TEST XGBRegressor clipped R² | 0.9986 |
| TEST 95% 예측구간 포함률 | 98.67% |
| 숨은 QA 28행 사후검증 WAPE | 1.38% |
| 현재 FORECAST | 28행 |
| 저장 모델 재로딩 | PASS |
| 리스크 검증 | PASS_WITH_LIMITATIONS |

가장 높은 TEST 세부 WAPE는 `RESIDENCE + horizon 3`의 3.19%로 확인되어 특정 그룹의 뚜렷한 성능 붕괴는 없었습니다. 다만 결과는 seed `20260803`, schema `room-demand-synth-schema-v1.0`인 단일 호텔 합성 데이터 성능이며 실제 호텔 일반화 성능을 뜻하지 않습니다.

산출물 재검증:

```powershell
python verify_artifacts.py
```
