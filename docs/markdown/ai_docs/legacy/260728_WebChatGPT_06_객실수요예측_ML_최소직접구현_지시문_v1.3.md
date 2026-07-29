# 웹 ChatGPT 객실수요예측 ML 최소 직접 구현 지시문 v1.3

작성일: 2026-07-28
기준 문서:

- `260728_호텔데이터허브_데이터베이스_설계서_통합본_v4.6.md`
- `260728_WebChatGPT_DB_테이블_컬럼_DDL_SQL생성_작업지시문_v1.4.md`
- `260728_WebChatGPT_01_PMS_SQL데이터생성_지시문_v2.2.md`
- `260728_WebChatGPT_02_POS_SQL데이터생성_지시문_v2.2.md`
- `260728_WebChatGPT_03_CRM_SQL데이터생성_지시문_v2.2.md`
- `260728_WebChatGPT_04_Facility_SQL데이터생성_지시문_v2.2.md`
- `260728_WebChatGPT_05_Banquet_SQL데이터생성_지시문_v2.2.md`

작업 목적: 웹 ChatGPT가 기존 1~5번 Source 데이터를 활용하는 객실수요예측 ML 최소 구현 코드와 실행 문서를 직접 생성한다.
구현 수준: 웹 ChatGPT가 직접 생성하는 시연 가능한 Baseline + ML 모델 + 평가 + 7일 예측
추가 합성데이터 생성: 금지
추가 물리 학습테이블 생성: 금지
모델 범위: 객실수요예측 1개

---

## 이 문서의 사용 방법

이 문서는 외부 코딩 에이전트 전달용이 아니라 **웹 ChatGPT 직접 실행 지시문**이다.

이 문서가 웹 ChatGPT에 업로드되거나 내용으로 제공되면 다음과 같이 행동한다.

1. 사용자가 다른 개발 도구에서 실행하도록 안내하지 않는다.
2. 사용자가 프롬프트를 다시 복사하도록 요구하지 않는다.
3. 설명만 제공하고 작업을 종료하지 않는다.
4. 아래 명세에 따라 Python·SQL·README·테스트 파일을 직접 생성한다.
5. 생성 파일은 `/mnt/data`에 저장한다.
6. 긴 코드를 채팅 본문에 전부 출력하지 않는다.
7. 최종 결과물을 ZIP 하나로 묶는다.
8. 실제 DB·Trino 연결정보가 없으면 코드 생성과 정적 검증까지만 수행한다.
9. DB 연결이 없는데 학습 성능이나 행 수를 임의로 만들어 내지 않는다.
10. 최종 응답에는 ZIP 링크, 개별 핵심 파일 링크, 검증 상태만 제공한다.

### 최종 생성 파일

```text
260728_객실수요예측_ML_최소구현_v1.3/
├─ ml/
│  ├─ sql/
│  │  └─ room_demand_feature_query.sql
│  ├─ train_room_demand.py
│  ├─ predict_room_demand.py
│  ├─ evaluate_room_demand.py
│  ├─ config.py
│  ├─ metrics.py
│  └─ __init__.py
├─ tests/
│  ├─ test_time_split.py
│  ├─ test_metrics.py
│  ├─ test_leakage_rules.py
│  ├─ test_prediction_bounds.py
│  ├─ test_feature_contract.py
│  └─ test_reproducibility_metadata.py
├─ contracts/
│  └─ room_demand_feature_set_registration.json
├─ artifacts/
│  └─ .gitkeep
├─ outputs/
│  └─ .gitkeep
├─ requirements.txt
├─ .env.example
├─ README.md
└─ implementation_report.md
```

최종 ZIP:

```text
260728_객실수요예측_ML_최소구현_v1.3.zip
```


## 1. 결론

현재 v4.6 설계와 1~5번 v2.2 생성 데이터만으로 최소 객실수요예측 ML을 구현할 수 있다.
단, 아래 point-in-time 계약을 적용하지 않으면 학습 데이터 누수가 발생하므로 구현을 진행하면 안 된다.

다음 항목은 새로 만들지 않는다.

```text
별도 ML 원천 데이터
별도 Feature Store
별도 학습용 DB
analytics.room_demand_daily 물리 테이블
analytics.room_booking_curve_daily 물리 테이블
ml.room_demand_training_snapshots 물리 테이블
외부 공개 호텔 데이터 복제본
딥러닝 모델
실시간 스트리밍
MLOps 플랫폼
```

학습 시점마다 Trino SQL을 실행하고, 결과를 Python DataFrame으로 받아 메모리에서 Feature·Label을 구성한다.

```text
1~5번 Source DB
→ Trino Feature Query
→ pandas DataFrame
→ 시간순 분할
→ Baseline
→ RandomForest 모델
→ 평가
→ 모델 파일 저장
→ 향후 7일 예측
```

