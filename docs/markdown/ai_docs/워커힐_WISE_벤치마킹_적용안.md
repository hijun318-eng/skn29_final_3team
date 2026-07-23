# SensePlace — WISE·WISE 2.0 벤치마킹 적용안

| 항목 | 내용 |
|---|---|
| 문서 설명 | WISE 공개 방향을 SensePlace의 호텔 VOC·운영 지원 범위와 비교한 의사결정용 작업 문서 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-07-21 15:24 |
| 작성·수정 | 김재홍 |

> 이 문서는 공개 자료를 바탕으로 한 독립 합성 데이터 PoC의 벤치마킹 결과다. WISE의 내부 구조, VOC 기능, 실제 연동 또는 성과를 SensePlace의 사실로 주장하지 않는다.

## 1. 목표와 완료 조건

- WISE와 WISE 2.0의 공개된 사실, 계획, 공급사 주장을 구분한다.
- SensePlace가 참고할 설계 원칙과 P0에서 제외할 기능을 명확히 한다.
- 기존 요구사항·WBS·FastAPI 경계에 미치는 영향을 식별한다.
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

## 3. 확인된 사실과 한계

| 구분 | 확인 내용 | SensePlace 적용 원칙 |
|---|---|---|
| [확인된 사실] WISE | SK네트웍스 공개 자료는 객실·레스토랑 매출 데이터를 구성원이 자연어로 조회·분석하는 서비스를 설명한다. | 직원용 자연어 조회와 데이터 관계화 방향만 참고한다. |
| [확인된 사실] WISE 2.0 | 2026년 하반기 고도화 계획으로 소개됐다. | 계획과 완료·운영 상태를 구분한다. |
| [추가 확인 필요] VOC 기능 | 공개 자료만으로 VOC 원문 분석, 처리 이력, 내부 API·권한 구조는 확인되지 않는다. | WISE에 VOC 기능이 있다고 단정하지 않는다. |
| [제안] 공급사 사례 | ontology·A2A·예측과 성능 수치는 공급사 설명이다. | 출처와 측정 한계를 붙인 참고 사례로만 사용한다. |
| [확인된 사실] 프로젝트 데이터 | 호텔 실데이터 확보 전까지 전량 합성 데이터만 사용한다. | `synthetic`, seed, schema version을 결과와 근거에 남긴다. |

공급사에 표시된 `144x`, `99.9%`, `24/7`은 측정 정의와 독립 검증이 확인되지 않았으므로 SensePlace의 KPI나 목표치로 전용하지 않는다.

## 4. WISE와 SensePlace 비교

| 비교 기준 | WISE 공개 방향 | SensePlace P0 |
|---|---|---|
| 주요 사용자 | 호텔 구성원 | 호텔 운영 관리자와 역할별 실무 관리자 |
| 주요 데이터 | 객실·레스토랑 매출 중심 공개 설명 | 합성 부정 VOC와 합성 운영지표 |
| 질문 범위 | 자연어 운영 조회 | 승인된 intent와 허용 metric·dimension |
| 관계 정의 | 데이터 관계화 방향 | `metric_catalog`와 versioned relation map |
| 계산 | 공개 내부 방식 미확인 | SQL·Python 기반 결정론적 계산 |
| 설명 | 자연어 조회·분석 | evidence 기반 설명, LLM 실행당 최대 1회 |
| 의사결정 | 공개 상세 workflow 미확인 | 보고서 `DRAFT`와 승인·보류·반려 이력 |
| 데이터 경계 | 공개 자료 범위만 확인 | 합성 표시, 실제 고객 데이터 사용 금지 |

## 5. P0 적용 범위

### 5.1 Versioned semantic catalog

[결정] `ontology-lite` 대신 `versioned semantic catalog`를 프로젝트 용어로 사용한다. 목적은 지식그래프 구축이 아니라 Django, FastAPI, SQL, 화면이 같은 지표와 관계 정의를 사용하도록 하는 것이다.

| 구성 | 최소 내용 |
|---|---|
| `metric_catalog` | 지표 코드, 정의, 단위, grain, 허용 dimension, source view, version |
| `topic_catalog` | VOC 주제 코드, 설명, 상위 주제, version |
| `service_area` | 서비스 구역 코드와 조직 scope 연결 |
| `topic_metric_relation` | topic, service area, metric, relation type, version |
| `role_scope` | 역할별 허용 metric, dimension, view |

필수 추적 정보는 `dataset_version`, `catalog_version`, `relation_version`, `rule_version`, `prompt_version`이다.

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

