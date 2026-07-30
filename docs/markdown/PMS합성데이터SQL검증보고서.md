# PMS 합성 데이터 SQL 검증 보고서

| 항목 | 내용 |
|---|---|
| 문서 설명 | 웹 ChatGPT 지시문으로 생성된 PMS PostgreSQL 합성 데이터 SQL의 지시문 준수 여부와 데이터 결함을 정적 검토한 결과 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-07-28 15:56 |
| 작성·수정 | 승 |
| 산출물 번호 | — |
| 제출 일자 | — |
| 대응 템플릿 | — |

## 1. 검증 개요

| 항목 | 내용 |
|---|---|
| 검증 대상 | `260728_01_pms_postgresql_2022_2026.sql` (1,815줄, 63,850 bytes) |
| 대상 위치 | 저장소 외부 (`Downloads/`). 저장소에 반입되지 않은 상태 |
| 기준 문서 | `260728_WebChatGPT_01_PMS_SQL데이터생성_지시문_v1.0.md` |
| 대상 범위 | `pms_guests`, `pms_room_inventory_daily`, `pms_reservations`, `pms_stays`, `pms_generation_audit` |
| 데이터 기간 | 2022-01-01 ~ 2026-12-31 (reference cutoff 2026-06-30) |
| 검증 방식 | 정적 코드 판독, 지시문 조항 대조, 수식 기반 수치 추정 |
| 검증 일자 | 2026-07-28 |

## 2. 검증 범위와 한계

### 2.1 수행한 검증

| 항목 | 방식 | 상태 |
|---|---|---|
| SQL 전문 판독 | 수동 | 완료 |
| 지시문 전 조항 준수 대조 | 수동 | 완료 |
| PostgreSQL 문법·제약·볼러틸리티 적합성 | 수동 | 완료 |
| 공휴일 날짜 세트 실제값 대조 | 수동 | 완료 |
| 행 수·OCC·ADR·RevPAR·ALOS | 수식 기반 추정 | 완료(추정) |

### 2.2 수행하지 못한 검증

**SQL을 실제로 실행하지 않았습니다.** 검증 환경에 `psql`이 설치되어 있지 않고 Docker daemon이 기동되지 않았습니다.

| 미검증 항목 | 상태 | 해소 조건 |
|---|---|---|
| 실제 생성 행 수 | Not Run | PostgreSQL 15+ 인스턴스 |
| 연도별 OCC·ADR·RevPAR 실측치 | Not Run | 동일 |
| 검증 쿼리 8.1~8.17 실행 결과 | Not Run | 동일 |
| `('x'\|\|substr(md5(...),1,8))::bit(32)::bigint` 부호 여부 | Not Run | 동일. 비음수로 판단했으나 미확인 |
| 실행 시간·메모리 사용량 | 미측정 | 동일 |

이 보고서의 모든 수치는 **추정치**이며 실측으로 대체되어야 합니다. 어떤 항목도 `Pass` 또는 `완료`로 기록하지 않았습니다.

## 3. 종합 판정

| 판정 | **조건부 부적합** |
|---|---|

스크립트는 문법상 실행 가능하며 지시문이 요구한 검증 11항목을 모두 구현하고 있고, 실행 시 전부 0을 반환할 것으로 판단합니다. 그러나 **그 검증들이 통과하는 상태에서도 집계값이 틀리는 구조적 결함 4건**이 존재합니다. 명시된 검증의 통과를 데이터 품질의 근거로 사용할 수 없습니다.

## 4. 발견사항 요약

| 심각도 | 건수 | 성격 |
|---|---|---|
| P0 치명 | 4 | 집계값 오류 또는 시간 논리 붕괴 |
| P1 중대 | 6 | 데모가 보여주려던 지표 신호 소실 |
| P2 운영 | 5 | 재현성·안전성·검증 실효성 |
| P3 갭 | 8 | 모델링 한계 및 스펙 미충족 |
| 합계 | 23 | — |

