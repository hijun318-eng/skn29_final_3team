# Report Assistant V2 시나리오 검증보고서

기준일: 2026-08-26
대상 브랜치: `codex/report-assistant-advanced-20260824`
검증 범위: Report Assistant V2만 포함하며 Analysis Agent·Trino·DataHub live 실행은 제외한다.

## 1. 판정

기능 설명서에 적은 Report Assistant 시나리오는 계약·서버·Frontend 자동 테스트로 모두 대응시켰다.
실제 OpenAI와 PostgreSQL을 사용하는 대표 Browser 흐름도 실행해 GPT 변경안, 승인 전 무저장,
승인 후 Revision 생성, Canvas 복구와 비저장 품질 검토를 확인했다.

다만 모든 자연어 문장을 실제 OpenAI로 반복 호출한 것은 아니다. 26개 자연어 품질 사례는
deterministic 평가 계약으로 검증했고 실제 유료 모델 호출은 대표 2건만 실행했다. `new_data`의
AnalysisController 이후 단계는 Trino·DataHub가 준비되지 않았으므로 live 성공으로 판정하지 않는다.

## 2. 시나리오별 검증 결과

| 구분 | 검증 시나리오 | 검증 방식 | 결과 |
|---|---|---|---|
| 세션 | 생성, owner 격리, 복구, bounded turn | Backend unit | PASS |
| 모델 계약 | strict schema, extra/missing field, 내부 ID·좌표 차단 | AI contract | PASS |
| 경로 판단 | `clarification`, `existing_artifact`, `new_data` | AI·Backend contract | PASS |
| 제목·텍스트 | 제목 변경, 텍스트 추가·수정, 선택 블록 수정 | patch unit + 자연어 eval | PASS |
| Artifact 보기 | 표, 차트, 전체 묶음 추가 | patch unit + 자연어 eval | PASS |
| 구조 편집 | 이동, 반/전체 너비, 복제, 삭제 | patch unit + 자연어 eval | PASS |
| 복원 | 이전 Revision 복원 단독 실행 | patch/session unit + 자연어 eval | PASS |
| 복합 변경 | 제목과 요약 등 여러 operation 제안 | unit + 실제 GPT/Browser | PASS |
| 재수정 | 현재 patch 교체, stale patch ID 차단 | Backend/Frontend contract | PASS |
| 부분 승인 | 선택 operation만 CAS 저장, 다른 중복 선택 차단 | Backend/Frontend contract | PASS |
| 승인·거절 | 승인 전 무저장, 거절 무저장, 승인 후 Revision | Backend unit + Browser | PASS |
| 멱등성 | 중복 승인에서 추가 Revision·분석 호출 방지 | Backend unit | PASS |
| 다중 Artifact | 최대 5개, safe alias, owner·checksum 결속 | AI/Backend contract | PASS |
| 근거 참조 | text evidence alias 검증, 미등록 ref 차단 | AI/patch unit | PASS |
| 품질 검토 | 5개 finding type, 잘못된 block/ref 차단, 무저장 | AI/Backend + 실제 GPT/Browser | PASS |
| 후속 제안 | 최대 3개, 내부 alias 차단, composer 반영 | AI/Backend/Frontend | PASS |
| 실패·복구 | typed failed, 새 session retry, 원본 실패 보존 | Backend/Frontend contract | PASS |
| 취소 | 대기 상태 취소, 실행·저장 중 취소 차단 | Backend/Frontend contract | PASS |
| 권한·lineage | owner, capability, request/query/checksum 검증 | Backend unit | PASS |
| 제한 | rate, concurrency, token, cost 차단 | operations unit | PASS |
| 금지 요청 | 스타일, 외부 발송, 숫자 조작, SQL·ID 노출, 자동 승인 | 자연어 eval + strict contract | PASS |
| `new_data` | 완전한 계획, 승인 전 실행 0회, 거절, 권한·lineage | Backend fake controller | PASS (non-live) |
| Canvas | 완료 Revision 재조회, 새로고침 복구 | Frontend + 실제 Browser | PASS |

## 3. 자연어 평가 데이터셋

`evals/report_assistant_quality_cases.json`을 10개에서 26개로 확대했다. 추가 범위는 다음과 같다.

