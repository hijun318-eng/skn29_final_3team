# Report Domain

`src/report`는 Report domain, repository contract와 framework-neutral route contract를 제공한다. 현재 Report runtime은 이미 FastAPI Backend와 Application PostgreSQL에 등록되어 있다.

## 현재 연결

- FastAPI adapter: `app/backend/app/api/report_router.py`
- PostgreSQL adapter: `app/backend/app/adapters/report_repository.py`
- Scheduler: `app/backend/app/services/report_scheduler.py`
- Runtime 등록: `app/backend/app/main.py`
- Alembic 등록: `app/backend/migrations/versions/20260804_04_report_registration.py` 이후 Report migration

공개 API는 인증·권한을 통과한 뒤 Report domain을 호출한다. 실행 결과 전체를 클라이언트가 주입하지 않으며, 서버가 승인된 Analysis Artifact와 현재 policy·context·watermark를 다시 확인한다.

## 파일 역할

- `domain.py`: Report entity, 상태와 versioned contract
- `repository.py`: repository contract와 테스트용 in-memory 구현
- `router.py`: framework-neutral route contract
- `migration_proposal*.sql`: 초기 제안 계약의 회귀 검증 자료

실제 DB 배포 기준은 proposal SQL이 아니라 Backend의 단일 Alembic chain이다.

## 검증

```powershell
python -m pytest tests/report tests/backend/test_report_registration.py tests/backend/test_report_scheduler.py -q
```
