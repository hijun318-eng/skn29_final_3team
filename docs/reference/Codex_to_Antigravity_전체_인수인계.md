# Codex → Antigravity 전체 프로젝트 인수인계

> **SUPERSEDED / 실행 금지**
>
> 이 문서는 2026-08-17 당시의 역사 자료이며 외부 env, principal JSON, 구 Role 절차를
> 포함하므로 현재 환경에 실행하지 않는다. 현행 두 Role·repo-local env 절차는
> [`docs/e2e_mvp/LOCAL_SETUP.md`](../e2e_mvp/LOCAL_SETUP.md)를 따른다.

> 기준 시각: 2026-08-17 KST
>
> 저장소: `C:\Users\Playdata\Desktop\SKN_FINAL\skn29_final_3team`
>
> 현재 브랜치/HEAD: `daesung` / `5887b6e`
>
> 판정: **metadata catalog/Glossary는 직전 live 검증에서 READY, 제품 전체 P0와 실제 Browser E2E는 NOT_READY**

## 1. 먼저 알아야 할 결론

Answervice는 호텔 업무 질문을 승인된 DataHub 용어·자산·권한·계산 규칙에 연결하고, SQLGlot으로 검증한 read-only SQL을 Trino에서 실행해 근거가 있는 Analysis·Artifact·Report로 저장하는 서비스다.

현재 소스는 과거의 질문별 하드코딩·정답 SQL·정적 Context·동기 I/O·거대 컴포넌트를 제거하는 대규모 production overhaul을 거쳤다. 그러나 이 변경은 아직 commit되지 않았고 실행 중 서비스도 없다. 따라서 다음 작업자는 새 기능을 바로 추가하기보다 현재 dirty tree를 보존하고, 동일 release의 실제 Browser→Backend→Model→DataHub/Trino→App DB→Report 흐름을 먼저 재현해야 한다.

절대 혼동하지 말아야 할 판정은 다음과 같다.

| 항목 | 현재 판정 | 근거와 한계 |
|---|---|---|
| 동적 source/catalog 구현 | 구현됨 | 코드·정적 계약 기준 |
| metadata-only DataHub 발행 | 직전 live 검증 `READY` | 2026-08-17 재조회 기록, 현재 runtime은 꺼져 있어 재확인 필요 |
| semantic search/vector/Ollama | 미검증·후순위 | 이번 metadata 발행과 E2E 범위에서 제외 |
| 실제 분석 Browser E2E | `NOT_READY` | 같은 요청의 model/query/artifact/report receipt 없음 |
| P0 전체 | 미완료 | 현행 PRD의 `VERIFIED` 요구사항 0개 |
| P1/P2 확장 | 보류 | P0 Gate를 우회해 확장하지 않음 |

## 2. 현재 작업 공간 상태

### Git

- 저장소 root는 상위 `SKN_FINAL`이 아니라 `SKN_FINAL\skn29_final_3team`이다.
- 브랜치는 `daesung`, HEAD는 `5887b6e`이며 로컬의 `origin/daesung` tracking ref도 같은 commit을 가리킨다. 이번 확인에서 remote fetch는 하지 않았다.
- working tree는 매우 크고 dirty하다.
  - modified 226개
  - deleted 148개
  - untracked 331개(이 인수인계 문서 포함)
  - 합계 705개 status entry
  - tracked diff만 374 files, +10,420 / -47,581 lines
- 이 변경은 하나의 production overhaul 묶음이다. `git reset`, `git checkout --`, `git clean`, 대량 복원, 임의 pull/merge/rebase를 하지 않는다.
- 삭제로 보이는 과거 문서·fixture·V4 경로와 새 untracked 모듈은 의도적인 구조 전환이 섞여 있다. status만 보고 삭제 또는 복구하지 않는다.
- commit, push, PR은 사용자의 별도 승인 전에는 하지 않는다.

### 현재 실행 환경

2026-08-17 인수인계 확인 시점의 실제 상태:

