# Walkerhill V4.1 SQL 읽기 전용 검토

## 1. 판정

`260814_Walkerhill_V4.1_SQL_verified.zip`으로 전환하는 결정은 유지한다. 다만 현재 archive는 **수정 전 실행·cutover NO-GO**다.

ZIP은 실행하거나 압축 해제하지 않고 archive entry와 텍스트만 읽었다. 따라서 아래 판정은 정적 감사이며 DBMS runtime 결과가 아니다.

## 2. 확인된 release 계약

| 항목 | ZIP 내부 명세 |
|---|---|
| schema version | `4.1.0` |
| base seed | `20260814` |
| generator | `sql-v1.0.0` |
| 데이터 기간 | `2024-01-01`~`2025-12-31` |
| 물리 데이터 | 5개 source engine, 38 tables·407 columns, 계약상 6,019,415 rows |
| namespace | `walkerhill_v4_1` |
| serving | `serving.analytics_v4_1`, 13 views·168 columns |
| 자체 판정 | DB runtime `NOT_RUN`, operational cutover `NO-GO` |

archive 내부 `README.md`, `QUALITY_REPORT.md`, DB별 DDL·seed·validator, Trino view와 access-control 파일을 읽었다.

검토한 제공본의 외부 식별값은 다음과 같다.

- 파일 크기: 140,882 bytes
- ZIP SHA-256: `a797d386c49b65bc23aa265bcd6beccc4534b141e7f9601c216aaa562ae1f64e`
- 파일 entry 68개: SQL 57, Markdown 8, YAML 1, shell 1, JSON 1
- 내부 checksum manifest·signature: 없음

이 값은 제공본 식별용 감사값이지 승인된 release signature가 아니다.

## 3. 확정 차단 결함

### Banquet status history 행수·전이 모순

파일:

- `02_postgresql_banquet/31_postgresql_banquet_status_history_seed.sql`
- `02_postgresql_banquet/50_postgresql_banquet_validator.sql`

status history seed는 세 번째 단계인 `CONFIRMED`를 다음 조건에서만 생성한다.

```sql
CASE
  WHEN b.booking_status IN ('COMPLETED', 'CONFIRMED') THEN 'CONFIRMED'
  ELSE NULL
END
```

따라서 최종 상태가 `CANCELLED`인 예약은 `INQUIRY → QUOTED → CANCELLED` 세 행만 갖고 `CONFIRMED`가 없다. booking seed 기준 취소 예약은 820건이다.

그러나 같은 파일의 header·README·validator는 모든 8,000건이 네 단계 `INQUIRY → QUOTED → CONFIRMED → terminal`을 갖고 총 32,000행이어야 한다고 요구한다. 정적으로 계산되는 값은 다음과 같다.

```text
7,180 × 4 + 820 × 3 = 31,180 rows
```

따라서 최소한 다음 validator Gate가 실패한다.

- expected row count 32,000
- booking별 history 4건
- 순차 status transition
- booking terminal status와 history terminal 일치 여부에 연쇄 영향 가능

이는 DBMS 종류와 관계없는 SQL 계약 모순이다. `SQL_verified`라는 파일명이나 정적 보고서를 runtime 통과 증거로 사용할 수 없다.

수정 전 정적 총 행수는 계약상 6,019,415보다 820 적은 6,018,595다. 6,019,415를 실제값이라고 표시하지 않고 수정 후 DBMS 결과로 다시 측정한다.

### 수정 결정이 필요한 부분

의도한 lifecycle을 먼저 확정해야 한다.

1. 취소도 `CONFIRMED` 후에만 가능하다면 seed가 모든 건에 `CONFIRMED`를 생성하도록 수정한다.
2. 견적 단계 취소가 정상이라면 header·expected count·validator·상태 전이 계약을 3/4단계 가변 lifecycle로 수정한다.

현재 README와 validator가 네 단계를 명시하므로 P0 전환의 최소 변경은 1안으로 보인다. 단, 이 문서는 SQL 수정 권한을 행사하지 않았고 archive도 바꾸지 않았다.

### MySQL·ClickHouse V4.1 read-only 권한 누락

