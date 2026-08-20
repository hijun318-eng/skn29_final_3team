# Answervice 제품 요구사항 정의서

## 1. 문서 계약

| 항목 | 내용 |
|---|---|
| 기준일 | 2026-08-16 KST |
| 제품 단계 | 동적 governed catalog 기반 P0 Vertical Slice |
| 요구사항 기준 | 이 문서의 P0 인수 조건 |
| 범위 기준 | [`00_기획서.md`](00_기획서.md) |
| 사용자 흐름 | [`02_유저플로우.md`](02_유저플로우.md) |
| 기술 구조 | [`03_아키텍처.md`](03_아키텍처.md) |

이 문서는 만들어야 할 제품 계약과 현재 구현 판정을 함께 보여 주되 둘을 같은 것으로 취급하지 않는다. 코드 존재, 단위 테스트 통과, 과거 시연 성공은 요구사항 완료를 뜻하지 않는다.

## 2. 상태와 증거

### 상태

| 상태 | 의미 |
|---|---|
| `NOT_STARTED` | 현재 릴리스 후보에서 구현 또는 검증을 시작하지 않음 |
| `PARTIAL` | 일부 구현은 확인됐지만 인수 조건을 충족하지 못함 |
| `BLOCKED` | 선행 결함 또는 외부 조건 때문에 검증을 진행할 수 없음 |
| `READY_TO_VERIFY` | 코드 경로는 있으나 요구 수준의 실제 증거가 없음 |
| `VERIFIED` | 같은 릴리스 후보와 고정된 버전 묶음에서 인수 조건을 재현함 |

### 증거 수준

| 수준 | 증거 | 사용할 수 있는 판정 |
|---|---|---|
| L0 | 정적 검사, 문서, fixture 결과 | 설계·형식 확인 |
| L1 | unit·contract test, 명시적 test double | 내부 계약 회귀 확인 |
| L2 | 실제 단일 의존성 통합 테스트 | 의존성별 통합 확인 |
| L3 | 실제 브라우저→HTTP→Backend→DataHub·Trino→Source DB→App DB | 사용자 기능 검증 |
| L4 | L3 + 거부·장애·취소·재시작·rollback·보안 검증 | 운영·보안 인수 |

P0 사용자 기능은 최소 L3, 보안·복구 요구는 L4가 있어야 `VERIFIED`다. PNG 한 장이나 test-double 기반 검증은 L3가 아니다.

### 릴리스 증거 묶음

한 번의 P0 판정에는 다음을 모두 고정한다.

- 모든 항목을 묶는 단일 `product_release_id`
- Git commit SHA와 dirty worktree 여부
- V4.1 archive SHA-256, `schema_version`, `base_seed`, 적용 migration checksum
- 실제 적재 row count·validator·replay 결과와 Trino view checksum
- DataHub environment, Glossary release/checksum, Term·Asset URN
- semantic/rule/context/policy/prompt/model 버전과 Docker image digest
- 테스트 명령·시각·환경·결과 원문
- 브라우저 network request, HTTP response, `request_id`, `analysis_run_id`, Trino `query_id`
- `conversation_id`, `turn_id`, `reply_to_turn_id`, Turn routing 결정과 참조한 `artifact_id`·presentation checksum
- App DB의 request·trace·artifact·report run과 결과 checksum
- 실패 사례의 오류 코드와 실제 종료 상태
- Golden E2E의 `cached=false`; cache hit은 별도 재실행 일치성 test로 판정

다른 데이터 릴리스나 다른 commit의 성공 결과를 섞어 하나의 `VERIFIED` 판정을 만들지 않는다.

## 3. P0 사용자와 권한

### P0 인수 환경

P0의 인수 대상은 **단일 호스트·통제된 네트워크의 release candidate**다. 외부 고객 운영, 기업 IAM/SSO, 고가용성은 P0 범위가 아니지만 브라우저 로그인, 서버 권한, App→Trino service identity, Source DB read-only 최소 권한은 실제 경로로 검증한다. 개발·운영의 실제 Trino 연결은 HTTPS, password 인증, CA 검증과 service principal 없이 시작하지 않으며, 단위 테스트만 외부 연결 없는 `MockTransport`를 명시적으로 주입할 수 있다.

| 역할 | P0 권한 | 제외 |
|---|---|---|
| `analyst` | 허용된 자연어 분석, 본인 Analysis 저장·재실행, Report 초안 작성·승인 요청 | Report 승인·공개, 권한 밖 원문·개인정보 조회 |
| `report_admin` | 승인 큐 조회, 승인·반려, 승인된 버전 수동 실행, Run 이력 조회 | 임의 자연어 분석과 데이터 권한 우회 |
| `platform_admin` | 통제된 단일 호스트에서 현재 애플리케이션 Capability 전체를 검증 | DataHub publish, Trino setup, Source DB 관리와 사용자별 객체 권한 우회 |
| 사업책임자 | P0에서는 승인된 결과·보고서의 수혜자 | 별도 로그인 역할과 직접 질의 UI |
| 데이터 거버넌스 담당자 | DataHub에서 Term·Domain·Owner·승인·관계를 관리 | 애플리케이션 내부 관리 UI |

사업책임자 직접 질의를 발표하려면 별도 역할·권한·화면을 구현하고 이 문서를 변경해야 한다. 현재 P0에서는 `analyst`가 사업 질문을 실행하고 사업책임자가 검증된 결과를 소비한다. `platform_admin` 권한은 사용자명 분기가 아니라 서버 Role→Capability 정책으로만 부여하며, 보고서 재실행의 effective subject와 App의 read-only service identity를 바꾸지 않는다.

## 4. P0 지원 질문 계약

P0는 다음 조합만 지원한다. 정확한 Metric ID·계산식·Gold 값은 V4.1 결함 수정과 런타임 검증 후 승인한다.

