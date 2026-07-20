# SKN29 Final 3Team

Hotel Signal AI는 그랜드 워커힐 서울을 모델링한 합성 운영 데이터와 합성 VOC를 이용해 권한 기반 대화형 분석과 이상 감지·근거 조사·주간 보고를 검증하는 내부 의사결정 지원 플랫폼이다. 결과는 실제 호텔의 현황·문제·성과를 의미하지 않는다.

2026-08-06 중간발표는 두 핵심 경로를 backend·DB·LLM과 연결하지 않은 6화면 frontend fixture로 시연한다. 기능 Baseline은 중간발표 이후 Django 인증·job 계층, FastAPI 분석 계층, PostgreSQL, LLM을 실제 연결해 `대화형 분석`과 `이상 감지→보고서→관리자 결정`을 각각 end-to-end로 완성한다.

VectorDB·sLLM·ML/DL·멀티 에이전트 비교는 Baseline 런타임과 분리된 실험 트랙으로 관리하며, 승인 전 실행 경로의 필수 dependency로 추가하지 않는다.

## MVP 공통 문서

다른 Codex 세션은 먼저 [Codex 공용 작업 가이드](./docs/markdown/final_project/codex_공용작업_가이드.md)에서 작업별 필수 문서와 Baseline 범위를 확인한다. 기존 공통 명세가 `01_common_development_specification.md` 역할을 하므로 같은 목적의 파일을 추가로 만들지 않는다.

1. [Codex 공용 작업 가이드](./docs/markdown/final_project/codex_공용작업_가이드.md)
2. [프로젝트 통제 문서](./docs/markdown/final_project/00_project_control.md)
3. [Hotel Signal AI 공통 개발 명세](./docs/markdown/final_project/common_project_specification.md)
4. 담당별 공용 문서

구조·화면 지원 문서:

- [최신 저장소 구조 감사](./docs/markdown/final_project/dev_repository_structure_audit.md)
- [프로젝트 디렉터리 구조](./docs/markdown/final_project/project_directory_structure.md)
- [화면설계서 초안](./docs/markdown/05_화면설계서_초안.md)

## 개인 branch 시작

```powershell
git clone https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team
git switch <본인 branch>
```

| 팀원 | Branch |
|---|---|
| 준희 | `junhee` |
| 민지 | `minji` |
| 승 | `seung` |
| 대성 | `daesung` |
| 재홍 | `jaehong` |

작업 시작, `dev` 반영, commit, push 방법은 [팀원 Git branch 사용 가이드](./docs/markdown/collaboration/README.md)를 확인한다.

## 문서 관리

- `docs/`에서 관리하는 Markdown 문서는 `docs/markdown/`에 저장한다.
- 제출 산출물과 제공 양식은 `docs/deliverables/`에 저장한다.
- 공식 산출물은 `두 자리 번호_문서이름_29기_3팀.확장자` 형식을 사용한다.
- 전체 번호와 저장 기준은 [문서 관리 규칙](./docs/문서관리규칙.md)을 확인한다.
