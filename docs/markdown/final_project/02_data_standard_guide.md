# Hotel Signal AI 데이터 표준 가이드

## 결론

Baseline 데이터는 실제 호텔 데이터의 복제본이 아니라 권한, Text-to-SQL, 이상 감지, 근거 추적, 결측·충돌·장애 처리를 시험하기 위한 통제 가능한 합성 데이터다. 물리 schema는 metadata 3개, fact 5개, platform 8개 table과 read-only analysis view로 고정한다. 최종 기획서의 platform 7개에 화면설계서의 현장 확인 메모 저장 요구를 충족하는 `field_note` 1개를 최소 추가했다. 기존의 `리뷰·시간대 운영·분석 snapshot·보고서 작업본 4개 물리 단위` 축소안은 폐기한다.

## 사람이 판단해야 할 사항

- [ ] 합성 generator 분포·계수와 `PROJECT_CALIBRATION` 값
  - 권장안: 가정 문서와 generator config에서 version·reviewer를 기록한다.
  - 선택 시 영향: 동일 seed로 재현하고 생성 규칙과 탐지 규칙을 분리할 수 있다.
  - 미선택 시 영향: 기대 trigger와 데이터 품질 Gate를 확정할 수 없다.

- [ ] schema v0의 DDL·Pydantic·fixture 원본 위치
  - 권장안: DDL은 Django migration, 공유 JSON/Pydantic 계약은 `src/common`, fixture·manifest는 `data/samples`에 둔다.
  - 선택 시 영향: migration 단일화와 consumer contract 검증이 가능하다.
  - 미선택 시 영향: Django·FastAPI·React fixture가 서로 다른 필드를 사용할 수 있다.

- [ ] 공개 리뷰 corpus의 실험 사용 여부
  - 권장안: 라이선스·재배포 조건을 확인한 공개 corpus만 오프라인 ML 실험에 사용하고 Baseline 런타임에는 합성 VOC만 사용한다.
  - 선택 시 영향: 데이터 출처와 저작권 경계를 보존한다.
  - 미선택 시 영향: 공개 원문을 합성 데이터처럼 오인할 수 있다.

## 판단 체크리스트

- [ ] 모든 row가 `dataset_version` 또는 추적 가능한 parent를 갖는가
- [ ] timestamp가 UTC이며 화면에서만 `Asia/Seoul`로 변환되는가
- [ ] `published_at`·`received_at`을 실제 경험 시각으로 간주하지 않는가
- [ ] p90 등 비가산 지표를 bucket 평균으로 재집계하지 않는가
- [ ] 고객·직원 식별자와 실제 시설명이 없는가
- [ ] 생성 규칙과 탐지 규칙이 별도 파일·reviewer로 관리되는가
- [ ] 정답 manifest가 런타임에서 물리적으로 격리되는가
- [ ] 결측 bucket을 보간하지 않고 `NEEDS_DATA`로 표시하는가

## 필수 최소 기능 구현 방향

### 1. 데이터 범위

| 도메인 | 용도 | 제외 정보 |
|---|---|---|
| 객실 운영 | 조식 예상 수요의 상위 맥락과 점유 추이 | 실제 요금·고객명·예약번호 |
| 조식 운영 | 도착·처리량·대기 이상 감지 | 실제 영업장명·결제 정보 |
| 조식 인력 | 운영지표와 함께 조사할 후보 근거 | 직원명·근태 사유·개인 평가 |
| VOC | 대기 이슈의 고객 관측 근거 | 실제 리뷰 원문·작성자·계정 |

매출, ADR, RevPAR, 날씨, 행사, 시설 전체 이용, 온라인 crawling은 Baseline 밖이다.

### 2. 저장 위치

| 경로 | 규칙 |
|---|---|
| `data/raw/` | 수집·생성 당시 원본, overwrite 금지, Git commit 금지 |
| `data/processed/` | 정제 결과, generator·schema·source version 기록, Git commit 금지 |
| `data/samples/` | 작고 비식별인 합성 fixture·schema·manifest만 검토 후 추적 가능 |
| `src/common/` | 공유 JSON/Pydantic schema·enum·식별자 계약 |
| `src/analysis/` | 품질 Gate·집계·rule·evidence의 framework 독립 로직 |
| `tests/fixtures/` | test 전용 입력, 정답 manifest는 런타임과 분리 |