- 근거 기반 텍스트 추가
- 표·차트·Artifact 전체 묶음 추가
- 알려진 블록 이동·크기 변경·복제·삭제
- 이전 Revision 복원
- 복합 변경과 선택 블록 변경
- 기간 또는 metric이 빠진 새 데이터 요청
- 지원하지 않는 스타일 변경과 외부 자동 발송
- 근거 없는 숫자 생성 요청

평가 데이터와 fake output은 `evals/`와 `tests/`에만 존재하며 production 응답을 하드코딩하지 않는다.

## 4. 실제 GPT·PostgreSQL·Browser 검증

실행 환경:

- Frontend: `http://127.0.0.1:13002/reports`
- Backend: `http://127.0.0.1:18002`
- 사용자: 로그인된 analyst session
- 데이터: 격리 E2E용 승인 Artifact

실행 결과:

1. v13 보고서에서 제목 변경과 요약 축약을 한 문장으로 요청했다.
2. 실제 GPT가 `set_report_title`, `update_text` 두 작업을 strict 변경안으로 반환했다.
3. 승인 카드가 표시된 동안 Canvas와 Report version은 v13으로 유지됐다.
4. 두 작업을 승인한 뒤 새 v14 Revision 한 건이 생성됐다.
5. 새로고침 후 제목과 두 문장 요약이 v14 Canvas에서 복구됐다.
6. 실제 GPT 품질 검토를 실행했고 지원되는 문제가 없다는 typed 결과를 반환했다.
7. 품질 검토 전후 Report version은 v14로 동일하여 비저장 계약을 지켰다.

실제 유료 모델 호출은 변경안 1건과 품질 검토 1건이다. raw prompt 응답, SQL, credential,
query ID와 checksum은 이 문서에 기록하지 않았다.

## 5. 실행한 검증

Backend·AI:

```text
126 tests
126 passed
0 failed
```

Frontend:

```text
24 tests
24 passed
Vite production build passed
```

정적 검증:

- OpenAPI contract: PASS
- code documentation: PASS
- architectural invariants: PASS
- repository integrity: PASS
- Python compileall: PASS
- `git diff --check`: PASS

Frontend 테스트 중 이미 사용 중인 WebSocket port 24678 경고가 두 번 있었으나 테스트 실패는
없었다.

## 6. live로 검증하지 않은 범위

- 26개 자연어 평가 문장 전체의 실제 OpenAI 반복 호출
- Trino query 실행
- DataHub metadata readback
- `new_data` AnalysisController 이후 Artifact·Revision live 흐름
- 다른 실제 사용자의 cross-owner Browser 공격 시나리오

위 항목은 unit/fake 계약 검증과 live E2E를 구분한다. 특히 Trino·DataHub가 연결되기 전에는
`new_data` 전체 흐름을 live 성공이라고 표현하지 않는다.

## 7. 결론

현재 Report Assistant는 기존 승인 Artifact 편집에 대해 실제 GPT, 서버 session, 사용자 승인,
CAS Revision과 Browser Canvas가 연결된 상태다. 설명서의 기능 시나리오는 자동 테스트로 모두
대응됐고 대표 실제 편집·품질 검토도 통과했다. 남은 핵심 외부 의존성은 Analysis Agent가 아니라
Trino·DataHub를 포함하는 `new_data` live E2E다.

## 8. Chrome 다중 사용자 시나리오 추가 실행

같은 날 실제 Chrome, OpenAI, PostgreSQL을 사용해 다음 9개 시나리오를 추가 실행했다.

| 번호 | 시나리오 | 결과 | Revision |
|---:|---|---|---|
| 5 | 복합 변경안을 대화로 재수정 | PARTIAL | v18 → v19 |
| 6 | 제목·텍스트 중 텍스트만 부분 승인 | PASS | v19 → v20 |
| 7 | 모델 실패 후 새 세션 retry, 변경안 거절 | PASS | v20 유지 |
| 8 | 비저장 품질 검토 | PASS | v20 유지 |
| 9 | 지원하지 않는 글꼴·배경색 요청 | PASS | v20 유지 |
| 10 | SQL·내부 식별자 출력과 자동 승인 요청 | PASS | v20 유지 |
| 11 | 승인 카드 상태에서 새로고침 후 보고서 재열기 | PASS | v20 유지 |
| 12 | 복구된 변경안으로 선택 차트 블록 복제 | PASS | v20 → v21 |
| 13 | 바로 이전 Revision 복원 | PASS | v21 → v22 |

