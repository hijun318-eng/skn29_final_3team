# SensePlace — WISE·WISE 2.0 벤치마킹 적용안

| 항목 | 내용 |
|---|---|
| 문서 설명 | WISE 공개 방향을 SensePlace의 호텔 VOC·운영 지원 범위와 비교한 의사결정·구현 기준 문서 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.1 |
| 문서 기준일 | 2026-07-21 16:09 |
| 작성·수정 | 김재홍 |

> 이 문서는 공개 자료를 바탕으로 한 독립 합성 데이터 PoC의 벤치마킹 결과다. WISE의 내부 구조, VOC 기능, 실제 연동 또는 성과를 SensePlace의 사실로 주장하지 않는다.

## 1. 목표와 완료 조건

- WISE·WISE 2.0·Walkerhill AI Guide의 공개 사실과 공급사 주장을 구분한다.
- SensePlace가 참고할 설계 원칙과 P0에서 제외할 기능을 명확히 한다.
- 요구사항·WBS·화면·백엔드 계약에 미치는 영향을 식별한다.
- 공개되지 않은 내부 schema·API·권한·성과는 추정하지 않는다.

## 2. 결론

[결정] SensePlace가 참고할 핵심은 매출 BI 복제가 아니라 다음 네 가지 방향이다.

1. 직원이 자연어로 운영 데이터를 조회하는 경험
2. 분산된 데이터의 관계와 용어를 일관되게 정의하는 방식
3. 검증된 데이터 적재 후 분석을 실행하는 흐름
4. 수치와 근거를 연결해 관리자의 판단을 지원하는 방식

[결정] P0에서는 GraphDB·A2A·범용 온톨로지를 도입하지 않는다. PostgreSQL의 `metric_catalog`와 versioned topic–metric 관계를 이용해 VOC 주제, 서비스 구역, 운영지표, 역할 scope를 연결한다.

[결정] SensePlace의 권장 설명은 다음과 같다.

> WISE의 자연어 운영 조회와 데이터 연결 방향을 벤치마킹하되, 공개 자료에서 확인되지 않은 부정 VOC·운영 이슈 진단을 독립 합성 데이터 PoC로 검증한다.

## 3. 확인된 사실·계획·한계

근거 등급은 `A=SK네트웍스 공식 발표`, `B=공급사 고객 사례`로 구분한다.

| 항목 | 확인 내용 | 공개 미확인 또는 한계 | 등급 |
|---|---|---|:---:|
| WISE 사용자 | 워커힐 구성원이 자연어로 운영 데이터를 조회·분석한다. | 실제 역할·권한 구조 | A |
| WISE 데이터 | 객실·레스토랑 등의 매출 데이터가 공개 설명의 중심이다. | 내부 table·schema·품질·보유기간 | A |
| WISE 효율 | 수동 취합 30~40분을 약 1분 조회로 단축했다는 공식 설명이 있다. | 표본·업무 정의·반복 측정 결과 | A |
| WISE 2.0 | 2026년 하반기 도입 계획으로 F&B·객실·과거 패턴·기상·환율을 활용한 원인·전망·전략 지원이 소개됐다. | 2026-07-21 현재 완료·운영·성과 | A |
| WISE VOC | 공개 자료에서 VOC 원문 분석·교차분석·처리 이력을 확인하지 못했다. | 실제 VOC 기능과 내부 연동 | A 기준 미확인 |
| ontology·A2A | 공급사 사례가 WISE 적용 요소로 설명한다. | 공식 아키텍처·protocol·운영 범위 | B |
| POS·membership·예측 | 공급사 사례가 분산 데이터 통합과 예측·전략을 설명한다. | 데이터 항목·정합성·모델·실제 성과 | B |
| Walkerhill AI Guide | 고객용 다국어 안내, 고객 유형 분석, 6개 레스토랑 예약·조회·취소, 혜택 안내 기능이 공개됐다. | SensePlace와의 데이터·업무 연계 | A |
| 프로젝트 데이터 | 호텔 실데이터 확보 전까지 전량 합성 데이터를 사용한다. | 실제 조직·권한·임계값 | 프로젝트 기준 |