이 구조는 별도 학습데이터 적재 없이도 다음 ML 구성요소를 갖춘다.

- 명확한 예측 대상
- Feature·Label 정의
- 시간 기준 데이터 분할
- Baseline 모델
- ML 모델
- 평가 지표
- 모델 저장
- 예측 결과
- 데이터 누수 검증
- 재현 가능한 seed

### 1.1 v4.6 연계 검증 결과

연계 가능한 입력:

| 입력 | v4.6 자산 | 판정 |
|---|---|---|
| 일별 객실 공급 | `pms_room_inventory_daily` | 사용 가능, cutoff 이전에 알려진 행만 사용 |
| 예약잔량 | `pms_reservations` | `booked_at`·`cancelled_at`으로 제한적 시점 복원 가능 |
| 실제 판매 객실 Label | `pms_stays` | 완료 stay만 숙박일별 전개 |
| 멤버십 시점 등급 | `crm_member_grade_history` | `[valid_from, valid_to)`로 사용 가능 |
| F&B lag | `pos_orders`·`pos_service_periods` | cutoff 이전 관측값만 사용 |
| 시설 downtime lag | `facility_events` | cutoff 이전 관측값만 사용 |
| 연회 확정 객실 블록 | `banquet_bookings` | cutoff 이전 확정·수정 행만 사용 |
| 향후 7일 공급·예약 | PMS future inventory·on-the-books reservation | 예측 모드에서 사용 가능 |

기본 제외:

- 현재 snapshot인 `crm_members.membership_grade`를 과거 Feature로 사용하지 않는다.
- 과거 상태 이력이 없는 `facility_events.event_status`로 예정 점검 이력을 복원하지 않는다.
- 과거 snapshot이 없는 `banquet_bookings.pickup_room_count`를 학습 Feature로 사용하지 않는다.
- 최종 `reservation_status`를 과거 cutoff의 예약 상태로 사용하지 않는다.
- `is_forecast=true` Source 행을 Label로 사용하지 않는다.

연계 판정:

```text
STATIC_DATA_CONTRACT = PASS
POINT_IN_TIME_RULES  = REQUIRED
TRINO_QUERY          = NOT_RUN
MODEL_TRAINING       = NOT_RUN
```

### 1.2 변경된 5인 병렬구현 계약 연계

ML Feature Query는 R2가 제공한 5개 source binding을 그대로 사용한다.

| source_id | DataHub platform instance | Trino catalog | ML 사용 |
|---|---|---|---|
| `pms` | `hotel_pms` | `pms` | 필수 Feature·Label |
| `pos` | `hotel_pos` | `pos` | 선택 lag Feature |
| `crm` | `hotel_crm` | `crm` | 선택 identity·event-time grade Feature |
| `facility` | `hotel_facility` | `facility` | 선택 downtime Feature |
| `banquet` | `hotel_banquet` | `banquet` | 선택 확정 객실 블록 Feature |

- Feature SQL은 승인된 DataHub URN↔Trino FQN `asset_binding`과 `join_policy`만 사용한다.
- `customer_identity_map`은 논리 이름이고 물리 테이블은 `crm_customer_map`이다.
- Facility의 `usage`·`inspection`·`incident`는 `facility_events.event_type`으로 구분한다.
- POS `payment`은 `pos_orders`의 결제 컬럼, Banquet `product`는 두 fact의 `product_code/category`로 구현한다.
- R1의 필수 수용 30건과 Gold 120건은 대화형 분석·NL2SQL 평가용이다. 객실수요예측의 시계열 train/validation/test 행이나 Label로 재사용하지 않는다.
- 다만 같은 `seed`, schema/scenario/fixture version, `as_of`, timezone, source watermark, policy version을 사용해 두 평가의 재현 조건을 맞춘다.

---

## 2. 구현 원칙

### 2.1 반드시 지킬 것

