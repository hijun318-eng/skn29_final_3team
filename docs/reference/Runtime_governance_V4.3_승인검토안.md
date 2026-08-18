# Runtime governance 승인 검토안

> **DRAFT / DATAHUB 발행 금지 / 승인 전 비권위 자료**
> 이 문서는 SQL AST와 SQL `COMMENT ON`만으로 구조적 근거를 정리한다. metric 의미·별칭·단위·집계·권한을 자동 승인하지 않는다.

## 생성 근거

- catalog release: `V4.3`
- serving schema: `serving.analytics_v4_3`
- SQL source SHA-256: `60e96f2002178e9b903024a96f0be33430afa08f61dcfc9ed6f44ca2d8483460`
- view: 13개
- 출력 필드: 168개
- 구조 분류: `AGGREGATE` 37개, `AGGREGATED_DERIVATION` 7개, `DERIVED_EXPRESSION` 6개, `GROUPING_KEY` 12개, `PASS_THROUGH` 63개, `PASS_THROUGH_TRANSFORM` 43개
- 상태: 모든 항목 `REVIEW_REQUIRED`; 승인 metadata 발행 0건

## 릴리스 문서가 명시한 선결 결정

- [ ] 이벤트 발생량 연결 기준
- [ ] 객실·식음·연회·시설 통합 매출의 세금·봉사료·인식 기준
- [ ] VOC 데이터의 학습·평가 사용 적합성
- [ ] 연회 취소 수수료와 환입의 인식 기준

위 네 항목은 release의 `데이터_구조_요약.md`와 `품질_보고서.md`가 후속 승인을 요구한다. 이 문서는 해당 결정을 대신하지 않는다.

## 승인자가 view마다 확정할 계약

- 업무 metric ID·표시명·별칭·단위와 소유자
- 원본 grain, 허용 dimension, 기준 time field와 timezone
- 기본 aggregation과 상위 grain reduction; 비율의 분자·분모·0 처리
- 필수 filter, 허용 join edge, synthetic 데이터 표시 방식
- 조회 가능한 role·domain과 최소/최대 query 기간·행 수
- pass-through 값이 upstream pre-aggregation을 보존하는지 여부

## 구조적 근거

### `serving.analytics_v4_3.banquet_daily`