| 항목 | P0 계약 |
|---|---|
| 기간 | `2024-01-01` 이상 `2026-01-01` 미만의 명시적 절대 기간, KST, `[start,end)` |
| 분석 유형 | 기간 비교, 호텔별 비교, 승인된 Metric의 구성 영역 비교 |
| 대표 경로 | `hotel_operations_monthly` 기반 객실·식음·연회·유료시설·통합 운영매출 비교 |
| 교차 검증 경로 | PMS·POS·CRM의 거래시점 유효 회원등급 기반 매출 비교 |
| 결과 표현 | 관측된 차이, 구성 영역별 기여, 합성 기준선과의 차이 |
| 금지 표현 | 검증되지 않은 인과관계, 미래 예측, 임의 Metric·JOIN 생성 |
| 대화 범위 | 같은 사용자가 소유한 하나의 선형 Conversation 안에서 승인된 Metric·기간·호텔 filter·dimension의 제한된 변경, 같은 대화의 최대 두 Analysis Turn 비교, 표현 전환과 Report 담기 |
| 대화에서 제외 | 다른 Conversation의 암묵 참조, 임의 과거 Turn 분기·병합, 장기 사용자 기억, raw transcript 전체를 실행 근거로 사용하는 방식 |
| 상대 기간 | `이번 달/지난 달`은 Conversation의 immutable `wall_clock_anchor`(`WALL_CLOCK`), `그 전 달/다음 달`은 명시한 `source_turn_id`의 절대 기간(`SOURCE_PERIOD`)을 기준으로 해석한다. 매 Turn에 base kind·base ID/date·KST·절대 `[start,end)`를 저장·표시하며 데이터 최신월로 조용히 바꾸지 않는다. |
| 데이터 가용 범위 | release/Asset별 `data_available_from`, `data_available_through` watermark를 metadata read-back으로 고정한다. 이는 사용자 시간 의미의 `wall_clock_anchor`와 별도이며 서로 대체하지 않는다. |

“이번 달”처럼 데이터 범위를 벗어나거나 기준시점이 불명확한 질문은 빈 성공 결과를 만들지 않는다. `OUT_OF_DATA_RANGE`를 반환하거나 절대 기간을 다시 묻는다.

현재 고정 후보 데이터에서 P0의 `WALL_CLOCK` 완료선은 표현을 정확히 해석하고 실제 current-clock 범위 초과를 L3에서 안전 차단하는 데까지다. wall-clock 상대월의 **성공 조회**는 승인 데이터 watermark가 해당 월을 포함하는 rolling release에서 별도 Gate로 올린다. P0 성공 멀티턴은 절대 월과 `SOURCE_PERIOD`로 검증한다.

상대기간 기준은 모델이나 client header의 자유 값이 아니다. Production `WALL_CLOCK`은 Backend의 신뢰된 KST clock에서 Conversation 생성 시 `wall_clock_anchor`로 고정한다. 일반 사용자 `X-As-Of` 같은 client override는 무시하거나 거부하고, 과거 clock은 production과 분리된 test profile에서만 봉인한다. `SOURCE_PERIOD`는 하나로 확정된 `source_turn_id`와 그 Turn의 절대 `[start,end)`를 고정한다. `지난/저번 달`은 WALL_CLOCK, `그 전 달`은 SOURCE_PERIOD다. `wall_clock_anchor` 변경은 기존 Conversation 안에서 허용하지 않고 새 Conversation으로만 시작한다.

### P0 제한 멀티턴 계약

P0 멀티턴은 각 Analysis Run을 이어서 수정하는 Agent memory가 아니다. **각 Analysis Run은 한 질문의 권한·Context·SQL·조회·결과를 원자적으로 끝내고, Conversation/Turn 계층은 확정된 논리 조건과 결과 참조만 다음 요청에 전달한다.** 과거 Run의 Approved Context·권한 snapshot·SQL을 현재 권한처럼 재사용하지 않는다.

| Turn routing | 판정과 실행 계약 |
|---|---|
| `ANALYSIS` | Metric·기간·filter·dimension·grain·비교 대상 중 하나라도 데이터 의미를 바꾸는 **완전하게 resolved된 요청**은 새 `analysis_run_id`를 만들고 현재 권한·Glossary·Rule·Binding으로 APP-G1→G2→Trino→G3를 다시 통과한다. preflight에서 막힌 Analysis Turn은 Run이 0건이다. |
| `PRESENTATION` | 현재 권한으로 읽을 수 있는 기존 Safe Artifact의 보유 column·row만 표·허용 chart로 다시 표현한다. 새 Analysis Run·Trino query를 만들지 않고 immutable presentation identity와 spec checksum을 남긴다. 필요한 grain·field가 Artifact에 없으면 표현 Turn으로 값을 만들지 않고 `ANALYSIS`로 명시 전환하거나 확인을 요청한다. |
| `REPORT_ACTION` | 사용자가 선택한 Artifact와 presentation identity를 본인 Report 초안 block에 연결한다. 초안 담기 자체는 query를 실행하지 않으며, 승인 Report의 수동 실행은 RPT-003대로 block마다 새 Analysis Run을 만든다. 대상 초안이 여러 개면 자동 선택하지 않는다. |

자유 텍스트 routing 결과는 비신뢰 typed candidate다. 서버는 현재 Conversation head, 명시적 `reply_to_turn_id`, source Artifact schema, 역할과 객체 소유권으로 다시 검증한다. `다른 그래프로`는 현재 view와 Artifact schema에 맞는 고정 allowlist의 다음 표현을 선택하고 종류를 응답에 명시한다. 참조 대상이 둘 이상이거나 “그거”의 source를 결정할 수 없으면 `BLOCKED + NEEDS_CLARIFICATION`으로 끝내며 query를 실행하지 않는다.

### P0 Golden Dialogue

