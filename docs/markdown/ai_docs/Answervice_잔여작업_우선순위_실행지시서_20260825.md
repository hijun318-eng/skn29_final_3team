# Answervice 잔여 작업 우선순위 실행지시서

| 항목 | 내용 |
|---|---|
| 문서 설명 | 현재 통합 작업공간의 잔여 작업을 우선순위와 완료 Gate에 따라 실행하기 위한 작업 지시서 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-08-25 10:10 KST |
| 작성·수정 | OpenAI Codex |
| 대상 경로 | `D:\bootcamp\20260824톨합` |
| 기준 Branch | `jaehong` |
| 상태 기준 | 현재 코드·Git 작업 트리·Docker 상태·Backend `/readiness`·PRD·WBS 교차 점검 |

## 1. 실행 결론

최우선 과제는 새 기능 추가가 아니다. 현재 `healthy`인 개별 컨테이너를 하나의 동일 릴리스로 결속하고 Backend `/readiness`를 `ready`로 만든 뒤, 실제 사용자 경로 E2E를 통과시키는 것이다.

작업은 아래 순서를 바꾸지 않는다.

```text
P0-1 릴리스 준비 상태 복구
→ P0-2 Source·Image·Manifest 동일 릴리스 동결
→ P0-3 전체 정적·회귀 Gate
→ P0-4 실제 사용자 E2E
→ P1 보안·장애·복구
→ P1 보고서·브라우저 마감
→ P2 모델·RAG·ML 운영 편입 판단
→ P3 문서·발표·최종 패키징
```

선행 단계가 실패하면 다음 단계의 성공을 최종 완료 증거로 사용하지 않는다. 과거 이미지, mock, fixture, screenshot 또는 다른 commit의 결과를 현재 릴리스 증거와 합치지 않는다.

## 2. 현재 기준선

| 점검 항목 | 현재 상태 | 판정 |
|---|---|---|
| Backend `/health` | `healthy` | 프로세스 생존 확인 |
| Backend `/readiness` | `not_ready` | 릴리스 차단 |
| 미준비 dependency | `semantic_release`, `catalog_manifest`, `trino_schema` | 최우선 해결 대상 |
| 주 Backend·Frontend·ML Runtime | `healthy`, RestartCount 0 | 개별 프로세스 정상 |
| Trino | `healthy`, RestartCount 0, `/v1/info` HTTP 200 | 기동 정상, 릴리스 schema 결속 미완료 |
| ML Runtime | `READY`, `LIVE_TRINO_PMS` 객실수요 모델 활성 | 객실수요 경로만 준비 |
| RAG Runtime | healthy, 17 documents·363 chunks | `ISOLATED_POC`, Tool 비활성, P2 미승인 |
| Git 작업 트리 | 수정 3개와 미추적 release·평가·script·문서 존재 | 릴리스 동결 불가 |
| Host Python Gate | `pytest` 미설치 | 전체 pytest 미실행 |
| Frontend Gate | React·Vite 의존성 미설치 | test 5건·build 미실행 |
| WBS | 완료 35, 진행 14, 대기 12, 검토 1 | 기준일이 오래되어 재판정 필요 |

## 3. P0-1 — Backend 릴리스 준비 상태 복구

### 3.1 목표

Backend `/readiness`의 `semantic_release`, `catalog_manifest`, `trino_schema`를 모두 `ready`로 바꾸고 전체 상태를 `ready`로 만든다.

### 3.2 작업 지시

1. 현재 Backend가 참조하는 `product_release_id`, semantic release ID, catalog manifest checksum을 확인한다.
2. DataHub의 active semantic release와 Backend 설정값이 같은지 확인한다.
3. catalog manifest가 실제 DataHub 전체 read-back 및 RuntimeCatalogProjection 결과와 일치하는지 확인한다.
4. Trino `information_schema`에서 active manifest가 요구하는 schema·table·column·type을 조회한다.
5. 누락된 release 적용이 필요하면 `.codex_issue_datahub_token.py`와 `.codex_apply_serving_release.ps1`의 입력·대상·비밀정보 출력 여부를 먼저 검토한 뒤 실행한다.
6. `serving.properties`의 Trino 476 native S3 설정이 현재 healthy 컨테이너와 일치하는지 확인한다.
7. Backend를 재기동해야 한다면 현재 release 설정을 고정한 뒤 한 번만 재기동하고 RestartCount와 readiness를 다시 확인한다.

### 3.3 금지 사항

