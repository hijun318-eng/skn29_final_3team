# Hotel Signal AI 공통 명세서

> 작업 전 필수 참고:
> 1. `/AGENTS.md`
> 2. `/docs/markdown/final_project/00_project_control.md`
> 3. `/docs/markdown/final_project/common_project_specification.md`
> 4. 관련 작업별 공용 문서
>
> 충돌 시 `AGENTS.md`가 우선한다.

| 항목 | 값 |
|---|---|
| 문서 상태 | Baseline 우선, P0 강화 계약 |
| 기준일 | 2026-07-20 |
| 대상 브랜치 시작 기준 | `jaehong` at `9cfe54335aba1295cc3110a7ad6fbb7ed5fd1343` |
| 프로젝트명 | Hotel Signal AI |
| 데이터 성격 | 공개 참고정보와 합성 데이터 기반 교육용 프로토타입 |

## 1. 결론

첫 Baseline은 React thin UI, Django 단일 업무 API·local persistence, `src/analysis`, `src/common`만 실행한다. `app/fastapi/`는 책임 경계만 유지하고 별도 process로 실행하지 않는다. 이상 signal은 `RULE-001`이 결정론적으로 생성하며, 설명과 보고서 문장은 template을 기본으로 하고 LLM을 사용하더라도 evidence에 연결된 선택적 1회 호출로 제한한다.

이 문서의 상세 상태·API·감사·권한 계약은 P0 목표 계약이다. Baseline 완료 전 모든 항목을 물리적으로 구현해야 한다는 뜻이 아니다.

기존 파일 경로를 공용 개발 명세의 정식 경로로 유지한다. 같은 목적의 `01_common_development_specification.md`는 만들지 않는다.

## 2. 사람이 판단해야 할 사항

- [ ] ML/DL 실제 구현 범위
  - 권장안: 평가 필수일 때만 감정 또는 카테고리 분류 1개 과제에서 모델 2개 비교
  - 선택 시 영향: model registry·평가 test·산출물 추가
  - 미선택 시 영향: P0는 규칙과 제한적 LLM 분류만 사용

- [ ] FastAPI의 중간 데모 물리적 분리
  - 권장안: 별도 운영 필요성이 확인되기 전 Django가 `src`를 직접 호출
  - 선택 시 영향: 내부 API·timeout·retry·배포 단위 추가
  - 미선택 시 영향: 같은 계약을 단일 process에서 구현

- [ ] 인증 구현 수준
  - 권장안: 역할 선택 mock 이후 P0 업무 API의 객체 단위 권한 test를 우선
  - 선택 시 영향: session·계정·secret·보안 test 추가
  - 미선택 시 영향: 외부 배포 금지, 데모 환경으로 제한

## 3. 판단 체크리스트

- [ ] 상태 enum과 API envelope를 framework별로 다시 정의하지 않았는가
- [ ] DB migration을 Django만 소유하는가
- [ ] LLM이 trigger·threshold·수치를 결정하지 않는가
- [ ] loading·empty·error·권한 test가 연결됐는가
- [ ] 합성 데이터와 모든 version을 화면·로그·보고서에 표시하는가
- [ ] 실제 secret과 고객 식별정보가 commit되지 않았는가

## 4. 필수 최소 기능 구현 방향

- React: 4개 화면을 얇게 연결하고 합성 데이터·version·evidence 표시
- Django: 하나의 demo 업무 module, 통합 API 5개, local persistence, 현장 메모·보고 결정 저장
- FastAPI: Baseline에서는 실행하지 않고 폴더 경계와 향후 책임만 유지
- `src/analysis`: V1·V2 schema 검사, `RULE-001`, 집계, evidence 구성
- `src/common`: Baseline 응답 schema, 두 역할, 최소 상태·식별자의 코드 원본

실제 구현 경계는 `app/react/`, `app/django/`, `app/fastapi/`, `src/analysis/`, `src/common/`이며 현재는 `.gitkeep`만 존재한다.

