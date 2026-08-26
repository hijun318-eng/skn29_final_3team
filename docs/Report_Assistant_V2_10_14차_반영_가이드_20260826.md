# Report Assistant V2 10~14차 통합 반영 가이드

기준일: 2026-08-26  
공유 브랜치: `origin/seung`  
변경 전 기준: `a116a4d4`  
10~12차 누적 기준 커밋: `a116a4d4`  
13·14차 구현 커밋: `d055cf20`  

## 1. 문서 목적

이 문서는 다른 개발자가 오늘 작업한 Report Assistant 10~14차 변경을 통합 브랜치에 반영할 때 관리자
화면, Report Builder UI 또는 기존 Agent 흐름을 덮어쓰지 않도록 변경 범위와 충돌 처리 방법을
정리한다.

이번 작업은 Analysis Agent, `AnalysisController`, Trino, DataHub, 관리자 운영 UI를 변경하지
않는다. DB schema와 API 계약도 바꾸지 않았으므로 migration 적용은 필요하지 않다.

## 2. 오늘 반영된 기능

### 10차: 부분 승인 operation 의존성 검증

- 사용자가 일부 operation만 승인해도 최종 조합을 서버에서 다시 dry-run
- 삭제할 block을 동시에 수정·이동·복제하거나 배치 anchor로 사용하는 모순 차단
- 같은 제목·text·block을 한 patch에서 중복 변경하는 모호한 조합 차단
- 잘못된 조합은 Revision 저장 전에 `REPORT_ASSISTANT_PATCH_INVALID`로 종료
- 전체 승인과 동일 선택 중복 승인의 기존 멱등 동작 유지

### 11차: 실패 복구 보강과 안전한 요청 취소

- `new_data` 분석 성공 뒤 최종 typed patch와 model trace를 DB에 먼저 고정
- `saving_revision` 복구 시 GPT와 `AnalysisController`를 다시 호출하지 않고 고정 patch만 사용
- Report 공개 응답에서 실제 query ID와 Artifact checksum 제거
- 비저장 품질 검토의 latency·attempt·token·비용을 기존 평가 레코드에 연결
- `ready`, `waiting_patch_approval`, `waiting_approval` 전용 취소 API와 Client 동작 추가
- 실행·Artifact 대기·Revision 저장 중에는 취소 완료로 가장하지 않고 상태 확인 안내

### 12차: 실제 GPT·PostgreSQL·Browser 편집 E2E

- 격리 PostgreSQL에 migration 단일 head `20260826_40` 적용
- 실제 OpenAI strict proposal에서 두 개 operation 생성 확인
- 승인 전에 Report version과 block이 바뀌지 않는 것 확인
- 일부 operation만 승인해 새 Revision 한 건 생성
- Backend 재시작 뒤 `saving_revision`을 GPT·AnalysisController 재호출 없이 복구
- 중복 승인 시 Revision 추가 생성 없음 확인
- Canvas와 새로고침 뒤 동일 Revision·block 복구
- Browser DOM에서 query ID·checksum·SQL 미노출과 console error 없음 확인

12차 결과는 기존 승인 Artifact 편집 E2E다. Trino·DataHub·Analysis Agent를 사용하는
`new_data` live E2E는 포함하지 않는다.

### 13차: 승인 카드 접근성·모바일 대응

- operation checkbox와 제목을 React `useId()` 기반 `id`/`htmlFor`로 연결
- 전체 선택, 전체 해제와 `선택 수 / 전체 수` 안내 추가
- 긴 변경 전·후 본문을 네이티브 `details`로 접고 필요할 때 전체 내용 표시
- 변경 전·후를 색상뿐 아니라 텍스트 label로 구분
- 승인 오류 발생 시 변경안 카드로 키보드 focus 복귀
- 버튼, checkbox, 접기 summary에 `focus-visible` 표시
- `prefers-reduced-motion` 환경에서 대기 spinner 애니메이션 중지
- 360px 폭과 화면 확대 환경에서 승인 버튼과 긴 본문의 가로 overflow 방지

승인 API와 operation index 계약은 기존과 같다. UI 선택값은 기존
`onApprove(selectedIndexes)` 경계로만 전달되고 Client가 새 승인 규칙을 만들지 않는다.

### 14차: GPT 품질 평가 기반

- 다음 10개 Report Assistant 시나리오를 명시적인 평가셋으로 구성
  - 제목만 변경
  - 근거를 유지한 요약 축약
  - 최소 operation 선택
  - 현재 근거로 답할 수 없는 요청
  - 존재하지 않는 block 요청
  - 모호한 기간·대상
  - 여러 Artifact 종합
  - 재수정 후 이전 operation 제거
  - 품질 finding을 patch로 전환
  - Artifact ID·SQL·승인 우회 prompt injection