1. 기존 1~5번 Source 데이터를 읽기 전용으로 사용한다.
2. Source DB에 새로운 데이터나 테이블을 추가하지 않는다.
3. Feature Query는 Trino에서 실행한다.
4. SQL 결과는 실행 중 DataFrame으로만 유지한다.
5. Forecast Source 행은 학습 Label에 사용하지 않는다.
6. 모든 Feature는 해당 예측 기준시각에 알 수 있었던 값만 사용한다.
7. 무작위 train/test 분할을 사용하지 않는다.
8. 모델 성능을 Seasonal Naive와 비교한다.
9. 합성 데이터 성능을 실제 호텔 성능으로 표현하지 않는다.
10. 실제 DB 연결이 없으면 테스트 결과를 성공으로 꾸미지 않는다.
11. 학습·평가·예측은 같은 Feature schema와 전처리 Pipeline을 사용한다.
12. 모델 metadata에 schema/scenario version, SQL hash, source watermark, split, seed, library version을 기록한다.
13. 모든 경로는 생성 ZIP 기준 상대경로를 사용한다.
14. Python 파일 하나가 300줄을 넘으면 query, service, repository, schema 역할로 분리한다.
15. Trino query identity는 `hotel_analyst` 범위의 read-only credential을 사용하고 DDL·DML·procedure·passthrough·`system` catalog를 호출하지 않는다.
16. Feature dataset, model input/output, log, metadata, API, CSV에 direct identifier나 secret 원문을 남기지 않는다.
17. `access-policy.yaml`의 policy version·content hash와 Context release를 실행 metadata에 기록한다.

### 2.2 구현하지 않을 것

```text
TensorFlow
PyTorch
LSTM
TFT
DeepAR
Hyperparameter 대규모 탐색
Feature Store
Airflow
MLflow 서버
모델 자동 재학습
실시간 예측
외부 날씨 API
경쟁호텔 가격
고객 개인정보
```

---

## 3. 예측 문제 정의

### 예측 대상

객실 유형별 향후 1~7일의 판매 객실 수를 예측한다.

```text
target = rooms_sold
grain  = property_id + target_date + room_type_code + horizon_days
```

### 예측 범위

```text
horizon_days = 1, 2, 3, 4, 5, 6, 7
```

### 기준시각

각 학습 행의 Feature는 다음 시각 **미만**에 알 수 있었던 값만 사용한다.

```text
prediction_cutoff_date = target_date - horizon_days
prediction_cutoff_at   = prediction_cutoff_date 00:00:00 Asia/Seoul
```

예:

```text
target_date            = 2026-07-20
horizon_days           = 7
prediction_cutoff_date = 2026-07-13
prediction_cutoff_at   = 2026-07-13T00:00:00+09:00
```

7월 13일 00시 이후 생성·변경된 예약·주문·포인트·시설 이벤트·연회 확정은 해당 행의 Feature로 사용하지 않는다.

비교 규칙:

```text
event_at < prediction_cutoff_at
source_updated_at < prediction_cutoff_at
known_at < prediction_cutoff_at
```

date 컬럼을 timestamp와 직접 비교하지 않는다.
MySQL·SQL Server·ClickHouse의 UTC 시각을 먼저 `Asia/Seoul` 기준 cutoff의 UTC 값과 비교한다.

---

## 4. 기존 데이터 활용 범위

1~5번 데이터를 모두 새 데이터 생성 없이 조회할 수 있다.

| Source | 필수 여부 | 최소 Feature |
|---|---|---|
| PMS | 필수 | 객실공급, 실제 판매 객실, 예약잔량, 취소, ADR, lag 수요 |
| POS | 선택 기본 ON | 직전 7일 F&B 이용객·순매출 |
| CRM | 선택 기본 ON | 예약잔량 중 멤버십 연결 비율·cutoff 시점 VIP 비율 |
| Facility | 선택 기본 ON | cutoff 이전 7일 downtime |
| Banquet | 선택 기본 ON | cutoff 이전 확정 객실 블록·예상 객실박 |

모든 부가 Feature가 없어도 PMS만으로 모델이 실행되어야 한다.

부가 Source 조회가 실패하면 전체 학습을 실패시키지 않고 다음과 같이 처리한다.

```text
PMS 실패      → 전체 실패
POS 실패      → 관련 Feature NULL, pos_source_available=0, 경고
CRM 실패      → 관련 Feature NULL, crm_source_available=0, 경고
Facility 실패 → 관련 Feature NULL, facility_source_available=0, 경고
Banquet 실패  → 관련 Feature NULL, banquet_source_available=0, 경고
```

실제 값 0과 Source 미가용을 같은 값으로 표현하지 않는다.

---

## 5. 최소 Feature 정의

### 5.1 PMS 필수 Feature

```text
target_date
room_type_code
horizon_days
available_room_nights
inventory_plan_known

booking_on_hand
cancelled_on_hand
booking_on_hand_ratio

rooms_sold_cutoff_lag_1
rooms_sold_cutoff_lag_7
rooms_sold_cutoff_lag_14
rooms_sold_cutoff_rolling_mean_7
rooms_sold_cutoff_rolling_mean_28

adr_cutoff_lag_7
cancellation_rate_cutoff_lag_28

target_day_of_week
target_month
target_is_weekend
target_is_month_start
target_is_month_end
```