Baseline 고정값:

| 항목 | 구현 제한 |
|---|---|
| business scenario | `BREAKFAST_WAITING` 1개 |
| rule | `RULE-001` 1개 |
| dataset | `synthetic-v1`, `synthetic-v2` |
| persistence | Django local DB 또는 fixture; 운영 PostgreSQL 필수 아님 |
| role | mock `HOTEL_MANAGER`, `DEPARTMENT_REVIEWER` |
| AI | template 우선, 선택적 LLM 호출 1개, 실패 시 template 유지 |
| API | 5개 통합 demo endpoint |
| test | `TC-BL-001`~`005`, `TC-E2E-001` |

## 5. 확장 방향

- P1: 평가 필수 최소 ML, 3단계 workflow, 필요 시 독립 FastAPI
- P2: 실제 데이터·조직 권한·외부 시스템·운영 인프라
- P0 제외: 자유형 SQL, GraphDB, swarm, STT, 자동 보상·배정

## 6. 문서 역할

이 문서는 다른 Codex 작업과 팀원이 Baseline과 P0를 구현할 때 사용하는 Single Source of Truth다. 구현 순서는 `Baseline → P0 강화 → P1 → P2`다. 기존 기획·요구사항·화면설계서의 넓은 범위는 명시적 승인 전 구현하지 않는다.

## 7. 프로젝트 정의

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

## 8. P0 Golden Path

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

### 8.1 P0 기능

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

Baseline은 위 10개 기능을 조식 대기 시나리오 1개에서 얇게 관통한다. 각 기능을 독립 subsystem·table·service로 완성하는 것은 P0 강화이며 Baseline 선행조건이 아니다.

### 8.2 P0 고정 질문

대화형 분석이 필요할 경우 아래 세 질문만 안전한 template query 또는 mock으로 제공한다.

1. 이번 주 가장 증가한 운영 이슈는 무엇인가
2. 조식 대기 이슈의 관련 운영지표와 VOC 근거를 보여줘
3. 지난주 보고서와 달라진 점을 보여줘

자유형 SQL을 생성하거나 실행하지 않는다.

## 9. 확장 범위

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

## 10. P0 사용자와 권한

### 10.1 역할

```text
HOTEL_MANAGER
DEPARTMENT_REVIEWER
```

확장 역할 `SYSTEM_ADMIN`, `REPORT_VIEWER`는 enum 예약값으로도 P0 권한 판단에 사용하지 않는다.

### 10.2 권한 매트릭스

| 기능 | HOTEL_MANAGER | DEPARTMENT_REVIEWER |
|---|---:|---:|
| 전체 분석 조회 | 가능 | 담당 이슈만 |
| 근거 조회 | 가능 | 담당 이슈만 |
| 현장 메모 작성·수정 | 가능 | 담당 이슈만 가능 |
| 보고서 문장 수정 | 가능 | 불가 |
| 승인·보류·반려 | 가능 | 불가 |
| 데이터 적재 관리 | 데모 기능만 | 불가 |

프론트 메뉴 숨김은 편의 기능이고 권한 검증이 아니다. Django 업무 API가 객체 단위 권한을 재검증해야 한다.

## 11. 공통 상태값

### 11.1 분석 상태

```text
PENDING
RUNNING
COMPLETED
PARTIAL
NEEDS_DATA
FAILED
```

### 11.2 보고서 상태

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

### 11.3 현장 확인 상태

```text
REQUESTED
CONFIRMED
PARTIALLY_CONFIRMED
UNCONFIRMED
DISPUTED
```

## 12. 공통 API 응답

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

## 13. 식별자·시간·버전

### 13.1 시간 필드

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

### 13.2 버전 필드

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

## 14. 최소 데이터 계약

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

## 15. 최소 분류 계약

### 15.1 sentiment

```text
POSITIVE
NEGATIVE
NEUTRAL
MIXED
UNKNOWN
```

