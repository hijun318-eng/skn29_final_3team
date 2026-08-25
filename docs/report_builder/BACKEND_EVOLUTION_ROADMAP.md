# Report Builder V2 백엔드 확장 로드맵

## 1. 목적과 현재 한계

이 문서는 UX 목업에 있으나 현재 저장 계약으로는 영속화하거나 canonical HTML/PDF로 동일하게
표현할 수 없는 기능의 구현 경계를 정의한다. 설계 문서일 뿐 이 변경에서 백엔드·DB·API를
수정하지 않는다.

현재 계약의 핵심 한계는 다음과 같다.

- 페이지가 엔티티가 아니며 블록의 전역 `y` 좌표에서 파생된다.
- 방향은 보고서 version 전체에 하나만 저장된다.
- 사용자 템플릿·댓글·이름 붙인 스냅샷 저장소가 없다.
- 표시 설정이 일부 블록의 `content` JSON에 섞여 있고 text는 같은 필드를 Markdown으로 쓴다.
- 화면은 7개 차트 이름을 제공하지만 PDF renderer는 `area`를 line으로,
  `horizontal-bar`, `stacked-bar`, `donut`, `pie`를 bar로 축약한다.
- 확정 HTML/PDF는 승인 version만 대상으로 하므로 draft 출력 UX는 별도 계약이 필요하다.

## 2. 구현 순서 요약

| 백엔드 단계 | 목표 | 선행 조건 | 상태 |
|---|---|---|---|
| B1 | typed block view spec 분리 | 없음 | 미착수 |
| B2 | 기존 7개 차트의 화면·HTML·PDF 의미 일치 | B1 | 미착수 |
| B3 | 페이지 엔티티와 혼합 orientation | B1 | 미착수 |
| B4 | 영구 템플릿 | B1, 필요하면 B3 | 미착수 |
| B5 | 댓글·영구 스냅샷·동시 편집 보호 | B1 | 미착수 |
| B6 | Artifact 표시 모드와 추가 차트 | B1, B2 | 미착수 |

B1과 B2를 먼저 하는 이유는 새 UX 설정을 기존 `content` 문자열에 더 쌓으면 text 본문 훼손과
renderer 불일치가 커지기 때문이다. 페이지 모델은 그 다음 독립 migration으로 진행한다.

## 3. B1 — typed block view spec

### 목표

블록 내용과 표현 설정을 분리하고 API에서 허용한 설정만 저장한다.

### 권장 DB 변경

새 migration에서 `report_v1.report_blocks`에 다음을 추가한다.

```text
view_spec_version varchar(32) NOT NULL DEFAULT 'report-view-v1'
view_spec jsonb NOT NULL DEFAULT '{}'
```

기존 `content`는 다음 의미만 유지한다.

- `text`: Markdown 본문
- 그 외 블록: migration 기간 동안 legacy 설정 read fallback

기존 chart/table/artifact `content` JSON은 새 migration에서 검증 가능한 값만 `view_spec`으로
옮긴다. 과거 migration 파일은 수정하지 않는다. 잘못된 JSON은 임의 보정하지 말고 migration
사전 검사에서 목록으로 차단한다.

### API 변경

- `ReportBlockRequest`와 `ReportBlockResponse`에 versioned `view_spec` 계약을 추가한다.
- 자유 `dict`를 그대로 허용하지 않고 block type별 Pydantic discriminated union을 사용한다.
- 허용 예: chart type, legend, label, palette, number format, artifact view mode.
- 선택·잠금·Zoom·가이드 같은 editor state는 계속 거부한다.
- 한 호환 기간 동안 legacy `content`를 읽되 응답은 정규화된 `view_spec`을 반환한다.

### 완료 조건

- text Markdown round-trip이 유지된다.
- legacy draft가 동일하게 렌더된다.
- 정의되지 않은 view setting은 422로 거부된다.
- source checksum에 정규화된 view spec과 version이 포함된다.

## 4. B2 — 기존 차트의 canonical parity

### 현재 결함

`app/backend/app/services/report_document_chart.py`는 이름과 다른 시각화를 생성한다.

