# Report Builder V2 백엔드 개발 인계서

## 이 문서의 목적

`seung` 브랜치에는 UX 목업을 실서비스 구조에 맞게 이식한 Report Builder V2 프론트가 있다.
다음 작업자는 이 프론트를 다시 만들지 말고, 현재 백엔드 계약 때문에 저장·출력까지 연결되지
못한 기능을 구현해 목업과 같은 완성도에 도달시키는 역할을 맡는다.

이 문서 하나를 작업 시작점으로 사용하고, 적힌 내용은 실제 코드와 migration으로 재확인한다.

## 작업 위치

```text
저장소: C:/Users/Playdata/Downloads/skn29_final_3team
작업 브랜치: seung
프론트 구현 기준 커밋: 26fd3d9
```

```powershell
git fetch origin
git switch seung
git pull origin seung
git status --short --branch
git stash list
```

- 구현은 `seung`에서 한다.
- `daesung`은 읽기 전용 참고 자료다.
- `dev`를 fetch·merge·수정하지 않는다.
- 기존 SQL·ZIP·인프라 변경과 stash를 건드리지 않는다.
- 기존 migration은 수정하지 않고 새 revision을 추가한다.
- 사용자 요청 없이 PR이나 자동 merge를 만들지 않는다.

## 최종 목표

UX 목업에서 가능한 다음 흐름이 실서비스 데이터와 canonical HTML/PDF에서도 동작해야 한다.

```text
Artifact 선택
→ A4 페이지에 KPI·Chart·Table·Summary로 배치
→ 자유 이동·Resize·정렬
→ 페이지 추가·삭제·복제·순서 변경
→ 페이지별 세로형·가로형 설정
→ 다양한 차트와 표시 속성 설정
→ 사용자 템플릿·댓글·스냅샷 저장
→ HTML/PDF 미리보기와 다운로드
```

목업의 mock 데이터나 출력 방식을 복사하는 것이 아니라 기존 Artifact lineage, 권한, 승인,
checksum, WeasyPrint 계약을 유지해 완성해야 한다.

## 현재까지 완료된 프론트 작업

| 단계 | 상태 | 내용 |
|---|---|---|
| 실서비스 기반 | 완료 | 12열 Grid, Artifact API, Draft 저장, Undo/Redo, HTML/PDF, 전체 방향 전환 |
| 편집 편의 | 완료 | 멀티 선택, 잠금, 일괄 작업, 정렬 가이드, 검색, 세션 스냅샷, 복사·붙여넣기, 8단계 크기 |
| Builder V2 셸 | 완료 | 3단 Library/Workspace/Properties, 흰색 A4, Zoom, Fullscreen, 페이지 위치 Navigator |
| 시각 이식 | 부분 완료 | V2 전용 DOM·CSS와 블록 chrome을 목업 방향으로 정돈. 픽셀 단위 브라우저 검수는 미완료 |
| 프론트 생산성 | 미완료 | Fit Page/Width, 크기 통일, 정렬·분배, 자동 정돈, 템플릿 썸네일 |
| 백엔드 확장 | 미착수 | 실제 페이지, 영구 템플릿·댓글·스냅샷, 차트/PDF parity, typed view spec |

현재 선택·잠금·검색·Zoom·스냅샷·클립보드 상태는 의도적으로 프론트 세션에만 있다. 이 상태를
API나 DB에 저장하지 않는다.

## `seung`에서 먼저 확인할 프론트 코드

### 화면 조립과 데이터 흐름

```text
app/frontend/src/pages/ReportsPage.jsx
app/frontend/src/features/reports/useReportsPageController.jsx
app/frontend/src/features/reports/useReportDraftState.ts
app/frontend/src/features/reports/useReportDragAndDrop.js
app/frontend/src/features/reports/useReportEditorTools.js
```

다음 흐름을 추적한다.

```text
Library/Properties 입력
→ draft mutation
→ commitBlocks
→ 저장 payload 변환
→ reportClient
→ ReportBlockRequest
```

### Builder V2 화면

```text
app/frontend/src/features/reports/v2/ReportBuilderV2.jsx
app/frontend/src/features/reports/v2/report-builder-v2.css
app/frontend/src/features/reports/components/ReportPropertiesPanel.jsx
app/frontend/src/features/reports/components/ReportToolPanel.jsx
app/frontend/src/features/reports/components/ReportEditorBlock.jsx
app/frontend/src/features/reports/components/ReportEditorCanvas.jsx
app/frontend/src/features/reports/components/ReportBlockControls.jsx
app/frontend/src/features/reports/components/reportPresentation.js
```

Properties에 보이지만 영속되지 않는 설정, 현재 `content` JSON에 저장되는 설정, Artifact에서
직접 읽는 설정을 구분한다.

### 현재 계약과 payload

```text
app/frontend/src/features/reports/reportDraftMutations.ts
app/frontend/src/features/reports/reportDraftOperations.js
app/frontend/src/features/reports/reportDocumentTypes.ts
app/frontend/src/features/reports/reportDocumentLayout.ts
app/frontend/src/api/reportClient.ts
```