## 5. 지시문 준수 대조

### 5.1 필수 검증 쿼리 (11항목)

| 요구 | 구현 위치 | 준수 | 비고 |
|---|---|---|---|
| inventory 날짜·객실유형 중복 0 | 8.3 | 준수 | — |
| `available_room_nights` 계산 불일치 0 | 8.4 | 준수 | — |
| 판매 객실박 > 가용 객실박 0 | 8.5 | 준수 | — |
| `checkout_date <= checkin_date` 0 | 8.6 | 준수 | — |
| `booked_at >= checkin_date` 0 | 8.7 | 준수 | — |
| CANCELLED 예약의 stay 0 | 8.8 | 형식 준수 | 구조상 실패 불가 |
| NO_SHOW 예약의 `room_revenue > 0` 0 | 8.9 | 형식 준수 | 구조상 실패 불가 |
| `room_revenue < 0` 0 | 8.10 | 준수 | — |
| 2026-07-01 이후 `is_forecast=false` 0 | 8.11 | 준수 | — |
| 실제 개인정보 패턴 0 | 8.16 | 형식 준수 | 구조상 실패 불가 |
| 연도별 OCC·ADR·RevPAR | 8.17 | 미흡 | 2026년 실적+예측 혼합 출력 |

11항목 전부 존재하나 **실질 검증력은 7항목**입니다. 상세는 6.3 P2-5 참조.

### 5.2 공통 SQL 산출 원칙

| 요구 | 준수 | 근거 |
|---|---|---|
| 8단계 구조 (헤더~요약 SELECT) | 준수 | 전 단계 존재 |
| 행별 `INSERT` 반복 금지 | 준수 | 전부 집합 기반 |
| 날짜·sequence를 SQL 내부 집합 생성 | 준수 | `generate_series` 사용 |
| **동일 seed 재실행 시 동일 결과** | **미준수** | `DateStyle` 미고정. 6.3 P2-1 |
| fact table 4개 공통 컬럼 | 준수 | — |
| 금액 KRW·음수 불가 | 준수 | CHECK 제약 |
| **환불·취소를 별도 금액 컬럼으로 표현** | **미준수** | 컬럼 부재. 6.1 P0-4 |
| KPI 비율 원천 테이블 저장 금지 | 준수 | — |
| 검증 실패 은폐 `UPDATE` 없음 | 준수 | — |
| `random()` 단독 의존 금지 | 준수 | `random()` 미사용 |
| 단일 transaction / 사후 인덱스 / `ANALYZE` | 준수 | — |
| 담당 외 테이블 생성 금지 | 준수 | 금지 테이블 0건 |
| 개인정보 미생성 | 준수 | 실명·연락처·주소·번호류 없음 |

### 5.3 생성 규모

| 테이블 | 지시문 요구 | 추정치 | 판정 |
|---|---|---|---|
| `pms_guests` | 100,000 | 100,000 | 일치 |
| `pms_room_inventory_daily` | 7,304 | 7,304 (1,826일 × 4타입) | 일치 |
| `pms_reservations` | 170,000 ~ 240,000 | 약 174,000 | 밴드 하단 |
| `pms_stays` | 130,000 ~ 190,000 | 약 134,000 | 밴드 하단 |

밴드 내이나 하한에 근접합니다. 파라미터 미세 조정 시 이탈 가능하므로 **실행 후 재확인이 필요**합니다.

## 6. 상세 발견사항

### 6.1 P0 — 치명

#### P0-1. forecast 매출이 실적과 동일 컬럼에 적재