ZIP은 MySQL POS와 ClickHouse Facility에 `walkerhill_v4_1` database를 새로 만들지만 해당 database를 Trino·DataHub가 읽을 principal의 `GRANT SELECT`가 없다. 반면 현재 repository의 구 DDL은 각각 `pos_db.*`의 `pos_readonly`, `facility.*`의 `facility_readonly`를 명시하고 Trino catalog도 이 계정을 사용한다. ZIP의 PostgreSQL·SQL Server 쪽에는 V4.1 권한 처리가 있지만 MySQL/ClickHouse V4.1 `40_*` 스크립트에는 대응 GRANT가 없다.

그대로 적용하면 credential 자체가 기존과 같더라도 새 database의 POS 6개·Facility 5개 table이 Trino source preflight와 DataHub ingestion에서 보이지 않아 DATA-G6가 막힌다. 다음을 archive의 명시적 배포 계약에 추가해야 한다.

- `walkerhill_v4_1.*` 또는 필요한 table만의 `SELECT`를 기존 read-only principal에 부여
- `INSERT`·`UPDATE`·`DELETE`·`DDL` 거부 negative test
- Trino catalog principal과 DataHub ingestion principal의 table visibility 확인
- setup/admin credential을 application query에 사용하지 않는 검사

### 이벤트 효과 계약과 생성 로직 불일치

V4.1은 이벤트 10개 × 호텔 3개 × 지표 5개의 `hotel_event_effect` 계약 150개를 만든다. 대상은 객실 OCCUPANCY_RATE·ADR, F&B ORDER_COUNT, 연회 BOOKING_COUNT, 시설 USAGE_COUNT다.

정적 호출 관계를 추적하면 PMS ADR만 이 계약을 직접 사용한다. PMS occupancy, POS, Banquet은 대응 계약을 사용하지 않고 Facility는 별도 event tag와 hardcoded multiplier를 사용한다. `event_counterfactual_daily` validator도 `PASS/REVIEW`를 출력할 뿐 unresolved REVIEW에서 배포를 중단시키지 않는다.

따라서 “동일 이벤트 계약이 모든 도메인 생성값에 반영된다”는 설명은 현재 성립하지 않는다. P0에서 event signal을 사용하려면 각 생성 SQL이 승인 계약을 실제 소비하도록 고치고 unresolved REVIEW=0을 machine Gate로 만든다. 그렇지 않으면 P0 질문·UI·모델 설명·Gold set에서 event/counterfactual 주장을 제외하고 해당 view를 비승인 자산으로 표시한다.

현재 Golden Path는 단순 기간·구성 변화 비교이므로 event/counterfactual을 사용하지 않고 인과를 말하지 않는다.

## 4. 아직 검증되지 않은 항목

- 5개 DBMS에서 DDL·seed·constraint·validator가 실제 통과하는지
- MySQL·ClickHouse read-only principal이 V4.1 table을 보고 write는 거부되는지
- 명세 row count 6,019,415가 실제 생성되는지
- 동일 seed 재실행의 idempotency와 hash 재현성
- 13개 Trino view의 생성, grain, join fan-out, null, 금액 합계
- event effect 계약과 실제 source 생성값이 일치하는지
- 독립 Gold SQL과 serving view 결과 일치
- DataHub ingestion 후 V4.1 Dataset·Column URN·schema·삭제 상태
- Glossary Term·관련 Asset 관계와 runtime 조회
- 앱 registry·binding·rule·prompt·Gold set 전환
- rollback 절차와 소요 시간

정적 검사가 추가 결함이 없다는 보증을 하지 않는다.

### ZIP이 말하는 DATA-G0~G7

Gate ID의 정확한 명칭과 한 줄 통과 조건은 ZIP 내부 `QUALITY_REPORT.md` §8에만 있다. README와 SQL에는 Gate ID→파일의 공식 manifest가 없으므로 아래 대응 파일은 실행 순서와 `script_type`을 대조한 해석이며, runner 구현 전에 별도 계약으로 고정해야 한다.

