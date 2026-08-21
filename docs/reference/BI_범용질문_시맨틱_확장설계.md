# BI 범용 질문 시맨틱 확장 설계

## 결론과 현재 판정

현재 문제는 질문 문장을 더 많이 하드코딩하면 해결되는 문제가 아니다. 운영 시맨틱 계약이 공개한 지표는 9개, 차원은 3개에 불과하고, 식음 업장·시설·연회장·회원 등급같은 분해 축을 기존 집계 뷰가 잃어버렸다. 또한 현재 요청 계약은 실질적으로 공개 지표 하나와 단일 기간 집계를 중심으로 하므로, 순위·추이·기간 비교·복수 지표·스냅샷을 안전하게 표현하지 못한다.

따라서 해결 단위는 예시 질문이 아니라 다음 네 층이다.

1. 재사용 가능한 fact·snapshot 그레인과 저카디널리티 차원
2. DataHub에서 승인·공개되는 지표·차원·시간·조인 계약
3. 질문을 집계·분해·추이·순위·비교로 표현하는 `AnalysisPlan`
4. 실행 직전 SQLGlot 검증과 Trino 실행, 유형화된 미지원 응답

LLM은 질문을 계획 계약으로 정규화하는 후보 생성기다. 지표 의미, 공개 여부, 필드, grain, 필터 가능성을 LLM이 만들거나 바꾸지 못한다. ML Agent는 향후 예측·이상탐지·원인 후보 점수화처럼 학습된 출력이 필요한 문제에 사용하며, 기본 BI 집계의 정확성을 대체하지 않는다.

## 작업 범위와 추가된 자산

Trino·Iceberg 교체 릴리스와 충돌하지 않도록 기존 13개 운영 뷰를 수정하지 않았다. `walkerhill-bi-serving-v1.20260820.1` 후보는 `serving.analytics_v4_3` 스키마에 새 이름 14개로만 추가했다.

| 영역 | 재사용 그레인 | 보존한 분해 축 |
|---|---|---|
| 객실 | 투숙 1박, 예약 1건, 일·호텔·객실유형 KPI | 객실유형, 예약채널, 세그먼트, 예약상태 |
| 식음 | 주문 1건 | 업장, 업장유형, 시간대, 주문상태 |
| 연회 | 행사 1건, 매출 line 1건 | 연회장, 행사유형, 예약상태 |
| 시설 | 이용·사고 1건, 일·시설 resource | 시설, 시설유형, 이용유형, 사고유형, 심각도 |
| 인력 | 일·호텔·부서·근무조 | 부서, 근무조 |
| 회원 | 최신 데이터 스냅샷의 회원 1명, 포인트 거래 1건 | 회원등급, 회원상태, 거래유형 |
| VOC | 리뷰 1건 | 채널, 접점, 유형, 감성, 주제 |
| 통합매출 | 일·호텔 | 일자, 호텔 |

생성 SQL은 `infrastructure/database/serving_candidates/walkerhill_bi_v1/10_reusable_fact_views.sql`, 재현 검증 SQL은 같은 폴더의 `20_reconciliation_validation.sql`이다. 지표·차원 후보는 `evals/semantic_review/answervice_bi_coverage.v1.json`이며 `REVIEW_REQUIRED`, `runtime_source=false`로 고정했다.

## 실행 검증 결과

2026-08-20 로컬 배포 스택에서 다음을 확인했다.

- SQLGlot Trino dialect가 14개 `CREATE VIEW`와 18개 검증 문을 전부 파싱했다.
- Trino에 14개 신규 뷰를 생성했다.
- 중복 key, 원천-뷰 매출, 영역별 건수, 통합매출 조정을 포함한 18개 검증의 `violation_count`가 모두 0이었다.
- DataHub Trino ingestion이 실패·경고 없이 445개 event를 쓰고 완료되었다. 해당 스키마에 기존 13개와 신규 14개를 합한 27개 뷰의 물리 메타데이터가 수집되었다.
- base ingestion이 기존 51개 runtime dataset의 lifecycle과 표시 identity 일부를 덮어쓴 사실을 live read-back으로 확인했다. 활성 semantic release의 exact manifest·checksum과 Trino comment를 기준으로 해당 aspect만 복구했고, 이후 Backend `/readiness`에서 DataHub transport·semantic release·catalog manifest·Trino schema를 포함한 모든 dependency가 `ready`임을 재검증했다.
- 배포 UI에서 `2026년 7월 예약된 객실 수는?`는 새 분석 3회 연속 무관한 승인 지표 목록 없이 `METRIC_NOT_AVAILABLE` 화면으로 종료되었고, 요청 ID도 노출되지 않았다. `2026년 7월 객실 매출은?`는 6,832,597,250 KRW 결과와 분석 근거를 반환했다. 지표를 실제로 생략한 `2026년 7월은?`만 지표 입력 명확화로 종료되었다.