| ID | 사용자 대화 | 필수 관측 결과 |
|---|---|---|
| `GD-01` | `2025년 8월 인식 객실 매출을 보여줘` → `그 전 달은?` → `두 달 비교해줘` | 같은 `conversation_id`에서 세 Turn은 서로 다른 immutable Analysis Run이다. 둘째 Turn은 승인된 Metric·filter·dimension만 상속하고 `2025-07-01` 이상 `2025-08-01` 미만으로 다시 저장한다. 셋째 Turn은 같은 대화의 호환 가능한 두 Turn만 참조해 새 비교 Run을 만들며, 모든 Run이 현재 권한과 같은 `product_release_id`에서 Gate를 다시 통과한다. |
| `GD-02` | `2025년 7월 인식 객실 매출을 보여줘` → `그래프로 띄워줘` → `다른 그래프로 띄워줘` → `표로도 띄워줘` → `현재 그래프와 표를 보고서에 담아줘` | Gold manifest가 첫 Artifact의 승인 day grain·value role과 현재 renderer 계약의 표현 순서 `line → bar(세로) → table`을 봉인한다. 이후 세 표현 Turn은 같은 `artifact_id`·`query_id`를 재사용하고 Trino 호출은 0건이며, 마지막 Turn은 현재 그래프와 표를 순서대로 두 block에 연결한다. 실제 Artifact가 봉인 schema와 다르면 Gate 실패다. |
| `GD-03` | 실제 current clock에서 `이번 달 인식 객실 매출을 보여줘` | 현재 월이 승인 데이터 범위 밖이면 `ANALYSIS` Turn은 `BLOCKED + OUT_OF_DATA_RANGE`, `analysis_run_id`·query·Artifact는 모두 0건이다. 가용 절대 기간을 보여 주고 사용자가 월을 선택한 새 Turn부터 Run을 만든다. 최신월 자동 치환과 client clock spoof를 금지하며 fixed-clock test를 current-clock E2E로 가장하지 않는다. |

세 Dialogue 모두 중간 새로고침 뒤 서버 이력으로 복원하고, 동일 idempotency 재전송·stale head·타 사용자 Turn ID·권한 회수·릴리스 변경 negative case까지 통과해야 한다. 단위 test나 대화 transcript screenshot만으로 합격하지 않는다.

`객실 매출`은 현재 `인식 객실 매출`과 `숙박일 배분 객실 매출`이 공유하는 별칭이다. 사용자가 시간 귀속 기준을 말하지 않으면 두 정의를 보여 주고 선택받으며, 선택 전에는 Analysis Run·query를 만들지 않는다. LLM이나 alias 순서로 기본 Metric을 정하지 않는다.

정렬·비교·0분모·null·rounding 의미는 선택된 Metric의 runtime governance rule에서 가져온다. 애플리케이션이나 평가 prompt가 특정 통화·기간·domain 순서를 기본값으로 보정하지 않으며, 필요한 규칙이 없으면 계산 전에 차단한다.

데이터 reconciliation과 제품 held-out 평가는 섞지 않는다. reconciliation은 catalog에 게시할 물리 schema·grain·fan-out·checksum을 결정론적으로 검증한다. held-out 평가는 runtime Context와 독립된 평가 저장소에서 semantic 구조·AST·결과 허용 오차를 봉인하되, 그 질문·정답 SQL을 production prompt·JSON·fallback에 복사하지 않는다. `P0-GOLD`는 DATA-001~004와 GOV-001~008의 **candidate readiness**가 끝난 뒤 GOV-009 활성화 전에 승인한다.

## 5. P0 기능 요구사항

### DATA — Runtime catalog release 전환

| ID | 요구사항과 인수 조건 | 상태 |
|---|---|---|
| DATA-001 | release authoring이 Source DB와 Trino에서 전체 물리 identity·column type·ordinal·nullability를 발견하고, 입력 scope 누락·중복·drift를 fail-closed 한다. | `READY_TO_VERIFY` |
| DATA-002 | 읽기 전용 check의 predecessor·target catalog hash를 명시적 publish가 다시 요구하며, publish 전후 DataHub native governance·custom properties·semantic checksum을 전체 read-back 한다. 부분 publish는 active release가 되지 않는다. | `READY_TO_VERIFY` |
| DATA-003 | runtime은 DataHub release manifest와 live dataset/term/governance 내용을 다시 hash하고 Trino `information_schema` point lookup과 일치할 때만 Context를 만든다. 특정 view 수나 FQN 목록은 코드에 두지 않는다. | `READY_TO_VERIFY` |
| DATA-004 | semantic producer가 모든 active Dataset의 일반 metadata에서 embedding을 만들고 GMS read-back과 active Elasticsearch document fingerprint를 연결해 검증한다. | `READY_TO_VERIFY` |
| DATA-005 | 기존 저장 Analysis Definition·승인 Report Version은 새 catalog에 조용히 재해석하지 않고 version mismatch로 차단하거나 명시적 새 version을 만든다. | `PARTIAL` |
| DATA-006 | code/image·data·semantic·prompt/model/policy·migration을 한 `product_release_id`로 고정한 candidate에 대해 canary와 rollback rehearsal을 수행한 뒤에만 활성 pointer를 전환한다. | `NOT_STARTED` |

현재 구현은 authoring·publish·read-back·runtime fail-close 경계를 갖지만 live DataHub catalog가 기대 scope보다 불완전하고 semanticContent가 없어 positive 전환 증거는 없다.

### GOV — DataHub 중심 의미 거버넌스

| ID | 요구사항과 인수 조건 | 상태 |
|---|---|---|
| GOV-001 | P0 Metric의 이름·별칭·정의·단위·Domain·Owner·승인 상태를 DataHub Business Glossary Term으로 등록한다. | `PARTIAL` |
| GOV-002 | 각 Term과 active Dataset·Column 사이의 관련 자산 관계가 DataHub에 존재하고 역조회된다. | `NOT_STARTED` |
| GOV-003 | Node 1이 로컬 후보 목록만 고르는 것이 아니라 DataHub에서 승인된 Term을 발견·조회하고 관련 Asset을 얻는다. | `PARTIAL` |
| GOV-004 | 런타임은 삭제·미승인 Term, 관계 단절, schema drift, alias 충돌, unit 불일치를 APP-G1 전에 차단한다. | `PARTIAL` |
| GOV-005 | 실행 계산식·filter·join·time·identity·permission 계약은 Term URN과 Glossary version에 연결된 버전 Rule Layer에서 읽는다. | `PARTIAL` |
| GOV-006 | 로컬 JSON은 공개 schema·version manifest·설정·test fixture로만 사용한다. runtime metadata는 bounded in-memory snapshot만 허용하며 refresh 실패나 출처 불일치는 `METADATA_UNAVAILABLE`로 fail-closed 한다. | `READY_TO_VERIFY` |
| GOV-007 | Context·trace·결과 근거에 Term URN, Glossary checksum, Dataset/Column URN, Rule version을 보존하고 화면에서 확인할 수 있다. | `PARTIAL` |
| GOV-008 | **Candidate readiness:** Glossary Term·관계, versioned Rule·Binding·policy checksum을 하나의 immutable `semantic_release_id` manifest로 묶는다. 후보는 staging 또는 release별 shadow/versioned URN 집합에 out-of-place publish하고 전부 read-back하기 전에는 runtime에 노출하지 않는다. DataHub 직접 변경은 RBAC로 제한하고 runtime은 manifest가 허용한 immutable URN만 읽는다. candidate canary는 전역 pointer가 아니라 명시적 `product_release_id`로 조회한다. policy checksum은 정책 버전이고 사용자별 현재 entitlement는 매 Run의 별도 permission snapshot으로 고정한다. | `NOT_STARTED` |
| GOV-009 | **Activation:** pre-cutover Gate 승인 뒤 data·semantic·App 기본값을 같은 `product_release_id`로 바꾸며 이때만 active semantic pointer를 전환한다. readiness·Golden smoke 실패 시 이전 pointer와 cache namespace를 복원하고, 부분 publish나 서로 다른 릴리스 조합이 runtime에서 보이지 않음을 L4 receipt로 증명한다. | `NOT_STARTED` |

