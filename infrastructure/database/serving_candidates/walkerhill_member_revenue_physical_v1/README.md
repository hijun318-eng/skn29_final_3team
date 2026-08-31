# 회원 매출 물리 실행 후보

상태는 `REVIEW_REQUIRED / NOT_RUN`이다. 이 디렉터리의 SQL은 현재 Trino·DataHub·RuntimeCatalog를 변경하지 않는다.

## 문제와 결정

현행 `serving.analytics_v4_3.member_revenue_daily`는 PMS 객실 집계와 POS 식음 집계를 하나의
`FULL OUTER JOIN` 안에서 계산한다. 바깥 쿼리가 `room_revenue_krw`만 선택해도 Trino 계획에는
PMS·POS·CRM이 모두 남는다.

Metric을 객실·식음 자산으로 분리하면 현재 단일 자산 멀티 출력 계약과 승인된 Semantic Request
재실행 범위가 달라진다. 이 후보는 대신 다음 물리 경계만 추가한다.

1. 객실 회원매출을 `member_room_revenue_daily` materialized view로 독립 집계한다.
2. 식음 회원매출을 `member_fnb_revenue_daily` materialized view로 독립 집계한다.
3. 기존 `member_revenue_daily`는 두 개의 작은 materialized 결과만 결합한다.

기존 공개 FQN, grain, 시간 필드, 차원, Metric 컬럼은 유지한다. helper materialized view는 활성
Metric 자산으로 자동 승격하지 않는다.

## 읽기 전용 계획 증거

2026-08-30 현재 배포된 Trino 483에서 `EXPLAIN (TYPE DISTRIBUTED)`만 실행했다. 데이터 조회,
객체 생성, refresh, DataHub 발행은 수행하지 않았다.

| 대상 | plan fragments | 원천 범위 | Trino query ID |
|---|---:|---|---|
| 현행 객실 단독 합계 | 13 | PMS + POS + CRM | `20260830_091518_02801_u4kx2` |
| 객실 materialized 후보 정의 | 5 | PMS + CRM | `20260830_091328_02799_u4kx2` |
| 식음 materialized 후보 정의 | 6 | POS + CRM | `20260830_091419_02800_u4kx2` |

fragment 수는 실제 refresh 시간이나 처리 행 수를 보장하지 않는다. 다만 두 후보가 서로의 매출
원천을 계획에 포함하지 않는다는 구조적 증거다.

## 실행 순서와 활성화 Gate

1. serving release writer로 `10_member_revenue_materialized_views.sql`을 검토·실행한다.
2. 같은 source release 안에서 `20_refresh_member_revenue_materialized_views.sql`을 실행한다.
3. `30_member_revenue_validation.sql`의 모든 `violation_count`가 0인지 확인한다.
4. 두 `EXPLAIN`에서 PMS·POS·CRM 원천이 아니라 materialized storage table만 읽는지 확인한다.
5. serving metadata를 DataHub에 다시 수집하고 공개 view의 새 lineage를 read-back한다.
6. 동일 Trino/DataHub receipt로 새 inactive RuntimeCatalogProjection을 컴파일·검증한다.
7. 기존 `member_room_revenue`, `member_fnb_revenue`, `membership_tier`의 공개 계약이 동일한 새
   catalog release를 별도 승인한 뒤에만 product release를 전환한다.

원천 release가 바뀌면 materialized view를 다시 refresh해야 한다. 자동 refresh 주기는 실제 기업
데이터 갱신 정책을 알 수 없는 현재 범위에서 임의로 정하지 않는다. refresh 영수증이 없거나 source
release가 달라진 경우에는 기존 materialized 결과를 최신 데이터로 간주하면 안 된다.