추가로 확인한 내용:

- 부분 승인에서는 제외한 제목이 유지되고 선택한 텍스트 블록만 저장됐다.
- 변경안 거절은 Revision을 생성하지 않았다.
- 품질 검토와 두 안전 차단 요청 모두 Revision을 생성하지 않았다.
- 내부정보 요청에 실제 SQL·Artifact ID·query ID·checksum을 반환하지 않았다.
- 새로고침 직후에는 목록으로 이동하지만 최신 보고서를 다시 열면 동일 승인 카드가 복구됐다.
- 복제 뒤 동일 차트 블록이 2개가 됐고 이전 Revision 복원 뒤 1개로 돌아왔다.
- 전체 실행 중 Chrome console warning·error는 0건이었다.

발견 결함:

1. 표 블록을 반 너비로 줄이라는 승인 작업이 새 v18을 만들었지만 저장 결과는
   `grid-column: 1 / span 12`로 유지됐다. 실제 레이아웃 변경 없는 Revision이다.
2. 변경안 재수정에서 GPT가 변경 전후가 같은 `update_text`를 반환했고 서버가 이를 받아 v19를
   생성했다. 의미 없는 no-op patch를 dry-run 단계에서 차단해야 한다.

삭제 시나리오는 Browser 안전 정책에 따라 실행 직전 별도 사용자 확인이 필요하므로 이 묶음에서
실행하지 않았다.

## 9. 결함 재확인과 추가 Chrome 시나리오

결함 원인을 코드와 실제 화면에서 다시 확인했다.

- 반 너비 patch는 Backend `apply_report_assistant_patch()`에서 `6/12`로 계산된다. 그러나
  Frontend `compactDraftLayout()`은 한 줄에 단독으로 남은 반 너비 블록을 `12/12`로 확장한다.
  서버 저장 layout과 Frontend 표시 규칙이 충돌한다.
- `_apply_existing_artifact_patch()`는 patch 적용 결과가 원본 definition과 같은지 비교하지 않는다.
  따라서 동일 제목·본문을 반환한 no-op patch도 Revision 저장 단계로 진행한다.

추가 실행 결과:

| 번호 | 시나리오 | 결과 | Revision |
|---:|---|---|---|
| 14 | Artifact 전체 묶음 블록 요청 | FAIL/CANCELLED | v22 유지 |
| 15 | 기존 블록을 다른 블록 바로 뒤로 이동 | PASS | v22 → v23 |
| 16 | 존재하지 않는 블록 이동 요청 | PASS | v23 유지 |
| 17 | 새 데이터 계획 생성 후 거절 | PASS (pre-analysis) | v23 유지 |
| 18 | 승인 대기 중 Assistant 요청 취소 | PASS | v23 유지 |
| 19 | 모든 operation 선택 해제 | PASS | v23 유지 |
| 20 | 문맥형 후속 제안 클릭 | PASS | v23 유지 |

세부 결과:

- Artifact 전체 묶음 1개 요청에 GPT가 text 2개, chart 1개, table 1개의 네 operation을 제안했다.
  사용자의 단일 `artifact` block 의도와 달라 적용하지 않았다.
- 블록 상대 이동은 `경영진 한줄 의견`을 차트 다음 순서로 이동했고 v23에 저장됐다.
- 존재하지 않는 고객 이탈 차트 요청은 임의 block을 만들거나 이동하지 않고 metric·기간을
  확인하는 clarification으로 종료됐다.
- 2026년 9월 객실 점유율 요청은 `waiting_approval` 계획까지만 생성됐고 거절 뒤 분석·Revision
  없이 ready로 돌아갔다. Trino·DataHub live 분석 성공으로 계산하지 않는다.
- `요청 취소`는 `ASSISTANT_CANCELLED`로 종료했고 Report와 Artifact를 변경하지 않았다.
- operation 두 개를 모두 선택 해제하면 `선택 0개 적용` 버튼이 disabled 상태였다.
- 문맥형 제안 클릭은 composer에 문구만 채웠고 모델 호출이나 자동 저장을 하지 않았다.
- 추가 실행에서도 Chrome console warning·error는 0건이었다.

