# Hotel Signal AI 프로젝트 디렉터리 구조

## 1. 문서 목적

이 문서는 Hotel Signal AI Baseline과 후속 P0 강화의 파일 배치와 서비스 책임을 정한다. 첫 Baseline은 React·Django·`src`만 실행하며 `app/fastapi/`는 향후 독립 분석 서비스의 경계로만 유지한다.

작업 전 우선순위는 다음과 같다.

1. `/AGENTS.md`
2. `/docs/markdown/final_project/00_project_control.md`
3. `/docs/markdown/final_project/common_project_specification.md`
4. `/docs/문서관리규칙.md`
5. 이 문서

## 2. 조사 시점의 현재 구조

```text
repository/
├─ app/.gitkeep
├─ src/.gitkeep
├─ data/
│  ├─ raw/.gitkeep
│  ├─ processed/.gitkeep
│  └─ samples/.gitkeep
├─ tests/.gitkeep
├─ evals/.gitkeep
├─ notebooks/.gitkeep
├─ docs/
│  ├─ markdown/
│  │  └─ final_project/
│  ├─ deliverables/
│  └─ templates/
├─ AGENTS.md
├─ README.md
└─ .gitignore
```

현재 React·Django·FastAPI·Docker 프로젝트는 초기화되지 않았다.

## 3. 확정한 최소 구조

```text
repository/
├─ app/
│  ├─ react/       # 관리자 UI 공용 경계, 실제 code는 구현 시 추가
│  ├─ django/      # 업무 API·권한·DB 공용 경계, 실제 code는 구현 시 추가
│  └─ fastapi/     # AI 분석 API 공용 경계, 분리 결정 후 실제 code 추가
├─ src/
│  ├─ analysis/    # 결정론적 분석 로직 공용 경계
│  └─ common/      # 공유 enum·schema 공용 경계
├─ data/
│  ├─ raw/
│  ├─ processed/
│  └─ samples/
├─ tests/
├─ evals/
├─ notebooks/
└─ docs/
   ├─ markdown/final_project/
   ├─ deliverables/
   └─ templates/
```

## 4. 이번 작업에서 실제 생성한 폴더

팀별 작업 경계를 Git에서 공용으로 유지하기 위해 다음 폴더를 생성하고 각각 `.gitkeep`만 두었다.

```text
app/react/
app/django/
app/fastapi/
src/analysis/
src/common/
```

이는 구현 완료를 뜻하지 않는다. framework 초기화, dependency, 실행 진입점, 설정과 실제 코드는 아직 없다.

## 5. 생성하지 않은 확장 폴더

- `app/fastapi/agents/`, `app/fastapi/mcp/`
- 다수의 선제적 Django app과 React feature 폴더
- `src/retrieval/`, `src/embeddings/`, `src/graph/`
- `data/vectorstore/`
- Kafka·Redis·Neo4j·Kubernetes 관련 `infra/`
- `tests/e2e/`
- `docs/specs/`, `docs/wireframes/`, `docs/architecture/`, `docs/audit/`

## 6. `app`과 `src`의 차이

| 구분 | 포함 | 포함하지 않음 |
|---|---|---|
| `app` | 프레임워크 설정, route, controller/view, serializer, UI, 실행 진입점 | 재사용 가능한 핵심 계산을 중복 구현하지 않음 |
| `src` | 스키마 검증, 집계, 규칙, evidence 구성, 공통 enum·schema | HTTP·UI·ORM에 종속된 코드 |

의존 방향은 `app → src`다. `src`가 Django·FastAPI·React를 import하지 않는다.

## 7. 서비스별 책임

### 7.1 `app/react/`

- 데모 로그인 또는 역할 선택
- 호텔 관리자 대시보드
- 이상 이슈 상세와 현장 확인 메모
- 주간 보고서 검토·승인
- 합성 데이터·데이터 버전·근거·오류 상태 표시

브라우저에서 권한에 따라 메뉴를 숨기더라도 보안 통제로 간주하지 않는다. 실제 권한은 Django가 검증한다.

### 7.2 `app/django/`

- Baseline demo 역할 선택과 server-side 역할 검사
- Baseline 통합 API 5개와 데이터 조회
- 현장 확인 메모 저장
- 주간 보고서 상태와 관리자 결정 관리
- P0 강화 시 객체 권한과 감사 로그
- DB migration의 단일 주체
- 합성 데이터 버전 전환용 management command

### 7.3 `app/fastapi/`

- 리뷰 카테고리·속성·감정 분석 API
- 이상 신호의 근거 구성 지원
- 원인 후보·반대 근거·데이터 부족 문장 생성
- 주간 보고서 초안 문장 생성
- 모델·분석 버전과 불확실성 반환

