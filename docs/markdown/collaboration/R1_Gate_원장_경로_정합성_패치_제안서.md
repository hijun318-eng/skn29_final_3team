# R1 Gate 원장 경로 정합성 패치 제안서

| 항목 | 내용 |
|---|---|
| 문서 설명 | `Gate_실행_카드_원장.md`의 허용 경로가 실제 소스 트리와 어긋난 3건에 대한 R1 승인 요청 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.0 |
| 문서 기준일 | 2026-07-31 10:30 |
| 작성·수정 | 윤대성 / 기획 검토 결과 반영 |
| 승인 필요 | **R1 박준희** |

> 이 문서는 제안이며 원장을 수정하지 않았다. 원장은 Gate 판정의 단일 기준이므로 `ALLOWED_PATHS`를 고치면 **무엇이 통과하는지가 바뀐다**. 따라서 R1 승인 후에만 반영한다.

## 0. 요약

2026-07-31 기준 실제 소스 트리와 원장 허용 경로를 대조한 결과 3건의 불일치를 확인했다. 세 건 모두 현재 Wave 1 묶음이 전부 `MERGED_DEV`(terminal)라 **당장 게이트 동작을 바꾸지는 않는다.** terminal 묶음은 `ALLOWED_PATHS` 대신 개인 일일보고·공용 보고 경로만 허용하기 때문이다.

문제는 **Wave 2 발행 시점**이다. `## 역할별 기본 경로` 표가 새 실행 묶음의 `ALLOWED_PATHS` 작성 근거이므로, 지금 교정하지 않으면 Wave 2 카드가 존재하지 않는 경로를 허용하고 실제 작업 경로를 차단한다.

| # | 항목 | 현재 위험 | Wave 2 발행 후 위험 |
|---|---|---|---|
| C1 | 죽은 경로 4건 | 없음(terminal) | **R4가 자기 코드를 못 고침** |
| C2 | frontend 이중 소유 | 없음(terminal) | 폐기된 트리 수정이 통과됨 |
| C3 | 소유자 없는 문서 2건 | **있음** — CI가 검증하는데 아무도 못 고침 | 동일 |

## 1. 확인 방법

```text
git rev-parse --abbrev-ref HEAD   # 대조 시점의 작업 트리
find <경로> -type f -not -path '*/node_modules/*' | wc -l
```

| 경로 | 원장 기재 | 실제 | 판정 |
|---|---|---|---|
| `app/fastapi/**` | R4 허용 | `.gitkeep` 1개만 존재 | **죽은 경로** |
| `src/backend/**` | R4 허용 | 디렉터리 없음 | **죽은 경로** |
| `src/control_plane/**` | R4 허용 | 디렉터리 없음 | **죽은 경로** |
| `src/report/**` | R5 허용 | 디렉터리 없음 | **죽은 경로** |
| `tests/report/**` | R5 허용 | 디렉터리 없음 | 죽은 경로(미착수 예정 경로) |
| `app/backend/**` | 기본 경로표에 없음 | 파일 47개, 실제 R4 구현체 | **누락** |
| `app/react/**` | R5 허용 | `dist/` 빌드 산출물 6개만, 소스 없음 | **폐기 대상** |
| `app/enterprise-react/**` | R5 허용 | 파일 26개, 활성 frontend | 정상 |
| `docs/markdown/01_요구사항정의서.md` | 어느 역할에도 없음 | 존재, 작성자 송민지 | **소유자 공백** |
| `docs/markdown/05_화면설계서.md` | 어느 역할에도 없음 | 존재, 작성자 송민지·박준희 | **소유자 공백** |
| `docs/Answervice_기획서.md` | 어느 역할에도 없음 | 존재, 전 역할의 기준 문서 | **소유자 공백** |

## 2. C1 — 죽은 경로와 누락 경로

### 문제

원장 `## 역할별 기본 경로` 표(L142)의 R4 행이 `app/fastapi/**`, `src/backend/**`, `src/control_plane/**`를 가리키지만 셋 다 실체가 없다. R4의 실제 구현체는 `app/backend/**`(파일 47개)이며, 이 경로는 기본 경로표에 없다. R4-W1-F1 카드가 `app/backend/**`를 개별 허용해 우회한 상태다.

R5 행의 `src/report/**`, `tests/report/**`도 존재하지 않는다.

### 영향

Wave 2 카드를 기본 경로표대로 작성하면 R4는 자기 코드를 한 줄도 고칠 수 없고, `role-scope`가 전 파일을 침범으로 판정한다.

### 제안 (R4 행)