`text.content`는 Markdown 본문이고 chart/table/artifact의 `content`는 표시 설정 JSON도 겸한다.
새 설정을 이 문자열에 계속 추가하지 않는다.

### 임시 검토 모드

```text
app/frontend/src/features/reports/reportBuilderFlags.js
app/frontend/src/features/reports/reportReviewMode.js
```

`VITE_REPORT_REVIEW_MODE=true`는 LAN 검토용 mock 진입 경로일 뿐 운영 인증이나 실제 Artifact
연동의 완료 증거가 아니다. 기본값은 계속 꺼 둔다.

## 확인할 백엔드 코드

```text
app/backend/app/report_contracts.py
app/backend/app/api/report_router.py
app/backend/app/api/report_router_support.py
app/backend/app/adapters/report_definition_repository.py
app/backend/app/adapters/report_repository.py
app/backend/app/services/report_document.py
app/backend/app/services/report_document_chart.py
app/backend/app/services/report_document_layout.py
app/backend/app/services/report_document_types.py
app/backend/migrations/versions/20260804_05_report_v11_registration.py
app/backend/migrations/versions/20260814_20_report_replay_lineage.py
app/backend/migrations/versions/20260814_21_report_documents.py
app/backend/migrations/versions/20260814_22_report_artifact_blocks.py
app/backend/migrations/versions/20260814_23_report_display_settings.py
```

확인할 불변식:

- `ReportBlockRequest`는 `extra="forbid"`다.
- 블록은 12열 정수 좌표 `x`, `y`, `w`, `h`를 사용한다.
- `table`, `chart`, `artifact`는 Artifact와 분석 정의 lineage가 필요하다.
- 승인 version과 확정 document는 불변이다.
- HTML/PDF는 같은 승인 source와 checksum에서 생성된다.
- 현재 orientation은 definition version 전체에 하나만 저장된다.
- 현재 페이지는 엔티티가 아니라 전역 `y` 좌표에서 파생된다.

## 확인할 UX 목업 코드

목업 위치:

```text
C:/Users/Playdata/Documents/파이널 프젝젝젝/answervice-report-prototype
```

반드시 확인할 파일:

```text
src/report/ReportBuilder.jsx
src/report/layout.js
src/report/theme.js
src/data/mockReportData.js
src/styles/report.css
README.md
HANDOFF_TO_DAESUNG.md
```

`ReportBuilder.jsx`에서 다음 UX의 입력·상태·결과를 확인한다.

- 페이지 추가·삭제·복제·순서 변경
- 페이지별 portrait/landscape
- 8방향 Resize
- 멀티 선택과 크기 맞춤
- 자동 정돈
- 사용자 템플릿 저장·적용·삭제
- 블록 댓글
- 이름 붙인 스냅샷
- KPI·Goal·Chart·Table·Summary 표현
- 차트별 Properties와 데이터 Label
- 서체·글자 크기·색상
- 프레젠테이션과 출력 흐름

목업에서 가져오지 않을 것:

- 8열 픽셀 좌표계
- `Date.now()` 기반 ID
- mock Artifact·Evidence
- 독립 `pages` 로컬 state를 실서비스 저장 모델처럼 사용하는 방식
- DOM clone HTML
- `window.print()` PDF
- 외부 URL을 직접 넣는 이미지

## 현재 백엔드 때문에 완료하지 못한 부분

| 목업 기능 | 현재 상태 | 필요한 백엔드 변경 |
|---|---|---|
| 페이지 CRUD | 페이지가 `y`에서 파생되어 저장 불가 | `report_pages`, block `page_id`, pages+blocks 원자 저장 |
| 페이지별 방향 | 보고서 전체 방향만 저장 | page별 orientation과 named `@page` PDF 렌더링 |
| 사용자 템플릿 | 프론트 기본 템플릿만 존재 | template/version 저장소와 Artifact slot 계약 |
| 댓글 | 저장소 없음 | block과 분리된 comment table/API/권한 |
| 영구 스냅샷 | 세션에서만 유지 | append-only draft snapshot과 restore API |
| 동시 편집 | 마지막 저장이 덮을 수 있음 | draft revision 또는 `If-Match` CAS |
| 상세 표현 속성 | 일부가 `content` JSON에 혼재 | block type별 versioned `view_spec` |
| KPI·Summary 모드 | Artifact 전체/차트/표 중심 | lineage를 유지하는 artifact `view_mode` |
| 추가 차트 | PDF renderer가 지원하지 않음 | typed capability, backend SVG, HTML/PDF test |
| Draft PDF | 승인 document 경로만 권위 있음 | canonical renderer를 재사용하는 draft preview API |

## 반드시 먼저 해결할 결함

현재 프론트는 7개 차트 이름을 제공하지만 PDF renderer는 일부를 다른 형태로 축약한다.

```text
area → line
horizontal-bar → bar
stacked-bar → bar
donut → bar
pie → bar
```

