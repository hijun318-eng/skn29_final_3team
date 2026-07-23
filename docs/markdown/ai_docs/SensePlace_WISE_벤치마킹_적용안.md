# SensePlace — WISE·WISE 2.0 벤치마킹 및 적용안

> 검토 기준일: 2026-07-21
> 프로젝트 기준: 최신 로컬 `jaehong` branch, `SensePlace — 호텔 VOC·운영 지원 플랫폼` 공용 계약
> 적용 원칙: 공개 자료 기반 독립 합성 데이터 PoC이며 WISE 복제·연동을 주장하지 않는다.

## 0. 결론

WISE에서 SensePlace가 가져올 것은 매출 BI 기능이 아니라 `직원용 자연어 조회`, `분산 데이터의 관계 정의`, `데이터 적재 후 자동 분석`, `근거를 통한 의사결정 지원`이라는 설계 방향이다. 현재 프로젝트의 `SensePlace` Baseline은 이미 이 방향의 상당 부분을 `보장 intent 8종`, `metric_catalog`, `결정론적 품질 Gate·trigger`, `evidence`, `보고서 DRAFT`, `관리자 결정`으로 반영하고 있다.

따라서 P0에서 새로 필요한 것은 GraphDB·A2A·범용 온톨로지가 아니다. 기존 PostgreSQL 계약에 `VOC 주제 → 서비스 구역 → 운영지표 → 담당 scope`의 versioned 관계를 명시하고, 부정 VOC와 운영지표를 같은 시설·기간으로 정렬해 관측 사실·원인 후보·반대 근거·부족 데이터를 구분하는 것이다.

현재 요구사항에는 P0 경계를 다시 넓힐 수 있는 충돌이 남아 있다. `DAT-007`의 “온톨로지 구축”, `FUN-006`의 개방형 text-to-SQL·멀티에이전트, `AI-006`의 비지도 탐지, `DAT-006·INT-002`의 VectorDB, `3.6·6.7`의 GraphDB·멀티에이전트 제출 작업은 공용 통제 문서의 “Baseline 밖 분리 실험” 원칙에 맞게 의미를 좁혀야 한다. 기존 ID를 재사용하거나 즉시 수정하지 말고 사람 승인 후 문서 간 정합화 작업으로 처리한다.

SensePlace의 권장 포지셔닝은 다음과 같다.

> WISE의 자연어 운영 조회와 데이터 연결 방향을 벤치마킹하되, 공개 자료에서 확인되지 않은 부정 VOC·운영 이슈 진단을 독립 합성 데이터 PoC로 검증한다.

프로젝트 공식 명칭은 현재 활성 작업 문서 기준 `SensePlace — 호텔 VOC·운영 지원 플랫폼`이다. 읽기 전용 보호 문서인 `docs/markdown/final_project/`에는 과거 명칭 `Hotel Signal AI`가 남아 있으므로 원본을 수정하지 않고 후속 승인 대상 불일치로 기록한다.

## 0.1 사람이 판단해야 할 사항

- [x] 활성 작업 문서와 신규 산출물의 공식 명칭을 `SensePlace — 호텔 VOC·운영 지원 플랫폼`으로 통일한다.
  - 결정: 읽기 전용 보호 문서의 과거 명칭은 수정하지 않고 후속 승인 대상 불일치로 관리한다.
- [ ] 프로젝트 포지셔닝을 `WISE 보완형 VOC·운영 분석 독립 PoC`로 설명할지 승인한다.
  - 권장안: 승인. 단, WISE 확장 모듈·공식 연동·납품 후보라는 표현은 금지한다.
- [ ] P0 시맨틱 계층을 PostgreSQL `metric_catalog + versioned topic–metric 관계`로 제한할지 승인한다.
  - 권장안: 승인. Neo4j·OWL·자동 관계 추론·GraphRAG는 제외한다.
- [ ] P0 자연어 조회를 보장 intent 8종으로 제한하고 개방형 text-to-SQL을 P1로 이동할지 승인한다.
  - 권장안: 승인. 첫 vertical slice는 조식 대기 비교 질의 1종으로 검증한다.
- [ ] P0 탐지를 versioned rule만으로 수행하고 비지도 이상탐지는 분리 실험으로 둘지 승인한다.
  - 권장안: 승인. Baseline 재현성과 원인 후보 설명력을 우선한다.
- [ ] 긍정·중립 VOC의 P0 사용 범위를 결정한다.
  - 권장안: 저장·분류 품질·분모 검증에는 유지하되 trigger·원인 후보·우선순위 산정에는 사용하지 않는다. 주간 보고서의 긍정 VOC 섹션은 별도 승인 항목으로 둔다.
- [ ] WISE 공급사 사례 수치를 발표 자료에 포함할지 승인한다.
  - 권장안: 출처와 한계를 붙인 참고 사례로만 포함하고 SensePlace KPI·성과 목표에는 사용하지 않는다.

## 0.2 판단 체크리스트

