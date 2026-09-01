# 보고서 UI/UX 전수조사 및 중간발표 피드백 평가

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-08-31 KST |
| 목적 | 보고서 열람·편집·미리보기·확정 화면의 개선 대상을 고정하고, 중간발표 피드백의 실제 반영 수준을 과장 없이 평가한다. |
| 제품 수정 | 없음. 이 문서는 조사·평가 결과만 기록한다. |
| UI 실행 증거 | 배포 Runtime `7c94d2f1057d6a1531462178d9bb1185a947c9e3`에 대한 Playwright 열람 조사와 사용자 첨부 이미지 1~7 |
| 소스 대조 기준 | 현재 checkout `3ad8ba19c6e40fd6cbc2ce02df7225c6bbc92f38`. 보고서 소스 영역은 조사 시점에 clean이었지만 repository 전체는 다른 작업으로 dirty 상태였다. |
| 조사 제약 | 보고서 저장·확정·실행·삭제 등 쓰기 동작은 수행하지 않았다. 따라서 쓰기 이후 상태는 소스 계약으로만 평가했으며, 실제 성공으로 간주하지 않는다. |

---

## 1. 결론

현재 보고서 기능은 **기능 골격은 있으나 최종 사용자에게 제공하기에는 UI 상태 분리, 반응형 레이아웃, 블록 조작 피드백, 접근성, UX Writing 정리가 부족한 상태**다.

가장 먼저 고쳐야 할 문제는 다음 네 묶음이다.

1. **편집과 미리보기의 분리**
   - 미리보기와 확정본에는 블록 이동 손잡이, 더보기, 크기 조절점, 서식 도구, 블록별 `편집/미리보기` 전환을 노출하지 않는다.
   - 미리보기에는 문서 확인과 상위 동작만 남긴다.
2. **좌측 블록 패널과 반응형 레이아웃**
   - 블록 라이브러리는 좌측에 두되 캔버스를 덮는 임시 부유 패널이 아니라 고정·접기 가능한 패널로 만든다.
   - 모바일에서는 접근 가능한 drawer/dialog로 전환한다.
3. **AI 생성 흔적과 내부 구현 용어 제거**
   - 요청문을 그대로 쓴 보고서 제목, `Analysis result`, `HTML 초안`, `Artifact`, `draft`, `Assistant`, `12열 격자`, `서버에 저장` 같은 표현을 사용자 언어로 바꾼다.
   - 합성 데이터와 AI 생성 고지는 삭제하지 않고 한 번만 명확하게 제공한다.
4. **실패 후 행동과 드래그 대체 수단 제공**
   - 오류에는 `다시 시도`, `원본 다시 연결`, `블록 삭제` 등 복구 행동을 붙인다.
   - 드래그만으로 이동하게 하지 않고 클릭 추가, 이동 메뉴, 키보드 조작과 결과 안내를 함께 제공한다.

중간발표 피드백은 **방향과 설계 반영도는 높지만 완료 증거가 부족하다.** 현재의 일괄 `반영` 표기를 그대로 사용하면 구현과 검증을 혼동할 위험이 있다. 네 항목 모두 최종 발표에서는 `부분 반영` 또는 `설계·구현 반영, 동일 릴리스 실증 필요`로 표현하는 것이 정확하다.

---

## 2. 조사 범위와 판정 방법

### 2.1 조사한 화면과 상태

- 보고서 목록과 보고서 상태 표현
- 보고서 편집 화면
- 좌측 블록·분석 원본 패널
- 선택·비선택 블록
- Markdown 본문 편집 도구
- 블록 이동 손잡이·더보기·크기 조절점
- 보고서 미리보기
- 확정본 열람
- 단축키 도움말
- 모바일 블록 도구 overlay
- `320, 375, 600, 768, 1024, 1180, 1440px` viewport의 레이아웃·오버플로
- 키보드 focus와 dialog 배경 접근 가능 여부
- 사용자 노출 문구와 오류·복구 문구

### 2.2 증거 표기

| 표기 | 의미 |
|---|---|
| `P` | Playwright에서 실제 표시·DOM·크기·focus를 확인 |
| `I` | 사용자가 제공한 이미지에서 확인 |
| `S` | 현재 소스의 사용자 노출 문자열·컴포넌트 계약에서 확인 |
| `D` | 제품 기준 문서와 PRD에서 확인 |

### 2.3 우선순위

| 우선순위 | 기준 |
|---|---|
| `P0` | 핵심 작업을 완료하지 못하거나, 오조작·데이터 상태 혼동·중대한 접근성 차단을 일으킴 |
| `P1` | 작업은 가능하지만 레이아웃 파손, 상태 혼동, 복구 불가 또는 높은 인지 비용을 일으킴 |
| `P2` | 문구·일관성·발견성·시각적 완성도를 떨어뜨림 |
| `P3` | 후속 polish 또는 고급 편의 기능 |

### 2.4 조사 한계

- 이번 조사는 사용자 요청대로 읽기 중심으로 진행했다.
- 보고서 생성·저장·확정·재실행의 네트워크 mutation은 실행하지 않았다.
- 실제 배포 Runtime과 현재 checkout commit이 다르므로, 화면에서 확인한 사실과 현재 소스에서 확인한 사실을 같은 것으로 합치지 않았다.
- `전수조사`의 의미는 위에 적은 화면·상태·viewport·문구 범위의 전체 조사다. 모든 데이터 형태, 브라우저 엔진, 운영 권한 조합을 검증했다는 뜻은 아니다.

---

## 3. 보고서 UI/UX 전수조사

### 3.1 편집·미리보기·확정 상태

| ID | 우선순위 | 확인된 문제 | 근거 | 개선 방향 | 완료 기준 |
|---|---:|---|---|---|---|
| MODE-01 | P0 | 미리보기 문서 위에 블록 이동 손잡이, 더보기, 크기 조절점 또는 편집 도구가 남을 수 있다. 사용자는 문서를 보는 중인지 편집 중인지 구분하기 어렵다. | P, I-3~5 | 미리보기 renderer를 편집 DOM과 분리하거나 모든 editor chrome을 구조적으로 제외한다. | 미리보기 DOM에 drag handle, resize handle, block menu, formatting toolbar, selection outline이 0개다. |
| MODE-02 | P1 | Markdown 블록마다 `편집/미리보기` 전환이 표시되어 문서 전체의 편집·미리보기 상태와 충돌한다. | I-4, I-5 | 문서 수준에서만 편집/미리보기를 전환한다. 블록은 선택 시 편집되고 document preview에서는 결과만 렌더링한다. | 블록마다 반복되는 모드 전환이 없고 현재 문서 모드가 상단에서 한 번만 표시된다. |
| MODE-03 | P1 | 미리보기에서 `HTML 초안 · 검토 단계`, `저장된 HTML 초안`, `A4 HTML 초안`처럼 같은 상태를 여러 번 설명한다. | P, S: `ReportDocumentView.jsx` | `확정 전 검토`와 `보고서 내용을 확인하세요`로 축약한다. | 상태명·제목·설명이 서로 다른 정보를 제공하며 `초안` 반복은 한 영역당 1회 이하이다. |
| MODE-04 | P1 | 확정본에서 `PDF 확정본·수정 불가`, `안전하게 보관`, `변경되지 않음`, `새 버전` 안내가 중복된다. | P, S: `ReportDocumentView.jsx:63-69` | `확정된 보고서입니다. 수정하려면 새 버전을 만드세요.` 한 문장으로 통합한다. | 확정 상태·불변성·다음 행동을 한 영역에서 한 번만 설명한다. |
| MODE-05 | P1 | 확정본에서도 용지 방향 control이 disabled 상태로 노출되어 행동 가능한 옵션처럼 보인다. | S: `ReportDocumentView.jsx:52` | 확정본에는 방향 값을 읽기 전용 정보로 표시하고 control을 제거한다. | disabled 편집 control 없이 `A4 가로/세로` 정보만 표시한다. |
| MODE-06 | P1 | `보고서 실행`이 새 데이터를 조회하는지, 배포하는지, PDF를 다시 만드는지 알 수 없다. | P, S: `ReportDocumentView.jsx:52` | 실제 동작 검증 후 `최신 데이터로 다시 생성` 또는 정확한 결과 중심 동사로 명명한다. | 버튼만 읽어도 실행 결과와 새 Run 생성 여부를 예측할 수 있다. |
| MODE-07 | P2 | 목록의 `열람`, 편집기의 `Preview`, 확정 화면의 `확정 HTML 열기`가 같은 계열 행동에 다른 용어를 쓴다. | P, S | 초안은 `미리보기`, 확정본은 `열기`로 상태별 표준을 정한다. | 같은 상태·동작에 동일 label을 사용한다. |
| MODE-08 | P2 | `확정하고 PDF 생성` 계열 문구가 보고서 확정과 파일 생성 중 무엇이 주 행동인지 혼동시킨다. | S: `useReportsPageController.jsx:300` | 제품의 주 결과가 보고서 확정이면 버튼은 `보고서 확정`, 확인 dialog에서 PDF 생성을 설명한다. | 주 버튼에는 하나의 사용자 목표만 표현된다. |

### 3.2 레이아웃·잘림·겹침·반응형