- Docker Desktop Linux engine: 실행되지 않음
- `127.0.0.1:13000` Frontend: 닫힘
- `127.0.0.1:28000` Backend: 닫힘
- `127.0.0.1:18443` Trino: 닫힘
- `127.0.0.1:19002` DataHub UI: 닫힘
- `127.0.0.1:18081` DataHub GMS: 닫힘
- 내부/외부 env 파일은 모두 존재하고 `VITE_BACKEND_BASE_URL=/api`다.
- `/api`는 container Frontend의 Nginx가 `backend:8000`으로 proxy하는 정상 same-origin 값이다. root Compose Browser E2E를 위해 이를 무조건 `http://127.0.0.1:28000`으로 바꾸지 않는다.

### secret 경계

- 운영 정본 후보: `%LOCALAPPDATA%\Answervice\deployment\answervice.env`
- principal·Trino password DB·TLS 파일도 저장소 밖 absolute path를 사용한다.
- repository-local `infrastructure/database/.env`가 현재 존재하고 secret 값을 포함하므로 integrity gate가 실패한다.
- 이 파일은 출력·commit·전달하지 않는다. 사용자가 만든 파일이므로 임의 삭제도 하지 않는다.
- 값이 노출됐다고 판단되는 경우 파일 삭제와 credential rotation을 별개 조치로 다룬다.

## 3. 제품과 아키텍처

현재 기본 구조는 다음 modular monolith다.

```text
Browser
  → Nginx + React/Vite
  → FastAPI
      → external OpenAI-compatible model
      → DataHub GraphQL/Rest.li
      → SQLGlot policy/binding
      → Trino HTTPS/read-only
          → PMS / POS / CRM / Banquet / Facility DB
      → App PostgreSQL
          → Analysis / Evidence / Artifact / Report
```

핵심 역할:

- `analyst`: 자연어 분석, 결과·근거 확인, Artifact에서 Report 초안 생성
- `report_admin`: Report 검토·승인·최종 산출물 확인
- DataHub read principal과 publish principal은 분리
- App runtime DB 계정과 migration 계정은 분리
- model은 해석·SQL 후보·서술을 돕지만 권한·실행·공개 합격을 결정하지 않음

현재 사용자 화면은 여전히 single-turn 중심이다. App DB에 conversation 골격은 있지만 Conversation/Turn 소유권, head CAS, active lease, bounded multi-turn orchestration은 완성되지 않았다. 보고서도 여러 block을 지원하지만 대화에서 여러 Artifact/View를 선택해 같은 초안에 누적하는 전체 orchestration은 미완료다.

## 4. 지금까지 완료한 핵심 변경

### production overhaul

- 질문 문자열 `if`, 정규식, 한국어 hint dictionary 기반 routing 제거
- 특정 질문 전용 Context/Metric JSON, 정답 SQL, 고정 CTE prompt 경로 제거
- SQL parsing·policy·typed parameter binding을 하나의 SQLGlot AST 경계로 통합
- 동기 `urllib`/DB 경계를 async `httpx.AsyncClient`와 단일 `async_sessionmaker`로 전환
- DataHub/Trino/governance/execution adapter와 service 책임 분리
- scheduler race, idempotency/CAS, timeout/cancel 경계 보강
- production fake/in-memory repository와 test auth 우회 제거, test double은 `tests/`로 이동
- `ReportsPage.jsx`와 report state/artifact/DnD/A4 print 책임 분리
- production module과 공개 API에 한국어 책임·입력·실패 계약 문서화
- 과거 release/seed는 archive로 분리하고 현재 Compose/runtime fallback에서 제거

### DataHub metadata/governance

직전 live 기록:

- catalog release: `walkerhill-v4.3-catalog.1`
- Dataset 51개 / Column 578개
- 승인 runtime Metric Glossary Term 7개
- governance entity 8개 / aspect 458개
- catalog SHA-256: `d8efc5cb11f543a93ce8d3b584899a90f9548d9f9deb6b897e737a629a720ce8`
- DataHub Rest.li·GraphQL native governance와 Trino physical schema read-back 일치
- 검색 모드는 `lexical`; semantic/vector/Ollama는 이 Gate에 포함하지 않음

이 숫자는 현재 꺼진 runtime의 상태를 대신하지 않는다. 다음 실행에서 같은 release와 checksum을 다시 확인해야 한다.

### 승인된 업무 의미의 제한