현재 source는 DataHub 전체 pagination snapshot, dataset semantic search, native Domain·Owner·Lifecycle, Term/Column 관계와 structured runtime properties를 읽고 content-derived checksum을 재구성한다. 질문별 로컬 후보 목록·키워드 ranking·static Context JSON은 제거됐다. 다만 실행 중인 live stack은 semantic overlay가 배포되지 않았고 release scope도 불완전하므로 이 구조를 Glossary 연동 완료나 production E2E 성공으로 발표하지 않는다.

### AUTH — 인증·인가

| ID | 요구사항과 인수 조건 | 상태 |
|---|---|---|
| AUTH-001 | 안전한 password hash와 만료 가능한 server-side session 또는 동등한 방식으로 로그인·로그아웃·세션 복원을 처리한다. cookie 보안 속성을 검증한다. | `READY_TO_VERIFY` |
| AUTH-002 | 모든 P0 API에서 역할과 객체 소유권을 서버가 검사하며 URL·body 변조로 타인의 Conversation·Turn·Analysis·Artifact·View·Report에 접근할 수 없다. 현재 기존 Analysis·Report 일부 경로에는 검사가 있으나 Conversation·Turn API가 없고 전체 객체 ID 주입 negative test도 완료되지 않았다. | `PARTIAL` |
| AUTH-003 | DataHub asset, Rule, Trino 조회, 결과 열·행에 같은 권한 스냅샷을 적용하고 trace에 policy version을 기록한다. | `PARTIAL` |
| AUTH-004 | 권한 거부·마스킹·세션 만료·로그인 반복 공격의 L4 테스트를 통과한다. | `NOT_STARTED` |

### ANL — 질문부터 결과까지

| ID | 요구사항과 인수 조건 | 상태 |
|---|---|---|
| ANL-001 | Turn-level understanding preflight가 완전한 typed request를 하나로 확정한 뒤에만 한 개의 새 `analysis_run_id`를 만든다. 각 Run은 terminal 상태와 immutable 입력·권한·release evidence를 가진 원자적 single-turn 실행이며 후속 질문이 기존 Run을 덮어쓰지 않는다. 현재 단일 Run 경로는 있으나 preflight/Run 경계와 통합 release·permission 고정이 끝나지 않았다. | `PARTIAL` |
| ANL-002 | Metric·기간·호텔 등 필수 정보가 모호하면 현재 principal이 볼 수 있는 metadata 후보만 제시하고 확인 전에는 Analysis Run·Node 2·Trino를 만들거나 호출하지 않는다. preflight의 coarse/object/metadata visibility와 Run의 field/row execution permission snapshot을 분리해 권한 없는 Term·Asset 이름·정의도 누출하지 않는다. 현재 pipeline 내부 차단은 있으나 Turn-level no-Run preflight 계약은 없다. | `PARTIAL` |
| ANL-003 | 확인 응답은 원 요청과 연결된 새 실행을 만들며 선택하지 않은 해석을 trace에서 제외한다. 현재 Frontend는 선택 문구를 원 질문에 이어 붙여 독립 `/analysis` 요청으로 보내고 원 request/Turn linkage가 없다. | `PARTIAL` |
| ANL-004 | Approved Context에는 Term, Asset, Field, Rule, absolute time range, Backend-owned `wall_clock_anchor`, 별도 data availability watermark, permission snapshot, version이 포함되고 APP-G1을 통과한다. wall clock과 data cutoff를 같은 `as_of` 값으로 혼용하지 않는다. | `PARTIAL` |
| ANL-005 | Node 2는 Approved Context 밖의 table·column·join·metric을 사용하지 않으며 parameterized read-only SQL만 만든다. | `READY_TO_VERIFY` |
| ANL-006 | APP-G2가 SQL AST, allowlist, scan/result/timeout 상한을 검사한다. 허용 가능한 오류는 한 번만 제한 수정하고 재실패 시 종료한다. | `READY_TO_VERIFY` |
| ANL-007 | 실제 Trino가 V4.1 view를 조회하고 query ID·통계·실행 시간을 trace에 남긴다. write·DDL·다중 statement는 0건이다. | `BLOCKED` |
| ANL-008 | APP-G3는 결과 schema·행수·금액 범위·노출 정책·근거 완전성을 검사한다. APP-G3는 의미 정확성을 보증한다고 표현하지 않는다. | `READY_TO_VERIFY` |
| ANL-009 | 표·차트·요약·사용한 Metric·기간·출처·query ID·경고가 같은 server artifact에서 렌더링된다. 하드코딩 KPI가 없다. | `READY_TO_VERIFY` |
| ANL-010 | 대표 경로와 회원 교차 검증 경로가 승인 Gold Result와 허용 오차 안에서 일치한다. | `BLOCKED` |
| ANL-011 | sealed utterance manifest가 존댓말/반말, 조사·띄어쓰기, 어순, 경미 오탈자, 승인 별칭, 한/영 혼용, 후속 지시어와 의미 contrast를 포함한다. 같은 의미는 같은 resolved request hash/clarification으로 수렴한다. 숫자·날짜·단위·부정·비교 방향·`이상/초과`·호텔/등급·대체/추가 token은 보존하고, 이를 바꿀 수 있는 교정은 확인한다. unsupported intent·권한 우회·prompt injection을 허용 질문으로 변조하지 않는다. calibration 뒤 threshold를 봉인한다. 평가 설계는 [멀티턴·발화 이해 BP와 벤치마크 적용](../reference/멀티턴_발화이해_BP_벤치마크.md)을 따라 CheckList `MFT/INV/DIR/NEG`, BFCL 방식의 per-Turn backend state/path oracle, KLUE 방식의 joint slot exact match를 적용한다. 공개 benchmark·leaderboard 점수 자체는 제품 Gate 증거가 아니다. 현재 공백 정리·alias substring parser와 NOT_RUN eval은 증거가 아니다. | `NOT_STARTED` |