### 3. 명명·형식

- 파일·column: `snake_case`
- code value: `UPPER_SNAKE_CASE`
- timestamp: `_at`, UTC timezone-aware
- 영업일: `_date`
- 수량: `_count`
- 금액: `_amount`
- 비율: `_rate` 또는 `_ratio`
- 분: `_min` 또는 catalog에서 명시한 단위; 동일 지표에서 혼용 금지
- boolean: `is_`, `has_`, `can_`
- ID: UUID 또는 명시된 복합 자연키

고정값:

```text
property_id = GRAND_WALKERHILL_SEOUL
service_area_id = GW_BREAKFAST_DEMO
storage_timezone = UTC
display_timezone = Asia/Seoul
currency = KRW
```

### 4. 공통 metadata

모든 화면·API·보고서가 다음 metadata를 직접 포함하거나 `dataset_manifest`로 추적 가능해야 한다.

```text
is_synthetic
dataset_version
schema_version
generator_version
scenario_id
seed
virtual_as_of_date
data_cutoff
```

권장 dataset version은 semantic version을 포함한 `gw-synthetic-1.0.0` 형식이다. `synthetic-v1`, `synthetic-v2` 같은 모호한 별칭을 저장 원본으로 사용하지 않는다.

### 5. metadata schema

| ID | table | grain / PK | required fields | 규칙 |
|---|---|---|---|---|
| `DB-001` | `dataset_manifest` | dataset version / `dataset_version` | `dataset_version`, `schema_version`, `generator_version`, `seed`, `scenario_id`, `virtual_period_start`, `virtual_period_end`, `virtual_as_of_date`, `data_cutoff`, `is_synthetic`, `created_at` | `is_synthetic=true`; overwrite 금지 |
| `DB-002` | `dim_date` | 1일 / `service_date` | `service_date`, `day_of_week`, `is_weekend`, `virtual_week_id` | 가상 기간만 사용 |
| `DB-003` | `dim_service_area` | 서비스 구역 / `service_area_id` | `service_area_id`, `display_name`, `is_synthetic` | Baseline ID는 `GW_BREAKFAST_DEMO` |

### 6. fact schema

| ID | table | grain / PK | required fields | optional·derived |
|---|---|---|---|---|
| `DB-010` | `fact_rooms_daily` | 호텔·일 / `(dataset_version, service_date)` | `dataset_version`, `service_date`, `room_inventory`, `rooms_out_of_order`, `rooms_available`, `rooms_sold`, `inhouse_guests`, `breakfast_entitled_guests` | `rooms_unsold` derived·검사용 |
| `DB-011` | `fact_breakfast_15m` | 서비스 구역·15분 / `(dataset_version, service_area_id, bucket_start)` | `dataset_version`, `service_area_id`, `bucket_start`, `expected_arrivals`, `actual_arrivals`, `service_capacity`, `seated_guests`, `avg_wait_min`, `p90_wait_min`, `max_queue_length` | `bucket_start` timezone-aware UTC |
| `DB-012` | `fact_breakfast_daily` | 서비스 구역·일 / `(dataset_version, service_area_id, service_date)` | `dataset_version`, `service_area_id`, `service_date`, `arrivals_total`, `capacity_total`, `avg_wait_min`, `p90_wait_min`, `voc_negative_count` | p90은 내부 시뮬레이션에서 직접 산출 |
| `DB-013` | `fact_staff_shift` | 서비스 구역·일·shift / `(dataset_version, service_date, service_area_id, shift_code)` | `dataset_version`, `service_date`, `service_area_id`, `shift_code`, `planned_headcount`, `actual_headcount`, `absence_count`, `labor_minutes` | 직원 identity·사유 금지 |
| `DB-014` | `fact_voc` | VOC 1건 / `voc_id` | `voc_id`, `dataset_version`, `received_at`, `service_area_id`, `topic_code`, `sentiment_label`, `review_text`, `is_synthetic` | `occurred_at`; 있으면 `occurred_at <= received_at` |