- [x] 현재 WISE와 WISE 2.0 계획을 구분했다.
- [x] SK네트웍스 공식 발표와 공급사 고객 사례 주장을 분리했다.
- [x] 공개 자료에서 VOC 기능이 확인되지 않는다는 한계를 기록했다.
- [x] SensePlace를 WISE 연동·복제 시스템으로 표현하지 않았다.
- [x] WISE 매출 BI·예측을 P0에 복제하지 않았다.
- [x] P0 시맨틱 계층을 PostgreSQL 관계 정의로 제한했다.
- [x] A2A·GraphDB·OWL·GraphRAG·외부 변수는 P1 또는 실험으로 분리했다.
- [x] `144x`, `99.9%`, `24/7`을 프로젝트 KPI로 전용하지 않았다.
- [x] 합성 데이터·seed·schema version·근거·결정 이력을 유지했다.
- [ ] 프로젝트 명칭, 자연어 질의 범위, 긍정·중립 VOC 사용은 사람 승인이 필요하다.

## 0.3 필수 최소 반영 방향

```text
합성 NEGATIVE VOC
→ topic_code·service_area_id 정규화
→ versioned topic–metric 관계 조회
→ 동일 시설·기간 운영지표 정렬
→ 품질 Gate
→ versioned rule 기반 이상 감지
→ 관측 사실·원인 후보·반대 근거·부족 데이터
→ evidence_id가 연결된 보고서 DRAFT
→ HOTEL_MANAGER 승인·보류·반려
```

P0에 추가할 핵심은 별도 Graph 서비스가 아니라 기존 계약의 빈 연결고리인 `topic–metric 관계의 명시적 version 관리`다.

## 1. 벤치마킹 목적과 범위

### 목표와 완료 조건

- WISE, WISE 2.0, Walkerhill AI Guide, 공급사 사례의 사용자·데이터·기능·근거 수준을 분리한다.
- SensePlace가 가져올 원칙과 가져오지 않을 기능을 P0·P1로 결정한다.
- 기존 요구사항·WBS·화면·백엔드 계약의 영향을 ID 단위로 제시한다.
- 공개되지 않은 내부 구조·schema·성과를 추정하지 않는다.

### 포함 범위

- 공개 웹 자료의 사실 검증
- 기존 프로젝트 기준 문서와의 정합성 검토
- 문서 개정 전 영향 분석과 권장안

### 제외 범위

- WISE 실제 연동, API·DB schema 추정
- 코드, migration, dependency, 외부 API 연결
- GraphDB·A2A runtime 구현
- 실제 호텔 KPI·임계값·운영 성과 확정

### 프롬프트 자체 검토

사용자 제공 프롬프트는 출처 등급, 금지 표현, P0·P1 경계, 문서 영향 범위를 명시했다는 점에서 실행 가능성이 높다. 다만 다음 보완이 필요하다.

1. “기본 결론”을 검증 전 확정값으로 두면 확인 편향이 생길 수 있으므로, 각 결론에 출처·확인일·반증 조건을 연결해야 한다.
2. 공급사 수치의 분모·기간·측정 방식이 없으므로 정확한 성과 비교에는 사용할 수 없다.
3. `ontology-lite`는 물리 구현을 오해하게 할 수 있으므로 프로젝트 용어를 `versioned semantic catalog`로 고정하는 편이 안전하다.
4. 읽기 전용 보호 문서에는 과거 명칭이 남아 있으므로 신규 문서가 이를 현재 공식 명칭으로 오인하지 않도록 구분해야 한다.
5. 현재 공용 통제 문서는 긍정 VOC가 포함된 주간 보고서를 P0 계약으로 두지만 프롬프트는 긍정·중립 활용을 금지한다. 적용 전 사람 결정이 필요하다.

## 2. 확인된 사실·계획·미확인 영역

근거 등급은 `A=SK네트웍스 공식 발표`, `B=공급사 고객 사례`, `C=보조 자료`로 구분한다.

| 항목 | 현재 확인 사실 | 향후 계획 | 공개 미확인 | 등급 |
|---|---|---|---|:---:|
| WISE 사용자 | 워커힐 구성원 | 사용자 확대 여부 미확인 | 실제 역할·권한 구조 | A |
| WISE 데이터 | 객실·레스토랑 등의 매출 데이터 | WISE 2.0에서 F&B·객실·과거 패턴·기상·환율 활용 계획 | 내부 table·schema·품질·보유기간 | A |
| WISE 조회 | 자연어 질문으로 조회·분석 후 답변 | 원인·전망·대응 전략 지원 계획 | 보장 질의 수·Text-to-SQL 구현 방식 | A |
| WISE 효율 | 수동 취합 30~40분을 약 1분 조회로 단축했다는 공식 설명 | 추가 고도화 | 측정 표본·업무 정의·반복 측정 결과 | A |
| WISE VOC | 공개 자료에서 확인되지 않음 | 공개 계획에서 확인되지 않음 | VOC 분석·교차분석·주간 보고·처리 이력 | A 기준 미확인 |
| WISE 2.0 상태 | 2026-04-01 발표 당시 2026년 하반기 도입 계획 | 외부 데이터 기반 매출 증감 원인·전망·전략 | 2026-07-21 현재 완료·운영·성과 | A |
| 온톨로지·A2A | 공급사 사례가 WISE에 적용됐다고 설명 | 공개 계획 미확인 | 공식 아키텍처·protocol·운영 범위 | B |
| POS·멤버십 | 공급사 사례가 분산 데이터를 통합했다고 설명 | 공개 계획 미확인 | 데이터 항목·정합성·권한 | B |
| 매출 예측·전략 | 공급사 사례 설명 | 공식 WISE 2.0 방향과 개념적으로 유사 | 실제 모델·정확도·운영 성과 | B |
| Walkerhill AI Guide | 고객용 다국어 안내, 유형 분석, 6개 레스토랑 예약·조회·취소, 혜택 안내 기능 | 고객 맞춤 기능 고도화 | SensePlace와 데이터·업무 연계 | A |
| 사용자 제공 MP4 2개 | 2026-07-21 HTTP 200, `video/mp4` 접근 가능 | 해당 없음 | 안정적인 자막·측정 정의·독립 검증 자료 | C |

