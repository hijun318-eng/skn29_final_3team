# Answervice 기획서 요약본

| 항목 | 내용 |
|---|---|
| 문서 설명 | Answervice 최종 기획서와 실행 규칙을 팀 내부용으로 압축한 요약본 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-07-31 12:10 |
| 작성·수정 | 윤대성 / 3팀 사용자 요청·Codex 반영 |

> 대상: 팀원 5명 (평가자용 아님)
> 기준 문서: `docs/Answervice_기획서.md` v1.2 · `Gate_실행_카드_원장.md` v2.14 · 통합일정 20260729-20260903

---

## 3줄 요약

1. **뭘 만드나** — 사내 데이터가 5군데 DB에 흩어져 있는데, 사용자가 한국어로 질문하면 알아서 SQL 만들어 조회하고 근거까지 붙여서 답해주는 서비스. 그 답을 보고서 블록으로 재사용·자동 실행까지.
2. **뭐가 핵심이냐** — LLM이 SQL을 "잘 짜는 것"이 아니라, **LLM이 짠 SQL을 실행 전에 검사해서 통과한 것만 돌리는 구조**. 검사 게이트 3개(G1·G2·G3)가 핵심이고 LLM은 판정 권한이 없음.
3. **왜 어렵나** — 5인이 5.4주(7/29~9/3)에 DB 4종·DataHub·Trino·FastAPI·React·sLLM을 동시에 붙여야 함. 그래서 **경로 소유권 + CI 자동 검사**로 충돌을 막는 게 절반의 일.

---

## 용어 — 처음 나올 때 한 줄

| 용어 | 뜻 |
|---|---|
| **DataHub Core** | 데이터가 어디에 뭐가 있는지를 모아둔 카탈로그. 실제 데이터는 안 들고 있고 "설명서"만 가짐 |
| **Trino** | 여러 DB에 흩어진 데이터를 한 번의 SQL로 조회해주는 엔진. 실제 조회는 여기서 함 |
| **연합 조회(Federated Query)** | 데이터를 한군데로 옮기지 않고 각 DB에 그대로 둔 채 조회하는 방식 |
| **Context Package** | 이 질문에 답할 때 써도 되는 테이블·지표·JOIN·권한을 한 묶음으로 정리한 것. 매 질문마다 새로 만듦 |
| **G1 / G2 / G3** | 각각 근거 검사 / SQL 안전성 검사 / 결과 검사. 이 셋만 합격을 판정함 |
| **Guardrail** | LLM이 만든 SQL을 실행 전에 막는 안전장치 |
| **AST** | SQL을 문법 트리로 쪼갠 것. 문자열 검색이 아니라 구조로 검사해야 우회가 안 됨 |
| **Artifact** | 질문·조건·출처·검증 결과를 함께 저장한 분석 결과물. 보고서가 이걸 재사용 |
| **fixture** | 같은 테스트를 반복할 수 있게 고정해둔 테스트 데이터 |
| **gold 세트** | 정답이 확정된 평가용 질문 묶음. 모델 성능을 재는 기준 |
| **as_of** | "언제 기준으로" 계산할지 고정하는 기준 시각. 이게 없으면 어제와 오늘 답이 달라짐 |
| **sLLM** | 작은 LLM. 여기선 RunPod GPU에 직접 띄워 씀 |
| **LoRA** | 모델 전체를 다시 학습하지 않고 작은 어댑터만 붙여 학습하는 방식 |
| **Wave** | 함께 개발하고 한 번에 합칠 작업 묶음 |
| **Gate (I0~I5)** | 단계별 통과 검사. R1이 판정함 |
| **handoff manifest** | Wave 끝낼 때 내는 결과 보고 JSON. 뭘 바꿨고 뭘 검증했고 뭐가 남았는지 |
| **ALLOWED_PATHS** | 내가 이번 Wave에 수정해도 되는 파일 경로 목록 |
| **watermark** | 데이터가 어느 시점까지 반영됐는지 표시하는 값 |
| **idempotency** | 같은 요청이 여러 번 와도 결과가 한 번만 생기는 성질 |