Baseline에서는 FastAPI project를 초기화하거나 실행하지 않는다. 현재 폴더는 팀 작업 경계만 표시한다. 독립 분석 서비스가 필요하다는 검증과 승인이 있을 때 P1에서 초기화하며, 그 경우에도 사용자 DB, 권한 DB, migration, 원시 SQL 실행 API를 가지지 않는다.

### 7.4 `src/analysis/`

- 입력 스키마 검증
- 규칙 기반 이상 감지
- 기간·시설 단위 집계
- VOC와 운영지표 결합
- evidence 묶음 구성
- V1·V2 결과 비교

### 7.5 `src/common/`

- 상태 enum
- 식별자·시간·버전 규칙
- 공통 API envelope schema
- 오류 코드
- React·Django·FastAPI 계약의 코드 원본

## 8. DB migration 단일화

Django만 DB migration을 생성·적용한다. FastAPI와 `src`는 Django 모델을 소유하지 않고, 승인된 repository/service interface 또는 API 계약으로 데이터를 읽는다.

다음은 금지한다.

- FastAPI 전용 사용자·권한 테이블
- 같은 테이블의 Django·FastAPI 중복 migration
- 프레임워크마다 다른 enum 저장값
- LLM이 생성한 SQL을 운영 DB에 직접 실행

## 9. 데이터 폴더 운영 규칙

| 경로 | 용도 | Git 정책 |
|---|---|---|
| `data/raw/` | 원천 공개·합성 입력의 로컬 보관 | `.gitkeep`, README 외 생성 파일 commit 금지 |
| `data/processed/` | 정제·집계 결과 | `.gitkeep`, README 외 생성 파일 commit 금지 |
| `data/samples/` | 작고 비식별인 재현 가능 예시·fixture | schema version·seed·`synthetic` 표시 후 제한적으로 추적 |

모든 합성 데이터는 최소 `data_version`, `schema_version`, `seed`, `synthetic=true`를 기록한다. 실제 고객·예약·운영 원본을 저장소에 넣지 않는다.

## 10. 금지 파일과 자산

- `.env`, API key, password, private key
- 실제 고객 이름·연락처·예약번호·객실번호가 포함된 파일
- `data/raw/`, `data/processed/`의 생성 데이터
- 10MB를 초과하는 확인되지 않은 산출물
- 승인되지 않은 호텔 로고·사진·폰트
- 실제 구현 없이 존재만 하는 framework boilerplate

## 11. 파일·모듈 이름 규칙

- Python module·package: `snake_case`
- React component: `PascalCase`
- TypeScript utility·hook: 프로젝트 초기화 시 합의한 한 가지 규칙 사용
- API path: 소문자 명사를 사용하고 복합어는 `kebab-case`로 통일
- DB table·field: `snake_case`
- enum value: 명세에 정의된 대문자 `UPPER_SNAKE_CASE`
- 식별자: `<entity>_id`
- 시간: UTC 저장, `Asia/Seoul` 표시 원칙을 명시적으로 구현
- 테스트: Python은 `test_<unit>.py`, 프론트는 초기화한 test runner 규칙 적용

## 12. 새 기능 추가 위치

| 기능 | 위치 | 조건 |
|---|---|---|
| 화면·상태 표현 | `app/react/` | 승인된 Baseline 4화면 계약 존재 |
| 역할 검사·업무 API·local DB | `app/django/` | Baseline 통합 API 계약 확정 |
| 독립 모델 서빙 | `app/fastapi/` | 별도 프로세스 운영 필요성이 검증됨 |
| 집계·규칙·교차분석 | `src/analysis/` | framework 독립 test 작성 가능 |
| 공통 enum·schema | `src/common/` | 둘 이상의 실행 경계가 공유 |
| 테스트·평가 | `tests/`, `evals/` | 기대 결과와 version이 정의됨 |
| 사람이 읽는 계약 | `docs/markdown/final_project/` | 기존 문서와 중복되지 않음 |

## 13. 구조 변경 승인 절차

1. 기존 위치와 중복 여부를 검색한다.
2. P0 또는 승인된 확장 요구사항에 필요한지 확인한다.
3. 책임·소유 데이터·dependency·migration 영향을 기록한다.
4. 대안과 trade-off를 팀에 제시한다.
5. 공통 명세와 화면·API 계약을 먼저 갱신한다.
6. 승인 후 최소 폴더와 실제 파일을 함께 만든다.
7. 경로·import·링크·테스트를 검증한다.

빈 폴더를 만들기 위한 구조 변경과 기술 유행만을 이유로 한 인프라 추가는 승인 대상이 아니다.