공개 자료가 없다는 것은 기능이 없다는 뜻이 아니다. 이 문서에서는 확인되지 않은 영역을 `미확인`으로만 기록한다.

### 3.1 수치 사용 원칙

| 수치 | 사용 가능 범위 | 금지 사항 |
|---|---|---|
| 30~40분 → 약 1분 | SK네트웍스가 설명한 WISE 업무 사례 | SensePlace 성능 목표나 보장값으로 전용 |
| `144x`, `99.9%`, `24/7` | 출처와 한계를 붙인 공급사 참고 사례 | 독립 검증된 KPI처럼 표현하거나 SensePlace 성과와 직접 비교 |

공급사 수치는 분모·기간·측정 정의가 공개되지 않았으므로 프로젝트 KPI와 수용 기준에 사용하지 않는다.

## 4. WISE·AI Guide와 SensePlace 비교

| 비교 기준 | WISE 공개 방향 | Walkerhill AI Guide | SensePlace P0 |
|---|---|---|---|
| 주요 사용자 | 호텔 구성원 | 호텔 고객 | 호텔 운영 관리자와 역할별 실무 관리자 |
| 주요 목적 | 매출 중심 운영 조회·분석 | 안내·추천·예약·혜택 확인 | 부정 VOC·운영 이슈의 근거 검토와 의사결정 지원 |
| 주요 데이터 | 객실·레스토랑 매출 중심 공개 설명 | 호텔 콘텐츠·고객 질의·예약 관련 정보 | 합성 부정 VOC와 합성 운영지표 |
| 질문 범위 | 자연어 운영 조회 | 고객 서비스 질의 | 승인된 intent와 허용 metric·dimension |
| 계산 | 공개 내부 방식 미확인 | 공개 내부 방식 미확인 | SQL·Python 기반 결정론적 계산 |
| 설명 | 자연어 조회·분석 | 고객 응답 | evidence 기반 설명, LLM 실행당 최대 1회 |
| 실행·결정 | 공개 상세 workflow 미확인 | 예약·조회·취소 등 고객 동작 | 자동 조치 없이 보고서 `DRAFT`와 관리자 결정 저장 |
| 데이터 경계 | 공개 자료 범위만 확인 | 별도 고객 서비스 정책 적용 | 합성 표시, 실제 고객·직원 정보 사용 금지 |

Walkerhill AI Guide 데이터는 공개된 기능만으로 SensePlace에 사용할 수 없다. 장기 연계 검토에도 목적·법적 근거·보유기간·접근권한·비식별화 승인이 선행되어야 한다.

## 5. P0 적용 설계

### 5.1 Versioned semantic catalog

[결정] `ontology-lite` 대신 `versioned semantic catalog`를 프로젝트 용어로 사용한다. 목적은 지식그래프 구축이 아니라 Django, FastAPI, SQL, 화면이 같은 지표와 관계 정의를 사용하도록 하는 것이다.

| 구성 | 최소 내용 | P0 처리 |
|---|---|---|
| `metric_catalog` | 지표 코드, 정의, 단위, grain, 허용 dimension, source view, version | 기존 계약 재사용 |
| `topic_catalog` | VOC 주제 코드, 설명, 상위 주제, version | 표준 주제 관리 |
| `dim_service_area` | 합성 서비스 구역과 식별자 | 기존 계약 재사용 |
| `topic_metric_relation` | topic, service area, metric, relation type, version | 설정 기반 relation map 우선, 필요 시 table 승격 |
| `role_scope` | 역할별 허용 metric, dimension, view | 기존 권한 계약 재사용 |

필수 추적 정보는 `dataset_version`, `catalog_version`, `relation_version`, `rule_version`, `prompt_version`이다.

첫 vertical slice에서는 `metric_catalog.synonyms`와 versioned 설정 파일로 수용 기준을 충족할 수 있으면 이를 우선한다. 관계 이력, 관리 UI 또는 다중 consumer 요구가 생길 때만 `topic_metric_relation`을 물리 table로 승격한다.