### CONV — 제한된 멀티턴 Conversation·Turn

| ID | 요구사항과 인수 조건 | 상태 |
|---|---|---|
| `CONV-001` | 사용자는 본인 Conversation을 생성·조회·재개·보관할 수 있고 새로고침 뒤 서버 이력이 복원된다. Conversation은 owner, 상태, head Turn, `product_release_id`를 가지며 타인 ID로 읽거나 이어 쓸 수 없다. `ARCHIVED`는 read-only이고 모든 mutation/lease 예약은 Turn·Run 없이 `409 CONVERSATION_ARCHIVED`; P0 unarchive는 지원하지 않는다. 현재 DB 골격은 있으나 사용자 API·head·실제 request 연결이 없다. | `PARTIAL` |
| `CONV-002` | 실행 중에는 idempotent `turn_command/analysis_request`, Conversation active lease와 resolved `ANALYSIS`의 Run 생성·상태, attempt·heartbeat·외부 query 제출 증거만 상태 전이하며 저장한다. immutable Turn, Conversation head, focus, ViewSpec, Draft block/revision 같은 사용자 가시 domain mutation은 terminal commit 전까지 만들거나 바꾸지 않는다. 완료 시 Run terminal 상태·결과 Artifact 또는 ViewSpec/focus·Draft block/revision, command terminal화, immutable terminal Turn, Conversation head 전진, lease 해제를 **같은 transaction**으로 한 번 commit한다. UI는 실행 중 command/request와 선택적 Run에 재연결한다. Turn은 reply/source/clarifies IDs, routing, terminal status와 결과 참조를 가지며 owner 원문은 별도 암호화 store, audit은 redacted utterance·resolved request·hash로 제한한다. | `NOT_STARTED` |
| `CONV-003` | 후속 해석은 raw transcript가 아니라 승인된 논리 slot과 ordered `source_turn_ids` 최대 두 개만 사용한다. 사용자 slot patch는 필드별 `INHERIT/SET/REMOVE`를 구분하고 `USER_REQUESTED_FILTER`만 상속한다. `POLICY_REQUIRED_FILTER`·permission constraint는 상속·삭제하지 않고 현재 entitlement/Rule에서 매 Analysis Run 다시 만든다. 변경·상속 field의 source Turn과 provenance를 저장·표시하고 모호하면 실행 전 확인한다. | `NOT_STARTED` |
| `CONV-004` | 상대기간은 `WALL_CLOCK`(Backend-owned `wall_clock_anchor`)과 `SOURCE_PERIOD`(`source_turn_id`의 절대 기간)를 구분해 `[start,end)`로 저장한다. client clock spoof를 거부하고 월 경계·재로그인·재시작으로 기존 해석을 바꾸지 않는다. wall clock 기준 변경은 새 Conversation만 허용한다. 인증 Context가 client `X-As-Of`를 입력으로 받지 않고 Backend KST 날짜를 사용하며 Frontend 공통 header도 제거된 경계와 회귀 test는 존재한다. 그러나 Conversation anchor 저장·두 relative base resolver·GD-03 no-Run L3는 아직 없다. 현재 후보는 GD-01 SOURCE_PERIOD 성공과 GD-03 실제 current-clock 범위 초과를 L3로, WALL_CLOCK 성공 resolver는 production에서 비활성인 고정 clock integration으로 검증한다. | `PARTIAL` |
| `CONV-005` | 서버는 Turn을 `ANALYSIS`·`PRESENTATION`·`REPORT_ACTION` 중 하나로 typed routing한다. 명확화는 원 route의 `BLOCKED + NEEDS_CLARIFICATION` 결과다. 분류 model이 있더라도 권한, Artifact schema, 허용 chart, query 필요 여부와 Report 대상은 결정론적 validator가 최종 판정한다. 현재 runtime에는 이 typed Turn router가 없고 GENERAL/TEMPLATE 분석 routing만 있다. | `NOT_STARTED` |
| `CONV-006` | 표현 전환은 같은 Safe Artifact에서만 immutable presentation spec을 만들고 `artifact_id`, 원 `query_id`, view type, field mapping, sort/format, checksum을 보존한다. 성공 `PRESENTATION`만 current View와 ordered visible views를 갱신하며 Report에 담은 표·chart는 선택 presentation과 원 Definition lineage를 고정한다. | `PARTIAL` |
| `CONV-007` | 매 Turn에서 Conversation·reply/source Turn·Artifact·Report draft의 객체 권한을 검사한다. 새 Analysis Run은 현재 entitlement에서 permission snapshot과 `POLICY_REQUIRED_FILTER`를 다시 만들며 과거 정책 필터를 상속하지 않는다. 권한 회수 뒤의 서버 fetch·표현·Report mutation은 차단하고 Frontend는 401/403·재연결 시 메모리/로컬 cache를 purge한다. 이미 렌더된 픽셀이나 사용자가 외부 저장한 파일까지 회수한다고 주장하지 않는다. | `PARTIAL` |
| `CONV-008` | Conversation 생성 시 서버가 하나의 `product_release_id`를 고정하고 모든 Turn·Analysis Run·Artifact·presentation·Report lineage가 이를 상속한다. active pointer 변경으로 기존 대화를 다른 data·semantic·policy 조합에 조용히 재해석하지 않으며, 고정 릴리스가 실행 불가하면 `409 RESOURCE_CONFLICT`로 새 Conversation 전환을 안내한다. | `NOT_STARTED` |
| `CONV-009` | mutation은 먼저 `(owner, conversation_id, idempotency_key)`를 조회한다. 같은 key·같은 canonical hash면 head가 이미 전진했어도 기존 command/Turn을 반환하고, 같은 key·다른 hash면 `409 IDEMPOTENCY_CONFLICT`다. 새 key일 때만 `expected_head_turn_id` CAS와 active lease를 검사해 command를 예약한다. terminal Turn+head commit은 한 번뿐이며 report hash에는 `report_as_of`를 포함한다. 현재 저장 Analysis·Report의 일부 멱등은 이 순서·hash 충돌을 완성하지 않았다. | `PARTIAL` |
| `CONV-010` | data focus는 같은 owner·Conversation·release의 `SUCCEEDED` Analysis Turn과 APP-G3 Safe Artifact만 갱신한다. `PARTIAL`은 P0 implicit focus에서 제외한다. 성공 Presentation은 View focus만 갱신하고 Report Action은 data/View focus를 바꾸지 않는다. `BLOCKED/FAILED/CANCELLED` Turn은 기존 focus를 보존하며 source Turn은 선행 eligible Analysis만 허용한다. | `NOT_STARTED` |

