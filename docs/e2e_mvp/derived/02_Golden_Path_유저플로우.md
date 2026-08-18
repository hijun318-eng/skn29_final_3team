# Golden Path 유저플로우

> **SUPERSEDED / 과거 계약:** 현재 사용자 흐름은 [`../../product/02_유저플로우.md`](../../product/02_유저플로우.md)다. 아래 흐름의 구 데이터·증거를 현재 완료로 해석하지 않는다.

## 1. 사용자와 시작 조건

- 제품 관점의 사용자는 C-level 또는 호텔 사업책임자다.
- MVP의 실제 인증 역할은 `hotel_analyst`다.
- Backend, App PostgreSQL, DataHub Core, Trino와 설정된 model provider가 준비돼 있어야 한다.
- 사용자는 테이블·컬럼명 대신 승인된 업무 용어와 분석 기간을 질문에 포함한다.

대표 질문:

> 2026년 5월과 6월 GOLD 고객의 객실·식음 통합 매출을 비교하고 변화와 근거를 보여줘.

이 질문은 PMS·CRM·POS, GOLD 등급의 유효 기간, 객실·F&B 매출 정의와 승인 JOIN을 사용한다.

## 2. 정상 흐름

1. 사용자가 Agent 화면에 자연어 질문 한 문장만 제출한다.
2. Frontend는 인증 정보, `conversation_id`와 질문을 `POST /analysis`로 보낸다.
3. Backend는 실제 인증 주체와 role을 확인하고 `request_id`·`trace_id`를 만든다.
4. Node 1은 승인된 업무 용어를 기준으로 Metric 후보와 기간 후보를 구조화한다.
5. Context Builder는 정확히 하나의 기간을 `[start, end_exclusive)`로 계산하고, 권한 범위 안의 Metric·Asset·Binding·JOIN Rule을 결합한다.
6. G1이 Context 완전성과 권한을 검사한다.
7. Node 2가 Approved Context 안에서 SQL 초안을 만들고, G2가 read-only·자산·컬럼·JOIN·필터·기간 정책을 검사한다.
8. G2를 통과한 SQL만 Trino에서 실행된다. G2 실패는 정형 오류로 최대 1회 Repair한 뒤 다시 검사한다.
9. G3가 결과 Schema·크기·민감정보·JOIN 증폭 신호를 검사하고 Safe Result를 만든다.
10. Node 3는 Safe Result의 숫자와 기간만 사용해 설명한다.
11. Backend는 Evidence, Query ID, Gate trace와 Artifact를 저장한다.
12. Frontend는 실제 응답의 표·차트·출처·기간·상태를 표시한다.
13. 사용자가 저장하면 확정된 기간을 Analysis Definition 파라미터로 보관한다.
14. 사용자가 Report 초안을 만들면 저장된 Artifact·Query ID를 참조하는 Block을 서버에 저장한다.

## 3. Slice 1 확인 흐름

### 3.1 기간이 없는 경우

```text
질문 제출
→ Node 1 period_candidates = []
→ Context Builder 차단
→ BLOCKED / CONTEXT_INCOMPLETE
→ "질문에 분석 기간을 하나만 명확히 포함해 주세요"
```

- Node 2, G2, Trino와 Node 3를 호출하지 않는다.
- Frontend는 실패 결과나 샘플 데이터를 표시하지 않는다.
- 사용자가 기간을 포함한 새 질문을 제출해야 새 요청을 시작한다.

### 3.2 Metric이 모호한 경우

```text
"2026년 6월 객실 매출을 분석해 줘"
→ 승인 후보: 인식 객실 매출 / 숙박일 배분 객실 매출
→ BLOCKED / CONTEXT_INCOMPLETE
→ 승인된 한글 업무명 버튼 표시
→ 사용자가 하나 선택
→ 선택 내용을 포함한 새 질문 제출
```

- 제안 목록은 현재 사용자의 권한 범위와 승인된 glossary에서만 만든다.
- 내부 Metric ID, 원시 컬럼명과 권한 밖 Metric을 제안하지 않는다.
- Backend가 첫 후보를 임의 선택하지 않는다.

### 3.3 기간이 하나로 해석되지 않는 경우

