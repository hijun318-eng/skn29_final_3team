# 팀 협업 규칙

사람이 확인할 협업 규칙은 이 파일 하나에서 관리한다.

## Branch와 PR

- 개인 branch는 `junhee`, `minji`, `seung`, `daesung`, `jaehong`만 사용한다.
- 개인 branch의 작업은 `dev`로 PR을 연다.
- 배포 가능한 통합본만 `dev -> main` PR로 반영한다.
- 개인 branch에서 `main`으로 직접 PR을 열거나 force push하지 않는다.

## Commit과 PR title

- 형식: `<type>(<scope>): <summary>`
- 허용 type: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`, `perf`, `style`, `data`, `eval`
- subject는 72자 이하로 작성하고 마침표로 끝내지 않는다.
- 하나의 commit과 PR은 하나의 주된 의도만 담는다.
- 실행하지 않은 검증 결과를 commit이나 PR에 적지 않는다.

PR을 만들 때 target branch를 사람이 확인한다. 팀원 PC에는 별도 hook이나 setup script를 설치하지 않는다.

## 데이터와 평가

- `.env`, API key, 고객 원문과 개인정보를 commit하지 않는다.
- `data/raw`, `data/processed`의 생성 파일은 commit하지 않는다.
- 합성 데이터는 `synthetic`, seed, schema version을 기록한다.
- 평가 자료는 실제 평가 workflow와 test set이 생긴 뒤 필요한 구조를 추가한다.

root `AGENTS.md`만 Codex 자동 인식을 위해 repository root에 두며, 별도 도구별 협업 폴더는 사용하지 않는다.