---

## 1. 이 프로젝트가 푸는 문제

```
기업 데이터 사일로
  ├─ 답을 찾으려면 여러 부서·시스템을 거쳐야 함
  │    └─ 해결: 메타데이터 기반 통제형 대화 분석
  └─ 부서 횡단 보고서를 사람이 매번 취합
       └─ 해결: 검증된 분석 결과를 재사용하는 자동 리포팅
```

**두 기능은 별개가 아님.** 대화형 분석이 근거 있는 블록을 만드는 앞단, 자동 리포팅이 그 블록을 편집·승인·반복 실행하는 뒷단. 그래서 질문·자산·SQL·검증결과·출처의 ID가 보고서까지 끊기지 않고 이어져야 함.

**적용 데이터는 전량 합성 데이터.** 워커힐 호텔 운영 환경을 모사했지만 실제 데이터가 아니고, 특정 기업 성과를 주장하는 게 아니라 이기종 연결 구조를 검증하는 사례임.

---

## 2. 전체 흐름 — 질문 하나가 지나가는 길

```
챗 질문  또는  저장된 report_plan_id
   ↓
[Router]           승인된 템플릿·보고서 계획에 걸리나?
   ↓ (안 걸리면)
[Node 1]           질문 정규화 — 지표·기간·검색어로 구조화
   ↓
[Context Layer]    DataHub + 업무정책 병렬 조회 → Context Package 생성
   ↓
[G1]  Context Gate ── 실패 → 사용자에게 되묻기 / 안전 종료
   ↓ 통과
SQL 출처 결정  ┌ 템플릿 SQL
               ├ SQL Plan Cache
               └ [Node 2] 생성 SQL
   ↓
[G2]  SQL Policy Gate ── 실패 → [Node 2′] 1회만 수정 → [G2′] → 실패 시 종료
   ↓ 통과
Result Cache 확인  또는  Trino 읽기 전용 실행
   ↓
[Result Shaper] → [G3] Result Check ── 실패 → 설명 안 함, trace_id만 반환
   ↓ 통과
[Node 3]           근거 기반 설명 (수치 재계산 금지)
   ↓
보고서 조립 · artifact_id 저장
```

### 꼭 기억할 3가지

- **LLM은 합격을 판정하지 않음.** G1·G2·G3만 판정. Node 3은 G3 통과한 결과만 설명함.
- **SQL 수정은 딱 1번.** Node 2′가 무한 self-repair 하지 않음.
- **Cache도 Gate를 우회 못 함.** 캐시 히트여도 권한·정책 재검증함.

### Node별 책임

| Node | 하는 일 | **하면 안 되는 일** |
|---|---|---|
| Node 1 | 모호성 탐지, 지표·기간·검색어 구조화 | 테이블 확정, 권한 판정 |
| Node 2 | Context Package로 Trino SQL 생성 | 권한 판정, 실행 허용, 결과 계산 |
| Node 2′ | G2 거절 SQL을 승인 범위 안에서 1회 수정 | 반복 self-repair |
| Node 3 | 검증된 결과를 지표·기간·필터와 함께 설명 | SQL 정답 판정, **수치 재계산**, CoT 수신 |

### Gate별 판정

| Gate | 뭘 보나 | 실패하면 |
|---|---|---|
| G1 | 역할·권한, context_release, policy_version, as_of, 참조 테이블 유효성 | 문맥 부족이면 되묻기, 권한 없으면 안전 종료 |
| G2 | AST, allowlist, read-only, 승인 JOIN, 시간 함수, EXPLAIN, hard LIMIT | Node 2′ 1회 수정 후 재검증, 또 실패면 종료 |
| G3 | schema, row filter·mask·샘플링 증적, 범위·이상치, checksum | 사유와 trace_id 반환, **Node 3 호출 금지** |

---

## 3. 데이터 구성 — 5개 사일로 / 4종 엔진

