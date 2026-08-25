# Report Builder V2 작업 현황

이 문서는 `seung` 브랜치의 Report Builder V2 구현 상태와 다음 작업 경계를 설명한다.
UX 기준 목업은 저장소 밖의
`C:/Users/Playdata/Documents/파이널 프젝젝젝/answervice-report-prototype`이며,
목업의 8열 픽셀 좌표계와 mock 데이터는 실서비스에 복사하지 않는다.

백엔드·DB 변경이 필요한 후속 설계는
[`BACKEND_EVOLUTION_ROADMAP.md`](BACKEND_EVOLUTION_ROADMAP.md)를 따른다.

## 1. 권위 있는 실서비스 계약

- 편집 좌표는 `x`, `y`, `w`, `h`를 사용하는 12열 정수 격자다.
- 보고서 방향은 현재 definition version 전체에 적용되는 `portrait` 또는 `landscape`다.
- 저장 가능한 블록은 `table`, `chart`, `artifact`, `text`다.
- `table`, `chart`, `artifact`는 실제 Artifact와 분석 정의 lineage를 요구한다.
- `text.content`는 실제 Markdown 본문이다.
- `chart`, `table`, `artifact`의 `content`는 현재 표시 설정 JSON도 겸한다.
- 승인 HTML/PDF는 백엔드 canonical renderer와 WeasyPrint가 생성한다.
- `ReportBlockRequest`는 `extra="forbid"`이므로 편집 UI 상태를 payload에 넣을 수 없다.

선택, 잠금, 검색, 스냅샷, 클립보드, Zoom, 정렬 가이드는 프론트 세션 상태이며
서버 저장과 승인 문서 checksum에 포함되지 않는다.

## 2. 구현 단계

| 단계 | 상태 | 구현 내용 |
|---|---|---|
| 0. 실서비스 기반 | 기존 완료 | 12열 Grid, Artifact API, lineage, draft 저장, Undo/Redo, HTML/PDF, 전체 방향 전환 |
| 1. 편집 편의 | 완료 | Shift 멀티 선택, 잠금, 일괄 잠금·삭제, 정렬 가이드, 검색, 세션 스냅샷, 복사·붙여넣기, 8단계 크기 |
| 2. Builder V2 셸 | 완료 | feature flag, 3단 Library/Workspace/Properties, A4 workspace, Zoom, fullscreen, 파생 페이지 navigator |
| 3. 목업 시각 이식 | 부분 완료 | V2 전용 CSS 격리, 패널·A4·블록 chrome 정돈. 브라우저 픽셀 단위 시각 검수는 완료 증거가 아님 |
| 4. 프론트 생산성 | 미완료 | Fit Page/Fit Width, 선택 크기 통일, 정렬·분배, 자동 정돈, 템플릿 썸네일 |
| 5. 백엔드 확장 | 미착수 | 페이지 엔티티, 영구 템플릿·댓글·스냅샷, typed view spec, 차트/PDF 의미 일치 |

## 3. 현재 V2 구성

- `app/frontend/src/features/reports/v2/ReportBuilderV2.jsx`
  - 기존 controller 상태를 새 화면 계층에 배선하는 adapter다.
- `app/frontend/src/features/reports/v2/report-builder-v2.css`
  - `[data-report-builder="v2"]` 아래로 격리된 편집 화면 전용 스타일이다.
- `app/frontend/src/features/reports/useReportEditorTools.js`
  - 서버 payload와 분리된 선택·잠금·검색·스냅샷·클립보드·Zoom 상태를 소유한다.
- `app/frontend/src/features/reports/components/ReportPropertiesPanel.jsx`
  - 주 선택 블록의 제목·위치·크기·차트·Evidence·일괄 작업을 제공한다.
- `app/frontend/src/features/reports/reportBuilderFlags.js`
  - `VITE_REPORT_BUILDER_V2=true`에서만 V2 화면을 사용한다.
- `app/frontend/src/features/reports/reportReviewMode.js`
  - `VITE_REPORT_REVIEW_MODE=true`인 LAN 검토 빌드에만 임시 세션과 review data를 제공한다.

Review Mode는 운영 인증의 대체물이 아니다. 기본값은 꺼져 있으며 운영 빌드나 일반 병합에서
환경 변수를 활성화하면 안 된다.

## 4. 아직 프론트만으로 가능한 작업

다음은 백엔드 계약을 바꾸지 않고 기존 12열 helper와 `commitBlocks`를 재사용해 구현할 수 있다.

1. Workspace 크기를 관찰하는 Fit Page/Fit Width Zoom
2. 멀티 선택 블록의 너비·높이 통일
3. 왼쪽·가운데·오른쪽 및 위·가운데·아래 정렬과 간격 분배
4. 잠긴 블록을 제외한 현재 페이지 자동 정돈
5. 현재 template block 배열을 축소 표시하는 템플릿 썸네일

8방향 resize, marquee selection, 여러 블록 동시 drag는 프론트 작업이지만 충돌 처리와
페이지 경계를 함께 바꾸므로 위 항목보다 뒤에 둔다.

## 5. 목업과 의도적으로 다른 부분

- 목업의 페이지 배열은 독립 로컬 state지만 실서비스 페이지는 현재 블록 `y`에서 파생한다.
- 목업의 HTML clone과 `window.print()`는 사용하지 않는다.
- 목업의 mock KPI·차트·Evidence는 가져오지 않는다.
- 목업의 페이지별 방향, 페이지 CRUD, 댓글, 사용자 템플릿은 저장되는 것처럼 가장하지 않는다.
- 목업의 폰트·블록 스타일과 추가 차트는 canonical HTML/PDF와 계약이 생기기 전까지 노출하지 않는다.

## 6. 다음 작업자가 지킬 불변식

1. `daesung`은 비교용이며 구현은 `seung`에서 한다.
2. UI-only 상태를 `draft.blocks`, API payload, DB column에 임의로 넣지 않는다.
3. `text` 블록에 `setBlockSetting`을 사용해 Markdown 본문을 덮어쓰지 않는다.
4. Artifact 이동·resize·복사 시 `artifactId`, `queryId`, source/evidence lineage를 보존한다.
5. 새 차트는 frontend Recharts만 추가하지 않고 HTML/PDF renderer까지 같은 의미로 구현한다.
6. 기존 migration은 수정하지 않고 새 revision을 추가한다.
7. 기능 하나를 작은 diff와 독립 테스트로 완성한 뒤 다음 기능으로 간다.

## 7. 검증 진입점

```powershell
cd C:/Users/Playdata/Downloads/skn29_final_3team/app/frontend
npm.cmd run build

cd C:/Users/Playdata/Downloads/skn29_final_3team
npm.cmd --prefix app/frontend run test
```

보고서 전용 회귀는 `tests/frontend/report-*.test.mjs`와
`tests/frontend/report-builder-v2.test.mjs`를 우선 확인한다. 실제 브라우저와 PDF를 실행하지
않았으면 각각 시각 검증 또는 PDF 검증 완료로 기록하지 않는다.