| ID | 우선순위 | 확인된 문제 | 근거 | 개선 방향 | 완료 기준 |
|---|---:|---|---|---|---|
| LAYOUT-01 | P0 | 좁은 화면에서 좌측 블록 패널이 캔버스를 덮고, 뒤 문서의 텍스트와 편집 도구가 잘린다. | P, I-3 | desktop은 좌측 고정 panel, tablet/mobile은 modal drawer로 분리한다. drawer가 열리면 배경을 inert 처리한다. | 320~768px에서 panel과 캔버스가 동시에 조작 가능한 상태로 겹치지 않는다. |
| LAYOUT-02 | P0 | 좁은 viewport에서 상단 명령, 제목, 저장 상태 또는 A4 canvas가 화면 밖으로 넘어가며 페이지 전체 수평 스크롤이 발생할 수 있다. | P | 명령을 우선순위별로 줄이고 secondary action은 `더보기`로 접는다. A4만 내부 scroll container를 사용한다. | 각 조사 viewport에서 `document.body.scrollWidth <= innerWidth`이고 모든 상단 핵심 명령에 접근 가능하다. |
| LAYOUT-03 | P1 | 부유 이동 손잡이·더보기 버튼이 블록 상단과 서식 toolbar를 덮는다. | I-4, I-5 | handle과 menu를 블록 좌측 gutter에 정렬하고 선택·hover·focus 규칙을 통일한다. | control hitbox가 본문·toolbar·테두리와 겹치지 않는다. |
| LAYOUT-04 | P1 | 선택 블록의 resize handle이 캔버스 바깥으로 튀어나오거나 외곽선과 겹친다. | I-5 | handle을 block bounds 안쪽 또는 reserved gutter에 배치하고 canvas clipping을 고려한다. | 모든 zoom·viewport에서 handle 전체가 보이고 클릭 영역이 잘리지 않는다. |
| LAYOUT-05 | P1 | 분석 원본 목록 카드의 하단 chevron/control이 카드 경계 아래로 잘려 보인다. | I-1 | 카드 높이를 내용 기반으로 만들고 expand control을 행 중앙 또는 우측에 정렬한다. | 카드의 모든 icon과 focus ring이 경계 안에 표시된다. |
| LAYOUT-06 | P1 | 긴 보고서 제목과 본문이 panel 뒤 또는 viewport 우측에서 잘리며 wrap·scroll 정책이 일관되지 않다. | P, I-3 | title은 2줄 clamp+전체 tooltip, 본문은 문서 폭 안에서 wrap한다. | 긴 한글·영문·숫자 문자열로 정보 손실 없는 wrap을 통과한다. |
| LAYOUT-07 | P1 | 단축키 `Ctrl/Cmd+Y · Ctrl/Cmd+Shift+Z`가 좁은 cell에서 여러 줄로 비정상 분절된다. | P, I-7 | key combination을 각각 별도 `kbd`로 표시하고 설명 column을 유연하게 둔다. | 320px와 200% zoom에서 key·설명이 서로 겹치거나 잘리지 않는다. |
| LAYOUT-08 | P1 | 모바일 블록 도구와 단축키 dialog가 열려도 배경의 focusable control이 접근 가능해 focus가 이탈할 수 있다. | P | native `dialog` 또는 검증된 modal pattern, focus trap, `aria-modal`, background inert, Escape·focus return을 적용한다. | Tab 순환이 dialog 내부에 머물고 닫은 뒤 trigger로 돌아온다. |
| LAYOUT-09 | P2 | 페이지 번호가 상단 진행값, canvas label, 문서 header, footer 등 최대 네 번 노출된다. | P | 편집 화면에는 navigator 한 곳, 출력 문서에는 footer 한 곳만 둔다. | 동일 viewport에서 편집용 page count와 출력용 page number가 중복되지 않는다. |
| LAYOUT-10 | P2 | A4 방향·크기 정보가 toolbar, page badge, preview metadata에서 반복된다. | P | 편집 시 toolbar 한 곳, preview 시 metadata 한 곳으로 제한한다. | 상태별 동일 정보 노출이 1회이다. |
| LAYOUT-11 | P2 | undo/redo가 큰 icon-only button으로 분리되어 공간을 많이 쓰고 의미를 즉시 읽기 어렵다. | I-2 | desktop은 compact group+tooltip, 좁은 화면은 `더보기` 또는 keyboard hint에 넣는다. | visible/accessible name이 일치하고 핵심 action보다 시각적 우선순위가 낮다. |
| LAYOUT-12 | P2 | 도움말만 짙은 dark modal을 사용해 다른 보고서 UI와 시각 체계가 끊긴다. | I-7 | 공통 dialog token, radius, shadow, color, typography를 사용한다. | light/dark theme 각각 공통 modal과 동일 token을 사용한다. |

### 3.3 정보구조·좌측 블록 패널

| ID | 우선순위 | 확인된 문제 | 근거 | 개선 방향 | 완료 기준 |
|---|---:|---|---|---|---|
| IA-01 | P1 | `보고서 구성 → 블록 추가 → 추가할 항목`이 좁은 panel에서 같은 의미를 반복한다. | P | 좌측 panel 제목을 `블록 추가`로 고정하고 `클릭하거나 끌어와 추가하세요` 한 줄만 제공한다. | panel 상단에 제목·설명·검색 외 중복 heading이 없다. |
| IA-02 | P1 | 분석 원본 선택과 해당 원본의 요약·KPI·차트·표 선택 관계가 목록만 보고 이해하기 어렵다. | P, I-1 | 원본을 1차 accordion, 추가 가능한 view를 2차 child list로 만들고 source 이름·기간·metric을 유지한다. | 사용자가 추가 전 `어떤 원본의 어떤 표현`인지 확인할 수 있다. |
| IA-03 | P1 | 여러 카드가 `객실 매출`처럼 같은 제목을 반복해 기간·호텔·분석 단위를 구분하기 어렵다. | I-1 | 카드 제목은 metric, 보조 정보는 기간·범위·출처로 구성하며 중복 시 qualifier를 붙인다. | 중복 title만으로도 최소 하나의 구분 가능한 보조 정보가 표시된다. |
| IA-04 | P1 | 선택 상태가 파란 border에 의존하고, 현재 선택한 원본과 추가 대상의 관계가 떨어져 있다. | P, I-1 | check/selected label, source summary와 child group을 함께 표시한다. | 색상 없이도 선택 상태와 대상 관계를 이해할 수 있다. |
| IA-05 | P2 | 상단 `블록` 버튼은 panel을 여는지 새 블록을 즉시 만드는지 불명확하다. | I-6 | `블록 추가` 또는 `블록 도구`로 명명하고 panel 상태를 chevron으로 표시한다. | label만으로 결과가 분명하며 `aria-expanded`가 상태를 전달한다. |
| IA-06 | P2 | 검색 placeholder의 `블록·본문·분석 결과 검색`은 검색 범위와 결과 동작을 한 번에 이해하기 어렵다. | S | 좌측 library는 `추가할 블록 검색`, 문서 검색은 별도 기능으로 분리한다. | 한 검색창은 하나의 정보 집합만 검색한다. |
| IA-07 | P2 | `분석 원본`, `추가할 분석 요소`, `선택한 원본`이 개발 데이터 모델을 따라가며 사용자 작업 언어가 아니다. | P | `분석 결과 선택`, `추가할 내용`, `선택한 분석 결과`로 통일한다. | 한 개념에 한 용어만 사용한다. |
| IA-08 | P2 | panel에 빈 상태·출처 없음·시간 기준 없음이 여러 줄 누적되어 실제 선택 action을 밀어낸다. | S: `ReportToolPanel.jsx:120` | 핵심 결손 하나만 표시하고 자세한 metadata는 펼침 정보로 이동한다. | empty/partial 상태에서 주 행동이 첫 viewport에 보인다. |

### 3.4 블록 편집·드래그앤드롭·Markdown

| ID | 우선순위 | 확인된 문제 | 근거 | 개선 방향 | 완료 기준 |
|---|---:|---|---|---|---|
| EDIT-01 | P0 | 이동이 drag 중심이며 drag가 어려운 사용자에게 동일 결과를 만드는 명확한 single-pointer 대체 수단이 부족하다. | P, S | `더보기`에 `위로 이동`, `아래로 이동`, `페이지로 이동`을 제공하고 click-add를 유지한다. | 모든 drag 결과를 drag 없이 클릭/탭으로 달성한다. |
| EDIT-02 | P1 | drag handle·drag 가능 영역·drop 가능 위치가 항상 명확하지 않다. | P, I-4~5 | primary draggable에는 일관된 handle, `cursor: grab`, hover/focus background를 제공한다. | 조작 전 draggable과 handle을 시각·키보드로 식별한다. |
| EDIT-03 | P1 | drag 중 최종 위치를 예측할 수 있는 drop indicator와 target feedback이 약하다. | P | 2px insertion line, target highlight, 간결한 drag preview를 사용한다. | drop 전 before/after/page target이 시각적으로 분명하다. |
| EDIT-04 | P1 | 키보드 이동은 `Space/Enter`, 방향키, `12열 격자`라는 내부 규칙을 알아야 해 발견성이 낮다. | P, I-7, S: `ReportShortcutHelp.jsx:12-14` | 이동 메뉴를 기본 대체 수단으로 제공하고 keyboard shortcut은 고급 기능으로 둔다. | 도움말을 열지 않아도 keyboard 또는 menu로 이동을 시작할 수 있다. |
| EDIT-05 | P1 | 이동 완료 후 새 위치·순서를 설명하는 screen-reader feedback이 충분히 검증되지 않았다. | P | live region으로 block명, 이전/새 위치, 페이지를 알리고 focus를 trigger에 유지한다. | 이동 뒤 screen reader가 결과를 한 번만 읽고 다음 이동을 계속할 수 있다. |
| EDIT-06 | P1 | Markdown 본문 toolbar가 block handle·menu와 겹치며 content 영역보다 control이 더 두드러진다. | I-4, I-5 | 텍스트 선택 시 inline toolbar, 블록 선택 시 block action만 표시한다. 두 계층을 분리한다. | selection state마다 필요한 한 종류의 toolbar만 표시된다. |
| EDIT-07 | P1 | Markdown visual mode가 있는데 블록별 `편집/미리보기`가 반복되어 사용자 mental model이 복잡하다. | I-4, I-5 | visual editor를 기본으로 하고 Markdown syntax 입력을 지원한다. raw Markdown이 필요하면 문서 또는 block의 명시적 advanced action으로 제공한다. | 사용자에게 동시에 두 개의 preview 개념이 나타나지 않는다. |
| EDIT-08 | P1 | resize handle은 시각적이지만 정확한 크기·최소/최대·snap 결과가 설명되지 않는다. | P, I-5 | resize 중 column/size preview, min/max, invalid state를 표시한다. menu에 preset width를 제공한다. | pointer 없이도 폭 preset을 선택할 수 있고 invalid drop이 저장되지 않는다. |
| EDIT-09 | P2 | `블록 자동 정돈`과 `12열 계약`이 사용자 목적보다 내부 grid를 설명한다. | S: `ReportEditorToolbar.jsx:57`, `useReportDraftState.ts` | `레이아웃 정리`로 명명하고 `겹친 블록을 순서대로 정리합니다.`처럼 결과를 설명한다. | label과 성공 안내에서 `12열`, `계약`을 제거한다. |
| EDIT-10 | P2 | 다중 선택이 `Shift+클릭` hint에 의존하고 선택 범위·해제 방법이 상시 보이지 않는다. | S: `ReportBuilderV2.jsx:107` | 선택 상태에서 contextual count와 `선택 해제`를 제공한다. | mouse와 keyboard 모두 다중 선택·해제를 완료한다. |
| EDIT-11 | P2 | 빈 canvas 안내가 `왼쪽 편집 도구에서 템플릿`이라고 설명하지만 현재 panel 용어와 맞지 않는다. | S: `ReportEditorCanvas.jsx:33` | `왼쪽에서 블록을 선택하거나 끌어와 시작하세요.`로 통일한다. | 빈 상태 용어가 실제 panel heading과 같다. |
| EDIT-12 | P2 | source 기반 block과 일반 text block의 추가 방식이 서로 다른데 하나의 `블록 추가` 아래에서 차이가 명확하지 않다. | P | `내용`과 `분석 결과` 두 group으로 나누되 같은 click/drag 규칙을 사용한다. | block type별 기대 결과와 필요 source를 추가 전에 알 수 있다. |

