# Hotel Signal AI 공통 명세서

> 작업 전 필수 참고:
> 1. `/AGENTS.md`
> 2. `/docs/markdown/final_project/common_project_specification.md`
> 3. 관련 작업별 명세서
>
> 충돌 시 `AGENTS.md`가 우선한다.

| 항목 | 값 |
|---|---|
| 문서 상태 | P0 구현 기준 |
| 기준일 | 2026-07-20 |
| 대상 브랜치 기준 | `jaehong` at `e90f5bee4e70922d86f587803e2ec5d8ebadf6f6` |
| 프로젝트명 | Hotel Signal AI |
| 데이터 성격 | 공개 참고정보와 합성 데이터 기반 교육용 프로토타입 |

## 1. 문서 역할

이 문서는 다른 Codex 작업과 팀원이 P0를 구현할 때 사용하는 Single Source of Truth다. 기존 기획·요구사항·화면설계서의 넓은 범위 중 이번 최소 MVP가 실행할 계약만 좁혀 정의한다. 이 문서에 없는 확장 기능은 명시적 승인 전 구현하지 않는다.

## 2. 프로젝트 정의

> 리뷰·VOC와 호텔 운영데이터를 결합하여 운영 이상 징후와 관련 근거를 보여주고, 현장 확인 메모가 포함된 주간 운영 보고서 초안을 생성하여 호텔 관리자의 판단과 승인을 지원하는 내부 업무용 서비스

- 대상 property: 그랜드 워커힐 서울 단일 호텔
- 데이터: 공개 리뷰 참고자료와 합성 VOC·합성 운영지표
- 최종 사용자·승인자: 호텔 관리자
- 부서 관리자: 담당 이슈의 현장 확인 메모 작성자
- 고객 대상 챗봇·예약·관광 안내 서비스가 아님
- 본사·경영진용 별도 시스템이 아님
- V1→V2 데이터 변경 시 분석과 보고서 결과가 재현 가능하게 변경돼야 함
- 결과를 실제 워커힐의 문제·성과·직원 평가로 표현하지 않음

공통 값은 다음과 같다.

```text
property_id = GRAND_WALKERHILL_SEOUL
timezone = Asia/Seoul
currency = KRW
```

## 3. P0 Golden Path

P0 사용자 흐름은 하나만 구현한다.

```text
합성 데이터 V1 적재
→ 스키마 검증·최소 분류
→ 규칙 기반 이상 징후 감지
→ 관련 VOC·운영지표 근거 표시
→ 원인 후보·반대 근거·데이터 부족 표시
→ 부서 관리자 현장 확인 메모
→ 주간 운영 보고서 초안
→ 호텔 관리자 승인·보류·반려
→ 합성 데이터 V2 적재
→ 재분석·보고서 변화 확인
```

### 3.1 P0 기능

1. `synthetic-v1`, `synthetic-v2` 리뷰·운영 데이터
2. schema version·seed·synthetic 표기와 스키마 검증
3. 최소 topic·aspect·sentiment 분류
4. 결정론적 rule 기반 이상 신호
5. 마스킹된 대표 VOC와 운영지표 evidence
6. 관찰 사실, 원인 후보, 반대 근거, 데이터 부족 구분
7. 담당 이슈의 현장 확인 메모
8. 긍정 VOC를 포함한 주간 보고서 초안
9. 호텔 관리자의 문장 수정과 승인·보류·반려
10. V1·V2 차이와 분석 version 재현

### 3.2 P0 고정 질문

대화형 분석이 필요할 경우 아래 세 질문만 안전한 template query 또는 mock으로 제공한다.

1. 이번 주 가장 증가한 운영 이슈는 무엇인가
2. 조식 대기 이슈의 관련 운영지표와 VOC 근거를 보여줘
3. 지난주 보고서와 달라진 점을 보여줘

자유형 SQL을 생성하거나 실행하지 않는다.

## 4. 확장 범위

