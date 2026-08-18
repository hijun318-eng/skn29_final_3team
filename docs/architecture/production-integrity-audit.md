# Answervice production integrity audit

## 판정 범위

이 문서는 2026-08-16에 `skn29_final_3team`의 Git 관리 파일과 unignored 파일을 대상으로 수행한 전수 감사 결과를 기록한다. 사용자별 질문 하나를 통과시키기 위한 mock·고정 질문 분기·정답 SQL·요청 전용 JSON을 제거하는 것이 목적이며, test fixture와 불변 과거 release archive는 운영 경로와 분리해 판정한다.

파일별 분류 결과는 [`repository-file-inventory.md`](repository-file-inventory.md)에 생성한다. 두 파일 모두 다음 명령의 현재 구현을 권위로 삼는다.

```powershell
python scripts/audit_repository_integrity.py --write-report
python scripts/check_code_documentation.py
```

## 평가서 지적과 변경 결과

| 평가서 지적 | 현재 구현 | 운영 판정 |
|---|---|---|
| 질문 문자열·정규식·힌트 dictionary | 질문 원문은 model 해석 입력일 뿐 SQL policy 분기에 전달하지 않는다. DataHub Term·Dataset semantic search와 typed Context가 선택 근거다. | 제거 |
| prompt의 고정 다중-table CTE | prompt는 입력된 schema·metric·join·time·parameter contract만 사용하도록 제한한다. repair도 violation code와 동일 Context만 받는다. | 제거 |
| 요청 전용 Context/Metric JSON | 요청별 snapshot·source registry·asset health·demo manifest와 runtime import를 삭제했다. | 제거 |
| 정규식 SQL 검증·문자열 parameter 치환 | `sqlglot`으로 한 번 parse한 AST에서 table·column·join·placeholder·limit·aggregate를 검증하고 같은 expression을 typed binding과 실행에 사용한다. | 제거 |
| async handler의 동기 HTTP/DB I/O | `httpx.AsyncClient`, 단일 `async_sessionmaker`, async repository/service 경계로 통합했다. | 제거 |
| scheduler 조기 전진·동시 완료 race | terminal run evidence와 동일 definition/version/run ID, 예정 시각을 조건으로 한 원자적 update만 다음 schedule을 확정한다. | 교정 |
| 한국어 3-byte token 추정 | provider token usage를 우선하고 fallback은 Unicode code point가 아닌 tokenizer-compatible 보수적 예산 경계를 사용한다. | 교정 |
| DataPlatform·ReportsPage monolith | DataHub/Trino/governance/execution과 report state/lifecycle/artifact/DnD/view/A4 print 책임으로 분해했다. 일반 source는 500줄 이하, 단일 cascade는 근거가 있는 800줄 이하 예외만 허용한다. | 분해 |
| 폐기된 외부 UI 의존·문서 참조 | code/config/document 전체에서 해당 제품명 검색 결과가 0건이어야 최종 Gate를 통과한다. | 제거 |

## 운영 권위와 JSON 경계

운영 schema·column·Metric·Dimension·Join·Time·entitlement의 권위는 DataHub GraphQL과 Trino `information_schema`의 live read-back이다. DataHub release manifest와 dataset/term custom properties도 그대로 신뢰하지 않고 native governance를 포함한 content-derived checksum을 runtime에서 다시 계산한다.

저장소 JSON은 다음 네 종류만 허용한다.

1. 공개 API·node I/O처럼 generator와 validator가 있는 versioned schema
2. dependency·model capacity·provider contract처럼 명시적 소유자가 있는 versioned manifest/config
3. Trino access-control처럼 배포 엔진이 직접 소비하고 CI가 문법을 검사하는 policy
4. `tests/` 아래의 test-only fixture

특정 질문, 고객 등급, 기간, Metric, table 조합, 정답 SQL을 보유한 JSON은 운영 파일·cache·fallback으로 허용하지 않는다. `infrastructure/database/releases/`와 `infrastructure/database/sql/data/`는 checksum을 보존하는 불변 과거 archive이며 현재 Compose·bootstrap·CI·application import에서 참조하지 않는다.

## 추가 전수 감사에서 제거한 우회 경로

