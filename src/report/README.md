# 보고서 도메인 계약

`src/report`는 프레임워크에 종속되지 않은 보고서 도메인 모델과 포트, 라우터 계약을 제공한다. 실제 FastAPI 등록, 인증·인가, PostgreSQL 영속화, 수동 실행, 스케줄 실행은 `app/backend`의 adapter와 service가 담당하며 공통 Alembic 체인을 사용한다.

## 무결성 경계

- 보고서 저장소는 애플리케이션 조립 단계에서 명시적으로 주입한다. 운영 코드에는 메모리 저장소나 성공 응답 fallback이 없다.
- 승인된 정의 버전은 불변으로 취급하고, 실행마다 `definition_version`, `as_of`, 정책·컨텍스트·watermark·artifact·query·snapshot checksum을 보존한다.
- 외부 클라이언트의 수동 실행 요청은 `definition_id`, `version`, `as_of`, `idempotency_key`만 받는다. command ID, 상태, 결과와 실행 증거는 서버가 소유한다.
- 전체 실행 결과 적재 계약은 신뢰된 내부 worker 경계이며 외부 API로 노출하지 않는다.

공개 API를 바꾸면 `tests/report`의 도메인·라우터 계약과 `tests/backend`의 영속화·실행·스케줄 테스트를 함께 갱신한다.
