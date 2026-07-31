# Answervice 기획서 요약본

| 항목 | 내용 |
|---|---|
| 문서 설명 | Answervice 최종 기획서를 팀 내부 이해용으로 압축한 요약본 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.1 |
| 문서 기준일 | 2026-07-31 12:40 |
| 작성·수정 | 윤대성 / 3팀 사용자 요청·Codex 반영 |

> 대상: 팀원 5명 (평가자용 아님)
> 기준 문서: `docs/Answervice_기획서.md` v1.2
> 이 문서는 **무엇을 만드는지 이해**하기 위한 자료임. 일정·진척·담당 상태는 `docs/markdown/02_WBS.md`와 실행 카드 원장에서 봄.

---

## 3줄 요약

1. **뭘 만드나** — 사내 데이터가 5군데 DB에 흩어져 있는데, 사용자가 한국어로 질문하면 알아서 SQL 만들어 조회하고 근거까지 붙여서 답해주는 서비스. 그 답을 보고서 블록으로 재사용·자동 실행까지.
2. **뭐가 핵심이냐** — LLM이 SQL을 "잘 짜는 것"이 아니라, **LLM이 짠 SQL을 실행 전에 검사해서 통과한 것만 돌리는 구조**. 검사 게이트 3개(G1·G2·G3)가 핵심이고 LLM은 판정 권한이 없음.
3. **뭐가 다르냐** — DataHub를 쓴다는 게 아니라, 승인·버전·토큰 제한이 걸린 Context Layer와 SQL Guardrail, 그리고 분석 결과를 보고서에서 재실행할 수 있다는 것.

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

### 지금 뭐가 불편한가

- 데이터 위치와 의미를 물어보려고 담당자를 반복해서 거쳐야 함
- 같은 "고객"인데 소스마다 식별자와 이름이 달라서 그냥 조인이 안 됨
- SQL을 쓸 줄 알아도 소스별 방언·권한·기준 시각·지표 정의를 동시에 맞춰야 함
- 결과를 보고서로 옮기면 질문 조건과 출처가 떨어져 나가서 재현이 안 됨

### AS-IS → TO-BE

| 관점 | AS-IS | TO-BE |
|---|---|---|
| 데이터 탐색 | 담당자에게 위치·의미 문의 | DataHub 메타데이터와 승인 컨텍스트로 검색 |
| SQL 작성 | 사용자가 소스별 스키마·방언을 직접 이해 | sLLM이 생성하고 parser·정책 검증기가 검사 |
| 조인 | 담당자 암묵지 | 승인된 공통키·JOIN만 사용 |
| 결과 해석 | 수치와 기준을 따로 확인 | 결과 + 지표·필터·기간·기준시각을 함께 표시 |
| 보고서 | 복사해서 매 주기 재작성 | 검증된 블록을 재사용·재실행 |

**안 바뀌는 것도 명확히** — 자산 소유자의 접근 승인, 원본 DB의 권한, 신규 관계의 검토·승인, 업무 판단의 최종 책임, 게시 전 사용자 승인.

**데이터는 전량 합성입니다.** 워커힐 운영 환경을 모사했지만 실제 데이터가 아니고, 특정 기업 성과를 주장하는 게 아니라 이기종 연결 구조를 검증하는 사례임.

---

## 2. 질문 하나가 지나가는 길

이게 제품의 전부라고 봐도 됩니다.

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
[G2]  SQL Policy Gate ── 실패 → [Node 2′] 1회만 수정 → [G2′] → 또 실패면 종료
   ↓ 통과
Result Cache 확인  또는  Trino 읽기 전용 실행
   ↓
[Result Shaper] → [G3] Result Check ── 실패 → 설명 안 함, trace_id만 반환
   ↓ 통과
[Node 3]           근거 기반 설명 (수치 재계산 금지)
   ↓
