# 로컬 E2E 실행 및 검증 가이드

| 항목 | 내용 |
|---|---|
| 문서 설명 | 다른 개발자 환경에서 Answervice 전체 서비스를 실행하고 E2E 연결을 확인하는 최소 절차 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-08-12 00:43 |
| 작성·수정 | 박준희 |
| 권장 저장 위치 | `docs/markdown/로컬_E2E_실행_검증_가이드.md` |

## 1. 준비

- Windows PowerShell, Git, Docker Desktop과 Docker Compose v2를 준비한다.
- 저장소 루트에서 실행한다.
- 실제 고객 데이터 대신 저장소의 합성 데이터만 사용한다.
- OpenAI API key와 로컬 DB·DataHub용 비밀번호를 준비한다.

```powershell
git clone https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team
git switch codex/ai-constraint-unlock-e2e
Copy-Item .env.example .env
```

`.env`에서 모든 `REQUIRED`를 환경별 값으로 바꾼다. 실제 key와 password는 commit하지 않는다.

```powershell
Select-String -Path .env -Pattern '=REQUIRED$'
```

출력이 없어야 한다. 로컬 화면 검증은 `AUTH_MODE=test`를 사용하며 운영 환경에서는 `AUTH_MODE=release`와 별도 principals 파일을 사용한다.

## 2. 전체 서비스 실행

DataHub, Trino, 5개 원천 DB, App PostgreSQL, Backend, Frontend를 한 번에 기동한다.

```powershell
docker compose --env-file .env --profile full config --quiet
docker compose --env-file .env --profile full up -d --build --wait --wait-timeout 1800
```

DataHub에 승인된 serving View 8개의 semantic metadata를 게시하고 검증한다.

```powershell
python infrastructure/database/datahub/publish_semantic_catalog.py --server http://127.0.0.1:18081
python infrastructure/database/datahub/verify_semantic_catalog.py --server http://127.0.0.1:18081
```

접속 주소는 다음과 같다.

| 서비스 | 주소 |
|---|---|
| 분석 화면 | `http://127.0.0.1:13000/agent` |
| Backend API | `http://127.0.0.1:18000` |
| Trino | `http://127.0.0.1:18080` |
| DataHub | `http://127.0.0.1:19002` |
| DataHub GMS | `http://127.0.0.1:18081` |

## 3. 연결 검증

모든 dependency가 `ready`인지 확인한다.

```powershell
$readiness = Invoke-RestMethod http://127.0.0.1:18000/readiness
$readiness.data | ConvertTo-Json -Depth 5
```

`app_postgres`, `migration`, `approved_templates`, `trino`, `datahub`, `model`이 모두 `ready`여야 한다.

변경 범위 자동 테스트를 실행한다.

```powershell
python -m pytest tests/backend/test_analysis_pipeline.py tests/backend/test_i2_data_platform.py tests/backend/test_production_model.py tests/backend/test_readiness.py tests/backend/test_router_configuration.py -q
node --test tests/frontend/contracts.test.mjs
```

브라우저에서 아래 두 질문을 각각 실행한다.

```text
이번 달 객실 매출을 일별로 분석해줘
2026년 6월 객실 매출을 일별로 분석해줘
```

성공 기준은 `success` 상태, 오류 없음, 첫 질문은 2026-07-01~07-28의 28행, 두 번째 질문은 2026-06-01~06-30의 30행이 표와 차트에 표시되는 것이다.

## 4. 모델 교체

기본적으로 모든 Node는 OpenAI를 사용한다.

```dotenv
MODEL_MODE=openai
OPENAI_MODEL=gpt-4.1-mini
NODE2_MODEL_ENDPOINT=
NODE2_MODEL_API_TOKEN=
NODE2_MODEL=Qwen/Qwen3-4B
```

Node2만 OpenAI-compatible sLLM으로 교체할 때 `NODE2_MODEL_ENDPOINT`, `NODE2_MODEL_API_TOKEN`, `NODE2_MODEL`을 설정하고 Backend를 다시 만든다.

```powershell
docker compose --env-file .env --profile full up -d --build backend
```

설정을 비우면 Node2도 OpenAI를 사용한다.

## 5. 현재 허용 범위와 종료

- 조회는 읽기 전용이며 G1·G2·G3와 승인된 metric·join 계약을 통과해야 한다.
- Trino 연결이 되어 있어도 임의 DB·임의 join은 실행하지 않는다.
- 실제 E2E가 확인된 대표 시나리오는 객실 매출의 동적 기간 조회다.
- 여러 DB 시나리오는 승인된 PMS+CRM 및 PMS+CRM+POS 계약 범위에서 별도 검증한다.

```powershell
docker compose --env-file .env --profile full down
```

데이터까지 초기화할 때만 명시적으로 `--volumes`를 추가한다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-08-12 00:43 | OpenAI·DataHub·Trino 기반 로컬 실행과 동적 날짜 E2E 검증 절차 작성 |