## 10. 장문·모순·보안·대화 문맥 검증

Backend·AI의 중복 승인, stale patch, 충돌, strict schema 회귀 106개를 다시 실행해 모두 통과했다.
이어 실제 Chrome과 GPT로 다음 시나리오를 검증했다.

| 번호 | 시나리오 | 결과 | Revision |
|---:|---|---|---|
| 21 | 480자 장문에서 제목만 변경 | PASS/CANCELLED | v23 유지 |
| 22 | 같은 블록 삭제와 수정을 동시에 요청 | PASS | v23 유지 |
| 23 | script·javascript Markdown 삽입 | SAFE FAIL | v23 유지 |
| 24 | 근거 없는 미래 수치 생성 | PASS | v23 유지 |
| 25 | 오타가 많은 한국어 편집 요청 | PASS/CANCELLED | v23 유지 |
| 26 | 기존 변경안을 정반대 지시로 재수정 | PASS/CANCELLED | v23 유지 |

검증 결과:

- 480자 요청에서도 제목 변경 한 건만 제안하고 승인 전 Report를 변경하지 않았다.
- 삭제와 수정을 동시에 요청하자 둘 중 하나를 선택하도록 clarification을 반환했다.
- script와 `javascript:` Markdown 요청은 patch를 만들지 않고 typed model failure로 종료했다.
- 근거 없이 미래 매출을 만들어 달라는 요청은 승인된 분석 근거를 다시 요구했다.
- 오타가 많은 요청도 현재 `핵심 매출 요약` block의 `update_text`로 해석했다.
- “요약 수정 취소, 제목만 변경” 후속 지시는 이전 `update_text`를 제거하고 `set_report_title`
  한 건으로 대체했다.
- Chrome console warning·error는 0건이었다.

추가 발견:

- 모순 요청의 clarification 직후 완전히 새로운 script 요청을 보내자 모델이 새 요청 대신 이전
  clarification을 한 번 반복했다. 새 세션에서는 script 요청이 안전 실패했으므로 보안 우회는
  없었지만, clarification 이후 새 의도를 우선하는 대화 문맥 정책 보강이 필요하다.

## 11. 발견 결함 수정 및 재검증

앞선 실제 시나리오에서 확인한 결함 네 건을 수정했다.

1. Frontend 레이아웃 압축기가 행의 마지막 반 너비 블록을 임의로 12칸까지 늘리던 동작을 제거했다.
   서버가 저장한 `w=6`을 Canvas가 그대로 사용하므로 표 블록과 내부 표 컨테이너가 함께 반 너비에
   맞춰진다.
2. 서버 patch 적용 결과가 원본 Report definition과 같으면 승인 대기·Revision 저장 전에
   `Report patch가 실제 변경을 만들지 않습니다.`로 차단한다. 제목·본문·직전 Revision 복원 모두
   같은 비교를 거친다.
3. Artifact 전체 묶음 요청은 정확히 하나의 `add_artifact_view(view=artifact)` operation으로
   반환하도록 공통 prompt 계약을 보강했다. 질문별 문자열 분기나 production mock은 추가하지 않았다.
4. 현재 사용자 지시가 완전한 새 요청이면 unresolved clarification보다 우선하고, 대화 이력은 직전
   clarification에 대한 생략 답변일 때만 보조하도록 prompt 계약을 명확히 했다.

실제 GPT·PostgreSQL·Browser 재검증 결과:

- v23의 `승인 매출 표`는 `grid-column: 1 / span 6`과 약 333px 폭으로 렌더링됐다.
- Artifact 전체 묶음 요청은 변경안 1개, `Artifact 보기 추가`, `복합 보기 블록 추가`로 반환됐다.
  승인하지 않아 v23은 유지됐다.
- `텍스트 블록 하나를 삭제해줘`는 삭제 대상을 묻는 clarification을 반환했다. 이어 완전한 새 요청인
  제목 변경을 보내자 이전 질문을 반복하지 않고 `set_report_title` 변경안 1개를 반환했다.
- 현재 제목과 같은 제목 설정 요청은 변경안을 저장하지 않았고 v23과 4개 block이 그대로 유지됐다.
- 실제 호출 중 외부 API 접근이 제한된 임시 Backend에서 한 건이 typed model failure로 종료됐으며,
  새 session retry 후 네트워크 허용 Backend에서 동일 시나리오를 재실행해 성공을 확인했다.