- 설명: 호텔·영업일 단위 연회 예약·참석·계약액·인식매출 합성 KPI
- SQL: `23_trino_banquet_views.sql`
- 직접 upstream: `banquet.walkerhill_v4_3.banquet_bookings`, `banquet.walkerhill_v4_3.banquet_revenue_lines`, `banquet.walkerhill_v4_3.banquet_venues`
- grain 후보: 없음 — 승인자가 명시해야 함

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `business_date` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.business_date, r.business_date)` | `b.business_date`, `r.business_date` | 행사일 또는 매출 인식일 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `hotel_code` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.hotel_code, r.hotel_code)` | `b.hotel_code`, `r.hotel_code` | 행사장 소속 합성 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `operating_events` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.operating_events, 0)` | `b.operating_events` | 완료·확정 상태를 합한 운영 연회 건수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `completed_events` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.completed_events, 0)` | `b.completed_events` | 실제 행사일을 지나 COMPLETED로 종료된 합성 연회 건수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `confirmed_events` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.confirmed_events, 0)` | `b.confirmed_events` | 확정 상태 합성 연회 건수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `cancelled_events` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.cancelled_events, 0)` | `b.cancelled_events` | 취소 상태 합성 연회 건수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `attendees` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.attendees, 0)` | `b.attendees` | 확정 연회의 실제 또는 예상 합성 참석자 수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `contracted_amount_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.contracted_amount_krw, CAST('0' AS DECIMAL))` | `b.contracted_amount_krw` | 확정 연회의 합성 계약금액 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `gross_amount_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.gross_amount_krw, CAST('0' AS DECIMAL))` | `r.gross_amount_krw` | 할인·취소 전 연회 매출 총액 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `discount_amount_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.discount_amount_krw, CAST('0' AS DECIMAL))` | `r.discount_amount_krw` | 연회 할인 합계 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `reversal_amount_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.reversal_amount_krw, CAST('0' AS DECIMAL))` | `r.reversal_amount_krw` | 연회 취소·환입 합계 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `recognized_revenue_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.recognized_revenue_krw, CAST('0' AS DECIMAL))` | `r.recognized_revenue_krw` | 회계 인식 기준 합성 연회 순매출 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `estimated_cost_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.estimated_cost_krw, CAST('0' AS DECIMAL))` | `r.estimated_cost_krw` | 합성 원가율로 산출한 분석용 추정 원가 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |

### `serving.analytics_v4_3.event_counterfactual_daily`

- 설명: 동일 호텔의 행사 전후 비행사일 평균을 기준선으로 둔 합성 이벤트 반사실 비교. 인과 추정치가 아님
- SQL: `31_trino_event_counterfactual_validation.sql`
- 직접 upstream: `pms.walkerhill_v4_3.event_master`, `pms.walkerhill_v4_3.hotel_event_effect`, `serving.analytics_v4_3.hotel_operations_daily`
- grain 후보: 없음 — 승인자가 명시해야 함

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `event_id` | `PASS_THROUGH` | `a.event_id` | `a.event_id` | 공개 행사 또는 합성 시나리오 이벤트 코드 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `event_name` | `PASS_THROUGH` | `a.event_name` | `a.event_name` | 이벤트 표시명 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `start_date` | `PASS_THROUGH` | `a.start_date` | `a.start_date` | 이벤트 영향 분석 시작일 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `end_date` | `PASS_THROUGH` | `a.end_date` | `a.end_date` | 이벤트 영향 분석 종료일 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `hotel_code` | `PASS_THROUGH` | `a.hotel_code` | `a.hotel_code` | 이벤트 효과를 다르게 적용받는 합성 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `domain` | `PASS_THROUGH` | `a.domain` | `a.domain` | ROOMS·FNB·BANQUET·FACILITY 중 영향 도메인 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `metric_name` | `PASS_THROUGH` | `a.metric_name` | `a.metric_name` | OCCUPANCY_RATE·ADR·ORDER_COUNT·BOOKING_COUNT·USAGE_COUNT 중 비교 지표 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `actual_days` | `PASS_THROUGH` | `a.actual_days` | `a.actual_days` | lead·행사·lag 영향 구간에서 관측된 합성 영업일 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `baseline_days` | `PASS_THROUGH` | `b.baseline_days` | `b.baseline_days` | 영향 구간 전후 35일 중 다른 이벤트 영향일까지 제외한 기준 영업일 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `actual_metric_mean` | `PASS_THROUGH` | `a.actual_metric_mean` | `a.actual_metric_mean` | 행사 구간의 일평균 합성 지표 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `counterfactual_metric_mean` | `PASS_THROUGH` | `b.counterfactual_metric_mean` | `b.counterfactual_metric_mean` | 동일 호텔 행사 전후 비행사일의 일평균 합성 지표 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `realized_uplift_rate` | `DERIVED_EXPRESSION` | `a.actual_metric_mean / NULLIF(b.counterfactual_metric_mean, 0) - 1` | `a.actual_metric_mean`, `b.counterfactual_metric_mean` | actual/counterfactual-1로 계산한 합성 상승률 | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `baseline_quality` | `DERIVED_EXPRESSION` | `CASE WHEN COALESCE(b.baseline_days, 0) >= 14 THEN 'USABLE' ELSE 'INSUFFICIENT' END` | `b.baseline_days` | 오염 제거 후 기준일이 14일 이상이면 USABLE, 아니면 INSUFFICIENT | `BUSINESS_APPROVAL_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `uplift_min` | `PASS_THROUGH` | `a.uplift_min` | `a.uplift_min` | 모델 계약에 기록한 삼각 시나리오 최소 상승률 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `uplift_mode` | `PASS_THROUGH` | `a.uplift_mode` | `a.uplift_mode` | 모델 계약에 기록한 삼각 시나리오 최빈 상승률 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `uplift_max` | `PASS_THROUGH` | `a.uplift_max` | `a.uplift_max` | 모델 계약에 기록한 삼각 시나리오 최대 상승률 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `confidence` | `PASS_THROUGH` | `a.confidence` | `a.confidence` | 이벤트 근거와 모델링 규칙에 부여한 0~1 신뢰도 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |

### `serving.analytics_v4_3.facility_daily`

