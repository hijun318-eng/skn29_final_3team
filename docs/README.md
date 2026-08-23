# Answervice 문서 지도

이 폴더의 제품 기준 문서는 `product/` 아래 네 파일이다. 현재 무엇이 실제 구현됐는지는 문서 순위가 아니라 코드·설정·마이그레이션·런타임 증거로 판정하고 그 결과를 PRD 상태에 반영한다. 문서가 충돌하면 단순히 위 파일이 아래 파일을 모두 덮지 않고, 아래의 필드별 권위를 먼저 적용한다.

1. 사용자의 현재 명시적 결정
2. 제품 목적·사용자·P0/P1/P2 범위는 `docs/product/00_기획서.md`
3. Requirement ID·상태·인수 조건·Release Gate는 `docs/product/01_PRD.md`
4. actor·정상/거부/실패 순서·상태 전이는 `docs/product/02_유저플로우.md`
5. 컴포넌트 책임·신뢰 경계·배포/전환 방식은 `docs/product/03_아키텍처.md`
6. 실제 구현 여부는 현재 코드·설정·마이그레이션·실행 증거
7. `docs/e2e_mvp/source/` 원문과 그 밖의 과거 기획·파생·제출 문서는 참고 근거

현재 사용자의 명시적 결정에 따라 DataHub 책임·API·도입 순서가 기존 v3.4 또는
`docs/product/*`와 충돌하면
[`DataHub_Core_Analysis_Agent_전환전략.md`](reference/DataHub_Core_Analysis_Agent_전환전략.md)의
`FINAL STRATEGY`를 전환 기준으로 우선한다. 이 예외는 PRD Requirement 상태를 자동으로
변경하지 않으며 Phase 0A에서 제품 문서와 동기화한다.

문서와 코드가 다르면 어느 한쪽을 자동으로 정답 처리하지 않는다. 차이를 결함 또는 미검증 상태로 기록하고, 같은 릴리스 후보에서 다시 검증한다.

## 기준 문서

| 문서 | 책임 | 넣지 않는 내용 |
|---|---|---|
| [`product/00_기획서.md`](product/00_기획서.md) | 왜 만들고 누구에게 어떤 가치를 주는지, P0/P1/P2 범위 | API·테이블·클래스 세부 |
| [`product/01_PRD.md`](product/01_PRD.md) | 구현해야 할 사용자 결과, 인수 조건, 현재 판정 | 구현 방법과 과거 작업 일지 |
| [`product/02_유저플로우.md`](product/02_유저플로우.md) | 필수 정상·확인·거부·실패·재사용 흐름 | 컴포넌트 내부 호출 상세 |
| [`product/03_아키텍처.md`](product/03_아키텍처.md) | 현재 구조, P0 목표 구조, 확장 경계와 전환 순서 | 기능 완료 선언 |

## 보조 자료

- 저장소 상위 폴더의 `01_Answervice_PRD_v3.4.md`부터
  `04_Answervice_최종프로젝트_요구사항_대응_5단계검토_v1.1.md`까지는 사용자가 지정한
  v3.4 제품 baseline이다. 현재 진행률 증거는 아니며, DataHub 관련 목표 결정이 충돌하면
  아래 최종 전환 전략과 사용자의 최신 결정을 우선한다.