- deterministic fake와 캡처된 live 결과를 `mode`로 명시적으로 구분
- strict 계약, route, operation, server dry-run, 불필요 operation, evidence ref, 재수정 반영률 계산
- 모델 attempts, latency, input/output token, 추정 비용 계산
- prompt/model version을 평가 결과와 연결
- provider usage 또는 가격이 없으면 token·비용을 `0`이 아닌 `null`로 유지
- 결과에는 사용자 지시, raw prompt, raw model response, SQL을 포함하지 않음

실제 GPT 기준/후보 비교는 비용 승인 전이라 실행하지 않았다. 따라서 현재 prompt
`PROMPT-v1.8.1`과 model release `MODEL-RELEASE-v1.33.0`은 그대로다.

## 3. 10~14차 변경 경계

10~12차까지의 누적 구현은 `a116a4d4`에 포함돼 있으며, 13·14차 증분은 `d055cf20`이다. 다른
개발자의 브랜치가 이미 `a116a4d4`를 포함하면 `d055cf20`만 추가 반영한다. 포함하지 않았다면
개별 파일을 임의 복사하기보다 `origin/seung`의 누적 commit history를 기준으로 통합한다.

### 13·14차 증분 파일과 책임

| 파일 | 변경 책임 | 충돌 가능성 |
|---|---|---|
| `app/frontend/src/features/reports/components/ReportAssistantPanel.jsx` | 승인 카드 선택·긴 본문·focus 접근성 | 높음 |
| `app/frontend/src/features/reports/v2/report-builder-v2.css` | 승인 카드 반응형·focus·모션 감소 | 높음 |
| `tests/frontend/report-builder-v2.test.mjs` | 13차 UI 정적 계약 | 중간 |
| `evals/report_assistant_quality_cases.json` | GPT 평가 시나리오 10건 | 낮음 |
| `evals/report_assistant_quality.py` | 안전한 품질 지표 계산과 CLI | 낮음 |
| `tests/backend/test_report_assistant_operations.py` | 평가셋·채점·null 비용 회귀 | 중간 |
| `tests/ai/test_model_contracts_live.py` | 활성 release 기대값 `v1.33.0` 정합화 | 낮음 |
| `docs/Report_Assistant_V2_구현_진행_20260824.md` | 13·14차 범위와 검증 기록 | 중간 |

수정하지 않은 주요 충돌 경계:

- `ReportAssistantOperationsPanel.jsx`
- 관리자 summary·failures UI와 권한 정책
- `ReportsPage.jsx`
- `useReportsPageController.jsx`
- `useReportLifecycleState.ts`
- `reportClient.ts`
- Backend router·repository·contract
- migration 전체
- `src/ai/prompt_registry.py`
- `src/ai/contracts/model_release.v1.json`
- Analysis Agent, Trino, DataHub 코드와 설정

## 4. 권장 반영 순서

### 같은 `seung` 브랜치를 기준으로 작업하는 경우

1. 본인 dirty 변경을 먼저 별도 commit으로 보존한다.
2. `origin/seung` 최신 상태를 fetch한다.
3. 본인 브랜치에 merge하거나 rebase하기 전에 위 변경 파일과 겹치는지 확인한다.
4. 충돌이 없으면 최신 `origin/seung`을 통합한다.
5. 충돌이 있으면 아래 파일별 원칙에 따라 수동 병합한다.
6. 필수 테스트를 실행한 뒤에만 통합 완료로 판단한다.

### 통합 브랜치에 구현만 선택 반영하는 경우

```powershell
git fetch origin
git cherry-pick d055cf20
```

이 명령은 통합 브랜치가 `a116a4d4`를 이미 포함한 경우에만 사용한다. 10~12차가 없다면
`d055cf20` 하나만 가져와서는 전체 기능이 연결되지 않으므로 최신 `origin/seung` 누적 history를
병합한다. 이미 같은 변경이 포함된 브랜치에 커밋을 다시 cherry-pick하지 않는다.

## 5. 파일별 충돌 해결 원칙

### `ReportAssistantPanel.jsx`

파일 전체를 ours/theirs로 선택하지 않는다. 다음 hunk만 유지한다.

- React import의 `useId`, `useRef`
- `PATCH_VALUE_PREVIEW_LENGTH`
- `PatchValue`
- `AssistantPatchApproval`의 `approvalRef`, `operationIdPrefix`
- 오류 발생 시 `approvalRef.current?.focus()`
- 전체 선택·전체 해제·선택 개수 UI
- checkbox `id`와 label `htmlFor`
- 부모에서 `errorCode={workflowError}` 전달