```text
area -> line
horizontal-bar -> bar
stacked-bar -> bar
donut -> bar
pie -> bar
```

따라서 현재 UI의 7개 선택지가 PDF에서 모두 같은 의미로 보존된다고 볼 수 없다.

### 변경 범위

1. chart capability allowlist를 frontend와 backend가 공유할 versioned 계약으로 정의한다.
2. backend SVG renderer에 실제 area, horizontal bar, stacked bar, donut, pie를 구현한다.
3. 차트별 필수 데이터 모양을 검증한다.
4. HTML과 PDF가 같은 SVG와 legend/label/색상 규칙을 사용하게 한다.
5. 미지원 조합은 bar fallback이 아니라 typed render error로 닫는다.

### 완료 조건

- 7종 golden SVG/HTML/PDF 테스트가 존재한다.
- 음수·0·빈 데이터·혼합 단위·긴 라벨을 검증한다.
- Preview와 PDF의 차트 종류·series·색상·범례가 의미상 일치한다.

## 5. B3 — 페이지 엔티티와 혼합 orientation

### 권장 DB 모델

새 `report_v1.report_pages` 테이블을 version 하위 엔티티로 둔다.

```text
definition_id uuid
definition_version integer
page_id uuid
page_order integer
name varchar(255)
orientation varchar(16) CHECK ('portrait', 'landscape')
PRIMARY KEY (definition_id, definition_version, page_id)
UNIQUE (definition_id, definition_version, page_order)
```

`report_blocks`에는 같은 definition/version의 page를 참조하는 `page_id`를 추가하고 `y`를
page-local 좌표로 바꾼다. 승인 version의 page와 block은 기존 불변 trigger 범위에 포함한다.

### 호환 migration

기존 version마다 현재 orientation의 파생 페이지를 만든다. 블록을 모두 첫 페이지에 넣으면
기존 multi-page 출력이 달라지므로 현재 `contentRows` 규칙으로 page index와 local `y`를
결정해 각 page에 연결한다. migration 전후 HTML page count와 block 순서를 비교한다.

### API 변경

- definition 응답에 순서가 고정된 `pages`를 추가한다.
- draft 저장은 pages와 blocks를 한 transaction에서 원자적으로 교체한다.
- 페이지 추가·삭제·복제·순서 이동은 별도 endpoint를 많이 만들기보다 전체 draft document
  replacement 하나로 시작한다.
- 삭제 page에 block이 남거나, page order가 중복되거나, block이 page 경계를 벗어나면 거부한다.
- 동시 저장 손실을 막기 위해 revision 또는 `If-Match` 기반 CAS를 함께 도입한다.

### Renderer 변경

- source checksum에 page ID, order, orientation을 포함한다.
- HTML은 page별 named `@page` 규칙을 사용하고 각 page section에 해당 page name을 지정한다.
- WeasyPrint 실제 PDF에서 세로·가로·세로 혼합 순서와 page break를 검증한다.

## 6. B4 — 영구 템플릿

템플릿은 실제 Artifact ID를 복사한 보고서가 아니라 layout과 typed slot을 저장해야 한다.
그렇지 않으면 다른 기간·사용자의 Artifact lineage를 잘못 재사용한다.

### 최소 모델

```text
report_templates: template_id, owner_id, scope, title, created_at, updated_at
report_template_versions: template_id, version, status, page_spec, block_specs, created_at
```

- `scope`는 처음에는 `private`만 지원하고 팀 공유는 권한 모델이 준비된 뒤 추가한다.
- data block은 `artifact_id` 대신 `slot_kind`, 허용 view mode, 최소 schema 조건을 가진다.
- 적용 시 사용자가 선택한 현재 Artifact를 검증해 새 block lineage를 만든다.
- builtin template도 같은 schema의 versioned seed로 관리하되 운영 중 임의 수정하지 않는다.

### API

- 목록, 생성, 새 version, 삭제 또는 archive, template 적용 전 검증을 제공한다.
- 적용 결과는 바로 저장하지 않고 검증된 draft patch로 반환한 뒤 기존 draft 저장 경로를 쓴다.

## 7. B5 — 댓글·영구 스냅샷·동시 편집 보호

### 댓글