| Gate | ZIP의 통과 조건 | 현재 실행 계약 공백 |
|---|---|---|
| DATA-G0 사전점검 | 후보 namespace 충돌 0 | 다섯 source `00_*_preflight`와 Trino source preflight의 경계가 미정 |
| DATA-G1 DDL 컴파일 | 엔진별 문법 오류 0, data dictionary 저장 성공 | `40_*` constraint/index와 Trino schema 포함 여부 미정 |
| DATA-G2 seed 생성 | table별 계약 row count 일치 | 공통 runner와 실패 exit 규칙 없음 |
| DATA-G3 키·금액 무결성 | 모든 `50_*` violation 0 | 결과 행만 출력하며 Banquet 결함 때문에 현재 통과 불가 |
| DATA-G4 분포 현실성 | 호텔·월·요일·이벤트 분포 사람 검토 승인 | checklist·허용 범위·reviewer·evidence 형식 없음 |
| DATA-G5 replay | 같은 seed의 row count·정렬 hash 일치 | clean replay·canonical sort/serialization·hash manifest 없음 |
| DATA-G6 Trino 통합 | tuple 의미 오류·중복·fan-out 0 | `30`과 `31`의 Gate 범위가 다르고 `31`은 view도 생성함 |
| DATA-G7 보안 | TLS·인증 후 setup 사용자 위장 불가 | package에 TLS/authenticator와 spoof negative test가 없어 `BLOCKED` |

따라서 PRD에서 DATA-G0~G7을 요구하는 것만으로는 인수 기준이 되지 않는다. 실행 전 release manifest에 각 Gate의 입력 파일, 명령, oracle, violation 판단, non-zero 종료, receipt 경로, reviewer를 고정한다. 특히 DATA-G4·DATA-G5는 새 실행 가능한 계약을 먼저 만들어야 한다. 앱 분석의 Context·SQL·Result Gate는 `APP-G1~G3`로 별도 표기한다.

## 5. Compose·적재 위험

ZIP의 compose와 keeper는 V4.1 정의를 포함하지만 V4.1 source SQL 전체를 자동 적재하는 완결된 설치 경로로 보지 않는다.

- 기존 service demo seed mount가 남아 있고 V4.1 source schema 적재는 별도 적용이 필요하다.
- keeper는 `walkerhill_v4_1`이 이미 존재할 때 V4.1 view를 조건부 생성한다.
- volume 이름에 구 v3/v4 naming이 섞여 있어 새 volume과 기존 volume의 선택을 잘못할 위험이 있다.
- archive를 단순히 compose에 덮어쓰면 어떤 데이터 release가 실행 중인지 불명확해질 수 있다.
- MySQL·ClickHouse V4.1 read grant가 없어 기존 read-only Trino catalog로는 새 source가 보이지 않는다.

다수 preflight·validator는 PASS/FAIL 행을 반환할 뿐 실패 시 process exit code를 non-zero로 만드는 공통 runner가 없다. 중간 실패 후 일부 DDL이 남을 수 있으므로 runner가 check 결과를 파싱하고 violation 0을 강제하며, 실패 namespace를 폐기한 뒤 clean replay하도록 해야 한다.

추가 정적 불일치도 새 release에서 정리한다.

- MySQL seed가 임시 검사용 `assert_empty_pos_master()` procedure를 제거하지 않는다.
- `31_trino_event_counterfactual_validation.sql`은 validator라는 이름과 달리 production view를 `CREATE OR REPLACE`한다.
- PMS validator header의 check 수와 실제 named check 수가 다르다.
- README의 시간·memory·disk 예상치는 실측 결과가 아니다.

전환 runbook은 engine별 적용 순서, 새 volume, namespace, checksum, validator, 실패 시 정리·복구를 명시해야 한다.

## 6. 보안 한계

ZIP 문서가 명시하듯 현재 Trino HTTP 경로는 사용자가 username을 주장할 수 있고 이것이 인증을 의미하지 않는다. access-control JSON과 Source DB read-only 권한은 필요한 방어지만 신원 위장을 막지 못한다.

- 로컬 폐쇄형 개발자 탐색: 한계를 명시하고 제한 사용 가능하나 P0 `VERIFIED` 증거로 사용 금지
- 실제 서비스·공유 환경: TLS, 인증, service identity, 사용자→service 권한 mapping 전에는 NO-GO

`hotel_synthetic_setup` 같은 setup principal은 view 생성·검증에만 사용하고 애플리케이션 일반 query principal과 분리한다.

## 7. 개발 영향

기존 데이터 계약에서 새 SQL로 바꾸는 결정 자체는 재검토하지 않는다. 대신 다음 구현이 함께 바뀌어야 한다.