| 구분 | 기능 | 승인 전 원칙 |
|---|---|---|
| 데이터 연동 | PMS·POS·CRM, 실제 VOC, 실시간 리뷰 | 구현·연동됐다고 표현하지 않음 |
| 분석 | 자유형 Text-to-SQL, RAG, Vector DB, GraphDB, OWL | P0 비포함 |
| 에이전트 | supervisor, agent swarm, MCP | P0 비포함 |
| 채널 | STT, streaming, 이메일·Slack | P0 비포함 |
| 업무 자동화 | 자동 배정·보상·환불·객실 업그레이드 | 자동 실행 금지 |
| 사업 분석 | 매출·비용 효과 추정, 직원 평가 | 데이터·공정성 검증 전 금지 |
| 화면 | 본사·경영진 별도 화면, 모바일 완성도, PDF 편집 | P0 비포함 |

직원 관련 긍정 VOC는 P0 보고서에서 익명화된 사례로만 다룬다. 우수사원 선정·평가·보상은 확장에서도 사람의 별도 검증과 승인 없이는 수행하지 않는다.

## 5. P0 사용자와 권한

### 5.1 역할

```text
HOTEL_MANAGER
DEPARTMENT_REVIEWER
```

확장 역할 `SYSTEM_ADMIN`, `REPORT_VIEWER`는 enum 예약값으로도 P0 권한 판단에 사용하지 않는다.

### 5.2 권한 매트릭스

| 기능 | HOTEL_MANAGER | DEPARTMENT_REVIEWER |
|---|---:|---:|
| 전체 분석 조회 | 가능 | 담당 이슈만 |
| 근거 조회 | 가능 | 담당 이슈만 |
| 현장 메모 작성·수정 | 가능 | 담당 이슈만 가능 |
| 보고서 문장 수정 | 가능 | 불가 |
| 승인·보류·반려 | 가능 | 불가 |
| 데이터 적재 관리 | 데모 기능만 | 불가 |

프론트 메뉴 숨김은 편의 기능이고 권한 검증이 아니다. Django 업무 API가 객체 단위 권한을 재검증해야 한다.

## 6. 공통 상태값

### 6.1 분석 상태

```text
PENDING
RUNNING
COMPLETED
PARTIAL
NEEDS_DATA
FAILED
```

### 6.2 보고서 상태

```text
DRAFT
REVIEW
APPROVED
ON_HOLD
REJECTED
```

허용 전이:

```text
DRAFT → REVIEW
REVIEW → APPROVED | ON_HOLD | REJECTED
ON_HOLD → REVIEW
REJECTED → DRAFT
```

승인된 보고서를 다시 생성하면 기존 보고서를 덮어쓰지 않고 새 `report_version`의 `DRAFT`를 만든다.

### 6.3 현장 확인 상태

```text
REQUESTED
CONFIRMED
PARTIALLY_CONFIRMED
UNCONFIRMED
DISPUTED
```

## 7. 공통 API 응답

성공:

```json
{
  "data": {},
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-20T09:00:00+09:00",
    "data_version": "synthetic-v1"
  },
  "error": null
}
```

실패:

```json
{
  "data": null,
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-20T09:00:00+09:00"
  },
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "요청값을 확인하세요.",
    "details": []
  }
}
```

