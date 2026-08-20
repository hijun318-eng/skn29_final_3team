# Answervice 저장소 작업 지침

이 문서는 `skn29_final_3team` 저장소에서 작업하는 사람과 자동화 에이전트가 따라야 하는 저장소 전용 규칙이다. 현재 사용자의 명시적 요청과 안전·권한 제약이 이 문서보다 우선한다.

## 제품 목표

Answervice는 사용자의 자연어 질문을 승인된 업무 정의와 데이터 자산에 연결하고, 읽기 전용 SQL로 분석한 뒤 결과·근거·보고서를 함께 제공한다. 화면이나 테스트가 그럴듯하게 보이는 것보다, 동일 release의 실제 Backend, DataHub, Trino, source DB, app DB, model 계약이 안전하게 연결되는 것이 우선이다.

정상 분석 흐름은 다음 순서를 지킨다.

```text
인증과 권한 확인
→ 질문 해석 또는 명확화 요청
→ 승인된 업무 용어·지표·자산 탐색
→ 권한·스키마·관계·기간 규칙이 포함된 Context 구성
→ 매개변수화된 읽기 전용 SQL 생성
→ SQLGlot AST 정책 검증과 서버 소유 값 바인딩
→ Trino 실행과 결과 검증
→ 근거·lineage·artifact 저장
→ 보고서 초안·확정·재실행
```

## 작업 시작과 범위

1. 저장소 root와 `git status --short --branch`를 먼저 확인한다.
2. 기존 dirty worktree는 사용자 작업으로 간주한다. 관련 없는 파일을 되돌리거나 이동·삭제하지 않는다.
3. [`docs/README.md`](docs/README.md)를 기준으로 현행 제품 문서와 역사 자료를 구분한다.
4. 목표, 포함 범위, 제외 범위, 변경 권한, 완료 조건, 검증 방법을 먼저 정한다.
5. 코드·설정·migration·runtime 상태와 문서가 다르면 실제 구현과 검증된 계약을 기준으로 함께 정정한다.
6. commit, push, PR, 외부 배포, 유료 API 호출, 외부 데이터 전송은 사용자의 별도 승인이 없으면 하지 않는다.

과거 계획서·발표자료·프롬프트는 배경 자료일 뿐 현행 제품의 권위 있는 계약이 아니다. 역사 자료는 실행 경로에서 분리하고 필요하면 `SUPERSEDED / 실행 금지` 배너와 현행 문서 링크를 둔다.

## 이름과 책임 경계

- 파일·모듈·함수·타입 이름은 `data_platform`, `context_registry`, `report_execution`처럼 책임과 도메인을 드러내야 한다.
- 날짜, 단계번호, `latest`, `new`, `old`만으로 구현 이름을 만들지 않는다.
- API version, DB migration revision, 외부 schema identifier처럼 호환성에 필요한 공개 식별자는 임의로 바꾸지 않는다.
- UI, API, 도메인 규칙, transport, persistence, policy를 한 파일에 몰아넣지 않는다.
- 기존 port·adapter·service로 충분하면 같은 책임의 추상화나 의존성을 추가하지 않는다.
- 근거 없이 microservice, 범용 agent framework, 별도 queue를 도입하지 않는다.

## 책임 분리

- 파일 줄 수를 고정 상한으로 검사하지 않는다.
- 파일 크기와 무관하게 UI, API, 도메인 규칙, transport, persistence, policy의 책임 경계와 응집도를 기준으로 분리한다.
- 단순히 줄 수를 줄이기 위한 무의미한 위임 모듈이나 중복 추상화는 만들지 않는다.

## 동적 데이터·AI 계약

