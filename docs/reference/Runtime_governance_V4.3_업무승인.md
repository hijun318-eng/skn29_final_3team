# Runtime governance V4.3 업무 승인

## 상태와 범위

- 결정 상태: **BUSINESS_APPROVED**
- 결정일: 2026-08-16 KST
- 적용 release: `V4.3` / `walkerhill-v4.3-sql-20260815-derived.1`
- 적용 schema: `serving.analytics_v4_3`
- SQL source SHA-256: `60e96f2002178e9b903024a96f0be33430afa08f61dcfc9ed6f44ca2d8483460`
- 데이터 성격: 실제 고객·영업 실적이 아닌 재현 가능한 합성 데이터
- 허용 목적: V4.3 분석 기능, SQL, 화면, 보고서, 권한 및 실패 경로 검증
- 금지 목적: 실제 워커힐 실적 공시, 회계·세무 판단, 인과 추론, 실제 고객 행동 일반화
- 기술 발행 상태: **NOT_PUBLISHED** — live physical check와 target·predecessor checksum 확인 후 명시적 발행이 필요하다.

이 결정은 [Runtime governance V4.3 승인 검토안](Runtime_governance_V4.3_승인검토안.md)의
구조적 근거와 위 SQL digest에만 적용한다. SQL 또는 schema가 바뀌면 자동 승계하지 않고 재검토한다.

## 공통 계약

- 금액 단위는 원화 `KRW`이며 V4.3 안에서만 합산한다.
- 일별 serving grain은 원칙적으로 `business_date + hotel_code`다. 월별 view는
  `month_start + hotel_code`이며 일별 additive component를 `SUM`한다.
- `hotel_analyst`는 합성 데이터 표시가 유지되는 분석 경로에서 승인된 지표만 조회할 수 있다.
- 비율과 평균은 일별 결과를 단순 평균하지 않는다. 승인된 분자·분모를 먼저 합산한 뒤 다시 계산한다.
- 분모가 0이면 `NULL`을 유지한다. 0%나 0원으로 바꾸어 의미를 만들지 않는다.
- future scenario인 2026-08-16~2026-08-31 값은 관측 실적이 아니라 동결 합성 시나리오로 표시한다.
- 원천·serving dataset의 synthetic provenance와 DataHub release tag를 결과와 보고서에서 제거하지 않는다.

## 1. 통합 운영매출

### 승인 정의

`total_operating_revenue_krw`는 다음 네 V4.3 serving component를 호텔·영업일별로 합한
**합성 운영매출 proxy**로 승인한다.

```text
room_revenue_krw
+ fnb_revenue_krw
+ banquet_revenue_krw
+ facility_revenue_krw
```

- 객실: `CHECKED_OUT`이며 complimentary·house-use가 아닌 숙박일의
  `net_room_revenue = gross_room_rate - discount_amount`다. 세금·봉사료는 포함하지 않는다.
- 식음: POS의
  `net_amount = item_gross - discount + service_charge + tax - refund - void`다.
  세금과 봉사료를 포함한다.
- 연회: 완료 행사 revenue line의
  `recognized_amount = gross_amount - discount_amount - reversal_amount`다.
  V4.3 생성본의 reversal은 0이다.
- 시설: 유료 이용의 `gross_amount`이며 원천 설명상 부가세를 포함한다.
- 한 도메인의 해당 일자 행이 없으면 integrated view의 기존 `COALESCE(..., 0)` 규칙을 따른다.

### 허용과 제한

- 일→월, 호텔 여러 개→전체의 `SUM`은 허용한다.
- `total_operating_revenue_krw`를 공식 회계매출, 세전매출, 순매출 또는 부가세 제외 매출로 부르지 않는다.
- 도메인별 세금·봉사료 포함 기준이 다르므로 외부 재무제표와 비교하거나 margin을 계산하지 않는다.
- 구성 component와 계산식을 항상 lineage로 제공한다. 구성 기준이 바뀌면 새 metric version과 재승인이 필요하다.

## 2. 이벤트 발생량과 효과 연결