- 통합매출은 회계매출이 아니라 V4.3 합성 운영매출 proxy로만 사용
- 이벤트 효과는 비행사일 비교이며 인과효과로 표현하지 않음
- VOC는 기능·SQL·보고서 검증용이며 실제 고객 인사이트나 모델 학습 근거로 사용하지 않음
- 연회는 취소 건수만 허용; 존재하지 않는 취소 수수료/환입 metric을 만들지 않음
- `realized_uplift_rate`는 `baseline_quality=USABLE` 조건을 기술적으로 강제하지 못해 발행 후보에서 보류됨

## 5. 현행 제품 판정

현행 기준은 `docs/product/`의 네 문서다. 과거 `docs/e2e_mvp/derived/`의 완료 기록은 역사 자료이며 현재 release 증거가 아니다.

`docs/product/01_PRD.md`의 76개 상태:

| 상태 | 개수 |
|---|---:|
| `VERIFIED` | 0 |
| `READY_TO_VERIFY` | 17 |
| `PARTIAL` | 28 |
| `BLOCKED` | 10 |
| `NOT_STARTED` | 21 |

대표 blocker:

- 실제 Trino positive 분석과 Gold 결과: `ANL-007`, `ANL-010`
- 실제 Browser E2E: `P0-E2E-REAL`
- 실제 Report 재실행: `P0-REPORT-RERUN`
- 보안·실패 Gate: `P0-SECURITY`, `P0-FAILURE`
- candidate/activation release 묶음: `GOV-008`, `GOV-009`, `DATA-006`
- Conversation/Turn bounded multi-turn: 다수 `CONV-*` 미완료
- 동일 release evidence manifest와 정량 held-out: `P0-EVIDENCE`, `P0-QUANT`

## 6. 검증 상태

### 이번 인수인계에서 현재 tree에 실행한 read-only 검증

- `python app/backend/scripts/export_openapi.py --check`: PASS
- `python scripts/check_code_documentation.py`: PASS
  - 250 source files / 54 executable configs
- `python scripts/lint_architectural_invariants.py`: PASS
  - 220 source files
- `python scripts/audit_repository_integrity.py`: FAIL
  - 유일 보고 항목은 repository-local `infrastructure/database/.env`
- `git diff --check`: whitespace 오류 없음
  - 일부 JSON의 CRLF→LF 안내만 있음

### 직전 기록이지만 현재 PASS로 승격하면 안 되는 결과

삭제된 `docs/architecture/production-integrity-audit.md`에 남아 있던 2026-08-16 기록:

- Python 510 passed, 30 skipped, 251 subtests passed
- Frontend 13/13 passed
- Frontend production build PASS
- root/full/semantic-search Compose config PASS

그 뒤 파일이 더 변경됐고 현재 Docker가 꺼져 있으므로 이 결과는 현재 전체 검증이 아니다. Antigravity는 작업 후 현행 `AGENTS.md`의 전체 명령을 다시 실행해야 한다.

## 7. Antigravity의 다음 작업 순서

### 1단계 — 컨텍스트와 변경 보존

1. workspace를 반드시 저장소 root `skn29_final_3team`로 연다.
2. `.agents/rules/answervice-handover.md`, `AGENTS.md`, `docs/README.md`, `docs/product/00~03`, 이 문서를 읽는다.
3. `git status --short --branch`와 변경 통계를 다시 캡처한다.
4. 사용자 변경을 되돌리지 않는다. commit/push도 하지 않는다.

### 2단계 — runtime 기동 전 안전 확인

1. Docker Desktop이 실제로 시작됐는지 확인한다.
2. 기존 `answervice` volume/container 목록을 read-only snapshot한다.
3. 다른 Compose project, volume, VHDX를 건드리지 않는다.
4. 외부 env의 필수 key는 값이 아니라 존재 여부와 참조 파일 존재만 검사한다.
5. root/full/split/semantic Compose 조합을 render해 profile과 port를 확인한다.
6. `/api`는 container Nginx proxy 계약임을 유지한다.

### 3단계 — metadata release 재확인

1. DataHub와 Trino가 같은 51/578 scope를 반환하는지 확인한다.
2. 7개 Metric Term, governance entity/aspect, catalog hash를 다시 read-back한다.
3. release/checksum/schema drift가 있으면 E2E를 시작하지 않고 fail-closed 원인을 고친다.
4. semantic search는 이번 작업에 임의로 추가하지 않는다.

