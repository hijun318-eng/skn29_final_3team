# SensePlace 후속 작업 실행 프롬프트

> 작성 기준: 2026-07-20 · 기준 브랜치: `daesung`
> 이 문서는 다음 Codex 작업에서 복사해 사용할 실행 인계용 프롬프트다. 현재 상태와 일정은 실행 시점의 저장소와 `02_WBS.md`에서 다시 확인한다.

## 공통 마스터 프롬프트

```text
SensePlace 프로젝트의 다음 미완료 작업을 구현해줘.

[목표]
- `docs/markdown/02_WBS.md`에서 선행 작업이 충족된 가장 이른 미완료 작업을 선택한다.
- 이번 실행 범위는 아래 [이번 실행 단계] 하나로 제한한다.
- 구현 결과, 계약 문서, 테스트 evidence와 WBS 상태를 같은 작업에서 일치시킨다.

[이번 실행 단계]
- 아래 단계별 프롬프트 중 하나를 붙여 넣는다.

[시작 전 필수 확인]
1. repository root, 현재 branch, `git status --short`와 기존 사용자 변경을 확인한다.
2. root `AGENTS.md`와 작업 경로에 적용되는 추가 지침을 읽는다.
3. 다음 문서를 우선순위대로 읽고 충돌 시 앞 문서를 따른다.
   - `docs/markdown/SensePlace_기획서_초안.md`: 제품·Baseline·실험·Gate 기준
   - `docs/markdown/01_요구사항정의서.md`: 요구사항 ID·수용 기준
   - `docs/markdown/02_WBS.md`: 담당·일정·현황·산출물
   - `docs/markdown/03_프로젝트기획서.md`: 프로젝트 설명·R&R
4. 관련 구현과 테스트가 이미 존재하는지 먼저 검색하고 사용자 변경을 보존한다.

[고정 결정]
- 문서 제목은 변경하지 않는다. 공식 서비스 본문 명칭은 `SensePlace`다.
- Baseline과 모델 실험은 모두 합성 VOC·합성 운영 데이터만 사용한다. 실제 고객 데이터와 공개 리뷰 corpus는 사용하지 않는다.
- 합성 VOC는 규칙·template으로 label을 고정하고, LLM은 문장 다양화에만 선택적으로 사용한다. generator와 evaluator를 분리한다.
- Baseline은 기능 A(보장 질문 8종→SQL Guard→표·차트·설명)와 기능 B(결정론적 이상 감지→evidence→원인 후보→보고서 DRAFT→관리자 결정)다.
- 인증은 Django session이며 역할은 `HOTEL_MANAGER`, `FNB_MANAGER`, `ROOMS_MANAGER` 3종이다.
- Django는 인증·권한·job·report·decision을, 별도 FastAPI는 품질 Gate·query·Incident·LLM fallback을 담당한다. PostgreSQL을 기준 저장소로 사용한다.
- 외부 LLM은 실행당 최대 1회 호출하고 timeout·retry·비용 상한을 설정한다. 실패해도 결정론적 수치와 template 문장을 유지하고 `PARTIAL` 상태를 반환한다.
- 반례 16건 Gate는 08/13~08/14, 미통과 Baseline 보완 한계는 08/18, 최종 Golden Path는 연속 5회 재현한다.
- ML/DL·VectorDB·sLLM·단일/다역할 Agent 비교는 공식 독립 실험이지만 Baseline 선행 의존성이나 Gate 통과 조건이 아니다.
- 추천 질문 UX와 MCP adapter는 Gate 이후 승인받은 경우에만 구현한다.
- 기존 요구사항 62개 ID와 Baseline 43·독립 실험 8·승인 후 확장 11 분류를 유지한다.

[변경 금지·제외]
- `docs/markdown/final_project/`와 `docs/templates/`는 읽기 전용이다.
- `docs/markdown/05_화면설계서_초안.md`는 사용자가 다시 명시하기 전까지 수정하지 않는다. WBS의 6개 목업은 별도 UI 구현 범위다.
- 실제·공개 데이터 수집, 실시간 내부 시스템 연동, 자동 현장 조치, 다호텔 상용 운영은 범위 밖이다.
- 사용자 승인 없이 dependency 설치, 외부 비용 발생, commit, push, PR을 수행하지 않는다.

[작업 방식]
- 이번 단계의 입력·출력 schema, 오류 상태, 권한, version, acceptance test를 먼저 고정한다.
- 가장 작은 end-to-end 경로부터 구현하고 독립 실험과 승인 후 확장을 Baseline 코드 경로에서 분리한다.
- 계산·집계·판정은 SQL·Python·규칙으로 수행하고 LLM이 수치나 원인을 임의 생성하지 못하게 한다.
- 테스트에서 정상 경로뿐 아니라 권한 거부, 결측, 중복, timeout, SQL injection과 근거 외 주장을 확인한다.
- 저장소 파일을 변경하면 `02_WBS.md`, 현재 branch 일일보고와 같은 주차 주간보고를 갱신한다.

[완료 보고]
- 선택한 WBS ID와 완료 조건
- 변경 파일과 핵심 결과
- 실행한 테스트·검증 및 결과
- 실행하지 못한 검증
- 남은 위험·결정 필요 항목
- 다음에 이어서 할 수 있는 WBS ID
```