`operating_revenue_daily_fact` 조정 쿼리는 결과가 0이었지만 Trino가 soft stage 경고(79 stages, 기본 경고 기준 50)를 발생시켰다. 정확성 실패는 아니지만 활성화 전 물리화·부분 집계 또는 계획 단순화 검토가 필요하다.

base ingestion 직후 semantic republish·전체 read-back 없이 Backend를 열면 readiness가 닫히는 운영 위험은 남아 있다. base ingestion과 semantic publication을 하나의 원자적 작업처럼 오인하지 말고, 기존 release aspect 보존 또는 semantic republish를 배포 절차의 필수 단계로 유지해야 한다.

## 운영 계약

### 지표 판정과 승인 경계

질문은 바로 Node 1에 보내지 않는다. Backend가 active DataHub release와 Glossary에서 현재
principal에게 허용된 자산을 lexical·semantic 증거로 먼저 순위화하고, 그 bounded context만
Node 1에 공급한다. 검색 hit가 많으면 단순 top-N으로 잘라 dependency나 JOIN 경로를 끊지 않고,
Metric·Dimension dependency와 승인 경로가 완전한 component를 순위대로 최대 8개 자산까지
편입한다. 각 component 내부는 중간 node까지 entitlement·공통 policy·calendar 계약을
모두 통과해야 한다. 다만 서로 독립적인 component는 같은 calendar인 경우 후보 해석
범위에서 함께 회수할 수 있고, Node 1 선택 후에 실행 subgraph를 다시 계산할 때
공통 policy·JOIN·grain이 없으면 typed semantic error로 닫힌다. 이는 특정 질문 사전이나
질문 정규식이 아니라 active release의 그래프와 계약으로 동작한다.

Node 1은 먼저 승인 용어와 독립적으로 질문에 쓰인 측정 대상의 원문 연속 구간을
`measurement_source_texts`에 질문 순서대로 최대 4개 추출하고, 그 다음 요청 전체의 지표
판정을 `selected`, `ambiguous`, `unsupported`, `missing` 중 하나로 반환한다. 기존
`measurement_source_text`와 `selected_metric_id`는 정확히 한 개일 때만 채우는 호환
projection이다. 서버는 원문 포함 여부와 다음 일관성을 검증하며 모델 출력만으로 실행
권한을 열지 않는다.

- `selected`: 요청한 모든 측정 대상이 승인된 `BUSINESS` 지표 1~4개에 각각 유일하게
  대응하고 `selected_metric_ids`·후보 순서가 일치해야 실행한다.
- `ambiguous`: 승인된 후보가 2개 이상일 때 그 후보만 선택 화면에 노출한다.
- `unsupported`: 측정 개념은 있지만 공개 지표가 없으므로 `METRIC_NOT_AVAILABLE`로 종료하며 전체 지표로 fallback하지 않는다.
- `missing`: 질문에 측정 개념 자체가 없으므로 지표를 입력하도록 명확화를 요청한다.

모델이 `selected`라고 응답하면서 `metric_candidates`와 `selected_metric_ids`를 서로 다르게
반환하면 서버 장애로 처리하거나 임의 지표를 실행하지 않는다. DataHub에서 확인된 BUSINESS
후보만 남기고 선택값은 비운 뒤 typed 지표 명확화로 낮춘다. 반면 후보 밖 ID, 권한 밖 Metric,
연산·의도 불일치처럼 안전하게 명확화할 근거가 없는 계약 위반은 계속 fail-closed로 닫는다.

미지원은 영구 차단을 뜻하지 않는다. 운영 질문에서 드러난 후보는 source field, grain, time semantics, aggregation, dimension binding, permission을 검토한 뒤 새 semantic release의 `BUSINESS` 지표로 승인할 수 있다. 예를 들어 현재 review 후보에는 예약 1건 기준 `room_reservation_count`와 예약 객실박 기준 `booked_room_nights`가 별개로 존재한다. 둘을 `occupied_room_nights`와 임의로 합치지 않고 업무 정의가 승인된 항목만 활성화한다.

### 질문 연산

`AnalysisPlan` active 계약은 다음 연산을 질문 문장이 아니라 구조화된 enum으로 표현한다.

| 연산 | 의미 | 필수 조건 |
|---|---|---|
| `aggregate` | 기간 전체의 합계·평균·건수 | 지표 1~4개, 사건 지표는 기간 |
| `breakdown` | 차원별 분해 | 선택 지표의 source asset에 binding된 차원 |
| `time_trend` | 일·주·월 버킷 추이 | 승인된 time field와 bucket |
| `top_n` / `bottom_n` | 지표 정렬과 N개 제한 | 차원, 1~100의 N, 안정적 tie-breaker |
| `period_comparison` | 두 기간의 값·차이·증감률 | 비교 가능한 지표와 두 완결 기간 |

