# Report Builder V2 프론트엔드 고도화 인계서

## 목적

`seung` 브랜치에 구현된 Report Builder V2를 UX 목업과 비교해 남은 프론트 편집 기능과
시각적 완성도를 높인다. 현재 기능을 다시 만들지 말고 기존 controller, draft, 12열 Grid,
Artifact API를 재사용한다.

백엔드 저장 계약이 필요한 페이지 CRUD·영구 템플릿·댓글·추가 차트는 가짜 UI로 만들지 않고
`BACKEND_DEVELOPER_HANDOFF.md`의 백엔드 작업 이후 연결한다.

## 작업 위치

```text
저장소: C:/Users/Playdata/Downloads/skn29_final_3team
작업 브랜치: seung
현재 V2 기준 커밋: 26fd3d9
현재 인계 문서 기준 커밋: f947a7a
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
- 기존 SQL·ZIP·인프라 파일과 stash를 건드리지 않는다.
- 사용자 요청 없이 PR이나 자동 merge를 만들지 않는다.

## 최종 목표

실서비스 Report Builder가 목업과 유사한 밀도와 사용감을 가지면서 다음 흐름을 제공해야 한다.

```text
Library에서 Artifact 또는 Block 선택
→ 흰색 A4에 추가
→ 이동·Resize·Grid Snap
→ 여러 블록 선택
→ 크기 통일·정렬·분배·자동 정돈
→ Properties 수정
→ 세로·가로 A4와 Zoom 확인
→ Preview에서 편집 UI 제거
```

저장 모델은 목업이 아니라 실서비스 12열 좌표와 기존 API를 사용한다.

## 현재까지 구현된 기능

- Builder V2 전용 3단 DOM: Library / A4 Workspace / Properties
- V2 루트 아래로 격리된 CSS
- 흰색 A4와 세로·가로 비율
- Artifact·Text·Chart·Table 추가
- Drag & Drop, Resize, Grid Snap
- Shift+클릭 멀티 선택
- 블록 잠금·일괄 잠금·일괄 삭제
- 정렬 가이드
- 제목·Text 검색과 결과 포커스
- 세션 스냅샷
- 복사·붙여넣기와 Artifact lineage 보존
- 8단계 크기
- Zoom 70/85/100
- Builder 전체화면
- 파생 페이지 Navigator
- 오른쪽 Properties
- 기존 Preview·저장·Undo/Redo·방향 전환 연결

## 먼저 확인할 실서비스 프론트 코드

### 화면과 상태 배선

```text
app/frontend/src/pages/ReportsPage.jsx
app/frontend/src/features/reports/useReportsPageController.jsx
app/frontend/src/features/reports/useReportDraftState.ts
app/frontend/src/features/reports/useReportDragAndDrop.js
app/frontend/src/features/reports/useReportEditorTools.js
```

### V2 화면과 스타일

```text
app/frontend/src/features/reports/v2/ReportBuilderV2.jsx
app/frontend/src/features/reports/v2/report-builder-v2.css
app/frontend/src/features/reports/components/ReportPropertiesPanel.jsx
app/frontend/src/features/reports/components/ReportToolPanel.jsx
app/frontend/src/features/reports/components/ReportEditorToolbar.jsx
app/frontend/src/features/reports/components/ReportEditorCanvas.jsx
app/frontend/src/features/reports/components/ReportEditorBlock.jsx
app/frontend/src/features/reports/components/ReportBlockControls.jsx
app/frontend/src/features/reports/components/reportPresentation.js
```

### 배치와 문서 계약

```text
app/frontend/src/features/reports/reportDraftOperations.js
app/frontend/src/features/reports/reportDraftMutations.ts
app/frontend/src/features/reports/reportDocumentLayout.ts
app/frontend/src/features/reports/reportDocumentValidation.ts
app/frontend/src/features/reports/reportArtifactLayout.js
app/frontend/src/contracts/report.ts
```

새 배치 알고리즘을 만들기 전에 `placeDraftBlock`, `compactDraftLayout`, page layout helper처럼 이미
있는 함수를 찾고 재사용한다.

## 확인할 UX 목업 코드

목업 위치:

```text
C:/Users/Playdata/Documents/파이널 프젝젝젝/answervice-report-prototype
```

```text
src/report/ReportBuilder.jsx
src/report/layout.js
src/report/theme.js
src/data/mockReportData.js
src/styles/report.css
README.md
HANDOFF_TO_DAESUNG.md
```

비교할 항목:

- Toolbar 높이와 정보 계층
- Library 카드 크기·간격·분류
- Workspace 여백과 A4 중앙 정렬
- Properties 폭·섹션 순서·입력 밀도
- 선택·잠금·Resize Handle·Drop Preview 상태
- Fit Zoom과 전체화면
- 멀티 선택 후 크기 통일·정렬·분배
- 자동 정돈
- Template thumbnail
- 8방향 Resize
- Marquee selection과 group drag
- Preview 전환

가져오지 않을 것:

- 목업의 8열 픽셀 좌표계
- mock Artifact·Evidence
- `Date.now()` ID
- 목업의 독립 pages state
- DOM clone HTML과 `window.print()` PDF
- 가짜 페이지 CRUD·영구 저장 UI

## 남은 프론트 작업 순서

### F1. Fit Page / Fit Width Zoom

현재 고정 Zoom 70/85/100에 다음 선택지를 추가한다.

```text
페이지 맞춤
너비 맞춤
70%
85%
100%
```

- `ResizeObserver`로 Workspace와 현재 A4 크기를 측정한다.
- Zoom은 로컬 상태로 유지하고 payload에 넣지 않는다.
- 세로형·가로형과 Library/Properties 접힘 상태 변경 시 다시 계산한다.
- A4가 패널 아래로 숨지 않고 Workspace 상단 중앙에 위치해야 한다.

### F2. 멀티 선택 정렬 도구

선택된 잠기지 않은 블록에 다음 작업을 제공한다.

- 너비 통일
- 높이 통일
- 왼쪽·가운데·오른쪽 정렬
- 위·가운데·아래 정렬
- 가로·세로 간격 균등 분배

규칙:

- 한 작업은 한 번의 `commitBlocks`로 처리해 Undo 한 번으로 복원한다.
- 잠긴 블록은 기준으로 사용할 수 있지만 수정하지 않는다.
- 블록 ID와 Artifact lineage 필드를 재생성하지 않는다.
- 페이지 경계와 다른 블록 충돌은 기존 helper로 검증한다.

### F3. 자동 정돈

- 목업의 `packPageBlocks`를 복사하지 않는다.
- 기존 실서비스의 12열 배치·compact helper를 재사용한다.
- 읽는 순서 `(page, y, x)`를 유지한다.
- 잠긴 블록은 이동하지 않는다.
- A4 여백과 page row 경계를 지킨다.
- 전체 결과를 한 번의 `commitBlocks`로 반영한다.
- 안전한 빈 위치를 찾지 못하면 일부 성공으로 조용히 처리하지 말고 안내한다.

### F4. Visual Parity

1440×900을 우선 기준으로 목업과 코드 수준에서 비교한다.

- Header와 Workspace Toolbar의 중복 정보 제거
- Library 240~260px, Properties 258~300px 범위 유지
- 1440px 이상에서 3단 구조 고정
- 1180~1439px에서 폭 축소와 Workspace 가로 스크롤
- 1180px 미만에서 Library/Properties Drawer
- A4 상단 중앙 정렬과 페이지 간 40~56px 간격
- 선택되지 않은 블록 chrome 최소화
- hover·선택·잠금 상태를 명확히 구분
- 버튼·Input 높이, Border, Radius, Typography 통일

V2 스타일은 `[data-report-builder="v2"]` 아래에만 추가한다. 전역 `button`, `input`,
`.notion-report-editor`를 다시 덮어쓰지 않고 HTML/PDF 출력 CSS도 수정하지 않는다.

### F5. Template Thumbnail과 Properties 정리

- 현재 template block 배열을 CSS 미니맵으로 축소 표시한다.
- 실제 Chart를 thumbnail 안에서 다시 렌더링하지 않는다.
- Properties를 기본 / 크기·위치 / 차트 / Evidence / 세션 도구로 정리한다.
- 선택 없음, 단일 선택, 멀티 선택 상태를 각각 분명히 표시한다.
- 사용자 템플릿 저장 버튼은 백엔드 API가 생기기 전까지 만들지 않는다.

### F6. 고급 Pointer UX

F1~F5 완료 후 별도 작업으로 검토한다.

- 8방향 Resize Handle
- 빈 영역 Drag Marquee Selection
- 선택 블록 Group Drag

이 기능은 `x/y/w/h`, 충돌, page 경계를 동시에 바꾸므로 각 기능을 독립 커밋으로 구현한다.
기존 단일 Drag/Resize 회귀 테스트 없이 한 번에 추가하지 않는다.

## 백엔드 작업 전까지 만들지 않을 UI

- 페이지 추가·삭제·복제·순서 변경
- 페이지별 orientation 저장
- 사용자 템플릿 영구 저장
- 댓글 영구 저장
- 영구 버전 스냅샷
- Scatter·Radar·Treemap 등 PDF 미지원 차트
- DOM clone HTML 다운로드
- `window.print()` PDF
- 원본 값을 직접 수정하는 KPI

해당 기능은 다음 문서의 백엔드 계약 구현 후 연결한다.

```text
docs/report_builder/BACKEND_DEVELOPER_HANDOFF.md
docs/report_builder/BACKEND_EVOLUTION_ROADMAP.md
```

## 반드시 지킬 불변식

1. `text.content`는 Markdown 본문이므로 `setBlockSetting`으로 덮어쓰지 않는다.
2. `selected`, `locked`, `zoom`, `guides`, `snapshots`, `clipboard`를 API payload에 넣지 않는다.
3. 복사·이동·Resize 후 `artifactId`, `queryId`, Source/Evidence를 유지한다.
4. 새 ID는 기존 `createUuid`를 사용한다.
5. 12열 Grid와 기존 page row 계산을 유지한다.
6. Preview에서 Library, Properties, Grid, Handle, 선택 표시, Guide를 숨긴다.
7. 새 라이브러리를 설치하기 전에 React, dnd-kit, Recharts, Lucide와 기존 helper를 재사용한다.

## 테스트

기존 테스트와 함께 최소 다음 회귀를 추가한다.

- Fit Page/Fit Width 계산
- portrait/landscape Zoom 재계산
- 잠긴 블록 일괄 작업 제외
- 너비·높이 통일 Undo
- 정렬·분배 후 충돌 방지
- 자동 정돈 후 읽는 순서 유지
- Artifact lineage 유지
- text Markdown 보존
- 1440px 3단 CSS
- 작은 화면 Drawer CSS
- Preview 편집 chrome 제거

```powershell
cd C:/Users/Playdata/Downloads/skn29_final_3team/app/frontend
npm.cmd run build

cd C:/Users/Playdata/Downloads/skn29_final_3team
npm.cmd --prefix app/frontend run test
python scripts/check_code_documentation.py
python scripts/lint_architectural_invariants.py
git diff --check
```

기존 `analysis-dashboard.test.mjs`, `contracts.test.mjs` 실패와 새 회귀를 구분한다. 실제 브라우저를
확인하지 않았으면 시각 검증 완료라고 보고하지 않는다.

## 프론트 개발자에게 요청하는 첫 회신

코드와 목업을 읽은 뒤 구현 전에 아래 형식으로 짧게 회신해 주세요.

```text
1. seung V2 코드 확인 완료 여부:
2. 목업 코드 확인 완료 여부:
3. 이미 구현되어 재사용할 기능:
4. 목업과 가장 크게 다른 화면 요소:
5. 첫 구현 대상으로 선택한 F 단계:
6. 예상 변경 파일:
7. 기존 Drag/저장/lineage 회귀 방지 방법:
8. 브라우저 비교 가능 여부:
9. 사용자 확인이 필요한 디자인 결정:
```

확인하지 않은 기능은 완료됐다고 표현하지 말고, 코드에서 확인한 사실과 제안을 구분해 주세요.
