# Walkerhill V4.3 교체 검토 및 실행 보고서

> **ARCHIVED / 실행 금지** — 이 문서는 2026-08-15 시점의 합성 데이터 적재 실패를 보존한 감사 기록이다.
> 현재 Compose, DataHub authoring, Trino discovery 또는 제품 readiness의 입력이 아니며, 이 문서의
> 고정 namespace·행 수·SQL·release ID를 새 환경의 정답이나 복구 절차로 재사용해서는 안 된다.
> 현재 운영 절차는 `infrastructure/database/datahub/SEMANTIC_AUTHORING.md`와 runtime metadata 검증을 따른다.

작성 기준: 2026-08-15 KST  
현재 판정: **BLOCKED — source shadow partial load, 제품 전환 미실행**

## 결론

PMS, Banquet, POS는 올바른 `walkerhill_v4_3` namespace에 적재됐고 bundled validator가 PASS했다. CRM 적재 중 패키지와 runner가 SQL Server 대상 database를 강제하지 않아 `crm_db`가 아닌 `master.walkerhill_v4_3`에 7개 테이블이 생성됐다. 이어 VOC 8만 건 단일 재귀 CTE가 SQL Server `Error 701` 메모리 부족으로 실패했다.

즉시 중단 규칙에 따라 Facility, Trino, DataHub, 앱·AI·UI 전환은 실행하지 않았다. 기존 source namespace, serving schema, DataHub metadata, 앱 기본 pointer는 변경하지 않았다.

## 실행 release

- release ID: `walkerhill-v4.3-sql-20260815-derived.1`
- 원본 ZIP SHA-256: `615618e6be89f0851821f15a9a1bb84dcdabb9cf8ea5ea0c0c48b0221030c284`
- 현재 derived canonical tree SHA-256: `a95c34c845b2e8b00408999acff170a277a087c25830b4775c88f8b31f80e260`
- 현재 manifest SHA-256: `f072d697f593084650f27946dafbad84a3d7195277291028a6a7f424ed895358`
- manifest: `infrastructure/database/releases/walkerhill_v4_3_20260815_derived_1/manifest.json`
- 실행 receipt: `C:\Users\Playdata\Desktop\SKN_FINAL\.codex-tmp\v43-receipts-derived-1\receipts.jsonl`

실행 중 발견된 오류를 반영해 derived tree와 manifest를 갱신했다. 이미 실행된 각 파일의 실제 SHA-256은 append-only receipt에 별도로 고정돼 있다. 재개 전에는 수정본 manifest를 기준으로 아직 실행하지 않은 CRM·Facility부터 새 receipt를 남기고, 기존 3개 도메인은 같은 파일 hash인지 확인한 뒤 validator를 다시 실행해야 한다.

## 현재 source 상태

| 엔진·도메인 | 올바른 대상 | 현재 상태 | 확인 행 수 | 판정 |
|---|---|---:|---:|---|
| PostgreSQL PMS | `pms_db.walkerhill_v4_3` | 15 tables 적재·validator 완료 | 2,519,447 | PASS |
| PostgreSQL Banquet | `banquet_db.walkerhill_v4_3` | 5 tables 적재·validator 완료 | 84,954 | PASS |
| MySQL POS | `walkerhill_v4_3` | 6 tables 적재·grant·validator 완료 | 3,324,815 | PASS |
| SQL Server CRM | `crm_db.walkerhill_v4_3` | schema 없음 | 0 | BLOCKED |
| ClickHouse Facility | `walkerhill_v4_3` | 미실행 | 0 | NOT_RUN |

올바른 database에 적재된 합계는 `5,929,216 / 7,815,868`행이다.

잘못 생성된 SQL Server 상태는 다음과 같다.

