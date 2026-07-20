# SKN29 Final 3Team

Hotel Signal AI는 합성 리뷰·VOC와 합성 운영지표를 결합해 이상 신호의 근거와 현장 확인 메모가 포함된 주간 보고서 초안을 제공하고 호텔 관리자의 승인을 지원하는 내부 업무용 프로토타입이다.

P0 Golden Path는 `합성 데이터 V1·V2 → 규칙 기반 이상 감지 → VOC·운영지표 근거 → 현장 확인 메모 → 주간 보고서 → 승인·보류·반려` 하나로 제한한다. 확장 기능은 공통 명세의 승인 절차를 거치기 전 구현하지 않는다.

첫 Baseline은 조식 대기 시나리오 1개, `RULE-001`, 통합 API 5개, 4개 화면만 구현한다. 독립 FastAPI와 운영 수준 인증·감사·세분 데이터 저장은 Baseline E2E 통과 후 P0 강화로 검토한다.

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