P0는 Conversation당 하나의 선형 head와 하나의 active command lease만 지원한다. 임의 과거 Turn에서의 branch·merge, Conversation 간 기억, vector memory, 전체 transcript 재주입과 자율 계획은 P1/P2 별도 요구다.

### FAIL — 실패·취소·부분 성공

| ID | 요구사항과 인수 조건 | 상태 |
|---|---|---|
| FAIL-001 | `turn_status`와 Analysis `run_status`를 분리한다. 모든 저장 Turn은 terminal `SUCCEEDED/BLOCKED/PARTIAL/FAILED/CANCELLED`와 `turn_reason_code`를 가지며 Analysis Run이 없는 표현·보고서·명확화 결과도 여기에 기록한다. `run_status`는 실제 Analysis Run에만 `RECEIVED`, `ROUTED`, terminal `SUCCEEDED/BLOCKED/PARTIAL/FAILED/CANCELLED`를 사용한다. OpenAPI·Frontend·DB·trace가 둘을 혼동하지 않는다. | `PARTIAL` |
| FAIL-002 | 사용자 취소가 backend task뿐 아니라 실행 중인 Trino query까지 전파되고 최종 상태가 `CANCELLED`가 된다. | `READY_TO_VERIFY` |
| FAIL-003 | zero rows는 성공 차트가 아니라 조회 조건·기간·출처와 함께 `BLOCKED + EMPTY_RESULT`로 표시한다. | `READY_TO_VERIFY` |
| FAIL-004 | 필수 source/block 실패로 합계 의미가 깨지면 `FAILED`; 선택적 block만 실패하고 핵심 의미가 유지될 때만 `PARTIAL + PARTIAL_FAILURE`다. | `PARTIAL` |
| FAIL-005 | dependency readiness가 불완전하거나 cache가 stale이면 fake·old JSON·last success로 대체하지 않는다. | `NOT_STARTED` |
| FAIL-006 | 각 command/Analysis Run은 lease·heartbeat·attempt와 외부 query 제출 상태를 저장하고 Trino client tag에 `request_id/run_id/attempt`를 넣는다. crash 후 reconciler는 query ID가 없더라도 service principal query listing+tag로 고아 query를 찾아 취소하며 server-side timeout으로 상한을 둔다. 결과 commit이 불명확하면 Run을 `FAILED + ORPHANED_EXECUTION/RESULT_COMMIT_UNKNOWN`으로 닫고 같은 recovery transaction에서 command terminal화·FAILED Turn 1회 commit·head advance·lease 해제를 멱등 수행한다. 자동 재조회와 지난 Artifact 대체는 금지한다. | `NOT_STARTED` |

상태와 원인 코드는 다음처럼 분리한다. 아래 분석 결과는 `run_status/reason_code`, Run이 없는 Turn은 같은 terminal 의미의 `turn_status/turn_reason_code`에 기록한다. 현재 enum에 없는 값은 P0 API 계약에 추가하고 OpenAPI drift 검사를 통과해야 한다.

| 상황 | terminal `run_status` | 대표 `reason_code` |
|---|---|---|
| 정상 완료 | `SUCCEEDED` | 없음 |
| 명확화 필요·기간 밖·권한 거부·metadata/schema 전제 불충족·SQL 정책 거부·0행 | `BLOCKED` | `NEEDS_CLARIFICATION`, `OUT_OF_DATA_RANGE`, `ACCESS_DENIED`, `METADATA_UNAVAILABLE`, `SCHEMA_DRIFT`, `SQL_POLICY_BLOCKED`, `EMPTY_RESULT` |
| 선택 block만 실패하고 핵심 의미 유지 | `PARTIAL` | `PARTIAL_FAILURE` |
| source/model/dependency timeout·내부 오류·필수 block 실패 | `FAILED` | `QUERY_TIMEOUT`, `MODEL_TIMEOUT`, `DEPENDENCY_UNAVAILABLE`, `INTERNAL_ERROR` |
| 사용자 취소 | `CANCELLED` | `REQUEST_CANCELLED` |
| 모호한 후속 참조 | `BLOCKED` | `NEEDS_CLARIFICATION` |
| 지원 범위 밖 의도 | `BLOCKED` | `UNSUPPORTED_INTENT` |

Turn을 commit하기 전의 precondition 실패는 위 `run_status` 표에 넣지 않는다.

| 상황 | HTTP 결과 | Turn·Run |
|---|---|---|
| 같은 Conversation에 미완료 head-changing command | `409 CONVERSATION_BUSY` | 새 Turn·Run·View·Report mutation 없음 |
| `expected_head_turn_id` 불일치 | `409 CONVERSATION_CONFLICT` | 새 Turn·Run 없음 |
| 같은 idempotency key와 다른 request hash | `409 IDEMPOTENCY_CONFLICT` | 새 Turn·Run 없음 |
| Conversation에 고정한 release가 더 이상 실행 불가 | `409 RESOURCE_CONFLICT` | 새 Turn·Run 없음 |
| 보관된 Conversation mutation | `409 CONVERSATION_ARCHIVED` | 새 Turn·Run 없음 |
| stale `expected_draft_revision` | `409 REPORT_DRAFT_CONFLICT` | Report block·revision 변경 없음 |

### SAVE·REPORT — 저장·재실행·보고서