| 사일로 | 데이터 | 엔진 | 왜 분리했나 |
|---|---|---|---|
| PMS | 예약, 객실, 투숙, 요금 | PostgreSQL | 표준 RDB, 예약·투숙 관계 |
| F&B POS | 주문, 매장, 상품, 결제 | MySQL | 거래형 데이터, MySQL 방언 |
| 멤버십 CRM | 고객, 등급, 포인트 | SQL Server | `member_no`, SQL Server 방언 |
| 시설 운영 | 시설 이용, 점검, 장애 | ClickHouse | 분석형 조회·타입·집계 차이 |
| 연회·매출 | 연회 예약, 상품, 매출 | PostgreSQL | 같은 엔진이어도 connection·책임 격리 |

**= 4개 엔진 런타임 / 5개 논리 DB / 5개 자격증명 / 5개 ingestion recipe / 5개 Trino catalog**

### 조인 관련해서 꼭 알아야 할 것

- 고객 매핑은 **CRM의 물리 테이블** `crm.dbo.customer_identity_map`. 코드에 하드코딩하는 게 아니라 실제 테이블이고 DataHub URN도 따로 있음.
- 회원 등급은 **현재값 컬럼 쓰면 안 됨.** `member_grade_history`의 `[valid_from, valid_to)` 반개구간으로 계산.
- "골드 회원 매출"처럼 별말 없으면 → **거래·투숙 시점(event time)에 유효했던 등급**으로 계산. 현재 등급 기준은 별도 규칙.

---

## 4. R&R × 일정

### 역할

| 역할 | 담당 | branch | 주 책임 |
|---|---|---|---|
| **R1** 기술PM·통합·품질·릴리스 | 박준희 | `junhee` | 공통 계약, 루트 Compose·env·CI, 통합 test, Gate 판정, 릴리스 |
| **R2** 데이터플랫폼·메타데이터·연합조회 | 정승 | `seung` | 5 source DDL·seed, identity bridge, DataHub recipe, Trino catalog, 정답 fixture |
| **R3** AI·모델·프롬프트·ModelOps | 윤대성 | `daesung` | Node 1·2·2′·3 I/O schema, prompt, fake adapter, 평가 runner, LoRA 실험 |
| **R4** 백엔드 Control Plane | 김재홍 | `jaehong` | FastAPI·OpenAPI, Controller·Router, Context Builder, **G1·G2·G3**, Cache, Artifact, worker |
| **R5** 프론트엔드·자동 리포팅 | 송민지 | `minji` | Chat·Evidence·표·차트, Report grid·editor·history, Catalog·Audit UI |

> **G1·G2·G3 구현은 R4 소유.** R3는 Node의 입출력 계약만 소유함. 이거 헷갈리면 작업이 겹침.

### 주차별 일정

| 기간 | R1 박준희 | R2 정승 | R3 윤대성 | R4 김재홍 | R5 송민지 | 종료점 |
|---|---|---|---|---|---|---|
| 7/29~7/31 | 범위·소유권·통합 profile | source·engine·논리 모델 | Node 경계·I/O schema | backend 경계·공통 객체 | frontend 후보·IA·상태 | **I0** |
| 8/3~8/7 | 공통 계약·Compose·env·CI | PMS/CRM DDL·seed·identity | fake adapter·prompt baseline | OpenAPI·auth·DB·Controller | type·mock·Chat/Report 계약 | **I1** |
| 8/10~8/14 | 통합 profile 대표 질문 검증 | PMS/CRM ingestion·2 catalog | fake 설명·평가 runner | Template·Context·G1/G2/G3 | Chat·Evidence·표·차트 | **I2** |
| 8/17~8/21 | 5-source·일반 질문·보안 | 5 recipe·catalog·JOIN | Node 1·2·2′·3·Base 비교 | 실제 model adapter·Cache | 오류 상태·Report module | **I3** |
| 8/24~8/28 | Report·장애·복구·성능 통합 | 평가 fixture·5번째 source | LoRA 1회 비교·조건부 채택 | Report 등록·worker·schedule | editor·run·history·Audit | **I4 · 기능 동결** |
| 8/31 | 필수 30건 판정 | 빈 환경 재생성·최종 hash | 전체 model 평가·fallback | backend 전체 회귀 | production build·E2E | **RC1** |
| 9/1 | 전체 리허설·결함 분배 | 데이터 재적재 리허설 | model server 재기동 | API·worker·trace 리허설 | 발표 동선 리허설 | 리허설 |
| 9/2 | 최종 수용·release SHA 동결 | schema/seed/watermark 동결 | model/prompt/adapter 동결 | API/migration/policy 동결 | frontend/Report route 동결 | **RC2 · I5** |
| 9/3 | 발표 진행·통합 질의응답 | 데이터 근거 설명 | AI·모델 설명 | Gate·Control Plane 설명 | 서비스 시연 | **최종발표** |

