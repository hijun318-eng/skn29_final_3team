# Answervice Report Builder 목업 전체 기능 명세서

## 1. 문서 목적

이 문서는 독립 UX 목업인 `answervice-report-prototype`의 실제 구현을 코드 기준으로 설명한다.
백엔드 또는 프론트 작업 에이전트가 목업에서 검증한 사용 경험을 실서비스 `seung` 브랜치에
옮길 때 기능을 빠뜨리거나, mock 동작을 운영 계약으로 오해하지 않도록 하는 것이 목적이다.

문서에 없는 기능을 목업이 지원한다고 추정하지 않는다. 코드와 기존 README/Handoff 내용이
다를 때는 현재 `ReportBuilder.jsx`와 관련 모듈의 동작을 기준으로 작성했다.

이 문서는 **외부 목업 폴더에 접근할 수 없는 에이전트도 사용할 수 있는 자급형 명세서**다.
기능 설명뿐 아니라 핵심 상태, 데이터 구조, 배치 알고리즘, Drag/Resize/History/Page/Template,
Chart registry와 디자인 토큰의 구현 예시를 뒤쪽 부록에 포함한다. 로컬 경로는 원본 추적용이며
이 문서를 이해하기 위한 필수 조건이 아니다.

## 2. 코드 위치와 실행 주소

목업 프로젝트:

```text
C:/Users/Playdata/Documents/파이널 프젝젝젝/answervice-report-prototype
```

현재 LAN 검토 주소:

```text
http://192.168.0.37:4174/
```

실행:

```powershell
cd "C:/Users/Playdata/Documents/파이널 프젝젝젝/answervice-report-prototype"
npm.cmd install
npm.cmd run dev -- --port 4174 --strictPort
```

주요 파일:

```text
src/report/ReportBuilder.jsx       전체 화면, 상태, 편집 동작
src/report/layout.js               8열 Grid와 자동 배치
src/report/theme.js                색상, 서체, 글자 크기 단계
src/data/mockReportData.js         호텔 Mock 데이터와 11종 차트 목록
src/styles/report.css              편집기·A4·Print 스타일
src/report/prototype.test.mjs      데이터와 배치 최소 계약 테스트
README.md                          간단 실행 안내
HANDOFF_TO_DAESUNG.md              초기 이식 참고 문서
```

## 3. 제품 성격과 비범위

### 제품 성격

- 백엔드와 인증이 없는 독립 React UX 목업이다.
- 모든 데이터는 브라우저 메모리의 Mock 데이터다.
- 새로고침하면 편집 내용, 템플릿, 댓글, 스냅샷이 사라진다.
- 실제 Artifact API, DB 저장, 권한, 승인, checksum을 사용하지 않는다.
- 목업의 목적은 보고서 편집 흐름과 화면 밀도를 체험하는 것이다.

### 그대로 이식하면 안 되는 부분

- 8열 픽셀 좌표계
- `Date.now()`와 난수 기반 ID
- 사용자가 직접 수정할 수 있는 Mock KPI 숫자
- 가짜 Source/Evidence
- 외부 URL 또는 Base64 이미지의 무검증 저장
- 브라우저 DOM clone HTML
- `window.print()` PDF
- 컴포넌트 하나가 전체 상태를 소유하는 구조
- 브라우저 메모리에만 존재하는 pages/templates/comments/snapshots

## 4. 기술 구성

```text
React 19
Vite 8
dnd-kit/core
Recharts
Lucide React
CSS
```

외부 상태관리 라이브러리는 없다. `ReportBuilder`가 모든 편집 상태를 `useState`로 소유한다.

## 5. 전체 화면 구조

편집 상태의 화면은 다음 구조다.

```text
┌──────────────┬─────────────────────────────────────────────────────┐
│ Brand        │ Report Builder Topbar                               │
│ Sidebar      ├────────────┬──────────────────────────┬─────────────┤
│              │ Library    │ Workspace                │ Properties  │
│ 데이터 분석  │ 검색       │ Workspace Toolbar        │ 페이지/블록 │
│ 보고서       │ 템플릿     │ 흰색 A4                  │ 속성        │
│              │ 콘텐츠     │                          │ 댓글        │
│ 사용자       │ 차트 11종  │                          │ Evidence    │
│              │ 분석 결과  │                          │ 복제/삭제   │
│              │ 페이지     │                          │             │
└──────────────┴────────────┴──────────────────────────┴─────────────┘
```

### 기본 치수

| 영역 | 기본값 |
|---|---|
| Brand Sidebar | 224px, fixed |
| Topbar | 104px, sticky |
| Library | 244px |
| Workspace | 최소 620px, 나머지 폭 사용 |
| Properties | 258px |
| 페이지 간격 | 아래 50px |
| Workspace 점 Grid | 18px 간격 |
| 최소 Body 폭 | 1180px |

1360px 이하에서는 Library 220px, Workspace 최소 570px, Properties 235px로 축소한다.
모바일 Drawer 편집은 구현되어 있지 않다.

## 6. A4와 Grid 계약

### A4 화면 크기

```text
portrait:  794 × 1123px
landscape: 1123 × 794px
```

Print CSS에서는 다음 물리 크기를 사용한다.

```text
portrait:  210 × 297mm
landscape: 297 × 210mm
```

### Grid 상수

```text
열 수: 8
페이지 여백: 40px
블록 가로 Gap 보정: 16px
행 간격: 20px
세로 Snap: 24px
최소 블록 높이: 72px
```

### 중요한 배치 특성

목업은 완전한 자유 좌표 Canvas가 아니다.

사용자가 Drag 중에는 블록 하나의 `x`, `y`를 임시로 자유롭게 바꾸지만 Pointer를 놓는 순간
`packPageBlocks`가 전체 페이지를 다시 정렬한다.

최종 위치 규칙:

1. 블록을 `y`, 그다음 `x` 순서로 정렬한다.
2. 각 블록의 현재 픽셀 너비를 1~8열 span으로 변환한다.
3. 한 행에 왼쪽부터 배치한다.
4. 다음 블록까지 합쳐 8열을 넘으면 새 행으로 넘긴다.
5. 같은 행의 모든 블록 높이를 그 행에서 가장 높은 블록 높이로 맞춘다.
6. 행 사이에 20px 간격을 둔다.
7. 최종 `x`, `y`는 자동 배치 결과로 다시 계산한다.

따라서 다음이 보장된다.

- 최종 블록은 서로 겹치지 않는다.
- 같은 행 블록은 같은 높이를 갖는다.
- 좌우 위치는 열 span과 정렬 순서에서 파생된다.
- 사용자가 원하는 임의의 빈 공간을 최종 상태로 유지하기 어렵다.

### 자동 배치 버튼

일반 배치와 달리 마지막 행의 남는 열을 채운다.

예를 들어 2열 KPI 세 개가 한 행에 있어 6/8열만 차지하면 마지막 KPI의 너비를 2열 늘려
행 전체를 채운다. 다른 블록은 늘리지 않는다.

## 7. 핵심 상태 모델

| 상태 | 의미 | 지속 범위 |
|---|---|---|
| `pages` | 전체 페이지와 블록 | 브라우저 메모리 |
| `pageId` | 현재 편집 페이지 | 브라우저 메모리 |
| `selectedId` | Properties가 수정하는 주 선택 블록 | 브라우저 메모리 |
| `multiSelectedIds` | Shift로 추가한 보조 선택 집합 | 브라우저 메모리 |
| `preview` | 편집/Preview 전환 | 브라우저 메모리 |
| `zoom` | 55/72/90/100% | 브라우저 메모리 |
| `fontId` | 전체 보고서 서체 | 브라우저 메모리 |
| `history` | Undo/Redo용 pages snapshot | 최대 40단계 |
| `clipboard` | 복사한 블록 하나 | 브라우저 메모리 |
| `templates` | 기본+사용자 템플릿 | 브라우저 메모리 |
| `snapshots` | 이름 붙인 전체 pages snapshot | 최대 20개 |
| `searchQuery` | 블록 검색어 | 브라우저 메모리 |
| `presenting` | 전체화면 프레젠테이션 | 브라우저 메모리 |
| `overflowNotice` | 페이지 초과 안내 | 4.5초 |

### 페이지 데이터

```text
id
name
orientation: portrait | landscape
blocks[]
```

### 공통 블록 데이터

```text
id
kind
title
x
y
width
height
locked?
comments?
```