- P0 질문은 요구사항에서 보장한 intent로 제한한다.
- 핵심 4종을 우선 E2E로 연결하고 나머지는 같은 계약으로 확장한다.
- LLM은 질문을 semantic plan으로 해석할 수 있지만 raw SQL을 직접 실행하지 않는다.
- SQL builder는 허용 view·metric·dimension·grain·scope만 사용한다.
- 결과에는 기간, 단위, 표본, timezone, data cutoff와 version을 표시한다.
- 미지원 질문은 추측하지 않고 `UNSUPPORTED_QUESTION` 등 합의된 상태로 거절한다.

### 5.4 Trigger와 근거

- 자동성은 검증된 합성 batch에 versioned rule을 실행하는 범위로 제한한다.
- 동일 dataset·rule·relation version은 같은 signal과 수치를 만들어야 한다.
- 원인 후보와 반대 근거, 부족 데이터는 별도 필드로 반환한다.
- 수치·사실 문장은 `evidence_id`로 역추적할 수 있어야 한다.
- 관리자 승인 전 보고서는 항상 `DRAFT·합성`으로 표시한다.

## 6. P0·실험·범위 밖 구분

| 구분 | 포함 항목 |
|---|---|
| P0 | PostgreSQL semantic catalog, 승인 intent, read-only SQL, rule 기반 감지, evidence, 보고서 DRAFT, 관리자 결정 |
| 독립 실험 | pgvector 유사 VOC 검색, sLLM 비교, 단일·다역할 Agent 비교, 비지도 탐지 비교 |
| P1 후보 | 추가 intent, 외부 변수, STT, 운영 관측성 강화 |
| 범위 밖 | WISE 실제 연동 주장, A2A 운영망, GraphDB 필수화, 실제 PMS·POS·CRM 직접 연결, 자동 조치 |

독립 실험은 Baseline 실행 경로와 dependency를 분리하고 Gate 통과 조건으로 사용하지 않는다.

## 7. 기존 문서와 작업 영향

| 대상 | 반영 또는 확인 내용 | 처리 원칙 |
|---|---|---|
| `01_요구사항정의서.md` | 자연어 질의 범위, semantic catalog, 실험 범위 | 사람 승인 없이 requirement ID·우선순위를 바꾸지 않는다. |
| `02_WBS.md` | `2.9`, `3.6`, `6.9`의 완료 조건 | 신규 WBS를 만들지 않고 기존 작업에 연결한다. |
| `03_프로젝트기획서.md` | WISE와 SensePlace의 차별화·비목표 | 공개 사실과 프로젝트 제안을 구분한다. |
| `05_화면설계서_초안.md` | relation version, 기간·단위, 미지원 상태 | 화면 계약 변경은 요구사항 승인 후 반영한다. |
| FastAPI 연동 문서 | catalog·scope·version 전달 | 내부 API 상세 schema는 구현 전에 확정한다. |

## 8. 사람이 결정해야 할 사항

- [ ] P0 시맨틱 계층을 PostgreSQL `metric_catalog + versioned topic–metric 관계`로 제한할지 승인한다.
- [ ] P0 질문을 보장 intent로 제한하고 개방형 text-to-SQL을 제외할지 승인한다.
- [ ] P0 감지를 versioned rule로 제한하고 비지도 탐지를 독립 실험으로 둘지 승인한다.
- [ ] 긍정·중립 VOC를 저장·품질 검증까지만 사용할지 결정한다.
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
| 안전 | scope·allowlist·grain 위반 SQL 실행이 0건이다. |
| Human-in-the-loop | 승인 전 report가 `DRAFT·합성`이다. |

## 10. 남은 위험

1. WISE·WISE 2.0의 내부 VOC 기능과 실제 아키텍처는 공개 자료로 확인할 수 없다.
2. 공급사 수치는 측정 정의가 없어 프로젝트 성능과 직접 비교할 수 없다.
3. 실제 조직·권한·임계값이 없어 합성 PoC 결과를 호텔 현황이나 효과로 일반화할 수 없다.
4. semantic catalog, intent 범위, 긍정·중립 VOC 사용은 사람의 승인이 남아 있다.

## 11. 출처

- [SK네트웍스, 본격 성장 모드 워커힐, 혁신은 지속된다!](https://www.sknetworks.co.kr/pr/news-room/FQNLa2HzABGAbKEz), 2026-04-16
- [SK네트웍스, AI 가이드 론칭 1년 맞아 서비스 고도화](https://www.sknetworks.co.kr/pr/news-room/zt3XSDIDIWdsaAY0), 2026-04-01
- [SK네트웍스, 워커힐 AI 가이드 오픈](https://www.sknetworks.co.kr/pr/news-room/EMVi9WvLXywNf0pj), 2025-04-28
- [Common Computer](https://comcom.ai/), 검토일 2026-07-21
- [Common Computer English](https://comcom.ai/en), 검토일 2026-07-21

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-07-21 15:24 | 보호 기준 자료를 바탕으로 WISE 공개 사실·적용 범위·결정 항목을 편집 가능한 일반 문서로 정리 |