### 4단계 — 실제 분석 E2E

세부 절차는 `docs/reference/Antigravity_실제_분석_E2E_실행_인수인계.md`를 따른다.

반드시 한 요청에서 다음 식별자를 연결한다.

```text
Browser action
→ HTTP request_id / trace_id
→ model route와 prompt/schema version
→ DataHub Term/Dataset/Column URN + catalog checksum
→ Trino query_id
→ App DB query execution / evidence / artifact_id
→ Browser Artifact
→ Report draft/version/run
→ HTML/PDF checksum
```

정상 흐름뿐 아니라 미인증, 모호한 질문, 역할/소유권 거부, 빈 결과, timeout/cancel 중 최소 계약상 요구 실패 흐름도 검증한다. Browser 화면만 보고 PASS라 부르지 않는다.

### 5단계 — 결함 수정

- 특정 acceptance 질문만 통과시키는 분기·JSON·SQL·fixture를 production에 추가하지 않는다.
- 오류는 가장 좁은 일반 계약 경계에서 수정한다.
- migration 변경이 필요하면 배포된 revision을 수정하지 말고 새 revision을 추가한다.
- 기능 파일은 고정 줄 수가 아니라 책임 경계와 응집도를 기준으로 분리한다.
- 코드 변경과 한국어 책임 문서를 같은 patch에서 갱신한다.

### 6단계 — 전체 Gate와 문서 판정

1. `AGENTS.md`의 정적→unit/contract→integration→browser E2E→failure/ops 순서로 실행한다.
2. skip과 live 미실행을 PASS로 바꾸지 않는다.
3. 같은 commit/data/model/policy/catalog/migration의 evidence manifest를 만든다.
4. 실제 증거가 있는 Requirement만 PRD 상태를 올린다.
5. P0 Gate 전부가 같은 release에서 `VERIFIED`되기 전에는 전체 완료라고 쓰지 않는다.

## 8. 반드시 지켜야 하는 규칙 요약

1. 현재 사용자 요청 > 안전/권한 > repository `AGENTS.md` > 기타 문서 순서다.
2. 현재 dirty tree는 사용자 자산이다. 임의 정리·삭제·복원 금지.
3. 외부 배포, 유료 API, 데이터 전송, commit/push/PR은 명시 승인 필요.
4. 질문별 `if`/regex/dictionary, 정답 SQL, 요청 전용 JSON, 고정 KPI 금지.
5. DataHub/Trino 불완전·불일치·장애는 typed error로 닫고 stale/fake fallback 금지.
6. model output은 비신뢰 입력이다. 권한·실행·최종 공개를 model이 결정하지 않음.
7. SQL은 SQLGlot AST 하나로 parse/policy/binding하며 read-only·parameterized·allowlisted여야 함.
8. secret을 argv·URL·log·screenshot·문서·Git에 넣지 않음.
9. DataHub read/publish, App runtime/migration, Source runtime 계정을 최소권한으로 분리.
10. event loop의 동기 HTTP/DB/filesystem/subprocess 금지.
11. 상태 전이·idempotency·CAS·schedule race는 SQL WHERE/transaction으로 검증.
12. 보고서의 데이터 근거는 승인 Artifact·Definition·query lineage이며 채팅 문장/화면 캡처가 아님.
13. 배포된 migration과 checksum archive는 immutable.
14. mock/fixture는 unit/contract 증거일 뿐 live/E2E 증거가 아님.
15. 테스트를 실행하지 않았으면 통과했다고 쓰지 않음.

## 9. Codex와 Antigravity 차이를 반영한 작업법

### 지침 로딩

- Codex는 repository의 `AGENTS.md` 계층 지침을 작업 규칙으로 사용했다.
- Antigravity는 workspace rule을 `.agents/rules/`에 두며 rule은 Markdown이다. 이 저장소에는 이번 인수인계 전까지 `.agents/skills/`만 있었고 workspace rule이 없었다.
- `.agents/rules/answervice-handover.md`를 진입 규칙으로 사용하고, Antigravity UI에서 해당 rule이 활성화됐는지 확인한다.
- `AGENTS.md` 전체를 이 문서에 복제하지 말고 실제 파일을 다시 읽는다. 규칙이 갱신되면 복사본보다 원본이 우선이다.