- readiness를 통과시키기 위해 dependency를 `not_required`로 낮추지 않는다.
- 임시 JSON, 과거 manifest, last-success cache로 semantic release를 대체하지 않는다.
- DataHub token, DB 비밀번호, TLS private key를 문서·Git·터미널 결과에 출력하지 않는다.
- Trino `/v1/info` 성공만으로 schema 연결 성공을 선언하지 않는다.

### 3.4 완료 조건

- Backend `/readiness` HTTP 응답의 전체 `status`가 `ready`다.
- 모든 필수 dependency가 `ready` 또는 사전 승인된 `not_required`다.
- `semantic_release`, `catalog_manifest`, `trino_schema`가 같은 `product_release_id` 증거에 연결된다.
- Trino에서 인증된 `SELECT 1`과 active schema의 대표 read-only query가 성공한다.
- Backend·Trino RestartCount가 0이며 최소 10분 동안 health가 유지된다.

### 3.5 필수 증거

- readiness 응답 원문에서 비밀정보를 제거한 receipt
- product release·semantic release·catalog checksum·Trino schema fingerprint
- Trino query ID, 실행 시각, read-only 판정
- 사용한 source commit SHA와 image digest

## 4. P0-2 — Git·Image·Manifest 동일 릴리스 동결

### 4.1 목표

현재 수정 사항을 검토해 하나의 승인 가능한 source SHA로 만들고, Backend·Frontend·ML·Trino 설정과 manifest가 같은 SHA와 release ID를 가리키게 한다.

### 4.2 작업 지시

1. 다음 변경을 각각 `반영`, `제외`, `별도 보관`으로 판정한다.
   - `infrastructure/database/trino/etc/catalog/serving.properties`
   - `src/modelops/model_runtime_manifest.v1.json`
   - `tests/ai/test_runtime_model_configuration.py`
   - `src/modelops/releases/node2_pilot800_20260824.json`
   - `evals/reports/`
   - `.codex_apply_serving_release.ps1`
   - `.codex_issue_datahub_token.py`
   - 수정된 벡터DB 결과서
2. `~$`로 시작하는 Word 잠금 파일은 Word 프로세스와 원본 저장 상태를 확인한 후 Git 대상에서 제외한다.
3. release manifest에 source SHA, data release, DataHub release, catalog checksum, model·prompt·policy version, migration head를 기록한다.
4. Backend·Frontend·ML 이미지를 승인 source SHA로 다시 만들고 OCI revision label 또는 동등한 provenance를 넣는다.
5. 컨테이너의 image digest와 source SHA가 manifest와 일치하는지 확인한다.
6. 모든 검증이 끝난 뒤에만 commit하고 승인 대상 branch로 merge한다.

### 4.3 완료 조건

- 의도하지 않은 수정·미추적 파일·잠금 파일이 없다.
- `git diff --check`가 통과한다.
- 승인 source SHA와 각 실행 image digest가 release manifest에 존재한다.
- 동일 release의 migration head·model manifest·catalog manifest가 연결된다.
- merge 후 재검증 대상 SHA가 더 이상 바뀌지 않는다.

## 5. P0-3 — 전체 정적·회귀 Gate 실행

### 5.1 목표

현재 source SHA에서 저장소 전체 Gate를 재현하고 실패·skip·미실행을 분리한다.

### 5.2 환경 준비

1. 프로젝트 README와 lock file 기준으로 Python 가상환경과 Frontend dependency를 복구한다.
2. 임의 최신 버전 설치나 lock file 재생성을 금지한다.
3. 전체 pytest의 `--basetemp`는 저장소 밖 OS 임시 경로를 사용한다.

### 5.3 필수 검증

```powershell
python -m compileall app src tests
python -m pytest -p no:cacheprovider --basetemp <OS_TEMP_PATH> tests
npm ci
npm test
npm run build
docker compose config
git diff --check
```

추가로 OpenAPI contract, code documentation, architecture invariant, repository integrity와 모든 Compose profile config를 실행한다.

### 5.4 완료 조건

- 전체 pytest 실패 0건이다.
- 환경 부족으로 skip된 검증은 PASS 수에 넣지 않고 별도 목록화한다.
- Frontend test와 production build가 모두 성공한다.
- 모든 Compose profile이 동일 env contract로 parse된다.
- 생성된 build·cache·임시 파일이 Git 작업 트리에 남지 않는다.

## 6. P0-4 — 실제 사용자 E2E 봉인

### 6.1 목표

mock·fixture·고정 응답·과거 cache 없이 실제 Browser·HTTP·Backend·DataHub·Trino·Source DB·App DB 흐름을 검증한다.

### 6.2 필수 정상 경로