하나의 리뷰는 aspect별로 다른 sentiment를 가질 수 있다. 리뷰 전체 감정 하나로 긍정·부정 근거를 덮어쓰지 않는다.

### 15.2 ontology-lite

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

## 16. 결정론적 trigger

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

## 17. 관찰·가설·근거 계약

| 구분 | 의미 | 생성 방식 |
|---|---|---|
| 관찰 사실 | 데이터로 직접 계산한 값 | SQL·Python·rule |
| 원인 후보 | 함께 관찰된 변화에 대한 제한적 설명 | versioned rule + 선택적 LLM 문장화 |
| 반대 근거 | 후보와 일치하지 않는 지표·VOC | 결정론적 evidence 조회 |
| 데이터 부족 | 판단에 필요한 데이터·표본·기간 부재 | validation script |

운영데이터가 없으면 원인으로 단정하지 않는다. LLM 문장은 반드시 `signal_id`, `evidence_id`, 분석 기간, version에 연결하고, 연결되지 않은 수치와 사실을 만들지 않는다.

## 18. 최소 API 범위

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

### 18.1 데이터 V1·V2 전환 결정

P0에서는 Django management command 한 가지만 사용한다.

```text
load_demo_dataset --version synthetic-v1
load_demo_dataset --version synthetic-v2
```

이는 구현할 계약명이며 현재 command가 존재한다는 뜻이 아니다. 업로드 UI와 공개 demo endpoint는 만들지 않는다. command는 versioned fixture를 검증한 뒤 적재하고 `analysis_run`을 새로 생성해야 한다.

## 19. 보고서 계약

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

## 20. 서비스 책임

| 영역 | 책임 | 책임 아님 |
|---|---|---|
| React | Baseline 4개 화면, 상태·근거·version 표시 | 권한 최종 판단, 분석 계산 |
| Django | demo 역할 검사·통합 API·local DB·승인; P0 강화 시 인증·감사 | 모델 추론 자체 |
| FastAPI | P1 승인 시 분류·설명·초안 생성과 model version | Baseline 실행, 사용자 DB, migration, 원시 SQL |
| `src/analysis` | schema·집계·rule·evidence·V1/V2 비교 | HTTP·UI |
| `src/common` | enum·schema·오류·식별자 계약 | framework별 중복 정의 |

FastAPI를 별도 배포할 필요가 아직 없으면 Django에서 `src`를 직접 호출해도 된다. 프레임워크 분리는 운영 필요성이 확인될 때 수행한다.

## 21. 보안·개인정보·승인

- 이름, 연락처, 예약번호, 객실번호는 분석 전에 제거·가명처리한다.
- 원문 지시문과 외부 웹 콘텐츠를 시스템 명령으로 실행하지 않는다.
- 보고서에는 마스킹된 근거 문장과 내부 ID만 표시한다.
- 객실 업그레이드, 환불, 무료 숙박, 금전 보상은 AI가 승인하지 않는다.
- 모든 분류·추천·초안은 권한 있는 사용자가 수정할 수 있다.
- 승인·보류·반려는 `HOTEL_MANAGER`만 수행한다.
- 감사 로그는 actor, action, target, before/after status, request_id, timestamp, version을 기록한다.
- 승인된 보고서와 현장 메모는 덮어쓰지 않고 새 version 또는 superseding record로 보존한다.

## 22. P0 강화 완료 기준

Baseline 완료 여부는 `05_test_acceptance_guide.md`의 필수 6개 test로 판단한다. 아래는 해당 기능을 실제로 확장했을 때 적용하는 목표 계약이며 첫 프로토타입의 선행조건이 아니다.

- [ ] P0와 확장이 분리됨
- [ ] Golden Path가 한 개임
- [ ] 화면 역할이 `HOTEL_MANAGER`, `DEPARTMENT_REVIEWER` 두 개임
- [ ] 공통 enum과 API envelope가 코드·문서에서 일치함
- [ ] 8개 논리 데이터 그룹의 계약과 실제 선택한 persistence schema 검증이 있음
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