### 3.5 오류·빈 상태·복구

| ID | 우선순위 | 확인된 문제 | 근거 | 개선 방향 | 완료 기준 |
|---|---:|---|---|---|---|
| ERR-01 | P0 | `이 블록의 분석 데이터를 불러오지 못했습니다`와 `요청한 리소스를 찾을 수 없습니다`가 겹치지만 복구 action이 없다. | P, S: `ReportArtifactContent.jsx:106-107` | 하나의 원인 중심 오류로 합치고 `다시 시도`, `원본 다시 연결`, `블록 삭제`를 상황별 제공한다. | 오류마다 최소 하나의 유효한 다음 행동이 있다. |
| ERR-02 | P1 | backend/API `Error.message`가 사용자에게 직접 노출될 수 있어 내부 문구·영문·민감 정보가 섞일 위험이 있다. | S: `reportPageLabels.ts` | typed error code→승인된 사용자 문구로 매핑하고 unknown은 안전한 fallback으로 닫는다. | raw exception·stack·SQL·identifier가 UI에 노출되지 않는다. |
| ERR-03 | P1 | `원본을 임의로 해석하지 않았습니다`는 시스템 정책을 설명하지만 사용자가 무엇을 해야 하는지 알려주지 않는다. | S: `ReportArtifactContent.jsx:138` | `표 데이터가 없어 이 블록을 표시할 수 없습니다.`와 복구 action으로 바꾼다. | 오류 문구가 상태·원인·다음 행동을 순서대로 전달한다. |
| ERR-04 | P1 | 이전 합본 분석 요소 오류가 내부 migration 용어 중심이며 재구성 과정이 길다. | P | `이전 형식의 분석 블록입니다.`와 `블록 다시 구성` CTA를 제공한다. | 한 번의 CTA에서 가능한 새 block 선택으로 이동한다. |
| ERR-05 | P1 | 저장 분석 보관함 부분 실패 문구가 길고 제외 수·기존 연결 사용 가능 여부를 한 문단에 섞는다. | S: `useReportArtifacts.ts:100-146` | 상단 alert에는 결과와 행동만, 세부 제외 수는 펼침 정보로 둔다. | alert 첫 문장으로 현재 할 수 있는 일을 알 수 있다. |
| ERR-06 | P2 | `다른 블록은 계속 확인할 수 있습니다`는 사실이지만 해당 오류를 해결하지 못한다. | S: `ReportArtifactContent.jsx:107` | 오류 block 복구 action을 우선하고 문서 전체 영향은 보조 설명으로 둔다. | 오류 card의 primary content가 복구 방법이다. |
| ERR-07 | P2 | `오류가 아니라 유효한 빈 분석 결과입니다`는 방어적이고 기계적인 표현이다. | S: `ReportArtifactContent.jsx:123` | `조건에 맞는 데이터가 없습니다.`와 기간·필터 변경 action을 제공한다. | empty와 error를 badge·icon·action으로 구분한다. |
| ERR-08 | P2 | 15초 timeout 문구가 기술 숫자를 강조하고 재시도 외 원인·대체 경로가 없다. | S: `useFinalReportDocument.ts:88` | `확정 문서를 불러오지 못했습니다.`를 기본으로 하고 필요할 때만 timeout 세부 정보를 표시한다. | 사용자는 기술 시간 제한을 몰라도 복구할 수 있다. |

---

## 4. AI 티·불필요한 글씨·UX Writing 전수조사

### 4.1 삭제가 아니라 정리해야 하는 원칙

- **삭제 대상:** 구현 세부, 개발자 모델명, 기계 번역, 요청문 복사, 같은 상태의 반복, 행동 없는 정책 문구.
- **유지 대상:** 합성 데이터, AI 생성 초안, 확정본 불변성, 권한·출처와 같은 신뢰 고지.
- **표현 방법:** 중요한 고지는 페이지당 한 번, 짧고 구체적으로 제공한다. 세부 기술 정보는 `기술 정보` 또는 `자세히`에 접는다.

### 4.2 문구별 수정안

| ID | 유형 | 현재 문구·패턴 | 문제 | 권장 문구·규칙 |
|---|---|---|---|---|
| COPY-01 | AI 생성 흔적 | `2026년 7월 호텔별 운영매출 보여줘 보고서` | 자연어 요청문이 제목에 그대로 남음 | `2026년 7월 호텔별 운영매출 보고서`. `보여줘/알려줘/분석해줘/표로도` 같은 요청 동사는 제목에서 제거한다. |
| COPY-02 | AI 생성 흔적 | `표로도 보여줘 보고서` | 맥락 없는 후속 발화를 제목으로 복사 | metric·기간·view를 조합한 `호텔별 운영매출 상세 보고서` |
| COPY-03 | 영문 fallback | `Analysis result 요약/차트/데이터` | 자동 생성 기본값과 영문이 노출 | `7월 운영매출 요약`, `호텔별 운영매출`, `운영매출 상세 데이터`처럼 metric 기반으로 결정론적 생성 |
| COPY-04 | 언어·단위 불일치 | `Room Revenue`/`객실 매출`, `KRW`/`원` | 같은 개념을 혼용 | locale별 한 언어와 한 단위 규칙 사용. 한국어 UI 기본은 `객실 매출`과 `원/억 원` |
| COPY-05 | 기계적 서술 | 기간·호텔·모든 금액·합계·최고·최저를 한 문장에 나열 | 읽기 어렵고 AI 요약처럼 보임 | `7월 운영매출은 331.1억 원입니다. GRAND가 189.7억 원으로 가장 높았습니다.`처럼 결론 우선, 상세 값은 표로 분리 |
| COPY-06 | 과도한 데이터 수식 | `2026년 7월 기준 합성 통합 운영매출은 총 ... KRW입니다.` | `기준/합성/통합/총`이 한 문장에 누적 | 합성 여부는 badge 한 곳에서 고지하고 본문은 `7월 운영매출은 ...원입니다.` |
| COPY-07 | AI 반복 | `AI 초안 만들기`, `AI 초안 지시`, `AI 초안 생성`, `AI 초안 검토 필요` | 한 작업에서 AI를 네 번 반복 | 기능명 `초안 만들기`, field `작성 요청`, button `초안 만들기`. 한 번만 `AI가 만든 초안입니다. 확정 전 내용을 확인하세요.` |
| COPY-08 | 내부 검증 용어 | `AI 검증 근거` | 사용자에게 검증 방식처럼 보이나 실제 의미가 모호 | `연결된 분석 결과` 또는 `출처` |
| COPY-09 | 내부 제품명 | `Assistant에 전달합니다` | 내부 component/영문 노출 | `작성 도우미에 사용됩니다.` |
| COPY-10 | 내부 상태 | `현재 draft를 서버에 저장` | 영문·저장 구현 노출 | `현재 초안 저장` |
| COPY-11 | 내부 포맷 | `HTML 초안`, `HTML 편집 초안` | 사용자가 알 필요 없는 renderer 형식 | `보고서 미리보기`, `편집 중` |
| COPY-12 | 내부 객체 | `Artifact`, `포함 Artifact`, `원본 Artifact` | 개발 domain object 노출 | `분석 결과`, `포함된 분석 결과`, `원본 분석 결과` |
| COPY-13 | 내부 식별자 | `PDF 식별값` | 일반 사용자에게 행동 가치가 없음 | 기본 화면에서 제거하고 `기술 정보` 안에 `파일 확인 코드`로 제공 |
| COPY-14 | 내부 layout | `12열 격자`, `기존 12열 계약` | 구현 제약 노출 | `격자` 또는 `레이아웃`. 결과는 `겹친 블록을 순서대로 정리했습니다.` |
| COPY-15 | 저장 구현 | `서버에 저장` | 사용자가 저장 위치를 선택하지 않는다면 불필요 | `저장`. 동기화 상태가 필요하면 `저장됨/저장 중/저장 실패` |
| COPY-16 | 반복 label | 모든 제목 위 `보고서 섹션` | 실제 heading을 반복해 정보 밀도 저하 | 제거하고 block title 자체를 heading으로 사용 |
| COPY-17 | 내부 근거 label | `근거 · Artifact 요약` | 기술 lineage를 그대로 노출 | `출처: 분석 요약` 또는 `출처` details |
| COPY-18 | 버전 표기 | `v1`, `v2` | 비개발자에게 의미가 약함 | 목록·확정 안내는 `버전 1`. 공간이 좁은 기술 정보에서만 `v1` 허용 |
| COPY-19 | 과장·중복 | `확정된 문서를 안전하게 보관하고 있습니다` | 안전성 주장을 증명하지 않으며 상태 설명이 중복 | `확정된 보고서입니다. 수정하려면 새 버전을 만드세요.` |
| COPY-20 | 모호한 상태 | `확정본 없음` | 사용자가 할 수 있는 행동이 없음 | 보관 상태라면 `복원 후 열람 가능` 등 실제 다음 행동 표시 |
| COPY-21 | 모호한 label | `근거 연결`, `근거 변경` | 무엇을 연결·변경하는지 불분명 | `출처`, `사용할 분석 결과 변경` |
| COPY-22 | 장황한 AI 진행 | `근거를 유지하며 검토할 변경안을 준비하고 있습니다.` | 기계적이고 불필요한 정책 설명 | `변경안을 만드는 중입니다.` |
| COPY-23 | 장황한 AI 완료 | `현재 근거 자료로 만들 수 있는 변경안을 준비했습니다. 적용 전에 검토해 주세요.` | `근거/준비` 반복 | `변경안이 준비되었습니다. 적용할 내용을 확인하세요.` |
| COPY-24 | 불필요한 heading | `종합 편집 근거 선택` | 내부 architecture 용어 | `사용할 분석 결과 선택` |
| COPY-25 | 상태 중복 | 목록의 `초안`과 `편집 중` | 같은 상태를 두 column에서 반복 | 상태 badge와 최근 수정 시각만 표시 |
| COPY-26 | 장황한 상시 도움말 | `초안은 자유롭게 배치하고 서버에 저장할 수 있습니다. 확정본 편집 시 새 버전 초안이 생성됩니다.` | 개발 설명이 목록마다 노출 | 상시 문구는 제거. 확정본에서 편집을 누를 때 `새 버전이 만들어집니다.`를 contextual 안내 |
| COPY-27 | 장황한 빈 상태 | `새 초안을 만들면 서버에 저장되고 편집 화면으로 바로 이동합니다.` | 당연한 전환과 구현 세부를 설명 | `새 보고서를 만들고 편집을 시작하세요.` |
| COPY-28 | 필요한 고지 | `실제 호텔 운영 데이터가 아닌 교육·시연용 결과입니다.` | 삭제하면 신뢰·윤리 문제가 생김 | 유지하되 report/page 상단 badge 한 곳에서 명확히 표시하고 본문마다 반복하지 않는다. |
| COPY-29 | 필요한 고지 | `생성 결과는 AI 초안이며 확정 전에 검토가 필요합니다.` | 의미는 필요하지만 여러 번 반복 | AI 생성 직후 또는 확정 전 한 번만 `AI가 만든 초안입니다. 확정 전 내용을 확인하세요.` |
| COPY-30 | 접근성 이름 | icon-only `보기` 또는 빈 summary 이름 | 시각 context 없이는 목적을 알 수 없음 | visible label `보기 설정` 또는 정확한 `aria-label`. visible label과 accessible name을 일치시킨다. |