공개 자료가 없다는 것은 기능이 없다는 뜻이 아니다. 이 문서에서는 `확인되지 않음`으로만 기록한다.

## 3. 수치 검증과 주의사항

### 공식 자료

| 수치 | 공식 표현의 범위 | 사용 가능 범위 | 금지 |
|---|---|---|---|
| 30~40분 → 1분 | F&B·객실 매출 데이터를 수동 취합하던 업무와 자연어 조회의 비교 | WISE 도입 사례 설명 | SensePlace 성능 목표·동일 업무 비교 |
| 활성 사용자 3만 명 | AI Guide 도입 1년 성과 | AI Guide 채택 사례 | WISE 사용자 수 또는 SensePlace 목표 |
| FIT 투숙객 3명 중 1명 | AI Guide 이용 흐름 | 고객용 서비스 채택 사례 | 내부 관리자 도구 채택률 추정 |

`30~40분 → 1분`은 산술상 약 30~40배지만 공급사 `144x`와 같은 지표로 계산하지 않는다. 전자는 특정 취합·조회 시간이고 후자는 “Faster decision-making”으로 표기돼 측정 대상이 다르다.

### 공급사 사례

| 수치 | 페이지 표기 | 검증 한계 | SensePlace 처리 |
|---|---|---|---|
| `144x` | Faster decision-making | 기준 업무·기간·표본·산식 없음 | 참고 사례만, KPI 전용 금지 |
| `99.9%` | Real-time POS data reduction | “reduction”의 대상·분모·오류 정의 불명확 | 원문 병기, 정확도·가용성으로 재해석 금지 |
| `24/7` | Automatic data application | 대상 source·지연·장애·운영 수준 미공개 | P0 실시간·무중단 목표로 사용 금지 |

SensePlace KPI는 자체 합성 시나리오에서 별도로 정의한다. 최소 후보는 `동일 input·rule version 재현율`, `근거 연결 완전성`, `보장 intent 정답률`, `권한 위반 SQL 실행 0건`, `중복 batch 중복 incident 0건`, `보고서 초안 작성 시간`이다.

## 4. WISE와 SensePlace 비교

| 비교 항목 | WISE 공개 범위 | WISE 2.0 공개 계획 | SensePlace P0 | SensePlace P1·실험 |
|---|---|---|---|---|
| 주요 사용자 | 워커힐 구성원 | 구성원 | 호텔 내부 관리자·담당 데모 역할 | 실제 조직 mapping 검증 |
| 핵심 데이터 | 객실·레스토랑 매출 | F&B·객실·과거 패턴·기상·환율 | 합성 조식 운영·인력·부정 VOC | 날씨 또는 행사 합성 변수 1종 |
| 자연어 조회 | 매출 데이터 조회·분석 | 원인·전망·전략 지원 | 보장 intent 8종, 첫 slice 1종 | 검증된 개방형 질의 확대 |
| 주요 분석 | 매출 조회 | 매출 증감 원인·전망·전략 | 부정 VOC·운영 동기간 변화 | 검증 시나리오·시설 확대 |
| VOC | 공개 확인 불가 | 공개 확인 불가 | 핵심 분석 대상 | 실데이터 mapping 승인 후 검토 |
| 시맨틱 계층 | 공식 구조 미확인 | 공식 발표는 다양한 데이터 연결 방향 | PostgreSQL catalog·관계 map | Graph 실험은 가치 입증 후 |
| 외부 변수 | 공개 확인 없음 | 기상·환율 등 | schema 확장 가능성만 | 날씨·행사 1종 비교 실험 |
| Agent | 공식 구조 미확인 | 공식 구조 미확인 | 한 workflow의 명시적 단계 | 단일 vs 역할 분리 비교 |
| 자동 분석 | 공급사 24/7 주장 | 공식 세부 미확인 | batch READY 후 rule 실행 | schedule·event source 확대 |
| 결과 형태 | 자연어 답변 | 원인·전망·전략 | 표·차트·evidence·report DRAFT | 보고·질의 종류 확대 |
| 승인 workflow | 공개 확인 불가 | 공개 확인 불가 | 승인·보류·반려·audit | 외부 전달 승인 Gate |
| 데이터 현실성 | 실제 내부 데이터로 설명 | 실제 내부·외부 데이터 계획 | `synthetic only` | 승인된 비식별 sample |
| 범위 제한 | 공개 세부 미확인 | 2026년 하반기 계획 | 조식 대기 대표 시나리오 | 시설·기간·질문 확대 |

