# REPORT-v1.1.0-DRAFT 계약

이 모듈은 framework-neutral Report domain·route 계약과 독립 검증용 메모리 저장소를 제공한다.
운영 runtime은 `app/backend`의 FastAPI router, PostgreSQL 저장소와 단일 Alembic chain에 등록되어 있다.
`REPORT-v1.0.0` 요청·응답 호환성을 유지하면서 v1.1 layout, history, manual command, schedule 계약을 추가한다.

현재 backend 등록 범위:

1. `create_report_router(...)` 계약을 공통 인증·인가 뒤 FastAPI `APIRouter`로 제공한다.
2. application PostgreSQL 저장소로 definition, run, schedule과 command를 영속화한다.
3. 승인된 definition version은 불변으로 유지하고 각 run에 정책·Context·watermark·Artifact 근거를 보존한다.
4. `POST /reports/runs/manual`은 최소 식별자만 받고 command ID와 상태는 서버가 관리한다.
5. `report-worker`가 예약 command를 소비해 분석과 Artifact 생성을 실행한다.