1. 로그인 후 새 Conversation을 생성한다.
2. 승인된 절대 기간의 객실 매출 질문을 실행한다.
3. DataHub 후보 검색과 entitlement·release membership 필터를 확인한다.
4. Node 1 typed request, RuntimeContextPackage, G1을 확인한다.
5. Node 2 SQL 생성, G2 AST·read-only 검사와 최대 1회 repair를 확인한다.
6. Trino 실제 query ID와 결과 hash를 확인한다.
7. G3를 통과한 Artifact에서 표·차트·요약·근거를 렌더링한다.
8. 같은 Artifact의 표현 변경은 Trino 재호출 0건인지 확인한다.
9. 현재 View를 Report에 추가하고 Report 재실행 시 새 Run·query ID가 생성되는지 확인한다.
10. `request_id → turn → run → tool_call → query_id → artifact → report → audit` 계보를 조회한다.

### 6.3 필수 MCP 경로

- `initialize`
- `tools/list`
- 허용 사용자의 실제 `tools/call`
- 미허용 사용자의 list·call 동시 차단
- 잘못된 protocol version·tool name·추가 input field 거부
- RAG·ML Tool은 승인 상태와 P2 편입 결정에 따라 노출 또는 fail-closed 처리

### 6.4 필수 실패 경로

- 모호한 Metric·기간: Run·Trino query 0건
- 승인 데이터 범위 밖 상대기간: `BLOCKED + OUT_OF_DATA_RANGE`
- 빈 결과: `BLOCKED + EMPTY_RESULT`
- 권한 없는 객체 ID: 403 또는 계약된 거부 상태
- G2 재실패: 1회 repair 후 terminal 실패
- timeout·사용자 취소: Trino query 취소와 terminal 상태 일치
- 선택 block 실패: 의미가 유지될 때만 `PARTIAL`

### 6.5 완료 조건

- 정상·명확화·거부·실패·취소·Report 재실행이 같은 release에서 통과한다.
- 각 경로의 Browser 화면, HTTP 응답, DB 상태, query ID, audit가 하나의 trace로 연결된다.
- `cached=false` 대표 정상 경로가 존재한다.
- 현재 PRD의 P0 E2E 관련 Requirement와 Release Gate 상태를 실제 증거에 따라 재판정한다.

## 7. P1-1 — 보안·장애·복구 Gate

### 7.1 작업 지시

- 타 사용자 Conversation·Turn·Artifact·Report ID 주입을 전수 차단한다.
- session 만료, logout, 권한 회수 뒤 server fetch와 Frontend cache purge를 확인한다.
- Trino service principal 사칭·write·DDL·다중 statement를 차단한다.
- DataHub token·DB credential·TLS 인증서의 저장·rotation·폐기 절차를 검증한다.
- Backend crash, Trino timeout, query 제출 후 응답 유실, DB commit 불명확 상황을 fault-injection한다.
- 고아 query·영구 RUNNING Run·중복 query가 0건인지 reconciler로 확인한다.
- backup→restore→rollback rehearsal을 격리 환경에서 수행한다.

### 7.2 완료 조건

- P0 보안 요구는 L4 증거를 가진다.
- 복구 후 데이터·projection·policy가 서로 다른 release로 섞이지 않는다.
- 실패를 과거 Artifact나 빈 성공 응답으로 대체하지 않는다.

## 8. P1-2 — Frontend·Report 마감

### 8.1 작업 지시

- Report 일정 실행·Assistant UI의 실제 Backend 연결을 완료한다.
- Request Trace·선택형 고급 Audit UI를 실제 trace contract와 연결한다.
- 로딩·실패·차단·부분 성공·취소·재연결 상태를 구분한다.
- ML 예측 화면에 모델 version, 합성 여부, feature 기준시각, 실행 ID를 표시한다.
- 접근성 keyboard navigation, focus, 색 대비, screen reader label을 검증한다.
- 새로고침·중복 클릭·동시 tab·느린 네트워크 Browser E2E를 수행한다.

### 8.2 완료 조건

- WBS `6.8`, `6.10`, `6.11`, `7.4`를 실제 코드와 E2E 증거로 재판정한다.
- Frontend build 결과와 실제 배포 image가 같은 source SHA다.
- 화면의 성공 표시가 Backend terminal 상태 및 저장된 Artifact와 일치한다.

## 9. P2 — ModelOps·RAG·ML 운영 편입 판단

### 9.1 Node 2 sLLM

- `node2_pilot800_20260824`의 실제 endpoint를 연결하고 `live_endpoint_verified`를 검증한다.
- 20건 smoke 결과를 최종 품질 Gate로 사용하지 않는다.
- `full3000` 학습은 비용·품질 개선 가설·승인자가 있을 때만 실행한다.
- Base·adapter hash, context window, output token, latency·VRAM·오류율을 release manifest에 연결한다.