## 5. SensePlace 차별화 정의

차별화는 “WISE보다 우수”가 아니라 `공개 범위와 다른 검증 문제`로 정의한다.

```text
NEGATIVE VOC
+ 동일 시설·기간 운영지표
+ 결정론적 품질 Gate·versioned rule
+ 관측 사실·원인 후보·반대 근거·부족 데이터
+ evidence_id·dataset/rule/model version
+ 보고서 DRAFT·관리자 결정·audit
```

### 포함

1. 부정 VOC 주제와 운영지표의 명시적 관계
2. 인과 확정이 아닌 후보·반증·missing data 분리
3. 같은 input과 version에서 같은 수치·signal 재현
4. LLM 실패 시 수치와 evidence 유지
5. 승인 전 자동 조치 금지

### 포함하지 않음

- 매출 예측·전략 BI 복제
- 실제 WISE schema·API·권한 추정
- 고객 예약·추천·개인화·미션
- 직원 개인 평가·자동 인력 배치·자동 보상
- 공급사 수치를 이용한 성과 주장

## 6. P0 ontology-lite 적용안

프로젝트 용어는 `ontology-lite`보다 `versioned semantic catalog`를 권장한다. P0 목적은 지식그래프 구축이 아니라 LLM과 화면이 같은 지표·주제·서비스 구역·권한 정의를 사용하도록 만드는 것이다.

### 6.1 최소 개념

```text
SERVICE_AREA
VOC_TOPIC
VOC_ASPECT
METRIC
ROLE_SCOPE
EXTERNAL_VARIABLE_TYPE  # P0에서는 정의만, 분석 미사용
```

`FACILITY`는 현재 `dim_service_area`, `DEPARTMENT`는 실제 조직으로 오해될 수 있으므로 `ROLE_SCOPE`로 대응한다.

### 6.2 최소 구조

| 구조 | 기존 계약 | P0 결정 | 역할 |
|---|---|---|---|
| `metric_catalog` | 존재 | 유지·필수 | 정의·단위·grain·동의어·source view·version |
| `dim_service_area` | 존재 | 유지·필수 | 합성 서비스 구역 |
| `fact_voc.topic_code` | 존재 | 유지·필수 | VOC 표준 주제 |
| `role_scope` | 존재 | 유지·필수 | 역할별 허용 resource |
| `topic_metric_relation` | 미정 | 최소 추가 후보 | topic·service area·metric·relation type·version |
| `concept_aliases` | `metric_catalog.synonyms` 일부 대응 | 별도 table 생성 보류 | 첫 slice에서 부족할 때만 추가 |
| `external_variable_catalog` | 없음 | P0 table 생성 보류 | P1 schema 설계 시 추가 |

새 table을 무조건 늘리지 않는다. 첫 slice에서 `metric_catalog.synonyms`와 설정 파일 기반 관계 map으로 수용 기준을 충족하면 그 구조를 우선한다. 관계 이력·관리 UI·다중 consumer가 필요해질 때 `topic_metric_relation`을 물리 table로 승격한다.

권장 관계 필드:

```text
relation_id
topic_code
service_area_id
metric_code
relation_type        # OBSERVE_WITH, COMPARE_WITH, OWNED_BY_SCOPE
relation_version
valid_from
valid_to
is_active
rationale
```

### 6.3 P0 관계 예시

```text
VOC_TOPIC: BREAKFAST_WAITING
→ SERVICE_AREA: GW_BREAKFAST_DEMO
→ VOC_ASPECT: WAIT_TIME
→ METRIC: AVG_WAIT_MIN
→ METRIC: P90_WAIT_MIN
→ METRIC: ACTUAL_ARRIVALS
→ METRIC: ACTUAL_HEADCOUNT
→ ROLE_SCOPE: FNB
```

이 관계는 “원인”이 아니라 조회·비교할 후보 지표의 범위를 정의한다.

### 6.4 P1 관계 예시

```text
EXTERNAL_VARIABLE: WEATHER_RAIN
→ RELATION_TYPE: OBSERVE_WITH
→ METRIC: ARRIVAL_CONCENTRATION
→ VOC_TOPIC: BREAKFAST_WAITING
```

날씨가 대기의 원인이라는 규칙으로 사용하지 않는다. 추가 실험에서 같은 기간의 관측 변수로만 사용하며 반대 사례를 함께 평가한다.

## 7. 자연어 조회 벤치마킹 반영

