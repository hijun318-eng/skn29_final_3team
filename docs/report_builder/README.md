# 보고서 편집기 고도화 현황 및 우선순위

이 문서는 `seung` 브랜치에서 진행 중인 "보고서 편집기(Report Builder) UX 고도화" 작업의 현재 상태를 기록한다. 새 세션(AI 포함)이 이 작업을 이어받을 때는 이 문서를 먼저 읽고, 아래 "검증된 사실"은 코드로 재확인한 뒤 신뢰할 것.

## 0. 두 개의 코드베이스가 존재한다

| | 위치 | 성격 |
|---|---|---|
| **프로토타입** | `C:/Users/Playdata/Documents/파이널 프젝젝젝/answervice-report-prototype` (이 git 저장소 밖, 별도 로컬 프로젝트) | UX 검증용 목업. 100% mock 데이터, 백엔드/인증 없음. 자유 드래그·리사이즈·8칸 그리드 자동 재배치(`src/report/layout.js`의 `packPageBlocks`) |
| **실서비스** | 이 저장소의 `app/frontend/src/pages/ReportsPage.jsx` + `app/backend/app/api/report_router.py` 등 | 실제 백엔드에 연결된, 이미 동작하는 보고서 편집기. `daesung` 브랜치 작업이 `dev`/`seung`에 이미 병합되어 있음 |

**중요**: 프로토타입 코드를 실서비스에 그대로 옮겨 붙이는 것은 불가능하다(좌표계·블록 스키마·데이터 소스 규칙이 다름). 프로토타입은 "코드 이식 대상"이 아니라 "UX 레퍼런스"로만 쓴다.

## 1. 실서비스 백엔드 제약 (코드로 검증된 사실)

### 1.1 블록은 12칸 정수 그리드, 타입은 3종뿐

`app/backend/app/report_contracts.py`의 `ReportBlockRequest`:
```python
type: Literal["table", "chart", "text"] = "table"
x: int = Field(ge=0, le=11)
w: int | None = Field(ge=1, le=12)
```

DB 제약 (`app/backend/migrations/versions/20260804_05_report_v11_registration.py`):
```sql
CHECK (columns = w AND x >= 0 AND y >= 0 AND w BETWEEN 1 AND 12 AND h > 0 AND x + w <= 12)
CHECK ((block_type IN ('table', 'chart') AND artifact_id IS NOT NULL)
    OR (block_type = 'text' AND btrim(content) <> ''))
```

**핵심**: `table`/`chart` 블록은 반드시 실제 분석 결과(`artifact_id`)에 연결되어야 DB에 저장된다. Mock 숫자를 직접 타이핑해 넣는 방식은 DB 단에서부터 막혀 있다(G1·G2·G3 증거 기반 원칙과 일치). `text` 블록만 artifact 없이 자유롭게 저장 가능(Markdown 지원, 내용만 있으면 됨).

### 1.2 API 계약 (`app/backend/app/api/report_router.py`)

이미 존재하는 엔드포인트: 정의 생성/목록(`/reports/definitions`), 버전 조회, 블록 전체 교체(`PUT .../blocks`), 승인(`.../approve`, 승인되면 트리거로 불변화됨), 다음 draft 생성, 분석 아티팩트로부터 초안 생성(`/reports/drafts/from-analysis-artifact`), 실행(runs)/스케줄/AI 어시스턴트 초안(`/reports/assistant/drafts`). `app/frontend/src/api/reportClient.ts`가 전부 감싸서 제공한다.

### 1.3 인증

`app/backend/app/auth.py`(세션 토큰) + `app/frontend/src/components/auth/SessionLogin.jsx`. 쿠키 기반 세션(`credentials: "include"`)으로 동작.

## 2. 실서비스(`ReportsPage.jsx`)에 이미 구현되어 있는 것

- Undo/Redo (`history` state, `undo`/`redo` 함수)
- 드래그·리사이즈 + 12칸 그리드 자동 재배치(`placeDraftBlock`, `compactDraftLayout` — `app/frontend/src/contracts/report.ts`)
- 블록 복제/삭제 (`ReportBlockMenu`)
- 템플릿(드래그로 삽입, `REPORT_TEMPLATES`/`ARTIFACT_TEMPLATES`)
- `text` 블록 Markdown 편집 (`MarkdownBlockEditor`)

## 3. 프로토타입에는 있지만 실서비스엔 없는 것

블록 잠금, 멀티 셀렉트 + 일괄 정렬/삭제, 버전 스냅샷, 블록 댓글, 전체 텍스트 검색, 드래그 정렬 가이드라인, KPI/목표게이지/이미지 전용 블록 타입, 서체·색상 팔레트, 표 조건부 서식.

## 4. 고도화 구현 우선순위

### P0 — 백엔드 변경 없이 바로 착수 가능 (프론트엔드 상태 관리만)
지금 `ReportsPage.jsx`의 기존 구조(블록 배열 + `history` state) 위에 얹으면 되는 것들. 프로토타입 구현을 레퍼런스로 재작성.

1. 블록 잠금 (이동/리사이즈/삭제 차단 플래그)
2. 멀티 셀렉트 + 일괄 잠금/삭제
3. 드래그 정렬 가이드라인 (다른 블록과 위/아래/왼쪽/가운데 정렬 시 안내선)
4. 버전 스냅샷 (전체 blocks 배열을 이름 붙여 저장/복원, Undo/Redo와 별개)
5. 블록 댓글
6. 전체 텍스트 검색 (block.content 순회)

### P1 — `text` 블록 안에서 해결 (백엔드 변경 없음)
제목/AI 요약/일반 문단 스타일은 이미 자유로운 `text` 블록의 Markdown/HTML content로 표현 가능. 서체·글자색·글자크기 등은 text 블록 렌더러에 스타일 옵션을 추가하는 방식으로 구현.

### P2 — 백엔드 스키마 변경 필요
KPI 카드, 목표 대비 게이지, 이미지 블록처럼 구조화된 전용 블록 타입이 필요한 기능. `report_contracts.py`의 `Literal["table","chart","text"]`, DB `report_block_type_check` 제약, `report.ts`의 타입 정의를 모두 확장하는 마이그레이션이 필요. **팀 논의 후 진행.**

### P3 — 조직적 확인 필요
`docs/e2e_mvp/03_E2E_아키텍처_및_계약.md` §7 "Slice 1 변경 경계"에 "Report editor 고도화는 Slice 1 변경 경계가 아니다"라고 명시되어 있음. P2 이상 규모의 작업(특히 스키마 변경)은 이 범위 승인을 먼저 받아야 한다. P0/P1은 편집 UX 개선 수준이라 상대적으로 부담이 적지만, 착수 전 팀 공유는 권장.

## 5. 참고 파일

- `app/backend/app/report_contracts.py`
- `app/backend/migrations/versions/20260804_04_report_registration.py`, `20260804_05_report_v11_registration.py`
- `app/backend/app/api/report_router.py`
- `app/backend/app/adapters/report_repository.py`
- `app/frontend/src/pages/ReportsPage.jsx`
- `app/frontend/src/contracts/report.ts`
- `app/frontend/src/api/reportClient.ts`
- 프로토타입: `C:/Users/Playdata/Documents/파이널 프젝젝젝/answervice-report-prototype/src/report/ReportBuilder.jsx`, `src/report/layout.js`