- 설명: 시설·사고·자원 원천을 호텔 운영일 수준으로 선집계한 합성 시설 KPI
- SQL: `24_trino_facility_views.sql`
- 직접 upstream: `facility.walkerhill_v4_3.facility_incidents`, `facility.walkerhill_v4_3.facility_master`, `facility.walkerhill_v4_3.facility_resource_daily`, `facility.walkerhill_v4_3.facility_usage_events`
- grain 후보: 없음 — 승인자가 명시해야 함

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `business_date` | `PASS_THROUGH_TRANSFORM` | `COALESCE(u.business_date, i.business_date, r.business_date)` | `i.business_date`, `r.business_date`, `u.business_date` | 시설 활동의 영업일 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `hotel_code` | `PASS_THROUGH_TRANSFORM` | `COALESCE(u.hotel_code, i.hotel_code, r.hotel_code)` | `i.hotel_code`, `r.hotel_code`, `u.hotel_code` | 공용 시설까지 GRAND·VISTA·DOUGLAS 중 하나에 귀속한 합성 보고 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `usage_events` | `PASS_THROUGH_TRANSFORM` | `COALESCE(u.usage_events, 0)` | `u.usage_events` | 시설 이용 이벤트 수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `facility_guests` | `PASS_THROUGH_TRANSFORM` | `COALESCE(u.facility_guests, 0)` | `u.facility_guests` | 시설 이용 합성 인원 합계 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `facility_revenue_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(u.facility_revenue_krw, CAST('0' AS DECIMAL))` | `u.facility_revenue_krw` | 유료 시설 합성 총매출 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `incidents` | `PASS_THROUGH_TRANSFORM` | `COALESCE(i.incidents, 0)` | `i.incidents` | 시설 사고·불편 건수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `high_severity_incidents` | `PASS_THROUGH_TRANSFORM` | `COALESCE(i.high_severity_incidents, 0)` | `i.high_severity_incidents` | HIGH 심각도 사고 건수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `incident_impact_minutes` | `PASS_THROUGH_TRANSFORM` | `COALESCE(i.incident_impact_minutes, 0)` | `i.incident_impact_minutes` | 사고 운영 영향 시간 합계(분) | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `energy_kwh` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.energy_kwh, CAST('0' AS DECIMAL))` | `r.energy_kwh` | 합성 전력 사용량 합계(kWh) | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `water_m3` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.water_m3, CAST('0' AS DECIMAL))` | `r.water_m3` | 합성 용수 사용량 합계(m³) | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `waste_kg` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.waste_kg, CAST('0' AS DECIMAL))` | `r.waste_kg` | 합성 폐기물 발생량 합계(kg) | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |

### `serving.analytics_v4_3.fnb_daily`

- 설명: 호텔·영업일 단위 POS 주문, 커버, 세금·봉사료·환불을 분리한 합성 식음 KPI
- SQL: `21_trino_fnb_views.sql`
- 직접 upstream: `pos.walkerhill_v4_3.pos_orders`, `pos.walkerhill_v4_3.pos_outlets`
- grain 후보: `business_date`, `hotel_code`

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `business_date` | `GROUPING_KEY` | `o.business_date` | `o.business_date` | POS 주문이 귀속되는 영업일 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED` |
| `hotel_code` | `GROUPING_KEY` | `m.hotel_code` | `m.hotel_code` | 업장 소속 GRAND·VISTA·DOUGLAS 합성 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED` |
| `completed_orders` | `AGGREGATE` | `COUNT(*) FILTER(WHERE o.order_status IN ('PAID', 'PARTIAL_REFUND'))` | `o.order_status` | 완료 상태 합성 주문 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `reversed_orders` | `AGGREGATE` | `COUNT(*) FILTER(WHERE o.order_status IN ('VOID', 'REFUNDED'))` | `o.order_status` | 취소 또는 환불 상태 합성 주문 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `covers` | `AGGREGATE` | `SUM(CASE WHEN o.order_status <> 'VOID' THEN o.guest_count ELSE 0 END)` | `o.guest_count`, `o.order_status` | 완료 주문의 합성 고객 커버 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `item_gross_amount_krw` | `AGGREGATE` | `SUM(o.item_gross_amount)` | `o.item_gross_amount` | 할인 전 메뉴 품목 총액 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `discount_amount_krw` | `AGGREGATE` | `SUM(o.discount_amount)` | `o.discount_amount` | 주문 할인 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `service_charge_amount_krw` | `AGGREGATE` | `SUM(o.service_charge_amount)` | `o.service_charge_amount` | 주문 봉사료 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `tax_amount_krw` | `AGGREGATE` | `SUM(o.tax_amount)` | `o.tax_amount` | 주문 세액 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `reversal_amount_krw` | `AGGREGATED_DERIVATION` | `SUM(o.refund_amount + o.void_amount)` | `o.refund_amount`, `o.void_amount` | 환불액과 취소액 합계 | `BUSINESS_APPROVAL_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED` |
| `net_revenue_krw` | `AGGREGATE` | `SUM(o.net_amount)` | `o.net_amount` | 할인·환불·취소를 반영한 합성 POS 순매출 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `average_check_krw` | `AGGREGATED_DERIVATION` | `CAST(SUM(o.net_amount) AS DOUBLE) / NULLIF(COUNT(*) FILTER(WHERE o.order_status IN ('PAID', 'PARTIAL_REFUND')), 0)` | `o.net_amount`, `o.order_status` | 합성 순매출/완료 주문 수 | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED` |

### `serving.analytics_v4_3.hotel_operations_daily`

