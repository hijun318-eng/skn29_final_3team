# SensePlace — FastAPI 내부·외부 연동 범위

| 항목 | 내용 |
|---|---|
| 문서 설명 | SensePlace의 Django·FastAPI·PostgreSQL·외부 LLM 간 책임과 호출 경계를 정리한 백엔드 작업 문서 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-07-21 15:24 |
| 작성·수정 | 김재홍 |

> 이 문서는 구현 전 연동 경계 기준이다. 개별 endpoint의 최종 request·response schema, timeout, retry, 인증 방식은 담당자 승인과 실제 코드·테스트로 확정한다.

## 1. 목표와 완료 조건

- Browser가 호출하는 공개 backend를 Django 하나로 제한한다.
- FastAPI를 내부 AI·분석 서비스로 제한한다.
- 인증·권한·상태·데이터 쓰기 소유권을 Django에 둔다.
- FastAPI의 DB 접근을 허용된 analytics view의 read-only로 제한한다.
- 외부 LLM 호출 횟수·입력·Fallback·감사 기준을 명확히 한다.
- P0와 실험·확장 범위를 분리한다.

## 2. 결론

[결정] 호출 방향은 다음과 같이 고정한다.

```text
Browser
→ Django 공개 API
→ Django job·worker
→ FastAPI 내부 API
→ PostgreSQL analytics view 또는 외부 LLM API
```

[결정] Django는 인증·권한·job·report·decision의 원본이다. FastAPI는 적재 후 품질 Gate, 규칙 감지, query pipeline, SQL Guard, Incident 분석과 제한된 LLM 연동을 담당한다.

[결정] Browser는 FastAPI를 직접 호출하지 않는다. FastAPI는 사용자의 role을 자체 판단하지 않고 Django가 저장·검증한 `scope_snapshot`만 사용한다.

## 3. 계층별 책임

| 계층 | 담당 | 담당하지 않음 |
|---|---|---|
| Browser·Frontend | 로그인 화면, 질문·결과·상태 표시, Django polling | FastAPI 직접 호출, raw SQL 전송 |
| Django·DRF | session 인증, RBAC, 공개 `/api/v1/*`, job·report·decision 저장, audit | 분석 SQL 계산, 자유형 LLM 판단 |
| Django worker | job 실행, FastAPI 호출, timeout·retry 정책 적용, 결과 저장 | 사용자 권한 재정의 |
| FastAPI | 내부 `/internal/v1/*`, 품질 Gate, rule 감지, query·Incident workflow, SQL Guard | 로그인 원본, report 승인, 업무 table 쓰기 |
| PostgreSQL | 합성 analytics view와 업무 table 저장 | 애플리케이션 권한 판단 |
| 외부 LLM | evidence 기반 질문 해석 또는 문장 초안 | KPI 계산, SQL 실행, 원인 확정, 자동 승인 |

## 4. 전체 연동 범위

| 구분 | 호출 방향 | 목적 | 인증·안전 | 범위 |
|---|---|---|---|---|
| 내부 입력 | Django worker → FastAPI | 분석 실행 | 내부 인증, request ID, `scope_snapshot` | P0 |
| 내부 조회 | FastAPI → PostgreSQL | VOC·운영지표 조회 | read-only role, allowlist, timeout | P0 |
| 내부 반환 | FastAPI → Django worker | 구조화 결과 반환 | schema version, idempotency key | P0 |
| 외부 호출 | FastAPI → LLM API | 질문 해석 또는 evidence 설명 | 환경변수 key, timeout, 최대 1회 | P0 |
| 내부 실험 | 분리 실험 → pgvector | 유사 VOC 검색 성능 비교 | Baseline dependency와 분리 | 실험 |
| 외부 입력 | STT → 별도 수집 경계 | 음성 VOC 텍스트 변환 | PII·보존 정책 필요 | P1 후보 |
| 실제 호텔 시스템 | Integration layer → pipeline | PMS·POS·CRM 데이터 수집 | 별도 계약·보안 검토 | 범위 밖/P2 |
| 외부 전달 | Django → 업무 채널 | 승인된 보고서 전달 | 사용자 승인 필수 | 보류 후보 |

## 5. FastAPI 내부 API 후보

공개 API는 `/api/v1/*`, Django worker가 호출하는 내부 API는 `/internal/v1/*`를 사용한다.