- `e2e_mvp/source/`: 사용자가 지정한 원문. 이번 재정의의 근거이지만 최신 제품 계약은 아니다.
- `e2e_mvp/derived/`: 과거 시점의 작업 문서와 실행 기록. 현재 성공을 자동 증명하지 않는다.
- `Answervice_기획서.md`: 삭제하지 않고 보존하는 과거 종합 기획서다.
- `reference/Walkerhill_V4.1_SQL_검토.md`: 실행 금지 판정을 포함한 과거 SQL 후보의 읽기 전용 감사 기록이다.
- `reference/P0_실행목표_프롬프트.md`: 이전 기준선에서 파생된 실행 금지 archive다. 새 작업은 저장소 루트 `AGENTS.md`와 제품 기준 문서를 직접 따른다.
- `reference/멀티턴_발화이해_BP_벤치마크.md`: Dialogflow CX, KLUE-DST, CheckList, BFCL, Structured Outputs와 eval BP를 우리 Turn·slot·상태/경로 회귀 계약으로 번역한 참고 자료다. 공개 점수 자체는 제품 Gate가 아니다.
- `reference/Runtime_governance_V4.3_승인검토안.md`: V4.3 serving SQL AST와 컬럼 설명에서 생성한 비권위 DRAFT다. 업무 승인 전에는 DataHub runtime governance로 발행하지 않는다.
- `reference/Runtime_governance_V4.3_업무승인.md`: V4.3 생성식과 동일하게 제한한 통합매출·이벤트·VOC·연회 취소의 업무 승인 기록이다. 실제 발행은 별도의 live check에서 확인한 target·predecessor checksum과 전체 read-back을 요구한다.
- `reference/BI_범용질문_시맨틱_확장설계.md`: 특정 예시 문장이 아닌 범용 BI 질문을 위한 재사용 fact·시맨틱·AnalysisPlan 계약, 현재 검증 증거, 승인·배포 Gate를 정의한다.
- `reference/DataHub_Core_공식사용_BP_조사.md`: DataHub Core v1.7 공식 기능과 현행 구현을 대조한 조사 자료다. 조사 시점의 제안이며 제품 계약이나 live capability 증거는 아니다.
- `reference/DataHub_Core_Analysis_Agent_전환전략.md`: DataHub-first 책임 경계, Analysis 우선 멀티에이전트 확장, API·Search·BM25 정책과 단계별 Gate를 확정한 `FINAL STRATEGY`다. 구현 완료 선언은 아니며 실제 채택 사항은 제품 기준 문서에 동기화해야 한다.
- `reference/DataHub_Core_Analysis_Agent_전환_실행프롬프트.md`: 위 전략을 한 번에 하나의 명시적 Phase/subphase씩 적용하기 위한 `FINAL EXECUTION PROMPT`다. 기본 활성 범위는 Phase 0A이며 Gate 승인 없이 다음 단계로 진행하지 않는다.
- `reference/DataHub_Core_Phase0A_현행정합성감사.md`: v3.4 목표·현재 host·deployed/live·최종 DataHub-first 결정을 분리한 Phase 0A 감사다. 문서 정합성 Gate는 `PASS`이며 당시 제품 기능은 `UNVERIFIED`였다.
- `reference/DataHub_Core_Phase0B_compatibility_evidence_Gate.md`: versioned capability/evidence schema, 제품 release manifest와 7종 객체 binding의 additive migration을 기록한다. 격리 DB upgrade/rollback과 기존 API/MCP 회귀 Gate는 `PASS`이며 실제 runtime 전파는 Phase 1 대상이다.
- `reference/DataHub_Core_Phase1_Conversation_Safety_Gate.md`: mandatory CAS·hash-before-replay·atomic terminal commit·release pin·durable orphan query reconcile의 격리 candidate Gate다. 판정은 `PASS`이며 현재 실행 stack 배포 증거가 아니다.
- `reference/DataHub_Core_Phase2_Search_Gate.md`: bounded DataHub Search와 봉인 한국어 Gold의 Phase 2A·2B `PASS`, 격리 candidate canary·rollback과 `PROMOTE` 판정을 기록한다. 현재 실행 stack의 배포 완료 증거는 아니다.
- `reference/DataHub_Core_Phase3_Capability_Gate.md`: pinned Core v1.7 native Metric·별도 `aiContext`의 `SUPPORTED` 판정과 stable shadow equality·retirement·rollback Phase 3 `PASS`를 기록한다. runtime authority는 활성화하지 않았다.
- `reference/DataHub_Core_Phase4_RuntimeCatalogProjection_Gate.md`: immutable projection·CAS·rollback·7종 receipt와 Report receipt의 격리 live Gate를 기록한다. service account/token cleanup, canonical·membership equality 100%, generation 4 activation과 rollback을 독립 read-back해 Phase 4를 `PASS`로 판정했다.
- `reference/DataHub_Core_Phase5_Node1_Grounding_Gate.md`: bounded DataHub Search로 만든 최소 Node1 context, instruction injection 방어, active release 재결속과 source authority evidence의 격리 Gate를 기록한다. Gold 5/5와 rollback을 통과한 Phase 5 `PASS`이며 현재 stack 배포 증거는 아니다.
- `reference/DataHub_Core_Phase6_Single_Asset_Analysis_Gate.md`: 동일 serving asset의 8개 봉인 AST·실제 Trino 독립 기준 결과, ratio·복수 Metric과 cancel/timeout/empty/schema drift closure, same-release Artifact의 격리 Gate를 기록한다. final generation 10의 Phase 6 `PASS`이며 현재 stack 배포 증거는 아니다.
- `reference/DataHub_Core_Phase7_Bounded_Multi_Turn_Gate.md`: slot provenance, clarification resume, presentation zero-query와 Report action의 bounded multi-turn 격리 Gate를 기록한다. final generation 15의 Phase 7 `PASS`이며 현재 stack 배포 증거는 아니다.
- `reference/DataHub_Core_Phase8_Native_Semantic_Shadow_Gate.md`: pinned Core v1.7 native SemanticModel·field·relationship 표면과 legacy/native equality, 검색·Node 1·SQL·Trino 비회귀 및 rollback을 기록한다. final generation 18의 Phase 8 `PASS`이며 native runtime authority 전환 선언은 아니다.
- `reference/DataHub_Core_Phase9_Multi_Asset_JOIN_Gate.md`: 승인된 many-to-one edge에서 DIRECT_JOIN·PREAGGREGATE·SEMI_JOIN의 SQLGlot AST와 실제 Trino 독립 기준 결과, fail-closed negative와 activation/rollback을 기록한다. final generation 21의 Phase 9 `PASS`이며 현재 stack 배포 증거는 아니다.
- `reference/DataHub_Core_Phase10_P0_Same_Release_Gate.md`: canonical PRD, 승인된 BUSINESS 10·SUPPORT 4 semantic과 P0 Gold 55건을 현재 source/model/migration 및 9개 evidence 축에 결속하고 실제 제품 API에서 2회 반복 평가하는 Phase 10 판정이다. 동적 정본은 `.tmp` seal/eval receipt이며 하나라도 실패하면 `BLOCKED`이고 Phase 11 진입 근거가 아니다.
- `reference/DataHub_Core_Phase0_10_회고_Graph_Foundation_평가.md`: Phase 0A~10의 코드·Gate·실행 증거를 다시 대조하고 Post-P10 Graph Foundation 제안의 수용·보류·기각을 기록한다. Neo4j 필수 도입은 채택하지 않고 유효한 안전 계약만 기존 조건부 경로에 반영했다.
- `architecture/`: 최신 Archify 원본 JSON 4개와 HTML 4개만 유지한다. 모두 showcase 9/9와 1440·1600·1920·2048 containment를 통과했고 1440 light/dark를 수동 확인했다. 이는 그림 품질 `GO`이며 제품 구현 완료 증거는 아니다.
- `reference/Walkerhill_V4.1_SQL_검토.md`와 V4.3 교체 보고서는 삭제된 생성·적재 구현의 역사적 감사 기록이다. 현재 runtime 입력이나 rollback 절차로 실행하지 않는다.
- `daily_reports/`, `deliverables/`, `templates/`: 일지·제출물·양식이다. 제품 요구의 권위 원본이 아니다.