댓글은 block `content`나 승인 document source에 섞지 않는다.

```text
report_block_comments:
comment_id, definition_id, definition_version, block_id,
author_id, body, created_at, updated_at, resolved_at
```

- 권한 있는 사용자만 작성·수정·resolve할 수 있다.
- 기본 출력물과 source checksum에서는 제외한다.
- 승인 version 댓글 허용 여부는 제품 정책으로 정하되 승인 block 자체는 수정하지 않는다.

### 영구 스냅샷

현재 세션 스냅샷과 별도로 사용자가 명시적으로 저장한 draft revision만 append-only로 보존한다.

```text
report_draft_snapshots:
snapshot_id, definition_id, definition_version, name,
base_revision, canonical_draft_json, created_by, created_at
```

복원은 과거 row를 덮어쓰지 않고 현재 draft에 새 revision으로 적용한다. canonical JSON은 B1/B3
Pydantic 계약을 통과한 pages와 blocks만 저장한다.

### 동시 편집

- draft version에 증가하는 `revision`을 둔다.
- 저장 요청은 읽은 revision을 제출한다.
- 불일치하면 409와 최신 revision을 반환하며 마지막 저장 승자 방식으로 덮지 않는다.

## 8. B6 — Artifact 표시 모드와 추가 차트

### KPI·AI Summary·전체 Artifact

가능하면 새 DB block type을 늘리지 않고 `artifact` block의 typed `view_mode`로 표현한다.

```text
full | kpi | chart | table | summary
```

- 모든 mode는 원래 `artifact_id`, `query_id`, analysis definition, checksum, Evidence를 유지한다.
- KPI 값은 Artifact metric 중 선택된 key를 참조하며 사용자가 숫자를 직접 덮어쓰지 않는다.
- summary는 Artifact summary를 표시하고 출처 없는 자유 문장은 text block으로 구분한다.
- view schema가 Artifact와 맞지 않으면 `VIEW_SCHEMA_INCOMPATIBLE`로 실패한다.

### 추가 차트

B2 완료 뒤 다음 순서로 하나씩 frontend와 backend를 함께 추가한다.

1. Scatter
2. Radar
3. Radial Bar
4. Composed
5. Treemap
6. Funnel

각 차트는 typed view spec, 데이터 capability 검사, frontend renderer, backend SVG, HTML/PDF golden
test가 한 변경 단위다. 화면에서만 보이는 차트는 출시하지 않는다.

이미지 block은 외부 URL을 직접 저장하지 않는다. 승인된 asset 저장소, media type·크기 제한,
checksum, 접근 권한, HTML/PDF embedding 정책이 별도 설계될 때만 추가한다.

## 9. Draft HTML/PDF 출력

목업의 DOM clone과 `window.print()`는 이식하지 않는다. 승인 전 출력이 필요하면 기존 renderer를
재사용하는 authenticated preview endpoint를 추가한다.

- 입력은 저장 계약과 동일하게 검증된 draft source다.
- 외부 URL과 editor chrome은 포함하지 않는다.
- preview 결과는 승인 document로 저장하거나 approved 상태로 표시하지 않는다.
- 요청 크기·timeout·rate limit을 둔다.
- 실제 확정본은 기존 승인·checksum·document repository 경로만 사용한다.

## 10. 단계별 검증과 커밋 경계

각 B 단계는 migration, backend 계약, repository, renderer, frontend adapter, 테스트를 섞어 한 번에
완성하지 않는다. 권장 커밋 순서는 다음과 같다.

1. ADR/계약과 migration
2. repository와 API contract
3. frontend adapter
4. HTML/PDF renderer와 golden test
5. 기존 definition migration/read-back 검증

필수 회귀 항목:

- Artifact lineage와 owner scope
- 승인 version 불변성
- draft CAS 충돌
- legacy definition read-back
- text Markdown 보존
- page overflow와 mixed orientation
- HTML/PDF checksum
- 부분 실패 block과 다시 실행

구현하지 않은 단계는 UI에서 저장되는 것처럼 표시하지 않는다. feature flag가 필요하면 기본값을
꺼 두고 DB migration과 API capability read-back이 확인된 환경에서만 노출한다.