복수 지표는 기본 4개로 제한하고, 모든 지표가 같은 grain으로 사전 집계되거나 승인된 조인 경로를 가질 때만 하나의 계획에 넣는다. 조건을 만족하지 못하면 LLM에게 임의 JOIN을 허용하지 않고 분리 분석 제안 또는 typed error를 반환한다.

Node 1의 `analysis_operation`과 `result_limit`은 대화 슬롯과 Context fast-path에서도
보존된다. Node 2는 이를 서버 소유 실행 슬롯으로 받으며, SQL Guard는 최종 AST에서
연산별 GROUP BY, 시간 정렬, 순위 방향과 LIMIT을 다시 확인한다. 복수 Metric 설명은
단일 Metric 전용 Node 3에 첫 지표만 넘기지 않고, G3 결과에서 결정론적으로 모든
BUSINESS Metric을 요약한다. Node 2의 `metric_ids`는 SUPPORT 계산 의존성까지 포함하지만
`output_metric_ids`는 사용자가 요청한 BUSINESS Metric만 포함한다. SUPPORT 결과 필드는
검증·reduction 원본에는 남겨도 API table과 chart에서는 제거한다.

### 시간

- 사건·일 지표는 기간이 필요하다. 연도가 생략된 월은 질문의 타임존과 `as_of`의 연도를 쓰되, 완료 기간은 `end_exclusive <= as_of`여야 한다.
- `membership_current_snapshot`같은 스냅샷은 질문에 기간이 없을 때 소스의 `MAX(snapshot_date)`를 쓴다. 배포 시각이나 `CURRENT_DATE`를 쓰지 않는다.
- 기간 필요 여부는 자산 검색 전 문장만 보고 결정하지 않는다. 선택 Metric의 DataHub time mode가
  `range`일 때만 기간을 요구하며, `latest_snapshot`은 서버 `as_of`보다 작은 source time의 최댓값을
  사용한다. 같은 대화의 직전 `range`도 snapshot 질문에 상속하지 않는다.
- 미래 기간, 열린 기간, 해석 불가 기간은 임의 보정하지 않고 기간 오류로 반환한다.

### 차원과 필터

차원 ID는 `outlet`, `facility`, `membership_tier`처럼 업무 개념을 나타내지만 실행 직전에는 반드시 선택 지표의 asset에 속한 실제 필드로 축소해야 한다. 서로 다른 fact의 동명 필드를 단일 전역 field로 간주하지 않는다. 명시된 필터 값은 실제 차원 domain에서 확인하고, 일치하지 않으면 필터를 조용히 버리지 않는다.

## 활성화 순서와 Gate

1. **완료 — 물리 확장:** 신규 14개 뷰 생성, 18개 조정, DataHub 스키마·리니지 수집.
2. **완료 — 안전 런타임 보강:** SUPPORT와 일반 미지원 지표를 전체 BUSINESS 지표 목록으로 잘못 fallback하지 않고 `METRIC_NOT_AVAILABLE`로 구분한다. 지표를 생략한 질문과 여러 승인 지표가 실제로 모호한 질문은 별도로 구분하며, 사용자가 차원을 요청하지 않으면 임의 `GROUP BY`를 생성하지 않는다.
3. **승인 필요 — 시맨틱 후보:** 업무 담당자가 지표 이름·정의·단위·집계·필터·공개 여부를 검토한다. 승인 전에는 DataHub에 검색되더라도 분석 실행 소스가 아니다.
4. **부분 완료 — 계획 계약:** 기존 active runtime v2 release는 유지하고 `ANSWERVICE-ANALYSIS-PLAN-v2`와
   `ANSWERVICE-ANALYSIS-CAPABILITY-v1` sidecar를 추가했다. 14개 후보 뷰의 asset별 dimension/time
   binding 및 최대 4개 Metric·범용 연산을 검증하며, 실제 SQL JOIN은 Metric edge whitelist와
   팬아웃 결정표를 다시 통과해야 한다. Node 1 복수 Metric·연산·result limit 슬롯과
   연산별 SQL AST 검증은 active model release에 반영했다. 추가로 단일 승인 `VIEW_REUSE`의
   집계·분해·추이·순위·기간비교는 `AnalysisPlan`에서 SQLGlot AST로 결정론적으로 생성하며,
   동일 시간·필터 scope의 복수 Metric과 ratio도 같은 G2를 통과해야 실행한다. planning
   capability 전체를 DataHub JSON 문서로 복제하는 방식은 채택하지 않았다. 대신 현재 active
   release의 BUSINESS Metric을 DataHub v1.7 native Metric·Dataset/SchemaField 관계로 투영하는
   check/publish/read-back Gate를 추가했고, SUPPORT·permission·grain·fan-out 정책은 canonical
   execution contract에 유지한다. 실제 live check는 BUSINESS 10개와 native 관계 26개를 계산했지만
   `CHECKED_NOT_PUBLISHED`이며, 미승인 14개 후보와 runtime cutover는 열지 않았다.
   단일 `latest_snapshot`의 typed plan·SQLGlot AST·G2·서버 기준일 binding·G3/API/UI 증거는
   구현했지만 해당 계약을 가진 DataHub release의 publish/read-back과 runtime activation은 아직
   Gate 밖이다. 다중 asset JOIN AST 생성도 승인 edge가 없어 열지 않았다. 2026-08-21 배포 UI의 단일 승인 뷰 집계에서는 실행 trace에 Node 2가
   없고 `typed_sql_compiler`와 G2·Trino·G3가 순서대로 통과했으며, 브라우저 console 오류·경고도
   없었다. 이 smoke 결과를 전체 조합 회귀 통과로 확대 해석하지 않는다.
