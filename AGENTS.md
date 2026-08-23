# Answervice 프로젝트 규칙

Answervice는 자연어 질문을 승인된 업무 정의와 데이터 자산에 연결하고, 읽기 전용 SQL로 분석해 결과와 근거를 제공하는 서비스다.

- 현재 제품 범위는 `docs/README.md`에서 확인하고, 구현 여부는 현재 코드·설정·migration·runtime 증거로 판단한다.
- production 경로에 목업, mock, fake, demo fixture, 고정 응답, 빈 성공값, 숨은 fallback을 두지 않는다. test double은 `tests/`에서 명시적으로 주입한다.
- 특정 질문·사용자·대상·기간·metric·테이블 조합을 위한 분기·정규식·키워드 map·정적 JSON이나 정답 SQL·Context·KPI를 만들지 않는다.
- 표현과 조건이 달라진 동등한 요청도 코드 변경 없이 같은 계약과 실행 경로로 처리한다.
- 제품 동작과 후보·분석 범위는 승인된 runtime metadata, 사용자 권한, 서버에서 확정한 조건으로 구성한다.
- model output은 신뢰할 수 없는 입력이며 권한·정책·실행·최종 상태는 서버가 결정한다.
- SQL은 승인된 자산만 사용하는 매개변수화된 단일 read-only query이며 동일한 SQLGlot AST로 검증한다.
- metadata·dependency·권한이 불완전하면 명확화를 요청하거나 실패로 종료하고, 결과를 꾸며 성공 처리하지 않는다.
- unit·mock 검증과 live 통합 검증을 구분하며, 운영 준비 완료는 동일 release의 Backend·DataHub·Trino·DB·model 연결 증거가 있을 때만 선언한다.

## Numbered Phase Gate

- Phase 전용 subset은 회귀 탐지용이며 현재 tree 전체 Gate를 대체하지 않는다.
- 각 numbered Phase 종료 전 OpenAPI, code documentation, architecture invariant, repository integrity, Python compileall, 전체 `tests`, Frontend test/build, 모든 Compose profile config와 `git diff --check`를 실행한다.
- 전체 pytest는 저장소 내부의 고유 `--basetemp`와 `-p no:cacheprovider`를 사용한다. 외부 dependency가 없어 skip된 test는 live evidence나 PASS 수에 합산하지 않는다.
- current source와 다른 image, 과거 screenshot·receipt, mock/test-double 결과를 현재 release evidence로 승계하지 않는다.
- Gate 문서는 위 검증과 같은 source receipt에서 생성하며 실패가 하나라도 있으면 `PASS` 또는 `VERIFIED`를 기록하지 않는다.
- migration은 격리 DB에서 upgrade→downgrade→replay를 검증하고, code rollback과 DB rollback을 같은 의미로 표현하지 않는다.
