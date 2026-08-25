# Answervice ML 패키지

기획서의 최소 P2 방안을 적용한다. 공식 ML-as-a-Tool 후보는 예약 No-show 이진분류 1개뿐이며 I5 완료와 R1의 별도 Gate 승인 전에는 비활성이다. 객실수요 7일 예측은 삭제하지 않고 오프라인 회귀 기술검증 산출물로 보존한다.

| 패키지 | 역할 | 메인챗·MCP | 현재 상태 |
|---|---|---|---|
| `reservation_no_show` | 향후 P2 공식 후보 | 승인 전 미등록·호출 차단 | 원천 라벨 Gate `BLOCKED` |
| `room_demand_forecast` | 오프라인 참고 분석 | 등록하지 않음 | 결과 재현 가능 |

현재 프로젝트에는 MCP server를 도입하지 않는다. `config/mcp_servers.template.json`도 빈 registry를 유지하며, 과거 로컬 stdio 산출물은 기술검증 이력일 뿐 현재 활성화 근거가 아니다.

## 공통 로컬 검증

두 분석 패키지는 저장소 내부의 공통 가상환경을 사용한다. 아래 명령은 현재 checkout의 상대경로만 사용한다.

```powershell
cd <repository-root>
python -m venv src\ml\.venv
src\ml\.venv\Scripts\python.exe -m pip install -r src\ml\requirements.txt
src\ml\.venv\Scripts\python.exe src\ml\verify_local.py
```

검증기는 No-show의 fail-closed 상태와 단일 후보 routing 계약, 객실수요 오프라인 산출물, 빈 MCP registry를 확인한다. `PASS`는 모델 활성화가 아니라 분석 산출물과 차단 정책의 정합성을 뜻한다.

`data/raw`는 Git에 포함하지 않는다. 새 checkout에서도 저장 모델의 Tool 호출을 확인할 수 있도록 각 패키지의 `fixtures/`에 최소 합성 inference 입력만 포함하며, raw 입력이 없을 때 자동으로 사용한다. 전체 재학습에는 별도의 합성 원천 또는 학습 CSV가 필요하다.

최종 검증 증거는 `artifacts/final_local_verification.json`에 저장한다.

전체 결과와 Git 공유 범위는 `reports/260804_Answervice_ML_MCP_로컬_최종검증보고서_v1.0.md`에서 확인한다.

## 공통 운영 Gate

| 항목 | 현재 상태 | 다음 완료 기준 |
|---|---|---|
| No-show 원천 라벨·시점 | BLOCKED | `NO_SHOW`와 기준시점 이후 `outcome_recorded_at`이 있는 승인 snapshot으로 재학습 |
| No-show 원천 계보 | BLOCKED | snapshot ID·추출 시각·원천 파일 SHA-256 기록 |
| No-show Trino Feature 조회 | 로컬 PASS 기록 | P2 승인 후 production 서비스 adapter에서 동일 SQL 호출 |
| 운영 UI 예측 구분 | 미검증 | 모델 예측·합성 여부·기준 시점 표시 |
| 운영 감사 로그 | 미검증 | 실행 ID·모델·Feature 버전·기준 시점 영구 저장 |
| 운영 MCP end-to-end | 범위 밖 | I5 이후 R1 P2 Gate 승인 시 인증·RDB·UI 포함 검증 |
| 운영 hard timeout | 미검증 | 실제 배포 경계에서 2초 중단 확인 |
| Top15 업무량 정책 | 로컬 적용·승인 대기 | 상위 비율과 일일 최대 연락 건수 승인 |

No-show 후보는 모든 Gate가 PASS가 될 때까지 비활성이다. 객실수요 모델은 비활성 Tool이 아니라 애초에 registry 대상이 아닌 참고 모델이다.