| 영역 | 필수 변경 |
|---|---|
| 기간 | 2026 예시·상대 기간을 제거하고 2024~2025 절대 기간·`as_of` 계약 적용 |
| source registry | `walkerhill_v4_1`과 `serving.analytics_v4_1`만 기본 참조 |
| semantic contract | 새 view·column·grain·Metric 계산식으로 재작성 |
| identity | 회원등급은 거래 시점 유효 이력을 사용하고 bridge 중복을 검증 |
| DataHub | V4.1 URN, schema, Domain/Owner, Glossary Term·Asset relation 재발행 |
| Node 1·2 | 새 Metric/Asset/Rule 후보와 허용 SQL 범위로 전환 |
| Gold/eval | 구 seed 결과 폐기, 새 Gold SQL·Result·negative set 생성 |
| 저장 결과 | data release/version을 기록하고 구 Result를 최신으로 재사용 금지 |
| 화면 | source/version/as_of와 범위 밖 오류를 표시 |
| 운영 | canary, rollback rehearsal, release manifest, Trino 인증 보강 |

### 현재 adapter의 V4.1 차단 조건

`app/backend/app/adapters/governed_data_platform.py`의 데이터 후보 계약 loader는 다음을 강제한다.

- release contract 전체의 `assets`가 8개를 넘으면 거부
- FQN이 `serving.analytics.v4_*`로 시작해야 함
- DataHub URN platform-instance가 `serving_v4`여야 함

V4.1 serving은 13개 view와 새 `analytics_v4_1` namespace를 사용하므로 전부 등록하면 adapter가 시작 단계에서 거부한다. 이는 SQL 자체가 아니라 확정된 app cutover blocker다.

`ContextPackageBuilder.MAX_DATASETS=8`은 한 질문의 Context 폭을 제한하는 안전 상한으로 유지할 수 있다. 하지만 release registry 전체 cardinality와 요청별 Context cardinality는 다른 계약이다. loader는 13개 이상 V4.1 asset을 등록할 수 있게 바꾸고, Node 1·권한·APP-G1이 한 요청에 최대 8개만 선택하도록 분리해야 한다. FQN·URN·platform-instance validation도 V4.1의 정확한 명명 계약으로 갱신한다.

AI/eval builder도 구 `serving.analytics` view·field·metric과 2026 GOLD 질문을 코드에 고정한다. V4.1은 등급이 `CLASSIC/PLUS/PREMIER`이고 serving grain이 다르므로 fixture 날짜만 바꾸면 해결되지 않는다. P0 질문→logical Metric→preferred V4.1 view/field 계약을 승인한 뒤 training case, prompt, heldout, Gold SQL과 UI 추천 질문을 함께 다시 만든다.

대표 운영매출 질문은 `hotel_operations_monthly`라는 승인된 통합 mart 하나를 조회하고 DataHub lineage로 PMS·POS·Banquet·Facility 근거를 설명한다. 이 경로를 “LLM이 런타임에 여러 asset을 동적 JOIN했다”고 발표하지 않는다. 동적 교차 JOIN을 증명하려면 별도 multi-asset Rule과 Gold case가 필요하다.

`event_counterfactual_daily` 결과는 통계적 인과 추정을 대신하지 않는다. UI와 모델 설명은 “원인”이 아니라 “관측 차이”, “구성 기여”, “합성 기준선 비교”로 제한한다.

## 8. 실행 전 Gate

1. lifecycle 의도 확정과 banquet SQL·validator 수정
2. MySQL·ClickHouse V4.1 read-only grant와 write 거부 test 추가
3. event effect를 실제 구현하거나 P0 비승인 자산으로 제외
4. machine-enforced runner, clean failure와 rollback 계약 추가
5. archive 재생성, 새 release ID와 entry별 checksum manifest·SHA-256 고정
6. 모든 SQL에 parser/static lint와 상호 계약 검사 적용
7. 격리된 새 volume에서 5개 DB 적재·validator
8. clean replay와 row/hash 비교
9. Trino 13 views와 독립 Gold 검증
10. DataHub Dataset·Glossary·relation publish/verify
11. 앱·AI·UI 계약 전환과 실제 L3/L4 E2E
12. rollback rehearsal
13. 승인된 evidence manifest 후 cutover

현재 1~4번부터 끝나지 않았으므로 실행·cutover 완료로 표시하지 않는다.

## 9. 이번 검토에서 하지 않은 일

- ZIP 압축 해제·내용 수정·SQL 실행
- Docker volume·DB·DataHub 변경
- 기존 데이터와 금액 비교
- cutover·rollback 수행

이 제한 때문에 runtime 성공을 주장하지 않는다.