| API 후보 | 목적 | 최소 입력 | 최소 출력 | P0 Fallback |
|---|---|---|---|---|
| `GET /internal/v1/health` | 서비스 상태 확인 | request ID | 서비스·DB 상태 | 장애 상태 반환 |
| `POST /internal/v1/quality-gates` | 적재 후 분석 가능성 검사 | dataset version, batch ID | 상태, 실패 규칙 | `NEEDS_DATA` |
| `POST /internal/v1/detection-runs` | versioned rule 실행 | dataset·rule version | signal, 근거 ID | 명시적 실패 상태 |
| `POST /internal/v1/query-runs` | 보장 질문 분석 | 질문, 기간, scope snapshot | plan, 표, chart, 설명 | 수치·표만 반환 |
| `POST /internal/v1/incident-runs` | Incident 조사·초안 생성 | incident key, signal, scope | evidence, 브리프, 보고서 DRAFT | template brief·DRAFT |

[결정] P0 Incident 응답은 evidence·이슈 브리프·보고서 DRAFT를 함께 반환한다. 별도 `POST /internal/v1/report-narratives`는 재사용 또는 LLM timeout 격리 필요가 확인될 때 P1에서 검토한다.

상세 필드 타입, HTTP status, timeout, retry와 error code는 구현 전 API contract에서 확정한다.

## 6. 요청 공통 계약

FastAPI 요청에는 최소한 다음 추적값이 필요하다.

- `request_id`
- `job_id`
- `idempotency_key`
- `scope_snapshot_id` 또는 검증된 scope 값
- `dataset_version`
- 해당 작업의 `schema_version`
- 필요 시 `rule_version`, `catalog_version`, `prompt_version`

FastAPI는 client가 직접 보낸 role·scope를 신뢰하지 않는다. Django 인증 후 DB에 저장한 snapshot을 worker가 전달해야 한다.

## 7. PostgreSQL 접근 경계

| 대상 | FastAPI 허용 | 금지 | 용도 |
|---|---|---|---|
| `metric_catalog` | 조회 | 수정·삭제 | 지표·단위·grain·source view 확인 |
| `role_scope` 또는 scope snapshot | 조회·요청 검증 | 권한 원본 변경 | 허용 metric·dimension·view 제한 |
| analytics view | `SELECT` | `INSERT`, `UPDATE`, `DELETE`, DDL | KPI·VOC 교차분석 |
| `fact_voc` | 마스킹된 합성 필드 조회 | 개인정보·원문 무제한 조회 | 근거 VOC |
| `fact_voc_topic` | 승인된 감성·주제 범위 조회 | 승인 범위 밖 활용 | 주제·근거 span |
| `analysis_run`·`job` | 필요한 상태 조회 | 최종 상태 덮어쓰기 | 중복 방지·재현성 확인 |
| `report`·`report_decision` | 접근 금지 | 생성·승인·수정 | Django 전담 |

SQL Guard는 허용 view·column·metric·dimension·grain·scope를 검증하고 다음을 차단한다.

- 다중 statement와 주석 우회
- `UNION` 기반 범위 우회
- DML·DDL
- 금지 함수와 system catalog 접근
- 비가산 지표의 잘못된 재집계
- 승인되지 않은 기간·시설·역할 scope

## 8. 외부 LLM 연동 경계

| 항목 | 허용 | 금지 |
|---|---|---|
| 질문 해석 | 보장 질문을 semantic plan으로 변환 | 자유형 SQL 실행 |
| 분석 설명 | 계산 수치와 evidence 서술 | 수치 생성·변경 |
| 원인 후보 | 규칙 결과를 후보로 정리 | 실제 원인 확정 |
| 보고서 초안 | evidence 기반 `DRAFT` 작성 | 자동 승인·자동 전달 |
| 호출 횟수 | 실행당 최대 1회 | 반복 Agent loop |
| 실패 처리 | template Fallback과 `PARTIAL` | 계산 결과 폐기 |

LLM 입력에는 개인정보·API key·불필요한 VOC 원문을 포함하지 않는다. 출력은 evidence ID와 계산 결과를 기준으로 검증하고 근거 밖 주장을 제거한다.

## 9. 오류·상태·Fallback