모든 lag·rolling window는 `target_date`가 아니라 `prediction_cutoff_date`를 기준으로 계산한다.
window의 마지막 포함 일자는 `prediction_cutoff_date - 1일`이다.

PMS 예약잔량은 최종 `reservation_status` 대신 다음 규칙으로 재구성한다.

```text
booked_at < prediction_cutoff_at
cancelled_on_hand = cancelled_at < prediction_cutoff_at
booking_on_hand = booked_at < prediction_cutoff_at
                  AND (cancelled_at IS NULL OR cancelled_at >= prediction_cutoff_at)
                  AND checkin_date <= target_date
                  AND target_date < checkout_date
```

`source_updated_at`이 cutoff 이후인 행에서는 cutoff 이후에만 알 수 있는 상태·금액 컬럼을 사용하지 않는다.

목표일 inventory는 `source_updated_at < prediction_cutoff_at`인 계획 행만 사용한다.
없으면 객실유형별 과거에 알려진 `physical_rooms`를 공급 상한으로 사용하고 `inventory_plan_known=0`으로 표시한다.
실제 발생한 OOO·house-use를 과거 cutoff Feature로 소급 사용하지 않는다.

### 5.2 POS 보조 Feature

예측 cutoff 이전 7일만 사용한다.

```text
fnb_covers_lag_7d
fnb_net_amount_lag_7d
pos_source_available
```

```text
ordered_at >= prediction_cutoff_at - INTERVAL '7' DAY
ordered_at < prediction_cutoff_at
source_updated_at < prediction_cutoff_at
```

### 5.3 CRM 보조 Feature

예측 기준일에 존재하는 on-the-books 예약만 사용한다.

```text
member_booking_ratio
vip_booking_ratio
crm_source_available
```

CRM mapping과 등급은 모두 cutoff 시점 유효기간을 적용한다.

```text
map.valid_from < prediction_cutoff_at
AND (map.valid_to IS NULL OR prediction_cutoff_at < map.valid_to)
AND map.source_updated_at < prediction_cutoff_at

grade.valid_from < prediction_cutoff_at
AND (grade.valid_to IS NULL OR prediction_cutoff_at < grade.valid_to)
AND grade.source_updated_at < prediction_cutoff_at
```

`vip_booking_ratio`는 `crm_member_grade_history.grade_code='VIP'`로 계산한다.
현재 snapshot인 `crm_members.membership_grade`를 사용하지 않는다.

### 5.4 Facility 보조 Feature

```text
facility_downtime_lag_7d
facility_source_available
```

`event_at`과 `source_updated_at`이 모두 cutoff 이전인 INCIDENT만 사용한다.
현재 schema에는 상태 변경 이력이 없으므로 `scheduled_inspection_count_target_date`는 기본 Feature에서 제외한다.
미래 이용·미래 장애 데이터는 사용하지 않는다.

### 5.5 Banquet 보조 Feature

```text
confirmed_banquet_count
confirmed_banquet_expected_guests
confirmed_room_block_count
confirmed_expected_room_nights
banquet_source_available
```

다음 조건을 모두 만족해야 한다.

```text
confirmed_at < prediction_cutoff_at
source_updated_at < prediction_cutoff_at
cancelled_at IS NULL OR cancelled_at >= prediction_cutoff_at
group_checkin_date <= target_date
group_checkout_date > target_date
```

최종 `booking_status`만으로 과거 상태를 판정하지 않는다.
과거 snapshot이 없는 `pickup_room_count`는 학습 Feature에서 제외한다.

---

## 6. Label 정의

PMS 실제 투숙 데이터에서 목표일의 판매 객실 수를 계산한다.

```text
rooms_sold
= 목표일에 실제 점유된 객실 수
```

조건:

```text
pms_stays.is_forecast = false
pms_stays.data_period_status IN (
  REFERENCE_CALIBRATED,
  SYNTHETIC_ACTUAL_LIKE,
  YTD_SYNTHETIC
)
stay_status = COMPLETED
```

한 투숙이 여러 날이면 체크인일부터 체크아웃 전날까지 일자별로 펼친다.

```text
actual_checkin_date <= target_date < actual_checkout_date
```

Label은 `property_id + target_date + room_type_code`별 고유 `room_unit_code` 수로 계산한다.
`IN_HOUSE`는 아직 최종 결과가 아니므로 학습 Label에서 제외한다.

무료 객실과 내부 사용 객실은 기본 Label에서 제외한다.

```text
complimentary_flag = false
house_use_flag = false
```

---

## 7. 데이터 기간과 분할

### 학습 대상 기간

```text
2022-01-01 ~ 2026-07-27
```

Forecast 구간과 생성 기준일에 아직 완료되지 않은 `2026-07-28` 영업일은 제외한다.

### 분할