WISE의 자연어 조회 경험은 참고하되 P0를 범용 질의로 확대하지 않는다.

### P0

- 공용 명세의 보장 intent 8종 유지
- 첫 vertical slice 1종 우선
- semantic query plan을 결정론적 schema로 제한
- allowlist view, role scope, SELECT-only, parameter binding, row limit, timeout 적용
- 허용되지 않은 metric·dimension·grain·기간은 SQL 실행 전 거부
- 사용자 입력 raw SQL과 자유형 SQL 직접 실행 금지
- plan, SQL hash, row count, dataset version, evidence 기록

첫 질의:

> 이번 주 조식 대기시간이 지난 4주보다 길어진 시간대를 보여줘.

최소 acceptance:

1. intent·metric·dimension·기간·비교기간이 승인된 plan으로 변환된다.
2. `FNB_MANAGER` scope에서만 허용 view가 조회된다.
3. p90 비가산 재집계가 차단된다.
4. 같은 dataset·질문 normalization·catalog version은 같은 query plan을 만든다.
5. 결과에 기간·단위·표본·timezone·data cutoff·version이 표시된다.

### P1

- 외부 변수 1종 포함 비교 질의
- 보장 intent 확대
- 미지원 질문의 clarification 또는 거절 정책 개선
- 개방형 text-to-SQL은 정답 query set과 SQL Guard 통과율이 확보된 뒤 제한적으로 도입

## 8. Trigger·자동 분석 반영

공급사의 `24/7` 표현을 복제하지 않는다. P0의 자동성은 데이터 batch가 검증된 뒤 단일 versioned rule을 한 번 실행하는 것으로 제한한다.

```text
dataset batch 등록
→ READY
→ 품질 Gate
→ versioned rule 1개
→ idempotency 확인
→ incident 생성
→ evidence 수집
→ report DRAFT
```

### P0 필수

- `dataset_version`, `scenario_id`, `rule_id`, `rule_version` 기록
- `NORMAL`, `BREAKFAST_CONGESTION`, `VOC_ONLY_SPIKE`, `OPS_ONLY_SPIKE`, `MISSING_DATA`, `DUPLICATE_BATCH` 검증
- LLM 없이 trigger 재현
- 동일 idempotency key의 incident·report 중복 생성 금지
- 감지 기준 미충족·표본 부족·근거 충돌 구분

### 확장

- 정기 schedule
- 외부 변수 batch 갱신 trigger
- 실제 source adapter
- event streaming
- 비지도 detector 비교

## 9. Agent 구조 반영

P0는 A2A가 아니라 하나의 명시적 workflow다. LangGraph를 사용하더라도 여러 자율 agent가 아니라 실패·상태·입출력이 분명한 단계로 구현한다.

```text
Query Workflow
Detection Workflow
Incident Evidence Workflow
Report Narrative Workflow
```

### P0 책임

| 단계 | 책임 | LLM 사용 |
|---|---|---:|
| Query plan | 질문을 제한된 plan으로 변환 | 허용, 결정론 검증 필수 |
| Detection | 품질 Gate·threshold·minimum sample | 금지 |
| Evidence | 승인 view에서 수치·VOC evidence 연결 | 검색 계획만 허용 |
| Report | evidence 기반 문장·한계 작성 | 허용 |
| Decision | 승인·보류·반려 | 사람만 |

LLM은 최대 한 번 재생성 후 실패하면 `PARTIAL`로 종료한다. KPI, trigger, 원인 확정, 승인 상태를 결정하지 않는다.

### 분리 실험

단일 Incident workflow와 `계획·조사·작성` 3역할 구성을 같은 fixture로 비교한다.

비교 지표:

- 정답 evidence 회수율
- evidence 누락·잘못된 연결
- latency·token
- 실패율·재현성
- 구현·운영 복잡도

A2A protocol 채택은 이 비교와 보안·감사 요구가 실제 이점을 보일 때만 검토한다.

## 10. Walkerhill AI Guide와 경계

| 항목 | Walkerhill AI Guide | SensePlace |
|---|---|---|
| 사용자 | 호텔 고객 | 합성 역할 기반 내부 관리자·담당자 |
| 목적 | 안내·추천·유형 분석·예약·혜택 확인 | VOC·운영 evidence 검토와 의사결정 지원 |
| 데이터 | 호텔 콘텐츠·고객 질의·예약 관련 정보 | 합성 부정 VOC·조식 운영·인력·metadata |
| 실행 | 6개 레스토랑 예약·조회·취소 등 고객 동작 | 자동 조치 없음, 보고서 결정만 저장 |
| 개인정보 | 별도 고객 서비스 정책 적용 | 실제 고객·직원 정보 생성·사용 금지 |
| 공개 성과 | 활성 사용자 등 공식 발표 존재 | 자체 합성 test 결과만 사용 |

P0 제외:

- 고객 챗봇
- 레스토랑·객실 예약
- 고객 유형·추천·개인화
- 다국어 고객 안내
- 오프라인 미션
- AI Guide 대화 데이터 연계