- 후보가 0개 또는 2개 이상이면 `CONTEXT_INCOMPLETE`로 차단한다.
- 잘못된 월이나 역전된 범위는 정상 기간으로 보정하지 않는다.
- 실제 날짜 계산은 Node 1/Backend의 결정론적 로직이 담당하며 모델이 임의 계산하지 않는다.

## 4. 공통 실패 흐름

| 실패 지점 | 외부 상태 | 다음 동작 |
|---|---|---|
| 인증 | HTTP `401` 또는 `403` | 실행하지 않음 |
| Context/G1 | `BLOCKED` + `CONTEXT_INCOMPLETE` 또는 `ACCESS_DENIED` | 사용자 확인 또는 종료 |
| 모델 계약 | `FAILED` + 계약 오류 | SQL 실행하지 않음 |
| G2 | `BLOCKED` + `SQL_POLICY_BLOCKED` | 허용 범위에서 1회 Repair 후 종료 |
| Trino | `FAILED` 또는 `PARTIAL` + `QUERY_SOURCE_FAILED` | retryable 여부에 따라 재시도 안내 |
| G3 | `BLOCKED` 또는 `FAILED` + 근거/민감정보 오류 | Raw Result 미노출 |
| Report Block | `PARTIAL_SUCCESS` 또는 `FAILED` | 실패 Block과 과거 성공 결과 분리 |

실패 시 fixture, 템플릿 결과, 브라우저 저장값과 이전 성공 결과로 대체하지 않는다.

## 5. 화면 상태 계약

| 서버 결과 | 화면 상태 | 표시 내용 |
|---|---|---|
| 처리 중 | `LOADING` | 현재 처리 중임만 표시 |
| `SUCCEEDED` | `READY` | 표·차트·설명·Evidence |
| `PARTIAL` | `PARTIAL` | 성공·실패 Source 구분 |
| Metric 확인 필요 | `ERROR` + 제안 | 승인 Metric 선택 버튼 |
| 기간 확인 필요 | `ERROR` | 기간을 포함한 새 질문 안내 |
| `ACCESS_DENIED` | `FORBIDDEN` | 안전한 권한 안내 |
| 근거 부족 | `INSUFFICIENT_EVIDENCE` | 결과 숨김과 오류 코드 |

Frontend는 서버 상태를 임의로 성공으로 바꾸지 않는다.

## 6. Slice 1 E2E 시나리오

### 정상

1. `2026년 5월과 6월 GOLD 고객의 객실·식음 통합 매출을 보여줘.`를 제출한다.
2. 요청 파라미터에는 별도 기간 필드를 보내지 않는다.
3. 응답 Evidence 기간이 `2026-05-01` 이상 `2026-07-01` 미만인지 확인한다.
4. PMS·CRM·POS Source, Query ID, Artifact ID와 G1·G2·G3 통과를 확인한다.
5. 결과를 저장하고 저장된 기간으로 재실행할 수 있는지 확인한다.

### 사용자 확인

1. `2026년 6월 객실 매출을 분석해 줘.`를 제출한다.
2. Trino query가 생성되지 않고 승인 Metric 제안이 표시되는지 확인한다.
3. `인식 객실 매출`을 선택한다.
4. 새 request ID로 실행되고 Evidence 기간이 `2026-06-01` 이상 `2026-07-01` 미만인지 확인한다.

### 차단

1. `객실 매출을 분석해 줘.`를 제출한다.
2. 기간 확인 메시지와 `CONTEXT_INCOMPLETE`를 확인한다.
3. trace에 QUERY·G3·ARTIFACT 성공 단계가 없는지 확인한다.

## 7. 완료 증거

- 정상·확인·차단 요청의 HTTP 상태와 응답 본문
- 서로 다른 `request_id`와 `trace_id`
- Node별 호출 여부, G1·G2·G3 결과와 Repair 횟수
- Trino Query ID와 실제 Result row
- Evidence 기간, Source URN/FQN, Policy·Context·Model Version
- 저장된 Artifact와 화면 표·차트의 일치
- 브라우저에서 제안 선택 후 새 요청이 실행되는 화면 기록

최신 아키텍처: [03. 아키텍처와 전환 계약](../../product/03_아키텍처.md)