- 업무 용어, metric 정의·별칭·집계·단위·소유자·승인 상태의 운영 원본은 DataHub Business Glossary와 승인된 governance metadata다.
- asset, field, join, time, identity, entitlement, query policy는 runtime에서 읽은 typed context로만 전달한다.
- 질문 문구, 고객 등급, 특정 호텔, 기간 표현, 테이블 조합을 기준으로 분기하는 `if`, 정규식, 키워드 map, 정적 hint 사전을 production에 두지 않는다.
- 특정 요청을 만족시키는 별도 JSON, 고정 Context snapshot, 정답 SQL, 미리 계산한 KPI를 운영 원본이나 장애 fallback으로 사용하지 않는다.
- JSON은 공개 schema, versioned manifest, 재현 가능한 configuration, 승인 receipt, test fixture처럼 권위·생성 절차·검증기·만료 조건이 명확한 경우에만 사용한다.
- DataHub 장애, catalog 불완전, checksum 불일치, schema drift, 승인 용어·관계 부재는 성공처럼 우회하지 않고 typed error로 닫는다.
- model output은 신뢰할 수 없는 입력이다. 권한, 실행, 공개 여부, 최종 상태를 model이 결정하지 않는다.
- model·prompt·schema·policy·catalog·migration·cache namespace는 하나의 제품 release 경계로 묶는다.

## SQL 생성과 실행

- SQL은 runtime Context의 asset·field·metric·join·time·permission 계약으로 구성한다. prompt, migration, application helper가 특정 질문의 완성 CTE를 반환해서는 안 된다.
- SQL parsing과 안전성 판단은 `sqlglot` AST 결과 하나를 공유한다. SQL 문자열 정규식, 별도 수기 tokenizer, 실행 직전 문자열 치환으로 validator를 우회하지 않는다.
- SQL은 한 개의 매개변수화된 read-only query여야 하며 승인된 asset·column·join만 사용한다.
- placeholder는 AST에서 식별하고 expected set과 exact match한 뒤 서버 소유 typed 값을 AST transform으로 바인딩한다.
- question 원문은 SQL policy에 전달하지 않는다. resolved metric·comparison·time·join·permission 규칙만 전달한다.
- schema lookup, query 실행, pagination, cancellation은 같은 principal과 capability 계약을 사용한다.

## DataHub 카탈로그와 Glossary 발행

- metadata-only 발행은 dataset·schema·description·owner·domain·tag·Glossary·lineage까지만 다룬다. semantic search, embedding, vector index, Ollama를 같은 완료 조건에 묶지 않는다.
- 카탈로그 범위는 live DataHub의 활성 dataset과 runtime ingestion recipe, 명시된 serving schema의 교집합으로 결정한다. 특정 호텔·질문·표 목록을 별도 JSON이나 Python 상수로 복제하지 않는다.
- dataset·field 설명은 live schema read-back을 권위 값으로 사용한다. 같은 field 이름이라도 dataset별 정의가 다르면 하나의 용어로 임의 병합하지 않고 물리 범위가 포함된 결정적 Glossary term으로 발행한다.
- serving lineage는 release SQL을 SQLGlot AST로 해석해 생성하며 정규식·파일명 추론·수기 edge 목록을 사용하지 않는다.
- 발행은 `--check` 사전검증, 최소권한 publish principal의 멱등 upsert, `--verify` 전체 live read-back 순서를 지킨다. 동일 dataset의 read-modify-write association은 순차 실행해 aspect 갱신 손실을 막는다.
- DataHub v1.7 read-back은 실제 API 권위 범위를 따른다. GlossaryTerm lifecycle과 컬럼별 term 연결은 Rest.li aspect에서 exact 검증하고, GraphQL은 dataset·term identity, native owner/domain, dataset-level term 집합을 교차검증한다. GraphQL이 반환하지 않는 field를 로컬 기본값이나 mock 응답으로 보충하지 않는다.
- publish principal은 metadata 수정에 필요한 권한만 가진 별도 service identity여야 한다. 사용자·그룹·정책 관리 권한이나 삭제 권한을 편의상 추가하지 않는다.
- runtime metric governance는 serving SQL AST와 `COMMENT ON`에서 비권위 DRAFT를 먼저 생성한다. 비율·통합매출·이벤트 효과·VOC처럼 업무 판단이 필요한 항목은 승인 주체가 grain·time·aggregation·reduction·entitlement를 확정하기 전까지 `REVIEW_REQUIRED`로 두며 DataHub runtime metadata에 발행하지 않는다.
- 합성 release의 업무 승인은 해당 생성 SQL·제약·검증식과 exact source digest에만 적용한다. 도메인별 세금 포함 방식, 합성 label, 구조적 0값처럼 실제 생성 계약이 다른 값을 하나의 업계 표준으로 미화하지 않는다. 발행은 읽기 전용 `--check`에서 확인한 target·predecessor checksum을 명시적 `--publish`에 다시 제시하고, 전체 live read-back이 일치한 뒤에만 runtime을 연다. 별도 조직의 2인 승인이나 규제 요건이 생기기 전에는 형식적인 자체 서명 절차를 추가하지 않는다.