### 4.3 UX Writing 금칙·검사 규칙

일반 사용자 화면에서 다음 문자열이 새로 추가되면 review를 실패시키는 정적 검사를 권장한다.

`Artifact`, `draft`, `Assistant`, `HTML 초안`, `서버에 저장`, `12열 계약`, `Analysis result`

예외는 개발자용 `기술 정보` 영역과 log/test fixture다. `AI`, `합성 데이터`, `PDF`, `A4`, `Markdown`은 무조건 금지하지 않고 실제 사용자 목적과 법적·윤리적 고지에 필요한 위치에서만 사용한다.

---

## 5. 도움말·접근성 조사

| ID | 우선순위 | 문제 | 개선 및 검증 기준 |
|---|---:|---|---|
| A11Y-01 | P0 | drag 동작에 single-pointer 대체 수단이 불명확하다. | 각 block menu에 이동 action을 제공하고 drag 없이 같은 결과를 만들 수 있어야 한다. |
| A11Y-02 | P0 | mobile tool drawer·shortcut dialog가 배경 focus를 완전히 차단하지 못할 수 있다. | `aria-modal`, inert, focus trap, Escape, trigger focus return을 자동화 검증한다. |
| A11Y-03 | P1 | 320px·고배율에서 shell control과 안내 문구가 reflow하지 않고 수평으로 넘어간다. | A4 canvas 자체는 2차원 layout 예외가 가능하지만 app shell·dialog·text는 320 CSS px에서 정보·기능 손실 없이 reflow해야 한다. |
| A11Y-04 | P1 | drag 결과를 screen reader가 확인하기 어렵다. | block명·이전/새 위치를 live region으로 한 번 안내하고 focus를 유지한다. |
| A11Y-05 | P1 | icon-only button과 빈 accessible name이 존재할 수 있다. | 모든 focusable control의 이름을 검사하고 visible label이 있으면 accessible name과 일치시킨다. |
| A11Y-06 | P1 | 파란 border만으로 선택·drop target을 표현한다. | icon, label, shape/indicator를 함께 사용하고 색상만으로 상태를 전달하지 않는다. |
| A11Y-07 | P2 | 도움말이 내부 용어 중심이고 긴 shortcut을 한 cell에 압축한다. | `단축키` 제목, 작업별 group, OS별 key 표시, 고급 layout shortcut은 `고급` section으로 이동한다. |
| A11Y-08 | P2 | 도움말의 설명 `입력창 밖에서...`가 길고 예외 규칙을 먼저 설명한다. | `블록을 선택한 뒤 사용할 수 있습니다. 입력 중에는 일반 편집 키가 우선합니다.`로 단축한다. |

---

## 6. 유사 서비스·Best Practice 비교와 적용 전략

이 절의 `BP`는 사용자가 요청한 Best Practice로 해석했다.