- 설명: 도메인 선집계 결과를 호텔·영업일 키로 결합한 V4.3 합성 통합 운영 마트
- SQL: `25_trino_integrated_hotel_views.sql`
- 직접 upstream: `pms.walkerhill_v4_3.calendar_daily`, `pms.walkerhill_v4_3.event_master`, `pms.walkerhill_v4_3.hotel_event_effect`, `serving.analytics_v4_3.banquet_daily`, `serving.analytics_v4_3.facility_daily`, `serving.analytics_v4_3.fnb_daily`, `serving.analytics_v4_3.room_daily`, `serving.analytics_v4_3.staffing_daily`
- grain 후보: 없음 — 승인자가 명시해야 함

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `business_date` | `PASS_THROUGH` | `k.business_date` | `k.business_date` | 통합 운영 실적 영업일 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `hotel_code` | `PASS_THROUGH` | `k.hotel_code` | `k.hotel_code` | GRAND·VISTA·DOUGLAS 합성 보고 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `event_id` | `PASS_THROUGH` | `e.event_id` | `e.event_id` | 해당 날짜·호텔에 가장 높은 신뢰도로 연결된 행사 코드 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `event_name` | `PASS_THROUGH` | `e.event_name` | `e.event_name` | 연결된 공개 행사 또는 합성 외부 이벤트 표시명 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `available_room_nights` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.available_room_nights, 0)` | `r.available_room_nights` | 일별 판매 가능 객실박 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `occupied_room_nights` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.occupied_room_nights, 0)` | `r.occupied_room_nights` | 일별 점유 객실박 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `occupancy_rate` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.occupancy_rate, 0e0)` | `r.occupancy_rate` | 일별 객실 점유율 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `adr_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.adr_krw, 0e0)` | `r.adr_krw` | 일별 합성 평균객실단가 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `room_revenue_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(r.room_revenue_krw, CAST('0' AS DECIMAL))` | `r.room_revenue_krw` | 일별 합성 객실매출 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `fnb_orders` | `PASS_THROUGH_TRANSFORM` | `COALESCE(f.completed_orders, 0)` | `f.completed_orders` | 일별 완료 POS 주문 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `fnb_revenue_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(f.net_revenue_krw, CAST('0' AS DECIMAL))` | `f.net_revenue_krw` | 일별 합성 식음 순매출 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `banquet_events` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.operating_events, 0)` | `b.operating_events` | 일별 완료·확정 운영 연회 건수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `banquet_revenue_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(b.recognized_revenue_krw, CAST('0' AS DECIMAL))` | `b.recognized_revenue_krw` | 일별 합성 연회 인식매출 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `facility_uses` | `PASS_THROUGH_TRANSFORM` | `COALESCE(x.usage_events, 0)` | `x.usage_events` | 일별 시설 이용 이벤트 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `facility_revenue_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(x.facility_revenue_krw, CAST('0' AS DECIMAL))` | `x.facility_revenue_krw` | 일별 합성 유료시설 매출 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `staffing_hours` | `PASS_THROUGH_TRANSFORM` | `COALESCE(s.actual_hours, CAST('0' AS DECIMAL))` | `s.actual_hours` | 일별 합성 실제 근로시간 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `overtime_hours` | `PASS_THROUGH_TRANSFORM` | `COALESCE(s.overtime_hours, CAST('0' AS DECIMAL))` | `s.overtime_hours` | 일별 합성 초과근로시간 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `total_operating_revenue_krw` | `DERIVED_EXPRESSION` | `COALESCE(r.room_revenue_krw, CAST('0' AS DECIMAL)) + COALESCE(f.net_revenue_krw, CAST('0' AS DECIMAL)) + COALESCE(b.recognized_revenue_krw, CAST('0' AS DECIMAL)) + COALESCE(x.facility_revenue_krw, CAST('0' AS DECIMAL))` | `b.recognized_revenue_krw`, `f.net_revenue_krw`, `r.room_revenue_krw`, `x.facility_revenue_krw` | 객실+식음+연회+시설 합성 매출 합계. 실제 워커힐 실적이 아님 | `BUSINESS_APPROVAL_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |

### `serving.analytics_v4_3.hotel_operations_monthly`

- 설명: 호텔 통합 운영 일별 마트를 월 단위로 가중 재집계한 합성 KPI
- SQL: `25_trino_integrated_hotel_views.sql`
- 직접 upstream: `serving.analytics_v4_3.hotel_operations_daily`
- grain 후보: `month_start`, `hotel_code`

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `month_start` | `GROUPING_KEY` | `DATE_TRUNC('MONTH', business_date)` | `business_date` | 집계월 첫날 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `hotel_code` | `GROUPING_KEY` | `hotel_code` | `hotel_code` | GRAND·VISTA·DOUGLAS 합성 보고 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `available_room_nights` | `AGGREGATE` | `SUM(available_room_nights)` | `available_room_nights` | 월간 판매 가능 객실박 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `occupied_room_nights` | `AGGREGATE` | `SUM(occupied_room_nights)` | `occupied_room_nights` | 월간 점유 객실박 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `occupancy_rate` | `AGGREGATED_DERIVATION` | `CAST(SUM(occupied_room_nights) AS DOUBLE) / NULLIF(SUM(available_room_nights), 0)` | `available_room_nights`, `occupied_room_nights` | 월간 가중 객실 점유율 | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `adr_krw` | `AGGREGATED_DERIVATION` | `CAST(SUM(room_revenue_krw) AS DOUBLE) / NULLIF(SUM(occupied_room_nights), 0)` | `occupied_room_nights`, `room_revenue_krw` | 월간 가중 평균객실단가 | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `room_revenue_krw` | `AGGREGATE` | `SUM(room_revenue_krw)` | `room_revenue_krw` | 월간 합성 객실매출 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `fnb_revenue_krw` | `AGGREGATE` | `SUM(fnb_revenue_krw)` | `fnb_revenue_krw` | 월간 합성 식음 순매출 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `banquet_revenue_krw` | `AGGREGATE` | `SUM(banquet_revenue_krw)` | `banquet_revenue_krw` | 월간 합성 연회 인식매출 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `facility_revenue_krw` | `AGGREGATE` | `SUM(facility_revenue_krw)` | `facility_revenue_krw` | 월간 합성 유료시설 매출 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `total_operating_revenue_krw` | `AGGREGATE` | `SUM(total_operating_revenue_krw)` | `total_operating_revenue_krw` | 월간 4개 영업 도메인 합성 매출 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `staffing_hours` | `AGGREGATE` | `SUM(staffing_hours)` | `staffing_hours` | 월간 합성 실제 근로시간 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `overtime_hours` | `AGGREGATE` | `SUM(overtime_hours)` | `overtime_hours` | 월간 합성 초과근로시간 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |

### `serving.analytics_v4_3.hotel_voc_signal_daily`

- 설명: 운영 부하·매출과 VOC 평점·저평점·후속 확인을 호텔·일자 한 행에서 비교하는 합성 분석 뷰
- SQL: `26_trino_voc_views.sql`
- 직접 upstream: `serving.analytics_v4_3.hotel_operations_daily`, `serving.analytics_v4_3.voc_daily`
- grain 후보: 없음 — 승인자가 명시해야 함

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `business_date` | `PASS_THROUGH` | `o.business_date` | `o.business_date` | 운영과 VOC를 결합한 영업일 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `hotel_code` | `PASS_THROUGH` | `o.hotel_code` | `o.hotel_code` | GRAND·VISTA·DOUGLAS 합성 보고 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `event_id` | `PASS_THROUGH` | `o.event_id` | `o.event_id` | 해당 호텔·일자에 연결된 대표 이벤트 코드 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `occupancy_rate` | `PASS_THROUGH` | `o.occupancy_rate` | `o.occupancy_rate` | 일별 합성 객실 점유율 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `adr_krw` | `PASS_THROUGH` | `o.adr_krw` | `o.adr_krw` | 일별 합성 평균객실단가 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `fnb_orders` | `PASS_THROUGH` | `o.fnb_orders` | `o.fnb_orders` | 일별 완료 식음 주문 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `banquet_events` | `PASS_THROUGH` | `o.banquet_events` | `o.banquet_events` | 일별 확정 연회 건수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `facility_uses` | `PASS_THROUGH` | `o.facility_uses` | `o.facility_uses` | 일별 시설 이용 이벤트 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `overtime_hours` | `PASS_THROUGH` | `o.overtime_hours` | `o.overtime_hours` | 일별 합성 초과근로시간 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `total_operating_revenue_krw` | `PASS_THROUGH` | `o.total_operating_revenue_krw` | `o.total_operating_revenue_krw` | 객실·식음·연회·시설 일별 합성 매출 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `review_count` | `PASS_THROUGH_TRANSFORM` | `COALESCE(v.review_count, 0)` | `v.review_count` | 호텔·일자 합성 VOC 리뷰 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `average_rating` | `PASS_THROUGH` | `v.average_rating` | `v.average_rating` | 리뷰 건수로 가중한 1~5 합성 평균평점 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `low_rating_reviews` | `PASS_THROUGH_TRANSFORM` | `COALESCE(v.low_rating_reviews, 0)` | `v.low_rating_reviews` | 1~2점 합성 리뷰 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `negative_reviews` | `PASS_THROUGH_TRANSFORM` | `COALESCE(v.negative_reviews, 0)` | `v.negative_reviews` | NEGATIVE 감성 합성 리뷰 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `followup_reviews` | `PASS_THROUGH_TRANSFORM` | `COALESCE(v.followup_reviews, 0)` | `v.followup_reviews` | 후속 확인 필요 합성 리뷰 수 | `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |

### `serving.analytics_v4_3.membership_daily`

- 설명: 영업일 단위 합성 멤버십 포인트 적립·사용·만료 활동
- SQL: `22_trino_membership_views.sql`
- 직접 upstream: `crm.walkerhill_v4_3.crm_point_transactions`
- grain 후보: `business_date`

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `business_date` | `GROUPING_KEY` | `CAST(AT_TIMEZONE(event_at, 'Asia/Seoul') AS DATE)` | `event_at` | 포인트 거래의 한국 표준시 영업일 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED` |
| `point_transactions` | `AGGREGATE` | `COUNT(*)` | 없음 | 일별 포인트 원장 행 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `active_members` | `AGGREGATE` | `COUNT(DISTINCT member_no)` | `member_no` | 일별 포인트 변동이 있었던 중복 제거 합성 회원 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `points_earned` | `AGGREGATE` | `SUM(CASE WHEN points_delta > 0 THEN points_delta ELSE 0 END)` | `points_delta` | 양수 적립 포인트 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `points_redeemed` | `AGGREGATE` | `-SUM(CASE WHEN txn_type = 'REDEEM' THEN points_delta ELSE 0 END)` | `points_delta`, `txn_type` | 사용 포인트의 절대값 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `points_expired` | `AGGREGATE` | `-SUM(CASE WHEN txn_type = 'EXPIRE' THEN points_delta ELSE 0 END)` | `points_delta`, `txn_type` | 만료 포인트의 절대값 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `net_points_delta` | `AGGREGATE` | `SUM(points_delta)` | `points_delta` | 적립에서 사용·만료를 차감한 순변동 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |

### `serving.analytics_v4_3.room_daily`

- 설명: 호텔·영업일 단위 객실 공급, 판매, 매출과 OCC·ADR·RevPAR를 제공하는 합성 서빙 뷰
- SQL: `20_trino_room_views.sql`
- 직접 upstream: `pms.walkerhill_v4_3.pms_room_inventory_daily`, `pms.walkerhill_v4_3.pms_stay_nights`, `pms.walkerhill_v4_3.pms_stays`
- grain 후보: 없음 — 승인자가 명시해야 함

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `business_date` | `PASS_THROUGH` | `i.business_date` | `i.business_date` | 객실 실적 귀속 영업일 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `hotel_code` | `PASS_THROUGH` | `i.hotel_code` | `i.hotel_code` | GRAND·VISTA·DOUGLAS 합성 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `available_room_nights` | `PASS_THROUGH` | `i.available_room_nights` | `i.available_room_nights` | 물리 객실에서 고장·하우스유즈를 제외한 판매 가능 객실박 수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `occupied_room_nights` | `PASS_THROUGH_TRANSFORM` | `COALESCE(a.occupied_room_nights, 0)` | `a.occupied_room_nights` | 무료·하우스유즈를 제외한 실제 합성 점유 객실박 수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `room_revenue_krw` | `PASS_THROUGH_TRANSFORM` | `COALESCE(a.room_revenue_krw, CAST('0' AS DECIMAL))` | `a.room_revenue_krw` | 숙박일별 요금·할인을 물리 원장에서 합산한 일별 원화 합성 객실매출 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `occupancy_rate` | `DERIVED_EXPRESSION` | `CAST(COALESCE(a.occupied_room_nights, 0) AS DOUBLE) / NULLIF(i.available_room_nights, 0)` | `a.occupied_room_nights`, `i.available_room_nights` | occupied_room_nights / available_room_nights | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED` |
| `adr_krw` | `DERIVED_EXPRESSION` | `CAST(COALESCE(a.room_revenue_krw, CAST('0' AS DECIMAL)) AS DOUBLE) / NULLIF(a.occupied_room_nights, 0)` | `a.occupied_room_nights`, `a.room_revenue_krw` | room_revenue_krw / occupied_room_nights | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED` |
| `revpar_krw` | `DERIVED_EXPRESSION` | `CAST(COALESCE(a.room_revenue_krw, CAST('0' AS DECIMAL)) AS DOUBLE) / NULLIF(i.available_room_nights, 0)` | `a.room_revenue_krw`, `i.available_room_nights` | room_revenue_krw / available_room_nights | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED` |