## 인증·보안·외부 I/O

- production adapter는 DataHub·Trino·DB·model 실패를 mock 응답, demo fixture, 빈 성공값으로 바꾸지 않는다.
- fake, mock, stub, in-memory repository는 `tests/` 아래에서 명시적으로 주입한다. production module에 test token, test auth mode, 숨은 local fallback을 두지 않는다.
- 외부 HTTP는 async `httpx`와 명시적 timeout·취소·동일 origin 검증을 사용한다. `urlopen`, 동기 network I/O, event-loop 내부 blocking semaphore를 사용하지 않는다.
- 운영 model endpoint와 credential 전송 경로는 HTTPS, URL credential·query·fragment 금지, `trust_env=False`를 기본으로 한다. test의 `MockTransport`만 명시적 주입 경계로 허용한다.
- Trino runtime은 HTTPS, password authentication, CA 검증, 명시적 service principal, 최소 ACL을 요구한다. `/v1/info`는 liveness일 뿐 readiness 증거가 아니며 실제 principal의 terminal `SELECT 1`로 인증·query 권한을 확인한다.
- DataHub 운영 경계는 인증된 canonical token, 승인된 transport, native governance와 GraphQL capability 검증을 요구한다. 무인증 mutation이나 LAN 전체 포트 공개를 허용하지 않는다.
- secret, 원문 비밀번호, 불필요한 개인정보를 argv, URL, log, trace, 문서, commit에 넣지 않는다.
- repository 내부 `.env`를 운영 secret 저장소로 사용하지 않는다. 외부 absolute env/secret 경로를 요구하고 값은 process argument로 전달하지 않는다.
- source DB runtime 계정은 API가 실제 사용하는 table·operation만 허용한다. migration 계정과 runtime 계정을 분리한다.

## async·상태·영속성

- DB는 단일 async engine/sessionmaker 경계를 사용하고 transaction commit·rollback 소유자를 명확히 한다.
- event loop에서 동기 DB, filesystem, subprocess, HTTP 작업을 직접 실행하지 않는다. 필요한 local file I/O는 `asyncio.to_thread` 등 명시적 경계로 격리한다.
- idempotency, CAS, terminal-state transition, schedule race, retry count를 SQL WHERE와 transaction 경계에서 검증한다.
- navigation, artifact, model, PDF 요청은 generation 또는 cancellation으로 오래된 응답이 최신 선택을 덮지 못하게 한다.
- timeout·cancel·connection close 경로를 성공 경로와 같은 수준으로 검증한다.

## 보고서와 프런트엔드

- 보고서는 채팅 문장이나 화면 캡처를 데이터 근거로 복사하지 않는다. 승인된 artifact, view specification, analysis definition, query lineage를 연결한다.
- 확정 PDF와 HTML preview는 orientation, currency, row sampling, table layout 계약을 공유한다.
- A4 물리 페이지 경계와 내부 출력 overflow를 구분한다. 인쇄 root의 grid·sidebar layout을 명시적으로 격리한다.
- 큰 페이지 component는 list, lifecycle, draft history, artifact hydration, block rendering, drag-and-drop, document/print 책임으로 분리한다.
- memo는 단순 wrapper가 아니라 structural sharing과 안정적인 callback/selector로 실제 재렌더 범위를 줄여야 한다.
- browser storage 실패는 서버 저장 성공을 되돌리지 않는다. 경고 후 서버 snapshot을 적용하고 dirty/saving 상태를 일관되게 정리한다.

## 주석과 문서화