| 항목 | 내용 |
|---|---|
| 위치 | SQL 747행, 759행, 1711~1754행 |
| 현상 | 2026-07-01 이후 구간도 `room_revenue = booked_amount`로 채움 |
| 규모(추정) | 184일 × 297실 × OCC 0.79 ≈ 43,000 room night, 약 120억 KRW |
| 가중 요인 | 검증 8.17이 2026년을 한 행으로 합산하고 `'YTD_AND_FORECAST_SCENARIO'` 라벨 하나로 덮음 |
| 위반 조항 | `2026년 7~12월 데이터를 실제 실적 또는 확정치로 표현하지 않는다` |
| 영향 | Text-to-SQL에 "2026년 객실 매출"을 질의하면 실적+예측 혼합값 반환 |

```sql
SELECT is_forecast, count(*), sum(room_revenue)
FROM pms_stays
WHERE data_period_status IN ('YTD_SYNTHETIC', 'FORECAST_SCENARIO')
GROUP BY is_forecast;
```

지시문은 forecast 구간에 `제한된 forecast stay`를 허용했으나, 실제 구현은 하반기 재고 전체를 stay로 채웠습니다.

#### P0-2. `booked_at > source_updated_at` — 갱신 시점 이후에 발생한 예약

| 항목 | 내용 |
|---|---|
| 위치 | SQL 624행, 799행, 1183행 |
| 현상 | forecast 행의 `source_updated_at`은 생성 시각 `2026-07-28 05:00+00` 고정이나, `booked_at = checkin_date - lead_days` |
| 예시 | 체크인 2026-11-15, 리드타임 30일 → `booked_at = 2026-10-16` (갱신 시각보다 3개월 늦음) |
| 영향 | on-the-books 예약이 성립하지 않아 pickup / booking pace 분석 전면 무의미 |

```sql
SELECT count(*) FROM pms_reservations WHERE booked_at > source_updated_at;
```

#### P0-3. 고객 생성 이전에 존재하는 예약

| 항목 | 내용 |
|---|---|
| 위치 | SQL 200~202행, 554~562행 |
| 현상 | `created_at`은 2021-01-01부터 2,007일 균등 분포이나 `guest_no`는 예약 날짜와 무관하게 무작위 배정 |
| 규모(추정) | 전체 예약의 40~50% |
| 영향 | FK는 통과하나 시간 논리 붕괴. 고객 생애가치·재방문 주기 분석 불가 |

```sql
SELECT count(*)
FROM pms_reservations r JOIN pms_guests g USING (guest_id)
WHERE r.booked_at < g.created_at;
```

#### P0-4. 취소 예약 금액이 매출로 집계됨

| 항목 | 내용 |
|---|---|
| 위치 | SQL 113~136행 (DDL) |
| 현상 | `CANCELLED` 예약도 `booked_amount`가 양수로 잔존. 환불액·취소수수료 컬럼 부재 |
| 규모(추정) | 취소율 약 18% |
| 위반 조항 | `환불·취소는 별도 상태와 금액 컬럼으로 표현한다` |
| 책임 구분 | 지시문 자체 모순. 9장 충돌 기록 참조 |

```sql
SELECT reservation_status, count(*), sum(booked_amount)
FROM pms_reservations GROUP BY reservation_status;
```

### 6.2 P1 — 중대