### `serving.analytics_v4_3.room_monthly_kpi`

- 설명: 일별 객실 실적을 월·호텔 단위로 가중 재집계한 합성 객실 KPI
- SQL: `20_trino_room_views.sql`
- 직접 upstream: `serving.analytics_v4_3.room_daily`
- grain 후보: `month_start`, `hotel_code`

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `month_start` | `GROUPING_KEY` | `DATE_TRUNC('MONTH', business_date)` | `business_date` | KPI 집계월의 첫날 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `hotel_code` | `GROUPING_KEY` | `hotel_code` | `hotel_code` | 합성 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `available_room_nights` | `AGGREGATE` | `SUM(available_room_nights)` | `available_room_nights` | 월간 판매 가능 객실박 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `occupied_room_nights` | `AGGREGATE` | `SUM(occupied_room_nights)` | `occupied_room_nights` | 월간 점유 객실박 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `room_revenue_krw` | `AGGREGATE` | `SUM(room_revenue_krw)` | `room_revenue_krw` | 월간 합성 객실매출 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `occupancy_rate` | `AGGREGATED_DERIVATION` | `CAST(SUM(occupied_room_nights) AS DOUBLE) / NULLIF(SUM(available_room_nights), 0)` | `available_room_nights`, `occupied_room_nights` | 월간 점유 객실박/판매 가능 객실박 | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `adr_krw` | `AGGREGATED_DERIVATION` | `CAST(SUM(room_revenue_krw) AS DOUBLE) / NULLIF(SUM(occupied_room_nights), 0)` | `occupied_room_nights`, `room_revenue_krw` | 월간 객실매출/점유 객실박 | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |
| `revpar_krw` | `AGGREGATED_DERIVATION` | `CAST(SUM(room_revenue_krw) AS DOUBLE) / NULLIF(SUM(available_room_nights), 0)` | `available_room_nights`, `room_revenue_krw` | 월간 객실매출/판매 가능 객실박 | `BUSINESS_APPROVAL_REQUIRED`, `DENOMINATOR_AND_ZERO_POLICY_REQUIRED`, `NON_ADDITIVE_REDUCTION_REQUIRED`, `PREAGGREGATED_SOURCE_REVIEW_REQUIRED` |