블록 종류에 따라 value, delta, chartType, series, text, rows 등 추가 필드가 붙는다.

## 8. 초기 보고서

초기화 시 세 페이지를 만든다.

### 1페이지: 표지

- 방향: 세로
- Cover 블록
- Executive Intelligence Report Text 블록

### 2페이지: 경영 요약

- 방향: 가로
- 제목
- 총 매출, 객실 매출, OCC, ADR KPI
- 최근 12개월 Area Chart
- 사업부별 Donut Chart
- AI 경영 요약

### 3페이지: 상세 실적

- 방향: 세로
- 제목
- 사업부 매출·영업이익률 Chart
- 상세 실적 Table
- 의사결정 Insight

초기 선택 페이지는 `경영 요약`, 초기 선택 블록은 `최근 12개월 매출 추이`다.

## 9. Topbar 기능

### 보고서 제목

- 기본값: `2026년 8월 월간 경영 보고서`
- uncontrolled input이다.
- pages 상태나 Snapshot에 포함되지 않는다.
- HTML 내보내기는 A4 페이지 DOM만 복제하므로 Topbar 제목 자체는 출력되지 않는다.
- 보고서 안의 Heading 또는 Cover 제목과 자동 동기화되지 않는다.

### 서체

전체 Builder에 CSS 변수 `--report-font`로 적용한다.

```text
고딕: Inter, Noto Sans KR
명조: Noto Serif KR
둥근 고딕: Gowun Dodum
```

Google Fonts를 외부 `@import`한다. 완전한 offline self-contained font embedding은 아니다.

### Zoom

```text
55%
72% 기본
90%
100%
```

고정 선택만 있고 Fit Page/Fit Width 자동 계산은 편집 화면에 없다.

### 초기화

- `pages`를 초기 세 페이지로 되돌린다.
- Undo/Redo history를 비운다.
- pageId, 선택, Template, Snapshot, Clipboard, Font, Zoom은 모두 초기화하지 않는다.
- 현재 pageId가 초기 페이지에 없으면 렌더는 첫 페이지를 fallback으로 사용하지만 pageId 값은 남는다.

### Undo/Redo

- 전체 pages tree를 snapshot으로 보관한다.
- 최대 40개 past/future를 유지한다.
- Drag/Resize 중 매 Pointer move는 history에 넣지 않는다.
- Pointer release 후 전체 재배치를 한 번의 history 단계로 기록한다.
- 블록 추가·삭제·속성 변경·페이지 변경·댓글도 history 대상이다.
- 사용자 Template 목록과 이름 붙인 Snapshot 목록은 Undo 대상이 아니다.

### 이름 붙인 Snapshot

- 사용자가 `window.prompt`로 이름을 입력한다.
- 전체 pages 상태를 저장한다.
- 최신 항목이 위에 온다.
- 최대 20개다.
- Restore는 Undo 가능한 한 번의 pages 변경으로 처리한다.
- Snapshot 삭제 자체는 Undo되지 않는다.
- 새로고침하면 모두 사라진다.

### HTML

1. Preview를 강제로 켠다.
2. `.preview-pages` DOM을 복제한다.
3. Chrome과 Resize Handle을 제거한다.
4. 접근 가능한 document stylesheet의 CSS rule을 문자열로 합친다.
5. Blob을 만들어 `answervice-report.html`로 다운로드한다.
6. Download 후 Preview 상태를 자동으로 끄지 않는다.

실서비스에서 사용할 수 없는 이유:

- DOM이 canonical source가 된다.
- 브라우저·외부 폰트·현재 CSS에 따라 결과가 달라진다.
- 승인, checksum, Artifact version을 고정하지 않는다.

### PDF

1. Preview를 강제로 켠다.
2. `window.print()`를 실행한다.
3. 사용자가 브라우저 인쇄 대화상자에서 PDF 저장을 선택한다.
4. 이후 Preview 상태를 자동으로 끄지 않는다.

### 프레젠테이션

- Builder 외부에 검은 전체화면 Overlay를 표시한다.
- 지원 브라우저에서는 해당 영역에 Fullscreen API를 요청한다.
- 첫 페이지부터 시작한다.
- 화면 크기와 페이지 방향에 따라 0.2~1.4 범위 Zoom을 계산한다.
- 좌우 버튼, 방향키, PageUp/PageDown으로 페이지를 이동한다.
- Esc 또는 종료 버튼으로 닫는다.
- Browser Fullscreen이 외부 원인으로 종료되면 Presentation 상태도 종료한다.

### 단축키 도움말

- Modal로 조작 목록을 보여 준다.
- 배경 클릭, 닫기 버튼, Esc로 닫는다.

## 10. Library 구조

왼쪽 Library 순서:

1. 검색
2. 템플릿
3. 콘텐츠
4. 차트 갤러리
5. 분석 결과
6. 페이지

Library item은 클릭 추가와 Drag 추가를 모두 지원한다.

### Drag 시작

- dnd-kit PointerSensor를 사용한다.
- 포인터가 6px 이상 움직여야 Drag를 시작한다.
- Drag 중 작은 Overlay에 아이콘과 제목을 표시한다.

### A4 Drop

- Drop 대상은 현재 페이지 하나다.
- translated drag rect와 A4 bounding rect를 Zoom으로 역산한다.
- Drop 좌표를 열과 24px 세로 단계로 Snap한다.
- 이후 전체 페이지를 다시 pack하므로 Drop 좌표는 순서를 결정하는 힌트에 가깝다.

### 콘텐츠 Library

```text
KPI
목표 대비
데이터 테이블
이미지
텍스트
AI Summary
```

### 분석 결과 Library

```text
8월 전체 매출    → KPI
객실 월별 매출   → Line Chart
F&B 매출 분석    → Pie Chart
VIP 고객 분석    → Summary
```

모두 Mock이며 실제 Artifact ID, Query ID, Evidence가 없다.

## 11. 블록 추가 기본값

| 종류 | 기본 너비 | 기본 높이 |
|---|---:|---:|
| KPI | 2/8 | 120px |
| 목표 대비 | 3/8 | 120px |
| Chart | 4/8 | 288px |
| Table | 6/8 | 264px |
| Image | 4/8 | 220px |
| Text/Summary | 6/8 | 192px |

동적 Chart의 기본 데이터는 월별 총 매출이다.

추가 후 A4 높이를 초과하면 추가를 취소하고 4.5초 안내를 표시한다.

## 12. 블록 선택

### 일반 클릭

- 해당 블록을 주 선택으로 설정한다.
- 기존 보조 선택을 모두 해제한다.
- Properties는 주 선택 블록을 표시한다.

### Shift+클릭

- 클릭한 블록을 보조 선택 Set에 추가하거나 제거한다.
- 기존 주 선택 블록은 바뀌지 않는다.
- 최종 선택 집합은 `selectedId + multiSelectedIds`다.

### 빈 A4 클릭

- 주 선택과 보조 선택을 모두 해제한다.
- Properties는 페이지 설정을 표시한다.

## 13. 블록 이동

- 블록 상단 Chrome의 Move 버튼에서 Pointer 이동을 시작한다.
- 잠긴 블록은 이동할 수 없다.
- Zoom을 역산해 실제 페이지 좌표를 계산한다.
- x는 8열에 Snap한다.
- y는 24px에 Snap한다.
- 이동 중에는 해당 블록만 바꾸고 다른 블록은 움직이지 않는다.
- Pointer release 때 전체 페이지를 다시 pack한다.
- 최종 배치에서는 겹침이 제거된다.

## 14. 블록 Resize

선택 블록에 다음 8개 Handle을 표시한다.

```text
n, ne, e, se, s, sw, w, nw
```

- 잠긴 블록에서는 Handle을 숨긴다.
- 너비는 1/8~8/8열로 Snap한다.
- 높이는 24px 단위, 최소 72px로 Snap한다.
- Pointer release 때 전체 페이지를 다시 pack한다.
- 북쪽·서쪽 Handle도 현재 코드는 width/height만 바꾸고 x/y를 반대 방향으로 보정하지 않는다.
  따라서 일반 디자인 도구의 반대편 고정 Resize와 정확히 같지는 않다.
- 같은 행 블록은 release 후 행 최대 높이로 다시 맞춰질 수 있다.

### Alt+Wheel Resize

```text
Alt+Wheel       너비를 한 열씩 증감
Alt+Shift+Wheel 높이를 24px씩 증감
```