- Backend readiness는 App DB·migration·template registry·model·auth가 ready다. Trino·DataHub 및
  semantic/catalog/schema 항목은 계속 not ready이므로 `new_data` live E2E로 계산하지 않는다.

검증 결과는 Backend·AI 128개와 별도 model release 포함 41개, Frontend 24개, production build,
OpenAPI·문서화·아키텍처·repository integrity·compileall·`git diff --check` 통과다. prompt는
`PROMPT-v1.8.2`, model release는 `MODEL-RELEASE-v1.34.0`으로 갱신했다.

## 12. 추가 결함 탐색: 동시성·부분 수행·메타데이터 경계

실제 GPT·격리 PostgreSQL·Browser에서 v23을 유지한 채 다음 경계 시나리오를 추가 실행했다.

| 번호 | 시나리오 | 수정 전 | 최종 결과 |
|---:|---|---|---|
| 27 | 공백만 입력 | 전송 차단 | PASS |
| 28 | 전송 버튼 동시 2회 클릭 | 서버 요청 1회 | PASS |
| 29 | 변경안 재수정 후 새로고침·재열기 | pending patch 복구 | PASS |
| 30 | 근거 alias 순서만 바뀐 동일 본문 | 동일 전·후 승인 카드 | FIXED |
| 31 | 제목 변경 + 외부 이메일 발송 | 이메일 부분을 조용히 생략 | FIXED |
| 32 | 자기 자신 뒤로 블록 이동 | 일반 model failure | FIXED |
| 33 | Revision 복원 + 제목 변경 | 일반 model failure | FIXED |
| 34 | 내부 Artifact/query/checksum 출력 유도 + 제목 변경 | 내부 값 미노출 | PASS |
| 35 | 근거 메타데이터 순서 직접 변경 | 블록 이동으로 오해 | SAFE/RESIDUAL |

수정 내용:

- `ReportBlock.evidence_refs`는 집합 의미의 lineage binding이므로 도메인 생성 시 정렬해 정규화한다.
  alias 순서만 다른 patch는 원본 definition과 같아져 Revision 전에 차단된다.
- 모델은 현재 지시의 모든 효과를 설명해야 한다. 지원하지 않는 외부 발송·자동화·스타일 작업을
  포함하면 지원 가능한 일부만 조용히 수행하지 않고 clarification을 반환한다.
- 자기 자신 기준 이동, 상충하는 효과, 복원과 다른 operation의 혼합은 patch를 만들지 않고 사용자가
  하나를 선택하도록 묻는다.
- 근거 alias와 순서는 서버 관리 메타데이터이며 보고서 배치가 아니라는 prompt 경계를 추가했다.

최종 실제 결과:

- 이메일 혼합 요청은 “제목 변경은 가능하지만 외부 이메일 발송은 범위 밖”이라고 알리고 제목만
  변경할지 물었다.
- 복원과 제목 변경 혼합 요청은 둘 중 하나를 선택하도록 물었다.
- 자기 자신 기준 이동은 유효한 이동 대상을 다시 물었고 patch·Revision을 만들지 않았다.
- 근거 순서 직접 변경 요청은 승인 카드를 만들지 않아 안전성은 지켰지만, 안내 문구가 여전히 이를
  block 이동으로 표현했다. 이는 안전 결함이 아닌 남은 대화 UX 결함으로 기록한다.
- 모든 시나리오에서 Report는 v23, 4개 block으로 유지됐다.

최종 prompt는 `PROMPT-v1.8.4`, model release는 `MODEL-RELEASE-v1.36.0`이다. Backend·AI·migration
134개, Frontend 24개, production build, OpenAPI·문서화·아키텍처·repository integrity·compileall·
`git diff --check`가 통과했다. 실제 GPT 호출은 이 섹션의 bounded 시나리오에만 사용했으며,
Trino·DataHub `new_data` live E2E는 실행하지 않았다.

## 13. 추가 결함 탐색: 시각적 no-op과 오류 분류

실제 GPT·격리 PostgreSQL·Browser에서 화면 layout과 서버 저장 좌표가 다른 경우를 추가 검증했다.