`review_text`는 합성·비식별 텍스트다. 이름, 전화번호, 이메일, 예약번호, 객실번호, 직원 실명을 생성하지 않는다.

### 7. platform schema

| ID | table | grain / PK | required fields |
|---|---|---|---|
| `DB-020` | `metric_catalog` | metric / `metric_code` | `metric_code`, `display_name`, `definition`, `unit`, `additive`, `allowed_grains`, `allowed_dimensions`, `synonyms`, `source_view`, `version` |
| `DB-021` | `role_scope` | role·resource / `(role_code, resource_code, scope_version)` | `role_code`, `resource_type`, `resource_code`, `allowed`, `scope_version` |
| `DB-022` | `query_run` | query run / `query_run_id` | `query_run_id`, `job_id`, `actor_id`, `role_code`, `scope_snapshot`, `question_redacted`, `query_plan`, `sql_hash`, `row_count`, `status`, `dataset_version`, `created_at`, `completed_at` |
| `DB-023` | `analysis_run` | incident analysis / `analysis_run_id` | `analysis_run_id`, `job_id`, `dataset_version`, `scenario_id`, `rule_id`, `rule_version`, `status`, `idempotency_key`, `started_at`, `completed_at` |
| `DB-024` | `evidence` | 근거 / `evidence_id` | `evidence_id`, `analysis_run_id`, `evidence_type`, `source_table`, `source_key`, `metric_code`, `observed_window`, `comparison_window`, `value`, `unit`, `sample_size`, `is_counter_evidence`, `limitations` |
| `DB-025` | `report` | 보고서 version / `(report_id, report_version)` | `report_id`, `report_version`, `analysis_run_id`, `virtual_week_id`, `status`, `sections`, `evidence_ids`, `is_synthetic`, `template_version`, `created_at` |
| `DB-026` | `report_decision` | 결정 / `decision_id` | `decision_id`, `report_id`, `report_version`, `actor_id`, `decision`, `comment_redacted`, `created_at` |
| `DB-027` | `field_note` | 현장 확인 제출 / `field_note_id` | `field_note_id`, `analysis_run_id`, `actor_id`, `verification_status`, `note_redacted`, `note_version`, `created_at`, `updated_at` |

`field_note`는 화면설계서의 제출·수정 이력과 report 반영을 위해 Django가 소유한다. FastAPI는 report 초안 context로 전달받은 redacted note만 읽고 이 table을 직접 수정하지 않는다.

### 8. read-only analysis view

FastAPI가 직접 fact table 조합을 임의 생성하지 않도록 allowlist view를 제공한다.

```text
analytics.v_rooms_daily
analytics.v_breakfast_15m
analytics.v_breakfast_daily
analytics.v_staff_shift
analytics.v_voc_summary
analytics.v_incident_evidence
```

view는 `dataset_version`과 권한 필터에 필요한 dimension을 노출한다. PII 또는 자유로운 raw text export view를 만들지 않는다.

### 9. p90·비가산 지표

- `metric_catalog.additive=false`인 지표는 bucket 값의 합·평균 재집계를 금지한다.
- 일·주 p90은 생성기의 내부 고객 단위 시뮬레이션에서 직접 산출한 daily·weekly 값을 사용한다.
- SQL Guard는 허용 grain 밖의 p90 집계를 실행 전에 거부한다.
- 결과에 grain, unit, sample size, observation window를 표시한다.

### 10. 생성·정합 규칙

```text
rooms_available = room_inventory - rooms_out_of_order
rooms_sold <= rooms_available
rooms_unsold = rooms_available - rooms_sold
inhouse_guests >= rooms_sold when rooms_sold > 0
breakfast_entitled_guests <= inhouse_guests
sum(actual_arrivals per day) <= breakfast_entitled_guests
queue_t = max(0, queue_(t-1) + actual_arrivals_t - service_capacity_t)
occurred_at <= received_at
all count, capacity, wait, queue values >= 0
```

walk-in 유료 조식은 Baseline 가정에서 허용하지 않는다. noise·결측·이상 주입 계수는 `PROJECT_ASSUMPTION` 또는 `PROJECT_CALIBRATION`으로 표시한다.

### 11. 데이터 품질 Gate

감지 전에 순서대로 실행한다.