### Gate 통과 조건

| Gate | 통과 기준 | 통과 증거 |
|---|---|---|
| I0 | 역할·범위·파일 소유권 확정 | 결정 원장, branch mapping |
| I1 | metric/time/schema/API/model/Report 계약 동결 | 버전 붙은 contract·fixture |
| I2 | 대표 질문을 **LLM 없이** 전체 왕복 | result hash·trace·화면 |
| I3 | 일반 질문 + Node 1·2·2′·3 통합 | 필수 30건 subset·trace |
| I4 | Chat→Artifact→Report→Run History 연결 | 수동·예약·partial trace |
| I5 | 보안·장애·복구·재현성·발표 환경 | release manifest·runbook |

---

## 5. 내 브랜치에 push하면 무슨 검사가 도는가

**CI 실패했을 때 이 표부터 보세요.**

| Job | 뭘 검사하나 | 실패하면 내가 할 일 | seung | daesung | jaehong | minji |
|---|---|---|---|---|---|---|
| `role-scope` | 내가 바꾼 파일이 `ALLOWED_PATHS` 안인지 + handoff manifest 정합성 | Summary에 침범 경로가 그대로 찍힘. **그 파일 되돌리고** 필요하면 change request | ○ | ○ | ○ | ○ |
| `python-contracts` | Python compile + `pytest tests` **전체** | 내 변경과 무관한 실패면 **내 코드 고치지 말고 R1에게** | ○ | ○ | ○ | ○ |
| `document-quality` | 문서 정책, WBS 형식, 일일보고 형식 | 문서 헤더(버전·기준일 `YYYY-MM-DD HH:MM`) 확인 | ○ | ○ | ○ | ○ |
| `frontend-contracts` | `npm ci` → build → 화면 계약 test | lockfile 갱신 여부 확인 | – | – | – | ○ |
| `compose-config` | DataHub fragment + dev/full/split-host 3개 profile | fragment 문법·env 변수 확인 | ○ | – | – | – |
| `quality-gate` | 위 결과 집계 + R1 대시보드 출력 | 위 중 하나가 red면 같이 red | ○ | ○ | ○ | ○ |

> `python-contracts`와 `document-quality`는 **모든 브랜치에서 전체를** 돕니다. 그래서 R3 테스트가 깨지면 R5도 red가 됩니다. 역할별 분기는 Wave 2 전에 적용 예정이고, 그때까지 타 역할 실패는 내 결함으로 계산하지 않습니다.

### 판정 등급 — 뭐가 막고 뭐가 안 막나

| 판정 | 언제 | **CI 차단?** |
|---|---|:---:|
| `PASS` | 다 정상 | — |
| `FAIL` | 허용 경로 침범 / 필수 필드 누락 / `FAIL`·`BLOCKED` 검증 | **차단** |
| `REVIEW_REQUIRED` | 잔여 위험·미실행 검증·change request·외부 승인 요청 적음 | 안 막음 |
| `NOT_RUN` | 아직 manifest 안 냄 | 안 막음 |
| `N/A` | 이미 `MERGED_DEV`라 manifest 불필요 | — |

**중요 — 잔여 위험 적어도 CI 안 막힙니다.** 예전엔 막혔는데 2026-07-31에 고쳤습니다(원장 v2.14). 정직하게 적은 사람이 손해 보면 아무도 안 적게 되고, 그러면 Gate가 모으려던 증거 자체가 사라지기 때문입니다.