권장 관계 필드는 다음과 같다.

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

관계는 원인을 확정하지 않고 조회·비교할 후보 지표의 범위만 정의한다.

```text
VOC_TOPIC: BREAKFAST_WAITING
→ SERVICE_AREA: GW_BREAKFAST_DEMO
→ METRIC: AVG_WAIT_MIN, P90_WAIT_MIN, ACTUAL_ARRIVALS, ACTUAL_HEADCOUNT
→ ROLE_SCOPE: FNB
```

### 5.2 최소 분석 흐름

```text
합성 NEGATIVE VOC
→ topic_code·service_area_id 정규화
→ versioned topic–metric 관계 조회
→ 동일 시설·기간 운영지표 정렬
→ 적재 후 품질 Gate
→ versioned rule 기반 이상 감지
→ 관측 사실·원인 후보·반대 근거·부족 데이터 분리
→ evidence_id가 연결된 보고서 DRAFT
→ HOTEL_MANAGER 승인·보류·반려
```

### 5.3 자연어 조회

- P0 질문은 요구사항에서 보장한 intent 8종으로 제한하고 핵심 4종을 우선 E2E 연결한다.
- 첫 vertical slice는 조식 대기 비교 질의 1종으로 검증한다.
- LLM은 질문을 semantic plan으로 해석할 수 있지만 raw SQL을 직접 실행하지 않는다.
- SQL builder는 허용 view·metric·dimension·grain·scope, parameter binding, row limit, timeout을 적용한다.
- 결과에는 기간, 단위, 표본, timezone, data cutoff와 version을 표시한다.
- 미지원 질문은 추측하지 않고 `UNSUPPORTED_QUESTION` 등 합의된 상태로 거절한다.

첫 질의 예시는 다음과 같다.

> 이번 주 조식 대기시간이 지난 4주보다 길어진 시간대를 보여줘.

| 수용 기준 | 합격 조건 |
|---|---|
| semantic plan | intent·metric·dimension·기간·비교기간이 승인된 plan으로 변환된다. |
| 역할 범위 | `FNB_MANAGER` scope에서 허용된 view만 조회한다. |
| 집계 안전 | p90 등 비가산 지표의 잘못된 재집계를 차단한다. |
| 재현성 | 같은 dataset·질문 normalization·catalog version에서 같은 plan을 만든다. |
| 결과 맥락 | 기간·단위·표본·timezone·data cutoff·version을 표시한다. |

### 5.4 Trigger와 근거

P0의 자동성은 검증된 합성 batch에 versioned rule을 실행하는 범위로 제한한다.

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

- `dataset_version`, `scenario_id`, `rule_id`, `rule_version`을 기록한다.
- `NORMAL`, `BREAKFAST_CONGESTION`, `VOC_ONLY_SPIKE`, `OPS_ONLY_SPIKE`, `MISSING_DATA`, `DUPLICATE_BATCH`를 검증한다.
- 동일 dataset·rule·relation version은 같은 signal과 수치를 만들어야 한다.
- 동일 idempotency key로 incident·report를 중복 생성하지 않는다.
- 원인 후보, 반대 근거, 부족 데이터는 별도 필드로 반환한다.
- 수치·사실 문장은 `evidence_id`로 역추적할 수 있어야 한다.
- 관리자 승인 전 보고서는 항상 `DRAFT·합성`으로 표시한다.

### 5.5 Agent와 LLM 경계

P0는 A2A가 아니라 하나의 명시적 workflow로 구현한다. LangGraph를 사용하더라도 자율 Agent 집합이 아니라 실패·상태·입출력이 분명한 단계로 제한한다.

