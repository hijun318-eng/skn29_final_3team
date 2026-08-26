# Report Assistant 실제 화면 전환 독립 검증 프롬프트

당신은 Answervice 저장소의 독립 검증 담당자다. 코드를 수정하지 말고 현재 dirty worktree를
그대로 보존하면서 Report Assistant의 하드코딩 showcase 제거 여부를 증거로 판정하라.

## 환경

- 저장소: `report-assistant-advanced`
- 브랜치: `codex/report-assistant-advanced-20260824`
- 기준 브랜치: `origin/dev`
- 기존 dirty 변경은 사용자 작업이므로 되돌리거나 정리하지 않는다.
- 저장소 루트 `AGENTS.md`를 전체 읽고 준수한다.
- secret 값은 출력하지 않는다.
- mock·fixture·화면 모양을 live/E2E 성공 근거로 사용하지 않는다.

## 검증 목표

1. production source와 Docker build에서 다음 항목이 완전히 제거됐는지 확인한다.
   - `VITE_REPORT_ASSISTANT_SHOWCASE`
   - `REPORT_ASSISTANT_SHOWCASE`
   - `ReportAssistantShowcase`
   - `showcase-period-comparison`
   - `LOCAL VERIFICATION`
2. `App.jsx`가 시작 시 실제 `/auth/session` 검증을 수행하고, 인증 전에는 실제
   `SessionLogin`, 인증 후에는 권한에 따라 `ReportsPage`를 렌더링하는지 확인한다.
3. 실제 Report Assistant client가 다음 API를 사용하는지 확인한다.
   - `POST /reports/assistant/sessions`
   - `POST /reports/assistant/sessions/{id}/messages`
   - `POST /reports/assistant/sessions/{id}/approval`
4. Backend가 모델 제안, AnalysisController, Artifact lineage/checksum 검증, Report revision
   CAS 저장 경계를 보유하는지 확인한다.
5. Docker 배포 후 `/agent`가 showcase가 아니라 실제 인증 경계를 표시하는지 확인한다.
6. Backend `/health`와 `/readiness`를 분리 판정하고, readiness 503을 성공으로 표현하지 않는다.
7. App DB의 report definition, approved Artifact, Assistant session/turn 건수를 조회해 실제
   E2E가 수행됐는지 확인한다.

## 필수 명령

```powershell
git status --short --branch
rg -n "VITE_REPORT_ASSISTANT_SHOWCASE|REPORT_ASSISTANT_SHOWCASE|ReportAssistantShowcase|showcase-period-comparison|LOCAL VERIFICATION" app compose.report-assistant-stage5.yml
Set-Location app/frontend
npm.cmd test
npm.cmd run build
```

Docker가 실행 중이면 container health, `/health`, `/readiness`, Frontend HTTP 상태와 access
log를 읽기 전용으로 확인한다. 사용자가 명시하지 않은 migration, 데이터 적재, token 발급,
외부 모델 호출은 수행하지 않는다.

## 판정 형식

- `PASS`: showcase 참조 0건, Frontend test/build 통과, 배포 화면이 실제 인증 경계를 사용
- `PARTIAL`: 코드 제거는 됐지만 인증 또는 외부 dependency가 없어 실제 ReportsPage/E2E 미검증
- `FAIL`: showcase 우회가 남아 있거나 고정 Artifact/분석 계획이 production 경로에서 실행됨

마지막에 다음을 구분해 보고한다.

1. 하드코딩 제거 판정
2. 실제 Frontend 연결 판정
3. 실제 Backend 기능 존재 여부
4. live E2E 수행 여부
5. 정확한 blocker와 다음 최소 작업