### 9.2 RAG

- 현재 8문항 embedding 비교는 모델 선택 근거로 부족하므로 승인 Gold 80문항 이상을 먼저 봉인한다.
- 답변 의미 정확성의 `MANUAL_REVIEW_REQUIRED`를 사람 검토로 닫는다.
- P2 승인 전에는 Tool 등록을 계속 비활성으로 유지한다.
- 승인 시 HMAC, citation, timeout, audit, 역할 정책을 실제 MCP 호출로 검증한다.

### 9.3 ML

- 객실수요 모델은 실제 MCP/Backend/UI/audit 경로를 검증한다.
- No-show 모델은 신뢰 가능한 `outcome_recorded_at`과 승인 source snapshot이 확보되기 전까지 비활성으로 유지한다.
- No-show readiness의 모든 Gate가 PASS가 되기 전 local demo 우회 활성화를 금지한다.

### 9.4 완료 조건

- 각 기능을 `운영 편입`, `P2 유지`, `제외` 중 하나로 승인자가 결정한다.
- 운영 편입 항목만 Tool Registry에서 활성화한다.
- 미승인 기능은 P0/P1 완료 판정을 막지 않으며 UI에서도 운영 기능처럼 노출하지 않는다.

## 10. P3 — 문서·WBS·발표·최종 패키징

### 10.1 작업 지시

1. WBS의 2026-08-13 기준 상태를 현재 source와 실행 증거로 갱신한다.
2. Trino 재시작·Model API 종료로 기록된 2026-08-24 통합 현황을 현재 상태로 수정한다.
3. PRD의 66개 P0 Requirement와 11개 Release Gate를 증거 수준에 따라 재판정한다.
4. 최종 발표 Story·PT·Q&A 근거·시연 시나리오를 같은 release receipt로 작성한다.
5. 성공·차단·Partial·Report 시연을 녹화하고 사용한 SHA·release ID를 기록한다.
6. README, migration head, manifest, 실행 방법, 복구 절차와 승인 SHA를 최종 소스 패키지에 포함한다.

### 10.2 완료 조건

- 문서·WBS·발표자료·시연영상의 버전과 승인 SHA가 일치한다.
- 현재 상태와 충돌하는 과거 문서는 과거 기록임을 명시한다.
- 실패 또는 미실행 Gate를 `PASS`, `VERIFIED`, `완료`로 표현하지 않는다.

## 11. 담당 및 승인 기준

| 우선순위 | 주 담당 | 공동 검증 | 최종 승인 |
|---|---|---|---|
| P0-1 DataHub·Trino release readiness | R2·R4 | R1·R3 | R1 |
| P0-2 Git·Image·Manifest 동결 | R1·R4 | 전원 | R1 |
| P0-3 전체 Gate | R1 | 전원 | R1 |
| P0-4 실제 E2E | R4·R5 | R1·R2·R3 | R1 |
| P1 보안·복구 | R4 | R1·R2 | R1 |
| P1 Frontend·Report | R5 | R1·R4 | R1 |
| P2 ModelOps·RAG·ML | R3 | R1·R2·R4·R5 | R1 |
| P3 문서·발표 | R1 | 전원 | R1 |

## 12. 일일 작업 보고 형식

각 작업자는 아래 형식으로만 상태를 보고한다.

| 항목 | 작성 내용 |
|---|---|
| 작업 ID | `P0-1` 형식 |
| 기준 SHA·release ID | 실제 값 |
| 변경 파일 | 경로 목록 |
| 실행 검증 | 명령·시각·PASS/FAIL/SKIP |
| Runtime 증거 | image digest·query ID·request/trace ID |
| 미실행 검증 | 사유와 담당자 |
| 잔여 위험 | 구체적인 실패 조건 |
| 다음 작업 | 선행 조건을 만족한 한 단계 |

## 13. 최종 완료 판정

다음 조건을 모두 만족하기 전에는 프로젝트 전체 완료로 선언하지 않는다.

- Backend 전체 readiness `ready`
- 동일 source SHA·image digest·data·DataHub·catalog·model·policy·migration release 봉인
- 전체 pytest·Frontend test/build·Compose·architecture Gate PASS
- 실제 Browser 기반 정상·거부·실패·취소·Report E2E PASS
- 보안·복구 L4 증거 확보
- Git 승인 branch merge 및 승인 SHA 고정
- WBS·PRD·현황·발표자료·시연영상 동기화

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-08-25 10:10 KST | 현재 runtime·Git·WBS·PRD 점검을 기준으로 잔여 작업을 P0~P3 실행 순서와 완료 Gate로 정리 |