- native passive:false wheel listener를 사용해 Canvas Scroll을 막는다.
- 잠긴 블록에서는 동작하지 않는다.
- Properties의 8단계 너비 버튼과 같은 열 계산을 사용한다.

## 15. 정렬 Guide

이동 중인 블록과 형제 블록을 비교해 붉은 선을 표시한다.

가로 기준:

- 위쪽 y 일치
- 아래쪽 y+height 일치

세로 기준:

- 왼쪽 x 일치
- 가로 중심 일치

현재 지원하지 않는 Guide:

- 오른쪽 edge
- 세로 중심
- 블록 사이 동일 간격
- Guide 위치로 강제 자석 Snap

Guide는 편집 상태에서 내부 블록 이동 중에만 표시한다.

## 16. 잠금

- 각 블록에 `locked` Boolean을 둔다.
- 잠기면 이동, Resize, 개별 삭제를 막는다.
- 잠긴 블록은 노란 점선 Outline과 항상 보이는 Chrome을 갖는다.
- Properties에서 잠금/해제할 수 있다.
- 멀티 선택 Properties에서 모두 잠금/모두 해제를 지원한다.
- 잠금은 pages 상태에 포함되어 Undo/Snapshot 대상이지만 서버에는 저장되지 않는다.

주의:

- Keyboard 일괄 삭제는 선택 중 잠긴 블록이 하나라도 있으면 전체 삭제를 막는다.
- 멀티 선택 Properties의 `모두 삭제`는 현재 `bulkDelete`를 직접 호출해 잠긴 블록도 함께
  제거한다. 목업 내부에서도 경로별 동작이 다르므로 실서비스에서는 정책을 하나로 통일해야 한다.

## 17. 복사·붙여넣기·복제

### 복사

- 주 선택 블록 하나만 Clipboard에 복사한다.
- 원본 페이지 폭도 함께 보관한다.

### 붙여넣기

- 다른 방향 페이지에서도 원래 열 span을 유지하도록 너비를 다시 계산한다.
- 원본보다 x/y를 24px씩 이동해 복제한다.
- 새 ID를 발급한다.
- 댓글은 복사하지 않는다.
- 모든 표시 설정, 편집된 Table rows, 색상, Font 설정은 복사한다.
- 전체 페이지를 repack하고 A4를 넘으면 붙여넣기를 취소한다.

### Properties 복제

- 주 선택 블록 제목 뒤에 `복사본`을 붙인다.
- 나머지 동작은 붙여넣기와 같다.

## 18. 멀티 선택 일괄 작업

선택이 두 개 이상이면 Properties가 Multi Select 화면으로 바뀐다.

지원:

- 첫 번째 선택 블록을 기준으로 너비 통일
- 첫 번째 선택 블록을 기준으로 높이 통일
- 모두 잠금
- 모두 잠금 해제
- 모두 삭제

지원하지 않음:

- 좌/중/우 위치 정렬
- 위/중/아래 위치 정렬
- 간격 분배
- Group Drag

크기 통일 후 전체 페이지를 다시 pack한다.

## 19. 페이지 관리

### 페이지 선택

- 번호, 이름, 방향 아이콘을 표시한다.
- 선택 시 블록 선택을 해제한다.

### 페이지 추가

- `세로 A4`, `가로 A4` 버튼이 있다.
- 빈 페이지를 목록 마지막에 추가한다.
- 기본 이름은 `새 세로 페이지` 또는 `새 가로 페이지`다.

### 페이지 복제

- 원본 바로 다음 위치에 삽입한다.
- 이름에 `복사본`을 붙인다.
- 모든 블록을 새 ID로 복제한다.
- 댓글은 제거한다.

### 페이지 삭제

- 한 페이지만 남았을 때는 삭제할 수 없다.
- 현재 페이지를 삭제하면 남은 첫 페이지로 이동한다.

### 페이지 순서

- 위/아래 버튼으로 한 칸 이동한다.
- 첫 페이지의 위 이동, 마지막 페이지의 아래 이동은 비활성화한다.

### 페이지 방향

- 페이지별 portrait/landscape를 지원한다.
- 기존 블록의 열 span을 이전 페이지 폭에서 계산한다.
- 새 방향의 페이지 폭으로 픽셀 너비를 다시 만든다.
- 높이를 새 A4 높이 이하로 자른다.
- 전체 페이지를 repack한다.

### 페이지 이름

- 블록을 선택하지 않았을 때 Properties에서 바로 수정한다.

## 20. 페이지 Overflow

페이지 가장 아래 블록의 `y + height`가 `A4 height - 40px`를 넘으면 Overflow로 판단한다.

- 블록 추가·복사·붙여넣기는 Overflow가 발생하면 Commit하지 않는다.
- 기존 블록 Resize나 속성 변경으로 Overflow가 생기면 변경은 남고 상단 Banner를 표시한다.
- A4 자체는 `overflow:hidden`이라 Banner가 없으면 아래 콘텐츠가 잘릴 수 있다.
- 자동 배치와 Template 적용은 모든 경로에서 동일한 Overflow guard를 사용하지 않는다.

실서비스에서는 모든 저장·미리보기·출력 경로가 같은 Page validation을 사용해야 한다.

## 21. Template

### 기본 Template 네 개

1. 월간 실적 요약, 가로
2. 목표 달성 대시보드, 가로
3. 임원 브리핑 1장, 세로
4. 분기 비교, 세로

### Thumbnail

- 실제 Chart나 Table을 작은 크기로 렌더링하지 않는다.
- 블록 x/y/width/height를 축소한 Wireframe을 표시한다.
- 블록 종류별 색상으로 구분한다.
- 방향, 블록 수, 기본 Template Badge를 표시한다.

### 현재 페이지를 Template으로 저장

- `window.prompt`로 이름을 입력한다.
- 현재 방향, 페이지 폭, blocks 배열을 브라우저 상태에 저장한다.
- 새로고침하면 사라진다.

### Template 적용

- 현재 페이지에 합치지 않고 새 페이지를 만든다.
- Template 방향을 유지한다.
- 모든 블록에 새 ID를 부여한다.
- 원래 열 span을 새 페이지 폭에 맞춰 보존한다.
- 댓글은 제거한다.
- 전체 블록을 repack한다.

### 사용자 Template 삭제

- 사용자가 만든 Template에만 삭제 버튼이 있다.
- 기본 Template은 삭제할 수 없다.

## 22. 검색

- 모든 페이지 블록을 순회한다.
- 대소문자를 무시한다.
- `title`, `text`, `note`를 검색한다.
- 결과에 블록 제목과 페이지 이름을 표시한다.
- 결과를 클릭하면 해당 페이지로 이동하고 블록을 주 선택한다.

현재 Placeholder는 `제목·본문·주석 검색`이라고 표시하지만 댓글 `comments[].text`는 검색하지
않는다. 여기서 `주석`은 Chart의 `note`만 의미하는 구현이다.

## 23. 블록별 기능

### Cover

- 고정된 Brand 문구, 큰 제목, Tagline, `2026.08`을 표시한다.
- 현재 BlockContent에서는 Inline 편집을 제공하지 않는다.
- Properties의 공통 제목 Input으로만 제목을 바꿀 수 있다.

### Heading

- 제목과 부제목을 표시한다.
- A4에서 클릭해 Inline 편집할 수 있다.
- Properties에서 본문, 글자 크기, 글자색을 바꾼다.
- 하단 파란 구분선을 사용한다.

### KPI

필드:

```text
title
value
delta
deltaYoY
compareBase: prevMonth | prevYear
```

- 제목, 값, 증감률을 A4에서 Inline 편집한다.
- 비교 기준에 따라 delta 또는 deltaYoY를 표시한다.
- 절댓값 10 이상 증감이면 `이상치` Badge를 표시한다.
- 이 기준은 통계 분석이 아니라 목업의 단순 임계치다.
- 실제 Artifact나 목표 데이터와 연결되어 있지 않다.

### 목표 대비

필드:

```text
title
current
target
unit
```

- 현재 값/목표 값으로 달성률을 계산한다.
- 진행 Bar는 0~100%로 잘라 표시한다.
- 화면에는 계산된 달성률을 표시한다.
- 목표 이상이면 파란 Bar와 `목표 달성`, 미달이면 붉은 Bar와 남은 값을 표시한다.
- 제목, 현재 값, 목표 값을 Inline 편집한다.

### Chart

공통 필드:

```text
title
chartType
legend
labels
colors[]
note
dimension
series[]
focusCategory
```

- 제목을 Inline 편집한다.
- `note`가 있으면 Chart 상단에 설명을 표시한다.
- Pie/Donut slice를 클릭하면 해당 카테고리 외 slice를 흐리게 표시한다.
- 이 focus는 같은 Chart 내부 시각 효과이며 다른 블록을 필터링하지 않는다.

### Table

열:

```text
사업부
매출
전월 대비
영업이익률
```

- 모든 열 Header를 클릭해 오름차순, 내림차순, 해제 순으로 정렬한다.
- 숫자 문자열은 기호와 단위를 제거해 숫자로 비교한다.
- 사업부는 한국어 문자열로 비교한다.
- 각 Cell을 A4에서 직접 편집할 수 있다.
- 첫 편집 시 공통 Mock rows를 블록 자체 `rows`로 복사한다.
- 다른 Table 블록과 편집 내용이 공유되지 않는다.
- `highlightThreshold` 이상 절대 증감률을 배경색과 굵은 글씨로 강조한다.

### Image

- 외부 이미지 URL을 입력할 수 있다.
- 로컬 파일을 선택하면 FileReader로 Base64 Data URL을 저장한다.
- 대체 텍스트를 입력할 수 있다.
- `object-fit: cover`로 블록 전체를 채운다.
- URL allowlist, 크기 제한, checksum, 권한 검사는 없다.

### AI Summary

- AI Badge, 제목, 본문을 표시한다.
- 제목과 본문을 A4에서 직접 편집한다.
- Properties에서 본문, 글자 크기, 글자색을 바꾼다.
- 실제 AI 호출 결과가 아닌 Mock 문장이다.

### Text

- `REPORT NOTE`, 제목, 본문을 표시한다.
- 제목과 본문을 A4에서 직접 편집한다.
- 줄바꿈을 Paragraph로 표시한다.
- Markdown parser는 없다.

## 24. Inline 편집

- 제목·값은 한 줄 Input, 본문은 Textarea를 사용한다.
- Pointer down 전파를 막아 편집 중 Drag가 시작되지 않게 한다.
- 입력 후 600ms 멈추면 Commit한다.
- Blur에서도 Commit한다.
- 값이 바뀌지 않았으면 Commit하지 않는다.
- 한 줄 Input에서 Enter를 누르면 Blur/Commit한다.
- Esc는 입력 전 값으로 되돌리고 Blur한다.
- 매 Key stroke가 아니라 Commit 단위로 Undo history를 만든다.

## 25. Chart 11종

| ID | 이름 | 데이터 형태 | 주요 설정 |
|---|---|---|---|
| `line` | 라인 | 월별/사업부별 다중 지표 | legend, labels, series, colors |
| `area` | 영역 | 월별/사업부별 다중 지표 | legend, labels, series, colors |
| `bar` | 세로 막대 | 월별/사업부별 다중 지표 | legend, labels, series, colors |
| `horizontalBar` | 가로 막대 | 사업부 4개 단일 값 | labels, category colors |
| `stackedBar` | 누적 막대 | 월별/사업부별 다중 지표 | legend, series, colors |
| `pie` | 파이 | 사업부 4개 비중 | labels, category colors, focus |
| `donut` | 도넛 | 사업부 4개 비중 | labels, category colors, focus |
| `radar` | 레이더 | 사업부 4개 단일 값 | color |
| `radial` | 방사형 | 사업부 4개 단일 값 | labels, category colors |
| `scatter` | 산점도 | 월 번호 x, 매출 y | color |
| `composed` | 혼합 | 첫 지표 Bar, 나머지 Line | legend, labels, series, colors |

### 동적 Chart 데이터 기준

동적 Chart:

```text
line, area, bar, stackedBar, composed
```

기준 선택:

```text
월별
사업부별
```

월별 지표:

```text
총 매출(억)
객실 매출(억)
F&B 매출(억)
OCC(%)
ADR(원)
```

사업부별 지표:

```text
매출(억)
전월 대비(%)
영업이익률(%)
```

- Checkbox로 한 개 이상 series를 선택한다.
- 마지막 series를 해제하려 하면 해당 series를 다시 남겨 빈 선택을 방지한다.
- 월별/사업부별 기준을 바꾸면 첫 번째 지표 하나로 초기화하고 색상도 초기화한다.
- 단위가 다른 OCC·ADR·매출을 같은 Y축에 그릴 수 있어 분석적으로 올바른 축 계약은 아니다.

## 26. 색상과 Typography

### 색상 Palette

```text
#176fe5 #50a2ff #20b486 #e6a23c #805ad5
#e15b64 #2fb6b2 #f2b134 #5b6f89 #0f766e
```

- Chart series 또는 category별로 Palette index를 저장한다.
- Palette 길이를 넘으면 순환한다.
- Text/Summary/Heading은 기본색 Reset을 지원한다.

### 글자 크기

```text
작게      0.85
보통      1.00
크게      1.25
아주 크게 1.50
```

블록 Wrapper의 기본 16px에 scale을 곱하고 내부 요소를 `em` 단위로 함께 확대한다.

## 27. Properties 상세

### 선택 없음

- 페이지 이름
- 페이지 방향
- 블록 선택 안내

### 단일 선택 공통

- 제목
- 잠금
- 너비 1~8단계
- 현재 열 span과 시작 열
- X/Y/W/H 읽기 전용 표시
- 댓글
- Mock Source/Evidence
- 복제
- 삭제

### Chart

- 차트 유형 11종
- 범례
- 데이터 Label
- 데이터 기준과 지표
- 지표/카테고리 색상
- 선택 주석

### KPI

- 값
- 전월 대비
- 전년 동월 대비
- 비교 기준

### 목표 대비

- 현재 값
- 목표 값
- 단위

### Table

- 전월 대비 강조 임계치

### Image

- URL
- 파일 업로드
- 대체 텍스트

### Text/Summary/Heading

- 본문
- 글자 크기 4단계
- 글자색

### 멀티 선택

- 너비 맞추기
- 높이 맞추기
- 모두 잠금/해제
- 모두 삭제

## 28. 댓글

- 블록별 댓글 배열을 사용한다.
- 작성자는 항상 `호텔 분석가`로 고정한다.
- 현재 시각을 ISO 문자열로 저장한다.
- Properties에서 작성·삭제한다.
- 빈 댓글은 추가할 수 없다.
- 블록 Chrome에 댓글 개수 Badge를 표시한다.
- 복제, Paste, Template 적용, 페이지 복제에서는 댓글을 제거한다.
- 검색은 댓글 본문을 검색하지 않는다.
- 댓글은 pages history와 Snapshot에는 포함되지만 서버에는 저장되지 않는다.

## 29. Preview

- Brand Sidebar를 숨긴다.
- Library, Workspace Toolbar, Properties를 포함한 editor-grid를 숨긴다.
- 모든 페이지를 순서대로 중앙에 표시한다.
- Grid 배경을 A4 내부에서 제거한다.
- 블록 선택, Chrome, Resize Handle, Guide를 표시하지 않는다.
- 페이지 번호와 Footer는 유지한다.
- Topbar는 축소된 상태로 남으며 Preview/HTML/PDF 등의 Action도 남는다.
- Zoom은 최대 90%로 제한해 Preview 페이지를 표시한다.

## 30. Keyboard와 접근성

### 단축키

```text
Ctrl/Cmd+Z             Undo
Ctrl/Cmd+Shift+Z       Redo
Ctrl/Cmd+Y             Redo
Ctrl/Cmd+C             주 선택 블록 복사
Ctrl/Cmd+V             붙여넣기
Backspace/Delete       선택 블록 삭제
Shift+Click            다중 선택 추가/제거
Alt+Wheel              너비 조절
Alt+Shift+Wheel        높이 조절
←/→, PageUp/PageDown   프레젠테이션 이동
Esc                    편집 취소/Modal·프레젠테이션 종료
```

Input, Textarea, Select, contenteditable에 Focus가 있으면 전역 복사·삭제·Undo 단축키를 처리하지
않아 텍스트 편집을 보호한다.

### 접근성 요소

- Move, Resize, 삭제, 잠금, 댓글 버튼에 aria-label이 있다.
- Table Header는 `aria-sort`를 사용한다.
- Image alt를 입력할 수 있다.
- Modal은 배경 클릭과 Esc를 지원한다.

제약:

- DnD와 Resize의 완전한 Keyboard 조작은 구현되어 있지 않다.
- Library item이 button이라 클릭 추가는 Keyboard로 가능하지만 A4 위치 지정은 Pointer 중심이다.

## 31. Mock 데이터

### 월별 데이터

- 최근 12개월, 9월부터 다음 해 8월까지다.
- 총 매출은 13.2억에서 18.24억으로 증가한다.
- OCC, ADR, 객실 매출, F&B 매출을 함께 가진다.

### 사업부

```text
객실 11.4억
F&B 4.2억
연회 2.64억
기타 0.72억
```

### Table

- 사업부별 매출
- 전월 대비
- 영업이익률

### AI Summary

8월 전체 매출 증가, 객실 매출 주도, F&B 성장, VIP 객단가 상승을 설명하는 고정 문장이다.

## 32. 현재 자동 테스트

`npm.cmd run test`는 다음을 검사한다.

- 12개월 Mock 데이터
- Test fixture 블록 너비 범위
- Artifact fixture에 KPI/Chart/Summary/Table 포함
- 차트 10종 이상과 Pie/Radar 존재
- 자동 배치 후 블록 비겹침
- 월별·사업부별 지표가 숫자
- Palette 8색 이상과 순환
- Font 2~4종 제한
- 자동 배치 Stretch가 마지막 블록만 늘림

테스트하지 않는 영역:

- 실제 React 사용자 상호작용
- DnD 좌표
- Resize 8방향
- Undo/Redo
- 페이지 CRUD
- HTML/PDF 결과
- Presentation
- 접근성 E2E

## 33. 코드와 문서/UI가 어긋나는 부분

다른 에이전트는 다음을 이미 해결된 기능으로 잘못 판단하지 않아야 한다.

1. 초기 `HANDOFF_TO_DAESUNG.md`의 미구현 범위에는 Undo/Redo가 적혀 있으나 현재 코드는
   Undo/Redo를 구현했다. 현재 코드가 권위 값이다.
2. 검색 Placeholder는 댓글까지 검색하는 것처럼 보이지만 실제로는 title/text/note만 검색한다.
3. `HTML`은 외부 Font까지 완전히 내장한 self-contained 결과가 아니다.
4. 8방향 Resize Handle은 있지만 북/서 Resize에서 x/y 반대편 고정 보정은 없다.
5. 정렬 Guide는 시각 안내이며 최종 위치는 Guide가 아니라 row pack이 결정한다.
6. `library`와 `initialBlocks` export는 테스트가 참조하지만 현재 `ReportBuilder`의 Library와 초기
   페이지는 컴포넌트 내부 상수를 사용한다.
7. Preview는 편집 3단 패널을 숨기지만 Topbar 전체를 숨기지는 않는다.
8. 페이지 전체 방향 혼합 Print는 CSS로 표현하지만 실제 Browser PDF 회귀 테스트가 없다.
9. KPI/Table 값은 사용자가 직접 수정할 수 있으므로 실제 분석 lineage 보존 모델이 아니다.

## 34. 실서비스 이식 매핑

| 목업 개념 | `seung`에서 확인할 위치 | 이식 원칙 |
|---|---|---|
| Topbar | `ReportEditorToolbar.jsx` | 기존 저장·실행·Preview 함수 연결 |
| Library | `ReportToolPanel.jsx` | 실제 Artifact option과 add 함수 사용 |
| A4 | `ReportPageCanvas.jsx` | 12열 좌표와 page row 계약 유지 |
| Block | `ReportEditorBlock.jsx` | Artifact lineage를 spread로 보존 |
| Properties | `ReportPropertiesPanel.jsx` | text content와 setting 분리 |
| Selection tools | `useReportEditorTools.js` | UI-only 상태는 서버 payload에서 제외 |
| Drag | `useReportDragAndDrop.js` | 12열 충돌/배치 helper 재사용 |
| Draft | `useReportDraftState.ts` | `commitBlocks`를 Undo·저장 진입점으로 사용 |
| Page CRUD | 백엔드 확장 필요 | `report_pages` 이후 연결 |
| Template | 백엔드 확장 필요 | Artifact ID가 아닌 slot 기반 저장 |
| Comments | 백엔드 확장 필요 | block content와 분리된 table/API |
| Chart 11종 | renderer 확장 필요 | 화면·HTML·PDF를 함께 완료 |
| HTML/PDF | 기존 backend renderer | DOM clone/print를 이식하지 않음 |

## 35. 실서비스 구현 우선순위

### 프론트만으로 가능한 작업

1. Fit Page/Fit Width
2. 멀티 선택 크기 통일·정렬·분배
3. 기존 12열 helper를 사용한 자동 정돈
4. Template wireframe thumbnail
5. Properties 정보 구조 정돈
6. 8방향 Resize의 정확한 좌표 보정
7. Marquee Selection과 Group Drag

### 백엔드 계약이 먼저 필요한 작업

1. Typed block view spec
2. 기존 7개 차트의 HTML/PDF 의미 일치
3. `report_pages`와 페이지별 orientation
4. Artifact `full/kpi/chart/table/summary` view mode
5. 영구 Template
6. 댓글·영구 Snapshot·Draft revision
7. Scatter/Radar/Radial/Composed/Treemap/Funnel renderer
8. canonical Draft HTML/PDF Preview API

상세 백엔드 작업은 다음 문서를 따른다.

```text
docs/report_builder/BACKEND_DEVELOPER_HANDOFF.md
docs/report_builder/BACKEND_EVOLUTION_ROADMAP.md
```

프론트 작업은 다음 문서를 따른다.

```text
docs/report_builder/FRONTEND_ENHANCEMENT_HANDOFF.md
```

## 36. 목업 기준 사용자 인수 시나리오

다른 에이전트가 구현 완료를 판단할 때 다음 시나리오를 사용한다.

### 시나리오 A: Artifact 기반 보고서 작성

1. 분석 결과 Library를 연다.
2. 전체 매출 KPI를 가로 A4에 Drag한다.
3. 객실 월별 매출 Chart를 추가한다.
4. VIP Summary를 추가한다.
5. 블록이 겹치지 않고 8열 Grid에 배치되는지 확인한다.
6. 제목과 표시 설정을 바꾼다.
7. Preview에서 편집 Chrome이 사라지는지 확인한다.

### 시나리오 B: 블록 편집

1. Chart를 이동한다.
2. 8방향 Handle과 Alt+Wheel로 Resize한다.
3. Pointer release 후 전체 행이 정돈되는지 확인한다.
4. 잠금 후 이동·Resize·삭제가 막히는지 확인한다.
5. Undo로 이전 상태를 복원한다.

### 시나리오 C: 멀티 선택

1. Shift+클릭으로 여러 블록을 선택한다.
2. 너비와 높이를 통일한다.
3. 모두 잠근다.
4. 잠금 해제 후 일괄 삭제한다.
5. Undo 한 번으로 복원한다.

### 시나리오 D: 페이지

1. 세로 페이지와 가로 페이지를 추가한다.
2. 페이지 이름을 바꾼다.
3. 페이지를 복제하고 순서를 이동한다.
4. 페이지 방향을 바꿔 블록 span이 유지되는지 확인한다.
5. 한 페이지만 남으면 삭제가 막히는지 확인한다.

### 시나리오 E: Template과 Snapshot

1. 현재 페이지를 사용자 Template으로 저장한다.
2. Thumbnail을 확인한다.
3. Template을 적용해 새 페이지가 생기는지 확인한다.
4. 전체 상태를 이름 붙인 Snapshot으로 저장한다.
5. 편집 후 Snapshot을 복원한다.
6. Undo로 Restore 전 상태로 돌아간다.

### 시나리오 F: 출력

1. Preview로 모든 페이지를 확인한다.
2. HTML을 내려받는다.
3. 브라우저에서 HTML을 연다.
4. PDF 버튼으로 Print 대화상자를 연다.
5. 세로·가로 페이지 순서와 편집 UI 제외를 확인한다.

실서비스에서는 E/F 시나리오의 저장·출력이 서버 계약과 checksum을 통해 검증되어야 한다.

## 37. 다음 작업 에이전트에게 전달할 지시