| 상황 | FastAPI 결과 | Django 처리 |
|---|---|---|
| 품질 Gate 실패 | `NEEDS_DATA`와 실패 규칙 | job 상태와 사용자 안내 저장 |
| 지원하지 않는 질문 | `UNSUPPORTED_QUESTION` | 지원 질문 안내 |
| 권한·scope 위반 | `FORBIDDEN_SCOPE` | 감사 이력과 실패 상태 저장 |
| SQL Guard 차단 | `BLOCKED_QUERY` | SQL 미실행·오류 사유 표시 |
| LLM timeout | 계산 결과와 template 설명, `PARTIAL` | 수치 보존·재시도 안내 |
| FastAPI timeout | 명시적 실패 또는 제한 retry | 무한 대기 금지 |
| 중복 요청 | 기존 idempotent 결과 | 중복 job·incident 생성 금지 |

실패 시 수치와 결정론적 결과를 유지하고 LLM 설명만 template으로 대체한다.

## 10. P0 최소 연결 순서

1. Django가 session 인증과 role scope를 확인한다.
2. Django가 job과 `scope_snapshot`을 저장하고 `job_id`를 반환한다.
3. Worker가 FastAPI health와 내부 인증을 확인한다.
4. FastAPI가 허용된 analytics view를 read-only로 조회한다.
5. Query 경로에서 보장 질문 1종을 표·차트·근거 구조로 반환한다.
6. Incident 경로에서 signal 1건을 evidence·브리프·보고서 DRAFT로 반환한다.
7. LLM은 필요한 경우 실행당 1회만 호출하고 실패 시 template을 사용한다.
8. Django가 결과와 audit event를 저장한다.
9. Frontend가 Django를 polling해 상태와 결과를 표시한다.
10. 관리자가 보고서를 승인·보류·반려하고 Django가 결정 이력을 저장한다.

## 11. FastAPI 비담당 범위

- 사용자 로그인과 session 관리
- 역할·권한의 원본 관리
- Browser용 공개 API
- 사용자 파일 업로드와 적재 전 validation
- 보고서 승인·보류·반려
- 실제 PMS·POS·CRM 직접 연결
- 고객 자동 응답
- 보상·인력 배치·외부 시스템 자동 조치

## 12. 사람이 결정해야 할 사항

- [ ] Django worker와 FastAPI 사이 내부 인증 방식을 결정한다.
- [ ] FastAPI read-only DB role과 허용 analytics view를 확정한다.
- [ ] 동기·비동기 호출, timeout, retry 1회와 backoff 값을 확정한다.
- [ ] LLM 기본·대체 모델과 비용·timeout 한도를 확정한다.
- [ ] 개별 endpoint의 request·response JSON Schema와 error code를 확정한다.
- [ ] pgvector 실험을 FastAPI runtime과 물리적으로 분리할지 확정한다.

## 13. 검증 방법

| 검증 | 합격 조건 |
|---|---|
| 공개 경계 | Browser→FastAPI 직접 호출 경로가 없다. |
| 인증·권한 | Django가 검증한 scope snapshot만 FastAPI가 사용한다. |
| DB 안전 | FastAPI role의 DML·DDL과 금지 view 접근이 모두 실패한다. |
| 결정론 | 같은 input·version에서 같은 수치와 signal을 반환한다. |
| LLM 안전 | 실행당 최대 1회이며 timeout에도 계산 결과가 유지된다. |
| 상태 관리 | job·report·decision의 최종 쓰기는 Django만 수행한다. |
| 중복 방지 | 같은 idempotency key로 중복 job·incident가 생기지 않는다. |
| 추적성 | request·dataset·rule·catalog·prompt version과 evidence를 역추적할 수 있다. |

## 14. 남은 위험

1. 실제 dependency와 서비스 배포 구조가 없어 endpoint는 아직 구현 계약 후보이다.
2. 내부 인증, timeout, retry, JSON Schema가 미확정이다.
3. Django와 FastAPI 이중 서비스는 일정·관측성·장애 대응 복잡도를 높인다.
4. 실제 호텔 데이터와 외부 시스템 연동은 별도 보안·개인정보·운영 승인이 필요하다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-07-21 15:24 | 보호 기준 자료의 HTML 내용을 최신 Django·FastAPI P0 경계와 문서관리 규칙에 맞는 Markdown 작업 문서로 정리 |