```text
Train
2022-01-01 ~ 2024-12-31

Validation
2025-01-01 ~ 2025-12-31

Test
2026-01-01 ~ 2026-07-27
```

행 단위 무작위 분할은 금지한다.

같은 `target_date`의 서로 다른 객실 유형과 horizon이 서로 다른 분할에 들어가면 안 된다.

각 split의 초기 lag 부족 행은 해당 split 이전 과거 데이터로 Feature를 계산할 수 있지만,
Label과 평가 행은 지정 split 밖으로 이동시키지 않는다.

---

## 8. Feature Query 구현

다음 파일을 생성한다.

```text
ml/sql/room_demand_feature_query.sql
```

### Query 요구사항

1. Trino SQL로 작성한다.
2. CTE를 사용해 한 파일로 구성한다.
3. 물리 View나 물리 테이블을 생성하지 않는다.
4. `CREATE TABLE AS`, `INSERT`, `UPDATE`, `DELETE`를 사용하지 않는다.
5. 최종 결과는 학습 가능한 평면 테이블이다.
6. `horizon_days` 1~7을 `UNNEST(SEQUENCE(1, 7))`로 생성한다.
7. `prediction_cutoff_date` 기준으로 Feature를 제한한다.
8. Source별 CTE를 독립적으로 구성한다.
9. 부가 Source Feature는 LEFT JOIN한다.
10. Label이 없는 미래 target_date는 예측 모드에서만 반환한다.
11. parameter는 `mode`, `as_of_at`, `train_start`, `train_end`를 typed binding으로 받는다.
12. 학습 모드는 `target_date <= 2026-07-27`, 예측 모드는 `as_of_at` 다음 1~7일만 반환한다.
13. 모든 timestamp 비교는 UTC로 정규화한 `prediction_cutoff_at`을 사용한다.
14. 최종 정렬은 `property_id, target_date, room_type_code, horizon_days`로 고정한다.
15. source별 row count·watermark와 최종 dataset checksum을 별도 검증 SELECT로 제공한다.

### 최종 컬럼

```text
property_id
target_date
room_type_code
horizon_days
prediction_cutoff_date
prediction_cutoff_at_utc

available_room_nights
inventory_plan_known
booking_on_hand
cancelled_on_hand
booking_on_hand_ratio

rooms_sold_cutoff_lag_1
rooms_sold_cutoff_lag_7
rooms_sold_cutoff_lag_14
rooms_sold_cutoff_rolling_mean_7
rooms_sold_cutoff_rolling_mean_28

adr_cutoff_lag_7
cancellation_rate_cutoff_lag_28

fnb_covers_lag_7d
fnb_net_amount_lag_7d
pos_source_available
member_booking_ratio
vip_booking_ratio
crm_source_available
facility_downtime_lag_7d
facility_source_available
confirmed_banquet_count
confirmed_banquet_expected_guests
confirmed_room_block_count
confirmed_expected_room_nights
banquet_source_available

target_day_of_week
target_month
target_is_weekend
target_is_month_start
target_is_month_end

rooms_sold
```

학습 모드의 `rooms_sold`는 NOT NULL이어야 하고, 예측 모드에서는 NULL이어야 한다.

---

## 9. 모델 구현

### 사용 모델

```text
Baseline:
Seasonal Naive

ML:
scikit-learn RandomForestRegressor
```

딥러닝이나 별도 Boosting 라이브러리는 사용하지 않는다.

### Baseline

```text
candidate_date = target_date - 7 × k일 중 prediction_cutoff_date보다 이른 가장 최근 동일 요일
prediction = candidate_date의 rooms_sold
```

`target_date-7일`이 cutoff와 같거나 이후이면 `target_date-14일` 등 더 이전 동일 요일을 사용한다.
동일 요일 값이 없으면 cutoff 이전 객실유형별 최근 28일 평균을 사용한다.

### ML 기본 파라미터

```python
RandomForestRegressor(
    n_estimators=300,
    max_depth=12,
    min_samples_leaf=5,
    max_features="sqrt",
    random_state=20260728,
    n_jobs=-1,
)
```

과도한 튜닝은 하지 않는다.

### 전처리

```text
숫자형:
실제 값 결측은 train median
Source 미가용 Feature는 NULL + source_available=0

범주형:
room_type_code one-hot encoding

날짜:
원본 날짜 문자열은 모델에 직접 넣지 않음
```

`Pipeline`과 `ColumnTransformer`를 사용한다.
median·one-hot category는 Train split에서만 fit하고 Validation·Test·예측에는 transform만 적용한다.

모델 입력에서 다음 식별·시간 원문·Label은 제외한다.

```text
property_id
target_date
prediction_cutoff_date
prediction_cutoff_at_utc
rooms_sold
```