- 정적 Template 역할 파일을 삭제하고 승인 SQL·parameter·source·allowed role을 App DB의 동일 row에서 transactionally 조회하도록 변경했다. 역할 근거를 안전하게 복원할 수 없는 기존 승인 row는 migration에서 DRAFT로 되돌린다.
- production 기본 `InMemoryReportRepository`와 package export를 제거하고 test double을 `tests/support/`로 이동했다.
- 고정 질문 button·날짜 placeholder·호텔 전용 field/title 추론을 Frontend에서 제거했다. 서버가 승인 label을 주지 않으면 canonical field를 그대로 표시한다.
- 질문별 demo seed·고정 serving SQL·keeper/recovery·synthetic principal·정적 source contract의 active Compose·script 참조를 제거했다.
- OpenAPI 예시는 runtime fallback이 아님을 모듈 경계에 명시하고, 실제 호텔 질문·FQN 대신 임의의 중립 계약 값을 사용한다.
- mock transport 기반 검증은 contract/unit으로만 명명한다. 실제 외부 dependency와 연결하지 않은 결과에 live·production·E2E PASS를 붙이지 않는다.
- production 인증의 test token·`AUTH_MODE` 분기를 삭제하고 테스트만 FastAPI dependency로 principal을 주입한다.
- Trino runtime은 HTTPS·private CA·Basic principal로 terminal `SELECT 1`까지 확인하며, DataHub readiness는 조회 전용 service actor의 인증 GraphQL 응답을 검증한다.
- DataHub clean start는 PAT가 필요 없는 `Core`와 외부에서 발급한 서로 다른 read/publish actor·PAT를 검증하는 `Catalog` 단계로 분리했다. Backend에는 mutation credential을 주입하지 않는다.
- 활성 model route는 versioned capacity manifest의 provider·model ID·output 한도에 결속하고 readiness가 각 `/v1/models`의 exact ID를 확인한다.

## 주석 인수 기준

모든 production module과 공개 class/function/method/hook/component는 한국어 책임 문서를 가진다. 이름만 바꾼 자동 생성형 문구는 검사기가 거부한다. 보안 권한, SQL AST, typed binding, transaction/CAS, idempotency, checksum, pagination, timeout/cancel, external read-back에는 구현 방법보다 해당 검사가 필요한 이유와 실패 시 닫히는 경계를 가까운 주석에 기록한다.

주석은 코드 한 줄을 한국어로 다시 읽는 용도가 아니다. 공개 호출자가 입력 권위·반환 계약·typed failure를 이해하고, 유지보수자가 무결성 검사를 삭제했을 때 어떤 우회가 생기는지 알 수 있어야 한다.

## Live 상태와 남은 Release Gate

source와 local contract 검증이 통과해도 현재 live production 준비 완료를 뜻하지 않는다. 2026-08-17 metadata-only 발행 후 다음을 실제 재조회했다.

- release scope: DataHub와 Trino 모두 51 Dataset/578 Column
- runtime governance: 7개 metric Glossary Term, 8개 owner/domain/lifecycle entity, 458 aspects
- catalog fingerprint: `d8efc5cb11f543a93ce8d3b584899a90f9548d9f9deb6b897e737a629a720ce8`
- 검증한 상태: 최소권한 publish 후 Rest.li 전체 aspect, GraphQL native governance·release membership, Trino physical schema의 독립 read-back
- 검증하지 않은 상태: semantic indexing·검색, model을 포함한 Browser→Backend→DataHub/Trino→Source/App DB positive query E2E

따라서 metadata catalog/Glossary gate는 `READY`지만 제품 전체 rollout은 `NOT_READY`다. semantic search를 도입할 때는 별도 전략·비교 검증을 거치고, 실제 query E2E는 같은 `product_release_id`의 query ID·request/trace/artifact receipt로 별도 Gate를 수행한다.

## 최종 검증 기록

2026-08-16 최종 stable source에서 다음 결과를 확인했다.

- OpenAPI committed snapshot: `OPENAPI_CONTRACT_VERIFIED`
- code documentation: 242 source files, 54 executable configs 통과
- architecture line/pattern linter: 212 source files 통과
- repository integrity inventory: 688 files 통과
- Python compileall: `app/backend`, `src`, DataHub infrastructure, scripts, evals, tests 통과
- 전체 Python test: 510 passed, 30 skipped, 251 subtests passed
- Frontend test: 13/13 passed
- Frontend production build: Vite 8.1.5, 2,661 modules 통과
- root/full/semantic-search Compose expansion: 세 구성 모두 `config --quiet` 통과
- forbidden pattern, 폐기 UI 의존, runtime archive reference, production auth bypass 검색: 허용된 검사 코드·migration tombstone·MockTransport test seam 외 활동 코드 0건
- `git diff --check`: 오류 0건(CRLF→LF 안내만 존재)

30개 skip은 disposable migration/report DB, 별도 real HTTP, opt-in live DataHub/Trino,
live semantic producer와 `ANSWERVICE_RUNTIME_URL`이 필요한 검증이다. 이를 통과로 바꾸지
않았으며 위의 live rollout `NOT_READY` 판정도 유지한다.
