# Answervice MVP PRD

## 목표

사용자의 자연어 질문을 실제 서비스 데이터로 분석하고, 검증된 결과를 표·차트·보고서 초안으로 이어 주는 하나의 Golden Path를 제공한다.

## MVP 범위

- React 분석 화면에서 질문과 분석 기간을 입력한다.
- Backend가 인증과 권한을 확인한다.
- DataHub Core가 허용된 dataset, metric, column, filter를 Context로 확정한다.
- Node 1은 질문을 구조화하고, Node 2는 승인된 Context 안에서 Trino SQL을 생성한다.
- G2가 read-only, asset, metric, 기간, LIMIT 정책을 검사한 뒤 Trino가 실제 SQL을 실행한다.
- Node 3가 실제 Result를 설명하고 Backend가 Artifact를 저장한다.
- Frontend가 서버가 반환한 표·차트를 표시하고 Report 초안을 저장한다.

## 제외 범위

- 새로운 합성 데이터 생성 SQL 작성
- 운영 배포, 자동 스케일링, 비용 최적화
- 모델 재학습과 weight·adapter의 Git 저장
- fixture·mock·하드코딩 KPI를 제품 성공 근거로 사용하는 방식

## 완료 조건

- 실제 Docker 서비스와 HTTP 요청으로 Golden Path가 성공한다.
- 모델이 생성한 SQL이 정책 검사를 통과한 경우에만 Trino에서 실행된다.
- 화면 값이 저장된 Analysis Artifact와 일치한다.
- 실패 시 성공처럼 보이는 가짜 결과 대신 명시적인 오류가 반환된다.