반대로 **실행 안 한 검증을 `PASS`로 적는 건 증거 위조로 취급**합니다. 모르면 비워두지 말고 `Not Run`과 사유를 쓰세요.

### handoff manifest 내는 법

```bash
python .github/scripts/gate_scope.py \
  --branch <내branch> --base origin/dev --head HEAD \
  --mode merge-base --write-handoff
```

`handoffs/<실행묶음ID>.json` 초안이 생깁니다. 이미 있으면 덮어쓰지 않습니다. 초안은 `COMPLETED_CARDS`가 비어 있고 `TEST_RESULTS`에 안내 문구가 들어 있으니 **실제 값으로 채우세요.**

필수 13개: `EXECUTION_BUNDLE_ID` `ROLE` `BRANCH` `BASE_SHA` `RESULT_SHA` `COMPLETED_CARDS` `CHANGED_FILES` `CONTRACT_VERSIONS` `TEST_RESULTS` `NOT_RUN` `CHANGE_REQUESTS` `RESIDUAL_RISKS` `EXTERNAL_APPROVAL_REQUIRED`

### 작업 흐름

```
junhee  ─┐
seung   ─┤
daesung ─┼──→  dev  ──→ (I5 이후) main
jaehong ─┤
minji   ─┘

개인 branch끼리 직접 병합 ✗ / dev·main 병합은 R1만
```

**멈춰야 하는 5가지 조건** — 목표 Gate 도달 / 카드 범위 완료 / 역할 밖 변경 필요 / 계약 충돌 / 필수 검증 실패

---

## 6. 성공지표 — 이건 협상 대상 아님

환경·모델과 무관하게 착수 시점에 확정한 값입니다.

| 영역 | 합격선 |
|---|---|
| 소스 연결 | 5개 소스 전부 ingestion·DataHub 검색·Trino 조회 성공 |
| 추적성 | `request_id → context release → model/policy → query_id → artifact_id` 재구성률 **100%** |
| 안전 | DDL·DML·procedure·passthrough·권한 밖 요청의 원본 실행 **0건** |
| 대표 질문 | 고정 30건(단일 10 / 교차 10 / 모호 5 / 권한·금지 5) 전부 올바른 성공 또는 중단 |
| 시간 재현 | 같은 조건에서 보고서 블록 결과 checksum 일치율 **100%** |
| 출처 일치 | 화면 출처 / Context URN / 생성 SQL catalog / 실제 실행 소스 불일치 **0건** |
| 개인정보 | 일반 role의 결과·모델입력·응답·로그·보고서에서 직접식별 원문 노출 **0건** |
| 운영·복구 | RPO 24시간 / RTO 4시간 이내 |

정확도·p95·VRAM·비용은 **단계 2 baseline 측정 후에** 확정합니다. "보고서 7일 → 수 분"은 성과가 아니라 **검증할 가설**로만 씁니다.

> ⚠️ **대표 질문 30건 문항과 metric 승인값은 아직 미확정** (2026-07-31 기준). 원장에 `REPRESENTATIVE_QUESTION=N/A — I1 승인 전 작성 금지`로 걸려 있고, 이게 현재 I1의 blocker입니다. **R1 승인 전에 문항 만들지 마세요.**

---

## 7. 범위 — 뭘 하고 뭘 안 하나

| 범위 | 우선순위 | 완료선 |
|---|---|---|
| 메인 챗 | **P0** | 자연어 질문 → 근거·표·차트까지 읽기 전용 분석 |
| 자동 리포팅 | **P0** | 12-column grid 편집, AI 보조, 챗 왕복, 수동·스케줄 실행 |
| 데이터 카탈로그·커넥션 | P1 | DataHub 자산 탐색, 5개 소스 상태, API 사용 증명 |
| MCP Tool 관리 | P2 | Tool 메타정보·상태·권한·최근 실행 |
| 사내 문서 RAG | P2 | 권한·유효기간 필터, 버전·인용 위치 표시 |
| ML-as-a-Tool | P2 | Feature Set → 모델 Tool 호출 1개 대표 경로 |
| 고객 360 | 후속 | I5 이후 별도 Gate |