1. 먼저 이 목업 파일과 `seung` 프론트 코드를 모두 읽는다.
2. 목업 기능별로 `이미 연결됨 / 프론트만 필요 / 백엔드 필요 / 이식 금지`를 표로 작성한다.
3. 확인하지 않은 기능을 구현됐다고 보고하지 않는다.
4. 목업의 8열 좌표나 Mock 데이터를 실서비스 계약으로 만들지 않는다.
5. Artifact lineage와 canonical HTML/PDF를 기능보다 우선한다.
6. 기능 하나를 migration/API/frontend/renderer/test까지 작은 단위로 완료한다.
7. 실제 Browser 또는 PDF를 확인하지 않았으면 각각 검증 완료라고 말하지 않는다.

## 38. 첫 회신 양식

이 문서를 받은 에이전트는 구현 전에 다음 형식으로 답한다.

```text
1. 목업 코드 확인 완료 여부:
2. seung 프론트 확인 완료 여부:
3. 목업 기능 중 이미 실서비스에 연결된 기능:
4. 프론트 작업만 남은 기능:
5. 백엔드 변경이 필요한 기능:
6. 실서비스에 이식하면 안 되는 Mock 기능:
7. 첫 구현 범위:
8. 예상 변경 파일과 migration:
9. Artifact lineage와 HTML/PDF 보존 방법:
10. 사용자에게 확인받아야 할 결정:
```

코드에서 확인한 사실과 구현 제안을 구분해 답한다.

---

# 자급형 구현 코드 부록

아래 내용은 원본 폴더에 접근하지 못하는 에이전트가 목업의 구현 방식을 이해하기 위한 코드
참조다. 실서비스에 그대로 복사하는 코드가 아니라 기능의 입력·상태·출력을 확인하는 기준이다.

## 39. Package와 진입 구조

목업의 최소 package 구성:

```json
{
  "name": "answervice-report-prototype",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 0.0.0.0",
    "build": "vite build",
    "preview": "vite preview --host 0.0.0.0",
    "test": "node src/report/prototype.test.mjs"
  },
  "dependencies": {
    "@dnd-kit/core": "^6.3.1",
    "lucide-react": "1.25.0",
    "react": "19.2.7",
    "react-dom": "19.2.7",
    "recharts": "3.10.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "6.0.3",
    "vite": "8.1.5"
  }
}
```

Component 책임 구조:

```text
ReportBuilder
├─ DndContext
├─ BrandSidebar
├─ Topbar
├─ Library
│  ├─ Search
│  ├─ TemplateThumb / TemplateCard
│  ├─ LibraryItem
│  └─ PageList
├─ Workspace
│  ├─ WorkspaceToolbar
│  ├─ OverflowBanner
│  └─ PageCanvas
│     ├─ ReportBlock
│     │  └─ BlockContent
│     └─ AlignmentGuides
├─ Properties
│  ├─ ChartDataFields
│  ├─ SwatchPicker
│  └─ CommentThread
├─ PresentationOverlay
├─ DragOverlay
└─ ShortcutsPanel
```

원본은 위 책임을 대부분 `ReportBuilder.jsx` 한 파일에 둔다. 실서비스에서는 이 구조를 참고하되
기존 `useReportsPageController`, draft hook, component 경계를 유지한다.

## 40. 데이터 구조의 코드 표현

원본은 TypeScript type 없이 JavaScript object를 사용한다. 동등한 의미를 type으로 표현하면
다음과 같다.

```ts
type Orientation = "portrait" | "landscape";

type Comment = {
  id: string;
  author: string;
  text: string;
  at: string;
};

type BaseBlock = {
  id: string;
  kind: "cover" | "heading" | "kpi" | "goal" | "chart" |
        "table" | "image" | "summary" | "text";
  title: string;
  x: number;
  y: number;
  width: number;
  height: number;
  locked?: boolean;
  comments?: Comment[];
  fontScale?: 0.85 | 1 | 1.25 | 1.5;
  textColor?: number | null;
};

type KpiBlock = BaseBlock & {
  kind: "kpi";
  value?: string;
  delta?: string;
  deltaYoY?: string;
  compareBase?: "prevMonth" | "prevYear";
};

type GoalBlock = BaseBlock & {
  kind: "goal";
  current?: string | number;
  target?: string | number;
  unit?: string;
};

type ChartBlock = BaseBlock & {
  kind: "chart";
  chartType: "line" | "area" | "bar" | "horizontalBar" |
             "stackedBar" | "pie" | "donut" | "radar" |
             "radial" | "scatter" | "composed";
  legend?: boolean;
  labels?: boolean;
  dimension?: "month" | "division";
  series?: string[];
  colors?: number[];
  note?: string;
  focusCategory?: string;
};

type TableBlock = BaseBlock & {
  kind: "table";
  rows?: Array<{
    division: string;
    revenue: string;
    change: string;
    margin: string;
  }>;
  highlightThreshold?: string | number;
};

type ImageBlock = BaseBlock & {
  kind: "image";
  src?: string;
  alt?: string;
};

type TextBlock = BaseBlock & {
  kind: "cover" | "heading" | "summary" | "text";
  text?: string;
};

type Page = {
  id: string;
  name: string;
  orientation: Orientation;
  blocks: Array<BaseBlock>;
};

type UserTemplate = {
  id: string;
  name: string;
  builtin?: boolean;
  orientation: Orientation;
  pageWidth: number;
  blocks: Array<BaseBlock>;
};

type NamedSnapshot = {
  id: string;
  name: string;
  pages: Page[];
};
```

실서비스 차이:

```text
목업: id, kind, pixel geometry, 직접 수정 가능한 mock values
실서비스: UUID, type, 12열 x/y/w/h, artifactId/queryId, lineage
```

## 41. 전체 React 상태 코드

목업의 편집 상태는 다음 hooks로 구성된다.

```jsx
const [pages, setPages] = useState(makeInitialPages);
const [pageId, setPageId] = useState("dashboard");
const [selectedId, setSelectedId] = useState("trend");
const [preview, setPreview] = useState(false);
const [zoom, setZoom] = useState(.72);
const [fontId, setFontId] = useState(FONT_OPTIONS[0].id);
const [activeItem, setActiveItem] = useState(null);
const [presenting, setPresenting] = useState(false);
const [presentIndex, setPresentIndex] = useState(0);
const [presentZoom, setPresentZoom] = useState(1);
const [overflowNotice, setOverflowNotice] = useState("");
const [clipboard, setClipboard] = useState(null);
const [multiSelectedIds, setMultiSelectedIds] = useState(() => new Set());
const [helpOpen, setHelpOpen] = useState(false);
const [templates, setTemplates] = useState(() => STARTER_TEMPLATES);
const [snapshots, setSnapshots] = useState([]);
const [searchQuery, setSearchQuery] = useState("");
const [history, setHistory] = useState({ past: [], future: [] });
```

실서비스에서 `pages/templates/comments/snapshots`를 그대로 하나의 local state로 만들면 안 된다.
현재 backend contract가 권위를 가져야 하는 상태와 session-only 편의 상태를 먼저 분리한다.

## 42. Grid와 자동 배치 실제 코드

목업의 `layout.js` 전체 핵심은 다음과 같다.

```js
export const GRID_COLUMNS = 8;
export const PAGE_MARGIN = 40;
export const BLOCK_GAP = 16;
export const ROW_GAP = 20;
export const ROW_STEP = 24;

export const clamp = (value, min, max) =>
  Math.min(Math.max(value, min), max);

export const grid = (pageWidth) => ({
  column: (pageWidth - PAGE_MARGIN * 2) / GRID_COLUMNS,
});

export const spanWidth = (span, pageWidth) =>
  grid(pageWidth).column * clamp(span, 1, GRID_COLUMNS) - BLOCK_GAP;

export const widthSpan = (width, pageWidth) =>
  clamp(
    Math.round((width + BLOCK_GAP) / grid(pageWidth).column),
    1,
    GRID_COLUMNS,
  );

export const snapColumn = (x, pageWidth, width) => {
  const column = grid(pageWidth).column;
  const maxIndex = GRID_COLUMNS - widthSpan(width, pageWidth);
  return PAGE_MARGIN
    + clamp(Math.round((x - PAGE_MARGIN) / column), 0, maxIndex) * column;
};

export function packPageBlocks(
  blocks,
  pageWidth,
  { stretchLastToFillRow = false } = {},
) {
  const column = grid(pageWidth).column;
  const ordered = [...blocks].sort((a, b) => a.y - b.y || a.x - b.x);
  const packed = [];
  let row = [];
  let rowCols = 0;
  let y = PAGE_MARGIN;

  const flushRow = () => {
    if (!row.length) return;
    let finalRow = row;
    if (stretchLastToFillRow && rowCols < GRID_COLUMNS) {
      const lastIndex = row.length - 1;
      const extraColumns = GRID_COLUMNS - rowCols;
      finalRow = row.map((item, index) => index === lastIndex
        ? { ...item, width: item.width + extraColumns * column }
        : item);
    }
    const rowHeight = Math.max(...finalRow.map((item) => item.height));
    for (const item of finalRow) {
      packed.push({ ...item, y, height: rowHeight });
    }
    y += rowHeight + ROW_GAP;
    row = [];
    rowCols = 0;
  };

  for (const item of ordered) {
    const span = widthSpan(item.width, pageWidth);
    if (rowCols > 0 && rowCols + span > GRID_COLUMNS) flushRow();
    row.push({
      ...item,
      x: PAGE_MARGIN + rowCols * column,
      width: spanWidth(span, pageWidth),
    });
    rowCols += span;
    if (rowCols >= GRID_COLUMNS) flushRow();
  }
  flushRow();
  return packed;
}
```