| 참고 | 확인한 패턴 | Answervice 적용 | 그대로 복사하지 않을 부분 |
|---|---|---|---|
| [Notion writing & editing](https://www.notion.com/help/writing-and-editing-basics) | block 좌측 `⋮⋮` handle, drag 중 파란 guide, sidebar reorder, slash/plus block menu | handle을 좌측 gutter에 통일하고 drop 위치를 명확히 표시한다. block library를 좌측에 둔다. | 자유 문서 editor처럼 무제한 nesting하지 않는다. 보고서는 A4·근거·승인 계약을 유지한다. |
| [GitBook blocks](https://gitbook.com/docs/creating-content/blocks) | block 왼쪽 `+`, `/` insert palette, keyboard 검색·삽입, block 단위 선택·이동 | click-add를 기본으로 하고 Markdown text에서 `/` command palette를 보조 입력으로 제공한다. | 문서 출판 workflow를 그대로 가져오지 않고 분석 source 연결을 별도 group으로 유지한다. |
| [GitBook Markdown](https://gitbook.com/docs/creating-content/formatting/markdown) | visual editor에서 Markdown syntax를 keyboard-friendly 입력 방식으로 지원 | visual editing을 기본으로 하되 heading/list/quote/link 등 Markdown typing shortcut을 지원한다. | 사용자에게 raw Markdown과 block preview를 동시에 강요하지 않는다. |
| [GitBook quickstart](https://gitbook.com/docs/getting-started/quickstart) | editing과 published preview를 명확히 분리 | document preview를 clean renderer로 만들고 editor chrome을 제거한다. | Git branch 개념을 일반 보고서 사용자에게 노출하지 않는다. |
| [Atlassian drag design](https://atlassian.design/components/pragmatic-drag-and-drop/design-guidelines/) | drag 가능성 표시, 단순 preview, 명확한 drop indicator, action menu 이동 | 항상/hover handle 규칙, insertion line, 최대 3개 정보의 drag preview, `더보기` 이동 action을 사용한다. | 방향키만을 기본 대체 수단으로 삼지 않는다. |
| [Atlassian drag accessibility](https://atlassian.design/components/pragmatic-drag-and-drop/accessibility-guidelines/) | drag 대체 control, 결과 live announcement, focus 유지 | `위/아래/페이지로 이동` menu와 live region을 구현한다. | handle button과 별도 more button을 중복 배치하지 않는다. block당 action trigger는 하나로 통합한다. |
| [WCAG 2.2 Dragging Movements](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html) | drag 결과를 drag 없이 single pointer로 달성 | click-add·이동 menu·size preset을 acceptance criterion으로 둔다. | drag를 제거하지는 않는다. drag는 빠른 조작, menu는 동등한 대안으로 제공한다. |
| [WCAG Reflow](https://www.w3.org/WAI/WCAG21/Understanding/reflow.html) | 320 CSS px에서 기능·정보 손실 없는 reflow | shell·toolbar·dialog는 320px에서 단일 방향 scroll로 사용 가능하게 한다. | A4 canvas·table처럼 본질적으로 2차원인 영역은 내부 scroll을 허용하되 전체 page overflow와 구분한다. |
| [WAI accessible names](https://www.w3.org/WAI/ARIA/apg/practices/names-and-descriptions/) | 이름은 짧고 목적 중심이며 visible label을 우선 | `보기`→`보기 설정`, `블록`→`블록 추가`처럼 동작을 먼저 쓴다. | 긴 설명을 `aria-label`에 모두 넣지 않고 description으로 분리한다. |

### 6.1 권장 화면 구조

#### Desktop

```text
상단: 뒤로 | 제목·저장상태 | 미리보기 | 보고서 확정
좌측 280~320px: 블록 추가
  - 내용
  - 분석 결과
  - 검색
중앙: A4 canvas
우측 300~340px: 선택한 블록 속성
```

- 좌측 panel은 사용자 제안대로 block entry point로 고정한다.
- canvas를 덮지 않고 panel 접기 시 canvas가 넓어진다.
- block handle과 more action은 block 좌측 gutter 한 곳으로 통합한다.
- 선택한 block이 없으면 우측 panel은 접거나 document 설정만 보여준다.

#### Tablet·Mobile

- 상단 `블록 추가`가 좌측 drawer를 연다.
- drawer는 modal semantics와 자체 vertical scroll을 가진다.
- block을 click-add하면 drawer를 닫고 추가된 block으로 focus를 이동한다.
- A4는 내부 horizontal scroll 또는 fit-to-width를 제공한다.
- 핵심 action은 화면 밖으로 밀리지 않고 sticky command bar에 남긴다.

#### Preview·Final

- document content만 렌더링한다.
- 선택·drag·resize·format·block mode control은 0개다.
- preview top bar에는 `편집으로 돌아가기`, `보고서 확정`만 둔다.
- final top bar에는 `새 버전으로 편집`, `열기/다운로드`와 실제 의미가 확인된 재실행 action만 둔다.

### 6.2 권장 block 상호작용

1. 좌측 library를 클릭하면 현재 page의 다음 안전 위치에 block을 추가한다.
2. drag는 빠른 배치를 위한 보조 방식이다.
3. drag 시작 전 handle과 draggable 상태가 보인다.
4. drag 중 insertion line·target highlight·간결한 preview가 보인다.
5. drop 후 위치를 announce하고 focus를 유지한다.
6. `더보기`에서 drag 없이 이동·복제·삭제할 수 있다.
7. Markdown text는 visual editor에서 `/`, `#`, `-`, `>` 등 syntax shortcut을 지원한다.
8. preview에서는 위 control을 전부 제거한다.

---

## 7. 수정 우선순위와 인수 기준

### P0 — 상태 혼동·작업 차단 제거

1. preview/final에서 editor chrome 완전 제거
2. 320~768px panel overlay·전체 page horizontal overflow 해결
3. mobile drawer·shortcut dialog focus containment
4. drag의 click/menu 대체 수단
5. block 오류에 recovery action 제공

### P1 — 편집 흐름 재구성

1. 좌측 block library 고정·접기 구조
2. source→추가할 view의 2단 hierarchy
3. drag handle·drop indicator·live announcement
4. Markdown block toolbar와 block action 계층 분리
5. title·본문·shortcut wrapping과 clipping 해결
6. draft/preview/final 상태별 action label 통일

### P2 — AI 티·문구·시각 체계 정리

1. 요청문 기반 제목 normalization
2. `Analysis result` 등 fallback 제거
3. `Artifact/draft/Assistant/HTML/서버/12열` 사용자 노출 제거
4. AI·합성 데이터 고지 1회 원칙
5. 반복 page/version/status 문구 축소
6. 도움말을 공통 dialog UI로 통일

### 자동화 인수 기준

- viewport matrix: `320, 375, 600, 768, 1024, 1180, 1440px`
- 각 viewport에서 app shell body horizontal overflow 0
- preview/final의 editor-only selector 수 0
- modal open 중 외부 focusable 접근 0, close 후 trigger focus 복귀
- drag 없이 block 추가·재배치·크기 preset 선택 가능
- drag 완료 live message에 block명·새 위치 포함
- user-facing string에서 금칙 내부 용어 0
- 보고서 제목 normalization fixture 통과
- 한국어 locale에서 동일 metric·currency 표기 일관
- error/empty state마다 상태 구분과 유효한 다음 action 존재

---

## 8. 중간발표 피드백 평가

### 8.1 전체 평가

| 관점 | 평가 |
|---|---|
| 문제 정의·스토리텔링 | 강점이다. 데이터 사일로→업무 정의→안전한 분석→보고서라는 연결이 명확하다. |
| 기술 설계 | 강점이다. DataHub, RuntimeCatalogProjection, APP-G1/G2/G3, SQLGlot, Trino, Report lineage의 신뢰 경계가 구체적이다. |
| 코드 골격 | 상당 부분 존재한다. metadata search, context binding, SQL guard, query execution, result artifact, report replay 경로가 확인된다. |
| 실제 통합 증거 | 부족하다. PRD 기준 `P0-E2E-REAL`, `P0-REPORT-RERUN`, `P0-SECURITY`, `P0-FAILURE`가 아직 차단 상태다. |
| 정량 검증 | 가장 큰 공백이다. `P0-QUANT`와 held-out 기준선·threshold가 완료되지 않았다. |
| 현재 `반영` 표기 | 과도하다. `부분 반영`, `READY_TO_VERIFY`, `BLOCKED`를 구분해야 한다. |

핵심 평가는 **“설계는 매우 좋고 구현 경로도 상당히 연결됐지만, 동일 릴리스의 실환경 증거와 정량 지표가 설계를 따라오지 못하고 있다”**이다.

사용자가 정리한 기존 답변 문장 자체는 남은 공백을 비교적 솔직하게 적었다. 문제는 모든 행의 상태를 `반영`으로 묶은 부분이다.

| 항목 | 기존 답변 문장 평가 | 상태 수정 |
|---|---|---|
| ① E2E | 실제 DataHub·Trino E2E와 보고서 재실행이 남았다고 적은 점은 정확하다. 다만 앞 문장의 `흐름을 연결함`이 실환경 연결 완료로 읽힐 수 있다. | `부분 반영 — 코드 경로 존재, L3 미검증` |
| ② KPI·Re-planning | Glossary·Context와 G2 1회 보정 범위를 제한한 점은 정확하다. 이것을 일반적인 Agent Re-planning으로 확대해 부르면 과장이다. | `부분 반영 — KPI context/G2 repair, 기타 실패 replan 미구현` |
| ③ 사용자·역할·지표 | 역할 경계와 미측정 지표를 인정한 점은 좋다. 다만 `C-level 핵심 사용자`와 현재 P0 actor가 일치하는지 명시해야 한다. | `부분 반영 — 경계 구현, 타깃·정량 실증 보완` |
| ④ Cross-domain·거버넌스 | 남은 실조회·민감정보·부분실패·지표를 적은 점은 정확하다. native semantic shadow와 Neo4j가 runtime 구현처럼 읽히지 않게 해야 한다. | `부분 반영/설계 반영 — live federation·masking·Neo4j 미검증/미구현` |

### 8.2 피드백 ① — 전체 E2E Pipeline

#### 현재 판정

**부분 반영 — 코드 경로 존재, 동일 릴리스 실제 E2E와 보고서 재실행은 미검증**

#### 확인된 구현

- 질문 기반 bounded DataHub asset search와 entitlement/release 재결속:
  - `app/backend/app/services/analysis/stages/context_stage.py:80-103, 226-243`
- active RuntimeCatalogProjection·DataHub Search·TLS Trino 조립:
  - `app/backend/app/api/analysis_router_runtime.py:33-39`
- G1→typed/server compiler·G2 AST guard:
  - `app/backend/app/services/analysis/stages/plan_stage.py:167-171, 246-254`
- Trino 실행과 query ID·G3 evidence 처리:
  - `app/backend/app/services/analysis/stages/query_stage.py:80-106, 248-292`
- G3 이후 table/chart용 Artifact 생성:
  - `app/backend/app/services/analysis/stages/result_stage.py:158-203`
- 저장 분석과 승인 보고서 block별 fresh replay:
  - `app/backend/app/api/router.py:401-493`
  - `app/backend/app/services/report/execution.py:112-254, 339-384`
  - `app/backend/app/api/report_router.py:596-629`

#### 남은 공백

- PRD `ANL-007` 실제 Trino query ID·통계·실행 시간은 `BLOCKED`.
- `P0-E2E-REAL`과 `P0-REPORT-RERUN`은 `BLOCKED`.
- test double·fixture·mock 기반 test는 L1 계약 증거이며 실제 DataHub·Trino·Source DB E2E가 아니다.
- browser에서 본 표·차트·보고서가 같은 Artifact·query ID·checksum을 유지한다는 same-release receipt가 없다.

#### 최종 발표 전 최소 증거

1. `cached=false` 실제 질문 1건의 browser network→request ID→analysis run→Trino query ID→Artifact→UI 연결
2. 같은 Artifact의 요약·표·차트·보고서 값·기간·출처 checksum 일치
3. 승인 보고서 수동 재실행에서 block마다 새 Analysis Run·query ID·result Artifact 생성
4. 재실행 권한, release conflict, ViewSpec 불일치, idempotency retry, restart 복원 negative case

### 8.3 피드백 ② — KPI·업무 맥락과 Agent Re-planning

#### 현재 판정

**부분 반영 — KPI/업무 맥락과 G2 1회 보정은 있으나 일반적인 Agent Re-planning은 아님**

#### 타당한 부분

- DataHub Glossary·Context·RuntimeCatalogProjection 기반 의미 결속 방향은 단순 Text-to-SQL보다 낫다.
- 모호한 metric·기간·자산은 확인 후 실행하는 fail-closed 계약을 둔 점이 좋다.
- APP-G2에서 허용 가능한 SQL 오류만 bounded correction 1회로 제한한 것은 안전하다.

확인된 코드·단위 계약:

- metric·기간·asset 모호성에서 clarification 반환:
  - `app/backend/app/services/analysis/stages/context_stage.py:65-103, 360-389`
- G2 위반 시 Node2 repair를 최대 1회 수행하고 재검증:
  - `app/backend/app/services/analysis/stages/plan_stage.py:246-259, 330-376`
- 1회 repair와 unsafe SQL의 query 0건 단위 검증:
  - `tests/backend/test_analysis_pipeline.py:896-924`
- empty·evidence violation을 G3에서 typed failure로 종료:
  - `app/backend/app/services/analysis/stages/query_stage.py:254-292`
  - `tests/backend/test_analysis_pipeline.py:926-936`

#### 과장하면 안 되는 부분

- `G2 실패 시 SQL 1회 보정`을 `Agent Re-planning 구현 완료`로 표현하면 안 된다.
- Trino timeout·connector failure·empty result·data 부족·G3 evidence failure·report block partial failure에 대한 공통 replanning state machine은 구현·검증 완료 상태가 아니다.
- 권한·PII·write·미승인 JOIN 같은 policy failure는 재계획 대상이 아니라 즉시 종료해야 한다.

#### 권장 replanning 계약

| 실패 | 처리 |
|---|---|
| 질문 모호성·기간 부족 | 실행 전 사용자에게 확인, Run/Trino 0 |
| SQL 구조 오류 | 승인 context 안에서 최대 1회 보정 |
| Trino 일시 장애·timeout | 같은 SQL의 무조건 retry 금지. query 상태 확인 후 bounded retry 또는 실패 |
| 데이터 0행 | 조건·기간을 임의 변경하지 않고 `데이터 없음`으로 종료, 사용자 선택으로 새 Run |
| G3 schema/evidence 실패 | 결과를 보여주지 않고 새 query 후보가 논리적으로 유효할 때만 명시적 재계획 |
| 권한·PII·write·미승인 JOIN | 즉시 차단, retry/replan 금지 |

### 8.4 피드백 ③ — 핵심 사용자·역할·정보교환·정량 지표

#### 현재 판정

**부분 반영 — stage 책임은 분리됐지만 핵심 사용자와 정량 실증은 아직 발표에서 더 정확히 정리해야 함**

#### 핵심 사용자

현재 PRD의 P0 직접 사용자는 `analyst`와 권한 있는 `report_admin`이다. 사업책임자는 승인된 결과·보고서의 수혜자이며 직접 질의 actor가 아니다.

- 근거: `docs/product/01_PRD.md:67-73`

따라서 최종 발표에서는 다음 중 하나를 선택해야 한다.

1. **현재 구현에 맞춘 설명:** `분석가가 자연어로 안전하게 분석하고, 사업책임자가 검증된 보고서를 소비한다.`
2. **C-level 직접 사용을 주장:** 별도 역할·권한·질의 화면·승인·용어 수준·오류 복구까지 실제 구현하고 PRD를 변경한다.

현재 구현에서 2번을 주장하는 것은 근거가 부족하다.

#### 역할 경계

Planner·Metadata·Query·Validation·Report를 모두 자율 Agent라고 부르기보다 다음처럼 설명하는 편이 정확하다.

| 책임 | 현재 적절한 표현 |
|---|---|
| Planner | 제한된 stage/service |
| Metadata | DataHub Search + RuntimeCatalogProjection |
| Query | typed compiler/Node2 후보 + SQL builder |
| Validation | APP-G1/G2/G3 결정론적 gate |
| Report | Artifact lineage를 재사용하는 결정론적 service/workflow |
| Agent | 상위 capability route와 승인된 tool 조율 |

정보교환은 `질문→후보 URN→RuntimeContextPackage→SQL/Gate evidence→query ID/result→Artifact→Report block` 순서로 request/run/release/permission identifier를 보존한다는 식으로 설명해야 한다.

현재 코드의 실제 stage 경계는 `Context(G1·metadata·Node1)→Plan(Node2·G2·1회 repair)→Query(Trino·G3)→Result(Artifact)`이며 Report replay는 별도 service가 analysis controller를 호출한다.

- `app/backend/app/services/analysis/pipeline.py:41-65, 125-137`
- `app/backend/app/services/report/execution.py:237-260, 339-384`

#### 정량 지표

현재 `P0-QUANT`는 `NOT_STARTED`이며 `QA-002`의 표본·threshold·반복·승인 계약이 봉인되지 않았다.

Gold 정확도와 latency p50/p95를 계산하는 평가 utility는 존재한다.

- `evals/p0_gold_scoring.py:24-91`
- `evals/runner.py:72-133`

그러나 계산 utility의 존재는 실제 product release의 기준선·성공률·threshold가 측정됐다는 뜻이 아니다. `docs/product/01_PRD.md:260-281`은 report rerun·failure·quant Gate를 `BLOCKED/NOT_STARTED`로 두고, `docs/product/01_PRD.md:299`는 현재 P0 `VERIFIED` 완료 항목이 0개라고 명시한다.

최종 발표 전 최소 지표:

- 질문 해석 성공률·명확화율
- 승인된 SQL 구조 정확도와 금액·row Gold 일치율
- cold/warm end-to-end p50·p95
- 단계별 DataHub·model·Trino·render latency
- report rerun block 성공률·전체 성공률·Artifact 일치율
- G2 bounded recovery 성공률
- empty/timeout/cancel/G3/policy failure의 정확한 종료율
- 권한 우회·write·PII negative case 0건

### 8.5 피드백 ④ — Cross-domain·권한·민감정보·부분실패·Semantic Layer

#### 현재 판정

**부분 반영 — join·read-only·RBAC·shadow 구조는 있으나 실제 Cross-domain·masking·부분실패·semantic cutover는 미검증, Neo4j는 미구현 조건부 확장**

#### 확인된 구현

- canonical join graph와 연결 불가 시 임의 JOIN 금지:
  - `app/backend/app/adapters/query_join_graph.py:1-4, 39-62`
- 승인 edge·predicate·fan-out grain을 검사하는 SQLGlot guard:
  - `app/backend/app/services/sql_guard/join_semantics.py:71-176, 373-396`
  - `app/backend/app/services/sql_guard/guard.py:401-458`
- PMS/PostgreSQL, POS/MySQL, CRM/SQL Server, Facility/ClickHouse, Banquet/PostgreSQL용 Trino catalog 구성:
  - `infrastructure/database/trino/etc/catalog/`
- runtime role→capability와 unknown role fail-closed:
  - `app/backend/app/authorization.py:16-103`
- read-only SQL policy와 Trino SELECT-only ACL:
  - `app/backend/app/services/sql_guard/guard.py:503-529`
  - `infrastructure/database/trino/etc/access-control-rules.json:51-73`
- native semantic은 runtime authority가 아닌 shadow:
  - `infrastructure/database/datahub/native_semantic_shadow.py:226-291`
  - `infrastructure/database/datahub/native_metric_shadow.py:176-244`

#### 남은 공백

- PRD `ANL-010` Cross-domain Gold와 `ANL-007` 실제 Trino 조회가 `BLOCKED`.
- multi-catalog 설정은 연합조회 실행 성공의 증거가 아니다.
- RBAC·PII 표시 계약은 있으나 실제 field/row masking과 권한 negative L4가 완료되지 않았다.
- DataHub native semantic은 `shadow_publishable` 수준이며 runtime cutover authority가 아니다.
- 부분 실패·재시작·durable execution history의 same-release L4 증거가 없다.
- Neo4j/`graph.resolve`는 코드 구현이 아니라 Phase 10 이후 정량 gap이 있을 때만 여는 조건부 설계다.

#### 발표 시 안전한 표현

- `Cross-domain JOIN을 위한 승인 관계와 안전 검증 구조를 구현했다.`
- `실제 다중 DB 연합조회·권한·부분 실패는 동일 릴리스 E2E 증거를 추가해야 한다.`
- `DataHub native semantic은 shadow 검증 단계이며 runtime 정본 전환 전이다.`
- `Neo4j는 현재 구현이 아니라 DataHub-first 경로의 정량 한계가 입증될 때 검토하는 확장안이다.`

---

## 9. 중간발표 피드백 답변 수정안

현재 표의 `반영`을 아래처럼 고치는 것을 권장한다.

### ① E2E Pipeline

**판정: 부분 반영**

> 자연어 질문→DataHub Metadata 탐색→Context 결속→SQL 생성·APP-G1/G2 검증→Trino 실행→APP-G3→표·차트·보고서로 이어지는 코드 경로를 구성했다. 다만 동일 product release의 실제 DataHub·Trino `cached=false` E2E와 승인 보고서 재실행 receipt는 아직 완료되지 않아 최종 검증 항목으로 남아 있다.

### ② KPI·업무 맥락·Re-planning

**판정: 부분 반영**

> DataHub Glossary·Context·RuntimeCatalogProjection으로 KPI와 업무 정의를 결속하고, 모호한 질문은 실행 전에 확인하도록 구성했다. APP-G2에서 허용 가능한 SQL 오류는 최대 1회 보정하지만, Trino 장애·데이터 부족·APP-G3 실패까지 포괄하는 Agent Re-planning은 아직 후속 범위다. 권한·PII·write 위반은 재계획하지 않고 즉시 차단한다.

### ③ 사용자·역할·정보교환·정량 지표

**판정: 부분 반영**

> P0 직접 사용자는 analyst와 report_admin이며, 사업책임자는 검증된 결과·보고서의 수혜자로 정의했다. Planner·Metadata·Query·Validation·Report 책임을 stage/service와 결정론적 Gate로 분리하고 Context·SQL·query ID·Artifact·근거를 단계별로 전달한다. 질의 성공률·SQL/결과 정확도·p50/p95·보고서 재실행 성공률은 held-out 계약과 동일 릴리스 실측이 남아 있다.

### ④ Cross-domain·거버넌스·정량화

**판정: 부분 반영/설계 반영**

> 승인된 canonical join graph, DataHub native semantic shadow, Trino multi-catalog, Role/Capability, SQLGlot read-only 검증과 실행 이력 구조를 구성했다. 실제 Cross-domain 연합조회, field/row 민감정보 통제, 부분 실패·재시작, 정량 지표는 동일 릴리스 L3/L4 검증이 남아 있다. Neo4j는 구현 완료 항목이 아니라 Phase 10 이후 DataHub-first 경로의 정량 gap이 입증될 때 검토하는 조건부 확장이다.

---

## 10. 최종발표 전 권장 순서

1. **same-release Golden E2E 1개 봉인**
   - browser request, DataHub 후보·URN, product release, G1/G2, Trino query ID, G3, Artifact, UI를 연결한다.
2. **보고서 재실행 1개 봉인**
   - 승인 report의 복수 block이 fresh Run·query·Artifact를 만들고 동일 보고서에서 성공·실패 상태를 정확히 표시하게 한다.
3. **정량 평가 계약을 먼저 봉인**
   - 표본, metric, threshold, 반복 횟수, 승인자를 결과 확인 전에 고정한다.
4. **Cross-domain 실조회와 보안 negative demo**
   - 승인 JOIN 성공 1개, 미승인 JOIN/권한/PII/write 차단 각 1개를 실제 query/trace로 보인다.
5. **bounded recovery demo**
   - G2 1회 보정 성공과 재실패 종료를 보이고, policy failure는 재시도하지 않음을 보인다.
6. **UI P0 정리**
   - clean preview, 좌측 block panel, 좁은 화면 clipping, 오류 복구, drag 대체 수단을 우선한다.
7. **발표 문구의 완료 수준 정정**
   - `구현`, `단위 검증`, `동일 릴리스 실증`을 서로 다른 열로 보여준다.
8. **Neo4j는 후순위 유지**
   - 현재 DataHub-first 경로의 recall·recovery·p95 gap과 OFF/ON 순이득이 먼저다.

---

## 11. 최종 판정

### UI/UX

**현재 상태: P0/P1 개선 필요**

기능의 존재보다 사용자가 현재 상태와 다음 행동을 정확히 이해하도록 만드는 일이 먼저다. 특히 preview의 editor chrome, 좌측 panel overlay, 좁은 화면 clipping, drag 대체 수단, 오류 recovery, 내부 용어 노출은 최종 데모 전에 해결하는 편이 좋다.

### 중간발표 피드백

**평가: 방향은 정확하고 설계 품질은 높지만, `반영 완료`가 아니라 `부분 반영·검증 필요`가 정확하다.**

최종 프로젝트의 평가를 좌우할 것은 새로운 기술 이름의 추가가 아니라 다음 네 가지 실제 증거다.

1. 같은 릴리스의 실제 E2E
2. 보고서 fresh 재실행
3. Cross-domain·권한·실패의 negative evidence
4. 사전 봉인된 정량 지표

이 네 항목을 확보한 뒤에만 `완료` 또는 `VERIFIED`를 사용해야 한다.

---

## 12. 추가 요청 부록 — 2026-09-01

> 이 절은 사용자의 추가 요청을 기록하기 위해 문서 끝에만 추가했다. 1~11절의 기존 내용은 수정하지 않았다. 기존 제안과 충돌하는 경우 구현 시에는 이 절의 최신 사용자 요구를 우선 확인한다.

### 12.1 추가 이미지에서 확인한 사항

#### 추가 이미지 1 — 핵심 지표 Artifact

- `2026년 3월 1일부터 8월 29일까지`가 제목과 본문 metadata에서 반복된다.
- `분석 결과`와 `핵심 지표` badge가 실제 사용자가 읽어야 할 metric보다 먼저 노출된다.
- `객실 매출`과 `억 원`이 작은 label에 함께 들어가고 실제 값 `373.4`와 단위가 분리되어 한 번에 읽기 어렵다.
- 실제 KPI card가 차지하는 면적보다 block 높이·우측 여백이 크다.
- 편집용 block type·출처 표시는 필요할 수 있지만 preview에서는 핵심 값보다 시각적 우선순위가 높을 이유가 없다.

#### 추가 이미지 2 — 요약 문장 block

- 한 문장에 전체 기간, 합계, 최고 월과 금액, 최저 월과 금액이 모두 들어가 길고 기계적으로 보인다.
- `2026년 3월 1일`, `7월 1일`처럼 월 집계의 bucket 시작일로 보이는 값이 사용자에게 일 단위 의미처럼 노출된다.
- block 내부 상단에 큰 빈 공간이 남고 문장이 아래쪽에 배치되어 content와 frame 높이가 맞지 않는다.
- 편집 toolbar를 숨긴 뒤에도 editor용 reserved height 또는 수동 block height가 그대로 남는지 확인이 필요하다.

### 12.2 추가 요구사항 요약

| ID | 우선순위 | 추가 요구 | 결정 방향 |
|---|---:|---|---|
| ADD-01 | P0 | 같은 열·줄에 있다는 이유로 block 높이를 강제로 동일하게 만드는 로직 수정 | 각 block의 `x/y/w/h`를 독립적으로 유지하고, 정렬·충돌 방지와 높이 동기화를 분리한다. |
| ADD-02 | P1 | Artifact를 중복 없이 깔끔하고 사용자 친화적으로 재설계 | 사용자 UI에서는 `분석 결과`로 표현하고 제목·기간·단위·block type·출처의 반복을 제거한다. |
| ADD-03 | P0 | 좌우뿐 아니라 위·아래 방향으로도 자유로운 resize 제공 | 세로·모서리 resize, 유형별 최소 높이, keyboard/preset 대체 수단을 제공한다. |
| ADD-04 | P1 | 월 비교에서 ISO 날짜 대신 월 granularity에 맞는 제목·축 표시 | canonical 날짜는 보존하고 presentation formatter에서 `2026년 5~8월`, `5월`처럼 표시한다. |
| ADD-05 | P0 | block preview에서 편집 menu 제거 및 불필요한 여백 축소 | block preview는 mode 전환 control 외 편집 chrome을 unmount하고 content 높이를 다시 계산한다. 문서 preview/final에서는 mode control도 제거한다. |

### 12.3 ADD-01 — 같은 열·줄 block의 높이 독립

#### 변경해야 할 규칙

같은 열, 같은 grid line 또는 같은 행에 배치됐다는 사실만으로 형제 block의 높이를 동일하게 만들지 않는다.

- 위치 `x/y`, 폭 `w`, 높이 `h`는 block별 독립 상태다.
- drag는 기본적으로 대상 block의 `x/y`만 바꾼다.
- resize는 대상 block의 `w/h`만 바꾼다.
- 충돌 방지는 필요한 block의 `y` 이동으로 해결하되, 형제 block의 `h`를 암묵적으로 바꾸지 않는다.
- `레이아웃 정리`는 겹침 제거와 읽기 순서 정돈만 수행한다.
- 동일 높이 정렬이 필요하면 자동 규칙이 아니라 명시적 `높이 맞추기` 명령으로 제공한다.

#### 예시

```text
같은 열
┌──────── KPI  h=3 ────────┐
└───────────────────────────┘
┌──────── Chart h=7 ───────┐
│                           │
│                           │
└───────────────────────────┘
```

두 block의 `x`와 `w`가 같아도 `h`는 독립적이어야 한다.

#### 인수 기준

1. 같은 열에 `h=3` KPI와 `h=7` chart를 배치해도 두 높이가 유지된다.
2. 한 block을 세로 resize해도 다른 block의 `h`가 변하지 않는다.
3. 한 block의 이동·resize 때문에 충돌이 생기면 형제 block은 필요한 만큼 위치만 이동하며 내용이 겹치지 않는다.
4. undo/redo, 저장→새로고침, preview, 확정 HTML/PDF에서 같은 높이와 순서를 유지한다.
5. 자동 정돈 전후의 block ID별 `w/h`가 사용자의 명시적 resize 없이 바뀌지 않는다.

### 12.4 ADD-02 — Artifact 정보구조와 BI형 시각 정리

#### 용어 원칙

- backend·trace·개발 문서에서는 `Artifact` domain 용어를 유지할 수 있다.
- 일반 사용자 화면에서는 `분석 결과`, `핵심 지표`, `차트`, `표`처럼 결과 유형으로 표현한다.
- checksum, query ID, source URN은 기본 card에 표시하지 않고 `출처·기술 정보` details에 둔다.
- 합성 데이터 표시는 숨기지 않고 report 또는 page 수준에서 한 번 명확히 제공한다.

#### 권장 시각 계층

```text
1. 질문에 답하는 제목
2. 핵심 값 또는 핵심 시각화
3. 비교·변화·예외 한 줄
4. 필요할 때만 기간·필터·출처 세부 정보
```

추가 이미지 1의 preview 표현 예시:

```text
2026년 3~8월 객실 매출
373.4억 원
```

- 이미 제목에 기간이 있으면 `2026년 3월 1일부터 8월 29일까지`를 다시 표시하지 않는다.
- `분석 결과` label과 `핵심 지표` badge는 editor library·inspector에서만 사용하고 preview에서는 숨긴다.
- 단위는 값과 결합해 `373.4억 원`으로 읽히게 한다.
- 비교 기준이 있으면 `직전 기간 대비 8.2% 증가`처럼 한 줄만 추가한다.
- 동일 내용을 KPI card와 요약 문장으로 동시에 반복해야 할 이유가 없으면 하나만 유지한다.

#### Artifact 유형별 최소 정보

| 유형 | 기본 노출 | details로 이동 |
|---|---|---|
| KPI | metric명, 값+단위, 비교값 1개 | 정확한 기간, source, query ID, checksum |
| Chart | 질문형 제목, 축·단위, 필요한 legend | source field, aggregation, 정확한 range |
| Table | 제목, 명확한 column label, 단위 | query·source·전체 row 수 |
| Summary | 결론 1~2문장 | 전체 수치 나열, provenance |

#### BI·유사 서비스 참고

| 공식 참고 | 적용할 원칙 |
|---|---|
| [Power BI 접근 가능한 보고서 설계](https://learn.microsoft.com/en-us/power-bi/create-reports/desktop-accessibility-creating-reports) | title·axis·label을 명확히 쓰고 jargon을 피한다. 같은 내용을 보여주는 visual을 중복 배치하지 않으며 page clutter를 줄인다. |
| [Power BI dashboard design tips](https://learn.microsoft.com/en-us/power-bi/create-reports/service-dashboards-design-tips) | 가장 중요한 정보는 상단에 두고, card는 핵심 수치를 강조하되 context를 함께 제공한다. 한 화면에서 읽을 수 있도록 필수 정보만 남긴다. |
| [Power BI mobile report BP](https://learn.microsoft.com/en-us/power-bi/create-reports/power-bi-create-mobile-optimized-report-best-practices) | 중요 visual만 유지하고 불필요한 title·gridline·legend·빈 공간을 줄인다. mobile은 top-to-bottom narrative와 content에 맞는 높이를 사용한다. |
| [Metabase dashboard cards](https://www.metabase.com/docs/latest/dashboards/introduction) | card 크기에 맞춰 시각화를 적응시키고, dashboard는 한 주제에 집중하며 중요한 card를 상단·큰 크기로 배치한다. |

#### 인수 기준

1. 한 block의 기본 preview에서 같은 기간 문자열은 최대 1회만 표시된다.
2. metric 단위는 값과 분리되어 의미가 모호해지지 않는다.
3. `분석 결과`, `Artifact`, block type badge가 핵심 제목·값보다 먼저 읽히지 않는다.
4. 동일 metric·기간·결론을 전달하는 KPI와 summary 중복을 정적 규칙 또는 review checklist로 탐지한다.
5. 320~1440px에서 title·value·axis·legend가 잘리지 않고, 좁은 card는 덜 중요한 metadata부터 숨긴다.

### 12.5 ADD-03 — 자유로운 세로·모서리 resize

#### 조작 규칙

- desktop pointer에서는 상·하·좌·우와 네 모서리 resize를 지원한다.
- 위쪽 edge resize는 block의 `y`와 `h`를 함께 바꾸되 아래 edge의 시각적 위치를 유지한다.
- 아래쪽 edge resize는 `h`만 바꾼다.
- 모서리 resize는 `w/h`를 함께 바꾸며 필요하면 chart의 `비율 잠금`을 선택적으로 제공한다.
- grid snap은 유지할 수 있지만 사용자가 세로 크기를 바꾸지 못하게 하는 제약으로 사용하지 않는다.
- resize 시작·진행·완료 시 현재 폭·높이 또는 column/row 값을 표시한다.
- `Esc`는 진행 중 resize를 취소하고 undo/redo가 한 번의 resize를 한 단계로 처리한다.

#### block 유형별 동작

| 유형 | 기본 높이 | 세로 resize 결과 |
|---|---|---|
| Text/Markdown | 내용에 따라 자동 증가 | 최소 높이 이상에서 수동 높이 가능. preview는 editor toolbar 공간을 제외해 다시 측정 |
| KPI | compact content-fit | 최소 높이 이하로 축소 금지. 값·label이 잘리지 않아야 함 |
| Chart | 권장 기본 비율 | 높이에 따라 plot·legend·label을 responsive 재배치 |
| Table | header+최소 row 수 | editor에서는 표시 row 수가 변하고, 출력에서는 page break 정책으로 처리 |

#### drag 대체 수단

- inspector에 폭·높이 preset 또는 숫자 입력을 제공한다.
- `작게/보통/크게/콘텐츠에 맞춤` preset을 pointer·keyboard로 사용할 수 있게 한다.
- resize handle에 block명을 포함한 accessible name을 제공한다.

#### 인수 기준

1. 선택 block의 위·아래 edge와 네 모서리에서 높이를 변경할 수 있다.
2. 세로 resize 중 형제 block 높이는 변하지 않는다.
3. 최소 높이에서 text, value, axis, legend, table header가 잘리지 않는다.
4. resize 결과가 editor, block preview, document preview, 저장 복원, HTML/PDF에서 일치한다.
5. pointer 없이 preset 또는 숫자 입력으로 같은 높이 결과를 만들 수 있다.

### 12.6 ADD-04 — 월 granularity 기반 제목·축·요약

#### 핵심 원칙

원본 값과 lineage에는 canonical ISO date/range를 그대로 보존하고, 사용자가 읽는 title·axis·summary에서만 granularity와 locale에 맞게 표현한다.

- formatter는 raw 값 모양을 보고 월 단위라고 추측하지 않는다.
- server Artifact의 `time_granularity`, `time_range`, timezone을 사용한다.
- 월 집계 row의 `2026-05-01`은 bucket 시작일이지 `5월 1일 하루`가 아니다.
- end-exclusive 범위를 title에 그대로 노출해 한 달이 더 많거나 적게 보이게 하지 않는다.

#### 표시 규칙

| 상황 | 보고서·block 제목 | chart axis | tooltip·details |
|---|---|---|---|
| 같은 해 월 범위 | `2026년 5~8월 객실 매출 비교` | `5월, 6월, 7월, 8월` | `2026년 5월 · 55.6억 원` |
| 연도를 넘는 월 범위 | `2025년 11월~2026년 2월 객실 매출 비교` | `2025년 11월, 12월, 2026년 1월, 2월` 또는 연도 group | 정확한 연·월+값 |
| 한 달 | `2026년 5월 객실 매출` | 일별 data면 `1일, 2일…` | 정확한 날짜+값 |
| 일 범위 | `2026년 5월 1~8일 객실 매출` | `5/1, 5/2…` | `2026년 5월 1일` |
| 연 범위 | `2023~2026년 객실 매출 비교` | `2023년, 2024년…` | 연도+값 |

월 집계로 확인된 경우 추가 이미지 2의 요약 예시:

> 2026년 3~8월 객실 매출은 373.4억 원입니다. 7월이 68.3억 원으로 가장 높았고, 3월이 55.6억 원으로 가장 낮았습니다.

정확한 원 단위 전체 값과 canonical range는 표 또는 details에서 확인하게 한다.

[Looker Studio의 날짜·시간 공식 문서](https://cloud.google.com/looker/docs/studio/dates-and-times)는 chart가 날짜 field를 year/month/day granularity로 group할 수 있고 월 표시에는 Month granularity를 사용하도록 안내한다. Answervice도 query 결과 날짜를 문자열 치환하는 대신 명시적 time granularity를 presentation 계약으로 사용해야 한다.

#### 인수 기준

1. 월별 비교의 제목·축·summary에 `YYYY-MM-01`이 노출되지 않는다.
2. 같은 해, 연도 교차, 단월, 일별, 연별 fixture를 각각 검증한다.
3. `[start, end)` 범위에서 마지막 포함 월을 정확히 계산한다.
4. KST와 UTC 경계에서도 월 label이 앞·뒤 월로 이동하지 않는다.
5. editor, preview, HTML, PDF가 같은 title·axis·tooltip formatting contract를 사용한다.
6. raw ISO range와 query lineage는 details·trace에서 손실 없이 유지된다.

### 12.7 ADD-05 — block preview의 편집 menu 제거와 여백 회수

#### 두 preview 수준을 구분한다

1. **편집기 내부 block preview**
   - block을 다시 edit 상태로 바꾸기 위한 compact `편집` 또는 mode switch만 남길 수 있다.
   - 굵게·기울임·제목·목록·인용·링크 toolbar, drag handle, resize handle, 더보기 등 편집 menu는 렌더링하지 않는다.
2. **문서 전체 preview와 확정본**
   - block별 mode switch까지 포함해 모든 editor control을 렌더링하지 않는다.

#### 여백 처리

- 편집 menu를 단순히 `visibility: hidden`으로 숨겨 공간을 남기지 않는다.
- preview 상태에서는 edit toolbar container를 조건부 unmount하거나 layout에서 완전히 제외한다.
- toolbar가 사라진 뒤 block의 content height와 최소 높이를 다시 측정한다.
- content는 block 상단에서 일관된 padding으로 시작한다.
- 기본은 `content-fit`이며 사용자가 명시적으로 고정 높이를 선택한 block만 그 높이를 유지한다.
- 고정 높이를 유지하더라도 editor toolbar용 빈 공간은 남기지 않는다.
- 추가 이미지 2처럼 한두 줄 본문이 큰 frame 아래쪽에 붙지 않게 한다.

#### 인수 기준

1. block preview에서 formatting button·drag handle·resize handle·block menu 수가 0이다.
2. document preview/final에서는 block mode switch 수도 0이다.
3. edit→block preview 전환 후 toolbar가 차지하던 높이가 0이 되고 내용이 상단 padding 위치로 이동한다.
4. 짧은 본문은 content-fit 높이를 사용하며 비정상적인 상·하단 빈 공간이 없다.
5. 다시 edit로 전환하면 toolbar와 handle이 복원되고 focus가 편집 위치로 이동한다.
6. preview 상태 control은 keyboard·screen reader focus 순서에도 남지 않는다.

### 12.8 추가 요구 통합 검증 시나리오

| 시나리오 | 절차 | 기대 결과 |
|---|---|---|
| 독립 높이 | 같은 열에 KPI `h=3`, chart `h=7` 배치 후 chart 높이 변경 | KPI 높이 불변, 겹침 없음 |
| 세로 resize | text의 위 edge와 chart의 아래 edge를 각각 drag | `y/h` 규칙에 맞게 변경, undo 1회로 복원 |
| 저장 parity | 다른 높이의 block을 저장·새로고침·preview·HTML/PDF 확인 | 위치·폭·높이·읽기 순서 일치 |
| Artifact compact | 추가 이미지 1 형태의 KPI를 preview | 기간 반복 0, `373.4억 원` 결합, edit badge/menu 없음 |
| 짧은 summary | 추가 이미지 2 형태의 두 줄 text를 preview | content-fit, 상단 정렬, toolbar reserved gap 0 |
| 월 비교 | May~August monthly Artifact 렌더 | 제목 `2026년 5~8월...`, 축 `5월~8월`, ISO 날짜 미노출 |
| 연도 교차 | 2025-11~2026-02 monthly Artifact 렌더 | 연도 경계를 잃지 않는 title·axis |
| 접근성 | drag 없이 menu/preset으로 이동·resize | pointer drag와 같은 저장 결과, live 안내와 focus 유지 |

### 12.9 추가 요청의 적용 순서

1. **ADD-05 preview chrome 제거와 content reflow**
2. **ADD-01 block 높이 결합 해제**
3. **ADD-03 세로·모서리 resize와 대체 control**
4. **ADD-04 granularity 기반 공통 formatter**
5. **ADD-02 Artifact hierarchy·중복 제거**

앞 세 항목은 같은 layout state와 renderer를 건드릴 가능성이 높으므로 한 계약으로 설계하되, 구현 commit과 검증은 독립적으로 나누는 편이 안전하다. 이 절은 수정 지시가 아니라 다음 구현을 위한 추가 조사·요구사항 기록이다.