| ID | 요구사항과 인수 조건 | 상태 |
|---|---|---|
| SAVE-001 | Analysis Definition, Run, Result/Artifact를 분리하고 질문·parameter schema·version·checksum을 보존한다. | `READY_TO_VERIFY` |
| SAVE-002 | 저장 분석 재실행은 현재 권한·Glossary·Rule·Binding을 다시 검증하고 새 Run·query ID를 만든다. 과거 결과를 현재 결과처럼 복사하지 않는다. | `READY_TO_VERIFY` |
| SAVE-003 | 중복 POST와 재시도는 canonical request hash를 결합한 idempotency key로 중복 Turn·Analysis Run·Report Run을 막고, 같은 key의 다른 payload는 충돌로 거부한다. | `PARTIAL` |
| RPT-001 | analyst는 자신이 소유한 Definition으로 Report 초안을 만들고 승인 큐로 전달할 수 있다. Draft mutation은 `draft_revision/expected_revision` CAS와 append idempotency hash를 사용하고 선택 block append·순서·revision 증가를 한 transaction으로 commit한다. stale 편집은 `409 REPORT_DRAFT_CONFLICT`로 기존 block을 덮지 않는다. report_admin은 할당·소유권 범위 안에서 승인·반려하며 actor·decision·version을 감사한다. | `PARTIAL` |
| RPT-002 | 승인 버전은 stable block ID·order·`is_required`·criticality policy version, layout·static text·참조 Definition·parameter schema·`period_mode`·ViewSpec과 초안 Conversation의 product/semantic release를 checksum으로 고정한다. preview의 `source_artifact_id`와 실행의 `result_artifact_id`를 구분한다. 새 release나 criticality 변경은 새 Version·재승인이 필요하다. | `PARTIAL` |
| RPT-003 | 수동 실행 actor는 `report_admin`, 각 block의 effective subject는 Definition 원 소유자, Trino 접속은 App service identity다. Run은 승인 Version의 product/semantic release만 사용하며 실행 불가하면 생성 전 `409 RESOURCE_CONFLICT`다. 시작 시 subject별 현재 권한과 하나의 `report_as_of`를 `report_permission_snapshot_id`로 고정하고 모든 child Analysis Run이 이를 참조한다. idempotency hash는 `report_as_of`를 포함한다. `ABSOLUTE` 기간은 유지하고 승인된 `RELATIVE` template만 report_as_of에서 해석한다. | `PARTIAL` |
| RPT-004 | Block별 새 `result_artifact_id`, status·reason·checksum·Term/Asset/query 근거와 actor·effective subject·service identity·policy version을 보존하고 매 실행 APP-G3를 통과한다. 저장 ViewSpec은 field role·grain·type compatibility를 새 Artifact에서 다시 검증해 적용하며 불일치 시 `VIEW_SCHEMA_INCOMPATIBLE`로 block을 실패시킨다. source Artifact 값·screenshot·과거 query를 대체 결과로 사용하지 않는다. P0 열람은 소유 `analyst`와 권한 있는 `report_admin`으로 제한한다. | `PARTIAL` |
| RPT-005 | 재시작 후 승인 버전·Run·Block Run·artifact를 App DB에서 복원한다. | `READY_TO_VERIFY` |

`VIEW_SCHEMA_INCOMPATIBLE`는 Analysis `reason_code`가 아니라 Report 실행의 별도 `report_block_reason_code` enum이다. OpenAPI·App DB·Frontend가 같은 enum을 사용하고 필수/선택 block 정책이 이를 Report Run의 `FAILED/PARTIAL`로 승격한다.

### OPS·SEC·QA — 실제 서비스 완료선

| ID | 요구사항과 인수 조건 | 상태 |
|---|---|---|
| OPS-001 | readiness가 App DB, DataHub Glossary, Trino source, model endpoint를 각각 실제 probe하고 code/image·data·semantic·prompt/model/policy·migration의 `product_release_id` 일치를 검사하며 불일치 시 fail-closed 한다. | `PARTIAL` |
| OPS-002 | timeout·retry·circuit break·max scan/result·동시 실행 상한과 오류 예산을 설정하고 부하 기준을 실측한다. | `PARTIAL` |
| OPS-003 | DB migration, serving view, App DB의 backup/restore와 rollback runbook을 실제 rehearsal 한다. | `NOT_STARTED` |
| OPS-004 | 시작 시와 주기적으로 만료 lease·비terminal Analysis Run·외부 query를 reconcile해 FAIL-006대로 terminal 처리하고, crash 지점별로 중복 query·고아 query·영구 진행중 Run이 0건임을 L4 fault-injection으로 검증한다. | `NOT_STARTED` |
| SEC-001 | Trino의 신뢰되지 않은 username header만으로 사용자 신원을 결정하지 않는다. App이 사용자·객체 권한을 검증해 Approved Context와 SQL에 강제하고, Trino는 제한된 App query service principal만 신뢰한다. P0 App 경로에는 선택한 authenticator·trust anchor·인증 transport·credential 저장 위치·rotation/폐기 중 기존 query 정책·서버 권한 mapping을 명시하고 다른 principal 사칭·write·setup principal 사용 negative test를 security manifest와 L4 receipt로 증명한다. | `BLOCKED` |
| SEC-002 | 외부 모델에는 승인된 최소 schema/context만 전송한다. 원문 행·secret·password·불필요한 PII를 전송·로그하지 않는다. | `READY_TO_VERIFY` |
| SEC-003 | 로그에 secret, raw sensitive result, 민감 SQL literal이 없고 감사 로그는 actor·action·object·decision·version만 보존한다. | `READY_TO_VERIFY` |
| SEC-004 | 사용자 질문, Glossary alias·설명, schema 설명, source/result 문자열을 prompt injection 가능한 비신뢰 입력으로 취급한다. adversarial set에서 policy 우회·비승인 tool/field 접근·secret 노출이 0건이어야 한다. | `NOT_STARTED` |
| QA-001 | runtime catalog에서 선택한 정상 archetype과 명확화·권한거부·Glossary stale·schema drift·APP-G2 retry·timeout·cancel·empty·partial·report rerun을 같은 릴리스에서 L3/L4로 검증한다. | `BLOCKED` |
| QA-002 | sealed calibration set으로 기준선을 측정한 뒤 held-out 공개 전에 질문 해석, Glossary grounding, SQL 구조, Gold 결과, 허용·거부, report 재실행 일치율과 cold/warm p50·p95의 표본·threshold·반복 횟수·승인자를 사전 등록한다. held-out 결과를 본 뒤 threshold를 낮추지 않는다. | `NOT_STARTED` |
| QA-003 | OpenAPI와 Frontend 타입 drift를 자동 검사하고, 기본 CI가 모든 Frontend test·올바른 Compose env 경로·대상 branch를 검사한다. test-double HTTP lane과 release E2E lane을 이름과 증거에서 분리한다. | `PARTIAL` |
| QA-004 | held-out Gold는 training·few-shot·prompt 선택·early stopping과 격리하고 manifest checksum을 먼저 봉인한다. split은 단순 paraphrase가 아니라 intent family·join graph·SQL template·temporal pattern 단위 누수를 검사한다. | `NOT_STARTED` |