실서비스 적용 시에는 위 코드를 복사하지 않고 12열 `compactDraftLayout`과
`placeDraftBlock` 계열 helper가 같은 책임을 수행하는지 확인한다.

## 43. Selection과 History 코드

### 주 선택 + Shift 보조 선택

```jsx
const selectedIds = new Set(multiSelectedIds);
if (selectedId) selectedIds.add(selectedId);

const handleSelect = (id, shiftKey) => {
  if (!shiftKey || !id) {
    setSelectedId(id);
    setMultiSelectedIds(new Set());
    return;
  }
  setMultiSelectedIds((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
};
```

### 전체 pages Snapshot 기반 History

```jsx
const pagesRef = useRef(pages);
useEffect(() => { pagesRef.current = pages; }, [pages]);

const commitPages = (updater) => setPages((current) => {
  const next = typeof updater === "function" ? updater(current) : updater;
  if (next === current) return current;
  setHistory((history) => ({
    past: [...history.past.slice(-39), current],
    future: [],
  }));
  return next;
});

const undo = () => setHistory((history) => {
  if (!history.past.length) return history;
  const previous = history.past.at(-1);
  const current = pagesRef.current;
  setPages(previous);
  return {
    past: history.past.slice(0, -1),
    future: [current, ...history.future].slice(0, 40),
  };
});

const redo = () => setHistory((history) => {
  if (!history.future.length) return history;
  const [next, ...future] = history.future;
  const current = pagesRef.current;
  setPages(next);
  return {
    past: [...history.past, current].slice(-40),
    future,
  };
});
```

실서비스는 전체 pages가 아니라 기존 draft block history와 `commitBlocks`를 사용해야 한다.

## 44. Library DnD와 내부 Drag 코드

### Library Item

```jsx
function LibraryItem({ item, onAdd }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `library:${item.id}`,
    data: item,
  });

  return (
    <button
      ref={setNodeRef}
      className={`library-card ${isDragging ? "dragging" : ""}`}
      onClick={() => onAdd(item)}
      {...attributes}
      {...listeners}
    >
      <span><item.icon size={15} /></span>
      <b>{item.title}</b>
      <GripVertical size={13} />
    </button>
  );
}
```

### Pointer Sensor

```jsx
const sensors = useSensors(
  useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
);
```

### Library Drop 좌표 변환

```jsx
const onDragEnd = ({ active, over }) => {
  const item = active.data.current;
  const target = String(over?.id || "");
  if (item && target === `page:${page.id}`) {
    const rect = document
      .querySelector(`[data-page-id="${page.id}"]`)
      ?.getBoundingClientRect();
    const translated = active.rect.current.translated;
    addBlock(item, rect && translated ? {
      x: (translated.left - rect.left) / zoom,
      y: (translated.top - rect.top) / zoom,
    } : undefined);
  }
  setActiveItem(null);
};
```

### 내부 블록 Drag/Resize 핵심

```js
const dx = (event.clientX - startX) / zoom;
const dy = (event.clientY - startY) / zoom;

if (mode === "move") {
  onChange({
    x: snapColumn(startItem.x + dx, pageWidth, item.width),
    y: clamp(
      Math.round((startItem.y + dy) / ROW_STEP) * ROW_STEP,
      0,
      pageHeight - item.height,
    ),
  });
}

if (direction.includes("e")) width = startItem.width + dx;
if (direction.includes("w")) width = startItem.width - dx;
if (direction.includes("s")) height = startItem.height + dy;
if (direction.includes("n")) height = startItem.height - dy;

width = spanWidth(widthSpan(width, pageWidth), pageWidth);
height = clamp(
  Math.round(height / ROW_STEP) * ROW_STEP,
  72,
  pageHeight,
);
```

Pointer move 중에는 대상 블록만 변경하고 Pointer up에서 다음을 실행한다.

```js
const commitLayout = () => commitPages((pages) => pages.map((candidate) =>
  candidate.id === page.id
    ? { ...candidate, blocks: repackPage(candidate.blocks, candidate.orientation) }
    : candidate,
));
```

이 분리는 Gesture 중 다른 블록이 움직이는 현상을 피하고 Undo를 한 단계로 만든다.

## 45. 블록 추가·복제·Overflow 코드

### A4 높이 검사

```js
const pageFits = (blocks, orientation) => {
  if (!blocks.length) return true;
  const bottom = Math.max(...blocks.map((block) => block.y + block.height));
  return bottom <= A4[orientation].height - PAGE_MARGIN;
};
```

### 공통 Commit Guard

```jsx
const commitIfFits = (nextBlockId, packed) => {
  if (!pageFits(packed, page.orientation)) {
    setOverflowNotice(
      `"${page.name}" 페이지가 이미 가득 찼습니다. `
      + "블록 크기를 줄이거나 새 페이지를 추가해 주세요.",
    );
    return;
  }
  commitPages((items) => items.map((candidate) =>
    candidate.id === page.id
      ? { ...candidate, blocks: packed }
      : candidate,
  ));
  setSelectedId(nextBlockId);
};
```

### 복제의 필드 보존

```jsx
const cloneBlock = (source, position) => {
  const size = A4[page.orientation];
  const x = snapColumn(position?.x ?? source.x, size.width, source.width);
  const y = clamp(
    Math.round((position?.y ?? source.y) / ROW_STEP) * ROW_STEP,
    0,
    size.height - source.height,
  );
  const next = {
    ...source,
    id: uid(source.kind),
    x,
    y,
    comments: [],
  };
  commitIfFits(
    next.id,
    repackPage([...page.blocks, next], page.orientation),
  );
};
```

실서비스에서는 `...source` 방식이 lineage 필드까지 보존되는지 타입과 sanitizer 테스트로 확인하고
ID는 반드시 기존 `createUuid`를 사용한다.

## 46. Page와 Template 코드

### Orientation 변경

```jsx
const updatePage = (change) => commitPages((pages) => pages.map((candidate) => {
  if (candidate.id !== page.id) return candidate;
  const orientation = change.orientation || candidate.orientation;
  const reflow = change.orientation
    && change.orientation !== candidate.orientation;

  const blocks = reflow
    ? candidate.blocks.map((block) => {
      const span = widthSpan(block.width, A4[candidate.orientation].width);
      return {
        ...block,
        width: spanWidth(span, A4[orientation].width),
        height: Math.min(block.height, A4[orientation].height),
      };
    })
    : candidate.blocks;

  return {
    ...candidate,
    ...change,
    blocks: repackPage(blocks, orientation),
  };
}));
```

### Page 추가/복제/삭제/이동

```jsx
const addPage = (orientation) => {
  const id = uid("page");
  commitPages((pages) => [...pages, {
    id,
    name: orientation === "portrait" ? "새 세로 페이지" : "새 가로 페이지",
    orientation,
    blocks: [],
  }]);
  setPageId(id);
  clearSelection();
};

const duplicatePage = (id) => {
  const source = pages.find((page) => page.id === id);
  if (!source) return;
  const clone = {
    ...source,
    id: uid("page"),
    name: `${source.name} 복사본`,
    blocks: source.blocks.map((block) => ({
      ...block,
      id: uid(block.kind),
      comments: [],
    })),
  };
  commitPages((pages) => {
    const index = pages.findIndex((page) => page.id === id);
    return [...pages.slice(0, index + 1), clone, ...pages.slice(index + 1)];
  });
};

const deletePage = (id) => {
  if (pages.length <= 1) return;
  commitPages((pages) => pages.filter((page) => page.id !== id));
};

const movePage = (id, delta) => commitPages((pages) => {
  const index = pages.findIndex((page) => page.id === id);
  const target = index + delta;
  if (target < 0 || target >= pages.length) return pages;
  const next = [...pages];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
});
```

