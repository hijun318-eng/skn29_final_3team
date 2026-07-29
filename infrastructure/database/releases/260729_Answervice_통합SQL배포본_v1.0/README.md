# Answervice 통합 SQL 배포본 v1.0

## 사용 목적

팀 공유 시 이 ZIP 하나만 전달한다. 내부 SQL은 PostgreSQL, MySQL, SQL Server, ClickHouse, Trino 엔진별로 분리되어 있으므로 하나의 SQL 파일처럼 통째로 실행하지 않는다.

## 구성

- `01_SQL_결과물/`: 역할별 SQL 원본 21개, 역할별 ZIP 5개, manifest, 정적 검증보고서
- `02_적용_작업지시문/`: 저장소에 SQL을 안전하게 매핑하기 위한 작업지시문
- `checksum_manifest.sha256`: 배포본 파일 무결성 확인용

## SQL 개수

- R2 정승: 12개
- R4 김재홍: 3개
- R5 송민지: 1개
- R1 박준희: 2개
- ML 작업카드: 3개
- 합계: 21개

## 실행 상태

- 파일 생성 및 정적 검증: 완료
- 실제 DB 실행: NOT_RUN
- Trino Query: NOT_RUN
- Alembic migration: NOT_RUN
- 모델 학습: NOT_RUN

## 주의

접속정보가 있어도 실행 승인으로 간주하지 않는다. Source DB·Trino 적용은 R2, Application DB·Alembic 적용은 R4, 공유 환경 적용은 R1의 명시적 승인이 필요하다.