## 6. P0 Release Gate

| Gate | 통과 조건 | 현재 |
|---|---|---|
| `P0-DATA-CUTOVER` | DATA-001~006과 OPS-003을 `DATA-G0~G7`, semantic candidate round-trip read-back, candidate canary, backup/restore·rollback rehearsal, cutover 승인, 전환 후 readiness·Golden smoke evidence로 검증 | `BLOCKED` |
| `P0-GLOSSARY` | GOV-001~009의 live DataHub L2/L3 증거, out-of-place candidate 전체 read-back과 최종 activation/rollback | `PARTIAL` |
| `P0-GOLD` | DATA-001~004·GOV-001~008 candidate readiness 통과 후, GOV-009 activation 전에 승인한 product Gold manifest·oracle·tolerance·held-out checksum | `BLOCKED` |
| `P0-E2E-REAL` | mock·fixture·하드코딩·result cache 없이 UF-02 `cached=false` L3 | `BLOCKED` |
| `P0-REPORT-RERUN` | 실제 새 Analysis Run을 만드는 UF-06 L3 | `BLOCKED` |
| `P0-GOLDEN-DIALOGUE` | GD-01~03을 인증 Conversation에서 실제 browser→HTTP→Backend→DataHub/Trino→App DB로 실행한다. 새로고침 복원, Run/View/query 수, 상대기간 범위 초과, lineage, idempotency·동시성·권한·release negative case가 모두 계약과 일치한다. | `NOT_STARTED` |
| `P0-SECURITY` | 허용·거부·마스킹·Trino 인증·write 0건 L4 | `BLOCKED` |
| `P0-FAILURE` | UF-03~05 실패 행렬 L3/L4 | `BLOCKED` |
| `P0-EVIDENCE` | 동일 릴리스 증거 manifest 재현 | `NOT_STARTED` |
| `P0-QUANT` | held-out 실행 전에 봉인한 표본·metric·threshold·반복·승인 계약과 최신 결과 | `NOT_STARTED` |

### Requirement→Gate 추적

| Gate | 반드시 `VERIFIED`여야 하는 Requirement |
|---|---|
| `P0-DATA-CUTOVER` | DATA-001~006, OPS-003 |
| `P0-GLOSSARY` | GOV-001~009 |
| `P0-GOLD` | ANL-010, QA-004와 위 선행 DATA/GOV 요구 |
| `P0-E2E-REAL` | AUTH-001~003, ANL-001~009, ANL-011, QA-003 |
| `P0-REPORT-RERUN` | SAVE-001~003, RPT-001~005 |
| `P0-GOLDEN-DIALOGUE` | CONV-001~010, AUTH-002~003, ANL-001~009, ANL-011, SAVE-003, RPT-001~005, QA-003 |
| `P0-SECURITY` | AUTH-002~004, SEC-001~004 |
| `P0-FAILURE` | FAIL-001~006, OPS-001~002, OPS-004, QA-001 |
| `P0-EVIDENCE` | QA-003과 이 문서 2절의 릴리스 증거 묶음 전체 |
| `P0-QUANT` | ANL-011, QA-002, QA-004 |

P0 완료에는 **모든 P0 Requirement ID와 모든 Release Gate가 같은 릴리스 후보에서 `VERIFIED`**여야 한다. Gate 표에 누락된 Requirement를 waiver로 처리하지 않으며, 범위를 빼려면 구현 후가 아니라 평가 전에 이 PRD를 새 버전으로 승인한다. 현재 P0 완료 항목은 0개다. 이는 코드가 없다는 뜻이 아니라 V4.1과 동일 릴리스 증거 기준으로 검증된 Gate가 없다는 뜻이다.

## 7. P1·P2 요구

P1은 예약 실행, 검증 결과를 근거로 한 제한된 보고서 작성 지원, 승인된 read-only MCP 조회다. P2는 RAG, ML-as-a-Tool, 추천, 확장 Catalog UI다. 코드가 이미 있더라도 P0 Gate를 우회해 검증·확장하지 않는다.

P1에 job queue나 별도 worker가 필요한지는 예약 동시성·실행 시간·다중 인스턴스 요구를 실측한 뒤 결정한다. P0에는 새 분산 시스템을 추가하지 않는다.

## 8. 현재 판정의 한계

- V4.1 SQL은 요청에 따라 실행하지 않았다.
- 외부 모델을 호출하지 않았다.
- 2026-08-15의 로컬 `ready` 관측은 Trino 공개 liveness, DataHub `/config`, model endpoint HTTP 상태, principal 파일 크기만 확인하던 이전 probe 결과라 폐기한다. 현재 계약은 runtime principal의 terminal `SELECT 1`, 인증된 DataHub GraphQL, 활성 model route별 exact model ID, 실제 principal parser를 요구하지만 이 강화된 readiness를 동일 release의 live stack에서 다시 실행한 evidence receipt는 아직 없다.
- 유료·쓰기 가능한 실제 분석 요청과 브라우저 release E2E는 새로 수행하지 않았다.
- 현재 `chat.conversations`와 `RequestContext.conversation_id`는 골격일 뿐 `/analysis` 요청·저장·Frontend 이력과 연결되지 않고, presentation Turn 계약과 Golden Dialogue E2E도 없다.
- 따라서 이 문서의 상태는 코드·설정·문서에 대한 감사 판정이며 제품 인증서가 아니다.

다음 문서: [`02_유저플로우.md`](02_유저플로우.md)