```text
- | R4 | `app/fastapi/**`, `src/backend/**`, `src/control_plane/**`, `tests/backend/**`, app DB·migration | ... |
+ | R4 | `app/backend/**`, `tests/backend/**`, app DB·migration | ... |
```

### 제안 (R5 행)

```text
- | R5 | I0의 frontend 후보, I0에서 확정한 활성 frontend, `src/report/**`, `tests/frontend/**`, `tests/report/**`, Report proposal | ... |
+ | R5 | I0에서 확정한 활성 frontend(`app/enterprise-react/**`), `tests/frontend/**`, Report proposal | ... |
```

`src/report/**`·`tests/report/**`는 Report 구현 착수 시점(Wave 3~4)에 실제 생성될 경로를 확인한 뒤 다시 추가한다. **존재하지 않는 경로를 미리 허용하지 않는다** — 오타나 잘못된 위치에 만든 파일까지 통과시키기 때문이다.

### 부수 확인 필요

R4-W1 카드의 `TEST_COMMANDS`(L311, L547)도 `python -m compileall app/fastapi src/backend src/control_plane`을 담고 있다. 현재 이 명령은 빈 디렉터리를 컴파일하므로 조용히 성공한다. `app/backend`로 교정을 제안한다. **`ci.yml`의 `python-contracts`는 이미 `app/backend`를 컴파일하고 있으므로 CI 동작 변화는 없다.**

## 3. C2 — frontend 이중 소유

### 문제

원장 본문 L145는 "R5는 **I0에서만** `app/react/**`와 `app/enterprise-react/**`를 함께 조사할 수 있다. 구현 변경은 결정된 활성 frontend 하나에만 적용한다"고 규정한다. 그런데 R5-W1 카드의 `ALLOWED_PATHS`(L336)는 두 경로를 모두 허용한다. 원장 본문과 원장 카드가 서로 모순이다.

후속 카드 R5-W1-F1(L467)은 이미 `app/enterprise-react/**`만 허용하고 `app/react/**`를 `FORBIDDEN_PATHS`로 명시했으므로, **활성 frontend 결정은 이미 내려졌다.** 기본 경로표만 따라오지 못한 상태다.

`app/react`에는 소스가 없고 `dist/` 빌드 산출물 6개만 남아 있다.

### 제안

1. 기본 경로표 L145 문장을 다음으로 교체한다.

```text
- R5는 I0에서만 `app/react/**`와 `app/enterprise-react/**`를 함께 조사할 수 있다. 구현 변경은 결정된 활성 frontend 하나에만 적용한다.
+ I0 결정에 따라 활성 frontend는 `app/enterprise-react/**` 하나다. `app/react/**`는 구형 트리이며 소스 없이 `dist/` 산출물만 남아 있다. 전 역할의 `FORBIDDEN_PATHS`로 유지하고, 삭제 여부는 발표 자료 의존성을 확인한 뒤 R1이 별도 결정한다.
```

2. `app/react/dist`가 발표·데모에서 참조되는지 확인한다. 참조되지 않으면 별도 change request로 트리를 삭제한다. **이번 패치에서는 삭제하지 않는다** — 어떤 화면이 이 산출물을 쓰는지 확인되지 않았기 때문이다.

## 4. C3 — 소유자 없는 문서 (현재 진행형 위험)

### 문제

`ci.yml`의 `document-quality` job은 매 push마다 다음 문서를 검증한다.

```text
docs/markdown/01_요구사항정의서.md
docs/markdown/02_WBS.md
docs/markdown/05_화면설계서.md
docs/markdown/collaboration/Gate_실행_카드_원장.md
docs/markdown/collaboration/I0_결정_및_I1_공통_계약_원장.md
docs/markdown/collaboration/I1_평가_원장.md
```

이 중 `01_요구사항정의서.md`와 `05_화면설계서.md`는 **어느 역할의 `ALLOWED_PATHS`에도 없다.** 대조 과정에서 **`docs/Answervice_기획서.md`도 같은 상태**임을 확인했다. 이 문서는 전 역할의 기준 문서이자 원장 `## 기획서 추적성 기준`이 참조하는 대상이다.

- R1 허용: `AGENTS.md`, `compose*.yml`, `.env.example`, `.github/**`, `.githooks/**`, `tests/integration/**`, `docs/markdown/02_WBS.md`, `docs/markdown/collaboration/**`, `docs/markdown/ai_docs/5인_병렬구현_*` — **01·05·기획서 모두 미포함**
- R5 허용: `app/enterprise-react/**`, `src/report/**`, `tests/frontend/**`, `tests/report/**` — 문서 미포함
- 실제 작성자: 01 = 송민지(R5), 05 = 송민지·박준희(R5·R1 공동), 기획서 = 윤대성(R3)

검증 명령:

```text
python .github/scripts/gate_scope.py --branch junhee --base origin/dev --head HEAD --mode merge-base
# → docs/Answervice_기획서.md 는 R1-W1 ALLOWED_PATHS 밖으로 판정됨
```

### 영향

**검증은 하는데 아무도 고칠 수 없다.** `document-quality`가 01·05에서 실패하면 담당자가 수정하는 순간 `role-scope`가 허용 경로 침범으로 FAIL한다. 어느 쪽으로도 CI를 통과시킬 수 없는 교착 상태다. 현재는 두 문서가 검증을 통과하고 있어 드러나지 않았을 뿐이다.

기획서는 더 직접적이다. **기획 검토 결과를 반영하려면 반드시 이 파일을 고쳐야 하는데, 고칠 수 있는 역할이 없다.** 실제로 이번 검토의 기획서 수정분(§1.1·§16.1·§18.1·§20·§20.1·§20.4·§20.5·§21)은 어느 branch에서 push해도 `role-scope`가 FAIL한다.

### 제안

기본 경로표에 다음을 추가한다.

```text
| R1 | ... , `docs/Answervice_기획서.md`, `docs/markdown/05_화면설계서.md`(R5와 공동) | ... |
| R5 | ... , `docs/markdown/01_요구사항정의서.md`, `docs/markdown/05_화면설계서.md` | ... |
```

기획서를 R1 단독 소유로 두는 이유는 원장·WBS·매뉴얼과의 정합성 판정이 R1의 승인 책임이기 때문이다. R3(현 작성자)을 포함한 다른 역할은 change request로 개정안을 제출한다. 공동 소유가 부담스러우면 05를 R5 단독으로 두고 R1은 change request로 반영하는 대안도 가능하다.

어느 쪽이든 **세 문서를 검증 목록이나 추적성 기준에 유지하려면 소유자가 반드시 지정돼야 한다.** 소유자를 지정하지 않기로 결정한다면 `document-quality`의 검증 목록에서 01·05를 제거하고, 기획서는 저장소 밖에서 관리해야 한다.

## 5. 승인 요청 항목

| # | 요청 | 게이트 동작 변화 | 미승인 시 결과 |
|---|---|---|---|
| 1 | R4 기본 경로를 `app/backend/**`로 교정 | Wave 2 발행 시점부터 | R4가 Wave 2에서 자기 코드 수정 불가 |
| 2 | R5 기본 경로에서 죽은 경로 제거 | Wave 2 발행 시점부터 | 존재하지 않는 경로 허용 유지 |
| 3 | R4-W1 `TEST_COMMANDS`의 compile 대상 교정 | 없음(CI는 이미 `app/backend` 사용) | 문서와 CI 불일치 유지 |
| 4 | 활성 frontend를 `app/enterprise-react` 단일로 본문 확정 | 없음(R5-W1-F1에서 이미 적용) | 원장 본문·카드 모순 유지 |
| 5 | `app/react` 트리 삭제 여부 결정 | 없음 | 폐기 트리 잔존 |
| 6 | `01_요구사항정의서.md`·`05_화면설계서.md` 소유자 지정 | **즉시** | 두 문서 수정 시 CI 교착 |
| 7 | `docs/Answervice_기획서.md`를 R1 소유로 지정 | **즉시** | **기획 검토 반영분을 어느 branch에서도 push할 수 없음** |

6·7번은 Wave 2를 기다릴 필요 없이 지금 결정해야 한다. 특히 7번은 이번 기획 검토의 기획서 수정분이 이미 작업 트리에 있으므로 **선행 조건**이다.

### 이번 수정분의 반영 경로

기획 검토로 이미 수정한 파일과 그 소유 역할은 다음과 같다. `.github/**`·`tests/integration/**`·`docs/markdown/ai_docs/5인_병렬구현_*`·`docs/markdown/collaboration/**`는 모두 R1-W1 허용 경로 안이므로 **`junhee` branch에서 커밋하면 `role-scope`를 통과한다.** 기획서 1건만 7번 승인이 선행돼야 한다.

| 파일 | 소유 | push 가능 branch |
|---|---|---|
| `.github/workflows/ci.yml`, `.github/scripts/gate_scope.py` | R1 | `junhee` |
| `tests/integration/test_gate_scope.py` | R1 | `junhee` |
| `5인_병렬구현_01~05_매뉴얼_최종안.md`, `5인_병렬구현_통합일정_*.md` | R1 | `junhee` |
| 이 제안서(`docs/markdown/collaboration/**`) | R1 | `junhee` |
| `docs/Answervice_기획서.md` | **미지정** | **없음 — 7번 승인 필요** |

## 6. 이 패치에 포함하지 않은 것

다음은 별도 승인 대상으로 남긴다.

- 역할별 test 경로 분기 (`python-contracts`·`document-quality`의 교차 역할 차단)
- `dev` 병합 경로의 `pull_request` 트리거와 branch protection 명문화
- `bundles()` 파싱의 명시 키 기반 전환과 파싱 실패 시 fail-closed
- `next_gate_lines()`의 `Latest dev SHA` 라벨 교정(현재 push된 개인 branch HEAD를 출력)
- `concurrency` 그룹 설정, `--next-gate` 하드코딩 해소

## 7. 이미 해소된 항목

- **manifest `RESULT_SHA` 닭-달걀**: 원장 v2.12(`359ce6c`)에서 R1이 `result_sha_matches_checked_head()`를 도입해 해소했다. `RESULT_SHA`가 검사 head의 조상이면서 둘 사이 diff가 자기 handoff manifest 하나뿐인 경우를 통과시킨다. 검증 강도를 낮추지 않고 절차만 가능하게 만든 해법이므로 그대로 유지한다.
- **`NOT_RUN` 상시 차단**: v2.13에서 handoff 차단 대상을 `FAIL`로 한정해 해소했다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.0 | 2026-07-31 | 실제 소스 트리 대조 결과를 근거로 원장 경로 정합성 3건 패치 제안 |
