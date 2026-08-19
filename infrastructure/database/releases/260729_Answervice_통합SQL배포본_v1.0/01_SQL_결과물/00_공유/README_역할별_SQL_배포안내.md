# Answervice 팀공유 SQL 결과물 v1.0

기준 문서: 역할소유권 인덱스 v2.1, 00R v2.1, 00A·00B·00C·00D, 01~05 v2.3, 06 v1.4

## 역할별 전달

| 담당 | 전달 폴더 | 실행 가능한 변경 SQL | 읽기 전용 검증 SQL |
|---|---|---:|---:|
| 데이터(정승) | `R2_정승_Source_Seed_Trino/` | Source DDL 5, seed 5, Trino View 1 | 1 |
| 백엔드(김재홍) | `R4_김재홍_ApplicationDB/` | Application P0/P1 DDL 1 | preflight 1, postflight 1 |
| 프론트엔드(송민지) | `R5_송민지_Report_Migration_초안/` | 0 | Report 계약 검토 1 |
| PM/검증(박준희) | `R1_박준희_통합검증/` | 0 | Application Gate 1, Trino Gate 1 |
| ML 작업카드 담당자 | `ML_작업카드_객실수요예측/` | 0 | Feature Query 2, preflight 1 |

## 실행 순서

1. 백엔드 Application preflight
2. 백엔드 Application P0/P1 DDL, 백엔드 승인 필요
3. 데이터 Source DDL 5개, 각 엔진별 데이터 담당 승인 필요
4. 데이터 seed 01~05, `ALLOW_SYNTHETIC_RESEED=true` 별도 승인 필요
5. 데이터 Trino catalog 연결 후 analytics View SQL
6. 프론트엔드 Report read-only 검토 결과를 백엔드에 인계
7. ML Feature Query는 read-only Trino 계정으로만 실행
8. PM/검증 Gate 검증 후 공유 환경 적용 승인

`INCLUDE_P2=false`이므로 P2 SQL은 이 패키지에 포함하지 않았다.
실제 DB·Trino 실행은 수행하지 않았다.
