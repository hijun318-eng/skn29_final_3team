# SensePlace API·AI 연동 원칙 요약

> 2026-07-24 압축본. 과거 endpoint·schema 초안은 `legacy/03_api_ai_integration_contract_원본_20260724_1138.md`에 보관한다.

## 경계

- 사용자 요청은 인증·권한 검사를 통과한 단일 외부 경계를 거친다.
- 내부 분석은 검증된 사용자·시설·기간·지표 범위만 사용한다.
- 장시간 작업은 상태와 오류를 조회할 수 있어야 한다.
- 데이터 조회는 허용된 view·metric·dimension으로 제한한다.

## 응답 최소 항목

- 요청·작업 식별자와 상태
- 결과 데이터와 표시 단위
- 기간·표본·합성 여부와 version
- 근거 식별자와 제한 사항
- 안정적인 오류 코드

## 신뢰성

timeout, retry, idempotency, 권한 실패와 부분 실패를 구분한다. LLM 실패 시 계산 결과와 근거를 보존하고 설명 생성만 제한한다. 실제 endpoint와 payload는 구현 코드와 API 명세에서 확정한다.
