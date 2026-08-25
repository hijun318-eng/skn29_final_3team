# Answervice 구현 및 Merge 현황 요약

| 항목 | 내용 |
|---|---|
| 문서 설명 | MCP·RAG·ML·관리자 페이지의 통합 구현, Docker 기동 및 검증 현황 요약 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-08-24 17:45 |
| 작성·수정 | OpenAI Codex |
| 대상 경로 | `D:\bootcamp\20260824톨합` |
| 상태 기준 | 실제 코드 변경과 2026-08-24 동적 Docker/API 확인 결과 |

## 1. 결론

현재 작업공간에는 RAG, ML, MCP 연동 기반과 독립 관리자 페이지가 이식되어 있다. 관리자 페이지와 원천 데이터베이스 5개, DataHub 핵심 서비스는 실제 기동 확인을 마쳤다.

다만 Trino는 설정과 실행 이미지 버전 차이로 재시작 중이며, Model API는 Docker Desktop 재시작 후 컨테이너가 종료된 상태다. MCP의 `initialize → tools/list → 실제 Tool 호출 → 전체 분석 흐름`도 이 작업공간에서 최종 재검증하지 않았다.

따라서 현재 상태는 **부분 통합 완료**이며, 전체 MCP 완료 또는 최종 E2E 완료로 판정하면 안 된다.

## 2. 구현 및 이식 현황

| 영역 | 구현·이식 내용 | 현재 판정 |
|---|---|---|
| RAG | RAG API, 로컬 답변 API, pgvector, 통합 Backend·Frontend 구성이 작업공간에 존재 | 코드 이식됨, 최신 전체 E2E 재검증 필요 |
| ML | ML 분석 Backend·Runtime·Frontend 구성과 역할 기반 접근 코드가 존재 | 코드 이식됨, Runtime 재기동 필요 |
| MCP | RAG·ML·DataHub·데이터 조회 연동을 위한 MCP 구조와 Backend 연결 기반이 존재 | 구조 이식됨, MCP 프로토콜 실호출 재검증 필요 |
| 관리자 페이지 | 독립 FastAPI·PostgreSQL·Nginx SPA 구성, 로그인·세션·연결 상태 화면 구현 | 동적 로그인 및 주요 연결 상태 확인 |
| 원천 데이터 | PMS·POS·CRM·Facility·Banquet 데이터베이스 Compose 기동 | 5개 모두 healthy 확인 |
| DataHub | Kafka·MySQL·OpenSearch·GMS, TLS, SystemUpdate 초기화 | 핵심 4개 healthy, SystemUpdate exit 0 |
| Trino | TLS·비밀번호 DB·Serving Catalog·Object Store 구성 | 현재 재시작 반복, 수정 필요 |
| 권한 | 일반 조회는 모든 사용자 허용, ML은 객실수요담당자·시스템관리자 대상 정책 코드가 있으나 차단 적용은 false | 요청 정책 반영, 운영 전 재검토 필요 |

## 3. 관리자 페이지 적용 내용

독립 관리자 시스템은 기존 서비스와 별도 Compose로 구성되어 있다.

| 구성 | 내용 |
|---|---|
| Web | Nginx 기반 SPA, `127.0.0.1:28080` |
| API | FastAPI, `127.0.0.1:28081` |
| DB | PostgreSQL, `127.0.0.1:35432` |
| 인증 | 관리자 로그인과 세션 쿠키 방식 |
| 디자인 | 기존 서비스의 색상·레이아웃·컴포넌트 톤에 맞춤 |
| 상태 확인 | PostgreSQL DSN, HTTP, TCP Probe 지원 |
| Docker 네트워크 | Admin, Node2 Validation, 원천 DB, DataHub 네트워크 연결 |

주요 반영 파일:

- `admin/backend/app/config.py`
- `admin/backend/app/services.py`
- `admin/compose.yml`
- `admin/.env`

`admin/.env`에는 민감정보가 있으므로 문서에 값을 기록하지 않는다.

## 4. Docker 및 데이터 플랫폼 현황

사용 컨텍스트와 프로젝트 범위:

| 항목 | 값 |
|---|---|
| Docker Context | `desktop-linux` |
| Compose Project | `answervice` |
| 조회 필터 | `label=com.docker.compose.project=answervice` |

### 4.1 확인된 주요 상태