**P2와 고객 360은 9/3 발표 완료 조건에 안 들어갑니다.** 미착수를 릴리스 실패로 계산하지 않습니다.

---

## 8. 일정 압축 — 10주 계획을 5.4주에

기획 원안은 10주짜리입니다. 실제는 7/29~9/3, **약 5.4주**.

**압축은 "빨리 하기"가 아니라 "범위 줄이기"입니다.** 단계를 겹쳐서 같은 걸 더 빨리 만드는 게 아니라, 산출물 폭을 줄이고 종료 조건은 그대로 둡니다.

| 원 계획 | 압축 후 | 그래도 지키는 것 |
|---|---|---|
| 5개 소스 전체 교차 조회를 단계 2에 | 대표 **2-source** slice 먼저(I2), 5 source는 단독 조회 + 승인된 2~3-source JOIN(I3) | G1·G2·G3 우회 0건, 출처 불일치 0건 |
| 단계 1에 gold 120건 전수 검수 | 필수 30건 먼저, gold 120건은 I3까지 분할 | 미검수 샘플의 gold 승격 금지 |
| 9~10주 안정화 | 8/28 기능 동결 → 8/31 RC1 → 9/2 전체 동결 → 9/3 발표 | 필수 합격선 전항 |

감당 안 되는 범위는 **일정을 당기지 말고 I5 이후로 넘깁니다.**

---

## 9. 기술 스택 — 계획 vs 실제

⚠️ 표시는 계획과 현재 구현이 다른 항목입니다. I1에서 어느 쪽으로 갈지 정합니다.

| 영역 | 계획 | 현재 (2026-07-31) |
|---|---|---|
| 프론트엔드 | React 19, Vite | React 19.2.7, Vite 8.1.5 ✅ |
| 타입 체계 | TypeScript | ⚠️ **미도입** (`.jsx` 10 / `.tsx` 1 / `.ts` 4) |
| 차트 | Apache ECharts | ⚠️ **recharts 3.10.0** 사용 중 |
| 서버 상태 | TanStack Query | ⚠️ 미도입 |
| 보고서 배치 | react-grid-layout + dnd-kit | ⚠️ 미도입 |
| API | FastAPI, Pydantic v2, OpenAPI | `app/backend` 진행 중 |
| 앱 DB | PostgreSQL, SQLAlchemy 2, Alembic | Alembic chain 구성 완료 |
| SQL 검증·실행 | SQLGlot + Trino | Trino 구성 완료, **G2 미구현** |
| sLLM 서빙 | RunPod + vLLM | 미착수 (Wave 3) |
| 관측성 | OpenTelemetry | 미착수 |

> **경로 주의:** 백엔드 실제 코드는 `app/backend/**`입니다. `app/fastapi`·`src/backend`·`src/control_plane`은 **비어 있는 죽은 경로**이고, 프론트는 `app/enterprise-react`가 활성입니다(`app/react`는 dist만 남은 구형). 원장 경로표 교정은 R1 승인 대기 중입니다.

---

## 10. 리스크 — 실제로 터질 것들