- 모든 production module은 파일 상단에서 그 파일의 권위 있는 입력, 소유 책임, 외부 경계를 한국어로 설명한다.
- 공개 class·function·hook·component·adapter·service에는 입력 제약, 반환 계약, 상태 변화, typed failure를 한국어 docstring/JSDoc/TSDoc으로 기록한다.
- 구현 한 줄을 번역하는 주석은 쓰지 않는다. 권한 필터, transaction/CAS, idempotency, checksum, pagination, timeout/cancel, AST policy, 외부 readback처럼 생략하면 불변식이 깨지는 이유를 가장 가까운 위치에 적는다.
- 같은 문장을 여러 API에 복사하지 않는다. 실제 owner scope, 정렬, limit, transition, side effect, 실패 조건을 함수별로 설명한다.
- 코드와 다른 주석은 결함이다. 동작 변경과 같은 patch에서 갱신한다.
- TODO는 모호한 희망사항으로 남기지 않는다. 현재 작업에서 해결하거나 구체적인 blocker·완료 조건·담당 경계를 적는다.
- `python scripts/check_code_documentation.py`가 일반 문구와 누락 문서를 거부해야 하며, checker를 피하기 위한 형식적 주석을 추가하지 않는다.

## migration·manifest·archive

- 배포된 migration은 checksum으로 보호되는 immutable 기록이다. 설명을 추가한다는 이유로 과거 migration을 수정하지 않는다. 새 변경은 새 revision에 둔다.
- 공개 schema·manifest의 고정 식별자는 호환성 계약이다. 고정 이유와 변경 절차를 문서화한다.
- 검증된 과거 release archive는 checksum을 보존하고 운영 compose·runtime import에서 분리한다.
- 현재 runtime이 참조하지 않는 historical fixture를 production 성공 근거로 인용하지 않는다.

## 검증과 증거

- 검증 순서는 정적 정책 → unit·contract → 실제 dependency integration → browser E2E → 실패·운영 시나리오 순으로 확장한다.
- mock·fixture 기반 결과는 `unit/contract` 증거로만 부른다. 실제 DataHub·Trino·DB·model·Browser가 같은 release로 연결되지 않은 결과에 `live`, `production`, `E2E PASS`를 붙이지 않는다.
- 테스트를 실행하지 않았으면 통과했다고 쓰지 않는다. skip, 환경 오류, 실행하지 못한 live 검증을 분리한다.
- 완료 전 다음 명령을 현재 tree에서 실행한다.

```text
python app/backend/scripts/export_openapi.py --check
python scripts/check_code_documentation.py
python scripts/lint_architectural_invariants.py
python scripts/audit_repository_integrity.py --write-report
python scripts/audit_repository_integrity.py
python -m compileall -q app/backend src infrastructure/database/datahub scripts evals tests
python -m pytest -p no:cacheprovider --basetemp <고유한 저장소 내부 경로> tests -q -ra
npm.cmd run test                  # app/frontend
npm.cmd run build                 # app/frontend, 고유한 임시 outDir 사용
git diff --check
```

- Compose root/full/split/semantic 조합을 실제 merge한 config로 검증한다.
- production 전체 파일을 inventory하고 질문 전용 JSON·고정 SQL·demo fallback·production test double·test auth·secret 경로·죽은 import를 검사한다.
- inventory와 무결성 검사가 통과한 상태에서만 `--write-report` 산출물을 갱신한다.
- 외부 dependency를 실행하지 못했으면 단위 검증과 운영 준비 완료를 구분해 보고한다.

## 파일과 임시 산출물 위생

- 대용량 raw log, cache, model weight, secret, pytest/browser 임시 산출물을 Git에 넣지 않는다.
- 임시 디렉터리는 고유 경로를 사용하고 작업 후 정확한 절대 경로를 검증해 제거한다.
- 사용자가 만든 파일을 임의로 정리하지 않는다. 삭제는 운영 참조·소유권·복구 가능성을 확인한 뒤 수행한다.
- 저장소 상위 폴더는 사용자가 명시한 범위에서만 정리한다.

## 완료 보고

최종 보고에는 다음을 구분한다.

- 실제로 완성된 동작과 현재 상태
- 주요 변경 파일과 책임 경계
- 실행한 검증과 정확한 결과
- skip·환경 제약·실행하지 못한 live 검증
- 외부 시스템이나 미배포 release 때문에 남은 위험
- 삭제된 secret 파일과 별도로 필요한 credential 회전 조치

컴퓨터 종료처럼 되돌리기 어려운 후속 동작은 모든 필수 검증과 독립 감사에서 차단 항목이 없을 때만 실행한다.
