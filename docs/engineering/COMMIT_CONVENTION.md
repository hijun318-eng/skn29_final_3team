# Git Commit Message Convention

## 1. 목적

사람과 AI가 짧은 Git history만 읽어도 변경 의도, 영향 영역, 검증 여부를 복원할 수 있게 한다. 형식은 Conventional Commits를 바탕으로 하되 `data`, `eval` type을 프로젝트에 추가한다.

## 2. 기본 형식

```text
<type>(<scope>): <summary>

[optional body]

[optional trailers]
```

규칙:

- `type`과 `scope`는 영문 소문자를 사용한다.
- `summary`는 기본적으로 한국어로 쓰고 코드 식별자는 원문을 유지한다.
- subject 전체는 72자 이하, 마침표 없이 한 의도만 표현한다.
- body는 subject만으로 이유·위험·검증을 알기 어려울 때만 쓴다.
- 실제 diff와 실행 증거에 없는 내용을 쓰지 않는다.

## 3. Type

| type | 사용 시점 |
|---|---|
| `feat` | 사용자에게 보이는 기능 추가 |
| `fix` | 결함 수정 |
| `data` | schema, generator, 전처리, 품질 규칙 변경 |
| `eval` | 평가셋, 지표, grader, threshold 변경 |
| `docs` | 문서만 변경 |
| `refactor` | 동작 변경 없는 구조 개선 |
| `test` | 테스트 추가·수정 |
| `perf` | 성능 개선 |
| `build` | 의존성·빌드 시스템 변경 |
| `ci` | CI workflow 변경 |
| `style` | 동작 없는 formatting 변경 |
| `chore` | 위 항목에 속하지 않는 유지보수 |

## 4. 권장 Scope

`repo`, `docs`, `voc`, `data`, `etl`, `analytics`, `agent`, `prompt`, `api`, `ui`, `report`, `infra`, `test`

새 scope는 코드·문서의 실제 경계가 생겼을 때만 추가한다. 여러 scope가 필요하면 변경이 한 commit인지 먼저 재검토한다.

## 5. 선택 body

```text
data(generator): 조식 혼잡 시나리오를 추가

Why:
- 정상 변동과 인력 부족 후보를 함께 평가하기 위해 필요

Changes:
- S-01 강도와 기간 parameter 추가
- scenario truth를 분석 입력에서 분리

Validation:
- `python -m pytest tests/data`

Data-Version: synthetic-0.2.0
```

비어 있는 섹션은 쓰지 않는다. 실행하지 않은 테스트는 `Validation`에 적지 않는다.

## 6. 예시

```text
docs(repo): Codex 작업 지침과 평가 기준을 통합
data(etl): VOC 시간대 정규화 규칙을 추가
eval(voc): 부정 감성 gold set의 모호 사례를 보강
feat(report): 주간 CX 리포트에 데이터 기준일을 표시
fix(analytics): 빈 비교 기간의 증감률 계산을 차단
```

Breaking change:

```text
data(schema)!: facility_operations 키 구조를 변경
```

## 7. AI 작성 절차

1. 사용자가 의도한 경로만 stage한다.
2. `git diff --cached --name-status`와 `git diff --cached`를 검토한다.
3. `$draft-commit-message`를 호출한다.
4. 메시지가 staged diff만 설명하는지 사람이 확인한다.
5. 사용자가 명시적으로 요청한 경우에만 commit한다.

staged diff가 없으면 메시지를 추측하지 않는다. unrelated 변경이 섞였으면 먼저 commit 분할을 제안한다.

## 8. 로컬 검증 설치

저장소 최초 1회:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-repo.ps1
```

이 명령은 local Git config의 `core.hooksPath`를 `.githooks`로 설정한다. 공유 파일만 확인하고 Git config를 바꾸지 않으려면:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-repo.ps1 -CheckOnly
```

Merge, Revert, `fixup!`, `squash!` subject는 도구가 생성하는 형식을 허용한다.