| ID | 발견 | 위치 | 상세 |
|---|---|---|---|
| P1-1 | OCC 캡 0.82가 상수화 | 443~458행 | 2025년 base `0.6790 × 1.05 × 1.055 = 0.7522`. DELUXE 계수 1.05와 주말 1.07만 곱해도 0.845로 계절 가중치 적용 전에 캡에 도달. 2025~2026년 주말 STANDARD·DELUXE(객실의 80%)와 8·10월 평일이 0.82로 평탄화되어 계절성·주말 프리미엄·2026 회복 신호가 소실 |
| P1-2 | ADR 수준이 anchor 대비 약 1.5배 | 638~644행 | 증가 추세는 정확(2023/2022 = 1.069650 vs anchor 1.06965, 2024/2023 = 1.13885 vs 1.13884). 수준은 2022 추정 ADR 205,000원 대 anchor 138,874원(+47%), RevPAR 약 126,000원 대 81,642원(+55%). 지시문은 property factor를 OCC에만 부여했고 ADR 프리미엄 근거 미기록 |
| P1-3 | 2025·2026 ADR 계수 출처 없음 | 642~643행 | `1.303441`(전년비 +7.0%), `1.368613`(+5.0%)은 anchor 표·지시문 어디에도 없는 값. 헤더 주석에 근거 미기록으로 감사 불가 |
| P1-4 | LOS 4박 하드 컷 | 525행 | 점유가 슬롯별 독립 시행이라 run length가 기하분포. p=0.82 성수기의 이론 평균 5.5박이 전부 4박으로 절단되어 5박 이상 0건, 4박 스파이크 발생. ALOS 추정 2.9박(도심 호텔 통상 1.5~2.0의 약 1.5배). `LONG_STAY` 요금제 조건이 `nights >= 3`인데 최대 4박이라 일반 예약과 구분 불가 |
| P1-5 | 취소·노쇼가 균등 분포 | 921~927행 | extra 예약의 체크인을 1,826일 균등 분포로 추출. 실제 stay는 강한 계절성이나 취소는 평탄. "월별 취소율", "리드타임-취소 상관", "채널별 취소율" 질의가 노이즈만 반환 |
| P1-6 | `market_segment = guest_segment` 고정 | 572행 | 한 고객은 전 기간 동일 세그먼트이며 채널 분포도 세그먼트에 완전 종속. 세그먼트 분석이 고객 마스터 분석과 동치가 되어 교차 분석 자유도 없음 |

### 6.3 P2 — 운영·재현성

| ID | 발견 | 위치 | 상세 및 조치 |
|---|---|---|---|
| P2-1 | `DateStyle` 미고정 | 262행, 479행 | 해시 키가 `'inventory-ooo\|' \|\| business_date \|\| ...` 형태로 date를 암묵적 text 캐스팅. date→text 변환은 `DateStyle` GUC에 종속되어 `ISO, YMD`는 `2022-01-01`, `SQL, MDY`는 `01/01/2022`가 되므로 md5 결과가 완전히 달라짐. `TIME ZONE`은 고정했으나 `DateStyle`은 누락. **`SET LOCAL DateStyle = 'ISO, YMD';` 한 줄 추가로 해소** |
| P2-2 | `DROP TABLE ... CASCADE` | 65~69행 | 5개 생성기가 공유하는 스키마에서 `analytics_*`·`report_*` 담당이 `pms_*` 위에 만든 view를 무경고 삭제. `RESTRICT`로 전환 |
| P2-3 | `stay_no` 전역 채번을 해시 키로 사용 | 545행 | OOO 비율을 0.003에서 0.004로 바꾸면 가용 슬롯 변동 → run 구조 변동 → 전체 `stay_no` 이동 → 채널·요금제·가격 전부 재추첨. 파라미터 단위 A/B 비교 불가. `(room_type_code, room_unit, checkin_date)` 자연키로 교체 |
| P2-4 | 안전장치 해제 | 58~60행 | `statement_timeout = '0'`, `idle_in_transaction_session_timeout = '0'`. 공유 DB에서 무한 락 위험. `'30min'` 상한 권장 |
| P2-5 | 검증 3건 실패 불가 | 8.8·8.9·8.16 | stay는 `CHECKED_OUT`·`BOOKED` 예약에서만 생성되므로 8.8·8.9의 조인 결과가 항상 공집합. 8.16의 스캔 대상은 enum·ID 컬럼뿐이라 항상 0. 회귀 가드로는 유효하나 검증 통과의 근거로 제시 불가. 주석에 명시 필요 |

### 6.4 P3 — 모델링 갭