| 대상 | 최종 확인 상태 | 설명 |
|---|---|---|
| Admin Web | healthy | 관리자 화면 접속 가능 |
| Admin API | healthy | 로그인 및 연결 목록 API 확인 |
| Admin DB | healthy | 관리자 데이터 저장소 |
| PMS PostgreSQL | healthy | TCP 연결 확인 |
| POS MySQL | healthy | TCP 연결 확인 |
| CRM SQL Server | healthy | TCP 연결 확인 |
| Facility ClickHouse | healthy | TCP 연결 확인 |
| Banquet PostgreSQL | healthy | TCP 연결 확인 |
| App PostgreSQL | running | Backend 공용 데이터베이스 |
| DataHub OpenSearch | healthy | 신규 볼륨 초기화 완료 |
| DataHub Kafka | healthy | 메시지 브로커 |
| DataHub MySQL | healthy | DataHub 저장소 |
| DataHub GMS | healthy | TLS SAN 수정 후 health 통과 |
| DataHub SystemUpdate | exited 0 | 필수 OpenSearch 인덱스 생성 완료 |
| Serving Catalog | healthy | Trino용 Catalog |
| Serving Object Store | healthy | Trino용 Object Store |
| Trino | restarting | S3 설정과 Trino 476의 설정 계약 불일치 |
| Model API | exited 255 | Docker Desktop 재시작 뒤 자동 복구되지 않음 |

### 4.2 로컬 유지 이미지

다음 이미지 태그가 로컬 Docker에 존재함을 확인했다.

| 이미지 |
|---|
| `answervice-rag-e2e-backend:20260819-orchestration2` |
| `trinodb/trino:476` |
| `opensearchproject/opensearch:2.19.3` |
| `confluentinc/cp-kafka:8.2.2` |
| `mysql:8.2` |
| `acryldata/datahub-gms:v1.7.0` |
| `postgres:16.13-bookworm` |

Kafka와 MySQL 8.2는 이미지 데이터는 있었지만 태그가 없어 Docker Desktop 화면에 표시되지 않았다. 실행 컨테이너의 이미지 ID에 공식 태그를 다시 연결해 복구했다.

## 5. Trino 장애 현황

Trino는 현재 사용할 수 있는 정상 상태가 아니다.

| 항목 | 내용 |
|---|---|
| 실행 이미지 | `trinodb/trino:476` |
| 상태 | 재시작 반복 |
| 확인 RestartCount | 28 |
| 직접 원인 | Iceberg Catalog의 `s3.endpoint`, `s3.path-style-access`, `s3.region` 등의 속성이 사용되지 않았다고 판단되어 부팅 실패 |
| 구조 원인 | 현재 dev Compose 설정은 Trino 483 기준인데 운영 유지 이미지 정책으로 476을 실행 |

Admin 화면의 Trino `READY`는 TCP 포트 개방 확인 결과다. Trino가 재시작하는 짧은 시간에도 포트가 열릴 수 있으므로 실제 SQL 서비스 정상 여부를 뜻하지 않는다.

권장 해결은 Trino 476을 유지하면서 native S3 활성화와 476 호환 Catalog 속성을 적용한 뒤 `SELECT 1`과 실제 Catalog 조회를 확인하는 것이다. 대안은 dev Compose 기준인 Trino 483으로 통일하는 것이지만 기존 이미지 유지 정책과 큰 이미지 다운로드 비용을 다시 검토해야 한다.

## 6. Model API 장애 현황

Model API는 코드 자체가 실패한 것으로 확인되지 않았다.

| 항목 | 내용 |
|---|---|
| 대상 컨테이너 | `answervice-ml-validation-runtime-20260824` |
| 현재 상태 | `Exited (255)` |
| 종료 전 기록 | `GET /health` 200 반복 확인 |
| 추정 원인 | Docker Desktop Engine 재시작 뒤 자동 복구되지 않음 |
| 필요한 조치 | 기존 ML Compose 설정으로 Runtime 재기동 후 `/health`와 실제 추론 호출 확인 |

ML Runtime은 기존 운영 관리 대상 8개에 포함되지 않아 이번 복구 과정에서 임의 재시작하지 않았다.

## 7. Admin 연결 화면의 실제 의미

마지막 Admin API 확인 결과:

| 연결 | Admin 표시 | 실제 판단 |
|---|---|---|
| PMS | READY | 정상 |
| POS | READY | 정상 |
| CRM | READY | 정상 |
| Facility | READY | 정상 |
| Banquet | READY | 정상 |
| App PostgreSQL | READY | 정상 |
| DataHub | READY | GMS healthy와 SystemUpdate 성공 확인 |
| Trino | READY | TCP 기준의 일시적 false positive, 실제 서비스 비정상 |
| Model API | DOWN | ML Runtime 종료 상태 |

운영 상태 화면의 정확도를 높이려면 Trino는 인증된 `SELECT 1`, DataHub는 실제 GMS health 응답, Model API는 `/health` 응답을 기준으로 바꿔야 한다.

## 8. Merge 현황

| 구분 | 상태 | 비고 |
|---|---|---|
| 통합 작업공간 반영 | 적용됨 | `D:\bootcamp\20260824톨합` 기준 |
| RAG·ML·MCP 구조 이식 | 적용됨 | 작업공간 코드 기준 |
| 관리자 페이지 통합 | 적용됨 | 독립 Compose와 네트워크 연결 포함 |
| 데이터 플랫폼 통합 | 적용됨 | 원천 DB·DataHub·Serving 계층 |
| Git commit | 이번 작업에서 확인하지 않음 | Git 명령 미실행 |
| 개인 브랜치 → dev merge | 확인하지 않음 | 실제 branch·commit 비교 필요 |
| 원격 JAEHONG 브랜치 반영 | 확인하지 않음 | push 또는 강제 갱신 수행 기록 없음 |
| 공식 Merge 완료 판정 | 보류 | Trino·Model API·MCP E2E 미완료 |

작업 중 `answervice-rag-daesung-api-20260824` 컨테이너가 별도 세션에서 새로 생성된 것을 확인했다. 이 컨테이너는 이번 작업에서 생성하지 않았으며 소유자 확인 전에는 변경하거나 삭제하지 않는다.

## 9. 저장소 외부 런타임 파일

운영 비밀정보와 override는 저장소 밖에 생성했다.

| 경로 | 용도 |
|---|---|
| `%LOCALAPPDATA%\Answervice\deployment\answervice-20260824.env` | 데이터 플랫폼 배포 환경값 |
| `%LOCALAPPDATA%\Answervice\deployment\trino-476.override.yml` | Trino 476 및 고유 컨테이너 이름 override |
| `%LOCALAPPDATA%\Answervice\deployment\datahub.override.yml` | DataHub 고유 이름과 포트 override |
| `%LOCALAPPDATA%\Answervice\secrets\database-20260824\` | Trino·DataHub TLS, 인증 DB, Catalog 키 |

비밀번호, 토큰, private key 원문은 저장소 문서와 로그에 기록하지 않는다.

## 10. 남은 작업 우선순위

| 순서 | 작업 | 완료 조건 |
|---:|---|---|
| 1 | Trino 476 호환 S3 Catalog 설정 적용 | 컨테이너 healthy, 재시작 0, 인증된 `SELECT 1` 성공 |
| 2 | ML Runtime 재기동 | `/health` 200과 실제 추론 1건 성공 |
| 3 | Admin Probe 정확도 개선 | Trino·DataHub·Model의 애플리케이션 수준 검증 |
| 4 | MCP 프로토콜 검증 | `initialize`, `tools/list`, 실제 Tool 호출 성공 |
| 5 | RAG·ML·DataHub 실연동 검증 | Mock 없는 실제 조회와 응답 확인 |
| 6 | 전체 분석 E2E | `G1 → Node2 → G2 → Trino → G3` 성공 |
| 7 | 감사 추적 검증 | `request_id → tool_call → query → artifact → audit` 저장 확인 |
| 8 | Git Merge 확인 | branch·commit·diff 확인 후 dev 또는 승인 브랜치에 반영 |

## 11. 완료 판정 기준

다음 흐름이 실제 사용자 질의로 통과하기 전에는 MCP 또는 전체 통합 완료로 선언하지 않는다.

```text
사용자 질문
→ 인증·권한
→ Router
→ MCP Tool
→ 실제 DataHub / RAG / ML
→ 승인 Context
→ G1
→ Node2
→ G2
→ 실제 Trino
→ G3
→ 응답·보고서
→ Audit Trace 저장
```

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-08-24 17:45 | MCP·RAG·ML·관리자 페이지 이식, Docker 기동, DataHub 정상화, Trino·Model API 장애와 Merge 보류 상태 정리 |