### 승인 정의

- 이벤트 존재·기간은 `event_master`, 호텔·domain·metric별 영향 구간과 시나리오 값은
  `hotel_event_effect`를 사용한다.
- 같은 호텔·일자에 이벤트가 겹치면 integrated daily view가 사용하는
  `max_by(event_id, ROW(confidence, event_id))` 규칙으로 대표 이벤트 하나를 고른다.
- 생성 시 사용한 `uplift_min`, `uplift_mode`, `uplift_max`, lead/lag, capacity limit은
  합성 시나리오 parameter이며 관측 추정치가 아니다.
- `event_counterfactual_daily`의 비교 기준은 같은 호텔·metric의 행사 전후 35일 중
  모든 이벤트 영향 구간을 제외한 영업일 평균이다.
- `baseline_days >= 14`이고 counterfactual 분모가 0이 아닐 때만 비교 가능하다.
  `realized_uplift_rate = actual_metric_mean / counterfactual_metric_mean - 1`을 사용한다.

### 허용과 제한

- 행사 구간과 비행사일 구간의 합성 scenario 비교, 파이프라인 회귀검증, 시각화에만 허용한다.
- `realized_uplift_rate`를 인과효과, 증분매출, 실제 행사 ROI 또는 미래 예측 정확도로 표현하지 않는다.
- `baseline_quality=INSUFFICIENT`, 기준값 `NULL`, 기준값 0인 행은 분석에서 제외하고 보완 추정하지 않는다.
- 서로 다른 event·hotel·metric의 uplift rate는 합산하지 않는다. 필요 시 각 행과 표본일 수를 함께 제시한다.

## 3. VOC 사용 범위

### 승인 정의

- `crm_voc_reviews`의 평점·제목·본문·접점·연결 키는 모두 합성값이다.
- `is_external=true`는 외부 리뷰 형식이라는 뜻이며 실제 외부 플랫폼 수집을 의미하지 않는다.
- `sentiment_label`, `sentiment_score`, `primary_topic`, `urgency_level`,
  `requires_followup`, `analysis_confidence`는 `RULE_SENTIMENT_V1` 생성 규칙의 결과다.
- V4.3 실제 생성식에서 `sentiment_label`은 종합 평점 1~2=NEGATIVE, 3=NEUTRAL,
  4~5=POSITIVE이고, `requires_followup`은 종합 평점 1~2일 때 true다.
- 운영 귀속 시간은 제출시각이 아니라 `source_business_date`다.

### 허용과 제한

- 허용: UI·SQL·보고서·집계·lineage·권한·후속조치 흐름의 기능 검증,
  합성 규칙을 정답으로 하는 회귀평가.
- 금지: 실제 고객 감성 추정, 실제 VOC 품질 주장, 범용 NLP 학습, 모델 성능 평가,
  외부 리뷰 채널 성과 비교.
- `review_count`, 저평점·긍정·부정·후속조치 건수는 합산할 수 있다.
- `average_rating`의 상위 grain 집계는 `SUM(average_rating * review_count) / SUM(review_count)`만 허용한다.
  일별 평균의 단순 평균은 금지한다.
- review 원문과 member/source 연결 키를 결과에 불필요하게 노출하지 않고 aggregate view를 우선한다.

## 4. 연회 취소와 환입

### 승인 정의

- `cancelled_events`는 `booking_status='CANCELLED'`인 행사 건수이며 행사일에 귀속한다.
- 운영 행사·참석자·계약금액은 `COMPLETED`와 `CONFIRMED`만 포함하고 취소 행은 제외한다.
- V4.3 `banquet_revenue_lines`는 `COMPLETED` 행사에만 생성된다.
- V4.3 생성본에는 취소 수수료 line이 없으며 `reversal_amount`는 항상 0이다.

### 허용과 제한

- 취소 건수와 취소율의 분자 후보로 `cancelled_events`를 사용할 수 있다.
  취소율을 발행하려면 분모를 전체 예약 건수로 할지 운영+취소 건수로 할지 별도 metric 정의가 필요하다.