### `serving.analytics_v4_3.staffing_daily`

- 설명: 호텔·영업일 단위로 근무조와 부서를 합산한 합성 인력 KPI
- SQL: `24_trino_facility_views.sql`
- 직접 upstream: `facility.walkerhill_v4_3.hotel_staffing_daily`
- grain 후보: `business_date`, `hotel_code`

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `business_date` | `GROUPING_KEY` | `business_date` | `business_date` | 인력 실적 영업일 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED` |
| `hotel_code` | `GROUPING_KEY` | `hotel_code` | `hotel_code` | 인력이 배치된 합성 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED` |
| `planned_hours` | `AGGREGATE` | `SUM(planned_hours)` | `planned_hours` | 부서·근무조 계획 근로시간 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `actual_hours` | `AGGREGATE` | `SUM(actual_hours)` | `actual_hours` | 부서·근무조 실제 근로시간 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `guest_facing_fte` | `AGGREGATE` | `SUM(guest_facing_fte)` | `guest_facing_fte` | 8시간 기준 고객 접점 합성 FTE 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `overtime_hours` | `AGGREGATE` | `SUM(overtime_hours)` | `overtime_hours` | 계획 대비 초과근로시간 합계 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `event_load_index` | `AGGREGATE` | `MAX(event_load_index)` | `event_load_index` | 해당 호텔 영업일의 최대 이벤트 부하 지수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `ROLLUP_POLICY_REQUIRED` |

### `serving.analytics_v4_3.voc_daily`