### Template 저장과 적용

```jsx
const saveAsTemplate = () => {
  const name = window.prompt("템플릿 이름", `${page.name} 템플릿`);
  if (!name) return;
  setTemplates((templates) => [...templates, {
    id: uid("template"),
    name,
    orientation: page.orientation,
    pageWidth: A4[page.orientation].width,
    blocks: page.blocks,
  }]);
};

const applyTemplate = (template) => {
  const id = uid("page");
  const targetWidth = A4[template.orientation].width;
  const cloned = template.blocks.map((block) => {
    const span = widthSpan(block.width, template.pageWidth);
    return {
      ...block,
      id: uid(block.kind),
      width: spanWidth(span, targetWidth),
      comments: [],
    };
  });
  commitPages((pages) => [...pages, {
    id,
    name: template.name,
    orientation: template.orientation,
    blocks: repackPage(cloned, template.orientation),
  }]);
  setPageId(id);
  clearSelection();
};
```

실서비스 Template은 위 blocks를 그대로 DB에 저장하지 않고 Artifact slot과 schema requirement를
저장해야 한다.

## 47. Chart registry와 데이터 코드

### 11종 registry

```js
export const chartTypes = [
  ["line", "라인"],
  ["area", "영역"],
  ["bar", "세로 막대"],
  ["horizontalBar", "가로 막대"],
  ["stackedBar", "누적 막대"],
  ["pie", "파이"],
  ["donut", "도넛"],
  ["radar", "레이더"],
  ["radial", "방사형"],
  ["scatter", "산점도"],
  ["composed", "혼합"],
].map(([id, label]) => ({ id, label }));

const DYNAMIC_CHART_TYPES = [
  "line",
  "area",
  "bar",
  "stackedBar",
  "composed",
];
```

### 지표 registry

```js
export const monthlyMetricFields = [
  { key: "revenue", label: "총 매출(억)" },
  { key: "roomRevenue", label: "객실 매출(억)" },
  { key: "fnbRevenue", label: "F&B 매출(억)" },
  { key: "occ", label: "OCC(%)" },
  { key: "adr", label: "ADR(원)" },
];

export const divisionMetricFields = [
  { key: "revenue", label: "매출(억)" },
  { key: "change", label: "전월 대비(%)" },
  { key: "margin", label: "영업이익률(%)" },
];
```

### Chart 분기 구조

```text
pie/donut      → PieChart + Cell + focusCategory opacity
radar          → RadarChart
radial         → RadialBarChart
scatter        → ScatterChart(month index, revenue)
horizontalBar  → vertical-layout BarChart(divisions)
stackedBar     → BarChart + shared stackId
composed       → first series Bar + remaining Line
area           → AreaChart
bar            → BarChart
default        → LineChart
```

실서비스는 이 registry 이름을 그대로 API에 채택하지 않는다. 현재 backend의 kebab-case 이름과
canonical renderer capability를 기준으로 versioned mapping을 만든다.

## 48. Theme와 CSS 디자인 토큰

### Theme 코드

```js
export const PALETTE = [
  "#176fe5", "#50a2ff", "#20b486", "#e6a23c", "#805ad5",
  "#e15b64", "#2fb6b2", "#f2b134", "#5b6f89", "#0f766e",
];

export const FONT_OPTIONS = [
  { id: "sans", label: "고딕 (기본)", family: "Inter, 'Noto Sans KR', sans-serif" },
  { id: "serif", label: "명조", family: "'Noto Serif KR', serif" },
  { id: "round", label: "둥근 고딕", family: "'Gowun Dodum', sans-serif" },
];

export const FONT_SIZE_BASE = 16;
export const FONT_SIZE_STEPS = [
  { id: "sm", label: "작게", scale: 0.85 },
  { id: "md", label: "보통", scale: 1 },
  { id: "lg", label: "크게", scale: 1.25 },
  { id: "xl", label: "아주 크게", scale: 1.5 },
];
```

### CSS 핵심값

```css
:root {
  color: #e8edf5;
  background: #070b11;
  --blue: #176fe5;
  --line: #202d40;
  --panel: #0b121c;
}

.brand-sidebar { width: 224px; background: #05080e; }
.topbar { height: 104px; background: #05090f; }
.editor-grid {
  grid-template-columns: 244px minmax(620px, 1fr) 258px;
}
.library,
.properties { background: #09101a; }
.workspace {
  background-color: #151a22;
  background-image: radial-gradient(#2d3643 1px, transparent 1px);
  background-size: 18px 18px;
}
.a4-page {
  overflow: hidden;
  color: #1a2635;
  background: #fff;
  box-shadow: 0 20px 70px rgba(0, 0, 0, .35);
}
.report-object {
  border: 1px solid #dce5ef;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 5px 18px rgba(38, 58, 82, .06);
}
.report-object.selected {
  outline: 2px solid #176fe5;
  outline-offset: 2px;
}
.report-object.locked {
  outline: 1.5px dashed #f0c36e;
  outline-offset: 2px;
}
```

### 반응형 한계

```css
body { min-width: 1180px; }

@media (max-width: 1360px) {
  body { min-width: 1050px; }
  .editor-grid {
    grid-template-columns: 220px minmax(570px, 1fr) 235px;
  }
}
```

실서비스 V2 CSS는 반드시 `[data-report-builder="v2"]` 아래로 scope하고 위 전역 selector를
복사하지 않는다.

## 49. Preview와 Export 코드

### HTML Export

```js
async function exportHtml(fontFamily) {
  const source = document.querySelector(".preview-pages")
    || document.querySelector(".page-shell")?.parentElement;
  const clone = source?.cloneNode(true);
  if (!clone) return;

  clone.querySelectorAll(".object-chrome,.resize-point")
    .forEach((node) => node.remove());

  let css = "";
  for (const sheet of document.styleSheets) {
    try {
      css += [...sheet.cssRules].map((rule) => rule.cssText).join("\n");
    } catch {
      // cross-origin stylesheet는 읽지 못한다.
    }
  }

  const html = `<!doctype html>
  <html lang="ko">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width">
      <title>Answervice Report</title>
      <style>${css}</style>
    </head>
    <body class="html-export">${clone.outerHTML}</body>
  </html>`;

  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  link.download = "answervice-report.html";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
```

### Print CSS 개념

```css
@page portraitPage { size: A4 portrait; margin: 0; }
@page landscapePage { size: A4 landscape; margin: 0; }

.a4-page.portrait { page: portraitPage; }
.a4-page.landscape { page: landscapePage; }

@media print {
  .brand-sidebar,
  .editor-grid,
  .topbar { display: none !important; }

  .object-chrome,
  .resize-point { display: none !important; }

  .page-shell { break-after: page; }
}
```

이 코드는 기능을 설명하기 위한 목업 기준이다. 실서비스에서는 기존 backend document source,
renderer version, source/html/pdf checksum과 WeasyPrint 경로만 사용한다.

## 50. 외부 목업 폴더 없이 작업하는 방법

다른 에이전트가 이 MD 하나만 받았을 때 다음 순서로 작업한다.

```text
1. 1~38절에서 기능과 현재 제약을 읽는다.
2. 39~49절의 코드 부록에서 상태·입력·알고리즘을 확인한다.
3. seung의 기존 controller/draft/renderer에서 대응 지점을 찾는다.
4. 목업 기능을 다음 네 종류로 분류한다.
   - 이미 구현됨
   - 프론트만 수정하면 됨
   - 백엔드·DB·renderer가 필요함
   - mock 전용이라 이식 금지
5. 기존 12열, Artifact lineage, canonical HTML/PDF를 보존하는 최소 변경을 설계한다.
6. 기능 하나씩 구현하고 테스트한다.
```

원본 목업 폴더가 없어도 위 설명과 코드 부록으로 기능·상태·배치 방식·디자인 기준을 판단할 수
있다. 다만 픽셀 단위 시각 비교가 필요할 때만 실행 중인 `http://192.168.0.37:4174/` 화면 또는
별도 Screenshot을 요청한다.