## 단계별로 붙여 넣을 프롬프트

### 1. 계약 동결 · WBS 1.7, 2.1, 2.9

```text
[이번 실행 단계]
`1.7`, `2.1`, `2.9` 범위에서 API schema, 합성 DDL, 3역할 권한표, `dataset_manifest`, `metric_catalog`, 공통 상태·오류 계약을 동결해줘. 기존 문서와 구현 경계를 대조하고 중복 계약은 새로 만들지 말고 단일 기준으로 연결해줘. LLM timeout·retry·비용 상한은 측정 가능한 설정값과 기록 위치까지 정의해줘. 완료 조건은 schema 검증, 대표 fixture validation, 역할별 허용·거부 사례와 계약 간 참조 일치다.
```

### 2. 합성 데이터·품질 Gate · WBS 2.2~2.8, 2.10

```text
[이번 실행 단계]
`2.2`~`2.8`, `2.10` 중 선행 계약이 완료된 작업을 구현해줘. 규칙·template 기반 합성 VOC와 객실·조식·인력 운영 데이터를 같은 scenario key로 생성하고 seed·schema version·generator version·정답 label을 manifest에 기록해줘. 실제·공개 corpus는 사용하지 말고 정상·단일 이상·복합 이상·결측·중복 fixture를 포함해줘. 품질 Gate 실패 batch는 적재·분석에서 차단하고 테스트 evidence를 남겨줘.
```

### 3. 인증·서비스 골격 · WBS 6.1, 6.2

```text
[이번 실행 단계]
`6.1`, `6.2`의 Django session 로그인, 3역할 scope, job 생성·polling, immutable `scope_snapshot` 골격을 구현해줘. 비밀번호 해시, 서버측 권한 강제, 권한 우회 거부, job 상태 전이와 감사 정보를 테스트해줘. FastAPI 내부 호출에는 사용자 입력 역할을 신뢰하지 않고 Django가 확정한 scope만 전달하도록 계약을 고정해줘.
```

### 4. 중간발표 목업 · WBS 4.1~4.4

```text
[이번 실행 단계]
`4.1`~`4.4` 범위에서 WBS에 정의된 6개 SensePlace 목업 화면과 역할 선택, fixture 기반 표·차트, 합성 데이터 표시, 보고서 `DRAFT` 상태를 구현해줘. `05_화면설계서_초안.md`는 수정하지 말고 최신 contract fixture만 사용해 완성 서비스 경험을 보여줘. backend 미연결 요소는 실제 동작처럼 오인되지 않도록 명확히 표시해줘.
```