- 설명: 호텔·제출일·채널별 합성 VOC 평점과 감성·후속조치 건수를 집계한 일별 뷰
- SQL: `26_trino_voc_views.sql`
- 직접 upstream: `crm.walkerhill_v4_3.crm_voc_analysis`, `crm.walkerhill_v4_3.crm_voc_reviews`
- grain 후보: `business_date`, `hotel_code`, `source_channel`

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `business_date` | `GROUPING_KEY` | `r.source_business_date` | `r.source_business_date` | 리뷰가 평가하는 원 운영 객체의 영업일 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED` |
| `hotel_code` | `GROUPING_KEY` | `r.hotel_code` | `r.hotel_code` | 리뷰 대상 합성 호텔 코드 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED` |
| `source_channel` | `GROUPING_KEY` | `r.source_channel` | `r.source_channel` | 리뷰 수집 채널 | `BUSINESS_APPROVAL_REQUIRED`, `DIMENSION_AND_GRAIN_REQUIRED` |
| `review_count` | `AGGREGATE` | `COUNT(*)` | 없음 | 일별 합성 리뷰 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `average_rating` | `AGGREGATE` | `ROUND(AVG(CAST(r.rating_overall AS DOUBLE)), 4)` | `r.rating_overall` | 1~5 종합 평점 평균 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED`, `WEIGHTING_POLICY_REQUIRED` |
| `low_rating_reviews` | `AGGREGATE` | `COUNT_IF(r.rating_overall <= 2)` | `r.rating_overall` | 1~2점 리뷰 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `negative_reviews` | `AGGREGATE` | `COUNT_IF(a.sentiment_label = 'NEGATIVE')` | `a.sentiment_label` | NEGATIVE 감성 리뷰 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `positive_reviews` | `AGGREGATE` | `COUNT_IF(a.sentiment_label = 'POSITIVE')` | `a.sentiment_label` | POSITIVE 감성 리뷰 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |
| `followup_reviews` | `AGGREGATE` | `COUNT_IF(a.requires_followup)` | `a.requires_followup` | 후속 확인 필요 리뷰 수 | `AGGREGATION_AND_REDUCTION_REQUIRED`, `BUSINESS_APPROVAL_REQUIRED` |

### `serving.analytics_v4_3.voc_review_detail`

- 설명: 원본 합성 평점·리뷰와 별도 감성·주제 분석을 1:1 결합한 VOC 검토 뷰
- SQL: `26_trino_voc_views.sql`
- 직접 upstream: `crm.walkerhill_v4_3.crm_voc_analysis`, `crm.walkerhill_v4_3.crm_voc_reviews`
- grain 후보: 없음 — 승인자가 명시해야 함

| 필드 | 구조 분류 | SQL 식 | 식 내부 컬럼 | 설명 | 필수 검토 |
|---|---|---|---|---|---|
| `voc_review_id` | `PASS_THROUGH` | `r.voc_review_id` | `r.voc_review_id` | 합성 VOC 리뷰 식별자 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `business_date` | `PASS_THROUGH` | `r.source_business_date` | `r.source_business_date` | 리뷰가 평가하는 원 운영 객체의 영업일 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `submitted_at` | `PASS_THROUGH` | `r.submitted_at` | `r.submitted_at` | 오프셋을 보존한 리뷰 제출 시각 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `hotel_code` | `PASS_THROUGH` | `r.hotel_code` | `r.hotel_code` | 리뷰 대상 GRAND·VISTA·DOUGLAS 코드 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `source_channel` | `PASS_THROUGH` | `r.source_channel` | `r.source_channel` | 내부 설문·QR 또는 외부 형식 합성 리뷰 채널 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `touchpoint` | `PASS_THROUGH` | `r.touchpoint` | `r.touchpoint` | ROOM·FNB·FACILITY 등 고객 여정 접점 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `selected_category` | `PASS_THROUGH` | `r.selected_category` | `r.selected_category` | 합성 고객이 선택한 원본 의견 범주 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `rating_overall` | `PASS_THROUGH` | `r.rating_overall` | `r.rating_overall` | 1~5 합성 종합 평점 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `rating_service` | `PASS_THROUGH` | `r.rating_service` | `r.rating_service` | 1~5 합성 서비스 평점 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `rating_cleanliness` | `PASS_THROUGH` | `r.rating_cleanliness` | `r.rating_cleanliness` | 객실 접점의 1~5 합성 청결 평점 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `rating_food` | `PASS_THROUGH` | `r.rating_food` | `r.rating_food` | 식음·연회 접점의 1~5 합성 음식 평점 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `rating_facility` | `PASS_THROUGH` | `r.rating_facility` | `r.rating_facility` | 시설 접점의 1~5 합성 시설 평점 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `rating_value` | `PASS_THROUGH` | `r.rating_value` | `r.rating_value` | 1~5 합성 가격 대비 가치 평점 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `review_title` | `PASS_THROUGH` | `r.review_title` | `r.review_title` | 평점 방향과 선택 범주를 반영한 합성 제목 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `review_text_original` | `PASS_THROUGH` | `r.review_text_original` | `r.review_text_original` | 실제 외부 문장을 복제하지 않은 한국어 합성 리뷰 원문 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `language_code` | `PASS_THROUGH` | `r.language_code` | `r.language_code` | 원문 ISO 639-1 언어 코드 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `is_external` | `PASS_THROUGH` | `r.is_external` | `r.is_external` | 외부 리뷰 형식 여부. 실제 수집 여부가 아님 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `sentiment_label` | `PASS_THROUGH` | `a.sentiment_label` | `a.sentiment_label` | POSITIVE·NEUTRAL·NEGATIVE 합성 감성 라벨 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `sentiment_score` | `PASS_THROUGH` | `a.sentiment_score` | `a.sentiment_score` | -1~1 합성 감성 점수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `primary_topic` | `PASS_THROUGH` | `a.primary_topic` | `a.primary_topic` | 규칙 분석기가 분류한 주요 운영 주제 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `urgency_level` | `PASS_THROUGH` | `a.urgency_level` | `a.urgency_level` | LOW·MEDIUM·HIGH 운영 확인 긴급도 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `requires_followup` | `PASS_THROUGH` | `a.requires_followup` | `a.requires_followup` | 저평점 후속 확인 필요 여부 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `analysis_confidence` | `PASS_THROUGH` | `a.analysis_confidence` | `a.analysis_confidence` | 0~1 합성 분석 신뢰도. 실제 모델 성능이 아님 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `related_source` | `PASS_THROUGH` | `r.related_source` | `r.related_source` | 관련 PMS·POS·시설·연회 객체 유형 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `related_id` | `PASS_THROUGH` | `r.related_id` | `r.related_id` | 관련 원천의 합성 논리 키 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `member_no` | `PASS_THROUGH` | `r.member_no` | `r.member_no` | 동의 기반 교차 도메인 분석용 합성 회원 키. 비회원은 NULL | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `outlet_id` | `PASS_THROUGH` | `r.outlet_id` | `r.outlet_id` | FNB 리뷰가 참조하는 합성 POS 업장 키 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `facility_id` | `PASS_THROUGH` | `r.facility_id` | `r.facility_id` | 시설 리뷰가 참조하는 합성 시설 키 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `visit_cohort` | `PASS_THROUGH` | `r.visit_cohort` | `r.visit_cohort` | NEW·RETURNING 합성 방문 코호트 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |
| `prior_visit_count` | `PASS_THROUGH` | `r.prior_visit_count` | `r.prior_visit_count` | 이번 이용 이전의 합성 방문 횟수 | `BUSINESS_APPROVAL_REQUIRED`, `UPSTREAM_SEMANTICS_REQUIRED` |

## 승인 기록란

- 승인 release/version:
- 승인 주체와 역할:
- 승인 시각:
- 승인된 view/field 목록:
- 보류 또는 거절 목록과 사유:
- DataHub read-back 검증 결과:

승인 전에는 이 문서를 runtime governance bundle이나 DataHub custom property로 변환하지 않는다.