5. **부분 완료 — catalog-generated structural regression:** 예시 질문을 만들지 않고 SQL checksum에
   결속된 후보에서 단일 Metric×가능 연산×바인딩 차원 1,179건과 모든 BUSINESS Metric pair
   946건을 생성한다. 현재 총 2,125건 중 771건은 구조상 `READY`, 1,354건은 명시적 blocker가
   있다. cross-asset pair 888건은 JOIN 계약이 없어 `JOIN_GRAPH_REQUIRED`이며, time grain·비교
   window·혼합 time mode 조합도 별도 코드로 차단한다. 단일 snapshot 조합 27건은 executor
   capability가 확인되어 기존 time-mode blocker에서 해제됐다. 이 Gate는 Node 1 자연어
   정확도나 실제 결과 정확도를 대신하지 않으며, review-only 후보는 채점할 수 없다.
6. **배포 Gate:** semantic publish check, 명시적 승인, publish, 전체 read-back, backend E2E, 배포 UI Playwright를 같은 release ID에서 통과한다.

후보와 실행 subgraph의 권위 경계는 분리했다. 첫 pass는 실행 filter 값을 요구하거나 Trino schema를
조회하지 않고 권한 있는 후보와 active release checksum receipt를 반환한다. Node 1이 Metric·Dimension을
선택하면 서버가 candidate payload가 아니라 같은 release 전체에서 ratio operand·source asset·공통 허용
JOIN의 유일 최단 경로를 다시 계산하고, 선택 subgraph에 대해서만 node·Metric 권한과 live schema를
검증한다. 병렬 edge 또는 동률 경로는 질문 문구로 추측하지 않고 semantic contract 오류로 닫는다.

Node 1의 실제 선택지는 DataHub Glossary label·alias·definition과 Dataset lexical/semantic rank로
bounded Metric projection을 만든다. ratio operand는 실행 의존성으로 남아도 Node 1 선택지에서는 제외하고,
멀티턴의 확정 Metric은 질문 문자열 보정이 아니라 active release의 Metric→Dataset 관계로 다시 찾는다.
따라서 같은 Dataset의 무관한 Metric 전체를 LLM에 보내는 구조는 제거했지만, 내부 asset recall은 여전히
최대 8개 완전한 dependency component와 Dataset 단위 semantic search를 사용한다.

다음 검색 과제는 DataHub가 지원하는 Glossary Term/native Metric semantic hit를 함께 사용해 Metric
retrieval recall·precision을 catalog-generated case로 측정하는 것이다. 서로 다른 calendar/time mode는
현재 단일 `calendar_id` Node 1 계약에서 섞지 않는다. Metric 선택과 기간 해석을 별도 typed 단계로
분리한 뒤 선택된 Metric들의 호환 시간 계약만 허용해야 한다. dependency를 잘라낸 단순 top-5나 특정
질문별 예외는 추가하지 않는다.

구조 Gate는 다음처럼 읽기 전용으로 재현한다. 기본 출력은 case 전체를 생략한 checksum·집계이며,
상세 감사에만 `--include-cases`를 사용한다.

```powershell
python evals/catalog_regression_runner.py `
  --semantic-candidate evals/semantic_review/answervice_bi_coverage.v1.json `
  --sql-directory infrastructure/database/serving_candidates/walkerhill_bi_v1 `
  --check
```

## 하지 않는 것

- 특정 10개 문장을 질문 패턴이나 정규식으로 매핑하지 않는다.
- 승인되지 않은 SUPPORT 원시 값을 사용자 지표로 바꾸지 않는다.
- 차원이 없는 질문에 모든 사용 가능 차원을 임의로 그룹화하지 않는다.
- 지표의 원인을 GPT가 데이터 근거 없이 서술하지 않는다.
- 시맨틱 승인 전에 후보 JSON을 운영 `runtime_source`로 전환하지 않는다.