`horizon_days`, calendar 파생 Feature, source availability flag는 모델 입력에 포함한다.

---

## 10. 생성할 코드

```text
ml/
├─ sql/
│  └─ room_demand_feature_query.sql
├─ train_room_demand.py
├─ predict_room_demand.py
├─ evaluate_room_demand.py

artifacts/
├─ room_demand_model.joblib
├─ room_demand_metrics.json
├─ room_demand_feature_columns.json
├─ room_demand_model_metadata.json
└─ room_demand_data_profile.json

contracts/
└─ room_demand_feature_set_registration.json

outputs/
└─ room_demand_forecast_YYYYMMDD.csv
```

`room_demand_model_metadata.json` 필수 항목:

```text
model_version
schema_version=schema-v4.6-websql
scenario_version=scenario-v4.6
fixture_version=source-fixture-v4.6
synthetic=true
generated_at=2026-07-28T05:00:00Z
feature_contract_version=room-demand-feature-v1.3
seed=20260728
feature_sql_sha256
dataset_sha256
source_watermark_set
source_asset_urns
source_trino_fqns
context_release
access_policy_version
access_policy_hash
train/validation/test date range
row count by split
library versions
trained_at
```

`contracts/room_demand_feature_set_registration.json`은 Application P2 `ml.feature_sets` 등록용 payload이며 다음을 포함한다.

```text
feature_set_key=room_demand_daily
version_no=1
name=Room Demand Daily Feature Set
feature_schema_json
source_asset_urns_json
feature_query_sql_hash
sql_policy_version
event_time_field=prediction_cutoff_at_utc
as_of_rule_json
missing_value_policy_json
status=DRAFT
```

P2가 비활성 상태이면 payload 파일만 생성하고 Application DB에 직접 INSERT하지 않는다.
승인 API와 권한이 제공된 경우에만 별도 명시적 단계에서 등록한다.
Trino FQN, Context release, access policy hash는 현재 13컬럼 `ml.feature_sets`에 임의 필드를 추가하지 않고 model metadata와 `implementation_report.md`에 기록한다. FQN은 등록된 `source_asset_urns_json`의 승인 `asset_binding`에서 해석한다.

### `train_room_demand.py`

역할:

```text
Trino 연결
→ Feature Query 실행
→ 시간 분할
→ Baseline 평가
→ RandomForest 학습
→ Validation·Test 평가
→ 모델·컬럼·지표 저장
```

### `predict_room_demand.py`

역할:

```text
기준일 입력
→ 기준일 00:00:00 Asia/Seoul을 공통 cutoff로 고정
→ 기준일 다음 1~7일 Feature 조회
→ 모델 로드
→ 객실 유형별 예측
→ 0~available_room_nights 범위 clipping 후 정수 반올림
→ CSV 출력
```

### `evaluate_room_demand.py`

역할:

```text
Baseline과 ML 비교
객실 유형별 성능
horizon별 성능
전체 성능
오차가 큰 날짜 20건
```

---

## 11. 평가 지표

다음 네 개만 사용한다.

```text
MAE
RMSE
WAPE
R2
```

MAPE는 판매 객실 수가 0인 행에서 불안정하므로 필수 지표로 사용하지 않는다.
WAPE 분모가 0인 평가 집합은 `NOT_EVALUABLE_ZERO_ACTUAL`로 표시하고 0으로 대체하지 않는다.

### 수용 기준

```text
학습 행 수 >= 20,000
PMS orphan 또는 시간 역전 = 0
forecast Label 행 = 0
Train/Validation/Test 날짜 중복 = 0
target_date 기준 lag가 cutoff 이후를 참조한 행 = 0
cutoff 이후 source_updated_at Feature 행 = 0
현재 CRM snapshot 등급을 사용한 과거 Feature = 0
예정 점검·pickup snapshot 누수 Feature = 0
동일 입력 재실행 dataset checksum 불일치 = 0
예측값 < 0 = 0
예측값 > available_room_nights = 0
ML Test WAPE <= Seasonal Naive Test WAPE
```

ML이 Baseline보다 나쁘면 숨기지 않는다.

```text
model_status = BASELINE_BETTER
```

이 경우에도 파이프라인 구현 결과는 인정하되 최종 예측은 Seasonal Naive를 사용한다.

---

## 12. 최소 시연 화면·결과

별도 대시보드를 새로 만들지 않는다.

기존 화면 또는 간단한 결과 카드에 다음만 표시한다.

```text
예측 기준일
향후 7일 객실 유형별 예상 판매 객실
예상 OCC
Baseline WAPE
ML WAPE
채택 모델
가장 영향이 큰 Feature 5개
합성 데이터 사용 안내
```

