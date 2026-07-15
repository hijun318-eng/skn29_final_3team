# Git 협업 규칙

## Branch와 PR

- 고정 branch는 `main`, `dev`, `junhee`, `minji`, `seung`, `daesung`, `jaehong`이다.
- 코드와 문서 변경은 담당 개인 branch에서 수행한다.
- 개인 branch의 작업은 `dev`로 PR을 연다.
- 최종 반영은 `dev -> main` PR로 진행한다.
- 개인 branch에서 `main`으로 직접 PR을 열거나 force push하지 않는다.

## Commit과 PR title

- 형식은 `<type>(<scope>): <summary>`이다.
- 허용 type은 `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`, `perf`, `style`, `data`, `eval`이다.
- type과 scope는 영문 소문자로 유지하고 summary와 필요한 body는 한국어로 작성한다.
- subject는 72자 이하로 작성하고 마침표로 끝내지 않는다.
- 하나의 commit과 PR에는 하나의 주된 의도만 담고, 실행하지 않은 검증 결과를 적지 않는다.