| 리스크 | 조기 신호 | 대응 |
|---|---|---|
| 자원 경합 (5 DB + DataHub + Trino + 앱) | swap, container restart, indexing 지연 | 프로파일별 peak 측정, full 실패 시 host 분리. **fixture 줄여서 성공 처리 금지** |
| connector·타입·방언 불일치 | driver/type coercion 오류 | DB 버전 고정, catalog 단독·JOIN spike, 문제 타입 명시 변환 |
| 잘못된 source·column·JOIN | 실행은 되는데 gold 결과 불일치 | DataHub grounding, 승인 JOIN만, Context 제한 |
| SQL 검증기 과소·과대 차단 | negative test 실패 / 정상 질문 거부 증가 | parser 기반 정책, 허용·차단 fixture 양쪽 |
| **gold 세트 제작 병목** | 리뷰 대기, 정답 불일치 | 단계 1 핵심 산출물, 역할별 공동 승인 |
| metadata 문제를 파인튜닝으로 덮기 | 데이터 늘려도 같은 JOIN 오류 반복 | baseline 실패 원인부터 분류, Context 고친 뒤 재측정 |
| **대표 질문·metric 미확정** | 원장 blocker 유지 | R1 승인 전 문항 작성 금지 |
| CI 교차 역할 차단 | 내 변경과 무관한 job이 red | 역할별 test 분기 (Wave 2 전) |
| dev 병합 검사 공백 | dev 이력에 role scope 판정 없음 | PR 트리거 + branch protection (승인 대기) |

---

## 11. 지금 열려 있는 것 (2026-07-31)

**I1 blocker**

- 대표 질문·metric 승인값 미확정
- OpenAPI·UI·Report 초안 version 미동결
- 실제 schema에 없는 PMS 수익 필드
- PMS↔CRM event-time 승인 JOIN 미등록

**R1 승인 대기** — `docs/markdown/collaboration/R1_Gate_원장_경로_정합성_패치_제안서.md`

1. R4 경로를 `app/backend/**`로 교정 (현재 죽은 경로 3개)
2. R5 죽은 경로(`src/report`·`tests/report`) 제거
3. R4-W1 `TEST_COMMANDS` compile 대상 교정
4. 활성 frontend를 `app/enterprise-react` 단일로 확정
5. `app/react` 삭제 여부
6. **`01_요구사항정의서.md`·`05_화면설계서.md` 소유자 지정** ← 지금 CI가 검증하는데 아무도 못 고치는 상태
7. 기획서 소유자 R1 지정 (반영 완료, 사후 승인)

**CI 개선 대기** — 역할별 test 분기 / `dev` PR 트리거 + branch protection / 원장 파싱 취약성

---

## 12. 헷갈리기 쉬운 것 정리

- **DataHub는 조회 엔진이 아님.** 메타데이터 기준 시스템. 실제 조회는 Trino.
- **DataHub CLI만 돌리고 GMS 끄는 건 불가.** ingestion이 GMS sink를 필요로 함.
- **P1 카탈로그 화면보다 DataHub ingestion·API가 먼저.** 사용자 기능 순서와 기술 의존 순서는 다름.
- **`dev` profile은 개발용이지 수용 시험 대체가 아님.** 전체 통합은 `full`로 판정.
- **모든 Node가 Base 모델을 기준선으로 씀.** LoRA는 채택 Gate 통과 시에만 Node 2·2′에 적용. Node 1·3에는 절대 적용 안 함.
- **합성 데이터에 의도한 패턴이 있어도** 모델이 근거 없이 원인을 단정하면 실패로 분류.
- **자동 CI 통과 = 기계 검증 완료**일 뿐. 제품 수용·계약 Freeze·최종 Gate는 R1이 별도 판정.

---

## 참고 문서

| 문서 | 용도 |
|---|---|
| `docs/Answervice_기획서.md` | 전체 기준 (v1.2) |
| `docs/markdown/collaboration/Gate_실행_카드_원장.md` | **실행 권한·상태·허용 경로의 단일 기준** (v2.14) |
| `docs/markdown/ai_docs/5인_병렬구현_0*_매뉴얼_최종안.md` | 역할별 상세 — `3.4`절에 CI 설명 있음 |
| `docs/markdown/ai_docs/5인_병렬구현_통합일정_*.md` | 일정·Gate·병합 순서 |
| `docs/markdown/02_WBS.md` | 공식 담당·상태 |

---

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-07-31 12:10 | 기획서 v1.2와 원장 v2.14를 기준으로 팀 내부용 요약본 작성. 3줄 요약, 용어 풀이, 질문 실행 흐름, 5개 사일로 구성, R&R×주차별 일정, 역할별 CI 검사 표, 성공지표, 일정 압축 원칙, 열려 있는 결정 사항을 포함 |