| 잘못된 대상 | 객체 | 행 수 |
|---|---|---:|
| `master.walkerhill_v4_3` | `crm_membership_tiers` | 3 |
| `master.walkerhill_v4_3` | `crm_members` | 150,000 |
| `master.walkerhill_v4_3` | `crm_member_grade_history` | 192,000 |
| `master.walkerhill_v4_3` | `crm_point_transactions` | 480,000 |
| `master.walkerhill_v4_3` | `crm_customer_map` | 110,000 |
| `master.walkerhill_v4_3` | `crm_voc_reviews` | 0 |
| `master.walkerhill_v4_3` | `crm_voc_analysis` | 0 |

오적재 합계는 932,003행이며 `crm_db`에는 `walkerhill_v4_3` schema가 없다.

## 확인된 수정과 검증

1. POS bridge validator 기대값을 현재 seed 산식의 `101,573`건으로 수정했다.
   - 실제 POS validator 결과: `pos_bridge_linked_order_count = 0 violations`, PASS
2. Banquet room-block pickup을 PMS와 동일한 `2026-09-01` exclusive boundary로 clamp했다.
   - Banquet validator 14개 gate와 5개 table count가 모두 PASS
3. ClickHouse 대형 INSERT target column과 누락된 logical duplicate gate를 추가했다.
   - 아직 runtime 실행하지 않아 NOT_RUN
4. Trino `max_by`에 `event_id` tie-break를 추가했다.
   - Trino 476에서 축약 구문 검증 PASS, serving view 생성은 NOT_RUN
5. MySQL·ClickHouse V4.3 read-only role grant SQL을 추가했다.
   - MySQL grant 실행 PASS, 실제 query principal 음성 검증은 아직 NOT_RUN
6. SQL Server 모든 CRM SQL에 `USE [crm_db]`를 추가하고 runner에도 `-d crm_db`를 강제했다.
7. CRM VOC review·analysis를 2,000행 batch로 수정했다.
   - SQL Server `PARSEONLY` 구문 검증 PASS
   - runtime 재실행은 cleanup 승인 전 NOT_RUN

## 실제 소요시간에서 확인된 운영 위험

- POS order seed: 약 2,212초(36.9분)
- POS item seed: 약 2,417초(40.3분)
- POS payment/refund seed: 약 228초
- POS validator: 약 307초

기존 문서의 “POS seed 최대 30분”은 V4.3에 맞지 않는다. 최소 90분 이상의 engine timeout과 전체 작업 시간 예산이 필요하다.

## 현재 blocker와 승인 필요한 작업

`master.walkerhill_v4_3`는 이번 실행에서 생성된 오적재 candidate임을 row count와 receipt로 확인했다. 그러나 삭제는 별도 승인 사항이므로 수행하지 않았다.

승인 후 다음 순서로만 재개한다.

1. `cleanup-master-misload.sql`의 exact object 목록을 다시 read-only 확인
2. `master.walkerhill_v4_3`의 7 tables, 2 functions, schema만 제거
3. 기존 `master` 시스템·사용자 객체와 `crm_db`가 정상인지 재확인
4. 수정된 CRM preflight를 `crm_db`에서 실행해 collision=0 확인
5. CRM을 2,000행 batch로 적재하고 1,093,947행·validator·read-only gate 확인
6. CRM PASS 후에만 Facility → Trino → DataHub → 앱 candidate 순서로 진행

승인 전용 cleanup 파일:

`infrastructure/database/releases/walkerhill_v4_3_20260815_derived_1/cleanup-master-misload.sql`

## 실행하지 않은 검증

- Facility 5 tables / 792,705행
- Trino source visibility, `analytics_v4_3` 13 views와 교차 도메인 gate
- source 5개 read-only 계정의 SELECT 성공·write 거부 전수 검사
- 현실성 51/32 SQL
- clean replay·canonical row hash·Trino restart 복구
- DataHub V4.3 ingest·URN/schema/lineage/Glossary read-back
- 앱·AI·UI candidate, Gold/held-out, rollback rehearsal, logical cutover

따라서 현재 상태는 `CANDIDATE_LOADED`나 `RELEASED`가 아니라 **BLOCKED**다.