### 5. 독립 모델 실험 · WBS 3.1~3.7

```text
[이번 실행 단계]
`3.1`~`3.7` 중 하나의 독립 실험을 합성 데이터만 사용해 재현 가능하게 수행해줘. 비교 대상 2개 이상, 고정 split·seed·metric, 오류 분석, 지연·비용과 artifact version을 기록해줘. 실험 결과는 Baseline runtime 의존성이나 Gate 조건으로 연결하지 말고 규칙 Baseline과의 차이를 보고서에 명시해줘.
```

### 6. 기능 A · WBS 5.2, 6.4, 6.9

```text
[이번 실행 단계]
`5.2`, `6.4`, `6.9`의 기능 A를 구현해줘. 보장 질문 8종을 semantic plan으로 매핑하고 `metric_catalog`의 허용 metric·grain·filter·role scope로 SQL을 생성·검증해 read-only로 실행해줘. 비가산 지표 재집계와 SQL injection을 차단하고 결과를 표·차트·근거 기반 설명으로 연결해줘. LLM 실패 시 동일 수치와 template 설명을 반환하는 테스트를 포함해줘.
```

### 7. 기능 B·보고서 · WBS 5.3~5.7, 5.9, 6.3, 6.5, 6.6

```text
[이번 실행 단계]
`5.3`~`5.7`, `5.9`, `6.3`, `6.5`, `6.6` 중 선행 작업이 완료된 기능 B 경로를 구현해줘. `READY` batch에 versioned rule을 적용하고 같은 기간 VOC·운영 근거, 반대 근거, 부족 데이터를 묶어 Incident를 생성해줘. 원인은 확정하지 말고 후보와 대응 옵션만 제시하며 보고서는 `DRAFT`로 생성해 호텔 관리자만 승인·보류·반려할 수 있게 해줘. 승인본 덮어쓰기와 자동 현장 조치는 금지해줘.
```

### 8. Baseline Gate·보완 · WBS 6.11, 7.1~7.3, 7.6

```text
[이번 실행 단계]
`6.11`, `7.1`~`7.3`, `7.6`의 반례 16건 Baseline Gate를 자동 실행해줘. 정상, 운영·VOC 복합/단일 이상, 결측, 권한 거부, SQL injection, p90 재집계, 중복 batch, FastAPI·LLM timeout, 근거 외 주장, 승인 전 확정 노출과 목업 오인을 포함해 pass/fail evidence를 남겨줘. 실패 시 08/18까지 Baseline만 보완하고 독립 실험·승인 확장 때문에 Gate 수정 범위가 넓어지지 않게 해줘.
```

### 9. 승인 확장·최종 안정화 · WBS 7.4, 7.5, 7.7, 8.1~8.5

```text
[이번 실행 단계]
Baseline Gate 통과 evidence를 먼저 확인한 뒤 승인 기록이 있는 확장만 구현해줘. 승인된 확장이 없으면 `7.5`, `8.1`~`8.5`의 합성 데모, 문서, 발표자료, 시연영상, fallback 자료와 최종 안정화만 진행해줘. 같은 seed의 Golden Path를 연속 5회 재현하고 실패 원인·수정·재검증 결과를 남겨줘.
```

## 현재 가장 먼저 실행할 순서

1. `1.7` API schema·합성 DDL·권한표·manifest·metric catalog 계약 동결
2. `2.1`, `2.9` 합성 VOC schema·label·template 및 semantic catalog 확정
3. `2.2`, `2.3`, `2.10` 합성 fixture·정답 manifest 생성
4. `2.5`, `2.7` 품질 Gate와 PostgreSQL analytics view 구축
5. `6.1`, `6.2` Django session·3역할·job 골격 구현

위 순서는 `02_WBS.md`의 실제 상태나 선행 조건이 바뀌면 그 문서를 기준으로 다시 계산한다.