보고서 조립 · artifact_id 저장
```

### 여기서 꼭 기억할 3가지

- **LLM은 합격을 판정하지 않음.** G1·G2·G3만 판정함. Node 3은 G3 통과한 결과만 설명함.
- **SQL 수정은 딱 1번.** Node 2′가 무한 self-repair 하지 않음.
- **Cache도 Gate를 우회 못 함.** 캐시가 맞아도 권한·정책을 다시 검증함.

### 실행 경로 4가지

| 경로 | 흐름 |
|---|---|
| 템플릿 적중 | Router → Template Binding → Context → G1 → 템플릿 SQL → G2 → 실행 → G3 → Node 3 |
| Plan Cache 적중 | Router → Node 1 → Context → G1 → 캐시 SQL → G2 → 실행 → G3 → Node 3 |
| 일반 질문 | Router → Node 1 → Context → G1 → **Node 2** → G2 → 실행 → G3 → Node 3 |
| 예약 보고서 | `report_plan_id`로 진입, 템플릿·Context release·권한·`as_of`를 **다시** 검증 |

---

## 3. Node와 Gate의 책임 경계

작업이 겹치기 제일 쉬운 지점이라 정확히 봐두세요.

| Node | 하는 일 | **하면 안 되는 일** |
|---|---|---|
| Node 1 | 모호성 탐지, 지표·기간·검색어 구조화 | 테이블 확정, 권한 판정 |
| Node 2 | Context Package로 Trino SQL 생성 | 권한 판정, 실행 허용, 결과 계산 |
| Node 2′ | G2 거절 SQL을 승인 범위 안에서 1회 수정 | 반복 self-repair |
| Node 3 | 검증된 결과를 지표·기간·필터와 함께 설명 | SQL 정답 판정, **수치 재계산**, CoT 수신 |

| Gate | 뭘 보나 | 실패하면 |
|---|---|---|
| **G1** Context | 역할·권한, context_release, policy_version, as_of, 참조 테이블 유효성 | 문맥 부족이면 되묻기, 권한 없으면 안전 종료 |
| **G2** SQL Policy | AST, allowlist, read-only, 승인 JOIN, 시간 함수, EXPLAIN, hard LIMIT | Node 2′ 1회 수정 후 재검증, 또 실패면 종료 |
| **G3** Result | schema, row filter·mask·샘플링 증적, 범위·이상치, checksum | 사유와 trace_id 반환, **Node 3 호출 금지** |

> **G1·G2·G3 구현은 R4 소유.** R3는 Node의 입출력 계약만 소유합니다.

---

## 4. 계층별 역할

| 계층 | 하는 일 | **안 하는 일** |
|---|---|---|
| DataHub Core | 메타데이터 수집·검색, 스키마·소유자·태그 | 원천 데이터 저장, SQL 실행, 연합 조회 |
| Context Layer | 자산 검색, 승인 지표·JOIN·정책 결합, 권한 필터, 압축·버전 | DataHub 스키마 복제 저장, LLM의 자유 선택 허용 |
| Controller | 실행 순서, SQL 출처 선택, timeout, 상태, 수정 1회 상한 | 자연어 생성, 자율 Tool 계획 |
| LLM Node | 질문 정규화, SQL 생성·1회 수정, 근거 설명 | 권한·Gate 판정, SQL 실행, 수치 재계산 |
| G1·G2·G3 | 합격 판정과 즉시 종료 | 자유 self-review |
| Cache | 승인 SQL plan·권한별 결과 재사용, version·watermark 무효화 | Gate 우회, 권한 다른 결과 공유 |
| Trino | 5개 catalog 읽기 전용 조회, row filter·mask | 메타데이터 기준 시스템 노릇 |
| Result Shaper | 승인 집계·샘플링·표시 상한 적용, 증적 생성 | 원시 대량 row를 모델에 전달 |

---

## 5. 데이터 구성 — 5개 사일로 / 4종 엔진

| 사일로 | 데이터 | 엔진 | 왜 분리했나 |
|---|---|---|---|
| PMS | 예약, 객실, 투숙, 요금 | PostgreSQL | 표준 RDB, 예약·투숙 관계 |
| F&B POS | 주문, 매장, 상품, 결제 | MySQL | 거래형 데이터, MySQL 방언 |
| 멤버십 CRM | 고객, 등급, 포인트 | SQL Server | `member_no`, SQL Server 방언 |
| 시설 운영 | 시설 이용, 점검, 장애 | ClickHouse | 분석형 조회·타입·집계 차이 |
| 연회·매출 | 연회 예약, 상품, 매출 | PostgreSQL | 같은 엔진이어도 connection·책임 격리 |

**= 4개 엔진 런타임 / 5개 논리 DB / 5개 자격증명 / 5개 ingestion recipe / 5개 Trino catalog**

엔진을 5종으로 늘리지 않은 이유는, 숫자를 채우는 것보다 **방언·타입·connector 차이를 실제로 검증하는 게** 목적이기 때문입니다.

### 조인에서 헷갈리기 쉬운 것

- 고객 매핑은 **CRM의 물리 테이블** `crm.dbo.customer_identity_map`. 코드에 하드코딩하는 게 아니라 실제 테이블이고 DataHub URN도 따로 있음.
- 회원 등급은 **현재값 컬럼 쓰면 안 됨.** `member_grade_history`의 `[valid_from, valid_to)` 반개구간으로 계산.
- "골드 회원 매출"처럼 별말 없으면 → **거래·투숙 시점(event time)에 유효했던 등급**으로 계산. 현재 등급 기준은 별도 규칙.

---

## 6. 무엇을 만들고 무엇을 안 만드나

| 범위 | 우선순위 | 완료선 |
|---|---|---|
| 메인 챗 | **P0** | 자연어 질문 → 근거·표·차트까지 읽기 전용 분석 |
| 자동 리포팅 | **P0** | 12-column grid 편집, AI 보조, 챗 왕복, 수동·스케줄 실행 |
| 데이터 카탈로그·커넥션 | P1 | DataHub 자산 탐색, 5개 소스 상태, API 사용 증명 |
| MCP Tool 관리 | P2 | Tool 메타정보·상태·권한·최근 실행 |
| 사내 문서 RAG | P2 | 권한·유효기간 필터, 버전·인용 위치 표시 |
| ML-as-a-Tool | P2 | Feature Set → 모델 Tool 호출 1개 대표 경로 |
| 고객 360 | 후속 | I5 이후 별도 Gate |

**P2와 고객 360은 발표 완료 조건에 안 들어갑니다.** 미착수를 릴리스 실패로 계산하지 않습니다.

### 실패를 어떻게 다루나

실패를 숨기지 않고 유형별로 구분해 보여주는 게 설계 원칙입니다.

| 상태 | 언제 | 사용자에게 |
|---|---|---|
| 문맥 부족·모호 (G1) | 기간·지표·대상이 안 정해짐 | 필요한 조건만 되물음 |
| 정책 차단 (G2) | SQL 구조·권한·JOIN·비용 정책 위반 | 내부 정책 노출 없이 안전한 사유와 힌트 |
| 실행 실패 (Trino) | 방언·timeout·connector 오류 | 재시도 가능 여부와 실패 source |
| 결과 증적 미달 (G3) | schema·증적·범위 검사 실패 | 검증 실패로 종료, **단정적 설명 금지** |
| 부분 실패 | 일부 소스·블록만 실패 | 성공·실패를 분리 표시 |
| 근거 부족 | 데이터가 결론을 지지 안 함 | 단정하지 않고 추가 확인 필요 표시 |

모든 오류에 `trace_id`가 붙습니다. 원문 DB 오류·내부 정책 상세·stack trace·모델 추론 과정은 사용자와 Node 3에 **노출하지 않습니다.**

---

## 7. 성공의 정의

환경이나 모델이 달라져도 흔들리지 않는 값이라 착수 시점에 확정했습니다.

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

정확도·p95·VRAM·비용은 **baseline 측정 후에** 확정합니다. "보고서 7일 → 수 분"은 성과가 아니라 **검증할 가설**로만 씁니다.

### 평가 데이터

| 세트 | 규모 | 구성 |
|---|---|---|
| 필수 수용 세트 | 30건 | 단일 10, 교차 10, 모호 5, 권한·금지 5 — 전수 인간 검수 |
| gold 평가 세트 | 120건 | 단일 50, 2-source 35, 3-source 15, negative 20 |
| 개발 검증 세트 | 80~120건 | gold와 표현·템플릿 그룹이 겹치지 않게 분리 |
| 학습 후보 세트 | 600~1,000건 | 층화 20% 인간 검수, **미검수 샘플의 gold 승격 금지** |

---

## 8. 팀 구성

| 역할 | 담당 | branch | 주 책임 |
|---|---|---|---|
| **R1** 기술PM·통합·품질·릴리스 | 박준희 | `junhee` | 공통 계약, 루트 Compose·env·CI, 통합 test, Gate 판정, 릴리스 |
| **R2** 데이터플랫폼·메타데이터·연합조회 | 정승 | `seung` | 5 source DDL·seed, identity bridge, DataHub recipe, Trino catalog, 정답 fixture |
| **R3** AI·모델·프롬프트·ModelOps | 윤대성 | `daesung` | Node 1·2·2′·3 I/O schema, prompt, fake adapter, 평가 runner, LoRA 실험 |
| **R4** 백엔드 Control Plane | 김재홍 | `jaehong` | FastAPI·OpenAPI, Controller·Router, Context Builder, **G1·G2·G3**, Cache, Artifact, worker |
| **R5** 프론트엔드·자동 리포팅 | 송민지 | `minji` | Chat·Evidence·표·차트, Report grid·editor·history, Catalog·Audit UI |

**검증 독립성** — gold 세트는 R1(업무 의미)과 R2(SQL·결과)가 공동 승인합니다. SQL 정책과 read-only는 R4가 구현하고 **R1이 구현자와 분리된 입장에서** negative test를 합니다.

**작업 방식** — 개인 branch에서 작업하고 통합은 `dev` 하나로만 모읍니다. 개인 branch끼리 직접 병합하지 않고, `dev`·`main` 병합은 R1만 합니다. 다른 역할이 소유한 파일은 직접 고치지 않고 change request로 넘깁니다.

---

## 9. 개발 단계 (I0~I5)

일정이 아니라 **무엇이 끝나야 다음으로 가는지**를 정의한 것입니다.

| 단계 | 끝났다고 보는 기준 |
|---|---|
| **I0** 기준 정렬 | 역할·범위·파일 소유권이 정해지고 결정 원장에 남음 |
| **I1** Contract Freeze | metric/time/schema/API/model/Report 계약에 버전이 붙고, R4·R5가 fake adapter로 개발 가능 |
| **I2** Deterministic Slice | 대표 질문이 **LLM 생성 없이** 전체 왕복하고 trace가 남음 |
| **I3** General LLM | 일반 질문과 Node 1·2·2′·3이 통합되고 보안 기준선 통과 |
| **I4** Reporting | Chat→Artifact→Report→실행 이력이 연결되고 부분 실패·중복 방지 검증 |
| **I5** Release | 빈 환경 재현, 필수 30건, 보안·장애·복구·성능·E2E 판정, 모든 버전 동결 |

**달력상 날짜가 됐다고 넘어가지 않습니다.** 각 역할은 승인된 범위에서 fake·fixture로 최대한 독립 진행하고, 목표 Gate 도달·범위 완료·역할 밖 변경 필요·계약 충돌·필수 검증 실패 이 5가지에서만 멈춥니다.

---

## 10. 기술 스택

| 영역 | 채택 | 비고 |
|---|---|---|
| 프론트엔드 | React 19 + Vite | 활성 frontend는 `app/enterprise-react` |
| 차트 | recharts | 표·KPI·반응형 요구 충족 |
| API·계약 | FastAPI, Pydantic v2, OpenAPI | typed contract |
| 애플리케이션 DB | PostgreSQL, SQLAlchemy 2, Alembic | Context 승인본·artifact·report·audit 저장 |
| 실행 흐름 | Deterministic Controller + 상태 머신 | 자유 ReAct 아님 |
| SQL 검증·실행 | SQLGlot + Trino | G2의 AST 검사와 Trino의 read-only·mask를 분리 |
| sLLM 서빙 | RunPod GPU Pod + vLLM | 전 Node Base 기준선 |
| 관측성 | OpenTelemetry | request→context→model→Trino→artifact 연결 |
| 타입 체계 / 캐시 | 구현 단계에서 확정 | I1에서 결정 |

**백엔드 코드는 `app/backend/**`입니다.** 헷갈리기 쉬운데 `app/fastapi`·`src/backend`·`src/control_plane`은 비어 있는 경로입니다.

---

## 11. 리스크

| 리스크 | 조기 신호 | 대응 |
|---|---|---|
| 자원 경합 (5 DB + DataHub + Trino + 앱) | swap, container restart, indexing 지연 | 프로파일별 peak 측정, full 실패 시 host 분리. **fixture 줄여서 성공 처리 금지** |
| connector·타입·방언 불일치 | driver/type coercion 오류 | DB 버전 고정, catalog 단독·JOIN spike |
| 잘못된 source·column·JOIN | 실행은 되는데 gold 결과 불일치 | DataHub grounding, 승인 JOIN만, Context 제한 |
| SQL 검증기 과소·과대 차단 | negative test 실패 / 정상 질문 거부 증가 | parser 기반 정책, 허용·차단 fixture 양쪽 |
| **gold 세트 제작 병목** | 리뷰 대기, 정답 불일치 | 핵심 산출물로 배정, 역할별 공동 승인 |
| metadata 문제를 파인튜닝으로 덮기 | 데이터 늘려도 같은 JOIN 오류 반복 | baseline 실패 원인부터 분류, Context 고친 뒤 재측정 |
| 계약 동결 지연 | 미확정 상태로 구현 착수 | 승인 전 작성 금지, 미확정은 DRAFT 또는 사유와 함께 기록 |

---

## 12. 헷갈리기 쉬운 것

- **DataHub는 조회 엔진이 아님.** 메타데이터 기준 시스템. 실제 조회는 Trino.
- **DataHub CLI만 돌리고 GMS 끄는 건 불가.** ingestion이 GMS sink를 필요로 함.
- **P1 카탈로그 화면보다 DataHub ingestion·API가 먼저.** 사용자 기능 순서와 기술 의존 순서는 다름.
- **`dev` profile은 개발용이지 수용 시험 대체가 아님.** 전체 통합은 `full`로 판정.
- **모든 Node가 Base 모델을 기준선으로 씀.** LoRA는 채택 Gate 통과 시에만 Node 2·2′에 적용. Node 1·3에는 절대 적용 안 함.
- **합성 데이터에 의도한 패턴이 있어도** 모델이 근거 없이 원인을 단정하면 실패로 분류.
- **자동 CI 통과 = 기계 검증 완료**일 뿐. 제품 수용·계약 Freeze·최종 Gate는 R1이 별도 판정.

---

## 용어

| 용어 | 뜻 |
|---|---|
| **DataHub Core** | 데이터가 어디에 뭐가 있는지를 모아둔 카탈로그. 실제 데이터는 안 들고 있고 "설명서"만 가짐 |
| **Trino** | 여러 DB에 흩어진 데이터를 한 번의 SQL로 조회해주는 엔진. 실제 조회는 여기서 함 |
| **연합 조회** | 데이터를 한군데로 옮기지 않고 각 DB에 그대로 둔 채 조회하는 방식 |
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
| **handoff** | Wave 끝낼 때 다음 역할에 넘기는 결과와 증거 |
| **watermark** | 데이터가 어느 시점까지 반영됐는지 표시하는 값 |
| **idempotency** | 같은 요청이 여러 번 와도 결과가 한 번만 생기는 성질 |
| **immutable** | 승인 뒤 고치지 않고, 바꿀 땐 새 버전을 만드는 방식 |

---

## 참고 문서

| 문서 | 용도 |
|---|---|
| `docs/Answervice_기획서.md` | 전체 기준 |
| `docs/markdown/collaboration/Gate_실행_카드_원장.md` | 실행 권한·상태·허용 경로의 단일 기준 |
| `docs/markdown/ai_docs/5인_병렬구현_0*_매뉴얼_최종안.md` | 역할별 상세 |
| `docs/markdown/02_WBS.md` | 일정·담당·상태 |

---

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.1 | 2026-07-31 12:40 | 문서 성격을 프로젝트 이해 자료로 정리. 진척·현황 서술과 주차별 일정 요약, CI 운영 절차를 제외하고 문제 정의·실행 경로·책임 경계·데이터 구성·범위·성공 정의·단계 기준 중심으로 재구성 |
| v1.0 | 2026-07-31 12:10 | 기획서 v1.2 기준 팀 내부용 요약본 최초 작성 |