### 대화 컨텍스트

- Codex의 과거 task/thread 내용은 Antigravity로 자동 이관되지 않는다. 이 문서와 현재 파일을 context로 명시적으로 첨부한다.
- 폴더 전체를 한 번에 넣고 모두 읽었다고 가정하지 않는다. 권위 문서와 변경 대상 파일을 `@` context로 우선 지정한다.
- 과거 agent의 “완료” 발언보다 현재 코드·runtime·PRD를 우선한다.

### 도구와 권한

- Codex skill/tool 이름은 Antigravity에서 동일하지 않을 수 있다. 기능을 이름으로 가정하지 말고 실제 사용 가능한 terminal, browser, MCP, skills를 확인한다.
- Browser E2E는 Antigravity의 browser/Chrome 도구 또는 현재 workspace의 Playwright skill로 실제 UI를 조작한다.
- terminal/review/JavaScript execution policy가 작업에 필요한 수준인지 확인하되, 위험 작업을 자동 승인하지 않는다.
- 여러 agent를 병렬로 쓰더라도 같은 dirty checkout을 동시에 수정하게 하지 않는다. 분석 전용과 파일 소유 범위를 분리한다.

### 결과 보고

Antigravity의 최종 보고는 다음을 분리한다.

1. 확인된 사실
2. 실제 변경 파일과 책임
3. 실행한 명령과 정확한 결과
4. skip·미실행 live 검증
5. 남은 blocker와 위험
6. commit/push/외부 변경 여부

## 10. 권위 문서 읽기 순서

1. `AGENTS.md` — 저장소 절대 작업 규칙
2. `docs/README.md` — 문서 권위와 상태 규칙
3. `docs/product/00_기획서.md` — 목적·P0/P1/P2
4. `docs/product/01_PRD.md` — Requirement/Gate와 현재 판정
5. `docs/product/02_유저플로우.md` — 정상·명확화·거부·실패·보고서 흐름
6. `docs/product/03_아키텍처.md` — 현재/목표 구조와 release 전환
7. `scripts/audit_repository_integrity.py` — 현행 무결성 감사. 과거 기록이던 `docs/architecture/production-integrity-audit.md`는 삭제됐다.
8. `docs/reference/Antigravity_실제_분석_E2E_실행_인수인계.md` — 다음 실제 E2E 절차
9. 현재 코드·Compose·migration·runtime read-back — 최종 구현 사실

과거 `docs/e2e_mvp/derived/`, 발표자료, screenshot, daily report는 배경 자료일 뿐 현재 완료 근거가 아니다.

## 11. 시작 프롬프트

Antigravity에 다음처럼 시작시키면 된다.

```text
저장소 root C:\Users\Playdata\Desktop\SKN_FINAL\skn29_final_3team에서 작업한다.
.agents/rules/answervice-handover.md와 그 파일이 지정한 권위 문서를 먼저 읽는다.
현재 705개 항목의 dirty worktree를 사용자 자산으로 보존하며 reset/clean/checkout/pull/commit/push하지 않는다.
Docker Desktop과 서비스는 현재 꺼져 있다. 먼저 read-only 상태와 기존 volume을 확인하고,
docs/reference/Antigravity_실제_분석_E2E_실행_인수인계.md 범위의 실제 Browser E2E만 진행한다.
VITE_BACKEND_BASE_URL=/api는 container Nginx proxy의 정상 값이므로 임의 변경하지 않는다.
mock/fixture/하드코딩/정답 SQL/요청 전용 JSON 없이 같은 release의 request_id, trace_id,
DataHub checksum, Trino query_id, artifact_id, report/PDF checksum을 연결한다.
실제 증거가 없으면 PASS나 완료라고 쓰지 말고 BLOCKED 원인과 다음 행동을 보고한다.
```

## 12. 참고한 agent 제품 문서

- Codex `AGENTS.md`: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- Antigravity Rules/Workflows: https://antigravity.google/docs/rules-workflows
- Antigravity IDE 시작 가이드: https://codelabs.developers.google.com/getting-started-agy-ide

제품 문서는 작업 도구 차이를 설명하는 데만 사용했다. 프로젝트의 기능 사실과 완료 판정은 현재 저장소와 runtime 증거가 우선이다.
