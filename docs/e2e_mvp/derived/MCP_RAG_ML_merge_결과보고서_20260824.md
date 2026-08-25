# MCP·RAG·ML Merge 결과보고서

| 항목 | 내용 |
|---|---|
| 문서 목적 | 후속 AI 또는 개발자가 현재 변경을 안전하게 병합하고 검증하도록 구현 계약과 증거 제공 |
| 기준일 | 2026-08-24 |
| 작업 트리 | `D:\bootcamp\20260824톨합` |
| 기준 브랜치 | `daesung` |
| 대상 런타임 | Docker Context `desktop-linux`, Compose Project `answervice` |
| 결과 상태 | MCP Tool Registry, RAG, ML, Audit, 역할 공개 정책 통합 및 동적 검증 완료 |

## 1. Merge 결론

현재 변경은 기존 Backend의 인증과 `RequestContext`를 그대로 사용하면서 MCP를 얇은 실행 경계로 추가했다. RAG와 ML 구현을 새로 복제하지 않고 기존 서비스에 typed adapter를 연결했다.

```text
Authentication / RequestContext
→ MCP Router
→ Tool Registry + Access Policy
→ Typed Input Validation
→ Existing RAG or ML Service
→ Actual Runtime
→ Structured MCP Result
→ PostgreSQL Audit
```

Merge 시 핵심 보존 조건은 다음과 같다.

1. MCP 목록 권한과 호출 권한은 반드시 같은 중앙 정책을 사용한다.
2. 기본값 `MCP_ROLE_ENFORCEMENT_ENABLED=false`를 유지한다.
3. ML 제한 모드 허용 역할은 `analyst`, `platform_admin`으로 유지한다.
4. Alembic `20260824_36 → 20260824_37` 순서를 보존한다.
5. RAG와 ML은 Mock이나 하드코딩 결과가 아니라 기존 실제 Runtime을 호출한다.
6. 기존 작업 트리의 다른 변경을 되돌리지 않는다.

## 2. 구현 범위

### 2.1 MCP Transport

Endpoint는 `POST /mcp`이며 다음 JSON-RPC method를 지원한다.

| Method | 기능 |
|---|---|
| `initialize` | 프로토콜 협상과 서버 정보 반환 |
| `tools/list` | 현재 사용자에게 허용된 Tool 목록 반환 |
| `tools/call` | Tool 입력 검증 후 실제 서비스 호출 |

현재 서버 계약은 다음 값을 요구한다.

| 구분 | 값 또는 조건 |
|---|---|
| Protocol Version | `2026-07-28` |
| 공통 Header | `MCP-Protocol-Version`, `Mcp-Method` |
| Tool 호출 Header | `Mcp-Name`과 `params.name` 일치 |
| 공통 Params | 모든 요청에 유효한 `clientInfo` 필요 |
| 인증 | 기존 로그인 세션 또는 Backend 인증 계약 |

`tools/list`와 `tools/call`이 서로 다른 권한 판단을 사용하지 않도록 `McpToolService._authorized()`에서 중앙 정책을 호출한다.

### 2.2 Tool 계약

| Tool | 입력 | 실제 실행 경로 |
|---|---|---|
| `analysis.get_run` | `request_id: UUID` | `PostgresAnalysisRepository.get_run()` |
| `rag.answer` | `query: string`, 길이 2~500 | `InternalManualAgent.execute()` |
| `ml.predict` | `hotel_scope`, `OCCUPANCY_RATE`, `horizon` 1~7 | `MLPredictionService.predict_approved_task()` |

Tool Registry가 비활성 상태이거나 ID와 코드가 일치하지 않으면 실행하지 않는다. Pydantic 입력 모델은 추가 필드를 거부한다.

### 2.3 RAG 연결

- Tool code를 `rag.answer`로 통일했다.
- `InternalManualAgent`를 통해 실제 RAG API를 호출한다.
- HMAC 요청, 역할 매핑, 인용 근거, RAG 감사 저장 경로를 유지한다.
- RAG Registry 역할은 현재 네 canonical role 전체다.

### 2.4 ML 연결

- Tool code를 `ml.predict`로 통일했다.
- MCP 입력을 기존 ML 서비스가 받는 승인 요청으로 변환한다.
- 기존 ML 권한, capability 확인, Runtime 호출, 결과 검증, 집계, audit 경계를 재사용한다.
- Runtime timeout 기본값은 30초다.
- 검증된 실제 결과의 feature source는 `LIVE_TRINO_PMS`다.

### 2.5 Audit

MCP 실행은 Tool Registry ID, 사용자, 역할, trace, 입력 hash, 상태, 지연 시간, 출력 참조, 오류 코드를 PostgreSQL에 기록한다.

기록 상태는 최소 다음을 포함한다.

