# Hotel Signal AI 개발 저장소 구조 감사

## 1. 조사 기준

| 항목 | 값 |
|---|---|
| 조사일 | 2026-07-20 |
| 작업 브랜치 | `jaehong` |
| 기준 커밋 | `e90f5bee4e70922d86f587803e2ec5d8ebadf6f6` |
| 원격 비교 | `origin/dev` = `origin/jaehong` = 기준 커밋 |
| 저장소 | `https://github.com/hijun318-eng/skn29_final_3team.git` |
| 조사 범위 | 폴더, 실행 코드, 설정, 의존성, 문서, 테스트·평가 경계 |

이 문서는 동기화 직후의 저장소를 기준으로 한 구조 감사 결과다. Git 동기화 이력 자체는 제품 성과로 보지 않는다.

## 2. 현재 최상위 구조

```text
repository/
├─ .agents/
├─ .githooks/
├─ app/
├─ data/
├─ docs/
├─ evals/
├─ notebooks/
├─ src/
├─ submission/
├─ tests/
├─ AGENTS.md
├─ README.md
└─ .gitignore
```

`app/`, `src/`, `tests/`, `evals/`, `notebooks/`, `submission/`은 현재 `.gitkeep`만 포함한다. `data/`에는 `raw/`, `processed/`, `samples/`와 각 `.gitkeep`이 있다.

## 3. 현재 서비스 구현 상태

| 점검 항목 | 확인 결과 | 판정 |
|---|---|---|
| React | 프로젝트·`package.json`·build 설정 없음 | 미구현 |
| Django | 프로젝트·`manage.py`·migration 없음 | 미구현 |
| FastAPI | 애플리케이션 진입점·dependency 없음 | 미구현 |
| Docker/Compose | 파일 없음 | 미구현 |
| Python dependency | `pyproject.toml`, `requirements*.txt`, lock file 없음 | 미정 |
| Node dependency | `package.json`, lock file 없음 | 미정 |
| CI | `.github/workflows/` 없음 | 미구현 |
| Git hook | secret·데이터·크기 검사와 commit message 검사 존재 | 유지 |
| 테스트·평가 | 경계 폴더만 존재 | 미구현 |
| 합성 데이터 | 버전별 파일 없음, `data/samples/` 경계만 존재 | 준비 필요 |

확인된 코드는 없으므로 React·Django·FastAPI 기능이 동작한다고 표현하지 않는다. 현재 단계의 산출물은 구현 기준과 계약이다.

## 4. 이미 존재하는 폴더

- 실행 경계: `app/`, `src/`
- 데이터 경계: `data/raw/`, `data/processed/`, `data/samples/`
- 품질 경계: `tests/`, `evals/`, `notebooks/`
- 문서 경계: `docs/markdown/`, `docs/deliverables/`, `docs/templates/`
- 협업 경계: `.agents/`, `.githooks/`

따라서 같은 목적의 최상위 폴더를 추가하지 않는다.

## 5. 비어 있는 폴더

다음 폴더는 Git 추적 경계를 나타낼 뿐 구현을 포함하지 않는다.

```text
app/
src/
tests/
evals/
notebooks/
submission/
```

`data/raw/`와 `data/processed/`도 생성 데이터가 아니라 `.gitkeep`만 추적한다. 실제 원본·처리 데이터는 `.gitignore` 정책상 commit하지 않는다.

## 6. 유지할 구조

- `app`: 사용자에게 노출되는 실행 진입점
- `src`: 프레임워크에 독립적인 분석·공통 계약 로직
- `data`: 합성 입력과 처리 결과의 로컬 경계
- `tests`: 결정론적 로직과 API 계약 검증
- `evals`: 분류·설명·보고 품질 평가 자산
- `docs/markdown`: 사람이 읽는 명세와 작업 문서

`submission/`은 기존 경계이므로 삭제하지 않지만, 공식 산출물은 문서 관리 규칙에 따라 `docs/deliverables/`를 사용한다.

## 7. 생성할 최소 구조