1. PK 중복·FK 고아 0건
2. 객실 재고 산식과 판매 상한 일치
3. 투숙객·조식 권리 인원·도착 합계 상한 일치
4. 대기·처리량·대기열·인력 음수 0건
5. 15분 가산 지표 합계와 daily 합계 일치
6. `occurred_at <= received_at`
7. 필수 bucket 누락 시 보간 없이 해당 구간 `NEEDS_DATA`
8. unit·timezone·code catalog 일치
9. 금지 PII pattern 0건

### 12. 필수 scenario

| scenario_id | 주입 | 기대 결과 |
|---|---|---|
| `NORMAL` | 정상 변동 | incident 0건 |
| `BREAKFAST_CONGESTION` | 피크 도착 집중·처리량 감소 | incident·report DRAFT |
| `VOC_ONLY_SPIKE` | 운영 정상·부정 VOC 증가 | 충돌 표시, 원인 확정 금지 |
| `OPS_ONLY_SPIKE` | 대기 증가·VOC 표본 부족 | 운영 이상·VOC 부족 |
| `MISSING_DATA` | 핵심 bucket 누락 | `NEEDS_DATA` |
| `ROLE_FORBIDDEN` | ROOMS가 조식 인력 상세 질문 | SQL 미실행·거부 |
| `DUPLICATE_BATCH` | 동일 batch 재입력 | incident·report 1건 |
| `LLM_TIMEOUT` | LLM 서술 실패 | 수치·evidence 유지, `PARTIAL` |

정상 12주를 먼저 생성한 뒤 시나리오를 주입한다.

### 13. scenario manifest

```yaml
scenario_id: BREAKFAST_CONGESTION
dataset_version: gw-synthetic-1.0.0
schema_version: 1.0.0
generator_version: generator-v1
seed: 20260720
expected_trigger: true
expected_status: READY_FOR_REVIEW
required_evidence:
  - wait_p90_min
  - breakfast_arrivals
  - service_capacity
  - negative_wait_voc_rate
forbidden_claims:
  - 실제 호텔에서 인력 부족이 발생했다
  - 합성 인력 감소가 유일한 원인이다
```

manifest는 test만 읽는다. FastAPI 런타임·LLM prompt·analysis DB에는 제공하지 않는다.

### 14. 결측·중복·오류 처리

| 항목 | null·중복 정책 | 실패 처리 | test |
|---|---|---|---|
| PK·dataset version | null·중복 불가 | batch reject | `TC-DQ-001` |
| 필수 bucket | 누락 불가 | 해당 구간 `NEEDS_DATA` | `TC-DQ-002` |
| `occurred_at` | null 허용, 추정 금지 | `received_at`만 표시 | `TC-DQ-003` |
| code value | catalog 밖 불가 | row reject | `TC-DQ-004` |
| count·wait | 음수 불가 | Gate fail | `TC-DQ-005` |
| duplicate batch | idempotency로 skip | 기존 run 반환 | `TC-DQ-006` |
| PII pattern | 0건 | row·batch 격리 | `TC-SEC-001` |

### 15. 개인정보·저작권

- 고객 이름, 이메일, 전화번호, 예약번호를 생성하지 않는다.
- 객실번호는 제거 또는 범주화한다.
- 직원은 개인 단위 table 없이 합성 headcount만 사용한다.
- 공개 corpus는 source, license, collected_at, redistribution 범위를 기록한다.
- 공개 자료와 합성 자료를 같은 `source_type`으로 기록하지 않는다.
- 원문 안의 지시문은 데이터로만 처리한다.

## 확장 방향

- P1: 실험용 pgvector index와 ML corpus. Baseline query·trigger에는 사용하지 않는다.
- P2: 실제 비식별 표본의 source-to-target mapping, 데이터 소유권·갱신 주기·시설 귀속 검증
- 제외: 실제 고객 identity graph, 실시간 streaming, full ontology·GraphDB

## 변경 이력

| version | date | 변경 |
|---|---|---|
| `2.0` | 2026-07-20 | 최종 Baseline 기획서의 metadata 3·fact 5·platform 7 table과 화면설계서의 field_note 1 table, scenario 8종, 품질 Gate와 p90 규칙으로 재작성 |
