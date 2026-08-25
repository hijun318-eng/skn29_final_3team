# 예약 No-show 이진 분류 ML

기획서가 권고한 유일한 P2 `ML-as-a-Tool` 후보 프로젝트다. 예약 1건을 한 행으로 사용하고 체크인 전날 18시 기준 No-show 확률을 예측한다. I5 완료와 R1의 별도 Gate 승인 전에는 비활성이다.

## 현재 상태

- 기존 ONNX는 `SYNTHETIC_RULE_V1` 파생 라벨로 만든 과거 기술 fixture이며 운영 성능 근거가 아니다.
- 재학습에는 원천 `NO_SHOW`, 기준시점 이후의 `outcome_recorded_at`, `source_snapshot_id`, 추출 시각이 모두 필요하다. 하나라도 없으면 학습을 중단한다.
- 기존 stdio 결과는 과거 기술검증 기록으로만 보존한다. 현재 readiness에 FAIL이 있으므로 `local_demo` 우회 활성화도 차단한다.
- 객실수요 회귀 모델은 참고 산출물로 분리하고 이 분류 모델과 섞지 않는다.
- `data/raw`가 없는 Git checkout에서는 `fixtures/reservation_no_show_inference.csv` 1행으로 저장 ONNX의 Tool 호출을 검증한다.

## 실행

```powershell
cd src/ml/reservation_no_show
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_tool_fixture.py
.\.venv\Scripts\python.exe run_main_chat_fixture.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe verify_artifacts.py
```

포함된 ONNX 모델과 로컬 `data/raw/reservation_no_show` fixture로 위 추론 검증을 실행할 수 있다. 재학습은 PMS export를 별도로 준비한 뒤 다음처럼 경로를 지정한다.

```powershell
$env:ANSWERVICE_ML_SOURCE_DIR='D:\path\to\synthetic_db_export\full'
$env:ANSWERVICE_ML_SOURCE_SNAPSHOT_ID='pms-snapshot-v1'
$env:ANSWERVICE_ML_SOURCE_EXTRACTED_AT='2026-08-10T00:00:00Z'
.\.venv\Scripts\python.exe train.py
```

재학습 출력 데이터는 저장소의 `data/raw/reservation_no_show`에 생성되며 Git에는 포함하지 않는다.

결과 요약은 `reports/260804_Answervice_예약_No-show_이진분류_ML_결과보고서_v1.3.md`에서 확인한다.