| ID | 내용 | 위치 |
|---|---|---|
| P3-1 | `CHECKED_IN` 상태 미생성. reference cutoff 시점의 재실 고객이 0명이라 "현재 투숙 중" 질의 불가 | 747행 |
| P3-2 | `room_unit`은 슬롯 인덱스이며 실제 객실이 아님. OOO 증감 시 번호가 밀려 동일 번호가 다른 방을 지칭. `room_number` 컬럼 부재로 객실 단위 분석 불가 | 474행 |
| P3-3 | 단위 혼재. `quoted_room_rate`는 1박 단가이나 `discount_amount`·`booked_amount`·`commission_amount`는 건 단위 총액. 관계가 문서·CHECK 어디에도 없어 `discount_amount / quoted_room_rate`를 할인율로 계산하면 최대 4배 부풀려짐 | 686~712행 |
| P3-4 | `pms_stays`만 period·forecast CHECK 제약 부재. `pms_room_inventory_daily`·`pms_reservations`에는 존재하는 비대칭 | 1299~1331행 |
| P3-5 | `checkout_date`가 최대 2027-01-04까지 초과. `data_end = 2026-12-31` 계약 위반 | 939행 |
| P3-6 | `FORECAST_SCENARIO` 구간이 이미 경과한 2026-07-01 ~ 07-28을 포함. 생성 시각이 07-28인데 그 이전 4주가 예측으로 라벨됨 | 299행 |
| P3-7 | 고객 약 18%(추정 18,000명)가 예약 0건. CRM 매핑 대상 표시 컬럼이 없어 타 소스 생성기가 `1~80,000` 규칙을 독립 추론해야 함 | 554행 |
| P3-8 | fact table에 `property_id` 부재(`pms_generation_audit`에만 존재). 멀티 프로퍼티 확장 시 재설계 필요 | 99행 이하 |

## 7. 이상 없음으로 확인된 항목

| 항목 | 확인 내용 |
|---|---|
| 공휴일 날짜 | 설·추석 9개 세트가 실제 한국 공휴일과 전부 일치 (2022 설 01-31~02-02, 2025 추석 10-05~08, 2026 설 02-16~18 등) |
| 행 수 계산 | 7,304 = 1,826일(2024 윤년 포함) × 4 room type |
| ID 채번 충돌 | `RSV-`가 `stay_no`(1..N)와 `stay_count + extra_no`(N+1..)로 구간 분리되어 충돌 없음 |
| 시간 제약 | `booked_at < checkin_date`, `cancelled_at < checkin_date`, `actual_checkin_at < actual_checkout_at`이 생성 로직상 모두 충족 |
| PostgreSQL 문법 | `AT TIME ZONE '리터럴'`은 IMMUTABLE이라 CHECK 제약에서 합법. `ANALYZE`는 transaction 내 허용. `generate_series(1, 0)`은 0행 반환으로 에러 없음 |
| 금지 테이블 | `pos_*`, `crm_*`, `facility_*`, `banquet_*`, `analytics_*`, `report_*` 등 0건 생성 |
| 개인정보 | 실명·전화번호·이메일·주소·카드번호·주민등록번호·여권번호·자격증명 일절 없음 |
| ADR 추세 | 2022 → 2023 → 2024 연쇄 증가율이 anchor 표와 소수점 5자리까지 일치 |

## 8. 권고 조치

### 8.1 즉시 (P0)

| 순번 | 조치 | 대상 |
|---|---|---|
| 1 | `pms_stays_actual` view 생성 및 검증 8.17을 actual·forecast 2행으로 분리 출력 | P0-1 |
| 2 | forecast 예약의 `booked_at <= 2026-07-28` 강제, `CHECK (booked_at <= source_updated_at)` 추가 | P0-2 |
| 3 | `guest_no` 배정을 `created_at` 단조 함수로 전환 (번호가 낮을수록 오래된 고객) | P0-3 |
| 4 | `refund_amount`·`cancellation_fee` 컬럼 추가 (지시문 컬럼 명세 개정 선행 필요) | P0-4 |

