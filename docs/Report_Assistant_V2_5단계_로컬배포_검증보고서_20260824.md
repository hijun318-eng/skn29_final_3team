# Report Assistant V2 5단계 로컬 배포 검증 보고서

> **SUPERSEDED — 실행 근거로 사용 금지 (2026-08-25)**
> 이 문서가 검증한 `LOCAL VERIFICATION` showcase는 제거되었다. 현재 Frontend는 실제
> session 검증과 `ReportsPage` 경로만 사용하며, 인증·Trino·DataHub·model readiness가
> 준비되기 전에는 실제 Report Assistant E2E 완료로 판정하지 않는다.

기준일: 2026-08-24
브랜치: `codex/report-assistant-advanced-20260824`
판정: **부분 완료 — 애플리케이션 배포 성공, 실제 데이터 E2E는 외부 설정 미비로 차단**

## 이번에 실제로 완료한 범위

- 기존 `hotel-synthetic-db_app-postgres-data` volume을 삭제하거나 초기화하지 않고 재사용했다.
- 저장소의 `provision-app-postgres.sh`를 실행해 bootstrap admin 소유 application object를
  전용 migration role로 이관했다.
- 전용 migration role로 전체 Alembic chain을 적용했고 현재 head
  `20260824_33`을 DB에서 확인했다.
- 최신 source로 backend와 frontend Docker image를 다시 만들었다.
- backend를 `0.0.0.0:18001`, frontend를 `0.0.0.0:13001`에 배포했다.
- 로그인 없는 로컬 검증 화면에서 A4 보고서, Report Assistant 패널, 새 데이터 승인 카드를
  브라우저로 확인했다.
- 검증 화면이 `/api/readiness`를 호출해 실제 backend 상태와 준비되지 않은 의존성을 표시한다.
- production code에 질문별 mock 응답, 고정 SQL, seed 또는 fallback Artifact를 추가하지 않았다.

## 확인 URL

- 보고서 화면: `http://192.168.0.37:13001/agent`
- Backend health: `http://192.168.0.37:18001/health`
- Backend readiness: `http://192.168.0.37:18001/readiness`

`/agent`는 로그인과 데이터 적재가 없어도 승인 UX를 확인하기 위한 **LOCAL VERIFICATION UI**다.
실제 수치 대신 `데이터 미적재`를 표시하며, 승인 버튼을 눌러도 이 화면 자체가 운영 데이터
분석 성공을 가장하지 않는다. 실제 ReportsPage의 서버 세션·승인·CAS 연결 코드는 별도로
구현돼 있지만, live 실행은 아래 의존성이 준비돼야 한다.

## 실제 확인 결과

| 항목 | 결과 |
|---|---|
| App PostgreSQL container | healthy |
| DB provision job | exit 0 |
| Alembic migration job | exit 0 |
| Migration head | `20260824_33` |
| Backend container | healthy, `/health` HTTP 200 |
| Frontend container | healthy, LAN `/agent` HTTP 200 |
| 브라우저 렌더링 | desktop 보고서·Assistant·승인 카드 확인 |
| 브라우저 console | warning/error 없음 |
| Backend readiness | HTTP 503, fail closed |

준비된 항목은 `app_postgres`, `migration`, `analysis_template_registry`다.
`report_scheduler`는 이번 로컬 검증에서 의도적으로 `not_required`다.

준비되지 않은 항목은 다음과 같다.

- `trino`
- `datahub_transport`
- `semantic_release`
- `catalog_manifest`
- `trino_schema`
- `model`
- `auth_session_store`

확인 당시 기존 DataHub GMS container 자체는 healthy였지만 backend용 URL/token이 주입되지
않았다. 기존 Trino container는 TLS keystore password와 internal shared secret 미설정으로
restart 중이었다. OpenAI-compatible model endpoint/key/model과 auth session 설정도 외부 env에
없었다. 자격증명을 임의 생성하거나 mock 성공으로 대체하지 않았다.

## 5단계 완료 판정에 아직 필요한 것

1. 승인된 DataHub read token과 backend transport URL을 외부 secret으로 주입한다.
2. Trino TLS/shared secret과 backend query credential을 복구해 container readiness를 통과시킨다.
3. 승인된 semantic release와 catalog manifest를 연결한다.
4. 실제 model endpoint/key/model 및 auth principal/session 설정을 주입한다.
5. 실제 사용자로 한 요청을 실행해 같은 request ID가 모델 계획, SQL Guard, Trino query,
   approved Artifact, 보고서 revision까지 이어지는지 검증한다.
6. owner/권한 거절, 중복 승인, lineage/checksum 불일치, process crash 후 복구를 live 환경에서
   증빙한다.

위 항목이 완료되기 전에는 “Report Assistant 실제 데이터 5단계 E2E 완료”라고 판정하지 않는다.

## 코드·브라우저 검증

- Report Assistant AI/Backend 핵심 unittest: 57개 통과
- runtime lifecycle unittest: backend Docker image에서 2개 통과
- Frontend test: 24개 통과
- Frontend production build: 통과
- 코드 문서화 검사: 340 source files, 62 executable configs 통과
- repository integrity audit: 857 files 통과
- `git diff --check`: 통과
- LAN 브라우저: 보고서, 실제 `not_ready` 표시, 승인 카드, console warning/error 0건 확인

로컬 Python에는 `sqlglot`이 없어 runtime lifecycle module을 직접 import할 수 없었다. 패키지를
임의 설치하지 않고 동일 backend Docker image에서 해당 테스트를 실행했다. DataHub, Trino,
운영 모델 endpoint를 호출하는 live/E2E 검증은 실행하지 않았다.

## 실행과 종료

외부 env를 사용한 실행 명령은 다음과 같다.

```powershell
docker compose `
  --env-file C:\Users\Playdata\Downloads\skn29_final_3team\infrastructure\database\.env `
  -f compose.report-assistant-stage5.yml up -d --build
```

이 로컬 검증 stack만 내릴 때는 volume 삭제 옵션을 사용하지 않는다.

```powershell
docker compose `
  --env-file C:\Users\Playdata\Downloads\skn29_final_3team\infrastructure\database\.env `
  -f compose.report-assistant-stage5.yml down
```

`down -v`는 기존 App DB volume을 손상시킬 수 있으므로 사용하지 않는다.