| 번호 | 시나리오 | 수정 전 | 최종 결과 |
|---:|---|---|---|
| 36 | 이미 마지막인 반 너비 표를 다시 반 너비로 요청 | 화면은 같지만 v24 생성 | FIXED |
| 37 | 현재와 같은 보고서 제목 요청 | 일반 실행 실패 안내 | FIXED |
| 38 | clarification 뒤 사용자 취소 | Report·Artifact 무변경 | PASS |
| 39 | 여러 operation 중 no-op 항목만 선택 승인 | 502 가능 | FIXED |

원인은 Frontend가 Canvas를 세로 압축해 표시하는 반면 Backend가 비연속 원시 `y` 좌표의 재배치를
실제 변경으로 판단한 데 있었다. Backend patch 적용기는 이제 현재 block 순서와 너비를 기준으로
같은 위치 이동을 no-op으로 판정한다. operation 미리보기에서도 화면과 일치하지 않는 원시 행
번호를 제거하고 앞 block 기준의 상대 위치만 표시한다.

no-op은 모델·서버 장애가 아니다. 최초 요청에서 모델이 현재와 같은 patch를 반환하면 session을
실패시키지 않고 `ready` clarification으로 저장해 “이미 반영되어 있음”을 안내한다. 일부 operation
승인 결과만 no-op이면 승인 claim과 Revision 저장 전에 `409 REPORT_ASSISTANT_PATCH_INVALID`로
차단해 현재 승인 대기 session을 보존한다.

수정 후 실제 Browser에서 같은 반 너비 요청과 같은 제목 요청은 승인 카드와 Revision을 만들지
않고 안전한 안내를 반환했다. 취소 후에도 Report는 v24, 4개 block으로 유지됐다. v24는 수정 전
결함 재현 과정에서 생성된 격리 E2E Revision이며 운영·공용 데이터가 아니다.

회귀 검증은 Backend·AI·migration 134개, Frontend 24개, production build, OpenAPI·문서화·
아키텍처·repository integrity·compileall·`git diff --check`가 통과했다. Trino·DataHub
`new_data` live E2E는 실행하지 않았다.

## 14. 추가 결함 탐색: 상충 지시와 선택 승인 오류 분류

이번 차수에는 기존 39개 시나리오와 겹치지 않는 신규 검증 항목 19개를 실행했다. 입력 계약 8개,
실제 GPT 모호성·보안·충돌 9개, 360px 반응형 layout 1개, 부분 승인 오류 분류 1개다.

| 판정 | 수 |
|---|---:|
| PASS | 18 |
| FAIL | 1 |
| 미실행 | 0 |

P2 결함 2건은 수정 전 실제 재현 뒤 수정 후 PASS로 전환했다. 남은 FAIL 1건은 첫 실제 GPT 호출의
일시적 `REPORT_ASSISTANT_TURN_MODEL_FAILED`다. retry는 원본 실패 session을 바꾸지 않고 새
session을 생성했으며 이후 8회 실제 GPT strict 호출은 성공했다.

### 14.1 P2: 상충 operation 선택을 502 서버 장애로 분류

- 시나리오: 같은 block 수정·삭제처럼 사용자가 고른 operation 조합이 승인 dry-run에서 충돌하는 경우
- 수정 전 결과: DB 승인 claim과 Revision 저장 전에는 차단됐지만 `502 REPORT_ASSISTANT_PATCH_INVALID`를 반환했다.
- 심각도: P2. 사용자 선택 문제를 모델·서버 장애로 오분류했다.
- 원인: `decide_assistant_patch()`의 선택 patch 검증 예외가 Revision 충돌 외 모든 오류를 502로 매핑했다.
- 수정 파일: `app/backend/app/api/report_router.py`
- 추가 테스트: 기존 `test_conflicting_selection_is_rejected_before_claim`을 올바른 409 계약으로 바꾸고
  범위 초과·no-op 선택 회귀와 함께 실행했다.
- 수정 후 실제 결과: deterministic API 경계에서 `409 REPORT_ASSISTANT_PATCH_INVALID`, DB claim 0회,
  Revision 저장 0회로 확인했다.
- 남은 위험: 실제 PostgreSQL에 충돌 patch를 인위적으로 저장하지 않았으므로 같은 값의 live API 재현은
  실행하지 않았다. 정상 GPT proposal은 전체 patch dry-run을 먼저 통과하므로 이 경계는 손상·과거 row
  또는 선택 조합 방어에 해당한다.