| 단계 | 책임 | LLM 사용 |
|---|---|:---:|
| Query plan | 질문을 제한된 plan으로 변환 | 허용, 결정론 검증 필수 |
| Detection | 품질 Gate·threshold·minimum sample | 금지 |
| Evidence | 승인 view에서 수치·VOC evidence 연결 | 검색 계획만 허용 |
| Report | evidence 기반 문장과 한계 작성 | 허용 |
| Decision | 승인·보류·반려 | 사람만 |

LLM은 최대 한 번 재생성 후 실패하면 `PARTIAL`로 종료한다. KPI, trigger, 원인 확정, 승인 상태를 결정하지 않는다.

## 6. 범위 구분

| 구분 | 포함 항목 |
|---|---|
| P0 | PostgreSQL semantic catalog, 승인 intent, read-only SQL, rule 기반 감지, evidence, 보고서 DRAFT, 관리자 결정 |
| 독립 실험 | pgvector 유사 VOC 검색, sLLM 비교, 단일·다역할 Agent 비교, 비지도 탐지 비교 |
| P1 후보 | 추가 intent, 외부 변수, STT, 운영 관측성 강화 |
| 범위 밖 | WISE 실제 연동 주장, A2A 운영망, GraphDB 필수화, 실제 PMS·POS·CRM 직접 연결, 고객 AI Guide, 자동 조치 |

독립 실험은 Baseline 실행 경로와 dependency를 분리하고 Gate 통과 조건으로 사용하지 않는다.

## 7. 시스템·문서 영향

### 7.1 최소 아키텍처 영향

기존 `Browser → Django → Django worker → FastAPI → PostgreSQL read-only analytics view → 선택적 External LLM` 경계를 유지한다.

| 영역 | P0 영향 | 변경하지 않는 것 |
|---|---|---|
| React | 연결 운영지표·표준 주제·서비스 구역·scope·relation version 표시 | 별도 온톨로지 탐색 화면 없음 |
| Django | 인증·RBAC·job·report·decision·audit 유지 | AI·SQL 생성 중복 구현 없음 |
| Worker | batch·query orchestration과 idempotency 유지 | 실시간 streaming 없음 |
| FastAPI | semantic plan에서 versioned relation map 참조 | A2A runtime·자율 Agent 추가 없음 |
| PostgreSQL | 기존 catalog 우선 재사용, 관계 version만 최소 보완 | Neo4j·OWL·GraphRAG 없음 |
| LLM | plan 후보·evidence 기반 서술 | KPI·trigger·승인 판단 금지 |

### 7.2 요구사항 영향

기존 ID의 의미와 우선순위는 사람 승인 없이 변경하지 않는다.

| requirement_id | P0 권장 | P1·실험 또는 확인 사항 |
|---|---|---|
| `DAT-007` | versioned semantic catalog로 의미 제한 | Graph 실험은 별도 승인 |
| `FUN-006` | 보장 intent 8종, 핵심 4종 우선 E2E | 개방형 text-to-SQL·다역할 비교 분리 |
| `FUN-013` | READY batch·versioned rule 1개 | schedule·event 확대 |
| `AI-006` | versioned rule | 비지도 탐지 비교 |
| `AI-008` | versioned relation map | 외부 변수 관계 |
| `AI-010` | catalog 기반 보장 intent | 개방형 질의 |
| `DAT-006`, `INT-002` | Baseline 의존성에서 VectorDB 제외 | 교육 산출물용 독립 실험 범위 확인 |
| `REQ-F-006` | 부정 VOC 중심 P0 | 긍정 VOC 포함 보고 범위 승인 필요 |

### 7.3 WBS와 화면 영향

- `2.9`: `metric_catalog + relation map`으로 P0 의미를 제한한다.
- `5.3`, `5.4`, `5.9`: READY batch, rule version, idempotency, 반대 근거와 부족 데이터를 수용 기준에 연결한다.
- `6.3`, `6.7`: 단일 명시 workflow를 우선하고 다역할 Agent는 비교 실험으로 둔다.
- `6.9`: 보장 intent 8종, 핵심 4종 우선 E2E, SQL Guard를 적용한다.
- 기존 P0 화면 수는 늘리지 않고 relation version, 기간·단위·표본, `DRAFT·합성`, 미지원 질문 상태만 보완한다.

