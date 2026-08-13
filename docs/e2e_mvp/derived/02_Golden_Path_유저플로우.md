# Golden Path 유저플로우

## 시작 조건

- 사용자는 인증된 `hotel_analyst` 권한을 가진다.
- Backend, App PostgreSQL, DataHub Core, Trino와 모델 endpoint가 준비되어 있다.
- 질문에는 분석 대상과 기간이 포함되거나 화면에서 기간을 지정한다.

## 정상 흐름

1. 사용자가 Agent 화면에서 질문과 시작일·종료일을 제출한다.
2. Frontend가 인증 정보와 함께 분석 API를 호출한다.
3. Backend가 Node 1 결과와 DataHub Core Context를 결합한다.
4. Node 2가 승인된 Context만 사용해 한 개의 read-only Trino SQL을 반환한다.
5. Backend가 SQL을 검증하고 기간·필터 파라미터를 봉인한다.
6. Trino가 실제 데이터를 조회한다.
7. Node 3가 조회 결과와 제한 사항을 설명한다.
8. Backend가 Analysis Artifact를 저장하고 표·차트 데이터를 반환한다.
9. 사용자가 선택하면 해당 Artifact를 참조하는 Report 초안을 저장한다.

## 실패 흐름

- 인증 실패, Context 부족, 모델 계약 위반, SQL 정책 위반, Trino 오류는 각각 명시적인 실패로 반환한다.
- 실패 시 템플릿 결과, fixture 값, 이전 성공 결과로 대체하지 않는다.
- 모델 출력은 실행 결과가 아니며 Trino 실행이 끝나기 전에는 분석 성공으로 표시하지 않는다.

## E2E 증거

- HTTP 상태와 응답 본문
- 모델 node별 trace와 사용 모델
- G1·G2·G3 통과 여부
- Trino query ID와 Result row
- 저장된 Artifact와 화면 표·차트의 일치