Feature 중요도는 RandomForest의 `feature_importances_`를 사용한다.

---

## 13. API 최소 범위

API 구현이 필요한 경우 하나만 만든다.

```text
GET /api/v1/ml/room-demand/forecast?as_of_date=YYYY-MM-DD
```

ML은 P2 선택 기능이다. API route 등록과 운영 feature flag 활성화는 별도 승인 전 수행하지 않는다.

응답 예시:

```json
{
  "as_of_date": "2026-07-28",
  "model_version": "room-demand-rf-v1",
  "feature_contract_version": "room-demand-feature-v1.3",
  "schema_version": "schema-v4.6-websql",
  "scenario_version": "scenario-v4.6",
  "model_status": "ML_SELECTED",
  "is_synthetic": true,
  "fixture_version": "source-fixture-v4.6",
  "context_release": "NOT_REGISTERED",
  "access_policy_version": "NOT_PROVIDED",
  "access_policy_hash": "NOT_PROVIDED",
  "source_watermark_set": {},
  "forecast": [
    {
      "target_date": "2026-07-29",
      "room_type_code": "STANDARD",
      "horizon_days": 1,
      "predicted_rooms_sold": 112,
      "available_room_nights": 147,
      "predicted_occupancy_rate": 0.7619
    }
  ]
}
```

API가 현재 MVP에 필요하지 않다면 CSV 산출로 종료한다.

---

## 14. 데이터 누수 검증

다음을 자동 테스트로 구현한다.

```text
booked_at >= prediction_cutoff_at인 예약 Feature 포함 0
cancelled_at < prediction_cutoff_at인 예약의 booking_on_hand 포함 0
target_date 기준 lag·rolling 계산 0
POS ordered_at >= prediction_cutoff_at인 행 사용 0
CRM joined_at >= prediction_cutoff_at인 회원 사용 0
CRM map·grade 유효기간 경계 위반 0
crm_members.membership_grade를 과거 VIP Feature에 사용 0
Facility event/source_updated_at >= prediction_cutoff_at인 행 사용 0
scheduled_inspection_count_target_date Feature 존재 0
Banquet confirmed_at/source_updated_at >= prediction_cutoff_at인 행사 사용 0
confirmed_pickup_room_count Feature 존재 0
is_forecast=true인 stay Label 사용 0
IN_HOUSE stay Label 사용 0
2026-07-28 Label 사용 0
Test 날짜가 Train에 포함 0
승인되지 않은 URN·FQN·JOIN 사용 0
다른 source의 우연히 같은 local ID 직접 JOIN 0
direct identifier·secret 원문 출력 0
```

---

## 15. 실패 처리

### Trino 연결 실패

```text
status = DATA_SOURCE_UNAVAILABLE
모델 학습 중단
```

### 부가 Source 실패

```text
PMS 외 Source:
경고 기록
고정 Feature schema 유지
해당 Feature NULL, source_available=0
PMS-only 모델 계속 실행
```

### 데이터 부족

```text
학습 행 수 < 5,000
→ 모델 학습 중단
→ Seasonal Naive만 출력
```

### ML 성능 미달

```text
ML WAPE > Baseline WAPE
→ Baseline 채택
→ 모델 파일은 실험 결과로만 저장
```

---

## 16. 완료 기준

다음 결과가 모두 존재해야 한다.

```text
Feature Query SQL
학습 코드
예측 코드
평가 코드
저장된 모델
metrics JSON
model metadata JSON
data profile JSON
향후 7일 예측 CSV
실행 방법
정적 테스트
```

저장된 모델·metrics·data profile·예측 CSV는 실제 Trino query와 학습이 성공한 경우에만 생성한다.
DB 비연결 환경에서는 `.gitkeep`만 유지하고 가짜 artifact·CSV를 만들지 않는다.

실제 DB·Trino가 없는 환경에서는 다음과 같이 기록한다.

```text
CODE_GENERATION = PASS
STATIC_TEST = PASS 또는 FAILED
DB_QUERY = NOT_RUN
MODEL_TRAINING = NOT_RUN
```

샘플 수치나 가짜 성능지표를 만들어 성공으로 표시하지 않는다.

---

## 17. 웹 ChatGPT 직접 구현 지시

1. 현재 대화에 제공된 기준 문서와 파일을 확인한다.
2. 기존 프로젝트 파일이 업로드되어 있으면 DB·Trino 연결 모듈을 우선 재사용한다.
3. 프로젝트 파일이 제공되지 않았으면 독립 실행 가능한 최소 패키지를 생성한다.
4. 새로운 프레임워크를 추가하지 않는다.
5. Python 의존성은 다음으로 제한한다.

```text
pandas
numpy
scikit-learn
joblib
trino
```