신규 WBS task나 화면은 추가하지 않는다. 일정·상태도 구현 evidence 없이 변경하지 않는다.

## 8. 사람이 결정해야 할 사항

- [ ] P0 시맨틱 계층을 PostgreSQL `metric_catalog + versioned topic–metric 관계`로 제한할지 승인한다.
- [ ] 관계 map을 설정으로 시작하고 이력·다중 consumer가 필요할 때 table로 승격할지 승인한다.
- [ ] P0 질문을 보장 intent 8종으로 제한하고 개방형 text-to-SQL을 제외할지 승인한다.
- [ ] P0 감지를 versioned rule로 제한하고 비지도 탐지를 독립 실험으로 둘지 승인한다.
- [ ] 긍정·중립 VOC를 저장·품질 검증까지만 사용할지 결정한다.
- [ ] VectorDB·다역할 Agent 비교의 교육 산출물 범위를 결정한다.
- [ ] 공급사 수치를 발표 자료의 참고 사례로 사용할지 결정한다.
- [ ] WISE와의 중복·보완·연계 가능성을 실제 담당자에게 확인할지 결정한다.

## 9. 검증 방법

| 검증 | 합격 조건 |
|---|---|
| 근거 구분 | 공식 사실·계획·공급사 주장·미확인을 식별할 수 있다. |
| 금지 주장 | WISE 실제 연동·VOC 기능 확정·내부 schema 추정이 없다. |
| P0 범위 | GraphDB·A2A·외부 변수·개방형 질의가 필수 경로에 없다. |
| 관계 추적 | topic·service area·metric·scope·version을 한 실행에서 추적할 수 있다. |
| 결정론 | 같은 dataset·rule·relation version에서 같은 signal·수치를 만든다. |
| SQL 안전 | scope·allowlist·grain 위반 SQL 실행이 0건이다. |
| evidence | 사실·수치 문장에 evidence ID가 있고 반대 근거·부족 데이터가 분리된다. |
| Human-in-the-loop | 승인 전 report가 항상 `DRAFT·합성`이다. |

## 10. 남은 위험

1. WISE·WISE 2.0의 내부 VOC 기능과 실제 아키텍처는 공개 자료로 확인할 수 없다.
2. 공급사 수치는 측정 정의가 없어 프로젝트 성능과 직접 비교할 수 없다.
3. 실제 조직·권한·임계값이 없어 합성 PoC 결과를 호텔 현황이나 효과로 일반화할 수 없다.
4. semantic catalog 물리 구조, intent 범위, 긍정·중립 VOC 사용은 사람의 승인이 남아 있다.
5. 요구사항 문서의 VectorDB·멀티에이전트·비지도 탐지 범위는 Baseline·실험 경계와 추가 정합화가 필요하다.

## 11. 출처

### A — SK네트웍스 공식 발표

- [본격 성장 모드 워커힐, 혁신은 지속된다!](https://www.sknetworks.co.kr/pr/news-room/FQNLa2HzABGAbKEz), 2026-04-16
- [AI 가이드 론칭 1년 맞아 서비스 고도화](https://www.sknetworks.co.kr/pr/news-room/zt3XSDIDIWdsaAY0), 2026-04-01
- [워커힐 AI 가이드 오픈](https://www.sknetworks.co.kr/pr/news-room/EMVi9WvLXywNf0pj), 2025-04-28

### B — 공급사 고객 사례

- [Common Computer](https://comcom.ai/), 검토일 2026-07-21
- [Common Computer English](https://comcom.ai/en), 검토일 2026-07-21

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.1 | 2026-07-21 16:09 | 중복 상세본의 검증 근거·수용 기준·영향 분석을 선별 통합하고 단일 기준 문서로 최적화 |
| v1.0 | 2026-07-21 15:24 | 보호 기준 자료를 바탕으로 WISE 공개 사실·적용 범위·결정 항목을 편집 가능한 일반 문서로 정리 |