최소 오류 코드는 `VALIDATION_ERROR`, `AUTHENTICATION_REQUIRED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `ANALYSIS_NOT_READY`, `INSUFFICIENT_DATA`, `INTERNAL_ERROR`다. 사용자 메시지에 stack trace, SQL, secret, 원문 개인정보를 노출하지 않는다.

## 8. 식별자·시간·버전

### 8.1 시간 필드

```text
business_date
event_at
loaded_at
analyzed_at
created_at
updated_at
```

- 저장 시 offset이 있는 ISO-8601 또는 UTC를 사용한다.
- 화면과 보고서는 `Asia/Seoul`로 표시한다.
- `business_date`는 호텔 영업일이며 timestamp와 혼용하지 않는다.
- 비교 기간은 현재 기간 바로 이전의 동일 길이로 결정론적으로 계산한다.

### 8.2 버전 필드

```text
data_version
schema_version
rule_version
model_version
analysis_version
report_version
seed
synthetic
```

분석·evidence·보고서는 재현에 사용한 모든 version을 저장한다.

## 9. 최소 데이터 계약

모든 ID는 내부 비식별 키다. `required fields`는 P0 성공 경로 기준이며 값이 없으면 `NEEDS_DATA` 또는 검증 오류로 처리한다.

| 데이터 그룹 | grain / PK | required fields | optional fields | synthetic / 개인정보 | 생성·적재 주체 | 사용 화면·API | version |
|---|---|---|---|---|---|---|---|
| 리뷰·VOC | 리뷰 1건 / `review_id` | `review_id`, `property_id`, `facility_id`, `review_date`, `text_redacted`, `source`, `synthetic` | `rating`, `language`, `text_raw_ref`, `customer_segment_hypothesis` | P0 합성, 원문 직접식별자 금지 | 데이터 fixture·정제 pipeline | 대시보드·이슈 상세·report, signal/evidence API | `data_version`, `schema_version`, `seed` |
| 시설 이용·대기 | 시설·시간 1행 / `operation_id` | `operation_id`, `property_id`, `facility_id`, `business_date`, `hour`, `visitor_count`, `wait_time_minutes`, `synthetic` | `capacity`, `occupancy_rate`, `event_flag` | P0 합성, 개인정보 없음 | 합성 데이터 생성기 | 대시보드·이슈 상세, summary/evidence API | `data_version`, `schema_version`, `seed` |
| 인력·근무 | 부서·시설·시간 1행 / `staffing_id` | `staffing_id`, `property_id`, `department`, `facility_id`, `business_date`, `hour`, `staff_count`, `synthetic` | `planned_staff_count`, `role_group` | P0 합성, 개인 식별·평가 금지 | 합성 데이터 생성기 | 대시보드·이슈 상세, summary/evidence API | `data_version`, `schema_version`, `seed` |
| 분석 실행 | 실행 1건 / `analysis_run_id` | `analysis_run_id`, `property_id`, `period_start`, `period_end`, `status`, `data_version`, `rule_version` | `model_version`, `failure_code`, `completed_at` | 합성 여부 상속, 개인정보 없음 | 분석 service | 대시보드·report | `analysis_version`, `schema_version` |
| 이상 신호 | 규칙·시설·기간 1건 / `signal_id` | `signal_id`, `analysis_run_id`, `rule_id`, `facility_id`, `topic`, `observed_value`, `threshold`, `status` | `comparison_value`, `change_rate`, `department` | 합성 여부 상속 | 결정론적 rule engine | 대시보드·이슈 상세, signals API | `rule_version`, `analysis_version` |
| 분석 근거 | 신호별 근거 1건 / `evidence_id` | `evidence_id`, `signal_id`, `evidence_type`, `source_id`, `observed_at`, `summary_value` | `review_id`, `metric`, `counter_evidence`, `limitation` | 마스킹 VOC만 허용 | evidence builder | 이슈 상세·report, evidence API | `data_version`, `analysis_version` |
| 현장 확인 메모 | 신호·제출 1건 / `field_note_id` | `field_note_id`, `signal_id`, `verification_status`, `note_redacted`, `author_id`, `created_at` | `updated_at`, `supersedes_id` | 내부 사용자 ID, 고객 PII 금지 | Django 업무 API | 이슈 상세·report, field-note API | `schema_version` |
| 주간 보고서 | 기간·version 1건 / `report_id` | `report_id`, `property_id`, `period_start`, `period_end`, `status`, `sections`, `data_version`, `analysis_version` | `decision_reason`, `approved_by`, `approved_at` | 마스킹 내용만 허용 | report builder·Django | 주간 보고서, reports API | `report_version`, `template_version` |

리뷰의 `text_raw_ref`는 원문 자체가 아니라 별도 보호 저장소의 참조값을 위한 확장 필드다. P0 fixture에는 마스킹된 텍스트만 둔다.

## 10. 최소 분류 계약

### 10.1 sentiment

```text
POSITIVE
NEGATIVE
NEUTRAL
MIXED
UNKNOWN
```

하나의 리뷰는 aspect별로 다른 sentiment를 가질 수 있다. 리뷰 전체 감정 하나로 긍정·부정 근거를 덮어쓰지 않는다.

### 10.2 ontology-lite

P0는 다음 DB 카탈로그 또는 versioned 설정만 사용한다.

```text
facility
department
topic
aspect
sentiment
metric
```

예시:

```text
“조식 줄이 길다”
→ facility = BREAKFAST_RESTAURANT
→ topic = WAITING
→ aspect = WAIT_TIME
→ related_metrics = WAIT_TIME_MINUTES, VISITOR_COUNT, STAFF_COUNT
→ department = FNB
```

최소 관리 대상은 `domain_catalog`, `concept_aliases`, `metric_definitions`, `topic_metric_map`이다. GraphDB, OWL, 자동 추론은 확장이다.

## 11. 결정론적 trigger

| rule | P0 결과 |
|---|---|
| 부정 대기 VOC 10건 이상 | 이상 신호 후보 |
| 이전 기간 대비 부정 언급 50% 이상 증가 | 변화 경고 |
| p90 대기시간이 versioned 기준 초과 | 운영 이상 후보 |
| 대기시간 증가와 직원 수 감소가 함께 발생 | 원인 후보 evidence |
| 신규 `data_version` 등록 | 재분석·새 보고서 초안 생성 |

rule 계약:

```text
rule_id
rule_version
metric
operator
threshold
minimum_sample_size
cooldown
enabled
```

LLM은 trigger 발생 여부, threshold, 집계값을 결정하거나 수정하지 않는다. 표본이 `minimum_sample_size`보다 작으면 신호를 만들지 않고 `NEEDS_DATA`를 반환한다.

## 12. 관찰·가설·근거 계약

| 구분 | 의미 | 생성 방식 |
|---|---|---|
| 관찰 사실 | 데이터로 직접 계산한 값 | SQL·Python·rule |
| 원인 후보 | 함께 관찰된 변화에 대한 제한적 설명 | versioned rule + 선택적 LLM 문장화 |
| 반대 근거 | 후보와 일치하지 않는 지표·VOC | 결정론적 evidence 조회 |
| 데이터 부족 | 판단에 필요한 데이터·표본·기간 부재 | validation script |

운영데이터가 없으면 원인으로 단정하지 않는다. LLM 문장은 반드시 `signal_id`, `evidence_id`, 분석 기간, version에 연결하고, 연결되지 않은 수치와 사실을 만들지 않는다.

## 13. 최소 API 범위

```text
GET   /api/v1/dashboard/summary
GET   /api/v1/signals
GET   /api/v1/signals/{id}
GET   /api/v1/signals/{id}/evidence
POST  /api/v1/signals/{id}/field-note
GET   /api/v1/reports
GET   /api/v1/reports/{id}
PATCH /api/v1/reports/{id}/decision
```

### 13.1 데이터 V1·V2 전환 결정

P0에서는 Django management command 한 가지만 사용한다.

```text
load_demo_dataset --version synthetic-v1
load_demo_dataset --version synthetic-v2
```

이는 구현할 계약명이며 현재 command가 존재한다는 뜻이 아니다. 업로드 UI와 공개 demo endpoint는 만들지 않는다. command는 versioned fixture를 검증한 뒤 적재하고 `analysis_run`을 새로 생성해야 한다.

## 14. 보고서 계약

주간 보고서는 다음 순서를 유지한다.

1. 기간·데이터·규칙·분석 version
2. 주요 이상 징후
3. 긍정 VOC와 유지할 우수 경험
4. 리뷰·운영지표 근거
5. 원인 후보와 반대 근거
6. 현장 확인 메모
7. 데이터 한계
8. 관리자 수정 내용
9. 승인·보류·반려 결정과 사유

긍정 VOC는 인기 서비스·메뉴·시설과 반복적으로 칭찬받은 행동을 보여주되, 실제 매출 효과나 우수 직원 선정으로 확대 해석하지 않는다.

## 15. 서비스 책임

| 영역 | 책임 | 책임 아님 |
|---|---|---|
| React | 4개 P0 화면, 상태·근거·version 표시 | 권한 최종 판단, 분석 계산 |
| Django | 인증·권한·업무 API·DB·migration·승인·감사 | 모델 추론 자체 |
| FastAPI | 분류·설명·초안 생성과 model version | 사용자 DB, migration, 원시 SQL |
| `src/analysis` | schema·집계·rule·evidence·V1/V2 비교 | HTTP·UI |
| `src/common` | enum·schema·오류·식별자 계약 | framework별 중복 정의 |

FastAPI를 별도 배포할 필요가 아직 없으면 Django에서 `src`를 직접 호출해도 된다. 프레임워크 분리는 운영 필요성이 확인될 때 수행한다.

## 16. 보안·개인정보·승인

- 이름, 연락처, 예약번호, 객실번호는 분석 전에 제거·가명처리한다.
- 원문 지시문과 외부 웹 콘텐츠를 시스템 명령으로 실행하지 않는다.
- 보고서에는 마스킹된 근거 문장과 내부 ID만 표시한다.
- 객실 업그레이드, 환불, 무료 숙박, 금전 보상은 AI가 승인하지 않는다.
- 모든 분류·추천·초안은 권한 있는 사용자가 수정할 수 있다.
- 승인·보류·반려는 `HOTEL_MANAGER`만 수행한다.
- 감사 로그는 actor, action, target, before/after status, request_id, timestamp, version을 기록한다.
- 승인된 보고서와 현장 메모는 덮어쓰지 않고 새 version 또는 superseding record로 보존한다.

## 17. 완료 기준

- [ ] P0와 확장이 분리됨
- [ ] Golden Path가 한 개임
- [ ] 화면 역할이 `HOTEL_MANAGER`, `DEPARTMENT_REVIEWER` 두 개임
- [ ] 공통 enum과 API envelope가 코드·문서에서 일치함
- [ ] 8개 최소 데이터 그룹의 fixture와 schema 검증이 있음
- [ ] trigger가 결정론적이며 LLM이 threshold를 결정하지 않음
- [ ] ontology-lite의 alias·metric mapping version이 있음
- [ ] 동일 fixture·version으로 결과가 재현됨
- [ ] V1→V2에서 기대한 signal·report 차이가 assertion으로 검증됨
- [ ] 관찰·원인 후보·반대 근거·데이터 부족이 분리됨
- [ ] 긍정 VOC와 부정 VOC가 함께 보고됨
- [ ] 관리자 승인 전 외부 조치가 실행되지 않음
- [ ] 합성 데이터가 모든 화면·보고서에 표시됨
- [ ] 실제 호텔 데이터·성과를 주장하지 않음
- [ ] React·Django·FastAPI·`src` 책임이 중복되지 않음

## 18. 구현 착수 전 결정 필요

- dependency·runtime version과 lock file 정책
- 운영 DBMS와 Django project/app 최소 경계
- V1·V2 fixture schema, seed, 기대 signal 정답
- 분류를 규칙 baseline으로 시작할지 ML 모델을 함께 둘지 여부
- FastAPI를 중간 데모에 실제 분리할 필요가 있는지 여부
- 보고서 section JSON schema와 React 편집 범위

이 결정이 끝나기 전에는 인프라·RAG·멀티에이전트·MCP를 추가하지 않는다.