의존성은 실제 문법·테스트를 확인한 버전으로 `requirements.txt`에 정확히 고정한다. 임의 최신 버전 범위를 쓰지 않는다.

6. 환경변수는 기존 `.env.example` 규칙을 따르거나 새 `.env.example`을 생성한다.
7. 비밀번호·토큰을 코드에 넣지 않는다.
8. 테스트는 외부 DB 없이도 Feature 전처리·분할·지표 계산을 검증할 수 있게 작성한다.
9. 실제 DB가 연결되면 Feature Query부터 모델 평가까지 한 번에 실행할 수 있게 작성한다.
10. 작업 결과와 미실행 항목을 구분해 `implementation_report.md`에 기록한다.
11. 프로젝트 고유 폐기 명칭을 코드·주석·파일명에 사용하지 않는다.
12. 모든 파일을 생성한 뒤 Python 문법 검사와 단위 테스트를 실행한다.
13. 테스트가 실패하면 가능한 범위에서 수정하고 재실행한다.
14. 실제 DB 연결이 없어 실행하지 못한 항목은 `NOT_RUN`으로 남긴다.
15. 최종적으로 전체 파일을 ZIP으로 묶어 제공한다.
16. 핵심 코드는 `FeatureRepository`, `TrainingService`, `PredictionService`, `EvaluationService` 책임으로 분리한다.
17. 파일 하나가 300줄을 넘으면 역할별 module로 분리한다.
18. R2 adapter나 승인 connection module이 있으면 재사용하고, DataHub·Trino vendor client를 별도 중복 구현하지 않는다.
19. `implementation_report.md`에 source별 URN/FQN, watermark, row count, dataset checksum, policy version/hash와 실행 여부를 기록한다.
20. R1의 30/120 대화형 분석 fixture를 ML 학습 데이터로 읽는 코드가 있으면 실패 처리한다.

---

## 18. 구현 상태 표기

웹 ChatGPT는 최종 보고서에 다음 상태를 구분한다.

```text
FILE_GENERATION
PYTHON_SYNTAX_CHECK
STATIC_TEST
UNIT_TEST
TRINO_QUERY
MODEL_TRAINING
MODEL_EVALUATION
FORECAST_GENERATION
```

사용 가능한 상태값:

```text
PASS
FAILED
NOT_RUN
PARTIAL
```

DB 접속정보가 없을 때 허용되는 정상 결과:

```text
FILE_GENERATION      = PASS
PYTHON_SYNTAX_CHECK  = PASS
STATIC_TEST          = PASS
UNIT_TEST            = PASS
TRINO_QUERY          = NOT_RUN
MODEL_TRAINING       = NOT_RUN
MODEL_EVALUATION     = NOT_RUN
FORECAST_GENERATION  = NOT_RUN
```

합성 성능값이나 예측 CSV를 임의로 만들어 실행 완료처럼 표시하지 않는다.

---

## 19. 최종 판단 기준

이 구현은 다음 수준을 목표로 한다.

```text
실제 호텔 운영 배포 모델
X

합성 다중 DB 데이터를 활용한
재현 가능한 객실수요예측 ML MVP
O
```

모델이 복잡하지 않아도 다음이 확인되면 ML 구현으로 인정할 수 있다.

- 기존 데이터에서 Feature·Label을 생성했다.
- 시간순 데이터 분할을 적용했다.
- Baseline과 ML을 비교했다.
- 평가 지표를 기록했다.
- 모델을 저장하고 향후 7일을 예측했다.
- 데이터 누수를 자동 검증했다.
- 합성 데이터라는 한계를 명시했다.

이 범위를 넘는 딥러닝·자동 재학습·MLOps는 현재 구현 대상이 아니다.


---

## 20. 웹 ChatGPT 최종 실행 명령

이 문서를 받은 즉시 다음을 수행한다.

1. 지정한 폴더 구조와 파일을 생성한다.
2. Trino Feature Query SQL을 작성한다.
3. 학습·평가·예측 Python 코드를 작성한다.
4. 단위 테스트를 작성한다.
5. `requirements.txt`, `.env.example`, `README.md`를 작성한다.
6. Python 문법 검사와 DB 비의존 테스트를 실행한다.
7. 오류가 있으면 수정 후 재검증한다.
8. `implementation_report.md`에 실행·미실행 상태를 기록한다.
9. 모든 결과를 `260728_객실수요예측_ML_최소구현_v1.3.zip`으로 압축한다.
10. 최종 응답에는 다운로드 링크와 검증 요약만 제시한다.

사용자에게 다른 개발 도구를 사용하라고 안내하거나 별도 개발환경에서 대신 구현하라고 지시하지 않는다.