장기적으로도 AI Guide 데이터는 공개 정책이나 기술 가능성만으로 사용할 수 없다. 별도 목적·법적 근거·보유기간·접근권한·비식별화 승인이 필요하다.

## 11. 최소 아키텍처 영향

기존 경계를 유지한다.

```text
Browser
→ Django
→ Django worker
→ FastAPI
→ PostgreSQL read-only analytics view
→ 선택적 External LLM
```

| 영역 | P0 영향 | 변경하지 않는 것 |
|---|---|---|
| React | 연결 운영지표·표준 주제·서비스 구역·role scope·관계 version 표시 | 별도 온톨로지 탐색 화면 없음 |
| Django | 인증·RBAC·job·report·decision·audit 유지 | AI·SQL 생성 중복 구현 없음 |
| Worker | batch·query orchestration과 idempotency 유지 | 실시간 streaming 없음 |
| FastAPI | semantic plan에서 versioned relation map 참조 | A2A runtime·자율 agent 추가 없음 |
| PostgreSQL | 기존 catalog를 우선 재사용, 관계 version만 최소 보완 | Neo4j·OWL·GraphRAG 없음 |
| LLM | plan 후보·evidence 기반 서술 | KPI·trigger·승인 판단 금지 |

현재 공용 계약은 이 경계를 이미 정의한다. 이번 벤치마킹은 서비스 추가가 아니라 `시맨틱 관계의 이름·version·acceptance`를 더 명확히 하는 변경이다.

## 12. 요구사항 영향 분석

기존 ID의 의미를 즉시 변경하지 않는다. 아래는 승인 후 정합화할 최소 패치 제안이다.

| requirement_id | 현재 내용 요약 | 벤치마킹 영향 | P0 권장 | P1·실험 | acceptance 영향 | 사람 승인 |
|---|---|---|---|---|---|:---:|
| `BIZ-001` | VOC·운영지표 동일 시설·기간 교차분석 | 핵심 차별화 유지 | 부정 VOC 중심 | 시설·변수 확대 | relation version과 정렬 key 검증 추가 | 아니오 |
| `BIZ-002` | 원인 후보·연관 지표·점검 항목 | 강화 | 반대 근거·부족 데이터 분리 | 현장 결과 feedback | 인과 확정 표현 0건 | 아니오 |
| `BIZ-003` | 근거 수치·기간·리뷰 | 강화 | evidence ID·version 필수 | 출처 확대 | evidence 없는 문장 노출 0건 | 아니오 |
| `DAT-002` | 다중 주제 저장 | 경량 시맨틱 연결 필요 | `topic_code` 표준화 | taxonomy 확대 | topic version 추적 | 예 |
| `DAT-004` | 교차분석 이력 | 관계 version 누락 보완 | relation·rule version 기록 | 외부 변수 기록 | 재조회 결과 동일 | 예 |
| `DAT-007` | 온톨로지 구축 | 과대 해석 방지 | versioned semantic catalog | Graph 실험 | GraphDB 없이 질의 grounding 통과 | 예 |
| `FUN-006` | 약 10 intent+개방형 text-to-SQL+멀티에이전트 | P0 과대 | 보장 intent 8종 | 개방형·역할 분리 비교 | intent별 regression 통과 | 예 |
| `FUN-013` | 자동 trigger | `24/7` 복제 금지 | READY batch·rule 1개 | schedule·event 확대 | duplicate 0, LLM 없이 재현 | 예 |
| `AI-003` | 근거 문장 추출 | VOC evidence 강화 | 저장된 합성 원문 span 연결 | 검색 확대 | 생성 근거 금지 | 아니오 |
| `AI-005` | 부정 VOC 계산 | P0 핵심 | 건수·비율·비교기간 | topic 확대 | 분모 0·표본 수 규칙 | 아니오 |
| `AI-006` | 규칙+비지도 탐지 | P0와 실험 분리 | versioned rule | 비지도 비교 | 동일 input 동일 signal | 예 |
| `AI-008` | VOC topic·운영지표 mapping | 핵심 보완 대상 | versioned relation map | 외부 변수 | 미정의 관계는 분석 거부 | 예 |
| `AI-009` | 규칙 기반 원인 후보 | 강화 | 후보·반대·부족 데이터 | rule 확대 | 확정 원인 표현 0건 | 아니오 |
| `AI-010` | 온톨로지 기반 text-to-SQL | 용어·범위 축소 | catalog 기반 보장 intent | 개방형 질의 | Guard·scope·grain 위반 실행 0건 | 예 |
| `INT-001` | LLM 장애 시 통계 유지 | 유지 | `PARTIAL` fallback | provider 비교 | 수치·trigger·evidence 보존 | 아니오 |
| `NFR-003` | 결정론·version | 강화 | relation version 추가 | 외부 변수 version | 재현 test | 아니오 |
| `NFR-005` | 근거·신뢰도·검토 | 강화 | 근거 상태를 개별 표시 | feedback loop | 임의 종합 신뢰도 금지 | 예 |

추가 정합화 대상:

- `DAT-006`, `INT-002`: VectorDB는 Baseline 의존성이 아니라 교육 산출물용 분리 실험으로 표현
- `REQ-F-006`: 긍정 VOC 포함 주간 보고서와 “부정 VOC 중심 P0”의 경계 승인
- `FUN-012`: “온톨로지가 답할 수 있는 질문”을 “승인된 catalog·intent가 답할 수 있는 질문”으로 명확화

새 요구사항 ID는 만들지 않는다. 기존 ID가 해당 의미를 수용할 수 없다고 사람이 결정할 때만 요구사항 정의서에서 새 ID를 발급한다.

## 13. WBS 영향 분석

일정·상태는 이번 검토만으로 변경하지 않는다. 실행 evidence가 없으므로 어떤 구현 task도 완료 처리하지 않는다.

| WBS ID | 현재 task | 최소 영향 | 결정 |
|---|---|---|---|
| `1.7` | Baseline 구조·공통 계약 | 벤치마킹 경계와 금지 주장 반영 | 작업 로그 연결 |
| `2.9` | 온톨로지·시맨틱 레이어 | `metric_catalog + relation map`으로 P0 의미 제한 | 사람 승인 후 명칭·완료 조건 수정 |
| `3.6` | VectorDB·GraphDB 구축 | Baseline과 분리된 VectorDB 실험, GraphDB 필수 아님 | 제출 요건 확인 필요 |
| `5.3` | 이상징후 탐지 규칙 | READY batch·rule 1개·idempotency·반례 추가 | 일정 유지 |
| `5.4` | VOC·운영지표 교차분석 | relation version·반대 근거·부족 데이터 추가 | 일정 유지 |
| `5.7` | FastAPI·LLM·VectorDB 패키징 | VectorDB를 런타임 필수에서 분리 | 사람 승인 후 문구 수정 |
| `5.9` | 능동형 trigger | `24/7`이 아닌 batch event로 완료 조건 제한 | 일정 유지 |
| `6.3` | LangGraph supervisor | 자율 supervisor보다 단일 명시 workflow 우선 | 사람 승인 필요 |
| `6.7` | 멀티에이전트 연동·예외 test | 단일 vs 3역할 비교 실험으로 재정의 | 제출 요건 확인 필요 |
| `6.9` | text-to-SQL | 보장 intent 8종·첫 slice 1종·SQL Guard | 일정 유지 |
| `7.1` | 전체 기능 통합 | P0 경계 회귀 검증 | 일정 유지 |

신규 WBS task는 권장하지 않는다. `topic–metric 관계 version 정의`는 `2.9`, 보장 질의 축소는 `6.9`, batch trigger는 `5.9`에 포함할 수 있다.

## 14. 화면 영향

기존 P0 6화면을 유지하고 새 화면을 만들지 않는다.

### P0 표시 보완

- `연결된 운영지표`
- `표준 VOC 주제`
- `서비스 구역`
- `담당 scope`
- `relation/catalog version`
- `WISE 공개 방향을 참고한 독립 PoC`
- `SYNTHETIC DEMO DATA`

### 화면별 최소 영향

| 화면 | 보완 |
|---|---|
| `P0-010` 운영 홈 | benchmark 수치 대신 자체 dataset·rule 상태 표시 |
| `P0-020` 대화형 분석 | 승인 intent·semantic plan·관계 version·미지원 질문 거절 표시 |
| `P0-030` 이상징후 상세 | batch·rule·표본·비교기간·중복 방지 상태 표시 |
| `P0-040` 이슈 브리프 | 관측 사실·후보·반대 근거·부족 데이터·담당 scope 분리 |
| `P0-050` 주간 보고 | `DRAFT·합성`, evidence·version·결정 이력 유지 |

### 제외

- WISE 매출 조회·예측 화면
- 고객 AI Guide 화면
- Graph 탐색·온톨로지 관리 화면
- Agent 작업 시각화
- 외부 변수 관리 화면
- `144x·99.9%·24/7` 성과 카드

## 15. 프로젝트 문서 최소 개정

이번 벤치마킹 검토에서는 제품 범위·API·데이터 계약을 직접 변경하지 않는다. 작업 추적을 위한 WBS·일일보고 갱신은 계약 변경으로 보지 않으며, 실제 계약 변경은 승인 후 아래 순서로 최소 패치한다.

| 우선 | 문서 | 최소 패치 | 이유 |
|:---:|---|---|---|
| 1 | `docs/markdown/01_요구사항정의서.md` | `DAT-007`, `FUN-006`, `AI-006`, `AI-008`, `AI-010`, `DAT-006`, `INT-002` P0·실험 경계 정합화 | 요구사항 의미·acceptance 원본 |
| 2 | `docs/markdown/02_WBS.md` | 관련 task 명칭·완료 조건만 동기화 | 일정 단일 기준 |
| 3 | `docs/markdown/03_프로젝트기획서.md` | “온톨로지·멀티에이전트·VectorDB 필수” 표현을 Baseline·실험으로 구분 | 프로젝트 범위 설명 |
| 4 | `docs/markdown/05_화면설계서_초안.md` | relation version·지원 intent·미지원 상태 표시 | UI contract |
| 5 | backend·data 공용 계약 | 승인된 relation 필드와 test ID만 추가 | 구현 전 소비자 정합 |

