# 최소 프로젝트 폴더 구조

## 1. 최종 구조

기술 스택을 결정하기 전에 빈 구조를 과도하게 만들지 않는다. 현재 필요한 영역만 다음과 같이 유지한다.

```text
project-root/
├─ data/
│  ├─ raw/              원본·합성 Raw data, Git ignore
│  ├─ processed/        전처리 결과, Git ignore
│  └─ samples/          작고 비식별화된 공유 sample
├─ docs/                기획·개발·협업 문서
├─ notebooks/           EDA·실험 notebook
├─ src/                 데이터 처리·분석·Agent·API code
├─ app/                 demo·service entrypoint
├─ tests/               code test
├─ evals/               기능별 test set과 품질 baseline
├─ submission/          최종 제출 산출물
├─ scripts/             설치·검증·반복 작업 자동화
├─ .env.example         공유 가능한 환경변수 예시
├─ .gitignore
├─ requirements.txt     검증된 Python dependency
├─ AGENTS.md
├─ CONTRIBUTING.md
└─ README.md
```

`.agents/`, `.claude/`, `.github/`, `.githooks/`는 사용자 기능 폴더가 아니라 팀 협업과 자동 검증을 위한 숨김 설정이므로 함께 버전 관리한다.

## 2. 디렉터리 규칙

| 경로 | 규칙 |
|---|---|
| `data/raw/` | 실제·합성 원본 파일은 commit하지 않고 `.gitkeep`만 유지한다. |
| `data/processed/` | 재생성 가능한 전처리 결과는 commit하지 않고 `.gitkeep`만 유지한다. |
| `data/samples/` | 비식별화된 작은 sample만 review 후 commit한다. |
| `docs/` | 문서 원본을 두며 같은 규칙을 여러 파일에 복제하지 않는다. |
| `notebooks/` | 재현 가능한 EDA·실험 notebook만 두며 commit 전 불필요한 output과 secret을 제거한다. |
| `src/` | 실제 module이 생길 때만 하위 directory를 추가한다. |
| `app/` | Streamlit, FastAPI 등 실행 framework가 확정되기 전에는 `.gitkeep`만 둔다. 별도 `frontend/`와 `backend/`는 필요가 확인된 뒤 추가한다. |
| `tests/` | test 종류가 실제로 늘어날 때만 unit/integration 하위 구조를 만든다. |
| `evals/` | AI·분석 기능의 version별 test set, baseline, 비교 report를 관리한다. |
| `submission/` | 최종 PPT, PDF, 설명서 등 제출 확정본을 둔다. 임시 export는 넣지 않는다. |
| `scripts/` | 팀원이 같은 명령으로 반복해야 하는 설치·검증 작업만 둔다. |

## 3. 환경 파일

- `.env`: 개인 PC 전용이며 Git에 올리지 않는다.
- `.env.example`: 변수명과 secret이 아닌 안전한 예시만 공유한다.
- `requirements.txt`: 확정·검증된 runtime dependency만 추가한다. 기술 스택이 미정인 현재는 package를 임의로 넣지 않는다.
- app dependency와 실행 설정은 framework 선택 후 추가한다.

## 4. `src/` 확장 기준

다음 이름은 후보일 뿐 지금 빈 directory로 만들지 않는다.

| 후보 | 추가 조건 |
|---|---|
| `src/config/` | 여러 module이 공유하는 설정 code가 생겼을 때 |
| `src/data/` | 수집·합성·정제 pipeline code가 생겼을 때 |
| `src/llm/` | LLM provider 호출과 prompt 관리가 분리될 때 |
| `src/agent/` | Agent workflow code가 생겼을 때 |
| `src/embeddings/`, `src/retrieval/` | RAG와 vector 검색을 실제 architecture로 채택했을 때 |
| `src/utils/` | 둘 이상의 module이 공유하는 함수가 생겼을 때 |

## 5. top-level 확장 기준

새 top-level directory는 기존 위치로 표현할 수 없고 반복 사용될 것이 확인된 경우에만 Decision Record와 함께 추가한다. 실제 파일이 생기면 해당 directory의 불필요한 `.gitkeep`은 제거한다.