실제 구현을 시작할 때만 다음 하위 경계를 순서대로 만든다.

```text
app/react/
app/django/
app/fastapi/
src/analysis/
src/common/
```

공용 작업 경계를 명확히 하라는 후속 결정에 따라 위 5개 폴더를 생성하고 `.gitkeep`만 추적한다. framework 초기화와 실제 기능 구현은 별도 작업이며, 이 폴더 존재를 구현 완료로 해석하지 않는다.

## 8. 생성하지 않을 구조

명시적 승인과 실제 코드가 생기기 전에는 다음을 만들지 않는다.

```text
docs/specs/
docs/wireframes/
docs/architecture/
docs/audit/
app/fastapi/agents/
app/fastapi/mcp/
src/retrieval/
src/embeddings/
src/graph/
data/vectorstore/
infra/kafka/
infra/redis/
infra/neo4j/
tests/e2e/
```

## 9. 기존 문서와의 중복 가능성

| 기존 문서 | 중복 위험 | 결정 |
|---|---|---|
| `05_화면설계서_초안.md` | 와이어프레임 가이드와 목적 중복 | 별도 문서 없이 기존 문서에 P0 우선 규칙 추가 |
| `01_요구사항정의서.md` | 일부 데이터·API·화면 계약 존재 | 원 요구사항은 보존하고 P0 실행 계약만 공통 명세에서 좁혀 정의 |
| `03_프로젝트기획서.md` | 서비스 범위·기술 방향 존재 | 기획 배경은 보존하고 구현 SSOT 역할은 부여하지 않음 |
| `voc/HOTEL_VOC_AI_AGENT.md` | 서비스 개념·데이터 예시 존재 | 도메인 참고자료로 유지 |
| `final_project/최종_프로젝트_*` | 일정·교육 산출물 안내 | 일정 근거로만 유지 |

기존 문서와 공통 명세가 충돌하면 `AGENTS.md` 다음으로 `common_project_specification.md`의 P0 계약을 적용하고, 요구사항 원문 변경은 별도 합의로 처리한다.

## 10. 경로 변경 위험

- 기존 화면설계서가 많은 화면과 확장 기능을 포함하므로 P0 표시가 없으면 구현 범위가 다시 커질 수 있다.
- `docs/markdown/` 밖에 Markdown을 만들면 문서 관리 규칙과 충돌한다.
- Django와 FastAPI가 각각 migration을 가지면 데이터 소유권이 분산된다.
- `app`과 `src`에 같은 분석 로직을 복제하면 API 간 결과가 달라질 수 있다.
- 이 로컬 클론의 `remote.origin.fetch`는 `dev`만 자동 추적하므로 다른 원격 브랜치 검증 시 명시적 refspec 확인이 필요하다.
- 빈 프레임워크 폴더를 먼저 대량 생성하면 실제 기술 결정 전 구조가 사실상 고정될 수 있다.

## 11. 검증 명령

```powershell
git branch --show-current
git rev-parse HEAD
git rev-list --left-right --count origin/jaehong...origin/dev
rg --files
Get-ChildItem app,src,data,tests,evals,notebooks -Recurse -Force
Get-ChildItem -Recurse -File -Include Dockerfile,package.json,pyproject.toml,requirements*.txt,manage.py
```

## 12. 미확인 사항

- React·Django·FastAPI의 구체 버전과 dependency 관리 방식
- 운영 DBMS와 Django app 경계
- 합성 V1·V2 스키마·seed·생성 책임자
- 분류 모델 종류와 모델 서빙 방식
- 데모 인증을 세션 기반으로 구현할지 역할 선택 mock으로 제한할지 여부
- 최종 배포 환경, 도메인, 네트워크·secret 관리 방식
- 실제 호텔 데이터 또는 기존 WISE·PMS·POS·CRM 접근 가능성

이 항목은 구현 착수 전에 결정하되, 미확인 상태를 이유로 P0 계약 밖 인프라를 선제 도입하지 않는다.