## 상태와 증거 규칙

요구사항 상태는 `NOT_STARTED`, `PARTIAL`, `BLOCKED`, `READY_TO_VERIFY`, `VERIFIED`만 사용한다.

- 코드나 테스트가 있다는 이유만으로 `VERIFIED`로 올리지 않는다.
- `VERIFIED`는 같은 릴리스 후보의 commit, 데이터 릴리스, 모델·정책 버전, 실행 시각과 검증 결과가 연결될 때만 사용한다.
- mock·fixture·fake 기반 테스트는 계약 회귀 증거이지 제품 E2E 증거가 아니다.
- 화면 PNG는 보조 증거다. 실제 HTTP 응답, Trino query ID, 저장된 request/trace/artifact와 연결되지 않으면 실행 증거가 아니다.
- 새 데이터 릴리스로 전환하면 과거 데이터의 금액·행 수·query ID 기반 성공 판정은 새 릴리스에 승계하지 않는다.

## 파일 위생

- 테스트 임시 파일은 OS 임시 디렉터리에 만들고 저장소나 상위 작업 폴더에 남기지 않는다.
- 재현에 필요한 결과만 `docs/`에 요약하고, 대용량 raw 로그·cache·build 결과는 Git에 넣지 않는다.
- 과거 기록은 삭제보다 명확한 상태 표기와 링크를 우선한다.
- 현재 사용자 변경이 있는 파일은 명시적 요청 없이 이동·복원·정리하지 않는다.