- 취소 수수료, 취소 매출, 환입 손익은 V4.3에 존재하지 않으므로 metric으로 발행하지 않는다.
- `contracted_amount_krw`나 `recognized_revenue_krw`에서 취소 수수료를 역산하지 않는다.
- 향후 non-zero reversal 또는 cancellation fee line을 적재하면 새 schema/data version에서 재승인한다.

## 발행 전 잔여 Gate

### 승인된 metric publication 후보

| metric ID | 표시명·alias | source field | aggregation / reduction | 단위 | 추가 제약 |
|---|---|---|---|---|---|
| `total_operating_revenue_krw` | 합성 통합 운영매출, 합성 운영매출 | `hotel_operations_daily.total_operating_revenue_krw` | `sum / sum` | `KRW` | 구성 4개 component와 synthetic 표기를 함께 제공 |
| `voc_review_count` | 합성 VOC 리뷰 수, 리뷰 건수 | `voc_daily.review_count` | `sum / sum` | `count` | `source_business_date` 기준 |
| `voc_low_rating_reviews` | 합성 저평점 리뷰 수, 1~2점 리뷰 수 | `voc_daily.low_rating_reviews` | `sum / sum` | `count` | V4.3 rating rule에만 적용 |
| `voc_negative_reviews` | 합성 부정 리뷰 수, NEGATIVE 리뷰 수 | `voc_daily.negative_reviews` | `sum / sum` | `count` | `RULE_SENTIMENT_V1`에만 적용 |
| `voc_positive_reviews` | 합성 긍정 리뷰 수, POSITIVE 리뷰 수 | `voc_daily.positive_reviews` | `sum / sum` | `count` | `RULE_SENTIMENT_V1`에만 적용 |
| `voc_followup_reviews` | 합성 후속확인 리뷰 수, 후속조치 리뷰 수 | `voc_daily.followup_reviews` | `sum / sum` | `count` | V4.3에서는 rating 1~2 규칙 |
| `banquet_cancelled_events` | 합성 취소 연회 건수, 취소 행사 수 | `banquet_daily.cancelled_events` | `sum / sum` | `count` | 행사일 기준, 취소 수수료 의미 없음 |

`hotel_analyst`가 synthetic provenance가 표시되는 분석 경로에서 위 후보를 조회하도록 승인한다.
실제 policy에서는 각 source asset의 serving domain entitlement도 함께 요구한다.

### 기술 보류

- `event_counterfactual_daily.realized_uplift_rate`: 업무 의미는 승인됐지만
  `baseline_quality=USABLE`을 서버 소유 고정값으로 강제하는 parameter allowed-value 계약이
  아직 없다. 호출자가 다른 quality 값을 넣을 수 있는 현재 계약으로는 발행하지 않는다.
- `voc_daily.average_rating`: 업무 정의는 승인됐지만 상위 grain에서 `review_count` 가중식이 필요하다.
  현재 단일-column source 계약으로 단순 평균을 발행하면 틀리므로 multi-column weighted reduction 지원 전까지 보류한다.
- 연회 취소율: 분모가 승인되지 않았다. 전체 예약 또는 운영+취소 중 하나를 별도 결정하기 전까지 보류한다.
- `reversal_amount_krw`와 취소 수수료: 현재 생성값이 구조적 0이고 수수료 line이 없어 보류가 아니라 **존재하지 않는 metric**으로 처리한다.
- `actual_metric_mean`·`counterfactual_metric_mean`: `metric_name`에 따라 count·KRW·ratio가 섞여 단일 unit metric으로 발행하지 않는다.

### 잔여 기술 Gate

1. 51개 asset의 grain·column role·entitlement를 live DataHub key metadata와 exact 비교한다.
2. authoring `--check`로 policy·physical scope·predecessor·target hash를 생성한다.
3. 사용자가 확인한 predecessor·target hash를 명시적 `--publish`에 다시 제시한다.
4. 발행 후 DataHub와 Trino의 content-derived catalog hash가 일치할 때만 runtime을 연다.