새 차트를 추가하기 전에 기존 7개 차트가 화면·HTML·PDF에서 같은 의미로 렌더되도록 고친다.
미지원 조합은 bar fallback으로 성공시키지 말고 typed render error로 닫는다.

## 백엔드 구현 순서

### B1. Typed View Spec

`report_blocks`에 versioned `view_spec`을 추가해 내용과 표현 설정을 분리한다.

```text
view_spec_version varchar(32)
view_spec jsonb
```

- text의 `content`는 Markdown으로 보존한다.
- 자유 JSON 대신 block type별 Pydantic 계약을 사용한다.
- legacy content 설정은 호환 기간 동안 읽고 검증된 값만 migration한다.
- source checksum에 정규화된 view spec을 포함한다.

### B2. 기존 차트 Canonical Parity

- Bar, Horizontal Bar, Line, Area, Stacked Bar, Donut, Pie를 실제 형태로 렌더한다.
- frontend capability, backend SVG, HTML, PDF가 같은 계약을 사용한다.
- 음수·0·빈 데이터·긴 Label·혼합 단위를 검증한다.

### B3. 실제 Page 모델

```text
report_pages:
definition_id, definition_version, page_id, page_order, name, orientation

report_blocks.page_id
```

- 기존 전역 `y`를 파생 page index와 page-local `y`로 migration한다.
- pages와 blocks를 한 transaction에서 저장한다.
- page ID/order/orientation을 checksum에 포함한다.
- 실제 WeasyPrint에서 portrait/landscape 혼합 순서를 검증한다.

### B4. Artifact View Mode

새 KPI 블록에 mock 숫자를 저장하지 말고 artifact 블록의 typed view mode로 구현한다.

```text
full | kpi | chart | table | summary
```

모든 mode에서 `artifact_id`, `query_id`, analysis definition, checksum, Evidence를 유지한다.

### B5. 영구 Template

템플릿에는 실제 Artifact ID를 복사하지 않는다. layout과 `slot_kind`, 허용 view mode, 필요한
schema를 versioned template로 저장하고 적용 시 현재 Artifact를 검증해 lineage를 연결한다.

### B6. 댓글·Snapshot·동시 저장

- 댓글은 block content와 승인 checksum에서 분리한다.
- Snapshot은 검증된 canonical draft를 append-only로 저장한다.
- Draft revision 불일치는 409로 거부한다.

### B7. 추가 차트와 Draft 출력

기존 7종 parity 완료 후 Scatter, Radar, Radial Bar, Composed, Treemap, Funnel을 하나씩 추가한다.
각 차트는 frontend renderer와 backend SVG/HTML/PDF test를 한 변경 단위로 완료한다.

Draft 출력은 DOM clone이나 `window.print()`가 아니라 기존 canonical renderer를 재사용하는
인증된 preview API로 구현한다. Preview 결과를 승인 document로 저장하지 않는다.

## 구현 원칙

1. 한 번에 모두 구현하지 않고 B 단계 하나씩 작은 커밋으로 완료한다.
2. 첫 작업은 B1 계약과 migration이며 검증 전 B2 이후를 구현하지 않는다.
3. 기존 migration을 수정하지 않는다.
4. UI-only 상태를 API나 DB에 추가하지 않는다.
5. Artifact lineage, owner scope, 승인 불변성을 회귀 테스트한다.
6. 화면에만 구현하고 저장·PDF가 된다고 보고하지 않는다.
7. Mock Artifact를 실제 연동 증거로 사용하지 않는다.
8. 실제 PDF를 만들지 않았다면 PDF 검증 완료라고 말하지 않는다.

## 기본 검증

```powershell
cd C:/Users/Playdata/Downloads/skn29_final_3team/app/frontend
npm.cmd run build

cd C:/Users/Playdata/Downloads/skn29_final_3team
npm.cmd --prefix app/frontend run test
python app/backend/scripts/export_openapi.py --check
python scripts/check_code_documentation.py
python scripts/lint_architectural_invariants.py
python scripts/audit_repository_integrity.py
```

환경이나 dependency가 없어 실행하지 못한 검증은 통과로 기록하지 않는다.

## 백엔드 개발자에게 요청하는 첫 회신

코드를 읽은 뒤 바로 구현하기 전에 아래 형식으로 짧게 회신해 주세요.

```text
1. seung 프론트 확인 완료 여부:
2. 목업 코드 확인 완료 여부:
3. 현재 API에 이미 연결된 기능:
4. 프론트에만 있고 저장되지 않는 기능:
5. HTML/PDF에서 의미가 달라지는 기능:
6. 첫 구현 대상으로 선택한 B 단계:
7. 예상 변경 파일과 migration:
8. Artifact lineage와 기존 보고서 호환 방법:
9. 사용자 확인이 필요한 결정:
```

첫 회신에서 확인하지 않은 기능을 완료됐다고 표현하지 말고, 코드로 확인한 사실과 제안 사항을
구분해 주세요.