| 상태 | 의미 |
|---|---|
| `SUCCEEDED` | 실제 Tool 실행 성공 |
| `FAILED` | Runtime, Repository, 입력 이후 실행 실패 |
| `DENIED` | 역할 또는 capability 정책에 의한 거부 |

## 3. 권한 결정

### 3.1 현재 적용값

```text
MCP_ROLE_ENFORCEMENT_ENABLED=false
```

공개 모드에서는 인증된 canonical role 전체가 MCP Tool을 조회하고 호출할 수 있다.

```text
analyst
report_admin
data_admin
platform_admin
```

### 3.2 향후 제한값

```text
MCP_ROLE_ENFORCEMENT_ENABLED=true
```

제한 모드에서 `ml.predict` 허용 역할은 다음과 같다.

```text
analyst         # 현재 객실수요담당자 canonical role
platform_admin  # 시스템관리자 canonical role
```

`report_admin`, `data_admin`은 ML 목록에서 제외되며 직접 호출도 `ACCESS_DENIED`, JSON-RPC `-32001`로 거부된다.

별도 `room_demand_manager` enum과 DB role constraint는 추가하지 않았다. 전역 역할 추가는 인증 파일, DB constraint, 권한 snapshot, UI와 마이그레이션에 연쇄 영향을 주므로 현재 요구사항에서는 `analyst` 매핑이 최소 위험안이다.

## 4. 변경 파일 Inventory

| 파일 | 변경 종류 | Merge 시 보존할 내용 |
|---|---|---|
| `app/backend/app/api/mcp_router.py` | 변경 | MCP JSON-RPC transport, protocol/header 검증, initialize/list/call |
| `app/backend/app/services/mcp_tool_service.py` | 신규 또는 변경 | Registry 조회, typed validation, 실제 RAG/ML dispatch, 중앙 ACL |
| `app/backend/app/services/mcp_audit_repository.py` | 신규 | MCP 실행 감사 이력 영속화 |
| `app/backend/app/services/mcp_access_policy.py` | 신규 | 공개 모드 기본값과 ML 제한 역할 중앙 정책 |
| `app/backend/app/services/rag_gateway.py` | 변경 | RAG Tool code `rag.answer` |
| `app/backend/app/services/ml_prediction_service.py` | 변경 | `predict_approved_task`, 중앙 ML 역할 정책 |
| `app/backend/app/api/ml_router.py` | 변경 | ML HTTP 경로에도 같은 역할 정책 적용, request ID 전달 |
| `app/backend/compose.fragment.yml` | 변경 | ML timeout 30초, 역할 적용 플래그 기본값 false |
| `app/backend/migrations/versions/20260824_36_rag_tool_registry.py` | 신규 | `rag.answer`, `ml.predict` Tool Registry 등록 |
| `app/backend/migrations/versions/20260824_37_mcp_role_visibility.py` | 신규 | RAG 전체 역할과 ML 향후 제한 역할 저장 |

## 5. Database Migration 계약

현재 테스트 DB의 Alembic revision은 `20260824_37`이다.

```text
20260823_35
→ 20260824_36
→ 20260824_37
```

Registry 최종값은 다음과 같다.

| Tool | Enabled | `required_roles_json` |
|---|---|---|
| `analysis.get_run` | `true` | `["analyst"]` |
| `rag.answer` | `true` | `["analyst","report_admin","data_admin","platform_admin"]` |
| `ml.predict` | `true` | `["analyst","platform_admin"]` |

공개 모드에서는 중앙 정책이 Registry role 제한을 적용하지 않는다. 제한 모드에서는 capability와 Registry role을 적용하며 ML은 코드의 고정 allow-list도 함께 확인한다.

이미 적용된 `20260824_36`을 수정하지 않는다. 역할 정책 변경은 반드시 후속 migration으로 수행한다.

## 6. 동적 검증 증거

### 6.1 이전 실제 Tool 검증

| 항목 | 결과 |
|---|---|
| RAG 호출 | `ANSWER`, citations 2건 |
| RAG trace | `3787658ae67448808e81db9711041109` |
| ML 호출 | `SUCCESS`, hotel `GRAND`, metric `OCCUPANCY_RATE` |
| ML source | `LIVE_TRINO_PMS` |
| ML model | `live-pms-hist-gradient-boosting@pms-grand-2026-08-19` |
| ML Trino query ID | 3건 반환 |
| ML trace | `c9b677d965f94c7da4185d753ca87b26` |
| 인증 없음 | HTTP 401 |
| 잘못된 MCP protocol | JSON-RPC `-32600` |
| 잘못된 Tool 인자 | JSON-RPC `-32602` |
| 감사 이력 | RAG/ML 성공과 접근 거부 저장 확인 |