다른 개발자가 Assistant composer, 관리자 패널, Artifact 선택 또는 ReportsPage 연결을 변경했다면
그 변경을 유지하고 위 hunk만 합친다. 기존 `selectedIndexes`와
`onApprove(selectedIndexes)` 흐름을 두 번째 상태 관리로 복제하지 않는다.

### `report-builder-v2.css`

기존 Report Builder 레이아웃과 팀원의 breakpoint를 유지하고 다음 selector를 병합한다.

- `.report-assistant-patch-selection`
- `.report-assistant-patch-item`
- `.report-assistant-patch-detail`
- `.report-assistant-approval:focus-visible` 계열
- `@media(prefers-reduced-motion:reduce)`
- 480px 이하의 Assistant 전용 overflow 규칙

팀원이 480px breakpoint를 이미 갖고 있다면 새 media block을 중복 생성하지 말고 기존 block 안에
Assistant selector만 합친다. `.builder-inspector` 폭은 기존 팀 UI가 더 엄격한 값을 사용하면
`100vw`를 넘지 않는 조건만 보존한다.

### 평가 파일

`evals/report_assistant_quality.py`는 production model adapter가 아니다. 모델 호출이나 질문별 운영
분기를 추가하지 않는다. 실제 모델 결과는 외부에서 캡처한 안전한 필드만 `--outputs`로 전달한다.

```powershell
python evals/report_assistant_quality.py `
  --outputs <안전한-평가결과.json> `
  --mode deterministic_fake
```

실제 모델 캡처 결과만 `--mode captured_live`로 표시한다. mode 이름만 바꿔 fake를 live로 보고하면
안 된다.

### `test_model_contracts_live.py`

이 변경은 production release를 올린 것이 아니다. production manifest와 loader가 이미 강제하는
`MODEL-RELEASE-v1.33.0`에 테스트 기대값을 맞춘 한 줄 수정이다. 통합 브랜치가 더 최신 release를
사용한다면 해당 브랜치의 manifest·loader·prompt hash를 권위로 삼고 세 값이 모두 일치해야 한다.

## 6. 충돌 후 금지 사항

- `ReportAssistantPanel.jsx` 전체를 한쪽 버전으로 덮어쓰기
- 관리자 화면 파일을 이번 작업 때문에 수정하기
- 실제 GPT 비교 없이 prompt/model release 올리기
- 평가 JSON을 production 질문 router 또는 고정 응답으로 사용하기
- fake 결과를 live GPT 평가로 표시하기
- token·비용 미측정값을 0으로 변환하기
- SQL, Artifact ID, query ID, checksum, raw model response를 평가 결과나 Browser에 추가하기
- 기존 migration 수정 또는 신규 migration 생성
- Analysis Agent·Trino·DataHub 연결을 이번 커밋의 완료 조건에 포함하기

## 7. 검증 결과와 재검증 명령

현재 커밋 기준 확인 결과:

- Report Assistant 관련 Backend·AI unittest 124개 통과
- model release·평가기 targeted test 23개 통과
- Frontend test 24개 통과
- Frontend production build 통과
- OpenAPI contract 통과
- 코드 문서화·아키텍처·repository integrity 통과
- Python compileall 통과
- `git diff --check` 통과
- 360px Browser viewport에서 document 가로 overflow 없음
- Browser console error 없음

통합 후 최소 재검증:

```powershell
$env:PYTHONPATH='.;app/backend'
python -m unittest `
  tests.ai.test_model_contracts_live `
  tests.ai.test_report_assistant_contract `
  tests.backend.test_report_assistant_session `
  tests.backend.test_report_assistant_patch `
  tests.backend.test_report_assistant_operations `
  tests.backend.test_report_migration

python app/backend/scripts/export_openapi.py --check
python scripts/check_code_documentation.py
python scripts/lint_architectural_invariants.py
python scripts/audit_repository_integrity.py
python -m compileall -q app/backend src evals tests
git diff --check

Set-Location app/frontend
npm.cmd run test
npm.cmd run build
```

## 8. 남은 작업

Report Assistant의 GPT 단독 고도화에서 남은 Gate는 14차 실제 모델 비교다.

```text
현재 PROMPT-v1.8.1 baseline 실행
→ 동일 10개 평가셋으로 후보 prompt 실행
→ 계약·route·operation·근거·비용 비교
→ 개선 기준 충족 시에만 prompt/model release 갱신
```

이 작업은 OpenAI 비용이 발생하므로 별도 승인 전에는 실행하지 않는다. Trino·DataHub와 Analysis
Agent를 사용하는 `new_data` live E2E는 이 문서 범위 밖의 별도 최종 통합 작업이다.