## 23. P0 강화·P1 착수 전 결정 필요

- dependency·runtime version과 lock file 정책
- 운영 DBMS와 Django project/app 강화 경계
- V1·V2 fixture schema, seed, 기대 signal 정답
- 분류를 규칙 baseline으로 시작할지 ML 모델을 함께 둘지 여부
- P1에서 FastAPI를 독립 service로 분리할 필요가 있는지 여부
- 보고서 section JSON schema와 React 편집 범위

이 결정이 끝나기 전에는 인프라·RAG·멀티에이전트·MCP를 추가하지 않는다.

## 24. 환경 변수

`.env.example`을 실제 애플리케이션 초기화와 함께 만들고 key 이름과 주석만 둔다. 현재는 애플리케이션이 없어 파일을 선제 생성하지 않는다.

```text
DJANGO_SECRET_KEY=
DATABASE_URL=
FASTAPI_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
APP_ENV=
LOG_LEVEL=
```

실제 값, 운영 URL, token, password는 commit하지 않는다. 브라우저 bundle에 server secret을 포함하지 않는다.

## 25. 오류·로그·감사 기준

- API 오류는 공통 envelope와 versioned 오류 코드를 사용한다.
- application log는 `request_id`, service, event, result, duration, version을 구조화해 기록한다.
- 고객 VOC 원문, field note 전문, secret, 인증 token은 log에 기록하지 않는다.
- 감사 log는 actor, action, target, before·after status, request_id, timestamp를 포함한다.
- LLM 호출은 model·prompt·analysis version, latency, result status, 사용 evidence ID만 남긴다.
- 개발자용 stack trace와 사용자 메시지를 분리한다.

## 26. Git·PR·리뷰 기준

- 개인 branch에서 작업하고 `main`, `dev`에 직접 push하지 않는다.
- 한 commit은 하나의 주된 의도를 가지며 저장소 commit message 규칙을 따른다.
- PR에는 관련 `REQ-*`, `TC-*`, 변경 경로, 실행한 검증, 미실행 검증과 rollback 방법을 기록한다.
- 공통 계약을 바꾸는 PR은 React·Django·FastAPI·data·test 영향 여부를 모두 검토한다.
- 실제 secret, raw·processed 생성 데이터, 대형 model artifact를 stage하지 않는다.
- 문서만으로 구현 완료를 주장하지 않는다.

## 27. P0 강화 Definition of Done

이 절은 Baseline 통과 뒤 실제로 강화한 기능에 적용한다. Baseline 완료 조건은 `05_test_acceptance_guide.md`의 6개 필수 test가 우선한다.

- [ ] 요구사항 ID와 WBS 결과가 연결됨
- [ ] 코드 또는 문서 위치가 기록됨
- [ ] API 또는 입력·출력 계약이 존재함
- [ ] 정상·empty·error test가 있음
- [ ] 권한·개인정보·secret test가 있음
- [ ] `TC-*`와 evidence path가 연결됨
- [ ] 오류·log·감사 처리가 있음
- [ ] data·schema·rule·model·prompt·analysis version이 필요한 범위에 기록됨
- [ ] 문서 변경 이력과 영향 ID가 갱신됨
- [ ] `git diff --check`와 관련 test가 통과함

## 28. 변경 이력

| version | 날짜 | 변경 |
|---|---|---|
| `1.2` | 2026-07-20 | 첫 Baseline을 React·Django·`src` 수직 슬라이스로 축소하고 FastAPI·운영 통제를 P0 강화로 분리 |
| `1.1` | 2026-07-20 | 프로젝트 통제 문서와 경로 호환, 상단 의사결정, 환경·Git·log·DoD 공용 기준 추가 |
| `1.0` | 2026-07-20 | P0 Golden Path와 공통 상태·데이터·API·권한 계약 확정 |