### 8.2 차기 (P1)

| 순번 | 조치 | 대상 |
|---|---|---|
| 5 | OCC 캡을 `LEAST` 방식에서 로지스틱 압축 방식으로 전환하고 base occupancy 하향 | P1-1 |
| 6 | `property_adr_premium`을 명명 상수로 분리해 헤더와 `generation_notes`에 기록. 2025·2026 ADR 계수 근거도 동일 위치에 기록 | P1-2, P1-3 |
| 7 | LOS를 점유 확률에서 분리. 세그먼트별 LOS 분포를 먼저 추출한 뒤 재고에 배치하는 순서로 역전 | P1-4 |
| 8 | 취소를 균등 분포 대신 생성된 stay를 모수로 리드타임·채널·요금제 조건부 확률로 파생 | P1-5 |
| 9 | `market_segment`를 예약 단위로 재추첨 (주 성향 80%, 이탈 20%) | P1-6 |

### 8.3 병행 (P2)

| 순번 | 조치 | 대상 |
|---|---|---|
| 10 | `SET LOCAL DateStyle = 'ISO, YMD';` 추가 | P2-1 |
| 11 | `CASCADE`를 `RESTRICT`로 전환 | P2-2 |
| 12 | 해시 키를 자연키로 교체 | P2-3 |
| 13 | `statement_timeout = '30min'` 설정 | P2-4 |
| 14 | 8.8·8.9·8.16을 실패 불가 회귀 가드로 주석 명시하고 실효 검증 4건 추가 | P2-5 |

8.3의 14번 추가 검증 쿼리:

```sql
SELECT count(*) FROM pms_reservations WHERE booked_at > source_updated_at;

SELECT count(*) FROM pms_reservations r JOIN pms_guests g USING (guest_id)
WHERE r.booked_at < g.created_at;

SELECT count(*) FROM pms_reservations
WHERE booked_amount
   <> quoted_room_rate * (checkout_date - checkin_date) - discount_amount;

SELECT sum(booked_amount) FROM pms_reservations
WHERE reservation_status = 'CANCELLED';
```

## 9. 미해결 충돌과 결정 필요 항목

#### 충돌 기록

| 항목 | 기준 A | 기준 B | 적용 근거 | 적용 결정 | 확인 필요 |
|---|---|---|---|---|---|
| 취소·환불 금액 표현 | 지시문 `공통 SQL 산출 원칙`: 환불·취소는 별도 금액 컬럼으로 표현 | 지시문 `pms_reservations` 컬럼 명세: 환불·취소 금액 컬럼 없음 | 지시문 내부 모순으로 우열 판단 불가 | 결정 보류 | 지시문 개정 여부를 팀에서 결정 |

### 9.1 결정 필요 항목

| 번호 | 항목 | 배경 |
|---|---|---|
| 1 | 지시문 v1.1 개정 여부 | P1-1·P1-2·P1-4·P0-4는 지시문 v1.0의 파라미터·컬럼 명세가 원인. SQL만 수정하면 CRM·POS·Facility·Banquet 담당 생성기와 계약이 어긋남 |
| 2 | ADR 프리미엄 처리 방식 | 프리미엄 배수를 명시 상수로 확정할지, base rate를 낮춰 anchor에 근접시킬지 |
| 3 | 대상 SQL의 저장소 반입 위치 | 현재 저장소 외부(`Downloads/`)에 있음. 반입 시 04·06·07 산출물 중 어느 계열에 연결할지 결정 필요 |
| 4 | 실행 검증 환경 | PostgreSQL 15+ 인스턴스가 제공되면 2.2의 Not Run 항목을 실측으로 대체 가능 |

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-07-28 15:56 | 최초 작성. PMS 합성 데이터 SQL 정적 검증 결과 23건(P0 4·P1 6·P2 5·P3 8) 기록 |