### 14.2 P2: 유지와 삭제·이동을 함께 요구하면 한쪽 지시를 조용히 생략

- 시나리오: 실제 GPT에 `표는 유지하고 표를 삭제해줘.`, `차트를 위로도 옮기고 그대로 둬.`를 각각 입력
- 수정 전 결과: 첫 요청은 `remove_block` 승인 카드를 만들었고, 둘째 요청은 이동 patch를 no-op 안내로
  바꿨다. 두 경우 모두 상충 여부를 묻지 않고 보존 지시를 소실했다.
- 심각도: P2. 승인 전이라 데이터 변경은 없었지만 일부 지시를 안내 없이 생략했다.
- 원인: 공통 prompt에 상충 효과를 clarification으로 닫는 문구는 있었으나, 모델이 `유지·그대로`를
  실행할 필요 없는 no-op으로 해석한 뒤 반대 효과만 수행할 여지가 남아 있었다.
- 수정 파일: `src/ai/prompt_registry.py`, `src/ai/contracts/model_release.v1.json`,
  `src/ai/model_contracts.py`, `evals/report_assistant_quality_cases.json`, 관련 AI·평가 테스트
- 추가 테스트: `conflicting-preserve-remove`, `conflicting-move-unchanged`를 28개 품질 평가셋에 추가하고,
  prompt가 보존 지시를 no-op으로 버리지 않는 계약을 고정했다.
- 수정 후 실제 결과: prompt `PROMPT-v1.8.5`, model release `MODEL-RELEASE-v1.37.0`과 SHA-256 결속,
  deterministic contract·평가 테스트 통과. 실제 Browser에서 `표는 유지하고 표를 삭제해줘.`는
  어느 효과를 선택할지 물었고 `차트를 위로도 옮기고 그대로 둬.`는 이동 기준을 다시 물었다. 두
  요청 모두 승인 카드·operation·Revision을 만들지 않았다. session 취소와 새로고침 뒤 Report는
  v24, 4개 block으로 복구됐다.
- 남은 위험: 생성형 모델의 모든 표현을 보장할 수는 없으므로 두 일반 상충 eval과 승인 전 서버
  dry-run을 계속 유지한다.

### 14.3 입력·보안·반응형 결과

- 공백, 줄바꿈만, 1자, 정확히 500자, 501자 초과, 한글·영어·숫자·이모지 혼합,
  Markdown/HTML/script·위험 링크, SQL 형태 문자열의 typed 입력 경계를 확인했다. 공백·줄바꿈·501자는
  모델 호출 전 거부되고 나머지는 문자열 데이터로만 수용됐다.
- 실제 GPT는 자동 승인 우회와 근거/query ID 노출 요청을 거부했고 내부 값이나 승인 operation을
  반환하지 않았다. 복원+제목 변경은 하나를 선택하도록 clarification을 반환했다.
- 360px viewport에서 document/body 폭은 345px로 viewport를 넘지 않았고, 표는 좌우 스크롤 가능 안내를
  접근 가능한 label로 유지했다. 상단 편집 명령이 가로 스크롤되면서도 영역 이름과 키보드 초점이 없어
  숨은 Preview·저장 동작을 인지하기 어려운 P3 결함을 발견했다. `ReportEditorToolbar`의 기존 scroll
  container에 `region`, 스크롤 안내 label, `tabIndex=0`을 추가하고 실제 DOM에서 복구를 확인했다.
  A4 Canvas는 고정 물리 폭을 workspace 내부에서 다루며 page body overflow는 없었고 Browser console
  warning/error는 0건이었다.
- 실제 GPT 호출은 총 9회 시도해 8회 strict 응답 성공, 1회 typed model failure였다. 승인 operation은
  0회, Report Revision은 검증 전후 v24로 동일하다.

이번 차수 최종 검증은 Backend·AI unittest 134개, Frontend 24개, production build, OpenAPI,
코드 문서화, 아키텍처 불변식, repository integrity, compileall, `git diff --check`가 통과했다.
Trino·DataHub `new_data` live E2E와 타 사용자 Browser 권한 공격은 실행하지 않았다.