보호 문서인 `docs/markdown/final_project/`는 이번 작업에서 읽기만 했고 수정하지 않았다. 공용 계약 변경이 필요하면 보호 원본을 직접 바꾸지 말고 사용자 승인 후 편집 가능한 작업 문서에서 변경안을 먼저 확정해야 한다.

## 16. 검증 방법과 남은 위험

### 검증 방법

| 검증 | 합격 조건 |
|---|---|
| 출처 구분 | 공식 사실·공식 계획·공급사 주장·미확인을 각 문장에 식별 가능 |
| 금지 주장 검색 | WISE 실제 연동·VOC 기능 확정·내부 schema 추정·공급사 수치 KPI 전용 0건 |
| P0 범위 | GraphDB·A2A·외부 변수·개방형 질의가 Baseline 필수에 없음 |
| 관계 계약 | topic·service area·metric·scope·version을 한 query run에서 추적 가능 |
| 결정론 | 같은 dataset·rule·relation version에서 같은 signal·수치 |
| SQL 안전 | scope·allowlist·grain 위반 SQL 실행 0건 |
| evidence | 사실·수치 문장에 evidence ID가 있고 반대 근거·부족 데이터가 분리됨 |
| Human-in-the-loop | 승인 전 report가 항상 `DRAFT·합성` |

### 남은 위험

1. WISE·WISE 2.0의 내부 VOC 기능과 실제 아키텍처는 공개자료로 확인할 수 없다.
2. 공급사 수치는 측정 정의가 없어 비교 가능성이 낮다.
3. 읽기 전용 보호 문서에는 과거 명칭 `Hotel Signal AI`가 남아 있어 현재 활성 문서와의 명칭 불일치를 별도 승인 전까지 유지해야 한다.
4. 요구사항 문서와 공용 통제 문서의 VectorDB·멀티에이전트·비지도 탐지 범위가 불일치한다.
5. 긍정 VOC 포함 보고와 부정 VOC 중심 P0의 경계를 승인해야 한다.
6. 실제 데이터·조직·권한·임계값이 없으므로 합성 PoC 결과를 워커힐 현황이나 효과로 일반화할 수 없다.

## 17. 출처

### A — SK네트웍스 공식 발표

- [본격 성장 모드 워커힐, 혁신은 지속된다!](https://www.sknetworks.co.kr/pr/news-room/FQNLa2HzABGAbKEz), 2026-04-16: WISE의 구성원용 매출 자연어 조회와 30~40분→1분 설명
- [AI 가이드 론칭 1년 맞아 서비스 고도화](https://www.sknetworks.co.kr/pr/news-room/zt3XSDIDIWdsaAY0), 2026-04-01: AI Guide 기능·이용 성과와 WISE 2.0의 2026년 하반기 계획
- [워커힐 AI 가이드 오픈](https://www.sknetworks.co.kr/pr/news-room/EMVi9WvLXywNf0pj), 2025-04-28: 고객용 AI 안내 서비스의 초기 범위

### B — 공급사 고객 사례

- [Common Computer](https://comcom.ai/), 검토일 2026-07-21
- [Common Computer English](https://comcom.ai/en), 검토일 2026-07-21: WISE의 ontology·A2A·F&B/POS/membership·예측/전략 및 `144x·99.9%·24/7` 표기

### C — 사용자 제공 보조 영상

- [사용자 제공 영상 1](https://framerusercontent.com/assets/ZNMBiKLwG9AQ3qH1rLReh5xfLw.mp4)
- [사용자 제공 영상 2](https://framerusercontent.com/assets/hQAv23r4bbqPKJY6UKCyeO8BE.mp4)

두 영상은 접근 가능 여부만 확인했으며, 안정적인 자막·측정 정의가 없는 보조 자료이므로 본 문서의 독립 사실 근거로 사용하지 않았다.

## 18. 최종 결정

벤치마킹 반영은 가능하다. 단, 승인 없이 기능을 추가하는 방식이 아니라 현재 공용 Baseline을 다음처럼 더 엄격히 제한하는 방식이어야 한다.

```text
WISE에서 참고: 직원용 자연어 조회·데이터 관계화·적재 기반 자동 분석·의사결정 지원
SensePlace가 구현: 합성 부정 VOC·운영지표·결정론·evidence·관리자 결정
P0에서 제외: WISE 매출 BI, A2A, GraphDB, 외부 변수, 범용 text-to-SQL, 고객 AI Guide
```

사람이 시맨틱 관계 물리 구조, 자연어 질의 범위, 긍정·중립 VOC 사용, 분리 실험 제출 범위를 승인한 뒤에만 기존 핵심 문서를 개정한다. 공식 명칭은 신규·활성 작업 문서에서 `SensePlace — 호텔 VOC·운영 지원 플랫폼`을 사용한다.