### 6.2 역할 정책 실제 검증

공개 모드 결과:

```text
public:analyst tools=3 ml=true
public:report_admin tools=3 ml=true
public:data_admin tools=3 ml=true
public:platform_admin tools=3 ml=true
public:report_admin ml.predict=SUCCESS source=LIVE_TRINO_PMS
```

제한 모드 결과:

```text
restricted:analyst ml=true
restricted:platform_admin ml=true
restricted:report_admin ml=false direct_call=-32001
restricted:data_admin ml=false direct_call=-32001
```

검증 종료 상태:

```text
MCP_ROLE_ENFORCEMENT_ENABLED=false
health=healthy
restarts=0
```

검증용 인증 파일은 임시 생성 후 삭제했으며 원래 인증 파일을 다시 mount했다.

## 7. Docker Runtime 상태

| 항목 | 값 |
|---|---|
| Context | `desktop-linux` |
| Project label | `com.docker.compose.project=answervice` |
| 관리 대상 Backend | `answervice-rag-e2e-backend-20260819-test` |
| Image | `answervice-rag-e2e-backend:20260819-orchestration2` |
| Host port | `127.0.0.1:28001` |
| App DB | `answervice_mcp_daesung` |
| 최종 상태 | `healthy`, restart 0 |

다른 RAG, ML, Frontend 컨테이너는 이 권한 변경을 위해 수정하거나 제거하지 않았다.

## 8. Merge 절차

1. 위 Inventory 파일을 기존 변경과 함께 충돌 없이 반영한다.
2. `20260824_36`, `20260824_37` migration chain을 보존한다.
3. 배포 환경에 `MCP_ROLE_ENFORCEMENT_ENABLED=false`를 명시한다.
4. Backend 이미지를 현재 소스로 다시 빌드한다.
5. 해당 App DB에 Alembic `upgrade head`를 적용한다.
6. 기존 인증 secret mount와 Runtime URL을 유지해 Backend를 재배포한다.
7. `/health`와 `/readiness`를 확인한다.
8. 정상 로그인 후 `initialize`, `tools/list`, `tools/call`을 순서대로 실행한다.
9. RAG, ML 결과가 실제 Runtime provenance를 포함하는지 확인한다.
10. PostgreSQL audit에서 성공 또는 거부 이력을 확인한다.

## 9. 후속 AI 작업 시 금지사항

- `MCP_ROLE_ENFORCEMENT_ENABLED` 기본값을 임의로 `true`로 바꾸지 않는다.
- 익명 공개로 해석해 인증을 제거하지 않는다.
- `tools/list`만 공개하고 `tools/call`은 별도 정책으로 분기하지 않는다.
- 역할 이름을 새로 추가하면서 DB constraint와 인증 계약을 누락하지 않는다.
- 기존 RAG/ML 구현을 Mock으로 교체하지 않는다.
- 실제 API Key, 비밀번호, 세션 secret을 로그나 문서에 남기지 않는다.
- 관리 대상 외 Docker 컨테이너와 이미지를 정리하지 않는다.
- `--remove-orphans`를 사용하지 않는다.

## 10. 미완료 또는 별도 판단 항목

| 항목 | 현재 판단 |
|---|---|
| 전용 `room_demand_manager` 역할 | 미도입, 현재 `analyst`로 매핑 |
| 권한 제한 활성화 시점 | 운영 책임자가 결정, 현재 false 유지 |
| 전체 사용자 질문부터 보고서까지 Golden E2E | 이번 역할 변경의 완료 범위가 아님 |
| DataHub 장애, Trino 장애 전체 회귀 | 기존 통합 계획에서 별도 반복 검증 필요 |
| Frontend 역할별 메뉴 숨김 | Backend 정책과 별도 확인 필요 |

## 11. AI 인수인계용 최소 Context

```yaml
workspace: D:\bootcamp\20260824톨합
docker_context: desktop-linux
compose_project: answervice
backend_container: answervice-rag-e2e-backend-20260819-test
backend_image: answervice-rag-e2e-backend:20260819-orchestration2
database: answervice_mcp_daesung
alembic_revision: 20260824_37
mcp_endpoint: POST /mcp
mcp_protocol_version: 2026-07-28
role_enforcement_env: MCP_ROLE_ENFORCEMENT_ENABLED
role_enforcement_final_value: false
room_demand_role_mapping: analyst
system_admin_role_mapping: platform_admin
registered_tools:
  - analysis.get_run
  - rag.answer
  - ml.predict
final_runtime_status: healthy
```

## 변경 이력

| 버전 | 일자 | 내용 |
|---|---|---|
| 1.0 | 2026-08-24 | MCP·RAG·ML 이식, 권한 정책, 마이그레이션, 동적 검증 및 Merge 조건 정리 |
